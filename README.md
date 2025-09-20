# Couples Coach Telethon Bot

This repository contains a metric-first couples coaching bot powered by [Telethon](https://github.com/LonamiWebs/Telethon). The bot listens to a couple's shared group chat and private DMs, computes relational health metrics, maintains living advice blocks, and delivers instant feedback when important thresholds are crossed.

## Quick start

1. **Clone** this repository and create a Python 3.11 virtual environment.
2. **Install dependencies** with:
   ```bash
   make setup
   ```
3. **Configure environment variables**:
   - Copy `.env.example` to `.env` and fill in the secrets provided by Telegram and your LLM vendors.
   - Ensure the bot user created in [BotFather](https://t.me/BotFather) has privacy mode **disabled** so it can read group messages.
4. **Bootstrap the database**:
   ```bash
   make seed
   ```
5. **Run the bot**:
   ```bash
   make run
   ```
   The entrypoint (`python -m couples_bot.app`) runs migrations, prints a mini setup guide, and starts the Telethon event loop.

## Environment variables

| Key | Description |
| --- | ----------- |
| `TELEGRAM_API_ID` | Telegram API ID (from https://my.telegram.org). |
| `TELEGRAM_API_HASH` | Telegram API hash. |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather. |
| `BOT_OWNER_USER_ID` | Telegram user ID allowed to run admin commands. |
| `ENABLE_LLM` | `true` to enable LLM-powered advice, otherwise uses rule heuristics. |
| `OPENAI_API_KEY` | API key for OpenAI. |
| `OPENAI_MODEL` | Defaults to `o4-mini`. |
| `GROQ_API_KEY` | API key for Groq fallback. |
| `GROQ_MODEL` | Defaults to `openai/gpt-oss-120b`. |
| `DEFAULT_TZ` | Default timezone for couples, e.g., `America/New_York`. |
| `LOG_LEVEL` | Logging level (default `INFO`). |
| `DATABASE_PATH` | Path to the SQLite database file (default `./couples_bot.db`). |

The `Settings` class in `couples_bot/config.py` loads these values from the environment or `.env` file.

## Linking a couple

1. Add the bot to the shared Telegram group and ensure privacy mode is off.
2. In the group chat, an admin runs `/link @PartnerA @PartnerB`.
3. Each partner sends the bot a DM: `/consent yes`.
4. Either partner can DM `/status` or `/advice` to view the latest metrics and guidance.

## Advice blocks & instant alerts

- Advice blocks refresh every ten minutes (or after fifty new messages) per partner and include: one empathy sentence, one concrete action, and a suggested phrasing.
- Instant DM alerts fire for praise (green), risk (red), or logistics (blue) when computed metrics cross configured thresholds. Alerts respect DND windows, daily caps, and per-metric cooldowns.

## LLM fallback behavior

`couples_bot.llm.provider.llm_complete` attempts to use OpenAI first. If OpenAI is disabled or returns an error, the call automatically falls back to Groq:

- **Standard completions** use `openai/gpt-oss-120b` with the same parameters.
- **Tool-enabled completions** switch to `groq/compound` and pass `compound_custom={"tools": {"enabled_tools": [...]}}` using the provided `enabled_tools` tuple.

When both providers are unavailable, an `LLMDisabled` exception is raised and the advice engine falls back to rule-based summaries.

### Enabling Groq compound tools

Set `ENABLE_LLM=true` and provide `GROQ_API_KEY`. When `llm_complete` is invoked with `use_tools=True`, ensure you pass the allowed tool names in `enabled_tools`; the provider will route the request to `groq/compound` with the proper payload (`compound_custom.tools.enabled_tools`).

## Running tests

```
make test
```

The repository ships with synthetic data in `tests/samples/conversation.jsonl` so the metric computations and alert pipelines can be exercised without external services.
