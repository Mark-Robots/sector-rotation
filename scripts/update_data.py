"""
Sector Rotation · Data Update Script
=====================================
Scarica prezzi via yfinance, calcola tutte le metriche (RRG, Stage Weinstein,
performance, cross-region) e salva un JSON pronto per essere letto dall'HTML.

Pensato per girare su GitHub Actions una volta al giorno.

Output: data/sector_data.json
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# TICKERS
# ============================================================
US_BENCHMARK = 'SPY'
US_SECTORS = {
    'XLK':  'Tecnologia',
    'XLF':  'Finanziari',
    'XLV':  'Sanità',
    'XLY':  'Consumi voluttuari',
    'XLP':  'Consumi essenziali',
    'XLE':  'Energia',
    'XLI':  'Industriali',
    'XLB':  'Materiali base',
    'XLU':  'Utility',
    'XLRE': 'Immobiliare',
    'XLC':  'Comunicazioni',
    'SOXX': 'Semiconduttori',
    'IBB':  'Biotech',
    'KRE':  'Banche regionali',
    'XHB':  'Costruttori case',
    'XRT':  'Retail',
    'ITA':  'Aerospazio & Difesa',
}

EU_BENCHMARK = 'EXSA.DE'
EU_SECTORS = {
    'EXV3.DE': 'Tecnologia',
    'EXV1.DE': 'Banche',
    'EXV5.DE': 'Automobili',
    'EXH1.DE': 'Energia',
    'EXV4.DE': 'Sanità',
    'EXH5.DE': 'Assicurazioni',
    'EXH3.DE': 'Servizi finanziari',
    'EXH2.DE': 'Retail',
    'EXH8.DE': 'Media',
    'EXH4.DE': 'Industriali',
    'EXV8.DE': 'Costruzioni',
    'EXV6.DE': 'Risorse base',
    'EXH6.DE': 'Beni personali',
    'EXV2.DE': 'Telecomunicazioni',
    'EXH7.DE': 'Alimentari & Bevande',
    'EXV7.DE': 'Chimica',
    'EXH9.DE': 'Utility',
    'EXV9.DE': 'Viaggi & Tempo libero',
}

CROSS_PAIRS = [
    ('Tecnologia',          'XLK',  'EXV3.DE'),
    ('Banche / Finanziari', 'XLF',  'EXV1.DE'),
    ('Energia',             'XLE',  'EXH1.DE'),
    ('Sanità',              'XLV',  'EXV4.DE'),
    ('Industriali',         'XLI',  'EXH4.DE'),
    ('Auto / Consumi vol.', 'XLY',  'EXV5.DE'),
    ('Utility',             'XLU',  'EXH9.DE'),
    ('Materiali base',      'XLB',  'EXV6.DE'),
    ('Consumi essenziali',  'XLP',  'EXH7.DE'),
    ('Comunicazioni',       'XLC',  'EXV2.DE'),
    ('Retail',              'XRT',  'EXH2.DE'),
]


# ============================================================
# HOLDINGS · Top titoli per settore (per il drill-down)
# Liste curate dei top constituent per ETF settoriale
# ============================================================
US_HOLDINGS = {
    'XLK':  ['AAPL', 'MSFT', 'ORCL', 'CRM', 'ACN', 'ADBE', 'CSCO', 'IBM', 'INTU'],
    'XLF':  ['BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'SPGI', 'GS', 'AXP', 'MS', 'BLK', 'C', 'PGR', 'CB'],
    'XLV':  ['LLY', 'UNH', 'JNJ', 'ABBV', 'MRK', 'TMO', 'ABT', 'PFE', 'DHR', 'BMY', 'ISRG'],
    'XLY':  ['TSLA', 'MCD', 'NKE', 'SBUX', 'BKNG', 'TJX', 'F', 'GM', 'MAR'],
    'XLP':  ['PG', 'KO', 'PEP', 'PM', 'MO', 'MDLZ', 'CL', 'KMB', 'GIS'],
    'XLE':  ['XOM', 'CVX', 'COP', 'EOG', 'SLB', 'OXY', 'MPC', 'PSX', 'VLO', 'KMI', 'WMB', 'FANG'],
    'XLI':  ['CAT', 'HON', 'UNP', 'UPS', 'DE', 'ETN', 'EMR'],
    'XLB':  ['LIN', 'APD', 'SHW', 'ECL', 'NEM', 'FCX', 'DD', 'NUE', 'CTVA', 'DOW'],
    'XLU':  ['NEE', 'SO', 'DUK', 'AEP', 'EXC', 'SRE', 'XEL', 'PEG', 'ED', 'AWK'],
    'XLRE': ['PLD', 'AMT', 'EQIX', 'WELL', 'PSA', 'O', 'DLR', 'SPG', 'CCI', 'EXR'],
    'XLC':  ['META', 'GOOGL', 'GOOG', 'NFLX', 'TMUS', 'DIS', 'VZ', 'T', 'CMCSA', 'EA'],
    'SOXX': ['NVDA', 'AVGO', 'AMD', 'QCOM', 'TXN', 'INTC', 'MU', 'AMAT', 'LRCX', 'KLAC', 'ASML', 'TSM', 'MRVL', 'ADI'],
    'IBB':  ['VRTX', 'AMGN', 'GILD', 'REGN', 'BIIB', 'ILMN', 'MRNA', 'BMRN', 'INCY'],
    'KRE':  ['MTB', 'FCNCA', 'ZION', 'CFG', 'RF', 'FITB', 'HBAN', 'KEY', 'CMA', 'WAL'],
    'XHB':  ['DHI', 'LEN', 'PHM', 'NVR', 'TOL', 'MTH', 'MAS', 'BLDR'],
    'XRT':  ['COST', 'AMZN', 'HD', 'LOW', 'WMT', 'TGT', 'BBY', 'DG', 'DLTR', 'ROST'],
    'ITA':  ['RTX', 'BA', 'LMT', 'NOC', 'GD', 'GE', 'TDG', 'LHX', 'HII'],
}

EU_HOLDINGS = {
    # Tecnologia · STM e i pochi nomi tech italiani
    'EXV3.DE': ['STM.MI', 'REY.MI', 'TXT.MI', 'DEA.MI', 'TIPRA.MI'],
    
    # Banche · settore italiano per eccellenza
    'EXV1.DE': ['ISP.MI', 'UCG.MI', 'BMPS.MI', 'BAMI.MI', 'BPER.MI', 'MB.MI', 'CRG.MI', 'BPSO.MI'],
    
    # Automobili & Componenti · Stellantis, Ferrari, Pirelli, Brembo
    'EXV5.DE': ['STLAM.MI', 'RACE.MI', 'PIRC.MI', 'BRE.MI', 'IVG.MI'],
    
    # Energia · ENI, Tenaris, Saras, Snam, ERG
    'EXH1.DE': ['ENI.MI', 'TEN.MI', 'SAR.MI', 'ERG.MI', 'SPM.MI'],
    
    # Sanità · Recordati, DiaSorin, Amplifon
    'EXV4.DE': ['REC.MI', 'DIA.MI', 'AMP.MI', 'PHM.MI', 'GVS.MI'],
    
    # Assicurazioni · Generali, Unipol
    'EXH5.DE': ['G.MI', 'US.MI', 'UNI.MI'],
    
    # Servizi finanziari · Azimut, FinecoBank, Mediolanum, Banca Generali
    'EXH3.DE': ['AZM.MI', 'FBK.MI', 'BMED.MI', 'BGN.MI', 'ANIM.MI'],
    
    # Retail · pochi nomi puri italiani
    'EXH2.DE': ['OVS.MI', 'ESPR.MI'],
    
    # Media · MediaForEurope (ex-Mediaset), Cairo, RCS, Mondadori
    'EXH8.DE': ['MFEA.MI', 'CAI.MI', 'RCS.MI', 'MN.MI'],
    
    # Industriali · Leonardo, Prysmian, Interpump, Webuild
    'EXH4.DE': ['LDO.MI', 'PRY.MI', 'IP.MI', 'AVIO.MI', 'DAN.MI'],
    
    # Costruzioni · Buzzi, Webuild, Salcef
    'EXV8.DE': ['BZU.MI', 'WBD.MI', 'SCF.MI'],
    
    # Risorse base · pochi nomi italiani puri (Tenaris è anche qui)
    'EXV6.DE': [],
    
    # Beni personali · Moncler, Brunello, Tod's, Ferragamo, Geox (luxury Made in Italy)
    'EXH6.DE': ['MONC.MI', 'BC.MI', 'TOD.MI', 'FCT.MI', 'GEO.MI', 'TPRO.MI'],
    
    # Telecomunicazioni · TIM, Inwit
    'EXV2.DE': ['TIT.MI', 'INW.MI'],
    
    # Alimentari & Bevande · Campari, De Longhi, Newlat
    'EXH7.DE': ['CPR.MI', 'DLG.MI', 'NL.MI'],
    
    # Chimica · pochi nomi italiani
    'EXV7.DE': ['ECNL.MI', 'ICOR.MI'],
    
    # Utility · grande forza in Italia: Enel, Snam, Terna, Italgas, A2A, Hera, Iren
    'EXH9.DE': ['ENEL.MI', 'SRG.MI', 'TRN.MI', 'ITG.MI', 'A2A.MI', 'HER.MI', 'IRE.MI', 'ACE.MI'],
    
    # Viaggi & Tempo libero · pochi nomi italiani puri
    'EXV9.DE': ['MARR.MI', 'IG.MI'],
}


# ============================================================
# DATA FETCHING
# ============================================================
def fetch_prices(tickers, period='2y'):
    """Bulk download + fallback per-ticker. Robusto a fallimenti parziali."""
    if isinstance(tickers, str):
        tickers = [tickers]
    
    result = pd.DataFrame()
    
    # Strategy 1: bulk
    try:
        data = yf.download(
            tickers, period=period, auto_adjust=True,
            progress=False, threads=True, group_by='ticker'
        )
        if data is not None and not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                cols = {}
                for t in tickers:
                    try:
                        if t in data.columns.get_level_values(0):
                            s = data[t]['Close'].dropna()
                            if len(s) > 0:
                                cols[t] = s
                    except Exception:
                        pass
                if cols:
                    result = pd.DataFrame(cols)
            elif 'Close' in data.columns:
                close = data['Close']
                if isinstance(close, pd.Series):
                    result = close.to_frame(name=tickers[0])
                else:
                    result = close.dropna(axis=1, how='all')
    except Exception as e:
        print(f"  Bulk failed: {e}", file=sys.stderr)
    
    # Strategy 2: per-ticker fallback
    missing = [t for t in tickers if t not in result.columns or result[t].dropna().empty]
    for t in missing:
        try:
            hist = yf.Ticker(t).history(period=period, auto_adjust=True)
            if hist is not None and not hist.empty and 'Close' in hist.columns:
                s = hist['Close'].dropna()
                if len(s) > 0:
                    if s.index.tz is not None:
                        s.index = s.index.tz_localize(None)
                    result[t] = s
        except Exception as e:
            print(f"  Per-ticker {t} failed: {e}", file=sys.stderr)
    
    if not result.empty:
        result = result.dropna(axis=1, how='all')
        if result.index.tz is not None:
            result.index = result.index.tz_localize(None)
    
    return result


# ============================================================
# RRG · RS-Ratio + RS-Momentum (metodo JdK approssimato)
# ============================================================
def calculate_rrg(symbol_prices, benchmark_prices, window=14):
    sym_w = symbol_prices.resample('W-FRI').last()
    bench_w = benchmark_prices.resample('W-FRI').last()
    df = pd.concat([sym_w, bench_w], axis=1).dropna()
    df.columns = ['sym', 'bench']
    
    if len(df) < window * 5:
        return None
    
    rs = df['sym'] / df['bench']
    long_window = window * 4
    rs_mean = rs.rolling(window=long_window, min_periods=window*2).mean()
    rs_std = rs.rolling(window=long_window, min_periods=window*2).std()
    rs_z = (rs - rs_mean) / rs_std
    rs_ratio = 100 + rs_z.clip(-3.5, 3.5) * 3
    
    rs_roc = rs_ratio.diff(periods=window // 3)
    roc_std = rs_roc.rolling(window=long_window, min_periods=window*2).std()
    rs_mom_z = rs_roc / roc_std
    rs_momentum = 100 + rs_mom_z.clip(-3.5, 3.5) * 3
    
    out = pd.DataFrame({
        'rs_ratio': rs_ratio,
        'rs_momentum': rs_momentum
    }).dropna()
    return out if len(out) > 5 else None


def classify_quadrant(rs, mom):
    if pd.isna(rs) or pd.isna(mom):
        return 'N/A'
    if rs >= 100 and mom >= 100:
        return 'Leader'
    if rs < 100 and mom >= 100:
        return 'Emergente'
    if rs < 100 and mom < 100:
        return 'Debole'
    return 'In rallentamento'


def find_signal_dates(rrg_df, current_state):
    """
    Trova le date di ingresso nello stato attuale per tutti e 4 gli stati.
    
    Leader: ultima volta che RS >= 100 (e mom era già >= 100)
    Emergente: ultima volta che momentum >= 100 (con RS ancora < 100)
    In rallentamento: ultima volta che momentum < 100 (con RS ancora >= 100)
    Debole: ultima volta che RS < 100 (con mom ancora < 100)
    """
    if rrg_df is None or len(rrg_df) < 5:
        return None
    
    rs = rrg_df['rs_ratio'].values
    mom = rrg_df['rs_momentum'].values
    dates = rrg_df.index
    n = len(rs)
    
    result = {'state_entry_date': None, 'signal_date': None}
    
    if current_state == 'Leader':
        # entry: ultima volta che RS è passato da <100 a >=100
        entry_idx = None
        for i in range(n - 1, 0, -1):
            if rs[i] >= 100 and rs[i-1] < 100:
                entry_idx = i
                break
        if entry_idx is None and rs[0] >= 100:
            entry_idx = 0
        
        if entry_idx is not None:
            result['state_entry_date'] = dates[entry_idx].strftime('%Y-%m-%d')
            # signal: quando momentum è passato da <100 a >=100 (entrata in Emergente)
            signal_idx = entry_idx
            for i in range(entry_idx, 0, -1):
                if mom[i] >= 100 and mom[i-1] < 100:
                    signal_idx = i
                    break
            result['signal_date'] = dates[signal_idx].strftime('%Y-%m-%d')
    
    elif current_state == 'Emergente':
        # entry: ultima volta che momentum è passato da <100 a >=100
        entry_idx = None
        for i in range(n - 1, 0, -1):
            if mom[i] >= 100 and mom[i-1] < 100:
                entry_idx = i
                break
        if entry_idx is not None:
            result['state_entry_date'] = dates[entry_idx].strftime('%Y-%m-%d')
            result['signal_date'] = result['state_entry_date']
    
    elif current_state == 'In rallentamento':
        # entry: ultima volta che momentum è passato da >=100 a <100 (era Leader, ora rallenta)
        entry_idx = None
        for i in range(n - 1, 0, -1):
            if mom[i] < 100 and mom[i-1] >= 100:
                entry_idx = i
                break
        if entry_idx is not None:
            result['state_entry_date'] = dates[entry_idx].strftime('%Y-%m-%d')
            result['signal_date'] = result['state_entry_date']
    
    elif current_state == 'Debole':
        # entry: ultima volta che RS è passato da >=100 a <100 (entrata nella debolezza)
        # OPPURE momentum è passato da >=100 a <100 (caduto da Emergente)
        entry_idx = None
        for i in range(n - 1, 0, -1):
            # Caduto da Leader o In rallentamento (RS è sceso sotto 100)
            if rs[i] < 100 and rs[i-1] >= 100:
                entry_idx = i
                break
            # Oppure caduto da Emergente (momentum è sceso sotto 100, mentre RS era già < 100)
            if mom[i] < 100 and mom[i-1] >= 100 and rs[i] < 100:
                entry_idx = i
                break
        if entry_idx is not None:
            result['state_entry_date'] = dates[entry_idx].strftime('%Y-%m-%d')
            result['signal_date'] = result['state_entry_date']
    
    return result if result['state_entry_date'] else None


def perf_since(prices, date_str):
    """Calcola % di ritorno tra date_str e l'ultimo prezzo disponibile."""
    if not date_str or prices is None or len(prices) == 0:
        return None
    try:
        target = pd.to_datetime(date_str)
        idx = prices.index
        if idx.tz is not None:
            idx = idx.tz_localize(None)
            prices = prices.copy()
            prices.index = idx
        valid = prices[prices.index >= target]
        if len(valid) == 0:
            return None
        start_price = float(valid.iloc[0])
        end_price = float(prices.iloc[-1])
        return ((end_price / start_price) - 1) * 100
    except Exception:
        return None


def weeks_between(date_str, end_date):
    """Settimane tra date_str e end_date (Timestamp o stringa)."""
    if not date_str:
        return None
    try:
        d1 = pd.to_datetime(date_str)
        d2 = pd.to_datetime(end_date) if isinstance(end_date, str) else end_date
        if hasattr(d2, 'tz') and d2.tz is not None:
            d2 = d2.tz_localize(None)
        delta = (d2 - d1).days
        return max(0, int(round(delta / 7)))
    except Exception:
        return None


def classify_stage(prices, ma_weeks=30):
    weekly = prices.resample('W-FRI').last().dropna()
    if len(weekly) < ma_weeks + 8:
        return 'N/A'
    ma = weekly.rolling(window=ma_weeks).mean()
    ma_slope = (ma.diff(periods=4) / ma.shift(4)) * 100
    if pd.isna(ma.iloc[-1]) or pd.isna(ma_slope.iloc[-1]):
        return 'N/A'
    price = float(weekly.iloc[-1])
    ma_curr = float(ma.iloc[-1])
    slope = float(ma_slope.iloc[-1])
    distance_pct = ((price - ma_curr) / ma_curr) * 100
    
    if price > ma_curr:
        if slope > 0.3: return '2'
        if slope < -0.3: return '3'
        return '3' if distance_pct < 3 else '2'
    else:
        if slope < -0.3: return '4'
        return '1'


def compute_stock_entry(close, ma_weeks=30):
    """Data d'ingresso 'Weinstein' per un singolo titolo.

    Definizione: il titolo e' 'dentro' quando la chiusura settimanale e' sopra
    la propria MA a 30 settimane. La data d'ingresso e' la prima settimana del
    segmento continuativo PIU' RECENTE sopra la MA30 (l'ultima rottura al rialzo
    della media da una base).

    Restituisce un dict {entryDate, weeksFromEntry, perfFromEntry, stockStage}
    oppure None se il titolo e' attualmente sotto la MA30 (Stage 1 o 4: nessun
    ingresso attivo) o se lo storico e' insufficiente.

    `close` = serie pandas dei prezzi di chiusura (giornalieri, auto_adjust).
    """
    try:
        weekly = close.resample('W-FRI').last().dropna()
        if len(weekly) < ma_weeks + 8:
            return None
        ma = weekly.rolling(window=ma_weeks).mean()
        inside = (weekly > ma) & ma.notna()
        if not bool(inside.iloc[-1]):
            return None  # oggi sotto la MA30: nessun ingresso attivo
        # risali all'indietro finche' resta 'dentro'
        i = len(inside) - 1
        while i > 0 and bool(inside.iloc[i - 1]):
            i -= 1
        entry_ts = weekly.index[i]
        # Mappa l'etichetta settimanale (venerdi' nominale di fine periodo) all'ultima
        # data di trading REALE entro quella settimana: evita di mostrare un venerdi'
        # futuro quando l'aggiornamento gira a settimana in corso.
        real = close.index[close.index <= entry_ts]
        entry_real = real[-1] if len(real) else entry_ts
        entry_price = float(weekly.iloc[i])
        last_close = float(close.iloc[-1])
        weeks_from_entry = (len(weekly) - 1) - i
        perf_from_entry = (last_close / entry_price - 1) * 100 if entry_price > 0 else None
        # Distinzione settimana CHIUSA vs IN CORSO (parziale).
        # L'ultima barra e' "aperta" se il suo venerdi' nominale e' successivo
        # all'ultimo giorno di trading reale del titolo.
        last_real = close.index[-1]
        last_label = weekly.index[-1]
        last_bar_open = last_label.date() > last_real.date()
        last_closed_idx = (len(weekly) - 2) if last_bar_open else (len(weekly) - 1)
        # provvisorio = entrato sulla settimana ancora aperta (data "futura")
        entry_provisional = bool(i == (len(weekly) - 1) and last_bar_open)
        # ultima entrata confermata = entrato sull'ultima settimana gia' chiusa
        entry_last_closed = bool((not entry_provisional) and i == last_closed_idx)
        return {
            'entryDate': entry_real.date().isoformat(),
            'weeksFromEntry': int(weeks_from_entry),
            'perfFromEntry': round(perf_from_entry, 1) if perf_from_entry is not None else None,
            'stockStage': classify_stage(close),
            'entryProvisional': entry_provisional,
            'entryLastClosed': entry_last_closed,
        }
    except Exception:
        return None


# ============================================================
# COMPUTE METRICS
# ============================================================
def compute_sector_metrics(prices_df, bench_ticker, sector_dict):
    if bench_ticker not in prices_df.columns:
        return []
    bench_series = prices_df[bench_ticker].dropna()
    
    rows = []
    for ticker, name in sector_dict.items():
        if ticker not in prices_df.columns:
            continue
        sym_prices = prices_df[ticker].dropna()
        if len(sym_prices) < 100:
            continue
        
        rrg = calculate_rrg(sym_prices, bench_series)
        if rrg is None or len(rrg) < 6:
            continue
        
        last_rs = float(rrg['rs_ratio'].iloc[-1])
        last_mom = float(rrg['rs_momentum'].iloc[-1])
        prev_rs = float(rrg['rs_ratio'].iloc[-5]) if len(rrg) > 5 else last_rs
        quadrant = classify_quadrant(last_rs, last_mom)
        stage = classify_stage(sym_prices)
        
        # Performance
        roc_13w = ((sym_prices.iloc[-1] / sym_prices.iloc[-min(65, len(sym_prices)-1)]) - 1) * 100
        roc_52w = ((sym_prices.iloc[-1] / sym_prices.iloc[-min(252, len(sym_prices)-1)]) - 1) * 100
        
        bench_aligned = bench_series.reindex(sym_prices.index).dropna()
        if len(bench_aligned) > 65:
            sym_ret_13w = ((sym_prices.iloc[-1] / sym_prices.iloc[-65]) - 1) * 100
            bench_ret_13w = ((bench_aligned.iloc[-1] / bench_aligned.iloc[-65]) - 1) * 100
            rel_13w = sym_ret_13w - bench_ret_13w
        else:
            rel_13w = 0
        
        # Tail ultime 5 settimane
        tail_rs = [round(float(v), 2) for v in rrg['rs_ratio'].iloc[-5:].tolist()]
        tail_mom = [round(float(v), 2) for v in rrg['rs_momentum'].iloc[-5:].tolist()]
        
        # Serie 26 settimane per chart
        weeks_26 = rrg['rs_ratio'].iloc[-26:] if len(rrg) >= 26 else rrg['rs_ratio']
        rs_series = [
            {'date': d.strftime('%Y-%m-%d'), 'value': round(float(v), 2)}
            for d, v in weeks_26.items()
        ]
        
        # Storico segnali · per TUTTI gli stati (così possiamo testare anche i Debole)
        signal_info = None
        if quadrant in ('Leader', 'Emergente', 'In rallentamento', 'Debole'):
            sig = find_signal_dates(rrg, quadrant)
            if sig:
                last_data_date = sym_prices.index[-1]
                perf_from_state = perf_since(sym_prices, sig['state_entry_date'])
                perf_from_signal = perf_since(sym_prices, sig['signal_date'])
                
                # Perf vs benchmark dalle stesse date
                bench_for_perf = bench_series.copy()
                if bench_for_perf.index.tz is not None:
                    bench_for_perf.index = bench_for_perf.index.tz_localize(None)
                perf_bench_state = perf_since(bench_for_perf, sig['state_entry_date'])
                perf_bench_signal = perf_since(bench_for_perf, sig['signal_date'])
                
                signal_info = {
                    'stateEntryDate': sig['state_entry_date'],
                    'signalDate': sig['signal_date'],
                    'weeksFromState': weeks_between(sig['state_entry_date'], last_data_date),
                    'weeksFromSignal': weeks_between(sig['signal_date'], last_data_date),
                    'perfFromState': round(perf_from_state, 1) if perf_from_state is not None else None,
                    'perfFromSignal': round(perf_from_signal, 1) if perf_from_signal is not None else None,
                    'benchFromState': round(perf_bench_state, 1) if perf_bench_state is not None else None,
                    'benchFromSignal': round(perf_bench_signal, 1) if perf_bench_signal is not None else None,
                    'benchTicker': bench_ticker,
                    'relFromState': round(perf_from_state - perf_bench_state, 1) if (perf_from_state is not None and perf_bench_state is not None) else None,
                    'relFromSignal': round(perf_from_signal - perf_bench_signal, 1) if (perf_from_signal is not None and perf_bench_signal is not None) else None,
                }
        
        display_ticker = ticker.replace('.DE', '').replace('.US', '')
        
        rows.append({
            'ticker': display_ticker,
            'ticker_raw': ticker,
            'name': name,
            'stage': stage,
            'state': quadrant,
            'rsRatio': round(last_rs, 2),
            'rsMom': round(last_mom, 2),
            'delta5w': round(last_rs - prev_rs, 2),
            'roc13w': round(float(roc_13w), 1),
            'roc52w': round(float(roc_52w), 1),
            'rel13w': round(float(rel_13w), 1),
            'tailRS': tail_rs,
            'tailMom': tail_mom,
            'rsRatioSeries': rs_series,
            'signal': signal_info,
        })
    
    return rows


def compute_cross_region(prices_df):
    """Cross-region analysis: USA vs EU per settore omologo."""
    if US_BENCHMARK not in prices_df.columns or EU_BENCHMARK not in prices_df.columns:
        return []
    
    us_bench = prices_df[US_BENCHMARK].dropna()
    eu_bench = prices_df[EU_BENCHMARK].dropna()
    
    # Guard: se un benchmark e' troppo corto (es. buco temporaneo dei dati EU da
    # yfinance), salta il cross-region invece di andare out-of-bounds su iloc[-65].
    if len(us_bench) < 65 or len(eu_bench) < 65:
        return []
    
    rows = []
    for label, us_tick, eu_tick in CROSS_PAIRS:
        if us_tick not in prices_df.columns or eu_tick not in prices_df.columns:
            continue
        
        us = prices_df[us_tick].dropna()
        eu = prices_df[eu_tick].dropna()
        
        if len(us) < 65 or len(eu) < 65:
            continue
        
        us_rel = ((us.iloc[-1]/us.iloc[-65]) / (us_bench.iloc[-1]/us_bench.iloc[-65]) - 1) * 100
        eu_rel = ((eu.iloc[-1]/eu.iloc[-65]) / (eu_bench.iloc[-1]/eu_bench.iloc[-65]) - 1) * 100
        
        cross_now = us.iloc[-1] / eu.iloc[-1]
        cross_13w = us.iloc[-65] / eu.iloc[-65]
        cross_change = ((cross_now / cross_13w) - 1) * 100
        
        leader = 'USA' if cross_change > 0 else 'EU'
        
        rows.append({
            'label': label,
            'usT': us_tick.replace('.US', ''),
            'euT': eu_tick.replace('.DE', ''),
            'usRel': round(float(us_rel), 1),
            'euRel': round(float(eu_rel), 1),
            'cross': round(float(cross_change), 1),
            'leader': leader,
        })
    
    return rows


# ============================================================
# HOLDINGS · Drill-down su singoli titoli con P/E
# ============================================================
def fetch_ticker_fundamentals(symbol, signal_date=None):
    """Recupera P/E, market cap, nome, performance per un singolo ticker.
    Se signal_date è fornita, calcola anche la perf da quella data."""
    try:
        tk = yf.Ticker(symbol)
        info = tk.info or {}
        
        # Periodo esteso per coprire signal_date anche lontane
        hist = tk.history(period='2y', auto_adjust=True)
        if hist.empty:
            return None
        
        last_close = float(hist['Close'].iloc[-1])
        roc_13w = None
        roc_ytd = None
        perf_from_signal = None
        
        if len(hist) >= 65:
            roc_13w = float(((last_close / hist['Close'].iloc[-65]) - 1) * 100)
        
        # YTD
        current_year = hist.index[-1].year
        ytd_data = hist[hist.index.year == current_year]
        if not ytd_data.empty:
            roc_ytd = float(((last_close / ytd_data['Close'].iloc[0]) - 1) * 100)
        
        # Performance dal signal_date (se fornito)
        if signal_date:
            try:
                target = pd.to_datetime(signal_date)
                hist_idx = hist.index
                if hist_idx.tz is not None:
                    hist_idx = hist_idx.tz_localize(None)
                    hist_local = hist.copy()
                    hist_local.index = hist_idx
                else:
                    hist_local = hist
                valid = hist_local[hist_local.index >= target]
                if len(valid) > 0:
                    start_price = float(valid['Close'].iloc[0])
                    perf_from_signal = ((last_close / start_price) - 1) * 100
            except Exception:
                pass
        
        # P/E e altri multipli
        trailing_pe = info.get('trailingPE')
        forward_pe = info.get('forwardPE')
        peg = info.get('pegRatio') or info.get('trailingPegRatio')
        market_cap = info.get('marketCap')
        div_yield = info.get('dividendYield')
        
        name = info.get('shortName') or info.get('longName') or symbol
        if name and len(name) > 30:
            name = name[:28] + '..'
        
        # Data d'ingresso 'Weinstein' del titolo (riusa lo storico gia' scaricato)
        entry = compute_stock_entry(hist['Close'])
        
        return {
            'ticker': symbol,
            'name': name,
            'price': round(last_close, 2),
            'trailingPE': round(float(trailing_pe), 1) if trailing_pe and trailing_pe > 0 else None,
            'forwardPE': round(float(forward_pe), 1) if forward_pe and forward_pe > 0 else None,
            'peg': round(float(peg), 2) if peg and peg > 0 else None,
            'marketCapB': round(float(market_cap) / 1e9, 1) if market_cap else None,
            'divYield': round(float(div_yield), 2) if div_yield else None,
            'roc13w': round(roc_13w, 1) if roc_13w is not None else None,
            'rocYtd': round(roc_ytd, 1) if roc_ytd is not None else None,
            'perfFromSignal': round(perf_from_signal, 1) if perf_from_signal is not None else None,
            'entryDate': entry['entryDate'] if entry else None,
            'weeksFromEntry': entry['weeksFromEntry'] if entry else None,
            'perfFromEntry': entry['perfFromEntry'] if entry else None,
            'stockStage': entry['stockStage'] if entry else None,
            'entryProvisional': entry['entryProvisional'] if entry else False,
            'entryLastClosed': entry['entryLastClosed'] if entry else False,
        }
    except Exception as e:
        print(f"    Failed {symbol}: {e}", file=sys.stderr)
        return None


def compute_holdings_for_sector(sector_ticker, holdings_list, signal_date=None, etf_perf_from_signal=None):
    """Recupera fundamentals per tutte le holding di un settore e calcola:
    - P/E relativo (vs mediana del settore)
    - Performance dal segnale (se signal_date fornita)
    - Performance vs ETF settore (se etf_perf_from_signal fornita)
    - Tag 'premium giustificato' per titoli con P/E alto MA outperformance
    """
    print(f"  Holdings {sector_ticker}: scarico {len(holdings_list)} titoli (signal={signal_date})...")
    
    rows = []
    for sym in holdings_list:
        fund = fetch_ticker_fundamentals(sym, signal_date=signal_date)
        if fund:
            rows.append(fund)
    
    if not rows:
        return []
    
    # P/E relativo (vs mediana settore)
    valid_pe = [r['trailingPE'] for r in rows if r['trailingPE'] is not None]
    if valid_pe:
        median_pe = float(np.median(valid_pe))
        for r in rows:
            if r['trailingPE'] is not None:
                r['peRelative'] = round(r['trailingPE'] / median_pe, 2)
            else:
                r['peRelative'] = None
    else:
        for r in rows:
            r['peRelative'] = None
    
    # Performance relativa vs ETF settore (mantenuta come info di contesto)
    for r in rows:
        if r.get('perfFromSignal') is not None and etf_perf_from_signal is not None:
            r['perfVsEtf'] = round(r['perfFromSignal'] - etf_perf_from_signal, 1)
        else:
            r['perfVsEtf'] = None
    
    # Tag interpretativi · basati su Perf 3M (momentum corrente) + P/E
    # Identifico prima i top 3 per Perf 3M del settore (i veri leader correnti)
    valid_3m = [r for r in rows if r.get('roc13w') is not None]
    top3_tickers = set()
    if valid_3m:
        sorted_by_3m = sorted(valid_3m, key=lambda r: r['roc13w'], reverse=True)
        top3_tickers = {r['ticker'] for r in sorted_by_3m[:3]}
    
    for r in rows:
        tag = None
        perf_3m = r.get('roc13w')
        pe_rel = r.get('peRelative')
        
        if perf_3m is None:
            r['tag'] = None
            continue
        
        # 🚀 Top momentum: nei top 3 del settore per Perf 3M
        if r['ticker'] in top3_tickers and perf_3m > 5:
            tag = 'top_momentum'
        # 🪤 Value trap: P/E basso ma performance negativa significativa
        elif pe_rel is not None and pe_rel < 0.85 and perf_3m < -5:
            tag = 'value_trap'
        # 🎯 Sconto + momentum: P/E basso E performance positiva forte
        elif pe_rel is not None and pe_rel < 0.85 and perf_3m > 10:
            tag = 'value_momentum'
        # ⚠️ Caro e fermo: P/E alto ma performance debole
        elif pe_rel is not None and pe_rel > 1.20 and perf_3m < 5:
            tag = 'expensive_flat'
        # 💎 Premium ok: P/E alto E performance solida
        elif pe_rel is not None and pe_rel > 1.20 and perf_3m > 10:
            tag = 'premium_ok'
        # 💤 Stagnante: performance fra -5% e +5%
        elif -5 <= perf_3m <= 5:
            tag = 'stagnant'
        
        r['tag'] = tag
    
    # Ordino per Perf 3M decrescente · momentum corrente
    # Titoli senza perf_3m vanno in fondo
    def sort_key(r):
        perf = r.get('roc13w')
        if perf is None:
            return (1, 0)  # In fondo
        return (0, -perf)
    
    rows.sort(key=sort_key)
    return rows


def compute_all_holdings(metrics_list, holdings_dict, max_sectors=None):
    """Per i settori LEADER o EMERGENTE, calcola holdings con P/E.
    Sfrutta i signal_info già calcolati nei metrics per dare anche
    performance dal segnale e performance vs ETF settore."""
    if max_sectors is None:
        target_sectors = [m for m in metrics_list if m.get('state') in ('Leader', 'Emergente')]
    else:
        sorted_metrics = sorted(metrics_list, key=lambda m: m.get('rsRatio', 0), reverse=True)
        target_sectors = sorted_metrics[:max_sectors]
    
    out = {}
    for m in target_sectors:
        ticker = m.get('ticker_raw') or m.get('ticker')
        if ticker in holdings_dict:
            signal = m.get('signal') or {}
            holdings = compute_holdings_for_sector(
                ticker,
                holdings_dict[ticker],
                signal_date=signal.get('signalDate'),
                etf_perf_from_signal=signal.get('perfFromSignal')
            )
            if holdings:
                out[m.get('ticker')] = {
                    'sector_name': m.get('name'),
                    'sector_state': m.get('state'),
                    'signal_date': signal.get('signalDate'),
                    'etf_perf_from_signal': signal.get('perfFromSignal'),
                    'holdings': holdings,
                }
    return out



# ============================================================
# PORTFOLIO MODEL · Generazione automatica di allocazione modello
# ============================================================
def build_portfolio_model(us_metrics, eu_metrics, us_holdings, eu_holdings):
    """
    Costruisce allocazione modello su 3 profili (prudente/bilanciato/aggressivo).
    """
    
    def is_valid(sector):
        state = sector.get('state')
        stage = sector.get('stage', '')
        phase_num = None
        for c in stage:
            if c.isdigit():
                phase_num = int(c)
                break
        if state not in ('Leader', 'Emergente'):
            return False
        if phase_num is None or phase_num not in (1, 2):
            return False
        return True
    
    def calc_score(sector):
        state = sector.get('state')
        signal = sector.get('signal') or {}
        weeks = signal.get('weeksFromState') or 0
        rel_perf = signal.get('relFromState') or 0
        rs_ratio = sector.get('rsRatio') or 100
        stage = sector.get('stage', '')
        
        score = 0
        if state == 'Leader': score += 60
        elif state == 'Emergente': score += 40
        
        rs_excess = max(0, rs_ratio - 100)
        score += min(20, rs_excess * 2)
        score += min(15, max(0, rel_perf * 0.5))
        
        if state == 'Leader':
            if weeks > 40: score -= 10
            elif 5 <= weeks <= 25: score += 5
        elif state == 'Emergente':
            if weeks < 3: score -= 5
            elif weeks >= 5: score += 3
        
        if '2' in stage: score += 5
        return round(max(0, score), 1)
    
    all_sectors = []
    for s in us_metrics:
        if is_valid(s):
            all_sectors.append({**s, 'region': 'USA', 'score': calc_score(s)})
    for s in eu_metrics:
        if is_valid(s):
            all_sectors.append({**s, 'region': 'EU', 'score': calc_score(s)})
    
    all_sectors.sort(key=lambda x: x['score'], reverse=True)
    
    if not all_sectors:
        return {
            'comment': 'Nessun settore operativamente valido. Il sistema non rileva al momento Leader o Emergenti in fase coerente. Mantenere prevalenza di liquidità in attesa di nuovi segnali.',
            'profiles': {},
            'excluded_summary': [],
        }
    
    PROFILES = {
        'prudente':   {'equity_pct': 30, 'n_sectors': 3,    'max_per_sector': 12},
        'bilanciato': {'equity_pct': 50, 'n_sectors': 5,    'max_per_sector': 12},
        # Aggressivo: tutti i settori validi disponibili, max teorico 20 ma in pratica
        # saranno 7-12 a seconda di quanti Leader/Emergente in Fase 1/2 ci sono
        'aggressivo': {'equity_pct': 80, 'n_sectors': None, 'max_per_sector': 14},
    }
    
    def get_top_picks(region, sector_ticker, n=3):
        holdings_dict = us_holdings if region == 'USA' else eu_holdings
        info = holdings_dict.get(sector_ticker)
        if not info or not info.get('holdings'):
            return []
        rows = info['holdings']
        filtered = [r for r in rows if r.get('tag') != 'value_trap']
        return filtered[:n]
    
    profiles_out = {}
    for profile_name, cfg in PROFILES.items():
        # n_sectors=None significa "tutti i settori validi disponibili"
        if cfg['n_sectors'] is None:
            selected = all_sectors[:]  # tutti
        else:
            selected = all_sectors[:cfg['n_sectors']]
        if not selected:
            continue
        
        total_score = sum(s['score'] for s in selected)
        equity_pct = cfg['equity_pct']
        max_pct = cfg['max_per_sector']
        
        allocations = []
        residual = 0
        for s in selected:
            proportion = s['score'] / total_score if total_score > 0 else 1.0 / len(selected)
            weight = proportion * equity_pct
            if weight > max_pct:
                residual += weight - max_pct
                weight = max_pct
            allocations.append({'sector': s, 'weight': weight})
        
        guard = 0
        while residual > 0.1 and guard < 10:
            redistributable = [a for a in allocations if a['weight'] < max_pct - 0.01]
            if not redistributable:
                break
            extra = residual / len(redistributable)
            residual = 0
            for a in redistributable:
                room = max_pct - a['weight']
                add = min(extra, room)
                a['weight'] += add
                residual += extra - add
            guard += 1
        
        cash_pct = 100 - equity_pct
        
        profile_items = []
        for a in allocations:
            s = a['sector']
            # NB: holdings_dict usa 'ticker' semplificato (es. 'EXV2'), non 'ticker_raw' (es. 'EXV2.DE')
            ticker_key = s.get('ticker')
            picks_us = get_top_picks('USA', ticker_key, 3) if s['region'] == 'USA' else []
            picks_it = get_top_picks('EU', ticker_key, 3) if s['region'] == 'EU' else []
            signal = s.get('signal') or {}
            
            profile_items.append({
                'sector_name': s['name'],
                'sector_ticker': s['ticker'],
                'region': s['region'],
                'state': s['state'],
                'stage': s.get('stage', ''),
                'weight_pct': round(a['weight'], 1),
                'score': s['score'],
                'weeks_from_state': signal.get('weeksFromState'),
                'perf_from_state': signal.get('perfFromState'),
                'rel_from_state': signal.get('relFromState'),
                'picks_us': [{'ticker': p['ticker'], 'name': p['name'], 'perf_3m': p.get('roc13w'), 'pe_rel': p.get('peRelative'), 'tag': p.get('tag'), 'entry_date': p.get('entryDate'), 'weeks_from_entry': p.get('weeksFromEntry'), 'perf_from_entry': p.get('perfFromEntry'), 'stock_stage': p.get('stockStage'), 'entry_provisional': p.get('entryProvisional'), 'entry_last_closed': p.get('entryLastClosed')} for p in picks_us],
                'picks_it': [{'ticker': p['ticker'], 'name': p['name'], 'perf_3m': p.get('roc13w'), 'pe_rel': p.get('peRelative'), 'tag': p.get('tag'), 'entry_date': p.get('entryDate'), 'weeks_from_entry': p.get('weeksFromEntry'), 'perf_from_entry': p.get('perfFromEntry'), 'stock_stage': p.get('stockStage'), 'entry_provisional': p.get('entryProvisional'), 'entry_last_closed': p.get('entryLastClosed')} for p in picks_it],
            })
        
        profiles_out[profile_name] = {
            'equity_pct': equity_pct,
            'cash_pct': cash_pct,
            'allocations': profile_items,
        }
    
    # Genera commento di scenario
    n_leaders = sum(1 for s in all_sectors if s['state'] == 'Leader')
    n_emerging = sum(1 for s in all_sectors if s['state'] == 'Emergente')
    
    sector_themes = {}
    for s in all_sectors[:7]:
        name = s['name'].lower()
        theme = None
        if 'energia' in name: theme = 'Energia'
        elif 'tecnologia' in name or 'semicon' in name: theme = 'Tecnologia'
        elif 'banc' in name or 'finanz' in name: theme = 'Finanziari'
        elif 'sanit' in name or 'biotech' in name: theme = 'Sanità'
        elif 'consum' in name or 'retail' in name or 'aliment' in name: theme = 'Consumi'
        elif 'industri' in name: theme = 'Industriali'
        elif 'telecom' in name or 'comunic' in name: theme = 'Comunicazioni'
        elif 'utility' in name: theme = 'Utility'
        elif 'immobili' in name: theme = 'Immobiliare'
        elif 'materiali' in name or 'risorse' in name or 'chimica' in name: theme = 'Materiali'
        elif 'assicur' in name: theme = 'Assicurazioni'
        elif 'personal' in name or 'lusso' in name: theme = 'Lusso'
        if theme:
            sector_themes.setdefault(theme, []).append(s)
    
    top_theme = max(sector_themes.items(), key=lambda x: len(x[1]))[0] if sector_themes else None
    
    excluded = []
    for s in (us_metrics + eu_metrics):
        if s.get('state') in ('Debole', 'In rallentamento'):
            signal = s.get('signal') or {}
            rel = signal.get('relFromState')
            if rel is not None and rel < -8:
                excluded.append({
                    'ticker': s.get('ticker'),
                    'name': s.get('name'),
                    'state': s.get('state'),
                    'rel_perf': rel,
                })
    excluded.sort(key=lambda x: x['rel_perf'])
    excluded_top5 = excluded[:5]
    
    parts = []
    parts.append(f"📊 Quadro attuale: {n_leaders} settori Leader confermati e {n_emerging} Emergenti operativamente validi.")
    if top_theme:
        parts.append(f"Tema centrale: {top_theme}.")
    
    mature_leaders = [s for s in all_sectors if s['state'] == 'Leader' and (s.get('signal') or {}).get('weeksFromState', 0) > 40]
    if mature_leaders:
        names = ', '.join(s['ticker'] for s in mature_leaders)
        wk = mature_leaders[0].get('signal', {}).get('weeksFromState')
        parts.append(f"⚠️ Leader maturo: {names} ({wk} settimane di leadership) — peso ridotto nel modello per rischio di top.")
    
    fresh_emerging = [s for s in all_sectors if s['state'] == 'Emergente' and (s.get('signal') or {}).get('weeksFromState', 0) < 5]
    if fresh_emerging:
        names = ', '.join(s['ticker'] for s in fresh_emerging)
        parts.append(f"🆕 Emergenti freschi (da monitorare nelle prossime settimane): {names}.")
    
    if excluded_top5:
        names = ', '.join(f"{e['ticker']} ({e['rel_perf']:+.1f}%)" for e in excluded_top5[:3])
        parts.append(f"❌ Settori esclusi per alpha negativa significativa: {names}.")
    
    return {
        'comment': ' '.join(parts),
        'profiles': profiles_out,
        'excluded_summary': excluded_top5,
    }


# ============================================================
# RANKING SETTORI · classifica forza con confronto settimana precedente
# ============================================================
def compute_sector_ranking(us_metrics, eu_metrics, history_path='data/ranking_history.json'):
    """
    Costruisce la classifica globale (USA + EU) ordinata per forza,
    e confronta con lo snapshot di 7 giorni fa.
    
    Punteggio di forza basato su:
    - Stato del settore (Leader=100, Emergente=70, In rallentamento=40, Debole=10)
    - Forza relativa attuale (rsRatio - 100, scaling)
    - Performance dal segnale vs benchmark (alpha)
    - Settimane nello stato (penalità per Leader maturi)
    """
    
    def score_sector(s):
        state = s.get('state')
        signal = s.get('signal') or {}
        rs_ratio = s.get('rsRatio') or 100
        rel_perf = signal.get('relFromState') or 0
        weeks = signal.get('weeksFromState') or 0
        stage = s.get('stage', '')
        
        # Punteggio base in funzione dello stato
        if state == 'Leader':
            base = 100
        elif state == 'Emergente':
            base = 70
        elif state == 'In rallentamento':
            base = 40
        elif state == 'Debole':
            base = 10
        else:
            base = 50
        
        # Componente forza relativa (rs_ratio centrato a 100)
        rs_component = (rs_ratio - 100) * 2  # ogni punto sopra 100 vale 2
        
        # Componente alpha vs benchmark (puoi guadagnare/perdere fino a +/- 30)
        alpha_component = max(-30, min(30, rel_perf * 0.5))
        
        # Penalità per Leader maturo (rischio top)
        maturity_penalty = 0
        if state == 'Leader' and weeks > 40:
            maturity_penalty = -10
        elif state == 'Leader' and weeks > 60:
            maturity_penalty = -20
        
        # Bonus Fase 2 (trend rialzista confermato)
        phase_bonus = 0
        if '2' in stage:
            phase_bonus = 5
        elif '4' in stage:
            phase_bonus = -5
        
        total = base + rs_component + alpha_component + maturity_penalty + phase_bonus
        return round(total, 1)
    
    # Combina USA + EU
    all_sectors = []
    for s in us_metrics:
        all_sectors.append({
            'ticker': s.get('ticker'),
            'name': s.get('name'),
            'region': 'USA',
            'state': s.get('state'),
            'stage': s.get('stage'),
            'rsRatio': s.get('rsRatio'),
            'rsMom': s.get('rsMom'),
            'signal': s.get('signal'),
            'roc52w': s.get('roc52w'),
            'score': score_sector(s),
        })
    for s in eu_metrics:
        all_sectors.append({
            'ticker': s.get('ticker'),
            'name': s.get('name'),
            'region': 'EU',
            'state': s.get('state'),
            'stage': s.get('stage'),
            'rsRatio': s.get('rsRatio'),
            'rsMom': s.get('rsMom'),
            'signal': s.get('signal'),
            'roc52w': s.get('roc52w'),
            'score': score_sector(s),
        })
    
    # Ordina per punteggio decrescente
    all_sectors.sort(key=lambda x: x['score'], reverse=True)
    
    # Assegna posizione corrente
    for i, s in enumerate(all_sectors):
        s['rank'] = i + 1
    
    # Carica storico precedente (se esiste)
    prev_ranks = {}
    prev_valid = {}
    prev_roc = {}
    prev_date = None
    history = []
    try:
        if os.path.exists(history_path):
            with open(history_path, 'r') as f:
                history = json.load(f)
    except Exception as e:
        print(f"  Storico ranking non disponibile: {e}", file=sys.stderr)
        history = []
    
    # Trova snapshot 5-9 giorni fa (per confronto "settimana precedente")
    today = datetime.now(timezone.utc).date()
    for snap in reversed(history):
        try:
            snap_date = datetime.fromisoformat(snap['date']).date()
            days_diff = (today - snap_date).days
            if 5 <= days_diff <= 9:
                prev_ranks = {r['ticker']: r['rank'] for r in snap.get('ranks', [])}
                prev_valid = {r['ticker']: r.get('valid') for r in snap.get('ranks', [])}
                prev_roc = {r['ticker']: r.get('roc52w') for r in snap.get('ranks', [])}
                prev_date = snap['date']
                break
        except Exception:
            continue
    
    # Aggiungi delta vs settimana precedente
    for s in all_sectors:
        prev = prev_ranks.get(s['ticker'])
        if prev is not None:
            delta = prev - s['rank']  # positivo = salito in classifica
            if delta > 0:
                s['rank_change'] = delta  # numero di posizioni guadagnate
                s['rank_direction'] = 'up'
            elif delta < 0:
                s['rank_change'] = abs(delta)
                s['rank_direction'] = 'down'
            else:
                s['rank_change'] = 0
                s['rank_direction'] = 'flat'
            s['prev_rank'] = prev
        else:
            s['rank_change'] = None
            s['rank_direction'] = 'new'
            s['prev_rank'] = None
    
    # Salva snapshot odierno (mantenendo storico di 30 giorni)
    today_snapshot = {
        'date': datetime.now(timezone.utc).isoformat(),
        'ranks': [{'ticker': s['ticker'], 'rank': s['rank'], 'score': s['score'],
                   'valid': (s.get('state') in ('Leader', 'Emergente') and str(s.get('stage')) in ('1', '2')),
                   'roc52w': s.get('roc52w')}
                  for s in all_sectors],
    }
    # Rimuovi snapshot precedente dello stesso giorno
    history = [h for h in history if not h.get('date', '').startswith(today.isoformat())]
    history.append(today_snapshot)
    # Mantieni solo ultimi 35 giorni
    if len(history) > 35:
        history = history[-35:]
    
    try:
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        with open(history_path, 'w') as f:
            json.dump(history, f, indent=2)
        print(f"  Snapshot salvato in {history_path}")
    except Exception as e:
        print(f"  Errore salvataggio storico: {e}", file=sys.stderr)
    
    # --- Movimenti della settimana: entrati/usciti dal trend (gate valido) vs ~7 giorni fa ---
    def _is_valid(s):
        return s.get('state') in ('Leader', 'Emergente') and str(s.get('stage')) in ('1', '2')
    have_prev_valid = bool(prev_valid) and any(v is not None for v in prev_valid.values())
    entered, exited = [], []
    if have_prev_valid:
        for s in all_sectors:
            pv = prev_valid.get(s['ticker'])
            now = _is_valid(s)
            info = {'ticker': s['ticker'], 'name': s['name'], 'region': s['region'],
                    'state': s['state'], 'stage': s['stage'], 'score': s['score']}
            if now and pv is False:
                entered.append(info)
            elif (not now) and pv is True:
                exited.append(info)
    weekly_moves = {
        'entered': entered,
        'exited': exited,
        'prev_date': prev_date,
        'available': have_prev_valid,
    }

    # --- Top 10 dell'anno (roc52w rolling 52 sett.) + entrate/uscite dalla top-10 ---
    ranked_roc = sorted([s for s in all_sectors if s.get('roc52w') is not None],
                        key=lambda x: x['roc52w'], reverse=True)
    now_set = set(s['ticker'] for s in ranked_roc[:10])
    have_prev_roc = bool(prev_roc) and any(v is not None for v in prev_roc.values())
    t10_entered, t10_exited = [], []
    if have_prev_roc:
        prev_sorted = sorted([tk for tk, v in prev_roc.items() if v is not None],
                             key=lambda tk: prev_roc[tk], reverse=True)
        prev_set = set(prev_sorted[:10])
        by_tk = {s['ticker']: s for s in all_sectors}
        for tk in (now_set - prev_set):
            s = by_tk.get(tk)
            if s:
                t10_entered.append({'ticker': tk, 'name': s['name'], 'region': s['region'], 'roc52w': s.get('roc52w')})
        for tk in (prev_set - now_set):
            s = by_tk.get(tk)
            if s:
                t10_exited.append({'ticker': tk, 'name': s['name'], 'region': s['region'], 'roc52w': s.get('roc52w')})
    top10_moves = {
        'entered': t10_entered,
        'exited': t10_exited,
        'prev_date': prev_date,
        'available': have_prev_roc,
    }

    return {
        'ranking': all_sectors,
        'prev_snapshot_date': prev_date,
        'weekly_moves': weekly_moves,
        'top10_moves': top10_moves,
    }


def main():
    print("Sector Rotation · Data Update")
    print("=" * 60)
    
    all_tickers = (
        [US_BENCHMARK] + list(US_SECTORS.keys()) +
        [EU_BENCHMARK] + list(EU_SECTORS.keys())
    )
    all_tickers = list(set(all_tickers))
    
    print(f"Scarico {len(all_tickers)} ticker da yfinance...")
    prices = fetch_prices(all_tickers, period='2y')
    
    obtained = list(prices.columns)
    missing = [t for t in all_tickers if t not in obtained]
    print(f"  Ottenuti: {len(obtained)}/{len(all_tickers)}")
    if missing:
        print(f"  Mancanti: {', '.join(missing)}")
    
    if prices.empty:
        print("ERRORE: nessun dato scaricato.", file=sys.stderr)
        sys.exit(1)
    
    print("\nCalcolo metriche USA...")
    us_metrics = compute_sector_metrics(prices, US_BENCHMARK, US_SECTORS)
    print(f"  {len(us_metrics)} settori USA elaborati")
    
    print("Calcolo metriche EU...")
    eu_metrics = compute_sector_metrics(prices, EU_BENCHMARK, EU_SECTORS)
    print(f"  {len(eu_metrics)} settori EU elaborati")
    
    # Salvaguardia: se un'intera regione e' vuota, yfinance ha bucato i dati
    # (tipico coi ticker Xetra .DE). Meglio fermarsi PRIMA di salvare, cosi' non
    # si sovrascrive il sector_data.json valido del run precedente con dati parziali.
    if len(us_metrics) == 0 or len(eu_metrics) == 0:
        regione = 'EU' if len(eu_metrics) == 0 else 'USA'
        print(f"\n✗ ABORT: 0 settori {regione} elaborati — dati incompleti da yfinance "
              f"(probabile buco temporaneo su {EU_BENCHMARK if regione=='EU' else US_BENCHMARK}).",
              file=sys.stderr)
        print("  Il file dati NON e' stato toccato. Rilancia il workflow tra qualche minuto.",
              file=sys.stderr)
        sys.exit(1)
    
    print("Calcolo cross-region...")
    cross_rows = compute_cross_region(prices)
    print(f"  {len(cross_rows)} coppie cross-region")
    
    # Holdings drill-down: settori LEADER + EMERGENTE
    print("\nDrill-down titoli per settori LEADER + EMERGENTE (USA)...")
    us_holdings = compute_all_holdings(us_metrics, US_HOLDINGS)
    print(f"  {len(us_holdings)} settori USA elaborati")
    
    print("Drill-down titoli per settori LEADER + EMERGENTE (EU/Italia)...")
    eu_holdings = compute_all_holdings(eu_metrics, EU_HOLDINGS)
    print(f"  {len(eu_holdings)} settori EU/Italia elaborati")
    
    # Costruisce la classifica di forza con confronto settimana precedente
    print("\nCostruzione classifica di forza...")
    ranking_data = compute_sector_ranking(us_metrics, eu_metrics)
    print(f"  {len(ranking_data['ranking'])} settori classificati")
    if ranking_data.get('prev_snapshot_date'):
        print(f"  Confronto con snapshot del {ranking_data['prev_snapshot_date'][:10]}")
    
    # Costruisce il portafoglio modello automatico
    print("\nCostruzione portafoglio modello...")
    portfolio = build_portfolio_model(us_metrics, eu_metrics, us_holdings, eu_holdings)
    print(f"  Profili generati: {list(portfolio['profiles'].keys())}")
    
    # Date più recente nei dati
    last_data_date = prices.index[-1].strftime('%Y-%m-%d')
    
    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_data_date': last_data_date,
        'tickers_obtained': len(obtained),
        'tickers_total': len(all_tickers),
        'tickers_missing': missing,
        'us': {
            'benchmark': US_BENCHMARK,
            'benchmark_label': 'S&P 500',
            'sectors': us_metrics,
            'holdings': us_holdings,
        },
        'eu': {
            'benchmark': EU_BENCHMARK,
            'benchmark_label': 'STOXX 600',
            'sectors': eu_metrics,
            'holdings': eu_holdings,
        },
        'cross': cross_rows,
        'portfolio': portfolio,
        'ranking': ranking_data,
    }
    
    out_path = Path(__file__).parent.parent / 'data' / 'sector_data.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ Salvato in {out_path}")
    print(f"  Dimensione: {out_path.stat().st_size / 1024:.1f} KB")
    print(f"  Data ultimi dati: {last_data_date}")

    # ---- Forward log: snapshot settimanale dei settori validi e dei picks ----
    # Storico "vero" che cresce a ogni run; complementa il backtest retrospettivo.
    try:
        log_path = Path(__file__).parent.parent / 'data' / 'signals_log.json'
        log = []
        if log_path.exists():
            with open(log_path, encoding='utf-8') as f:
                log = json.load(f)
        # snapshot dei picks dal profilo 'bilanciato' (rappresentativo)
        picks_snap = []
        prof = (portfolio.get('profiles') or {}).get('bilanciato') or {}
        for a in prof.get('allocations', []):
            for key in ('picks_us', 'picks_it'):
                for p in a.get(key, []):
                    picks_snap.append({
                        'ticker': p.get('ticker'),
                        'sector': a.get('sector_name'),
                        'region': a.get('region'),
                        'entry_date': p.get('entry_date'),
                        'perf_from_entry': p.get('perf_from_entry'),
                    })
        valid_sectors = [{'ticker': a.get('sector_ticker'), 'name': a.get('sector_name'),
                          'region': a.get('region'), 'state': a.get('state'), 'stage': a.get('stage')}
                         for a in prof.get('allocations', [])]
        snap = {'date': last_data_date, 'updated_at': output['updated_at'],
                'valid_sectors': valid_sectors, 'picks': picks_snap}
        # last-write-wins per la stessa data (evita duplicati su run multipli)
        log = [e for e in log if e.get('date') != last_data_date]
        log.append(snap)
        log = log[-520:]  # ~10 anni di settimane, cap di sicurezza
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=1)
        print(f"  Forward log: {len(log)} snapshot in {log_path.name}")
    except Exception as e:
        print(f"  ! Forward log non aggiornato: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
