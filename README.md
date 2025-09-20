# Couples Coach Telethon Bot

This repository ships a metric-first MVP for a Telegram couples coach. It
combines a Telethon bot, SQLite storage, heuristics-driven scorecard, automated
advice, and background reasoning jobs so you can run a supportive companion for
a shared couple chat and each partner's DM.

## Quick start

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and **disable
   privacy mode** so the bot can read group messages.
2. Copy `.env.example` to `.env` and fill in the required values.
3. Bootstrap the database and seed thresholds:

   ```bash
   make setup
   make seed
   ```

4. Start the hot-lane bot (group + DM handlers):

   ```bash
   make run
   ```

5. In a separate terminal run the background REAG worker:

   ```bash
   make worker
   ```

The entry point (`python -m couples_bot.app`) connects to Telegram, runs
migrations, registers handlers, ticks the REAG scheduler, and prints a mini
guide. The worker (`python -m workers.reag_worker`) drains the reasoning queue
and applies model outputs to advice, metrics, and optional graph storage.

## Environment variables

| Key | Description |
| --- | ----------- |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Telegram API credentials from https://my.telegram.org. |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather. |
| `BOT_OWNER_USER_ID` | Telegram user id for admin commands. |
| `ENABLE_LLM` | `1` to enable LLM features; `0` for rule-based advice only. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Primary provider (default `o4-mini`). |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq fallback for plain chat (default `openai/gpt-oss-120b`). |
| `GROQ_FALLBACK_MODEL` | Model used when the REAG queue is under backpressure (default `llama-3.3-70b-versatile`). |
| `DEFAULT_TZ` | Olson timezone name for couples without explicit tz. |
| `LOG_LEVEL` | Python logging level (e.g. `INFO`). |
| `DATABASE_PATH` | SQLite path (default `couples.sqlite`). |
| `REAG_SILENCE_SECS` | Required quiet window before enqueuing a REAG job (default `180`). |
| `REAG_MIN_INTERVAL_SECS` | Minimum spacing between REAG jobs per couple (default `300`). |
| `REAG_QUEUE_HIGH_WATERMARK` | Pending job count that triggers backpressure routing (default `12`). |
| `REAG_MAX_OUT_TOKENS` | Max completion tokens for REAG runs (default `4096`). |
| `GRAPH_ENABLED` | `true` to enable graph/vector adapters; `false` (default) is a no-op. |

## Linking a couple

1. Add the bot to the couple's shared group chat.
2. In the group chat, run `/link @partnerA @partnerB`.
3. Each partner must DM the bot `/consent yes`. Tracking starts only after both
   have opted in.
4. Partners can DM `/status` or `/advice` to view metrics or refresh advice.

### Consent & privacy controls

- `/forget` wipes a partner's personal data and revokes consent.
- `/pause` stops tracking without unlinking the couple.
- `/resume` restarts tracking.
- `/export` dumps recent logs.

## Metrics and alerts

The hot lane logs every message, labels it with lexicon-based heuristics, and
computes all 18 relationship metrics—covering conflict tone, demand → withdraw
patterns, language-style matching, emoji warmth, future-planning density, and
follow-through latency. Instant DMs fire when thresholds cross:

- **Green (praise)**: soft starts, repair successes, turning toward bids, fast
  follow-through, high positive-to-negative conflict ratios.
- **Red (risk)**: harsh starts, neg-affect reciprocity spikes, demand/withdraw
  surges, boundary violations, contempt bands above baseline.
- **Blue (logistics)**: SLA misses and plan-to-happen ratios slipping below
  0.6 for commitments due within a day.

Cooldowns, partner Do-Not-Disturb windows, and daily caps prevent spam.

## Background REAG lane

When the conversation goes quiet for `REAG_SILENCE_SECS`, the scheduler enqueues
one REAG job per couple (no more than once per `REAG_MIN_INTERVAL_SECS`). The
worker reads raw slices since the last run, performs a reasoning-augmented
Groq call, and expects strict JSON containing graph updates, full scorecard
values, and refreshed advice blocks. If the queue length crosses
`REAG_QUEUE_HIGH_WATERMARK`, the worker automatically routes to
`GROQ_FALLBACK_MODEL` to catch up. All runs are logged to SQLite (`jobs` and
`reag_runs` tables) for observability and idempotency.

## Advice generation

Advice blocks per partner refresh every ~10 minutes or after 50 messages. By
default the bot calls OpenAI `o4-mini`. If OpenAI is unavailable, it falls back
to Groq `openai/gpt-oss-120b`. When a caller requests tool use, the provider
switches to `groq/compound` and enables the requested tools via the
`compound_custom.tools.enabled_tools` payload. With both providers disabled, the
advice engine falls back to a rule-based summary derived from metric deltas.

## Development

- `make setup` – install dependencies.
- `make seed` – apply migrations and seed default thresholds.
- `make run` – start the Telethon bot.
- `make worker` – run the REAG worker loop.
- `make test` – run the pytest suite.
- `make fmt` – placeholder formatting target.

Tests ship with synthetic sample data to validate the metrics, alert cooldowns,
and LLM provider routing.
