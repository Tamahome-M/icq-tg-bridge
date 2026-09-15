#!/bin/sh
# Обновление установленного моста архивом с GitHub.
#
# Ничего лишнего не требует: скачивание и распаковка идут через Python,
# который в системе уже есть. Настройки, сессия, база, снимки и окружение
# остаются на месте.
#
#   ./update-from-github.sh                     # ветка main, /opt/icq-tg-bridge
#   ./update-from-github.sh -d /path -b dev     # другой каталог или ветка
#   ./update-from-github.sh -n                  # показать, что изменится

set -eu

# Весь скрипт — в одном блоке: shell разбирает его целиком до запуска и
# потом не читает файл с диска. Иначе, обновив сам себя на середине, он
# продолжает читать новую версию со старого смещения — и падает на мусоре.
{

DIR=/opt/icq-tg-bridge
REPO=https://github.com/Tamahome-M/icq-tg-bridge
BRANCH=main
OWNER=icqbridge
SERVICE=icq-tg-bridge
DRY=""

while getopts "d:b:r:u:s:nh" opt; do
    case "$opt" in
        d) DIR="$OPTARG" ;;
        b) BRANCH="$OPTARG" ;;
        r) REPO="$OPTARG" ;;
        u) OWNER="$OPTARG" ;;
        s) SERVICE="$OPTARG" ;;
        n) DRY=1 ;;
        h) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "неизвестный ключ: -$opt" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1;32m==\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

[ -d "$DIR" ] || die "каталог $DIR не найден — укажите свой ключом -d"
[ -f "$DIR/run.py" ] || die "в $DIR не видно run.py: это точно каталог моста?"

PYTHON="$DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=$(command -v python3) || die "не нашёл python3"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

say "Скачиваю $REPO ($BRANCH)"
"$PYTHON" - "$REPO/archive/refs/heads/$BRANCH.zip" "$WORK/src.zip" <<'PY'
import sys, urllib.request
url, dest = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
    f.write(r.read())
PY

say "Распаковываю"
"$PYTHON" - "$WORK/src.zip" "$WORK/unpacked" <<'PY'
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    z.extractall(sys.argv[2])
    # zipfile права не восстанавливает — возвращаем бит исполнения тем
    # файлам, у которых он был (иначе этот самый скрипт после обновления
    # перестаёт запускаться).
    for info in z.infolist():
        mode = (info.external_attr >> 16) & 0o777
        if mode & 0o111 and not info.is_dir():
            os.chmod(os.path.join(sys.argv[2], info.filename), mode)
PY

NEW=$(find "$WORK/unpacked" -mindepth 1 -maxdepth 1 -type d | head -1)
[ -n "$NEW" ] || die "в архиве не нашлось каталога с исходниками"
[ -f "$NEW/run.py" ] || die "в архиве нет run.py — похоже, скачалось не то"

# Общие правила для показа и для обновления — один текст, чтобы -n не врал.
RULES=$(cat <<'PY'
import pathlib

# Куда не заглядываем вовсе: рабочие данные и всё, что начинается с точки —
# каталог установки служит пользователю моста домом (.venv, .claude, …).
SKIP_PARTS = {"photos", "render", "downloads", "claude", "__pycache__"}
KEEP_NAMES = {"config.toml"}

def skip(rel: pathlib.Path) -> bool:
    name = rel.name
    return (rel.parts[0].startswith(".")
            or bool(SKIP_PARTS & set(rel.parts))
            or name in KEEP_NAMES
            or ".session" in name          # tg.session, max.session и их журналы
            or name.startswith("bridge.db")  # база, WAL и копии
            or name.endswith(".log"))

def stale(cur: pathlib.Path, new: pathlib.Path, wanted: set) -> list:
    """Файлы, которых в новой версии нет, — только внутри каталогов, которые
    есть в самом архиве (bridge/, tests/, tools/, …). Корень установки и чужие
    каталоги не чистим никогда: там лежат сессии, база и то, о чём скрипт не
    знает."""
    owned = {p.relative_to(new).parts[0] for p in new.iterdir() if p.is_dir()}
    out = []
    for dst in sorted(cur.rglob("*"), reverse=True):
        rel = dst.relative_to(cur)
        if len(rel.parts) < 2 or rel.parts[0] not in owned:
            continue
        if skip(rel) or rel in wanted:
            continue
        out.append(dst)
    return out

def planned(new: pathlib.Path):
    """Что копируем: (относительный путь, это каталог)."""
    for src in sorted(new.rglob("*")):
        rel = src.relative_to(new)
        if skip(rel):
            continue
        yield rel, src.is_dir()
PY
)

if [ -n "$DRY" ]; then
    say "Что изменится (ничего не трогаю)"
    "$PYTHON" - "$NEW" "$DIR" "$RULES" <<'PY'
import filecmp, pathlib, sys
new, cur = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
exec(sys.argv[3])
changed = added = 0
wanted = set()
for rel, is_dir in planned(new):
    wanted.add(rel)
    if is_dir:
        continue
    dst = cur / rel
    if not dst.exists():
        print("  новый    ", rel); added += 1
    elif not filecmp.cmp(new / rel, dst, shallow=False):
        print("  изменён  ", rel); changed += 1
gone = [p for p in stale(cur, new, wanted) if p.is_file()]
for p in gone:
    print("  удалится ", p.relative_to(cur))
print(f"итого: изменится {changed}, добавится {added}, удалится {len(gone)}")
PY
    exit 0
fi

# служба может не работать — это не повод падать
if command -v rc-service >/dev/null 2>&1; then
    say "Останавливаю службу"; rc-service "$SERVICE" stop || true
    START="rc-service $SERVICE start"
elif command -v systemctl >/dev/null 2>&1; then
    say "Останавливаю службу"; systemctl stop "$SERVICE" || true
    START="systemctl start $SERVICE"
else
    say "Менеджер служб не найден — остановите и запустите мост вручную"
    START=""
fi

if [ -f "$DIR/bridge.db" ]; then
    BACKUP="$DIR/bridge.db.backup-$(date +%Y%m%d-%H%M%S)"
    cp "$DIR/bridge.db" "$BACKUP"
    say "Копия базы: $BACKUP"
fi

say "Обновляю файлы"
"$PYTHON" - "$NEW" "$DIR" "$RULES" <<'PY'
import pathlib, shutil, sys
new, cur = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
exec(sys.argv[3])

wanted = set()
copied = 0
for rel, is_dir in planned(new):
    wanted.add(rel)
    dst = cur / rel
    if is_dir:
        dst.mkdir(parents=True, exist_ok=True)
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(new / rel, dst)
    copied += 1

# Убираем файлы, которых в новой версии больше нет, — по правилам stale().
removed = 0
for dst in stale(cur, new, wanted):
    if dst.is_file():
        dst.unlink(); removed += 1
    elif dst.is_dir() and not any(dst.iterdir()):
        dst.rmdir()

print(f"  обновлено файлов: {copied}, удалено устаревших: {removed}")
PY

say "Проверяю зависимости"
"$PYTHON" -m pip install -q -r "$DIR/requirements.txt" 2>/dev/null \
    || say "  pip недоступен или без сети — пропускаю"

if id "$OWNER" >/dev/null 2>&1; then
    say "Возвращаю владельца $OWNER"
    chown -R "$OWNER:$OWNER" "$DIR"
    [ -f "$DIR/config.toml" ] && chmod 600 "$DIR/config.toml"
    for f in "$DIR"/*.session; do [ -f "$f" ] && chmod 600 "$f"; done
fi
# На всякий случай — даже если архив пришёл без прав.
chmod 755 "$DIR"/tools/*.sh

if [ -n "$START" ]; then
    say "Запускаю службу"
    if $START; then
        sleep 2
        say "Последние записи журнала"
        tail -n 15 "/var/log/$SERVICE.log" 2>/dev/null || true
    else
        say "Служба не запустилась — файлы обновлены, смотрите журнал:"
        tail -n 20 "/var/log/$SERVICE.log" 2>/dev/null || true
        exit 1
    fi
fi

say "Готово"
exit 0

}
