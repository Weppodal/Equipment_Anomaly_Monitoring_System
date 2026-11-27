import os
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
FIXTURES_DIR = os.path.join(PROJECT_ROOT, "tests", "fixtures")

# Создаем папку для тестовых данных согласно п. 9.4 ТЗ
os.makedirs(FIXTURES_DIR, exist_ok=True)

# 1. Генерируем нормальную работу оборудования (7 дней с шагом 1 минута = 10 080 строк)
np.random.seed(42)
n_rows = 10080
device_id = "compressor_01"
timestamps = pd.date_range(start="2026-05-01 00:00:00", periods=n_rows, freq="1min")

# Базовые средние значения нормальной работы для расчёта точного отклонения
BASELINE_MEANS = {
    "temperature": 65.0,
    "vibration": 1.8,
    "current": 12.5,
    "pressure": 4.2,
}

# Имитируем плавные суточные колебания + небольшой шум датчиков
time_idx = np.arange(n_rows)
temperature = BASELINE_MEANS["temperature"] + 3.0 * np.sin(2 * np.pi * time_idx / 1440) + np.random.normal(0, 0.5, n_rows)
vibration = BASELINE_MEANS["vibration"] + 0.2 * np.sin(2 * np.pi * time_idx / 720) + np.random.normal(0, 0.08, n_rows)
current = BASELINE_MEANS["current"] + 0.5 * np.cos(2 * np.pi * time_idx / 1440) + np.random.normal(0, 0.15, n_rows)
pressure = BASELINE_MEANS["pressure"] + np.random.normal(0, 0.05, n_rows)

df = pd.DataFrame({
    "timestamp": timestamps,
    "device_id": device_id,
    "temperature": np.round(temperature, 2),
    "vibration": np.round(vibration, 3),
    "current": np.round(current, 2),
    "pressure": np.round(pressure, 2),
    "temperature_unit": "C",
})

# Список для накопления эталонных событий
events_log = []

def inject_anomaly(start_idx, duration, param_name, delta, anomaly_type):
    end_idx = start_idx + duration
    df.loc[start_idx:end_idx, param_name] = np.round(df.loc[start_idx:end_idx, param_name] + delta, 3)

    peak_val = df.loc[start_idx:end_idx, param_name].max() if delta > 0 else df.loc[start_idx:end_idx, param_name].min()
    # Величина отклонения от нормального базового уровня
    deviation = round(float(peak_val - BASELINE_MEANS[param_name]), 3)

    events_log.append({
        "event_id": len(events_log) + 1,
        "device_id": device_id,
        "parameter_name": param_name,
        "start_time": df.loc[start_idx, "timestamp"],
        "end_time": df.loc[end_idx, "timestamp"],
        "peak_value": peak_val,
        "deviation": deviation,
        "anomaly_type": anomaly_type,
    })

# 2. Внедряем 12 размеченных аномалий (по ТЗ нужно минимум 10)
# События 1-4: Перегрев (рост температуры до ~88-95 °C на 10-15 минут)
overheat_starts = [500, 2100, 4800, 7900]
for start in overheat_starts:
    inject_anomaly(
        start_idx=start,
        duration=12,
        param_name="temperature",
        delta=np.random.uniform(22.0, 26.0),
        anomaly_type="overheat",
    )

# События 5-8: Скачок вибрации (рост до ~5-7 мм/с на 5-8 минут)
vib_starts = [1200, 3400, 6100, 8800]
for start in vib_starts:
    inject_anomaly(
        start_idx=start,
        duration=6,
        param_name="vibration",
        delta=np.random.uniform(3.8, 4.8),
        anomaly_type="high_vibration",
    )

# События 9-12: Перегрузка по току (на 8 минут)
load_starts = [1800, 4100, 7000, 9500]
for start in load_starts:
    inject_anomaly(
        start_idx=start,
        duration=8,
        param_name="current",
        delta=np.random.uniform(6.0, 7.5),
        anomaly_type="overload",
    )

# Сортируем эталонную разметку по времени начала и перенумеровываем event_id
events_df = pd.DataFrame(events_log).sort_values("start_time").reset_index(drop=True)
events_df["event_id"] = events_df.index + 1

# Сохраняем эталонный файл и эталонную разметку событий
df.to_csv(os.path.join(FIXTURES_DIR, "reference_telemetry.csv"), index=False)
events_df.to_csv(os.path.join(FIXTURES_DIR, "reference_events.csv"), index=False)

# 3. Создаем 4 файла с ошибками для негативных испытаний (Раздел 9.3 ТЗ)

# Н-01: Нерегулярный шаг датчика (сбиваем время в середине файла)
df_irregular = df.copy()
df_irregular.loc[3000:3010, "timestamp"] = df_irregular.loc[3000:3010, "timestamp"] + pd.Timedelta(seconds=23)
df_irregular.to_csv(os.path.join(FIXTURES_DIR, "err_01_irregular_step.csv"), index=False)

# Н-02: Пропуски и NaN в показаниях
df_nan = df.copy()
df_nan.loc[1500:1505, "temperature"] = np.nan
df_nan.loc[4500:4503, "current"] = np.nan
df_nan.to_csv(os.path.join(FIXTURES_DIR, "err_02_missing_nan.csv"), index=False)

# Н-03: Длинный период без данных (вырезаем 4 часа записей = 240 строк)
df_gap = df.drop(index=range(5000, 5240)).reset_index(drop=True)
df_gap.to_csv(os.path.join(FIXTURES_DIR, "err_03_long_gap.csv"), index=False)

# Н-04: Параметр в другой единице измерения (температура в Кельвинах вместо Цельсия: +273.15)
df_units = df.copy()
df_units["temperature"] = np.round(df_units["temperature"] + 273.15, 2)
df_units["temperature_unit"] = "K"
df_units.to_csv(os.path.join(FIXTURES_DIR, "err_04_wrong_units.csv"), index=False)

# Н-05: Повторные метки времени (Сценарий П-03)
df_ts_dup = df.copy()
df_ts_dup.at[2001, "timestamp"] = df_ts_dup.at[2000,"timestamp"]
df_ts_dup.at[4888, "timestamp"] = df_ts_dup.at[4887, "timestamp"]
df_ts_dup.to_csv(os.path.join(FIXTURES_DIR, "err_05_duplicate_timestamps.csv"), index=False)

# Н-06: Некорректные числовые значения (текстовый мусор вместо цифры)
df_bad_num = df.copy()
df_bad_num["temperature"] = df_bad_num["temperature"].astype(object)
df_bad_num["current"] = df_bad_num["current"].astype(object)
df_bad_num.at[2500, "temperature"] = "sensor_err"
df_bad_num.at[3655, "current"] = "12.5current"
df_bad_num.to_csv(os.path.join(FIXTURES_DIR, "err_06_invalid_numbers.csv"), index=False)

# Н-07: Неявная ошибка единиц измерения (колонка temperature_unit отсутствует, но значения в Кельвинах)
df_implicit_units = df.drop(columns=["temperature_unit"]).copy()
df_implicit_units["temperature"] = np.round(df_implicit_units["temperature"] + 273.15, 2)
df_implicit_units.to_csv(os.path.join(FIXTURES_DIR, "err_07_implicit_kelvin.csv"), index=False)

print(f"Готово! Файлы сохранены в папку {FIXTURES_DIR}")

