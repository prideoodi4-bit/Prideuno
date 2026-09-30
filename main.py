import logging
import os

from uno_bot.bot import build_app

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is required")
    app = build_app(token)
    app.run_polling(allowed_updates=None, drop_pending_updates=False)


if __name__ == "__main__":
    main()
