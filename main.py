import os
import re
import json
import asyncio
import tempfile
import random
from typing import List, Dict, Tuple, Optional
from threading import Thread

import requests
from flask import Flask
from pydub import AudioSegment

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    FSInputFile
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


# ======================
# CONFIG
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8326285649:AAGmU4yBIgxFvcWLBcDzE0MTh88inEM7Y1g").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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").strip()

CHANNEL_USERNAME = "@speakingzoneway"
CHANNEL_URL = "https://t.me/speakingzoneway"

PORT = int(os.getenv("PORT", "10000"))

GROQ_BASE = "https://api.groq.com/openai/v1"

# Model fallback (decommission bo‘lsa keyingisiga o‘tadi)
GROQ_CHAT_MODELS = [
    os.getenv("GROQ_CHAT_MODEL", "").strip() or "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
]

ADMIN_IDS = {858726164, 1593591147}

STATS_FILE = "stats.json"
stats = {"exams_completed": {}, "dict_lookups": {}, "writings_completed": {}}


def load_stats():
    global stats
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
    except Exception:
        pass


def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def inc_stat(section: str, user_id: int, amount: int = 1):
    uid = str(user_id)
    if section not in stats:
        stats[section] = {}
    stats[section][uid] = int(stats[section].get(uid, 0)) + amount
    save_stats()


# ======================
# SCORE -> CEFR (siz so‘ragan)
# ======================
def clamp_20_75(x: int) -> int:
    return max(20, min(75, int(x)))

def cefr_from_score_20_75(score: int) -> str:
    s = clamp_20_75(score)
    if 20 <= s <= 27: return "A1"
    if 28 <= s <= 37: return "A2"
    if 38 <= s <= 50: return "B1"
    if 51 <= s <= 64: return "B2"
    if 65 <= s <= 73: return "C1"
    return "C2"  # 74–75

def ielts_from_cefr(cefr: str) -> str:
    return {
        "A1": "~1.0–2.5",
        "A2": "~3.0–3.5",
        "B1": "~4.0–5.0",
        "B2": "~5.5–6.5",
        "C1": "~7.0–8.0",
        "C2": "~8.5–9.0",
    }.get(cefr, "~3.0–3.5")


# ======================
# FLASK keep-alive (Render + UptimeRobot)
# ======================
app = Flask(__name__)

@app.get("/")
def home():
    return "OK"

@app.get("/health")
def health():
    return "healthy", 200

def run_web():
    app.run(host="0.0.0.0", port=PORT)


# ======================
# STATES
# ======================
class SpeakingStates(StatesGroup):
    answering = State()

class DictionaryStates(StatesGroup):
    waiting_word = State()

class WritingStates(StatesGroup):
    writing_text = State()


# ======================
# QUESTION BANKS
# ======================
SPEAKING_QUESTION_BANK: List[str] = [
    "What is your name?",
    "Where do you live?",
    "What do you like to do in your free time?",
    "What is your favorite food and why?",
    "Do you like music? What kind?",
    "What time do you usually get up?",

    "What is your hobby? Why do you like it?",
    "Tell me about your daily routine.",
    "What did you do yesterday?",
    "Describe a memorable day.",
    "Talk about your future plans.",
    "Describe your best friend and why you like them.",

    "Do you think social media is helpful or harmful? Why?",
    "Discuss advantages and disadvantages of online learning.",
    "Describe a challenge you faced and how you solved it.",
    "Should students wear uniforms? Discuss both sides.",
    "What makes a person successful? Give examples.",
    "Discuss trade-offs between security and privacy.",
]

WRITING_PROMPTS = {
    "friend_50": [
        "Write a message to your friend. Invite them to meet this weekend. Include time, place, and what you will do.",
        "Write a message to your friend. Say sorry because you cannot come today. Explain why and suggest another day.",
        "Write a message to your friend. Recommend a movie or game you enjoyed. Say why you liked it.",
        "Write a message to your friend. Ask for help with homework. Explain what you don’t understand.",
    ],
    "manager_120": [
        "Write an email to your manager. Request a day off. Give reasons and suggest how you will cover your work.",
        "Write an email to your manager. Report a problem (internet/equipment). Explain the impact and ask for support.",
        "Write an email to your manager. Explain you will be late. Give a reason and say how you will catch up.",
        "Write an email to your manager. Ask for feedback on your performance and how to improve.",
    ],
    "essay_200": [
        "Essay: Some people think social media does more harm than good. Discuss both views and give your opinion.",
        "Essay: Online learning is becoming popular. What are the advantages and disadvantages?",
        "Essay: People should exercise every day. Do you agree or disagree? Give reasons and examples.",
        "Essay: Technology makes life easier, but it can also create problems. Discuss and give examples.",
    ],
}


# ======================
# KEYBOARDS
# ======================
def sub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Obuna bo‘lish", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="🔍 Obunani tekshirish", callback_data="check_sub")],
        ]
    )

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗣 Speaking")],
            [KeyboardButton(text="📚 Dictionary")],
            [KeyboardButton(text="✍️ Writing")],
        ],
        resize_keyboard=True
    )

def back_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Orqaga")]],
        resize_keyboard=True
    )


# ======================
# BOT
# ======================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ======================
# SUB CHECK
# ======================
async def is_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("creator", "administrator", "member")
    except Exception:
        return False

async def require_sub(message: Message, state: Optional[FSMContext] = None) -> bool:
    user_id = message.from_user.id
    if not await is_subscribed(bot, user_id):
        if state:
            await state.clear()
        await message.answer(
            "Botdan foydalanish uchun avval kanalga obuna bo‘ling:\n"
            f"➡️ {CHANNEL_URL}\n\n"
            "Obuna bo‘lgach, «Obunani tekshirish» ni bosing.",
            reply_markup=sub_keyboard()
        )
        return False
    return True


# ======================
# AUDIO
# ======================
async def convert_ogg_to_wav(ogg_path: str, wav_path: str) -> None:
    audio = AudioSegment.from_file(ogg_path)
    audio.export(wav_path, format="wav")


# ======================
# GROQ (SDKsiz)
# ======================
def groq_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {GROQ_API_KEY}"}

def groq_stt_whisper(wav_path: str) -> str:
    if not GROQ_API_KEY:
        return ""
    url = f"{GROQ_BASE}/audio/transcriptions"
    try:
        with open(wav_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            data = {"model": "whisper-large-v3", "language": "en", "response_format": "json"}
            r = requests.post(url, headers=groq_headers(), files=files, data=data, timeout=60)
        if r.status_code != 200:
            print("GROQ STT HTTP:", r.status_code, r.text[:400])
            return ""
        js = r.json()
        return (js.get("text") or "").strip()
    except Exception as e:
        print("GROQ STT ERROR:", repr(e))
        return ""

def groq_chat_json(system: str, user_json: Dict) -> Optional[Dict]:
    if not GROQ_API_KEY:
        return None

    url = f"{GROQ_BASE}/chat/completions"
    last_err = None

    for model in GROQ_CHAT_MODELS:
        if not model:
            continue

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_json, ensure_ascii=False)},
            ],
            "temperature": 0.1,
        }

        try:
            r = requests.post(
                url,
                headers={**groq_headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=60
            )
            if r.status_code != 200:
                last_err = (r.status_code, r.text[:500])
                continue

            content = r.json()["choices"][0]["message"]["content"] or ""
            m = re.search(r"\{.*\}", content, re.S)
            if not m:
                last_err = ("NO_JSON", content[:250])
                continue

            return json.loads(m.group(0))

        except Exception as e:
            last_err = ("EXC", repr(e))
            continue

    print("GROQ CHAT FAILED:", last_err)
    return None


# ======================
# SPEAKING EVAL (off-topic cap)
# ======================
def enforce_caps_from_relevance(score: int, avg_rel: float) -> int:
    s = clamp_20_75(score)
    if avg_rel < 2.0:
        return min(s, 37)  # A2 max
    if avg_rel < 3.0 and s >= 38:
        return min(s, 37)  # B1+ chiqmasin
    return s

async def evaluate_speaking_strict(questions: List[str], answers: List[str]) -> Dict:
    system = (
        "You are a STRICT IELTS Speaking examiner.\n"
        "Return ONLY JSON keys:\n"
        "score_20_75 (20..75), feedback_uz (Uzbek), corrected_best_version (English), per_question.\n"
        "per_question items include relevance_to_question (0..5).\n"
        "If off-topic, relevance must be low.\n"
    )

    data = groq_chat_json(system, {
        "items": [{"question": q, "answer": a} for q, a in zip(questions, answers)]
    })

    if not data:
        joined = " ".join(a.strip() for a in answers if a and a.strip())
        score = 24 if len(joined.split()) < 12 else 35
        score = clamp_20_75(score)
        return {
            "score_20_75": score,
            "feedback_uz": "Baholash xizmati ishlamadi. Taxminiy natija.",
            "corrected_best_version": joined or "—",
        }

    score = clamp_20_75(int(data.get("score_20_75", 20)))
    per_q = data.get("per_question") or []
    rels = []
    for it in per_q:
        try:
            rels.append(float(it.get("relevance_to_question", 0)))
        except Exception:
            pass
    avg_rel = sum(rels) / len(rels) if rels else 0.0
    score = enforce_caps_from_relevance(score, avg_rel)

    return {
        "score_20_75": score,
        "feedback_uz": str(data.get("feedback_uz", "")).strip(),
        "corrected_best_version": (str(data.get("corrected_best_version", "")).strip() or "—"),
        "avg_relevance": avg_rel,
    }


# ======================
# WRITING: advice/maslahat
# ======================
def word_count(s: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", s))

def split_answers(text: str) -> Dict[int, str]:
    parts = {1: "", 2: "", 3: ""}
    m1 = re.search(r"(?:^|\n)\s*1\)\s*(.*?)(?=(?:\n\s*2\)|\Z))", text, re.S)
    m2 = re.search(r"(?:^|\n)\s*2\)\s*(.*?)(?=(?:\n\s*3\)|\Z))", text, re.S)
    m3 = re.search(r"(?:^|\n)\s*3\)\s*(.*)\Z", text, re.S)
    if m1: parts[1] = m1.group(1).strip()
    if m2: parts[2] = m2.group(1).strip()
    if m3: parts[3] = m3.group(1).strip()
    return parts

def safe_text(x) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    return str(x)

def build_writing_advice(prompts: List[Dict], wc1: int, wc2: int, wc3: int) -> str:
    lines = []
    lines.append("📌 Maslahat (Task bo‘yicha):")

    lines.append("\n1) Friend (min 50 words)")
    if wc1 < 50:
        lines.append(f"❌ Juda qisqa: {wc1}/50 so‘z. Kamida 50 so‘z yozing.")
    else:
        lines.append(f"✅ So‘z soni: {wc1}/50 (OK)")
    lines.append("✅ Kerak: greeting + maqsad + 2-3 detal (qachon/qayerda/nima) + yakun.")
    lines.append("🧩 Namuna:")
    lines.append("- Hi! Do you want to meet this weekend?")
    lines.append("- Let’s meet at 5 pm near the park and play football.")

    lines.append("\n2) Manager email (min 120 words)")
    if wc2 < 120:
        lines.append(f"❌ Juda qisqa: {wc2}/120 so‘z. Kamida 120 so‘z yozing.")
    else:
        lines.append(f"✅ So‘z soni: {wc2}/120 (OK)")
    lines.append("✅ Kerak: sabab + sana + ishni qoplash rejasi + minnatdorchilik + imzo.")
    lines.append("🧩 Namuna:")
    lines.append("- I would like to request a day off on Monday because I have a medical appointment.")
    lines.append("- I will complete my tasks on Friday and ask Ali to cover urgent calls.")

    lines.append("\n3) Essay (min 180 words)")
    if wc3 < 180:
        lines.append(f"❌ Juda qisqa: {wc3}/180 so‘z. Kamida 180–200 so‘z yozing.")
    else:
        lines.append(f"✅ So‘z soni: {wc3}/180 (OK)")
    lines.append("✅ Kerak: intro + 2 ta body (sabab+misol) + conclusion.")
    lines.append("🧩 Linkers: Firstly, moreover, however, on the other hand, for example, in conclusion")

    lines.append("\n✅ Umumiy tavsiyalar:")
    lines.append("- Har task savoliga mos yozing (off-topic bo‘lsa baho qattiq tushadi).")
    lines.append("- 1), 2), 3) formatdan chiqib ketmang.")
    lines.append("- Takrorni kamaytiring, oddiy grammatikani to‘g‘ri ishlating (present/past/future).")

    return "\n".join(lines)

async def evaluate_writing_strict(prompts: List[Dict[str, str]], full_text: str) -> Dict:
    answers = split_answers(full_text)
    wc1 = word_count(answers[1])
    wc2 = word_count(answers[2])
    wc3 = word_count(answers[3])

    coverage = 0
    if wc1 >= 50: coverage += 1
    if wc2 >= 120: coverage += 1
    if wc3 >= 180: coverage += 1

    advice = build_writing_advice(prompts, wc1, wc2, wc3)

    system = (
        "You are a STRICT IELTS Writing examiner.\n"
        "Return ONLY JSON keys:\n"
        "score_20_75 (20..75), off_topic (true/false), feedback_uz (Uzbek), corrected_best_version (English).\n"
        "Be strict about task completion and relevance.\n"
    )

    data = groq_chat_json(system, {
        "prompts": prompts,
        "answers": [
            {"task": 1, "min_words": 50, "word_count": wc1, "text": answers[1]},
            {"task": 2, "min_words": 120, "word_count": wc2, "text": answers[2]},
            {"task": 3, "min_words": 180, "word_count": wc3, "text": answers[3]},
        ],
        "task_coverage": coverage
    })

    if not data:
        # fallback
        score = 20
        if coverage == 2: score = 32
        if coverage == 3: score = 45
        score = clamp_20_75(score)
        if coverage <= 1:
            score = min(score, 37)  # A2 max
        feedback = "Baholash xizmati ishlamadi. Word count va task bajarilishi bo‘yicha taxminiy natija.\n\n" + advice
        corrected = full_text if full_text else "—"
        return {
            "score_20_75": score,
            "task_coverage": coverage,
            "off_topic": True if coverage <= 1 else False,
            "feedback_uz": feedback,
            "corrected_best_version": corrected,
            "wc1": wc1, "wc2": wc2, "wc3": wc3,
        }

    score = clamp_20_75(int(data.get("score_20_75", 20)))
    off_topic = bool(data.get("off_topic", False))

    # cap
    if coverage <= 1 or off_topic:
        score = min(score, 37)

    feedback = safe_text(data.get("feedback_uz", "")).strip() or "—"
    corrected = safe_text(data.get("corrected_best_version", "")).strip() or "—"

    full_feedback = feedback + "\n\n" + advice

    return {
        "score_20_75": score,
        "task_coverage": coverage,
        "off_topic": off_topic,
        "feedback_uz": full_feedback,
        "corrected_best_version": corrected,
        "wc1": wc1, "wc2": wc2, "wc3": wc3,
    }


# ======================
# DICTIONARY
# ======================
def dict_lookup(word: str) -> Tuple[str, str, Optional[str]]:
    try:
        r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=15)
        if r.status_code != 200:
            return ("—", "—", None)
        data = r.json()[0]

        ipa = "—"
        audio_url = None

        for ph in data.get("phonetics", []):
            if ph.get("text") and ipa == "—":
                ipa = ph["text"]
            if ph.get("audio") and not audio_url:
                audio_url = ph["audio"]

        definition = "—"
        meanings = data.get("meanings", [])
        if meanings and meanings[0].get("definitions"):
            definition = meanings[0]["definitions"][0].get("definition", "—")

        return (ipa, definition, audio_url)
    except Exception:
        return ("—", "—", None)

def translate_uz(word: str) -> str:
    word = word.strip()
    if not word:
        return "—"
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "uz", "dt": "t", "q": word}
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            translated = "".join([chunk[0] for chunk in data[0] if chunk and chunk[0]])
            translated = (translated or "").strip()
            if translated:
                return translated
    except Exception:
        pass
    return "Tarjima topilmadi."

def download_to_temp(url: str, suffix: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or not r.content:
            return None
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception:
        return None


# ======================
# /start + check_sub + admin
# ======================
@dp.message(CommandStart())
async def start(message: Message):
    if not await require_sub(message):
        return
    await message.answer("✅ Siz obunasiz. Bo‘lim tanlang:", reply_markup=main_menu())


@dp.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery):
    if await is_subscribed(bot, call.from_user.id):
        await call.message.answer("✅ Obuna tasdiqlandi! Endi bot ishlaydi.", reply_markup=main_menu())
    else:
        await call.message.answer("❌ Hali obuna emassiz.", reply_markup=sub_keyboard())
    await call.answer()


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Siz admin emassiz.")
        return

    exams = stats.get("exams_completed", {})
    looks = stats.get("dict_lookups", {})
    writes = stats.get("writings_completed", {})
    user_ids = set(exams.keys()) | set(looks.keys()) | set(writes.keys())

    if not user_ids:
        await message.answer("📭 Hozircha statistika yo‘q.")
        return

    lines = ["👑 Admin panel", "", "ID | Speaking | Dictionary | Writing", "---|---|---|---"]
    for uid in sorted(user_ids, key=lambda x: int(x)):
        lines.append(f"{uid} | {int(exams.get(uid, 0))} | {int(looks.get(uid, 0))} | {int(writes.get(uid, 0))}")
    await message.answer("\n".join(lines))


# ======================
# BACK
# ======================
@dp.message(F.text == "⬅️ Orqaga")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    if not await require_sub(message):
        return
    await message.answer("🏠 Asosiy menyu:", reply_markup=main_menu())


# ======================
# SPEAKING (FULL)
# ======================
@dp.message(F.text == "🗣 Speaking")
async def speaking_start(message: Message, state: FSMContext):
    if not await require_sub(message, state):
        return
    if not GROQ_API_KEY:
        await message.answer("❌ GROQ_API_KEY yo‘q. Render/PC env ga qo‘ying.")
        return

    questions = random.sample(SPEAKING_QUESTION_BANK, k=3)
    await state.update_data(questions=questions, q_index=0, answers=[])
    await state.set_state(SpeakingStates.answering)

    await message.answer(
        "🗣 Speaking testi boshlandi.\n⚠️ Faqat INGLIZCHA gapiring, sekin va aniq.\n\n"
        f"1) {questions[0]} (Answer by voice)",
        reply_markup=back_menu()
    )


@dp.message(SpeakingStates.answering)
async def speaking_voice(message: Message, state: FSMContext):
    if not await require_sub(message, state):
        return

    if message.text and message.text.strip().lower() == "⬅️ orqaga":
        await state.clear()
        await message.answer("🏠 Asosiy menyu:", reply_markup=main_menu())
        return

    if not message.voice:
        await message.answer("Iltimos, faqat VOICE yuboring. 🎤")
        return

    data = await state.get_data()
    questions = data.get("questions") or random.sample(SPEAKING_QUESTION_BANK, k=3)
    q_index = int(data.get("q_index", 0))
    answers: List[str] = data.get("answers", [])

    ogg_fd, ogg_path = tempfile.mkstemp(suffix=".ogg")
    wav_fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(ogg_fd)
    os.close(wav_fd)

    try:
        file = await bot.get_file(message.voice.file_id)
        await bot.download_file(file.file_path, destination=ogg_path)

        try:
            await convert_ogg_to_wav(ogg_path, wav_path)
        except Exception:
            await message.answer(
                "❌ Voice ishlamadi: ffmpeg yo‘q bo‘lishi mumkin.\n"
                "✅ PC’da: ffmpeg o‘rnating.\n"
                "✅ Render’da: ffmpeg qo‘shish kerak."
            )
            return

        await message.answer("🎧 Ovoz matnga aylantirilmoqda...")
        transcript = groq_stt_whisper(wav_path)

        if not transcript:
            await message.answer("❌ Ovoz tushunilmadi. Sekinroq va aniqroq yuboring.")
            return

        answers.append(transcript)
        await state.update_data(answers=answers)
        await message.answer(f"📝 Tushungan matn:\n{transcript}")

        q_index += 1
        await state.update_data(q_index=q_index)

        if q_index < 3:
            await message.answer(f"{q_index+1}) {questions[q_index]} (Answer by voice)")
            return

        await message.answer("✅ Hamma javoblar olindi. Imtihondek baholanmoqda...")
        res = await evaluate_speaking_strict(questions[:3], answers[:3])

        score = clamp_20_75(int(res.get("score_20_75", 20)))
        cefr = cefr_from_score_20_75(score)
        ielts = ielts_from_cefr(cefr)

        await message.answer(
            "📊 Natija (Speaking):\n"
            f"🏷 CEFR: {cefr}\n"
            f"🎯 IELTS (taxminiy): {ielts}\n"
            f"⭐ Umumiy ball: {score}/75\n\n"
            f"🧠 Izoh (UZ): {res.get('feedback_uz','—')}\n\n"
            f"✅ To‘g‘rilangan eng yaxshi variant:\n{res.get('corrected_best_version','—')}",
            reply_markup=main_menu()
        )

        inc_stat("exams_completed", message.from_user.id, 1)
        await state.clear()

    finally:
        for p in (ogg_path, wav_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ======================
# DICTIONARY (faqat tugma bosilganda)
# ======================
@dp.message(F.text == "📚 Dictionary")
async def dictionary_start(message: Message, state: FSMContext):
    if not await require_sub(message, state):
        return
    await state.set_state(DictionaryStates.waiting_word)
    await message.answer(
        "📚 Dictionary\nSo‘z yozing (masalan: hi, hobby, routine)\n"
        "Men so‘zni audio qilib o‘qib beraman 🔊\n\n"
        "⚠️ Faqat MATN yuboring.",
        reply_markup=back_menu()
    )

@dp.message(DictionaryStates.waiting_word)
async def dictionary_lookup_handler(message: Message, state: FSMContext):
    if not await require_sub(message, state):
        return

    if not message.text:
        await message.answer("So‘zni MATN qilib yozing. Masalan: hi")
        return

    if message.text.strip().lower() == "⬅️ orqaga":
        await state.clear()
        await message.answer("🏠 Asosiy menyu:", reply_markup=main_menu())
        return

    word = re.sub(r"[^a-zA-Z'\-]", "", message.text.strip()).lower()
    if not word:
        await message.answer("So‘zni to‘g‘ri yozing. Masalan: hi")
        return

    ipa, definition, audio_url = dict_lookup(word)
    uz = translate_uz(word)

    temp_audio = None
    if audio_url:
        if audio_url.startswith("//"):
            audio_url = "https:" + audio_url
        temp_audio = download_to_temp(audio_url, ".mp3")

    if temp_audio:
        try:
            await message.answer_voice(FSInputFile(temp_audio), caption=f"🔊 {word} (pronunciation)")
        except Exception:
            await message.answer_audio(FSInputFile(temp_audio), caption=f"🔊 {word} (pronunciation)")

    await message.answer(
        f"✅ {word}\n"
        f"📌 English definition: {definition}\n"
        f"🇺🇿 Tarjima (UZ): {uz}\n"
        f"🔤 IPA: {ipa}\n\n"
        "Yana so‘z yozing:"
    )

    inc_stat("dict_lookups", message.from_user.id, 1)

    if temp_audio:
        try:
            os.remove(temp_audio)
        except Exception:
            pass


# ======================
# WRITING (FULL + maslahat)
# ======================
@dp.message(F.text == "✍️ Writing")
async def writing_start(message: Message, state: FSMContext):
    if not await require_sub(message, state):
        return

    p1 = random.choice(WRITING_PROMPTS["friend_50"])
    p2 = random.choice(WRITING_PROMPTS["manager_120"])
    p3 = random.choice(WRITING_PROMPTS["essay_200"])

    prompts = [
        {"task": 1, "type": "friend_message", "min_words": 50, "prompt": p1},
        {"task": 2, "type": "manager_email", "min_words": 120, "prompt": p2},
        {"task": 3, "type": "essay", "min_words": 180, "prompt": p3},
    ]

    await state.update_data(writing_prompts=prompts)
    await state.set_state(WritingStates.writing_text)

    await message.answer(
        "✍️ Writing (imtihondagidek)\n"
        "1 ta xabarda 3 tasiga ham javob yozing.\n"
        "Format:\n"
        "1) ...\n2) ...\n3) ...\n\n"
        f"1) (min 50 words) {p1}\n\n"
        f"2) (min 120 words) {p2}\n\n"
        f"3) (min 180 words) {p3}\n",
        reply_markup=back_menu()
    )

@dp.message(WritingStates.writing_text)
async def writing_submit(message: Message, state: FSMContext):
    if not await require_sub(message, state):
        return

    if not message.text:
        await message.answer("Writing javobni MATN qilib yuboring.\n1) ...\n2) ...\n3) ...")
        return

    if message.text.strip().lower() == "⬅️ orqaga":
        await state.clear()
        await message.answer("🏠 Asosiy menyu:", reply_markup=main_menu())
        return

    data = await state.get_data()
    prompts = data.get("writing_prompts", [])
    full_text = message.text.strip()

    if not prompts or len(prompts) != 3:
        await message.answer("Topic topilmadi. Qayta ✍️ Writing bosing.")
        await state.clear()
        return

    await message.answer("🧾 Writing baholanmoqda (halol, imtihondek)...")
    res = await evaluate_writing_strict(prompts, full_text)

    score = clamp_20_75(int(res.get("score_20_75", 20)))
    cefr = cefr_from_score_20_75(score)
    ielts = ielts_from_cefr(cefr)

    coverage = int(res.get("task_coverage", 0) or 0)
    wc1 = int(res.get("wc1", 0) or 0)
    wc2 = int(res.get("wc2", 0) or 0)
    wc3 = int(res.get("wc3", 0) or 0)

    feedback = safe_text(res.get("feedback_uz", "")).strip() or "—"
    corrected = safe_text(res.get("corrected_best_version", "")).strip() or "—"

    await message.answer(
        "📊 Natija (Writing):\n"
        f"🏷 CEFR: {cefr}\n"
        f"🎯 IELTS (taxminiy): {ielts}\n"
        f"⭐ Umumiy ball: {score}/75\n\n"
        f"🧾 Task coverage: {coverage}/3\n"
        f"🔢 Word count: 1) {wc1} | 2) {wc2} | 3) {wc3}\n\n"
        f"🧠 Izoh (UZ):\n{feedback}\n\n"
        f"✅ To‘g‘rilangan eng yaxshi variant:\n{corrected}",
        reply_markup=main_menu()
    )

    inc_stat("writings_completed", message.from_user.id, 1)
    await state.clear()


# ======================
# VOICE BLOCK (outside speaking)
# ======================
@dp.message(F.voice)
async def block_voice_outside_speaking(message: Message, state: FSMContext):
    st = await state.get_state()
    if st == SpeakingStates.answering.state:
        return
    if st == DictionaryStates.waiting_word.state:
        await message.answer("📚 Dictionary uchun faqat MATN yozing (masalan: hi).")
        return
    if st == WritingStates.writing_text.state:
        await message.answer("✍️ Writing uchun VOICE emas, MATN yozing.\n1) ...\n2) ...\n3) ...")
        return
    await message.answer("Menyudan tanlang 👇", reply_markup=main_menu())


@dp.message()
async def fallback(message: Message):
    if not await require_sub(message):
        return
    await message.answer("Menyudan tanlang 👇", reply_markup=main_menu())


# ======================
# RUN
# ======================
async def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN yo‘q. Env ga BOT_TOKEN qo‘ying.")
        return

    load_stats()
    Thread(target=run_web, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
