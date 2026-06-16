import sqlite3
import json
from datetime import datetime
from typing import Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name    TEXT NOT NULL,
    props        TEXT NOT NULL DEFAULT '{}',
    data         TEXT NOT NULL DEFAULT '',
    level        TEXT NOT NULL DEFAULT 'silent',
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_level_status ON messages(level, status);
CREATE INDEX IF NOT EXISTS idx_type_name ON messages(type_name);
"""

# 旧版迁移：检测旧表（有 source/type/content 列），升级到新 schema
_OLD_SCHEMA_MIGRATED = False


def _ensure_schema(conn: sqlite3.Connection) -> None:
    global _OLD_SCHEMA_MIGRATED
    if _OLD_SCHEMA_MIGRATED:
        return
    # 检测是否已迁移
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "level" in cols:
        _OLD_SCHEMA_MIGRATED = True
        return

    # 旧表：source, type, content, metadata → 迁移到新 schema
    conn.executescript("""
        ALTER TABLE messages RENAME TO messages_old;
    """ + SCHEMA_SQL + """
        INSERT INTO messages (id, type_name, props, data, level, status, created_at, processed_at)
        SELECT
            id,
            type,                        -- type_name
            '{}',                        -- props（旧表无此信息，默认空）
            content,                     -- data
            'popup',                     -- level（旧消息视为 popup）
            status,
            created_at,
            processed_at
        FROM messages_old;
        DROP TABLE messages_old;
    """)
    conn.commit()
    _OLD_SCHEMA_MIGRATED = True


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def add_message(
    db_path: str,
    type_name: str,
    props: Optional[dict] = None,
    data: object = "",
    level: str = "silent",
) -> int:
    conn = _connect(db_path)
    status = "pending" if level == "popup" else "silent"
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    serialized_data = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    cur = conn.execute(
        "INSERT INTO messages (type_name, props, data, level, status) VALUES (?, ?, ?, ?, ?)",
        [type_name, json.dumps(props or {}, ensure_ascii=False), serialized_data, level, status],
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def get_popup_messages(
    db_path: str,
    limit: int = 10,
    offset: int = 0,
) -> list[sqlite3.Row]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM messages WHERE level='popup' AND status='pending' ORDER BY created_at LIMIT ? OFFSET ?",
        [limit, offset],
    ).fetchall()
    conn.close()
    return rows


def get_popup_messages_since(
    db_path: str,
    since: str,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """获取 since 之后新增的 pending popup 消息。"""
    if not since:
        return get_popup_messages(db_path, limit=limit)
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM messages WHERE level='popup' AND status='pending' AND created_at > ? ORDER BY created_at LIMIT ?",
        [since, limit],
    ).fetchall()
    conn.close()
    return rows


def get_message(db_path: str, msg_id: int):
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT * FROM messages WHERE id = ?", [msg_id]
    ).fetchone()
    conn.close()
    return row


def mark_processed(db_path: str, msg_ids: list[int]) -> int:
    if not msg_ids:
        return 0
    placeholders = ",".join("?" for _ in msg_ids)
    conn = _connect(db_path)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        f"UPDATE messages SET status='processed', processed_at=? WHERE id IN ({placeholders})",
        [now] + msg_ids,
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def mark_all_popup_processed(db_path: str) -> int:
    conn = _connect(db_path)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "UPDATE messages SET status='processed', processed_at=? WHERE level='popup' AND status='pending'",
        [now],
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def count_pending(db_path: str) -> int:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages WHERE level='popup' AND status='pending'", []
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def count_by_level(db_path: str) -> dict:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT level, status, COUNT(*) AS cnt FROM messages GROUP BY level, status", []
    ).fetchall()
    conn.close()
    result = {"popup": {"pending": 0, "processed": 0}, "silent": 0}
    for r in rows:
        lvl = r["level"]
        if lvl == "silent":
            result["silent"] = r["cnt"]
        else:
            st = r["status"]
            result["popup"][st] = r["cnt"]
    return result


def search_messages(
    db_path: str,
    level: Optional[str] = None,
    type_name: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    conditions = []
    params = []

    if level:
        conditions.append("level = ?")
        params.append(level)
    if type_name:
        conditions.append("type_name = ?")
        params.append(type_name)
    if search:
        conditions.append("data LIKE ?")
        params.append(f"%{search}%")

    where = " AND ".join(conditions) if conditions else "1=1"
    conn = _connect(db_path)
    rows = conn.execute(
        f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return rows


def exclude_pending_by_type(db_path: str, type_name: str) -> int:
    """将指定 type 的 pending popup 降级为 silent（AI 取消订阅后调用）"""
    conn = _connect(db_path)
    cur = conn.execute(
        "UPDATE messages SET level='silent', status='silent' WHERE type_name=? AND level='popup' AND status='pending'",
        [type_name],
    )
    conn.commit()
    conn.close()
    return cur.rowcount


