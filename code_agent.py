# code_agent.py

import os
import uuid
import logging
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException
import httpx
from pydantic import BaseModel
from supabase import create_client, Client


SUPABASE_URL = os.getenv("SUPABASE_URL")  # 👈 добавь
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")  # 👈 добавь
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)  # 👈 добавь


# === Настройка ===
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
AGENT_TYPE = "code"
BOT_CONTACT = "@Freelance_mvp_bot"  # Замени на реальный Telegram
ALLOWED_KEYWORDS = ["бот", "скрипт", "сайт", "парсинг", "scraper", "api", "telegram", "chrome", "python"]

# === Логирование ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("code_agent")

# === Хранилище дублей (в памяти)
processed_ids = set()

# === Инициализация FastAPI ===
app = FastAPI()

# === Модель входящего заказа ===
class Order(BaseModel):
    id: str
    title: str
    link: str = ""
    description: str
    contact: str = ""


# === Хелпер: Проверка на ключевые слова ===
def is_relevant_task(text: str) -> bool:
    text = text.lower()
    return any(keyword in text for keyword in ALLOWED_KEYWORDS)


# === Хелпер: Генерация ответа через OpenRouter ===
async def generate_response_via_openrouter(description: str) -> str:
    try:
        system_prompt = "Ты программист-фрилансер. Пиши вежливо, уверенно. Предложи сделать задачу, укажи контакт."
        user_prompt = f"Есть задача: {description}. Сгенерируй короткий отклик от разработчика."

        payload = {
            "model": "openchat/openchat-7b",  # Можно заменить на нужную модель
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=30)

        if response.status_code == 200:
            reply = response.json()
            return reply["choices"][0]["message"]["content"]
        else:
            logger.warning(f"OpenRouter error {response.status_code}: {response.text}")
            return f"Здравствуйте! Ознакомился с заданием. Готов выполнить. Мой Telegram: {BOT_CONTACT}"

    except Exception as e:
        logger.error(f"LLM error: {e}")
        return f"Здравствуйте! Ознакомился с заданием. Готов выполнить. Мой Telegram: {BOT_CONTACT}"


# === Эндпоинт приёма заказа ===
@app.post("/handle_order")
async def handle_order(order: Order) -> Dict[str, Any]:
    logger.info(f"Получен заказ: {order.id} — {order.title}")

    # Проверка в Supabase на наличие отклика
    try:
        existing = supabase.table("orders").select("response").eq("id", order.id).execute()
        if existing.data and existing.data[0].get("response"):
            logger.info(f"Повторный заказ (уже есть ответ) в Supabase: {order.id}")
            return {"status": "duplicate", "response": ""}
    except Exception as e:
        logger.error(f"Ошибка при проверке дубля в Supabase: {e}")

    # Фильтрация
    if not is_relevant_task(order.title + " " + order.description):
        logger.info(f"Неподходящее задание: {order.title}")
        return {"status": "irrelevant", "response": ""}

    # Генерация отклика
    reply = await generate_response_via_openrouter(order.description)
    
    # Сохраняем отклик в Supabase
    try:
        supabase.table("orders").update({
            "response": reply,
            "status": "replied"
        }).eq("id", order.id).execute()
        logger.info(f"Отклик сохранён в Supabase для заказа {order.id}")
    except Exception as e:
        logger.warning(f"Не удалось сохранить отклик в Supabase: {e}")

    processed_ids.add(order.id)

    logger.info(f"Сгенерирован отклик для {order.id}")
    return {
        "status": "ok",
        "agent": AGENT_TYPE,
        "response": reply
    }


# === Пинг для проверки ===
@app.get("/ping")
async def ping():
    return {"status": "alive", "agent": AGENT_TYPE}
