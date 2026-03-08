import { useEffect, useMemo, useState } from "react";

import {
  API_BASE,
  confirmToc,
  createTask,
  generateToc,
  listLogs,
  listNodes,
  getParseReport,
  getToc,
  listChat,
  listTasks,
  listTocVersions,
  parseRequirement,
  reviewToc,
  startGeneration,
  uploadDocx
} from "./api";
import "./styles.css";

const STATUS_CN = {
  NEW: "新建",
  PARSED: "已解析",
  TOC_REVIEW: "目录审阅中",
  GENERATING: "生成中",
  LAYOUTING: "排版中",
  EXPORTING: "导出中",
  DONE: "已完成",
  PAUSED: "已暂停",
  FAILED: "失败"
};

function statusCn(status) {
  return STATUS_CN[status] || status || "-";
}

function TocTree({ nodes }) {
  if (!nodes || nodes.length === 0) {
    return <p>暂无目录内容。</p>;
  }

  return (
    <ul className="toc-tree">
      {nodes.map((node) => (
        <li key={node.node_uid}>
          <span>
            {node.node_id} {node.title}
            {node.is_generation_unit ? <strong className="tag"> 生成单元</strong> : null}
          </span>
          {node.children?.length ? <TocTree nodes={node.children} /> : null}
        </li>
      ))}
    </ul>
  );
}

export default function App() {
  const [tasks, setTasks] = useState([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [newTaskTitle, setNewTaskTitle] = useState("目录审阅任务");

  const [file, setFile] = useState(null);
  const [parseReport, setParseReport] = useState(null);

  const [tocVersions, setTocVersions] = useState([]);
  const [selectedVersionNo, setSelectedVersionNo] = useState(0);
  const [tocDoc, setTocDoc] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [feedback, setFeedback] = useState("");
  const [nodeStates, setNodeStates] = useState([]);
  const [recentLogs, setRecentLogs] = useState([]);

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selectedTask = useMemo(
    () => tasks.find((item) => item.task_id === selectedTaskId) || null,
    [tasks, selectedTaskId]
  );

  const selectedVersion = useMemo(
    () => tocVersions.find((item) => item.version_no === selectedVersionNo) || null,
    [tocVersions, selectedVersionNo]
  );

  const canReviewToc = selectedTask?.status === "TOC_REVIEW";

  async function withAction(fn, successMessage = "") {
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const result = await fn();
      if (successMessage) setMessage(successMessage);
      return result;
    } catch (err) {
      setError(err.message || "操作失败");
      return null;
    } finally {
      setLoading(false);
    }
  }

  async function loadTasks(defaultTaskId = "") {
    const result = await withAction(() => listTasks());
    if (!result) return;
    setTasks(result);

    if (defaultTaskId) {
      setSelectedTaskId(defaultTaskId);
      return;
    }

    if (!selectedTaskId && result.length > 0) {
      setSelectedTaskId(result[0].task_id);
    }
  }

  async function loadTaskContext(taskId, preferredVersionNo = 0) {
    if (!taskId) {
      setParseReport(null);
      setTocVersions([]);
      setSelectedVersionNo(0);
      setTocDoc(null);
      setChatMessages([]);
      setNodeStates([]);
      setRecentLogs([]);
      return;
    }

    try {
      const report = await getParseReport(taskId);
      setParseReport(report);
    } catch {
      setParseReport(null);
    }

    let versions = [];
    try {
      versions = await listTocVersions(taskId);
    } catch {
      versions = [];
    }
    setTocVersions(versions);

    let targetVersionNo = preferredVersionNo;
    if (!targetVersionNo && versions.length > 0) {
      targetVersionNo = versions[0].version_no;
    }

    if (targetVersionNo) {
      try {
        const doc = await getToc(taskId, targetVersionNo);
        setTocDoc(doc);
        setSelectedVersionNo(targetVersionNo);
      } catch {
        setSelectedVersionNo(0);
        setTocDoc(null);
      }
    } else {
      setSelectedVersionNo(0);
      setTocDoc(null);
    }

    try {
      const messages = await listChat(taskId);
      setChatMessages(messages);
    } catch {
      setChatMessages([]);
    }

    await loadRuntimeData(taskId);
  }

  async function loadRuntimeData(taskId) {
    if (!taskId) {
      setNodeStates([]);
      setRecentLogs([]);
      return;
    }
    try {
      const [nodes, logs] = await Promise.all([
        listNodes(taskId),
        listLogs(taskId, 30)
      ]);
      setNodeStates(nodes);
      setRecentLogs(logs);
    } catch {
      // Runtime polling should be best-effort.
    }
  }

  async function refreshCurrentTask(preferredVersionNo = 0) {
    if (!selectedTaskId) return;
    await loadTasks(selectedTaskId);
    await loadTaskContext(selectedTaskId, preferredVersionNo);
  }

  useEffect(() => {
    loadTasks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadTaskContext(selectedTaskId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) return undefined;
    const timer = window.setInterval(() => {
      loadRuntimeData(selectedTaskId);
      listTasks()
        .then((items) => setTasks(items))
        .catch(() => {});
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedTaskId]);

  async function handleCreateTask(event) {
    event.preventDefault();
    const created = await withAction(() => createTask(newTaskTitle), "任务已创建");
    if (!created) return;
    await loadTasks(created.task_id);
    await loadTaskContext(created.task_id);
  }

  function handleFileChange(event) {
    const selected = event.target.files?.[0] || null;
    if (!selected) {
      setFile(null);
      return;
    }
    if (!selected.name.toLowerCase().endsWith(".docx")) {
      setError("仅支持 .docx 文件");
      setFile(null);
      event.target.value = "";
      return;
    }
    setError("");
    setFile(selected);
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (!selectedTaskId) {
      setError("请先选择任务");
      return;
    }
    if (!file) {
      setError("请先选择 .docx 文件");
      return;
    }

    const result = await withAction(() => uploadDocx(selectedTaskId, file), "上传成功");
    if (!result) return;
    await refreshCurrentTask();
  }

  async function handleParse() {
    if (!selectedTaskId) {
      setError("请先选择任务");
      return;
    }

    const result = await withAction(
      () => parseRequirement(selectedTaskId),
      "解析完成，已生成 requirement.json 与 parse_report.json"
    );
    if (!result) return;

    setParseReport(result.parse_report || null);
    await refreshCurrentTask();
  }

  async function handleGenerateToc() {
    if (!selectedTaskId) {
      setError("请先选择任务");
      return;
    }

    const result = await withAction(() => generateToc(selectedTaskId), "目录 toc_v1 已生成");
    if (!result) return;
    await refreshCurrentTask(result.version_no);
  }

  async function handleSwitchVersion(versionNo) {
    if (!selectedTaskId || !versionNo) return;
    const doc = await withAction(() => getToc(selectedTaskId, versionNo));
    if (!doc) return;
    setSelectedVersionNo(versionNo);
    setTocDoc(doc);
  }

  async function handleReviewToc(event) {
    event.preventDefault();
    if (!selectedTaskId || !selectedVersionNo) {
      setError("请先选择目录版本");
      return;
    }
    if (!feedback.trim()) {
      setError("请填写目录修改意见");
      return;
    }

    const result = await withAction(
      () => reviewToc(selectedTaskId, feedback.trim(), selectedVersionNo),
      `已生成 toc_v${(tocVersions[0]?.version_no || 0) + 1}`
    );
    if (!result) return;

    setFeedback("");
    await refreshCurrentTask(result.version_no);
  }

  async function handleConfirmAndStart() {
    if (!selectedTaskId || !selectedVersionNo) {
      setError("请先选择目录版本");
      return;
    }

    const confirmed = await withAction(
      () => confirmToc(selectedTaskId, selectedVersionNo),
      "目录已确认并冻结"
    );
    if (!confirmed) return;

    await withAction(
      () => startGeneration(selectedTaskId),
      "已提交后台 Worker，请确保 worker 进程正在运行"
    );
    await refreshCurrentTask(selectedVersionNo);
  }

  const diffSummary = selectedVersion?.diff_summary_json;
  const summary = diffSummary?.summary || {};

  return (
    <div className="page">
      <header className="header">
        <h1>Multi-Agent 文档生成系统（第 4 轮：目录闭环）</h1>
        <p>实现上传、解析、目录版本化修订、目录冻结与生成启动约束。</p>
        <p>API: {API_BASE}</p>
      </header>

      {message ? <div className="banner success">{message}</div> : null}
      {error ? <div className="banner error">{error}</div> : null}

      <section className="card">
        <h2>任务与上传</h2>
        <div className="layout">
          <form className="stack" onSubmit={handleCreateTask}>
            <label>
              新任务标题
              <input
                value={newTaskTitle}
                onChange={(e) => setNewTaskTitle(e.target.value)}
                placeholder="输入任务标题"
              />
            </label>
            <button type="submit" disabled={loading}>
              创建任务
            </button>
          </form>

          <div className="stack">
            <label>
              选择任务
              <select
                value={selectedTaskId}
                onChange={(e) => setSelectedTaskId(e.target.value)}
                disabled={loading}
              >
                <option value="">请选择任务</option>
                {tasks.map((task) => (
                  <option key={task.task_id} value={task.task_id}>
                    {task.task_id} | {task.title} | {statusCn(task.status)}
                  </option>
                ))}
              </select>
            </label>

            <form className="stack" onSubmit={handleUpload}>
              <label>
                上传需求文档（仅 .docx）
                <input
                  type="file"
                  accept=".docx"
                  onChange={handleFileChange}
                  disabled={loading || !selectedTaskId}
                />
              </label>
              <button type="submit" disabled={loading || !selectedTaskId || !file}>
                保存上传文件
              </button>
            </form>
          </div>
        </div>
      </section>

      <section className="card">
        <h2>阶段操作</h2>
        <div className="actions">
          <button
            type="button"
            onClick={handleParse}
            disabled={loading || !selectedTaskId || selectedTask?.status !== "NEW"}
          >
            1. 执行 Requirement 解析（NEW -&gt; PARSED）
          </button>
          <button
            type="button"
            onClick={handleGenerateToc}
            disabled={loading || !selectedTaskId || selectedTask?.status !== "PARSED"}
          >
            2. 生成目录（PARSED -&gt; TOC_REVIEW）
          </button>
          <button
            type="button"
            onClick={handleConfirmAndStart}
            disabled={loading || !canReviewToc || !selectedVersionNo}
          >
            3. 确认目录 / 开始生成内容
          </button>
        </div>
      </section>

      <section className="card">
        <h2>当前任务状态</h2>
        {selectedTask ? (
          <div className="stats">
            <div>任务ID：{selectedTask.task_id}</div>
            <div>标题：{selectedTask.title}</div>
            <div>状态：{statusCn(selectedTask.status)}</div>
            <div>当前阶段：{selectedTask.current_stage || "-"}</div>
            <div>当前节点：{selectedTask.current_node_uid || "-"}</div>
            <div>确认目录版本：{selectedTask.confirmed_toc_version || "-"}</div>
            <div>上传文件：{selectedTask.upload_file_name || "-"}</div>
            <div>最近错误：{selectedTask.latest_error || "-"}</div>
            <div>总进度：{Math.round((selectedTask.total_progress || 0) * 100)}%</div>
            <div>
              节点进度：{selectedTask.completed_nodes || 0}/{selectedTask.total_nodes || 0}
            </div>
            <div>任务心跳：{selectedTask.last_heartbeat_at || "-"}</div>
          </div>
        ) : (
          <p>请先选择任务。</p>
        )}
      </section>

      <section className="card">
        <h2>节点执行状态</h2>
        {nodeStates.length === 0 ? (
          <p>暂无节点状态。</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>节点</th>
                  <th>标题</th>
                  <th>状态</th>
                  <th>阶段</th>
                  <th>进度</th>
                  <th>心跳</th>
                </tr>
              </thead>
              <tbody>
                {nodeStates.map((node) => (
                  <tr key={node.node_uid}>
                    <td>{node.node_id}</td>
                    <td>{node.title}</td>
                    <td>{node.status}</td>
                    <td>{node.current_stage || "-"}</td>
                    <td>{Math.round((node.progress || 0) * 100)}%</td>
                    <td>{node.last_heartbeat_at || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h2>最近日志</h2>
        {recentLogs.length === 0 ? (
          <p>暂无日志。</p>
        ) : (
          <div className="log-box">
            {recentLogs.map((log) => (
              <p key={log.event_id}>
                [{log.created_at}] [{log.stage}] [{log.status}] {log.message}
              </p>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h2>目录版本与审阅</h2>
        {!canReviewToc && selectedTask ? (
          <p className="muted-note">
            当前任务不在 TOC_REVIEW 阶段，目录已锁定或尚未进入目录审阅阶段。
          </p>
        ) : null}

        <div className="layout">
          <div>
            <h3>版本列表</h3>
            {tocVersions.length === 0 ? <p>暂无目录版本。</p> : null}
            <div className="version-list">
              {tocVersions.map((item) => (
                <button
                  key={item.toc_version_id}
                  type="button"
                  className={item.version_no === selectedVersionNo ? "version-btn active" : "version-btn"}
                  onClick={() => handleSwitchVersion(item.version_no)}
                  disabled={loading}
                >
                  toc_v{item.version_no}
                  {item.is_confirmed ? "（已确认）" : ""}
                  {item.based_on_version_no ? ` <- v${item.based_on_version_no}` : ""}
                </button>
              ))}
            </div>

            <h3>版本差异摘要</h3>
            {diffSummary ? (
              <ul>
                <li>新增节点：{summary.add_count || 0}</li>
                <li>删除节点：{summary.remove_count || 0}</li>
                <li>标题变更：{summary.title_change_count || 0}</li>
                <li>顺序变化：{summary.reorder_count || 0}</li>
              </ul>
            ) : (
              <p>当前版本无 diff（通常是首版）。</p>
            )}

            <form className="stack" onSubmit={handleReviewToc}>
              <label>
                提交目录修改意见（基于当前选中版本）
                <textarea
                  rows={4}
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  disabled={loading || !canReviewToc || !selectedVersionNo}
                  placeholder="例如：新增施工准备章节；调整章节顺序；修改第一个三级标题"
                />
              </label>
              <button type="submit" disabled={loading || !canReviewToc || !selectedVersionNo}>
                提交审阅意见并生成新版本
              </button>
            </form>
          </div>

          <div>
            <h3>目录树预览</h3>
            {tocDoc?.tree ? <TocTree nodes={tocDoc.tree} /> : <p>请选择目录版本查看。</p>}
          </div>
        </div>
      </section>

      <section className="card">
        <h2>目录审阅聊天记录</h2>
        {chatMessages.length === 0 ? (
          <p>暂无聊天记录。</p>
        ) : (
          <div className="log-box">
            {chatMessages.map((msg) => (
              <p key={msg.message_id}>
                [{msg.role}] {msg.content}
                {msg.related_toc_version ? ` (v${msg.related_toc_version})` : ""}
              </p>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h2>parse_report 预览</h2>
        {parseReport ? <pre>{JSON.stringify(parseReport, null, 2)}</pre> : <p>暂无解析报告。</p>}
      </section>
    </div>
  );
}
