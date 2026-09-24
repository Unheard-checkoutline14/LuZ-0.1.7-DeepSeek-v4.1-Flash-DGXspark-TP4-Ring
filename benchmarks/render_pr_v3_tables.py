#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_pr_v3_tables.py -- emit the PR-v3 tables from the archive.

Companion to `pr_matrix_v3.py`. The PR-v3 section of FINAL-METRICS carries a
`<!-- generated from ... -->` marker and `scripts/check_report_tables.py` compares
that table against this renderer's output, so the published numbers cannot drift
from `data/prv3-20260918/` without a failing check:

    python3 benchmarks/render_pr_v3_tables.py data/prv3-20260918

Prints two blocks (the 34-cell per-cell table and the 7x5 compressed view), each
preceded by the same marker the report uses.

The concurrency columns come from `pr_v3_concurrency.py`'s clustering rule
(gap tolerance 10 ms) applied to the raw per-stream files -- NOT from the
`ttft_overlap_peak` field in summary.json, which is degenerate when
`max_new_tokens=1` because `t_end - t_first` is ~0.1 ms.
"""
import glob
import json
import os
import statistics
import sys

CONCS = [1, 2, 4, 8, 16]
TOL = 0.010

MARKER_FULL = "<!-- generated from summary.json + raw/*-c*-w0.json%s -->"
MARKER_MATRIX = "<!-- generated from summary.json (7x5%s) -->"

# Both summary schemas this repo has shipped. `prv3-*` writes the verbose keys plus
# `_meta.sizes`; the 0.2.8 collector writes `{inp, conc, n, tok, wall, tps, ttft_first,
# ttft_last}` and no `_meta`. Rendering stays mechanical either way -- but the mapping is
# explicit and a missing output field raises, so a schema this script has never seen
# fails loudly instead of rendering blank cells that look like real zeros.
FIELD_ALIASES = {
    "inp": "input_tokens",
    "conc": "concurrency",
    "n": "streams_ok",
    "tok": "total_prompt_tokens",
    "wall": "wall_s",
    "tps": "total_throughput_tps",
    "ttft_first": "ttft_first_s",
    "ttft_last": "ttft_last_s",
}
REQUIRED = ["input_tokens", "concurrency", "streams_ok", "total_prompt_tokens", "wall_s",
            "total_throughput_tps", "ttft_first_s", "ttft_last_s"]


def normalize(summ, root=""):
    """Map either shipped summary schema onto the canonical field names."""
    cells = []
    for c in summ["cells"]:
        cell = dict(c)
        for short, full in FIELD_ALIASES.items():
            if short in cell and full not in cell:
                cell[full] = cell.pop(short)
        cells.append(cell)
    missing = sorted({k for c in cells for k in REQUIRED if k not in c})
    if missing:
        raise SystemExit("summary.json: cell(s) missing required field(s): %s" % missing)
    meta = dict(summ.get("_meta") or {})
    if "sizes" not in meta:
        meta["sizes"] = sorted({c["input_tokens"] for c in cells})
    # The marker must identify *which* archive produced the table: three archives in this
    # repo render the same shape, so a bare `(7x5)` marker made two different tables
    # answer to the same key and a checker comparing report-vs-archive could pass or fail
    # against the wrong table. Carry the run tag (falling back to the directory name).
    meta["run_tag"] = (summ.get("run_tag") or meta.get("run_tag")
                       or os.path.basename(os.path.normpath(root)))
    return {"cells": cells, "_meta": meta}


def clusters(vs, tol=TOL):
    vs = sorted(vs)
    out = [[vs[0]]]
    for v in vs[1:]:
        if v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "data/prv3-20260918"
    summ = normalize(json.load(open(os.path.join(root, "summary.json"), encoding="utf-8")), root)
    cells = {(c["input_tokens"], c["concurrency"]): c for c in summ["cells"]}
    sizes = summ["_meta"]["sizes"]

    width = {}
    for f in glob.glob(os.path.join(root, "raw", "*-c*-w0.json")):
        st = json.load(open(f, encoding="utf-8"))
        ok = [r for r in st if not r.get("error") and r.get("t_first")]
        inp = ok[0].get("input_tokens") or ok[0].get("prompt_tokens")
        conc = len(st)
        cl = clusters([r["t_first"] for r in ok])
        width[(inp, conc)] = (max(len(c) for c in cl), len(cl))

    tag = summ["_meta"].get("run_tag")
    suffix = (", %s" % tag) if tag else ""
    print(MARKER_FULL % suffix)
    print()
    print("| Input tokens | C | Streams OK | Total prompt tokens | Wall s | **Total t/s** "
          "| TTFT first s | TTFT last s | Observed batch width | Prefill batches | Verdict |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in sizes:
        for c in CONCS:
            x = cells.get((s, c))
            if not x:
                print(f"| {s} | {c} | — | — | — | **—** | — | — | — | — "
                      f"| ⛔ 未测（本轮停跑，非失败） |")
                continue
            w, nc = width[(s, c)]
            verdict = ("parallel (2/step)" if w >= 2
                       else ("serialized (1/step)" if c > 1 else "single stream"))
            print(f"| {s} | {c} | {x['streams_ok']}/{c} | {x['total_prompt_tokens']} "
                  f"| {x['wall_s']:.3f} | **{x['total_throughput_tps']:.1f}** "
                  f"| {x['ttft_first_s']:.3f} | {x['ttft_last_s']:.3f} | {w} | {nc} | {verdict} |")

    print()
    print(MARKER_MATRIX % suffix)
    print()
    print("| Input tokens | C1 | C2 | C4 | C8 | C16 | row median | best |")
    print("|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in sizes:
        vals = [f"{cells[(s, c)]['total_throughput_tps']:.1f}" if (s, c) in cells else "—"
                for c in CONCS]
        have = [cells[(s, c)]["total_throughput_tps"] for c in CONCS if (s, c) in cells]
        b = max((cells[(s, c)]["total_throughput_tps"], c) for c in CONCS if (s, c) in cells)
        print(f"| {s} | " + " | ".join(vals) +
              f" | {statistics.median(have):.1f} | **{b[0]:.1f}** @C{b[1]} |")

    missing = [(s, c) for s in sizes for c in CONCS if (s, c) not in cells]
    if missing:
        print(f"\n# NOTE: {len(missing)} cell(s) not measured: {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
