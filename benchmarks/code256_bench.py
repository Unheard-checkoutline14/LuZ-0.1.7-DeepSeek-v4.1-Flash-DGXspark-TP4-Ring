#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""code256_bench.py -- short-output (256-token) code-decode bench, 3 concurrency points.

This is the harness behind the fp4-indexer A/B in section 7 of
`docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md` (c1 -6.4% / c8 -0.9% /
c16 -3.3%), the only experiment in this board where a feature was kept
**despite** measuring slightly negative. It also backs the decode side of the
gateway note in section 9.

Method
------
- single fixed LRU-cache coding prompt, `max_new_tokens=256`, temperature 0
- concurrency points 1 / 8 / 16, one wave each, threads (not processes)
- aggregate = sum(completion_tokens) / wall
- per-stream = **upper** median of (ct - 1) / (wall - ttft), `sorted(x)[n // 2]`
- endpoint: SGLang native /generate on 127.0.0.1:8899, streaming

Runs A and B are produced by toggling `--enable-deepseek-v4-fp4-indexer` on the
engine and re-running this file unchanged. The command is printed by the harness
one line per cell, e.g. `code256 c1: agg=... per-stream=... ok=1/1`.

Reproducibility note (do not "fix" this silently)
-------------------------------------------------
The upper-median convention here matches `benchmarks/de_matrix.py`, not
`benchmarks/de_matrix_structured.py`. It is kept as-is so the published deltas
stay reproducible. See `benchmarks/README.md`.

Env
---
KEY_FILE   default /state/api-key   (engine API key, one line of text)
"""
import json, time, threading, urllib.request, os

KEY = open(os.environ.get("KEY_FILE", "/state/api-key")).read().strip()
BASE = "http://127.0.0.1:8899"

PROMPT = ("Reference notes: the cache stores recently accessed entries. An implementation "
          "should maintain ordering, handle replacement and validate its invariants.\n"
          "Now write a complete Python LRU cache module with a doubly linked list and dictionary, "
          "including get, put, delete, iteration, resize, clear, invariant validation, detailed docstrings "
          "and ten usage examples. Return code only. Implement all methods fully.\n<｜Assistant｜></think>")


def one(out, idx):
    body = json.dumps({"text": PROMPT, "stream": True,
                       "sampling_params": {"temperature": 0, "max_new_tokens": 256}}).encode()
    req = urllib.request.Request(BASE + "/generate", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t0 = time.time()
    ttft = None
    ct = 0
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            if not line.startswith(b"data:"):
                continue
            p = line[6:].strip()
            if p == b"[DONE]":
                break
            ev = json.loads(p)
            m = ev.get("meta_info", {})
            c = m.get("completion_tokens", 0)
            if ttft is None and c > 0:
                ttft = time.time() - t0
            ct = c
    out[idx] = (ttft, time.time() - t0, ct)


for conc in [1, 8, 16]:
    out = {}
    ths = [threading.Thread(target=one, args=(out, i)) for i in range(conc)]
    t0 = time.time()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    wall = time.time() - t0
    ok = [v for v in out.values() if v[0]]
    toks = sum(v[2] for v in ok)
    agg = toks / wall
    decs = [(v[2] - 1) / (v[1] - v[0]) for v in ok if v[1] > v[0]]
    med = sorted(decs)[len(decs) // 2]
    print(f"code256 c{conc}: agg={agg:.1f} per-stream={med:.1f} ok={len(ok)}/{conc}", flush=True)
