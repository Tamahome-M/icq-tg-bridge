"""Номера SNAC-семейств, подтипов и TLV, которые использует мост."""

# SNAC-семейства
OSERVICE = 0x0001   # служебное
LOCATE = 0x0002     # профили
BUDDY = 0x0003      # список онлайна
ICBM = 0x0004       # сообщения
INVITE = 0x0006
ADMIN = 0x0007
POPUP = 0x0008
PD = 0x0009         # приватность
USER_LOOKUP = 0x000A
STATS = 0x000B
SSBI = 0x0010       # аватарки на сервере (BART)
SSI = 0x0013        # контакт-лист на сервере
ICQ = 0x0015        # расширения ICQ
AUTH = 0x0017       # авторизация

# Версии семейств, которые сервер объявляет клиенту.
FAMILY_VERSIONS = {
    OSERVICE: 3,
    LOCATE: 1,
    BUDDY: 1,
    ICBM: 1,
    INVITE: 1,
    ADMIN: 1,
    POPUP: 1,
    PD: 1,
    USER_LOOKUP: 1,
    STATS: 1,
    SSBI: 1,
    SSI: 3,
    ICQ: 1,
}

# OSERVICE
SRV_READY = 0x0003
CLI_READY = 0x0002
RATE_REQ = 0x0006
RATE_RESP = 0x0007
RATE_ACK = 0x0008
SELF_INFO_REQ = 0x000E
SELF_INFO = 0x000F
CLI_VERSIONS = 0x0017
SRV_VERSIONS = 0x0018
SET_STATUS = 0x001E
SERVICE_REQUEST = 0x0004    # клиент просит адрес дополнительного сервиса
SERVICE_REDIRECT = 0x0005   # ответ: куда идти за этим сервисом
SRV_MOTD = 0x0013

# SSBI — аватарки. Клиент просит картинку по хешу, который сервер прислал
# в приметах контакта (TLV 0x001D блока сведений).
SSBI_ERROR = 0x0001
SSBI_ICQ_REQ = 0x0006       # клиент просит аватарку контакта
SSBI_ICQ_REPLY = 0x0007     # ответ с картинкой
BART_ICON = 0x0001          # тип приметы: хеш аватарки
BART_ICON_FLAGS = 0x01
BART_HASH_SIZE = 16

# TLV ответа 01/05
TLV_SERVICE_ID = 0x000D

# LOCATE
LOCATE_RIGHTS_REQ = 0x0002
LOCATE_RIGHTS = 0x0003
LOCATE_USER_INFO_REQ = 0x0015

# BUDDY
BUDDY_RIGHTS_REQ = 0x0002
BUDDY_RIGHTS = 0x0003
BUDDY_ARRIVED = 0x000B
BUDDY_DEPARTED = 0x000C

# ICBM
ICBM_PARAM_REQ = 0x0004
ICBM_PARAM_INFO = 0x0005
ICBM_SEND = 0x0006
ICBM_INCOMING = 0x0007
ICBM_CLIENT_ACK = 0x000B    # клиент подтвердил получение
ICBM_ACK = 0x000C
ICBM_CLIENT_EVENT = 0x0014

# PD
PD_RIGHTS_REQ = 0x0002
PD_RIGHTS = 0x0003

# SSI
SSI_RIGHTS_REQ = 0x0002
SSI_RIGHTS = 0x0003
SSI_LIST_REQ = 0x0004
SSI_LIST_REQ_IF_CHANGED = 0x0005
SSI_LIST = 0x0006
SSI_ACTIVATE = 0x0007
SSI_ADD = 0x0008
SSI_UPDATE = 0x0009
SSI_DELETE = 0x000A
SSI_EDIT_ACK = 0x000E
SSI_LIST_UNCHANGED = 0x000F
SSI_REMOVE_ME = 0x0016      # «удалиться из его контакт-листа»
SSI_EDIT_START = 0x0011
SSI_EDIT_END = 0x0012

# Типы элементов контакт-листа
SSI_TYPE_BUDDY = 0x0000
SSI_TYPE_GROUP = 0x0001
SSI_TYPE_PERMIT = 0x0002
SSI_TYPE_DENY = 0x0003
SSI_TYPE_PDINFO = 0x0004
SSI_TYPE_IGNORE = 0x000E       # список игнорируемых

# TLV внутри элементов контакт-листа
SSI_TLV_MEMBERS = 0x00C8       # список item_id внутри группы
SSI_TLV_ALIAS = 0x0131         # локальное имя контакта
SSI_TLV_AWAITING_AUTH = 0x0066

# AUTH (0x17)
AUTH_LOGIN_REQ = 0x0002
AUTH_LOGIN_REPLY = 0x0003
AUTH_MD5_KEY_REQ = 0x0006
AUTH_MD5_KEY_REPLY = 0x0007

# TLV авторизации
TLV_SCREENNAME = 0x0001
TLV_ROASTED_PASS = 0x0002
TLV_CLIENT_ID_STRING = 0x0003
TLV_ERROR_URL = 0x0004
TLV_BOS_ADDRESS = 0x0005
TLV_AUTH_COOKIE = 0x0006
TLV_ERROR_CODE = 0x0008
TLV_MD5_HASH = 0x0025

AUTH_ERR_BAD_PASSWORD = 0x0005

# TLV блока информации о пользователе
UI_TLV_CLASS = 0x0001
UI_TLV_SIGNON_TIME = 0x0003
UI_TLV_MEMBER_SINCE = 0x0005
UI_TLV_STATUS = 0x0006
UI_TLV_EXTERNAL_IP = 0x000A
UI_TLV_DC_INFO = 0x000C
UI_TLV_CAPABILITIES = 0x000D
UI_TLV_ONLINE_TIME = 0x000F
UI_TLV_BART = 0x001D        # приметы картинок: аватарка, x-статус

# Классы пользователя
CLASS_FREE = 0x0010
CLASS_ICQ = 0x0040

STATUS_ONLINE = 0x00000000
STATUS_AWAY = 0x00000001
STATUS_DND = 0x00000002
STATUS_NA = 0x00000004
STATUS_OCCUPIED = 0x00000010
STATUS_FREE_FOR_CHAT = 0x00000020
STATUS_OFFLINE = -1            # не код протокола: означает «слать 03/0C»

# Кодировки тела сообщения ICBM
CHARSET_ASCII = 0x0000
CHARSET_UNICODE = 0x0002   # UCS-2 big endian
CHARSET_LATIN1 = 0x0003

# Строка-соль в схеме авторизации по MD5
MD5_SALT = b"AOL Instant Messenger (SM)"

# Семейство 0x15 — расширения ICQ
ICQ_ERROR = 0x0001
ICQ_TO_SERVER = 0x0002
ICQ_FROM_SERVER = 0x0003

# Типы запросов и ответов внутри TLV 0x0001 (порядок байт — little-endian)
ICQ_META_REQ_TYPE = 0x07D0
ICQ_META_RESP_TYPE = 0x07DA
ICQ_OFFLINE_REQ = 0x003C       # клиент просит офлайн-сообщения
ICQ_OFFLINE_DELETE = 0x003E    # клиент просит их удалить
ICQ_OFFLINE_MSG = 0x0041       # одно офлайн-сообщение
ICQ_OFFLINE_DONE = 0x0042      # офлайн-сообщения закончились

# Запрос сведений о контакте и части ответа на него
ICQ_REQ_USER_INFO = 0x04B2
ICQ_REQ_SEARCH = 0x055F        # поиск по анкете
ICQ_SEARCH_RESULT = 0x01A4     # очередной найденный
ICQ_SEARCH_LAST = 0x01AE       # последний в выдаче
ICQ_NOT_FOUND = 0x32           # признак «ничего не нашлось»

# Поля запроса поиска: тип пишется big-endian, длина — little-endian
SEARCH_FIELD_UIN = 0x3601
SEARCH_FIELD_NICK = 0x5401
SEARCH_FIELD_FIRSTNAME = 0x4001
SEARCH_FIELD_LASTNAME = 0x4A01
SEARCH_FIELD_EMAIL = 0x5E01
SEARCH_FIELD_CITY = 0x9001
SEARCH_FIELD_KEYWORD = 0x2602
ICQ_INFO_BASIC = 0x00C8        # ник, имя, почта, телефон
ICQ_INFO_MORE = 0x00DC         # возраст, пол, домашняя страница
ICQ_INFO_WORK = 0x00D2         # сведения о работе
ICQ_INFO_ABOUT = 0x00E6        # заметки о пользователе
ICQ_INFO_INTERESTS = 0x00F0    # интересы
ICQ_INFO_END = 0x00FA          # конец ответа
ICQ_INFO_OK = 0x0A             # признак удачного ответа
