# Serving-interruption RCA: three image-placeholder `400`s and the sanitizer fix

**Date**: 2026-09-24 | **Executed by**: lead (during a 429 throttling window; no other
reviewer available) | **Nature**: production fix — deployed and re-verified

## TL;DR

A user's sessions were cut short three times (local 11:53:16 / 12:08:49 / 12:23:53 =
UTC 03:53:16 / 04:08:49 / 04:23:53), **all with the same cause**: on follow-up turns the
client (a CLI application, 5.6.2 / 2.147.0, from `<client-host>`) serialized a past-turn
image as **literal text**, and the engine's guard
`encoding_dsv41.py::_validate_no_image_sp_tokens` rejected the body with a hard `400`.
**Engine and container were healthy throughout** (up 14 h+, zero OOM, zero restarts, zero
5xx). The fix is a sanitizing layer in the `:8001` concurrency proxy: the literal token is
rewritten to plain text and the request is admitted. Shadow-verified, A/B'd against the
unfixed path, then switched over atomically; e2e re-verified.

## Timeline (UTC, journald as the authority)

| time | event | evidence layer |
|---|---|---|
| 09-23 12:01–13:47 | full-chain restart window (gateway started 3× 2615/2612/2597; `:8001` up 12:03:04; container up 13:39) | `ps` / `docker inspect` |
| 09-23 13:41–13:42 | `:8001` emitting `502`s to Prometheus `/metrics` (engine still cold) — same source as the `gateway.log` 502 burst | `:8001` journal |
| 09-24 03:53:16 | **400 #1** `upstream rejected 400 … image special token` | `:8001` journal + engine uvicorn 400 |
| 09-24 04:08:49 | **400 #2** same text (immediately after a 29k-token prefill succeeded) | as above |
| 09-24 04:23:53 | **400 #3** same text (the second interruption the user reported) | `:8001` journal |
| 09-24 04:37:49 | sanitizer deployed; the same probe goes `400` → `200` | journal banner + e2e |

## Root-cause chain

1. In this client's serialization of conversation history for this endpoint, images from
   earlier turns degrade into a text placeholder (**the image bytes are already gone**).
2. The VL engine's guard `_validate_no_image_sp_tokens` (`encoding_dsv41.py:594/600`)
   raises `ValueError` → `400` on that placeholder in either `content` or
   `reasoning_content`. **The guard itself is correct** — it exists to stop multimodal
   encoding corruption.
3. The engine log records only `400 Bad Request`, with no error body. The body is visible
   **only** in the `:8001` journal's `upstream rejected 400 body=…` warning — a textbook
   case for cross-layer evidence gathering.

Ruled out: no OOM (`journalctl -k` clean over 24 h); no container restart
(`RestartCount=0`); no RAM-triggered kill (available dipped to 8 GiB but no event);
the `:8899` engine histogram over 24 h was 13,730×200 / 12×400 (10 of them `bench`
`flush_cache`) / 4×401 and **zero 5xx**; every `502` burst and `504` in `gateway.log`
belongs to the 09-23 restart window and none occurred on the incident day.

## The fix (deployed on `:8001`, the single choke point of the chain)

File: `/opt/aicad-prod/scripts/concurrency_proxy_v2.py`
(md5 `d9aeaab6…` → `0cae16ca524693a362cab24ccd251c26`, 738 lines; the final 754-line
`rc3.7.1` is described below):

- new `sanitize_image_placeholders(body, path)`: walks every string value in the JSON,
  rewrites the image placeholder to plain text; **fail-open** (bodies that fail a safe
  JSON round-trip pass through unchanged); **deterministic** (same body → same output);
  runs **before** `maybe_inject` and before `body_key`, so dedup keys are computed on the
  sanitized body;
- the byte fast path keys on the ASCII substring `deepseek_image` — present in both the
  raw-UTF-8 and the `\uXXXX`-escaped body forms. The first version keyed on raw bytes and
  **missed the `ensure_ascii` form; test T1 caught it.** Writing the tests first paid for
  itself immediately;
- covers both `/chat/completions` and `/responses`, and both the `content` and
  `reasoning_content` guard branches; `SANITIZE_IMAGE_PLACEHOLDER=0` reverts it in one
  step; the count lands in `/gw/metrics:image_placeholders_sanitized`;
- backup: `concurrency_proxy_v2.py.bak-rc3.6.1-20260924` (33,927 B).

## Verification matrix (all pass)

| test | result |
|---|---|
| unit tests 9/9 (str / list / reasoning / path guard / counters / determinism / multi-turn / invalid JSON / pass-through) | OK (first version failed T1 → fast path fixed → all pass) |
| shadow instance + placeholder | `200` + sanitizer warning |
| shadow instance, ordinary body | `200` |
| **control**: production `:8001` + placeholder, *before* the switch | `400` — original failure reproduced, which is what attributes the cause |
| production `:8001` + placeholder, *after* the switch | **`200`** |
| production `:8001` ordinary / health / metrics | `200` / `200` / `200` |

## Residuals and recommendations

1. **The image content is not recoverable.** After sanitizing, the model sees placeholder
   text and will answer that it cannot see the image — the bytes were never in the
   interrupted requests. The real fix belongs to the client: send images as `image_url`
   content blocks (or as multimodal items on `/v1/responses`). Affected conversations
   should re-attach the image or start a new one.
2. **The engine guard has no switch, and the engine was not touched** (the frozen release
   baseline stays intact).
3. **Observability**: `/gw/metrics` now exposes `image_placeholders_sanitized`
   (replacements) and `image_sanitize_requests` (requests), which quantify how often this
   client-side serialization defect occurs in the fleet.

## Cross-audit and `rc3.7.1`

Per instruction, the change went through three-way cross-audit (QA + SRE + architect).
The architectural code review (10 replicated local tests, T1–T10) returned
**🟡 conditionally acceptable** and found:

- **🔴 P2-A (mandatory)**: the walk + re-serialize block sat **outside** the `try`, so an
  isolated surrogate item (`U+D800` → `UnicodeEncodeError`) or 2000-level nesting
  (`RecursionError`) would turn the promised fail-open into a **gateway `500`**;
- 🟠 policy-level note: the previous release's only body transformation defaulted to
  *off*, while this sanitizer defaults to *on* — a policy change, so it needs a decision
  record (this document serves as it);
- P3: the warning should carry the path; the metrics should separate request count from
  replacement count;
- confirmed: parse-then-replace covers both forms ✓, the fast path changes nothing on
  false positives ✓, dedup-key ordering ✓, kill switch ✓, `Content-Length` safety ✓.

**`rc3.7.1` fix** (md5 `299332c1aaac5d38e7d0deb054b6869f`, 754 lines, live 05:16:18 UTC):
① the whole walk + re-serialize block wrapped in `try/except Exception: return body`, so
any body that cannot be safely sanitized is forwarded verbatim — the fail-open contract is
restored; ② counters and logging moved *after* a successful rewrite (fail-open give-ups
are not counted); ③ the warning carries `request.path`; ④ new counter key
`image_sanitize_requests`. Backup chain: `.bak-rc3.6.1-20260924` /
`.bak-rc3.7-20260924` / live.

**Unit tests extended to 15/15** (including two regression cases from the review: the lone
surrogate and deep nesting must both fail open; one test had to be corrected — under
`ensure_ascii` the inner placeholder is the literal text `\uff5c`, not the `400` path, so
passing it through is the correct behaviour). e2e re-verification: placeholder → `200`
with a path-carrying sanitizer warning, ordinary / health / metrics all `200`, banner
reads `rc3.7.1`.

**Audit follow-up**: the production-side review is published as
[`rc37-prod-crossaudit-20260924.md`](rc37-prod-crossaudit-20260924.md); the adversarial
verification review is in the same batch. The decision record is served by this section
(context / decision / consequences / rollback / supersession conditions are all present:
once clients are fixed, set `SANITIZE_IMAGE_PLACEHOLDER=0`).

## Execution incident (honesty ledger)

The first deployment run used `pkill -f "concurrency_proxy_v2_rc37.py"`, which **matched
the remote `bash -c` command line carrying the whole script — i.e. itself — and committed
suicide** (SSH exit 255; same failure shape as `taskkill` matching its own console
window). The scene was verified to have zero side effects before redoing the work.
Lesson: a `pkill` pattern inside a remote script must not match that script
(bracket trick, e.g. `rc[37]`).

> This report was produced by an AI engineering-assurance team; key decisions should be
> reviewed by a human engineering owner.

---

## Publish note

This file is the **publication copy**. Relative to the internal original, only the
following substitutions were made — **no number, conclusion or causal statement was
altered**:

- client product identifier → "a CLI application" (versions retained as diagnostics)
- the client host address → `<client-host>`

The two remaining node-ish strings, `:8001` / `:8005` / `:8899` and `/opt/aicad-prod/…`,
are **already present in this repository** and are retained (published port scheme and
published project name). One stale sentence ("the production-side review is in progress")
was replaced with a link to the now-published `rc37-prod-crossaudit-20260924.md`.

Verified with `python3 scripts/check_redaction.py` (fail-closed, exit code 0). **The
checker was itself injection-verified**: inserting a `/home/<user>/`-style path or an
internal host name into this file makes it report `UNCLASSIFIED BLOCKER-CLASS HITS` and
exit 1; removing it restores 0.
