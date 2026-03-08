from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from backend.models.enums import NodeStatus, TaskStatus
from backend.models.schemas import NodeState, Task
from backend.orchestrator.orchestrator import Orchestrator
from backend.repositories.chat_message_repository import ChatMessageRepository
from backend.repositories.db import SQLiteDB
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.repositories.toc_repository import TOCRepository
from backend.worker.node_runner import NodeRunner
from tests.helpers import cleanup_temp_root, make_temp_root


class StateMachineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = make_temp_root("state_machine_test_")
        self.db = SQLiteDB(self.temp_root / "app.db")
        self.db.initialize()
        self.task_repository = TaskRepository(self.db)
        self.toc_repository = TOCRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)
        self.event_repository = EventLogRepository(self.db)
        self.chat_repository = ChatMessageRepository(self.db)
        self.runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=self.temp_root / "artifacts",
            template_path=Path("templates/standard_template.docx"),
        )
        self.orchestrator = Orchestrator(
            task_repository=self.task_repository,
            toc_repository=self.toc_repository,
            node_repository=self.node_repository,
            event_repository=self.event_repository,
            chat_repository=self.chat_repository,
            node_runner=self.runner,
            artifacts_root=self.temp_root / "artifacts",
        )

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    def test_task_transition_blocks_illegal_jump(self) -> None:
        task = Task(task_id="task_sm_1", title="状态机任务", status=TaskStatus.NEW)
        self.task_repository.create(task)

        with self.assertRaises(ValueError):
            self.orchestrator._transition_task(
                "task_sm_1",
                TaskStatus.DONE,
                current_stage="DONE",
            )

        self.orchestrator._transition_task(
            "task_sm_1",
            TaskStatus.PARSED,
            current_stage="PARSED",
        )
        stored = self.task_repository.get("task_sm_1")
        self.assertEqual(stored.status, TaskStatus.PARSED)

    def test_node_transition_blocks_illegal_jump(self) -> None:
        self.task_repository.create(Task(task_id="task_sm_1", title="状态机任务", status=TaskStatus.GENERATING))
        node = NodeState(
            node_state_id=f"node_{uuid.uuid4().hex[:12]}",
            task_id="task_sm_1",
            node_uid="uid_sm_001",
            node_id="1.1.1",
            title="节点状态机",
            level=3,
            status=NodeStatus.PENDING,
            progress=0.0,
            current_stage=NodeStatus.PENDING.value,
        )
        self.node_repository.upsert(node)

        with self.assertRaises(ValueError):
            self.runner._transition_node(node, NodeStatus.FACT_PASSED, 0.3)

        self.runner._transition_node(node, NodeStatus.TEXT_GENERATING, 0.08)
        stored = self.node_repository.get("task_sm_1", "uid_sm_001")
        self.assertEqual(stored.status, NodeStatus.TEXT_GENERATING)

    def test_plan_stages_for_resume_statuses(self) -> None:
        self.assertEqual(self.runner._plan_stages(NodeStatus.WAITING_MANUAL), ["manual_finalize"])
        self.assertEqual(self.runner._plan_stages(NodeStatus.NODE_DONE), [])
        self.assertEqual(self.runner._plan_stages(NodeStatus.TEXT_DONE)[0], "fact")
        self.assertEqual(self.runner._plan_stages(NodeStatus.IMAGE_DONE)[0], "length")


if __name__ == "__main__":
    unittest.main()
