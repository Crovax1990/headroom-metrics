# headroom-8790-autostart-forecast - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** La dashboard consumi su porta 8790 con previsioni giornaliere e mensili ai prezzi reali dei modelli, avviata automaticamente al boot insieme al proxy Headroom (anch'esso reso persistente), e i costi DeepSeek corretti nella configurazione Headroom.

**Why this approach:** Uso solo vie ufficiali documentate (`headroom install` per il proxy, unit systemd user per la dashboard) e la sorgente dati migliore (`/stats-history`: serie storiche + totali in una chiamata). I prezzi muse-spark erano già corretti e restano; solo DeepSeek viene corretto alle tariffe peak ufficiali, scelta conservativa confermata da te.

**What it will NOT do:** Non tocca il codice di Headroom, non cambia quota ($60) né reset (9 ott 2026), non usa Docker né permessi root, non migra dati storici.

**Effort:** Medium
**Risk:** Medium - il proxy live va migrato da figlio-di-wrap a servizio senza downtime né doppioni sulla 8787
**Decisions to sanity-check:** DeepSeek a tariffe peak (sovrastima ~2x in off-peak, dichiarato nel footer); verifica pricing via ricalcolo su /stats-history perché `/stats cost` vale 0.0; unit dashboard con `WantedBy=default.target` mai graphical-session.

Your next move: avvia con `/start-work headroom-8790-autostart-forecast`, oppure chiedi prima la high-accuracy review. Full execution detail follows below.

---

> TL;DR (machine): Medium effort, Medium risk; dashboard 8790 + boot persistence + per-model daily/monthly forecast + deepseek peak pricing fix.

## Scope
### Must have
- Dashboard metrics su `127.0.0.1:8790` (default cambiato nel codice), proxy Headroom fermo su `127.0.0.1:8787`, entrambi raggiungibili in simultanea.
- Proxy Headroom persistente al boot via via ufficiale `headroom install apply --preset persistent-service` con porta pinnata a 8787 e migrazione ordinata dal wrap-child live (PID 29637).
- Dashboard persistente al boot via user systemd unit `headroom-metrics.service` (directive boot-safe, non graphical-session) + `loginctl enable-linger`.
- Forecast giorno/mese nella dashboard da `GET /stats-history` live: sezione giornaliera (finestra disponibile, cap 14g) e sezione mensile (cumulato mese corrente + stima fine mese run-rate), costi per-modello a prezzi reali (Meta contributor peak-singolo per muse-spark; DeepSeek flash PEAK: miss 0.30 / hit 0.006 / out 1.20 USD per 1M).
- Correzione pricing Headroom per `deepseek-v4.1-flash` in `~/.headroom/config/models.json` (backup timestampato, verifica muse-spark invariato).
- Runbook con nomi unit reali (da `headroom install status`), comandi start/stop/logs/health per entrambi i servizi.
### Must NOT have (guardrails, anti-slop, scope boundaries)
- NO patch al codice sorgente di Headroom; solo config/env ufficialmente documentati.
- NO cambio valore quota ($60) né data reset (2026-10-09): la proiezione della data di esaurimento resta visibile, il valore quota è congelato.
- NO scope system-wide/root e NO deploy Docker: solo user scope.
- NO `WantedBy=graphical-session.target` nella unit (modello sbagliato per il boot, copiato da conky-resync).
- NO modifica manuale di `~/.headroom/proxy_savings.json`.
- NO nuove dipendenze Python: il progetto resta stdlib-only (`uv run --no-sync` resta valido).
- NO verifica via `/stats cost.total_cost_usd` (vale 0.0 oggi, pass vacuo): verifica pricing via ricalcolo su `/stats-history` deltas.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: none (no test framework; stdlib-only project) + agent-executed live smoke-checks (user-confirmed): `curl -fsS` su `/health` e `/api/stats` di entrambi i servizi, `systemctl --user is-enabled`, snapshot `--emit`, check JSON `models.json`.
- Evidence: .omo/evidence/task-<N>-headroom-8790-autostart-forecast.log (command output salvati lì dal worker, un file per todo).

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 1 (read-only, parallela): T1 pre-flight evidence.
- Wave 2 (sequenziale sul proxy live + file config): T2 backup, T3 persistent-service proxy, T4 default porta dashboard. T2 prima di T5; T3 prima di T7.
- Wave 3 (dashboard + pricing, dopo T2): T5 pricing models.json, T6 forecast per-modello (dopo T4 per non confliggere sullo stesso file: T4 prima di T6).
- Wave 4 (boot + runbook, dopo T3 e T6): T7 unit dashboard + linger, T8 ciclo stop/start + double-health, T9 runbook + evidence bundle.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| T1 pre-flight | — | T2–T9 (baseline) | — (è la wave 1) |
| T2 backup models.json | T1 | T5 | T3, T4 |
| T3 persistent proxy | T1 | T7, T8 | T2, T4 |
| T4 porta 8790 default | T1 | T6, T7 | T2, T3 |
| T5 pricing deepseek | T2 | T6 (costi footer) | — (dopo T2) |
| T6 forecast giorno/mese | T4, T5 | T8 | — |
| T7 unit dashboard | T3, T4 | T8 | — |
| T8 ciclo + double health | T6, T7 | T9 | — |
| T9 runbook + bundle | T8 | — | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Pre-flight evidence: proxy live, porte, unit, env pricing, baseline storico
  What to do / Must NOT do: Raccogli SOLO letture: `curl -fsS http://127.0.0.1:8787/health`, `ss -ltnp | grep -E '8787|8790'`, `ps -o pid,ppid -p 29637`, `headroom install status`, `echo $HEADROOM_MODEL_LIMITS`, `cat ~/.headroom/config/models.json`, `curl -fsS http://127.0.0.1:8787/stats-history` (salva baseline: lifetime totals + len series.daily/monthly), `systemctl --user list-units --all | grep -iE 'headroom|metrics'`, `loginctl show-user $USER | grep -i linger`, `which uv`. NON modificare nulla.
  Parallelization: Wave 1 | Blocked by: — | Blocks: 2, 3, 4, 5, 6, 7, 8, 9
  References (executor has NO interview context - be exhaustive): /home/crovax/workspace/headroom-metrics/headroom_dashboard.py:192-216 (CLI), https://docs.headroomlabs.ai/docs/metrics (endpoint /stats-history), https://docs.headroomlabs.ai/docs/persistent-installs (`headroom install status`)
  Acceptance criteria (agent-executable): file .omo/evidence/task-1-headroom-8790-autostart-forecast.log esiste e contiene: proxy health ok, 8787 LISTEN / 8790 free, PPID di 29637, valore HEADROOM_MODEL_LIMITS, contenuto models.json, lifetime totals + daily/monthly len.
  QA scenarios (name the exact tool + invocation): happy — tutti i comandi escono 0, Evidence .omo/evidence/task-1-headroom-8790-autostart-forecast.log; failure — se il proxy non risponde su :8787, STOP e registra nel log (non procedere ai todo 3-8), Evidence stesso file.
  Commit: N
- [x] 2. Backup timestampato di models.json + congelamento env pricing
  What to do / Must NOT do: `cp ~/.headroom/config/models.json ~/.headroom/config/models.json.$(date +%F-%H%M).bak` e registra il valore esatto di `$HEADROOM_MODEL_LIMITS` in .omo/evidence/task-2-headroom-8790-autostart-forecast.log. NON modificare i contenuti, solo copiare.
  Parallelization: Wave 2 | Blocked by: 1 | Blocks: 5
  References (executor has NO interview context - be exhaustive): /home/crovax/.headroom/config/models.json (chiavi openai.pricing + context_limits), https://docs.headroomlabs.ai/docs/filesystem-contract (precedenza config-dir models.json vs HEADROOM_MODEL_LIMITS)
  Acceptance criteria (agent-executable): `BACKUP=$(ls -t ~/.headroom/config/models.json.*.bak | head -1); test -n "$BACKUP" && diff ~/.headroom/config/models.json "$BACKUP" && echo BACKUP-OK` esce 0.
  QA scenarios (name the exact tool + invocation): happy — backup creato e identico, Evidence .omo/evidence/task-2-headroom-8790-autostart-forecast.log; failure — se models.json manca, registra e salta al todo 5 con nota (usa solo env), Evidence stesso file.
  Commit: N
- [x] 3. Proxy Headroom persistente al boot con migrazione dal wrap-child live
  What to do / Must NOT do: 1) `curl -fsS http://127.0.0.1:8787/health` (baseline). 2) Risolvi il PID live SENZA fidarti di 29637: `PROXY_PID=$(ss -ltnp 2>/dev/null | grep ':8787' | grep -oP 'pid=\K[0-9]+' | head -1); echo "PROXY_PID=$PROXY_PID"; tr '\0' ' ' < /proc/$PROXY_PID/cmdline | grep -q 'headroom.cli proxy' || { echo "PID-IDENTITY-FAIL"; exit 1; }` (se 29637 è staled, usa comunque $PROXY_PID scoperto). 3) `headroom install apply --preset persistent-service -p 8787` pinnando la porta esplicita (aggiungi `--env KEY=VALUE` solo per variabili che il proxy live usa e il supervisore non eredita: confronta `tr '\0' '\n' < /proc/$PROXY_PID/environ | grep -iE 'headroom|anthropic|openai|deepseek'`). 4) Prova riuso-o-kill: se dopo l'apply `ss -ltnp | grep 8787` mostra DUE listener o EADDRINUSE nei log, termina SOLO dopo identity-check: `tr '\0' ' ' < /proc/$PROXY_PID/cmdline | grep -q 'headroom.cli proxy' && kill $PROXY_PID` (solo dopo che la unit è active), poi riverifica. 5) `headroom install status` e annota il nome unit generata con `headroom install status | tee -a .omo/evidence/task-3-headroom-8790-autostart-forecast.log; echo "PROXY_UNIT=$(systemctl --user list-units --all --no-legend | grep -i headroom | awk '{print $1}' | head -1)" | tee -a .omo/evidence/task-3-headroom-8790-autostart-forecast.log`. Must NOT: non cambiare la porta del proxy, non killare mai un PID senza identity-check cmdline, non toccare `headroom wrap` oltre al kill del child migrato, non usare scope system-wide.
  Parallelization: Wave 2 | Blocked by: 1 | Blocks: 7, 8
  References (executor has NO interview context - be exhaustive): https://docs.headroomlabs.ai/docs/persistent-installs (preset persistent-service, lifecycle start/stop/restart/remove, manifest ~/.headroom/deploy/*/manifest.json (profilo reale dal log T3)), https://github.com/headroomlabs-ai/headroom/blob/main/headroom/install/supervisors.py (template unit user scope ~/.config/systemd/user/, Restart=on-failure, WantedBy=default.target)
  Acceptance criteria (agent-executable): `headroom install status` riporta il profilo healthy/active E `curl -fsS http://127.0.0.1:8787/health` esce 0 E `test $(ss -ltnp 2>/dev/null | grep -c ':8787') -eq 1 && echo SINGLE-LISTENER` esce 0.
  QA scenarios (name the exact tool + invocation): happy — unit active + health ok + listener unico, Evidence .omo/evidence/task-3-headroom-8790-autostart-forecast.log; failure — se EADDRINUSE/doppio proxy: kill del $PROXY_PID con identity-check (come sopra), `PROXY_UNIT=$(grep -oP "PROXY_UNIT=\K\S+" .omo/evidence/task-3-headroom-8790-autostart-forecast.log | head -1); systemctl --user restart $PROXY_UNIT`, riverifica health, Evidence stesso file (se ancora rotto: rollback `headroom install remove` + nota).
  Commit: N
- [x] 4. Default porta dashboard 8787→8790 + guard HEADROOM_PORT + sorgente live di default
  What to do / Must NOT do: In /home/crovax/workspace/headroom-metrics/headroom_dashboard.py cambia SOLO il default `--port` 8787→8790 (riga ~197) e il default `--sources` in `["http://127.0.0.1:8787/stats-history", "./exports/*.json"]` (URL per primo, file come fallback); aggiungi commento che `HEADROOM_PORT` muove SOLO il proxy e la porta dashboard è solo flag `--port`. NON toccare logica scenari/costi in questo todo. Poi `python3 -m py_compile headroom_dashboard.py` e `uv run --no-sync headroom_dashboard.py --port 8791 --emit /tmp/emit-check.html` come prova di render (porta 8791 per non occupare 8790).
  Parallelization: Wave 2 | Blocked by: 1 | Blocks: 6, 7
  References (executor has NO interview context - be exhaustive): /home/crovax/workspace/headroom-metrics/headroom_dashboard.py:160-216 (render + Handler + main/CLI)
  Acceptance criteria (agent-executable): `grep -n 'default=8790' headroom_dashboard.py` match E `grep -n 'stats-history' headroom_dashboard.py` match E `/tmp/emit-check.html` esiste con `@@PAYLOAD@@` sostituito (no placeholder residuo).
  QA scenarios (name the exact tool + invocation): happy — py_compile ok + emit ok, Evidence .omo/evidence/task-4-headroom-8790-autostart-forecast.log; failure — se l'emit fallisce: `git diff -- headroom_dashboard.py` nel log poi `git restore -- headroom_dashboard.py` e registra, Evidence stesso file.
  Commit: Y | refactor(metrics): default port 8790 + live stats-history source
- [x] 5. Correzione pricing DeepSeek (peak) in models.json, verifica muse-spark
  What to do / Must NOT do: Conferma la chiave provider di `deepseek-v4.1-flash` nelle serie live (`by_model` sotto quale provider in /stats-history) e nel codice Headroom (`headroom/providers/*.py`, via `grep -rn deepseek-v4 ~/.local/share/uv/tools/headroom-ai/` o docs HEADROOM_MODEL_LIMITS); scrivi in `~/.headroom/config/models.json` sotto il provider corretto `{"pricing": {"deepseek-v4.1-flash": {"input": 0.30, "output": 1.20, "cached_input": 0.006}}}` (tariffe PEAK ufficiali, singolo valore — sovrastima documentata in off-peak ~2x); lascia invariato il blocco muse-spark (0.10/0.20/0.002 = ufficiale). Se `$HEADROOM_MODEL_LIMITS` ombreggia il file (precedenza), applica lì invece e documenta. Verifica NON via `/stats cost.*` (=0.0) ma ricalcolando `real_cost_usd` sui `total_input_tokens_delta` di /stats-history prima/dopo. Must NOT: nessun altro modello, nessun valore blended senza documentarlo.
  Parallelization: Wave 3 | Blocked by: 2 | Blocks: 6
  References (executor has NO interview context - be exhaustive): /home/crovax/.headroom/config/models.json, https://docs.headroomlabs.ai/docs/configuration (HEADROOM_MODEL_LIMITS formato), https://api-docs.deepseek.com/quick_start/pricing/ (peak: miss 0.30/hit 0.006/out 1.20), https://ai.developer.meta.com/docs/pricing-rate-limits (contributor 0.10/0.002/0.20), /home/crovax/workspace/headroom-metrics/headroom_dashboard.py:56-68 (real_cost_usd)
  Acceptance criteria (agent-executable): `python3 -c "import json,os; d=json.load(open(os.path.expanduser('~/.headroom/config/models.json'))); print(d)"` mostra `deepseek-v4.1-flash` con `{"input": 0.30, "output": 1.20, "cached_input": 0.006}` sotto la chiave provider confermata E `curl -fsS http://127.0.0.1:8787/stats-history | python3 -c "import json,sys; h=json.load(sys.stdin); m=h['series']['monthly'][-1]; print('monthly_input_delta:', m['total_input_tokens_delta']); assert m['total_input_tokens_delta'] > 0"` esce 0 (i delta esistono per il ricalcolo).
  QA scenarios (name the exact tool + invocation): happy — JSON valido + delta mensili presenti, Evidence .omo/evidence/task-5-headroom-8790-autostart-forecast.log; failure — se il provider-key è ambiguo o il JSON invalido: `BACKUP=$(ls -t ~/.headroom/config/models.json.*.bak | head -1); cp "$BACKUP" ~/.headroom/config/models.json` e registra, Evidence stesso file.
  Commit: N (file fuori repo; backup+rollback documentati nel log)
- [x] 6. Forecast giorno/mese per-modello a costi reali nella dashboard
  What to do / Must NOT do: Estendi headroom_dashboard.py + dashboard.html: (a) tabella prezzi per-modello `{"muse-spark-1.3-contributor": {in 0.10, hit 0.002, out 0.20}, "deepseek-v4.1-flash": {in 0.30, hit 0.006, out 1.20}}` USD/1M (peak, documentato nel footer); (b) sezione giornaliera: ultimi min(disponibili,14) giorni da `series.daily` con token/costi totali e split per-modello (costo per-modello = input-delta × prezzo miss, cache non scomposta nel daily → dichiara approssimazione input-only nel footer); output misurati da `/stats tokens.output` quando disponibili al posto di OUTPUT_RATIO;   (c) sezione mensile: cumulato `series.monthly[-1]` + stima fine mese con formula esplicita `stima = cumulato + media_daily × giorni_rimanenti_mese` (media_daily = media `total_input_tokens_delta` su min(disponibili,14) giorni; giorni_rimanenti_mese da `calendar.monthrange(anno, mese)`; timestamp serie in UTC `Z`, dashboard mostra ora locale con suffisso); il limite input-only vale anche qui e va ridichiarato nel footer della sezione mensile; (d) scenari S1–S5 esistenti invariati ma con rate per-modello pesato; footer prezzi aggiornato con peak/off-peak deepseek + nota sovrastima off-peak. Must NOT: non cambiare quota/reset, non rimuovere scenari esistenti, non aggiungere dipendenze.
  Parallelization: Wave 3 | Blocked by: 4, 5 | Blocks: 8
  References (executor has NO interview context - be exhaustive): /home/crovax/workspace/headroom-metrics/headroom_dashboard.py:56-137 (real_cost_usd, merge_daily, analyze), /home/crovax/workspace/headroom-metrics/dashboard.html:31-75 (cards, tabella, footer), live `http://127.0.0.1:8787/stats-history` (shape: lifetime, series.daily[].{timestamp,total_input_tokens_delta,by_model}, series.monthly), live `http://127.0.0.1:8787/stats` (tokens.output, cost)
  Acceptance criteria (agent-executable): con export di test o live, `curl -fsS http://127.0.0.1:8790/api/stats | python3 -c "import json,sys; p=json.load(sys.stdin); assert len(p['scenarios'])==5; assert 'daily' in p and 'monthly' in p; print('ok')"` stampa ok E `curl -fsS http://127.0.0.1:8790/ | grep -q -iE 'giorn|month|mens' && echo SECTIONS-OK` esce 0.
  QA scenarios (name the exact tool + invocation): happy — 5 scenari + daily/monthly presenti, Evidence .omo/evidence/task-6-headroom-8790-autostart-forecast.log; failure — condizione degradata: `mkdir -p /tmp/empty-exports && uv run --no-sync --project /home/crovax/workspace/headroom-metrics ./headroom_dashboard.py --port 8792 --sources '/tmp/empty-exports/*.json' & PROBE_PID=$!; trap "kill $PROBE_PID 2>/dev/null" EXIT; sleep 3; curl -fsS http://127.0.0.1:8792/api/stats | grep -q '"error"' && echo DEGRADED-OK; kill $PROBE_PID; trap - EXIT; sleep 1; ss -ltn 2>/dev/null | grep -q ':8792' && { echo PROBE-STILL-LISTENING; exit 1; } || echo PROBE-CLEANED`; se manca `"error"` o crasha: bug, registra, Evidence stesso file.
  Commit: Y | feat(metrics): daily/monthly per-model forecast at real prices
- [x] 7. Unit systemd dashboard + linger + enable
  What to do / Must NOT do: Scrivi `~/.config/systemd/user/headroom-metrics.service` con: `After=network-online.target`, `WorkingDirectory=/home/crovax/workspace/headroom-metrics`, `ExecStart=/home/crovax/.local/bin/uv run --no-sync --project /home/crovax/workspace/headroom-metrics ./headroom_dashboard.py --host 127.0.0.1 --port 8790 --sources http://127.0.0.1:8787/stats-history --sources ./exports/*.json` (verifica prima il path reale di `uv` dal T1; fallback `/usr/bin/python3 ...` se uv inaffidabile), `Restart=on-failure`, `RestartSec=5`, `WantedBy=default.target` (MAI graphical-session.target). Poi `systemctl --user daemon-reload`, `enable --now`, `loginctl enable-linger $USER`. Must NOT: scope system, altre porte, variabili proxy.
  Parallelization: Wave 4 | Blocked by: 3, 4 | Blocks: 8
  References (executor has NO interview context - be exhaustive): /home/crovax/.config/systemd/user/conky-resync.service (anti-modello: graphical-session.target), https://github.com/headroomlabs-ai/headroom/blob/main/headroom/install/supervisors.py (template unit user scope)
  Acceptance criteria (agent-executable): `systemctl --user is-enabled headroom-metrics` → enabled E `systemctl --user is-active headroom-metrics` → active E `curl -fsS http://127.0.0.1:8790/health` esce 0.
  QA scenarios (name the exact tool + invocation): happy — enabled+active+health ok, Evidence .omo/evidence/task-7-headroom-8790-autostart-forecast.log; failure — se uv path errato: usa fallback python3 e riabilita, Evidence stesso file (`journalctl --user -u headroom-metrics -n 50` nel log).
  Commit: N (unit fuori repo; commit solo se si aggiunge copia in repo docs)
- [x] 8. Ciclo stop/start simulante il boot + double-health 8787/8790
  What to do / Must NOT do: `systemctl --user stop PROXY_UNIT headroom-metrics` (PROXY_UNIT dal log T3; mai placeholder letterali), verifica porte chiuse (`curl -fsS --max-time 3 http://127.0.0.1:8787/health` deve FALLIRE e idem 8790), poi `systemctl --user start PROXY_UNIT headroom-metrics` (proxy prima), readiness fail-closed con timeout esplicito `READY=0; for i in $(seq 1 30); do curl -fsS --max-time 2 http://127.0.0.1:8787/health >/dev/null && curl -fsS --max-time 2 http://127.0.0.1:8790/health >/dev/null && READY=1 && break; sleep 2; done; test $READY -eq 1 || { echo NOT-READY; exit 1; }; echo READY` (il token READY deve comparire nel log, altrimenti exit 1). Poi `curl -fsS http://127.0.0.1:8790/api/stats | python3 -c "import json,sys; p=json.load(sys.stdin); assert len(p['scenarios'])==5 and 'daily' in p and 'monthly' in p; print('PAYLOAD-OK')"`. Nota headless: se `systemctl --user`/`journalctl --user` falliscono per DBUS, riesporta `XDG_RUNTIME_DIR=/run/user/$(id -u)` e `tee` stderr nel log. NON riavviare la macchina.
  Parallelization: Wave 4 | Blocked by: 6, 7 | Blocks: 9
  References (executor has NO interview context - be exhaustive): nomi unit da T3 (headroom install status) e T7, /home/crovax/workspace/headroom-metrics/headroom_dashboard.py:177-186 (Handler /health /api/stats)
  Acceptance criteria (agent-executable): dopo il ciclo, entrambi gli health escono 0 e `/api/stats` contiene `scenarios` (5) + `daily` + `monthly`.
  QA scenarios (name the exact tool + invocation): happy — double health ok al primo colpo, Evidence .omo/evidence/task-8-headroom-8790-autostart-forecast.log; failure — se 8790 ok ma 8787 ko (o viceversa): identifica la unit ko (FAIL_UNIT=...) dai due health, `journalctl --user -u $FAIL_UNIT -n 100` nel log + `systemctl --user restart $FAIL_UNIT` + riverifica con loop readiness, Evidence stesso file.
  Commit: N
- [x] 9. Runbook + evidence bundle + pulizia porte temporanee
  What to do / Must NOT do: Scrivi runbook breve (nuovo file `RUNBOOK.md` nel repo o sezione in file esistente: start/stop/restart/logs/health per entrambe le unit con i NOMI REALI da T3/T7, comandi `systemctl --user`, `journalctl --user -u $PROXY_UNIT -n 100 -f` e `journalctl --user -u headroom-metrics -n 100 -f` (con PROXY_UNIT risolto dal log T3 come sopra), curl health, rollback pricing dal backup T2 (`BACKUP=$(ls -t ~/.headroom/config/models.json.*.bak | head -1); cp "$BACKUP" ~/.headroom/config/models.json`), `headroom install remove` come ultima spiaggia). Rimuovi file temporanei (`/tmp/emit-check.html`, snapshot di prova). Verifica bundle: `ls .omo/evidence/task-*-headroom-8790-autostart-forecast.log` = 9 file.
  Parallelization: Wave 4 | Blocked by: 8 | Blocks: —
  References (executor has NO interview context - be exhaustive): tutti i log T1–T8, nomi unit reali, ~/.headroom/config/models.json.*.bak (rollback)
  Acceptance criteria (agent-executable): RUNBOOK.md esiste con entrambi i nomi unit + comandi verificati (ogni comando del runbook eseguito una volta con esito nel log) E `test $(ls .omo/evidence/task-*-headroom-8790-autostart-forecast.log | wc -l) -eq 9 && echo BUNDLE-9-OK` esce 0.
  QA scenarios (name the exact tool + invocation): happy — runbook completo + bundle 9/9, Evidence .omo/evidence/task-9-headroom-8790-autostart-forecast.log; failure — comando runbook fallito: correggi il runbook e riesegui, Evidence stesso file.
  Commit: Y | docs(metrics): runbook autostart + forecast

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit — ogni todo 1-9 eseguito nell'ordine della dependency matrix, evidence 9/9 presenti, nessun Must-NOT violato (no patch codice Headroom, quota $60/reset 2026-10-09 invariati, user-scope only, stdlib-only).
- [x] F2. Code quality review — diff di headroom_dashboard.py + dashboard.html: solo default porta/sorgenti, tabella prezzi per-modello, sezioni daily/monthly; nessun placeholder @@ residuo nel render; py_compile ok; nessun segreto nei log.
- [x] F3. Real manual QA — doppio health live rieseguito: `curl -fsS http://127.0.0.1:8787/health` e `curl -fsS http://127.0.0.1:8790/health` entrambi 0; `/api/stats` con 5 scenari + daily + monthly; entrambe le unit `is-enabled`.
- [x] F4. Scope fidelity — runbook con nomi unit reali e comandi rieseguiti; backup pricing esistente + rollback documentato; porta proxy ancora 8787; nessuna migrazione dati o cambio quota.

## Commit strategy
- Commit solo file repo: T4 (refactor porta/sorgente), T6 (feat forecast), T9 (docs runbook). Messaggi convenzionali come nelle righe todo. Mai committare `~/.headroom/*`, unit systemd, `.bak`, log evidence, file /tmp.
- Ordine: T4 → T6 → T9 (3 commit separati, uno per todo).

## Success criteria
- `curl -fsS http://127.0.0.1:8787/health` e `curl -fsS http://127.0.0.1:8790/health` → entrambi `ok` dopo ciclo stop/start.
- `PROXY_UNIT=$(grep -oP "PROXY_UNIT=\K\S+" .omo/evidence/task-3-headroom-8790-autostart-forecast.log | head -1); systemctl --user is-enabled $PROXY_UNIT headroom-metrics` → `enabled` × 2; `loginctl show-user $USER` → `Linger=yes`.
- `/api/stats` (8790) → 5 scenari + `daily` (≤14 voci) + `monthly` (cumulato + stima) con costi per-modello peak.
- `models.json` → triple peak deepseek sotto provider corretto, muse-spark invariato, backup timestampato esistente.
- RUNBOOK.md con nomi unit reali, ogni comando rieseguito; bundle evidence 9/9 in `.omo/evidence/`.
