import json
import os
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime

# Конфигурация API
BOT_TOKEN = "8985673345:AAGF7pVhdDHbtdbNRg9dQisOkreiH2k9_X8"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

JSONBIN_KEY = "$2a$10$h2.ZCOXCrlmH5Z/e9ZaITe2GXKqFxAm8W.QJenqhljsvB6CvR8gF."
BIN_ID = "6ada83a1ffd5d1605383e9a6"
JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"

GEMINI_API_KEY = "AQ.Ab8RN6KWSNvZ2_05FBIGpgXDnQV7TdwcxeRxD1NEZkB7NsQTag"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={GEMINI_API_KEY}"

def http_request(url, method="GET", headers=None, data=None):
    if headers is None:
        headers = {}
    encoded_data = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"HTTP Error [{method} {url[:40]}...]: {e}")
        return None

def get_cloud_db():
    headers = {"X-Master-Key": JSONBIN_KEY}
    res = http_request(f"{JSONBIN_URL}/latest", method="GET", headers=headers)
    if res and "record" in res:
        return res["record"]
    return {"user": {}, "weight_history": [], "days": {}}

def update_cloud_db(data):
    headers = {
        "Content-Type": "application/json",
        "X-Master-Key": JSONBIN_KEY
    }
    return http_request(JSONBIN_URL, method="PUT", headers=headers, data=data)

def ask_gemini_nutrition(text):
    prompt = f"""
Ты — профессиональный ИИ-диетолог. Пользователь описывает, что он съел (или спрашивает совет).
Текст пользователя: "{text}"

Твоя задача — проанализировать блюдо(а), оценить примерный вес порций, если вес не указан, и вернуть СТРОГО валидный JSON следующего формата:
{{
  "is_meal": true,
  "summary": "Краткое понятное название блюда/перекуса",
  "calories": 450,
  "protein": 35.0,
  "fats": 12.0,
  "carbs": 48.0,
  "breakdown": [
    "Куриное филе (~150г): 247 ккал (Б: 46г, Ж: 5г, У: 0г)",
    "Гречка отварная (~120г): 140 ккал (Б: 5г, Ж: 2г, У: 28г)"
  ],
  "comment": "Короткий дружеский комментарий или совет (1 предложение)"
}}

Если текст НЕ про еду (например, просто приветствие или вопрос), верни:
{{
  "is_meal": false,
  "reply": "Твой ответ на вопрос пользователя"
}}

Не добавляй никакого markdown вроде ```json, только чистый JSON.
"""
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}
    res = http_request(GEMINI_URL, method="POST", headers=headers, data=body)
    try:
        if res and "candidates" in res:
            raw_text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
                raw_text = re.sub(r"\n?```$", "", raw_text)
            return json.loads(raw_text)
    except Exception as e:
        print(f"Gemini parse error: {e}")
    return None

def send_telegram(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    return http_request(url, method="POST", headers={"Content-Type": "application/json"}, data=payload)

def handle_update(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    if not text:
        return

    text_lower = text.lower()
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    db = get_cloud_db()

    if text_lower in ["/start", "/help", "старт"]:
        msg = (
            "🔥 <b>Привет! Я твой облачный AI-диетолог на базе Gemini & JSONBin.</b>\n\n"
            "Все данные сохраняются <b>в облаке 24/7</b>. Ты можешь писать мне на ходу с телефона!\n\n"
            "<b>Что можно отправлять:</b>\n"
            "• <b>Любую еду:</b> <i>«2 яйца, черных хлеб 40г, латте»</i>\n"
            "• <b>Вес:</b> <i>«вес 82.5»</i>\n"
            "• <b>Талия:</b> <i>«талия 90.5»</i>\n"
            "• <b>Итог:</b> /today или <i>«баланс»</i>\n"
            "• <b>Совет:</b> <i>«что съесть во ВкусВилле на 400 ккал?»</i>"
        )
        send_telegram(chat_id, msg)
        return

    weight_match = re.search(r"(?:вес|weight|^)\s*(\d{2,3}(?:[.,]\d{1,2})?)\s*(?:кг|kg)?$", text_lower)
    if "вес" in text_lower or (weight_match and float(weight_match.group(1).replace(",", ".")) > 50):
        val_str = weight_match.group(1).replace(",", ".") if weight_match else re.search(r"\d{2,3}(?:[.,]\d{1,2})?", text_lower).group(0).replace(",", ".")
        weight = float(val_str)
        prev_weight = db.get("user", {}).get("current_weight_kg", weight)
        diff = round(weight - prev_weight, 2)
        diff_str = f"({diff:+} кг)" if diff != 0 else "(без изменений)"
        
        db.setdefault("user", {})["current_weight_kg"] = weight
        db.setdefault("weight_history", []).append({
            "date": today_str,
            "weight_kg": weight,
            "time": now_time
        })
        update_cloud_db(db)
        
        start_weight = db.get("user", {}).get("start_weight_kg", 89.0)
        total_lost = round(start_weight - weight, 2)
        reply = (
            f"⚖️ <b>Вес сохранен в облако: {weight} кг {diff_str}</b>\n\n"
            f"📉 Всего сброшено с 15 сентября: <b>−{total_lost} кг</b>!\n"
            f"🎯 Цель: {db.get('user', {}).get('target_weight_kg', 76.0)} кг (осталось {round(weight - 76.0, 2)} кг)"
        )
        send_telegram(chat_id, reply)
        return

    if "талия" in text_lower or "талию" in text_lower:
        m = re.search(r"(\d{2,3}(?:[.,]\d)?)", text_lower)
        if m:
            waist = float(m.group(1).replace(",", "."))
            db.setdefault("user", {})["current_waist_cm"] = waist
            update_cloud_db(db)
            start_waist = db.get("user", {}).get("start_waist_cm", 96.0)
            send_telegram(chat_id, f"📏 <b>Талия сохранена в облако: {waist} см</b>\nС начала похудения ушло: <b>−{round(start_waist - waist, 1)} см</b>! 🔥")
            return

    if text_lower in ["/today", "/status", "итог", "баланс", "сегодня", "статус"]:
        day_data = db.setdefault("days", {}).setdefault(today_str, {"meals": [], "totals": {"calories": 0, "protein": 0, "fats": 0, "carbs": 0}})
        totals = day_data.get("totals", {})
        cals = totals.get("calories", 0)
        p = totals.get("protein", 0)
        f = totals.get("fats", 0)
        c = totals.get("carbs", 0)
        target = db.get("user", {}).get("recommended_calorie_target", 1850)
        rem = max(0, round(target - cals, 1))

        meals_txt = ""
        for m in day_data.get("meals", []):
            meals_txt += f"• <i>{m.get('time', '')}</i> — {m.get('title', '')} ({m.get('calories', 0)} ккал)\n"

        reply = (
            f"📊 <b>Итог на сегодня ({today_str}) из облака:</b>\n\n"
            f"🔥 Съедено: <b>{cals:.1f}</b> / {target} ккал\n"
            f"🟢 <b>Осталось до нормы:</b> {rem:.1f} ккал\n\n"
            f"🍗 Белки: <b>{p:.1f}г</b> / 140г\n"
            f"🥑 Жиры: <b>{f:.1f}г</b> / 55г\n"
            f"🍚 Углеводы: <b>{c:.1f}г</b> / 190г\n\n"
            f"🍽 <b>Приемы пищи:</b>\n{meals_txt if meals_txt else 'Пока пусто'}"
        )
        send_telegram(chat_id, reply)
        return

    ai_res = ask_gemini_nutrition(text)
    if ai_res and ai_res.get("is_meal"):
        cals = ai_res.get("calories", 0)
        p = ai_res.get("protein", 0)
        f = ai_res.get("fats", 0)
        c = ai_res.get("carbs", 0)
        summary = ai_res.get("summary", text)
        breakdown = ai_res.get("breakdown", [])
        comment = ai_res.get("comment", "")

        day_data = db.setdefault("days", {}).setdefault(today_str, {"meals": [], "totals": {"calories": 0, "protein": 0, "fats": 0, "carbs": 0}})
        day_data["meals"].append({
            "id": str(len(day_data["meals"]) + 1),
            "time": now_time,
            "title": summary,
            "calories": cals,
            "protein": p,
            "fats": f,
            "carbs": c
        })

        day_data["totals"]["calories"] = round(sum(m["calories"] for m in day_data["meals"]), 1)
        day_data["totals"]["protein"] = round(sum(m["protein"] for m in day_data["meals"]), 1)
        day_data["totals"]["fats"] = round(sum(m["fats"] for m in day_data["meals"]), 1)
        day_data["totals"]["carbs"] = round(sum(m["carbs"] for m in day_data["meals"]), 1)
        
        update_cloud_db(db)

        target = db.get("user", {}).get("recommended_calorie_target", 1850)
        today_total = day_data["totals"]["calories"]
        rem = max(0, round(target - today_total, 1))

        breakdown_str = "\n".join([f"  • {item}" for item in breakdown]) if breakdown else ""
        
        reply = (
            f"🧠 <b>Gemini посчитал и сохранил в JSONBin:</b>\n"
            f"<b>{summary}</b>\n"
            f"{breakdown_str}\n\n"
            f"🔥 <b>+{cals} ккал</b> (Б: {p}г | Ж: {f}г | У: {c}г)\n"
            f"━━━━━━━━━━━━━━\n"
            f"📈 <b>Итого за день:</b> {today_total:.1f} / {target} ккал\n"
            f"🟢 <b>Осталось до нормы:</b> {rem:.1f} ккал\n"
            f"🍗 Белок сегодня: <b>{day_data['totals']['protein']:.1f}г</b> / 140г\n\n"
            f"<i>💡 {comment}</i>"
        )
        send_telegram(chat_id, reply)
    elif ai_res and not ai_res.get("is_meal"):
        send_telegram(chat_id, ai_res.get("reply", "Понял тебя!"))
    else:
        send_telegram(chat_id, "Записал, но не удалось точно посчитать КБЖУ. Напиши подробнее!")

def main():
    print("Cloud-connected Gemini Diet Bot started...")
    last_update_id = 0
    while True:
        try:
            updates = http_request(f"{TELEGRAM_API_URL}/getUpdates?offset={last_update_id + 1}&timeout=20")
            if updates and updates.get("ok"):
                for item in updates.get("result", []):
                    last_update_id = item["update_id"]
                    if "message" in item:
                        handle_update(item["message"])
        except Exception as e:
            print(f"Polling loop: {e}")
            time.sleep(3)
        time.sleep(1)

if __name__ == "__main__":
    main()
