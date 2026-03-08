"""Streamlit UI for the first runnable V1 skeleton."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure `backend` package is importable when running `streamlit run ui/app.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app_service.task_service import TaskService
from backend.models.enums import TaskStatus


@st.cache_resource
def get_task_service() -> TaskService:
    return TaskService()


def task_label(task) -> str:
    return f"{task.task_id} | {task.title} | {status_cn(task.status.value)}"


def status_cn(status: str | None) -> str:
    mapping = {
        "NEW": "新建",
        "PARSED": "已解析",
        "TOC_REVIEW": "目录审阅中",
        "GENERATING": "内容生成中",
        "LAYOUTING": "排版中",
        "EXPORTING": "导出中",
        "DONE": "已完成",
        "PAUSED": "已暂停",
        "FAILED": "失败",
        "PENDING": "待处理",
        "TEXT_GENERATING": "正文生成中",
        "TEXT_DONE": "正文完成",
        "FACT_CHECKING": "事实校验中",
        "FACT_PASSED": "事实校验通过",
        "IMAGE_GENERATING": "图片生成中",
        "IMAGE_DONE": "图片生成完成",
        "IMAGE_VERIFYING": "图文校验中",
        "IMAGE_VERIFIED": "图文校验通过",
        "LENGTH_CHECKING": "字数检查中",
        "LENGTH_PASSED": "字数通过",
        "CONSISTENCY_CHECKING": "一致性检查中",
        "READY_FOR_LAYOUT": "待排版",
        "LAYOUTED": "已排版",
        "NODE_DONE": "节点完成",
        "NODE_FAILED": "节点失败",
        "WAITING_MANUAL": "等待人工处理",
    }
    if status is None:
        return "-"
    return mapping.get(status, status)


def render_task_tree(nodes: list[dict], indent: int = 0) -> None:
    for node in nodes:
        prefix = "  " * indent
        marker = "[生成单元]" if node.get("is_generation_unit") else ""
        st.text(f"{prefix}{node['node_id']} {node['title']} {marker}")
        children = node.get("children") or []
        if children:
            render_task_tree(children, indent + 1)


def main() -> None:
    st.set_page_config(page_title="多 Agent 文档系统 V1 骨架", layout="wide")
    st.title("多 Agent 工程实施文档系统（V1 骨架）")

    service = get_task_service()

    if "selected_task_id" not in st.session_state:
        st.session_state["selected_task_id"] = None

    st.subheader("1）新建或继续任务")
    with st.form("create_task_form"):
        title = st.text_input("任务标题", value="新建工程任务")
        create_btn = st.form_submit_button("创建任务")

    if create_btn:
        task = service.create_task(title)
        st.session_state["selected_task_id"] = task.task_id
        st.success(f"任务已创建：{task.task_id}")

    tasks = service.list_tasks()
    if tasks:
        options = [task.task_id for task in tasks]
        default_index = 0
        if st.session_state["selected_task_id"] in options:
            default_index = options.index(st.session_state["selected_task_id"])
        selected = st.selectbox(
            "选择任务",
            options=options,
            index=default_index,
            format_func=lambda tid: task_label(next(t for t in tasks if t.task_id == tid)),
        )
        st.session_state["selected_task_id"] = selected
    else:
        st.info("暂无任务。")
        return

    task_id = st.session_state["selected_task_id"]
    task = service.get_task(task_id)
    if task is None:
        st.error("所选任务不存在。")
        return

    st.caption(
        f"状态：{status_cn(task.status.value)} | 进度：{task.total_progress:.0%} | "
        f"已确认目录版本：{task.confirmed_toc_version or '-'}"
    )

    left, right = st.columns([1, 1])

    with left:
        st.subheader("2）上传 .docx")
        upload_file = st.file_uploader("上传需求文档（.docx）", type=["docx"])
        if st.button("保存上传文件", disabled=upload_file is None):
            if upload_file is None:
                st.warning("请先上传 .docx 文件。")
            else:
                try:
                    path = service.save_upload(
                        task_id=task_id,
                        file_name=upload_file.name,
                        file_content=upload_file.getvalue(),
                    )
                    st.success(f"已保存：{path}")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

        st.subheader("3）解析并生成目录")
        if st.button("执行解析与目录生成"):
            try:
                version = service.generate_toc(task_id)
                st.success(f"已生成目录版本：v{version.version_no}")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

        st.subheader("4）目录审阅")
        toc_versions = service.list_toc_versions(task_id)
        selected_version_no = None
        if toc_versions:
            selected_version_no = st.selectbox(
                "目录版本",
                options=[v.version_no for v in toc_versions],
                format_func=lambda v: f"toc_v{v}",
            )
            selected_version = next(v for v in toc_versions if v.version_no == selected_version_no)
            toc_doc = service.get_toc_document(task_id, selected_version_no)
            with st.expander("目录树", expanded=True):
                render_task_tree(toc_doc.get("tree", []), indent=0)
            with st.expander("版本差异摘要", expanded=False):
                st.json(selected_version.diff_summary_json or {})

            feedback = st.text_area(
                "目录修订意见",
                placeholder="Example: 增加一个节点，补充实施验收章节",
            )
            if st.button("提交目录意见"):
                try:
                    version = service.review_toc(task_id, feedback)
                    st.success(f"已创建 toc_v{version.version_no}")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

            if st.button("确认目录并初始化节点"):
                try:
                    count = service.confirm_toc(task_id, selected_version_no)
                    st.success(f"目录已确认，已初始化 {count} 个生成节点。")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        else:
            st.info("暂无目录版本。")

        st.subheader("5）启动 Worker")
        if st.button("启动生成任务", disabled=task.status != TaskStatus.GENERATING):
            try:
                service.start_generation(task_id)
                st.success("Worker 执行完成。")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

    with right:
        st.subheader("进度")
        latest_task = service.get_task(task_id)
        if latest_task:
            st.progress(float(latest_task.total_progress))
            st.write(
                {
                    "状态": status_cn(latest_task.status.value),
                    "当前阶段": status_cn(latest_task.current_stage),
                    "当前节点UID": latest_task.current_node_uid,
                    "完成节点数": latest_task.completed_nodes,
                    "总节点数": latest_task.total_nodes,
                    "最近错误": latest_task.latest_error,
                }
            )

        st.subheader("节点状态")
        node_states = service.get_node_states(task_id)
        if node_states:
            st.dataframe(
                [
                    {
                        "章节编号": n.node_id,
                        "节点标题": n.title,
                        "状态": status_cn(n.status.value),
                        "进度": n.progress,
                        "需人工确认": n.image_manual_required,
                        "更新时间": n.updated_at,
                    }
                    for n in node_states
                ],
                use_container_width=True,
            )
        else:
            st.info("暂无节点。")

        st.subheader("对话消息")
        messages = service.get_chat_messages(task_id)
        if messages:
            for msg in messages[-20:]:
                st.write(f"[{msg.role.value}] {msg.content}")
        else:
            st.info("暂无对话消息。")

        st.subheader("事件日志")
        logs = service.get_event_logs(task_id, limit=50)
        if logs:
            st.dataframe(
                [
                    {
                        "时间": e.created_at,
                        "阶段": status_cn(e.stage),
                        "状态": e.status.value,
                        "节点UID": e.node_uid,
                        "消息": e.message,
                    }
                    for e in logs
                ],
                use_container_width=True,
            )
        else:
            st.info("暂无日志。")

        st.subheader("输出文件")
        output_path = service.get_output_path(task_id)
        if output_path and Path(output_path).exists():
            data = Path(output_path).read_bytes()
            st.download_button(
                label="下载 output.docx",
                data=data,
                file_name="output.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        else:
            st.caption("暂无输出文件。")


if __name__ == "__main__":
    main()
