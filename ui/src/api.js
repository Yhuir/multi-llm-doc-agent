const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 15000);

async function request(path, options = {}) {
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      signal: controller.signal
    });
    const contentType = res.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await res.json()
      : await res.text();

    if (!res.ok) {
      const detail = typeof payload === "object" && payload?.detail ? payload.detail : payload;
      throw new Error(detail || `Request failed: ${res.status}`);
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`请求超时：${path}`);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getSystemConfig() {
  return request("/system/config");
}

export async function getHealth() {
  return request("/health", { timeoutMs: 3000 });
}

export async function updateSystemConfig(config) {
  return request("/system/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    timeoutMs: 10000
  });
}

export async function listTasks() {
  return request("/tasks");
}

export async function createTask(title, parentTaskId = null) {
  return request("/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, parent_task_id: parentTaskId })
  });
}

export async function getTask(taskId) {
  return request(`/tasks/${taskId}`);
}

export async function uploadDocx(taskId, file) {
  const formData = new FormData();
  formData.append("file", file);
  return request(`/tasks/${taskId}/upload`, {
    method: "POST",
    body: formData
  });
}

export async function parseRequirement(taskId) {
  return request(`/tasks/${taskId}/parse`, { method: "POST" });
}

export async function getParseReport(taskId) {
  return request(`/tasks/${taskId}/parsed/report`);
}

export async function generateToc(taskId) {
  return request(`/tasks/${taskId}/toc/generate`, { method: "POST" });
}

export async function listTocVersions(taskId) {
  return request(`/tasks/${taskId}/toc/versions`);
}

export async function getToc(taskId, versionNo) {
  return request(`/tasks/${taskId}/toc/${versionNo}`);
}

export async function getConfirmedToc(taskId) {
  return request(`/tasks/${taskId}/toc/confirmed`);
}

export async function reviewToc(taskId, feedback, basedOnVersionNo = null) {
  return request(`/tasks/${taskId}/toc/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      feedback,
      based_on_version_no: basedOnVersionNo
    }),
    timeoutMs: 60000
  });
}

export async function importTocOutline(taskId, outlineText, basedOnVersionNo = null) {
  return request(`/tasks/${taskId}/toc/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      outline_text: outlineText,
      based_on_version_no: basedOnVersionNo
    }),
    timeoutMs: 60000
  });
}

export async function confirmToc(taskId, versionNo) {
  return request(`/tasks/${taskId}/toc/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version_no: versionNo })
  });
}

export async function startGeneration(taskId) {
  return request(`/tasks/${taskId}/generation/start`, { method: "POST" });
}

export async function confirmAndStartGeneration(taskId, versionNo) {
  return request(`/tasks/${taskId}/generation/confirm-and-start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version_no: versionNo }),
    timeoutMs: 30000
  });
}

export async function listNodes(taskId) {
  return request(`/tasks/${taskId}/nodes`);
}

export async function listLogs(taskId, limit = 50) {
  return request(`/tasks/${taskId}/logs?limit=${limit}`);
}

export async function listChat(taskId) {
  return request(`/tasks/${taskId}/chat`);
}

export function outputUrl(taskId) {
  return `${API_BASE}/tasks/${taskId}/output`;
}

export { API_BASE };
