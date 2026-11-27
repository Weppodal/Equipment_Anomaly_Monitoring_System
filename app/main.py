import io
import os
import pandas as pd
import plotly.graph_objects as go
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Мониторинг аномалий оборудования")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

NUMERIC_COLUMNS = ["temperature", "vibration", "current", "pressure"]

REQUIRED_COLUMNS = ["timestamp", "device_id", *NUMERIC_COLUMNS]


def validate_telemetry_csv(content: bytes):
    """Проверка CSV файлов"""
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        return None, f"Ошибка чтения CSV-файла: {e}"

    # 1. Проверка обязательных колонок
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return None, f"Отсутствуют обязательные колонки: {', '.join(missing_cols)}"

    # 2. Проверка, есть ли вообще записи
    if len(df) == 0:
        return None, "Файл пуст (0 записей)."

    # Проверка явных единиц измерения (Ошибка Е-04)
    # Проверяем опциональную колонку temperature_unit (если она есть в файле)
    if "temperature_unit" in df.columns:
        bad_units = df[df["temperature_unit"].astype(str).str.strip().str.upper() != "C"]
        if not bad_units.empty:
            wrong_u = bad_units["temperature_unit"].iloc[0]
            return None, (
                f"Ошибка Е-04 (Другая единица измерения): для температуры указана единица '{wrong_u}', "
                "ожидается шкала Цельсия ('C')."
            )

    # 3. Проверка формата временных меток
    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M:%S")
    except Exception:
        return None, "Ошибка формата времени: колонка timestamp должна соответствовать ГГГГ-ММ-ДД ЧЧ:ММ:СС."

    # Проверка повторных меток времени
    dup_mask = df["timestamp"].duplicated(keep="first")
    if dup_mask.any():
        dup_ts = ', '.join(ts.strftime("%Y-%m-%d %H:%M:%S") for ts in df.loc[dup_mask, 'timestamp'])
        dup_count = int(dup_mask.sum())
        return None, (
            f"Ошибка временных меток (Сценарий П-03): обнаружены повторяющиеся метки времени "
            f"({dup_count} дубл., повторяющиеся метки: {dup_ts})."
        )

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Проверка пропусков и NaN, некорректных значений (Ошибка Е-02)
    cols_with_nan = []
    nan_rows_mask = df["device_id"].isna()  # учитываем пропуски и в device_id

    error_text = []

    for col in NUMERIC_COLUMNS:
        non_null_mask = df[col].notna()
        converted = pd.to_numeric(df[col], errors="coerce")

        # Если ячейка была не пустой, но после to_numeric стала NaN — значит там текст/мусор
        invalid_type_mask = non_null_mask & converted.isna()
        if invalid_type_mask.any():
            bad_ids = df[invalid_type_mask].index
            bad_values_text = [
                f"{df.loc[bad_idx, col]} (время: {df.loc[bad_idx, 'timestamp'].strftime('%Y-%m-%d %H:%M:%S')})"
                for bad_idx in bad_ids
            ]
            error_text.append(f"Ошибка типа данных: некорректное числовое значение '{', '.join(bad_values_text)}' в колонке '{col}'")
            continue

        # Сохраняем уже очищенную числовую колонку и фиксируем пустые ячейки (NaN)
        df[col] = converted
        nan_count = int(df[col].isna().sum())
        if nan_count > 0:
            cols_with_nan.append(f"{col} ({nan_count} шт.)")
            nan_rows_mask = nan_rows_mask | df[col].isna()

    if len(error_text) > 0:
        return None, "\n".join(error_text)

    if nan_rows_mask.any():
        if df["device_id"].isna().any():
            cols_with_nan.insert(0, f"device_id ({int(df['device_id'].isna().sum())} шт.)")
        nan_times = df.loc[nan_rows_mask, "timestamp"]
        t_start = nan_times.min().strftime("%Y-%m-%d %H:%M:%S")
        t_end = nan_times.max().strftime("%Y-%m-%d %H:%M:%S")
        time_info = t_start if t_start == t_end else f"в интервале с {t_start} по {t_end}"

        return None, (
            f"Ошибка Е-02 (Пропуски и NaN): обнаружены пустые значения в колонках: {', '.join(cols_with_nan)} "
            f"(время: {time_info})."
        )

    # Проверяем значение температуры, даже если есть колонка единиц измерения температуры и там написано "С", если нету этой колонки, по умолчанию считаем в Цельсиях
    if (df["temperature"] > 150).any() or (df["temperature"] < -50).any():
        bad_temp_idx = df[(df["temperature"] > 150) | (df["temperature"] < -50)].index.min()
        bad_temp = df.at[bad_temp_idx, "temperature"]
        bad_ts = df.at[bad_temp_idx, "timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        return None, (
            f"Ошибка Е-04 (Некорректная шкала температуры): значение {bad_temp} (в {bad_ts}) "
            "выходит за допустимый диапазон для градусов Цельсия (-50..150 °C). Возможно, данные переданы в Кельвинах или Фаренгейтах."
        )

    # 5. Проверка разрывов (Ошибка Е-03)
    diffs = df["timestamp"].diff().dropna()
    max_gap = diffs.max()
    if max_gap > pd.Timedelta(minutes=15):
        gap_idx = diffs.idxmax()
        t_before = df.loc[gap_idx - 1, "timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        t_after = df.loc[gap_idx, "timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        return None, (
            f"Ошибка Е-03 (Длинный период без данных): обнаружен разрыв телеметрии длиной {int(max_gap.total_seconds() // 60)} мин. "
            f"(отсутствуют данные с {t_before} по {t_after})."
        )

    # 6. Проверка регулярности шага (Ошибка Е-01)
    bad_step_mask = diffs.notna() & (diffs != pd.Timedelta(minutes=1))
    if bad_step_mask.any():
        first_bad_idx = diffs[bad_step_mask].index[0]
        t_prev = df.loc[first_bad_idx - 1, "timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        t_curr = df.loc[first_bad_idx, "timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        actual_sec = int(diffs.loc[first_bad_idx].total_seconds())

        return None, (
            f"Ошибка Е-01 (Нерегулярный шаг датчика): интервал между записями нарушен "
            f"(ожидается 60 сек., фактически {actual_sec} сек. между {t_prev} и {t_curr})."
        )

    return df, None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/upload", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
):
    if not file.filename.endswith(".csv"):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context = {"error": "Некорректное расширение файла. Загрузите файл в формате .csv"},
        )

    content = await file.read()
    df, error = validate_telemetry_csv(content)

    if error:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": error,
                "filename": file.filename,
            },
        )

    params_info = [
    ("temperature", "Температура (°C)"),
    ("vibration", "Вибрация (мм/с)"),
    ("current", "Ток двигателя (А)"),
    ("pressure", "Давление (бар)"),
    ]

    fig = go.Figure() # График

    # Добавляем все 4 линии на график, но видимой оставляем только первую (temperature)
    for idx, (col, label) in enumerate(params_info):
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df[col],
                name=label,
                visible=(idx == 0),
            )
        )

    # Создаем кнопки выпадающего списка внутри самого графика
    buttons = []
    for idx, (col, label) in enumerate(params_info):
        visibility = [i == idx for i in range(len(params_info))]
        buttons.append(
            dict(
                label=label,
                method="update",
                args=[
                    {"visible": visibility},
                    {
                        "title": {
                            "text": f"Показания датчика: {label} (Оборудование: {df['device_id'].iloc[0]})",
                            "y": 0.96
                        },
                        "yaxis": {"title": {"text": label}},
                    },
                ],
            )
        )

    fig.update_layout(
        title=dict(
            text=f"Показания датчика: {params_info[0][1]} (Оборудование: {df['device_id'].iloc[0]})",
            y=0.96,
        ),
        xaxis_title="Время измерения",
        yaxis_title=params_info[0][1],
        height=480,
        margin=dict(l=20, r=20, t=90, b=20),
        updatemenus=[
            dict(
                active=0,
                buttons=buttons,
                direction="down",
                showactive=True,
                x=0.0,
                xanchor="left",
                y=1.14,
                yanchor="top",
            )
        ],
    )

    plot_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    summary = {
        "filename": file.filename,
        "rows": len(df),
        "device_id": df["device_id"].iloc[0],
        "start_time": df["timestamp"].min(),
        "end_time": df["timestamp"].max(),
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "summary": summary,
            "plot_html": plot_html,
        },
    )
