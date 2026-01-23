import asyncio
import os
import aiohttp
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from deep_translator import GoogleTranslator
from gtts import gTTS
from flask import Flask
from threading import Thread

# --- SERVERNI UYG'OQ SAQLASH QISMI (FLASK) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot yoniq va ishlamoqda!"

def run():
    # Render beradigan portni avtomatik oladi yoki 8080 ishlatadi
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- BOT SOZLAMALARI ---
API_TOKEN = '8526236810:AAEzr3_sW4x2gMIFtIDLRQ9y7yTvWu56tUc'
CHANNEL_ID = "@speakingzoneway" 
CHANNEL_URL = "https://t.me/speakingzoneway" 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- O'Z-O'ZINI UYG'OTISH (SELF-PING) ---
async def self_ping():
    """Botni har 10 daqiqada uyg'otib turadi"""
    while True:
        await asyncio.sleep(600)  # 10 daqiqa kutish
        try:
            async with aiohttp.ClientSession() as session:
                # PASTDAGI MANZILNI O'ZINGIZNIKI BILAN ALMASHTIRING
                my_url = "https://uycieyfiuuwywofwheiuifweifkjsdsdbjdsuiyw-hgeg-kdakhda-1.onrender.com"
                async with session.get(my_url) as resp:
                    logging.info(f"O'z-o'zini uyg'otdi, status: {resp.status}")
        except Exception as e:
            logging.error(f"Ping xatosi: {e}")

# --- ASOSIY FUNKSIYALAR ---
async def get_english_definition(text):
    words = text.split()
    word_to_search = max(words, key=len) if len(words) > 1 else text
    async with aiohttp.ClientSession() as session:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word_to_search}"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                try:
                    meanings = data[0]['meanings'][0]
                    pos = meanings['partOfSpeech']
                    definition = meanings['definitions'][0]['definition']
                    return f"🔹 *{pos.capitalize()}*: {definition}"
                except: return None
            return None

async def check_sub_channels(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Obuna xatosi: {e}")
        return False

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    if await check_sub_channels(message.from_user.id):
        await message.answer("Xush kelibsiz! Menga inglizcha so'z yoki gap yuboring. ✍️")
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Kanalga qo'shilish 📢", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="Obuna bo'ldim ✅", callback_data="sub_done")]
        ])
        await message.answer("Botdan foydalanish uchun kanalga a'zo bo'ling:", reply_markup=markup)

@dp.message(F.text)
async def translate_handler(message: types.Message):
    if not await check_sub_channels(message.from_user.id):
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Kanalga qo'shilish 📢", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="Obuna bo'ldim ✅", callback_data="sub_done")]
        ])
        return await message.answer("Avval kanalga a'zo bo'ling:", reply_markup=markup)

    msg_text = message.text.strip()
    status_msg = await message.answer("Ma'lumotlar tayyorlanmoqda... 📖")
    try:
        uz_tr = GoogleTranslator(source='en', target='uz').translate(msg_text)
        en_def = await get_english_definition(msg_text)
        tts = gTTS(text=msg_text, lang='en')
        path = f"v_{message.from_user.id}.mp3"
        tts.save(path)
        caption = (f"🇬🇧 **Text:** {msg_text}\n"
                   f"🇺🇿 **Tarjimasi:** {uz_tr}\n\n"
                   f"📖 **English Explanation:**\n"
                   f"{en_def if en_def else '_Batafsil tushuntirish topilmadi._'}")
        await message.answer_voice(voice=FSInputFile(path), caption=caption, parse_mode="Markdown")
        await status_msg.delete()
        os.remove(path)
    except Exception as e:
        logging.error(f"Xatolik: {e}")
        await status_msg.edit_text("Kechirasiz, xatolik yuz berdi.")

@dp.callback_query(F.data == "sub_done")
async def sub_callback(call: types.CallbackQuery):
    if await check_sub_channels(call.from_user.id):
        await call.message.delete()
        await bot.send_message(call.from_user.id, "Rahmat! Endi foydalanishingiz mumkin. 😊")
    else:
        await call.answer("Siz hali a'zo bo'lmadingiz! ❌", show_alert=True)

async def main():
    # O'z-o'zini uyg'otish vazifasini ishga tushirish
    asyncio.create_task(self_ping())
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()  
    asyncio.run(main())
    
    