# Solana Jupiter/Raydium Arbitrage Monitor

A Python bot that watches **SOL ↔ ETH** opportunities between **Raydium** and **Jupiter** on Solana, records quote history to SQLite, and produces a simple learning summary so the monitor can improve over time.

## What this bot does

- Pulls direct venue quotes from **Raydium**
- Pulls comparison quotes from **Jupiter**
- Checks both cycle directions:
  - `raydium -> jupiter`
  - `jupiter -> raydium`
- Stores quotes and detected opportunities in SQLite
- Optionally rechecks a detected opportunity after a delay to learn whether it persisted or vanished
- Prints a JSON summary to stdout for automation

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
python3 bot.py --interval 20
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
