# Sector Rotation Lab

Dashboard di rotazione settoriale che si aggiorna automaticamente ogni giorno via GitHub Actions.

## Cosa fa

- **Mappa di Rotazione (RRG)** dei settori USA (SPDR) ed europei (iShares STOXX 600)
- **Fasi del trend** (Weinstein) per ogni settore
- **Confronto USA vs Europa** per settore omologo
- **Dati aggiornati ogni giorno** automaticamente, senza interventi manuali

## Setup (una volta sola, ~10 minuti)

### 1. Crea un nuovo repo su GitHub

- Vai su [github.com/new](https://github.com/new)
- Nome: per esempio `sector-rotation` (puoi scegliere)
- **Pubblico** (necessario per GitHub Pages gratuito)
- Non aggiungere README/license: li carichiamo noi

### 2. Carica i file di questo progetto

Carica nel repo, mantenendo la struttura cartelle:

```
sector-rotation/
├── .github/workflows/update.yml
├── scripts/update_data.py
├── data/sector_data.json        ← generato al primo run
├── index.html
└── README.md
```

Puoi farlo:
- Da web: trascina i file uno a uno (devi creare le cartelle dal pulsante "Add file")
- Da git: `git clone`, copia i file, `git add .`, `git commit`, `git push`

### 3. Attiva GitHub Pages

- Vai su **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: **main** · folder: **/ (root)**
- Salva

Dopo 1-2 minuti la dashboard sarà online a:
```
https://TUO-USERNAME.github.io/sector-rotation/
```

### 4. Esegui il primo aggiornamento dati

Il workflow è schedulato ogni giorno alle 22:00 UTC, ma per il primo caricamento devi lanciarlo manualmente:

- Vai su **Actions** del repo
- Seleziona **"Update Sector Data"** nella sidebar sinistra
- Clicca **"Run workflow" → Run workflow** (verde, in alto a destra)
- Aspetta ~1 minuto: si crea `data/sector_data.json`

### 5. Apri la dashboard

```
https://TUO-USERNAME.github.io/sector-rotation/
```

Da qui in avanti, il workflow si esegue da solo ogni giorno (lunedì-venerdì, dopo chiusura USA). Apri il link quando vuoi e vedi sempre i dati più recenti.

## Personalizzazione

### Cambiare quali settori monitorare

Modifica `scripts/update_data.py`, sezioni `US_SECTORS` ed `EU_SECTORS`. Aggiungi/togli ticker (devono essere validi su Yahoo Finance).

### Cambiare frequenza di aggiornamento

In `.github/workflows/update.yml`, riga `cron`:

- `'0 22 * * 1-5'` = ogni giorno lavorativo alle 22:00 UTC (attuale)
- `'0 22 * * 5'` = solo il venerdì sera (aggiornamento settimanale)
- `'0 */6 * * *'` = ogni 6 ore

Cron syntax: [crontab.guru](https://crontab.guru)

### Eseguire localmente per test

```bash
pip install yfinance pandas numpy
python scripts/update_data.py
```

Poi apri `index.html` con un server locale (la lettura del JSON via `file://` può essere bloccata dal browser):

```bash
python -m http.server 8000
# poi apri http://localhost:8000
```

## Architettura

- **GitHub Actions** scarica i prezzi via `yfinance` (server-side, nessun problema CORS), calcola tutte le metriche, salva `data/sector_data.json`
- **GitHub Pages** ospita gratuitamente i file statici (HTML + JSON)
- **L'HTML** legge il JSON al caricamento e renderizza dashboard, grafici, tabelle con Chart.js + SVG custom

Nessun server da gestire, nessun costo, scaling automatico.

## Metodologia

- **Forza relativa** (RS-Ratio): Z-score rolling 14 settimane del rapporto prezzo settore / benchmark, normalizzato attorno a 100
- **Velocità** (RS-Momentum): Z-score della variazione di RS-Ratio
- **Fasi del trend** (Stan Weinstein): posizione del prezzo rispetto alla media mobile a 30 settimane + pendenza della MA
- **Dati settimanali** (chiusura venerdì) per ridurre rumore

## Disclaimer

Strumento per uso personale. Non costituisce raccomandazione di investimento. I dati provengono da Yahoo Finance via `yfinance` e possono contenere errori o ritardi.
