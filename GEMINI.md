# 智能工程方案生成系统 (2026 旗舰版)

## 技术架构
本系统基于多 Agent 协作模式，适配 2026 最新旗舰模型：

- **核心逻辑/写作**：DeepSeek-V3 / Gemini 3.1 Pro (2M Context)
- **工程绘图**：字节跳动豆包 (ArtArk) / Mermaid Cloud Render
- **排版引擎**：Python-Docx + Mammoth (仿真预览)

## Agents 规范同步
1. **Requirement Parser**: 必须支持 .doc/.docx 混合解析，利用 Gemini 3.1 的长文本能力。
2. **Technical Detail**: 每章节目标字数 1800+，结构严谨。
3. **Diagram Agent**: 调用豆包 API 生成 4K 高清工程原理图。
4. **Mermaid Renderer**: 将甘特图代码自动截图并插入 Word 关键章节。

## 运行环境
- **网络**：支持 macOS 系统级 VPN (QX Tunnel 模式)，代码层零代理。
- **存储**：全流程 JSON 缓存，支持断点续传。
