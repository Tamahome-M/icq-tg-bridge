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
if [ ! -f "$KEYS/ca.key" ] || [ ! -f "$KEYS/signer.key" ]; then
	echo "== Создаю корневой и подписывающий сертификаты в $KEYS (один раз)"
	# Сертификаты собираются вручную (не openssl req -x509): у современного
	# OpenSSL при самоподписи домен MOTOMAGX на телефоне (2006–2008 год)
	# отвергает JAD как «неверный сертификат» — по стандарту X.509 критичное
	# расширение, которого он не понимает, обязано провалить проверку, а
	# openssl 3.x у -x509 по умолчанию ставит BasicConstraints критичным и
	# сам добавляет SubjectKeyIdentifier/AuthorityKeyIdentifier, которых у
	# заводских сертификатов Motorola нет вовсе. Дата окончания действия
	# хранится как знаковое 32-битное число — дальше 19 января 2038 она
	# переполняется в отрицательное (сертификат выглядит просроченным ещё
	# до 1970 года, и уже установленное приложение отказывается запускаться
	# с «ошибкой аутентификации»); заводские сертификаты Motorola поэтому
	# кончаются 31.12.2037 — берём тот же срок.
	python3 - "$KEYS" <<'PYEOF'
import sys, datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

keys = sys.argv[1]

def der_len(n):
	if n < 0x80: return bytes([n])
	b = n.to_bytes((n.bit_length()+7)//8, 'big')
	return bytes([0x80 | len(b)]) + b
def tlv(tag, content): return bytes([tag]) + der_len(len(content)) + content
def seq(*items): return tlv(0x30, b"".join(items))
def der_set(*items): return tlv(0x31, b"".join(items))
def oid(dotted):
	parts = [int(x) for x in dotted.split(".")]
	body = bytes([parts[0]*40 + parts[1]])
	for p in parts[2:]:
		if p == 0: body += bytes([0]); continue
		chunk = []
		while p: chunk.insert(0, p & 0x7f); p >>= 7
		for i in range(len(chunk)-1): chunk[i] |= 0x80
		body += bytes(chunk)
	return tlv(0x06, body)
def integer(n):
	b = n.to_bytes((n.bit_length()+7)//8 + 1, 'big') if n else b"\x00"
	while len(b) > 1 and b[0] == 0 and b[1] < 0x80: b = b[1:]
	return tlv(0x02, b)
def utf8str(s): return tlv(0x0c, s.encode('utf-8'))
def utctime(dt): return tlv(0x17, dt.strftime("%y%m%d%H%M%SZ").encode('ascii'))
def bitstring(data, unused=0): return tlv(0x03, bytes([unused]) + data)
def explicit(tagnum, content): return tlv(0xa0 | tagnum, content)
def name_rdn(oid_dotted, value_der): return der_set(seq(oid(oid_dotted), value_der))

SHA1_RSA_OID = "1.2.840.113549.1.1.5"
CN_OID, O_OID = "2.5.4.3", "2.5.4.10"
alg_sha1rsa = seq(oid(SHA1_RSA_OID), tlv(0x05, b""))
not_before = datetime.datetime.now(datetime.timezone.utc)
not_after = datetime.datetime(2037, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
validity = seq(utctime(not_before), utctime(not_after))

def build_cert(subject_name, issuer_name, spki, extensions, sign_key, serial_bytes):
	tbs = seq(explicit(0, integer(2)), integer(int.from_bytes(serial_bytes, 'big')),
	          alg_sha1rsa, issuer_name, validity, subject_name, spki, extensions)
	sig = sign_key.sign(tbs, padding.PKCS1v15(), hashes.SHA1())
	return seq(tbs, alg_sha1rsa, bitstring(sig))

import os
ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ca_name = seq(name_rdn(CN_OID, utf8str("TeleMotoMax Root CA")), name_rdn(O_OID, utf8str("icq-tg-bridge")))
ca_spki = ca_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
ca_ext = explicit(3, seq(seq(oid("2.5.29.19"), tlv(0x04, seq(tlv(0x01, b"\xff"))))))
ca_der = build_cert(ca_name, ca_name, ca_spki, ca_ext, ca_key, os.urandom(20))

signer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
signer_name = seq(name_rdn(CN_OID, utf8str("TeleMotoMax")), name_rdn(O_OID, utf8str("icq-tg-bridge")))
signer_spki = signer_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
signer_der = build_cert(signer_name, ca_name, signer_spki, b"", ca_key, os.urandom(20))

for name, key, der in (("ca", ca_key, ca_der), ("signer", signer_key, signer_der)):
	with open(f"{keys}/{name}.key", "wb") as f:
		f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
	with open(f"{keys}/{name}.der", "wb") as f:
		f.write(der)
	cert = x509.load_der_x509_certificate(der)
	with open(f"{keys}/{name}.pem", "wb") as f:
		f.write(cert.public_bytes(serialization.Encoding.PEM))
print("сертификаты собраны")
PYEOF
	chmod 600 "$KEYS"/*.key
fi

# Подпись JAR: RSA-SHA1 (PKCS#1 v1.5) по байтам JAR, base64 одной строкой.
SIG=$(openssl dgst -sha1 -sign "$KEYS/signer.key" "$JAR" | openssl base64 -A)
CERT1=$(openssl base64 -A < "$KEYS/signer.der")
CERT2=$(openssl base64 -A < "$KEYS/ca.der")

# Старые строки подписи убираем, новые дописываем. Разрешения в JAD не
# трогаем: у подписанного приложения каждый атрибут JAD обязан совпадать с
# манифестом в JAR, иначе установка молча отвергается (JSR-118, 905).
grep -v '^MIDlet-Certificate-\|^MIDlet-Jar-RSA-SHA1' "$JAD" > "$JAD.tmp"
{
	cat "$JAD.tmp"
	echo "MIDlet-Certificate-1-1: $CERT1"
	echo "MIDlet-Certificate-1-2: $CERT2"
	echo "MIDlet-Jar-RSA-SHA1: $SIG"
} > "$JAD" && rm -f "$JAD.tmp"
echo "== Подписано: $JAD"
echo "   корневой сертификат для телефона: $KEYS/ca.der"
openssl x509 -in "$KEYS/ca.pem" -noout -fingerprint -sha1 | sed 's/^/   /'
