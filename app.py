import streamlit as st
import os
import json
import time
from core.orchestrator import Orchestrator
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="工程实施方案自动生成系统 V2", layout="wide")

@st.cache_resource
def get_orchestrator(model_provider):
    return Orchestrator(model_provider=model_provider)

def build_toc_markdown(toc_nodes, level=1):
    md_str = ""
    for node in toc_nodes:
        indent = "    " * (level - 1)
        label = "未知层级"
        if level == 1: label = "一级目录"
        elif level == 2: label = "子系统" if node.get('subsystem', True) else "二级目录"
        elif level == 3: label = "二级目录"
        elif level == 4: label = "三级目录 (执行节点)"
        else: label = f"Level {level}"
        md_str += f"{indent}- **{node.get('title')}** `({label})`\n"
        if node.get('children'): md_str += build_toc_markdown(node.get('children'), level + 1)
    return md_str

def main():
    st.title("Multi-Agent 工程实施方案自动生成系统 (V2版)")
    if "task_id" not in st.session_state: st.session_state.task_id = None

    with st.sidebar:
        st.header("⚙️ 系统配置")
        env_file = ".env"
        
        # --- 文本生成 Block ---
        with st.expander("📝 文本生成配置", expanded=True):
            current_text_provider = os.getenv("TEXT_MODEL_PROVIDER", "volcengine-deepseek")
            text_provider = st.selectbox(
                "选择文本模型",
                options=["volcengine-deepseek", "deepseek-reasoner", "gemini-2.5-pro", "doubao-chat"],
                index=["volcengine-deepseek", "deepseek-reasoner", "gemini-2.5-pro", "doubao-chat"].index(current_text_provider),
                help="volcengine-deepseek 支持原生联网搜索（火山引擎版）。"
            )
            
            # 根据模型显示对应的 Key
            if text_provider == "volcengine-deepseek":
                current_key = os.getenv("ARK_API_KEY", "")
                text_key = st.text_input("ARK API Key (火山引擎)", value=current_key, type="password")
            elif text_provider == "deepseek-reasoner":
                current_key = os.getenv("DEEPSEEK_API_KEY", "")
                text_key = st.text_input("DeepSeek 官网 API Key", value=current_key, type="password")
            elif text_provider == "gemini-2.5-pro":
                current_key = os.getenv("GEMINI_API_KEY", "")
                text_key = st.text_input("Gemini API Key", value=current_key, type="password")
            else: # doubao-chat
                current_key = os.getenv("ARK_API_KEY", "")
                text_key = st.text_input("ARK API Key (豆包)", value=current_key, type="password")

        # --- 图片生成 Block ---
        with st.expander("🖼️ 图片生成配置", expanded=True):
            st.info("图片生成目前固定使用火山引擎 Doubao-Seedream 4.5 模型。")
            current_img_key = os.getenv("ARK_API_KEY", "")
            img_key = st.text_input("ARK API Key (用于图片生成)", value=current_img_key, type="password")

        if st.button("💾 保存并生效配置", type="primary"):
            try:
                from dotenv import set_key
                if not os.path.exists(env_file):
                    with open(env_file, 'w') as f: f.write("")
                
                set_key(env_file, "TEXT_MODEL_PROVIDER", text_provider)
                os.environ["TEXT_MODEL_PROVIDER"] = text_provider
                
                if text_provider in ["volcengine-deepseek", "doubao-chat"]:
                    set_key(env_file, "ARK_API_KEY", text_key)
                    os.environ["ARK_API_KEY"] = text_key
                elif text_provider == "deepseek-reasoner":
                    set_key(env_file, "DEEPSEEK_API_KEY", text_key)
                    os.environ["DEEPSEEK_API_KEY"] = text_key
                elif text_provider == "gemini-2.5-pro":
                    set_key(env_file, "GEMINI_API_KEY", text_key)
                    os.environ["GEMINI_API_KEY"] = text_key
                
                # 图片 Key 固定存为 ARK_API_KEY
                set_key(env_file, "ARK_API_KEY", img_key)
                os.environ["ARK_API_KEY"] = img_key
                
                st.cache_resource.clear()
                st.success("配置已更新！")
                st.rerun()
            except Exception as e:
                st.error(f"保存失败: {e}")

        st.divider()
        st.header("📂 任务管理")
        uploaded_file = st.file_uploader("1. 上传需求 Word 文档", type=["doc", "docx"])
        
        st.subheader("风格基准模板 (V2 双模板)")
        uploaded_t1 = st.file_uploader("2. 模板1: 实施方案范本 (Word)", type=["doc", "docx"])
        uploaded_t2 = st.file_uploader("3. 模板2: 施组技术部分 (PDF/Word)", type=["pdf", "doc", "docx"])
        
        orchestrator = get_orchestrator(text_provider)

        if st.button("🚀 新建任务并解析") and uploaded_file:
            os.makedirs("uploads", exist_ok=True)
            req_path = f"uploads/req_{uploaded_file.name}"
            with open(req_path, "wb") as f: f.write(uploaded_file.getbuffer())
            t1_path = "昆烟实施方案-目标范本.docx"
            t2_path = "太和曲靖技术部分(1).pdf"
            if uploaded_t1:
                t1_path = f"uploads/t1_{uploaded_t1.name}"
                with open(t1_path, "wb") as f: f.write(uploaded_t1.getbuffer())
            if uploaded_t2:
                t2_path = f"uploads/t2_{uploaded_t2.name}"
                with open(t2_path, "wb") as f: f.write(uploaded_t2.getbuffer())
            
            task_id = orchestrator.start_new_task(req_path)
            st.session_state.task_id = task_id
            with st.spinner("正在加载风格模板..."): orchestrator.update_templates(t1_path, t2_path)
            with st.spinner("正在解析需求文档..."): orchestrator.process_parsing(task_id)
            with st.spinner("正在生成初步目录..."): orchestrator.generate_toc(task_id)
            st.success("解析及目录生成完成！")
            st.rerun()

        st.divider()
        all_tasks = orchestrator.state_manager.get_all_tasks()
        if all_tasks:
            task_options = {t.id: f"{t.id[:8]}... ({t.status})" for t in all_tasks}
            selected_task = st.selectbox("恢复已有任务", options=list(task_options.keys()), format_func=lambda x: task_options[x])
            if st.button("恢复进度"):
                st.session_state.task_id = selected_task
                st.rerun()

    task_id = st.session_state.task_id
    if not task_id:
        st.info(f"请先在左侧配置模型并上传文档。当前文本模型: `{text_provider}`")
        return

    orchestrator = get_orchestrator(text_provider)
    task = orchestrator.state_manager.get_task(task_id)
    st.write(f"**任务 ID:** `{task_id}` | **状态:** `{task.status}` | **当前模型:** `{text_provider}`")

    if task.status == "TOC_REVIEW":
        st.header("第二步：目录审阅")
        latest_toc_record = orchestrator.state_manager.get_latest_toc(task_id)
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"当前目录版本 (v{latest_toc_record.version})")
            st.markdown(build_toc_markdown(latest_toc_record.toc_data.get("tree", [])))
        with col2:
            st.subheader("修改建议")
            feedback = st.text_area("输入修改意见")
            if st.button("提交修改"):
                with st.spinner("AI正在重新生成目录..."): orchestrator.revise_toc(task_id, feedback)
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
        st.progress(progress, text=f"生成进度: {completed_nodes}/{total_nodes}")
        
        if task.status == "GENERATING" and completed_nodes < total_nodes:
            if st.button("开始/继续生成内容"):
                progress_placeholder = st.empty()
                for node in nodes_state:
                    if node.status != "TEXT_GENERATED":
                        progress_placeholder.info(f"正在处理: {node.node_id} (使用 {text_provider})...")
                        orchestrator.generate_content_for_node(task_id, node.node_id)
                        time.sleep(1)
                progress_placeholder.success("生成完毕！")
                st.rerun()
        
        elif task.status == "GENERATING" and completed_nodes == total_nodes:
            st.success("内容已就绪。")
            if st.button("进入排版导出"):
                with st.spinner("正在生成 Word 文档..."): orchestrator.layout_document(task_id)
                st.rerun()
        elif task.status == "DONE":
            st.success("任务全部完成！")
            output_file = f"artifacts/final/{task_id}_output.docx"
            if os.path.exists(output_file):
                with open(output_file, "rb") as f:
                    st.download_button(label="下载最终版 Word 文档", data=f, file_name=f"实施方案_{task_id}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

if __name__ == "__main__": main()
