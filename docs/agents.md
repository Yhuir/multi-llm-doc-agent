# Agent 设计与 I/O 规范（agents.md）

版本：V1.1  
目标：定义每个 Agent 的职责、输入输出、约束、失败策略与推荐 prompt 结构

---

## 1. 总体原则

### 1.1 Agent 设计目标
每个 Agent 必须满足：
- 输入清晰
- 输出结构化
- 失败可重试
- 工件可落盘
- 结果可被下游消费

### 1.2 统一约束
- 输出禁止 Markdown 进入最终 Word 正文
- 所有关键事实尽量带 `source_refs`
- 所有 Agent 输出都应可落为 JSON
- 所有 Agent 错误都必须写 event_log
- 所有 Agent 应返回 `result / reason / artifacts`

### 1.3 Provider 隔离
Agent 不直接依赖具体模型供应商，而是依赖统一 Provider 接口。

---

## 2. Requirement Parser Agent

### 2.1 目标
解析用户上传的 `.docx`，生成结构化 requirement 数据。

### 2.2 输入
- `upload_file_path`
- `task_id`

### 2.3 输出
- `requirement.json`
- `parse_report.json`

### 2.4 主要职责
- 提取项目名称、客户、地点、工期、里程碑
- 识别子系统、范围、接口、约束、标准、验收条款
- 建立 `source_index`
- 为后续 fact grounding 准备 `source_refs`

### 2.5 失败策略
- 文件损坏：直接失败
- 非 docx：直接提示格式不支持
- 解析部分缺失：允许通过，但 parse_report 需标缺失项

### 2.6 推荐 Prompt / 规则
这类 Agent 尽量不用纯自由生成，应采用“规则解析 + LLM 辅助抽取”。

---

## 3. Style Extractor Agent

### 3.1 目标
从参考模板中抽取风格偏好，生成 `style_profile.json`。

### 3.2 输入
- 模板文本抽取结果
- 配置规则

### 3.3 输出
- `style_profile.json`

### 3.4 提取维度
- 行文语气
- 句式偏好
- 常见结构
- 术语密度
- 表格使用偏好
- 禁止表达

### 3.5 注意
- 只能学习写法与结构偏好
- 禁止复用模板目录标题
- 禁止复写模板原句

---

## 4. TOC Generator Agent

### 4.1 目标
根据 requirement 生成覆盖完整、粒度合适的目录树。

### 4.2 输入
- `requirement.json`
- `style_profile.json`
- 用户初始意见（可为空）

### 4.3 输出
- `toc_vN.json`

### 4.4 规则
- 至少到三级
- 必要时四级
- 所有子系统必须覆盖
- 目录逻辑顺序必须正确
- 最小生成单元需适合独立生成

### 4.5 推荐 Prompt 模板
系统提示应强调：
- 基于 requirement 解析结果而不是模板标题
- 不照搬模板目录
- 目录必须适合后续工程实施写作
- 能下钻到四级，但不能无意义过深

### 4.6 失败策略
- 若目录粒度明显不合理，则重试一次
- 若仍不合理，进入人工审阅

---

## 5. TOC Review Chat Agent

### 5.1 目标
根据用户自然语言反馈修订目录。

### 5.2 输入
- 旧版 `toc_vN.json`
- `user_feedback`
- `chat_history`

### 5.3 输出
- `toc_vN+1.json`
- `diff_summary.json`

### 5.4 核心规则
- 只能在目录审阅阶段使用
- 未确认目录前可以反复修订
- 一旦目录确认，不再允许调用此 Agent

### 5.5 输出要求
diff_summary 至少包含：
- added_nodes
- removed_nodes
- renamed_nodes
- moved_nodes
- reordered_nodes

---

## 6. Section Writer Agent

### 6.1 目标
生成单个最小生成节点的工程实施正文。

### 6.2 输入
- `toc_confirmed.json`
- `node_uid`
- `requirement.json`
- `style_profile.json`

### 6.3 输出
- `node_text.json`

### 6.4 约束
- 正文目标字数初稿建议 1850–2050
- 禁止 Markdown
- 必须是工程实施风格
- 必须可执行、可验收、可落地
- 小节标题动态生成
- 关键重难点至少 1 段
- 尽量对关键段落附 `source_refs`

### 6.5 推荐 Prompt 结构
系统提示建议包含：
1. 角色：工程实施方案编写专家
2. 目标：编写指定节点正文
3. 风格：style_profile
4. 数据来源：requirement
5. 严禁事项：
   - 不得照搬模板
   - 不得输出 Markdown
   - 不得编造设备型号/数量/标准号
6. 输出 JSON 结构要求

### 6.6 失败策略
- 字数明显不足：交给 Length Control
- unsupported facts 过多：交给 Fact Grounding revise
- 结构混乱：重试一次

---

## 7. Fact Grounding Agent

### 7.1 目标
校验正文中的关键事实是否有据可查，避免瞎编。

### 7.2 输入
- `node_text.json`
- `requirement.json`

### 7.3 输出
- `fact_check.json`

### 7.4 核心任务
- 抽取关键 claim
- 逐条与 requirement/source_index 对齐
- 标记 support_status
- 计算 grounded_ratio
- 输出 unsupported_claims

### 7.5 判定规则
推荐：
- 关键事实不允许 `UNSUPPORTED`
- `grounded_ratio >= 0.70`
- 否则 FAIL

### 7.6 推荐 Prompt 结构
你是工程文档事实校验器。  
仅根据 requirement 解析结果判断支持关系。  
不要帮作者补脑，不要默认常识等于事实来源。  
如果正文提出了 requirement 中不存在的关键参数/型号/标准号，应判定 unsupported。

### 7.7 失败策略
- 第一次失败：调用 `revise_text()`
- 第二次失败：节点进入 `WAITING_MANUAL`

---

## 8. Entity Extractor Agent

### 8.1 目标
从通过事实校验的正文中抽取图片必需实体。

### 8.2 输入
- `node_text.json`
- `fact_check.json`

### 8.3 输出
- `entities.json`

### 8.4 抽取维度
- 设备
- 拓扑
- 工艺步骤
- 关键参数
- 验收动作
- 场景元素

### 8.5 要求
- must-have 元素尽量少而关键
- 避免抽得过于抽象
- 避免抽出事实未通过校验的内容

---

## 9. Image Prompt Agent

### 9.1 目标
根据实体与正文生成 2–3 条出图 prompt。

### 9.2 输入
- `entities.json`
- `node_text.json`

### 9.3 输出
- `image_prompts.json`

### 9.4 规则
每条 prompt 必须包含：
- 画面类型
- 必须出现元素
- 禁止泛化项
- 绑定锚点
- 绑定小节

### 9.5 推荐 Prompt 结构
- 场景目标
- 必须元素列表
- 结构关系
- 视角要求（如俯视图、拓扑图、施工示意图）
- 禁止项（纯科技背景、过度抽象、缺少设备标注）

---

## 10. Image Generation Agent

### 10.1 目标
调用豆包或其他图片 Provider 生成图片。

### 10.2 输入
- `image_prompts.json`

### 10.3 输出
- 图片文件
- `images.json`

### 10.4 失败策略
- 单图最多 3 次
- 失败写入 retry_count
- 多次失败标记 `NEED_MANUAL_CONFIRM`
- 宽松模式下不阻塞节点继续

---

## 11. Image-Text Relevance Agent

### 11.1 目标
做工程可用版图文一致性校验。

### 11.2 输入
- `node_text.json`
- `images.json`
- `entities.json`

### 11.3 输出
- `image_relevance.json`

### 11.4 校验方法
V1 不做深度理解，建议：
- 检查 must-have 元素是否出现
- 检查图片类型与正文绑定小节是否匹配
- 计算 score
- 输出 missing_elements

### 11.5 阈值
- `score >= 0.75` 通过
- 任一 must-have 元素缺失：直接 fail

### 11.6 失败策略
- 自动重写 prompt 并重试
- 超限后转手动确认

---

## 12. Length Control Agent

### 12.1 目标
将正文控制到合格范围。

### 12.2 输入
- `node_text.json`

### 12.3 输出
- 更新后的 `node_text.json`
- `metrics` 中 word_count

### 12.4 规则
- `<1800`：补写
- `1800–2200`：通过
- `>2200`：精简

### 12.5 补写优先级
1. 验收标准与测试步骤
2. 参数与工艺控制
3. 规范条款落地解释
4. 风险矩阵与应对
5. 记录与留痕要求

### 12.6 精简原则
- 优先删空泛句
- 删重复表述
- 不删硬信息

### 12.7 最大轮次
- 补写最多 2 轮
- 仍不达标则 `WAITING_MANUAL` 或 `NODE_FAILED`（配置决定）

---

## 13. Consistency Check Agent

### 13.1 目标
在进入排版前做最终一致性检查。

### 13.2 输入
- `node_text.json`
- `fact_check.json`
- `images.json`
- `tables.json`
- `toc_confirmed.json`
- `requirement.json`

### 13.3 输出
- `consistency.json`

### 13.4 检查项
- 实体一致性
- 术语一致性
- 约束一致性
- 引用一致性

### 13.5 失败策略
- 可修复项：自动修复
- 不可修复项：WAITING_MANUAL

---

## 14. Table Planner / Table Builder Agent（可合并）

### 14.1 目标
判断是否需要表格，并输出 `tables.json`

### 14.2 输入
- `node_text.json`
- `requirement.json`

### 14.3 输出
- `tables.json`

### 14.4 触发条件
满足其一时才建议表格：
- >= 3 行数据
- >= 4 列
- 明显属于参数矩阵/设备清单/接口矩阵/测试记录

### 14.5 限制
- 每节点建议 <= 2 张表
- 不适合表格的内容必须用段落表达

---

## 15. Layout Agent

### 15.1 目标
基于模板样式组织 Word 内容。

### 15.2 输入
- `toc_confirmed.json`
- `node_text.json`
- `tables.json`
- `images.json`
- `standard_template.docx`

### 15.3 输出
- layout blocks / doc object / 中间 docx

### 15.4 规则
- 标题使用模板已有 Heading 样式
- 正文使用模板正文样式
- 表格统一使用 `BiddingTable`
- 图片按绑定锚点插入
- 多图可采用矩阵布局
- 单图保留单图题，多图矩阵用组图题

### 15.5 插图默认规则
- 优先插在 anchor 段落后
- 找不到 anchor 时插在小节末尾
- 再找不到则插在节点末尾并记 warning

---

## 16. Word Export Agent

### 16.1 目标
生成最终 Word 文件供下载。

### 16.2 输入
- Layout 结果
- `standard_template.docx`

### 16.3 输出
- `artifacts/{task_id}/final/output.docx`

### 16.4 要求
- 不修改模板定义本身
- 只在模板基础上填充内容
- 导出失败必须落日志

---

## 17. Progress & State Agent / Service

### 17.1 目标
为 UI 提供实时状态。

### 17.2 输入
- Task / Node / EventLog / Metrics

### 17.3 输出
- 总进度
- 当前节点
- 当前阶段
- 节点树状态
- 最近日志

### 17.4 规则
- 每阶段落盘后更新
- UI 轮询读取
- 避免直接从 worker stdout 解析 UI 状态

---

## 18. 推荐统一返回格式

所有 Agent 推荐统一返回：

```json
{
  "result": "PASS",
  "message": "说明信息",
  "artifacts": {
    "file": "path/to/file.json"
  },
  "metrics": {
    "duration_ms": 1200
  }
}
```

---

## 19. Agent 编排顺序（V1）

```text
Requirement Parser
-> Style Extractor
-> TOC Generator
-> TOC Review Chat
-> Section Writer
-> Fact Grounding
-> Entity Extractor
-> Image Prompt
-> Image Generation
-> Image Relevance
-> Length Control
-> Table Builder
-> Consistency Check
-> Layout
-> Word Export
```

说明：
- Table Builder 可放在 Length Control 之后，也可放在 Consistency 之前
- Fact Grounding 一定要早于 Entity/Image 流程
- TOC Review 只在目录阶段可调用

---

## 20. 开发建议

### 20.1 每个 Agent 一个目录
```text
agents/
├─ requirement_parser/
├─ style_extractor/
├─ toc_generator/
├─ toc_review/
├─ section_writer/
├─ fact_grounding/
├─ entity_extractor/
├─ image_prompt/
├─ image_generation/
├─ image_relevance/
├─ length_control/
├─ table_builder/
├─ consistency_check/
├─ layout/
└─ word_export/
```

### 20.2 每个 Agent 至少包含
- `agent.py`
- `models.py`
- `prompt.py`
- `tests/`
- `README.md`

---

## 21. V1 关键优先级

P0：
- Requirement Parser
- TOC Generator / Review
- Section Writer
- Fact Grounding
- Length Control
- Layout / Export
- State / Progress

P1：
- Entity / Image / Relevance
- Table Builder
- Manual Action UI

P2：
- 高级质量评分
- 自动修复增强
- 多模型优化
