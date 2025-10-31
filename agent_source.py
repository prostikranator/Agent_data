#!/usr/bin/env python3
"""
Agent-источник (Tinkoff) — лёгкий веб-сервис для отдачи данных портфеля.

Endpoints:
  GET /health
  GET /portfolio    -> JSON с позициями
  GET /portfolio/csv -> CSV с позициями
"""
import os
import logging
from typing import List, Dict, Any

from flask import Flask, jsonify, Response
import pandas as pd

# --- Корректный импорт Tinkoff SDK (предполагаем, что tinkoff-invest установлен) ---
# Мы используем официальный namespace, как в последнем рабочем варианте.
try:
    from tinkoff.invest import Client, MoneyValue, PortfolioResponse
    from tinkoff.invest.exceptions import RequestError
except ImportError:
    # Если импорт не удался, выдаем явное сообщение, чтобы пользователь проверил requirements
    raise ImportError(
        "Не удалось импортировать Tinkoff SDK. Убедитесь, что установлен пакет 'tinkoff-invest' "
        "или 'invest-python-sdk' через pip."
    )


# Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent_source")

# Конфигурация
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
if not TINKOFF_API_TOKEN:
    logger.warning("❌ TINKOFF_API_TOKEN не задан — запросы к Tinkoff вернут ошибку.")

# Flask
app = Flask(__name__)


# --- Вспомогательные функции ---

def money_to_float(m: MoneyValue) -> float:
    """Конвертирует MoneyValue -> float (рубли)."""
    try:
        # Используем getattr для безопасности
        units = getattr(m, 'units', 0)
        nano = getattr(m, 'nano', 0)
        return float(units) + float(nano) / 1_000_000_000
    except Exception:
        return 0.0


def portfolio_to_dataframe(portfolio: PortfolioResponse) -> pd.DataFrame:
    """Преобразует PortfolioResponse в DataFrame с полезными колонками."""
    rows: List[Dict[str, Any]] = []
    total_value = None
    
    # Общая стоимость портфеля
    if getattr(portfolio, "total_amount_portfolio", None):
        total_value = money_to_float(portfolio.total_amount_portfolio)

    for p in getattr(portfolio, "positions", []) or []:
        # Пропускаем пустые позиции
        if getattr(p, "quantity", None) is None or getattr(p.quantity, "units", 0) == 0:
            continue

        # Безопасное получение данных
        current_price = money_to_float(getattr(p, "current_price", None))
        expected_yield_val = money_to_float(getattr(p, "expected_yield", None))
        qty = getattr(p.quantity, "units", 0)

        total_pos_value = current_price * qty
        # Избегаем деления на ноль
        yield_pct = (expected_yield_val / total_pos_value * 100) if total_pos_value else 0.0

        rows.append({
            "figi": getattr(p, "figi", None),
            "ticker": getattr(p, "ticker", None), # Может быть None, но оставляем
            "instrument_type": getattr(p, "instrument_type", None),
            "quantity": qty,
            "price_rub": round(current_price, 2),
            "position_value_rub": round(total_pos_value, 2),
            "expected_yield_rub": round(expected_yield_val, 2),
            "expected_yield_pct": round(yield_pct, 2),
        })

    df = pd.DataFrame(rows)
    # Сохраняем общую стоимость в атрибутах DataFrame
    df.attrs["total_value_rub"] = round(total_value, 2) if total_value is not None else None
    return df


def fetch_tinkoff_portfolio() -> pd.DataFrame:
    """Подключается к Tinkoff и возвращает DataFrame."""
    if not TINKOFF_API_TOKEN:
        raise RuntimeError("TINKOFF_API_TOKEN не задан. См. логи.")

    try:
        with Client(TINKOFF_API_TOKEN) as client:
            # Получить аккаунты (берем первый)
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
        # Перебрасываем, чтобы обработчики маршрутов могли вернуть 502
        raise
    except Exception as e:
        logger.exception("Неожиданная ошибка при fetch_tinkoff_portfolio")
        raise


# --- Маршруты Flask ---

@app.route("/health", methods=["GET"])
def health():
    """Проверка работоспособности сервиса."""
    return jsonify({"status": "ok"}), 200


@app.route("/portfolio", methods=["GET"])
def portfolio_json():
    """Возвращает JSON с портфелем."""
    try:
        df = fetch_tinkoff_portfolio()
        total = df.attrs.get("total_value_rub", None)
        data = df.to_dict(orient="records")
        return jsonify({"total_value_rub": total, "positions": data}), 200
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except RequestError as e:
        return jsonify({"error": "Ошибка связи с Tinkoff API", "details": str(e)}), 502
    except Exception as e:
        logger.exception("Ошибка при обработке /portfolio")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


@app.route("/portfolio/csv", methods=["GET"])
def portfolio_csv():
    """Возвращает CSV."""
    try:
        df = fetch_tinkoff_portfolio()
        if df.empty:
            # Возвращаем пустую CSV с заголовком
            return Response("position_count\n0\n", mimetype="text/csv"), 200
        
        # Удаляем метаданные о сумме перед конвертацией в CSV
        df = df.drop(columns=['total_value_rub'], errors='ignore')
        csv = df.to_csv(index=False)
        return Response(csv, mimetype="text/csv"), 200
    except Exception as e:
        logger.exception("Ошибка при обработке /portfolio/csv")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


# --- Запуск ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info("Запуск Agent-источника (Tinkoff). Порт %s", port)
    try:
        # Устанавливаем debug=True, если запускаем локально
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception:
        logger.exception("Flask сервер упал при запуске")
        raise
