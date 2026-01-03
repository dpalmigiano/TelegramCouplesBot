# Encrypted check-in telemetry bot

This repository now ships a privacy-first telemetry layer for 10-question
wellness check-ins. The bot is responsible for assembling two InfluxDB-friendly
measurements per check-in:

1. **`checkin_meta` (plaintext)** – adherence + scheduling signals only
2. **`checkin_payload` (encrypted)** – the actual answers, including per-answer
   timestamps and entry method

The goal is maximum signal without leaking symptoms if the database is stolen:
Influx holds only low-cardinality tags and ciphertext; the bot decrypts on
export.

## Quick start

1. Copy `.env.example` to `.env` and provide keyring + Influx details.
2. Install dependencies: `make setup`
3. Run tests: `make test`

The Telethon scaffold remains available, but the default entry point focuses on
generating check-in measurement payloads for ingestion.

## Environment variables

| Key | Description |
| --- | ----------- |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Telegram API credentials (kept for compatibility). |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather (kept for compatibility). |
| `BOT_OWNER_USER_ID` | Telegram user id for admin commands (kept for compatibility). |
| `ENABLE_LLM` | `1` to enable LLM features; `0` for rule-based advice only. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Defaults to `o4-mini`. |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq fallback (default `openai/gpt-oss-120b`). |
| `DEFAULT_TZ` | Olson timezone name for check-ins without explicit tz. |
| `LOG_LEVEL` | Python logging level (e.g. `INFO`). |
| `PAYLOAD_KEYRING` | Comma-separated `kid:base64key` entries for AES-GCM (e.g. `2:...==,1:...==`). |
| `INFLUX_URL` / `INFLUX_ORG` / `INFLUX_BUCKET` | Connection settings for the time-series DB. |
| `DATABASE_PATH` | SQLite path (legacy; unused by check-in storage). |

## Schema design

Both measurements share `_time = scheduled_at_utc` and the same low-cardinality
tags: `user`, `slot`, `set`, `type`, `schema_v`, and optional `tz`.

### `checkin_meta` (plaintext fields)

- `status_code` – `0=scheduled`, `1=done`, `2=skipped`, `3=missed`, `4=late_partial`
- `answered_at_utc` – when the check-in finished (if answered)
- `latency_sec` – seconds between scheduled and answered
- `completion_pct` – answered / 10
- `missing_count` – unanswered items
- `nudge_count` – nudges sent
- `muted_during_window` – `0/1`

### `checkin_payload` (encrypted fields)

- `payload_ciphertext` – AES-GCM ciphertext of the payload JSON
- `payload_kid` – key id for rotation
- `payload_len` – ciphertext length for sanity/debug

### Payload JSON

The encrypted payload is a wide JSON blob containing per-question timestamps,
entry method, and optional controlled tags:

```json
{
  "schema_v": 1,
  "checkin_id": "a1b2c3d4e5",
  "scheduled_at_utc": "2026-01-03T18:00:00Z",
  "started_at_utc": "2026-01-03T18:02:10Z",
  "finished_at_utc": "2026-01-03T18:03:05Z",
  "slot": "10:00",
  "set": "FULL",
  "type": "scheduled",
  "answers": {
    "q1": {"v": 7, "t": "2026-01-03T18:02:15Z", "m": "button"},
    "q2": {"v": 4, "t": "2026-01-03T18:02:20Z", "m": "button"},
    "q3": {"v": -1, "t": "2026-01-03T18:02:25Z", "m": "button"},
    "q4": {"v": 6, "t": "2026-01-03T18:02:30Z", "m": "button"},
    "q5": {"v": 3, "t": "2026-01-03T18:02:35Z", "m": "button"},
    "q6": {"v": 6.5, "t": "2026-01-03T18:02:45Z", "m": "custom"},
    "q7": {"v": 2, "t": "2026-01-03T18:02:50Z", "m": "button"},
    "q8": {"v": 0, "t": "2026-01-03T18:02:55Z", "m": "button"},
    "q9": {"v": 1, "t": "2026-01-03T18:03:00Z", "m": "button"},
    "q10": {
      "caffeine_mg": {"v": 95, "t": "2026-01-03T18:03:02Z", "m": "button"},
      "baclofen_hours": {"v": 2.0, "t": "2026-01-03T18:03:05Z", "m": "button"}
    }
  },
  "tags": ["after-meal"]
}
```

## Data-quality rules

- Always write `checkin_meta` at the scheduled timestamp (even if unanswered).
- Clamp/validate ranges: q1/2/4/5 → 0–10, q3 → –5..+5, q6 → 0–24, q7 → 1–5,
  q8/9 → 0/1, q10 caffeine → 0–600, q10 baclofen → 0–24. Skipped items remain
  `null` in the payload.
- Late threshold is 45 minutes; partial answers after that are labeled
  `late_partial`.

## Export commands

- `/export 30` → decrypt last 30 days → CSV with columns per question + times
- `/export_all` → full export
- `/export_weekly_summary` (optional) → stats/graphs computed in the bot

## Development

- `make setup` – install dependencies
- `make test` – run the pytest suite
- `make fmt` – placeholder formatting target

