# Multi-Agent 工程实施方案自动生成系统（PRD/技术规格合一）


---

## 0. 背景与目标

### 0.1 背景
用户上传项目技术要求 Word（.doc/.docx），系统自动解析并生成“结构目录（可审阅）”，支持用户在类似 ChatGPT 的交互窗口中多轮修改确认目录；目录确认后，系统按“三级目录节点”（或者四级）为最小单元生成工程级实施内容（每节点约 2 页 A4）、自动生成 2–3 张强关联配图（使用豆包生成图片）、自动校验图文一致性与字数达标，最后自动排版输出可下载 Word 成品文档。

### 0.2 建设目标（可验收）
1）全文解析用户上传的项目技术要求 Word 文档（doc/docx）
2）基于全文解析结果自动生成结构目录树（仅展示给用户，不生成正文）
3）UI提供 AI 交互窗口：目录树发给用户审阅；用户提出修改建议后自动生成新版本目录树；循环直到用户明确发出“开始生成内容”的指令， 所有版本目录树都可回滚/对比差异
4）按确认后的目录树逐级生成内容（以“三级目录节点” （或者四级）为最小生成单元）
5）每个最小生成单元节点正文：字数1800-2000；
6）每个最小生成单元节点生成强关联配图2–3张（豆包出图）
7）图文一致性校验：不达标自动重生成图片（必要时重写prompt）
8）字数校验：不达标自动补写直至达标
9）word排版沿用standard_template.docx的样式， 包括一级、二级、三级标题，禁止Markdown语法，表格沿用BiddingTable样式
10）输出docx（可选另存doc），用户可下载
11）React UI 实时显示总进度百分比、安装目录树显示已完成与进行中的目录节点，并实时刷新
12）支持断点续跑：任何中断后保留进度，重启App后可继续

---

## 1. 产品范围（Scope）

### 1.1 In Scope
- Word 超长文档全文解析（doc/docx）
- 目录树生成、交互式修订、版本管理
- 以最小生成单元为单位的内容生成（工程实施文档风格）
- 每个最小生成单元2–3张图片生成（豆包）
- 图文一致性校验与重试
- 字数控制与补写
- Word 输出，含表格、图片、图题、标题样式、分页
- React 可视化进度与状态
- 断点续跑（Checkpoint/Resume）



---

## 2. 用户流程（User Journey）

A 用户新建任务或者继续上次未完成任务
B. 上传 Word（doc/docx）
C. 用户可以在AI交互窗口提出目录生成意见
D. 系统解析全文 → 生成目录树 v1 → UI 展示  
E. 用户在AI交互窗口提出修改 → 系统生成目录树 v2/v3…（可回滚/对比差异）  
F. 用户点击下方button“确认目录/开始生成内容”  
G. 系统按目录树逐个最小生成单元执行：生成正文 → 生成图片 → 图文一致性校验（不通过重试）→ 字数校验（不达标补写）→ 进入排版队列  
H. 全部完成 → 输出 Word 成品 → 下载

硬约束：未收到用户“开始生成内容”指令前，禁止进入正文生成。

用户在UI界面可以选择使用的文本生成大模型 （gemini， deepseek）， 以及图片生成大模型（豆包或其他），并且输入api key并可以点击保存， 下次使用时默认使用上次保存的模型和key。

---

## 3. 系统总体架构

### 3.1 模块/Agent 列表
Central Orchestrator（编排器）
- Requirement Parser Agent（解析）
- TOC Generator Agent（目录树生成）
- TOC Review Chat Agent（交互修订/版本）
- Section Writer Agent（按最小生成单元生成正文）
- Entity Extractor Agent（从正文抽取关键实体）
- Image Prompt Agent（生成豆包Prompt）
- Doubao Image Agent（豆包出图）
- Image-Text Relevance Agent（图文一致性校验）
- Length Control Agent（字数控制/补写）
- Consistency Check Agent（前后一致性：型号/名称/节点引用等）
- Layout Agent（Word排版：样式/表格/图片/分页）
- Word Export Agent（导出与下载）
- Progress & State Agent（进度/状态/日志/断点续跑）

### 3.2 技术栈建议
- UI：React
- Agent 编排： LangChain 
- Word：不了解
- 向量检索（可选）：
- 任务队列（可选）：
- 持久化：
- 图片：豆包文生图接口（由 Doubao Image Agent 调用）
- 大模型：

---

## 4. 断点续跑设计（强制）

### 4.1 设计目标
- 任何步骤中断（进程退出、电脑重启、网络异常）后，已完成的节点不重复生成
- 重启 App 后可选择“继续上次任务”或“新建任务”
- 同一任务可多次暂停/恢复

### 4.2 Checkpoint 策略
- 以“三级目录节点” (或者四级)为最小可恢复单元
- 每个节点有阶段状态机（见第5章），每完成一个阶段写入 checkpoint
- 每次写入包括：输入快照、输出工件路径、指标（字数/一致性分数）、错误与重试计数、耗时

### 4.3 持久化存储
- SQLite：task、toc_version、node_state、event_log
- 文件系统工件目录：artifacts/{task_id}/...
  - parsed/requirement.json
  - toc/toc_v1.json、toc_v2.json...
  - nodes/{node_id}/text.json、tables.json、images/*.png、metrics.json
  - final/output.docx

### 4.4 恢复逻辑
- App 启动：读取 SQLite 中最新未完成 task（status=RUNNING/PAUSED/FAILED）
- 用户选择继续后：
  - 对每个 node_id，按状态机找到“下一步待执行阶段”
  - 已完成阶段直接跳过；进行中阶段根据 last_heartbeat 判断是否需要回滚并重试
- 重试上限与人工介入点见第8章
- 用户点击上次未完成的任务后，UI自动加载该任务的所有生成的目录树版本，以及AI交互窗口的历史对话记录（如果有），以便用户回顾之前的修改意见和系统反馈。用户可以选择回滚到任一目录版本，或者在当前版本基础上继续修改， 并生成新版本目录树，直到确认目录开始生成内容。
---

## 5. 流程状态机（State Machine）

### 5.1 Task 状态
- NEW：创建任务，未解析
- PARSED：解析完成
- TOC_REVIEW：目录审阅中（可能多版本）
- GENERATING：正文生成中
- LAYOUTING：排版中
- EXPORTING：导出中
- DONE：完成
- PAUSED：用户暂停或系统中断可恢复
- FAILED：不可恢复失败（需人工处理或重新开始）

### 5.2 Node（三级目录节点）状态



---

## 6. 数据结构（JSON Schema）

说明：以下为示例结构；实际落地可用 Pydantic 校验。

### 6.1 requirement.json（解析结果）
{
  "project": {
    "name": "项目名称",
    "customer": "可选",
    "location": "可选",
    "duration_days": 90,
    "milestones": [
      {"name": "开工", "date": "2026-03-10"},
      {"name": "初验", "date": "2026-05-20"}
    ]
  },
  "scope": {
    "overview": "建设范围概述",
    "subsystems": [
      {
        "name": "子系统A",
        "description": "子系统范围",
        "requirements": [
          {"type": "tech_metric", "key": "带宽", "value": "10Gbps", "source_ref": "p3#L12"},
          {"type": "mandatory_clause", "text": "必须符合XXX标准", "source_ref": "p5#L8"}
        ],
        "interfaces": ["子系统B"]
      }
    ]
  },
  "constraints": {
    "standards": ["GBxxxx", "ISOxxxx"],
    "acceptance": ["验收条款摘要..."]
  },
  "source_index": {
    "p3#L12": {"page": 3, "paragraph_id": "para_45", "text": "原文片段..."}
  }
}

### 6.2 toc_vN.json（目录树）
{
  "version": 3,
  "generated_at": "2026-03-01T10:00:00",
  "tree": [
    {
      "node_id": "L1-001",
      "level": 1,
      "title": "总体实施方案",
      "children": [
        {
          "node_id": "SS-001",
          "level": 1,
          "subsystem": true,
          "title": "子系统A",
          "children": [
            {"node_id": "L2-SS001-001", "level": 2, "title": "施工准备", "children": [
              {"node_id": "L3-SS001-001-001", "level": 3, "title": "现场勘察与放样", "constraints": {"min_words": 1800, "images": [2,3]}, "source_refs": ["p2#L1"]}
            ]}
          ]
        }
      ]
    }
  ]
}

### 6.3 node_text.json（三级或四级目录正文结构化）

重要说明：
- **sections 中的小节标题不得固定**。
- 系统必须根据用户上传的技术要求文档、TOC上下文以及 Style Extractor 的风格分析结果 **动态生成小节结构**。


动态生成规则：
- 小节标题必须依据 toc 上下文自动生成。
- 若文档涉及设备清单、接口点位、测试用例、参数矩阵等结构化信息：**需要自行判断是否真的适合表格**（避免“为了形式堆表格”）。
  - 仅当信息可形成“结构化清单/矩阵”，且满足其一时才使用表格：>=3 行数据（不含表头）或 >=4 列，或明显是 2x2 以上参数矩阵。
  - 仅有 1-2 条条目、概念性描述、或施工流程叙述时，不要用表格；用正文段落表达即可。
  - 每个最小生成节点表格数量建议 <=2，除非确有大量结构化数据且能显著提升可读性。



### 6.5 images.json（图片工件与绑定）
{
  "images": [
    {
      "image_id": "img_001",
      "type": "topology",
      "file": "images/img_001.png",
      "caption": "图3-1 星型拓扑与交换机连接关系",
      "bound_to": {"section": "技术控制要点", "anchor": "星型拓扑"},
      "prompt": "必须包含：交换机、终端A/B/C、星型连接、端口标注..."
    }
  ]
}

### 6.6 metrics.json


---

## 7. Agent 输入输出规范（I/O Contract）

### 7.1 Requirement Parser Agent
输入：upload_file_path（doc/docx）
输出：
- requirement.json
- parse_report（缺失项/疑似错误/页码索引）

失败处理：
- doc：先转docx；转失败则任务FAILED并提示用户

### 7.2 TOC Generator Agent
输入：requirement.json
输出：toc_vN.json（目录树）
要求：
- 覆盖所有子系统
- 至少生成到三级目录，必要时四级/五级
- 每个最小生成节点必须满足可独立生成约2页内容的粒度

### 7.3 TOC Review Chat Agent
输入：
- toc_vN.json
- user_feedback（自然语言）
输出：
- toc_vN+1.json
- diff_summary（新增/删除/改名/调整层级/排序）

硬约束：用户未确认目录前不得触发正文生成。

### 7.4 Section Writer Agent（Gemini）
输入：
- toc_confirmed.json
- node_id（level=3）
- requirement.json（相关子系统与条款引用）
- 模板参考： 昆烟实施方案-目标范本.doc + 太和曲靖技术部分(1).pdf（风格学习，禁止照搬内容）
输出：
- node_text.json
要求：
- 禁止Markdown语法
- 工程实施风格：可执行、可验收、可落地
- 关键重难点必须提供1段，后续由Layout设置红色加粗

### 7.5 Entity Extractor Agent


### 7.6 Image Prompt Agent
输入：entities.json + node_text.json
输出：image_prompts.json（2–3条）
要求：每条prompt必须包含“必须出现元素”与“禁止泛化”约束

### 7.7 Doubao Image Agent
输入：image_prompts.json
输出：images/*.png + images.json

### 7.8 Image-Text Relevance Agent（强制）
输入：node_text.json + images.json + entities.json
输出：
- image_text_scores（每图分数、缺失元素列表）
- pass/fail
失败处理：
- fail → 调整prompt并重生成图片（

### 7.9 Length Control Agent（强制）
输入：node_text.json
输出：
- updated_node_text.json（补写后）
- word_count
失败处理：
- <1800 → 触发补写策略；达到上限仍不足 → NODE_FAILED（需人工）

### 7.10 Layout Agent


### 7.11 Word Export Agent
输入：已排版主doc对象/文件
输出：final/output.docx（可下载）

### 7.12 Progress & State Agent
输入：所有阶段事件
输出：UI实时进度、节点状态、日志、SQLite状态更新

---

## 8. 阈值、重试与失败策略（强制）

### 8.1 图文一致性阈值
- image_text_score 阈值：>= 0.75 通过（可配置）
- 必须出现元素缺失任意1项：直接判定不通过（即使分数高）

### 8.2 图像重试策略
- 单张图片最大重试次数：3 次
- 仍失败：标记该节点“需人工确认图片”，但节点可继续排版（可配置：严格模式下直接NODE_FAILED）

### 8.3 字数阈值
- 节点总字数 >= 1800 强制通过
- 推荐范围 2000–2200（不强制）

### 8.4 字数补写策略（按优先级）
1）补充验收标准与测试步骤（含记录表字段）
2）补充参数与工艺控制（线径/扭矩/弯曲半径/测试阈值等）
3）补充规范条款引用与落地解释
4）补充风险矩阵与应对
5）补充施工记录、旁站、照片留存要求

补写最大轮次：2轮；仍不足 → NODE_FAILED（提示人工补写或放宽阈值）

### 8.5 一致性检查
- 型号/设备名/数量前后不一致：触发自动修复（优先引用 requirement.json）
- 修复失败：节点标记“需人工确认”

---

## 9. Word 排版与格式规范（禁止Markdown进入Word）

### 9.1 样式
直接使用 `standard_template.docx` 中的样式定义，禁止在生成内容中插入任何 Markdown 语法（例如 #、-、*、| 等）。
样式： 一级标题、二级标题、三级标题、正文、表格（BiddingTable）等必须沿用模板定义，禁止自定义样式或直接设置字体/段落格式。

### 9.2 图片
- 学习模板中图片的排版风格（宽度、居中、图题位置与格式），但图片内容必须根据生成结果动态生成，禁止使用模板中的图片或图题。

### 9.3 分页
- 每个最小生成节点建议 2 页左右
- 若图片导致跨页严重：在图片前插入分页符（可配置）
- 节点结束后可选插入分页符（按版式需求）

---

## 10. React UI 模块设计

### 10.1 页面结构
1）新建任务区
- 新建任务/继续任务
- 当前任务信息（task_id、状态、开始时间）

2）系统配置区
- 文本生成模型选择（gemini、deepseek）
- 图片生成模型选择（豆包或其他）
- API Key 输入与保存

3）文件上传区
- 上传 Word（doc/docx）

2）目录审阅区（TOC Review）
- 展示目录树（可折叠）
- 切换历史版本目录

3）AI交互区
- 展示用户与系统的对话历史
- 按钮：
  - 开始生成目录 （系统会基于上传的文件以及用户在AI交互区的意见生成目录树v1）
  - 提交目录意见 （未生成目录时也可以提交意见，系统会基于上传的文件以及意见生成目录）
  - 确认目录/开始生成内容 （仅当用户点击后才进入正文生成阶段， 而且目录未生成时禁用改按钮）

3）进度区
- 总进度百分比
- 显示整个目录树，已完成节点打勾，进行中节点高亮， 未开始节点灰色， 用户可点击节点查看该节点的生成日志与指标（字数、图文一致性分数、重试次数等）

4）实时日志区
- 显示当前正在执行的节点与阶段
- 展示最近N条事件日志与错误信息

5）成果区
- 完成后显示下载按钮：output.docx
- 可选：下载生成报告（metrics/log）

### 10.2 进度计算（建议）


---

## 11. 部署与跨平台（Win/Mac）

### 11.1 是否需要 Docker？
结论：建议提供两种方式（都支持 Win/Mac）
A）非Docker（推荐给本地轻量使用）
- Python venv/conda 安装依赖
- 适合：个人电脑快速运行、调试方便、对Docker不熟用户

B）Docker（推荐给交付/团队/稳定环境）
- 统一依赖、减少“在我电脑能跑”的问题
- Win/Mac均可运行（需要安装 Docker Desktop）
- 适合：团队共享、CI/CD、部署到服务器

建议策略：
- 开发阶段：非Docker优先
- 交付/集成：提供Docker镜像与docker-compose



---


---

## 13.  生成规范（用于 Section Writer Agent）





---

## 16. V2 阶段新增特性与开发规范

### 16.1 豆包生成图片功能（并写入 Word）
**新增能力**
- 每个三级目录节点：生成 2–3 张“强关联配图”，并自动插入到最终 Word 对应位置（与段落强绑定）。
- 每张图必须包含：
  - `image_id`
  - `prompt`
  - `must_have_elements`（必须出现元素清单）
  - `caption`（图题）
  - `bind_anchor`（绑定到正文的段落锚点/小节名/关键句）

**工作流要求**
- **Entity Extractor**：从 `node_text.json` 抽取图片必须出现元素（设备/拓扑/工艺步骤/关键参数/验收点等）
- **Image Prompt Agent**：生成 2–3 条豆包 prompt
  - prompt 必须显式写出“必须出现元素”和“禁止泛化/禁止省略”的约束
- **Doubao Image Agent**：调用豆包文生图接口生成图片（PNG/JPG）
- **Image-Text Relevance Agent**：对图片与正文的一致性评分与缺失元素检查
  - 评分阈值默认 >=0.75
  - 缺失任一必须元素：直接 fail
  - fail 则自动重写 prompt 并重试（单图最多 3 次）
- **Layout Agent**：将图片插入 Word


**工件约定（新增/强化）**
- `artifacts/{task_id}/nodes/{node_id}/images/*.png`
- `artifacts/{task_id}/nodes/{node_id}/images.json`（包含 prompt、caption、绑定信息、重试次数）
- `artifacts/{task_id}/nodes/{node_id}/metrics.json`（包含 image_text_score）

### 16.2 生成内容字数约束：1800–2000 字（强制）
**硬约束**
- 每个三级目录节点最终正文总字数必须在 **1800–2000**（以中文字符计数可采用“中文字符数+英文单词折算”或直接按模型输出字数计数，落地需统一口径）。
- 若初稿不足：触发补写；若超出：触发精简（优先删减空泛描述、重复描述，保留参数/验收/步骤/风险等硬信息）。

**实现要求**
- **Section Writer Agent**：初稿生成目标范围设为 1850–1950，给补写/精简留缓冲。
- **Length Control Agent**：
  - `<1800`：按补写优先级补写（验收步骤→参数控制→规范条款落地→风险矩阵→记录表/旁站/留痕）
  - `>2000`：按“去冗余”策略精简（不删除关键流程、控制点、验收点、表格字段）
  - 最大补写轮次：2；仍不达标则 `NODE_FAILED`（或进入人工模式）

### 16.3 新增双模板参考（风格依据，禁止照搬内容与目录）
**模板参考 1**
- `昆烟实施方案-目标范本.docx`
- **用途**：

**模板参考 2**
- `太和曲靖技术部分(1).pdf`
- **用途**：

**强制约束（必须写进提示词与校验）**
- 只能“学习结构与写法”，不得照搬原文句子、不得复用模板目录标题。
- 目录名称必须以“用户上传技术要求 Word 的解析结果”为准，模板仅用于风格对齐。
- 输出不得包含 Markdown（包括但不限于 #、-、*、| 等）。



**语气与句式**
- 工业级严谨表达
- 客观叙述
- 常见句式：被动语态、祈使句
- 避免口语化表达

**结构偏好**
- 识别文档中常见逻辑层级


生成 Agent 在构造 sections 时必须遵循这些结构模式。

**表格触发机制**
。

---

## 2.2 输出内容排序规范

生成系统必须严格遵循目录层级逻辑。

要求：

**内容逻辑顺序**
- 所有正文必须位于其对应目录标题下方。
- 不允许正文漂移到其他章节。

**遍历一致性**
目录遍历必须严格按顺序：

示例正确：

1.1.1
1.1.2
1.1.3
1.2

示例错误：

1.1.2
1.1.1.11

系统必须在生成阶段进行编号校验，防止层级倒挂。

---

## 5.1 模板调用规范

系统排版必须基于 `standard_template.docx`。

该模板已经预置：

- 字体
- 颜色
- 标题层级
- 表格样式

Layout Agent **严禁硬编码样式**。

必须直接调用模板样式：

Heading 1
Heading 2
Heading 3
Heading 4
Normal

表格样式必须调用：

BiddingTable

该规则确保 Word 输出在不同环境中保持一致。

---

## 5.2 图片排版矩阵（V3）

当一个节点存在多张同类型图片时，Layout Agent 必须使用 **矩阵布局**。

实现方式：

- 使用无边框 Word 表格作为容器
- 自动排布图片

优先布局：

2 × 4

或

4 × 2

（最大支持 8 张图片）

规则：

- 单图：正常图题
- 多图矩阵：仅保留 **一条组图总图题**
- 自动移除每张图片的独立图题

---

