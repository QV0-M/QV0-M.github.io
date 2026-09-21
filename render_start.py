import os

from telegram.ext import Application

# The existing bot.py uses run_polling().
# Render Web Services need an HTTP listener, so we transparently
# replace run_polling() with Telegram webhook mode at startup.
_original_run_polling = Application.run_polling


def _run_webhook_on_render(self, *args, **kwargs):
    port = int(os.environ.get("PORT", "10000"))
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

    if not base_url:
        # Local fallback: keep the normal polling behavior.
        return _original_run_polling(self, *args, **kwargs)

    webhook_url = f"{base_url}/telegram-webhook"

    print(f"Starting Telegram webhook on port {port}")
    print(f"Webhook URL: {webhook_url}")

    return self.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram-webhook",
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


Application.run_polling = _run_webhook_on_render

import bot

bot.main()
