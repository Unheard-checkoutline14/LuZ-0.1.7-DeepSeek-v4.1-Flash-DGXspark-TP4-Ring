#!/usr/bin/env python3
"""de_matrix_v3.py — DE decode matrix, sparkDash-aligned (2026-09-18).

Fixes the published-board distortion where grammar-constrained structured
coding/json measured far below free-form prose:

  Root causes fixed (vs de_matrix_structured.py):
  1. xgrammar json_schema imposed per-token grammar mask overhead — a real
     slowdown UNLIKE any other row on the board. sparkDash never uses guided
     decoding: output types are prompt labels only ("never response_format,
     grammars, or guided JSON" — DecodeBench.js header).
  2. Schema-satisfiable outputs EOS early (grammar kills ignore_eos):
     ct=119..2282 streams polluted per-wave medians. sparkDash force-fills the
     budget with min_tokens=max_tokens, ignore_eos=true, stop=[] (+400-retry
     stripping them).

  Protocol (mirrors sparkDash DecodeBench.js / LlmStreaming.js):
  - 4 prompt types from src/shared/llmPrompts.js verbatim (structured/prose/
    code/json), each + FILL_TO_MAX_SUFFIX; per-stream unique suffix so no
    prefix-cache sharing; C1 = exact prompt.
  - temperature 0, top_p 1, thinking off via chat_template_kwargs
    {enable_thinking:false, thinking:false, thinking_mode:"disabled"}.
  - streaming /v1/chat/completions, stream_options.include_usage.
  - warmup: one 32-token stream per type.
  - per-stream decode tok/s = (completion_tokens − 1) / (tLast − tFirst)
    [first→last content-token window, excludes prefill + teardown];
    prefill tok/s = usage.prompt_tokens / ttft.
  - per-wave aggregate decode = totalDecodeTokens / (max tLast − min tFirst)
    common window; per-wave aggregate prefill = totalPrefillTokens /
    (max tFirst − min t0).
  - waves=3; cell central value = statistics.median over ALL ok streams of
    all waves (single unified rule, per benchmarks/README.md §6);
    wave count recorded in the emitted JSON.

Env: TYPES (default structured,prose,code,json), CONCURRENCIES (1,2,4,8,16),
WAVES (3), MAXTOK (2048), BASE (default http://127.0.0.1:8899), KEY_FILE.
Output: <OUT_DIR>/de_v3_matrix.json + per-cell raw records de_<type>_c<N>.json
"""
import concurrent.futures
import json
import os
import statistics
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:8899")
_rawkey = open(os.environ.get("KEY_FILE", "/dev/shm/apikey")).read().strip()
KEY = _rawkey.split("=", 1)[1] if _rawkey.startswith("API_KEY=") else _rawkey
TYPES = [t.strip() for t in os.environ.get("TYPES", "structured,prose,code,json").split(",")]
CONCS = [int(x) for x in os.environ.get("CONCURRENCIES", "1,2,4,8,16").split(",")]
WAVES = int(os.environ.get("WAVES", "3"))
MAXTOK = int(os.environ.get("MAXTOK", "2048"))
MODEL = os.environ.get("MODEL", "deepseek-v41-flash")
OUT_DIR = os.environ.get("OUT_DIR") or ("/state/de-v3-" + time.strftime("%Y%m%dT%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

# ---- sparkDash prompts, verbatim from src/shared/llmPrompts.js ----
FILL_TO_MAX_SUFFIX = (" Continue generating until you hit the maximum output "
                      "length; do not stop early—keep expanding with more content.")

DECODE_STRUCTURED_PROMPT = ("Count from 1 to 200. Output only the numbers, "
                            "separated by spaces. No other text.")
DECODE_PROSE_PROMPT = ("Write a detailed step-by-step explanation of how a hash map works, "
                       "including collision handling, resizing, and time complexity. Be thorough.")
DECODE_CODE_PROMPT = (
    "Output only Python source code. No comments, no docstrings, no markdown fences. "
    "Write functions clamp_00 through clamp_49. Each function is exactly:\n"
    "def clamp_NN(x, lo=0, hi=1):\n"
    "    if x < lo:\n"
    "        return lo\n"
    "    if x > hi:\n"
    "        return hi\n"
    "    return x\n"
    "Change only the function name suffix (00, 01, … 49). One blank line between functions. "
    "No other text.")
DECODE_JSON_PROMPT = ("Emit only a JSON array of fake GPU metrics rows. Each object needs "
                      "host, gpuIndex, utilPct, tempC, powerW, memUsedMb. Invent many rows. "
                      "No markdown. Keep expanding the array.")

PROMPTS = {
    "structured": DECODE_STRUCTURED_PROMPT,
    "prose": DECODE_PROSE_PROMPT,
    "code": DECODE_CODE_PROMPT,
    "json": DECODE_JSON_PROMPT,
}


def build_prompt(ptype, count, idx):
    base = PROMPTS[ptype] + FILL_TO_MAX_SUFFIX
    if count <= 1:
        return base
    return f"{base} (stream {idx + 1}/{count})"


def request_body(prompt, max_tokens, force_fill=True):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "top_p": 1,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {
            "enable_thinking": False,
            "thinking": False,
            "thinking_mode": "disabled",
        },
    }
    if force_fill:
        body["min_tokens"] = max_tokens
        body["ignore_eos"] = True
        body["stop"] = []
    return body


def stream_chat(prompt, max_tokens, force_fill=True, timeout=3600):
    """One streaming request; returns metrics dict (sparkDash timing basis)."""
    body = request_body(prompt, max_tokens, force_fill)
    req = urllib.request.Request(
        BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t0 = time.time()
    t_first = None
    t_last = None
    chars = 0
    usage_ct = None
    usage_pt = None
    err = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.strip()
                if not line.startswith(b"data:"):
                    continue
                p = line[5:].strip()
                if p == b"[DONE]":
                    break
                try:
                    ev = json.loads(p)
                except Exception:
                    continue
                if ev.get("error"):
                    err = str(ev["error"])[:200]
                    break
                ch = (ev.get("choices") or [{}])[0]
                d = ch.get("delta") or {}
                piece = (d.get("content") or "") + (d.get("reasoning_content") or "")
                if piece:
                    now = time.time()
                    if t_first is None:
                        t_first = now
                    t_last = now
                    chars += len(piece)
                u = ev.get("usage")
                if u:
                    usage_ct = u.get("completion_tokens")
                    usage_pt = u.get("prompt_tokens")
    except urllib.error.HTTPError as e:
        err = "HTTP %d %s" % (e.code, e.read()[:150].decode(errors="replace"))
    except Exception as e:
        err = repr(e)[:200]
    wall = time.time() - t0
    out = {"prompt_chars": len(prompt), "wall": round(wall, 3), "error": err}
    if err:
        return out
    ct = usage_ct if (usage_ct is not None and usage_ct > 0) else 0
    out["completion_tokens"] = ct
    out["prompt_tokens"] = usage_pt or 0
    out["output_chars"] = chars
    out["ttft"] = round(t_first - t0, 4) if t_first else None
    decode_s = (t_last - t_first) if (t_first and t_last and t_last > t_first) else 0
    out["decode_ms"] = round(decode_s * 1000, 1)
    decode_tokens = max(0, ct - 1) if ct > 0 else 0
    out["decode_tokens"] = decode_tokens
    out["decode_tps"] = round(decode_tokens / decode_s, 2) if decode_s > 0 and decode_tokens else None
    out["prefill_tps"] = round((usage_pt or 0) / (t_first - t0) * 1000, 1) if (t_first and usage_pt) else None
    out["chars_per_token"] = round(chars / ct, 3) if ct else None
    return out


def run_wave(ptype, conc, max_tokens):
    prompts = [build_prompt(ptype, conc, i) for i in range(conc)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
        recs = list(ex.map(lambda p: stream_chat(p, max_tokens), prompts))
    ok = [r for r in recs if not r.get("error") and r.get("decode_tps")]
    wave = {"conc": conc, "streams_ok": len(ok), "streams_failed": conc - len(ok)}
    if ok:
        decode_tokens_total = sum(r["decode_tokens"] for r in ok)
        # common decode window (sparkDash basis): max(tLast) − min(tFirst) over ok streams.
        # tFirst_abs = wave_start + ttft is not recoverable per record, so we anchor on
        # the wave wall: window ≈ max(wall) − min(ttft) — the earliest first token to the
        # latest finish. Documented in the emitted "convention" string.
        window_s = max(r["wall"] for r in ok) - min(r["ttft"] for r in ok)
        wave["agg_decode_tps_window"] = round(decode_tokens_total / window_s, 1) if window_s > 0 else None
        wave["median_decode_tps"] = statistics.median(r["decode_tps"] for r in ok)
        wave["mean_decode_tps"] = round(statistics.mean(r["decode_tps"] for r in ok), 2)
        wave["median_ttft"] = round(statistics.median(r["ttft"] for r in ok), 4)
        wave["median_prompt_tokens"] = statistics.median(r["prompt_tokens"] for r in ok)
        wave["median_chars_per_token"] = round(statistics.median(r["chars_per_token"] for r in ok), 3)
        wave["total_completion_tokens"] = sum(r["completion_tokens"] for r in ok)
        prefill_ok = [r for r in ok if r.get("prefill_tps")]
        if prefill_ok:
            wave["median_prefill_tps"] = statistics.median(r["prefill_tps"] for r in prefill_ok)
    else:
        wave["error"] = recs[0].get("error")
    return wave, recs


def warmup(ptype):
    prompt = PROMPTS[ptype]
    stream_chat(prompt, 32, force_fill=False, timeout=300)


def main():
    results = {}
    for ptype in TYPES:
        try:
            warmup(ptype)
        except Exception:
            pass
        for c in CONCS:
            waves = []
            raw_all = []
            for w in range(WAVES):
                wave, recs = run_wave(ptype, c, MAXTOK)
                wave["wave"] = w
                waves.append(wave)
                raw_all.append(recs)
            ok_waves = [w for w in waves if w.get("streams_ok")]
            all_tps = [r["decode_tps"]
                       for recs in raw_all for r in recs
                       if not r.get("error") and r.get("decode_tps")]
            cell = {
                "type": ptype, "conc": c, "max_tokens": MAXTOK, "waves": WAVES,
                "ok_waves": len(ok_waves),
                "median_decode_tps": round(statistics.median(all_tps), 2) if all_tps else None,
                "agg_decode_tps_best_wave": max((w["agg_decode_tps_window"] for w in ok_waves), default=None),
                "agg_decode_tps_median_wave": round(statistics.median([w["agg_decode_tps_window"] for w in ok_waves]), 1) if ok_waves else None,
                "median_prefill_tps": round(statistics.median([w["median_prefill_tps"] for w in ok_waves]), 1) if ok_waves and all("median_prefill_tps" in w for w in ok_waves) else None,
                "median_ttft_s": round(statistics.median([w["median_ttft"] for w in ok_waves]), 4) if ok_waves else None,
                "median_chars_per_token": round(statistics.median([w["median_chars_per_token"] for w in ok_waves]), 3) if ok_waves else None,
                "convention": ("decode_tps = (completion_tokens-1)/(tLast-tFirst) per stream; "
                               "cell median over all ok streams of all waves (statistics.median); "
                               "agg = per-wave common window; prefill numerator = real usage.prompt_tokens"),
            }
            results[f"DE-V3_{ptype}_C{c}"] = cell
            print(json.dumps(cell), flush=True)
            with open(os.path.join(OUT_DIR, f"de_{ptype}_c{c}.json"), "w") as f:
                json.dump(raw_all, f, indent=1)
    summary = {
        "protocol": "sparkDash-aligned: no grammar/guided decoding, prompt-label types only, "
                    "min_tokens=max_tokens + ignore_eos + stop=[] force-fill, temp 0, top_p 1, thinking off",
        "model": MODEL, "base": BASE, "max_tokens": MAXTOK,
        "waves": WAVES, "concurrencies": CONCS,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(os.path.join(OUT_DIR, "de_v3_matrix.json"), "w") as f:
        json.dump({"_meta": summary, **results}, f, indent=1)
    print("OUT_DIR=" + OUT_DIR, flush=True)


if __name__ == "__main__":
    main()
