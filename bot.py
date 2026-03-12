import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when /start is used."""
    if not update.message:
        return
    await update.message.reply_text(
        "Bot is online.\n"
        "Use /help to see commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a short help message."""
    if not update.message:
        return
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/ping - Health check\n\n"
        "Send any text message and I will echo it."
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple health-check command."""
    if not update.message:
        return
    await update.message.reply_text("pong")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo user text messages."""
    if not update.message or not update.message.text:
        return
    await update.message.reply_text(update.message.text)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log exceptions raised by handlers."""
    logger.exception("Unhandled exception while processing update", exc_info=context.error)


def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Missing TELEGRAM_BOT_TOKEN. Create a .env file or export the variable."
        )

    app = build_application(token)
    logger.info("Starting Telegram bot polling...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
