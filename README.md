# Multi-LLM Doc Agent

V1 最小可运行实现，目标是把工程实施类 `.docx` 需求文档转换成可审阅、可修订、可导出的 `output.docx`。

当前前后端形态：
- 前端：React + Vite
- API：FastAPI
- 后台执行：Worker
- 元数据：SQLite
- 大工件：本地 `artifacts/{task_id}/...`

## 1. 功能范围

已实现的主链路：
1. 上传 `.docx`
2. 解析 `requirement.json`
3. 生成 TOC
4. TOC 修订与版本化
5. 确认并冻结 TOC
6. Worker 串行生成节点正文
7. 事实校验、长度控制、一致性检查、表格构建
8. 宽松模式图片闭环
9. Layout 中间块生成
10. 基于模板导出 `artifacts/{task_id}/final/output.docx`

当前不做的内容：
- Docker
- 分布式队列
- 多用户协作
- 深度多模态图像理解
- 复杂人工介入工作台

## 2. 目录结构

```text
backend/
  agents/           各阶段 agent
  api/              FastAPI 接口
  app_service/      服务层
  config/           配置与运行时初始化
  db/               SQLite 初始化
  models/           枚举与 Pydantic schema
  orchestrator/     任务编排与状态流转
  repositories/     数据访问层
  worker/           Worker 主循环与节点执行
ui/
  src/              React 页面
templates/
  standard_template.docx
artifacts/
  {task_id}/...
tests/
```

## 3. 环境要求

- Python 3.13
- Node.js 18+
- `pip`
- `npm`

安装依赖：

```bash
python -m pip install -r requirements.txt
cd ui && npm install
```

## 4. 配置

复制环境变量模板：

```bash
cp .env.example .env
```

当前支持的主要配置项：
- `APP_DB_PATH`
- `APP_ARTIFACTS_ROOT`
- `APP_TEMPLATE_PATH`
- `APP_SYSTEM_CONFIG_PATH`
- `APP_API_HOST`
- `APP_API_PORT`
- `APP_WORKER_POLL_INTERVAL_SEC`
- `VITE_API_BASE`

后端会自动读取根目录 `.env`。

## 5. 模板文件准备

默认模板路径：

```text
templates/standard_template.docx
```

模板至少应包含这些样式：
- `Heading 1`
- `Heading 2`
- `Heading 3`
- `Heading 4`
- `Normal`
- `BiddingTable`

如果模板缺失或损坏，导出阶段会报错并在事件日志中记录。

## 6. 初始化行为

首次启动时会自动完成：
- 创建 `app.db`
- 初始化 SQLite 表
- 创建 `artifacts/`
- 初始化 `artifacts/system_config.json` 的读取路径

注意：
- SQLite 仅存元数据
- 大段正文、JSON 工件、图片和最终文档都写入 `artifacts/`

## 7. 启动顺序

建议使用三个终端，按顺序启动。

### 7.1 启动 API

```bash
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 7.2 启动 Worker

```bash
./run_worker.sh
```

等价命令：

```bash
python -m backend.worker.main
```

### 7.3 启动 React UI

```bash
./run_ui.sh
```

等价命令：

```bash
cd ui
npm run dev
```

默认地址：
- UI: `http://localhost:5173`
- API: `http://localhost:8000`

## 8. 典型使用流程

1. 打开 React UI
2. 新建任务
3. 上传 `.docx`
4. 点击解析需求
5. 生成目录
6. 如有需要，提交目录修订意见
7. 点击确认目录并开始生成
8. 保持 Worker 运行
9. 任务完成后下载 `output.docx`

## 9. 如何上传 `.docx`

系统只正式支持 `.docx`：
- UI 上传时会拦截非 `.docx`
- API `/tasks/{task_id}/upload` 也会拦截非 `.docx`

上传后的原文件会写入：

```text
artifacts/{task_id}/input/
```

## 10. Worker 如何执行

Worker 负责所有长时间执行逻辑，包括：
- 节点生成
- 事实校验
- 图片闭环
- 一致性检查
- Layout
- Word 导出

V1 约束：
- 单任务串行
- 节点串行
- 图片失败采用宽松模式
- 图片失败不阻塞整个任务导出

只跑一轮轮询：

```bash
python -m backend.worker.main --once
```

## 11. 产物路径

典型任务目录：

```text
artifacts/{task_id}/
  input/
  parsed/
  toc/
  nodes/{node_uid}/
  final/output.docx
```

关键文件：
- `parsed/requirement.json`
- `parsed/parse_report.json`
- `toc/toc_vN.json`
- `toc/toc_confirmed.json`
- `nodes/{node_uid}/text.json`
- `nodes/{node_uid}/fact_check.json`
- `nodes/{node_uid}/image_relevance.json`
- `nodes/{node_uid}/metrics.json`
- `final/layout_blocks.json`
- `final/output.docx`

## 12. 测试

运行全部测试：

```bash
python -m unittest discover -s tests
```

当前覆盖：
- schema validation
- repository
- task/node state machine
- TOC versioning
- checkpoint / resume
- layout/export smoke
- image pipeline smoke
- 最小 e2e smoke

## 13. 当前限制

- 文本、TOC、图片仍以规则版 / mock agent 为主
- 图片相关性校验不是深度多模态理解
- 人工介入 UI 仍是预留入口，不是完整闭环
- Layout 目前只做基础分页和模板样式映射
- 复杂分页、多图矩阵、复杂浮动布局仍是 TODO

## 14. 主要 TODO

- 把人工介入入口接成真实 API 与 UI 闭环
- 把图片 provider 从 mock 替换为真实服务
- 加强恢复策略与异常分级
- 补更多 API 层测试和前端交互测试
- 补更细的 Word 视觉回归检查

