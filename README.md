# Solana Arbitrage Monitor

A Python bot that watches configurable Solana token pairs across **Raydium**, **Jupiter**, and **Orca**, records quote history to SQLite, and produces lightweight analytics so you can iterate toward a better arbitrage search configuration.

## What this bot does

- Pulls direct venue quotes from **Raydium**
- Pulls routed comparison quotes from **Jupiter**
- Pulls pool-based comparison quotes from **Orca**
- Checks both cycle directions for any selected venue pair
- Stores quotes and detected opportunities in SQLite
- Emits human-readable alerts for profitable opportunities above a configurable threshold
- Can write an HTML dashboard from stored opportunity history
- Can sweep multiple pairs / venue combinations / sizes via an experiment runner
- Optionally rechecks a detected opportunity after a delay to learn whether it persisted or vanished
- Prints JSON summary to stdout for automation

## Important limitation

This is a **monitoring / research bot** first. It can also **prepare swap transactions** and now includes an **explicit execute-swaps mode** that signs and submits prepared transactions when given a wallet and RPC URL. Use live execution carefully.

## Built-in token defaults

Defined in `arbitrage_bot/token_config.py`:

- `SOL`: `So11111111111111111111111111111111111111112` (9 decimals)
- `ETH`: `2FPyTwcZLUg1MDrwsyoP4D6s1tM7hAkHYRjkNb5w6Pxk` (6 decimals)
- `USDC`: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` (6 decimals)
- `USDT`: `Es9vMFrzaCERmJfrF4H2FYD4uJ8V4aHcRUW2YCiMzFx` (6 decimals)

You can override mint/decimals from the CLI for other tokens.

## Quick start

Install runtime dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Then run a scan:

```bash
cd /home/sevy33/solana-jupiter-raydium-arb-bot
python3 bot.py --once
```

Monitor a different pair and venue combination:

```bash
python3 bot.py --once \
  --base-symbol SOL \
  --quote-symbol USDC \
  --left-venue orca \
  --right-venue jupiter \
  --amount 1 \
  --slippage-bps 30
```

Run a repeated monitor loop:

```bash
python3 bot.py --interval 20 --base-symbol SOL --quote-symbol USDC --alert-min-bps 50
```

Generate a dashboard from each run:

```bash
python3 bot.py --once --dashboard-output reports/dashboard.html
```

Prepare unsigned swaps for review:

```bash
python3 bot.py --once \
  --mode prepare-swaps \
  --wallet-path wallets/devnet.json \
  --network devnet
```

Execute prepared swaps through a specific RPC:

```bash
python3 bot.py --once \
  --mode execute-swaps \
  --wallet-path wallets/mainnet.json \
  --network mainnet-beta \
  --rpc-url https://your-solana-rpc.example
```

Run the cron-friendly monitor helper used for background alerts:

```bash
python3 scripts/cron_monitor.py
```

Run the experiment sweep matrix:

```bash
python3 scripts/run_experiments.py
```

## CLI options

```bash
python3 bot.py --help
```

Key flags:

- `--once` : run a single scan and exit
- `--interval <seconds>` : poll continuously
- `--base-symbol <symbol>` / `--quote-symbol <symbol>` : select token pair
- `--base-mint <mint>` / `--quote-mint <mint>` : override token mints
- `--base-decimals <n>` / `--quote-decimals <n>` : override token decimals
- `--amount <float>` : trade size in selected units
- `--amount-units base|quote` : interpret `--amount` in base or quote token units
- `--amount-sol <float>` : legacy shorthand for SOL-sized base trades
- `--left-venue raydium|jupiter|orca` : left side venue
- `--right-venue raydium|jupiter|orca` : right side venue
- `--slippage-bps <int>` : slippage tolerance in basis points
- `--min-profit-bps <float>` : minimum profit threshold to report
- `--db-path <path>` : SQLite location
- `--monitor-seconds <int>` : wait and recheck profitable opportunities
- `--jupiter-exclude-raydium` : compare Jupiter excluding Raydium liquidity
- `--jupiter-dexes <csv>` : Jupiter dex allowlist
- `--jupiter-exclude-dexes <csv>` : Jupiter dex blocklist
- `--alert-min-bps <float>` : only emit alerts at or above this threshold
- `--dashboard-output <path>` : write an HTML dashboard after each run
- `--mode monitor|prepare-swaps|execute-swaps` : monitor only, prepare swaps, or sign/send prepared swaps
- `--wallet-path <path>` : wallet JSON used for prepare/execute swap modes
- `--network devnet|mainnet-beta` : cluster tag used with wallet metadata
- `--rpc-url <url>` : Solana RPC endpoint required for `execute-swaps`
- `--confirm-timeout-seconds <float>` : confirmation wait timeout in execute mode
- `--poll-interval-seconds <float>` : polling interval while waiting for confirmation
- `--skip-preflight` : skip Solana RPC preflight during send
- `--commitment processed|confirmed|finalized` : required confirmation level in execute mode
- `--max-send-retries <int>` : RPC send retries in execute mode

## Experiment outputs

`python3 scripts/run_experiments.py` writes:

- `reports/experiments/latest.json`
- `reports/experiments/run_<timestamp>.json`

Default sweep covers:

- pairs: `SOL/USDC`, `SOL/USDT`, `USDC/USDT`, `SOL/ETH`
- venue combos: `raydium/jupiter`, `orca/jupiter`, `raydium/orca`
- sizes: `0.1`, `1.0`, `10.0` base units

## Data files

Default database path:

- `./data/arbitrage.db`

Common report outputs:

- `./reports/dashboard.html`
- `./reports/latest_scan.json`
- `./reports/experiments/latest.json`

## Always-on setup used here

- Cron refreshes the monitor every minute using `scripts/cron_monitor.py`
- The recommended production configuration from the first sweep is now:
  - pair: `SOL/USDC`
  - venues: `Raydium` vs `Jupiter`
  - amount: `0.1 SOL`
  - slippage: `50 bps`
  - persistence recheck: `15s`
  - Jupiter includes Raydium routes
- The cron script updates:
  - `reports/dashboard.html`
  - `reports/latest_scan.json`
- Discord alerts are emitted only when profitable opportunities meet the alert threshold
