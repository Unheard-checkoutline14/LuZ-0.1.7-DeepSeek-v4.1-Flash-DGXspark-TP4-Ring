#!/usr/bin/env python3
"""Sweep-verify an a8 bucket ladder against b12x's m-dependent tile demand.

b12x re-plans per call with the ACTUAL m (b12x_moe_fp4 -> plan_tp_moe_execution
(num_tokens=m)) and validates the capacity-C workspace against it. Tile_m
selection (_select_dynamic_tile_mn) is keyed on routed_rows=m*topk with
boundaries at 16*E and 36*E, and the tile demand is non-monotonic across those
boundaries: m just below a boundary needs MORE physical tiles than m at the
capacity rung above it. Serving crashed at cap=2048 / m~1070 (383 < 392).

For E=192 topk=6: tile_m=16 while m<=512, 32 while m<=1152, 64 above; peak
demand 407 tiles at m in (1024,1152] and (2048,2304]. Ladder under test:
(128, 256, 512, 1024, 2304, 4096) -- every rung's planned tiles >= the max
demand of its m-range. Dense sweep around boundaries, coarse elsewhere.
"""
import sys

import torch

from b12x.moe import fused_moe as fm

E, K, N, TOPK = 192, 5120, 2304, 6
DEV = torch.device("cuda:0")
LADDER = (128, 256, 512, 1024, 2304, 4096)
EXACT_MAX = 96


def cap_for(m):
    if m <= EXACT_MAX:
        return m
    for cap in LADDER:
        if m <= cap:
            return cap
    return None


def main():
    torch.manual_seed(0)
    src = fm.PackedSource(format=fm.PackedSourceFormat.MXFP4_E8M0_K32,
                          w13_layout=fm.W13Layout.W13)
    act = fm.ActivationSpec(mode=fm.ActivationMode.A8, nonlinearity="silu",
                            io_dtype=torch.bfloat16, swiglu_limit=10.0)
    geo = fm.MoEGeometry(num_experts=E, hidden_size=K, intermediate_size=N)
    wp = fm.plan_weights(source=src, activation=act, geometry=geo)
    w13 = torch.randint(0, 255, (E, 2 * N, K // 2), dtype=torch.uint8, device=DEV)
    w2 = torch.randint(0, 255, (E, K, N // 2), dtype=torch.uint8, device=DEV)
    sf13 = torch.ones(E, 2 * N, K // 32, dtype=torch.float8_e8m0fnu, device=DEV)
    sf2 = torch.ones(E, K, N // 32, dtype=torch.float8_e8m0fnu, device=DEV)
    ones = torch.ones(E, dtype=torch.float32, device=DEV)
    pw = fm.PackedWeights(w13=w13, w2=w2, w13_block_scales=sf13,
                          w2_block_scales=sf2, w13_global_scales=ones,
                          w2_global_scales=ones)
    experts = fm.prepare_weights(plan=wp, weights=pw)

    buckets = {}
    def bucket(cap):
        if cap not in buckets:
            exe = fm.plan_execution(
                experts=experts,
                capacity=fm.ExecutionCapacity(max_tokens=cap, top_k=TOPK))
            fm.prewarm(exe)
            specs = exe.scratch_specs()
            assert len(specs) == 1, specs
            scratch = torch.empty(specs[0].shape, dtype=specs[0].dtype,
                                  device=specs[0].device)
            buckets[cap] = (exe, scratch)
        return buckets[cap]

    # boundary-dense m set: tile_m switches at m=512 and m=1152 (routed 3072 /
    # 6912 at topk 6); also rung edges 1024/2304/4096 and a coarse fill.
    ms = set()
    for lo, hi, step in ((90, 520, 4), (1000, 1200, 2), (2020, 2320, 4),
                         (4060, 4096, 4), (520, 1000, 16), (1200, 2020, 16),
                         (2320, 4060, 16)):
        ms.update(range(lo, hi + 1, step))
    ms.update((511, 512, 513, 1023, 1024, 1025, 1151, 1152, 1153, 2303,
               2304, 2305))

    bad = 0
    for m in sorted(ms):
        cap = cap_for(m)
        if cap is None:
            print(f"m={m}: over ladder", flush=True)
            bad += 1
            continue
        exe, scratch = bucket(cap)
        x = torch.randn(m, K, dtype=torch.bfloat16, device=DEV) * 0.1
        ids = torch.zeros(m, TOPK, dtype=torch.int32, device=DEV)
        w = torch.full((m, TOPK), 1.0 / TOPK, dtype=torch.float32, device=DEV)
        try:
            b = fm.bind(exe, scratch=scratch, a=x, experts=experts,
                        topk_weights=w, topk_ids=ids)
            fm.run(binding=b)
            torch.cuda.synchronize()
        except Exception as exc:
            print(f"m={m:<5} cap={cap:<5} FAIL {str(exc)[:100]}", flush=True)
            bad += 1
    print(f"\nswept {len(ms)} m values, ladder={LADDER}, failures={bad}",
          flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
