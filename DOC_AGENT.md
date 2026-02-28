# 智能工程实施方案生成系统 - DOC_AGENT 配置

## 系统概览

本系统为多 Agent 自动化文档生成平台，核心技术栈已切换为国产化方案（DeepSeek + 豆包），无需 VPN：

- **解析与逻辑引擎**：DeepSeek-V3 / DeepSeek-R1 (负责解析、规划与写作)
- **绘图生成引擎**：豆包 (ArtArk) - 字节跳动 (负责流程图、架构图、施工照片生成)
- **排版引擎**：Python-Docx (负责生成专业 Word 文档)

生成逻辑：

```text
需求解析 (DeepSeek)
↓
总体/子系统进度 (DeepSeek)
↓
动作拆解 (DeepSeek)
↓
技术细化 (DeepSeek - 1800字/动作)
↓
豆包生图 (ByteDance Ark - 强关联图)
↓
图文校核 (DeepSeek)
↓
专业 Word 导出
```

---

## Agents 详细配置

### 核心模型参数
- **DeepSeek Base URL**: `https://api.deepseek.com`
- **豆包 (Ark) Base URL**: `https://ark.cn-beijing.volces.com/api/v3`

### 1. 技术细化 Agent (DeepSeek)
要求：字数充足，包含技术参数、质量控制措施。

### 2. 图像生成 Agent (豆包)
要求：生成高清流程图、原理图或施工现场模拟图。
