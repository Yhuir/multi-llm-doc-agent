"""TOC versions and node snapshots persistence."""

from __future__ import annotations

import json
import uuid
from typing import Any

from backend.models.schemas import TOCNode, TOCNodeSnapshot, TOCVersion, utc_now_iso
from backend.repositories.db import SQLiteDB


class TOCRepository:
    def __init__(self, db: SQLiteDB) -> None:
        self.db = db

    def create_version(self, toc_version: TOCVersion) -> TOCVersion:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO toc_version (
                    toc_version_id, task_id, version_no, file_path, based_on_version_no,
                    is_confirmed, diff_summary_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    toc_version.toc_version_id,
                    toc_version.task_id,
                    toc_version.version_no,
                    toc_version.file_path,
                    toc_version.based_on_version_no,
                    int(toc_version.is_confirmed),
                    json.dumps(toc_version.diff_summary_json, ensure_ascii=False)
                    if toc_version.diff_summary_json is not None
                    else None,
                    toc_version.created_by,
                    toc_version.created_at,
                ),
            )
        return toc_version

    def mark_confirmed(self, task_id: str, version_no: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE toc_version SET is_confirmed = 0 WHERE task_id = ?",
                (task_id,),
            )
            conn.execute(
                """
                UPDATE toc_version
                SET is_confirmed = 1
                WHERE task_id = ? AND version_no = ?
                """,
                (task_id, version_no),
            )

    def list_versions(self, task_id: str) -> list[TOCVersion]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM toc_version WHERE task_id = ? ORDER BY version_no DESC",
                (task_id,),
            ).fetchall()
        return [self._row_to_version(row) for row in rows]

    def get_version(self, task_id: str, version_no: int) -> TOCVersion | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM toc_version WHERE task_id = ? AND version_no = ?",
                (task_id, version_no),
            ).fetchone()
        return self._row_to_version(row) if row else None

    def get_latest_version(self, task_id: str) -> TOCVersion | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM toc_version
                WHERE task_id = ?
                ORDER BY version_no DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return self._row_to_version(row) if row else None

    def replace_snapshots(
        self,
        task_id: str,
        version_no: int,
        tree: list[TOCNode],
    ) -> list[TOCNodeSnapshot]:
        snapshots = self._flatten_tree(task_id=task_id, version_no=version_no, tree=tree)
        with self.db.connection() as conn:
            conn.execute(
                "DELETE FROM toc_node_snapshot WHERE task_id = ? AND version_no = ?",
                (task_id, version_no),
            )
            for item in snapshots:
                conn.execute(
                    """
                    INSERT INTO toc_node_snapshot (
                        snapshot_id, task_id, version_no, node_uid, node_id,
                        parent_node_uid, level, title, order_index, is_generation_unit,
                        source_refs_json, constraints_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.snapshot_id,
                        item.task_id,
                        item.version_no,
                        item.node_uid,
                        item.node_id,
                        item.parent_node_uid,
                        item.level,
                        item.title,
                        item.order_index,
                        int(item.is_generation_unit),
                        json.dumps(item.source_refs_json, ensure_ascii=False)
                        if item.source_refs_json is not None
                        else None,
                        json.dumps(item.constraints_json, ensure_ascii=False)
                        if item.constraints_json is not None
                        else None,
                        item.created_at,
                    ),
                )
        return snapshots

    def list_generation_units(self, task_id: str, version_no: int) -> list[TOCNodeSnapshot]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM toc_node_snapshot
                WHERE task_id = ? AND version_no = ? AND is_generation_unit = 1
                ORDER BY order_index ASC
                """,
                (task_id, version_no),
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    @staticmethod
    def _row_to_version(row: Any) -> TOCVersion:
        return TOCVersion(
            toc_version_id=row["toc_version_id"],
            task_id=row["task_id"],
            version_no=row["version_no"],
            file_path=row["file_path"],
            based_on_version_no=row["based_on_version_no"],
            is_confirmed=bool(row["is_confirmed"]),
            diff_summary_json=json.loads(row["diff_summary_json"])
            if row["diff_summary_json"]
            else None,
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_snapshot(row: Any) -> TOCNodeSnapshot:
        return TOCNodeSnapshot(
            snapshot_id=row["snapshot_id"],
            task_id=row["task_id"],
            version_no=row["version_no"],
            node_uid=row["node_uid"],
            node_id=row["node_id"],
            parent_node_uid=row["parent_node_uid"],
            level=row["level"],
            title=row["title"],
            order_index=row["order_index"],
            is_generation_unit=bool(row["is_generation_unit"]),
            source_refs_json=json.loads(row["source_refs_json"])
            if row["source_refs_json"]
            else None,
            constraints_json=json.loads(row["constraints_json"])
            if row["constraints_json"]
            else None,
            created_at=row["created_at"],
        )

    def _flatten_tree(
        self,
        *,
        task_id: str,
        version_no: int,
        tree: list[TOCNode],
    ) -> list[TOCNodeSnapshot]:
        snapshots: list[TOCNodeSnapshot] = []
        order = 0

        def walk(node: TOCNode, parent_uid: str | None) -> None:
            nonlocal order
            order += 1
            snapshots.append(
                TOCNodeSnapshot(
                    snapshot_id=f"snap_{uuid.uuid4().hex[:12]}",
                    task_id=task_id,
                    version_no=version_no,
                    node_uid=node.node_uid,
                    node_id=node.node_id,
                    parent_node_uid=parent_uid,
                    level=node.level,
                    title=node.title,
                    order_index=order,
                    is_generation_unit=node.is_generation_unit,
                    source_refs_json=node.source_refs,
                    constraints_json=node.constraints,
                    created_at=utc_now_iso(),
                )
            )
            for child in node.children:
                walk(child, node.node_uid)

        for root in tree:
            walk(root, None)

        return snapshots
