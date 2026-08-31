from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Any, Iterator


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
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_role ON feedback(role_id);
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

    def list_roles(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM roles ORDER BY id")]

    def get_role(self, role_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._dict(conn.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone())

    def create_role(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO roles(name, description, identity_rules, created_at) VALUES(?,?,?,?)",
                (data["name"], data.get("description", ""), data.get("identity_rules", ""), utc_now()),
            )
            row = conn.execute("SELECT * FROM roles WHERE id=?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def add_post(self, data: dict[str, Any]) -> dict[str, Any]:
        fields = ("role_id", "title", "text", "platform", "language", "content_type", "topic", "tone", "authenticity", "published_at", "source_name")
        values = [data.get(k, "") for k in fields]
        values[8] = data.get("authenticity", 3)
        values[9] = data.get("published_at")
        with self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO posts({','.join(fields)},created_at) VALUES({','.join('?' for _ in fields)},?)",
                (*values, utc_now()),
            )
            return dict(conn.execute("SELECT * FROM posts WHERE id=?", (cur.lastrowid,)).fetchone())

    def list_posts(self, role_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM posts WHERE role_id=? ORDER BY id", (role_id,))]

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

    def list_feedback(self, role_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM feedback WHERE role_id=? ORDER BY id DESC", (role_id,))]

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

    def list_review_inbox(self, role_id: int, approval_status: str = "PENDING_REVIEW") -> list[dict[str, Any]]:
        allowed = {"PENDING_REVIEW", "APPROVED", "REJECTED", "NOT_APPLICABLE"}
        if approval_status not in allowed:
            raise ValueError("Unknown approval status")
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM generation_runs
                WHERE role_id=? AND approval_status=? ORDER BY id DESC""",
                (role_id, approval_status),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["request"] = json.loads(item.pop("request_json"))
            item.pop("retrieved_json")
            item.pop("review_json")
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
            result["current_text"] = result["human_final_text"] or result["final_text"]
        return result

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
