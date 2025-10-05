import subprocess
import time
import sys
import datetime

def run_with_restart():
    restart_count = 0
    
    while True:
        try:
            print(f"[{datetime.datetime.now()}] Запуск main.py...")
            
            # Запускаем процесс
            process = subprocess.Popen([sys.executable, "main.py"])
            
            # Ждем завершения
            process.wait()
            exit_code = process.returncode
            
            if exit_code == 0:
                print(f"[{datetime.datetime.now()}] Скрипт завершился нормально.")
                break
            else:
                restart_count += 1
                print(f"[{datetime.datetime.now()}] Скрипт упал (код: {exit_code}). Перезапуск #{restart_count} через 3 секунды...")
                time.sleep(3)
                
        except KeyboardInterrupt:
            print(f"\n[{datetime.datetime.now()}] Остановлено пользователем")
            if process:
                process.terminate()
            break
        except Exception as e:
            print(f"[{datetime.datetime.now()}] Ошибка: {e}")
            time.sleep(3)

if __name__ == "__main__":
    run_with_restart()