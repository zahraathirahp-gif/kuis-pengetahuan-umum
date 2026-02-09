import asyncio
import json
import os
import random
import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0

DATA_FILE = 'quiz_data.json'

def load_db():
    default = {"users": {}, "groups": [], "questions": {"Umum": [{"q": "Ibukota Indonesia", "a": "jakarta"}]}, "ads_text": "Iklan Kosong.", "ads_photo": None}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f: return json.load(f)
        except: pass
    return default

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f: json.dump(db, f, indent=4)

def get_rank(pts):
    if pts < 50: return "Warga"
    if pts < 200: return "Pendekar"
    return "👑 Raja"

def format_hint(answer, revealed_indices=None):
    answer = answer.upper()
    if revealed_indices is None: revealed_indices = {0, len(answer)-1}
    chars = [char if i in revealed_indices or char == " " else "_" for i, char in enumerate(answer)]
    return " ".join(chars)

# --- STATE ---
current_games = {} 
group_participants = {} # Menghitung jumlah user unik yang aktif per grup

async def post_init(application: Application):
    user_commands = [
        BotCommand("start", "Mulai Game"),
        BotCommand("top", "Leaderboard"),
        BotCommand("hint", "Beli Huruf (-5 Pts)"),
        BotCommand("stop", "Berhenti")
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

# --- ENGINE ---
async def quiz_timer(context, chat_id, category, correct_ans):
    try:
        await asyncio.sleep(20)
        if chat_id in current_games:
            del current_games[chat_id]
            await context.bot.send_message(chat_id, f"⌛ Waktu Habis! Jawabannya: {correct_ans.upper()}")
            await asyncio.sleep(2)
            await send_question(context, chat_id, category)
    except asyncio.CancelledError: pass

async def send_question(context, chat_id, category):
    if chat_id in current_games and 'task' in current_games[chat_id]:
        current_games[chat_id]['task'].cancel()

    q_list = db['questions'].get(category, [])
    if not q_list: return await context.bot.send_message(chat_id, "Soal kosong.")
    
    q_data = random.choice(q_list)
    ans_clean = q_data['a'].lower().strip()
    initial_reveal = {0, len(ans_clean)-1}
    
    text = f"🎮 {category}\n\n❓ {q_data['q']}\n🔤 Clue: `{format_hint(ans_clean, initial_reveal)}`"
    kb = [[InlineKeyboardButton("⏭ Next", callback_data="game_skip"), InlineKeyboardButton("🛑 Stop", callback_data="game_stop")]]

    await context.bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    current_games[chat_id] = {"ans": ans_clean, "cat": category, "task": asyncio.create_task(quiz_timer(context, chat_id, category, ans_clean)), "start_time": time.time(), "revealed": initial_reveal}

# --- HANDLER ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    msg = update.message
    # Mendukung tag bot: /hint@botname -> /hint
    raw_text = (msg.text or msg.caption or "").lower().strip()
    text = raw_text.split('@')[0] 
    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    if update.effective_chat.type in ["group", "supergroup"] and chat_id not in db['groups']:
        db['groups'].append(chat_id); save_db()

    # COMMANDS
    if text == "/start":
        if update.effective_chat.type == "private":
            kb = [[InlineKeyboardButton("➕ Tambah ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
            intro = f"🤖 KUIS BOT\n\n📢 {db['ads_text']}"
            if db.get('ads_photo'): return await msg.reply_photo(db['ads_photo'], caption=intro, reply_markup=InlineKeyboardMarkup(kb))
            return await msg.reply_text(intro, reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("▶️ Mulai", callback_data="menu_start")]]
            return await msg.reply_text("Siap bermain?", reply_markup=InlineKeyboardMarkup(kb))

    if text in ["/top", "/rank", "/leaderboard"]:
        top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:10]
        t = "🏆 TOP 10 GLOBAL\n\n"
        for i, (u_id, d) in enumerate(top, 1): t += f"{i}. {d['name']} - {d['pts']} Pts ({get_rank(d['pts'])})\n"
        return await msg.reply_text(t)

    if text == "/hint" and chat_id in current_games:
        s_uid = str(uid)
        if db['users'].get(s_uid, {}).get('pts', 0) < 5: return await msg.reply_text("Poin kurang (Butuh 5)!")
        db['users'][s_uid]['pts'] -= 5; save_db()
        game = current_games[chat_id]
        hidden = [i for i in range(len(game['ans'])) if i not in game['revealed'] and game['ans'][i] != " "]
        if not hidden: return await msg.reply_text("Huruf sudah terbuka semua!")
        game['revealed'].add(random.choice(hidden))
        return await msg.reply_text(f"🔓 Hint baru: `{format_hint(game['ans'], game['revealed'])}`", parse_mode='Markdown')

    if text == "/admin" and uid == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("📢 Broadcast", callback_data='adm_bc')],
            [InlineKeyboardButton("🖼 Set Iklan", callback_data='adm_ads')],
            [InlineKeyboardButton("➕ Tambah Soal", callback_data='adm_q')],
            [InlineKeyboardButton("📤 Send DB (Backup)", callback_data='adm_db')]
        ]
        return await msg.reply_text("🛠 ADMIN PANEL", reply_markup=InlineKeyboardMarkup(kb))

    # ADMIN STATE LOGIC
    state = context.user_data.get('state')
    if state and uid == ADMIN_ID:
        if state == 'w_ads':
            db['ads_text'] = msg.caption or msg.text
            if msg.photo: db['ads_photo'] = msg.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            return await msg.reply_text("✅ Iklan Diperbarui!")
        elif state == 'w_q':
            try:
                k, s, j = [x.strip() for x in raw_text.split("|")]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "a":j}); save_db(); context.user_data['state'] = None
                return await msg.reply_text(f"✅ Soal Masuk ke {k}")
            except: return await msg.reply_text("Format: Kategori | Soal | Jawaban")
        elif state == 'w_bc':
            context.user_data['state'] = None
            for g in db['groups']:
                try: await msg.copy(chat_id=g)
                except: pass
            return await msg.reply_text("✅ Broadcast Selesai")

    # JAWABAN CHECKER
    if chat_id in current_games and text == current_games[chat_id]['ans']:
        game = current_games[chat_id]
        game['task'].cancel()
        
        # Logika Minimal 2 Orang
        if chat_id not in group_participants: group_participants[chat_id] = set()
        group_participants[chat_id].add(uid)

        if len(group_participants[chat_id]) < 2:
            await msg.reply_text(f"✅ {update.effective_user.first_name} Benar! Tapi butuh minimal 2 pemain aktif agar poin cair.")
        else:
            s_uid = str(uid)
            if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}
            pts = 15 if (time.time() - game['start_time']) < 5 else 10
            db['users'][s_uid]['pts'] += pts; save_db()
            await msg.reply_text(f"🎯 BENAR! {update.effective_user.first_name} (+{pts} Pts).\nTotal: {db['users'][s_uid]['pts']} ({get_rank(db['users'][s_uid]['pts'])})")

        del current_games[chat_id]; await asyncio.sleep(2); await send_question(context, chat_id, game['cat'])

# --- CALLBACK ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; d = q.data; cid = q.message.chat_id; uid = q.from_user.id
    if d == 'menu_start':
        kb = [[InlineKeyboardButton(f"📂 {c}", callback_data=f"start_{c}")] for c in db['questions'].keys()]
        await q.message.edit_text("PILIH KATEGORI:", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('start_'):
        await q.message.delete(); await send_question(context, cid, d.split('_')[1])
    elif d == 'game_skip' and cid in current_games:
        current_games[cid]['task'].cancel(); cat = current_games[cid]['cat']
        del current_games[cid]; await send_question(context, cid, cat)
    elif d == 'game_stop' and cid in current_games:
        current_games[cid]['task'].cancel(); del current_games[cid]; await q.message.reply_text("Game Dihentikan.")
    elif d.startswith('adm_') and uid == ADMIN_ID:
        if d == 'adm_db': save_db(); await q.message.reply_document(open(DATA_FILE, 'rb'), caption="Backup Database")
        elif d == 'adm_ads': context.user_data['state'] = 'w_ads'; await q.message.reply_text("Kirim Iklan (Foto+Caption):")
        elif d == 'adm_q': context.user_data['state'] = 'w_q'; await q.message.reply_text("Format: Kategori | Soal | Jawaban")
        elif d == 'adm_bc': context.user_data['state'] = 'w_bc'; await q.message.reply_text("Kirim pesan Broadcast:")
    await q.answer()

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL, handle_msg))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__': main()
