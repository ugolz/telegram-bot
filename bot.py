import os
import pickle
import random
import logging
import asyncio
import unicodedata
from collections import defaultdict
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

# Cache in memoria: chat_id → dict
chains: dict[int, dict] = {}

def get_chain(chat_id: int) -> dict:
    if chat_id not in chains:
        chains[chat_id] = load_chain(chat_id)
    return chains[chat_id]

# ---------------------------------------------------------------------------
# Caratteri Unicode ammessi (come nell'originale)
# ---------------------------------------------------------------------------

ALLOWABLE = {"Lc","Ll","Lm","Lo","Lt","Lu","Nd","Nl","No"}

def normalize_word(w: str) -> str:
    """Filtra i caratteri non-alfabetici/numerici e porta in minuscolo."""
    return "".join(c for c in w if unicodedata.category(c) in ALLOWABLE).lower()

# ---------------------------------------------------------------------------
# Logica Markov (ordine 1, stile SexyMarkovBot)
# ---------------------------------------------------------------------------

def add_message(message: str, g: dict):
    """
    Aggiunge un messaggio al modello.
    Struttura: g[parola_precedente] = [parola_successiva, ...]
    La chiave "" rappresenta l'inizio/fine frase.
    """
    words = [""] + message.lower().split() + [""]
    for i in range(1, len(words)):
        lw = normalize_word(words[i - 1])   # parola precedente (chiave)
        nw = words[i]                        # parola successiva (valore)
        if len(lw) < 50 and len(nw) < 50:
            if lw not in g:
                g[lw] = []
            g[lw].append(nw)

def generate(g: dict, max_words: int = 50) -> str | None:
    """
    Genera una frase con logica ibrida:
    - 50%: parte da una parola casuale qualsiasi nel vocabolario
    - 50%: parte dall'inizio frase ("") come nell'originale
    """
    if "" not in g:
        return None

    for _ in range(1000):
        words = []

        # scegli punto di partenza
        if random.randint(0, 10) < 5:
            # parte da una parola casuale del vocabolario
            word = random.choice([k for k in g.keys() if isinstance(k, str)])
        else:
            # parte dall'inizio frase
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
# Handler: apprende da ogni messaggio
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    g = get_chain(msg.chat_id)
    add_message(msg.text, g)
    # salva ogni 20 messaggi circa per non stressare il disco
    msg_count = sum(len(v) for v in g.values())
    if msg_count % 20 == 0:
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
# Handler: /markovclear (solo admin)
# ---------------------------------------------------------------------------

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id

    # verifica che sia admin
    try:
        member = await context.bot.get_chat_member(chat_id, msg.from_user.id)
        if member.status not in ("administrator", "creator"):
            await msg.reply_text("⛔ Solo gli admin possono usare questo comando.")
            return
    except Exception:
        pass

    chains[chat_id] = {}
    save_chain(chat_id, {})
    await msg.reply_text("🗑️ Modello azzerato.")

# ---------------------------------------------------------------------------
# Handler: /markovpause e /markovresume (solo admin)
# ---------------------------------------------------------------------------

PAUSED: set[int] = set()

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
    total_transitions = sum(len(v) for v in g.values())
    await update.message.reply_text(
        f"📊 *Statistiche*\n\n"
        f"🔑 Parole uniche: *{len(g)}*\n"
        f"🔀 Transizioni totali: *{total_transitions}*\n"
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

    # apprende solo se non in pausa
    async def handle_message_paused(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.chat_id in PAUSED:
            return
        await handle_message(update, context)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_paused))
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_start))
    app.add_handler(CommandHandler("pablitoo",      cmd_genera))
    app.add_handler(CommandHandler("stats",         cmd_stats))
    app.add_handler(CommandHandler("markovclear",   cmd_clear))
    app.add_handler(CommandHandler("markovpause",   cmd_pause))
    app.add_handler(CommandHandler("markovresume",  cmd_resume))

    logger.info("Bot avviato")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
