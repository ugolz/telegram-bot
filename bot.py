import os
import random
import logging
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
# Markov Chain (ordine 1) — una istanza per ogni chat
# ---------------------------------------------------------------------------

class MarkovChain:
    def __init__(self):
        self.model: dict[str, list[str | None]] = defaultdict(list)
        self.start_words: list[str] = []
        self.message_count: int = 0

    def learn(self, text: str):
        """Apprende una singola frase."""
        text = text.strip()
        if not text:
            return
        words = text.split()
        if len(words) < 2:
            return
        self.start_words.append(words[0])
        for i in range(len(words) - 1):
            self.model[words[i]].append(words[i + 1])
        self.model[words[-1]].append(None)
        self.message_count += 1

    def generate(self, max_words: int = 40) -> str | None:
        """Genera una frase. Restituisce None se il modello è vuoto."""
        if not self.start_words:
            return None
        word = random.choice(self.start_words)
        result = [word]
        for _ in range(max_words - 1):
            nexts = self.model.get(word)
            if not nexts:
                break
            word = random.choice(nexts)
            if word is None:
                break
            result.append(word)
        return " ".join(result)


# Dizionario chat_id → MarkovChain
chains: dict[int, MarkovChain] = {}

def get_chain(chat_id: int) -> MarkovChain:
    if chat_id not in chains:
        chains[chat_id] = MarkovChain()
    return chains[chat_id]


# ---------------------------------------------------------------------------
# Handler: apprende da ogni messaggio
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ascolta tutti i messaggi di testo e aggiorna il modello."""
    msg = update.message
    if not msg or not msg.text:
        return
    # Ignora comandi
    if msg.text.startswith("/"):
        return

    chain = get_chain(msg.chat_id)
    chain.learn(msg.text)


# ---------------------------------------------------------------------------
# Handler: /genera
# ---------------------------------------------------------------------------

async def cmd_genera(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancella il comando e genera una frase Markov."""
    msg = update.message
    if not msg:
        return

    # Prova a cancellare il messaggio di trigger
    try:
        await msg.delete()
    except BadRequest as e:
        logger.warning(f"Non riesco a cancellare il messaggio: {e}")

    chain = get_chain(msg.chat_id)

    # Lunghezza opzionale: /genera 80
    max_words = 40
    if context.args:
        try:
            max_words = max(5, min(200, int(context.args[0])))
        except ValueError:
            pass

    frase = chain.generate(max_words=max_words)

    if frase is None:
        await context.bot.send_message(
            chat_id=msg.chat_id,
            text="🤔 Non ho ancora abbastanza messaggi da cui imparare. Scrivi un po' nel gruppo!"
        )
    else:
        await context.bot.send_message(
            chat_id=msg.chat_id,
            text=frase
        )


# ---------------------------------------------------------------------------
# Handler: /start e /help
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Sono il MarkovBot!\n\n"
        "Imparo da tutti i messaggi scritti nel gruppo e genero frasi casuali su comando.\n\n"
        "📋 Comandi:\n"
        "• /genera — genera una frase\n"
        "• /genera 80 — genera una frase (max 80 parole)\n"
        "• /stats — statistiche sul modello\n\n"
        "⚙️ Per funzionare correttamente devo essere *admin* del gruppo "
        "(così posso cancellare il messaggio di trigger).",
        parse_mode="Markdown"
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chain = get_chain(update.message.chat_id)
    if chain.message_count == 0:
        await update.message.reply_text("📊 Nessun messaggio appreso finora.")
        return
    await update.message.reply_text(
        f"📊 *Statistiche*\n\n"
        f"💬 Messaggi appresi: *{chain.message_count}*\n"
        f"🔑 Token unici: *{len(chain.model)}*\n"
        f"🔀 Parole iniziali: *{len(chain.start_words)}*",
        parse_mode="Markdown"
    )


# ---------------------------------------------------------------------------
# Avvio
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "Variabile d'ambiente TELEGRAM_BOT_TOKEN non impostata.\n"
            "Esegui: export TELEGRAM_BOT_TOKEN='il_tuo_token'"
        )

    app = ApplicationBuilder().token(token).build()

    # Apprende da tutti i messaggi di testo (non comandi)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("genera", cmd_genera))
    app.add_handler(CommandHandler("stats", cmd_stats))

    logger.info("MarkovBot avviato. In ascolto…")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
