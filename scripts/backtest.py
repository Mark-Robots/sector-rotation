#!/usr/bin/env python3
"""
Backtest retrospettivo del sistema Megatrend Sentinel · v2 ADAPTIVE.

Regola testata (allineata alla modalita' Adaptive di megatrend-desk/azioni.html):
  1. GATE settore: il settore e' "valido" quando stato in {Leader, Emergente}
     E fase (Weinstein) in {1, 2}.
  2. UNIVERSO ADATTIVO: ogni 26 settimane (semestre), per ogni settore, il
     paniere dei candidati si auto-aggiorna in modo MECCANICO e point-in-time:
     restano solo i titoli con ROC a 13 settimane POSITIVO all'anchor,
     ordinati per dollar-volume medio 13w (i piu' liquidi), max ADAPTIVE_K.
  3. Quando un settore diventa valido -> si comprano i TOP-N titoli per
     momentum 13w calcolato all'ingresso, SCELTI DENTRO l'universo adattivo
     vigente a quella data.
  4. STOP-LOSS fisso -20% sul prezzo di chiusura settimanale: se la chiusura
     scende sotto entry*(1-SL) la posizione esce a QUELLA chiusura (il gap
     oltre lo stop resta a carico, come nella realta').
  5. Altrimenti si tiene finche' il settore resta valido; all'uscita del
     settore si vende. Costi COST_PCT per lato su ogni trade.
  6. In parallelo viene calcolato il backtest a LIVELLO ETF (si compra l'ETF
     settoriale nei periodi validi): e' il riferimento "pulito", immune da
     survivorship bias, pubblicato accanto a quello titoli.

Tutto e' point-in-time (rolling window): nessun dato futuro entra nel calcolo
dello stato a settimana t, nella composizione dell'universo, ne' nella
selezione dei titoli.

NB METODOLOGICO (bias residuo): il POOL di partenza (US_HOLDINGS/EU_HOLDINGS)
resta la lista dei constituent attuali. La selezione semestrale meccanica
elimina il cherry-picking, ma i titoli DELISTED/ACQUISITI negli anni passati
non sono nel pool (yfinance non li fornisce). Sovrastima residua stimata
~1-2%/anno, mitigata da stop-loss -20% e pesi equal-weight. Il backtest ETF
e' il numero di riferimento privo di questo bias.

Uso:
    python scripts/backtest.py            # scarica e calcola -> data/backtest.json
"""
import json
import os
import sys
from collections import defaultdict
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
COST_PCT = 0.1       # costo per lato di ogni trade titolo (0.1 = 0.1%)
STOP_LOSS_PCT = 20.0 # stop-loss fisso su chiusura settimanale (Adaptive)
REBAL_WEEKS = 26     # refresh semestrale dell'universo adattivo
ADAPTIVE_K = 8       # max candidati per settore dopo il filtro (per liquidita')
DV_WEEKS = 13        # finestra per il dollar-volume medio
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


# ============================================================
# UNIVERSO ADATTIVO (point-in-time, refresh semestrale)
# ============================================================

def build_anchors(calendar, rebal_weeks=REBAL_WEEKS):
    """Date di refresh dell'universo: una ogni `rebal_weeks` settimane."""
    return [calendar[i] for i in range(0, len(calendar), rebal_weeks)]


def adaptive_universe_at(anchor, holds, tk_wclose, tk_wdv,
                         mom_weeks=MOM_WEEKS, k=ADAPTIVE_K):
    """Candidati del settore all'anchor: solo titoli con ROC 13w > 0,
    ordinati per dollar-volume medio 13w decrescente, max k.
    Usa ESCLUSIVAMENTE dati <= anchor (point-in-time)."""
    scored = []
    for h in holds:
        wc = tk_wclose.get(h)
        if wc is None:
            continue
        hist = wc[wc.index <= anchor]
        if len(hist) <= mom_weeks:
            continue
        roc = hist.iloc[-1] / hist.iloc[-1 - mom_weeks] - 1
        if roc <= 0:
            continue
        dv = tk_wdv.get(h)
        dv_avg = 0.0
        if dv is not None:
            dvh = dv[dv.index <= anchor].tail(DV_WEEKS)
            if len(dvh):
                dv_avg = float(dvh.mean())
        scored.append((h, dv_avg))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [h for h, _ in scored[:k]]


def universe_for_date(t, anchors, uni_by_anchor):
    """Universo vigente alla data t = quello dell'ultimo anchor <= t."""
    last = None
    for a in anchors:
        if a <= t:
            last = a
        else:
            break
    return uni_by_anchor.get(last, []) if last is not None else []


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(prices_d, volumes_d=None):
    """Backtest doppio livello: TITOLI (regola Adaptive) + ETF (pulito).
    prices_d/volumes_d: DataFrame giornalieri (colonne = ticker)."""
    sector_map = {**{t: ('USA', US_BENCHMARK) for t in US_SECTORS},
                  **{t: ('EU', EU_BENCHMARK) for t in EU_SECTORS}}
    holdings_map = {**US_HOLDINGS, **EU_HOLDINGS}
    sector_names = {**US_SECTORS, **EU_SECTORS}

    bench_w = {
        US_BENCHMARK: weekly_close(prices_d, US_BENCHMARK),
        EU_BENCHMARK: weekly_close(prices_d, EU_BENCHMARK),
    }

    # rendimenti/chiusure settimanali per titolo + dollar-volume settimanale
    tk_wret, tk_wclose, tk_wdv = {}, {}, {}
    for tk in prices_d.columns:
        wc = weekly_close(prices_d, tk)
        if wc is not None and len(wc) > 2:
            tk_wclose[tk] = wc
            tk_wret[tk] = wc.pct_change()
            if volumes_d is not None and tk in volumes_d.columns:
                v = volumes_d[tk].dropna()
                if not v.empty:
                    dv_d = (prices_d[tk] * v).dropna()
                    tk_wdv[tk] = dv_d.resample('W-FRI').mean().dropna()

    # calendario settimanale di riferimento (benchmark US)
    if bench_w[US_BENCHMARK] is None:
        return {'error': 'benchmark US mancante'}
    calendar = bench_w[US_BENCHMARK].index
    anchors = build_anchors(calendar)

    # universi adattivi per settore/anchor (tutto point-in-time)
    uni = {}  # sector -> {anchor -> [tickers]}
    for sec in sector_map:
        holds = holdings_map.get(sec, [])
        if not holds:
            continue
        uni[sec] = {a: adaptive_universe_at(a, holds, tk_wclose, tk_wdv)
                    for a in anchors}

    trades = []
    week_contrib = defaultdict(list)       # titoli
    week_contrib_etf = defaultdict(list)   # ETF (pulito)
    sl_mult = 1.0 - STOP_LOSS_PCT / 100.0

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

        for (t_in, t_out, is_open) in periods:
            # ---------- livello ETF (pulito, nessun bias) ----------
            seg_etf = sec_weekly[(sec_weekly.index >= t_in) & (sec_weekly.index <= t_out)]
            if len(seg_etf) >= 2:
                rets_etf = seg_etf.pct_change()
                for j, dt in enumerate(seg_etf.index):
                    if j == 0:
                        continue
                    r = rets_etf.iloc[j]
                    if pd.isna(r):
                        r = 0.0
                    edge = (COST_PCT / 100.0) if (j == 1 or j == len(seg_etf) - 1) else 0.0
                    week_contrib_etf[dt].append(float(r) - edge)

            # ---------- livello TITOLI (regola Adaptive) ----------
            if not holds:
                continue
            universe = universe_for_date(t_in, anchors, uni.get(sec, {}))
            if not universe:
                continue  # semestre senza candidati validi -> cash
            # top-N per momentum 13w A t_in, dentro l'universo adattivo
            cand = []
            for h in universe:
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
                entry_p = float(seg.iloc[0])
                stop_level = entry_p * sl_mult
                # stop-loss: prima chiusura settimanale sotto il livello
                exit_j = len(seg) - 1
                stopped = False
                for j in range(1, len(seg)):
                    if float(seg.iloc[j]) <= stop_level:
                        exit_j = j; stopped = True
                        break
                exit_p = float(seg.iloc[exit_j])
                trade_open = bool(is_open) and not stopped and exit_j == len(seg) - 1
                perf = (exit_p / entry_p - 1) * 100 - 2 * COST_PCT
                trades.append({
                    'ticker': h,
                    'sector': sector_names.get(sec, sec),
                    'sector_ticker': sec,
                    'region': region,
                    'entry_date': seg.index[0].date().isoformat(),
                    'exit_date': seg.index[exit_j].date().isoformat(),
                    'weeks': int(exit_j),
                    'perf': round(perf, 1),
                    'open': trade_open,
                    'stop': stopped,
                })
                rets = tk_wret[h]
                for j in range(1, exit_j + 1):
                    dt = seg.index[j]
                    r = rets.get(dt, 0.0)
                    if pd.isna(r):
                        r = 0.0
                    edge = (COST_PCT / 100.0) if (j == 1 or j == exit_j) else 0.0
                    week_contrib[dt].append(float(r) - edge)

    if not week_contrib:
        return {'error': 'nessun trade generato'}

    # ---- Equity (equal-weight settimanale sulle posizioni aperte) ----
    def build_equity(contrib):
        first = min(contrib.keys())
        cal = calendar[calendar >= first]
        eq = []; dates = []; invested = 0
        prev = 1.0
        for dt in cal:
            c = contrib.get(dt, [])
            if c:
                ret = float(np.mean(c)); invested += 1
            else:
                ret = 0.0
            prev = prev * (1 + ret)
            eq.append(prev); dates.append(dt)
        return eq, dates, invested

    eq_sys, eq_dates, weeks_invested = build_equity(week_contrib)
    eq_etf_raw, eq_etf_dates, _ = build_equity(week_contrib_etf)
    # riallineo l'equity ETF sul calendario dell'equity titoli
    etf_map = dict(zip(eq_etf_dates, eq_etf_raw))
    eq_etf, base_etf = [], None
    for dt in eq_dates:
        v = etf_map.get(dt)
        if v is not None and base_etf is None:
            base_etf = v
        eq_etf.append((v / base_etf) if (v is not None and base_etf) else
                      (eq_etf[-1] if eq_etf else 1.0))

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
        'n_stopped': len([t for t in trades if t.get('stop')]),
        'win_rate_pct': round(100 * len(wins) / len(closed), 1) if closed else None,
        'avg_perf_pct': round(np.mean([t['perf'] for t in closed]), 1) if closed else None,
        'profit_factor': round(gains / losses, 2) if losses > 0 else None,
        'avg_weeks': round(np.mean([t['weeks'] for t in closed]), 1) if closed else None,
        'best_pct': round(max((t['perf'] for t in closed), default=0), 1),
        'worst_pct': round(min((t['perf'] for t in closed), default=0), 1),
        'exposure_pct': round(100 * weeks_invested / len(eq_dates), 1) if eq_dates else None,
    })

    equity = [{'date': d.date().isoformat(), 'system': round(s, 4),
               'bench': round(b, 4), 'etf': round(e, 4)}
              for d, s, b, e in zip(eq_dates, eq_sys, bench_eq, eq_etf)]
    trades_sorted = sorted(trades, key=lambda t: t['entry_date'], reverse=True)

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'params': {'top_n': TOP_N, 'ma_weeks': MA_WEEKS, 'mom_weeks': MOM_WEEKS,
                   'period': PERIOD, 'cost_pct': COST_PCT,
                   'stop_loss_pct': STOP_LOSS_PCT, 'rebal_weeks': REBAL_WEEKS,
                   'adaptive_k': ADAPTIVE_K,
                   'benchmark': 'Blend 50/50 ' + US_BENCHMARK + '+' + EU_BENCHMARK,
                   'gate': 'Leader/Emergente + Fase 1/2 · Adaptive 6m · SL -20%'},
        'metrics': {'system': sys_m,
                    'etf': equity_metrics(eq_etf, eq_dates),
                    'benchmark': equity_metrics(bench_eq, eq_dates)},
        'equity': equity,
        'trades': trades_sorted,
        'note': ('Titoli: regola Adaptive (universo meccanico semestrale ROC13>0 '
                 'per dollar-volume, stop-loss -20%, costi {:.2f}%/lato). '
                 'Bias residuo: il pool base sono i constituent attuali, i '
                 'delisted mancano -> sovrastima stimata ~1-2%/anno. '
                 "L'equity ETF e' il riferimento pulito, immune dal bias."
                 ).format(COST_PCT),
    }


def fetch_volumes(tickers, period=PERIOD):
    """Scarica i volumi giornalieri (per il ranking dollar-volume).
    Best-effort: se fallisce si procede senza (rank per solo ROC)."""
    try:
        import yfinance as yf
        data = yf.download(tickers, period=period, auto_adjust=True,
                           progress=False, threads=True, group_by='ticker')
        if data is None or data.empty:
            return None
        cols = {}
        if isinstance(data.columns, pd.MultiIndex):
            for t in tickers:
                try:
                    if t in data.columns.get_level_values(0):
                        s = data[t]['Volume'].dropna()
                        if len(s):
                            cols[t] = s
                except Exception:
                    pass
        elif 'Volume' in data.columns and len(tickers) == 1:
            cols[tickers[0]] = data['Volume'].dropna()
        return pd.DataFrame(cols) if cols else None
    except Exception as e:
        print(f"Volumi non disponibili ({e}): ranking per solo ROC.", file=sys.stderr)
        return None


def main():
    tickers = ([US_BENCHMARK] + list(US_SECTORS) + [EU_BENCHMARK] + list(EU_SECTORS))
    stock_tickers = []
    for hs in (US_HOLDINGS, EU_HOLDINGS):
        for lst in hs.values():
            stock_tickers += list(lst)
    tickers = sorted(set(tickers + stock_tickers))
    print(f"Backtest v2 Adaptive: scarico {len(tickers)} ticker (period={PERIOD})...")
    prices = fetch_prices(tickers, period=PERIOD)
    if prices is None or prices.empty:
        print("Nessun prezzo scaricato.", file=sys.stderr); sys.exit(1)
    volumes = fetch_volumes(sorted(set(stock_tickers)))
    result = run_backtest(prices, volumes)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    m = result.get('metrics', {}).get('system', {})
    e = result.get('metrics', {}).get('etf', {})
    b = result.get('metrics', {}).get('benchmark', {})
    print(f"OK -> {OUT}")
    print(f"  TITOLI (Adaptive): CAGR {m.get('cagr_pct')}% | MaxDD {m.get('max_drawdown_pct')}% | "
          f"Sharpe {m.get('sharpe')} | trade {m.get('n_trades')} (stop: {m.get('n_stopped')})")
    print(f"  ETF (pulito):      CAGR {e.get('cagr_pct')}% | MaxDD {e.get('max_drawdown_pct')}% | "
          f"Sharpe {e.get('sharpe')}")
    print(f"  BENCHMARK 50/50:   CAGR {b.get('cagr_pct')}%")


if __name__ == '__main__':
    main()
