import asyncio
import os
import aiohttp
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from deep_translator import GoogleTranslator
from gtts import gTTS
from flask import Flask
from threading import Thread

# --- ADMIN VA BAZA SOZLAMALARI ---
ADMIN_ID = 858726164
db_name = "users.db"

def init_db():
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    # Bazaga 'full_name' va 'message_count' ustunlarini qo'shdik
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, 
                       full_name TEXT, 
                       message_count INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def add_or_update_user(user_id, full_name):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    # Foydalanuvchi bo'lsa ismini yangilaydi, bo'lmasa qo'shadi
    cursor.execute("INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?)", (user_id, full_name))
    cursor.execute("UPDATE users SET full_name = ? WHERE user_id = ?", (full_name, user_id))
    conn.commit()
    conn.close()

def increment_message(user_id):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET message_count = message_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_top_users():
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    # Eng ko'p xabar yuborgan 10 ta foydalanuvchini olish
    cursor.execute("SELECT user_id, full_name, message_count FROM users ORDER BY message_count DESC LIMIT 10")
    users = cursor.fetchall()
    conn.close()
    return users

init_db()

# --- SERVERNI UYG'OQ SAQLASH QISMI ---
app = Flask('')
@app.route('/')
def home(): return "Bot yoniq!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run).start()

# --- BOT SOZLAMALARI ---
API_TOKEN = '8326285649:AAGmU4yBIgxFvcWLBcDzE0MTh88inEM7Y1g'
CHANNEL_ID = "@speakingzoneway"
CHANNEL_URL = "https://t.me/speakingzoneway"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ASOSIY FUNKSIYALAR ---
async def check_sub_channels(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except: return False

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        top_users = get_top_users()
        text = "📊 **Top foydalanuvchilar (Xabarlar soni bo'yicha):**\n\n"
        
        for i, user in enumerate(top_users, 1):
            u_id, name, count = user
            text += f"{i}. {name} (ID: `{u_id}`) — **{count}** ta xabar\n"
        
        if not top_users:
            text = "Hozircha foydalanuvchilar yo'q."
            
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("Ruxsat yo'q! ❌")

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    add_or_update_user(message.from_user.id, message.from_user.full_name)
    
    if await check_sub_channels(message.from_user.id):
        await message.answer("Xush kelibsiz! Menga so'z yuboring. ✍️")
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Kanalga qo'shilish 📢", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="Obuna bo'ldim ✅", callback_data="sub_done")]
        ])
        await message.answer("Botdan foydalanish uchun kanalga a'zo bo'ling:", reply_markup=markup)

@dp.message(F.text)
async def translate_handler(message: types.Message):
    if not await check_sub_channels(message.from_user.id):
        return await start_handler(message)

    # Xabar yuborgani uchun hisoblagichni oshiramiz
    increment_message(message.from_user.id)
    add_or_update_user(message.from_user.id, message.from_user.full_name)

    msg_text = message.text.strip()
    status_msg = await message.answer("Tayyorlanmoqda... 📖")
    try:
        uz_tr = GoogleTranslator(source='en', target='uz').translate(msg_text)
        tts = gTTS(text=msg_text, lang='en')
        path = f"v_{message.from_user.id}.mp3"
        tts.save(path)
        
        caption = f"🇬🇧 **Text:** {msg_text}\n🇺🇿 **Tarjimasi:** {uz_tr}"
        await message.answer_voice(voice=FSInputFile(path), caption=caption, parse_mode="Markdown")
        await status_msg.delete()
        os.remove(path)
    except:
        await status_msg.edit_text("Xatolik.")

@dp.callback_query(F.data == "sub_done")
async def sub_callback(call: types.CallbackQuery):
    if await check_sub_channels(call.from_user.id):
        await call.message.delete()
        await bot.send_message(call.from_user.id, "Tayyor! 😊")
    else:
        await call.answer("A'zo bo'lmadingiz! ❌", show_alert=True)

async def main():
    init_db()
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())