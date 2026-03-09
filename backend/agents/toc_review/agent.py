"""Rule-based TOC review agent that applies user feedback to the tree."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from backend.models.schemas import TOCDocument, TOCNode


@dataclass(slots=True)
class _NodeRef:
    node: TOCNode
    parent: TOCNode | None
    index: int


class TOCReviewChatAgent:
    """Apply common TOC review actions while preserving stable node_uid values."""

    _MINIMAX_TEXT_ENDPOINT = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
    _SPLIT_PATTERN = re.compile(r"[；;\n]+|(?:并且|同时|然后)")
    _QUOTE_PATTERN = re.compile(r"[“\"'‘](.+?)[”\"'’]")
    _MOVE_PATTERN = re.compile(r"(移动到|移到|放到|调整到|挪到)")
    _RENAME_KEYWORDS = ("改为", "改成", "修改为", "调整为", "命名为", "改名为", "更名为")
    _ADD_KEYWORDS = ("新增", "增加", "添加", "补充")
    _REMOVE_KEYWORDS = ("删除", "移除", "去掉", "删掉")
    _ORDINAL_MAP = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "十一": 11,
        "十二": 12,
        "十三": 13,
        "十四": 14,
        "十五": 15,
        "十六": 16,
        "十七": 17,
        "十八": 18,
        "十九": 19,
        "二十": 20,
        "首": 1,
        "首个": 1,
        "第一个": 1,
    }

    def review(
        self,
        *,
        toc_doc: TOCDocument,
        feedback: str,
        review_config: dict[str, Any] | None = None,
    ) -> TOCDocument:
        updated = copy.deepcopy(toc_doc)
        changed = False
        explicit_keep_targets = self._extract_keep_only_targets_from_feedback(feedback)
        if explicit_keep_targets:
            changed = self._apply_keep_only_action(
                updated.tree,
                targets=explicit_keep_targets,
                include_descendants=False,
            )
        else:
            actions = self._plan_actions_with_model(
                toc_doc=toc_doc,
                feedback=feedback,
                review_config=review_config or {},
            )
            actions = self._normalize_model_actions(actions, explicit_keep_targets)
            if actions:
                changed = self._apply_planned_actions(updated.tree, actions)

        if not changed:
            if self._apply_keep_only_from_feedback(updated.tree, feedback):
                changed = True

        if not changed:
            clauses = [item.strip() for item in self._SPLIT_PATTERN.split(feedback) if item.strip()]
            for clause in clauses:
                if self._apply_move(updated.tree, clause):
                    changed = True
                    continue
                if self._apply_rename(updated.tree, clause):
                    changed = True
                    continue
                if self._apply_add(updated.tree, clause):
                    changed = True
                    continue
                if self._apply_remove(updated.tree, clause):
                    changed = True
                    continue
                if self._apply_soft_rename(updated.tree, clause):
                    changed = True

        if not changed:
            return updated
        return updated

    def _normalize_model_actions(
        self,
        actions: list[dict[str, Any]],
        explicit_keep_targets: list[str],
    ) -> list[dict[str, Any]]:
        if not explicit_keep_targets:
            return actions
        normalized: list[dict[str, Any]] = []
        keep_overridden = False
        for action in actions:
            action_type = str(action.get("type") or "").strip().lower()
            if action_type == "keep_only" and not keep_overridden:
                patched = dict(action)
                patched["targets"] = explicit_keep_targets
                patched["include_descendants"] = False
                normalized.append(patched)
                keep_overridden = True
            else:
                normalized.append(action)
        if not keep_overridden and explicit_keep_targets:
            normalized.append(
                {
                    "type": "keep_only",
                    "targets": explicit_keep_targets,
                    "include_descendants": False,
                }
            )
        return normalized

    def _apply_keep_only_from_feedback(self, tree: list[TOCNode], feedback: str) -> bool:
        targets = self._extract_keep_only_targets_from_feedback(feedback)
        if not targets:
            return False
        return self._apply_keep_only_action(tree, targets=targets, include_descendants=False)

    def _extract_keep_only_targets_from_feedback(self, feedback: str) -> list[str]:
        compact = re.sub(r"\s+", "", feedback)
        if "仅保留" not in compact and "只保留" not in compact:
            return []
        if "删除其他" not in compact and "其余删除" not in compact and "其他都删除" not in compact:
            return []

        targets: list[str] = []
        for raw_line in feedback.splitlines():
            line = raw_line.strip().strip("“”\"'‘’")
            if not line:
                continue
            line = re.sub(r"\s+生成单元$", "", line)
            matched = re.match(r"^(?P<id>\d+(?:\.\d+)*)\s+(?P<title>.+)$", line)
            if matched is None:
                continue
            title = matched.group("title").strip()
            if title:
                targets.append(title)
            else:
                targets.append(matched.group("id"))
        return targets

    def _apply_planned_actions(self, tree: list[TOCNode], actions: list[dict[str, Any]]) -> bool:
        changed = False
        for action in actions:
            action_type = str(action.get("type") or "").strip().lower()
            if action_type == "rename":
                changed = self._apply_rename_action(
                    tree,
                    target=str(action.get("target") or ""),
                    new_title=str(action.get("new_title") or ""),
                ) or changed
            elif action_type == "add_child":
                changed = self._apply_add_action(
                    tree,
                    target=str(action.get("parent") or ""),
                    new_title=str(action.get("title") or ""),
                    mode="child",
                ) or changed
            elif action_type == "add_before":
                changed = self._apply_add_action(
                    tree,
                    target=str(action.get("reference") or action.get("target") or ""),
                    new_title=str(action.get("title") or ""),
                    mode="before",
                ) or changed
            elif action_type == "add_after":
                changed = self._apply_add_action(
                    tree,
                    target=str(action.get("reference") or action.get("target") or ""),
                    new_title=str(action.get("title") or ""),
                    mode="after",
                ) or changed
            elif action_type == "remove":
                changed = self._apply_remove_action(
                    tree,
                    target=str(action.get("target") or ""),
                ) or changed
            elif action_type == "move_before":
                changed = self._apply_move_action(
                    tree,
                    source=str(action.get("target") or action.get("source") or ""),
                    reference=str(action.get("reference") or ""),
                    mode="before",
                ) or changed
            elif action_type == "move_after":
                changed = self._apply_move_action(
                    tree,
                    source=str(action.get("target") or action.get("source") or ""),
                    reference=str(action.get("reference") or ""),
                    mode="after",
                ) or changed
            elif action_type == "move_under":
                changed = self._apply_move_action(
                    tree,
                    source=str(action.get("target") or action.get("source") or ""),
                    reference=str(action.get("parent") or action.get("reference") or ""),
                    mode="child",
                ) or changed
            elif action_type == "keep_only":
                targets = action.get("targets") or action.get("keep") or []
                include_descendants = bool(action.get("include_descendants", False))
                if isinstance(targets, list):
                    changed = self._apply_keep_only_action(
                        tree,
                        targets=[str(item) for item in targets if str(item).strip()],
                        include_descendants=include_descendants,
                    ) or changed
        return changed

    def _apply_rename_action(self, tree: list[TOCNode], *, target: str, new_title: str) -> bool:
        target_ref = self._match_node(tree, target)
        cleaned_title = self._cleanup_feedback_title(new_title)
        if target_ref is None or not cleaned_title:
            return False
        if self._normalize_title(cleaned_title) == self._normalize_title(target_ref.node.title):
            return False
        target_ref.node.title = cleaned_title
        return True

    def _apply_add_action(self, tree: list[TOCNode], *, target: str, new_title: str, mode: str) -> bool:
        target_ref = self._match_node(tree, target)
        cleaned_title = self._cleanup_feedback_title(new_title)
        if target_ref is None or not cleaned_title:
            return False

        if mode == "child":
            parent = target_ref.node
            prototype = parent.children[0] if parent.children else None
            if parent.is_generation_unit:
                parent.is_generation_unit = False
                parent.constraints = None
            parent.children.append(self._build_new_node(parent=parent, title=cleaned_title, prototype=prototype))
            return True

        parent = target_ref.parent
        if parent is None:
            return False
        insert_index = target_ref.index if mode == "before" else target_ref.index + 1
        parent.children.insert(
            insert_index,
            self._build_new_node(parent=parent, title=cleaned_title, prototype=target_ref.node),
        )
        return True

    def _apply_remove_action(self, tree: list[TOCNode], *, target: str) -> bool:
        target_ref = self._match_node(tree, target)
        if target_ref is None or target_ref.parent is None:
            return False
        target_ref.parent.children.pop(target_ref.index)
        self._normalize_parent_after_child_change(target_ref.parent)
        return True

    def _apply_move_action(self, tree: list[TOCNode], *, source: str, reference: str, mode: str) -> bool:
        source_ref = self._match_node(tree, source)
        target_ref = self._match_node(
            tree,
            reference,
            exclude_uid=source_ref.node.node_uid if source_ref else None,
        )
        if source_ref is None or target_ref is None or source_ref.parent is None:
            return False
        if mode == "child" and self._contains_uid(source_ref.node, target_ref.node.node_uid):
            return False

        moving_node = source_ref.parent.children.pop(source_ref.index)
        self._normalize_parent_after_child_change(source_ref.parent)

        if mode == "child":
            target_ref = self._match_node(tree, target_ref.node.node_uid)
            if target_ref is None:
                return False
            if target_ref.node.is_generation_unit:
                target_ref.node.is_generation_unit = False
                target_ref.node.constraints = None
            self._relevel_subtree(moving_node, target_ref.node.level + 1)
            target_ref.node.children.append(moving_node)
            return True

        target_ref = self._match_node(tree, target_ref.node.node_uid)
        if target_ref is None or target_ref.parent is None:
            return False
        self._relevel_subtree(moving_node, target_ref.node.level)
        insert_index = target_ref.index if mode == "before" else target_ref.index + 1
        target_ref.parent.children.insert(insert_index, moving_node)
        return True

    def _apply_keep_only_action(
        self,
        tree: list[TOCNode],
        *,
        targets: list[str],
        include_descendants: bool,
    ) -> bool:
        matched = [self._match_node(tree, target) for target in targets]
        matched_refs = [ref for ref in matched if ref is not None]
        if not matched_refs:
            return False

        keep_uids = {ref.node.node_uid for ref in matched_refs}
        ancestor_uids: set[str] = set()
        for ref in matched_refs:
            parent = ref.parent
            while parent is not None:
                ancestor_uids.add(parent.node_uid)
                parent_ref = self._find_ref_by_uid(tree, parent.node_uid)
                parent = parent_ref.parent if parent_ref is not None else None

        descendant_uids: set[str] = set()
        if include_descendants:
            for ref in matched_refs:
                self._collect_descendant_uids(ref.node, descendant_uids)

        allowed = keep_uids | ancestor_uids | descendant_uids
        changed = False
        for root in tree:
            root_changed, kept_children = self._prune_node_children(root, allowed)
            if root_changed:
                changed = True
            root.children = kept_children
            self._normalize_parent_after_child_change(root)
        return changed

    def _plan_actions_with_model(
        self,
        *,
        toc_doc: TOCDocument,
        feedback: str,
        review_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        provider = str(review_config.get("text_provider") or "").strip().lower()
        api_key = str(review_config.get("text_api_key") or "").strip()
        model_name = str(review_config.get("text_model_name") or "MiniMax-M2.5").strip() or "MiniMax-M2.5"
        if provider != "minimax" or not api_key:
            return []

        prompt = self._build_model_prompt(toc_doc=toc_doc, feedback=feedback)
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "name": "TOC Review Planner"},
                {"role": "user", "name": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        req = urlrequest.Request(
            self._MINIMAX_TEXT_ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urlrequest.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
        except (urlerror.URLError, TimeoutError, ValueError):
            return []

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return []

        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            return []

        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if isinstance(data.get("choices"), list)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            return []
        return self._extract_actions_from_model_text(content)

    def _build_model_prompt(self, *, toc_doc: TOCDocument, feedback: str) -> str:
        toc_lines = self._render_toc_lines(toc_doc.tree)
        instructions = [
            "你是目录审阅动作规划器。",
            "任务：根据用户的目录修改意见，把当前 TOC 转成结构化编辑动作。",
            "只允许输出 JSON，不要输出解释文字。",
            '输出格式：{"actions":[...]}',
            "允许的动作类型：rename, add_child, add_before, add_after, remove, move_before, move_after, move_under, keep_only。",
            'rename: {"type":"rename","target":"现有章节标题或编号","new_title":"新标题"}',
            'add_child: {"type":"add_child","parent":"现有章节标题或编号","title":"新增标题"}',
            'add_before/add_after: {"type":"add_before","reference":"现有章节标题或编号","title":"新增标题"}',
            'remove: {"type":"remove","target":"现有章节标题或编号"}',
            'move_before/move_after: {"type":"move_after","target":"要移动的标题","reference":"参考标题"}',
            'move_under: {"type":"move_under","target":"要移动的标题","parent":"新的父标题"}',
            'keep_only: {"type":"keep_only","targets":["要保留的标题或编号", "..."],"include_descendants":false}',
            "当用户表达“仅保留以下目录，删除其他”“只保留这些章节”时，优先使用 keep_only。",
            "如果意见不明确或无法从 TOC 中唯一定位，请返回空数组。",
            "不要重写整棵 TOC，不要发明大量新章节，只提取用户明确要求的修改。",
            "",
            "当前 TOC：",
            *toc_lines,
            "",
            f"用户意见：{feedback}",
        ]
        return "\n".join(instructions)

    def _render_toc_lines(self, tree: list[TOCNode]) -> list[str]:
        lines: list[str] = []

        def walk(nodes: list[TOCNode], depth: int) -> None:
            for node in nodes:
                if depth > 0:
                    lines.append(f'{"  " * (depth - 1)}- {node.node_id} {node.title}')
                walk(node.children, depth + 1)

        walk(tree, 0)
        return lines

    def _extract_actions_from_model_text(self, content: str) -> list[dict[str, Any]]:
        candidates = []
        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.S)
        candidates.extend(fenced)
        first = content.find("{")
        last = content.rfind("}")
        if first != -1 and last != -1 and first < last:
            candidates.append(content[first : last + 1])
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            actions = payload.get("actions")
            if isinstance(actions, list):
                return [item for item in actions if isinstance(item, dict)]
        return []

    def _find_ref_by_uid(self, tree: list[TOCNode], node_uid: str) -> _NodeRef | None:
        for ref in self._iter_refs(tree):
            if ref.node.node_uid == node_uid:
                return ref
        return None

    def _collect_descendant_uids(self, node: TOCNode, bucket: set[str]) -> None:
        bucket.add(node.node_uid)
        for child in node.children:
            self._collect_descendant_uids(child, bucket)

    def _prune_node_children(self, node: TOCNode, allowed: set[str]) -> tuple[bool, list[TOCNode]]:
        changed = False
        kept_children: list[TOCNode] = []
        for child in node.children:
            child_changed, child_kept = self._prune_node_children(child, allowed)
            if child_changed:
                changed = True
            child.children = child_kept
            if child.node_uid in allowed:
                kept_children.append(child)
                self._normalize_parent_after_child_change(child)
            else:
                changed = True
        return changed, kept_children

    def _apply_rename(self, tree: list[TOCNode], clause: str) -> bool:
        if not any(token in clause for token in self._RENAME_KEYWORDS):
            return False

        old_query = ""
        new_title = ""
        quoted = self._quoted_strings(clause)
        if len(quoted) >= 2:
            old_query, new_title = quoted[0], quoted[1]
        else:
            keyword = next((item for item in self._RENAME_KEYWORDS if item in clause), None)
            if keyword is None:
                return False
            matched = re.search(
                rf"(?:把|将)?(?P<old>.+?){re.escape(keyword)}(?P<new>.+)$",
                clause,
            )
            if matched is None:
                return False
            old_query = matched.group("old")
            new_title = matched.group("new")

        target_ref = self._match_node(tree, old_query)
        cleaned_title = self._cleanup_feedback_title(new_title)
        if target_ref is None or not cleaned_title:
            return False
        if self._normalize_title(cleaned_title) == self._normalize_title(target_ref.node.title):
            return False

        target_ref.node.title = cleaned_title
        return True

    def _apply_add(self, tree: list[TOCNode], clause: str) -> bool:
        if not any(token in clause for token in self._ADD_KEYWORDS):
            return False

        quoted = self._quoted_strings(clause)
        target_ref: _NodeRef | None = None
        new_title = ""
        mode = "child"

        if len(quoted) >= 2:
            if re.match(r"^\s*(?:新增|增加|添加|补充)", clause):
                target_ref = self._match_node(tree, quoted[1])
                new_title = quoted[0]
            else:
                target_ref = self._match_node(tree, quoted[0])
                new_title = quoted[1]
        else:
            matched = re.search(
                r"在(?P<target>.+?)(?P<pos>下|下面|前|前面|后|后面)(?:新增|增加|添加|补充)(?P<title>.+)$",
                clause,
            )
            if matched is not None:
                target_ref = self._match_node(tree, matched.group("target"))
                new_title = matched.group("title")
                mode = self._position_mode(matched.group("pos"))
            else:
                matched = re.search(
                    r"(?:新增|增加|添加|补充)(?P<title>.+?)到(?P<target>.+?)(?P<pos>下|下面|前|前面|后|后面)$",
                    clause,
                )
                if matched is not None:
                    target_ref = self._match_node(tree, matched.group("target"))
                    new_title = matched.group("title")
                    mode = self._position_mode(matched.group("pos"))
        if target_ref is None and len(quoted) >= 2:
            mode = self._infer_add_mode(clause)
            target_ref = self._match_node(tree, quoted[0])

        if target_ref is None:
            return False

        if "前" in clause:
            mode = "before"
        elif "后" in clause:
            mode = "after"
        elif "下" in clause:
            mode = "child"

        cleaned_title = self._cleanup_feedback_title(new_title)
        if not cleaned_title:
            return False

        if mode == "child":
            parent = target_ref.node
            prototype = parent.children[0] if parent.children else None
            if parent.is_generation_unit:
                parent.is_generation_unit = False
                parent.constraints = None
            new_node = self._build_new_node(parent=parent, title=cleaned_title, prototype=prototype)
            parent.children.append(new_node)
            return True

        parent = target_ref.parent
        if parent is None:
            return False
        new_node = self._build_new_node(parent=parent, title=cleaned_title, prototype=target_ref.node)
        insert_index = target_ref.index if mode == "before" else target_ref.index + 1
        parent.children.insert(insert_index, new_node)
        return True

    def _apply_remove(self, tree: list[TOCNode], clause: str) -> bool:
        if not any(token in clause for token in self._REMOVE_KEYWORDS):
            return False

        quoted = self._quoted_strings(clause)
        query = quoted[0] if quoted else clause
        target_ref = self._match_node(tree, query)
        if target_ref is None or target_ref.parent is None:
            return False

        target_ref.parent.children.pop(target_ref.index)
        self._normalize_parent_after_child_change(target_ref.parent)
        return True

    def _apply_move(self, tree: list[TOCNode], clause: str) -> bool:
        if self._MOVE_PATTERN.search(clause) is None:
            return False

        quoted = self._quoted_strings(clause)
        source_ref: _NodeRef | None = None
        target_ref: _NodeRef | None = None

        if len(quoted) >= 2:
            source_ref = self._match_node(tree, quoted[0])
            target_ref = self._match_node(tree, quoted[1], exclude_uid=source_ref.node.node_uid if source_ref else None)
        else:
            matched = re.search(
                r"(?:把|将)(?P<src>.+?)(?:移动到|移到|放到|调整到|挪到)(?P<target>.+?)(?P<pos>前面|前|后面|后|下面|下级|之下)$",
                clause,
            )
            if matched is None:
                return False
            source_ref = self._match_node(tree, matched.group("src"))
            target_ref = self._match_node(
                tree,
                matched.group("target"),
                exclude_uid=source_ref.node.node_uid if source_ref else None,
            )

        if source_ref is None or target_ref is None or source_ref.parent is None:
            return False

        position = "after"
        if any(token in clause for token in ("前面", "前")):
            position = "before"
        elif any(token in clause for token in ("下面", "下级", "之下")):
            position = "child"

        if position == "child" and self._contains_uid(source_ref.node, target_ref.node.node_uid):
            return False

        moving_node = source_ref.parent.children.pop(source_ref.index)
        self._normalize_parent_after_child_change(source_ref.parent)

        if position == "child":
            target_ref = self._match_node(tree, target_ref.node.node_uid)
            if target_ref is None:
                return False
            if target_ref.node.is_generation_unit:
                target_ref.node.is_generation_unit = False
                target_ref.node.constraints = None
            self._relevel_subtree(moving_node, target_ref.node.level + 1)
            target_ref.node.children.append(moving_node)
            return True

        target_ref = self._match_node(tree, target_ref.node.node_uid)
        if target_ref is None or target_ref.parent is None:
            return False

        self._relevel_subtree(moving_node, target_ref.node.level)
        insert_index = target_ref.index if position == "before" else target_ref.index + 1
        target_ref.parent.children.insert(insert_index, moving_node)
        return True

    def _apply_soft_rename(self, tree: list[TOCNode], clause: str) -> bool:
        if not any(token in clause for token in ("第一章", "第一章节", "首章")):
            return False
        if not any(token in clause for token in ("更明确", "更清晰", "修订", "优化标题")):
            return False

        first_editable = next((ref for ref in self._iter_refs(tree) if ref.parent is not None), None)
        if first_editable is None:
            return False
        if first_editable.node.title.endswith("（修订）"):
            return False
        first_editable.node.title = f"{first_editable.node.title}（修订）"
        return True

    def _build_new_node(self, *, parent: TOCNode, title: str, prototype: TOCNode | None) -> TOCNode:
        sibling_count = sum(
            1
            for child in parent.children
            if self._normalize_title(child.title) == self._normalize_title(title)
        )
        if prototype is not None and prototype.level == parent.level + 1:
            return self._clone_from_prototype(
                prototype=prototype,
                title=title,
                parent_uid=parent.node_uid,
                occurrence=sibling_count + 1,
            )

        level = parent.level + 1
        return TOCNode(
            node_uid=self._stable_uid(level, f"{parent.node_uid}::{self._normalize_title(title)}::{sibling_count + 1}"),
            node_id="",
            level=level,
            title=title,
            is_generation_unit=level >= 3,
            source_refs=list(parent.source_refs),
            constraints=self._generation_constraints() if level >= 3 else None,
            children=[],
        )

    def _clone_from_prototype(
        self,
        *,
        prototype: TOCNode,
        title: str,
        parent_uid: str,
        occurrence: int,
    ) -> TOCNode:
        cloned = TOCNode(
            node_uid=self._stable_uid(
                prototype.level,
                f"{parent_uid}::{self._normalize_title(title)}::{prototype.level}::{occurrence}",
            ),
            node_id=prototype.node_id,
            level=prototype.level,
            title=title,
            is_generation_unit=prototype.is_generation_unit,
            source_refs=list(prototype.source_refs),
            constraints=copy.deepcopy(prototype.constraints),
            children=[],
        )

        for index, child in enumerate(prototype.children, start=1):
            cloned.children.append(
                self._clone_child_subtree(
                    prototype=child,
                    parent_uid=cloned.node_uid,
                    occurrence=index,
                )
            )
        return cloned

    def _clone_child_subtree(self, *, prototype: TOCNode, parent_uid: str, occurrence: int) -> TOCNode:
        cloned = TOCNode(
            node_uid=self._stable_uid(
                prototype.level,
                f"{parent_uid}::{self._normalize_title(prototype.title)}::{prototype.level}::{occurrence}",
            ),
            node_id=prototype.node_id,
            level=prototype.level,
            title=prototype.title,
            is_generation_unit=prototype.is_generation_unit,
            source_refs=list(prototype.source_refs),
            constraints=copy.deepcopy(prototype.constraints),
            children=[],
        )
        for index, child in enumerate(prototype.children, start=1):
            cloned.children.append(
                self._clone_child_subtree(
                    prototype=child,
                    parent_uid=cloned.node_uid,
                    occurrence=index,
                )
            )
        return cloned

    def _iter_refs(self, tree: list[TOCNode]) -> list[_NodeRef]:
        refs: list[_NodeRef] = []

        def walk(nodes: list[TOCNode], parent: TOCNode | None) -> None:
            for index, node in enumerate(nodes):
                refs.append(_NodeRef(node=node, parent=parent, index=index))
                walk(node.children, node)

        walk(tree, None)
        return refs

    def _match_node(
        self,
        tree: list[TOCNode],
        query: str,
        *,
        exclude_uid: str | None = None,
    ) -> _NodeRef | None:
        query = self._cleanup_feedback_title(query)
        if not query:
            return None

        for ref in self._iter_refs(tree):
            if exclude_uid and ref.node.node_uid == exclude_uid:
                continue
            if ref.parent is None:
                continue
            if (
                query == ref.node.node_uid
                or query == ref.node.node_id
                or query == self._visible_node_id(ref.node.node_id)
            ):
                return ref

        ordinal_ref = self._match_ordinal_ref(tree, query, exclude_uid=exclude_uid)
        if ordinal_ref is not None:
            return ordinal_ref

        normalized_query = self._normalize_title(query)
        if not normalized_query:
            return None

        best: tuple[int, _NodeRef] | None = None
        for ref in self._iter_refs(tree):
            if exclude_uid and ref.node.node_uid == exclude_uid:
                continue
            if ref.parent is None:
                continue
            score = self._match_score(ref.node, query, normalized_query)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, ref)
        return best[1] if best else None

    def _match_ordinal_ref(
        self,
        tree: list[TOCNode],
        query: str,
        *,
        exclude_uid: str | None = None,
    ) -> _NodeRef | None:
        compact = re.sub(r"\s+", "", query)
        level: int | None = None
        if "一级标题" in compact or "第一章" in compact or "章" in compact:
            level = 2
        if "二级标题" in compact:
            level = 3
        if "三级标题" in compact:
            level = 4
        if "四级标题" in compact:
            level = 5
        if "章节" in compact and level is None:
            level = 2
        if "标题" in compact and level is None:
            level = None

        ordinal = self._extract_ordinal(compact)
        if ordinal is None:
            return None

        refs = [
            ref
            for ref in self._iter_refs(tree)
            if ref.parent is not None and (exclude_uid is None or ref.node.node_uid != exclude_uid)
        ]
        if level is not None:
            refs = [ref for ref in refs if ref.node.level == level]
        if not refs or ordinal < 1 or ordinal > len(refs):
            return None
        return refs[ordinal - 1]

    def _extract_ordinal(self, query: str) -> int | None:
        digit_match = re.search(r"第?(?P<num>\d+)(?:个|章|节|级标题|标题)?", query)
        if digit_match is not None:
            return int(digit_match.group("num"))

        longest = sorted(self._ORDINAL_MAP, key=len, reverse=True)
        for token in longest:
            if f"第{token}" in query or query.startswith(token):
                return self._ORDINAL_MAP[token]
        return None

    def _match_score(self, node: TOCNode, raw_query: str, normalized_query: str) -> int:
        if raw_query == node.node_uid or raw_query == node.node_id:
            return 10_000

        raw_title = self._strip_quotes(raw_query)
        normalized_title = self._normalize_title(node.title)
        if normalized_query == normalized_title:
            return 9_000 + len(normalized_title)
        if normalized_title and normalized_title in normalized_query:
            return 7_000 + len(normalized_title)
        if normalized_query and normalized_query in normalized_title:
            return 6_000 + len(normalized_query)
        if raw_title and raw_title in node.title:
            return 5_000 + len(raw_title)
        if node.title in raw_title:
            return 4_000 + len(node.title)
        return 0

    def _relevel_subtree(self, node: TOCNode, level: int) -> None:
        node.level = level
        for child in node.children:
            self._relevel_subtree(child, level + 1)
        if node.children:
            node.is_generation_unit = False
            node.constraints = None
        elif node.level >= 3:
            node.is_generation_unit = True
            node.constraints = node.constraints or self._generation_constraints()
        else:
            node.is_generation_unit = False
            node.constraints = None

    def _contains_uid(self, node: TOCNode, target_uid: str) -> bool:
        if node.node_uid == target_uid:
            return True
        return any(self._contains_uid(child, target_uid) for child in node.children)

    def _normalize_parent_after_child_change(self, parent: TOCNode) -> None:
        if parent.children:
            parent.is_generation_unit = False
            parent.constraints = None
            return
        if parent.level >= 3:
            parent.is_generation_unit = True
            parent.constraints = parent.constraints or self._generation_constraints()
        else:
            parent.is_generation_unit = False
            parent.constraints = None

    def _quoted_strings(self, text: str) -> list[str]:
        return [item.strip() for item in self._QUOTE_PATTERN.findall(text) if item.strip()]

    def _infer_add_mode(self, clause: str) -> str:
        if "前" in clause:
            return "before"
        if "后" in clause:
            return "after"
        return "child"

    def _position_mode(self, token: str) -> str:
        if "前" in token:
            return "before"
        if "后" in token:
            return "after"
        return "child"

    def _cleanup_feedback_title(self, text: str) -> str:
        cleaned = self._strip_quotes(text)
        cleaned = re.sub(r"^(?:请|请把|请将|把|将|在|到|对)\s*", "", cleaned)
        cleaned = re.sub(r"(?:吧|一下|一些|一下子|谢谢|即可|就行了?)$", "", cleaned)
        cleaned = cleaned.strip(" ：:，,。；;、")
        return cleaned.strip()

    def _strip_quotes(self, text: str) -> str:
        return text.strip().strip("“”\"'‘’")

    def _normalize_title(self, text: str) -> str:
        cleaned = self._strip_quotes(text)
        cleaned = re.sub(r"^[0-9]+(?:\.[0-9]+)*", "", cleaned)
        cleaned = re.sub(r"^[（(]?[一二三四五六七八九十百千0-9]+[)）.、]+", "", cleaned)
        cleaned = re.sub(r"[\s，。；：:、,.!！?？()（）【】\\[\\]<>《》“”\"'‘’\\-—_]+", "", cleaned)
        return cleaned.lower()

    def _visible_node_id(self, node_id: str) -> str:
        parts = node_id.split(".")
        if len(parts) <= 1:
            return node_id
        return ".".join(parts[1:])

    def _stable_uid(self, level: int, seed: str) -> str:
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
        return f"uid_l{level}_{digest}"

    def _generation_constraints(self) -> dict[str, object]:
        return {
            "min_words": 1800,
            "recommended_words": [1800, 2200],
            "images": [2, 3],
        }
