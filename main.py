from max import MaxClient as Client
from filters import filters
from classes import Message
from telegram import send_to_telegram
import os
import time
import hashlib
from collections import OrderedDict
from dotenv import load_dotenv

load_dotenv()

MAX_TOKEN = (os.getenv("MAX_TOKEN") or "").strip()
MAX_CHAT_IDS_RAW = (os.getenv("MAX_CHAT_IDS") or "").strip()
TG_BOT_TOKEN = (os.getenv("TG_BOT_TOKEN") or "").strip()
TG_CHAT_ID = (os.getenv("TG_CHAT_ID") or "").strip()
MONITOR_ID = (os.getenv("MONITOR_ID") or "").strip()

if not MAX_TOKEN or not MAX_CHAT_IDS_RAW or not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise SystemExit(
        "Ошибка в .env: нужны MAX_TOKEN, MAX_CHAT_IDS, TG_BOT_TOKEN, TG_CHAT_ID"
    )

MAX_CHAT_IDS = [int(x.strip()) for x in MAX_CHAT_IDS_RAW.split(",") if x.strip()]
client = Client(MAX_TOKEN)

_SKIP_STATUSES = {"REMOVED", "EDITED"}
_HISTORY_GRACE_MS = 5000
_CONTENT_DEDUP_SEC = 25


class Dedup:
    def __init__(self):
        self._ids: OrderedDict[str, float] = OrderedDict()
        self._cids: OrderedDict[str, float] = OrderedDict()
        self._content: OrderedDict[str, float] = OrderedDict()

    def _prune(self, store: OrderedDict[str, float], ttl: float):
        now = time.time()
        while store and now - next(iter(store.values())) > ttl:
            store.popitem(last=False)

    def check(self, message: Message, content_key: str) -> str | None:
        now = time.time()
        id_key = f"{message.chat.id}:{message.id}"
        self._prune(self._ids, 600)
        if id_key in self._ids:
            return f"duplicate id={message.id}"
        self._ids[id_key] = now

        if message.cid:
            cid_key = f"{message.chat.id}:{message.cid}"
            self._prune(self._cids, 600)
            if cid_key in self._cids:
                return f"duplicate cid={message.cid}"
            self._cids[cid_key] = now

        self._prune(self._content, _CONTENT_DEDUP_SEC)
        if content_key in self._content:
            return "duplicate content (burst)"
        self._content[content_key] = now
        return None


_dedup = Dedup()


def _attach_signature(attaches: list) -> tuple:
    sig = []
    for a in attaches or []:
        sig.append((
            a.get("_type"),
            a.get("photoId"),
            a.get("fileId"),
            a.get("videoId"),
            (a.get("baseUrl") or a.get("baseRawUrl") or "")[:120],
            a.get("name"),
        ))
    return tuple(sig)


def _extract_payload(message: Message) -> tuple[str, list, dict]:
    msg_text = message.text or ""
    msg_attaches = message.attaches or []
    link = message.kwargs.get("link") or {}

    if link.get("type") == "FORWARD":
        fwd = link.get("message") or {}
        msg_text = fwd.get("text") or msg_text
        msg_attaches = fwd.get("attaches") or msg_attaches
    return msg_text, msg_attaches, link


def _content_key(message: Message, msg_text: str, msg_attaches: list, link: dict) -> str:
    fwd_id = ""
    if link.get("type") == "FORWARD":
        fwd_id = str((link.get("message") or {}).get("id") or "")
    raw = "|".join([
        str(message.chat.id),
        str(message.sender),
        msg_text.strip(),
        str(_attach_signature(msg_attaches)),
        fwd_id,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


def resolve_attachments(client: Client, message: Message, attaches: list) -> list[dict]:
    """Turn MAX attaches into {url, type, name} for Telegram upload."""
    out = []
    chat_id = message.chat.id
    message_id = message.id

    for attach in attaches or []:
        kind = attach.get("_type")
        if kind == "PHOTO":
            url = attach.get("baseUrl") or attach.get("baseRawUrl")
            if url:
                out.append({"url": url, "type": "photo", "name": "photo.jpg"})
        elif kind == "VIDEO":
            video_id = attach.get("videoId")
            token = attach.get("token")
            thumb = attach.get("thumbnail")
            urls = (
                client.get_video_download_urls(
                    video_id, chat_id, message_id, token=token
                )
                if video_id else []
            )
            if urls:
                out.append({
                    "urls": urls,
                    "url": urls[0],
                    "type": "video",
                    "name": attach.get("name") or "video.mp4",
                    "thumb_url": thumb,
                })
            elif thumb:
                out.append({
                    "url": thumb,
                    "type": "photo",
                    "name": "thumb.jpg",
                })
        elif kind == "FILE":
            file_id = attach.get("fileId")
            if file_id:
                url = client.get_file_download_url(file_id, chat_id, message_id)
                if url:
                    out.append({
                        "url": url,
                        "type": "document",
                        "name": attach.get("name") or "file.bin",
                    })
        elif attach.get("baseUrl"):
            out.append({"url": attach["baseUrl"], "type": "photo", "name": "photo.jpg"})
    return out


@client.on_connect
def onconnect():
    if client.me is not None:
        print(
            f"Имя: {client.me.contact.names[0].name}, "
            f"Номер: {client.me.contact.phone} | ID: {client.me.contact.id}"
        )
        print(f"Сессия с {client.connected_at_ms}, старые сообщения пропускаем")


@client.on_message(filters.any())
def onmessage(client: Client, message: Message):
    if message.chat.id not in MAX_CHAT_IDS:
        return
    if message.status in _SKIP_STATUSES:
        print(f"skip status={message.status} id={message.id}")
        return

    if message.time and client.connected_at_ms:
        if message.time < client.connected_at_ms - _HISTORY_GRACE_MS:
            print(f"skip history id={message.id} time={message.time}")
            return

    msg_text, msg_attaches, link = _extract_payload(message)
    dup = _dedup.check(message, _content_key(message, msg_text, msg_attaches, link))
    if dup:
        print(f"skip {dup}")
        return

    try:
        name = message.user.contact.names[0].name
    except Exception:
        name = str(message.sender)

    if link.get("type") == "FORWARD":
        fwd = link.get("message") or {}
        try:
            forwarded_msg_author = client.get_user(id=fwd.get("sender"), _f=1)
            name = f"{name}\n(Переслано: {forwarded_msg_author.contact.names[0].name})"
        except Exception:
            name = f"{name}\n(Переслано)"

    attachments = resolve_attachments(client, message, msg_attaches)

    if msg_text or attachments:
        caption = f"<b>{name}</b>\n{msg_text}" if msg_text else f"<b>{name}</b>"
        print(
            f"-> TG chat={message.chat.id} id={message.id} "
            f"text={msg_text[:80]!r} attaches={len(attachments)}"
        )
        send_to_telegram(TG_BOT_TOKEN, TG_CHAT_ID, caption, attachments)


if __name__ == "__main__":
    client.run()
