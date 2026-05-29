# 🤖 MarkovBot for Telegram

Bot Telegram che apprende in tempo reale dai messaggi del gruppo e genera frasi casuali con catene di Markov.

---

## ⚡ Setup

### 1. Installa le dipendenze
```bash
pip install -r requirements.txt
```

### 2. Crea il bot con @BotFather
1. Apri Telegram → cerca **@BotFather**
2. Invia `/newbot` e segui le istruzioni
3. Copia il **token**

### 3. Imposta il token
```bash
export TELEGRAM_BOT_TOKEN="il_tuo_token"
```

### 4. Avvia
```bash
python bot.py
```

### 5. Aggiungi al gruppo come Admin
Il bot **deve essere admin** del gruppo per poter cancellare il messaggio `/genera`.  
Permessi necessari: **Elimina messaggi**.

---

## 📋 Comandi

| Comando | Descrizione |
|---|---|
| `/genera` | Cancella il comando e genera una frase |
| `/genera 80` | Genera una frase con max 80 parole |
| `/stats` | Statistiche (messaggi appresi, token) |

---

## ☁️ Deploy su Render (Background Worker)

1. Crea un repo GitHub con i file `bot.py` e `requirements.txt`
2. Vai su [render.com](https://render.com) → **New → Background Worker**
3. Collega il repo GitHub
4. Imposta:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
5. In **Environment Variables** aggiungi `TELEGRAM_BOT_TOKEN`
6. Clicca **Create** — il bot girerà 24/7

> ⚠️ Scegli **Background Worker** (non Web Service): è pensato per processi sempre attivi senza porta HTTP.

---

## Note

- Il modello è **in memoria**: se il bot si riavvia, riparte da zero
- Funziona su **più gruppi contemporaneamente** (modello separato per chat)
- Ignora i comandi (`/...`) nell'apprendimento
