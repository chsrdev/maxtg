from max import MaxClient as Client
from filters import filters
from classes import Message
from telegram import send_to_telegram
import time, os
from dotenv import load_dotenv

load_dotenv()

MAX_TOKEN = os.getenv("MAX_TOKEN")
MAX_CHAT_IDS = [int(x) for x in os.getenv("MAX_CHAT_IDS").split(",")]

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
if MAX_TOKEN == "" or MAX_CHAT_IDS == [] or TG_BOT_TOKEN == "" or TG_CHAT_ID == "":
    print("Ошибка в .env, перепроверьтье")
MONITOR_ID = os.getenv("MONITOR_ID")
client = Client(MAX_TOKEN)

@client.on_connect
def onconnect():
    if client.me != None:
        print(f"Имя: {client.me.contact.names[0].name}, Номер: {client.me.contact.phone} | ID: {client.me.contact.id}")


@client.on_message(filters.any())
def onmessage(client: Client, message: Message):
    if message.chat.id in MAX_CHAT_IDS and message.status != "REMOVED":
        msg_text = message.text
        msg_attaches = message.attaches
        name = message.user.contact.names[0].name
        if "link" in message.kwargs.keys():
            if "type" in message.kwargs["link"]:
                if message.kwargs["link"]["type"] == "REPLY": # TODO
                    ...
                if message.kwargs["link"]["type"] == "FORWARD":
                    msg_text = message.kwargs["link"]["message"]["text"]
                    msg_attaches = message.kwargs["link"]["message"]["attaches"]
                    forwarded_msg_author = client.get_user(id=message.kwargs["link"]["message"]["sender"], _f=1)
                    name = f"{name}\n(Переслано: {forwarded_msg_author.contact.names[0].name})"

        if msg_text != "" or msg_attaches != []:
            send_to_telegram(
                TG_BOT_TOKEN,
                TG_CHAT_ID,
                f"<b>{name}</b>\n{msg_text}" if msg_text != "" else f"<b>{name}</b>",
                msg_attaches
                # [attach['baseUrl'] for attach in msg_attaches if 'baseUrl' in attach]
            )
client.run()

