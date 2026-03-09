import { useEffect, useMemo, useState } from "react";

import {
  API_BASE,
  confirmAndStartGeneration,
  createTask,
  generateToc,
  getHealth,
  getSystemConfig,
  listLogs,
  listNodes,
  getParseReport,
  getToc,
  importTocOutline,
  listChat,
  listTasks,
  listTocVersions,
  outputUrl,
  reviewToc,
  updateSystemConfig,
  uploadDocx
} from "./api";
import "./styles.css";

const TEXT_MODEL_OPTIONS = [
  { label: "MiniMax-M2.5", modelName: "MiniMax-M2.5", provider: "minimax" }
];

const IMAGE_MODEL_OPTIONS = [
  { label: "MiniMax-M2.5", modelName: "MiniMax-M2.5", provider: "minimax" },
  { label: "Doubao-Seedream-5.0-lite", modelName: "Doubao-Seedream-5.0-lite", provider: "doubao" },
  { label: "Doubao-Seedream-4.5", modelName: "Doubao-Seedream-4.5", provider: "doubao" },
  { label: "Doubao-Seed3D-1.0", modelName: "Doubao-Seed3D-1.0", provider: "doubao" },
  { label: "Doubao-Seedream-4.0", modelName: "Doubao-Seedream-4.0", provider: "doubao" },
  { label: "Doubao-Seedream-3.0-t2i", modelName: "Doubao-Seedream-3.0-t2i", provider: "doubao" }
];

const DEFAULT_SYSTEM_CONFIG = {
  text_provider: TEXT_MODEL_OPTIONS[0].provider,
  image_provider: IMAGE_MODEL_OPTIONS[0].provider,
  text_model_name: TEXT_MODEL_OPTIONS[0].modelName,
  image_model_name: IMAGE_MODEL_OPTIONS[0].modelName,
  text_api_key: "",
  image_api_key: ""
};

const STATUS_CN = {
  NEW: "新建",
  PARSED: "已解析",
  TOC_REVIEW: "目录审阅中",
  GENERATING: "生成中",
  LAYOUTING: "排版中",
  EXPORTING: "导出中",
  DONE: "已完成",
  PAUSED: "已暂停",
  FAILED: "失败",
  PENDING: "待执行",
  TEXT_GENERATING: "正文生成中",
  TEXT_DONE: "正文已完成",
  FACT_CHECKING: "事实校验中",
  FACT_PASSED: "事实通过",
  IMAGE_GENERATING: "图片生成中",
  IMAGE_DONE: "图片已生成",
  IMAGE_VERIFYING: "图文校验中",
  IMAGE_VERIFIED: "图片校验完成",
  LENGTH_CHECKING: "字数检查中",
  LENGTH_PASSED: "字数通过",
  CONSISTENCY_CHECKING: "一致性检查中",
  READY_FOR_LAYOUT: "待排版",
  LAYOUTED: "已进入排版",
  NODE_DONE: "节点完成",
  NODE_FAILED: "节点失败",
  WAITING_MANUAL: "等待人工处理"
};

function statusCn(status) {
  return STATUS_CN[status] || status || "-";
}

function manualActionText(status) {
  if (!status || status === "NONE") {
    return "无";
  }
  if (status === "PENDING") {
    return "待人工确认";
  }
  if (status === "CONFIRMED") {
    return "已确认";
  }
  if (status === "SKIPPED") {
    return "已跳过";
  }
  if (status === "REGENERATED") {
    return "已重生成";
  }
  if (status === "FAILED") {
    return "人工处理失败";
  }
  return status;
}

function imageWarningText(node) {
  if (node.image_manual_required) {
    return "图片需人工确认";
  }
  if (node.manual_action_status && node.manual_action_status !== "NONE") {
    return `人工状态：${manualActionText(node.manual_action_status)}`;
  }
  return "-";
}

function countTocNodes(nodes) {
  if (!nodes || nodes.length === 0) {
    return 0;
  }
  return nodes.reduce(
    (total, node) => total + 1 + countTocNodes(node.children || []),
    0
  );
}

function getVisibleTocNodes(nodes) {
  if (!nodes || nodes.length === 0) {
    return [];
  }
  if (nodes.length === 1 && nodes[0].level === 1 && Array.isArray(nodes[0].children)) {
    return nodes[0].children;
  }
  return nodes;
}

function displayNodeId(nodeId) {
  if (!nodeId) {
    return "";
  }
  if (nodeId.startsWith("1.")) {
    return nodeId.slice(2);
  }
  return nodeId;
}

function normalizeSystemConfig(config) {
  const textOption =
    TEXT_MODEL_OPTIONS.find((item) => item.modelName === config?.text_model_name) ||
    TEXT_MODEL_OPTIONS.find((item) => item.provider === config?.text_provider) ||
    TEXT_MODEL_OPTIONS[0];

  const imageOption =
    IMAGE_MODEL_OPTIONS.find((item) => item.modelName === config?.image_model_name) ||
    IMAGE_MODEL_OPTIONS.find((item) => item.provider === config?.image_provider) ||
    IMAGE_MODEL_OPTIONS[0];

  const legacyApiKey = typeof config?.api_key === "string" ? config.api_key : "";

  return {
    text_provider: textOption.provider,
    image_provider: imageOption.provider,
    text_model_name: textOption.modelName,
    image_model_name: imageOption.modelName,
    text_api_key:
      typeof config?.text_api_key === "string" ? config.text_api_key : legacyApiKey,
    image_api_key:
      typeof config?.image_api_key === "string" ? config.image_api_key : legacyApiKey
  };
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
            {displayNodeId(node.node_id)} {node.title}
            {node.is_generation_unit ? <strong className="tag"> 生成单元</strong> : null}
          </span>
          {node.children?.length ? <TocTree nodes={node.children} /> : null}
        </li>
      ))}
    </ul>
  );
}

function upsertTocVersion(versions, nextVersion) {
  const filtered = versions.filter((item) => item.version_no !== nextVersion.version_no);
  return [nextVersion, ...filtered].sort((a, b) => b.version_no - a.version_no);
}

export default function App() {
  const [systemConfig, setSystemConfig] = useState(DEFAULT_SYSTEM_CONFIG);
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
  const [outlineText, setOutlineText] = useState("");
  const [nodeStates, setNodeStates] = useState([]);
  const [recentLogs, setRecentLogs] = useState([]);

  const [loading, setLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [busySince, setBusySince] = useState(0);
  const [switchingVersionNo, setSwitchingVersionNo] = useState(0);
  const [apiHealthy, setApiHealthy] = useState(true);
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
  const visibleTocNodes = useMemo(() => getVisibleTocNodes(tocDoc?.tree || []), [tocDoc]);

  const canReviewToc = selectedTask?.status === "TOC_REVIEW";
  const canImportToc =
    !!selectedTaskId &&
    (
      (selectedTask?.status === "NEW" && !!selectedTask?.upload_file_name) ||
      selectedTask?.status === "PARSED" ||
      selectedTask?.status === "TOC_REVIEW"
    );
  const tocNodeCount = useMemo(() => countTocNodes(visibleTocNodes), [visibleTocNodes]);
  const tocPreviewHeight = useMemo(
    () => Math.min(820, Math.max(280, tocNodeCount * 34)),
    [tocNodeCount]
  );
  const canBuildToc =
    !!selectedTaskId &&
    (
      (selectedTask?.status === "NEW" && !!selectedTask?.upload_file_name) ||
      selectedTask?.status === "PARSED"
    );
  const buildTocLabel =
    selectedTask?.status === "NEW"
      ? "1. 解析需求并生成目录（NEW -> TOC_REVIEW）"
      : "1. 生成目录（PARSED -> TOC_REVIEW）";
  const workerRuntimeHint = useMemo(() => {
    if (!selectedTask) {
      return null;
    }
    if (!["GENERATING", "LAYOUTING", "EXPORTING"].includes(selectedTask.status)) {
      return null;
    }
    if (!selectedTask.last_heartbeat_at) {
      return {
        level: "warning",
        text: "任务正在执行，但尚未收到心跳。请确认 worker 已启动。"
      };
    }

    const heartbeatTime = new Date(selectedTask.last_heartbeat_at).getTime();
    if (Number.isNaN(heartbeatTime)) {
      return {
        level: "warning",
        text: "任务心跳时间不可解析，请检查后端状态。"
      };
    }

    const idleSeconds = Math.floor((Date.now() - heartbeatTime) / 1000);
    if (idleSeconds >= 15) {
      return {
        level: "warning",
        text: `任务处于 ${statusCn(selectedTask.status)}，但已经 ${idleSeconds} 秒没有心跳更新，可能中断或 worker 卡住。`
      };
    }

    return {
      level: "info",
      text: `任务正在 ${statusCn(selectedTask.status)}，最近一次心跳是 ${idleSeconds} 秒前。`
    };
  }, [selectedTask, nodeStates, tasks]);

  async function withAction(fn, successMessage = "", activityLabel = "处理中") {
    setError("");
    setMessage("");
    setLoading(true);
    setBusyLabel(activityLabel);
    setBusySince(Date.now());
    try {
      const result = await fn();
      if (successMessage) setMessage(successMessage);
      return result;
    } catch (err) {
      setError(err.message || "操作失败");
      return null;
    } finally {
      setLoading(false);
      setBusyLabel("");
      setBusySince(0);
    }
  }

  async function loadTasks(defaultTaskId = "") {
    try {
      const result = await listTasks();
      setTasks(result);

      if (defaultTaskId) {
        setSelectedTaskId(defaultTaskId);
        return;
      }

      if (!selectedTaskId && result.length > 0) {
        setSelectedTaskId(result[0].task_id);
      }
    } catch (err) {
      setError(err.message || "任务列表加载失败");
    }
  }

  async function loadSystemConfigState() {
    try {
      const result = await getSystemConfig();
      setSystemConfig(normalizeSystemConfig(result));
    } catch (err) {
      setError(err.message || "系统配置加载失败");
    }
  }

  async function checkApiHealth() {
    try {
      await getHealth();
      setApiHealthy(true);
      return true;
    } catch {
      setApiHealthy(false);
      return false;
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

    let targetVersionNo = preferredVersionNo || selectedVersionNo;
    if (targetVersionNo && !versions.some((item) => item.version_no === targetVersionNo)) {
      targetVersionNo = 0;
    }
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
    loadSystemConfigState();
    checkApiHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadTaskContext(selectedTaskId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) return undefined;
    const timer = window.setInterval(() => {
      if (loading || configSaving) {
        return;
      }
      checkApiHealth();
      loadRuntimeData(selectedTaskId);
      listTasks()
        .then((items) => setTasks(items))
        .catch(() => {});
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedTaskId, loading, configSaving]);

  useEffect(() => {
    if (selectedTaskId) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (loading || configSaving) {
        return;
      }
      checkApiHealth();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [selectedTaskId, loading, configSaving]);

  async function handleCreateTask(event) {
    event.preventDefault();
    const created = await withAction(() => createTask(newTaskTitle), "任务已创建", "正在创建任务");
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

    const result = await withAction(
      () => uploadDocx(selectedTaskId, file),
      "上传成功",
      "正在上传 .docx 文件"
    );
    if (!result) return;
    await refreshCurrentTask();
  }

  async function handleGenerateToc() {
    if (!selectedTaskId) {
      setError("请先选择任务");
      return;
    }
    if (selectedTask?.status === "NEW" && !selectedTask?.upload_file_name) {
      setError("请先上传 .docx 文件");
      return;
    }

    const successMessage =
      selectedTask?.status === "NEW"
        ? "需求解析完成，目录已生成"
        : "目录已生成";
    const activityLabel =
      selectedTask?.status === "NEW"
        ? "正在解析需求并生成目录"
        : "正在生成目录";
    const result = await withAction(
      () => generateToc(selectedTaskId),
      successMessage,
      activityLabel
    );
    if (!result) return;
    await refreshCurrentTask(result.version_no);
  }

  async function handleSwitchVersion(versionNo) {
    if (!selectedTaskId || !versionNo) return;
    setError("");
    setSwitchingVersionNo(versionNo);
    try {
      const doc = await getToc(selectedTaskId, versionNo);
      setSelectedVersionNo(versionNo);
      setTocDoc(doc);
    } catch (err) {
      setError(err.message || "目录版本加载失败");
    } finally {
      setSwitchingVersionNo(0);
    }
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
      `已生成 toc_v${(tocVersions[0]?.version_no || 0) + 1}`,
      "正在生成新的目录版本"
    );
    if (!result) return;

    setFeedback("");

    if (result.toc_document) {
      setSelectedVersionNo(result.version_no);
      setTocDoc(result.toc_document);
    }
    setTocVersions((current) => upsertTocVersion(current, {
      toc_version_id: result.toc_version_id,
      task_id: result.task_id,
      version_no: result.version_no,
      file_path: result.file_path,
      based_on_version_no: result.based_on_version_no,
      is_confirmed: result.is_confirmed,
      diff_summary_json: result.diff_summary_json,
      created_by: result.created_by,
      created_at: result.created_at
    }));

    await loadTasks(selectedTaskId);
    try {
      const messages = await listChat(selectedTaskId);
      setChatMessages(messages);
    } catch {
      // Chat refresh is best-effort after review.
    }
  }

  async function handleImportToc(event) {
    event.preventDefault();
    if (!selectedTaskId) {
      setError("请先选择任务");
      return;
    }
    if (!outlineText.trim()) {
      setError("请先粘贴完整目录树");
      return;
    }

    const result = await withAction(
      () => importTocOutline(selectedTaskId, outlineText.trim(), selectedVersionNo || null),
      "完整目录树已导入",
      "正在导入完整目录树"
    );
    if (!result) return;

    setOutlineText("");

    if (result.toc_document) {
      setSelectedVersionNo(result.version_no);
      setTocDoc(result.toc_document);
    }
    setTocVersions((current) => upsertTocVersion(current, {
      toc_version_id: result.toc_version_id,
      task_id: result.task_id,
      version_no: result.version_no,
      file_path: result.file_path,
      based_on_version_no: result.based_on_version_no,
      is_confirmed: result.is_confirmed,
      diff_summary_json: result.diff_summary_json,
      created_by: result.created_by,
      created_at: result.created_at
    }));

    await refreshCurrentTask(result.version_no);
  }

  async function handleConfirmAndStart() {
    if (!selectedTaskId || !selectedVersionNo) {
      setError("请先选择目录版本");
      return;
    }

    const result = await withAction(
      () => confirmAndStartGeneration(selectedTaskId, selectedVersionNo),
      "目录已确认并已提交后台生成任务",
      "正在确认目录并开始生成内容"
    );
    if (!result) return;

    if (result.task) {
      setTasks((current) =>
        current.map((item) => (item.task_id === result.task.task_id ? result.task : item))
      );
    }
    await refreshCurrentTask(selectedVersionNo);
  }

  function handleSystemConfigChange(field, value) {
    if (field === "text_model_name") {
      const option = TEXT_MODEL_OPTIONS.find((item) => item.modelName === value) || TEXT_MODEL_OPTIONS[0];
      setSystemConfig((current) => ({
        ...current,
        text_model_name: option.modelName,
        text_provider: option.provider
      }));
      return;
    }

    if (field === "image_model_name") {
      const option = IMAGE_MODEL_OPTIONS.find((item) => item.modelName === value) || IMAGE_MODEL_OPTIONS[0];
      setSystemConfig((current) => ({
        ...current,
        image_model_name: option.modelName,
        image_provider: option.provider
      }));
      return;
    }

    setSystemConfig((current) => ({
      ...current,
      [field]: value
    }));
  }

  async function handleSaveSystemConfig(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusyLabel("正在检查后端服务");
    setBusySince(Date.now());
    const healthy = await checkApiHealth();
    if (!healthy) {
      setBusyLabel("");
      setBusySince(0);
      setError("后端 API 不可用，请启动或重启 uvicorn backend.api.main:app");
      return;
    }

    setConfigSaving(true);
    setBusyLabel("正在保存系统配置");
    setBusySince(Date.now());
    try {
      const saved = await updateSystemConfig({
        text_provider: systemConfig.text_provider,
        image_provider: systemConfig.image_provider,
        text_model_name: systemConfig.text_model_name,
        image_model_name: systemConfig.image_model_name,
        text_api_key: systemConfig.text_api_key,
        image_api_key: systemConfig.image_api_key
      });
      setSystemConfig(normalizeSystemConfig(saved));
      setMessage("系统配置已保存");
    } catch (err) {
      setError(err.message || "系统配置保存失败");
    } finally {
      setConfigSaving(false);
      setBusyLabel("");
      setBusySince(0);
    }
  }

  const diffSummary = selectedVersion?.diff_summary_json;
  const summary = diffSummary?.summary || {};

  return (
    <div className="page">
      <header className="header">
        <h1>Multi-Agent 文档生成系统</h1>
        <p>当前页面覆盖系统配置、上传、解析、目录冻结、后台生成和最终 output.docx 下载。</p>
        <p>API: {API_BASE}</p>
      </header>

      {!apiHealthy ? (
        <div className="banner error">
          后端 API 当前不可用。请启动或重启 `uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000`
        </div>
      ) : null}

      {(loading || configSaving) && busyLabel ? (
        <div className="loading-overlay" role="status" aria-live="polite">
          <div className="loading-box">
            <div className="loading-spinner" />
            <div>
              <strong>{busyLabel}</strong>
              <p>请等待当前动作完成。若长时间无响应，请检查 API 或 Worker 进程。</p>
              {busySince ? (
                <p className="muted-note">
                  已持续 {Math.max(1, Math.floor((Date.now() - busySince) / 1000))} 秒
                </p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {message ? <div className="banner success">{message}</div> : null}
      {error ? <div className="banner error">{error}</div> : null}

      <section className="card config-card">
        <details className="config-panel">
          <summary className="config-summary">
            <div>
              <h2>系统配置区</h2>
              <p>选择文本模型、图片模型及各自 API Key，保存到本地系统配置。</p>
            </div>
            <span className="summary-meta">
              文本：{systemConfig.text_model_name} | 图片：{systemConfig.image_model_name}
            </span>
          </summary>

          <form className="stack config-form" onSubmit={handleSaveSystemConfig}>
            <div className="grid-2">
              <label>
                文本模型
                <select
                  value={systemConfig.text_model_name}
                  onChange={(e) => handleSystemConfigChange("text_model_name", e.target.value)}
                  disabled={configSaving}
                >
                  {TEXT_MODEL_OPTIONS.map((item) => (
                    <option key={item.modelName} value={item.modelName}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                图片模型
                <select
                  value={systemConfig.image_model_name}
                  onChange={(e) => handleSystemConfigChange("image_model_name", e.target.value)}
                  disabled={configSaving}
                >
                  {IMAGE_MODEL_OPTIONS.map((item) => (
                    <option key={item.modelName} value={item.modelName}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="full-width">
                文本模型 API Key
                <input
                  type="password"
                  value={systemConfig.text_api_key}
                  onChange={(e) => handleSystemConfigChange("text_api_key", e.target.value)}
                  placeholder="输入文本模型 API Key"
                  autoComplete="off"
                  disabled={configSaving}
                />
              </label>

              <label className="full-width">
                图片模型 API Key
                <input
                  type="password"
                  value={systemConfig.image_api_key}
                  onChange={(e) => handleSystemConfigChange("image_api_key", e.target.value)}
                  placeholder="输入图片模型 API Key"
                  autoComplete="off"
                  disabled={configSaving}
                />
              </label>
            </div>

            <div className="config-actions">
              <span className="muted-note">保存后，新建任务会默认继承当前系统配置。</span>
              <button type="submit" disabled={configSaving}>
                {configSaving ? "保存中..." : "保存配置"}
              </button>
            </div>
          </form>
        </details>
      </section>

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
            onClick={handleGenerateToc}
            disabled={loading || !canBuildToc}
          >
            {buildTocLabel}
          </button>
          <button
            type="button"
            onClick={handleConfirmAndStart}
            disabled={loading || !canReviewToc || !selectedVersionNo}
          >
            2. 确认目录 / 开始生成内容
          </button>
        </div>
      </section>

      <section className="card">
        <h2>当前任务状态</h2>
        {selectedTask ? (
          <>
            {workerRuntimeHint ? (
              <div className={`banner ${workerRuntimeHint.level}`}>
                {workerRuntimeHint.text}
              </div>
            ) : null}
            {nodeStates.some((node) => node.image_manual_required) ? (
              <div className="banner warning">
                存在图片需人工确认的节点。当前为宽松模式，任务仍可继续排版与导出；人工确认入口预留在节点状态区。
              </div>
            ) : null}
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

            <div className="output-panel">
              <div>
                <strong>输出文件</strong>
                <p className="muted-note">
                  稳定输出路径：artifacts/{selectedTask.task_id}/final/output.docx
                </p>
              </div>
              {selectedTask.status === "DONE" ? (
                <a
                  className="download-link"
                  href={outputUrl(selectedTask.task_id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  下载 output.docx
                </a>
              ) : (
                <p className="muted-note">
                  任务完成后可下载最终 Word 文档。
                </p>
              )}
            </div>
          </>
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
                  <th>图片告警</th>
                  <th>进度</th>
                  <th>心跳</th>
                </tr>
              </thead>
              <tbody>
                {nodeStates.map((node) => (
                  <tr key={node.node_uid}>
                    <td>{displayNodeId(node.node_id)}</td>
                    <td>{node.title}</td>
                    <td>{statusCn(node.status)}</td>
                    <td>{statusCn(node.current_stage)}</td>
                    <td>
                      <div>{imageWarningText(node)}</div>
                      {node.image_manual_required ? (
                        <span className="warn-tag">人工确认入口预留</span>
                      ) : null}
                    </td>
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
        {!canReviewToc && !canImportToc && selectedTask ? (
          <p className="muted-note">
            当前任务不在 TOC_REVIEW 阶段，目录已锁定或尚未进入目录审阅阶段。
          </p>
        ) : null}
        {canImportToc ? (
          <p className="muted-note">
            自动生成目录不正确时，可以直接粘贴完整目录树导入。系统会在必要时先完成需求解析，再生成新的 toc 版本。
          </p>
        ) : null}

        <div className="layout toc-layout">
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
                  disabled={switchingVersionNo === item.version_no}
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

            <form className="stack" onSubmit={handleImportToc}>
              <label>
                直接导入完整目录树
                <textarea
                  rows={12}
                  value={outlineText}
                  onChange={(e) => setOutlineText(e.target.value)}
                  disabled={loading || !canImportToc}
                  placeholder={"例如：\n一、售后服务总体方案\n1.1 售后服务目标\n1.1.1 保障系统安全稳定运行"}
                />
              </label>
              <button type="submit" disabled={loading || !canImportToc}>
                导入完整目录树并生成新版本
              </button>
            </form>
          </div>

          <div>
            <h3>目录树预览</h3>
            <div
              className="toc-preview-panel"
              style={{ minHeight: `${tocPreviewHeight}px` }}
            >
              {visibleTocNodes.length > 0 ? <TocTree nodes={visibleTocNodes} /> : <p>请选择目录版本查看。</p>}
            </div>
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
