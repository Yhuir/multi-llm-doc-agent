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
  getTocWordBudget,
  importTocOutline,
  listChat,
  listTasks,
  listTocVersions,
  outputUrl,
  reviewToc,
  updateTocWordBudget,
  updateSystemConfig,
  uploadDocx
} from "./api";
import "./styles.css";

const TEXT_MODEL_OPTIONS = [
  { label: "MiniMax-M2.5", modelName: "MiniMax-M2.5", provider: "minimax" },
  { label: "gemini-3.1-pro-preview", modelName: "gemini-3.1-pro-preview", provider: "whatai" }
];

const IMAGE_MODEL_OPTIONS = [
  { label: "关闭图像生成", modelName: "关闭图像生成", provider: "disabled" },
  { label: "MiniMax-M2.5", modelName: "MiniMax-M2.5", provider: "minimax" },
  { label: "nano-banana", modelName: "nano-banana", provider: "whatai" },
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
  if (
    nodes.length === 1 &&
    nodes[0].level <= 1 &&
    Array.isArray(nodes[0].children)
  ) {
    return nodes[0].children;
  }
  return nodes;
}

function displayNodeId(nodeId) {
  return nodeId || "";
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

function buildWordBudgetInputState(document) {
  return (document?.chapters || []).reduce((acc, item) => {
    acc[item.chapter_node_uid] = String(item.target_total_pages || item.default_total_pages || "");
    return acc;
  }, {});
}

function TocWordBudgetTree({ nodes, budgetMap, inputValues, onChange }) {
  if (!nodes || nodes.length === 0) {
    return <p className="empty-note">暂无目录内容。</p>;
  }

  return (
    <ul className="toc-tree word-budget-tree">
      {nodes.map((node) => {
        const budgetItem = budgetMap[node.node_uid];
        return (
          <li key={node.node_uid}>
            <div className="budget-tree-line">
              <span>
                {displayNodeId(node.node_id)} {node.title}
                {node.is_generation_unit ? <strong className="tag"> 生成单元</strong> : null}
              </span>
              {budgetItem ? (
                <label className="budget-input-group">
                  <span>总页数</span>
                  <input
                    type="number"
                    min={2}
                    step="1"
                    value={inputValues[budgetItem.chapter_node_uid] ?? ""}
                    onChange={(event) =>
                      onChange(budgetItem.chapter_node_uid, event.target.value)
                    }
                  />
                </label>
              ) : null}
            </div>
            {budgetItem ? (
              <p className="budget-tree-note">
                覆盖 {budgetItem.generation_unit_count} 个生成单元，默认 {budgetItem.default_total_pages} 页。
              </p>
            ) : null}
            {node.children?.length ? (
              <TocWordBudgetTree
                nodes={node.children}
                budgetMap={budgetMap}
                inputValues={inputValues}
                onChange={onChange}
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function CollapsedRail({ side, title, subtitle, onExpand }) {
  return (
    <div className={`sidebar-rail ${side}`}>
      <button type="button" className="rail-trigger" onClick={onExpand}>
        <span>{subtitle}</span>
        <strong>{title}</strong>
      </button>
    </div>
  );
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
  const [busyScope, setBusyScope] = useState("");
  const [, setBusySince] = useState(0);
  const [switchingVersionNo, setSwitchingVersionNo] = useState(0);
  const [apiHealthy, setApiHealthy] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [outlineModalOpen, setOutlineModalOpen] = useState(false);
  const [wordBudgetModalOpen, setWordBudgetModalOpen] = useState(false);
  const [wordBudgetDoc, setWordBudgetDoc] = useState(null);
  const [wordBudgetInputs, setWordBudgetInputs] = useState({});

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
    () => Math.min(680, Math.max(360, tocNodeCount * 26)),
    [tocNodeCount]
  );
  const canBuildToc =
    !!selectedTaskId &&
    (
      (selectedTask?.status === "NEW" && !!selectedTask?.upload_file_name) ||
      selectedTask?.status === "PARSED"
    );
  const canAdjustWordBudget =
    !!selectedTaskId &&
    !!selectedVersionNo &&
    selectedTask?.status === "TOC_REVIEW";
  const buildTocLabel =
    selectedTask?.status === "NEW"
      ? "1. 解析需求并生成目录（NEW -> TOC_REVIEW）"
      : "1. 生成目录（PARSED -> TOC_REVIEW）";
  const wordBudgetMap = useMemo(
    () =>
      (wordBudgetDoc?.chapters || []).reduce((acc, item) => {
        acc[item.chapter_node_uid] = item;
        return acc;
      }, {}),
    [wordBudgetDoc]
  );
  const estimatedWordBudgetTotal = useMemo(
    () =>
      (wordBudgetDoc?.chapters || []).reduce((total, item) => {
        const rawValue = wordBudgetInputs[item.chapter_node_uid];
        const parsed = Number.parseInt(rawValue, 10);
        const nextValue = Number.isInteger(parsed) ? parsed : item.target_total_pages;
        return total + nextValue;
      }, 0),
    [wordBudgetDoc, wordBudgetInputs]
  );
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

  function isBusyForScope(scopes) {
    return Boolean(busyLabel) && scopes.includes(busyScope);
  }

  async function withAction(
    fn,
    successMessage = "",
    activityLabel = "处理中",
    activityScope = "global"
  ) {
    setError("");
    setMessage("");
    setLoading(true);
    setBusyLabel(activityLabel);
    setBusyScope(activityScope);
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
      setBusyScope("");
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
      setWordBudgetDoc(null);
      setWordBudgetInputs({});
      setWordBudgetModalOpen(false);
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
        setWordBudgetDoc(null);
        setWordBudgetInputs({});
      } catch {
        setSelectedVersionNo(0);
        setTocDoc(null);
        setWordBudgetDoc(null);
        setWordBudgetInputs({});
      }
    } else {
      setSelectedVersionNo(0);
      setTocDoc(null);
      setWordBudgetDoc(null);
      setWordBudgetInputs({});
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

  useEffect(() => {
    if (!outlineModalOpen && !wordBudgetModalOpen) {
      return undefined;
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setOutlineModalOpen(false);
        setWordBudgetModalOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [outlineModalOpen, wordBudgetModalOpen]);

  async function handleCreateTask(event) {
    event.preventDefault();
    const created = await withAction(
      () => createTask(newTaskTitle),
      "任务已创建",
      "正在创建任务",
      "task"
    );
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
      "正在上传 .docx 文件",
      "upload"
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
      activityLabel,
      "toc"
    );
    if (!result) return;
    setWordBudgetModalOpen(false);
    setWordBudgetDoc(null);
    setWordBudgetInputs({});
    await refreshCurrentTask(result.version_no);
  }

  async function handleSwitchVersion(versionNo) {
    if (!selectedTaskId || !versionNo) return;
    setError("");
    setSwitchingVersionNo(versionNo);
    setWordBudgetModalOpen(false);
    setWordBudgetDoc(null);
    setWordBudgetInputs({});
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
      "正在生成新的目录版本",
      "review"
    );
    if (!result) return;

    setFeedback("");
    setWordBudgetModalOpen(false);
    setWordBudgetDoc(null);
    setWordBudgetInputs({});

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
      "正在导入完整目录树",
      "import"
    );
    if (!result) return;

    setOutlineText("");
    setOutlineModalOpen(false);
    setWordBudgetModalOpen(false);
    setWordBudgetDoc(null);
    setWordBudgetInputs({});

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

  async function handleOpenWordBudgetModal() {
    if (!selectedTaskId || !selectedVersionNo) {
      setError("请先选择目录版本");
      return;
    }

    const result = await withAction(
      () => getTocWordBudget(selectedTaskId, selectedVersionNo),
      "",
      "正在加载目录页面配置",
      "word-budget"
    );
    if (!result) return;

    setWordBudgetDoc(result);
    setWordBudgetInputs(buildWordBudgetInputState(result));
    setWordBudgetModalOpen(true);
  }

  function handleWordBudgetInputChange(chapterNodeUid, value) {
    setWordBudgetInputs((current) => ({
      ...current,
      [chapterNodeUid]: value
    }));
  }

  async function handleSaveWordBudget(event) {
    event.preventDefault();
    if (!selectedTaskId || !selectedVersionNo || !wordBudgetDoc) {
      setError("请先选择目录版本");
      return;
    }

    const chapters = [];
    for (const item of wordBudgetDoc.chapters || []) {
      const rawValue = String(wordBudgetInputs[item.chapter_node_uid] || "").trim();
      const parsed = Number.parseInt(rawValue, 10);
      if (!Number.isInteger(parsed) || parsed <= 1) {
        setError(`${item.chapter_title} 的页数必须是大于 1 的整数`);
        return;
      }
      chapters.push({
        chapter_node_uid: item.chapter_node_uid,
        target_total_pages: parsed
      });
    }

    const result = await withAction(
      () => updateTocWordBudget(selectedTaskId, selectedVersionNo, chapters),
      "目录页面目标已保存",
      "正在保存目录页面目标",
      "word-budget"
    );
    if (!result) return;

    setWordBudgetDoc(result);
    setWordBudgetInputs(buildWordBudgetInputState(result));
    setWordBudgetModalOpen(false);
  }

  async function handleConfirmAndStart() {
    if (!selectedTaskId || !selectedVersionNo) {
      setError("请先选择目录版本");
      return;
    }

    const result = await withAction(
      () => confirmAndStartGeneration(selectedTaskId, selectedVersionNo),
      "目录已确认并已提交后台生成任务",
      "正在确认目录并开始生成内容",
      "confirm"
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
    setBusyScope("config");
    setBusySince(Date.now());
    const healthy = await checkApiHealth();
    if (!healthy) {
      setBusyLabel("");
      setBusyScope("");
      setBusySince(0);
      setError("后端 API 不可用，请启动或重启 uvicorn backend.api.main:app");
      return;
    }

    setConfigSaving(true);
    setBusyLabel("正在保存系统配置");
    setBusyScope("config");
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
      setBusyScope("");
      setBusySince(0);
    }
  }

  const diffSummary = selectedVersion?.diff_summary_json;
  const summary = diffSummary?.summary || {};
  const parseReportHighlights = parseReport
    ? [
        { label: "段落数", value: parseReport.paragraph_count ?? "-" },
        { label: "招标项", value: parseReport.bidding_requirement_count ?? "-" },
        { label: "缺失项", value: parseReport.missing_fields?.length ?? 0 },
      ]
    : [];

  return (
    <div className="page">
      <header className="header workspace-header">
        <div>
          <p className="eyebrow">Engineering Document Studio</p>
          <h1>Multi-Agent 文档生成系统</h1>
          <p>左侧管理配置与日志，中间持续查看目录树和节点状态，右侧完成上传、指令输入和生成控制。</p>
        </div>
        <div className="header-badges">
          <span className={`header-badge ${apiHealthy ? "healthy" : "offline"}`}>
            {apiHealthy ? "API 在线" : "API 不可用"}
          </span>
          <span className="header-badge subtle">API: {API_BASE}</span>
          {selectedTask ? (
            <span className="header-badge subtle">
              当前任务：{selectedTask.title} · {statusCn(selectedTask.status)}
            </span>
          ) : null}
        </div>
      </header>

      {!apiHealthy ? (
        <div className="banner error">
          后端 API 当前不可用。请启动或重启 `uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000`
        </div>
      ) : null}

      {message ? <div className="banner success">{message}</div> : null}
      {error ? <div className="banner error">{error}</div> : null}
      <div
        className={`workspace-shell${leftCollapsed ? " left-collapsed" : ""}${rightCollapsed ? " right-collapsed" : ""}`}
      >
        <aside className={`side-panel left-panel ${leftCollapsed ? "collapsed" : ""}`}>
          {leftCollapsed ? (
            <CollapsedRail
              side="left"
              title="配置与日志"
              subtitle="展开左侧"
              onExpand={() => setLeftCollapsed(false)}
            />
          ) : (
            <div className="panel-stack">
              <div className="panel-topbar">
                <div>
                  <p className="eyebrow">Left Panel</p>
                  <h2>系统配置与最近日志</h2>
                </div>
                <button type="button" className="ghost-btn" onClick={() => setLeftCollapsed(true)}>
                  收起
                </button>
              </div>

              <section className="card panel-card">
                <div className="section-heading">
                  <div>
                    <h3>系统配置区</h3>
                    <p>保存文本模型、图片模型和本地 API Key，新建任务默认继承这里的设置。</p>
                  </div>
                  <span className="section-badge">
                    文本：{systemConfig.text_model_name} | 图片：{systemConfig.image_model_name}
                  </span>
                </div>

                <form className="stack" onSubmit={handleSaveSystemConfig}>
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
                        placeholder={
                          systemConfig.image_provider === "disabled"
                            ? "已关闭图像生成，无需填写"
                            : "输入图片模型 API Key"
                        }
                        autoComplete="off"
                        disabled={configSaving || systemConfig.image_provider === "disabled"}
                      />
                    </label>
                  </div>

                  <div className="config-actions">
                    <span className="muted-note">配置保存在本地系统配置文件中，不进入任务正文。</span>
                    <button type="submit" disabled={configSaving}>
                      {configSaving ? "保存中..." : "保存配置"}
                    </button>
                  </div>
                  {isBusyForScope(["config"]) ? (
                    <div className="inline-activity" role="status" aria-live="polite">
                      <span className="inline-spinner" />
                      <span>{busyLabel}</span>
                    </div>
                  ) : null}
                </form>
              </section>

              <section className="card panel-card">
                <div className="section-heading">
                  <div>
                    <h3>最近日志</h3>
                    <p>实时查看 Worker 和各阶段 Agent 的执行信息。</p>
                  </div>
                  <span className="section-badge">{recentLogs.length} 条</span>
                </div>

                {recentLogs.length === 0 ? (
                  <p className="empty-note">暂无日志。</p>
                ) : (
                  <div className="log-box tall">
                    {recentLogs.map((log) => (
                      <article key={log.event_id} className="timeline-item">
                        <div className="timeline-meta">
                          <span>{log.stage}</span>
                          <span>{log.status}</span>
                        </div>
                        <p>{log.message}</p>
                        <time>{log.created_at}</time>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </div>
          )}
        </aside>

        <main className="center-panel">
          <section className="card center-hero">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Center Workspace</p>
                <h2>目录树版本与节点执行状态</h2>
                <p>中间区域保持常驻，用来对比目录版本、预览当前目录树并跟踪节点执行进度。</p>
              </div>
              {selectedTask ? (
                <span className="section-badge">{statusCn(selectedTask.status)}</span>
              ) : null}
            </div>

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

                <div className="hero-metrics">
                  <div className="metric-card accent">
                    <span>总进度</span>
                    <strong>{Math.round((selectedTask.total_progress || 0) * 100)}%</strong>
                    <p>当前阶段：{selectedTask.current_stage || "-"}</p>
                  </div>
                  <div className="metric-card">
                    <span>节点进度</span>
                    <strong>{selectedTask.completed_nodes || 0}/{selectedTask.total_nodes || 0}</strong>
                    <p>当前节点：{selectedTask.current_node_uid || "-"}</p>
                  </div>
                  <div className="metric-card">
                    <span>任务概览</span>
                    <strong>{selectedTask.title}</strong>
                    <p>ID：{selectedTask.task_id}</p>
                  </div>
                </div>

                <div className="task-meta-grid">
                  <div className="meta-chip"><span>确认目录</span><strong>{selectedTask.confirmed_toc_version || "-"}</strong></div>
                  <div className="meta-chip"><span>上传文件</span><strong>{selectedTask.upload_file_name || "-"}</strong></div>
                  <div className="meta-chip"><span>任务心跳</span><strong>{selectedTask.last_heartbeat_at || "-"}</strong></div>
                  <div className="meta-chip"><span>最近错误</span><strong>{selectedTask.latest_error || "-"}</strong></div>
                </div>

                {parseReportHighlights.length > 0 ? (
                  <div className="task-meta-grid compact">
                    {parseReportHighlights.map((item) => (
                      <div key={item.label} className="meta-chip soft">
                        <span>{item.label}</span>
                        <strong>{item.value}</strong>
                      </div>
                    ))}
                  </div>
                ) : null}

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
                    <p className="muted-note">任务完成后可下载最终 Word 文档。</p>
                  )}
                </div>
              </>
            ) : (
              <p className="empty-note">请先在右侧选择或创建任务。</p>
            )}
          </section>

          <section className="card panel-card">
            <div className="section-heading">
              <div>
                <h3>目录树版本</h3>
                <p>切换目录版本、查看差异摘要和当前目录结构。</p>
              </div>
              {selectedVersionNo ? <span className="section-badge">当前版本 v{selectedVersionNo}</span> : null}
            </div>

            {!canReviewToc && !canImportToc && selectedTask ? (
              <p className="muted-note">
                当前任务不在 TOC_REVIEW 阶段，目录已锁定或尚未进入目录审阅阶段。
              </p>
            ) : null}

            <div className="version-toolbar">
              {tocVersions.length === 0 ? (
                <p className="empty-note">暂无目录版本。</p>
              ) : (
                tocVersions.map((item) => (
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
                ))
              )}
            </div>

            <div className="diff-grid">
              <div className="diff-card">
                <span>新增节点</span>
                <strong>{summary.add_count || 0}</strong>
              </div>
              <div className="diff-card">
                <span>删除节点</span>
                <strong>{summary.remove_count || 0}</strong>
              </div>
              <div className="diff-card">
                <span>标题变更</span>
                <strong>{summary.title_change_count || 0}</strong>
              </div>
              <div className="diff-card">
                <span>顺序变化</span>
                <strong>{summary.reorder_count || 0}</strong>
              </div>
            </div>

            <div className="toc-preview-panel framed" style={{ height: `${tocPreviewHeight}px` }}>
              {visibleTocNodes.length > 0 ? (
                <TocTree nodes={visibleTocNodes} />
              ) : (
                <p className="empty-note">请选择目录版本查看。</p>
              )}
            </div>
          </section>

          <section className="card panel-card">
            <div className="section-heading">
              <div>
                <h3>节点执行状态</h3>
                <p>这里显示每个最小生成单元的状态、阶段、图片告警和心跳。</p>
              </div>
              <span className="section-badge">{nodeStates.length} 个节点</span>
            </div>

            {nodeStates.length === 0 ? (
              <p className="empty-note">暂无节点状态。</p>
            ) : (
              <div className="table-wrap status-table-wrap">
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
        </main>

        <aside className={`side-panel right-panel ${rightCollapsed ? "collapsed" : ""}`}>
          {rightCollapsed ? (
            <CollapsedRail
              side="right"
              title="上传与指令"
              subtitle="展开右侧"
              onExpand={() => setRightCollapsed(false)}
            />
          ) : (
            <div className="panel-stack">
              <div className="panel-topbar">
                <div>
                  <p className="eyebrow">Right Panel</p>
                  <h2>上传、指令与生成控制</h2>
                </div>
                <button type="button" className="ghost-btn" onClick={() => setRightCollapsed(true)}>
                  收起
                </button>
              </div>

              <section className="card panel-card">
                <div className="section-heading">
                  <div>
                    <h3>任务与上传文件</h3>
                    <p>先创建或选择任务，再上传 `.docx` 需求文件。</p>
                  </div>
                </div>

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

                {isBusyForScope(["task", "upload"]) ? (
                  <div className="inline-activity" role="status" aria-live="polite">
                    <span className="inline-spinner" />
                    <span>{busyLabel}</span>
                  </div>
                ) : null}

                <div className="divider" />

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
              </section>

              <section className="card panel-card">
                <div className="section-heading">
                  <div>
                    <h3>阶段操作</h3>
                    <p>生成目录、确认目录并开始正文生成，导入完整目录树使用独立弹窗。</p>
                  </div>
                </div>

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
                    className="ghost-btn strong"
                    onClick={handleOpenWordBudgetModal}
                    disabled={loading || !canAdjustWordBudget}
                  >
                    调整生成页面
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmAndStart}
                    disabled={loading || !canReviewToc || !selectedVersionNo}
                  >
                    2. 确认目录 / 开始生成内容
                  </button>
                  <button
                    type="button"
                    className="ghost-btn strong"
                    onClick={() => setOutlineModalOpen(true)}
                    disabled={loading || !canImportToc}
                  >
                    导入完整目录树
                  </button>
                </div>
                {isBusyForScope(["toc", "confirm", "import", "word-budget"]) ? (
                  <div className="inline-activity" role="status" aria-live="polite">
                    <span className="inline-spinner" />
                    <span>{busyLabel}</span>
                  </div>
                ) : null}
              </section>

              <section className="card panel-card">
                <div className="section-heading">
                  <div>
                    <h3>AI 指令与目录树对话</h3>
                    <p>这里复用同一个对话区：上方输入指令，下方查看 AI 目录修订记录。</p>
                  </div>
                  {selectedVersionNo ? <span className="section-badge">基于 v{selectedVersionNo}</span> : null}
                </div>

                {!canReviewToc && selectedTask ? (
                  <p className="muted-note">
                    当前任务不在 TOC_REVIEW 阶段，目录指令输入已锁定。
                  </p>
                ) : null}

                <form className="stack" onSubmit={handleReviewToc}>
                  <label>
                    输入用户指令
                    <textarea
                      rows={6}
                      value={feedback}
                      onChange={(e) => setFeedback(e.target.value)}
                      disabled={loading || !canReviewToc || !selectedVersionNo}
                      placeholder="例如：新增施工准备章节；调整章节顺序；把售后部分并入第六章；将一级目录改成我提供的结构"
                    />
                  </label>
                  <button type="submit" disabled={loading || !canReviewToc || !selectedVersionNo}>
                    提交审阅意见并生成新版本
                  </button>
                </form>
                {isBusyForScope(["review"]) ? (
                  <div className="inline-activity" role="status" aria-live="polite">
                    <span className="inline-spinner" />
                    <span>{busyLabel}</span>
                  </div>
                ) : null}

                <div className="dialog-box">
                  {chatMessages.length === 0 ? (
                    <p className="empty-note">暂无 AI 目录修订对话。</p>
                  ) : (
                    chatMessages.map((msg) => (
                      <article
                        key={msg.message_id}
                        className={`chat-bubble ${msg.role === "user" ? "user" : "assistant"}`}
                      >
                        <div className="chat-meta">
                          <span>{msg.role === "user" ? "用户" : msg.role === "assistant" ? "AI" : "系统"}</span>
                          {msg.related_toc_version ? <span>v{msg.related_toc_version}</span> : null}
                        </div>
                        <p>{msg.content}</p>
                      </article>
                    ))
                  )}
                </div>
              </section>
            </div>
          )}
        </aside>
      </div>

      {wordBudgetModalOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setWordBudgetModalOpen(false)}
        >
          <div
            className="modal-card wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="word-budget-modal-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">Generation Page Budget</p>
                <h2 id="word-budget-modal-title">调整生成页面</h2>
                <p>按一级标题设置总页面预算，系统会把该页面预算分摊到其下三级或四级生成单元。</p>
              </div>
              <button type="button" className="ghost-btn" onClick={() => setWordBudgetModalOpen(false)}>
                关闭
              </button>
            </div>

            <form className="stack" onSubmit={handleSaveWordBudget}>
              <div className="word-budget-summary">
                <div className="diff-card">
                  <span>目录版本</span>
                  <strong>v{selectedVersionNo || "-"}</strong>
                </div>
                <div className="diff-card">
                  <span>一级标题数</span>
                  <strong>{wordBudgetDoc?.chapters?.length || 0}</strong>
                </div>
                <div className="diff-card accent-soft">
                  <span>预计生成总页面数</span>
                  <strong>{estimatedWordBudgetTotal || 0}</strong>
                </div>
              </div>

              <div className="toc-preview-panel framed budget-modal-tree">
                <TocWordBudgetTree
                  nodes={visibleTocNodes}
                  budgetMap={wordBudgetMap}
                  inputValues={wordBudgetInputs}
                  onChange={handleWordBudgetInputChange}
                />
              </div>

              <p className="muted-note">
                每个输入值作用于该一级标题下全部三级或四级生成单元，系统会按生成单元数量进行分摊，
                每个最小生成单元会按分摊后的页面预算生成，单个一级标题的实际成文允许落在输入页数到输入页数 + 1 页之间。
              </p>

              <div className="modal-actions">
                <button type="button" className="ghost-btn" onClick={() => setWordBudgetModalOpen(false)}>
                  取消
                </button>
                <button
                  type="submit"
                  disabled={loading || !canAdjustWordBudget || !wordBudgetDoc}
                >
                  保存页面配置
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {outlineModalOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setOutlineModalOpen(false)}
        >
          <div
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="outline-modal-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">Import Full TOC</p>
                <h2 id="outline-modal-title">导入完整目录树</h2>
                <p>直接粘贴新的目录树结构，系统会基于当前任务生成新的 TOC 版本。</p>
              </div>
              <button type="button" className="ghost-btn" onClick={() => setOutlineModalOpen(false)}>
                关闭
              </button>
            </div>

            <form className="stack" onSubmit={handleImportToc}>
              <label>
                新目录树
                <textarea
                  rows={16}
                  value={outlineText}
                  onChange={(e) => setOutlineText(e.target.value)}
                  disabled={loading || !canImportToc}
                  placeholder={"例如：\n一、售后服务总体方案\n1.1 售后服务目标\n1.1.1 保障系统安全稳定运行"}
                />
              </label>
              <div className="modal-actions">
                <button type="button" className="ghost-btn" onClick={() => setOutlineModalOpen(false)}>
                  取消
                </button>
                <button type="submit" disabled={loading || !canImportToc}>
                  导入完整目录树并生成新版本
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
