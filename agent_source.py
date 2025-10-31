#!/usr/bin/env python3
"""
Agent-источник (Tinkoff) — лёгкий веб-сервис для отдачи данных портфеля.

Запуск:
  python agent_source.py

Endpoints:
  GET /health         -> 200 OK если сервис запущен (возвращает json status)
  GET /portfolio      -> возвращает JSON с текущими позициями и общей стоимостью
  GET /portfolio/csv  -> возвращает CSV (text/csv) с теми же данными

Требует в окружении:
  TINKOFF_API_TOKEN
"""
import os
import logging
import traceback
from typing import List, Dict, Any

from flask import Flask, jsonify, Response, request
import pandas as pd

# Попытка корректного импорта SDK — возможны варианты названия пакета в зависимостях
try:
    # Этот импорт соответствует большинству wheel'ей tinkoff-invest (tinkoff_invest)
    from tinkoff_invest import Client, MoneyValue, PortfolioResponse
except Exception:
    # Переходим на альтернативный namespace, если есть (устаревшие варианты)
    try:
        from tinkoff.invest import Client, MoneyValue, PortfolioResponse  # type: ignore
    except Exception as e:
        raise ImportError(
            "Не удалось импортировать Tinkoff SDK. Убедитесь, что в requirements.txt указан tinkoff-invest "
            "и что пакет установлен. Подробность ошибки: " + str(e)
        )

from tinkoff.invest.exceptions import RequestError  # может подняться из пакета

# Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent_source")

# Конфигурация
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
if not TINKOFF_API_TOKEN:
    logger.warning("TINKOFF_API_TOKEN не задан в окружении — сервис запустится, но запросы к Tinkoff вернут ошибку.")

# Flask
app = Flask(__name__)


def money_to_float(m: MoneyValue) -> float:
    """Конвертирует MoneyValue -> float (рубли)."""
    try:
        return float(m.units) + float(m.nano) / 1_000_000_000
    except Exception:
        return 0.0


def portfolio_to_dataframe(portfolio: PortfolioResponse) -> pd.DataFrame:
    """Преобразует PortfolioResponse в DataFrame с полезными колонками."""
    rows: List[Dict[str, Any]] = []
    total_value = None
    try:
        if getattr(portfolio, "total_amount_portfolio", None):
            total_value = money_to_float(portfolio.total_amount_portfolio)

        for p in getattr(portfolio, "positions", []) or []:
            # Пропускаем пустые позиции
            if getattr(p, "quantity", None) is None or getattr(p.quantity, "units", 0) == 0:
                continue

            current_price = money_to_float(getattr(p, "current_price", MoneyValue(units=0, nano=0)))  # type: ignore
            expected_yield_val = money_to_float(getattr(p, "expected_yield", MoneyValue(units=0, nano=0)))  # type: ignore
            qty = getattr(p.quantity, "units", 0)

            total_pos_value = current_price * qty if current_price and qty else 0.0
            yield_pct = (expected_yield_val / total_pos_value * 100) if total_pos_value else 0.0

            rows.append({
                "figi": getattr(p, "figi", None),
                "ticker": getattr(p, "ticker", None),
                "name": getattr(p, "name", None),
                "instrument_type": getattr(p, "instrument_type", None),
                "quantity": qty,
                "price_rub": round(current_price, 2),
                "position_value_rub": round(total_pos_value, 2),
                "expected_yield_rub": round(expected_yield_val, 2),
                "expected_yield_pct": round(yield_pct, 2),
            })
    except Exception:
        logger.exception("Ошибка при конвертации portfolio -> DataFrame")

    df = pd.DataFrame(rows)
    # добавим общий total_value как meta (не строка)
    df.attrs["total_value_rub"] = round(total_value, 2) if total_value is not None else None
    return df


def fetch_tinkoff_portfolio() -> pd.DataFrame:
    """Подключается к Tinkoff и возвращает DataFrame. В случае ошибки возвращает пустой DF."""
    if not TINKOFF_API_TOKEN:
        raise RuntimeError("TINKOFF_API_TOKEN не задан")

    try:
        with Client(TINKOFF_API_TOKEN) as client:
            # получить аккаунты
            accounts = client.users.get_accounts().accounts
            if not accounts:
                logger.info("У пользователя нет доступных аккаунтов в Tinkoff")
                return pd.DataFrame()

            account_id = accounts[0].id
            logger.info(f"Запрос портфеля для account_id={account_id}")

            portfolio = client.operations.get_portfolio(account_id=account_id)
            df = portfolio_to_dataframe(portfolio)
            return df
    except RequestError as e:
        logger.error("Ошибка RequestError при запросе к Tinkoff: %s", e)
        raise
    except Exception as e:
        logger.exception("Неожиданная ошибка при fetch_tinkoff_portfolio: %s", e)
        raise


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/portfolio", methods=["GET"])
def portfolio_json():
    """
    Возвращает JSON с портфелем.
    Пример: GET /portfolio
    """
    try:
        df = fetch_tinkoff_portfolio()
        total = df.attrs.get("total_value_rub", None)
        data = df.to_dict(orient="records")
        return jsonify({"total_value_rub": total, "positions": data}), 200
    except RuntimeError as e:
        logger.error("Runtime error: %s", e)
        return jsonify({"error": str(e)}), 500
    except RequestError as e:
        # явное сообщение про ошибку API
        logger.error("Tinkoff RequestError: %s", e)
        return jsonify({"error": "Ошибка связи с Tinkoff API", "details": str(e)}), 502
    except Exception as e:
        logger.exception("Ошибка при обработке /portfolio")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


@app.route("/portfolio/csv", methods=["GET"])
def portfolio_csv():
    """
    Возвращает CSV в text/csv. GET /portfolio/csv
    """
    try:
        df = fetch_tinkoff_portfolio()
        if df.empty:
            return Response("position_count\n0\n", mimetype="text/csv"), 200
        csv = df.to_csv(index=False)
        return Response(csv, mimetype="text/csv"), 200
    except Exception as e:
        logger.exception("Ошибка при обработке /portfolio/csv")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


# Удобный запуск для Render / локально
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # Логируем старт
    logger.info("Запуск Agent-источника (Tinkoff). Порт %s", port)
    # Оборачиваем run в try чтобы лог был в случае краха
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception:
        logger.exception("Flask сервер упал при запуске")
        raise
