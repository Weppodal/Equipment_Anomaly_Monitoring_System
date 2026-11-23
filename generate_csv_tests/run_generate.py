import os
import subprocess
import sys

venv_dir = ".venv"
is_windows = os.name == "nt"

python_bin = os.path.join(venv_dir, "Scripts", "python.exe") if is_windows else os.path.join(venv_dir, "bin", "python")

if not os.path.exists(venv_dir):
    print("Создание виртуального окружения...")
    subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
    print("Установка библиотек")
    subprocess.check_call([python_bin, "-m", "pip", "install", "-r", "requirements.txt"])

print("Генерация учебных файлов...")
subprocess.check_call([python_bin, "generate_data.py"])
input("Нажмите Enter, чтобы закрыть программу...")
