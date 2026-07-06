# Solana Jupiter/Raydium Arbitrage Monitor

A Python bot that watches **SOL ↔ ETH** opportunities between **Raydium** and **Jupiter** on Solana, records quote history to SQLite, and produces a simple learning summary so the monitor can improve over time.

## What this bot does

- Pulls direct venue quotes from **Raydium**
- Pulls comparison quotes from **Jupiter**
- Checks both cycle directions:
  - `raydium -> jupiter`
  - `jupiter -> raydium`
- Stores quotes and detected opportunities in SQLite
- Emits human-readable alerts for profitable opportunities above a configurable threshold
- Can write an HTML dashboard from stored opportunity history
- Optionally rechecks a detected opportunity after a delay to learn whether it persisted or vanished
- Prints JSON summary to stdout for automation

## Important limitation

This is a **monitoring / research bot**, not an auto-trading executor. It does **not** submit transactions or manage private keys. That is intentional for safety while you learn the market behavior.

## Pair configuration used now

- SOL mint: `So11111111111111111111111111111111111111112`
- ETH mint used here: `2FPyTwcZLUg1MDrwsyoP4D6s1tM7hAkHYRjkNb5w6Pxk`
  - Symbol on Raydium token list: `ETH`
  - Name: `Wrapped Ethereum (Sollet)`
- Also documented in `arbitrage_bot/token_config.py`:
  - `wormhole_weth`: `7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs`

During live testing in this session, Jupiter returned `TOKEN_NOT_TRADABLE` for the Wormhole WETH mint, so the bot currently defaults to the tradable Sollet ETH mint.

## Quick start

```bash
cd /home/sevy33/solana-jupiter-raydium-arb-bot
python3 bot.py --once
```

Run a repeated monitor loop:

```bash
python3 bot.py --interval 20 --alert-min-bps 50
```

Generate a dashboard from each run:

```bash
python3 bot.py --once --dashboard-output reports/dashboard.html
```

Run the cron-friendly monitor helper used for background alerts:

```bash
python3 scripts/cron_monitor.py
```

## CLI options

```bash
python3 bot.py --help
```

Key flags:

- `--once` : run a single scan and exit
- `--interval <seconds>` : poll continuously
- `--amount-sol <float>` : input size in SOL
- `--min-profit-bps <float>` : minimum profit threshold to report
- `--db-path <path>` : SQLite location
- `--monitor-seconds <int>` : wait and recheck profitable opportunities
- `--jupiter-exclude-raydium` : compare Jupiter excluding Raydium liquidity
- `--alert-min-bps <float>` : only emit alerts at or above this threshold
- `--dashboard-output <path>` : write an HTML dashboard after each run

## Data files

Default database path:

- `./data/arbitrage.db`

## Learning loop

The monitor keeps a history of opportunities and computes:

- total observations
- how many persisted on recheck
- persistence rate
- average profit in bps
- best historical direction

This gives you a base for later improvements like:

- filtering by time of day
- filtering by profit persistence
- tracking execution-size sensitivity
- adding alert thresholds or dashboards

## Always-on setup used here

- Cron refreshes the monitor every minute using `scripts/cron_monitor.py`
- The cron script updates:
  - `reports/dashboard.html`
  - `reports/latest_scan.json`
- Discord alerts are emitted only when profitable opportunities meet the alert threshold
- A local HTTP server can expose `reports/dashboard.html` on your LAN
