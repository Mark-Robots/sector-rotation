#!/usr/bin/env python3
"""
Backtest retrospettivo del sistema Megatrend Sentinel · livello TITOLI.

Regola testata (fedele al portafoglio modello):
  1. GATE settore: il settore e' "valido" quando stato in {Leader, Emergente}
     E fase (Weinstein) in {1, 2}.
  2. Quando un settore diventa valido -> si comprano i suoi TOP-N titoli per
     momentum a 13 settimane (point-in-time, calcolato all'ingresso).
  3. Si tengono finche' il settore resta valido; all'uscita del settore si vende.

Tutto e' calcolato point-in-time (rolling window): nessun dato futuro entra nel
calcolo dello stato a settimana t, ne' nella selezione dei titoli.

NB METODOLOGICO: le liste US_HOLDINGS/EU_HOLDINGS sono i top constituent CURATI
OGGI. Applicarle al passato introduce un SURVIVORSHIP/SELECTION BIAS che tende a
sovrastimare la performance dei titoli. L'equity dei titoli va letta con questa
cautela; un backtest a livello ETF (immune dal bias) e' il riferimento "pulito".

Uso:
    python scripts/backtest.py            # scarica e calcola -> data/backtest.json
"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# Riuso la logica del sistema per garantire coerenza con il live
from update_data import (
    US_SECTORS, EU_SECTORS, US_HOLDINGS, EU_HOLDINGS,
    US_BENCHMARK, EU_BENCHMARK,
    calculate_rrg, classify_quadrant, fetch_prices,
)

# -------- Parametri (modificabili) --------
TOP_N = 3            # titoli per settore (coerente con i picks)
MA_WEEKS = 30        # media mobile Weinstein
MOM_WEEKS = 13       # finestra momentum per la selezione titoli (~3 mesi)
PERIOD = '8y'        # storico da scaricare
COST_PCT = 0.0       # costo per lato di ogni trade titolo (es. 0.1 = 0.1%)
VALID_STATES = ('Leader', 'Emergente')
VALID_PHASES = ('1', '2')
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'backtest.json')


def stage_series(weekly, ma_weeks=MA_WEEKS):
    """Fase di Weinstein ('1'..'4'/'N/A') per OGNI settimana, coerente con
    classify_stage di update_data. Tutto backward-looking (no look-ahead)."""
    ma = weekly.rolling(window=ma_weeks).mean()
    ma_slope = (ma.diff(periods=4) / ma.shift(4)) * 100
    out = pd.Series(index=weekly.index, dtype=object)
    for i in range(len(weekly)):
        if pd.isna(ma.iloc[i]) or pd.isna(ma_slope.iloc[i]):
            out.iloc[i] = 'N/A'
            continue
        price = float(weekly.iloc[i]); ma_c = float(ma.iloc[i]); slope = float(ma_slope.iloc[i])
        dist = ((price - ma_c) / ma_c) * 100
        if price > ma_c:
            if slope > 0.3:
                out.iloc[i] = '2'
            elif slope < -0.3:
                out.iloc[i] = '3'
            else:
                out.iloc[i] = '3' if dist < 3 else '2'
        else:
            out.iloc[i] = '4' if slope < -0.3 else '1'
    return out


def sector_validity(sector_d, bench_d):
    """Serie booleana settimanale: il settore e' 'valido' (Leader/Emergente +
    Fase 1/2) a ogni settimana. Restituisce (valid_series, weekly_close) o None."""
    rrg = calculate_rrg(sector_d, bench_d)
    if rrg is None:
        return None
    weekly = sector_d.resample('W-FRI').last().dropna()
    stages = stage_series(weekly)
    idx = rrg.index.intersection(stages.index)
    if len(idx) < 30:
        return None
    valid = pd.Series(False, index=idx)
    for t in idx:
        state = classify_quadrant(rrg.loc[t, 'rs_ratio'], rrg.loc[t, 'rs_momentum'])
        phase = stages.loc[t]
        valid.loc[t] = (state in VALID_STATES) and (phase in VALID_PHASES)
    return valid, weekly


def find_periods(valid):
    """Intervalli [t_in, t_out] (indici di settimana) in cui valid e' True.
    t_out e' l'ultima settimana valida; se ancora valido a fine serie, open=True."""
    periods = []
    in_pos = False
    start = None
    arr = valid.values
    dates = valid.index
    for i in range(len(arr)):
        if arr[i] and not in_pos:
            in_pos = True; start = i
        elif not arr[i] and in_pos:
            in_pos = False
            periods.append((start, i - 1, False))
    if in_pos:
        periods.append((start, len(arr) - 1, True))
    return [(dates[a], dates[b], op) for (a, b, op) in periods]


def weekly_close(prices_d, ticker):
    if ticker not in prices_d.columns:
        return None
    s = prices_d[ticker].dropna()
    if s.empty:
        return None
    return s.resample('W-FRI').last().dropna()


def run_backtest(prices_d):
    """Calcola trade dei titoli + equity di sistema + benchmark da un DataFrame
    di prezzi giornalieri (colonne = ticker). Nessuna rete: testabile offline."""
    sector_map = {**{t: ('USA', US_BENCHMARK) for t in US_SECTORS},
                  **{t: ('EU', EU_BENCHMARK) for t in EU_SECTORS}}
    holdings_map = {**US_HOLDINGS, **EU_HOLDINGS}
    sector_names = {**US_SECTORS, **EU_SECTORS}

    bench_w = {
        US_BENCHMARK: weekly_close(prices_d, US_BENCHMARK),
        EU_BENCHMARK: weekly_close(prices_d, EU_BENCHMARK),
    }

    trades = []
    # posizione[settimana] -> lista di rendimenti settimanali dei titoli in pos.
    # costruiamo prima i rendimenti settimanali per titolo
    tk_wret = {}  # ticker -> Series rendimento settimanale
    tk_wclose = {}
    for tk in prices_d.columns:
        wc = weekly_close(prices_d, tk)
        if wc is not None and len(wc) > 2:
            tk_wclose[tk] = wc
            tk_wret[tk] = wc.pct_change()

    # contributo settimanale: dict date -> list di (ret, is_edge_open, is_edge_close)
    from collections import defaultdict
    week_contrib = defaultdict(list)

    for sec, (region, bench) in sector_map.items():
        sec_d = prices_d[sec].dropna() if sec in prices_d.columns else None
        bd = prices_d[bench].dropna() if bench in prices_d.columns else None
        if sec_d is None or bd is None or len(sec_d) < 260:
            continue
        sv = sector_validity(sec_d, bd)
        if sv is None:
            continue
        valid, sec_weekly = sv
        periods = find_periods(valid)
        holds = holdings_map.get(sec, [])
        if not holds:
            continue
        for (t_in, t_out, is_open) in periods:
            # selezione top-N per momentum 13w calcolato A t_in (point-in-time)
            cand = []
            for h in holds:
                wc = tk_wclose.get(h)
                if wc is None:
                    continue
                hist = wc[wc.index <= t_in]
                if len(hist) <= MOM_WEEKS:
                    continue
                mom = hist.iloc[-1] / hist.iloc[-1 - MOM_WEEKS] - 1
                cand.append((h, mom))
            cand.sort(key=lambda x: x[1], reverse=True)
            picks = [h for h, _ in cand[:TOP_N]]
            for h in picks:
                wc = tk_wclose[h]
                seg = wc[(wc.index >= t_in) & (wc.index <= t_out)]
                if len(seg) < 2:
                    continue
                entry_p = float(seg.iloc[0]); exit_p = float(seg.iloc[-1])
                perf = (exit_p / entry_p - 1) * 100 - 2 * COST_PCT
                trades.append({
                    'ticker': h,
                    'sector': sector_names.get(sec, sec),
                    'sector_ticker': sec,
                    'region': region,
                    'entry_date': seg.index[0].date().isoformat(),
                    'exit_date': seg.index[-1].date().isoformat(),
                    'weeks': int(len(seg) - 1),
                    'perf': round(perf, 1),
                    'open': bool(is_open),
                })
                # contributo all'equity: ogni settimana del segmento, rendimento del titolo
                rets = tk_wret[h]
                seg_dates = seg.index
                for j, dt in enumerate(seg_dates):
                    if j == 0:
                        continue  # entry: nessun rendimento la settimana d'ingresso
                    r = rets.get(dt, 0.0)
                    if pd.isna(r):
                        r = 0.0
                    edge = (COST_PCT / 100.0) if (j == 1 or j == len(seg_dates) - 1) else 0.0
                    week_contrib[dt].append(r - edge)

    # ---- Equity di sistema (equal-weight settimanale sui titoli in posizione) ----
    all_dates = sorted(week_contrib.keys())
    if not all_dates:
        return {'error': 'nessun trade generato'}
    # uso il calendario settimanale del benchmark US come asse temporale
    cal = bench_w[US_BENCHMARK].index if bench_w[US_BENCHMARK] is not None else pd.DatetimeIndex(all_dates)
    cal = cal[(cal >= all_dates[0])]
    eq_sys = [1.0]; eq_dates = []; weeks_invested = 0
    prev = 1.0
    for dt in cal:
        contribs = week_contrib.get(dt, [])
        if contribs:
            ret = float(np.mean(contribs)); weeks_invested += 1
        else:
            ret = 0.0
        prev = prev * (1 + ret)
        eq_sys.append(prev); eq_dates.append(dt)
    eq_sys = eq_sys[1:]

    # ---- Benchmark buy&hold: blend 50/50 US+EU ----
    bw_us = bench_w[US_BENCHMARK]; bw_eu = bench_w[EU_BENCHMARK]
    bench_eq = []
    base_us = base_eu = None
    for dt in eq_dates:
        pu = bw_us.asof(dt) if bw_us is not None else None
        pe = bw_eu.asof(dt) if bw_eu is not None else None
        if base_us is None and pu is not None and not pd.isna(pu):
            base_us = pu
        if base_eu is None and pe is not None and not pd.isna(pe):
            base_eu = pe
        parts = []
        if pu is not None and base_us:
            parts.append(pu / base_us)
        if pe is not None and base_eu:
            parts.append(pe / base_eu)
        bench_eq.append(float(np.mean(parts)) if parts else (bench_eq[-1] if bench_eq else 1.0))

    # ---- Metriche ----
    def equity_metrics(eq, dates):
        eq = np.array(eq, dtype=float)
        if len(eq) < 2:
            return {}
        rets = np.diff(eq) / eq[:-1]
        years = max((dates[-1] - dates[0]).days / 365.25, 0.1)
        total = eq[-1] - 1
        cagr = eq[-1] ** (1 / years) - 1
        run_max = np.maximum.accumulate(eq)
        mdd = float(np.min(eq / run_max - 1))
        vol = float(np.std(rets) * np.sqrt(52))
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(52)) if np.std(rets) > 0 else 0.0
        return {
            'total_return_pct': round(total * 100, 1),
            'cagr_pct': round(cagr * 100, 1),
            'max_drawdown_pct': round(mdd * 100, 1),
            'volatility_pct': round(vol * 100, 1),
            'sharpe': round(sharpe, 2),
        }

    closed = [t for t in trades if not t['open']]
    wins = [t for t in closed if t['perf'] > 0]
    gains = sum(t['perf'] for t in wins)
    losses = abs(sum(t['perf'] for t in closed if t['perf'] <= 0))
    sys_m = equity_metrics(eq_sys, eq_dates)
    sys_m.update({
        'n_trades': len(closed),
        'n_open': len([t for t in trades if t['open']]),
        'win_rate_pct': round(100 * len(wins) / len(closed), 1) if closed else None,
        'avg_perf_pct': round(np.mean([t['perf'] for t in closed]), 1) if closed else None,
        'profit_factor': round(gains / losses, 2) if losses > 0 else None,
        'avg_weeks': round(np.mean([t['weeks'] for t in closed]), 1) if closed else None,
        'best_pct': round(max((t['perf'] for t in closed), default=0), 1),
        'worst_pct': round(min((t['perf'] for t in closed), default=0), 1),
        'exposure_pct': round(100 * weeks_invested / len(eq_dates), 1) if eq_dates else None,
    })

    equity = [{'date': d.date().isoformat(), 'system': round(s, 4), 'bench': round(b, 4)}
              for d, s, b in zip(eq_dates, eq_sys, bench_eq)]
    trades_sorted = sorted(trades, key=lambda t: t['entry_date'], reverse=True)

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'params': {'top_n': TOP_N, 'ma_weeks': MA_WEEKS, 'mom_weeks': MOM_WEEKS,
                   'period': PERIOD, 'cost_pct': COST_PCT,
                   'benchmark': 'Blend 50/50 ' + US_BENCHMARK + '+' + EU_BENCHMARK,
                   'gate': 'Leader/Emergente + Fase 1/2'},
        'metrics': {'system': sys_m, 'benchmark': equity_metrics(bench_eq, eq_dates)},
        'equity': equity,
        'trades': trades_sorted,
        'note': 'Survivorship bias: holdings curati oggi applicati al passato.',
    }


def main():
    tickers = ([US_BENCHMARK] + list(US_SECTORS) + [EU_BENCHMARK] + list(EU_SECTORS))
    for hs in (US_HOLDINGS, EU_HOLDINGS):
        for lst in hs.values():
            tickers += list(lst)
    tickers = sorted(set(tickers))
    print(f"Backtest: scarico {len(tickers)} ticker (period={PERIOD})...")
    prices = fetch_prices(tickers, period=PERIOD)
    if prices is None or prices.empty:
        print("Nessun prezzo scaricato.", file=sys.stderr); sys.exit(1)
    result = run_backtest(prices)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    m = result.get('metrics', {}).get('system', {})
    print(f"OK -> {OUT}")
    print(f"  Trade chiusi: {m.get('n_trades')} | win {m.get('win_rate_pct')}% | "
          f"CAGR {m.get('cagr_pct')}% | MaxDD {m.get('max_drawdown_pct')}% | "
          f"vs bench CAGR {result.get('metrics',{}).get('benchmark',{}).get('cagr_pct')}%")


if __name__ == '__main__':
    main()
