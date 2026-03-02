# Multi-Agent 工程实施方案自动生成系统（PRD/技术规格合一）


---

## 0. 背景与目标

### 0.1 背景
用户上传项目技术要求 Word（.doc/.docx），系统自动解析并生成“结构目录（可审阅）”，支持用户在类似 ChatGPT 的交互窗口中多轮修改确认目录；目录确认后，系统按“三级目录节点”为最小单元生成工程级实施内容（每节点约 2 页 A4）、自动生成 2–3 张强关联配图（使用豆包生成图片）、自动校验图文一致性与字数达标，最后自动排版输出可下载 Word 成品文档。

### 0.2 建设目标（可验收）
1）全文解析用户上传的项目技术要求 Word 文档（doc/docx）
2）基于全文解析结果自动生成结构目录树（仅展示给用户，不生成正文）
3）提供 AI 交互窗口：目录树发给用户审阅；用户提出修改建议后自动生成新版本目录树；循环直到用户明确发出“开始生成内容”的指令
4）按确认后的目录树逐级生成内容（以“三级目录节点”为最小生成单元）
5）每个三级目录节点正文：字数1800-2000；排版：宋体小四单倍行距约2页A4
6）每个三级目录节点生成强关联配图2–3张（豆包出图）
7）图文一致性校验：不达标自动重生成图片（必要时重写prompt）
8）字数校验：不达标自动补写直至达标
9）自动排版Word：必须使用Word原生表格与样式，禁止Markdown语法进入Word
10）输出docx（可选另存doc），用户可下载
11）Streamlit UI 实时显示总进度百分比、已完成与进行中的目录节点，并实时刷新
12）支持断点续跑：任何中断后保留进度，重启App后可继续

---

## 1. 产品范围（Scope）

### 1.1 In Scope
- Word 文档全文解析（doc/docx）
- 目录树生成、交互式修订、版本管理
- 以三级目录为单位的内容生成（工程实施文档风格）
- 每三级目录2–3张图片生成（豆包）
- 图文一致性校验与重试
- 字数控制与补写
- Word 排版输出（python-docx），含表格、图片、图题、标题样式、分页
- Streamlit 可视化进度与状态
- 断点续跑（Checkpoint/Resume）



---

## 2. 用户流程（User Journey）

A. 上传 Word（doc/docx）  
B. 系统解析全文 → 生成目录树 v1 → UI 展示  
C. 用户在对话框提出修改 → 系统生成目录树 v2/v3…（可回滚/对比差异）  
D. 用户明确输入“确认目录/开始生成内容”  
E. 系统按目录树逐个三级目录节点执行：生成正文 → 生成图片 → 图文一致性校验（不通过重试）→ 字数校验（不达标补写）→ 进入排版队列  
F. 全部完成 → 输出 Word 成品 → 下载

硬约束：未收到用户“开始生成内容”指令前，禁止进入正文生成。

---

## 3. 系统总体架构

### 3.1 模块/Agent 列表
Central Orchestrator（编排器）
- Requirement Parser Agent（解析）
- TOC Generator Agent（目录树生成）
- TOC Review Chat Agent（交互修订/版本）
- Section Writer Agent（按三级目录生成正文）
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
- UI：Streamlit
- Agent 编排：简单版可先用自研 Orchestrator（Python），后续可升级 LangChain / AutoGen
- Word：python-docx（doc 先转 docx）
- 向量检索（可选）：Milvus/FAISS（用于引用规范条款与模板片段）
- 任务队列（可选）：Celery + Redis / RabbitMQ（并发生成时）
- 持久化：SQLite（状态）+ 本地文件系统（工件）+ 可选S3/MinIO
- 图片：豆包文生图接口（由 Doubao Image Agent 调用）
- 大模型：Gemini CLI（内容生成）、或 OpenAI（可替换）

---

## 4. 断点续跑设计（强制）

### 4.1 设计目标
- 任何步骤中断（进程退出、电脑重启、网络异常）后，已完成的节点不重复生成
- 重启 App 后可选择“继续上次任务”或“新建任务”
- 同一任务可多次暂停/恢复

### 4.2 Checkpoint 策略
- 以“三级目录节点”为最小可恢复单元
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
每个 node_id（level=3）拥有以下阶段：
1）NODE_PENDING（等待）
2）TEXT_GENERATED（正文初稿完成）
3）IMAGES_GENERATED（图片初稿完成）
4）IMAGE_TEXT_CHECKED（图文一致性通过）
5）LENGTH_CHECKED（字数达标）
6）CONSISTENCY_CHECKED（前后一致性通过）
7）NODE_READY_FOR_LAYOUT（可排版）
8）NODE_LAID_OUT（已写入Word）
9）NODE_DONE（节点完成）
失败态：NODE_FAILED（超过重试上限）

阶段间硬依赖：
TEXT → IMAGES → IMAGE_TEXT_CHECK → LENGTH_CHECK → CONSISTENCY → LAYOUT

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

### 6.3 node_text.json（三级目录正文结构化）
{
  "node_id": "L3-SS001-001-001",
  "title": "现场勘察与放样",
  "sections": [
    {"h": "工程概述", "min_words": 200, "text": "...."},
    {"h": "设备与材料清单", "table_ref": "tables/materials_001"},
    {"h": "工具与仪器配置", "text": "...."},
    {"h": "人员组织与岗位职责", "text": "...."},
    {"h": "施工流程说明", "min_words": 400, "text": "...."},
    {"h": "技术控制要点", "min_words": 400, "text": "...."},
    {"h": "质量控制措施", "min_words": 350, "text": "...."},
    {"h": "安全施工措施", "min_words": 350, "text": "...."},
    {"h": "风险分析与应对", "min_words": 350, "text": "...."},
    {"h": "关键重难点", "style": {"bold": true, "color": "red"}, "text": "...."}
  ]
}

### 6.4 tables.json（Word原生表格数据）
{
  "tables": [
    {
      "table_id": "materials_001",
      "title": "设备与材料清单",
      "columns": ["序号", "名称", "规格型号", "单位", "数量", "备注"],
      "rows": [
        ["1", "交换机", "XX-24G-10G", "台", "2", "核心设备"],
        ["2", "光纤跳线", "LC-LC 单模", "根", "20", "含备品"]
      ]
    }
  ]
}

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
{
  "word_count": 2056,
  "image_text_score": [
    {"image_id": "img_001", "score": 0.82, "pass": true}
  ],
  "retries": {"img_001": 1, "length_expand": 0},
  "timing": {"text_gen_s": 45, "image_gen_s": 60}
}

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
- 每个三级节点必须满足可独立生成约2页内容的粒度

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
- 模板参考1：昆烟实施方案-目标范本.doc（本地文件，写作风格的主要依据，但是内容以及目录名不能照搬， 需要根据上传的文件分析）
- 模板参考2：太和曲靖技术部分(1).pdf (本地文件，作为写作风格的依据)
输出：
- node_text.json（按第6.3结构，包含“设备与材料清单”表格所需字段）
要求：
- 禁止Markdown语法
- 工程实施风格：可执行、可验收、可落地
- 关键重难点必须提供1段，后续由Layout设置红色加粗

### 7.5 Entity Extractor Agent
输入：node_text.json
输出：
- entities.json（设备、型号、拓扑、关键步骤、参数、验收点）
- must_have_list（生成图片必须出现的元素清单）

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
- fail → 调整prompt并重生成图片（最多见第8章重试策略）

### 7.9 Length Control Agent（强制）
输入：node_text.json
输出：
- updated_node_text.json（补写后）
- word_count
失败处理：
- <1800 → 触发补写策略；达到上限仍不足 → NODE_FAILED（需人工）

### 7.10 Layout Agent
输入：
- toc_confirmed.json
- node_text.json（每节点最终版）
- tables.json
- images.json
输出：
- docx_part（将节点写入 Word 的中间文件或直接写入主doc）
要求：
- 使用Word原生表格对象
- 样式与分页符合第9章规范

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
- 正文：宋体，小四，单倍行距
- 一级标题：黑体，三号（建议映射 Word Heading 1）
- 二级标题：黑体，四号（Heading 2）
- 三级标题：黑体，四号或小四（Heading 3）
- 图宽：5英寸，居中
- 图题：居中，自动编号（图X-Y）
- 关键重难点：红色、加粗、单独段落（由Layout Agent设置）

### 9.2 表格
- 必须使用 python-docx 的 Table 创建
- 表头加粗；列宽自适应或按模板固定
- 表格标题：表X-Y 居中或左对齐（统一）

### 9.3 分页
- 每个三级目录节点建议 2 页左右
- 若图片导致跨页严重：在图片前插入分页符（可配置）
- 节点结束后可选插入分页符（按版式需求）

---

## 10. Streamlit UI 模块设计

### 10.1 页面结构
1）任务区
- 上传Word
- 新建任务/继续任务
- 当前任务信息（task_id、状态、开始时间）

2）目录审阅区（TOC Review）
- 展示目录树（可折叠）
- 展示版本号与差异摘要
- 对话框输入修改意见
- 按钮：生成新目录版本、回滚、确认目录、开始生成内容

3）进度区
- 总进度百分比（按“节点阶段权重”计算）
- 目录节点状态列表：
  - 已完成（绿色）
  - 进行中（蓝色）
  - 重试中（橙色）
  - 失败/需人工（红色）

4）实时日志区
- 显示当前正在执行的节点与阶段
- 展示最近N条事件日志与错误信息

5）成果区
- 完成后显示下载按钮：output.docx
- 可选：下载生成报告（metrics/log）

### 10.2 进度计算（建议）
- 总权重 = 所有三级节点数 * 100
- 每节点阶段权重：
  - TEXT_GENERATED 25
  - IMAGES_GENERATED 20
  - IMAGE_TEXT_CHECKED 15
  - LENGTH_CHECKED 10
  - CONSISTENCY_CHECKED 10
  - NODE_LAID_OUT 20
- 总进度 = 已完成权重之和 / 总权重

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

### 11.2 Windows/Mac 注意事项
- doc 转 docx：Windows可调用本地Office（可选），跨平台建议使用 LibreOffice headless 或第三方转换服务
- 字体：确保系统有宋体（Windows默认有，Mac可能没有），可在文档内嵌或提示安装字体；或者用“仿宋/思源宋体”替代（需明确）
- 路径与编码：统一使用UTF-8与Pathlib

---

## 12. 参考模板：昆烟实施方案-目标范本.doc

你提供的“昆烟实施方案-目标范本.doc（仅一个三级目录内容）”作为写作标准与格式对齐基准：
- 写作语气：工程实施方案口吻
- 章节结构：参考其标题组织、段落密度、表格风格
- 表达细节：参数、验收、风险、记录表等

重要说明：
- 由于本系统运行环境无法直接读取你本地根目录文件，实际落地时请在App里增加“模板文件选择/上传”入口，或在配置中指定该文件路径。
- Gemini CLI 生成内容时必须“对齐模板风格”，但不得照搬原文；只学习结构与写法。

---

## 13. Gemini CLI 生成规范（用于 Section Writer Agent）

### 13.1 生成约束（必须）
- 输出不得包含Markdown标记（例如 #、##、-、*、|表格等）
- 表格不直接输出为文本表格：输出表格数据结构（JSON rows/columns），由python-docx渲染
- 必须按“标准技术细化结构模板”输出10个模块，并满足各模块最低字数门槛
- 必须引用 requirement.json 中与该节点相关的技术指标/强制条款/验收要求（以“引用点”形式输出，供Consistency Agent核对）
- 必须提供“关键重难点”独立段落（后续设置红色加粗）

### 13.2 建议的 Gemini 提示词（示例）
系统提示（System）
你是工程实施方案撰写专家。请严格按指定JSON结构输出，不要输出任何Markdown。

用户提示（User）
输入：
1）requirement.json（与你任务相关的片段）
2）toc节点信息：node_id、子系统名、三级目录标题、上下文二级目录标题
3）模板文件：昆烟实施方案-目标范本.doc（作为写作风格参考）

输出（必须是JSON，字段如下）：
- node_id
- title
- sections：10个模块，每个包含 h、text；“设备与材料清单”模块改为输出 table（columns+rows）
- references：列出你引用的 requirement 关键条款id或source_ref
约束：
- 总字数1800至2000字，且每个模块满足最低字数（见下）
- 施工流程>=400；技术控制>=400；安全>=350；质量>=350；风险>=350
- 不得出现Markdown符号
- 内容必须可执行、可验收、参数具体

---

## 14. 验收用例清单（Acceptance Test Cases）

### 14.1 解析类
TC-01 上传docx可解析标题/段落/表格，生成requirement.json且有source_ref
TC-02 上传doc（旧格式）能自动转docx并解析成功
TC-03 文档包含多个子系统，子系统清单抽取完整无遗漏

### 14.2 目录类
TC-04 自动生成目录树v1，包含一级目录→子系统→二级→三级，三级节点粒度合理
TC-05 用户提出“合并/拆分/改名/调整层级”后生成v2且差异摘要正确
TC-06 未点击“确认目录/开始生成内容”时，系统不得生成正文

### 14.3 正文类
TC-07 任一三级节点生成正文>=1800字，且10个模块齐全
TC-08 各模块最低字数门槛满足（流程/技术/安全/质量/风险）
TC-09 关键重难点段落存在且可被Layout设置红色加粗

### 14.4 图片与一致性
TC-10 每三级节点生成2–3张图片，均有图题与绑定段落
TC-11 正文提到星型拓扑，图片必须出现星型连接关系与设备标注
TC-12 图文一致性评分<阈值时自动重生成，重试次数记录正确

### 14.5 字数补写
TC-13 字数不足触发补写，最终达到>=1800
TC-14 补写内容聚焦验收/参数/规范/风险，不出现大段空话

### 14.6 Word排版
TC-15 输出docx无Markdown残留，表格为Word原生可编辑表格
TC-16 标题样式在Word导航窗格可折叠
TC-17 图片宽度约5英寸居中，图题居中编号
TC-18 关键重难点为红色加粗独立段落

### 14.7 UI与断点续跑
TC-19 Streamlit显示总进度百分比与节点状态实时更新
TC-20 生成中强制关闭App，重启后可继续且不重复生成已完成节点
TC-21 中断时的日志、重试次数、工件文件仍可追溯

---

## 15. 交付物清单
- Streamlit 应用代码
- SQLite 状态库（运行时生成）
- artifacts 目录结构说明
- final/output.docx 示例


---

# 附：最小目录建议（便于启动实现）
1）先实现：解析 → 目录v1 → 目录交互修订 → 三级节点正文生成 → Word输出（不出图）
2）再加：豆包出图 → 图文一致性校验 → 自动重试
3）最后加：断点续跑完善、并发、性能优化

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
  - 图片宽度约 5 英寸、居中
  - 图片下方插入图题（居中、自动编号“图X-Y”）
  - 图片与其绑定小节内容放在同一节点内，必要时在图片前插入分页符（可配置）

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
**模板参考 1（主风格基准）**
- `昆烟实施方案-目标范本.doc`
- **用途**：写作语气、章节组织密度、工程落地表达、表格风格、验收/记录表写法。

**模板参考 2（技术写法补充）**
- `太和曲靖技术部分(1).pdf`（对应需求中的“技术部分(施组)”）
- **用途**：技术段落表达方式、施工工艺细化颗粒度、质量/安全/验收措辞、专业术语使用习惯。

**强制约束（必须写进提示词与校验）**
- 只能“学习结构与写法”，不得照搬原文句子、不得复用模板目录标题。
- 目录名称必须以“用户上传技术要求 Word 的解析结果”为准，模板仅用于风格对齐。
- 输出不得包含 Markdown（包括但不限于 #、-、*、| 等）。

**落地要求**
- **Streamlit UI** 增加“模板文件上传/选择”入口（两份模板可选填，但 v2 默认要求都提供；缺失需提示并允许降级）。
- **Requirement Parser** 或 **Template Loader** 将模板内容提取为“风格要点摘要”（例如：常用段落套路、验收表字段集合、风险表达模板），供 `Section Writer Agent` 使用，而不是将原文直接拼接生成。

**v2 对 Section Writer Agent 的提示词补充（建议直接加入 gemini 提示）**
- 在用户提示中新增：
  1）模板 1 风格要点摘要（从昆烟范本提取）
  2）模板 2 风格要点摘要（从施组 PDF 提取）
- 约束补充：
  - “请模仿模板写作风格，但不得复用模板任何目录标题与句子；目录与内容必须来自 `requirement.json` 与 `toc` 节点信息。”
  - “输出总字数必须 1800–2000。”
  - “需要提供 2–3 条图片生成所需的关键信息（实体/必须元素/绑定段落锚点），供后续 `Image Prompt Agent` 使用。”

### 16.4 v2 验收点增补（对应新增能力）
- 每三级节点 Word 中可见 2–3 张图片，且图片位置与绑定段落一致
- 图题存在、编号正确、居中
- 任一节点正文 1800–2000 字（严格）
- 模板风格一致但目录/措辞不与模板雷同（可抽检相似度或人工 spot check）

