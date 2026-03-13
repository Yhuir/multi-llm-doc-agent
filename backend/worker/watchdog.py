"""Cross-platform watchdog for API and Worker processes.

This watchdog is intended for long-running local usage. It starts the API and
Worker as child processes, monitors API health and worker heartbeats, and only
restarts a service when it is unhealthy instead of on a fixed timer.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from backend.config import AppSettings, load_settings
from backend.models.enums import NodeStatus, TaskStatus


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(heartbeat_at: str | None, *, timeout_sec: float, now: datetime | None = None) -> bool:
    parsed = _parse_iso_datetime(heartbeat_at)
    if parsed is None:
        return True
    current = now or _utc_now()
    return (current - parsed).total_seconds() > timeout_sec


def normalize_health_host(bind_host: str) -> str:
    cleaned = (bind_host or "").strip()
    if cleaned in {"", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return cleaned


def build_api_health_url(bind_host: str, port: int) -> str:
    return f"http://{normalize_health_host(bind_host)}:{port}/health"


@dataclass(frozen=True)
class WorkerHealthSnapshot:
    healthy: bool
    reason: str
    task_id: str | None = None
    node_uid: str | None = None
    stage: str | None = None
    heartbeat_at: str | None = None


def inspect_worker_heartbeat(
    db_path: str | Path,
    *,
    stale_after_sec: float,
    now: datetime | None = None,
) -> WorkerHealthSnapshot:
    """Inspect the oldest runnable task and determine whether worker heartbeat is stale."""

    current = now or _utc_now()
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        runnable_statuses = (
            TaskStatus.GENERATING.value,
            TaskStatus.LAYOUTING.value,
            TaskStatus.EXPORTING.value,
        )
        task_row = conn.execute(
            """
            SELECT task_id, status, current_stage, current_node_uid, last_heartbeat_at,
                   total_nodes, completed_nodes, updated_at
            FROM task
            WHERE status IN (?, ?, ?)
            ORDER BY updated_at ASC
            LIMIT 1
            """,
            runnable_statuses,
        ).fetchone()

        if task_row is None:
            return WorkerHealthSnapshot(healthy=True, reason="idle")

        task_id = str(task_row["task_id"])
        task_status = str(task_row["status"])
        task_stage = str(task_row["current_stage"] or task_status)
        task_heartbeat = str(task_row["last_heartbeat_at"] or task_row["updated_at"] or "")
        current_node_uid = str(task_row["current_node_uid"] or "").strip() or None
        total_nodes = int(task_row["total_nodes"] or 0)
        completed_nodes = int(task_row["completed_nodes"] or 0)

        if task_status == TaskStatus.GENERATING.value and current_node_uid:
            node_row = conn.execute(
                """
                SELECT node_uid, status, current_stage, last_heartbeat_at, updated_at
                FROM node_state
                WHERE task_id = ? AND node_uid = ?
                LIMIT 1
                """,
                (task_id, current_node_uid),
            ).fetchone()
            if node_row is not None:
                node_status = str(node_row["status"])
                node_stage = str(node_row["current_stage"] or node_status)
                node_heartbeat = str(node_row["last_heartbeat_at"] or node_row["updated_at"] or "")
                if node_status not in {NodeStatus.NODE_DONE.value, NodeStatus.NODE_FAILED.value}:
                    if _is_stale(node_heartbeat, timeout_sec=stale_after_sec, now=current):
                        return WorkerHealthSnapshot(
                            healthy=False,
                            reason="stale node heartbeat",
                            task_id=task_id,
                            node_uid=current_node_uid,
                            stage=node_stage,
                            heartbeat_at=node_heartbeat,
                        )
                    return WorkerHealthSnapshot(
                        healthy=True,
                        reason="active node heartbeat fresh",
                        task_id=task_id,
                        node_uid=current_node_uid,
                        stage=node_stage,
                        heartbeat_at=node_heartbeat,
                    )

        if task_status == TaskStatus.GENERATING.value:
            if total_nodes > completed_nodes and _is_stale(task_heartbeat, timeout_sec=stale_after_sec, now=current):
                return WorkerHealthSnapshot(
                    healthy=False,
                    reason="stale generating task heartbeat",
                    task_id=task_id,
                    node_uid=current_node_uid,
                    stage=task_stage,
                    heartbeat_at=task_heartbeat,
                )
            return WorkerHealthSnapshot(
                healthy=True,
                reason="generating heartbeat fresh",
                task_id=task_id,
                node_uid=current_node_uid,
                stage=task_stage,
                heartbeat_at=task_heartbeat,
            )

        if _is_stale(task_heartbeat, timeout_sec=stale_after_sec, now=current):
            return WorkerHealthSnapshot(
                healthy=False,
                reason="stale task heartbeat",
                task_id=task_id,
                stage=task_stage,
                heartbeat_at=task_heartbeat,
            )
        return WorkerHealthSnapshot(
            healthy=True,
            reason="task heartbeat fresh",
            task_id=task_id,
            stage=task_stage,
            heartbeat_at=task_heartbeat,
        )
    finally:
        conn.close()


@dataclass(frozen=True)
class ManagedServiceSpec:
    name: str
    command: list[str]
    cwd: Path
    record_path: Path
    log_path: Path
    startup_grace_sec: float


@dataclass
class ManagedServiceState:
    handle: subprocess.Popen[bytes] | None = None
    pid: int | None = None
    started_monotonic: float = 0.0
    log_handle: Any | None = None


class Watchdog:
    """Monitor API / Worker and restart only on real health failures."""

    def __init__(
        self,
        *,
        workspace: Path,
        settings: AppSettings,
        check_interval_sec: float = 20.0,
        api_failure_threshold: int = 3,
        api_request_timeout_sec: float = 5.0,
        api_startup_grace_sec: float = 45.0,
        worker_startup_grace_sec: float = 120.0,
        worker_heartbeat_timeout_sec: float = 900.0,
        python_executable: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.settings = settings
        self.check_interval_sec = max(check_interval_sec, 5.0)
        self.api_failure_threshold = max(api_failure_threshold, 1)
        self.api_request_timeout_sec = max(api_request_timeout_sec, 1.0)
        self.worker_heartbeat_timeout_sec = max(worker_heartbeat_timeout_sec, 60.0)
        self.python_executable = python_executable or sys.executable

        self.runtime_dir = self.workspace / self.settings.artifacts_root / "runtime"
        self.pid_dir = self.runtime_dir / "pids"
        self.log_dir = self.runtime_dir / "logs"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.watchdog_log_path = self.log_dir / "watchdog.log"
        self.api_health_url = build_api_health_url(self.settings.api_host, self.settings.api_port)
        self.base_env = self._build_base_env()
        self.should_stop = False

        self.specs = {
            "api": ManagedServiceSpec(
                name="api",
                command=[
                    self.python_executable,
                    "-m",
                    "uvicorn",
                    "backend.api.main:app",
                    "--host",
                    self.settings.api_host,
                    "--port",
                    str(self.settings.api_port),
                ],
                cwd=self.workspace,
                record_path=self.pid_dir / "api.json",
                log_path=self.log_dir / "api.log",
                startup_grace_sec=api_startup_grace_sec,
            ),
            "worker": ManagedServiceSpec(
                name="worker",
                command=[self.python_executable, "-m", "backend.worker.main"],
                cwd=self.workspace,
                record_path=self.pid_dir / "worker.json",
                log_path=self.log_dir / "worker.log",
                startup_grace_sec=worker_startup_grace_sec,
            ),
            "ui": ManagedServiceSpec(
                name="ui",
                command=[
                    self.python_executable,
                    "-m",
                    "backend.worker.ui_runner",
                    "--workspace",
                    str(self.workspace),
                ],
                cwd=self.workspace,
                record_path=self.pid_dir / "ui.json",
                log_path=self.log_dir / "ui.log",
                startup_grace_sec=120.0,
            ),
        }
        self.states = {name: ManagedServiceState() for name in self.specs}
        self.api_failure_count = 0

        self._install_signal_handlers()
        for service_name in self.specs:
            self._adopt_recorded_process(service_name)

    def run_forever(self) -> None:
        self._log(
            "WATCHDOG",
            (
                "Starting watchdog. "
                f"workspace={self.workspace} api_health={self.api_health_url} "
                f"worker_heartbeat_timeout_sec={self.worker_heartbeat_timeout_sec}"
            ),
        )
        try:
            while not self.should_stop:
                self._ensure_running("api")
                self._ensure_running("worker")
                self._ensure_running("ui")
                self._check_api_health()
                self._check_worker_health()
                time.sleep(self.check_interval_sec)
        finally:
            self._close_log_handles()

    def _build_base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        dotenv_path = self.workspace / ".env"
        if dotenv_path.exists():
            for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
        env.setdefault("PYTHONUNBUFFERED", "1")
        return env

    def _install_signal_handlers(self) -> None:
        def _handle_signal(signum: int, _frame: Any) -> None:
            self.should_stop = True
            self._log("WATCHDOG", f"Received signal {signum}; exiting watchdog without killing child services.")

        for signum in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if signum is not None:
                signal.signal(signum, _handle_signal)

    def _adopt_recorded_process(self, service_name: str) -> None:
        spec = self.specs[service_name]
        if not spec.record_path.exists():
            return
        try:
            record = json.loads(spec.record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            spec.record_path.unlink(missing_ok=True)
            return
        pid = int(record.get("pid") or 0)
        if pid <= 0 or not self._pid_exists(pid):
            spec.record_path.unlink(missing_ok=True)
            return
        state = self.states[service_name]
        state.pid = pid
        state.started_monotonic = time.monotonic()
        self._log("WATCHDOG", f"Adopted existing {service_name} process pid={pid}.")

    def _ensure_running(self, service_name: str) -> None:
        state = self.states[service_name]
        pid = self._current_pid(service_name)
        if pid is not None:
            return
        self._start_service(service_name)

    def _start_service(self, service_name: str) -> None:
        spec = self.specs[service_name]
        state = self.states[service_name]
        spec.record_path.parent.mkdir(parents=True, exist_ok=True)
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)

        if state.log_handle is not None:
            try:
                state.log_handle.close()
            except Exception:
                pass
        state.log_handle = open(spec.log_path, "ab")

        kwargs: dict[str, Any] = {
            "cwd": str(spec.cwd),
            "env": self.base_env,
            "stdout": state.log_handle,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True

        process = subprocess.Popen(spec.command, **kwargs)
        state.handle = process
        state.pid = process.pid
        state.started_monotonic = time.monotonic()
        spec.record_path.write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "started_at": _utc_now_iso(),
                    "command": spec.command,
                    "cwd": str(spec.cwd),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._log("WATCHDOG", f"Started {service_name} pid={process.pid}.")

    def _restart_service(self, service_name: str, *, reason: str) -> None:
        pid = self._current_pid(service_name)
        self._log("WATCHDOG", f"Restarting {service_name}. reason={reason} pid={pid}")
        self._stop_service(service_name)
        self._start_service(service_name)

    def _stop_service(self, service_name: str) -> None:
        spec = self.specs[service_name]
        state = self.states[service_name]
        pid = self._current_pid(service_name)

        if state.handle is not None and state.handle.poll() is None:
            state.handle.terminate()
            try:
                state.handle.wait(timeout=20)
            except subprocess.TimeoutExpired:
                state.handle.kill()
                state.handle.wait(timeout=10)
        elif pid is not None:
            self._terminate_pid(pid)

        spec.record_path.unlink(missing_ok=True)
        state.handle = None
        state.pid = None
        state.started_monotonic = 0.0

    def _current_pid(self, service_name: str) -> int | None:
        state = self.states[service_name]
        if state.handle is not None:
            if state.handle.poll() is None:
                state.pid = state.handle.pid
                return state.handle.pid
            self.specs[service_name].record_path.unlink(missing_ok=True)
            state.handle = None
            state.pid = None
            state.started_monotonic = 0.0
            return None
        if state.pid is not None and self._pid_exists(state.pid):
            return state.pid
        if state.pid is not None:
            self.specs[service_name].record_path.unlink(missing_ok=True)
        state.pid = None
        state.started_monotonic = 0.0
        return None

    def _within_startup_grace(self, service_name: str) -> bool:
        state = self.states[service_name]
        if state.started_monotonic <= 0:
            return False
        return (time.monotonic() - state.started_monotonic) < self.specs[service_name].startup_grace_sec

    def _check_api_health(self) -> None:
        if self._within_startup_grace("api"):
            return
        try:
            with urlrequest.urlopen(self.api_health_url, timeout=self.api_request_timeout_sec) as response:
                if response.status != 200:
                    raise RuntimeError(f"Unexpected API status {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") != "ok":
                    raise RuntimeError(f"Unexpected API payload {payload}")
        except (urlerror.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            self.api_failure_count += 1
            self._log(
                "WATCHDOG",
                (
                    f"API health check failed {self.api_failure_count}/{self.api_failure_threshold}: {exc}"
                ),
            )
            if self.api_failure_count >= self.api_failure_threshold:
                self.api_failure_count = 0
                self._restart_service("api", reason=f"health check failed: {exc}")
            return

        if self.api_failure_count:
            self._log("WATCHDOG", "API health check recovered.")
        self.api_failure_count = 0

    def _check_worker_health(self) -> None:
        if self._within_startup_grace("worker"):
            return
        snapshot = inspect_worker_heartbeat(
            self.workspace / self.settings.db_path,
            stale_after_sec=self.worker_heartbeat_timeout_sec,
        )
        if snapshot.healthy:
            return
        self._restart_service(
            "worker",
            reason=(
                f"{snapshot.reason}; task_id={snapshot.task_id or '-'} "
                f"node_uid={snapshot.node_uid or '-'} "
                f"stage={snapshot.stage or '-'} "
                f"heartbeat_at={snapshot.heartbeat_at or '-'}"
            ),
        )

    def _terminate_pid(self, pid: int) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not self._pid_exists(pid):
                return
            time.sleep(0.5)

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _close_log_handles(self) -> None:
        for state in self.states.values():
            if state.log_handle is None:
                continue
            try:
                state.log_handle.close()
            except Exception:
                pass
            state.log_handle = None

    def _log(self, stage: str, message: str) -> None:
        line = f"{_utc_now_iso()} [{stage}] {message}"
        print(line, flush=True)
        with self.watchdog_log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch API and Worker, restarting only on health failure.")
    parser.add_argument("--workspace", default=".", help="Repository root path.")
    parser.add_argument("--check-interval-sec", type=float, default=20.0)
    parser.add_argument("--api-failure-threshold", type=int, default=3)
    parser.add_argument("--api-request-timeout-sec", type=float, default=5.0)
    parser.add_argument("--api-startup-grace-sec", type=float, default=45.0)
    parser.add_argument("--worker-startup-grace-sec", type=float, default=120.0)
    parser.add_argument("--worker-heartbeat-timeout-sec", type=float, default=900.0)
    parser.add_argument("--python-executable", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    workspace = Path(args.workspace).resolve()
    os.chdir(workspace)
    settings = load_settings(workspace / ".env")
    watchdog = Watchdog(
        workspace=workspace,
        settings=settings,
        check_interval_sec=args.check_interval_sec,
        api_failure_threshold=args.api_failure_threshold,
        api_request_timeout_sec=args.api_request_timeout_sec,
        api_startup_grace_sec=args.api_startup_grace_sec,
        worker_startup_grace_sec=args.worker_startup_grace_sec,
        worker_heartbeat_timeout_sec=args.worker_heartbeat_timeout_sec,
        python_executable=args.python_executable,
    )
    watchdog.run_forever()


if __name__ == "__main__":
    main()
