"""Хранилище моста: соответствие UIN <-> чат Telegram и очередь сообщений
для телефона, который сейчас не в сети."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

# UIN чатов начинаются отсюда: семизначные, как настоящие ICQ-номера,
# и заведомо выше UIN владельца из конфига.
UIN_BASE = 1000000
PROCESSED_PER_CHAT = 2000       # память о повторах событий и граничной секунде догрузки


def limit_contacts(contacts: list["Contact"], limit: int, background: tuple[str, ...] = (),
                   recent_since: int = 0) -> list["Contact"]:
    """Оставляет не больше limit чатов: избранные, потом свежие, потом фоновые.

    Список должен быть отсортирован по позиции (свежие первыми); порядок
    сохраняется. limit <= 0 — без ограничения.
    """
    if limit <= 0 or len(contacts) <= limit:
        return list(contacts)

    def deferred(c: Contact) -> bool:
        return (c.group_name.strip().lower() in background
                and not (recent_since and c.last_ts >= recent_since))
    keep = [c for c in contacts if c.favourite][:limit]
    for tier in (lambda c: not c.favourite and not deferred(c),
                 lambda c: not c.favourite and deferred(c)):
        for contact in contacts:
            if len(keep) >= limit:
                break
            if tier(contact):
                keep.append(contact)
    return sorted(keep, key=lambda c: (c.position, c.uin))


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
    hidden: int = 0    # 1, если убран из списка с телефона
    muted: int = 0     # 1, если чат заглушён в самом Telegram
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
                hidden     INTEGER NOT NULL DEFAULT 0,
                muted      INTEGER NOT NULL DEFAULT 0,
                UNIQUE (peer_id, topic_id)
            );
            CREATE TABLE IF NOT EXISTS pending (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                uin     INTEGER NOT NULL,
                text    TEXT    NOT NULL,
                ts      INTEGER NOT NULL,
                sent_at INTEGER NOT NULL DEFAULT 0,
                forced  INTEGER NOT NULL DEFAULT 0,
                mention INTEGER NOT NULL DEFAULT 0,
                url     TEXT    NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS pending_uin ON pending(uin);
            CREATE TABLE IF NOT EXISTS processed_messages (
                uin        INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                PRIMARY KEY (uin, message_id)
            );
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
            CREATE TABLE IF NOT EXISTS inbox_reads (
                peer_id  INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                mark     INTEGER NOT NULL,
                by_id    INTEGER NOT NULL,
                PRIMARY KEY (peer_id, topic_id)
            );
            CREATE TABLE IF NOT EXISTS quote_sources (
                uin INTEGER NOT NULL,
                ref INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                PRIMARY KEY (uin, ref),
                UNIQUE (uin, message_id)
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
        if "muted" not in columns and "topic_id" in columns:
            self.conn.execute(
                "ALTER TABLE contacts ADD COLUMN muted INTEGER NOT NULL DEFAULT 0")
        if "hidden" not in columns and "topic_id" in columns:
            self.conn.execute(
                "ALTER TABLE contacts ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
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
                    hidden     INTEGER NOT NULL DEFAULT 0,
                    muted      INTEGER NOT NULL DEFAULT 0,
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
        if "mention" not in pending_columns:
            # Упоминание обходит мьют, но по-прежнему зависит от статуса
            # и избранного — поэтому оно не равнозначно forced.
            self.conn.execute(
                "ALTER TABLE pending ADD COLUMN mention INTEGER NOT NULL DEFAULT 0")
        if "url" not in pending_columns:
            # Ссылка, ради которой сообщение отправляется URL-сообщением ICQ:
            # клиент показывает её отдельной строкой и даёт открыть браузером.
            self.conn.execute(
                "ALTER TABLE pending ADD COLUMN url TEXT NOT NULL DEFAULT ''")
        if "attach" not in pending_columns:
            # Вложение сообщения для расширенного клиента: «photo:<номер
            # сообщения>» — по нему мост потом достаёт сам снимок.
            self.conn.execute(
                "ALTER TABLE pending ADD COLUMN attach TEXT NOT NULL DEFAULT ''")

        for table in ("pending", "held"):
            columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if "message_id" not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN message_id TEXT NOT NULL DEFAULT ''")
            if "source_ts" not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN source_ts INTEGER NOT NULL DEFAULT 0")
        self.conn.execute("CREATE INDEX IF NOT EXISTS held_uin ON held(uin)")
        held_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(held)")}
        if "attach" not in held_columns:
            self.conn.execute("ALTER TABLE held ADD COLUMN attach TEXT NOT NULL DEFAULT ''")

    # --- контакты -------------------------------------------------------

    def uin_for_peer(self, peer_id: int, *, kind: str, title: str,
                     group_name: str, position: int = 0, favourite: int = 0,
                     topic_id: int = 0, muted: int = 0) -> int:
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
                " favourite=?, muted=? WHERE uin=?",
                (kind, title, group_name, position, favourite, muted, uin),
            )
            return uin
        row = self.conn.execute("SELECT MAX(uin) AS m FROM contacts").fetchone()
        uin = max(row["m"] or 0, UIN_BASE) + 1
        self.conn.execute(
            "INSERT INTO contacts (uin, peer_id, topic_id, kind, title, group_name,"
            " position, favourite, muted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uin, peer_id, topic_id, kind, title, group_name, position, favourite, muted),
        )
        return uin

    def contacts(self, limit: int = 0, background: tuple[str, ...] = (),
                 recent_since: int = 0) -> list[Contact]:
        """Контакт-лист: то, что сейчас есть в Telegram.

        limit оставляет только самые свежие чаты: старые телефоны не тянут
        сотни контактов. Избранные остаются в списке при любом ограничении.

        background — фоновые группы (папки, в нижнем регистре): их чаты
        претендуют на место последними, когда остальные уже размещены. Чат
        из такой группы, писавший телефону после recent_since, идёт наравне
        со всеми: раз пишет — пусть будет под рукой.
        """
        rows = self.conn.execute(
            "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts, gone, hidden, muted, COALESCE(fav_manual, favourite) AS favourite FROM contacts WHERE gone = 0 AND hidden = 0 ORDER BY position, uin"
        ).fetchall()
        contacts = [Contact(**dict(r)) for r in rows]
        return limit_contacts(contacts, limit, background, recent_since)

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

    def set_hidden(self, uin: int, hidden: bool = True) -> None:
        """Убирает контакт с телефона или возвращает обратно.

        Признак ручной, поэтому обновление списка диалогов его не трогает:
        иначе скрытая тема возвращалась бы через десять минут.
        """
        self.conn.execute("UPDATE contacts SET hidden = ? WHERE uin = ?",
                          (int(hidden), uin))

    def raise_contact(self, uin: int) -> None:
        """Поднимает чат в начало списка — чтобы он влез в roster_limit.

        Нужно, когда чат возвращают на телефон вручную: сам по себе он
        стоит там, куда его поставила свежесть переписки, а она у забытого
        чата как раз никакая."""
        row = self.conn.execute(
            "SELECT MIN(position) FROM contacts WHERE gone = 0").fetchone()
        top = (row[0] if row and row[0] is not None else 0) - 1
        self.conn.execute("UPDATE contacts SET position = ? WHERE uin = ?", (top, uin))

    def contacts_all(self) -> list[Contact]:
        """Все живые чаты, включая убранные с телефона."""
        rows = self.conn.execute(
            "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts,"
            " gone, hidden, muted, COALESCE(fav_manual, favourite) AS favourite"
            " FROM contacts WHERE gone = 0 ORDER BY position, uin"
        ).fetchall()
        return [Contact(**dict(r)) for r in rows]

    def set_muted(self, uin: int, muted: bool) -> None:
        """Запоминает, что чат заглушён в Telegram."""
        self.conn.execute("UPDATE contacts SET muted = ? WHERE uin = ?",
                          (int(muted), uin))

    def mark_gone(self, uin: int) -> None:
        """Убирает контакт из списка, сохраняя за чатом его UIN."""
        self.conn.execute("UPDATE contacts SET gone = 1 WHERE uin = ?", (uin,))

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
            f"SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts, gone, hidden, muted, COALESCE(fav_manual, favourite) AS favourite FROM contacts WHERE gone = 0 AND peer_id NOT IN ({marks})",
            present,
        ).fetchall()
        if rows:
            self.conn.executemany(
                "UPDATE contacts SET gone = 1 WHERE uin = ?",
                [(r["uin"],) for r in rows],
            )
        return [Contact(**dict(r)) for r in rows]

    def mark_forum_shells(self, forums: "set[int] | list[int]") -> list[Contact]:
        """Убирает у форумов контакт «без темы»: форум показан темами, и его
        сообщения теперь расходятся по ним. UIN и здесь остаётся за записью."""
        rows = []
        for peer_id in forums:
            rows += self.conn.execute(
                "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts,"
                " gone, hidden, muted, COALESCE(fav_manual, favourite) AS favourite"
                " FROM contacts WHERE gone = 0 AND peer_id = ? AND topic_id = 0",
                (peer_id,),
            ).fetchall()
        if rows:
            self.conn.executemany("UPDATE contacts SET gone = 1 WHERE uin = ?",
                                  [(r["uin"],) for r in rows])
        return [Contact(**dict(r)) for r in rows]

    def contact_by_uin(self, uin: int) -> Contact | None:
        row = self.conn.execute(
            "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts, gone, hidden, muted, COALESCE(fav_manual, favourite) AS favourite FROM contacts WHERE uin = ?", (uin,)).fetchone()
        return Contact(**dict(row)) if row else None

    def contact_by_peer(self, peer_id: int, topic_id: int = 0) -> Contact | None:
        row = self.conn.execute(
            "SELECT uin, peer_id, topic_id, kind, title, group_name, position, last_ts,"
            " gone, hidden, muted, COALESCE(fav_manual, favourite) AS favourite"
            " FROM contacts WHERE peer_id = ? AND topic_id = ?",
            (peer_id, topic_id),
        ).fetchone()
        return Contact(**dict(row)) if row else None

    def uins_for_peer(self, peer_id: int) -> list[int]:
        """Основной чат и его темы: прочтение относится к их общему peer."""
        return [int(row[0]) for row in self.conn.execute(
            "SELECT uin FROM contacts WHERE peer_id = ?", (peer_id,))]

    # --- очередь офлайна ------------------------------------------------

    @contextmanager
    def _message_transaction(self):
        """Очередь, ID сообщения и отметка времени фиксируются вместе."""
        self.conn.execute("SAVEPOINT incoming_message")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK TO incoming_message")
            raise
        finally:
            self.conn.execute("RELEASE incoming_message")

    def quote_reference(self, uin: int, message_id: int | str) -> int:
        """Keep UUIDs reversible across restarts without changing the phone's 8 bytes."""
        try:
            value = int(message_id)
            return value if 0 < value < 2**64 else 0
        except (TypeError, ValueError):
            pass
        try:
            source = str(uuid.UUID(str(message_id)))
        except (ValueError, AttributeError):
            return 0
        row = self.conn.execute("SELECT ref FROM quote_sources WHERE uin=? AND message_id=?",
                                (uin, source)).fetchone()
        if row:
            return row["ref"]
        # Never recycle an expired reference: an old phone selection must
        # fail rather than silently point at a newer message with the same
        # leading UUID bits. The sequence also survives a bridge restart.
        value = int(self.get_meta("quote_ref_sequence", "0")) + 1
        while self.conn.execute("SELECT 1 FROM quote_sources WHERE uin=? AND ref=?", (uin, value)).fetchone():
            value += 1
        if value >= 2**63:
            return 0
        self.set_meta("quote_ref_sequence", str(value))
        self.conn.execute("INSERT INTO quote_sources (uin, ref, message_id) VALUES (?, ?, ?)",
                          (uin, value, source))
        self.conn.execute("DELETE FROM quote_sources WHERE uin=? AND rowid NOT IN "
                          "(SELECT rowid FROM quote_sources WHERE uin=? ORDER BY rowid DESC LIMIT ?)",
                          (uin, uin, PROCESSED_PER_CHAT))
        return value

    def quote_source(self, uin: int, reference: int) -> str | None:
        row = self.conn.execute("SELECT message_id FROM quote_sources WHERE uin=? AND ref=?",
                                (uin, reference)).fetchone()
        return row["message_id"] if row else None

    def message_processed(self, uin: int, message_id: int | str) -> bool:
        return bool(message_id) and self.conn.execute(
            "SELECT 1 FROM processed_messages WHERE uin = ? AND message_id = ?",
            (uin, str(message_id)),
        ).fetchone() is not None

    def _remember_message(self, uin: int, message_id: int | str) -> bool:
        if not message_id:
            return True
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO processed_messages (uin, message_id) VALUES (?, ?)",
            (uin, str(message_id)),
        )
        if not cur.rowcount:
            return False
        self.conn.execute(
            "DELETE FROM processed_messages WHERE uin = ? AND rowid NOT IN ("
            " SELECT rowid FROM processed_messages WHERE uin = ? ORDER BY rowid DESC LIMIT ?)",
            (uin, uin, PROCESSED_PER_CHAT),
        )
        return True

    def queue(self, uin: int, text: str, limit_per_chat: int, forced: bool = False,
              url: str = "", ts: int = 0, attach: str = "", mention: bool = False,
              message_id: int | str = 0, source_message_id: int | str | None = None,
              source_ts: int = 0) -> bool:
        """forced — ответ на команду или звонок: доставляем при любом статусе.

        mention — обращение ко мне: обходит мьют, сохраняя ограничения
        текущего статуса и избранного при отправке очереди.

        url — ссылка, которую стоит отдать URL-сообщением, а не простым текстом.
        ts — когда сообщение было написано на самом деле: по нему ставится
        метка времени и время в офлайн-пачке. Без него — сейчас.
        message_id — ID в исходной сети; False означает повтор или уже прочитанное.
        source_ts — точное время исходного сообщения в миллисекундах для MAX/eXpress.
        """
        ts = int(ts or time.time())
        source_id = str((message_id if source_message_id is None else source_message_id) or "")
        with self._message_transaction():
            if not self._remember_message(uin, message_id):
                return False
            if message_id:
                self.conn.execute(
                    "UPDATE contacts SET last_ts = MAX(last_ts, ?) WHERE uin = ?", (ts, uin))
            if not forced and self._inbox_read(uin, source_id, ts, source_ts):
                return False
            self.conn.execute(
                "INSERT INTO pending (uin, text, ts, forced, url, attach, mention, message_id, source_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uin, text, ts, int(forced), url, attach, int(mention), source_id, source_ts),
            )
            self.conn.execute(
                "DELETE FROM pending WHERE uin = ? AND id NOT IN ("
                "  SELECT id FROM pending WHERE uin = ? ORDER BY id DESC LIMIT ?)",
                (uin, uin, limit_per_chat),
            )
        return True

    def _inbox_read(self, uin: int, message_id: str, ts: int, source_ts: int) -> bool:
        """An offline read may precede a slow incoming event or catch-up result."""
        if not message_id:
            return False
        rows = self.conn.execute(
            "SELECT r.mark, r.by_id FROM inbox_reads r JOIN contacts c ON c.peer_id=r.peer_id "
            "WHERE c.uin=? AND (r.topic_id=-1 OR r.topic_id=c.topic_id)", (uin,))
        for row in rows:
            if row["by_id"]:
                if message_id.isascii() and message_id.isdecimal() and 0 < int(message_id) <= row["mark"]:
                    return True
            elif (source_ts or ts * 1000 + 999) <= row["mark"]:
                return True
        return False

    def drop_read_inbox(self, peer_id: int, mark: int, *, by_id: bool,
                        topic_id: int | None = None) -> tuple[int, int]:
        """Drop read source messages, retaining newer entries and forced replies.

        None means the whole peer; a topic marker applies only to that topic.
        Persist the marker so delayed events and restart catch-up cannot requeue
        the removed messages. Legacy timestamps have only second precision:
        the boundary second is retained unless its end is known to be read.
        """
        if mark <= 0:
            return 0, 0
        topic = -1 if topic_id is None else topic_id
        with self._message_transaction():
            self.conn.execute(
                "INSERT INTO inbox_reads (peer_id, topic_id, mark, by_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(peer_id, topic_id) DO UPDATE SET mark=MAX(mark, excluded.mark)",
                (peer_id, topic, mark, int(by_id)))
            mark = self.conn.execute(
                "SELECT mark FROM inbox_reads WHERE peer_id=? AND topic_id=?", (peer_id, topic)).fetchone()[0]
            recipients = "SELECT uin FROM contacts WHERE peer_id=?"
            args = [peer_id]
            if topic_id is not None:
                recipients += " AND topic_id=?"
                args.append(topic_id)
            if by_id:
                predicate = ("message_id<>'' AND message_id NOT GLOB '*[^0-9]*' "
                             "AND CAST(message_id AS INTEGER)>0 AND CAST(message_id AS INTEGER)<=?")
            else:
                predicate = ("message_id<>'' AND CASE WHEN source_ts>0 THEN source_ts "
                             "ELSE ts*1000+999 END<=?")
            removed = []
            for table in ("pending", "held"):
                guard = " AND forced=0" if table == "pending" else ""
                cur = self.conn.execute(
                    f"DELETE FROM {table} WHERE uin IN ({recipients}){guard} AND {predicate}",
                    (*args, mark))
                removed.append(cur.rowcount)
        return tuple(removed)

    def peek_pending(self) -> list[tuple[int, int, str, int, bool, str, str, bool]]:
        """Записи, ожидающие отправки. Уже отправленные, но ещё не
        подтверждённые, пропускаем — чтобы не слать их повторно."""
        rows = self.conn.execute(
            "SELECT id, uin, text, ts, forced, url, attach, mention FROM pending WHERE sent_at = 0 "
            "ORDER BY id"
        ).fetchall()
        return [(r["id"], r["uin"], r["text"], r["ts"], bool(r["forced"]), r["url"],
                 r["attach"], bool(r["mention"])) for r in rows]

    def pending_message_id(self, row_id: int) -> str:
        return self.pending_source(row_id)[0]

    def pending_source(self, row_id: int) -> tuple[str, int]:
        row = self.conn.execute("SELECT message_id, source_ts FROM pending WHERE id = ?", (row_id,)).fetchone()
        return (row["message_id"], row["source_ts"]) if row else ("", 0)

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

    def hold(self, uin: int, text: str, ts: int, limit_per_chat: int,
             message_id: int | str = 0, attach: str = "", source_ts: int = 0) -> None:
        source_id = str(message_id or "")
        if self._inbox_read(uin, source_id, ts, source_ts):
            return
        self.conn.execute("INSERT INTO held (uin, text, ts, message_id, attach, source_ts) VALUES (?, ?, ?, ?, ?, ?)",
                          (uin, text, ts, source_id, attach, source_ts))
        self.conn.execute(
            "DELETE FROM held WHERE uin = ? AND id NOT IN ("
            "  SELECT id FROM held WHERE uin = ? ORDER BY id DESC LIMIT ?)",
            (uin, uin, limit_per_chat),
        )

    def take_held(self, with_source: bool = False) -> list[tuple]:
        """Забирает придержанное целиком: что доставить, решает мост."""
        rows = self.conn.execute("SELECT uin, text, ts, message_id, attach, source_ts FROM held ORDER BY id").fetchall()
        if rows:
            self.conn.execute("DELETE FROM held")
        return [(r["uin"], r["text"], r["ts"], r["message_id"], r["attach"], r["source_ts"]) if with_source
                else (r["uin"], r["text"], r["ts"]) for r in rows]

    def held_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM held").fetchone()["c"]

    def note_delivered(self, peer_id: int, ts: int, topic_id: int = 0,
                       message_id: int | str = 0) -> None:
        """Запоминает время и ID обработанного сообщения, включая отсеянное."""
        with self._message_transaction():
            if message_id:
                contact = self.contact_by_peer(peer_id, topic_id)
                if contact is not None:
                    self._remember_message(contact.uin, message_id)
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

    def next_seq(self, name: str) -> int:
        """Сквозной счётчик с таким именем: 1, 2, 3… — переживает перезапуск."""
        key = f"seq_{name}"
        value = int(self.get_meta(key, "0") or 0) + 1
        self.set_meta(key, str(value))
        return value

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        return row["v"] if row else default

    def close(self) -> None:
        self.conn.close()
