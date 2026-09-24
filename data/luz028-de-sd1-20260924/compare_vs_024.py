#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_vs_024.py -- SD-1 DE retest (LUZ028_DE_SD1_20260924) vs 0.2.4 baseline
(dev3-v18-20260920). Fail-closed: exits 1 if any cell missing/failed/grammar!=None/ct!=2048.

Verdict bands (user ruling 2026-09-24): anchor = 0.2.4 baseline, drift band
  |delta| <= 5%   -> PASS (green)
  5% < |d| <= 10% -> WATCH (amber, record-only)
  |d| > 10%       -> INVESTIGATE (red)
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Baseline matrix of the 0.2.4-era SD-1 board, resolved relative to this file so the
# script runs from a fresh clone on any machine:
BASE = os.path.join(os.path.dirname(HERE), "dev3-v18-20260920", "de_v3_matrix.json")
RE = os.path.join(HERE, "de_v3_matrix.json")
TYPES = ["structured", "prose", "code", "json"]
CONCS = [1, 2, 4, 8, 16]

b = json.load(open(BASE, encoding="utf-8"))
r = json.load(open(RE, encoding="utf-8"))

meta = r["_meta"]
print("== retest _meta ==")
for k in ("protocol_id", "run_tag", "model", "max_tokens", "waves", "concurrencies", "types"):
    print(f"  {k} = {meta.get(k)}")
assert meta["protocol_id"] == "SD-1", "protocol mismatch"
assert meta["waves"] == 3 and meta["max_tokens"] == 2048
assert meta["types"] == TYPES and meta["concurrencies"] == CONCS

def key(t, c): return "DE-V3_%s_C%d" % (t, c)

fails = 0
rows = []
print("\n== per-cell comparison (median_decode_tps) ==")
hdr = f"{'cell':24s} {'retest':>8s} {'0.2.4':>8s} {'delta%':>8s}  {'ok':>5s} {'ct':>5s} {'gram':>5s}  verdict"
print(hdr); print("-" * len(hdr))
for t in TYPES:
    for c in CONCS:
        k = key(t, c)
        rb, rr = b[k], r[k]
        v_b = rb["median_decode_tps"]; v_r = rr["median_decode_tps"]
        d = (v_r - v_b) / v_b * 100.0
        ok = "%d/%d" % (rr["streams_ok"], rr["waves"])
        ct = rr.get("median_completion_tokens")
        gram = rr.get("grammar")
        if abs(d) <= 5: verdict = "PASS"
        elif abs(d) <= 10: verdict = "WATCH"
        else: verdict = "INVESTIGATE"
        if gram is not None or ct != 2048 or rr["streams_ok"] < rr["waves"]:
            verdict += " *HARD-FAIL*"; fails += 1
        rows.append((k, v_r, v_b, d, ok, ct, gram, verdict))
        print(f"{k:24s} {v_r:8.2f} {v_b:8.2f} {d:+8.2f}  {ok:>5s} {ct:>5} {str(gram):>5s}  {verdict}")

print("\n== per-conc type spread (max/min, retest) ==")
for c in CONCS:
    vals = {t: r[key(t, c)]["median_decode_tps"] for t in TYPES}
    lo, hi = min(vals.values()), max(vals.values())
    print(f"  C{c:<3d} spread = {hi/lo:.2f}x   " + "  ".join(f"{t}={vals[t]:.2f}" for t in TYPES))
print("\n== per-conc type spread (0.2.4 baseline) ==")
for c in CONCS:
    vals = {t: b[key(t, c)]["median_decode_tps"] for t in TYPES}
    lo, hi = min(vals.values()), max(vals.values())
    print(f"  C{c:<3d} spread = {hi/lo:.2f}x   " + "  ".join(f"{t}={vals[t]:.2f}" for t in TYPES))

n_pass = sum(1 for x in rows if x[7] == "PASS")
n_watch = sum(1 for x in rows if x[7] == "WATCH")
n_inv = sum(1 for x in rows if x[7].startswith("INVESTIGATE"))
print(f"\n== verdicts: PASS={n_pass}  WATCH={n_watch}  INVESTIGATE={n_inv}  hard-fails={fails} ==")
sys.exit(1 if (fails or n_inv) else 0)
