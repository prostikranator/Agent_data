# agent_source.py (Микросервис-источник данных)

import os
import logging
import pandas as pd
from flask import Flask, jsonify
from tinkoff.invest import Client, MoneyValue, PortfolioResponse
from tinkoff.invest.exceptions import RequestError

# --- 1. Настройка и Инициализация ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен Тинькофф берется из переменных окружения
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")

app = Flask(__name__)

if not TINKOFF_API_TOKEN:
    logger.critical("❌ TINKOFF_API_TOKEN не найден. Агент не сможет работать с инвестициями.")

# --- 2. ФУНКЦИИ ---

def to_rubles(money: MoneyValue) -> float:
    """Конвертирует MoneyValue в float рублей."""
    return money.units + money.nano / 1_000_000_000

def get_tinkoff_portfolio_data() -> tuple[int, str]:
    """Получает данные портфеля и форматирует их в строку."""
    if not TINKOFF_API_TOKEN:
        return 500, "❌ Ошибка: TINKOFF_API_TOKEN не задан."
        
    try:
        with Client(TINKOFF_API_TOKEN) as client:
            accounts = client.users.get_accounts().accounts
            if not accounts:
                return 200, "❌ Не найдено активных счетов."
            account_id = accounts[0].id
            
            portfolio: PortfolioResponse = client.operations.get_portfolio(account_id=account_id)
            data = []
            total_value = to_rubles(portfolio.total_amount_portfolio)
            
            for p in portfolio.positions:
                expected_yield_value = to_rubles(p.expected_yield) if p.expected_yield else 0
                current_price = to_rubles(p.current_price)
                if p.quantity is None or p.quantity.units == 0:
                    continue
                total_position_value = current_price * p.quantity.units
                data.append({
                    'Тикер/FIGI': p.figi,
                    'Тип': p.instrument_type,
                    'Кол-во': p.quantity.units,
                    'Цена (RUB)': f"{current_price:.2f}",
                    'Доходность (%)': f"{expected_yield_value / total_position_value * 100:.2f}" if total_position_value else "0.00"
                })

            df = pd.DataFrame(data)
            header = f"<b>💰 Портфель. Общая стоимость: {total_value:.2f} RUB</b>\n\n"
            
            if not df.empty:
                table_text = df.to_markdown(index=False, numalign="left", stralign="left")
                report = header + f"<pre>{table_text}</pre>"
            else:
                report = header + "Портфель пуст."

            return 200, report

    except RequestError as e:
        logger.error(f"Ошибка API Тинькофф: {e}")
        return 500, "⚠️ Ошибка связи с API Тинькофф."
    except Exception as e:
        logger.exception("Критическая ошибка при получении портфеля")
        return 500, f"⚠️ Неизвестная ошибка: {e}"

# --- 3. МАРШРУТЫ API ---

@app.route('/api/v1/portfolio', methods=['GET'])
def portfolio_api():
    """Отдает данные портфеля по HTTP-запросу."""
    status_code, report = get_tinkoff_portfolio_data()
    return jsonify({"report": report}), status_code

@app.route('/')
def index():
    return "✅ Агент-источник данных запущен.", 200

# --- 4. Запуск приложения ---
if __name__ == "__main__":
    port = int(os.environ.get("AGENT_PORT", 8000))
    # Запускаем на отдельном порту (например, 8000), не пересекаясь с основным ботом
    app.run(host="0.0.0.0", port=port)
