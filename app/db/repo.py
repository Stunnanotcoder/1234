from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import aiosqlite


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class User:
    telegram_id: int
    consent: int
    consent_at: str | None
    notify_enabled: int
    notify_consent_at: str | None
    name: str | None
    email: str | None
    role: str | None
    phone: str | None
    city: str | None
    designer_interest: int | None  # ✅ новое поле (может быть None если старая БД)
    designer_interest_at: str | None  # ✅ когда нажал "Сотрудничать"
    created_at: str | None
    updated_at: str | None


class Repo:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys=ON;")

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    def _c(self) -> aiosqlite.Connection:
        if not self.conn:
            raise RuntimeError("DB not connected")
        return self.conn

    async def init_schema(self, schema_path: str) -> None:
        """
        1) Создаёт таблицы из schema.sql (CREATE TABLE IF NOT EXISTS)
        2) Делает миграции для существующей БД (ALTER TABLE если колонок нет)
        """
        sql = Path(schema_path).read_text(encoding="utf-8")
        await self._c().executescript(sql)
        await self._c().commit()
        await self._apply_migrations()

    async def _apply_migrations(self) -> None:
        # --- users: designer_interest + designer_interest_at ---
        cols = await self._table_columns("users")

        if "designer_interest" not in cols:
            await self._c().execute("ALTER TABLE users ADD COLUMN designer_interest INTEGER DEFAULT 0")
        if "designer_interest_at" not in cols:
            await self._c().execute("ALTER TABLE users ADD COLUMN designer_interest_at TEXT NULL")

        await self._c().commit()

    async def _table_columns(self, table: str) -> set[str]:
        cur = await self._c().execute(f"PRAGMA table_info({table})")
        rows = await cur.fetchall()
        return {r["name"] for r in rows}

    async def ensure_user_row(self, telegram_id: int) -> None:
        now = utcnow_iso()
        await self._c().execute(
            """
            INSERT INTO users(telegram_id, created_at, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (telegram_id, now, now),
        )
        await self._c().commit()

    async def get_user(self, telegram_id: int) -> User | None:
        cur = await self._c().execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
        row = await cur.fetchone()
        if not row:
            return None

        d = dict(row)

        # На старых БД этих полей может не быть (до миграции)
        d.setdefault("designer_interest", 0)
        d.setdefault("designer_interest_at", None)

        return User(**d)

    async def set_consent(self, telegram_id: int, consent: bool, enable_notify: bool) -> None:
        now = utcnow_iso()
        await self.ensure_user_row(telegram_id)
        if consent:
            await self._c().execute(
                """
                UPDATE users
                SET consent=1, consent_at=?, notify_enabled=?, notify_consent_at=?,
                    updated_at=?
                WHERE telegram_id=?
                """,
                (now, 1 if enable_notify else 0, now if enable_notify else None, now, telegram_id),
            )
        else:
            await self._c().execute(
                """
                UPDATE users
                SET consent=0, consent_at=NULL, notify_enabled=0, notify_consent_at=NULL,
                    name=NULL, email=NULL, role=NULL, phone=NULL, city=NULL,
                    designer_interest=0, designer_interest_at=NULL,
                    updated_at=?
                WHERE telegram_id=?
                """,
                (now, telegram_id),
            )
        await self._c().commit()

    async def update_profile(self, telegram_id: int, **fields) -> None:
        await self.ensure_user_row(telegram_id)
        fields["updated_at"] = utcnow_iso()
        keys = list(fields.keys())
        vals = [fields[k] for k in keys]
        set_sql = ", ".join([f"{k}=?" for k in keys])
        await self._c().execute(
            f"UPDATE users SET {set_sql} WHERE telegram_id=?",
            (*vals, telegram_id),
        )
        await self._c().commit()

    async def toggle_notify(self, telegram_id: int) -> int:
        u = await self.get_user(telegram_id)
        if not u:
            await self.ensure_user_row(telegram_id)
            u = await self.get_user(telegram_id)
        assert u
        new_val = 0 if u.notify_enabled else 1
        now = utcnow_iso()
        await self._c().execute(
            """
            UPDATE users
            SET notify_enabled=?, notify_consent_at=COALESCE(notify_consent_at, ?),
                updated_at=?
            WHERE telegram_id=?
            """,
            (new_val, now, now, telegram_id),
        )
        await self._c().commit()
        return new_val

    async def delete_user(self, telegram_id: int) -> None:
        await self._c().execute("DELETE FROM users WHERE telegram_id=?", (telegram_id,))
        await self._c().commit()

    # ✅ ДИЗАЙНЕР: отметка интереса к сотрудничеству
    async def set_designer_interest(self, telegram_id: int, interested: bool) -> None:
        await self.ensure_user_row(telegram_id)
        now = utcnow_iso()
        await self._c().execute(
            """
            UPDATE users
            SET designer_interest=?,
                designer_interest_at=?,
                updated_at=?
            WHERE telegram_id=?
            """,
            (1 if interested else 0, now if interested else None, now, telegram_id),
        )
        await self._c().commit()

    # --------- Visit requests ---------
    async def create_visit_request(
        self,
        telegram_id: int,
        city: str,
        contact_method: str,
        contact_value: str | None,
        name_snapshot: str | None = None,   # ✅ теперь НЕ обязательно
        role_snapshot: str | None = None,   # ✅ теперь НЕ обязательно
    ) -> None:
        """
        Чтобы меню не падало, snapshots теперь optional.
        Если не передали — попробуем взять из users.
        """
        if name_snapshot is None or role_snapshot is None:
            u = await self.get_user(telegram_id)
            if u:
                if name_snapshot is None:
                    name_snapshot = u.name
                if role_snapshot is None:
                    role_snapshot = u.role

        now = utcnow_iso()
        await self._c().execute(
            """
            INSERT INTO visit_requests(
                telegram_id, name_snapshot, role_snapshot, city,
                contact_method, contact_value, status, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, 'new', ?)
            """,
            (telegram_id, name_snapshot, role_snapshot, city, contact_method, contact_value, now),
        )
        await self._c().commit()

    async def stats(self) -> dict:
        cur1 = await self._c().execute("SELECT COUNT(*) as c FROM users")
        users_count = (await cur1.fetchone())["c"]

        cur2 = await self._c().execute("SELECT COUNT(*) as c FROM users WHERE consent=1 AND notify_enabled=1")
        notify_count = (await cur2.fetchone())["c"]

        cur3 = await self._c().execute("SELECT COUNT(*) as c FROM visit_requests WHERE status='new'")
        vr_new = (await cur3.fetchone())["c"]

        return {"users": users_count, "notify": notify_count, "visit_new": vr_new}

    # --------- Collections / Sculptures ----------
    async def add_collection(self, title: str, short_desc: str | None, cover_file_id: str | None, sort_order: int) -> int:
        now = utcnow_iso()
        cur = await self._c().execute(
            """
            INSERT INTO collections(title, short_desc, cover_photo_file_id, is_active, sort_order, created_at, updated_at)
            VALUES(?, ?, ?, 1, ?, ?, ?)
            """,
            (title, short_desc, cover_file_id, sort_order, now, now),
        )
        await self._c().commit()
        return cur.lastrowid

    async def list_collections(self, active_only: bool = True, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
        where = "WHERE is_active=1" if active_only else ""
        cur_cnt = await self._c().execute(f"SELECT COUNT(*) as c FROM collections {where}")
        total = (await cur_cnt.fetchone())["c"]

        cur = await self._c().execute(
            f"""
            SELECT * FROM collections
            {where}
            ORDER BY sort_order DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows], total

    async def get_collection(self, collection_id: int) -> dict | None:
        cur = await self._c().execute("SELECT * FROM collections WHERE id=?", (collection_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def add_sculpture(self, collection_id: int, **fields) -> int:
        now = utcnow_iso()
        base = {
            "collection_id": collection_id,
            "title": fields.get("title"),
            "artist": fields.get("artist"),
            "year": fields.get("year"),
            "material": fields.get("material"),
            "dimensions": fields.get("dimensions"),
            "description_short": fields.get("description_short"),
            "description_full": fields.get("description_full"),
            "status": fields.get("status", "in_expo"),
            "is_featured": int(bool(fields.get("is_featured", 0))),
            "published_at": fields.get("published_at"),
            "created_at": now,
            "updated_at": now,
        }
        cur = await self._c().execute(
            """
            INSERT INTO sculptures(
                collection_id, title, artist, year, material, dimensions,
                description_short, description_full, status, is_featured,
                published_at, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                base["collection_id"], base["title"], base["artist"], base["year"], base["material"],
                base["dimensions"], base["description_short"], base["description_full"],
                base["status"], base["is_featured"], base["published_at"], base["created_at"], base["updated_at"]
            ),
        )
        await self._c().commit()
        return cur.lastrowid

    async def add_sculpture_photo(self, sculpture_id: int, file_id: str, sort_order: int) -> None:
        await self._c().execute(
            "INSERT INTO sculpture_photos(sculpture_id, file_id, sort_order) VALUES(?, ?, ?)",
            (sculpture_id, file_id, sort_order),
        )
        await self._c().commit()

    async def list_sculptures_by_collection(self, collection_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
        cur_cnt = await self._c().execute(
            "SELECT COUNT(*) as c FROM sculptures WHERE collection_id=?",
            (collection_id,),
        )
        total = (await cur_cnt.fetchone())["c"]

        cur = await self._c().execute(
            """
            SELECT * FROM sculptures
            WHERE collection_id=?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (collection_id, limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows], total

    async def get_sculpture(self, sculpture_id: int) -> dict | None:
        cur = await self._c().execute("SELECT * FROM sculptures WHERE id=?", (sculpture_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_sculpture_photos(self, sculpture_id: int) -> list[dict]:
        cur = await self._c().execute(
            "SELECT * FROM sculpture_photos WHERE sculpture_id=? ORDER BY sort_order ASC, id ASC",
            (sculpture_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def list_new_sculptures(self, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
        cur_cnt = await self._c().execute(
            "SELECT COUNT(*) as c FROM sculptures WHERE published_at IS NOT NULL"
        )
        total = (await cur_cnt.fetchone())["c"]

        cur = await self._c().execute(
            """
            SELECT * FROM sculptures
            WHERE published_at IS NOT NULL
            ORDER BY published_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows], total

    async def list_featured_sculptures(self, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
        cur_cnt = await self._c().execute(
            "SELECT COUNT(*) as c FROM sculptures WHERE is_featured=1"
        )
        total = (await cur_cnt.fetchone())["c"]

        cur = await self._c().execute(
            """
            SELECT * FROM sculptures
            WHERE is_featured=1
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows], total
