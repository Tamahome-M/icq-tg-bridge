#!/bin/sh
# Подпись сборки TeleMotoMax своим ключом (MIDP 2.0, JSR-118).
#
# Зачем: на MOTOMAGX (V8) файлы (JSR-75) — Restricted API, доступ только у
# приложений, подписанных сертификатом, который телефон знает. Своя подпись
# работает, если свой корневой сертификат положить в хранилище JVM телефона
# (для этого нужен root по SSH/Telnet — есть в SAedition) — см. README.
#
#   telemotomax/sign.sh                  # подписать dist/TeleMotoMax-V8.jad
#   telemotomax/sign.sh path/to/App.jad  # любой JAD рядом с его JAR
#
# Ключи — в ~/.tmm-sign/ (создаются при первом запуске, в репозиторий не
# попадают): ca.key/ca.der — корневой (его на телефон), signer.key/signer.der
# — подписывающий (им подписан JAR). В JAD добавляются MIDlet-Certificate-1-1
# (подписывающий), MIDlet-Certificate-1-2 (корневой) и MIDlet-Jar-RSA-SHA1.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
JAD=${1:-$HERE/dist/TeleMotoMax-V8.jad}
KEYS=${TMM_KEYS:-$HOME/.tmm-sign}
JAR=$(dirname "$JAD")/$(sed -n 's/^MIDlet-Jar-URL: *//p' "$JAD" | tr -d '\r')
[ -f "$JAR" ] || { echo "нет JAR: $JAR" >&2; exit 1; }

mkdir -p "$KEYS" && chmod 700 "$KEYS"
if [ ! -f "$KEYS/ca.key" ]; then
	echo "== Создаю корневой сертификат в $KEYS (один раз)"
	openssl req -x509 -newkey rsa:2048 -nodes -sha1 -days 7300 \
		-subj "/CN=TeleMotoMax Root CA/O=icq-tg-bridge" \
		-keyout "$KEYS/ca.key" -out "$KEYS/ca.pem" >/dev/null 2>&1
	openssl x509 -in "$KEYS/ca.pem" -outform DER -out "$KEYS/ca.der"
fi
if [ ! -f "$KEYS/signer.key" ]; then
	echo "== Создаю подписывающий сертификат"
	openssl req -newkey rsa:2048 -nodes -sha1 -subj "/CN=TeleMotoMax/O=icq-tg-bridge" \
		-keyout "$KEYS/signer.key" -out "$KEYS/signer.csr" >/dev/null 2>&1
	openssl x509 -req -sha1 -days 7300 -in "$KEYS/signer.csr" \
		-CA "$KEYS/ca.pem" -CAkey "$KEYS/ca.key" -CAcreateserial \
		-out "$KEYS/signer.pem" >/dev/null 2>&1
	openssl x509 -in "$KEYS/signer.pem" -outform DER -out "$KEYS/signer.der"
fi

# Подпись JAR: RSA-SHA1 (PKCS#1 v1.5) по байтам JAR, base64 одной строкой.
SIG=$(openssl dgst -sha1 -sign "$KEYS/signer.key" "$JAR" | openssl base64 -A)
CERT1=$(openssl base64 -A < "$KEYS/signer.der")
CERT2=$(openssl base64 -A < "$KEYS/ca.der")

# Старые строки подписи убираем, новые дописываем; MIDlet-Permissions —
# обязательные для подписанного приложения (JSR-118, файлы + камера).
grep -v '^MIDlet-Certificate-\|^MIDlet-Jar-RSA-SHA1\|^MIDlet-Permissions' "$JAD" > "$JAD.tmp"
{
	cat "$JAD.tmp"
	echo "MIDlet-Permissions: javax.microedition.io.Connector.file.read,javax.microedition.io.Connector.file.write,javax.microedition.io.Connector.socket,javax.microedition.io.Connector.http"
	echo "MIDlet-Permissions-Opt: javax.microedition.media.control.VideoControl.getSnapshot,javax.microedition.media.control.RecordControl"
	echo "MIDlet-Certificate-1-1: $CERT1"
	echo "MIDlet-Certificate-1-2: $CERT2"
	echo "MIDlet-Jar-RSA-SHA1: $SIG"
} > "$JAD" && rm -f "$JAD.tmp"
echo "== Подписано: $JAD"
echo "   корневой сертификат для телефона: $KEYS/ca.der"
openssl x509 -in "$KEYS/ca.pem" -noout -fingerprint -sha1 | sed 's/^/   /'
