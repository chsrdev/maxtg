import requests, json

def handle_attach(attach: dict) -> str:
    match attach["_type"]:
        case "FILE":
            return attach["name"]
        case _:
            return attach["_type"]

def send_to_telegram(TG_BOT_TOKEN: str="", TG_CHAT_ID: int = 0, caption: str = "", attachments: list[dict] = []):
    if not attachments:  # нет фоток — просто текст
        if caption == "": return
        api_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        resp = requests.post(api_url, data={
            "chat_id": TG_CHAT_ID, 
            "text": caption, 
            "parse_mode": "HTML"
            })
        print(resp.json())
        return

    if 1 <= len(attachments) <= 10:
        api_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMediaGroup"
        media = []
        not_handled_attachs = attachments.copy()
        for i, attach in enumerate(attachments):
            if attach["_type"] == "PHOTO":
                item = {"type": "photo", "media": attach["baseUrl"]}
                not_handled_attachs.remove(attach)
                if i == 0 and caption:
                    item["caption"] = caption
                    item["parse_mode"] = "HTML"
                media.append(item)
        if not_handled_attachs:
            if media:
                print(not_handled_attachs)
                media[0]["caption"] += f"\n\nНеобработанные файлы: " + ', '.join(handle_attach(attach) for attach in not_handled_attachs)
            else:
                send_to_telegram(TG_BOT_TOKEN, TG_CHAT_ID, caption + f"\n\nНеобработанные файлы: " + ', '.join(handle_attach(attach) for attach in not_handled_attachs))
                return

        payload = {
            "chat_id": TG_CHAT_ID,
            "media": json.dumps(media)
        }
        resp = requests.post(api_url, data=payload)
        print(resp.json())
        return

    # если фоток больше 10 — разобьём на несколько альбомов
    for i in range(0, len(attachments), 10):
        chunk = attachments[i:i+10]
        send_to_telegram(TG_BOT_TOKEN, TG_CHAT_ID, caption if i == 0 else "", chunk)
