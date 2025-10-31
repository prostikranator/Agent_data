# agent_source.py

import os
import json
from flask import Flask, jsonify
import pandas as pd
# ИСПОЛЬЗУЕМ НОВЫЙ SDK
from tinkoff.invest import Client, RequestError
from tinkoff.invest.constants import ACCOUNT_TYPE_TINKOFF

# Получение токена из переменных окружения
# ПРИМЕЧАНИЕ: новый SDK использует токены НОВОГО ОБРАЗЦА (должны работать и старые, но лучше создать новый ReadOnly)
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
    """Обрабатывает HTTP-запрос и возвращает данные портфеля в формате JSON."""
    data, status_code = get_portfolio()
    
    # Если статус 200 (успех), возвращаем JSON-строку
    if status_code == 200:
        return data, status_code, {'Content-Type': 'application/json'}
        
    # Если ошибка, возвращаем JSON-словарь с кодом ошибки
    return jsonify(data), status_code

def get_portfolio():
    """Получает портфель из Тинькофф Инвестиций, используя новый SDK."""
    if not TINKOFF_API_TOKEN:
        return {"error": "TINKOFF_API_TOKEN не установлен. Проверьте переменные окружения."}, 500

    try:
        # Инициализация клиента НОВОГО SDK
        # Client использует контекстный менеджер (with), что является лучшей практикой
        with Client(TINKOFF_API_TOKEN) as client:
            
            # 1. Получаем список счетов
            accounts_response = client.users.get_accounts()
            accounts = accounts_response.accounts
            
            # Отфильтруем счета (например, оставим только брокерские счета Тинькофф)
            tinkoff_accounts = [acc for acc in accounts if acc.type == ACCOUNT_TYPE_TINKOFF]
            
            if not tinkoff_accounts:
                return {"error": "Нет доступных брокерских счетов Тинькофф для этого токена."}, 500
                
            # Используем ID первого счета
            account_id = tinkoff_accounts[0].id
            
            # 2. Получаем портфель
            portfolio_response = client.operations.get_portfolio(account_id=account_id)
            
            positions = []
            for position in portfolio_response.positions:
                
                # В новом SDK данные о цене хранятся в формате Quotation (единицы и нано)
                # Переводим в float для удобства
                def quotation_to_float(quotation):
                    return quotation.units + quotation.nano / 10**9

                current_price = quotation_to_float(position.average_position_price)
                
                positions.append({
                    "ticker": position.ticker,
                    "figi": position.figi,
                    "name": position.name,
                    "balance": quotation_to_float(position.quantity), # Баланс теперь в quantity
                    "currency": position.average_position_price.currency,
                    "price": float(current_price),
                })
            
            # Преобразование списка позиций в DataFrame и затем в JSON
            df = pd.DataFrame(positions)
            
            return df.to_json(orient="records"), 200

    # Обработка ошибок, связанных с НОВЫМ API (RequestError)
    except RequestError as e: 
        error_msg = f"Ошибка API Тинькофф (RequestError): {e.metadata.message if e.metadata else e}"
        app.logger.error(error_msg)
        return {"error": error_msg}, 500
        
    # Обработка любых других непредвиденных ошибок (например, если pandas не может обработать данные)
    except Exception as e:
        error_msg = f"Неизвестная ошибка при получении портфеля: {e}"
        app.logger.error(error_msg)
        return {"error": error_msg}, 500

# Блок для запуска через Gunicorn на Render
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
    
