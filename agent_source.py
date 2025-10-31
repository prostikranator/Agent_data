import os
import json
from flask import Flask, jsonify, request
import pandas as pd
# Используем новую, рабочую библиотеку tinvest
from tinvest import SyncClient
# 2. Корректный импорт исключения
from tinvest.exceptions import TinvestApiError 

# Получение токена из переменных окружения
# В Render это устанавливается в разделе Environment
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")

app = Flask(__name__)

# --- Маршрут для проверки работоспособности (Health Check) ---
@app.route('/', methods=['GET'])
def health_check():
    """Проверка, что сервер запущен."""
    return "Agent Data Source is running!", 200

# --- Маршрут для получения портфеля ---
@app.route('/portfolio', methods=['GET'])
def portfolio_route():
    """Обрабатывает HTTP-запрос и возвращает данные портфеля."""
    data, status_code = get_portfolio()
    # Если данные возвращаются как строка (JSON), то возвращаем ее,
    # иначе jsonify для словаря ошибки.
    if status_code == 200:
        return data, status_code, {'Content-Type': 'application/json'}
    return jsonify(data), status_code

def get_portfolio():
    """Получает портфель и возвращает его в виде JSON-строки."""
    if not TINKOFF_API_TOKEN:
        # Если токен не установлен, возвращаем ошибку
        return {"error": "TINKOFF_API_TOKEN не установлен. Проверьте переменные окружения."}, 500

    try:
        # 1. Инициализация клиента tinvest
        client = SyncClient(TINKOFF_API_TOKEN)
        
        # 2. Получаем список счетов
        # Нам нужен ID счета для запроса портфеля
        accounts = client.get_accounts().payload.accounts
        if not accounts:
            return {"error": "Нет доступных счетов в Тинькофф для этого токена."}, 500
            
        # Берем первый счет, предполагая, что он основной
        account_id = accounts[0].broker_account_id
        
        # 3. Получаем портфель
        portfolio_response = client.get_portfolio(account_id=account_id).payload
        
        positions = []
        for position in portfolio_response.positions:
            # Преобразование данных для удобства: 
            # используем .value и .currency из объекта MoneyValue
            current_price = position.average_position_price.value 
            currency = position.average_position_price.currency
            
            positions.append({
                "ticker": position.ticker,
                "figi": position.figi,
                "name": position.name,
                "balance": float(position.balance), # Преобразуем для корректной работы с Pandas
                "currency": currency,
                "price": float(current_price),
            })
        
        # 4. Преобразование в DataFrame и JSON
        df = pd.DataFrame(positions)
        
        # Возвращаем результат в формате JSON
        return df.to_json(orient="records"), 200

    # Обработка специфических ошибок API
    except TinvestApiError as e: 
        error_msg = f"Ошибка API Тинькофф (Tinvest): {e.response.text}"
        app.logger.error(error_msg)
        return {"error": error_msg}, 500
    # Обработка любых других ошибок
    except Exception as e:
        error_msg = f"Неизвестная ошибка при получении портфеля: {e}"
        app.logger.error(error_msg)
        return {"error": error_msg}, 500

# Этот блок важен для запуска локально, но Render использует Gunicorn
if __name__ == '__main__':
    # На Render порт задается через env переменную PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
