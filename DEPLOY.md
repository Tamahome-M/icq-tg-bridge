# Развёртывание на Gentoo Linux

Инструкция для отдельной виртуальной машины. Мост работает от собственного
непривилегированного пользователя и не требует root после установки.

## 1. Зависимости

```bash
emerge --ask dev-lang/python:3.12 dev-python/pip dev-python/virtualenv
```

Pillow ставится колесом из PyPI и системных заголовков не требует. Если
собирается из исходников (экзотическая архитектура), понадобятся:

```bash
emerge --ask media-libs/libjpeg-turbo sys-libs/zlib
```

Проверьте версию: нужен Python 3.11 или новее — мост читает настройки
модулем `tomllib` из стандартной библиотеки.

```bash
python3 --version
```

## 2. Пользователь и каталог

```bash
useradd --system --home-dir /opt/icq-tg-bridge --shell /sbin/nologin icqbridge
mkdir -p /opt/icq-tg-bridge
```

Разверните файлы проекта в `/opt/icq-tg-bridge` и передайте их пользователю:

```bash
chown -R icqbridge:icqbridge /opt/icq-tg-bridge
chmod 750 /opt/icq-tg-bridge
```

## 3. Окружение Python

```bash
cd /opt/icq-tg-bridge
sudo -u icqbridge python3 -m venv .venv
sudo -u icqbridge .venv/bin/python -m pip install -r requirements.txt
```

Если в venv не оказалось pip (Gentoo умеет собирать Python без `ensurepip`):

```bash
curl -sS https://bootstrap.pypa.io/get-pip.py | sudo -u icqbridge .venv/bin/python
```

## 4. Настройки

```bash
sudo -u icqbridge cp config.example.toml config.toml
sudo -u icqbridge chmod 600 config.toml
sudo -u icqbridge nano config.toml
```

Заполните обязательное:

| Параметр | Что вписать |
|---|---|
| `oscar.uin` | номер, который вводится в клиенте (5–6 цифр) |
| `oscar.password` | пароль для входа с телефона |
| `oscar.bos_host` | адрес сервера, видимый с телефона |
| `telegram.api_id`, `api_hash` | ключи с https://my.telegram.org |

Не оставляйте `api_id` от чужих клиентов: Telegram гасит сессии, созданные
с публично известными ключами.

## 5. Вход в Telegram

Шаг интерактивный — запрашивает номер телефона, код из приложения и, если
включён, облачный пароль:

```bash
cd /opt/icq-tg-bridge
sudo -u icqbridge .venv/bin/python run.py login
sudo -u icqbridge chmod 600 tg.session
```

Файл `tg.session` равнозначен полному доступу к аккаунту Telegram. Он должен
принадлежать `icqbridge` и иметь права `600`.

## 6. Автозапуск (OpenRC)

```bash
cp contrib/icq-tg-bridge.openrc /etc/init.d/icq-tg-bridge
cp contrib/icq-tg-bridge.confd  /etc/conf.d/icq-tg-bridge
chmod +x /etc/init.d/icq-tg-bridge
rc-update add icq-tg-bridge default
rc-service icq-tg-bridge start
rc-service icq-tg-bridge status
tail -f /var/log/icq-tg-bridge.log
```

Для профиля с systemd вместо этого:

```bash
cp contrib/icq-tg-bridge.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now icq-tg-bridge
journalctl -u icq-tg-bridge -f
```

## 7. Порты и межсетевой экран

Мосту нужны два входящих порта: `5190` для протокола ICQ и `8080` для
фотографий (второй нужен только при `photos.enabled = true`).

Если мост стоит прямо на машине с внешним адресом (nftables):

```
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        ct state established,related accept
        iif lo accept
        tcp dport { 5190, 8080 } accept
    }
}
```

Если мост живёт на виртуальной машине за маршрутизатором, порты пробрасываются
на неё (замените адреса на свои):

```bash
iptables -t nat -A PREROUTING -d 203.0.113.10/32 -p tcp -m tcp --dport 5190 \
         -j DNAT --to-destination 10.0.0.5:5190
iptables -I FORWARD -d 10.0.0.5/32 -p tcp -m tcp --dport 5190 -j ACCEPT
```

То же самое для 8080. Проверить, что порт доступен снаружи:

```bash
nc -vz 203.0.113.10 5190
```

Важно: отвечать наружу нужно через того же провайдера, через которого пришёл
запрос. При двух аплинках ответ уйдёт по маршруту по умолчанию, и провайдер,
которому этот адрес не принадлежит, отбросит пакет. Лечится метками соединений
и отдельной таблицей маршрутизации.

## 8. Проверка

```bash
cd /opt/icq-tg-bridge
sudo -u icqbridge .venv/bin/python tests/test_flow.py
```

Тесты поднимают сервер на локальном порту и проходят полный цикл без Telegram
и без телефона.

В ICQ-клиенте укажите адрес из `bos_host`, порт `5190`, номер и пароль из
`config.toml`. Проверялось на Jimm (Motorola V3), но подойти должен любой
клиент OSCAR, где можно задать свой адрес сервера.

## 9. Обновление

```bash
rc-service icq-tg-bridge stop
cd /opt/icq-tg-bridge
# заменить файлы проекта, сохранив config.toml, tg.session, bridge.db
sudo -u icqbridge .venv/bin/python -m pip install -r requirements.txt
rc-service icq-tg-bridge start
```

Схема базы обновляется сама при запуске: недостающие колонки добавляются,
данные сохраняются.

## 10. Резервная копия

Достаточно трёх файлов, и все три — секреты:

```
config.toml    пароль и ключи Telegram
tg.session     доступ к аккаунту Telegram
bridge.db      соответствие UIN и чатов, очередь сообщений
```

Храните копию так же строго, как сами файлы: `bridge.db` содержит соответствие
номеров и названий чатов, а `tg.session` — вход в аккаунт.
