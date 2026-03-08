from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from backend.models.enums import NodeStatus, TaskStatus
from backend.models.schemas import NodeState, Task
from backend.repositories.db import SQLiteDB
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.worker.node_runner import NodeRunner
from tests.helpers import (
    cleanup_temp_root,
    make_temp_root,
    write_requirement_artifact,
    write_style_profile_artifact,
)


class CheckpointResumeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = make_temp_root("checkpoint_resume_test_")
        self.db = SQLiteDB(self.temp_root / "app.db")
        self.db.initialize()
        self.artifacts_root = self.temp_root / "artifacts"

        self.task_repository = TaskRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)
        self.event_repository = EventLogRepository(self.db)
        self.runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=self.artifacts_root,
            template_path=Path("templates/standard_template.docx"),
        )

        self.task_id = "task_resume"
        self.node_uid = "uid_resume_001"
        self.task_repository.create(
            Task(
                task_id=self.task_id,
                title="恢复测试任务",
                status=TaskStatus.GENERATING,
                current_stage="GENERATING",
            )
        )
        self.node_repository.upsert(
            NodeState(
                node_state_id=f"node_{uuid.uuid4().hex[:12]}",
                task_id=self.task_id,
                node_uid=self.node_uid,
                node_id="1.1.1",
                title="视频监控子系统",
                level=3,
                status=NodeStatus.PENDING,
                progress=0.0,
                current_stage=NodeStatus.PENDING.value,
            )
        )
        write_requirement_artifact(self.artifacts_root, self.task_id)
        write_style_profile_artifact(self.artifacts_root, self.task_id)

        self.node_dir = self.artifacts_root / self.task_id / "nodes" / self.node_uid
        (self.node_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (self.node_dir / "snapshots").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    def test_resume_continues_from_latest_stable_stage(self) -> None:
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None

        first_stage_ok = self.runner._execute_stage(node=node, node_dir=self.node_dir, stage_key="text")
        self.assertTrue(first_stage_ok)
        self.assertTrue((self.node_dir / "checkpoints" / "text_done.json").exists())

        resumed_runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=self.artifacts_root,
            template_path=Path("templates/standard_template.docx"),
        )
        stored = self.node_repository.get(self.task_id, self.node_uid)
        self.assertEqual(stored.status, NodeStatus.TEXT_DONE)
        self.assertEqual(resumed_runner._plan_stages(stored.status)[0], "fact")

        resumed_runner._run_single_node(stored)

        finished = self.node_repository.get(self.task_id, self.node_uid)
        self.assertEqual(finished.status, NodeStatus.NODE_DONE)
        self.assertTrue((self.node_dir / "checkpoints" / "node_done.json").exists())

        logs = self.event_repository.list_recent(self.task_id, limit=200, node_uid=self.node_uid)
        text_done_logs = [item for item in logs if item.stage == NodeStatus.TEXT_DONE.value]
        resume_logs = [item for item in logs if item.stage == "NODE_RESUME"]
        self.assertEqual(len(text_done_logs), 1)
        self.assertTrue(any("TEXT_DONE" in item.message for item in resume_logs))


if __name__ == "__main__":
    unittest.main()
