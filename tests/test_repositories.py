from __future__ import annotations

import json
import unittest
import uuid

from backend.models.enums import EventStatus, ManualActionStatus, NodeStatus, TaskStatus
from backend.models.schemas import EventLog, NodeState, TOCNode, TOCVersion, Task
from backend.repositories.db import SQLiteDB
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.repositories.toc_repository import TOCRepository
from tests.helpers import cleanup_temp_root, make_temp_root


class RepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = make_temp_root("repository_test_")
        self.db = SQLiteDB(self.temp_root / "app.db")
        self.db.initialize()
        self.task_repository = TaskRepository(self.db)
        self.toc_repository = TOCRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)
        self.event_repository = EventLogRepository(self.db)

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    def test_task_repository_create_update_and_resumable_listing(self) -> None:
        task = Task(task_id="task_repo_1", title="仓库测试", status=TaskStatus.NEW)
        done_task = Task(task_id="task_repo_2", title="已完成任务", status=TaskStatus.DONE)
        self.task_repository.create(task)
        self.task_repository.create(done_task)

        self.task_repository.update_upload("task_repo_1", "input.docx", "/tmp/input.docx")
        self.task_repository.update_progress(
            "task_repo_1",
            total_nodes=4,
            completed_nodes=1,
            total_progress=0.25,
            current_stage="PARSED",
        )
        self.task_repository.touch_heartbeat("task_repo_1", stage="GENERATING", node_uid="uid_001")

        stored = self.task_repository.get("task_repo_1")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.upload_file_name, "input.docx")
        self.assertEqual(stored.total_nodes, 4)
        self.assertEqual(stored.current_stage, "GENERATING")
        self.assertEqual(stored.current_node_uid, "uid_001")

        resumable_ids = {item.task_id for item in self.task_repository.list_resumable()}
        self.assertIn("task_repo_1", resumable_ids)
        self.assertNotIn("task_repo_2", resumable_ids)

    def test_toc_repository_version_and_snapshot_round_trip(self) -> None:
        version = TOCVersion(
            toc_version_id="tocv_001",
            task_id="task_repo_1",
            version_no=1,
            file_path="/tmp/toc_v1.json",
            is_confirmed=False,
            diff_summary_json={"summary": {"add_count": 1}},
            created_by="system",
        )
        self.toc_repository.create_version(version)
        tree = [
            TOCNode(
                node_uid="uid_root_001",
                node_id="1",
                level=1,
                title="工程实施方案",
                is_generation_unit=False,
                children=[
                    TOCNode(
                        node_uid="uid_l3_001",
                        node_id="1.1.1",
                        level=3,
                        title="视频监控子系统",
                        is_generation_unit=True,
                        source_refs=["p1#L1"],
                        constraints={"min_words": 1800},
                        children=[],
                    )
                ],
            )
        ]
        snapshots = self.toc_repository.replace_snapshots("task_repo_1", 1, tree)
        generation_units = self.toc_repository.list_generation_units("task_repo_1", 1)

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(len(generation_units), 1)
        self.assertEqual(generation_units[0].node_uid, "uid_l3_001")
        self.assertEqual(generation_units[0].source_refs_json, ["p1#L1"])
        self.assertEqual(self.toc_repository.get_latest_version("task_repo_1").version_no, 1)

        self.toc_repository.mark_confirmed("task_repo_1", 1)
        confirmed = self.toc_repository.get_version("task_repo_1", 1)
        self.assertTrue(confirmed.is_confirmed)

    def test_node_state_repository_retry_and_completion_counts(self) -> None:
        pending = NodeState(
            node_state_id=f"node_{uuid.uuid4().hex[:12]}",
            task_id="task_repo_1",
            node_uid="uid_001",
            node_id="1.1.1",
            title="节点一",
            level=3,
            status=NodeStatus.PENDING,
            progress=0.0,
            current_stage=NodeStatus.PENDING.value,
        )
        done = NodeState(
            node_state_id=f"node_{uuid.uuid4().hex[:12]}",
            task_id="task_repo_1",
            node_uid="uid_002",
            node_id="1.1.2",
            title="节点二",
            level=3,
            status=NodeStatus.NODE_DONE,
            progress=1.0,
            manual_action_status=ManualActionStatus.NONE,
            current_stage=NodeStatus.NODE_DONE.value,
        )
        self.node_repository.upsert(pending)
        self.node_repository.upsert(done)
        self.node_repository.increment_retry("task_repo_1", "uid_001", "retry_fact")
        self.node_repository.update_status(
            "task_repo_1",
            "uid_001",
            status=NodeStatus.TEXT_GENERATING,
            progress=0.1,
            current_stage=NodeStatus.TEXT_GENERATING.value,
            manual_action_status=ManualActionStatus.PENDING,
            image_manual_required=True,
        )

        stored = self.node_repository.get("task_repo_1", "uid_001")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.retry_fact, 1)
        self.assertEqual(stored.manual_action_status, ManualActionStatus.PENDING)
        self.assertTrue(stored.image_manual_required)
        self.assertEqual(self.node_repository.count_total("task_repo_1"), 2)
        self.assertEqual(self.node_repository.count_completed("task_repo_1"), 1)

    def test_event_log_repository_round_trip(self) -> None:
        event = EventLog(
            event_id="evt_repo_1",
            task_id="task_repo_1",
            node_uid="uid_001",
            stage="FACT_CHECKING",
            status=EventStatus.WARNING,
            message="发现需要重试",
            retry_count=1,
            meta_json={"score": 0.64},
        )
        self.event_repository.create(event)
        recent = self.event_repository.list_recent("task_repo_1", node_uid="uid_001")

        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].status, EventStatus.WARNING)
        self.assertEqual(recent[0].meta_json, {"score": 0.64})

        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT meta_json FROM event_log WHERE event_id = ?",
                ("evt_repo_1",),
            ).fetchone()
        self.assertEqual(json.loads(row["meta_json"]), {"score": 0.64})


if __name__ == "__main__":
    unittest.main()
