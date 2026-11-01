# Telegram bot setup: copy-paste texts

## Name (shown in chats)
رصد · Rasd

## Username
Set `TELEGRAM_BOT_USERNAME` in `.env` to the bot's username (without `@`). The dashboard uses it for the one-tap
link button (`https://t.me/<username>?start=<code>`).

## Profile photo
Use the Rasd radar mark from the brand assets (640×640).

## About, description and commands
The bot sets these itself on startup, in English and Arabic (`telegram/main.py`: `COMMANDS`, `DESCRIPTION`,
`SHORT_DESCRIPTION`); Telegram shows the Arabic texts to users whose app language is Arabic. Nothing to do in
BotFather. Commands: /start /new /campaigns /top /balance /lang /help.

## Linking flow
1. The user opens the dashboard → Settings → Telegram and presses “Generate linking code”.
2. “Open the bot and link” opens `t.me/<bot>?start=<code>`; the bot links the account at once. Sending
   `/link CODE` still works.
3. Links made by non-admin members wait for an admin's approval.
