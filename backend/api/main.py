"""FastAPI layer for the React frontend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.app_service.task_service import TaskService
from backend.config import load_settings


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    parent_task_id: str | None = None


class TOCReviewRequest(BaseModel):
    feedback: str = Field(min_length=1)
    based_on_version_no: int | None = None


class TOCImportRequest(BaseModel):
    outline_text: str = Field(min_length=1)
    based_on_version_no: int | None = None


class TOCConfirmRequest(BaseModel):
    version_no: int


class SystemConfigUpdateRequest(BaseModel):
    text_provider: str | None = None
    image_provider: str | None = None
    text_model_name: str | None = None
    image_model_name: str | None = None
    text_api_key: str | None = None
    image_api_key: str | None = None
    api_key: str | None = None


settings = load_settings()
service = TaskService(settings=settings)
app = FastAPI(title="Multi-Agent Doc Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/system/config")
def get_system_config() -> dict[str, Any]:
    return service.get_system_config()


@app.put("/system/config")
def update_system_config(payload: SystemConfigUpdateRequest) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    return service.update_system_config(updates)


@app.get("/tasks")
def list_tasks() -> list[dict[str, Any]]:
    return [task.model_dump(mode="json") for task in service.list_tasks()]


@app.get("/tasks/resumable")
def list_resumable_tasks() -> list[dict[str, Any]]:
    return [task.model_dump(mode="json") for task in service.list_resumable_tasks()]


@app.post("/tasks")
def create_task(payload: TaskCreateRequest) -> dict[str, Any]:
    task = service.create_task(
        title=payload.title,
        parent_task_id=payload.parent_task_id,
    )
    return task.model_dump(mode="json")


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.model_dump(mode="json")


@app.post("/tasks/{task_id}/upload")
async def upload_docx(task_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    filename = file.filename or ""
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx is supported")

    content = await file.read()
    try:
        path = service.save_upload(task_id=task_id, file_name=filename, file_content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"upload_file_path": str(path)}


@app.post("/tasks/{task_id}/parse")
def parse_requirement(task_id: str) -> dict[str, Any]:
    try:
        return service.parse_requirement(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/tasks/{task_id}/parsed/requirement")
def get_requirement(task_id: str) -> dict[str, Any]:
    payload = service.get_requirement_document(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="requirement.json not found")
    return payload


@app.get("/tasks/{task_id}/parsed/report")
def get_parse_report(task_id: str) -> dict[str, Any]:
    payload = service.get_parse_report(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="parse_report.json not found")
    return payload


@app.post("/tasks/{task_id}/toc/generate")
def generate_toc(task_id: str) -> dict[str, Any]:
    try:
        version = service.generate_toc(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return version.model_dump(mode="json")


@app.get("/tasks/{task_id}/toc/versions")
def list_toc_versions(task_id: str) -> list[dict[str, Any]]:
    return [version.model_dump(mode="json") for version in service.list_toc_versions(task_id)]


@app.get("/tasks/{task_id}/toc/{version_no}")
def get_toc(task_id: str, version_no: int) -> dict[str, Any]:
    try:
        return service.get_toc_document(task_id, version_no)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/tasks/{task_id}/toc/confirmed")
def get_confirmed_toc(task_id: str) -> dict[str, Any]:
    payload = service.get_confirmed_toc(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="toc_confirmed.json not found")
    return payload


@app.post("/tasks/{task_id}/toc/review")
def review_toc(task_id: str, payload: TOCReviewRequest) -> dict[str, Any]:
    try:
        version = service.review_toc(
            task_id,
            payload.feedback,
            based_on_version_no=payload.based_on_version_no,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = version.model_dump(mode="json")
    response["toc_document"] = service.get_toc_document(task_id, version.version_no)
    return response


@app.post("/tasks/{task_id}/toc/import")
def import_toc(task_id: str, payload: TOCImportRequest) -> dict[str, Any]:
    try:
        version = service.import_toc_outline(
            task_id,
            payload.outline_text,
            based_on_version_no=payload.based_on_version_no,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = version.model_dump(mode="json")
    response["toc_document"] = service.get_toc_document(task_id, version.version_no)
    return response


@app.post("/tasks/{task_id}/toc/confirm")
def confirm_toc(task_id: str, payload: TOCConfirmRequest) -> dict[str, Any]:
    try:
        node_count = service.confirm_toc(task_id, payload.version_no)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"seeded_nodes": node_count}


@app.post("/tasks/{task_id}/generation/start")
def start_generation(task_id: str) -> dict[str, Any]:
    try:
        service.start_generation(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "accepted": True,
        "task_id": task_id,
        "message": "Task queued. Start backend worker to execute.",
    }


@app.post("/tasks/{task_id}/generation/confirm-and-start")
def confirm_and_start_generation(task_id: str, payload: TOCConfirmRequest) -> dict[str, Any]:
    try:
        return service.confirm_and_start_generation(task_id, payload.version_no)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/tasks/{task_id}/nodes")
def list_nodes(task_id: str) -> list[dict[str, Any]]:
    return [node.model_dump(mode="json") for node in service.get_node_states(task_id)]


@app.get("/tasks/{task_id}/logs")
def list_logs(task_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return [event.model_dump(mode="json") for event in service.get_event_logs(task_id, limit=limit)]


@app.get("/tasks/{task_id}/chat")
def list_chat(task_id: str) -> list[dict[str, Any]]:
    return [msg.model_dump(mode="json") for msg in service.get_chat_messages(task_id)]


@app.get("/tasks/{task_id}/output")
def download_output(task_id: str) -> FileResponse:
    output_path = service.get_output_path(task_id)
    if output_path is None:
        raise HTTPException(status_code=404, detail="Output file not found")

    absolute_path = Path(output_path).resolve()
    if not absolute_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        path=str(absolute_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="output.docx",
    )
