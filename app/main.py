from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .agent import WritingAgent
from .config import settings
from .db import Database
from .documents import extract_text, split_posts
from .evals import DeterministicEvalRunner, compare_eval_runs
from .models import (
    EvalCaseCreate,
    EvalGenerationRequest,
    EvalRunCompareRequest,
    FeedbackCreate,
    GenerationRequest,
    PostCreate,
    RetrievalRequest,
    ReviewActionCreate,
    RoleCreate,
)


db = Database(settings.database_path)
db.init()
agent = WritingAgent(db, settings)
eval_runner = DeterministicEvalRunner(db)
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


@app.post("/eval-cases", status_code=201)
def create_eval_case(payload: EvalCaseCreate) -> dict:
    require_role(payload.role_id)
    try:
        return db.create_eval_case(payload.model_dump())
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="Evaluation case name and version already exist for this role") from exc
        raise


@app.get("/eval-cases")
def list_eval_cases(role_id: int, active_only: bool = True) -> list[dict]:
    require_role(role_id)
    return db.list_eval_cases(role_id, active_only)


@app.get("/eval-cases/{eval_case_id}")
def get_eval_case(eval_case_id: int) -> dict:
    result = db.get_eval_case(eval_case_id)
    if not result:
        raise HTTPException(status_code=404, detail="Evaluation case not found")
    return result


@app.post("/eval-runs", status_code=201)
def run_evaluation(payload: EvalGenerationRequest) -> dict:
    case = db.get_eval_case(payload.eval_case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Evaluation case not found")
    generation_result = db.get_generation(payload.generation_run_id)
    if not generation_result:
        raise HTTPException(status_code=404, detail="Generation run not found")
    if int(case["role_id"]) != int(generation_result["role_id"]):
        raise HTTPException(status_code=422, detail="Evaluation case and generation must belong to the same role")
    try:
        return eval_runner.evaluate_generation(payload.eval_case_id, payload.generation_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/eval-runs/compare")
def compare_evaluation_runs(payload: EvalRunCompareRequest) -> dict:
    try:
        return compare_eval_runs(db, payload.run_ids)
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 422
        raise HTTPException(status_code=status, detail=detail) from exc


@app.get("/eval-runs/{eval_run_id}")
def get_eval_run(eval_run_id: int) -> dict:
    result = db.get_eval_run(eval_run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return result


@app.get("/review-inbox")
def review_inbox(role_id: int, status: str = "PENDING_REVIEW") -> list[dict]:
    require_role(role_id)
    try:
        return db.list_review_inbox(role_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/generations/{run_id}/review-actions")
def list_review_actions(run_id: int) -> list[dict]:
    if not db.get_generation(run_id):
        raise HTTPException(status_code=404, detail="Generation run not found")
    return db.list_review_actions(run_id)


@app.post("/generations/{run_id}/review-actions", status_code=201)
def create_review_action(run_id: int, payload: ReviewActionCreate) -> dict:
    try:
        action = db.add_review_action(run_id, payload.model_dump())
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 409
        raise HTTPException(status_code=status, detail=detail) from exc
    generation_result = db.get_generation(run_id) or {}
    return {
        "review_action": action,
        "approval_status": generation_result.get("approval_status"),
        "current_text": generation_result.get("current_text"),
    }
