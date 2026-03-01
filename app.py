import streamlit as st
import os
import json
import time
from core.orchestrator import Orchestrator
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="工程实施方案自动生成系统", layout="wide")

@st.cache_resource
def get_orchestrator():
    return Orchestrator()

orchestrator = get_orchestrator()

# --- Helpers ---
def build_toc_markdown(toc_nodes, level=1):
    md_str = ""
    for node in toc_nodes:
        # Markdown 列表需要连贯的字符串才能正确解析缩进
        indent = "    " * (level - 1)
        
        # 优化层级标签显示
        label = "未知层级"
        if level == 1:
            label = "一级目录"
        elif level == 2:
            label = "子系统" if node.get('subsystem', True) else "二级目录"
        elif level == 3:
            label = "二级目录"
        elif level == 4:
            label = "三级目录 (执行节点)"
        else:
            label = f"Level {level}"
            
        md_str += f"{indent}- **{node.get('title')}** `({label})`\n"
        if node.get('children'):
            md_str += build_toc_markdown(node.get('children'), level + 1)
    return md_str

def main():
    st.title("Multi-Agent 工程实施方案自动生成系统")
    
    if "task_id" not in st.session_state:
        st.session_state.task_id = None

    # Sidebar for Tasks
    with st.sidebar:
        st.header("任务管理")
        uploaded_file = st.file_uploader("上传需求 Word 文档", type=["doc", "docx"])
        if st.button("新建任务并解析") and uploaded_file:
            # Save uploaded file
            os.makedirs("uploads", exist_ok=True)
            file_path = f"uploads/{uploaded_file.name}"
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
                
            task_id = orchestrator.start_new_task(file_path)
            st.session_state.task_id = task_id
            
            with st.spinner("正在解析文档..."):
                orchestrator.process_parsing(task_id)
            
            with st.spinner("正在生成初步目录..."):
                orchestrator.generate_toc(task_id)
                
            st.success("解析及目录生成完成！")
            st.rerun()

    task_id = st.session_state.task_id
    if not task_id:
        st.info("请先在左侧上传文档并创建任务。")
        return

    task = orchestrator.state_manager.get_task(task_id)
    st.write(f"**当前任务 ID:** `{task_id}` | **状态:** `{task.status}`")

    # Layout based on status
    if task.status == "TOC_REVIEW":
        st.header("第二步：目录审阅")
        latest_toc_record = orchestrator.state_manager.get_latest_toc(task_id)
        
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"当前目录版本 (v{latest_toc_record.version})")
            st.markdown(build_toc_markdown(latest_toc_record.toc_data.get("tree", [])))
            
        with col2:
            st.subheader("修改建议")
            feedback = st.text_area("输入修改意见（例如：合并XX，拆分XX，增加XX节点）")
            if st.button("提交修改"):
                with st.spinner("AI正在重新生成目录..."):
                    orchestrator.revise_toc(task_id, feedback)
                st.rerun()
                
            st.divider()
            if st.button("✅ 确认目录并开始生成内容", type="primary"):
                orchestrator.confirm_toc_and_start_generation(task_id)
                st.rerun()

    elif task.status in ["GENERATING", "LAYOUTING", "DONE"]:
        st.header("第三步：进度与状态")
        
        nodes_state = orchestrator.state_manager.get_node_states(task_id)
        total_nodes = len(nodes_state)
        completed_nodes = len([n for n in nodes_state if n.status == "TEXT_GENERATED"])
        
        progress = completed_nodes / total_nodes if total_nodes > 0 else 0
        st.progress(progress, text=f"正文生成进度: {completed_nodes}/{total_nodes}")
        
        # Action button to trigger generation (For MVP, sequential processing here)
        if task.status == "GENERATING" and completed_nodes < total_nodes:
            if st.button("开始/继续生成内容 (顺序执行)"):
                progress_placeholder = st.empty()
                for node in nodes_state:
                    if node.status != "TEXT_GENERATED":
                        progress_placeholder.info(f"正在生成节点: {node.node_id} ...")
                        orchestrator.generate_content_for_node(task_id, node.node_id)
                        time.sleep(1) # Small delay to avoid rate limits
                progress_placeholder.success("所有节点正文生成完毕！")
                st.rerun()
        
        elif task.status == "GENERATING" and completed_nodes == total_nodes:
            st.success("所有三级节点生成完毕，等待排版...")
            if st.button("进入排版导出"):
                with st.spinner("正在生成Word文档..."):
                    orchestrator.layout_document(task_id)
                st.rerun()
                
        elif task.status == "DONE":
            st.success("任务全部完成！")
            output_file = f"artifacts/final/{task_id}_output.docx"
            if os.path.exists(output_file):
                with open(output_file, "rb") as f:
                    st.download_button(
                        label="下载最终版 Word 文档",
                        data=f,
                        file_name=f"{task_id}_方案.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )

if __name__ == "__main__":
    main()
