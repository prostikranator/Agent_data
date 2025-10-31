# agent_source.py

import os
import json
from flask import Flask, jsonify, request
import pandas as pd
# 1. Корректный импорт клиента SyncClient
from tinvest import SyncClient
# 2. Корректный импорт исключения для обработки ошибок API (TinvestError)
from tinvest.exceptions import TinvestError 

# Получение токена из переменных окружения
# В Render это переменная среды TINKOFF_API_TOKEN
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
    """Получает портфель из Тинькофф Инвестиций и возвращает его в виде JSON-строки."""
    # Проверка наличия токена
    if not TINKOFF_API_TOKEN:
        return {"error": "TINKOFF_API_TOKEN не установлен. Проверьте переменные окружения."}, 500

    try:
        # Инициализация синхронного клиента
        client = SyncClient(TINKOFF_API_TOKEN)
        
        # Получаем список счетов (нужен ID счета)
        accounts = client.get_accounts().payload.accounts
        if not accounts:
            return {"error": "Нет доступных счетов в Тинькофф для этого токена."}, 500
            
        # Используем ID первого счета
        account_id = accounts[0].broker_account_id
        
        # Получаем портфель
        portfolio_response = client.get_portfolio(account_id=account_id).payload
        
        positions = []
        for position in portfolio_response.positions:
            # Обработка MoneyValue: извлекаем значение и валюту
            current_price = position.average_position_price.value 
            currency = position.average_position_price.currency
            
            positions.append({
                "ticker": position.ticker,
                "figi": position.figi,
                "name": position.name,
                "balance": float(position.balance), # Преобразование в float для удобства
                "currency": currency,
                "price": float(current_price),
            })
        
        # Преобразование списка позиций в DataFrame и затем в JSON
        df = pd.DataFrame(positions)
        
        return df.to_json(orient="records"), 200

    # Обработка ошибок, связанных с Тинькофф API (TinvestError)
    except TinvestError as e: 
        error_msg = f"Ошибка API Тинькофф (Tinvest): {e}"
        app.logger.error(error_msg)
        return {"error": error_msg}, 500
        
    # Обработка любых других непредвиденных ошибок
    except Exception as e:
        error_msg = f"Неизвестная ошибка при получении портфеля: {e}"
        app.logger.error(error_msg)
        return {"error": error_msg}, 500

# Блок для запуска через Gunicorn на Render
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # В реальной среде Render это запускается через Gunicorn, а не этот блок
    app.run(host='0.0.0.0', port=port)
