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

Команда `!render` перекодирует видео и голосовые через ffmpeg — нужна сборка
с кодеками `h263` и `libopencore_amrnb`:

```bash
echo "media-video/ffmpeg amr" >> /etc/portage/package.use/ffmpeg
emerge --ask media-video/ffmpeg
```

Флаг `amr` тянет `opencore-amr` — в нём кодер AMR-NB, которым кодируется звук;
`amrenc` (широкополосный AMR-WB) не нужен. Кодер H.263 и контейнеры 3GP/AMR у
ffmpeg встроенные. После сборки проверьте, что оба кодера на месте:

```bash
ffmpeg -hide_banner -encoders | grep -E 'libopencore_amrnb|h263'
```

Без ffmpeg мост работает как обычно: на странице `!render` соберутся текст
и фотографии, а видео с голосовыми останутся пометками.

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

## 9. Обновление из git

Рабочие файлы — `config.toml`, `tg.session`, `bridge.db`, каталог `photos` и
`.venv` — в репозиторий не входят, поэтому обновление их не трогает.

### Первый раз: связать установленный каталог с репозиторием

Если мост разворачивали из архива или образа, каталог ещё не репозиторий:

```bash
rc-service icq-tg-bridge stop
cd /opt/icq-tg-bridge
git config --global --add safe.directory /opt/icq-tg-bridge   # каталог чужого владельца
git init -q
git remote add origin https://github.com/<вы>/icq-tg-bridge.git
git fetch origin
git reset --hard origin/main     # приводит код к состоянию репозитория
chown -R icqbridge:icqbridge /opt/icq-tg-bridge
rc-service icq-tg-bridge start
```

`git reset --hard` перезаписывает только то, что есть в репозитории; файлы с
настройками, сессией и базой он не видит и не трогает. Локальные правки кода,
если вы их делали, будут потеряны — сохраните их заранее (`git stash` тут не
поможет, репозиторий только что создан).

### Дальше: обычное обновление

```bash
cp /opt/icq-tg-bridge/bridge.db /root/bridge.db.backup   # на всякий случай
rc-service icq-tg-bridge stop
cd /opt/icq-tg-bridge
git pull --ff-only
.venv/bin/python -m pip install -q -r requirements.txt   # если менялись зависимости
chown -R icqbridge:icqbridge /opt/icq-tg-bridge
rc-service icq-tg-bridge start
tail -f /var/log/icq-tg-bridge.log
```

Схема базы обновляется сама при запуске: недостающие колонки добавляются,
данные сохраняются. Обратной миграции нет — поэтому копия перед обновлением.

### Проверить до запуска

```bash
cd /opt/icq-tg-bridge
for t in tests/test_*.py; do .venv/bin/python "$t" || echo "СБОЙ: $t"; done
```

Тестам не нужны ни Telegram, ни телефон, и рабочих файлов они не трогают.

### Откатиться

```bash
rc-service icq-tg-bridge stop
cd /opt/icq-tg-bridge
git log --oneline -5             # найти предыдущий коммит
git reset --hard <коммит>
cp /root/bridge.db.backup bridge.db   # только если база успела измениться
chown -R icqbridge:icqbridge /opt/icq-tg-bridge
rc-service icq-tg-bridge start
```

### Если правили код на месте

```bash
git status                # покажет изменённые файлы
git diff > /root/my.patch # сохранить свои правки
git checkout -- .         # вернуть исходное состояние
git pull --ff-only
```

## 9а. Обновление одной командой

Проще всего обновляться скриптом `tools/update-from-github.sh`: он сам качает
свежий архив ветки, обновляет код и перезапускает службу. Ни git, ни unzip на
машине не нужны — скачивание и распаковка идут через Python, который и так
стоит вместе с мостом.

```bash
/opt/icq-tg-bridge/tools/update-from-github.sh -n   # показать, что изменится
/opt/icq-tg-bridge/tools/update-from-github.sh      # обновить
```

По шагам скрипт делает следующее: снимает копию базы с меткой времени,
останавливает службу (понимает OpenRC и systemd), обновляет файлы, удаляет
те, которых в новой версии больше нет, доставляет зависимости, возвращает
владельца и права `600` на настройки с сессией, запускает службу и показывает
хвост журнала. Если служба не поднялась, он говорит об этом и выходит с
ошибкой — файлы при этом уже обновлены.

Не трогает вовсе, ни перезаписью, ни удалением: `config.toml`, `tg.session`,
`bridge.db` вместе с копиями, каталог `photos`, `.venv` и файлы журналов.

| Ключ | Зачем |
|---|---|
| `-n` | только показать изменения, ничего не делать |
| `-d` | другой каталог установки (по умолчанию `/opt/icq-tg-bridge`) |
| `-b` | другая ветка (по умолчанию `main`) |
| `-r` | другой репозиторий |
| `-u` | владелец файлов (по умолчанию `icqbridge`) |
| `-s` | имя службы (по умолчанию `icq-tg-bridge`) |

Скрипт приводит установку к состоянию ветки на GitHub. Если в неё ещё не
попали свежие изменения, обновление откатит машину назад — поэтому перед
запуском полезно посмотреть `-n`.

## 10. Резервная копия

Достаточно трёх файлов, и все три — секреты:

```
config.toml    пароль и ключи Telegram
tg.session     доступ к аккаунту Telegram
bridge.db      соответствие UIN и чатов, очередь сообщений
```

Храните копию так же строго, как сами файлы: `bridge.db` содержит соответствие
номеров и названий чатов, а `tg.session` — вход в аккаунт.
