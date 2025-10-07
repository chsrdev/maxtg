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
    if message.chat.id in MAX_CHAT_IDS:
        send_to_telegram(
            TG_BOT_TOKEN,
            TG_CHAT_ID,
            f"<b>{message.user.contact.names[0].name}</b>\n{message.text}" if message.text != "" else f"<b>{message.user.contact.names[0].name}</b>",
            [attach['baseUrl'] for attach in message.attaches if 'baseUrl' in attach]
        )

client.run()

