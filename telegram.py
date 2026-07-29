import json
import os
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import tempfile


# Several CDN header profiles — okcdn often 400s on "wrong" client fingerprint
HEADER_PROFILES = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/117.0.0.0 Safari/537.36"
        ),
        "Referer": "https://web.max.ru/",
        "Origin": "https://web.max.ru",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/117.0.0.0 Safari/537.36"
        ),
        "Referer": "https://m.ok.ru/",
        "Origin": "https://m.ok.ru",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9",
    },
    {
        "User-Agent": "okhttp/4.12.0",
        "Accept": "*/*",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/117.0.0.0 Mobile Safari/537.36"
        ),
        "Referer": "https://web.max.ru/",
        "Accept": "*/*",
        "Range": "bytes=0-",
    },
]


def get_file_type(url: str, hint: str | None = None, name: str | None = None):
    if hint in ("photo", "video", "document"):
        mime = {
            "photo": "image/jpeg",
            "video": "video/mp4",
            "document": "application/octet-stream",
        }[hint]
        return hint, mime

    path = urlparse(url).path.lower()
    fname = (name or os.path.basename(path) or "").lower()
    blob = f"{path} {fname} {url.lower()}"

    video_exts = (".mp4", ".mov", ".avi", ".mkv", ".webm")
    photo_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")

    if any(ext in blob for ext in video_exts) or (
        "okcdn.ru" in url and hint == "video"
    ):
        return "video", "video/mp4"
    if (
        any(ext in blob for ext in photo_exts)
        or "i.oneme.ru" in url
        or "photo" in blob
    ):
        return "photo", "image/jpeg"
    return "document", "application/octet-stream"


def _candidate_urls(url: str) -> list[str]:
    """Generate slight URL variants that sometimes unblock okcdn."""
    out = [url]
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        # clientType=51 (mobile) sometimes rejects desktop UA — try 0/6 (web)
        if "clientType" in qs:
            for ct in ("0", "6", "51"):
                if qs["clientType"] == [ct]:
                    continue
                alt = dict(qs)
                alt["clientType"] = [ct]
                query = urlencode({k: v[0] for k, v in alt.items()})
                out.append(urlunparse(parsed._replace(query=query)))
    except Exception:
        pass
    # unique preserve order
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def download_file(url: str, is_video: bool = False):
    urls = _candidate_urls(url) if is_video or "okcdn.ru" in url else [url]
    last_err = None
    for candidate in urls:
        for headers in HEADER_PROFILES:
            try:
                response = requests.get(
                    candidate,
                    headers=headers,
                    timeout=90,
                    allow_redirects=True,
                )
                if response.status_code == 400:
                    last_err = f"400 for {candidate[:90]} UA={headers.get('User-Agent','')[:30]}"
                    continue
                response.raise_for_status()
                content = response.content
                # reject tiny HTML/error bodies
                ctype = (response.headers.get("Content-Type") or "").lower()
                if "text/html" in ctype or len(content) < 1024:
                    last_err = f"bad body ({ctype}, {len(content)}b)"
                    continue
                return content
            except Exception as e:
                last_err = str(e)
                continue
    print(f"Ошибка скачивания {url[:120]}...: {last_err}")
    return None


def download_any(urls: list[str], is_video: bool = False):
    for url in urls:
        content = download_file(url, is_video=is_video)
        if content:
            return content, url
    return None, None


def _upload_bytes(TG_BOT_TOKEN, TG_CHAT_ID, caption, item: dict, file_content: bytes):
    url = item.get("url") or ""
    file_type, mime = get_file_type(url, item.get("type"), item.get("name"))
    method = {
        "photo": "sendPhoto",
        "video": "sendVideo",
        "document": "sendDocument",
    }[file_type]
    field = file_type

    data = {"chat_id": TG_CHAT_ID, "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption
    if file_type == "video":
        data["supports_streaming"] = "true"

    ext_map = {"video": ".mp4", "photo": ".jpg", "document": ""}
    suffix = ext_map[file_type]
    if item.get("name") and "." in item["name"]:
        suffix = os.path.splitext(item["name"])[1] or suffix
    filename = item.get("name") or f"file{suffix}"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            files = {field: (filename, f, mime)}
            resp = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}",
                data=data,
                files=files,
                timeout=180,
            )
            print(resp.json())
            return resp.json().get("ok", False)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return False


def _send_one(TG_BOT_TOKEN, TG_CHAT_ID, caption, item: dict):
    urls = list(item.get("urls") or [])
    if item.get("url") and item["url"] not in urls:
        urls.insert(0, item["url"])

    is_video = item.get("type") == "video"
    content, used = download_any(urls, is_video=is_video)
    if content:
        item = dict(item)
        item["url"] = used or item.get("url") or ""
        return _upload_bytes(TG_BOT_TOKEN, TG_CHAT_ID, caption, item, content)

    thumb = item.get("thumb_url")
    if thumb and is_video:
        note = (
            f"{caption}\n[Видео не скачалось, превью]"
            if caption
            else "[Видео не скачалось, превью]"
        )
        thumb_content = download_file(thumb)
        if thumb_content:
            return _upload_bytes(
                TG_BOT_TOKEN,
                TG_CHAT_ID,
                note,
                {"url": thumb, "type": "photo", "name": "thumb.jpg"},
                thumb_content,
            )

    requests.post(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        data={
            "chat_id": TG_CHAT_ID,
            "text": (
                f"{caption}\n[Не удалось загрузить файл]"
                if caption
                else "[Не удалось загрузить файл]"
            ),
            "parse_mode": "HTML",
        },
    )
    return False


def _send_photo_album(TG_BOT_TOKEN, TG_CHAT_ID, caption, photos: list[dict]):
    """Send multiple photos as one Telegram album."""
    media = []
    files = {}
    for i, item in enumerate(photos):
        content = download_file(item["url"])
        if not content:
            continue
        key = f"photo{i}"
        media.append({
            "type": "photo",
            "media": f"attach://{key}",
            **({"caption": caption, "parse_mode": "HTML"} if i == 0 and caption else {}),
        })
        files[key] = (item.get("name") or f"photo{i}.jpg", content, "image/jpeg")

    if not media:
        if caption:
            requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                data={"chat_id": TG_CHAT_ID, "text": caption, "parse_mode": "HTML"},
            )
        return

    if len(media) == 1:
        first_key = next(iter(files))
        _upload_bytes(
            TG_BOT_TOKEN, TG_CHAT_ID, caption, photos[0], files[first_key][1]
        )
        return

    resp = requests.post(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMediaGroup",
        data={"chat_id": TG_CHAT_ID, "media": json.dumps(media)},
        files=files,
        timeout=120,
    )
    print(resp.json())


def send_to_telegram(
    TG_BOT_TOKEN: str = "",
    TG_CHAT_ID: int = 0,
    caption: str = "",
    attachments: list | None = None,
):
    attachments = attachments or []

    normalized = []
    for a in attachments:
        if isinstance(a, str):
            normalized.append({"url": a, "type": None, "name": None})
        elif isinstance(a, dict) and (a.get("url") or a.get("urls")):
            normalized.append(a)
    attachments = normalized

    if not attachments:
        if not caption:
            return
        resp = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": caption, "parse_mode": "HTML"},
        )
        print(resp.json())
        return

    photos = [a for a in attachments if a.get("type") == "photo"]
    others = [a for a in attachments if a.get("type") != "photo"]

    if len(photos) >= 2 and not others:
        _send_photo_album(TG_BOT_TOKEN, TG_CHAT_ID, caption, photos)
        return

    first = True
    for item in attachments:
        _send_one(TG_BOT_TOKEN, TG_CHAT_ID, caption if first else "", item)
        first = False
