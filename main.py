import asyncio
import json
import os
import random
import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0

DATA_FILE = 'quiz_data.json'

def load_db():
    default = {"users": {}, "groups": [], "questions": {"General": []}, "ads_text": "Iklan Kosong.", "ads_photo": None}
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

current_games = {} 
lobby_data = {} # {chat_id: {"host": id, "players": [ids], "names": [names]}}

async def post_init(application: Application):
    user_commands = [
        BotCommand("start", "Mulai Game"),
        BotCommand("top", "Leaderboard"),
        BotCommand("hint", "Beli Huruf (-5 Pts)"),
        BotCommand("stop", "Berhenti")
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

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

async def quiz_timer(context, chat_id, category, correct_ans):
    try:
        await asyncio.sleep(20)
        if chat_id in current_games:
            del current_games[chat_id]
            await context.bot.send_message(chat_id, f"⌛ Habis! Jawaban: {correct_ans.upper()}")
            await asyncio.sleep(2); await send_question(context, chat_id, category)
    except asyncio.CancelledError: pass

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    msg = update.message
    raw_text = (msg.text or msg.caption or "").lower().strip()
    text = raw_text.split('@')[0]
    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    if update.effective_chat.type in ["group", "supergroup"] and chat_id not in db['groups']:
        db['groups'].append(chat_id); save_db()

    if text == "/start":
        if update.effective_chat.type == "private":
            kb = [[InlineKeyboardButton("➕ Tambah ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
            intro = f"🤖 KUIS BOT\n\n📢 {db['ads_text']}"
            if db.get('ads_photo'): return await msg.reply_photo(db['ads_photo'], caption=intro, reply_markup=InlineKeyboardMarkup(kb))
            return await msg.reply_text(intro, reply_markup=InlineKeyboardMarkup(kb))
        else:
            lobby_data[chat_id] = {"host": uid, "players": [uid], "names": [update.effective_user.first_name]}
            kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="lobby_join")], [InlineKeyboardButton("Mulai ▶️", callback_data="lobby_start")]]
            return await msg.reply_text(f"🎮 **LOBBY KUIS**\n\nPlayer: \n1. {update.effective_user.first_name} (Host)", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    if text in ["/top", "/rank"]:
        top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:10]
        t = "🏆 TOP 10 GLOBAL\n\n"
        for i, (u_id, d) in enumerate(top, 1): t += f"{i}. {d['name']} - {d['pts']} Pts\n"
        return await msg.reply_text(t)

    if text == "/hint" and chat_id in current_games:
        s_uid = str(uid)
        if db['users'].get(s_uid, {}).get('pts', 0) < 5: return await msg.reply_text("Poin kurang!")
        db['users'][s_uid]['pts'] -= 5; save_db()
        game = current_games[chat_id]; hidden = [i for i in range(len(game['ans'])) if i not in game['revealed'] and game['ans'][i] != " "]
        if not hidden: return
        game['revealed'].add(random.choice(hidden))
        return await msg.reply_text(f"🔓 Hint: `{format_hint(game['ans'], game['revealed'])}`", parse_mode='Markdown')

    if text == "/admin" and uid == ADMIN_ID:
        kb = [[InlineKeyboardButton("📢 BC", callback_data='adm_bc')], [InlineKeyboardButton("🖼 Ads", callback_data='adm_ads')], [InlineKeyboardButton("➕ Soal", callback_data='adm_q')], [InlineKeyboardButton("📤 DB", callback_data='adm_db')]]
        return await msg.reply_text("🛠 ADMIN", reply_markup=InlineKeyboardMarkup(kb))

    # --- ADMIN STEP LOGIC ---
    state = context.user_data.get('state')
    if state and uid == ADMIN_ID:
        if state == 'w_ads':
            db['ads_text'] = msg.caption or msg.text; db['ads_photo'] = msg.photo[-1].file_id if msg.photo else db['ads_photo']
            save_db(); context.user_data['state'] = None; return await msg.reply_text("✅ OK")
        
        elif state == 'w_q_cat_name':
            context.user_data['new_q'] = {"cat": raw_text}; context.user_data['state'] = 'w_q_ques'
            return await msg.reply_text("Kirim Soalnya:")
        elif state == 'w_q_ques':
            context.user_data['new_q']['q'] = raw_text; context.user_data['state'] = 'w_q_ans'
            return await msg.reply_text("Kirim Jawabannya:")
        elif state == 'w_q_ans':
            q_data = context.user_data['new_q']; cat = q_data['cat']
            if cat not in db['questions']: db['questions'][cat] = []
            db['questions'][cat].append({"q": q_data['q'], "a": raw_text})
            save_db(); context.user_data['state'] = None; return await msg.reply_text(f"✅ Soal masuk ke {cat}")
            
        elif state == 'w_bc':
            context.user_data['state'] = None
            for g in db['groups']:
                try: await msg.copy(chat_id=g)
                except: pass
            return await msg.reply_text("✅ Selesai")

    # JAWABAN
    if chat_id in current_games and text == current_games[chat_id]['ans']:
        game = current_games[chat_id]; game['task'].cancel()
        is_multi = len(lobby_data.get(chat_id, {}).get('players', [])) >= 2
        if not is_multi:
            await msg.reply_text(f"✅ {update.effective_user.first_name} Benar! (Tapi poin 0 karena main sendiri).")
        else:
            s_uid = str(uid)
            if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}
            pts = 15 if (time.time() - game['start_time']) < 5 else 10
            db['users'][s_uid]['pts'] += pts; save_db()
            await msg.reply_text(f"🎯 {update.effective_user.first_name} (+{pts} Pts)")
        
        del current_games[chat_id]; await asyncio.sleep(2); await send_question(context, chat_id, game['cat'])

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; d = q.data; cid = q.message.chat_id; uid = q.from_user.id
    
    if d == "lobby_join":
        if cid in lobby_data and uid not in lobby_data[cid]['players']:
            lobby_data[cid]['players'].append(uid); lobby_data[cid]['names'].append(q.from_user.first_name)
            players_str = "\n".join([f"{i+1}. {name}" for i, name in enumerate(lobby_data[cid]['names'])])
            kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="lobby_join")], [InlineKeyboardButton("Mulai ▶️", callback_data="lobby_start")]]
            await q.message.edit_text(f"🎮 **LOBBY KUIS**\n\nPlayer: \n{players_str}", reply_markup=InlineKeyboardMarkup(kb))
        await q.answer()
    
    elif d == "lobby_start":
        if cid in lobby_data:
            if uid != lobby_data[cid]['host']: return await q.answer("Hanya Host yang bisa mulai!", show_alert=True)
            kb = [[InlineKeyboardButton(f"📂 {c}", callback_data=f"start_{c}")] for c in db['questions'].keys()]
            await q.message.edit_text("PILIH KATEGORI:", reply_markup=InlineKeyboardMarkup(kb))
        await q.answer()

    elif d.startswith('start_'):
        await q.message.delete(); await send_question(context, cid, d.split('_')[1])

    elif d == 'adm_q':
        kb = [[InlineKeyboardButton(c, callback_data=f"sel_cat_{c}")] for c in db['questions'].keys()]
        kb.append([InlineKeyboardButton("➕ Kategori Baru", callback_data="new_cat")])
        await q.message.reply_text("Pilih Kategori:", reply_markup=InlineKeyboardMarkup(kb)); await q.answer()

    elif d.startswith('sel_cat_'):
        context.user_data['state'] = 'w_q_ques'; context.user_data['new_q'] = {"cat": d.replace('sel_cat_', '')}
        await q.message.reply_text("Kirim Soalnya:"); await q.answer()
        
    elif d == "new_cat":
        context.user_data['state'] = 'w_q_cat_name'; await q.message.reply_text("Kirim Nama Kategori (Contoh: 🦁 Hewan):"); await q.answer()

    elif d == 'adm_db': save_db(); await q.message.reply_document(open(DATA_FILE, 'rb')); await q.answer()
    elif d == 'adm_ads': context.user_data['state'] = 'w_ads'; await q.message.reply_text("Kirim Iklan (Foto+Teks):"); await q.answer()
    elif d == 'adm_bc': context.user_data['state'] = 'w_bc'; await q.message.reply_text("Kirim BC:"); await q.answer()
    elif d == 'game_skip': 
        current_games[cid]['task'].cancel(); cat = current_games[cid]['cat']
        del current_games[cid]; await send_question(context, cid, cat); await q.answer()
    elif d == 'game_stop': 
        current_games[cid]['task'].cancel(); del current_games[cid]; await q.message.reply_text("Stop."); await q.answer()

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL, handle_msg))
    app.run_polling()

if __name__ == '__main__': main()
