from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.enums import NodeStatus, TaskStatus
from backend.models.schemas import NodeState, Task, utc_now_iso
from backend.repositories.db import SQLiteDB
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.worker.watchdog import build_api_health_url, inspect_worker_heartbeat


def _iso_offset(seconds: int) -> str:
    return (datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)).isoformat()


class WatchdogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(prefix="watchdog_test_", dir="/tmp"))
        self.db_path = self.temp_root / "app.db"
        self.db = SQLiteDB(self.db_path)
        self.db.initialize()
        self.task_repository = TaskRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root)

    def test_build_api_health_url_uses_loopback_for_wildcard_bind(self) -> None:
        self.assertEqual(build_api_health_url("0.0.0.0", 8000), "http://127.0.0.1:8000/health")

    def test_worker_heartbeat_is_healthy_when_no_runnable_task_exists(self) -> None:
        snapshot = inspect_worker_heartbeat(self.db_path, stale_after_sec=600)
        self.assertTrue(snapshot.healthy)
        self.assertEqual(snapshot.reason, "idle")

    def test_worker_heartbeat_is_healthy_for_fresh_active_node(self) -> None:
        task_id = "task_watchdog_fresh"
        node_uid = "uid_watchdog_fresh"
        self.task_repository.create(
            Task(
                task_id=task_id,
                title="fresh",
                status=TaskStatus.GENERATING,
                current_stage="GENERATING",
                current_node_uid=node_uid,
                total_nodes=1,
                completed_nodes=0,
                last_heartbeat_at=_iso_offset(-30),
            )
        )
        self.node_repository.upsert(
            NodeState(
                node_state_id=f"node_{uuid.uuid4().hex[:8]}",
                task_id=task_id,
                node_uid=node_uid,
                node_id="1.1.1",
                title="fresh node",
                level=3,
                status=NodeStatus.TEXT_GENERATING,
                progress=0.1,
                current_stage=NodeStatus.TEXT_GENERATING.value,
                last_heartbeat_at=_iso_offset(-20),
            )
        )

        snapshot = inspect_worker_heartbeat(self.db_path, stale_after_sec=600)
        self.assertTrue(snapshot.healthy)
        self.assertEqual(snapshot.reason, "active node heartbeat fresh")
        self.assertEqual(snapshot.task_id, task_id)
        self.assertEqual(snapshot.node_uid, node_uid)

    def test_worker_heartbeat_detects_stale_active_node(self) -> None:
        task_id = "task_watchdog_stale_node"
        node_uid = "uid_watchdog_stale_node"
        self.task_repository.create(
            Task(
                task_id=task_id,
                title="stale-node",
                status=TaskStatus.GENERATING,
                current_stage="GENERATING",
                current_node_uid=node_uid,
                total_nodes=1,
                completed_nodes=0,
                last_heartbeat_at=_iso_offset(-3600),
            )
        )
        self.node_repository.upsert(
            NodeState(
                node_state_id=f"node_{uuid.uuid4().hex[:8]}",
                task_id=task_id,
                node_uid=node_uid,
                node_id="1.1.1",
                title="stale node",
                level=3,
                status=NodeStatus.FACT_CHECKING,
                progress=0.24,
                current_stage=NodeStatus.FACT_CHECKING.value,
                last_heartbeat_at=_iso_offset(-3600),
            )
        )

        snapshot = inspect_worker_heartbeat(self.db_path, stale_after_sec=600)
        self.assertFalse(snapshot.healthy)
        self.assertEqual(snapshot.reason, "stale node heartbeat")
        self.assertEqual(snapshot.task_id, task_id)
        self.assertEqual(snapshot.node_uid, node_uid)

    def test_worker_heartbeat_detects_stale_layout_task(self) -> None:
        task_id = "task_watchdog_layout"
        self.task_repository.create(
            Task(
                task_id=task_id,
                title="layout",
                status=TaskStatus.LAYOUTING,
                current_stage="LAYOUTING",
                total_nodes=5,
                completed_nodes=5,
                last_heartbeat_at=_iso_offset(-4000),
                updated_at=_iso_offset(-4000),
                created_at=utc_now_iso(),
            )
        )

        snapshot = inspect_worker_heartbeat(self.db_path, stale_after_sec=600)
        self.assertFalse(snapshot.healthy)
        self.assertEqual(snapshot.reason, "stale task heartbeat")
        self.assertEqual(snapshot.task_id, task_id)


if __name__ == "__main__":
    unittest.main()
