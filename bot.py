import os
import random
import logging
import asyncio
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
# Markov Chain ordine 2
# ---------------------------------------------------------------------------

class MarkovChain:
    def __init__(self):
        # chiave: (parola1, parola2) → lista di parole successive
        self.model: dict[tuple, list] = defaultdict(list)
        self.start_pairs: list[tuple] = []
        self.message_count: int = 0

    def learn(self, text: str):
        """Apprende una singola frase."""
        text = text.strip()
        if not text:
            return
        words = text.split()
        if len(words) < 3:
            return
        self.start_pairs.append((words[0], words[1]))
        for i in range(len(words) - 2):
            key = (words[i], words[i + 1])
            self.model[key].append(words[i + 2])
        # marcatore di fine frase
        self.model[(words[-2], words[-1])].append(None)
        self.message_count += 1

    def generate(self, max_words: int = 40) -> str | None:
        """Genera una frase casuale. Restituisce None se il modello è vuoto."""
        if not self.start_pairs:
            return None

        pair = random.choice(self.start_pairs)
        result = list(pair)

        for _ in range(max_words - 2):
            nexts = self.model.get(pair)
            if not nexts:
                break
            next_word = random.choice(nexts)
            if next_word is None:
                break
            result.append(next_word)
            pair = (pair[1], next_word)

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
    msg = update.message
    if not msg or not msg.text:
        return
    get_chain(msg.chat_id).learn(msg.text)


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

    chain = get_chain(msg.chat_id)

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
        await context.bot.send_message(chat_id=msg.chat_id, text=frase)


# ---------------------------------------------------------------------------
# Handler: /start, /help, /stats
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Sono il MarkovBot!\n\n"
        "Imparo da tutti i messaggi scritti nel gruppo e genero frasi casuali su comando.\n\n"
        "📋 Comandi:\n"
        "• /pablitoo — genera una frase\n"
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
        f"🔑 Coppie uniche: *{len(chain.model)}*\n"
        f"🔀 Coppie iniziali: *{len(chain.start_pairs)}*",
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
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("pablitoo", cmd_genera))
    app.add_handler(CommandHandler("stats", cmd_stats))

    logger.info("Bot avviato")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    stop_event = asyncio.Event()
    await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
