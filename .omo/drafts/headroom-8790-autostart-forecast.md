---
slug: headroom-8790-autostart-forecast
status: review-in-flight
intent: clear
review_required: true
pending-action: write .omo/plans/headroom-8790-autostart-forecast.md
approach: Dashboard su 8790 con sorgente live /stats-history; proxy Headroom reso persistente via `headroom install apply --preset persistent-service`; dashboard resa persistent-service via user systemd unit + linger; forecast giorno/mese da series.daily/monthly con costi reali per-modello (Meta contributor + DeepSeek ufficiali); pricing Headroom corretto via models.json/HEADROOM_MODEL_LIMITS per deepseek, verifica muse-spark.
---

# Draft: headroom-8790-autostart-forecast

## Components (topology ledger)
<!-- id | outcome (one line) | status | evidence path -->
- C1 | Dashboard servita su 127.0.0.1:8790 senza clash con proxy :8787 | active | headroom_dashboard.py:192-216 (CLI --port default 8787); ss: 8787 LISTEN pid 29637, 8790 free
- C2 | Proxy Headroom auto-avvio al boot (persistent-service) | active | docs persistent-installs: `headroom install apply --preset persistent-service`; oggi proxy = child di `headroom wrap` (PPID 27417), nessuna unit/cron/autostart
- C3 | Dashboard metrics auto-avvio al boot (user systemd unit) | active | ~/.config/systemd/user/ esiste (solo conky-resync), systemd user manager running, linger off
- C4 | Forecast giorno/mese da API Headroom (/stats-history) con costi reali per-modello | active | /stats-history: lifetime + series.daily/monthly + by_model; merge_daily usa total_input_tokens_delta
- C5 | Correzione pricing Headroom (deepseek errato, verifica muse-spark) | active | ~/.headroom/config/models.json:1-14 (muse-spark 0.10/0.20/0.002 = ufficiale); vendored deepseek-v4-flash 0.14/0.28/0.0028 vs ufficiale peak 0.30/1.20/0.006

## Open assumptions (announced defaults)
<!-- assumption | adopted default | rationale | reversible? -->
- Meccanismo auto-avvio dashboard | user systemd unit `headroom-metrics.service` + `loginctl enable-linger` | systemd user manager attivo, user scope, nessun root richiesto | sì (unit rimovibile)
- Proxy persistente | `headroom install apply --preset persistent-service` (unit generata da Headroom, non scritta a mano) | via ufficiale documentata; `wrap` riusa proxy già attivo via POST /admin/runtime-env | sì (`headroom install remove`)
- Quota/reset dashboard | invariati: $60, reset 2026-10-09 (CFG esistente) | già configurati, utente non chiede cambio | sì (flag CLI)
- Prezzi muse-spark-1.3-contributor | $0.10 in / $0.20 out / $0.002 cached per 1M (già in CFG e models.json) | combaciano con ufficiale Meta contributor tier + OpenRouter | n/a (conferma, non cambio)
- Porta proxy Headroom | resta 8787, si sposta solo la dashboard su 8790 | utente: "spostiamo il servizio sulla 8790" = il servizio dashboard | sì

## Findings (cited)
- D1 docs pricing: Headroom usa LiteLLM model_cost DB (`headroom/pricing/litellm_pricing.py:1-7`); override via `HEADROOM_MODEL_LIMITS` (JSON/env/file) o `models.json` in `$HEADROOM_CONFIG_DIR` (`~/.headroom/config/models.json`) / workspace (`~/.headroom/models.json`); chiavi `{"input","output","cached_input"}` USD/1M; OpenAI-provider accetta anche lista `[input,output]`.
- D2 docs API (feedback-edit): `GET /stats` (+`?cached=1`), `/stats-history` (`?format=csv&series=daily`, by_model top-level), `/stats-lifetime` (loopback, `savings_tracker.lifetime_response()`), `/metrics` Prometheus, `/dashboard`, `/health` (+`/livez`,`/readyz`).
- D3 live :8787 verificato: /stats-history ha `lifetime{requests 7039, total_input_tokens 1217761500, cache_read_tokens 1071262054}` + `series.daily[].timestamp/total_input_tokens_delta/by_model(muse-spark-1.3-contributor)` + monthly; storage `~/.headroom/proxy_savings.json` schema_version 5.
- D4 ufficiali DeepSeek (`api-docs.deepseek.com/quick_start/pricing/`): deepseek-flash (V4.1-Flash) cacheHIT 0.003/0.006, cacheMISS 0.15/0.30, output 0.60/1.20 off-peak/peak USD/1M; peak lun-ven 01-04 e 06-10 UTC.
- D5 ufficiali Meta (`ai.developer.meta.com/docs/pricing-rate-limits` + Vercel mirror): contributor in 0.10 / cached 0.002 / out 0.20; standard 1.25/0.15/4.25 USD/1M. OpenRouter conferma `meta/muse-spark-1.3-contributor`.
- D6 Headroom vendored stale: `_DEEPSEEK_V4_PRICING deepseek-v4-flash in 0.14/out 0.28` (`litellm_pricing.py:345-387`) e `_DEEPSEEK_FALLBACK_PRICING cached 0.0028` (`providers/anthropic.py:226-229`) ≠ ufficiali D4 → causa costi errati dashboard Headroom per deepseek.
- D7 dashboard attuale: `real_cost_usd` usa PRICE singolo + OUTPUT_RATIO 0.0041 stimato (headroom_dashboard.py:64-68); non usa costi per-modello né output reali da /stats (`tokens.output`, `cost.total_cost_usd` disponibili).

## Decisions (with rationale)
- DEC1: sorgente primaria dashboard = `http://127.0.0.1:8787/stats-history` (serie + lifetime in una chiamata), fallback file `exports/*.json`. Perché: /stats-lifetime non ha serie giornaliere; /stats non ha history.
- DEC2: forecast mensile = proiezione run-rate da daily (media ultimi N giorni × giorni mese) + cumulato mese corrente da series.monthly; costi per-modello da by_model × prezzi ufficiali D4/D5. Perché: richiesto "per giorno e per mese" con "costi reali dei modelli".
- DEC3: correzione pricing Headroom via `~/.headroom/config/models.json` (precedenza config-dir) o `HEADROOM_MODEL_LIMITS`, con backup pre-change e verifica via /stats `cost.*` prima/dopo. Perché: via documentata, reversibile, niente patch al codice Headroom.

## Scope IN
- Port 8790 per dashboard (default CLI + docs/runbook).
- `headroom install apply --preset persistent-service` + verifica proxy attivo dopo reboot-logic (daemon-reload/enable, health check).
- Unit `~/.config/systemd/user/headroom-metrics.service` (ExecStart uv run dashboard --port 8790 --sources stats-history) + enable + linger.
- Dashboard: sezione giornaliera (ultimi 7-14g da series.daily, token/costi per-modello) + sezione mensile (cumulato monthly + stima fine mese) con prezzi reali per-modello; footer prezzi aggiornato.
- models.json: override deepseek (peak schedule-aware o valore singolo — vedi Q1), conferma muse-spark; backup `.bak` + rollback.
- Runbook breve: comandi start/stop/logs per entrambi i servizi.

## Scope OUT (Must NOT have)
- Nessuna patch al codice sorgente di Headroom (solo config/env).
- Nessun cambio quota/reset ($60, 2026-10-09) salvo richiesta.
- Nessun deploy Docker / scope system-wide (solo user scope).
- Nessuna migrazione dati storici; nessuna modifica a `proxy_savings.json` a mano.

## Open questions
- Q1 deepseek: RISPOSTO peak (conservativo, singolo valore; sovrastima off-peak ~2x dichiarata).
- Q2 test: RISPOSTO smoke-check live (curl + is-enabled + emit, nessun framework).

## Approval gate
status: review-in-flight (user approved plan + opted for high-accuracy review; round rr-20260915-03 active)

## Review round rr-20260915-03
<!-- ulw-plan-review-round-state-contract -->
```json
{
  "transition": "replace",
  "phase": "review_round_initialized",
  "atomic": true,
  "review_required": true,
  "plan_path": ".omo/plans/headroom-8790-autostart-forecast.md",
  "plan_sha256": "f3593086a070267009655b6d28d72d6cf1898bc375362ea2a0f1278bc62f9800",
  "review_round_id": "rr-20260915-03",
  "round_status": "active",
  "pending-action": "review .omo/plans/headroom-8790-autostart-forecast.md",
  "review": {
    "momus": { "status": "in_flight", "workspace_root": "/home/crovax/workspace/headroom-metrics", "runtime_home": null, "target": ".omo/plans/headroom-8790-autostart-forecast.md", "round_id": "rr-20260915-03", "plan_sha256": "84065ec35b71d66262bc60f9d0453ba3e0c7ab33e96d1efe96fa37b10bd1086f", "launch_id": "launch-momus-03", "session": null, "result": null },
    "independent": { "status": "in_flight", "workspace_root": "/home/crovax/workspace/headroom-metrics", "runtime_home": null, "target": ".omo/plans/headroom-8790-autostart-forecast.md", "round_id": "rr-20260915-03", "plan_sha256": "84065ec35b71d66262bc60f9d0453ba3e0c7ab33e96d1efe96fa37b10bd1086f", "launch_id": "launch-oracle-03", "session": null, "result": null }
  }
}
```

## Review round rr-20260915-04 (momus completion, plan unchanged)
- Plan sha256 still f3593086a070267009655b6d28d72d6cf1898bc375362ea2a0f1278bc62f9800 (no edits since oracle APPROVED rr-20260915-03).
- Oracle approval carried from rr-20260915-03 (session ses_f5af92806ffecR3f1hRlEieUOs, same digest).
- Momus rr-20260915-03 lane ack-only without deliverable (plus stale continuation INCONCLUSIVE on old digest) -> fresh momus lane launch-momus-04 on same digest.

## Review receipts (final)
- Momus rr-20260915-04 launch-momus-04: APPROVED (same digest, live validation match).
- Oracle rr-20260915-03 launch-oracle-03 session ses_f5af92806ffecR3f1hRlEieUOs: APPROVED (same digest, plan unmutated since).
- Live plan validation immediately before handoff: digest match confirmed above. Both approvals valid. Status: plan-complete.
