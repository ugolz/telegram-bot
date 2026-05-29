import os
import json
import pickle
import random
import logging
import asyncio
import unicodedata
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import BadRequest

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistenza su disco
# ---------------------------------------------------------------------------

DATA_DIR = "markov_data"
os.makedirs(DATA_DIR, exist_ok=True)

def db_path(chat_id: int) -> str:
    return os.path.join(DATA_DIR, f"chat_{chat_id}.pkl")

def load_chain(chat_id: int) -> dict:
    try:
        with open(db_path(chat_id), "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}

def save_chain(chat_id: int, g: dict):
    try:
        with open(db_path(chat_id), "wb") as f:
            pickle.dump(g, f)
    except Exception as e:
        logger.warning(f"Errore salvataggio chat {chat_id}: {e}")

chains: dict[int, dict] = {}

def get_chain(chat_id: int) -> dict:
    if chat_id not in chains:
        chains[chat_id] = load_chain(chat_id)
    return chains[chat_id]

# ---------------------------------------------------------------------------
# Caratteri Unicode ammessi
# ---------------------------------------------------------------------------

ALLOWABLE = {"Lc","Ll","Lm","Lo","Lt","Lu","Nd","Nl","No"}

def normalize_word(w: str) -> str:
    return "".join(c for c in w if unicodedata.category(c) in ALLOWABLE).lower()

# ---------------------------------------------------------------------------
# Logica Markov
# ---------------------------------------------------------------------------

def add_message(message: str, g: dict):
    words = [""] + message.lower().split() + [""]
    for i in range(1, len(words)):
        lw = normalize_word(words[i - 1])
        nw = words[i]
        if len(lw) < 50 and len(nw) < 50:
            if lw not in g:
                g[lw] = []
            g[lw].append(nw)

def generate(g: dict, max_words: int = 50) -> str | None:
    if "" not in g:
        return None
    for _ in range(1000):
        words = []
        if random.randint(0, 10) < 5:
            word = random.choice([k for k in g.keys() if isinstance(k, str)])
        else:
            word = random.choice(g[""])
        while word != "" and len(words) < max_words:
            words.append(word)
            key = normalize_word(word)
            if key not in g:
                break
            word = random.choice(g[key])
        msg = " ".join(words)
        if len(msg) > 0:
            return msg
    return None

# ---------------------------------------------------------------------------
# Caricamento cronologia Telegram (JSON export)
# ---------------------------------------------------------------------------

def load_history_json(path: str, chat_id: int) -> int:
    """Legge result.json di Telegram Desktop e popola il modello."""
    g = get_chain(chat_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Impossibile leggere {path}: {e}")
        return 0

    raw = data.get("messages", data) if isinstance(data, dict) else data
    count = 0
    for msg in raw:
        if not isinstance(msg, dict):
            continue
        text = msg.get("text", "")
        if isinstance(text, list):
            text = "".join(
                part if isinstance(part, str) else part.get("text", "")
                for part in text
            )
        text = text.strip()
        if text and not text.startswith("/"):
            add_message(text, g)
            count += 1

    save_chain(chat_id, g)
    logger.info(f"Cronologia caricata: {count} messaggi da {path}")
    return count

# ---------------------------------------------------------------------------
# Handler: apprende da ogni messaggio
# ---------------------------------------------------------------------------

PAUSED: set[int] = set()
msg_counters: dict[int, int] = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    if msg.chat_id in PAUSED:
        return
    g = get_chain(msg.chat_id)
    add_message(msg.text, g)
    msg_counters[msg.chat_id] = msg_counters.get(msg.chat_id, 0) + 1
    if msg_counters[msg.chat_id] % 20 == 0:
        save_chain(msg.chat_id, g)

# ---------------------------------------------------------------------------
# Handler: /pablitoo
# ---------------------------------------------------------------------------

async def cmd_genera(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    try:
        await msg.delete()
    except BadRequest as e:
        logger.warning(f"Non riesco a cancellare il messaggio: {e}")

    g = get_chain(msg.chat_id)
    max_words = 50
    if context.args:
        try:
            max_words = max(5, min(120, int(context.args[0])))
        except ValueError:
            pass

    frase = generate(g, max_words=max_words)
    if frase is None:
        await context.bot.send_message(
            chat_id=msg.chat_id,
            text="🤔 Non ho ancora abbastanza messaggi. Scrivi un po' nel gruppo!"
        )
    else:
        await context.bot.send_message(chat_id=msg.chat_id, text=frase)

# ---------------------------------------------------------------------------
# Handler: /carica — carica la cronologia dal JSON
# ---------------------------------------------------------------------------

async def cmd_carica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # solo admin
    try:
        member = await context.bot.get_chat_member(msg.chat_id, msg.from_user.id)
        if member.status not in ("administrator", "creator"):
            await msg.reply_text("⛔ Solo gli admin possono usare questo comando.")
            return
    except Exception:
        pass

    path = os.environ.get("CORPUS_PATH", "result.json")
    if not os.path.exists(path):
        await msg.reply_text(
            f"❌ File non trovato: `{path}`\n"
            "Imposta la variabile d'ambiente `CORPUS_PATH` con il percorso del file JSON.",
            parse_mode="Markdown"
        )
        return

    await msg.reply_text("⏳ Caricamento cronologia in corso…")
    count = load_history_json(path, msg.chat_id)
    g = get_chain(msg.chat_id)
    await msg.reply_text(
        f"✅ Caricati *{count}* messaggi dalla cronologia!\n"
        f"🔑 Parole uniche nel modello: *{len(g)}*",
        parse_mode="Markdown"
    )

# ---------------------------------------------------------------------------
# Handler: /markovclear, /markovpause, /markovresume
# ---------------------------------------------------------------------------

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    try:
        member = await context.bot.get_chat_member(msg.chat_id, msg.from_user.id)
        if member.status not in ("administrator", "creator"):
            await msg.reply_text("⛔ Solo gli admin possono usare questo comando.")
            return
    except Exception:
        pass
    chains[msg.chat_id] = {}
    save_chain(msg.chat_id, {})
    await msg.reply_text("🗑️ Modello azzerato.")

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    try:
        member = await context.bot.get_chat_member(msg.chat_id, msg.from_user.id)
        if member.status not in ("administrator", "creator"):
            await msg.reply_text("⛔ Solo gli admin possono usare questo comando.")
            return
    except Exception:
        pass
    PAUSED.add(msg.chat_id)
    await msg.reply_text("⏸️ Raccolta messaggi in pausa.")

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    try:
        member = await context.bot.get_chat_member(msg.chat_id, msg.from_user.id)
        if member.status not in ("administrator", "creator"):
            await msg.reply_text("⛔ Solo gli admin possono usare questo comando.")
            return
    except Exception:
        pass
    PAUSED.discard(msg.chat_id)
    await msg.reply_text("▶️ Raccolta messaggi ripresa.")

# ---------------------------------------------------------------------------
# Handler: /start, /help, /stats
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Sono il MarkovBot!\n\n"
        "Imparo da tutti i messaggi del gruppo e genero frasi casuali.\n\n"
        "📋 Comandi:\n"
        "• /pablitoo — genera una frase\n"
        "• /pablitoo 80 — genera una frase (max 80 parole)\n"
        "• /carica — carica la cronologia dal JSON export (solo admin)\n"
        "• /stats — statistiche sul modello\n"
        "• /markovclear — azzera il modello (solo admin)\n"
        "• /markovpause — pausa raccolta (solo admin)\n"
        "• /markovresume — riprendi raccolta (solo admin)\n\n"
        "⚙️ Devo essere *admin* del gruppo per cancellare il trigger.",
        parse_mode="Markdown"
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    g = get_chain(update.message.chat_id)
    if not g:
        await update.message.reply_text("📊 Nessun messaggio appreso finora.")
        return
    total = sum(len(v) for v in g.values())
    await update.message.reply_text(
        f"📊 *Statistiche*\n\n"
        f"🔑 Parole uniche: *{len(g)}*\n"
        f"🔀 Transizioni totali: *{total}*\n"
        f"⏸️ Pausa: *{'sì' if update.message.chat_id in PAUSED else 'no'}*",
        parse_mode="Markdown"
    )

# ---------------------------------------------------------------------------
# Avvio
# ---------------------------------------------------------------------------

async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN non impostato")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_start))
    app.add_handler(CommandHandler("pablitoo",     cmd_genera))
    app.add_handler(CommandHandler("carica",       cmd_carica))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("markovclear",  cmd_clear))
    app.add_handler(CommandHandler("markovpause",  cmd_pause))
    app.add_handler(CommandHandler("markovresume", cmd_resume))

    logger.info("Bot avviato")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
