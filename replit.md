# Telegram Bot

A simple Telegram bot built with Python using the `python-telegram-bot` library.

## Setup

- **Language**: Python 3.12
- **Library**: python-telegram-bot v22
- **Entry point**: `bot.py`

## Environment Variables

- `TELEGRAM_BOT_TOKEN` — Your bot token from @BotFather (stored as a Replit secret)

## Features

- `/start` — Greets the user
- `/help` — Lists available commands
- `/echo <text>` — Echoes the provided text
- Any plain text message — Bot repeats it back

## Running

The bot runs via the "Start application" workflow using `python bot.py`.
It uses long polling to receive updates from Telegram.
