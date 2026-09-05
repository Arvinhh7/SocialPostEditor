from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Any, Iterator


logger = logging.getLogger(__name__)
POST_METADATA_FIELDS = (
    "title",
    "platform",
    "language",
    "content_type",
    "topic",
    "tone",
    "authenticity",
    "published_at",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    identity_rules TEXT NOT NULL DEFAULT '',
                    default_generate_params_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    title TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT '',
                    content_type TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    tone TEXT NOT NULL DEFAULT '',
                    authenticity INTEGER NOT NULL DEFAULT 3 CHECK(authenticity BETWEEN 1 AND 5),
                    retrieval_status TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK(retrieval_status IN ('ACTIVE', 'RETIRED')),
                    published_at TEXT,
                    source_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_posts_role ON posts(role_id);
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    profile_json TEXT NOT NULL,
                    sample_post_ids TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(role_id, version)
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    task_summary TEXT NOT NULL DEFAULT '',
                    draft TEXT NOT NULL,
                    final_text TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    similarity_rating INTEGER CHECK(similarity_rating BETWEEN 1 AND 5),
                    admission_status TEXT NOT NULL DEFAULT 'CANDIDATE'
                        CHECK(admission_status IN ('CANDIDATE', 'ADMITTED', 'REJECTED')),
                    decision_reason TEXT NOT NULL DEFAULT '',
                    decided_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_role ON feedback(role_id);
                CREATE TABLE IF NOT EXISTS feedback_admission_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK(action IN ('ADMIT', 'REJECT')),
                    previous_status TEXT NOT NULL,
                    resulting_status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_admission_actions_feedback
                ON feedback_admission_actions(feedback_id, id);
                CREATE TABLE IF NOT EXISTS generation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    request_json TEXT NOT NULL,
                    retrieved_json TEXT NOT NULL,
                    draft TEXT NOT NULL,
                    final_text TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approval_status TEXT NOT NULL DEFAULT 'NOT_APPLICABLE',
                    human_final_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generation_run_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation_run_id INTEGER NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
                    step_index INTEGER NOT NULL CHECK(step_index >= 1),
                    step_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    prompt_version TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER NOT NULL DEFAULT 0 CHECK(duration_ms >= 0),
                    status TEXT NOT NULL CHECK(status IN ('COMPLETED', 'FAILED')),
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(generation_run_id, step_index)
                );
                CREATE INDEX IF NOT EXISTS idx_generation_steps_run
                ON generation_run_steps(generation_run_id, step_index);
                CREATE TABLE IF NOT EXISTS retrieval_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation_run_id INTEGER NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK(action IN ('NOT_RELEVANT', 'RETIRE', 'RESTORE')),
                    reason TEXT NOT NULL DEFAULT '',
                    query_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_retrieval_feedback_run
                ON retrieval_feedback(generation_run_id, id);
                CREATE INDEX IF NOT EXISTS idx_retrieval_feedback_post
                ON retrieval_feedback(post_id, id);
                CREATE TABLE IF NOT EXISTS post_retrieval_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK(action IN ('RETIRE', 'RESTORE')),
                    previous_status TEXT NOT NULL CHECK(previous_status IN ('ACTIVE', 'RETIRED')),
                    resulting_status TEXT NOT NULL CHECK(resulting_status IN ('ACTIVE', 'RETIRED')),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_post_retrieval_actions_post
                ON post_retrieval_actions(post_id, id);
                CREATE TABLE IF NOT EXISTS review_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation_run_id INTEGER NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK(action IN ('EDIT', 'APPROVE', 'REJECT')),
                    previous_status TEXT NOT NULL,
                    resulting_status TEXT NOT NULL,
                    content_before TEXT NOT NULL,
                    content_after TEXT NOT NULL,
                    diff_text TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_actions_run
                ON review_actions(generation_run_id, id);
                CREATE TABLE IF NOT EXISTS eval_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    expected_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    version TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    UNIQUE(role_id, name, version)
                );
                CREATE INDEX IF NOT EXISTS idx_eval_cases_role ON eval_cases(role_id, active);
                CREATE TABLE IF NOT EXISTS eval_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    eval_case_id INTEGER NOT NULL REFERENCES eval_cases(id) ON DELETE CASCADE,
                    generation_run_id INTEGER REFERENCES generation_runs(id) ON DELETE SET NULL,
                    config_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'COMPLETED', 'FAILED')),
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_eval_runs_case ON eval_runs(eval_case_id, id);
                CREATE TABLE IF NOT EXISTS eval_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    eval_run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
                    metric_name TEXT NOT NULL,
                    value REAL NOT NULL CHECK(value BETWEEN 0.0 AND 1.0),
                    threshold REAL NOT NULL CHECK(threshold BETWEEN 0.0 AND 1.0),
                    passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
                    reason TEXT NOT NULL DEFAULT '',
                    evaluator TEXT NOT NULL,
                    version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(eval_run_id, metric_name, evaluator, version)
                );
                CREATE INDEX IF NOT EXISTS idx_eval_scores_run ON eval_scores(eval_run_id, id);
                """
            )
            generation_columns = {row[1] for row in conn.execute("PRAGMA table_info(generation_runs)")}
            if "approval_status" not in generation_columns:
                conn.execute(
                    "ALTER TABLE generation_runs ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'NOT_APPLICABLE'"
                )
            if "human_final_text" not in generation_columns:
                conn.execute(
                    "ALTER TABLE generation_runs ADD COLUMN human_final_text TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                """UPDATE generation_runs
                SET approval_status='PENDING_REVIEW', human_final_text=final_text
                WHERE status IN ('PASS', 'REVISE') AND approval_status='NOT_APPLICABLE'"""
            )
            role_columns = {row[1] for row in conn.execute("PRAGMA table_info(roles)")}
            if "default_generate_params_json" not in role_columns:
                conn.execute(
                    "ALTER TABLE roles ADD COLUMN default_generate_params_json TEXT NOT NULL DEFAULT '{}'"
                )
            post_columns = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
            if "retrieval_status" not in post_columns:
                conn.execute(
                    "ALTER TABLE posts ADD COLUMN retrieval_status TEXT NOT NULL DEFAULT 'ACTIVE'"
                )
            feedback_columns = {row[1] for row in conn.execute("PRAGMA table_info(feedback)")}
            legacy_feedback = "admission_status" not in feedback_columns
            if legacy_feedback:
                conn.execute(
                    "ALTER TABLE feedback ADD COLUMN admission_status TEXT NOT NULL DEFAULT 'CANDIDATE'"
                )
            if "decision_reason" not in feedback_columns:
                conn.execute("ALTER TABLE feedback ADD COLUMN decision_reason TEXT NOT NULL DEFAULT ''")
            if "decided_at" not in feedback_columns:
                conn.execute("ALTER TABLE feedback ADD COLUMN decided_at TEXT")
            if legacy_feedback:
                conn.execute(
                    """UPDATE feedback
                    SET admission_status='ADMITTED',
                        decision_reason='Automatically admitted during legacy migration',
                        decided_at=created_at"""
                )
            conn.execute(
                """INSERT OR IGNORE INTO roles
                (id, name, description, identity_rules, created_at)
                VALUES (2, ?, ?, ?, ?)""",
                (
                    "Alignment AI｜GEO 品牌传播",
                    "面向关注 GEO、AI Visibility 与品牌传播的从业者，提供克制、教育型、基于证据的内容。",
                    "不得虚构客户、案例、数据或亲历；未经 proof_points 支持，不作量化承诺；不承诺搜索或模型中的固定排名。",
                    utc_now(),
                ),
            )

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    @staticmethod
    def _decode_role(row: sqlite3.Row | None) -> dict[str, Any] | None:
        result = dict(row) if row else None
        if result:
            raw = result.pop("default_generate_params_json", "{}")
            try:
                result["default_generate_params"] = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid default_generate_params_json for role_id=%s", result.get("id"))
                result["default_generate_params"] = {}
        return result

    @staticmethod
    def _clean_generate_defaults(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {key: item for key, item in value.items() if item is not None}

    def list_roles(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [self._decode_role(row) or {} for row in conn.execute("SELECT * FROM roles ORDER BY id")]

    def get_role(self, role_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._decode_role(conn.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone())

    def create_role(self, data: dict[str, Any]) -> dict[str, Any]:
        defaults = self._clean_generate_defaults(data.get("default_generate_params", {}))
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO roles
                (name, description, identity_rules, default_generate_params_json, created_at)
                VALUES(?,?,?,?,?)""",
                (
                    data["name"],
                    data.get("description", ""),
                    data.get("identity_rules", ""),
                    json.dumps(defaults, ensure_ascii=False),
                    utc_now(),
                ),
            )
            row = conn.execute("SELECT * FROM roles WHERE id=?", (cur.lastrowid,)).fetchone()
            return self._decode_role(row) or {}

    def update_role(self, role_id: int, data: dict[str, Any]) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for key in ("name", "description", "identity_rules"):
            if key in data and data[key] is not None:
                changes[key] = data[key]
        if "default_generate_params" in data:
            changes["default_generate_params_json"] = json.dumps(
                self._clean_generate_defaults(data.get("default_generate_params")), ensure_ascii=False
            )
        if not changes:
            raise ValueError("At least one role field is required")
        assignments = ",".join(f"{key}=?" for key in changes)
        with self.connect() as conn:
            updated = conn.execute(
                f"UPDATE roles SET {assignments} WHERE id=?",
                (*changes.values(), role_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Role not found")
            return self._decode_role(conn.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone()) or {}

    def clone_role(self, role_id: int, data: dict[str, Any]) -> dict[str, Any]:
        source = self.get_role(role_id)
        if not source:
            raise ValueError("Role not found")
        defaults = dict(source.get("default_generate_params", {}))
        for key, value in (data.get("default_generate_params_overrides") or {}).items():
            if value is None:
                defaults.pop(key, None)
            else:
                defaults[key] = value
        return self.create_role(
            {
                "name": data["name"],
                "description": source["description"] if data.get("description") is None else data["description"],
                "identity_rules": source["identity_rules"],
                "default_generate_params": defaults,
            }
        )

    @staticmethod
    def _insert_post(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
        fields = ("role_id", "title", "text", "platform", "language", "content_type", "topic", "tone", "authenticity", "published_at", "source_name")
        values = [data.get(k, "") for k in fields]
        values[8] = data.get("authenticity", 3)
        values[9] = data.get("published_at")
        cur = conn.execute(
            f"INSERT INTO posts({','.join(fields)},created_at) VALUES({','.join('?' for _ in fields)},?)",
            (*values, utc_now()),
        )
        return dict(conn.execute("SELECT * FROM posts WHERE id=?", (cur.lastrowid,)).fetchone())

    def add_post(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            return self._insert_post(conn, data)

    def add_posts(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert one ingestion batch atomically."""
        if not items:
            return []
        with self.connect() as conn:
            return [self._insert_post(conn, item) for item in items]

    def list_posts(self, role_id: int, retrieval_status: str | None = None) -> list[dict[str, Any]]:
        if retrieval_status not in {None, "ACTIVE", "RETIRED"}:
            raise ValueError("Unknown post retrieval status")
        with self.connect() as conn:
            if retrieval_status is None:
                rows = conn.execute("SELECT * FROM posts WHERE role_id=? ORDER BY id", (role_id,))
            else:
                rows = conn.execute(
                    "SELECT * FROM posts WHERE role_id=? AND retrieval_status=? ORDER BY id",
                    (role_id, retrieval_status),
                )
            return [dict(row) for row in rows]

    def get_post(self, post_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._dict(conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())

    @staticmethod
    def _post_metadata_changes(data: dict[str, Any]) -> dict[str, Any]:
        return {
            key: data[key]
            for key in POST_METADATA_FIELDS
            if key in data and data[key] is not None
        }

    def update_post_metadata(self, post_id: int, data: dict[str, Any]) -> dict[str, Any]:
        changes = self._post_metadata_changes(data)
        if not changes:
            raise ValueError("At least one metadata field is required")
        assignments = ",".join(f"{key}=?" for key in changes)
        with self.connect() as conn:
            updated = conn.execute(
                f"UPDATE posts SET {assignments} WHERE id=?",
                (*changes.values(), post_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Post not found")
            return dict(conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())

    def bulk_update_post_metadata(
        self,
        role_id: int,
        post_ids: list[int],
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        changes = self._post_metadata_changes(data)
        unique_ids = list(dict.fromkeys(int(post_id) for post_id in post_ids))
        if not unique_ids:
            raise ValueError("At least one post_id is required")
        if not changes:
            raise ValueError("At least one metadata field is required")
        placeholders = ",".join("?" for _ in unique_ids)
        assignments = ",".join(f"{key}=?" for key in changes)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM posts WHERE role_id=? AND id IN ({placeholders})",
                (role_id, *unique_ids),
            ).fetchall()
            found = {int(row["id"]) for row in rows}
            missing = [post_id for post_id in unique_ids if post_id not in found]
            if missing:
                raise ValueError(f"Posts not found for role: {missing}")
            conn.execute(
                f"UPDATE posts SET {assignments} WHERE role_id=? AND id IN ({placeholders})",
                (*changes.values(), role_id, *unique_ids),
            )
            updated_rows = conn.execute(
                f"SELECT * FROM posts WHERE role_id=? AND id IN ({placeholders})",
                (role_id, *unique_ids),
            ).fetchall()
        by_id = {int(row["id"]): dict(row) for row in updated_rows}
        return [by_id[post_id] for post_id in unique_ids]

    def latest_profile(self, role_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE role_id=? ORDER BY version DESC LIMIT 1", (role_id,)).fetchone()
            result = self._dict(row)
            if result:
                result["profile"] = json.loads(result.pop("profile_json"))
                result["sample_post_ids"] = json.loads(result["sample_post_ids"])
            return result

    def save_profile(self, role_id: int, profile: dict[str, Any], sample_ids: list[int]) -> dict[str, Any]:
        previous = self.latest_profile(role_id)
        version = 1 if not previous else int(previous["version"]) + 1
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO profiles(role_id,version,profile_json,sample_post_ids,created_at) VALUES(?,?,?,?,?)",
                (role_id, version, json.dumps(profile, ensure_ascii=False), json.dumps(sample_ids), utc_now()),
            )
        return self.latest_profile(role_id) or {}

    def add_feedback(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO feedback(role_id,task_summary,draft,final_text,reason,similarity_rating,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (data["role_id"], data.get("task_summary", ""), data["draft"], data["final_text"], data.get("reason", ""), data.get("similarity_rating"), utc_now()),
            )
            return dict(conn.execute("SELECT * FROM feedback WHERE id=?", (cur.lastrowid,)).fetchone())

    def get_feedback(self, feedback_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._dict(conn.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone())

    def list_feedback(self, role_id: int, admission_status: str | None = None) -> list[dict[str, Any]]:
        allowed = {"CANDIDATE", "ADMITTED", "REJECTED"}
        if admission_status is not None and admission_status not in allowed:
            raise ValueError("Unknown feedback admission status")
        with self.connect() as conn:
            if admission_status is None:
                rows = conn.execute("SELECT * FROM feedback WHERE role_id=? ORDER BY id DESC", (role_id,))
            else:
                rows = conn.execute(
                    "SELECT * FROM feedback WHERE role_id=? AND admission_status=? ORDER BY id DESC",
                    (role_id, admission_status),
                )
            return [dict(row) for row in rows]

    @staticmethod
    def _feedback_resulting_status(action: str) -> str:
        resulting_status = {"ADMIT": "ADMITTED", "REJECT": "REJECTED"}.get(action)
        if resulting_status is None:
            raise ValueError("Unknown feedback admission action")
        return resulting_status

    @staticmethod
    def _apply_feedback_admission(
        conn: sqlite3.Connection,
        feedback: sqlite3.Row,
        action: str,
        resulting_status: str,
        reason: str,
        decided_at: str,
    ) -> dict[str, Any]:
        feedback_id = int(feedback["id"])
        previous_status = str(feedback["admission_status"])
        if previous_status != "CANDIDATE":
            raise ValueError("Feedback admission has already been decided")
        updated = conn.execute(
            """UPDATE feedback
            SET admission_status=?, decision_reason=?, decided_at=?
            WHERE id=? AND admission_status='CANDIDATE'""",
            (resulting_status, reason, decided_at, feedback_id),
        )
        if updated.rowcount != 1:
            raise ValueError("Feedback admission changed during decision")
        cur = conn.execute(
            """INSERT INTO feedback_admission_actions
            (feedback_id,action,previous_status,resulting_status,reason,created_at)
            VALUES(?,?,?,?,?,?)""",
            (feedback_id, action, previous_status, resulting_status, reason, decided_at),
        )
        action_row = conn.execute(
            "SELECT * FROM feedback_admission_actions WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        feedback_row = conn.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        return {"feedback": dict(feedback_row), "admission_action": dict(action_row)}

    def decide_feedback_admission(self, feedback_id: int, data: dict[str, Any]) -> dict[str, Any]:
        action = str(data["action"])
        resulting_status = self._feedback_resulting_status(action)
        with self.connect() as conn:
            feedback = conn.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
            if not feedback:
                raise ValueError("Feedback not found")
            return self._apply_feedback_admission(
                conn,
                feedback,
                action,
                resulting_status,
                str(data.get("reason", "")),
                utc_now(),
            )

    def decide_feedback_admission_bulk(
        self,
        role_id: int,
        feedback_ids: list[int],
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        action = str(data["action"])
        resulting_status = self._feedback_resulting_status(action)
        unique_ids = list(dict.fromkeys(int(feedback_id) for feedback_id in feedback_ids))
        if not unique_ids:
            raise ValueError("At least one feedback_id is required")
        placeholders = ",".join("?" for _ in unique_ids)
        reason = str(data.get("reason", ""))
        decided_at = utc_now()
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM feedback WHERE role_id=? AND id IN ({placeholders})",
                (role_id, *unique_ids),
            ).fetchall()
            by_id = {int(row["id"]): row for row in rows}
            missing = [feedback_id for feedback_id in unique_ids if feedback_id not in by_id]
            if missing:
                raise ValueError(f"Feedback not found for role: {missing}")
            decided = [
                feedback_id
                for feedback_id in unique_ids
                if str(by_id[feedback_id]["admission_status"]) != "CANDIDATE"
            ]
            if decided:
                raise ValueError(f"Feedback admission has already been decided: {decided}")

            return [
                self._apply_feedback_admission(
                    conn,
                    by_id[feedback_id],
                    action,
                    resulting_status,
                    reason,
                    decided_at,
                )
                for feedback_id in unique_ids
            ]

    def list_feedback_admission_actions(self, feedback_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM feedback_admission_actions WHERE feedback_id=? ORDER BY id",
                    (feedback_id,),
                )
            ]

    def save_generation(self, data: dict[str, Any]) -> int:
        run_id = self.start_generation(data)
        self.finish_generation(run_id, data)
        return run_id

    def start_generation(self, data: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO generation_runs(role_id,request_json,retrieved_json,draft,final_text,review_json,status,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (
                    data["role_id"],
                    json.dumps(data["request"], ensure_ascii=False),
                    json.dumps(data.get("retrieved", []), ensure_ascii=False),
                    data.get("draft", ""),
                    data.get("final_text", ""),
                    json.dumps(data.get("review", []), ensure_ascii=False),
                    data.get("status", "RUNNING"),
                    utc_now(),
                ),
            )
            return int(cur.lastrowid)

    def finish_generation(self, run_id: int, data: dict[str, Any]) -> None:
        approval_status = "NOT_APPLICABLE" if data["status"] in {"FAILED", "BLOCKED"} else "PENDING_REVIEW"
        with self.connect() as conn:
            conn.execute(
                """UPDATE generation_runs
                SET retrieved_json=?, draft=?, final_text=?, review_json=?, status=?,
                    approval_status=?, human_final_text=?
                WHERE id=?""",
                (
                    json.dumps(data.get("retrieved", []), ensure_ascii=False),
                    data.get("draft", ""),
                    data.get("final_text", ""),
                    json.dumps(data.get("review", []), ensure_ascii=False),
                    data["status"],
                    approval_status,
                    data.get("final_text", ""),
                    run_id,
                ),
            )

    def add_generation_step(self, run_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO generation_run_steps
                (generation_run_id,step_index,step_name,input_json,output_json,provider,model,
                prompt_version,duration_ms,status,error_message,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    data["step_index"],
                    data["step_name"],
                    json.dumps(data.get("input", {}), ensure_ascii=False),
                    json.dumps(data.get("output", {}), ensure_ascii=False),
                    data.get("provider", ""),
                    data.get("model", ""),
                    data.get("prompt_version", ""),
                    max(0, int(data.get("duration_ms", 0))),
                    data["status"],
                    data.get("error_message", ""),
                    utc_now(),
                ),
            )
            row = conn.execute("SELECT * FROM generation_run_steps WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._decode_generation_step(row) or {}

    @staticmethod
    def _decode_generation_step(row: sqlite3.Row | None) -> dict[str, Any] | None:
        result = dict(row) if row else None
        if result:
            result["input"] = json.loads(result.pop("input_json"))
            result["output"] = json.loads(result.pop("output_json"))
        return result

    def list_generation_steps(self, run_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM generation_run_steps WHERE generation_run_id=? ORDER BY step_index",
                (run_id,),
            ).fetchall()
        return [item for row in rows if (item := self._decode_generation_step(row)) is not None]

    def list_generation_runs(self, role_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM generation_runs WHERE role_id=? ORDER BY id DESC",
                (role_id,),
            ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            for key in ("request_json", "retrieved_json", "review_json"):
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
            results.append(result)
        return results

    @staticmethod
    def _text_diff(before: str, after: str) -> str:
        return "".join(
            unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="before",
                tofile="after",
            )
        )

    def add_review_action(self, run_id: int, data: dict[str, Any]) -> dict[str, Any]:
        action = data["action"]
        with self.connect() as conn:
            generation = conn.execute("SELECT * FROM generation_runs WHERE id=?", (run_id,)).fetchone()
            if not generation:
                raise ValueError("Generation run not found")
            previous_status = str(generation["approval_status"])
            if previous_status == "NOT_APPLICABLE":
                raise ValueError("Failed or unfinished generation cannot be reviewed")
            current_text = str(generation["human_final_text"] or generation["final_text"])

            if action == "EDIT":
                if previous_status not in {"PENDING_REVIEW", "APPROVED"}:
                    raise ValueError("Only pending or approved content can be edited")
                after = str(data.get("edited_text", "")).strip()
                if not after:
                    raise ValueError("edited_text is required for EDIT")
                resulting_status = "PENDING_REVIEW"
            elif action == "APPROVE":
                if previous_status != "PENDING_REVIEW":
                    raise ValueError("Only pending content can be approved")
                after = str(data.get("edited_text") or current_text).strip()
                resulting_status = "APPROVED"
            elif action == "REJECT":
                if previous_status != "PENDING_REVIEW":
                    raise ValueError("Only pending content can be rejected")
                after = current_text
                resulting_status = "REJECTED"
            else:
                raise ValueError("Unknown review action")

            cur = conn.execute(
                """INSERT INTO review_actions
                (generation_run_id,action,previous_status,resulting_status,content_before,
                content_after,diff_text,reason,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    action,
                    previous_status,
                    resulting_status,
                    current_text,
                    after,
                    self._text_diff(current_text, after),
                    data.get("reason", ""),
                    utc_now(),
                ),
            )
            conn.execute(
                "UPDATE generation_runs SET approval_status=?, human_final_text=? WHERE id=?",
                (resulting_status, after, run_id),
            )
            row = conn.execute("SELECT * FROM review_actions WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def list_review_actions(self, run_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM review_actions WHERE generation_run_id=? ORDER BY id",
                    (run_id,),
                )
            ]

    @staticmethod
    def _build_review_summary(
        auto_status: str,
        reviews: list[dict[str, Any]],
        rewrite_count: int,
    ) -> dict[str, Any]:
        issues = list(
            dict.fromkeys(
                str(issue)
                for review in reviews
                for issue in (review.get("issues") or [])
                if str(issue).strip()
            )
        )
        blocked_reason = next(
            (str(review.get("blocked_reason", "")) for review in reversed(reviews) if review.get("blocked_reason")),
            "",
        )
        reason_text = "；".join(issues[:3])
        if auto_status == "BLOCKED":
            summary_text = f"自动审核阻塞：{blocked_reason or '缺少有效审核结论'}"
        elif auto_status == "FAILED":
            summary_text = "生成过程失败，不能进入人工审批"
        elif auto_status == "PASS" and rewrite_count:
            summary_text = f"经过 {rewrite_count} 轮改写，最终自动审核通过"
        elif auto_status == "PASS":
            summary_text = "初稿自动审核通过，无需改写"
        elif auto_status == "REVISE":
            summary_text = f"经过 {rewrite_count} 轮改写后仍需人工处理"
        else:
            summary_text = f"自动状态：{auto_status}"
        if reason_text and auto_status != "BLOCKED":
            summary_text += f"；审核原因：{reason_text}"
        return {
            "auto_status": auto_status,
            "review_count": len(reviews),
            "rewrite_count": rewrite_count,
            "issues": issues,
            "blocked_reason": blocked_reason,
            "summary_text": summary_text,
        }

    def list_review_inbox(
        self,
        role_id: int,
        approval_status: str = "PENDING_REVIEW",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        allowed = {"PENDING_REVIEW", "APPROVED", "REJECTED", "NOT_APPLICABLE"}
        if approval_status not in allowed:
            raise ValueError("Unknown approval status")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT generation_runs.*,
                    (SELECT COUNT(*) FROM generation_run_steps
                     WHERE generation_run_id=generation_runs.id
                       AND step_name LIKE 'revise_%') AS rewrite_count
                FROM generation_runs
                WHERE role_id=? AND approval_status=?
                ORDER BY id DESC LIMIT ? OFFSET ?""",
                (role_id, approval_status, limit, offset),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            rewrite_count = int(item.pop("rewrite_count"))
            item["request"] = json.loads(item.pop("request_json"))
            item.pop("retrieved_json")
            reviews = json.loads(item.pop("review_json"))
            item["review_summary"] = self._build_review_summary(
                str(item["status"]), reviews, rewrite_count
            )
            item["current_text"] = item["human_final_text"] or item["final_text"]
            results.append(item)
        return results

    def get_generation(self, run_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            result = self._dict(conn.execute("SELECT * FROM generation_runs WHERE id=?", (run_id,)).fetchone())
        if result:
            for key in ("request_json", "retrieved_json", "review_json"):
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
            result["steps"] = self.list_generation_steps(run_id)
            result["review_actions"] = self.list_review_actions(run_id)
            result["retrieval_feedback"] = self.list_retrieval_feedback(run_id)
            result["current_text"] = result["human_final_text"] or result["final_text"]
        return result

    def add_retrieval_feedback(self, run_id: int, data: dict[str, Any]) -> dict[str, Any]:
        post_id = int(data["post_id"])
        action = str(data["action"])
        if action != "NOT_RELEVANT":
            raise ValueError("Only NOT_RELEVANT is valid for generation retrieval feedback")
        with self.connect() as conn:
            generation = conn.execute("SELECT * FROM generation_runs WHERE id=?", (run_id,)).fetchone()
            if not generation:
                raise ValueError("Generation run not found")
            role_id = int(generation["role_id"])
            retrieved = json.loads(generation["retrieved_json"])
            retrieved_ids = {int(item["post_id"]) for item in retrieved}
            if post_id not in retrieved_ids:
                raise ValueError("Post was not retrieved by this generation run")
            post = conn.execute(
                "SELECT * FROM posts WHERE id=? AND role_id=?", (post_id, role_id)
            ).fetchone()
            if not post:
                raise ValueError("Post not found for generation role")
            duplicate = conn.execute(
                """SELECT id FROM retrieval_feedback
                WHERE generation_run_id=? AND post_id=? AND action=?""",
                (run_id, post_id, action),
            ).fetchone()
            if duplicate:
                raise ValueError("The same retrieval feedback has already been recorded")

            cur = conn.execute(
                """INSERT INTO retrieval_feedback
                (generation_run_id,role_id,post_id,action,reason,query_json,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (
                    run_id,
                    role_id,
                    post_id,
                    action,
                    data.get("reason", ""),
                    generation["request_json"],
                    utc_now(),
                ),
            )
            row = conn.execute("SELECT * FROM retrieval_feedback WHERE id=?", (cur.lastrowid,)).fetchone()
        result = dict(row)
        result["query"] = json.loads(result.pop("query_json"))
        result["effect"] = "RECORDED_ONLY"
        result["post_retrieval_status"] = str(post["retrieval_status"])
        return result

    def update_post_retrieval_status(self, post_id: int, data: dict[str, Any]) -> dict[str, Any]:
        action = str(data["action"])
        resulting_status = {"RETIRE": "RETIRED", "RESTORE": "ACTIVE"}.get(action)
        if resulting_status is None:
            raise ValueError("Unknown post retrieval action")
        with self.connect() as conn:
            post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            if not post:
                raise ValueError("Post not found")
            previous_status = str(post["retrieval_status"])
            if previous_status == resulting_status:
                state = "retired" if resulting_status == "RETIRED" else "active"
                raise ValueError(f"Post is already {state}")
            created_at = utc_now()
            conn.execute(
                "UPDATE posts SET retrieval_status=? WHERE id=?",
                (resulting_status, post_id),
            )
            cur = conn.execute(
                """INSERT INTO post_retrieval_actions
                (role_id,post_id,action,previous_status,resulting_status,reason,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (
                    int(post["role_id"]),
                    post_id,
                    action,
                    previous_status,
                    resulting_status,
                    data.get("reason", ""),
                    created_at,
                ),
            )
            updated_post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            action_row = conn.execute(
                "SELECT * FROM post_retrieval_actions WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return {"post": dict(updated_post), "retrieval_action": dict(action_row)}

    def list_post_retrieval_actions(self, post_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM post_retrieval_actions WHERE post_id=? ORDER BY id",
                    (post_id,),
                )
            ]

    def list_retrieval_feedback(self, run_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM retrieval_feedback WHERE generation_run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["query"] = json.loads(item.pop("query_json"))
            results.append(item)
        return results

    @staticmethod
    def _decode_eval_case(row: sqlite3.Row | None) -> dict[str, Any] | None:
        result = dict(row) if row else None
        if result:
            result["input_data"] = json.loads(result.pop("input_json"))
            result["expected_data"] = json.loads(result.pop("expected_json"))
            result["tags"] = json.loads(result.pop("tags_json"))
            result["active"] = bool(result["active"])
        return result

    def create_eval_case(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO eval_cases
                (role_id,name,input_json,expected_json,tags_json,version,active,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (
                    data["role_id"],
                    data["name"],
                    json.dumps(data["input_data"], ensure_ascii=False),
                    json.dumps(data.get("expected_data", {}), ensure_ascii=False),
                    json.dumps(data.get("tags", []), ensure_ascii=False),
                    data.get("version", "1.0.0"),
                    int(data.get("active", True)),
                    utc_now(),
                ),
            )
            row = conn.execute("SELECT * FROM eval_cases WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._decode_eval_case(row) or {}

    def get_eval_case(self, eval_case_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM eval_cases WHERE id=?", (eval_case_id,)).fetchone()
        return self._decode_eval_case(row)

    def list_eval_cases(self, role_id: int, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM eval_cases WHERE role_id=?"
        params: tuple[Any, ...] = (role_id,)
        if active_only:
            query += " AND active=1"
        query += " ORDER BY id"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [item for row in rows if (item := self._decode_eval_case(row)) is not None]

    @staticmethod
    def _decode_eval_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
        result = dict(row) if row else None
        if result:
            result["config"] = json.loads(result.pop("config_json"))
        return result

    def create_eval_run(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        status = data.get("status", "RUNNING")
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO eval_runs
                (eval_case_id,generation_run_id,config_json,status,started_at,completed_at)
                VALUES(?,?,?,?,?,?)""",
                (
                    data["eval_case_id"],
                    data.get("generation_run_id"),
                    json.dumps(data.get("config", {}), ensure_ascii=False),
                    status,
                    now,
                    now if status in {"COMPLETED", "FAILED"} else None,
                ),
            )
            row = conn.execute("SELECT * FROM eval_runs WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._decode_eval_run(row) or {}

    def get_eval_run(self, eval_run_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM eval_runs WHERE id=?", (eval_run_id,)).fetchone()
        result = self._decode_eval_run(row)
        if result:
            result["scores"] = self.list_eval_scores(eval_run_id)
        return result

    def finish_eval_run(self, eval_run_id: int, status: str) -> dict[str, Any] | None:
        if status not in {"COMPLETED", "FAILED"}:
            raise ValueError("finished evaluation status must be COMPLETED or FAILED")
        with self.connect() as conn:
            conn.execute(
                "UPDATE eval_runs SET status=?, completed_at=? WHERE id=?",
                (status, utc_now(), eval_run_id),
            )
            row = conn.execute("SELECT * FROM eval_runs WHERE id=?", (eval_run_id,)).fetchone()
        return self._decode_eval_run(row)

    def add_eval_score(self, eval_run_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO eval_scores
                (eval_run_id,metric_name,value,threshold,passed,reason,evaluator,version,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    eval_run_id,
                    data["metric_name"],
                    data["value"],
                    data["threshold"],
                    int(float(data["value"]) >= float(data["threshold"])),
                    data.get("reason", ""),
                    data.get("evaluator", "rule"),
                    data.get("version", "1.0.0"),
                    utc_now(),
                ),
            )
            row = conn.execute("SELECT * FROM eval_scores WHERE id=?", (cur.lastrowid,)).fetchone()
        result = dict(row)
        result["passed"] = bool(result["passed"])
        return result

    def list_eval_scores(self, eval_run_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_scores WHERE eval_run_id=? ORDER BY id",
                (eval_run_id,),
            ).fetchall()
        results = [dict(row) for row in rows]
        for result in results:
            result["passed"] = bool(result["passed"])
        return results
