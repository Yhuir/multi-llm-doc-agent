from __future__ import annotations

import unittest
from unittest.mock import patch

from docx import Document

from backend.agents.toc_generator import TOCGeneratorAgent
from backend.app_service.task_service import TaskService
from backend.models.enums import NodeStatus, TaskStatus
from backend.worker.worker_process import WorkerProcess
from tests.helpers import build_settings, cleanup_temp_root, create_sample_docx, make_temp_root


class EndToEndSmokeTestCase(unittest.TestCase):
    _MODEL_TOC = """
    {
      "root_title": "视频监控系统实施方案",
      "chapters": [
        {
          "title": "视频监控系统建设范围",
          "children": [
            {"title": "前端点位部署要求", "children": []},
            {"title": "平台接入与联调要求", "children": []}
          ]
        },
        {
          "title": "施工与验收要求",
          "children": [
            {"title": "施工组织与质量控制", "children": []},
            {"title": "验收资料与签认要求", "children": []}
          ]
        }
      ]
    }
    """

    def setUp(self) -> None:
        self.temp_root = make_temp_root("e2e_smoke_test_")
        self.settings = build_settings(self.temp_root)
        self.service = TaskService(settings=self.settings)
        self.worker = WorkerProcess(self.settings)
        self.service.update_system_config(
            {
                "text_provider": "minimax",
                "text_model_name": "MiniMax-M2.5",
                "text_api_key": "fake-key",
            }
        )

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    def test_docx_to_output_smoke_flow(self) -> None:
        task = self.service.create_task("端到端烟测")
        source_docx = create_sample_docx(
            self.temp_root / "input" / "sample.docx",
            [
                "端到端烟测项目",
                "视频监控子系统需要完成前端部署、链路联调和平台接入。",
                "施工过程应符合GB50348。",
                "验收阶段应形成记录并完成签认。",
            ],
        )

        upload_path = self.service.save_upload(task.task_id, "sample.docx", source_docx.read_bytes())
        parse_payload = self.service.parse_requirement(task.task_id)
        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=self._MODEL_TOC):
            v1 = self.service.generate_toc(task.task_id)
        toc_v1 = self.service.get_toc_document(task.task_id, v1.version_no)
        first_title = toc_v1["tree"][0]["children"][0]["title"]
        self.service.update_system_config({"text_api_key": ""})
        v2 = self.service.review_toc(task.task_id, f'把“{first_title}”改成“{first_title}（修订版）”')
        confirm_payload = self.service.confirm_and_start_generation(task.task_id, v2.version_no)
        seeded_nodes = confirm_payload["seeded_nodes"]

        processed = self.worker.run_once()

        final_task = self.service.get_task(task.task_id)
        nodes = self.service.get_node_states(task.task_id)
        logs = self.service.get_event_logs(task.task_id, limit=200)
        output_path = self.service.get_output_path(task.task_id)

        self.assertTrue(upload_path.exists())
        self.assertEqual(parse_payload["task_id"], task.task_id)
        self.assertEqual(v1.version_no, 1)
        self.assertEqual(v2.version_no, 2)
        self.assertGreaterEqual(seeded_nodes, 1)
        self.assertEqual(confirm_payload["task"]["status"], TaskStatus.GENERATING.value)
        self.assertEqual(processed, 1)
        self.assertIsNotNone(final_task)
        assert final_task is not None
        self.assertEqual(final_task.status, TaskStatus.DONE)
        self.assertEqual(final_task.current_stage, "DONE")
        self.assertIsNotNone(output_path)
        assert output_path is not None
        self.assertTrue(output_path.exists())
        self.assertTrue(all(node.status == NodeStatus.NODE_DONE for node in nodes))
        self.assertTrue(any(event.stage == "DONE" for event in logs))

        exported = Document(output_path)
        self.assertGreater(len(exported.paragraphs), 0)
        self.assertGreaterEqual(len(nodes), 1)

    def test_manual_outline_to_output_smoke_flow(self) -> None:
        task = self.service.create_task("手工目录树烟测")
        source_docx = create_sample_docx(
            self.temp_root / "input" / "manual_outline.docx",
            [
                "手工目录树烟测项目",
                "售后服务需覆盖维保、巡检、培训和应急响应。",
                "实施过程应兼顾不停机生产与分阶段改造窗口。",
                "应急处置需具备远程诊断、现场联动和闭环整改能力。",
            ],
        )

        self.service.save_upload(task.task_id, "manual_outline.docx", source_docx.read_bytes())
        outline = "\n".join(
            [
                "一、售后服务总体方案",
                "1.1 售后服务目标",
                "1.1.1 保障系统安全稳定运行",
                "二、应急响应措施",
                "2.1 应急响应总体机制",
                "2.1.1 7×24小时响应机制",
            ]
        )

        imported = self.service.import_toc_outline(task.task_id, outline)
        confirm_payload = self.service.confirm_and_start_generation(task.task_id, imported.version_no)
        processed = self.worker.run_once()

        final_task = self.service.get_task(task.task_id)
        nodes = self.service.get_node_states(task.task_id)
        output_path = self.service.get_output_path(task.task_id)

        self.assertEqual(imported.version_no, 1)
        self.assertEqual(confirm_payload["task"]["status"], TaskStatus.GENERATING.value)
        self.assertEqual(processed, 1)
        self.assertIsNotNone(final_task)
        assert final_task is not None
        self.assertEqual(final_task.status, TaskStatus.DONE)
        self.assertIsNotNone(output_path)
        assert output_path is not None
        self.assertTrue(output_path.exists())
        self.assertTrue(all(node.status == NodeStatus.NODE_DONE for node in nodes))

        exported = Document(output_path)
        all_text = "\n".join(paragraph.text for paragraph in exported.paragraphs)
        self.assertIn("售后服务总体方案", all_text)
        self.assertIn("应急响应措施", all_text)


if __name__ == "__main__":
    unittest.main()
