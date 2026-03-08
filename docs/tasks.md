# 开发任务拆解（tasks.md）

版本：V1.0  
用途：用于 Codex Desktop / Cursor / 人工开发排期、分工、验收  
依赖文档：
- `doc/pre.md`
- `doc/architecture.md`
- `doc/schema.md`
- `doc/agents.md`

---

## 1. 总体开发原则

### 1.1 目标
将系统拆解为可并行、可验收、可回归测试的开发任务，覆盖：

- 基础工程骨架
- 数据层
- Orchestrator / Worker
- Agents
- UI
- 排版与导出
- 恢复与日志
- 测试与交付

### 1.2 优先级定义
- **P0**：不完成则系统不可用
- **P1**：完成后系统具备完整 V1 体验
- **P2**：增强项，可延后

### 1.3 状态定义
建议任务状态：
- TODO
- IN_PROGRESS
- BLOCKED
- REVIEW
- DONE

---

## 2. 建议里程碑

## Milestone 1：工程基础骨架（P0）
目标：
- 跑起项目
- 建立目录结构
- 能创建任务并持久化

## Milestone 2：目录阶段闭环（P0）
目标：
- 上传 `.docx`
- 解析 requirement
- 生成 TOC
- 目录修订
- 目录确认冻结

## Milestone 3：节点生成闭环（P0）
目标：
- 节点正文生成
- 事实校验
- 字数控制
- 一致性检查
- 节点状态推进

## Milestone 4：排版导出闭环（P0）
目标：
- 基于模板输出 Word
- 支持图片、表格、分页
- 导出 `output.docx`

## Milestone 5：图片与人工介入（P1）
目标：
- 图片 prompt
- 图片生成
- 图文校验
- 人工处理失败图片

## Milestone 6：稳定性与打磨（P1/P2）
目标：
- 完善日志
- 断点恢复优化
- UI 细节
- 测试补齐

---

## 3. 任务拆解总表

| 编号 | 模块 | 任务 | 优先级 |
|---|---|---|---|
| T001 | 项目骨架 | 初始化项目目录与配置 | P0 |
| T002 | 项目骨架 | 建立 backend / ui / doc / artifacts 目录 | P0 |
| T003 | 配置 | 环境变量与本地配置加载 | P0 |
| T004 | 数据库 | SQLite 初始化与迁移脚本 | P0 |
| T005 | 数据库 | task / toc_version / node_state / event_log 表实现 | P0 |
| T006 | Repository | TaskRepository / NodeRepository / EventLogRepository | P0 |
| T007 | 服务层 | TaskService 基础操作 | P0 |
| T008 | 服务层 | TOCService / NodeService / ProgressService | P0 |
| T009 | 上传 | `.docx` 上传与文件保存 | P0 |
| T010 | Agent | Requirement Parser Agent | P0 |
| T011 | Agent | Style Extractor Agent | P1 |
| T012 | Agent | TOC Generator Agent | P0 |
| T013 | Agent | TOC Review Chat Agent | P0 |
| T014 | Orchestrator | 任务状态机实现 | P0 |
| T015 | Orchestrator | 节点状态机实现 | P0 |
| T016 | Orchestrator | 目录确认与冻结逻辑 | P0 |
| T017 | Worker | 后台 Worker 轮询与执行框架 | P0 |
| T018 | Worker | 心跳、checkpoint、重试机制 | P0 |
| T019 | Agent | Section Writer Agent | P0 |
| T020 | Agent | Fact Grounding Agent | P0 |
| T021 | Agent | Length Control Agent | P0 |
| T022 | Agent | Consistency Check Agent | P0 |
| T023 | Agent | Table Builder Agent | P1 |
| T024 | Agent | Entity Extractor Agent | P1 |
| T025 | Agent | Image Prompt Agent | P1 |
| T026 | Agent | Image Generation Agent | P1 |
| T027 | Agent | Image-Text Relevance Agent | P1 |
| T028 | 排版 | Layout Agent | P0 |
| T029 | 导出 | Word Export Agent | P0 |
| T030 | UI | 新建任务 / 继续任务页面 | P0 |
| T031 | UI | 配置区（模型/API Key） | P1 |
| T032 | UI | 目录审阅区 | P0 |
| T033 | UI | AI 交互区 | P0 |
| T034 | UI | 进度区与节点树状态展示 | P0 |
| T035 | UI | 实时日志区 | P0 |
| T036 | UI | 成果下载区 | P0 |
| T037 | UI | 人工介入区 | P1 |
| T038 | 恢复 | 继续任务 / 加载历史目录与消息 | P0 |
| T039 | Diff | 树级 diff 实现 | P0 |
| T040 | ID | node_uid / node_id 双 ID 机制 | P0 |
| T041 | Provider | TextModelProvider 抽象 | P0 |
| T042 | Provider | ImageModelProvider 抽象 | P1 |
| T043 | 测试 | 单元测试骨架 | P0 |
| T044 | 测试 | 端到端最小闭环测试 | P0 |
| T045 | 测试 | 恢复/重试/中断测试 | P0 |
| T046 | 交付 | README / 启动脚本 / 示例配置 | P0 |

---

## 4. 详细任务定义

## T001 初始化项目目录与配置
**优先级**：P0

### 目标
建立统一项目骨架。

### 输出
```text
backend/
ui/
doc/
artifacts/
tests/
```

### 验收标准
- 本地可启动
- 配置文件可读取
- 日志目录可创建

### 依赖
无

---

## T002 建立 backend / ui / doc / artifacts 目录
**优先级**：P0

### 目标
创建稳定目录结构，便于后续 Codex 继续生成代码。

### 建议结构
```text
backend/
├─ agents/
├─ app_service/
├─ config/
├─ models/
├─ orchestrator/
├─ providers/
├─ repositories/
├─ utils/
└─ worker/

ui/
tests/
artifacts/
doc/
```

### 验收标准
- 各目录存在
- 包结构可 import

---

## T003 环境变量与本地配置加载
**优先级**：P0

### 目标
支持本地配置与 API key 管理。

### 子任务
- 定义配置类
- 读取 `.env`
- 读取本地 app config
- 支持默认模型配置

### 验收标准
- 可加载文本模型配置
- 可加载图片模型配置
- 缺失配置时报错清晰

---

## T004 SQLite 初始化与迁移脚本
**优先级**：P0

### 目标
初始化数据库并支持 schema 升级。

### 子任务
- 创建 `app.db`
- 建表脚本
- 索引脚本
- 初始化数据脚本（可选）

### 验收标准
- 启动后自动初始化数据库
- 所有核心表创建成功

### 参考
见 `doc/schema.md`

---

## T005 task / toc_version / node_state / event_log 表实现
**优先级**：P0

### 目标
实现核心持久化表。

### 验收标准
- 可插入/更新/查询任务
- 可存目录版本
- 可存节点状态
- 可落事件日志

---

## T006 Repository 层实现
**优先级**：P0

### 目标
封装数据库访问。

### 子任务
- `TaskRepository`
- `TOCRepository`
- `NodeStateRepository`
- `EventLogRepository`
- `ChatMessageRepository`
- `ManualActionRepository`

### 验收标准
- Service 层无需直接写 SQL
- 基础 CRUD 可用

---

## T007 TaskService 基础操作
**优先级**：P0

### 目标
提供任务创建、查询、继续、更新状态等能力。

### 功能
- create_task
- get_task
- list_resumable_tasks
- update_status
- mark_failed
- mark_done

### 验收标准
- UI 可通过 Service 创建任务
- 可恢复任务列表可读取

---

## T008 TOCService / NodeService / ProgressService
**优先级**：P0

### 目标
补齐任务之外的业务操作。

### 验收标准
- 可写入/读取 TOC 版本
- 可读取节点进度
- 可计算总进度
- 可返回前端状态树数据

---

## T009 `.docx` 上传与文件保存
**优先级**：P0

### 目标
支持 `.docx` 上传与保存到任务工件目录。

### 规则
- 唯一正式支持 `.docx`
- 非 `.docx` 直接阻止上传或提示

### 验收标准
- 文件能保存到 `artifacts/{task_id}/input/`
- UI 能显示文件名
- 非法格式提示清晰

---

## T010 Requirement Parser Agent
**优先级**：P0

### 目标
解析 docx，输出 `requirement.json`

### 子任务
- 文档文本抽取
- 项目基础信息抽取
- 子系统抽取
- 条款/标准/验收项抽取
- source_index 建立
- parse_report 输出

### 验收标准
- 对示例 docx 能输出 requirement.json
- 关键字段存在
- source_ref 可追踪

### 依赖
T009

---

## T011 Style Extractor Agent
**优先级**：P1

### 目标
输出 `style_profile.json`

### 验收标准
- 可根据参考模板生成 style profile
- 不复用模板原文
- 可用于 Section Writer prompt

---

## T012 TOC Generator Agent
**优先级**：P0

### 目标
从 requirement 生成 toc_v1

### 子任务
- 至少三级目录
- 必要时下钻四级
- 生成 `node_uid`
- 标记 `is_generation_unit`

### 验收标准
- 所有子系统被覆盖
- 目录结构顺序正确
- 最小生成单元可独立生成

### 依赖
T010

---

## T013 TOC Review Chat Agent
**优先级**：P0

### 目标
根据用户反馈生成新的 TOC 版本。

### 子任务
- 聊天消息保存
- 版本基于旧版生成
- diff summary 输出

### 验收标准
- 支持 `toc_v1 -> toc_v2`
- 能记录修改说明
- 能回滚旧版本继续修改

---

## T014 任务状态机实现
**优先级**：P0

### 目标
按 `pre/architecture/schema` 实现 task 状态流转。

### 验收标准
- NEW -> PARSED -> TOC_REVIEW -> GENERATING -> LAYOUTING -> EXPORTING -> DONE
- 支持 PAUSED / FAILED
- 非法状态跳转被阻止

---

## T015 节点状态机实现
**优先级**：P0

### 目标
实现 node_state 全状态。

### 验收标准
- 节点状态能按阶段推进
- 状态可恢复
- WAITING_MANUAL 可被 UI 识别

---

## T016 目录确认与冻结逻辑
**优先级**：P0

### 目标
点击“确认目录 / 开始生成内容”后冻结 TOC。

### 验收标准
- 生成中无法再改当前任务目录
- 会生成 `toc_confirmed.json`
- 需要修改时只能创建派生任务

---

## T017 后台 Worker 轮询与执行框架
**优先级**：P0

### 目标
将长任务放到后台执行。

### 子任务
- Worker 启动
- 任务拉取
- 节点执行
- 阶段推进
- 异常捕获

### 验收标准
- UI 不阻塞
- Worker 可独立运行
- 可处理至少 1 个任务闭环

---

## T018 心跳、checkpoint、重试机制
**优先级**：P0

### 目标
支持可恢复执行。

### 子任务
- 定时心跳
- 阶段落盘
- 输入/输出快照路径保存
- retry 计数
- 僵死判断

### 验收标准
- 强制中断后可恢复
- 已完成阶段不重复执行
- 进行中阶段可回滚重试

---

## T019 Section Writer Agent
**优先级**：P0

### 目标
生成单节点工程实施正文。

### 子任务
- 动态小节标题
- 工程实施风格
- 不输出 Markdown
- 初稿字数控制在合理范围

### 验收标准
- 输出 `text.json`
- 正文结构可用于后续流程
- 至少包含 1 个关键重难点段落

---

## T020 Fact Grounding Agent
**优先级**：P0

### 目标
检查正文关键事实是否有来源支撑。

### 子任务
- claim 抽取
- support 判定
- grounded_ratio 计算
- unsupported 列表输出
- revise 回调

### 验收标准
- 能识别 unsupported claim
- 输出 `fact_check.json`
- 支持 revise 一轮以上

---

## T021 Length Control Agent
**优先级**：P0

### 目标
控制正文长度。

### 规则
- `<1800` 补写
- `1800–2200` 通过
- `>2200` 精简

### 验收标准
- 生成后写入 word_count
- 补写最多 2 轮
- 精简不丢关键事实

---

## T022 Consistency Check Agent
**优先级**：P0

### 目标
完成四类一致性检查。

### 子任务
- 实体一致性
- 术语一致性
- 约束一致性
- 引用一致性

### 验收标准
- 输出 `consistency.json`
- 可报告 issues
- 可对可修复项自动修复

---

## T023 Table Builder Agent
**优先级**：P1

### 目标
判断是否生成表格，并输出 `tables.json`

### 验收标准
- 不滥用表格
- 表格样式名固定为 `BiddingTable`
- 支持 bind_anchor / source_refs

---

## T024 Entity Extractor Agent
**优先级**：P1

### 目标
抽取出图必须元素。

### 验收标准
- 输出 `entities.json`
- must-have 元素足够具体
- 不包含未通过事实校验的虚构内容

---

## T025 Image Prompt Agent
**优先级**：P1

### 目标
输出 2–3 条强约束 prompt。

### 验收标准
- 包含 must-have elements
- 包含 forbidden elements
- 带 bind_anchor / bind_section

---

## T026 Image Generation Agent
**优先级**：P1

### 目标
调用图片 Provider 出图。

### 验收标准
- 可生成图片文件
- 输出 `images.json`
- 失败时支持最多 3 次重试
- 超限标记 `NEED_MANUAL_CONFIRM`

---

## T027 Image-Text Relevance Agent
**优先级**：P1

### 目标
做工程可用版图文相关性校验。

### 验收标准
- score 阈值可配置
- missing elements 可输出
- fail 时可触发重试

---

## T028 Layout Agent
**优先级**：P0

### 目标
基于模板样式完成排版。

### 子任务
- Heading 样式映射
- Normal 样式正文
- BiddingTable 表格
- 图片插入
- 组图矩阵
- 分页策略

### 验收标准
- 不硬编码替代模板样式
- 图表可插入指定位置
- 节点内容排版连续可读

---

## T029 Word Export Agent
**优先级**：P0

### 目标
输出 `output.docx`

### 验收标准
- 最终文件存在
- 文件可打开
- 下载路径可被 UI 使用

---

## T030 新建任务 / 继续任务页面
**优先级**：P0

### 目标
支持创建和继续任务。

### 验收标准
- 可展示未完成任务列表
- 可点击继续
- 当前任务信息可见

---

## T031 配置区（模型/API Key）
**优先级**：P1

### 目标
配置文本/图片模型与 API key。

### 验收标准
- 可保存默认配置
- 下次启动可读取
- UI 输入与本地配置一致

---

## T032 目录审阅区
**优先级**：P0

### 目标
展示 TOC 树与版本切换。

### 验收标准
- 目录可折叠
- 版本可切换
- 旧版本可查看
- 可触发回滚

---

## T033 AI 交互区
**优先级**：P0

### 目标
提交目录意见并显示对话。

### 验收标准
- 消息历史可见
- 可提交意见
- 可触发新 TOC 版本

---

## T034 进度区与节点树状态展示
**优先级**：P0

### 目标
展示总进度和节点状态。

### 验收标准
- 总进度实时更新
- 节点高亮当前项
- DONE / FAILED / MANUAL 状态颜色不同

---

## T035 实时日志区
**优先级**：P0

### 目标
展示最近事件日志。

### 验收标准
- 最近 N 条日志可显示
- 错误日志突出展示
- 支持按节点过滤（加分项）

---

## T036 成果下载区
**优先级**：P0

### 目标
展示 `output.docx` 下载入口。

### 验收标准
- 完成后可下载
- 可显示生成完成时间

---

## T037 人工介入区
**优先级**：P1

### 目标
处理 WAITING_MANUAL 节点。

### 支持动作
- 查看失败原因
- 重新生成当前节点
- 跳过图片
- 放宽阈值
- 手动确认通过
- 导出半成品

### 验收标准
- UI 可触发 manual_action
- 操作可写库
- 节点状态可继续推进

---

## T038 继续任务 / 加载历史目录与消息
**优先级**：P0

### 目标
恢复会话上下文。

### 验收标准
- 继续任务后可看到旧 TOC
- 可看到对话历史
- 可继续未完成阶段

---

## T039 树级 diff 实现
**优先级**：P0

### 目标
实现目录树差异比较。

### 识别项
- add
- remove
- rename
- move
- reorder

### 验收标准
- diff_summary 可供 UI 直接展示
- 文本修改与结构修改可区分

---

## T040 node_uid / node_id 双 ID 机制
**优先级**：P0

### 目标
保证节点跨版本稳定。

### 验收标准
- 改名时 node_uid 不变
- 章节编号变化不影响 node_uid
- node_uid 可用于恢复和工件归档

---

## T041 TextModelProvider 抽象
**优先级**：P0

### 目标
统一文本模型调用接口。

### 接口建议
- generate_text
- revise_text
- extract_structured_json
- score_or_classify

### 验收标准
- Section Writer / Fact Grounding / TOC Agent 可共用接口
- 更换模型不改业务逻辑

---

## T042 ImageModelProvider 抽象
**优先级**：P1

### 目标
统一图片模型调用接口。

### 接口建议
- generate_images
- rewrite_prompt
- health_check

### 验收标准
- Image Agent 不直接依赖具体厂商 SDK

---

## T043 单元测试骨架
**优先级**：P0

### 目标
建立最基本测试能力。

### 覆盖建议
- repository
- service
- state machine
- schema validation

### 验收标准
- 测试可运行
- 至少覆盖核心流程基础分支

---

## T044 端到端最小闭环测试
**优先级**：P0

### 目标
用示例 docx 跑通从上传到导出的最小流程。

### 验收标准
- 能产出 output.docx
- 能落 requirement / toc / text / logs
- 状态推进正确

---

## T045 恢复 / 重试 / 中断测试
**优先级**：P0

### 目标
验证断点续跑。

### 场景
- 文本生成中断
- 图片生成中断
- 导出前中断
- 进程重启后继续

### 验收标准
- 可恢复
- 已完成阶段不重复
- 日志可追踪

---

## T046 README / 启动脚本 / 示例配置
**优先级**：P0

### 目标
让项目可交接、可启动。

### 输出
- `README.md`
- `run_ui.sh / run_worker.sh`
- `.env.example`

### 验收标准
- 新开发者按 README 能跑起来
- 启动方式清晰

---

## 5. 推荐开发顺序

## Phase A：骨架与数据层
按顺序：
- T001
- T002
- T003
- T004
- T005
- T006
- T007
- T008

## Phase B：目录阶段闭环
- T009
- T010
- T012
- T013
- T014
- T016
- T030
- T032
- T033
- T038
- T039
- T040

## Phase C：节点生成闭环
- T015
- T017
- T018
- T019
- T020
- T021
- T022
- T041
- T034
- T035

## Phase D：排版与导出
- T023
- T028
- T029
- T036

## Phase E：图片与人工介入
- T024
- T025
- T026
- T027
- T031
- T037
- T042

## Phase F：测试与交付
- T043
- T044
- T045
- T046

---

## 6. 建议分工

### 后端 / 架构
负责：
- T003–T008
- T014–T018
- T041–T042

### Agent / AI
负责：
- T010–T013
- T019–T027

### UI
负责：
- T030–T038

### 文档输出 / Office
负责：
- T028–T029

### QA / 稳定性
负责：
- T043–T045

---

## 7. 每周交付建议（示例）

## Week 1
- 项目骨架
- DB
- Repository
- Service
- 上传 docx

## Week 2
- Requirement Parser
- TOC Generator
- TOC Review
- 目录 UI

## Week 3
- Worker
- 状态机
- Section Writer
- Fact Grounding
- Length Control

## Week 4
- Consistency
- Layout
- Export
- E2E 闭环

## Week 5
- Image pipeline
- Manual UI
- 恢复测试
- 文档与交付

---

## 8. 风险与阻塞项

### 8.1 高风险任务
- T010 Requirement Parser
- T019 Section Writer
- T020 Fact Grounding
- T028 Layout Agent
- T045 恢复测试

### 8.2 常见阻塞
- 模板样式与代码插入兼容性
- TOC 粒度不稳定
- fact grounding 误判率
- 图片接口稳定性
- Word 排版细节偏差

### 8.3 缓解措施
- 先做最小样例
- 提前准备 2–3 个代表性 docx
- 对 Layout 单独做样式回归测试
- 对恢复流程做强制 kill 测试

---

## 9. Definition of Done（DoD）

单个任务完成必须满足：
1. 代码提交
2. 通过基本测试
3. 有日志
4. 有异常处理
5. 与既有文档口径一致
6. 必要时补充 README / 注释
7. 可被下游模块调用

---

## 10. 最终交付基线

V1 最终至少应实现：
- 上传 `.docx`
- 解析 requirement
- 生成 TOC 并支持修订
- 确认目录并冻结
- 分节点生成正文
- 事实校验
- 字数控制
- 一致性检查
- Word 排版导出
- 实时进度
- 实时日志
- 断点续跑
- 图片失败宽松处理
- 基本人工介入能力

---

## 11. 推荐下一步

建议 Codex Desktop 下一步优先生成：

1. `backend/models/enums.py`
2. `backend/models/schemas.py`
3. `backend/repositories/*.py`
4. `backend/app_service/task_service.py`
5. `backend/orchestrator/orchestrator.py`
6. `backend/worker/node_runner.py`
7. `ui/src/App.jsx`

这样可以最快形成可运行骨架。
