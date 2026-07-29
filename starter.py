import subprocess
import time
import sys
import os
import datetime
from telegram import send_to_telegram
from dotenv import load_dotenv

load_dotenv()
TG_BOT_TOKEN = (os.getenv("TG_BOT_TOKEN") or "").strip()
MONITOR_ID = (os.getenv("MONITOR_ID") or "").strip()


def run_with_restart():
    process = None
    while True:
        try:
            print(f"[{datetime.datetime.now()}] Запуск main.py...")

            process = subprocess.Popen([sys.executable, "main.py"])
            if MONITOR_ID:
                send_to_telegram(
                    TG_BOT_TOKEN,
                    MONITOR_ID,
                    "<b>Бот встал</b>",
                )

            exit_code = process.wait()
            if MONITOR_ID:
                send_to_telegram(
                    TG_BOT_TOKEN,
                    MONITOR_ID,
                    f"[{datetime.datetime.now()}] Скрипт упал (код: {exit_code})",
                )
            print(
                f"[{datetime.datetime.now()}] Скрипт упал (код: {exit_code}). "
                "Перезапуск через 3 секунды..."
            )
            time.sleep(3)

        except KeyboardInterrupt:
            print(f"\n[{datetime.datetime.now()}] Остановлено пользователем")
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            break
        except Exception as e:
            print(f"[{datetime.datetime.now()}] Ошибка: {e}")
            time.sleep(3)


if __name__ == "__main__":
    run_with_restart()
