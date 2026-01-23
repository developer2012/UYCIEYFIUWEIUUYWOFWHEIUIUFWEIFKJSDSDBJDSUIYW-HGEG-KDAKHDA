import asyncio
import os
import aiohttp
import logging
import sqlite3 # Ma'lumotlar bazasi uchun
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from deep_translator import GoogleTranslator
from gtts import gTTS
from flask import Flask
from threading import Thread

# --- ADMIN VA BAZA SOZLAMALARI ---
ADMIN_ID = 858726164  # Sizning ID raqamingiz
db_name = "users.db"

# Ma'lumotlar bazasini sozlash
def init_db():
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def count_users():
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

init_db()

# --- SERVERNI UYG'OQ SAQLASH QISMI (FLASK) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot yoniq va ishlamoqda!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- BOT SOZLAMALARI ---
API_TOKEN = '7709778975:AAFHt5MrrafItyIojVAnlgJuZM7shFxdEUA'
CHANNEL_ID = "@speakingzoneway" 
CHANNEL_URL = "https://t.me/speakingzoneway" 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- O'Z-O'ZINI UYG'OTISH (SELF-PING) ---
async def self_ping():
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as session:
                my_url = "https://uycieyfiuuwywofwheiuifweifkjsdsdbjds-1cg7.onrender.com"
                async with session.get(my_url) as resp:
                    logging.info(f"Ping yuborildi: {resp.status}")
        except Exception as e:
            logging.error(f"Ping xatosi: {e}")

# --- ASOSIY FUNKSIYALAR ---
async def check_sub_channels(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Obuna xatosi: {e}")
        return False

# FAQAT ADMIN UCHUN ADMIN PANEL
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        total = count_users()
        await message.answer(f"📊 **Admin Panel**\n\n👤 Jami foydalanuvchilar: {total} ta\n✅ Bot holati: Faol")
    else:
        # Boshqalar yozsa bot javob bermaydi yoki rad etadi
        await message.answer("Kechirasiz, bu buyruq faqat bot egasi uchun! ❌")

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    add_user(message.from_user.id) # Bazaga qo'shish
    user_num = count_users() # Nechanchi foydalanuvchi ekanini bilish
    
    if await check_sub_channels(message.from_user.id):
        await message.answer(f"Xush kelibsiz!  ✍️")
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Kanalga qo'shilish 📢", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="Obuna bo'ldim ✅", callback_data="sub_done")]
        ])
        await message.answer(f" Botdan foydalanish uchun kanalga a'zo bo'ling:", reply_markup=markup)

@dp.message(F.text)
async def translate_handler(message: types.Message):
    if not await check_sub_channels(message.from_user.id):
        return await start_handler(message)

    msg_text = message.text.strip()
    status_msg = await message.answer("Ma'lumotlar tayyorlanmoqda... 📖")
    try:
        uz_tr = GoogleTranslator(source='en', target='uz').translate(msg_text)
        tts = gTTS(text=msg_text, lang='en')
        path = f"v_{message.from_user.id}.mp3"
        tts.save(path)
        
        caption = f"🇬🇧 **Text:** {msg_text}\n🇺🇿 **Tarjimasi:** {uz_tr}"
        await message.answer_voice(voice=FSInputFile(path), caption=caption, parse_mode="Markdown")
        await status_msg.delete()
        os.remove(path)
    except Exception as e:
        await status_msg.edit_text("Xatolik yuz berdi.")

@dp.callback_query(F.data == "sub_done")
async def sub_callback(call: types.CallbackQuery):
    if await check_sub_channels(call.from_user.id):
        await call.message.delete()
        await bot.send_message(call.from_user.id, "Rahmat! Endi foydalanishingiz mumkin. 😊")
    else:
        await call.answer("Siz hali a'zo bo'lmadingiz! ❌", show_alert=True)

async def main():
    asyncio.create_task(self_ping())
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()  
    asyncio.run(main())
