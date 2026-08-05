from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
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
                    created_at TEXT NOT NULL
                );
                """
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
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO generation_runs(role_id,request_json,retrieved_json,draft,final_text,review_json,status,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (data["role_id"], json.dumps(data["request"], ensure_ascii=False), json.dumps(data["retrieved"], ensure_ascii=False), data["draft"], data["final_text"], json.dumps(data["review"], ensure_ascii=False), data["status"], utc_now()),
            )
            return int(cur.lastrowid)

    def get_generation(self, run_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            result = self._dict(conn.execute("SELECT * FROM generation_runs WHERE id=?", (run_id,)).fetchone())
        if result:
            for key in ("request_json", "retrieved_json", "review_json"):
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
        return result

