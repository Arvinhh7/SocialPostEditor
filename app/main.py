from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .agent import WritingAgent
from .config import settings
from .db import Database
from .evals import DeterministicEvalRunner, compare_eval_runs
from .ingestion import ingest_uploaded_posts
from .models import (
    EvalCaseCreate,
    EvalGenerationRequest,
    EvalRunCompareRequest,
    FeedbackAdmissionDecision,
    FeedbackBulkAdmissionDecision,
    FeedbackCreate,
    GenerationRequest,
    PostBulkMetadataUpdate,
    PostCreate,
    PostMetadataUpdate,
    PostRetrievalStatusUpdate,
    RetrievalFeedbackCreate,
    RetrievalRequest,
    ReviewActionCreate,
    RoleCreate,
    RoleCloneRequest,
    RoleUpdate,
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


@app.patch("/roles/{role_id}")
def update_role(role_id: int, payload: RoleUpdate) -> dict:
    try:
        return db.update_role(role_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if "not found" in detail else 422, detail=detail) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="Role name already exists") from exc
        raise


@app.post("/roles/{role_id}/clone", status_code=201)
def clone_role(role_id: int, payload: RoleCloneRequest) -> dict:
    try:
        return db.clone_role(role_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if "not found" in detail else 422, detail=detail) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="Role name already exists") from exc
        raise


@app.get("/posts")
def list_posts(role_id: int, status: str | None = None) -> list[dict]:
    require_role(role_id)
    try:
        return db.list_posts(role_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/posts", status_code=201)
def create_post(payload: PostCreate) -> dict:
    require_role(payload.role_id)
    return db.add_post(payload.model_dump())


@app.patch("/posts/bulk")
def bulk_update_post_metadata(payload: PostBulkMetadataUpdate) -> dict:
    require_role(payload.role_id)
    try:
        posts = db.bulk_update_post_metadata(
            payload.role_id,
            payload.post_ids,
            payload.changes.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"updated_count": len(posts), "posts": posts}


@app.patch("/posts/{post_id}")
def update_post_metadata(post_id: int, payload: PostMetadataUpdate) -> dict:
    try:
        return db.update_post_metadata(post_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if "not found" in detail else 422, detail=detail) from exc


@app.post("/posts/{post_id}/retrieval-status", status_code=201)
def update_post_retrieval_status(post_id: int, payload: PostRetrievalStatusUpdate) -> dict:
    try:
        return db.update_post_retrieval_status(post_id, payload.model_dump())
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if "not found" in detail else 409, detail=detail) from exc


@app.get("/posts/{post_id}/retrieval-actions")
def list_post_retrieval_actions(post_id: int) -> list[dict]:
    if not db.get_post(post_id):
        raise HTTPException(status_code=404, detail="Post not found")
    return db.list_post_retrieval_actions(post_id)


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
    result = ingest_uploaded_posts(
        db,
        [(file.filename or "upload.txt", content)],
        role_id,
        {
            "platform": platform.strip(),
            "language": language.strip(),
            "content_type": content_type.strip(),
            "topic": topic.strip(),
            "tone": tone.strip(),
        },
        authenticity,
    )
    if result["failed"]:
        raise HTTPException(status_code=422, detail=result["failed"][0]["reason"])
    posts = [item["post"] for item in result["created"]]
    return {"count": len(posts), "posts": posts, "skipped": result["skipped"]}


@app.post("/posts/bulk-upload", status_code=201)
async def bulk_upload_posts(
    files: Annotated[list[UploadFile], File(description="一次选择多个 PDF、TXT 或 Markdown 文件")],
    role_id: Annotated[int, Form()],
    platform: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
    content_type: Annotated[str, Form()] = "",
    topic: Annotated[str, Form()] = "",
    tone: Annotated[str, Form()] = "",
    authenticity: Annotated[int, Form()] = 4,
) -> dict:
    require_role(role_id)
    if not 1 <= authenticity <= 5:
        raise HTTPException(status_code=422, detail="authenticity must be 1..5")
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")
    if len(files) > 30:
        raise HTTPException(status_code=413, detail="A maximum of 30 files can be uploaded at once")

    uploaded: list[tuple[str, bytes]] = []
    total_bytes = 0
    for file in files:
        filename = file.filename or "upload.txt"
        content = await file.read()
        total_bytes += len(content)
        if total_bytes > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Total upload exceeds 50 MB")
        uploaded.append((filename, content))

    defaults = {
        "platform": platform.strip(),
        "language": language.strip(),
        "content_type": content_type.strip(),
        "topic": topic.strip(),
        "tone": tone.strip(),
    }

    return ingest_uploaded_posts(db, uploaded, role_id, defaults, authenticity)


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
        explicit_request = payload.model_dump(include=payload.model_fields_set)
        return agent.generate(explicit_request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/feedback", status_code=201)
def create_feedback(payload: FeedbackCreate) -> dict:
    require_role(payload.role_id)
    return db.add_feedback(payload.model_dump())


@app.get("/feedback")
def list_feedback(role_id: int, status: str | None = None) -> list[dict]:
    require_role(role_id)
    try:
        return db.list_feedback(role_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/feedback/admission/bulk", status_code=201)
def decide_feedback_admission_bulk(payload: FeedbackBulkAdmissionDecision) -> dict:
    require_role(payload.role_id)
    try:
        decisions = db.decide_feedback_admission_bulk(
            payload.role_id,
            payload.feedback_ids,
            {"action": payload.action, "reason": payload.reason},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"decided_count": len(decisions), "decisions": decisions}


@app.get("/feedback/{feedback_id}/admission-actions")
def list_feedback_admission_actions(feedback_id: int) -> list[dict]:
    if not db.get_feedback(feedback_id):
        raise HTTPException(status_code=404, detail="Feedback not found")
    return db.list_feedback_admission_actions(feedback_id)


@app.post("/feedback/{feedback_id}/admission", status_code=201)
def decide_feedback_admission(feedback_id: int, payload: FeedbackAdmissionDecision) -> dict:
    try:
        return db.decide_feedback_admission(feedback_id, payload.model_dump())
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 409
        raise HTTPException(status_code=status, detail=detail) from exc


@app.get("/generations/{run_id}")
def generation(run_id: int) -> dict:
    result = db.get_generation(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return result


@app.get("/generations/{run_id}/retrieval-feedback")
def list_generation_retrieval_feedback(run_id: int) -> list[dict]:
    if not db.get_generation(run_id):
        raise HTTPException(status_code=404, detail="Generation run not found")
    return db.list_retrieval_feedback(run_id)


@app.post("/generations/{run_id}/retrieval-feedback", status_code=201)
def create_generation_retrieval_feedback(run_id: int, payload: RetrievalFeedbackCreate) -> dict:
    try:
        return db.add_retrieval_feedback(run_id, payload.model_dump())
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 409
        raise HTTPException(status_code=status, detail=detail) from exc


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
def review_inbox(
    role_id: int,
    status: str = "PENDING_REVIEW",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    require_role(role_id)
    try:
        return db.list_review_inbox(role_id, status, limit, offset)
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
