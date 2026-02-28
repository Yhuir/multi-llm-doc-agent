import os
import json
import streamlit as st
import time
import shutil
import mammoth
from datetime import datetime
from docx import Document
from src.main import DocumentGenerationOrchestrator
from src.utils.mermaid_renderer import render_mermaid_to_png # 新增导入

# 设置页面基本信息
st.set_page_config(page_title="智能工程方案生成系统 v5.5", layout="wide", page_icon="🏗️")

# 自定义风格
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; background-color: #007bff; color: white; }
    .timer-box { background: white; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b; }
    .word-preview-container {
        background-color: white; width: 210mm; padding: 20mm; margin: 20px auto; 
        box-shadow: 0 0 10px rgba(0,0,0,0.1); font-family: 'SimSun', serif;
    }
    </style>
""", unsafe_allow_html=True)

# --- 路径初始化 ---
CONFIG_FILE = "outputs/settings_config.json"
HISTORY_DIR = "outputs/history"
CACHE_FILE = "outputs/generation_cache.json"
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs("outputs", exist_ok=True)

def safe_get_list(data, key):
    if isinstance(data, list): return data
    if isinstance(data, dict): return data.get(key, [])
    return []

def load_settings():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

saved_settings = load_settings()

# --- 侧边栏 ---
with st.sidebar:
    st.title("📂 方案管理中心")
    with st.expander("⚙️ 引擎设置", expanded=True):
        platform = st.selectbox("选择平台", ["Google Gemini", "SiliconFlow 硅基流动", "DeepSeek 官方"])
        if platform == "Google Gemini": model_list = ["gemini-3.1-pro-preview", "gemini-3-flash-preview"]
        elif platform == "SiliconFlow 硅基流动": model_list = ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1"]
        else: model_list = ["deepseek-chat"]
        selected_model = st.selectbox("选择模型", model_list)
        api_key = st.text_input("API Key", value=saved_settings.get("llm_key", ""), type="password")
        if st.button("💾 记忆配置"):
            with open(CONFIG_FILE, "w") as f: json.dump({"platform": platform, "llm_model": selected_model, "llm_key": api_key}, f)
            st.success("已保存")

    if api_key: os.environ["LLM_API_KEY"] = api_key

# --- 主界面 ---
st.title("🏗️ 智能工程实施方案生成系统")
st.caption("Mermaid 自动化截图进 Word | 仿真排版预览 | 归档管理")

tab_gen, tab_pre = st.tabs(["🚀 生产流水线", "📄 Word 排版预览"])

with tab_gen:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f: cache_data = json.load(f)
        except: cache_data = {"subsystem_details": []}
    else: cache_data = {"subsystem_details": []}

    uploaded_file = st.file_uploader("📂 上传项目技术要求", type=["doc", "docx"])

    if uploaded_file and api_key:
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        temp_path = os.path.join("data", f"uploaded_req{ext}")
        with open(temp_path, "wb") as f: f.write(uploaded_file.getbuffer())
        
        if st.button("🏁 开始执行自动化生成任务"):
            orchestrator = DocumentGenerationOrchestrator()
            for attr in dir(orchestrator):
                agent = getattr(orchestrator, attr)
                if hasattr(agent, "llm"):
                    from src.utils.llm_client import LLMClient
                    agent.llm = LLMClient(model=selected_model)
            
            st.divider()
            col_t1, col_t2 = st.columns([2, 1])
            with col_t1:
                st.markdown("### 📊 项目总进度")
                total_p = st.progress(0)
                total_text = st.empty()
            with col_t2: timer_c = st.empty()

            with st.status("🚀 正在调度 Agent 流水线...", expanded=True) as status:
                current_task = st.empty()
                sub_p = st.progress(0)
                sub_text = st.empty()
                try:
                    start_time = time.time()
                    
                    # 1. 需求解析
                    if not cache_data.get("project_info"):
                        current_task.markdown("🏗️ **正在解析需求文档...**")
                        cache_data["project_info"] = orchestrator.requirement_parser.run(temp_path)
                    total_p.progress(5)

                    # 2. 总体规划 + Mermaid 截图渲染
                    if not cache_data.get("master_gantt"):
                        current_task.markdown("🏗️ **正在规划总体进度并生成甘特图...**")
                        mg = orchestrator.master_gantt_agent.run(cache_data["project_info"])
                        cache_data["master_gantt"] = mg
                        # 渲染 Mermaid 为图片
                        if mg.get("mermaid_code"):
                            img_path = render_mermaid_to_png(mg["mermaid_code"])
                            cache_data["master_gantt_img"] = img_path
                    total_p.progress(10)

                    subsystems = safe_get_list(cache_data["project_info"], "subsystems")
                    for s_idx, sub_name in enumerate(subsystems):
                        if any(s['name'] == sub_name for s in cache_data["subsystem_details"]): continue
                        
                        st.write(f"📂 **处理子系统: {sub_name}**")
                        # 生成子系统甘特图 + 截图
                        sg = orchestrator.subsystem_gantt_agent.run(cache_data["master_gantt"], sub_name)
                        sg_img = render_mermaid_to_png(sg.get("mermaid_code", ""))
                        
                        sub_plans = orchestrator.plan_generator_agent.run(sg)
                        plans_list = safe_get_list(sub_plans, "plans")
                        
                        sub_data = {"name": sub_name, "plans": [], "subsystem_gantt_img": sg_img}
                        for p_idx, plan in enumerate(plans_list):
                            sub_pct = int((p_idx / len(plans_list)) * 100)
                            sub_p.progress(sub_pct)
                            sub_text.markdown(f"🔸 子系统进度: `{sub_pct}%` | 处理: `{plan.get('title')}`")
                            
                            contents_json = orchestrator.content_generator_agent.run(plan)
                            contents_list = safe_get_list(contents_json, "contents")
                            plan_data = {"plan_title": plan.get("title", "阶段"), "contents": []}
                            for content in contents_list:
                                current_task.markdown(f"🏗️ **正在生成章节:** `{content.get('title')}`")
                                detail_text = orchestrator.technical_detail_agent.run(content)
                                refined_text = orchestrator.length_controller_agent.run(detail_text)
                                plan_data["contents"].append({"title": content.get("title"), "text": refined_text, "images": []})
                            sub_data["plans"].append(plan_data)
                        
                        cache_data["subsystem_details"].append(sub_data)
                        with open(CACHE_FILE, "w") as f: json.dump(cache_data, f, ensure_ascii=False)
                        orchestrator.word_exporter_agent.run(cache_data, output_path="outputs/preview_temp.docx")

                    total_p.progress(100)
                    final_docx = orchestrator.word_exporter_agent.run(cache_data)
                    ts = datetime.now().strftime("%m%d_%H%M")
                    hist_path = os.path.join(HISTORY_DIR, f"方案_{ts}.docx")
                    shutil.copy(final_docx, hist_path)

                    
                    status.update(label="✅ 任务圆满成功！", state="complete")
                    st.balloons()
                    with open(hist_path, "rb") as f:
                        st.download_button("📥 下载完整最终 Word 方案", f, file_name=f"方案_{ts}.docx")

                except Exception as e:
                    st.error(f"❌ 运行错误: {str(e)}")

with tab_pre:
    st.subheader("🖼️ Word 排版效果实时预览")
    if os.path.exists("outputs/preview_temp.docx"):
        with open("outputs/preview_temp.docx", "rb") as docx_file:
            html = mammoth.convert_to_html(docx_file).value
        st.markdown(f'<div class="word-preview-container">{html}</div>', unsafe_allow_html=True)
