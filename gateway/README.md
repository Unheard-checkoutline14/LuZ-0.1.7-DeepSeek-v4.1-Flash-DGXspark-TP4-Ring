# `gateway/` — streaming-aware concurrency proxy

A single-file [aiohttp](https://docs.aiohttp.org/) service that fronts the inference
engine and owns the parts of serving the engine does not: admission, liveness of idle
streams, request equivalence, and client-side input hygiene.

```
client ──►  gateway :8001  ──►  engine (OpenAI-compatible)
              │
              ├─ SSE heartbeat            idle streams survive minute-scale prefills
              ├─ TTFT budget              fail fast instead of holding a slot to nowhere
              ├─ backpressure admission   MAX_CONCURRENCY + bounded queue -> 429 + Retry-After
              ├─ equivalence dedup        same body hash -> 429, no second full prefill
              ├─ disconnect propagation   client gone -> upstream cancelled
              ├─ image-placeholder guard  literal image tokens rewritten, not rejected
              └─ /health, /gw/metrics
```

## Files

| file | what |
|---|---|
| `concurrency_proxy_v2.py` | the proxy — one file, no package, no config file of its own |
| `concurrency-proxy-v2.env.example` | every knob with its default and the reasoning behind it |
| `concurrency-proxy-v2.service.example` | systemd unit sample |
| `test_sanitize_image_placeholders.py` | unit tests for the G7 sanitizer (15 assertions, fail-closed) |

Requires `aiohttp` only. Python 3.8+ (no f-strings-as-logging, no `match`).

## Failure contract (read this before trusting a 200)

Every failure after the stream is open terminates the stream **explicitly**.
None of them rely on the client noticing that the body just stopped:

- errors are emitted as `chat.completion.chunk` frames carrying an `error` key;
- enqueue never raises — a full queue drops and counts the frame rather than
  throwing into the pump loop;
- a mid-flight upstream read failure emits an error frame before the terminator;
- error frames are followed by `data: [DONE]`;
- chunk-idle expiry logs `rx` / `tx` / elapsed and adds the delivered bytes to
  `chunk_idle_bytes_sent`.

The reason this section exists: an earlier iteration violated all four of these
in different ways, and **each violation looked like success to the caller** —
HTTP 200, a well-formed stream, a clean `[DONE]`, truncated content. If you
build on this, assert on the stream body, not the status code. A gateway that
fronts an LLM engine is in the business of distinguishing "finished" from
"stopped"; the status line does not carry that information.

## Why a gateway at all

Long-context requests take minutes to prefill. A downstream application with a 30 s
content timeout kills the request and retries it — and every retry restarts a *full*
prefill, which is how one slow request becomes a failure storm. A bare concurrency
counter is blind in exactly this window: the slot is held, the client sees nothing, then
times out. The gateway's job is to make that window observable and bounded
(heartbeat + TTFT budget), to refuse work it cannot serve promptly (admission
back-pressure), and to not pay for the same prefill twice (equivalence dedup).

## Image-placeholder sanitization (G7)

Some clients serialize a past-turn image as the engine's image special token written out
as **literal text**. An engine that validates input against those tokens rejects the
whole body with a hard `400` — and the conversation is dead, because the image bytes were
never in the request and cannot be restored.

The gateway rewrites the literal token to the plain text `[图像]` and lets the request
through. This is a **degradation bridge, not a repair**: the model then sees placeholder
text, and the fix that actually matters is on the client side (send images as `image_url`
content blocks / multimodal items). The sanitizer:

- applies to `POST /v1/chat/completions` and `POST /v1/responses` only, and runs **before**
  `enable_thinking` injection and before the dedup key, so dedup keys are computed on the
  sanitized body and stay stable;
- is **fail-open** — any body it cannot pass through a JSON round-trip safely (lone
  surrogate, pathological nesting depth) is forwarded **verbatim**, so the upstream
  produces the real 4xx instead of the gateway producing a 500;
- is **deterministic** and zero-write on the fast path: bodies without the ASCII substring
  `deepseek_image` (present in both raw-UTF-8 and `ensure_ascii` form) are returned
  byte-identical, never re-serialized;
- is observable — `image_placeholders_sanitized` (replacements) and
  `image_sanitize_requests` (requests, counted only when a rewrite actually happened) in
  `/gw/metrics`;
- has a kill switch: `SANITIZE_IMAGE_PLACEHOLDER=0` bypasses it entirely. Turn it off once
  the clients in your fleet no longer need it.

## Lineage and equivalence to the running service

This directory is a **publication copy**: comments and the module docstring are rewritten
for publication; the code is not.

| published in | `VERSION` string in the file | md5 (published file) | lines | corresponding deployment file |
|---|---|---|---|---|
| commit `92631ea` (v0.2.3 notes) | `concurrency-proxy-v2.0` | `dc4da4225cb04a4109988c0396b3aa1d` | 613 | pre-release snapshot, md5 `0606e1e24926d535e6f5dfdcc6fb57d3`, 649 lines |
| commit `aed15ce` (0.2.8 notes) | `concurrency-proxy-v2-rc3.7.1` | `705b746725c78b7f5e12ee0f5f199350` | 722 | rc3.7.1 as deployed, md5 `299332c1aaac5d38e7d0deb054b6869f`, 754 lines |
| this tree | `concurrency-proxy-v2-rc3.8.2` | `1ef114669a973f520652d8541b6e92da` | 777 | the file the fleet runs, md5 `e1a011627b4a0aa485a32d9da1f633da`, 821 lines |

Equivalence for the last row: `ast.dump()` of the two files is **byte-identical**
once docstrings are excluded — comments are not in the AST at all, and **not even
the version string or the log lines had to be normalized**. The md5s therefore
differ (publication rewrote the prose) while the programs do not. The same holds
for the rc3.7.1 row.

> **Between rc3.7.1 and rc3.8.2 — what actually changed at runtime.** Three
> rounds, all in the failure paths, none on the happy path:
>
> | round | change | why |
> |---|---|---|
> | rc3.8 | chunk-idle expiry now logs `rx`/`tx`/elapsed and adds a cumulative `chunk_idle_bytes_sent`; the idle timeout default moved 180 → 600 s; error frames gained an OpenAI `chat.completion.chunk` skeleton | a stalled stream and an unattributable client-side failure were indistinguishable |
> | rc3.8.1 | frame enqueue never raises (full queue drops + counts instead of throwing into the pump loop); heartbeats excluded from the delivered-byte count; skeleton frames gained `created`/`model` | a full queue turned into a *silent* truncation, and strict parsers rejected the skeleton |
> | rc3.8.2 | a mid-flight upstream read failure now emits an error frame | it previously ended the stream with a clean `[DONE]` after partial content |
>
> The operational lesson worth carrying: **a 200 status with a well-formed
> `[DONE]` is not evidence the answer completed.** Every one of these bugs
> presented to the client as a *successful* HTTP response. If you front an
> engine yourself, assert on the stream body — presence and shape of the error
> frame — not on the status code.
>
> **On the idle-timeout default:** the rc3.8 change (180 → 600 s) lives in the
> source default. A systemd `Environment=CHUNK_IDLE_TIMEOUT=180` line overrides
> it silently — `Environment=` wins over the code default, and `systemctl show`
> will keep reporting the unit's value. Check the *effective* value with
> `systemctl show -p Environment <unit>` **and** `/proc/<pid>/environ`, not the
> source you read.

### Iteration labels retained on purpose

Two `rc3.*` tokens survive in `concurrency_proxy_v2.py`: the `VERSION` constant
(`concurrency-proxy-v2-rc3.8.2`) and the sanitizer's warning line. They are kept
**verbatim** so that a reader can match this source against a live service (the
same strings appear in the startup banner and in every sanitizer warning in the
service journal). Every other change-history label from the development line was
removed.

The sanitizer warning line carries `rc3.7.1` while `VERSION` says `rc3.8.2` —
that is not a publication artifact; the deployed file has the same mismatch. The
sanitizer has not changed since rc3.7.1, so the line records the iteration that
introduced it. Read it as "the sanitizer was last touched in rc3.7.1", not as the
service's version. Grep `VERSION` (or the startup banner) when you need the
latter.

The `concurrency-proxy-v2.0` string in the first row was a publication-time invention — it
corresponded to no string in any running service. Retaining the service's own label
instead makes the source → banner → journal → report chain checkable end to end.

## Running the tests

```bash
python3 gateway/test_sanitize_image_placeholders.py                    # the file next to it
python3 gateway/test_sanitize_image_placeholders.py path/to/copy.py    # any other copy
```

The module is imported, never started, so no engine is needed. The tests pin the exact
placeholder code points (written as `\uXXXX` escapes so an editor cannot silently
normalize them) and cover the two fail-open regressions: a lone surrogate and 2000-level
nesting must both come back byte-identical.

## Reference deployment

Install path and unit values in `concurrency-proxy-v2.service.example` are *examples*: the
reference fleet installs the script at a project-specific path under `/opt` and supplies
`GW_API_KEY` from the unit's environment. Note that `systemctl show -p Environment` is
world-readable on a default systemd configuration — put the key in `EnvironmentFile=`
(mode 0600) rather than an inline `Environment=` if that matters to you.
