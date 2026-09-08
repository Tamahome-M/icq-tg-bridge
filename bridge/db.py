"""Хранилище моста: соответствие UIN <-> чат Telegram и очередь сообщений
для телефона, который сейчас не в сети."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

# UIN чатов начинаются отсюда: семизначные, как настоящие ICQ-номера,
# и заведомо выше UIN владельца из конфига.
UIN_BASE = 1000000


@dataclass
class Contact:
    uin: int
    peer_id: int
    kind: str          # user | bot | chat | channel
    title: str
    group_name: str
    position: int      # порядок в списке диалогов Telegram
    topic_id: int = 0  # тема форума; 0 — обычный чат
    last_ts: int = 0   # время последнего сообщения, дошедшего до телефона
    gone: int = 0      # 1, если чата больше нет в Telegram
    favourite: int = 0  # 1 — чат закреплён или назван избранным в настройках


class Storage:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                uin        INTEGER PRIMARY KEY,
                peer_id    INTEGER NOT NULL,
                topic_id   INTEGER NOT NULL DEFAULT 0,
                kind       TEXT    NOT NULL DEFAULT 'user',
                title      TEXT    NOT NULL DEFAULT '',
                group_name TEXT    NOT NULL DEFAULT '',
                position   INTEGER NOT NULL DEFAULT 0,
                last_ts    INTEGER NOT NULL DEFAULT 0,
                gone       INTEGER NOT NULL DEFAULT 0,
                favourite  INTEGER NOT NULL DEFAULT 0,
                fav_manual INTEGER,
                UNIQUE (peer_id, topic_id)
            );
            CREATE TABLE IF NOT EXISTS pending (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                uin     INTEGER NOT NULL,
                text    TEXT    NOT NULL,
                ts      INTEGER NOT NULL,
                sent_at INTEGER NOT NULL DEFAULT 0,
                forced  INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS pending_uin ON pending(uin);
            CREATE TABLE IF NOT EXISTS held (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                uin  INTEGER NOT NULL,
                text TEXT    NOT NULL,
                ts   INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            );
            """
        )
        # Колонка появилась позже — доводим базы, созданные ранними версиями.
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(contacts)")}
        if "last_ts" not in columns:
            self.conn.execute(
                "ALTER TABLE contacts ADD COLUMN last_ts INTEGER NOT NULL DEFAULT 0")
        if "gone" not in columns:
            self.conn.execute(
                "ALTER TABLE contacts ADD COLUMN gone INTEGER NOT NULL DEFAULT 0")
        if "favourite" not in columns:
            self.conn.execute(
                "ALTER TABLE contacts ADD COLUMN favourite INTEGER NOT NULL DEFAULT 0")
        if "fav_manual" not in columns:
            self.conn.execute("ALTER TABLE contacts ADD COLUMN fav_manual INTEGER")
        if "topic_id" not in columns:
            # Темы форумов — отдельные собеседники, поэтому ключ стал парой
            # (чат, тема). Уникальность в SQLite так просто не переставить,
            # поэтому переносим данные в новую таблицу.
            self.conn.executescript(
                """
                CREATE TABLE contacts_new (
                    uin        INTEGER PRIMARY KEY,
                    peer_id    INTEGER NOT NULL,
                    topic_id   INTEGER NOT NULL DEFAULT 0,
                    kind       TEXT    NOT NULL DEFAULT 'user',
                    title      TEXT    NOT NULL DEFAULT '',
                    group_name TEXT    NOT NULL DEFAULT '',
                    position   INTEGER NOT NULL DEFAULT 0,
                    last_ts    INTEGER NOT NULL DEFAULT 0,
                    gone       INTEGER NOT NULL DEFAULT 0,
                    favourite  INTEGER NOT NULL DEFAULT 0,
                    fav_manual INTEGER,
                    UNIQUE (peer_id, topic_id)
                );
                INSERT INTO contacts_new
                    (uin, peer_id, topic_id, kind, title, group_name, position,
                     last_ts, gone, favourite, fav_manual)
                SELECT uin, peer_id, 0, kind, title, group_name, position,
                       last_ts, gone, favourite, fav_manual FROM contacts;
                DROP TABLE contacts;
                ALTER TABLE contacts_new RENAME TO contacts;
                """
            )
        pending_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(pending)")}
        if "sent_at" not in pending_columns:
            self.conn.execute(
                "ALTER TABLE pending ADD COLUMN sent_at INTEGER NOT NULL DEFAULT 0")
        if "forced" not in pending_columns:
            self.conn.execute(
                "ALTER TABLE pending ADD COLUMN forced INTEGER NOT NULL DEFAULT 0")

    # --- контакты -------------------------------------------------------

    def uin_for_peer(self, peer_id: int, *, kind: str, title: str,
                     group_name: str, position: int = 0, favourite: int = 0,
                     topic_id: int = 0) -> int:
        """Возвращает UIN чата, заводя его при первой встрече.

        topic_id отличает темы форума: у каждой темы свой собеседник.
        """
        row = self.conn.execute(
            "SELECT uin FROM contacts WHERE peer_id = ? AND topic_id = ?",
            (peer_id, topic_id),
        ).fetchone()
        if row:
            uin = row["uin"]
            self.conn.execute(
                "UPDATE contacts SET kind=?, title=?, group_name=?, position=?, gone=0,"
                " favourite=? WHERE uin=?",
                (kind, title, group_name, position, favourite, uin),
            )
            return uin
        row = self.conn.execute("SELECT MAX(uin) AS m FROM contacts").fetchone()
        uin = max(row["m"] or 0, UIN_BASE) + 1
        self.conn.execute(
            "INSERT INTO contacts (uin, peer_id, topic_id, kind, title, group_name,"
            " position, favourite) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uin, peer_id, topic_id, kind, title, group_name, position, favourite),
        )
        return uin

    def contacts(self, limit: int = 0) -> list[Contact]:
        """Контакт-лист: то, что сейчас есть в Telegram.

        limit оставляет только самые свежие чаты: старые телефоны не тянут
        сотни контактов. Избранные остаются в списке при любом ограничении.
        """
        rows = self.conn.execute(
            "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts, gone, COALESCE(fav_manual, favourite) AS favourite FROM contacts WHERE gone = 0 ORDER BY position, uin"
        ).fetchall()
        contacts = [Contact(**dict(r)) for r in rows]
        if limit > 0 and len(contacts) > limit:
            keep = [c for c in contacts if c.favourite][:limit]
            for contact in contacts:
                if len(keep) >= limit:
                    break
                if not contact.favourite:
                    keep.append(contact)
            contacts = sorted(keep, key=lambda c: (c.position, c.uin))
        return contacts

    def toggle_favourite(self, uin: int) -> bool | None:
        """Переключает избранность чата вручную. Возвращает новое значение.

        Ручной выбор хранится отдельно от автоматического: обновление списка
        диалогов перепишет признак закреплённого чата, но не решение владельца.
        """
        contact = self.contact_by_uin(uin)
        if contact is None:
            return None
        value = 0 if contact.favourite else 1
        self.conn.execute("UPDATE contacts SET fav_manual = ? WHERE uin = ?", (value, uin))
        return bool(value)

    def mark_missing(self, present: list[int]) -> list[Contact]:
        """Помечает чаты, которых больше нет в Telegram, и возвращает их.

        Записи не удаляем: если чат вернётся, за ним останется прежний UIN,
        а вместе с ним и история переписки на телефоне.
        """
        if not present:
            return []          # пустой список диалогов — скорее сбой, чем удаление
        marks = ",".join("?" * len(present))
        # present — список peer_id; темы исчезнувшего чата уходят вместе с ним
        rows = self.conn.execute(
            f"SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts, gone, COALESCE(fav_manual, favourite) AS favourite FROM contacts WHERE gone = 0 AND peer_id NOT IN ({marks})",
            present,
        ).fetchall()
        if rows:
            self.conn.executemany(
                "UPDATE contacts SET gone = 1 WHERE uin = ?",
                [(r["uin"],) for r in rows],
            )
        return [Contact(**dict(r)) for r in rows]

    def contact_by_uin(self, uin: int) -> Contact | None:
        row = self.conn.execute(
            "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts, gone, COALESCE(fav_manual, favourite) AS favourite FROM contacts WHERE uin = ?", (uin,)).fetchone()
        return Contact(**dict(row)) if row else None

    def contact_by_peer(self, peer_id: int, topic_id: int = 0) -> Contact | None:
        row = self.conn.execute(
            "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts,"
            " gone, COALESCE(fav_manual, favourite) AS favourite"
            " FROM contacts WHERE peer_id = ? AND topic_id = ?",
            (peer_id, topic_id),
        ).fetchone()
        return Contact(**dict(row)) if row else None

    # --- очередь офлайна ------------------------------------------------

    def queue(self, uin: int, text: str, limit_per_chat: int, forced: bool = False) -> None:
        """forced — ответ на команду с телефона: такое доставляем при любом статусе."""
        self.conn.execute(
            "INSERT INTO pending (uin, text, ts, forced) VALUES (?, ?, ?, ?)",
            (uin, text, int(time.time()), int(forced)),
        )
        self.conn.execute(
            "DELETE FROM pending WHERE uin = ? AND id NOT IN ("
            "  SELECT id FROM pending WHERE uin = ? ORDER BY id DESC LIMIT ?)",
            (uin, uin, limit_per_chat),
        )

    def peek_pending(self) -> list[tuple[int, int, str, int]]:
        """Записи, ожидающие отправки. Уже отправленные, но ещё не
        подтверждённые, пропускаем — чтобы не слать их повторно."""
        rows = self.conn.execute(
            "SELECT id, uin, text, ts, forced FROM pending WHERE sent_at = 0 ORDER BY id"
        ).fetchall()
        return [(r["id"], r["uin"], r["text"], r["ts"], bool(r["forced"])) for r in rows]

    def mark_sent(self, row_id: int) -> None:
        self.conn.execute("UPDATE pending SET sent_at = ? WHERE id = ?",
                          (int(time.time()), row_id))

    def reset_sent(self, older_than: int | None = None) -> int:
        """Возвращает в очередь отправленное, но не подтверждённое.

        Без аргумента — всё сразу (телефон отключился); с аргументом —
        только то, что ждёт подтверждения дольше указанного числа секунд.
        """
        if older_than is None:
            cur = self.conn.execute("UPDATE pending SET sent_at = 0 WHERE sent_at > 0")
        else:
            cur = self.conn.execute(
                "UPDATE pending SET sent_at = 0 WHERE sent_at > 0 AND sent_at < ?",
                (int(time.time()) - older_than,))
        return cur.rowcount

    def in_flight_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM pending WHERE sent_at > 0").fetchone()["c"]

    def drop_pending(self, row_id: int) -> None:
        self.conn.execute("DELETE FROM pending WHERE id = ?", (row_id,))

    def pending_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM pending").fetchone()["c"]

    # --- придержанное на время «занят» ----------------------------------

    def hold(self, uin: int, text: str, ts: int, limit_per_chat: int) -> None:
        self.conn.execute("INSERT INTO held (uin, text, ts) VALUES (?, ?, ?)",
                          (uin, text, ts))
        self.conn.execute(
            "DELETE FROM held WHERE uin = ? AND id NOT IN ("
            "  SELECT id FROM held WHERE uin = ? ORDER BY id DESC LIMIT ?)",
            (uin, uin, limit_per_chat),
        )

    def take_held(self) -> list[tuple[int, str, int]]:
        """Забирает придержанное целиком: что доставить, решает мост."""
        rows = self.conn.execute("SELECT uin, text, ts FROM held ORDER BY id").fetchall()
        if rows:
            self.conn.execute("DELETE FROM held")
        return [(r["uin"], r["text"], r["ts"]) for r in rows]

    def held_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM held").fetchone()["c"]

    def note_delivered(self, peer_id: int, ts: int, topic_id: int = 0) -> None:
        """Запоминает, до какого момента чат уже доставлен на телефон."""
        self.conn.execute(
            "UPDATE contacts SET last_ts = ? WHERE peer_id = ? AND topic_id = ? AND last_ts < ?",
            (ts, peer_id, topic_id, ts),
        )

    # --- прочее ---------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, value),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        return row["v"] if row else default

    def close(self) -> None:
        self.conn.close()
