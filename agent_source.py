# agent_source.py

import os
import logging
import pandas as pd
from tinkoff.invest import Client, MoneyValue, PortfolioResponse
from tinkoff.invest.exceptions import RequestError

# --- 1. Настройка логирования и переменных ---
logger = logging.getLogger(__name__)

# Токен API Тинькофф берется из переменных окружения
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")

if not TINKOFF_API_TOKEN:
    logger.warning("⚠️ Переменная TINKOFF_API_TOKEN не найдена. Функции Тинькофф будут недоступны.")

# --- 2. ФУНКЦИИ АГЕНТА ИСТОЧНИКА ---

def to_rubles(money: MoneyValue) -> float:
    """Конвертирует MoneyValue в float рублей."""
    return money.units + money.nano / 1_000_000_000

def get_tinkoff_portfolio() -> str:
    """
    Получает данные портфеля из Тинькофф Инвестиций и форматирует их в таблицу.
    
    :return: Отформатированная HTML-строка с данными портфеля или сообщение об ошибке.
    """
    if not TINKOFF_API_TOKEN:
        return "❌ Не удалось получить портфель: TINKOFF_API_TOKEN не задан."
        
    try:
        with Client(TINKOFF_API_TOKEN) as client:
            accounts = client.users.get_accounts().accounts
            if not accounts:
                return "❌ Не найдено активных счетов в Тинькофф."
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
                return header + f"<pre>{table_text}</pre>"
            else:
                return header + "Портфель пуст."

    except RequestError as e:
        logger.error(f"Ошибка API Тинькофф: {e}")
        return "⚠️ Ошибка связи с API Тинькофф."
    except Exception as e:
        logger.exception("Критическая ошибка при получении портфеля")
        return f"⚠️ Неизвестная ошибка: {e}"
