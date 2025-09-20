# Couples Coach Telethon Bot

This repository ships a metric-first MVP for a Telegram couples coach. It wires a
Telethon bot, SQLite storage, metrics heuristics, and automated advice so you
can run a supportive companion for a shared couple chat and each partner's DM.

## Quick start

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and disable
   privacy mode so the bot can read group messages.
2. Copy `.env.example` to `.env` and fill in the required values.
3. Bootstrap the database:

   ```bash
   make setup
   make seed
   ```

4. Start the bot:

   ```bash
   make run
   ```

The entry point (`python -m couples_bot.app`) connects to Telegram, runs
migrations, and prints a mini guide. The bot listens to a shared group and the
partners' DMs.

## Environment variables

| Key | Description |
| --- | ----------- |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Telegram API credentials from https://my.telegram.org. |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather. |
| `BOT_OWNER_USER_ID` | Telegram user id for admin commands. |
| `ENABLE_LLM` | `1` to enable LLM features; `0` for rule-based advice only. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Defaults to `o4-mini`. |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq fallback (default `openai/gpt-oss-120b`). |
| `DEFAULT_TZ` | Olson timezone name for couples without explicit tz. |
| `LOG_LEVEL` | Python logging level (e.g. `INFO`). |
| `DATABASE_PATH` | SQLite path (default `couples.sqlite`). |

## Linking a couple

1. Add the bot to the couple's shared group chat.
2. In the group chat, run `/link @partnerA @partnerB`.
3. Each partner must DM the bot `/consent yes`. The bot only starts tracking
   once both have opted in.
4. Partners can DM `/status` or `/advice` to view metrics or refresh advice.

### Consent & privacy controls

- `/forget` wipes a partner's personal data and revokes consent.
- `/pause` stops tracking without unlinking the couple.
- `/resume` restarts tracking.
- `/export` dumps recent logs.

## Metrics and alerts

The pipeline logs every message, labels it with lexicon-based heuristics, and
computes 18 relationship metrics. Eight are fully implemented in the MVP and
the remainder return placeholder zeros with TODO notes.

Instant DMs fire when thresholds cross:

- **Green (praise)**: repair successes, turning toward bids, positive conflict
  ratio.
- **Red (risk)**: harsh starts, contempt flags, boundary issues.
- **Blue (logistics)**: SLA misses, plan slips.

Cooldowns, partner Do-Not-Disturb windows, and daily caps prevent spam.

## Advice generation

Advice blocks per partner refresh every ~10 minutes or after 50 messages. By
default the bot calls OpenAI `o4-mini`. If OpenAI is unavailable, it falls back
to Groq `openai/gpt-oss-120b`. When a caller requests tool use, the provider
switches to `groq/compound` and enables the requested tools via the
`compound_custom.tools.enabled_tools` payload.

To force Groq usage (or configure tools), set `ENABLE_LLM=1`, provide a
`GROQ_API_KEY`, and (optionally) set `OPENAI_API_KEY` blank so the fallback is
used.

If both providers are disabled, the advice engine automatically falls back to a
rule-based summary derived from metric deltas.

## Development

- `make setup` – install dependencies.
- `make seed` – apply migrations and seed default thresholds.
- `make run` – start the bot.
- `make test` – run the pytest suite.
- `make fmt` – placeholder formatting target.

Tests ship with synthetic sample data to validate the metrics, alert cooldowns,
and LLM provider fallback.

