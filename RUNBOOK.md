# RUNBOOK — headroom autostart + forecast dashboard

Units (real names, resolved from T3/T7 evidence):
- Proxy: `headroom-default.service` on :8787
- Dashboard: `headroom-metrics.service` (short: `headroom-metrics`) on :8790

## 1) Servizi e porte

| Servizio | Unit | Porta | Sorgente |
|---|---|---|---|
| Proxy headroom | `headroom-default.service` | 8787 | `headroom install` (user unit) |
| Dashboard metrics | `headroom-metrics.service` | 8790 | repo `headroom_dashboard.py` |

Boot: entrambe user units (`~/.config/systemd/user/`), abilitate per l'avvio
automatico. `loginctl show-user $USER` riporta `Linger=yes`, quindi partono al boot
senza login grafico.

## 2) Comandi

Status:

```bash
systemctl --user status headroom-default.service headroom-metrics
systemctl --user is-enabled headroom-default.service headroom-metrics
systemctl --user is-active headroom-default.service headroom-metrics
```

Start / stop / restart:

```bash
systemctl --user start headroom-default.service headroom-metrics
systemctl --user stop headroom-default.service headroom-metrics
systemctl --user restart headroom-default.service headroom-metrics
```

Logs (follow con `-f`, altrimenti one-shot con `-n 100`):

```bash
journalctl --user -u headroom-default.service -n 100 -f
journalctl --user -u headroom-metrics -n 100 -f
```

Health:

```bash
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8790/health
curl -fsS http://127.0.0.1:8790/api/stats
```

## 3) Rollback pricing

Il pricing vive in `~/.headroom/config/models.json`, con mirror env in
`~/.bashrc` (riga 161, `HEADROOM_MODEL_LIMITS`). Backup timestampato creato in T2:
`models.json.2026-09-15-1437.bak`. Rollback:

```bash
BACKUP=$(ls -t ~/.headroom/config/models.json.*.bak | head -1)
cp "$BACKUP" ~/.headroom/config/models.json
```

Poi riallineare il mirror in `~/.bashrc` (riga 161) allo stesso contenuto e
riavviare la proxy: `systemctl --user restart headroom-default.service`.

## 4) Last resort

Se le unit restano rotte dopo restart e rollback:

```bash
headroom install remove
```

Poi reinstallare da capo con `headroom install` e riapplicare le unit.

## 5) Boot note

Unit in user scope + `loginctl enable-linger $USER` (stato attuale: `Linger=yes`).
Verifica dopo un reboot con i comandi di status e gli health curl qui sopra.
