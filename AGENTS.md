# AGENTS.md — headroom-metrics

Istruzioni per agent che lavorano su questo repo. Comandi operativi completi: `RUNBOOK.md`.
Architettura e scelte: `README.md`. Non duplicare qui tabelle/comandi già presenti lì.

## Natura del repo

- Script Python stdlib-only (`headroom_dashboard.py`, ~500 righe) + template separato (`dashboard.html`).
  Zero dipendenze: `pyproject.toml` ha `dependencies = []`, si avvia con `uv run --no-sync`.
- Non è un servizio deployato da qui: la produzione gira via **systemd user unit**
  `headroom-metrics.service` (porta **8790**). Il proxy Headroom è un'altra unit
  (`headroom-default.service`, porta **8787**). Mai occupare quelle porte a mano
  (per prove usare `--port 8791/8792` + `--emit`, processi sempre killati e verificati con `ss`).
- Ogni pagina/API rilegge le sorgenti live (`/stats-history` Headroom + file locali);
  le sorgenti morte danno warning + banner, mai crash.

## Regole dure

1. **Mai toccare**: `~/.headroom/proxy_savings.json` (scritture solo dal proxy),
   quota totale ($60) e reset (2026-10-09) senza richiesta esplicita, unit systemd altrui,
   `WantedBy=graphical-session.target` (vietato: boot richiede `default.target`).
2. **Pricing**: unica fonte documentata `~/.headroom/config/models.json` (+ mirror env
   `HEADROOM_MODEL_LIMITS` in `~/.bashrc`, che ombreggia il file per le sessioni wrap).
   Backup timestampato OBBLIGATORIO prima di ogni modifica + rollback documentato.
   Prezzi ufficiali: Meta contributor 0.10/0.20/0.002; DeepSeek flash **peak** 0.30/1.20/0.006
   (fonte: https://opencode.ai/docs/go).
3. **Quota reale OpenCode**: nessuna API pubblica (workspace = login OpenAuth, SDK = solo
   server locale). Fonte = `exports/quota-models.json` (snapshot manuale). Non sondare
   opencode.ai con chiavi memorizzate. Hook futuro già pronto: `--quota-url` + `$OPENCODE_API_TOKEN`.
4. **Verifica dopo ogni cambio codice**: `python3 -m py_compile`, restart unit,
   `curl -fsS :8790/health` + assert `/api/stats` (5 scenari, `daily`, `monthly`,
   `quota.used`, `quota_models[3]`). Prova degradata su porta 8792 con cleanup verificato.
5. **Commit**: messaggi convenzionali (`refactor|feat|docs(scope): ...`); mai committare
   `.venv/`, `__pycache__/`, `*.log`, `.bak`, `/tmp/*`. `.omo/` (piani/evidence) è tracciato.

## Dove sta cosa

- CLI/porte/sorgenti: `headroom_dashboard.py` fondo `main()` (~riga 460+)
- Costi: `real_cost_usd`, `MODEL_PRICES`, `weighted_rate_usd_per_token`, `measured_output_ratio`
- Serie: `merge_daily`, `build_daily` (cap 14), `build_monthly` (`calendar.monthrange`, UTC→locale)
- Quota: `load_quota()` — precedenza url → models/used → fallback costo lifetime
- Template: `dashboard.html` —card `Per-modello mensile (OpenCode)` legata a `quota_models`
- Stato boot: `systemctl --user ... headroom-default.service headroom-metrics` + `loginctl ... Linger`
