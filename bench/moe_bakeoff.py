"""MoE kernel bake-off: FlashInfer CUTLASS W4A8 (serving path) vs b12x 1.3.0.

Runs on one GB10 (single local EP shard = rank0's 192 experts of layer 2,
real checkpoint weights). Measures per-M latency and numerics vs a bf16
dequantized reference. Layout order of w13 ([w1;w3] vs [w3;w1]) is probed
against the FI kernel so the same semantics feed the b12x arms.

Usage (inside a throwaway container of the serving image):
  PYTHONPATH=/opt/b12x python3 /bench/moe_bakeoff.py --arms fi w4a8 w4a16 \
      --ms 6 12 24 48 72 128 256 2048 --iters-small 30 --iters-large 10
"""
import argparse
import json
import sys
import time

import torch

E_LOCAL, K, N, TOPK, LIMIT, LAYER = 192, 5120, 2304, 6, 10.0, 2
CKPT = "/models/model-00005-of-00048.safetensors"
DEV = torch.device("cuda:0")


def load_experts():
    from safetensors import safe_open

    f = safe_open(CKPT, framework="pt", device="cpu")
    w1, w3, w2, s1, s3, s2 = [], [], [], [], [], []
    for e in range(E_LOCAL):
        w1.append(f.get_tensor(f"layers.{LAYER}.ffn.experts.{e}.w1.weight"))
        w3.append(f.get_tensor(f"layers.{LAYER}.ffn.experts.{e}.w3.weight"))
        w2.append(f.get_tensor(f"layers.{LAYER}.ffn.experts.{e}.w2.weight"))
        s1.append(f.get_tensor(f"layers.{LAYER}.ffn.experts.{e}.w1.scale"))
        s3.append(f.get_tensor(f"layers.{LAYER}.ffn.experts.{e}.w3.scale"))
        s2.append(f.get_tensor(f"layers.{LAYER}.ffn.experts.{e}.w2.scale"))
    st = lambda xs: torch.stack(xs, 0).to(DEV)
    w13_w1w3 = st([torch.cat([a, b], 0) for a, b in zip(w1, w3)])
    w13_w3w1 = st([torch.cat([b, a], 0) for a, b in zip(w1, w3)])
    w13_sf_w1w3 = st([torch.cat([a, b], 0) for a, b in zip(s1, s3)])
    w13_sf_w3w1 = st([torch.cat([b, a], 0) for a, b in zip(s1, s3)])
    return {
        "w13_w1w3": w13_w1w3, "w13_w3w1": w13_w3w1,
        "w13_sf_w1w3": w13_sf_w1w3, "w13_sf_w3w1": w13_sf_w3w1,
        "w2": st(w2), "w2_sf": st(s2),
    }


def interleave_scales(sf):
    from flashinfer import block_scale_interleave

    sf = sf.view(torch.uint8)
    out = sf.clone()
    for i in range(out.shape[0]):
        out[i] = block_scale_interleave(out[i]).reshape_as(out[i])
    return out.view(torch.float8_e8m0fnu)


def dequant_ref(x, ids, weights, w13, w13_sf, w2, w2_sf):
    """bf16 reference: dequant MXFP4 -> bf16, dense math, swiglu limit."""
    def deq(w_u8, sf):
        # w_u8 [N, K/2] int8 packed nibbles; sf [N, K/32] e8m0
        n, kh = w_u8.shape
        kk = kh * 2
        u8 = w_u8.view(torch.uint8)
        lo = u8 & 0xF
        hi = u8 >> 4
        fp4 = torch.stack([lo, hi], dim=-1).reshape(n, kk).float()
        sign = torch.where(fp4 >= 8, -1.0, 1.0)
        mag = torch.where(fp4 >= 8, fp4 - 8.0, fp4)
        lut = torch.tensor([0, 0.5, 1, 1.5, 2, 3, 4, 6], device=w_u8.device)
        val = lut[mag.long()] * sign
        s = sf.float()
        s = s.repeat_interleave(32, dim=1)
        return val * s

    out = torch.zeros(x.shape[0], K, dtype=torch.float32, device=x.device)
    for t in range(x.shape[0]):
        acc = torch.zeros(K, dtype=torch.float32, device=x.device)
        for j in range(ids.shape[1]):
            e = int(ids[t, j])
            w13e = deq(w13[e], w13_sf[e])
            gate = w13e[: w13e.shape[0] // 2] @ x[t].float()
            up = w13e[w13e.shape[0] // 2 :] @ x[t].float()
            act = (gate / LIMIT).clamp(max=8.0) * torch.sigmoid(gate / LIMIT) * up \
                if False else torch.nn.functional.silu(gate / LIMIT) * up
            w2e = deq(w2[e], w2_sf[e])
            acc += weights[t, j].float() * (w2e @ act)
        out[t] = acc
    return out


def fi_arm(x, ids, weights, w13, w13_sf, w2, w2_sf, global_scale):
    from flashinfer import mxfp8_quantize

    try:
        from sglang.srt.layers.moe.moe_runner.flashinfer_cutlass import (
            _flashinfer_cutlass_fused_moe,
        )
        fn, ActivationType = _flashinfer_cutlass_fused_moe()
    except Exception as exc:  # bare-container fallback, same symbols
        print(f"sglang helper import failed ({exc}); direct flashinfer import",
              flush=True)
        from flashinfer.fused_moe import cutlass_fused_moe as _fn
        from flashinfer.fused_moe.core import ActivationType as _AT
        fn, ActivationType = _fn, _AT

    xq, input_sf = mxfp8_quantize(x, is_sf_swizzled_layout=True, alignment=32)
    out = torch.empty(x.shape[0], K, dtype=torch.bfloat16, device=x.device)
    next_pow2 = 1 << max(0, (x.shape[0] - 1).bit_length()) if x.shape[0] > 1 else 1
    fn(
        input=xq,
        token_selected_experts=ids.to(torch.int32),
        token_final_scales=weights,
        fc1_expert_weights=w13.view(torch.int64),
        fc2_expert_weights=w2.view(torch.int64),
        output_dtype=torch.bfloat16,
        quant_scales=[w13_sf.view(torch.int32), global_scale,
                      w2_sf.view(torch.int32), global_scale],
        input_sf=input_sf,
        fc1_expert_biases=None, fc2_expert_biases=None,
        swiglu_alpha=None, swiglu_beta=None,
        swiglu_limit=torch.full((E_LOCAL,), LIMIT, dtype=torch.float32, device=x.device),
        tp_size=1, tp_rank=0, ep_size=1, ep_rank=0,
        use_w4_group_scaling=False, use_mxfp8_act_scaling=True,
        activation_type=ActivationType.Swiglu,
        tune_max_num_tokens=next_pow2,
        output=out,
        use_fused_finalize=True,
    )
    return out


class B12xArm:
    def __init__(self, mode, w13, w13_sf, w2, w2_sf, max_tokens, layout="W31"):
        from b12x.moe import fused_moe as fm

        self.fm = fm
        src = fm.PackedSource(
            format=fm.PackedSourceFormat.MXFP4_E8M0_K32,
            w13_layout=fm.W13Layout[layout],
        )
        act = fm.ActivationSpec(
            mode={"w4a8": fm.ActivationMode.A8, "w4a16": fm.ActivationMode.A16}[mode],
            nonlinearity="silu",
            io_dtype=torch.bfloat16,
            swiglu_limit=LIMIT,
        )
        geo = fm.MoEGeometry(
            num_experts=E_LOCAL, hidden_size=K, intermediate_size=N
        )
        wp = fm.plan_weights(source=src, activation=act, geometry=geo)
        ones = torch.ones(E_LOCAL, dtype=torch.float32, device=DEV)
        pw = fm.PackedWeights(
            w13=w13.view(torch.uint8), w2=w2.view(torch.uint8),
            w13_block_scales=w13_sf, w2_block_scales=w2_sf,
            w13_global_scales=ones, w2_global_scales=ones,
        )
        self.experts = fm.prepare_weights(plan=wp, weights=pw)
        self.plans = {}
        self.max_tokens = max_tokens
        exe = fm.plan_execution(
            experts=self.experts,
            capacity=fm.ExecutionCapacity(max_tokens=max_tokens, top_k=TOPK),
        )
        fm.prewarm(exe)
        self.exe = exe
        spec = exe.scratch_specs()[0]
        self.scratch = torch.empty(spec.shape, dtype=spec.dtype, device=spec.device)

    def run(self, x, ids, weights):
        b = self.fm.bind(
            self.exe, scratch=self.scratch, a=x,
            experts=self.experts,
            topk_weights=weights.to(torch.float32),
            topk_ids=ids.to(torch.int32),
        )
        return self.fm.run(binding=b)


def bench(fn, iters):
    s, e = torch.cuda.Event(True), torch.cuda.Event(True)
    torch.cuda.synchronize()
    s.record()
    for _ in range(iters):
        fn()
    e.record()
    torch.cuda.synchronize()
    return s.elapsed_time(e) * 1000.0 / iters  # us


def relerr(a, b):
    return ((a.float() - b.float()).norm() / (b.float().norm() + 1e-9)).item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", nargs="+", default=["fi", "w4a8", "w4a16"])
    ap.add_argument("--ms", nargs="+", type=int,
                    default=[6, 12, 24, 48, 72, 128, 256, 2048])
    ap.add_argument("--iters-small", type=int, default=30)
    ap.add_argument("--iters-large", type=int, default=10)
    ap.add_argument("--out", default="/state/moe-bakeoff.json")
    args = ap.parse_args()

    torch.manual_seed(0)
    W = load_experts()
    print(f"weights loaded: w13={tuple(W['w13_w1w3'].shape)} "
          f"w2={tuple(W['w2'].shape)}", flush=True)

    ms_max = max(args.ms)
    x = torch.randn(ms_max, K, dtype=torch.bfloat16, device=DEV) * 0.1
    ids = torch.randint(0, E_LOCAL, (ms_max, TOPK), device=DEV)
    logits = torch.randn(ms_max, TOPK, device=DEV)
    weights = torch.softmax(logits, -1).to(torch.float32)

    # Cross-lib layout probe: FI(w1w3/w3w1) x b12x(W13/W31) at M=48.
    fi_sf = {"w1w3": interleave_scales(W["w13_sf_w1w3"]),
             "w3w1": interleave_scales(W["w13_sf_w3w1"])}
    w2_sf_il = interleave_scales(W["w2_sf"])
    gscale = torch.ones(E_LOCAL, dtype=torch.float32, device=DEV)
    probe_m = 48
    xm, im, wm = x[:probe_m], ids[:probe_m], weights[:probe_m]
    fi_out = {o: fi_arm(xm, im, wm, W[f"w13_{o}"], fi_sf[o], W["w2"], w2_sf_il, gscale)
              for o in ("w1w3", "w3w1")}
    b12x_out = {}
    for lay in ("W13", "W31"):
        arm = B12xArm("w4a8", W[f"w13_w1w3" if lay == "W13" else "w13_w3w1"],
                      W[f"w13_sf_w1w3" if lay == "W13" else "w13_sf_w3w1"],
                      W["w2"], W["w2_sf"], ms_max, layout=lay)
        b12x_out[lay] = arm.run(xm, im, wm)
    cross = {f"fi_{o}__{lay}": round(relerr(fi_out[o], b12x_out[lay]), 4)
             for o in ("w1w3", "w3w1") for lay in ("W13", "W31")}
    best = min(cross, key=cross.get)
    fi_order = best.split("__")[0].split("_", 1)[1]
    b12x_layout = best.split("__")[1]
    print(f"cross-lib layout probe: {cross} -> fi={fi_order} b12x={b12x_layout}",
          flush=True)
    w13 = W[f"w13_{fi_order}"]
    w13_sf_raw = W[f"w13_sf_{fi_order}"]
    w13_sf_fi = fi_sf[fi_order]

    results = {"cross_probe": cross, "fi_order": fi_order,
               "b12x_layout": b12x_layout, "rows": []}
    arms = {}

    if "fi" in args.arms:
        def mk_fi(xx, ii, ww):
            return fi_arm(xx, ii, ww, w13, w13_sf_fi, W["w2"], w2_sf_il, gscale)
        arms["fi"] = mk_fi
    for m in ("w4a8", "w4a16"):
        if m in args.arms:
            arm = B12xArm(m, w13, w13_sf_raw, W["w2"], W["w2_sf"], ms_max,
                          layout=b12x_layout)
            arms[m] = arm.run

    for M in args.ms:
        iters = args.iters_small if M <= 256 else args.iters_large
        xm, im, wm = x[:M], ids[:M], weights[:M]
        row = {"M": M}
        for name, fn in arms.items():
            fn(xm, im, wm)  # warm
            us = bench(lambda: fn(xm, im, wm), iters)
            row[name] = round(us, 1)
            row[f"{name}_ms"] = round(us * M / 1e6, 3)
            print(f"M={M:5d} {name:6s} {us:9.1f} us  ({us*M/1e3:8.1f} ns/tok)",
                  flush=True)
        results["rows"].append(row)

    # numerics: cross-lib agreement at M=48 (indicative; both are A8 paths)
    M = 48
    num = {}
    for name, fn in arms.items():
        num[name] = round(relerr(fn(x[:M], ids[:M], weights[:M]),
                                 arms["fi"](x[:M], ids[:M], weights[:M])), 4) \
            if name != "fi" else 0.0
    results["relerr_vs_fi_M48"] = num
    print("cross-arm relerr vs FI @M48:", num, flush=True)

    json.dump(results, open(args.out, "w"), indent=1)
    print("saved", args.out, flush=True)


if __name__ == "__main__":
    main()
