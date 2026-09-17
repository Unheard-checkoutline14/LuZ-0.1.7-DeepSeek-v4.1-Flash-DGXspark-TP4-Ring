#!/usr/bin/env python3
"""Numeric gate: b12x MoE W4A16 (incumbent) vs W4A8_MX (candidate).

C-2 methodology, kernel level with real layer-2 weights:
  - top-1 agreement of combined expert output per token, >= 99.5% required
  - relerr / max-abs-err recorded for the noise floor
Three activation calibers (random, multi-scale): N(0, 0.1^2) as in the
bake-off, x5 magnitude, and a heavy-tailed outlier variant -- FP8 dynamic
per-block scaling must hold across the range. The e2e side of the dual
caliber (real serving activations) is covered by GSM8K + accept-length
gates in the A8 window.

Run inside the container with the stack DOWN (GPU free), from the repo
bench/ dir:  python3 moe_a8_numeric_gate.py [--ms ...]
"""
import argparse
import sys

import torch

from moe_bakeoff import (B12xArm, DEV, E_LOCAL, K, N, TOPK, fi_arm,
                         interleave_scales, load_experts)


def calib_x(m, kind, seed):
    g = torch.Generator(device=DEV).manual_seed(seed)
    base = torch.randn(m, K, dtype=torch.bfloat16, device=DEV, generator=g) * 0.1
    if kind == "std":
        return base
    if kind == "x5":
        return base * 5.0
    if kind == "outlier":  # 1% dims x40 -- stress per-block FP8 dynamic range
        mask = (torch.rand(m, K, device=DEV, generator=g) < 0.01)
        return base * torch.where(mask, 40.0, 1.0).to(torch.bfloat16)
    raise ValueError(kind)


def top1_agree(a, b):
    return (a.float().argmax(-1) == b.float().argmax(-1)).float().mean().item()


def relerr(a, b):
    return ((a.float() - b.float()).norm() / (b.float().norm() + 1e-9)).item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ms", nargs="+", type=int,
                    default=[6, 12, 24, 48, 72, 96, 128, 256, 512, 1024, 2048, 4096])
    ap.add_argument("--fi", action="store_true",
                    help="also compare b12x a8 vs the serving FlashInfer W4A8 "
                         "arm (two independent W4A8 implementations)")
    args = ap.parse_args()

    torch.manual_seed(0)
    W = load_experts()
    print(f"weights: w13={tuple(W['w13_w1w3'].shape)} w2={tuple(W['w2'].shape)}",
          flush=True)

    mmax = max(args.ms)
    # b12x prepare_weights repacks the packed tensors in place (probe: a fresh
    # arm matches FI at 0.0186, an arm rebuilt from the same tensors is
    # uncorrelated sqrt(2)). Give each arm its own copies so both are valid.
    keep13 = W["w13_w1w3"].clone()
    keep13sf = W["w13_sf_w1w3"].clone()
    keep2 = W["w2"].clone()
    keep2sf = W["w2_sf"].clone()
    a16 = B12xArm("w4a16", W["w13_w1w3"], W["w13_sf_w1w3"], W["w2"], W["w2_sf"],
                  max_tokens=mmax, layout="W13")
    print(f"weight-repack probe: prepare_weights rewrote w13 in place = "
          f"{not torch.equal(keep13, W['w13_w1w3'])}", flush=True)
    a8 = B12xArm("w4a8", keep13.clone(), keep13sf.clone(),
                 keep2.clone(), keep2sf.clone(),
                 max_tokens=mmax, layout="W13")
    fi = None
    if args.fi:
        # serving-verified W4A8 implementation (interleaved scales); own
        # pristine weight copies for the same in-place-repack reason
        fi = (interleave_scales(keep13sf.clone()), interleave_scales(keep2sf.clone()))
        gscale = torch.ones(E_LOCAL, dtype=torch.float32, device=DEV)
    print("arms prepared (w4a16 / w4a8_mx%s)" % (" / fi-w4a8" if args.fi else ""),
          flush=True)

    rows, worst = [], 1.0
    for m in args.ms:
        g = torch.Generator(device=DEV).manual_seed(1234 + m)
        ids = torch.randint(0, E_LOCAL, (m, TOPK), device=DEV, generator=g)
        w = torch.softmax(torch.randn(m, TOPK, device=DEV, generator=g), -1).to(torch.float32)
        for kind in ("std", "x5", "outlier"):
            x = calib_x(m, kind, 7 + m)
            if m == args.ms[0] and kind == "std":
                # Evidence probes for the sqrt(2) failure mode of gate v1/v2:
                # x is NOT mutated (below); the real cause was prepare_weights
                # repacking w13 in place, so the second arm built from the same
                # tensors computed on garbage. Every arm now gets its own
                # pristine weight copies.
                keep = x.clone()
                a16.run(x, ids, w)
                print(f"input-mutation probe: a16.run rewrote x in place = "
                      f"{not torch.equal(x, keep)}", flush=True)
            o16 = a16.run(x.clone(), ids, w.clone())
            o8 = a8.run(x.clone(), ids, w.clone())
            extra = ""
            if fi is not None:
                ofi = fi_arm(x.clone(), ids, w.clone(), keep13.clone(),
                             fi[0].clone(), keep2.clone(), fi[1].clone(), gscale)
                extra = (f"  fi8vs16={relerr(ofi, o16):.4f}"
                         f" b8vsfi8={relerr(o8, ofi):.4f}")
            agree = top1_agree(o16, o8)
            rel = ((o16.float() - o8.float()).norm() /
                   (o16.float().norm() + 1e-9)).item()
            mad = (o16.float() - o8.float()).abs().max().item()
            rows.append((m, kind, agree, rel, mad))
            worst = min(worst, agree)
            print(f"M={m:<5} {kind:<8} top1={agree*100:7.3f}%  relerr={rel:.5f}  "
                  f"maxabs={mad:.4f}{extra}", flush=True)

    print(f"\nWORST top1 = {worst*100:.3f}%  (gate >= 99.500%)")
    print("VERDICT:", "PASS" if worst >= 0.995 else "FAIL")
    sys.exit(0 if worst >= 0.995 else 1)


if __name__ == "__main__":
    main()
