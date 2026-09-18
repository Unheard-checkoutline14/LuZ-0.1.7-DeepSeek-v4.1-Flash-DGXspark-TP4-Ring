#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pr_ab_gw_vs_direct.py -- PR prefill A/B: serving gateway vs direct engine.

Backs the gateway note in section 9 of
`docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md` and the sparkDash
"unexpected reading" investigation: it re-measures the same prompt through the
:8001 gateway and straight into :8899, alternating the order so drift cancels.

Method
------
- prompt = `"[prefill-bench <salt>]\\n" + " the" * (n_target - 40) + "\\n\\nReply OK."`
  i.e. English filler, so the tokenizer does **not** compress it the way the old
  x-repeat method did (that is the whole point of this particular A/B -- see the
  verdict report, section 2.3).
- one request per arm, 4 arms, alternating gw / direct / gw / direct
- prefill tps = usage.prompt_tokens / (first-content-chunk - t0)
- a model-name preflight runs first, because the four model names in this stack
  are not interchangeable across the two paths

Provisioning
------------
Both keys come from the environment; there are no defaults and the script
refuses to start without them. They are the two credentials the stack really
uses at these two hops, so do not paste them into this file:

    export AB_GW_KEY=<key the :8001 gateway expects>
    export AB_DIRECT_KEY=<key the engine on :8899 expects>

On a live node these are already present in the serving `.env` (see
`.env.tp4.example`). Target/served model names are discovered by preflight, so
this file carries none of them.

Usage
-----
    python3 pr_ab_gw_vs_direct.py        # evidence = the stdout lines, tee them
"""
import json, os, sys, time, uuid, urllib.request, urllib.error

CAND = os.environ.get(
    "AB_MODEL_CANDIDATES",
    "deepseek-v4.1-flash,deepseek-v41-flash,deepseek-v4.1-flash-vision-exp",
).split(",")

GW = ("http://127.0.0.1:8001/v1/chat/completions", os.environ.get("AB_GW_KEY", ""))
DIRECT = ("http://127.0.0.1:8899/v1/chat/completions", os.environ.get("AB_DIRECT_KEY", ""))

if not GW[1] or not DIRECT[1]:
    sys.exit("AB_GW_KEY / AB_DIRECT_KEY must be set (see the provisioning block in this file)")


def chat(url, key, model, prompt, max_tokens, timeout):
    body = {"model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True, "max_tokens": max_tokens, "temperature": 0,
            "stream_options": {"include_usage": True}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    t0 = time.time(); tfirst = None; ptoks = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            if obj.get("error"):
                return None, None, None, json.dumps(obj["error"])[:200]
            if tfirst is None:
                ch = (obj.get("choices") or [{}])[0]
                d = ch.get("delta") or {}
                if d.get("content") or d.get("reasoning_content"):
                    tfirst = time.time()
            if obj.get("usage"):
                ptoks = obj["usage"].get("prompt_tokens")
    ttft = (tfirst - t0) if tfirst else -1.0
    tps = (ptoks / ttft) if (ptoks and ttft > 0) else -1.0
    return ptoks, ttft, tps, None


def preflight(url, key):
    """Return first model name that the endpoint accepts."""
    for m in CAND:
        try:
            pt, tt, tp, err = chat(url, key, m, "Say OK.", 4, 60)
            if err is None:
                return m
        except urllib.error.HTTPError:
            pass
        except Exception:
            pass
    return None


def run_big(url, key, model, n_target=131072):
    salt = uuid.uuid4().hex[:8]
    reserved = 40
    prompt = ("[prefill-bench %s]\nIgnore the filler text below and reply with OK when done.\n" % salt) \
             + " the" * (n_target - reserved) + "\n\nReply OK."
    pt, tt, tp, err = chat(url, key, model, prompt, 8, 600)
    return {"prompt_tokens": pt, "ttft_s": None if tt is None else round(tt, 3),
            "prefill_tps": None if tp is None else round(tp, 1), "err": err}


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


m_gw = preflight(*GW)
m_dr = preflight(*DIRECT)
emit({"event": "preflight", "gw_model": m_gw, "direct_model": m_dr})
if not m_gw or not m_dr:
    emit({"event": "abort", "reason": "preflight failed"})
    sys.exit(1)

results = []
for label, ep, model in [("gw8001", GW, m_gw), ("direct8899", DIRECT, m_dr),
                         ("gw8001", GW, m_gw), ("direct8899", DIRECT, m_dr)]:
    try:
        rec = run_big(*ep, model)
    except Exception as e:
        rec = {"err": repr(e)[:200]}
    rec["path"] = label
    results.append(rec)
    emit({"event": "run", **rec})

gw = [r["prefill_tps"] for r in results if r.get("path") == "gw8001" and r.get("prefill_tps")]
dr = [r["prefill_tps"] for r in results if r.get("path") == "direct8899" and r.get("prefill_tps")]
if gw and dr:
    gm = sum(gw) / len(gw); dm = sum(dr) / len(dr)
    emit({"event": "summary", "gw_mean_tps": round(gm, 1), "direct_mean_tps": round(dm, 1),
          "gw_vs_direct_pct": round((gm / dm - 1) * 100, 1)})
