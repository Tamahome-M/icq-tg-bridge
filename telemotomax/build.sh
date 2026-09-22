#!/bin/sh
# Сборка TeleMotoMax — клиента моста для Motorola V3 (форк Jimm 0.6).
#
# Исходники лежат рядом, в src/ и res/; модули FILES, SMILES_STD, AVATARS,
# язык русский. Ничего в систему не ставится: JDK 8, Ant, ProGuard 4.11 и
# заглушки CLDC/MIDP скачиваются в рабочий каталог. Нужны только curl и tar.
#
#   ./build.sh [рабочий каталог] [имя]   # результат: <каталог>/out/TeleMotoMax.jar, .jad
#
# Имя — это MIDlet-Name, по нему телефон различает программы; по умолчанию
# «TeleMotoMax», встанет рядом с Jimm со своими настройками.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${1:-$PWD/telemotomax-build}
NAME=${2:-TeleMotoMax}
VERSION=$(cat "$HERE/VERSION")
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


say "Настройки сборки"
rm -rf src && mkdir src && cp -r "$HERE/src" "$HERE/res" "$HERE/util" "$HERE/build.xml" "$HERE/COPYING" src/
# Версия одна на всё: номер из VERSION и дата сборки. Номер идёт в
# MIDlet-Version (телефон различает сборки по нему), «номер.дата» — в
# TeleMotoMax-Version и на экран «О программе», а старший и младший номера —
# в способность, которой клиент представляется мосту, чтобы в журнале моста
# была ровно та же версия, что стоит на телефоне.
STAMP="$VERSION.$(date +%y%m%d)"
MAJOR=${VERSION%%.*}
MINOR=${VERSION#*.}; MINOR=${MINOR%%.*}
# Набор модулей Jimm. FILES (передача файлов и прямые соединения между
# клиентами ICQ) вырезан из исходников целиком: с мостом он не нужен, а на
# KVM код лежит в той же куче, что и данные. Раньше без него пропадало
# «печатает» — разбор способностей контакта сидел в том же блоке; теперь
# он общий. У V3 нет и смайлов: ICQ-смайлы в переписке из Telegram/MAX —
# редкость, а набор картинок держал ~32 КБ кучи. CAMERA — снимок, кружок и
# файлы с карты (JSR-75): на V3 недоступно, сборка v8 включает.
MODULES=${TMM_MODULES:-v3}
case "$MODULES" in
	v3)    MODULES="AVATARS" ;;
	v8)    MODULES="SMILES_STD,AVATARS,CAMERA" ;;
esac
sed "s|###WTK###|$WORK/wtk|g; s|###PROGUARD###|$WORK/proguard|; s|###TMM-VERSION###|$STAMP|; \
     s|###TMM-VERSION-JAVA###|$VERSION|; s|###TMM-NAME###|$NAME|; \
     s|###TMM-MODULES###|$MODULES|" "$HERE/build.properties" > src/build.properties
sed -i "s|TMM_VERSION_MAJOR = .*;|TMM_VERSION_MAJOR = $MAJOR;|; \
        s|TMM_VERSION_MINOR = .*;|TMM_VERSION_MINOR = $MINOR;|" src/src/jimm/comm/Icq.java
# Сборка с камерой (V8) объявляет в JAD, какие закрытые API ей нужны.
# Файлы (JSR-75) — как обязательные (MIDlet-Permissions): с необязательными
# (-Opt) MotoMAGX всё равно отвечал SecurityException: Application not
# authorized, а обязательные он переводит в «спросить у владельца» — либо
# честно отказывается ставить, если домен их не даёт вовсе. Снимок и
# запись работали и так — их оставляем необязательными.
# Сеть — не Restricted API (в отличие от файлов), но для ДОВЕРЕННОГО
# (подписанного) приложения runtime разрешает только то, что явно
# перечислено здесь: без объявления сокет отвечал «не разрешено» даже в
# домене с полными правами — неподписанным сборкам это скрывал
# интерактивный запрос доступа у пользователя.
PERMS="javax.microedition.io.Connector.socket,javax.microedition.io.Connector.http,javax.microedition.io.Connector.https"
case "$MODULES" in *CAMERA*)
	PERMS="$PERMS,javax.microedition.io.Connector.file.read,javax.microedition.io.Connector.file.write,javax.microedition.media.control.VideoControl.getSnapshot,javax.microedition.media.control.RecordControl" ;;
esac
# Разрешения — необязательные (-Opt): обязательные файлы для неподписанной
# сборки дают молчаливый отказ в установке на MOTOMAGX, а подписанной
# телефон выдаёт и необязательные по политике её домена. Строка одна и в
# манифесте, и в JAD: у подписанного приложения они обязаны совпадать.
printf 'MIDlet-Permissions-Opt: %s\n' "$PERMS" >> src/res/MANIFEST.MF
say "Версия: $STAMP (способность TMM:$MAJOR.$MINOR, имя «$NAME», модули $MODULES)"
cd src

say "Сборка"
ant -q clean dist 2>&1 | grep -v '\[langs\]' || true
# clean стёр прошлый JAR — если его нет и сейчас, сборка не прошла; иначе в
# out/ и в dist/ уехал бы старый JAR под новым номером версии.
[ -f dist/bin/Jimm.jar ] || { printf '\033[1;31m==\033[0m Сборка не прошла — см. ошибки выше\n' >&2; exit 1; }
mkdir -p "$WORK/out" && cp dist/bin/Jimm.jar "$WORK/out/TeleMotoMax.jar" \
    && cp dist/bin/Jimm.jad "$WORK/out/TeleMotoMax.jad"

# Картинки, которые с мостом не нужны, а память телефона едят (см. README).
python3 - "$WORK/out/TeleMotoMax.jar" "$WORK/out/TeleMotoMax.jad" <<'PY'
import os, sys, zipfile
jar, jad = sys.argv[1], sys.argv[2]
strip = {"xstatus.png", "micons.png", "clicons.png", "logo.png"}
tmp = jar + ".tmp"
with zipfile.ZipFile(jar) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
    for item in src.infolist():
        if item.filename in strip:
            continue
        data = src.read(item.filename)
        if item.filename == "META-INF/MANIFEST.MF":
            # MIDlet-Jar-URL и MIDlet-Jar-Size — атрибуты JAD, в манифесте
            # им не место: у подписанного приложения атрибуты JAD обязаны
            # совпадать с манифестом, а эти два в JAD другие (имя V8-сборки,
            # настоящий размер) — установка отвергалась молча.
            lines, out = data.decode("utf-8").replace("\r", "").split("\n"), []
            skip = False
            for l in lines:
                if l.startswith(" ") and skip:
                    continue
                skip = l.startswith("MIDlet-Jar-URL:") or l.startswith("MIDlet-Jar-Size:")
                if not skip:
                    out.append(l)
            data = "\r\n".join(out).encode("utf-8")
        dst.writestr(item, data)
os.replace(tmp, jar)
size = os.path.getsize(jar)
lines = open(jad, encoding="utf-8").read().splitlines()
# JAD делается из манифеста, а манифест переносит длинные строки (72 байта,
# продолжение с пробела). В JAD переносов не бывает — склеиваем обратно.
joined = []
for l in lines:
    if l.startswith(" ") and joined:
        joined[-1] += l[1:]
    else:
        joined.append(l)
lines = [f"MIDlet-Jar-Size: {size}" if l.startswith("MIDlet-Jar-Size:") else l for l in joined]
open(jad, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
say "Готово: $WORK/out/TeleMotoMax.jar ($(wc -c < "$WORK/out/TeleMotoMax.jar") байт), TeleMotoMax.jad"

# TMM_DIST=1 — положить сборку в telemotomax/dist (в репозиторий): оттуда её
# раздаёт веб-сервер моста в разделе «Загрузки», и после обновления моста
# на VPS свежий клиент ставится на телефон по ссылке http://…/d/. Сборка
# v8 ложится как TeleMotoMax-V8.jar/.jad, v3 — как TeleMotoMax.jar/.jad.
if [ -n "${TMM_DIST:-}" ]; then
	DIST="$HERE/dist"; mkdir -p "$DIST"
	case "${TMM_MODULES:-v3}" in v8) BASE=TeleMotoMax-V8 ;; *) BASE=TeleMotoMax ;; esac
	cp "$WORK/out/TeleMotoMax.jar" "$DIST/$BASE.jar"
	sed "s|^MIDlet-Jar-URL: .*|MIDlet-Jar-URL: $BASE.jar|" "$WORK/out/TeleMotoMax.jad" > "$DIST/$BASE.jad"
	# Сборка V8 в репозитории — подписанная: на V8 файлы (JSR-75) даёт
	# только доверенное приложение, а телефон доверяет корню из
	# telemotomax/sign-keys (см. README, «Своя подпись»). V3 остаётся без
	# подписи — там этот корень не прописан, и подписанный JAD чужим
	# корнем P2K может и не принять. Ключи — тестовые, лежат рядом.
	if [ "$BASE" = TeleMotoMax-V8 ] && [ -f "$HERE/sign-keys/ca.key" ]; then
		sh "$HERE/sign.sh" "$DIST/$BASE.jad" | sed 's/^/   /'
	fi
	say "В репозиторий: telemotomax/dist/$BASE.jar"
fi

