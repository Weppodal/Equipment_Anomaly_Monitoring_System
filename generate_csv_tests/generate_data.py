import os
import numpy as np
import pandas as pd

# Создаем папку для тестовых данных согласно п. 9.4 ТЗ
os.makedirs("tests/fixtures", exist_ok=True)

# 1. Генерируем нормальную работу оборудования (7 дней с шагом 1 минута = 10 080 строк)
np.random.seed(42)
n_rows = 10080
timestamps = pd.date_range(start="2026-05-01 00:00:00", periods=n_rows, freq="1min")

# Имитируем плавные суточные колебания + небольшой шум датчиков
time_idx = np.arange(n_rows)
temperature = 65.0 + 3.0 * np.sin(2 * np.pi * time_idx / 1440) + np.random.normal(0, 0.5, n_rows)
vibration = 1.8 + 0.2 * np.sin(2 * np.pi * time_idx / 720) + np.random.normal(0, 0.08, n_rows)
current = 12.5 + 0.5 * np.cos(2 * np.pi * time_idx / 1440) + np.random.normal(0, 0.15, n_rows)
pressure = 4.2 + np.random.normal(0, 0.05, n_rows)

df = pd.DataFrame({
    "timestamp": timestamps,
    "device_id": "compressor_01",
    "temperature": np.round(temperature, 2),
    "vibration": np.round(vibration, 3),
    "current": np.round(current, 2),
    "pressure": np.round(pressure, 2),
    "is_anomaly": 0,
    "anomaly_type": "normal"
})

# 2. Внедряем 12 размеченных аномалий (по ТЗ нужно минимум 10)
# События 1-4: Перегрев (рост температуры до ~88-95 °C на 10-15 минут)
overheat_starts = [500, 2100, 4800, 7900]
for start in overheat_starts:
    df.loc[start:start+12, "temperature"] += np.random.uniform(22, 28)
    df.loc[start:start+12, "is_anomaly"] = 1
    df.loc[start:start+12, "anomaly_type"] = "overheat"

# События 5-8: Скачок вибрации (рост до ~5-7 мм/с на 5-8 минут)
vib_starts = [1200, 3400, 6100, 8800]
for start in vib_starts:
    df.loc[start:start+6, "vibration"] += np.random.uniform(3.5, 5.0)
    df.loc[start:start+6, "is_anomaly"] = 1
    df.loc[start:start+6, "anomaly_type"] = "high_vibration"

# События 9-12: Перегрузка по току и падение давления (на 8 минут)
load_starts = [1800, 4100, 7000, 9500]
for start in load_starts:
    df.loc[start:start+8, "current"] += np.random.uniform(6.0, 8.0)
    df.loc[start:start+8, "pressure"] -= np.random.uniform(1.2, 1.8)
    df.loc[start:start+8, "is_anomaly"] = 1
    df.loc[start:start+8, "anomaly_type"] = "overload"

# Сохраняем эталонный файл (его также нужно будет указать единицы измерения в шапке или метаданных)
df.to_csv("tests/fixtures/reference_telemetry.csv", index=False)

# 3. Создаем 4 файла с ошибками для негативных испытаний (Раздел 9.3 ТЗ)

# Н-01: Нерегулярный шаг датчика (сбиваем время в середине файла)
df_irregular = df.copy()
df_irregular.loc[3000:3010, "timestamp"] = df_irregular.loc[3000:3010, "timestamp"] + pd.Timedelta(seconds=23)
df_irregular.to_csv("tests/fixtures/err_01_irregular_step.csv", index=False)

# Н-02: Пропуски и NaN в показаниях
df_nan = df.copy()
df_nan.loc[1500:1505, "temperature"] = np.nan
df_nan.loc[4500:4503, "current"] = np.nan
df_nan.to_csv("tests/fixtures/err_02_missing_nan.csv", index=False)

# Н-03: Длинный период без данных (вырезаем 4 часа записей = 240 строк)
df_gap = df.drop(index=range(5000, 5240)).reset_index(drop=True)
df_gap.to_csv("tests/fixtures/err_03_long_gap.csv", index=False)

# Н-04: Параметр в другой единице измерения (температура в Кельвинах вместо Цельсия: +273.15)
df_units = df.copy()
df_units["temperature"] = np.round(df_units["temperature"] + 273.15, 2)
df_units.to_csv("tests/fixtures/err_04_wrong_units.csv", index=False)

print("Готово! Файлы сохранены в папку tests/fixtures/")

