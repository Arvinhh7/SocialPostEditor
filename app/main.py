from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .agent import WritingAgent
from .config import settings
from .db import Database
from .documents import extract_text, split_posts
from .models import FeedbackCreate, GenerationRequest, PostCreate, RetrievalRequest, RoleCreate


db = Database(settings.database_path)
db.init()
agent = WritingAgent(db, settings)
app = FastAPI(title="个性化社交媒体写作 Agent", version="0.1.0")


def require_role(role_id: int) -> None:
    if not db.get_role(role_id):
        raise HTTPException(status_code=404, detail="Role not found")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_mode": settings.llm_mode, "llm_provider": agent.llm.provider, "model": agent.llm.model, "retrieval_mode": settings.retrieval_mode}


@app.get("/roles")
def list_roles() -> list[dict]:
    return db.list_roles()


@app.post("/roles", status_code=201)
def create_role(payload: RoleCreate) -> dict:
    try:
        return db.create_role(payload.model_dump())
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="Role name already exists") from exc
        raise


@app.get("/posts")
def list_posts(role_id: int) -> list[dict]:
    require_role(role_id)
    return db.list_posts(role_id)


@app.post("/posts", status_code=201)
def create_post(payload: PostCreate) -> dict:
    require_role(payload.role_id)
    return db.add_post(payload.model_dump())


@app.post("/posts/upload", status_code=201)
async def upload_posts(
    file: Annotated[UploadFile, File()],
    role_id: Annotated[int, Form()],
    platform: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
    content_type: Annotated[str, Form()] = "",
    topic: Annotated[str, Form()] = "",
    tone: Annotated[str, Form()] = "",
    authenticity: Annotated[int, Form()] = 3,
) -> dict:
    require_role(role_id)
    if not 1 <= authenticity <= 5:
        raise HTTPException(status_code=422, detail="authenticity must be 1..5")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB")
    try:
        chunks = split_posts(extract_text(file.filename or "upload.txt", content))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    created = [
        db.add_post({"role_id": role_id, "title": title, "text": text, "platform": platform, "language": language, "content_type": content_type, "topic": topic, "tone": tone, "authenticity": authenticity, "source_name": file.filename or "upload"})
        for title, text in chunks
    ]
    return {"count": len(created), "posts": created}


@app.post("/profile/rebuild")
def rebuild_profile(role_id: int) -> dict:
    try:
        return agent.rebuild_profile(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/profile")
def get_profile(role_id: int) -> dict:
    require_role(role_id)
    profile = db.latest_profile(role_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile has not been built")
    return profile


@app.post("/retrieve")
def retrieve(payload: RetrievalRequest) -> dict:
    try:
        return {"hits": agent.retrieve(payload.role_id, payload.model_dump(), payload.top_k)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/generate")
def generate(payload: GenerationRequest) -> dict:
    try:
        return agent.generate(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/feedback", status_code=201)
def feedback(payload: FeedbackCreate) -> dict:
    require_role(payload.role_id)
    return db.add_feedback(payload.model_dump())


@app.get("/generations/{run_id}")
def generation(run_id: int) -> dict:
    result = db.get_generation(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return result
