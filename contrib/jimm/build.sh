#!/bin/sh
# Сборка Jimm 0.6 под Motorola с нужными мосту модулями.
#
# Штатная сборка «light» — вообще без модулей: в ней не разбираются
# способности контактов (нет «печатает» с телефона без прививки) и нет
# аватарок. «full» тянет лишнее: трафик, историю, прокси, антиспам,
# телефонную книгу. Здесь — середина: FILES (ради разбора способностей),
# SMILES_STD (картинки смайлов), AVATARS; язык только русский. Плюс патч
# chat-cap.patch: не больше 12 открытых чатов в памяти телефона.
#
# Ничего в систему не ставится: JDK 8, Ant, ProGuard и заглушки MIDP
# скачиваются в рабочий каталог. Нужны только curl и tar.
#
#   ./build.sh [рабочий каталог] [имя]   # результат: <каталог>/out/Jimm.jar, Jimm.jad
#
# Имя — это MIDlet-Name, по нему телефон различает установленные программы:
# «Jimm test» встанет рядом с обычным Jimm, со своими настройками и данными.

set -eu

WORK=${1:-$PWD/jimm-build}
NAME=${2:-Jimm}
HERE=$(cd "$(dirname "$0")" && pwd)
MAVEN=https://repo1.maven.org/maven2
mkdir -p "$WORK" && cd "$WORK"

say() { printf '\033[1;32m==\033[0m %s\n' "$*"; }

if [ ! -x jdk/bin/javac ]; then
    say "JDK 8 (Temurin)"
    URL=$(curl -sfL https://api.github.com/repos/adoptium/temurin8-binaries/releases/latest \
        | grep -o 'https://[^"]*OpenJDK8U-jdk_x64_linux_hotspot_[^"]*\.tar\.gz' | head -1)
    curl -sfL "$URL" -o jdk.tgz && mkdir -p jdk && tar xzf jdk.tgz -C jdk --strip-components=1
fi
if [ ! -x ant/bin/ant ]; then
    say "Ant"
    curl -sfL https://archive.apache.org/dist/ant/binaries/apache-ant-1.10.15-bin.tar.gz -o ant.tgz
    mkdir -p ant && tar xzf ant.tgz -C ant --strip-components=1
fi
export JAVA_HOME="$WORK/jdk" PATH="$WORK/jdk/bin:$WORK/ant/bin:$PATH"

if [ ! -f wtk/lib/jsr75.jar ]; then
    say "Заглушки CLDC/MIDP (microemu) — вместо Sun WTK"
    mkdir -p wtk/lib wtk/bin
    curl -sfL $MAVEN/org/microemu/cldcapi11/2.0.4/cldcapi11-2.0.4.jar -o wtk/lib/cldcapi11.jar
    curl -sfL $MAVEN/org/microemu/midpapi20/2.0.4/midpapi20-2.0.4.jar -o wtk/lib/midpapi20.jar
    curl -sfL $MAVEN/org/microemu/microemu-jsr-135/2.0.4/microemu-jsr-135-2.0.4.jar -o wtk/lib/mmapi.jar
    curl -sfL $MAVEN/org/microemu/microemu-jsr-75/2.0.4/microemu-jsr-75-2.0.4.jar -o wtk/lib/jsr75.jar
    # Преверификацию (StackMap для CLDC) делает ProGuard (microedition="true"),
    # а preverify из WTK сборке всё равно нужен — подставляем заглушку.
    cp "$HERE/preverify" wtk/bin/preverify && chmod +x wtk/bin/preverify
fi
if [ ! -f proguard/lib/proguard.jar ]; then
    # Именно 4.11: с ProGuard 6.2 сборка на Motorola V3 падала при запуске
    # («ошибка приложения») — KVM телефона не принимает его байткод или
    # преверификацию; с 4.11, версией той же эпохи, что и штатные сборки,
    # запускается. Проверено на телефоне 2026-09-15.
    say "ProGuard 4.11 (с задачей для Ant)"
    mkdir -p proguard/lib pg && cd pg
    curl -sfL $MAVEN/net/sf/proguard/proguard-base/4.11/proguard-base-4.11.jar -o base.jar
    curl -sfL $MAVEN/net/sf/proguard/proguard-anttask/4.11/proguard-anttask-4.11.jar -o ant.jar
    jar xf base.jar && jar xf ant.jar && rm -rf META-INF && jar cf ../proguard/lib/proguard.jar proguard
    cd .. && rm -rf pg
fi

if [ ! -d src/src ]; then
    say "Исходники Jimm (архив проекта на GitHub)"
    curl -sfL https://github.com/pavelkryukov/jimm/archive/refs/heads/master.tar.gz -o jimm.tgz
    mkdir -p src && tar xzf jimm.tgz -C src --strip-components=1
    say "Патч: не больше 12 открытых чатов в памяти"
    patch -p1 -d src < "$HERE/chat-cap.patch"
    say "Патч: вибрация «если скрыт» (крышка закрыта)"
    patch -p1 -d src < "$HERE/flip-vibra.patch"
    say "Патч: примета аватарки не теряется при уходе контакта в офлайн"
    patch -p1 -d src < "$HERE/avatar-offline.patch"
fi

say "Настройки сборки"
cd src
sed -i "s|^MIDP2/midp=.*|MIDP2/midp=$WORK/wtk|; s|^MOTOROLA/midp=.*|MOTOROLA/midp=$WORK/wtk|; \
        s|^proguard=.*|proguard=$WORK/proguard|; s|^target=.*|target=MOTOROLA|; \
        s|^modules=.*|modules=FILES,SMILES_STD,AVATARS|; s|^lang=.*|lang=RU|; \
        s|^version/jimm=.*|version/jimm=0.6.$(date +%y%m%d)-bridge|; s|^version/java=.*|version/java=1.0|; \
        s|^midlet/name=.*|midlet/name=$NAME|" build.properties
# Имя в меню телефона (MIDlet-1) в шаблоне манифеста прибито — пусть совпадает.
sed -i 's|^MIDlet-1: Jimm,|MIDlet-1: ###MIDLET-NAME###,|' res/MANIFEST.MF

say "Сборка"
ant -q clean dist 2>&1 | grep -v '\[langs\]' || true
mkdir -p "$WORK/out" && cp dist/bin/Jimm.jar dist/bin/Jimm.jad "$WORK/out/"

# Картинки, которые с мостом не нужны, а память телефона едят: каждая
# полоска 576x16 после распаковки — около 36 КБ в куче. Все загрузки
# обёрнуты в try/catch, а ImageList.elementAt без картинки отдаёт null,
# так что без них клиент работает, только без этих значков.
#   xstatus.png — X-статусы ICQ (сервер их не шлёт)
#   micons.png  — значки пунктов главного меню
#   clicons.png — значки клиентов собеседников (Miranda, QIP…)
#   logo.png    — логотип на заставке
# JIMM_KEEP_ICONS=1 оставляет всё как есть.
if [ -z "${JIMM_KEEP_ICONS:-}" ]; then
    say "Убираю ненужные с мостом картинки"
    python3 - "$WORK/out/Jimm.jar" "$WORK/out/Jimm.jad" <<'PY'
import os, sys, zipfile
jar, jad = sys.argv[1], sys.argv[2]
strip = {"xstatus.png", "micons.png", "clicons.png", "logo.png"}
tmp = jar + ".tmp"
with zipfile.ZipFile(jar) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
    for item in src.infolist():
        if item.filename in strip:
            continue
        dst.writestr(item, src.read(item.filename))
os.replace(tmp, jar)
size = os.path.getsize(jar)
lines = open(jad, encoding="utf-8").read().splitlines()
lines = [f"MIDlet-Jar-Size: {size}" if l.startswith("MIDlet-Jar-Size:") else l for l in lines]
open(jad, "w", encoding="utf-8").write("\n".join(lines) + "\n")
# Размер в манифесте внутри jar менять не надо: телефон смотрит в jad.
print(f"  jar теперь {size} байт")
PY
fi
say "Готово: $WORK/out/Jimm.jar ($(wc -c < "$WORK/out/Jimm.jar") байт), Jimm.jad"
