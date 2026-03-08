# 数据结构与数据库设计（schema.md）

版本：V1.1  
目标：定义 SQLite 表结构、关键 JSON 工件结构、字段约束与状态枚举

---

## 1. 总体原则

- 元数据进 SQLite
- 大工件进 artifacts 文件系统
- 所有 JSON 均应可被 Pydantic 校验
- 所有状态字段使用枚举，不用自由字符串
- 所有时间字段统一 ISO 8601

---

## 2. SQLite 表结构

## 2.1 task

用途：任务主表

| 字段 | 类型 | 说明 |
|---|---|---|
| task_id | TEXT PK | 任务唯一 ID |
| parent_task_id | TEXT NULL | 派生任务的父任务 ID |
| title | TEXT | 任务标题 |
| status | TEXT | 任务状态枚举 |
| upload_file_name | TEXT | 原始文件名 |
| upload_file_path | TEXT | 上传文件路径 |
| confirmed_toc_version | INTEGER NULL | 已确认目录版本 |
| min_generation_level | INTEGER NULL | 3 或 4 |
| text_provider | TEXT | 文本模型提供方 |
| image_provider | TEXT | 图片模型提供方 |
| total_nodes | INTEGER DEFAULT 0 | 最小生成节点总数 |
| completed_nodes | INTEGER DEFAULT 0 | 已完成节点数 |
| total_progress | REAL DEFAULT 0 | 总进度 0~1 |
| current_stage | TEXT NULL | 当前任务阶段 |
| current_node_uid | TEXT NULL | 当前执行节点 |
| latest_error | TEXT NULL | 最近错误 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |
| last_heartbeat_at | TEXT NULL | 最后心跳 |
| finished_at | TEXT NULL | 完成时间 |

### task.status 枚举
- NEW
- PARSED
- TOC_REVIEW
- GENERATING
- LAYOUTING
- EXPORTING
- DONE
- PAUSED
- FAILED

---

## 2.2 toc_version

用途：目录版本表

| 字段 | 类型 | 说明 |
|---|---|---|
| toc_version_id | TEXT PK | 版本记录 ID |
| task_id | TEXT | 所属任务 |
| version_no | INTEGER | 版本号 |
| file_path | TEXT | toc_vN.json 路径 |
| based_on_version_no | INTEGER NULL | 基于哪个版本修改 |
| is_confirmed | INTEGER | 是否确认版 |
| diff_summary_json | TEXT NULL | 差异摘要 JSON |
| created_by | TEXT | system / user |
| created_at | TEXT | 创建时间 |

唯一约束建议：
- `(task_id, version_no)` 唯一

---

## 2.3 toc_node_snapshot

用途：记录某一 TOC 版本中的节点快照

| 字段 | 类型 | 说明 |
|---|---|---|
| snapshot_id | TEXT PK | 快照 ID |
| task_id | TEXT | 所属任务 |
| version_no | INTEGER | 目录版本号 |
| node_uid | TEXT | 稳定 ID |
| node_id | TEXT | 章节编号，如 1.2.3 |
| parent_node_uid | TEXT NULL | 父节点稳定 ID |
| level | INTEGER | 层级 |
| title | TEXT | 标题 |
| order_index | INTEGER | 排序 |
| is_generation_unit | INTEGER | 是否最小生成单元 |
| source_refs_json | TEXT NULL | 来源引用 |
| constraints_json | TEXT NULL | 约束 |
| created_at | TEXT | 创建时间 |

---

## 2.4 node_state

用途：节点执行状态主表

| 字段 | 类型 | 说明 |
|---|---|---|
| node_state_id | TEXT PK | 记录 ID |
| task_id | TEXT | 所属任务 |
| node_uid | TEXT | 稳定节点 ID |
| node_id | TEXT | 当前章节编号 |
| title | TEXT | 节点标题 |
| level | INTEGER | 3 或 4 |
| status | TEXT | 节点状态 |
| progress | REAL | 0~1 |
| retry_text | INTEGER DEFAULT 0 | 文本重试次数 |
| retry_image | INTEGER DEFAULT 0 | 图片重试次数 |
| retry_fact | INTEGER DEFAULT 0 | 事实校验重试次数 |
| image_manual_required | INTEGER DEFAULT 0 | 是否需人工确认图片 |
| manual_action_status | TEXT NULL | 人工处理状态 |
| current_stage | TEXT NULL | 当前阶段 |
| last_error | TEXT NULL | 最近错误 |
| input_snapshot_path | TEXT NULL | 最近输入快照 |
| output_artifact_path | TEXT NULL | 最近输出工件 |
| started_at | TEXT NULL | 开始时间 |
| updated_at | TEXT | 更新时间 |
| last_heartbeat_at | TEXT NULL | 心跳 |
| finished_at | TEXT NULL | 完成时间 |

### node_state.status 枚举
- PENDING
- TEXT_GENERATING
- TEXT_DONE
- FACT_CHECKING
- FACT_PASSED
- IMAGE_GENERATING
- IMAGE_DONE
- IMAGE_VERIFYING
- IMAGE_VERIFIED
- LENGTH_CHECKING
- LENGTH_PASSED
- CONSISTENCY_CHECKING
- READY_FOR_LAYOUT
- LAYOUTED
- NODE_DONE
- NODE_FAILED
- WAITING_MANUAL

### manual_action_status 枚举
- NONE
- PENDING
- CONFIRMED
- SKIPPED
- REGENERATED
- FAILED

---

## 2.5 event_log

用途：全链路事件日志

| 字段 | 类型 | 说明 |
|---|---|---|
| event_id | TEXT PK | 事件 ID |
| task_id | TEXT | 所属任务 |
| node_uid | TEXT NULL | 所属节点 |
| stage | TEXT | 所处阶段 |
| status | TEXT | success / warning / error / info |
| message | TEXT | 日志内容 |
| retry_count | INTEGER DEFAULT 0 | 本阶段重试次数 |
| input_snapshot_path | TEXT NULL | 输入快照 |
| output_artifact_path | TEXT NULL | 输出工件 |
| duration_ms | INTEGER NULL | 耗时 |
| meta_json | TEXT NULL | 扩展 JSON |
| created_at | TEXT | 创建时间 |

索引建议：
- `(task_id, created_at)`
- `(task_id, node_uid, created_at)`

---

## 2.6 chat_message

用途：目录审阅聊天历史

| 字段 | 类型 | 说明 |
|---|---|---|
| message_id | TEXT PK | 消息 ID |
| task_id | TEXT | 所属任务 |
| role | TEXT | user / assistant / system |
| content | TEXT | 消息内容 |
| related_toc_version | INTEGER NULL | 关联目录版本 |
| created_at | TEXT | 创建时间 |

---

## 2.7 task_config

用途：任务级配置快照

| 字段 | 类型 | 说明 |
|---|---|---|
| task_config_id | TEXT PK | 记录 ID |
| task_id | TEXT | 所属任务 |
| text_provider | TEXT | 文本模型 |
| image_provider | TEXT | 图片模型 |
| text_model_name | TEXT | 模型名 |
| image_model_name | TEXT | 图片模型名 |
| strict_mode | INTEGER DEFAULT 0 | V1 默认宽松模式 |
| image_retry_limit | INTEGER DEFAULT 3 | 图片重试上限 |
| length_expand_limit | INTEGER DEFAULT 2 | 补写轮次 |
| length_trim_threshold | INTEGER DEFAULT 2200 | 精简阈值 |
| grounded_ratio_threshold | REAL DEFAULT 0.70 | 事实校验阈值 |
| image_score_threshold | REAL DEFAULT 0.75 | 图文相关性阈值 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

---

## 2.8 manual_action

用途：人工介入记录

| 字段 | 类型 | 说明 |
|---|---|---|
| action_id | TEXT PK | 记录 ID |
| task_id | TEXT | 所属任务 |
| node_uid | TEXT | 所属节点 |
| action_type | TEXT | 手动处理类型 |
| action_payload_json | TEXT NULL | 参数 |
| operator_name | TEXT NULL | 操作人 |
| result_status | TEXT | 结果 |
| created_at | TEXT | 创建时间 |

### action_type 枚举
- VIEW_FAILURE
- REGENERATE_NODE
- SKIP_IMAGE
- RELAX_THRESHOLD
- MARK_PASSED
- EXPORT_PARTIAL

---

## 3. JSON 工件结构

## 3.1 requirement.json

```json
{
  "project": {
    "name": "项目名称",
    "customer": "客户名称",
    "location": "项目地点",
    "duration_days": 90,
    "milestones": [
      {"name": "开工", "date": "2026-03-10"}
    ]
  },
  "scope": {
    "overview": "建设范围概述",
    "subsystems": [
      {
        "name": "子系统A",
        "description": "子系统范围",
        "requirements": [
          {
            "type": "tech_metric",
            "key": "带宽",
            "value": "10Gbps",
            "source_ref": "p3#L12"
          }
        ],
        "interfaces": ["子系统B"]
      }
    ]
  },
  "constraints": {
    "standards": ["GBxxxx", "ISOxxxx"],
    "acceptance": ["验收条款摘要"]
  },
  "source_index": {
    "p3#L12": {
      "page": 3,
      "paragraph_id": "para_45",
      "text": "原文片段"
    }
  }
}
```

### requirement 关键字段说明
- `source_ref` 是事实可追溯的基础
- `source_index` 为 fact grounding 和 traceability 提供原文引用
- 不要求所有普通说明句都有 source_ref，但关键事实必须有

---

## 3.2 style_profile.json

```json
{
  "tone": ["工业级严谨", "客观叙述", "可执行", "可验收"],
  "sentence_preferences": [
    "应",
    "应当",
    "必须",
    "完成后应"
  ],
  "structure_patterns": [
    "施工准备",
    "实施方法",
    "工艺控制",
    "验收要求",
    "风险与应对",
    "记录与留痕"
  ],
  "forbidden_patterns": [
    "口语化表达",
    "营销宣传语",
    "空泛总结"
  ],
  "table_preferences": {
    "max_tables_per_node": 2,
    "only_when_structured": true
  }
}
```

---

## 3.3 toc_vN.json

```json
{
  "version": 3,
  "generated_at": "2026-03-01T10:00:00",
  "based_on_version": 2,
  "tree": [
    {
      "node_uid": "uid_root_001",
      "node_id": "1",
      "level": 1,
      "title": "总体实施方案",
      "children": [
        {
          "node_uid": "uid_l2_001",
          "node_id": "1.1",
          "level": 2,
          "title": "子系统A",
          "children": [
            {
              "node_uid": "uid_l3_001",
              "node_id": "1.1.1",
              "level": 3,
              "title": "施工准备",
              "is_generation_unit": false,
              "children": [
                {
                  "node_uid": "uid_l4_001",
                  "node_id": "1.1.1.1",
                  "level": 4,
                  "title": "现场勘察与放样",
                  "is_generation_unit": true,
                  "constraints": {
                    "min_words": 1800,
                    "recommended_words": [1800, 2200],
                    "images": [2, 3]
                  },
                  "source_refs": ["p2#L1"]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

---

## 3.4 node_text.json

```json
{
  "node_uid": "uid_l4_001",
  "node_id": "1.1.1.1",
  "title": "现场勘察与放样",
  "summary": "本节点内容概述",
  "sections": [
    {
      "section_id": "sec_01",
      "title": "现场条件复核与放样准备",
      "paragraphs": [
        {
          "paragraph_id": "p_01",
          "text": "正文段落内容",
          "source_refs": ["p2#L1", "p3#L12"],
          "claim_ids": ["claim_001", "claim_002"],
          "anchors": ["anchor_site_survey"]
        }
      ]
    }
  ],
  "highlight_paragraphs": [
    {
      "paragraph_id": "p_key_01",
      "text": "关键重难点段落",
      "style_hint": "red_bold"
    }
  ],
  "word_count": 1890,
  "version": 2,
  "generated_at": "2026-03-07T11:00:00"
}
```

说明：
- `sections.title` 必须动态生成，不能写死
- 段落级 `source_refs` 用于 fact grounding 与引用追踪
- `anchors` 用于图片和表格绑定

---

## 3.5 fact_check.json

```json
{
  "node_uid": "uid_l4_001",
  "grounded_ratio": 0.86,
  "result": "PASS",
  "claims": [
    {
      "claim_id": "claim_001",
      "text": "主干链路应采用千兆以上传输能力",
      "claim_type": "parameter",
      "support_status": "SUPPORTED",
      "source_refs": ["p3#L12"]
    },
    {
      "claim_id": "claim_002",
      "text": "施工期为90天",
      "claim_type": "duration",
      "support_status": "SUPPORTED",
      "source_refs": ["p1#L5"]
    }
  ],
  "unsupported_claims": [],
  "weak_claims": []
}
```

### support_status 枚举
- SUPPORTED
- WEAKLY_SUPPORTED
- UNSUPPORTED
- GENERAL_ENGINEERING_KNOWLEDGE

---

## 3.6 entities.json

```json
{
  "node_uid": "uid_l4_001",
  "entities": [
    {
      "entity_id": "ent_001",
      "name": "交换机",
      "category": "device",
      "must_have": true
    },
    {
      "entity_id": "ent_002",
      "name": "星型拓扑",
      "category": "topology",
      "must_have": true
    }
  ]
}
```

---

## 3.7 image_prompts.json

```json
{
  "node_uid": "uid_l4_001",
  "prompts": [
    {
      "prompt_id": "prompt_001",
      "image_type": "topology",
      "prompt": "生成一张星型拓扑施工示意图，必须出现交换机、终端A/B/C、星型连接线、端口标注，禁止泛化为抽象科技背景图。",
      "must_have_elements": [
        "交换机",
        "终端A",
        "终端B",
        "终端C",
        "星型连接"
      ],
      "forbidden_elements": [
        "纯装饰性背景",
        "无标注抽象网络图"
      ],
      "bind_anchor": "anchor_site_survey",
      "bind_section": "现场条件复核与放样准备"
    }
  ]
}
```

---

## 3.8 images.json

```json
{
  "node_uid": "uid_l4_001",
  "images": [
    {
      "image_id": "img_001",
      "type": "topology",
      "file": "images/img_001.png",
      "caption": "图1-1 星型拓扑与终端连接关系示意",
      "group_caption": null,
      "prompt_id": "prompt_001",
      "must_have_elements": ["交换机", "终端A", "终端B", "终端C"],
      "bind_anchor": "anchor_site_survey",
      "bind_section": "现场条件复核与放样准备",
      "retry_count": 1,
      "status": "PASS"
    }
  ]
}
```

### images.status 枚举
- PASS
- RETRYING
- NEED_MANUAL_CONFIRM
- FAILED

---

## 3.9 image_relevance.json

```json
{
  "node_uid": "uid_l4_001",
  "image_scores": [
    {
      "image_id": "img_001",
      "score": 0.81,
      "missing_elements": [],
      "result": "PASS"
    }
  ],
  "overall_result": "PASS"
}
```

---

## 3.10 tables.json

```json
{
  "node_uid": "uid_l4_001",
  "tables": [
    {
      "table_id": "table_01",
      "title": "主要设备配置表",
      "headers": ["设备名称", "型号", "数量", "安装位置"],
      "rows": [
        ["接入交换机", "S5735", "4", "弱电间"],
        ["配线架", "24口", "2", "机柜内"]
      ],
      "style_name": "BiddingTable",
      "bind_anchor": "anchor_equipment_list",
      "source_refs": ["p4#L12", "p5#L8"]
    }
  ]
}
```

---

## 3.11 consistency.json

```json
{
  "node_uid": "uid_l4_001",
  "result": "PASS",
  "checks": {
    "entity_consistency": {
      "result": "PASS",
      "issues": []
    },
    "term_consistency": {
      "result": "PASS",
      "issues": []
    },
    "constraint_consistency": {
      "result": "PASS",
      "issues": []
    },
    "reference_consistency": {
      "result": "PASS",
      "issues": []
    }
  }
}
```

---

## 3.12 metrics.json

```json
{
  "node_uid": "uid_l4_001",
  "word_count": 1890,
  "grounded_ratio": 0.86,
  "image_score_avg": 0.81,
  "image_retry_total": 1,
  "text_retry_total": 1,
  "fact_retry_total": 0,
  "duration_ms": 482000,
  "final_status": "NODE_DONE"
}
```

---

## 3.13 progress.json（可选缓存）
这个文件不是必须进 artifacts，但可选。

```json
{
  "task_id": "task_001",
  "total_progress": 0.54,
  "current_node_uid": "uid_l4_001",
  "current_stage": "IMAGE_VERIFYING",
  "completed_nodes": 6,
  "total_nodes": 12
}
```

---

## 4. Pydantic 模型建议

建议至少建立以下模型：
- `Task`
- `TOCVersion`
- `TOCNode`
- `NodeState`
- `EventLog`
- `RequirementDocument`
- `NodeText`
- `FactCheck`
- `EntityExtraction`
- `ImagePrompts`
- `ImagesArtifact`
- `TablesArtifact`
- `ConsistencyReport`
- `Metrics`

---

## 5. 枚举建议

### 5.1 ClaimType
- equipment
- quantity
- location
- interface
- parameter
- threshold
- standard
- duration
- acceptance
- process

### 5.2 AgentResult
- PASS
- FAIL
- RETRY
- MANUAL
- SKIP

### 5.3 ChatRole
- user
- assistant
- system

---

## 6. 索引与约束建议

### 6.1 唯一约束
- `task.task_id`
- `toc_version(task_id, version_no)`
- `node_state(task_id, node_uid)`
- `chat_message.message_id`
- `event_log.event_id`

### 6.2 常用索引
- `task(status, updated_at)`
- `node_state(task_id, status)`
- `event_log(task_id, created_at)`
- `event_log(task_id, node_uid, created_at)`
- `toc_node_snapshot(task_id, version_no, node_uid)`

---

## 7. 文件命名建议

- `requirement.json`
- `style_profile.json`
- `toc_v1.json`
- `toc_confirmed.json`
- `text.json`
- `fact_check.json`
- `entities.json`
- `image_prompts.json`
- `images.json`
- `image_relevance.json`
- `tables.json`
- `consistency.json`
- `metrics.json`
- `output.docx`

---

## 8. Schema 演进原则

1. 所有新增字段必须向后兼容
2. 不删除旧字段，优先标记 deprecated
3. 节点工件文件命名保持稳定
4. `node_uid` 不可变
5. 目录编号 `node_id` 可变
