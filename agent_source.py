import os
import logging
import pandas as pd
from tinkoff.invest import Client, MoneyValue, PortfolioResponse
from tinkoff.invest.exceptions import RequestError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
if not TINKOFF_API_TOKEN:
    raise ValueError("❌ Не найден TINKOFF_API_TOKEN в окружении.")


def to_rubles(money: MoneyValue) -> float:
    """Конвертирует MoneyValue в float рублей."""
    return money.units + money.nano / 1_000_000_000


def get_portfolio() -> pd.DataFrame:
    """Возвращает DataFrame с портфелем Tinkoff."""
    try:
        with Client(TINKOFF_API_TOKEN) as client:
            accounts = client.users.get_accounts().accounts
            if not accounts:
                logger.warning("❌ Не найдено активных счетов.")
                return pd.DataFrame()

            account_id = accounts[0].id
            portfolio: PortfolioResponse = client.operations.get_portfolio(account_id=account_id)

            data = []
            for p in portfolio.positions:
                expected_yield_value = to_rubles(p.expected_yield) if p.expected_yield else 0
                current_price = to_rubles(p.current_price)
                if not p.quantity or p.quantity.units == 0:
                    continue
                total_position_value = current_price * p.quantity.units
                data.append({
                    'figi': p.figi,
                    'type': p.instrument_type,
                    'quantity': p.quantity.units,
                    'price_rub': round(current_price, 2),
                    'yield_percent': round((expected_yield_value / total_position_value * 100) if total_position_value else 0, 2)
                })
            return pd.DataFrame(data)

    except RequestError as e:
        logger.error(f"Ошибка Tinkoff API: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.exception("Критическая ошибка при получении портфеля")
        return pd.DataFrame()


if __name__ == "__main__":
    df = get_portfolio()
    if not df.empty:
        print(df)
    else:
        print("Портфель пуст или ошибка.")
