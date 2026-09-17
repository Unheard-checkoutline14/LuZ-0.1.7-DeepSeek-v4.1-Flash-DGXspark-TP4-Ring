#!/usr/bin/env python3
"""Reproduce the a8 workspace tile-mismatch crash per capacity rung.

Serving crashed with 'workspace physical-tile capacity mismatch: expected at
least 392, got 383' during warm-up with DSV41_MOE_B12X_QUANT=a8. The numeric
gate (single capacity=4096 bucket) ran clean, so the bug is capacity-rung
specific. This probe plans/executes every adapter rung with random weights
and reports which (cap, m) combinations fail to bind.
"""
import torch

from b12x.moe import fused_moe as fm

E, K, N, TOPK = 192, 5120, 2304, 6
DEV = torch.device("cuda:0")

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

for cap in (6, 12, 24, 48, 72, 96, 128, 256, 512, 1024, 2048, 4096):
    exe = fm.plan_execution(experts=experts,
                            capacity=fm.ExecutionCapacity(max_tokens=cap,
                                                          top_k=TOPK))
    fm.prewarm(exe)
    specs = exe.scratch_specs()
    if len(specs) == 1:
        scratch = torch.empty(specs[0].shape, dtype=specs[0].dtype,
                              device=specs[0].device)
    else:
        scratch = {s.name: torch.empty(s.shape, dtype=s.dtype, device=s.device)
                   for s in specs}
    for m in {cap, min(cap, 72), 1}:
        x = torch.randn(m, K, dtype=torch.bfloat16, device=DEV) * 0.1
        ids = torch.zeros(m, TOPK, dtype=torch.int32, device=DEV)
        w = torch.full((m, TOPK), 1.0 / TOPK, dtype=torch.float32, device=DEV)
        try:
            b = fm.bind(exe, scratch=scratch, a=x, experts=experts,
                        topk_weights=w, topk_ids=ids)
            fm.run(binding=b)
            torch.cuda.synchronize()
            print(f"cap={cap:<5} m={m:<5} OK   specs={len(specs)}", flush=True)
        except Exception as exc:
            print(f"cap={cap:<5} m={m:<5} FAIL specs={len(specs)} "
                  f"shapes={[tuple(s.shape) for s in specs][:2]} "
                  f"err={str(exc)[:90]}", flush=True)
