# Telegram alerts setup

The tracker sends price-drop / new-low / target alerts to Telegram. You need
two values in your `.env`:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Option A — reuse your stock-bot's bot (fastest)
If you already have a working Telegram bot for the stock-bot, just copy the
same `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from that project's `.env`
into this one. Trip alerts will arrive in the same chat.

## Option B — create a new bot
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the
   **bot token** it gives you.
2. Send any message to your new bot (so it can message you back).
3. Message **@userinfobot** (or open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser) to find your
   numeric **chat id**.
4. Put both into `.env`.

## Verify
- Restart the app (env vars load at startup), then click **🔔 Send test alert**
  in the sidebar. You should get a Telegram message.
- Or run a real check (`🔍 Check prices now`) — alerts fire on drops/new lows.
