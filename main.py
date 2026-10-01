import os
import asyncio
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Переменные окружения из настроек хостинга
BOT_TOKEN = os.getenv("EMPLOYEE_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
WORK_START_TIME = os.getenv("WORK_START_TIME", "09:00")
WORK_END_TIME = os.getenv("WORK_END_TIME", "18:00")

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("❌ Ошибка: Не заданы EMPLOYEE_BOT_TOKEN или ADMIN_ID в переменных окружения!")

ADMIN_ID = int(ADMIN_ID)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            full_name TEXT,
            date TEXT,
            check_in_time TEXT,
            check_out_time TEXT,
            lateness_minutes INTEGER DEFAULT 0,
            early_leave_minutes INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# Клавиатура сотрудника
employee_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📍 Пришел на смену"),
            KeyboardButton(text="🏁 Ушел со смены")
        ]
    ],
    resize_keyboard=True
)

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
        f"⏰ **График работы:** с {WORK_START_TIME} до {WORK_END_TIME}.\n"
        "Используйте кнопки ниже, чтобы отмечать начало и конец вашей смены.",
        reply_markup=employee_kb,
        parse_mode="Markdown"
    )

@dp.message(F.text == "📍 Пришел на смену")
async def check_in(message: types.Message):
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM attendance WHERE user_id = ? AND date = ?", (message.from_user.id, today_str))
    if cursor.fetchone():
        await message.answer("⚠️ Вы уже отметились о приходе сегодня!")
        conn.close()
        return

    start_hour, start_minute = map(int, WORK_START_TIME.split(":"))
    shift_start = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    
    lateness = 0
    if now > shift_start:
        lateness = int((now - shift_start).total_seconds() // 60)

    user_name = message.from_user.full_name
    cursor.execute(
        "INSERT INTO attendance (user_id, full_name, date, check_in_time, lateness_minutes) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, user_name, today_str, time_str, lateness)
    )
    conn.commit()
    conn.close()

    status_text = f"⚠️ Опоздание: {lateness} мин." if lateness > 0 else "Вы пришли вовремя!"
    await message.answer(f"✅ Приход зафиксирован в {time_str}.\n{status_text}")

    admin_msg = (
        f"🟢 **Сотрудник ПРИШЕЛ на смену**\n\n"
        f"👤 {user_name}\n"
        f"⏰ Время: {time_str}\n"
        f"📊 Статус: {f'🔴 Опоздание {lateness} мин' if lateness > 0 else '🟢 Вовремя'}"
    )
    await bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")

@dp.message(F.text == "🏁 Ушел со смены")
async def check_out(message: types.Message):
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, check_out_time FROM attendance WHERE user_id = ? AND date = ?", (message.from_user.id, today_str))
    record = cursor.fetchone()

    if not record:
        await message.answer("⚠️ Вы еще не отмечали приход на смену сегодня!")
        conn.close()
        return

    if record[1] is not None:
        await message.answer("⚠️ Вы уже отметили завершение смены сегодня!")
        conn.close()
        return

    end_hour, end_minute = map(int, WORK_END_TIME.split(":"))
    shift_end = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    
    early_leave = 0
    if now < shift_end:
        early_leave = int((shift_end - now).total_seconds() // 60)

    cursor.execute(
        "UPDATE attendance SET check_out_time = ?, early_leave_minutes = ? WHERE id = ?",
        (time_str, early_leave, record[0])
    )
    conn.commit()
    conn.close()

    status_text = f"⚠️ Уход раньше на: {early_leave} мин." if early_leave > 0 else "Отличная работа, смена окончена!"
    await message.answer(f"✅ Уход зафиксирован в {time_str}.\n{status_text}")

    user_name = message.from_user.full_name
    admin_msg = (
        f"🔴 **Сотрудник УШЕЛ со смены**\n\n"
        f"👤 {user_name}\n"
        f"⏰ Время ухода: {time_str}\n"
        f"📊 Статус: {f'🟠 Ушел раньше на {early_leave} мин' if early_leave > 0 else '🟢 Смена полностью отработана'}"
    )
    await bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")

@dp.message(Command("report"))
async def get_report(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет доступа к административной панели.")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT full_name, check_in_time, check_out_time, lateness_minutes, early_leave_minutes FROM attendance WHERE date = ?", 
        (today_str,)
    )
    records = cursor.fetchall()
    conn.close()

    if not records:
        await message.answer(f"📊 **Отчет за {today_str}:**\nСегодня еще никто не отмечался.", parse_mode="Markdown")
        return

    report = f"📊 **Отчет по смене за {today_str}:**\n\n"
    for name, in_time, out_time, late, early in records:
        in_info = f"{in_time} (Опоздание: {late} мин)" if late > 0 else f"{in_time} (Вовремя)"
        out_info = f"{out_time}" if out_time else "Еще на смене"
        if early > 0:
            out_info += f" (Раньше на {early} мин)"

        report += f"👤 **{name}**\n   ├ Приход: {in_info}\n   └ Уход: {out_info}\n\n"

    await message.answer(report, parse_mode="Markdown")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
