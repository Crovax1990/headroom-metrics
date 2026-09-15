# headroom-metrics

Dashboard locale (solo stdlib, zero dipendenze) che mostra consumi Headroom / OpenCode Go,
proiezione Standard fino al reset quota e forecast giorno/mese/anno a prezzi reali.

- **Vive su** `http://127.0.0.1:8790/` (il proxy Headroom resta su `:8787`)
- **Sorgente primaria**: `GET http://127.0.0.1:8787/stats-history` (serie storiche + totali in una chiamata)
- **Quota reale OpenCode**: snapshot manuale in `exports/quota-models.json` (nessuna API pubblica esiste — vedi sotto)

## Stato attuale (verificato live)

| Voce | Valore |
|---|---|
| Quota usata | $23.3891 / $60 → **38.98% ≈ 39%** |
| Muse Spark 1.3 Contributor | $22.1727 (36.95%) |
| DeepSeek V4.1 Flash | $1.2035 (2.01%) |
| Muse Spark 1.2 Contributor | $0.0129 (0.02%) |
| Reset quota | 2026-10-09 |
| Servizi | `headroom-default.service` (:8787) + `headroom-metrics.service` (:8790), entrambi `enabled`+`active`, `Linger=yes` |

## Avvio rapido

```bash
cd ~/workspace/headroom-metrics
uv sync
uv run --no-sync headroom_dashboard.py                 # default: :8790, sorgente live + fallback file
uv run --no-sync headroom_dashboard.py --emit report.html   # snapshot statico, esce subito
```

I servizi di produzione girano via systemd user unit (vedi `RUNBOOK.md`); non avviare
istanze manuali sulle stesse porte.

## Sorgenti dati e quota

Ordine `--sources` (ripetibile): prima `http://127.0.0.1:8787/stats-history`, poi `./exports/*.json`.
Le sorgenti morte vengono saltate con warning; a pagina vuota la dashboard mostra un banner
d'errore invece di crashare. Pulsante **Refresh** (`/refresh`) rilegge tutto senza riavvio.

Quota (`--quota 60 --reset 2026-10-09` di default), precedenza:
1. `--quota-url` — endpoint JSON generico `{used,total,reset,models:[{model,usd}]}`,
   auth via `Authorization: Bearer $OPENCODE_API_TOKEN`; qualsiasi errore → fallthrough
2. `--quota-models '{...}'` / `--quota-models-file` (default `./exports/quota-models.json`) + `--quota-used`
3. fallback: costo lifetime ricalcolato dai token

> **Nota OpenCode API**: al 2026-09-15 non esiste un endpoint pubblico/documentato per la quota
> (workspace dietro login OpenAuth; l'SDK in `/docs/sdk` pilota solo il server locale `:4096`).
> I valori in `exports/quota-models.json` vanno aggiornati a mano dalla pagina workspace.
> Se individui la chiamata del frontend (DevTools → Network), punta `--quota-url` lì.

## Prezzi reali per-modello (fonte: [docs Go](https://opencode.ai/docs/go))

| Modello | Input/1M | Output/1M | Cache/1M | Monthly limit |
|---|---|---|---|---|
| Muse Spark 1.3/1.2 Contributor | $0.10 | $0.20 | $0.002 | $60 |
| DeepSeek V4.1 Flash (Peak) | $0.30 | $1.20 | $0.006 | $15 |

La dashboard usa i peak DeepSeek (sovrastima ~2x in off-peak, dichiarato nel footer).
Stesso triple corretto in `~/.headroom/config/models.json` (+ mirror `HEADROOM_MODEL_LIMITS`
in `~/.bashrc:161`); backup `models.json.2026-09-15-1437.bak`; rollback in `RUNBOOK.md` §3.
Le % del sito sono sul workspace $60 — la dashboard resta allineata al sito.

## Proiezione Standard (trend su tutto lo storico)

Unico scenario `STD`: fit ai minimi quadrati su TUTTI i `series.daily` (nessun cap 14gg;
il cap resta solo per le righe mostrate in tabella), ricalcolato live a ogni request.
`forecast(d)=max(trend_today+m*d,0)` con `trend_today` = valore trend oggi e `m` = pendenza
token/giorno; giornaliera = forecast(0), mensile = cumulato mese + somma trend sui giorni
rimanenti (`calendar.monthrange`), annuale = somma 365g da oggi. Fallback media: se `days_observed<7`
o pendenza negativa, `forecast(d)=mean_all` con `note:"fallback media: storico corto o pendenza negativa"`
(pendenza riportata comunque as-is). Costi al rate pesato
`weighted_rate_usd_per_token()` sul mix lifetime. A storico assente: zeri + `note:"storico assente"`.

## Endpoint dashboard

| Endpoint | Risposta |
|---|---|
| `/` | pagina HTML (template `dashboard.html`, hot-reload a ogni modifica) |
| `/refresh`, `/api/stats` | JSON: `lifetime`, `quota{used,total,pct,left,days_left,reset}`, `quota_models[]`, `scenarios[1 STD]`, `projection{days_observed,mean_daily_tokens,slope,daily,monthly,annual,models}`, `daily[≤14]`, `monthly{cumulato+stima}`, `profiles`, `horizon` |
| `/health` | `ok` |

## Layout repo

```
headroom_dashboard.py   server + analisi + scenario Standard (stdlib only)
dashboard.html          template (placeholder @@PAYLOAD@@ / @@QUOTA@@)
exports/                quota-models.json (snapshot quota) + export JSON opzionali
RUNBOOK.md              comandi operativi, rollback pricing, boot note
AGENTS.md               note per agent (non duplicare qui i comandi: vedi RUNBOOK)
pyproject.toml          progetto uv, dependencies = []
```

## Operatività

Tutto in `RUNBOOK.md`: status/start/stop/logs/health per entrambe le unit, rollback pricing,
`headroom install remove` come last resort. Mai modificare a mano
`~/.headroom/proxy_savings.json`. `HEADROOM_PORT` muove solo il proxy; la porta dashboard
è solo il flag `--port`.
