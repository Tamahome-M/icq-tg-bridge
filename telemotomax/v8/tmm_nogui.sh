#!/bin/sh
# TeleMotoMax: доверие Java на Motorola V8 (MOTOMAGX, SAedition) к тестовому
# корню из telemotomax/sign-keys/ca.der — см. telemotomax/README.md,
# «Своя подпись». Положить в /home/.autorun/ (штатный автозапуск SAedition,
# имя *_nogui.*): /usr/setup — read-only squashfs, и подмена
# _devdomain.txt через mount -o bind делается заново при каждой загрузке.
# Первый раз — ещё стереть кеш, чтобы он пересобрался с новым доменом:
#   rm -f /ezxlocal/download/java/.policy/._policy.txt \
#         /ezxlocal/download/java/.policy/._hmac.txt \
#         /ezxlocal/download/java/.policy/._perhmac.dat
LOG=/ezxlocal/tmm/autorun.log
{
echo "== TMM autorun $(date)"
mkdir -p /ezxlocal/tmm
if ! grep -q TeleMotoMax /usr/setup/.policy/_devdomain.txt 2>/dev/null; then
	cp /usr/setup/.policy/_devdomain.txt /ezxlocal/tmm/_devdomain3.txt
	cat >> /ezxlocal/tmm/_devdomain3.txt <<EOF2
domain: TeleMotoMax
type: 0
rootcert: MIIDCjCCAfKgAwIBAgIUY72oJ5/rNCaO92QTGoX/qzQXouYwDQYJKoZIhvcNAQEFBQAwNjEcMBoGA1UEAwwTVGVsZU1vdG9NYXggUm9vdCBDQTEWMBQGA1UECgwNaWNxLXRnLWJyaWRnZTAeFw0yNjA5MjExMzI5NDJaFw0zNzEyMzEyMzU5NTlaMDYxHDAaBgNVBAMME1RlbGVNb3RvTWF4IFJvb3QgQ0ExFjAUBgNVBAoMDWljcS10Zy1icmlkZ2UwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDUvF7eAWVPhHkwcuHlElr7VU1dZ2OKyLxxGIcq3dlsbDm0y8BePxj+n4FAHFtaHV3scVqg8wJ8WoLnMpPs//ILVqUeexmrlUP9mPVXuRcR+lrSCpFFNgrCyclxAOSIfrSW5BVODQDVDfo+EkdvuK9UXOyNYgRTSVo8fTQq0RkLtjpr2oFh6D7H6SWrqwDXLSEnpVdgWZNqpCOtEGS7LBgobNeD11Y7WI4PaAUzXlZADK3xlRuBF7h0kR+prluFAgMY6BBEtEBNcsGqzxl2qG6oNrbV+UJhia8mcENcyllmAAjFfeoRKP9kRA0hTwwFPoXyiZ3gZ902AwmIKqlsEYmNAgMBAAGjEDAOMAwGA1UdEwQFMAMBAf8wDQYJKoZIhvcNAQEFBQADggEBACVR7ztDDfzM/OD/cDVk4Z5lnZb6emn0jT4K80ylDkc7FpmvKvaQJYVqG4CU2FXCYWbF7OI0iUcgeLAFSetExAdFsTFz/F+tr2tZtRpFtIzlTcRiA8GfG5B1ThDPwnBXAOPRWk4ufSCr6CzS0XdCCff9seHz1BiOfO6wWzYCABuH7NOlVf5WoHFgOcRozjbXVlaYRrZwEGAJloV8cSy8kTa7bbYTUmpgeRr/aWWmc4LlFZMmOQydWgd3917rgKZwis8d0xWwXZHDbFLi5oQMoIij+HdU9b8xh0tQy8+1IQmbo8t74YwEl/nrWXPvZib5NfKh9fboc/YMYIAq2E4HwwI=
allowchangestatus: 0
 
EOF2
fi
mount -o bind /ezxlocal/tmm/_devdomain3.txt /usr/setup/.policy/_devdomain.txt
echo "mount rc=$?"
grep -c TeleMotoMax /usr/setup/.policy/_devdomain.txt
} > $LOG 2>&1
