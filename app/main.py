import io
import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Мониторинг аномалий оборудования")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

REQUIRED_COLUMNS = ["timestamp", "device_id", "temperature", "vibration", "current", "pressure"]


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

    # 3. Проверка формата временных меток
    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M:%S")
    except Exception:
        return None, "Ошибка формата времени: колонка timestamp должна соответствовать ГГГГ-ММ-ДД ЧЧ:ММ:СС."

    df = df.sort_values("timestamp").reset_index(drop=True)

    # 4. Проверка пропусков и NaN (Ошибка Е-02)
    nan_mask = df[REQUIRED_COLUMNS].isna().any(axis=1)
    if nan_mask.any():
        nan_counts = df[REQUIRED_COLUMNS].isna().sum()
        cols_with_nan = nan_counts[nan_counts > 0]
        details = ", ".join([f"{col} ({cnt} шт.)" for col, cnt in cols_with_nan.items()])

        nan_times = df.loc[nan_mask, "timestamp"]
        t_start = nan_times.min().strftime("%Y-%m-%d %H:%M:%S")
        t_end = nan_times.max().strftime("%Y-%m-%d %H:%M:%S")
        time_info = t_start if t_start == t_end else f"в интервале с {t_start} по {t_end}"

        return None, (
            f"Ошибка Е-02 (Пропуски и NaN): обнаружены пустые значения в колонках: {details}."
            f"(время: {time_info})."
        )

    # 5. Проверка разрывов и регулярности шага (Ошибки Е-03 и Е-01)
    diffs = df["timestamp"].diff().dropna()
    max_gap = diffs.max()
    if max_gap > pd.Timedelta(minutes=15):
        gap_idx = diffs.idxmax()
        t_before = df.loc[gap_idx - 1, "timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        t_after = df.loc[gap_idx, "timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        return None, (
            f"Ошибка Е-03 (Длинный период без данных): обнаружен разрыв телеметрии длиной {int(max_gap.total_seconds() // 60)} мин."
            f"(отсутствуют данные с {t_before} по {t_after})."
        )

    # 5. Проверка регулярности шага (Ошибка Е-01)
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

    # 6. Проверка единиц измерения (Ошибка Е-04)
    # Нормальная температура компрессора ~65 °C; если среднее > 200 — переданы Кельвины или Фаренгейты
    if df["temperature"].mean() > 200:
        return None, (
            f"Ошибка Е-04 (Другая единица измерения): среднее значение температуры ({df['temperature'].mean():.1f}) "
            "выходит за пределы шкалы Цельсия (возможно, данные переданы в Кельвинах)."
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
