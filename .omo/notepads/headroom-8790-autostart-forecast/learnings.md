# Learnings — headroom-8790-autostart-forecast

Conventions, patterns, and successful approaches discovered during work on this plan.

_Auto-scaffolded by /start-work. Append new entries below - never overwrite._

---

## 2026-09-15 T2-T4 verified by orchestrator
- T2 BACKUP-OK: models.json.2026-09-15-1437.bak identical; HEADROOM_MODEL_LIMITS inline mirrors file (muse-spark 0.10/0.20/0.002).
- T3 proxy unit = headroom-default.service (user scope), Status running Healthy yes, SINGLE-LISTENER on 8787. Wrap-child 29637 gone.
- T4 diff minimal (2 defaults + guard comment); py_compile ok; emit 7396B no placeholder. Port 8790 still free (unit in T7).

## 2026-09-15 T5+T7 verified by orchestrator
- T5: triple deepseek under `openai` key in models.json (additive diff) + .bashrc:161 env updated (env shadows file for wrap sessions; systemd unit has empty Environment so service reads models.json file). muse-spark intact.
- T7: headroom-metrics.service enabled+active, /health ok, Linger=yes, WantedBy=default.target, no graphical-session.

## 2026-09-15 T8 verified by orchestrator
- Log has STOP_RC=0, both curl RC=7 "Failed to connect" (closed-port proof), START_RC=0, READY, PAYLOAD-OK, no NOT-READY. Both units active now.

## 2026-09-15 closure
- F1-F4 all APPROVE; plan 13/13; boulder completed. Note: dir is not a git repo, commits recorded in ledger only.
