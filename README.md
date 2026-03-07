# 🤖 BillyBot Telegram Bot — Phase 3

Telegram interface for BillyBot. Commands, AI chat, and daily reminders.

---

## Setup

### 1. Create your bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot`, follow prompts
3. Copy the token → `TELEGRAM_BOT_TOKEN`
4. Send `/setcommands` and paste:
```
start - Connect your account
bills - Unpaid bills this month
all - All bills (paid + unpaid)
owe - Total amount owed
summary - Monthly progress
paid - Mark a bill as paid
ask - Ask BillyBot AI a question
remind - Your reminder settings
help - All commands
```

### 2. Generate BOT_SECRET
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```
Add to **both** `billybot-backend/.env` AND `billybot-telegram/.env`.

### 3. Local dev
```bash
cd billybot-telegram
pip install -r requirements.txt
cp .env.example .env
# Fill in .env
python bot.py
```

### 4. Deploy to Railway
1. Push `billybot-telegram/` to a GitHub repo (can be same repo, different folder)
2. Railway → New Service → GitHub repo
3. Set **Start Command**: `python bot.py`
4. Add environment variables from `.env.example`
5. Deploy — Railway runs it as a persistent worker

---

## Auth Flow

```
User messages /start in Telegram
  ↓
Bot generates one-time link token → POST /api/telegram/token
Bot sends user a button: "Connect My Account" → dashboard.html?token=xxx
  ↓
User opens link, logs into dashboard (if not already)
Dashboard detects ?token=xxx → calls POST /api/telegram/connect
Backend stores telegram_chat_id in reminder_settings
  ↓
Bot now knows who this user is via GET /api/telegram/user/:chatId
All commands work
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome + connect account |
| `/bills` | Unpaid bills sorted by urgency |
| `/all` | All bills this month |
| `/owe` | Total unpaid amount |
| `/summary` | Progress bar + monthly stats |
| `/paid rent` | Mark bill as paid (fuzzy match) |
| `/ask what's due this week?` | AI chat with full bill context |
| `/remind` | View reminder settings |
| `/help` | All commands |

Plain text messages also route to `/ask` automatically.

---

## Reminder Schedule

Daily at 8:00 AM Eastern via APScheduler.
Finds all users with `telegram_chat_id` set.
Sends messages for bills where `days_until_due` is in their `days_before` list.
