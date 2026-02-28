import os
import json
import streamlit as st
import time
import shutil
import mammoth
from datetime import datetime
from docx import Document
from src.main import DocumentGenerationOrchestrator

# 设置页面基本信息
st.set_page_config(page_title="智能工程方案生成系统 v5.0", layout="wide", page_icon="🏗️")

# 自定义风格
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; background-color: #007bff; color: white; }
    .timer-box { background: white; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b; }
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
    
    with st.expander("⚙️ 推理引擎设置", expanded=True):
        platform = st.selectbox("选择平台", ["Google Gemini", "OpenAI (ChatGPT)", "SiliconFlow 硅基流动", "DeepSeek 官方"])
        
        # 模型下拉联动
        if platform == "Google Gemini":
            gemini_mapping = {
                "Gemini 2.5 Flash": "gemini-2.5-flash",
                "Gemini 2.5 Flash Lite": "gemini-2.5-flash-lite",
                "Gemini 3 Flash": "gemini-3.0-flash",
                "Gemini 2.5 Pro": "gemini-2.5-pro"
            }
            selected_display_name = st.selectbox("选择模型", list(gemini_mapping.keys()))
            selected_model = gemini_mapping[selected_display_name]
        elif platform == "OpenAI (ChatGPT)":
            model_list = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]
            selected_model = st.selectbox("选择模型", model_list)
        elif platform == "SiliconFlow 硅基流动":
            model_list = ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen2.5-72B-Instruct"]
            selected_model = st.selectbox("选择模型", model_list)
        else:
            model_list = ["deepseek-chat", "deepseek-reasoner"]
            selected_model = st.selectbox("选择模型", model_list)
        
        api_key = st.text_input("填入 API Key", value=saved_settings.get("llm_key", ""), type="password")
        
        if st.button("💾 记忆配置"):
            with open(CONFIG_FILE, "w") as f:
                json.dump({"platform": platform, "llm_model": selected_model, "llm_key": api_key}, f)
            st.success("配置已保存")

    # 自动注入环境变量
    if api_key:
        os.environ["LLM_API_KEY"] = api_key
        # 如果是 SiliconFlow，内部 LLMClient 会自动处理 URL，这里无需手动输入

    st.divider()
    st.subheader("📜 历史生成记录")
    history_files = sorted(os.listdir(HISTORY_DIR), reverse=True)
    for f in history_files[:5]:
        with open(os.path.join(HISTORY_DIR, f), "rb") as file:
            st.download_button(f"📥 {f}", file, file_name=f, key=f)

# --- 主界面 ---
st.title("🏗️ 智能工程实施方案生成系统")
st.caption("Gemini 3 旗舰驱动 | 配置自动记忆 | A4 仿真预览")

# 核心功能区域
tab_gen, tab_pre = st.tabs(["🚀 生产流水线", "📄 Word 排版预览"])

with tab_gen:
    # 存盘点检查
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f: cache_data = json.load(f)
            if cache_data.get("subsystem_details"):
                st.info(f"💾 检测到存盘点：已处理完 {len(cache_data['subsystem_details'])} 个子系统。")
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
            with col_t2:
                timer_c = st.empty()

            st.markdown("### 🛠️ 当前执行状态")
            with st.status("🚀 正在调度 Agent 流水线...", expanded=True) as status:
                # 显示已完成记录
                if cache_data.get("subsystem_details"):
                    st.write("💾 **已恢复历史进度:**")
                    for sub in cache_data["subsystem_details"]:
                        st.write(f"✅ 子系统: `{sub['name']}` (已完成)")
                    st.divider()

                current_task = st.empty()
                sub_p = st.progress(0)
                sub_text = st.empty()
                
                try:
                    start_time = time.time()
                    
                    # 1. 解析与规划
                    if not cache_data.get("project_info"):
                        current_task.markdown("🏗️ **正在解析需求文档...**")
                        project_reqs = orchestrator.requirement_parser.run(temp_path)
                        cache_data["project_info"] = project_reqs
                    else: project_reqs = cache_data["project_info"]
                    total_p.progress(5)

                    if not cache_data.get("master_gantt"):
                        current_task.markdown("🏗️ **正在规划总体进度...**")
                        master_gantt = orchestrator.master_gantt_agent.run(project_reqs)
                        cache_data["master_gantt"] = master_gantt
                    else: master_gantt = cache_data["master_gantt"]
                    total_p.progress(10)

                    subsystems = safe_get_list(project_reqs, "subsystems")
                    total_subs = len(subsystems)
                    
                    # 3. 核心循环 (RPD 优化版)
                    for s_idx, sub_name in enumerate(subsystems):
                        if any(s['name'] == sub_name for s in cache_data["subsystem_details"]):
                            continue
                        
                        st.write(f"📂 **处理子系统: {sub_name}**")
                        sub_gantt = orchestrator.subsystem_gantt_agent.run(master_gantt, sub_name)
                        sub_plans = orchestrator.plan_generator_agent.run(sub_gantt)
                        plans_list = safe_get_list(sub_plans, "plans")
                        
                        sub_data = {"name": sub_name, "plans": []}
                        for p_idx, plan in enumerate(plans_list):
                            plan_title = plan.get("title", "阶段")
                            sub_pct = int((p_idx / len(plans_list)) * 100)
                            sub_p.progress(sub_pct)
                            sub_text.markdown(f"🔸 当前子系统进度: `{sub_pct}%` | 处理阶段: `{plan_title}`")
                            
                            # 计算预计剩余时间
                            current_step = len(cache_data["subsystem_details"]) * 5 + p_idx + 1
                            elapsed = time.time() - start_time
                            rem_sec = int(((total_subs * 5) - current_step) * (elapsed / max(current_step, 1)))
                            if rem_sec > 0:
                                timer_c.markdown(f'<div class="timer-box"><small>预计剩余</small><br><b>{rem_sec//60}分 {rem_sec%60}秒</b></div>', unsafe_allow_html=True)
                            
                            granular_pct = 10 + int(((s_idx + (sub_pct/100)) / total_subs) * 85)
                            total_p.progress(min(granular_pct, 95))
                            total_text.markdown(f"总进度: **{granular_pct}%**")

                            # 核心改进：调用集成 Agent 一次性生成整章内容 (省 RPD)
                            current_task.markdown(f"🏗️ **批量生成计划章节:** `{plan_title}`")
                            # 从 PlanGenerator 拿到的 contents 列表
                            actions = plan.get("contents", [])
                            integrated_text = orchestrator.integrated_content_agent.run(plan_title, actions)
                            
                            # 解析并处理配图
                            image_configs = orchestrator.integrated_content_agent.parse_images(integrated_text)
                            final_images = []
                            for img_cfg in image_configs:
                                st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;🎨 正在生图: `{img_cfg.get('caption')}`")
                                img_path = orchestrator.diagram_generator_agent.llm.generate_image(
                                    img_cfg.get("prompt"), 
                                    f"data/images/img_{os.urandom(4).hex()}.png"
                                )
                                img_cfg["source"] = img_path
                                final_images.append(img_cfg)

                            sub_data["plans"].append({
                                "plan_title": plan_title,
                                "full_text": integrated_text,
                                "images": final_images
                            })
                            st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;✅ `{plan_title}` 编写与配图完成")
                        
                        cache_data["subsystem_details"].append(sub_data)
                        with open(CACHE_FILE, "w") as f: json.dump(cache_data, f, ensure_ascii=False)
                        orchestrator.word_exporter_agent.run(cache_data, output_path="outputs/preview_temp.docx")

                    total_p.progress(100)
                    total_text.markdown("✨ **全部生成任务已完成！**")
                    timer_c.empty()
                    status.update(label="✅ 任务圆满成功！", state="complete", expanded=False)
                    st.balloons()
                    
                    final_docx = orchestrator.word_exporter_agent.run(cache_data)
                    ts = datetime.now().strftime("%m%d_%H%M")
                    hist_path = os.path.join(HISTORY_DIR, f"方案_{ts}.docx")
                    shutil.copy(final_docx, hist_path)
                    
                    with open(hist_path, "rb") as f:
                        st.download_button("📥 立即下载最终 Word 方案", f, file_name=f"方案_{ts}.docx")

                except Exception as e:
                    st.error(f"❌ 运行错误: {str(e)}")
                    status.update(label="❌ 运行中断", state="error")

with tab_pre:
    st.subheader("🖼️ A4 排版效果实时预览")
    if os.path.exists("outputs/preview_temp.docx"):
        with open("outputs/preview_temp.docx", "rb") as docx_file:
            html = mammoth.convert_to_html(docx_file).value
        st.markdown(f'<div class="word-preview-container">{html}</div>', unsafe_allow_html=True)
    else:
        st.info("💡 任务启动后，此处将实时展示排版效果。")
