from __future__ import annotations

import unittest

from docx import Document

from backend.app_service.task_service import TaskService
from backend.models.enums import NodeStatus, TaskStatus
from backend.worker.worker_process import WorkerProcess
from tests.helpers import build_settings, cleanup_temp_root, create_sample_docx, make_temp_root


class EndToEndSmokeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = make_temp_root("e2e_smoke_test_")
        self.settings = build_settings(self.temp_root)
        self.service = TaskService(settings=self.settings)
        self.worker = WorkerProcess(self.settings)

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
        v1 = self.service.generate_toc(task.task_id)
        v2 = self.service.review_toc(task.task_id, "请修订第一章节标题")
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


if __name__ == "__main__":
    unittest.main()
