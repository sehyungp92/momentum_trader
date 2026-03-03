# Download Data & Run Baseline Backtests

Run these steps sequentially. Each step must complete before the next begins.
IBKR TWS or Gateway must be running on `127.0.0.1:7496` before starting.

## Prerequisites

```bash
cd C:\Users\sehyu\Documents\Other\Projects\momentum_trader
```

Verify IBKR connection is available and dependencies are importable:

```bash
python -c "from backtest.data.downloader import download_apex_data, download_nqdtc_data, download_vdubus_data; print('OK')"
```

## Step 1 — Download Strategy 1 (Apex) data

Downloads NQ 1-minute + NQ daily. The 1m data is the heaviest download (~1-2Y of minute bars).
Daily data extends to 5Y. IBKR pacing is handled automatically (1s between requests, 60s on violation).

```bash
python -m backtest.cli --strategy apex download --duration "5 Y"
```

Wait 5 seconds after completion before the next download to avoid pacing violations.

## Step 2 — Download Strategy 2 (NQDTC) data

Downloads NQ 5-minute bars. Skips NQ daily if already downloaded in Step 1.

```bash
python -m backtest.cli --strategy nqdtc download --duration "5 Y"
```

Wait 5 seconds after completion.

## Step 3 — Download Strategy 3 (VdubusNQ) data

Downloads NQ 15-minute + ES daily (for regime filter).

```bash
python -m backtest.cli --strategy vdubus download --duration "5 Y"
```

## Step 4 — Verify all data files exist

```bash
python -c "
from pathlib import Path
required = ['NQ_1m', 'NQ_1d', 'NQ_5m', 'NQ_15m', 'ES_1d']
data_dir = Path('data/raw')
for name in required:
    p = data_dir / f'{name}.parquet'
    if p.exists():
        import pandas as pd
        df = pd.read_parquet(p, engine='pyarrow')
        days = (df.index[-1] - df.index[0]).days
        print(f'  OK  {name:8s}  {len(df):>8,} bars  {days}d  ({str(df.index[0])[:10]} -> {str(df.index[-1])[:10]})')
    else:
        print(f'  MISSING  {name}')
"
```

All 5 files must show OK before proceeding. If any are MISSING, re-run the corresponding download step.

## Step 5 — Run Apex v2.2 baseline backtest

```bash
python -m backtest.cli --strategy apex run --report-file output/baseline_apex.txt
```

## Step 6 — Run NQDTC v2.0 baseline backtest

```bash
python -m backtest.cli --strategy nqdtc run --report-file output/baseline_nqdtc.txt
```

## Step 7 — Run VdubusNQ v4.0 baseline backtest

```bash
python -m backtest.cli --strategy vdubus run --report-file output/baseline_vdubus.txt
```

## Step 8 — Print summary of all baseline results

```bash
python -c "
from pathlib import Path
for name in ['apex', 'nqdtc', 'vdubus']:
    p = Path(f'output/baseline_{name}.txt')
    if p.exists():
        print(f'\n{\"=\" * 60}')
        print(f'  {name.upper()} BASELINE')
        print(f'{\"=\" * 60}')
        text = p.read_text(encoding='utf-8')
        # Print first section (performance summary)
        sections = text.split('\n\n')
        for s in sections[:2]:
            print(s)
    else:
        print(f'{name}: report not found at {p}')
"
```
