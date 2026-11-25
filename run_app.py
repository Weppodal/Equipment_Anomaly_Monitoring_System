import os
import subprocess
import sys
import webbrowser
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
venv_dir = os.path.join(BASE_DIR, ".venv")
is_windows = os.name == "nt"

def open_brower():
    time.sleep(1.5) # Ждём 1.5 секунды, пока uvicorn поднимет сервер
    webbrowser.open("http://127.0.0.1:8000")

python_bin = os.path.join(venv_dir, "Scripts", "python.exe") if is_windows else os.path.join(venv_dir, "bin", "python")

if not os.path.exists(venv_dir):
    print("Создание виртуального окружения...")
    subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
    print("Установка библиотек")
    subprocess.check_call([python_bin, "-m", "pip", "install", "-r", "requirements.txt"])

print("Запуск веб-приложения")
threading.Thread(target=open_brower, daemon=True).start()
subprocess.check_call([python_bin, "-m", "uvicorn", "app.main:app", "--reload"], cwd=BASE_DIR)
