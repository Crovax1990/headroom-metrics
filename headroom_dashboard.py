#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""headroom-metrics: server + proiezione consumi Headroom / OpenCode Go.

File attesi accanto allo script: dashboard.html (template con @@PAYLOAD@@ / @@QUOTA@@).
Sorgenti dati: glob locali (exports/*.json) e/o URL API Headroom (/stats-lifetime).
Le sorgenti irraggiungibili vengono saltate con warning: il server non muore mai.
"""
from __future__ import annotations

import argparse, calendar, glob, json, os, threading, urllib.error, urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "dashboard.html"

# tariffe PEAK ufficiali; deepseek off-peak ~2x sovrastimato
MODEL_PRICES = {
    "muse-spark-1.3-contributor": {"input": 0.10, "cached_input": 0.002, "output": 0.20},
    "deepseek-v4.1-flash": {"input": 0.30, "cached_input": 0.006, "output": 1.20},
}

CFG = {
    "SOURCES": [],
    "QUOTA_USD": 60.0,
    "RESET_DATE": date(2026, 10, 9),
    "HORIZON_OVERRIDE": None,
    "MARATHON_THRESHOLD": 250e6,
    "OUTPUT_RATIO": 0.0041,
    "CALIBRATION": 1.0,
    "HTTP_TIMEOUT": 10,
    "PRICE": {"input": 0.10, "cache_read": 0.002, "output": 0.20},
    "DEFAULT_LIGHT": 110e6, "DEFAULT_MARATHON": 380e6, "DEFAULT_RECENT": 260e6,
    "QUOTA_URL": None,
    "QUOTA_MODELS": None,
    "QUOTA_MODELS_FILE": "./exports/quota-models.json",
    "QUOTA_USED": None,
}
LOCK = threading.Lock()
_TCACHE: dict = {}


# ----------------------------- sorgenti dati -----------------------------
def fetch_source(src: str):
    """Legge un export da URL API o glob locale. NON solleva eccezioni."""
    if src.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(src, timeout=CFG["HTTP_TIMEOUT"]) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[warn] sorgente URL non raggiungibile o JSON invalido: {src} ({e}) -> ignorata")
            return []
    out = []
    for f in sorted(glob.glob(src)):
        try:
            out.append(json.loads(Path(f).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"[warn] file ignorato {f}: {e}")
    return out


def load_exports():
    exs = []
    for src in CFG["SOURCES"]:
        r = fetch_source(src)
        exs.extend(r if isinstance(r, list) else [r])
    return [e for e in exs if isinstance(e, dict) and e.get("lifetime")]


# ----------------------------- costi reali -----------------------------
def real_cost_usd(inp: float, cache: float, out_ratio: float | None = None) -> float:
    p = CFG["PRICE"]
    new = max(inp - cache, 0)
    out = inp * (CFG["OUTPUT_RATIO"] if out_ratio is None else out_ratio)
    return (new * p["input"] + cache * p["cache_read"] + out * p["output"]) / 1e6 * CFG["CALIBRATION"]


def _miss_price(model: str) -> float:
    pr = MODEL_PRICES.get(model)
    if pr:
        return pr["input"]
    return CFG["PRICE"]["input"]


def _out_price(model: str) -> float:
    pr = MODEL_PRICES.get(model)
    if pr:
        return pr["output"]
    return CFG["PRICE"]["output"]


def measured_output_ratio() -> float | None:
    """Tenta /stats derivato dalle sorgenti HTTP; ritorna output/input misurato o None."""
    for src in CFG["SOURCES"]:
        if not src.startswith(("http://", "https://")):
            continue
        base = src.rsplit("/stats-history", 1)[0] if "/stats-history" in src else src.rstrip("/")
        url = base + "/stats" if not base.endswith("/stats") else base
        try:
            with urllib.request.urlopen(url, timeout=CFG["HTTP_TIMEOUT"]) as r:
                s = json.loads(r.read().decode("utf-8"))
            tok = s.get("tokens") or {}
            out, inp = tok.get("output", 0), tok.get("input", 0)
            if out and inp:
                return out / inp
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return None


def weighted_rate_usd_per_token(ex: dict, out_ratio: float) -> float:
    """Rate per-token pesato sul mix per-modello (lifetime by_model)."""
    bm = ex.get("by_model") or {}
    lt = ex.get("lifetime", {})
    inp_total = lt.get("total_input_tokens", 0) or sum(
        (m.get("total_input_tokens", 0) for m in bm.values()), 0)
    if not inp_total:
        return 0.0
    cache_frac = (lt.get("cache_read_tokens", 0) / inp_total) if inp_total else 0.0
    cache_frac = min(max(cache_frac, 0.0), 1.0)
    if not bm:
        p = CFG["PRICE"]
        return ((1 - cache_frac) * p["input"] + cache_frac * p["cache_read"]
                + out_ratio * p["output"]) / 1e6 * CFG["CALIBRATION"]
    rate = 0.0
    for model, m in bm.items():
        tok = m.get("total_input_tokens", 0) or 0
        if tok <= 0:
            continue
        share = tok / inp_total
        pr = MODEL_PRICES.get(model, {"input": CFG["PRICE"]["input"],
                                      "cached_input": CFG["PRICE"]["cache_read"],
                                      "output": CFG["PRICE"]["output"]})
        per_tok = ((1 - cache_frac) * pr["input"] + cache_frac * pr["cached_input"]
                   + out_ratio * pr["output"]) / 1e6 * CFG["CALIBRATION"]
        rate += share * per_tok
    return rate


def _local_suffix(ts_utc: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M (ora locale)")
    except (ValueError, TypeError):
        return (ts_utc[:10] or "-") + " (ora locale)"


def build_daily(exs, out_ratio: float) -> list:
    best: dict = {}
    for e in exs:
        for d in (e.get("series", {}).get("daily") or []):
            k, v = d.get("timestamp", "")[:10], d.get("total_input_tokens_delta", 0)
            if k and v and v >= best.get(k, {}).get("total_input_tokens_delta", 0):
                best[k] = d
    ordered = [best[k] for k in sorted(best)]
    window = ordered[-min(len(ordered), 14):] if ordered else []
    rows = []
    for d in window:
        tok = d.get("total_input_tokens_delta", 0) or 0
        bym = d.get("by_model") or {}
        models = {}
        for model, m in bym.items():
            mt = m.get("total_input_tokens_delta", 0) or 0
            if mt > 0:
                models[model] = {"tokens": mt, "cost_usd": mt * _miss_price(model) / 1e6}
        out_tok = tok * out_ratio
        w_out = 0.0
        if tok and models:
            w_out = sum((v["tokens"] / tok) * _out_price(m) for m, v in models.items())
        elif tok:
            w_out = CFG["PRICE"]["output"]
        rows.append({
            "date": d.get("timestamp", "")[:10],
            "timestamp_utc": d.get("timestamp", ""),
            "local": _local_suffix(d.get("timestamp", "")),
            "tokens": tok,
            "output_tokens": out_tok,
            "cost_usd": sum(v["cost_usd"] for v in models.values()) + out_tok * w_out / 1e6,
            "models": models,
        })
    return rows


def build_monthly(ex, daily_rows: list, out_ratio: float) -> dict:
    monthly = (ex.get("series", {}).get("monthly") or [])
    last = monthly[-1] if monthly else {}
    cum_tok = last.get("total_input_tokens_delta", 0) or 0
    bym = last.get("by_model") or {}
    models = {}
    for model, m in bym.items():
        mt = m.get("total_input_tokens_delta", 0) or 0
        if mt > 0:
            models[model] = {"tokens": mt, "cost_usd": mt * _miss_price(model) / 1e6}
    out_tok = cum_tok * out_ratio
    w_out = 0.0
    if cum_tok and models:
        w_out = sum((v["tokens"] / cum_tok) * _out_price(m) for m, v in models.items())
    elif cum_tok:
        w_out = CFG["PRICE"]["output"]
    cum_cost = sum(v["cost_usd"] for v in models.values()) + out_tok * w_out / 1e6
    win = daily_rows[-min(len(daily_rows), 14):] if daily_rows else []
    avg_tok = mean([r["tokens"] for r in win]) if win else 0.0
    avg_cost = mean([r["cost_usd"] for r in win]) if win else 0.0
    today = date.today()
    try:
        ts = last.get("timestamp", "")
        y, m = (int(ts[:4]), int(ts[5:7])) if len(ts) >= 7 else (today.year, today.month)
        dim = calendar.monthrange(y, m)[1]
    except (ValueError, calendar.IllegalMonthError):
        y, m, dim = today.year, today.month, calendar.monthrange(today.year, today.month)[1]
    remaining = max(dim - today.day if (y, m) == (today.year, today.month) else dim, 0)
    return {
        "month": (last.get("timestamp", "")[:7] or f"{y:04d}-{m:02d}"),
        "timestamp_utc": last.get("timestamp", ""),
        "local": _local_suffix(last.get("timestamp", "")),
        "cumulative_tokens": cum_tok,
        "cumulative_cost_usd": cum_cost,
        "output_tokens": out_tok,
        "models": models,
        "avg_daily_tokens": avg_tok,
        "avg_daily_cost_usd": avg_cost,
        "days_remaining": remaining,
        "estimate_tokens": cum_tok + avg_tok * remaining,
        "estimate_cost_usd": cum_cost + avg_cost * remaining,
    }


def merge_daily(exs):
    days = {}
    for e in exs:
        for d in (e.get("series", {}).get("daily") or []):
            k, v = d.get("timestamp", "")[:10], d.get("total_input_tokens_delta", 0)
            if k and v:
                days[k] = max(days.get(k, 0), v)
    return [(date.fromisoformat(k), v) for k, v in sorted(days.items())]


# ----------------------------- quota provider dinamico -----------------------------
def _norm_models(raw) -> list:
    """Normalizza [{'model':str,'usd':float}] scartando voci malformate."""
    out = []
    if not isinstance(raw, list):
        return out
    for m in raw:
        if not isinstance(m, dict):
            continue
        try:
            out.append({"model": str(m.get("model", "?")), "usd": float(m.get("usd", 0) or 0)})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda r: r["usd"], reverse=True)
    return out


def _resolve(p: str) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (BASE_DIR / p)


def load_quota(fallback_used: float):
    """Precedenza: (1) --quota-url GET JSON; (2) --quota-models/--quota-models-file + --quota-used;
    (3) fallback lifetime real_cost. Non solleva mai."""
    total = CFG["QUOTA_USD"]
    reset = str(CFG["RESET_DATE"])
    used = fallback_used
    models: list = []
    # (1) endpoint generico {used,total,reset,models:[{model,usd}]}
    url = CFG.get("QUOTA_URL")
    if url:
        try:
            req = urllib.request.Request(url)
            tok = os.environ.get("OPENCODE_API_TOKEN")
            if tok:
                req.add_header("Authorization", f"Bearer {tok}")
            with urllib.request.urlopen(req, timeout=10) as r:
                q = json.loads(r.read().decode("utf-8"))
            if isinstance(q, dict):
                if isinstance(q.get("used"), (int, float)):
                    used = float(q["used"])
                if isinstance(q.get("total"), (int, float)) and float(q["total"]) > 0:
                    total = float(q["total"])
                if isinstance(q.get("reset"), str) and q["reset"]:
                    reset = q["reset"]
                models = _norm_models(q.get("models"))
                if isinstance(q.get("used"), (int, float)):
                    return used, total, reset, models
        except Exception as e:
            print(f"[warn] quota-url non raggiungibile o invalida: {url} ({e}) -> fallback")
    # (2) stringa JSON e/o file + override --quota-used
    try:
        if CFG.get("QUOTA_MODELS"):
            qm = json.loads(CFG["QUOTA_MODELS"])
            models = _norm_models(qm.get("models") if isinstance(qm, dict) else qm)
            if isinstance(qm, dict):
                if isinstance(qm.get("used"), (int, float)):
                    used = float(qm["used"])
                if isinstance(qm.get("total"), (int, float)) and float(qm["total"]) > 0:
                    total = float(qm["total"])
                if isinstance(qm.get("reset"), str) and qm["reset"]:
                    reset = qm["reset"]
    except Exception as e:
        print(f"[warn] --quota-models invalido ({e}) -> ignorato")
    try:
        mf = CFG.get("QUOTA_MODELS_FILE")
        if mf and _resolve(mf).exists():
            qf = json.loads(_resolve(mf).read_text(encoding="utf-8"))
            if isinstance(qf, dict):
                if isinstance(qf.get("used"), (int, float)):
                    used = float(qf["used"])
                if isinstance(qf.get("total"), (int, float)) and float(qf["total"]) > 0:
                    total = float(qf["total"])
                if isinstance(qf.get("reset"), str) and qf["reset"]:
                    reset = qf["reset"]
                fm = _norm_models(qf.get("models"))
                if fm:
                    models = fm
            else:
                fm = _norm_models(qf)
                if fm:
                    models = fm
    except Exception as e:
        print(f"[warn] quota-models-file illeggibile ({e}) -> fallback")
    if CFG.get("QUOTA_USED") is not None:
        try:
            used = float(CFG["QUOTA_USED"])
        except (TypeError, ValueError):
            pass
    # (3) fallback implicito: used resta fallback_used se nulla ha fornito altro
    return used, total, reset, models


# ----------------------------- analisi + scenari -----------------------------
def analyze() -> dict:
    exs = load_exports()
    now = datetime.now()
    today = date.today()
    horizon = CFG["HORIZON_OVERRIDE"] or max((CFG["RESET_DATE"] - today).days, 1)
    if not exs:
        raise RuntimeError("nessun export Headroom leggibile dalle sorgenti configurate")
    ex = max(exs, key=lambda e: e.get("generated_at", ""))
    lt = ex["lifetime"]
    inp, cache = lt.get("total_input_tokens", 0), lt.get("cache_read_tokens", 0)
    out_ratio = measured_output_ratio() or CFG["OUTPUT_RATIO"]
    cost = real_cost_usd(inp, cache, out_ratio)
    q_used, q_total, q_reset, q_models = load_quota(cost)
    q_models_pct = [{"model": m["model"], "usd": m["usd"],
                     "pct": (m["usd"] / q_total * 100 if q_total else 0)} for m in q_models]
    rate = weighted_rate_usd_per_token(ex, out_ratio) or ((cost / inp) if inp else 0.0)
    daily_rows = build_daily(exs, out_ratio)
    monthly = build_monthly(ex, daily_rows, out_ratio)
    daily = merge_daily(exs)
    thr = CFG["MARATHON_THRESHOLD"]
    light_v = [v for _, v in daily if 0 < v < thr]
    mara_v = [v for _, v in daily if v >= thr]
    light = mean(light_v) if light_v else CFG["DEFAULT_LIGHT"]
    marathon = mean(mara_v) if mara_v else CFG["DEFAULT_MARATHON"]
    recent = mean([v for _, v in daily[-4:]]) if daily else CFG["DEFAULT_RECENT"]

    scenarios = [
        ("S1", "Ritmo recenti (media ultimi 4g, tutti i giorni)", {d: recent for d in range(7)}, f"{recent/1e6:.0f}M/giorno"),
        ("S2", "Weekend osservato (ven+sab leggere, dom maratona)", {4: light, 5: light, 6: marathon}, f"ven/sab {light/1e6:.0f}M, dom {marathon/1e6:.0f}M"),
        ("S3", "Weekend controllato (maratona dimezzata)", {4: light, 5: light, 6: marathon / 2}, f"ven/sab {light/1e6:.0f}M, dom {marathon/2e6:.0f}M"),
        ("S4", "Leggere sparse (lun, mer, ven, sab)", {0: light, 2: light, 4: light, 5: light}, f"4 sessioni {light/1e6:.0f}M/sett."),
        ("S5", "Solo weekend leggero (ven, sab)", {4: light, 5: light}, f"2 sessioni {light/1e6:.0f}M/sett."),
    ]
    rows = []
    for sid, name, pattern, desc in scenarios:
        tot_tok, cum, exhaust = 0.0, cost, None
        for i in range(horizon):
            d = today + timedelta(days=i)
            tk = pattern.get(d.weekday(), 0)
            tot_tok += tk
            cum += tk * rate
            if exhaust is None and cum >= CFG["QUOTA_USD"]:
                exhaust = d.isoformat()
        pct = cum / CFG["QUOTA_USD"] * 100
        verdict, cls = ("OK", "ok") if pct <= 85 else (("ATTENZIONE", "warn") if pct <= 100 else ("SFORAMENTO", "over"))
        rows.append({"id": sid, "name": name, "desc": desc, "tokens": tot_tok,
                     "cost": cum - cost, "total": cum, "pct": pct,
                     "exhaust": exhaust or "", "verdict": verdict, "cls": cls})
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "generated_at": ex.get("generated_at", "-"),
        "lifetime": {"input": inp, "cache_read": cache,
                     "cache_pct": round(cache / inp * 100, 1) if inp else 0, "real_cost": cost},
        "quota": {"total": q_total, "used": q_used, "pct": q_used / q_total * 100 if q_total else 0,
                  "left": max(q_total - q_used, 0), "days_left": horizon,
                  "reset": q_reset},
        "quota_models": q_models_pct,
        "profiles": {"light": light, "marathon": marathon, "recent": recent},
        "horizon": horizon, "scenarios": rows,
        "daily_last": [{"d": str(d), "tok": v} for d, v in daily[-7:]],
        "daily": daily_rows,
        "monthly": monthly,
        "model_prices": MODEL_PRICES,
        "output_ratio": out_ratio,
    }


def load_payload() -> dict:
    """Non solleva mai: il server deve restare vivo anche senza sorgenti."""
    with LOCK:
        try:
            return analyze()
        except Exception as e:
            horizon = CFG["HORIZON_OVERRIDE"] or max((CFG["RESET_DATE"] - date.today()).days, 1)
            return {"error": str(e), "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "generated_at": "-", "scenarios": [],
                    "lifetime": {"input": 0, "cache_read": 0, "cache_pct": 0, "real_cost": 0},
                    "quota": {"total": CFG["QUOTA_USD"], "used": 0, "pct": 0, "left": CFG["QUOTA_USD"],
                              "days_left": horizon, "reset": str(CFG["RESET_DATE"])},
                    "quota_models": [],
                    "profiles": {"light": 0, "marathon": 0, "recent": 0},
                    "horizon": horizon, "daily_last": [], "daily": [], "monthly": {},
                    "model_prices": MODEL_PRICES, "output_ratio": CFG["OUTPUT_RATIO"]}


# ----------------------------- render template -----------------------------
def render(payload: dict) -> str:
    if not TEMPLATE_PATH.exists():
        return f"<pre>Template non trovato: {TEMPLATE_PATH}</pre>"
    mtime = TEMPLATE_PATH.stat().st_mtime          # reload automatico se modifichi l'HTML
    if _TCACHE.get("mtime") != mtime:
        _TCACHE["html"] = TEMPLATE_PATH.read_text(encoding="utf-8")
        _TCACHE["mtime"] = mtime
    html = _TCACHE["html"].replace("@@QUOTA@@", f"{CFG['QUOTA_USD']:.0f}")
    return html.replace("@@PAYLOAD@@", json.dumps(payload))


# ----------------------------- server -----------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, body: str, ctype="text/html; charset=utf-8", code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            self._send(render(load_payload()))
        elif p in ("/refresh", "/api/stats"):
            self._send(json.dumps(load_payload()), "application/json")
        elif p == "/health":
            self._send("ok", "text/plain")
        else:
            self._send("not found", "text/plain", 404)

    def log_message(self, fmt, *args):
        print(f"[{datetime.now():%H:%M:%S}] {fmt % args}")


def main():
    ap = argparse.ArgumentParser(description="Dashboard proiezione consumi Headroom")
    ap.add_argument("--sources", action="append", default=[],
                    help='glob locale o URL API (ripetibile). Es. "./exports/*.json"')
    ap.add_argument("--host", default="127.0.0.1")
    # HEADROOM_PORT moves ONLY the Headroom proxy; dashboard port is this --port flag only.
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--quota", type=float, default=60.0)
    ap.add_argument("--quota-url", default=None,
                    help='endpoint JSON generico {used,total,reset,models} (auth via $OPENCODE_API_TOKEN)')
    ap.add_argument("--quota-models", default=None,
                    help='stringa JSON con shape {"models":[{"model":str,"usd":float}]}')
    ap.add_argument("--quota-models-file", default="./exports/quota-models.json",
                    help="path file snapshot quota (relativo a BASE_DIR se non assoluto)")
    ap.add_argument("--quota-used", type=float, default=None)
    ap.add_argument("--reset", default="2026-10-09")
    ap.add_argument("--horizon", type=int, default=None)
    ap.add_argument("--calibration", type=float, default=1.0)
    ap.add_argument("--emit", default=None, help="scrive uno snapshot HTML statico")
    a = ap.parse_args()
    CFG["SOURCES"] = a.sources or ["http://127.0.0.1:8787/stats-history", "./exports/*.json"]
    CFG["QUOTA_USD"], CFG["RESET_DATE"] = a.quota, date.fromisoformat(a.reset)
    CFG["HORIZON_OVERRIDE"], CFG["CALIBRATION"] = a.horizon, a.calibration
    CFG["QUOTA_URL"], CFG["QUOTA_MODELS"] = a.quota_url, a.quota_models
    CFG["QUOTA_MODELS_FILE"], CFG["QUOTA_USED"] = a.quota_models_file, a.quota_used

    pay = load_payload()
    if pay.get("error"):
        print(f"[warn] {pay['error']} — il server parte comunque; riprova dal pulsante Refresh")
    if a.emit:
        Path(a.emit).write_text(render(pay), encoding="utf-8")
        print(f"[ok] snapshot statico: {Path(a.emit).resolve()}")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"[ok] dashboard: http://{a.host}:{a.port}/  (template: {TEMPLATE_PATH})")
    print(f"[ok] orizzonte: {pay['horizon']}g · quota ${CFG['QUOTA_USD']:.0f} · reset {CFG['RESET_DATE']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[ok] stop")


if __name__ == "__main__":
    main()
