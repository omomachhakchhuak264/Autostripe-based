# Telegram Bot Starter

This repository now includes a safe Telegram bot starter implementation.

## Files

- `bot.py` - bot entrypoint and handlers
- `requirements.txt` - Python dependencies
- `.env.example` - environment variable template

## Setup

1. Create and activate a virtual environment (recommended):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create your env file:

   ```bash
   cp .env.example .env
   ```

4. Edit `.env` and set `TELEGRAM_BOT_TOKEN` to your real token from BotFather.

## Run

```bash
python3 bot.py
```

## Commands

- `/start` - start bot
- `/help` - command list
- `/ping` - health check

Any non-command text message is echoed back.
