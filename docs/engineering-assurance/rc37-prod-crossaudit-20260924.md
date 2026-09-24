# `rc3.7.1` production cross-audit (concurrency-proxy-v2 · `:8001`)

- **Auditor**: SRE | **Audit target = `rc3.7.1`**
- **When**: 2026-09-24T05:18–05:21Z (this round). `rc3.7` had been audited 🟢 at
  04:49–04:53Z and was superseded at 05:16:18Z by `rc3.7.1` — the fix release that
  followed the architectural review's P2-A finding. **This report covers `rc3.7.1`.**
- **Object**: head node (`node-01`), `/opt/aicad-prod/scripts/concurrency_proxy_v2.py`
- **Discipline**: read-only throughout (`md5sum` / `wc` / `systemctl show` / `journalctl` /
  `ps` / read-only `curl GET` / `docker logs` / re-running the existing unit tests); inference
  probes capped at `max_tokens≤16`; **no writes, no restart, no kill, no edit to `.env.tp4`,
  no touching the production container configuration**
- **Verdict**: **🟢 production-acceptable** (0 blocking items; 3 non-blocking observations in §7)

---

## 1. Deployment consistency — ✅ all pass

| item | expected | observed | verdict |
|---|---|---|---|
| production script md5 | `299332c1aaac5d38e7d0deb054b6869f` | `299332c1aaac5d38e7d0deb054b6869f` | ✅ |
| line count | 754 | **754** | ✅ |
| backup chain ① | `.bak-rc3.6.1-20260924` = `d9aeaab640f77145583b629939b314be` | present (33,927 B) | ✅ |
| backup chain ② | `.bak-rc3.7-20260924` = `0cae16ca524693a362cab24ccd251c26` | present (37,465 B, mtime 09-24 04:37) | ✅ |
| service state | active | `active / running`, MainPID=**795656**, ExecMainStartTimestamp=**Thu 2026-09-24 05:16:18 UTC** | ✅ |
| startup banner | `rc3.7.1` | `concurrency-proxy-v2-rc3.7.1 0.0.0.0:8001->http://127.0.0.1:8899 conc=16 ttft=600s … dedup=True auth=on` | ✅ |

### P2-A fix in place (source-level check, read with `sed -n`)

```python
try:
    obj = walk(obj)
    if not count:
        return body                  # false positive: zero byte change (fast-path semantics)
    out = json.dumps(obj, ensure_ascii=False).encode("utf-8")
except Exception:
    # P2-A (audit finding): a lone surrogate U+D800 -> UnicodeEncodeError,
    # deep nesting -> RecursionError. Any body that cannot be safely
    # sanitized is forwarded verbatim, restoring the fail-open contract
    # (the upstream then returns the real 4xx instead of a gateway 500).
    return body
# counters and logging report only requests where a rewrite actually completed
METRICS["image_placeholders_sanitized"] += count
METRICS["image_sanitize_requests"] += 1
log.warning("rc3.7.1 sanitized %d image placeholder(s) on %s "
            "(client serialized image as text)", count, path)
```

⇒ All three increments landed: ① the whole walk+encode block inside `try/except`
(fail-open); ② counters moved after a successful encode; ③ the warning carries `path`
plus the new `image_sanitize_requests` key.

## 2. Runtime health — ✅ all pass

- journal since 05:16: **47 lines**; `traceback|exception` = **0**; `ERROR` = **0**.
- process: `pid=795656  RSS=40,736 KB (≈39.8 MB)  %CPU=0.2  ELAPSED=01:45  NLWP=1` ⇒ stable
  under light load.
- real client traffic has resumed: `POST /v1/chat/completions` from a CLI client
  (version 5.6.2) returns **200** (13,874 B).

## 3. End-to-end probes (`max_tokens=16`, key from `state/api-key`, target `127.0.0.1:8001/v1/chat/completions`) — ✅ 6/6

| probe | construction | observed | verdict |
|---|---|---|---|
| (a) literal placeholder | U+FF5C written literally | **http=200** | ✅ |
| (b) ordinary content | no placeholder | **http=200** | ✅ |
| (c) escaped form `\uff5c` | written escaped in the JSON body (body verified to contain the escape) | **http=200** + journal `rc3.7.1 sanitized 1 … on /v1/chat/completions` | ✅ |
| (d) `stream:true` + placeholder | — | **http=200**, `saw_[DONE]=True` | ✅ |
| **(e) lone surrogate U+D800** | body contains `\ud800` + placeholder | **http=400** (**upstream** FastAPI `json_invalid`, not a gateway 500) | ✅ fail-open |
| **(f) 3000-level nesting** | 3000 nested arrays inside a probe field + placeholder (6,182 B) | **http=400** (**upstream** `json_invalid` @offset 1191, not a gateway 500) | ✅ fail-open |

> (e) and (f) are direct verifications of **P2-A**: the gateway no longer returns 500; it
> forwards the unsanitizable body verbatim and lets the upstream produce a real 4xx —
> matching the contract stated in the code comment word for word.

## 4. Regression and rollback — ✅ all pass

| item | observed | verdict |
|---|---|---|
| `/health` | **200** | ✅ |
| `/metrics` (Prometheus scrape endpoint) | **200** | ✅ |
| Prometheus (`node-02`) `GET /metrics` | **200** consecutively (05:19:59 / 05:20:04 / 05:20:09; 82,636–82,657 B) | ✅ |
| kill switch | unit `Environment` does **not** set `SANITIZE_IMAGE_PLACEHOLDER` ⇒ defaults on; setting it to 0 in the script bypasses the layer entirely | ✅ |
| rollback chain | `live(rc3.7.1) ← .bak-rc3.7-20260924(0cae16ca) ← .bak-rc3.6.1-20260924(d9aeaab6)` — both levels present | ✅ |

## 5. `/gw/metrics` (read-only `GET` with `GW_API_KEY`; observation O2 discloses that this key is readable via `systemctl show`)

```json
{"version":"concurrency-proxy-v2-rc3.7.1","uptime_sec":231,"requests_total":83,"streams_total":7,
 "rejected_429_queue":0,"rejected_429_duplicate":0,"first_token_timeouts":0,"chunk_idle_timeouts":0,
 "write_timeouts":0,"stream_total_timeouts":0,"upstream_errors":0,"client_disconnects":0,
 "image_placeholders_sanitized":20,"image_sanitize_requests":17,"internal_retries":0,
 "active_streams":1,"queue_now":0, …}
```

- **new counter key `image_sanitize_requests`=17** ✅; `image_placeholders_sanitized`=20 ✅.
- **Internal self-consistency cross-check**: the journal holds **17** sanitizer warnings
  (15×`1 on /v1/chat/completions` + 1×`1 on /v1/responses` + 1×`4 on /v1/chat/completions`)
  = `image_sanitize_requests` 17 ✅; replacements 15×1+1×1+1×4 = **20** =
  `image_placeholders_sanitized` 20 ✅.
- the two fail-open probes (e)/(f) **are counted nowhere**, confirming the
  "only count completed rewrites" semantics ✅.
- the `/v1/responses` injection point is covered by the sanitizer too (1 warning) ✅.

## 6. Security — ✅ all pass

- the sanitizer warning contains only "count + path + fixed text" — **no request content
  leaked** (all 17 lines over `sort|uniq -c` fall into 3 count shapes). ✅
- after the probes, `traceback|exception|500` count = **0**. ✅
- upstream `:8899` engine over the last 10 minutes: `traceback|error|exception` = **0**;
  normal decode batches (accept rate 0.89, gen 82.02 tok/s) and `GET /metrics 200`; the
  `dsv41-head` container is `Up 16 hours (healthy)`. ✅
- unit tests re-run (the `/tmp` copy, including the T7/T8 fail-open regressions):
  **UNIT-TESTS 15/15 OK** (T11 path-guard / T12 multi-turn / T13 metrics / T14
  deterministic / T15 stream-key). ✅

## 7. Non-blocking observations (3, identical to the `rc3.7` round; none blocks release)

- **O1 (cosmetic)**: the unit's `Description` still says `…8001 -> 127.0.0.1:8002…` while
  the real `UPSTREAM=http://127.0.0.1:8899`. Fix it the next time the unit is edited.
- **O2 (low-severity information exposure)**: `systemctl show -p Environment
  concurrency-proxy-v2` exposes `GW_API_KEY` to any non-root user. Move it to
  `EnvironmentFile=` (mode 0600) or a runtime secret.
- **O3 (terminology)**: `/gw/metrics` returns JSON (the gateway's self-observability) while
  `/metrics` is the Prometheus scrape endpoint; the two are different and should not be
  conflated.

## 8. Read-only declaration

Every command run on `node-01` this round: `md5sum`, `wc -l`, `ls`, `sed`/`grep` (reading
the script), `systemctl is-active/show`, `journalctl`, `ps`, `curl` (GETs plus 6 inference
probes at `max_tokens=16`), `docker logs`, `docker ps`, `python3` on the `/tmp` copy of
the test file (re-running existing tests). **No writes, no restart/kill, no sudo, no edit
to `.env.tp4`, no change to the production container or unit.**

> This report was produced by an AI engineering-assurance team; key decisions should be
> reviewed by a human engineering owner.

---

## Publish note

This file is the **publication copy**. Relative to the internal original, only the
following substitutions were made — **no number, conclusion or causal statement was
altered**:

- internal host name → `node-01` / `node-02` (the repository's published node naming)
- the client product identifier → "a CLI client" (version retained as a diagnostic)

`:8001` / `:8002` / `:8899`, `state/api-key` and `/opt/aicad-prod/…` are **already present
in this repository** and are retained unchanged (published port scheme, published harness
path convention, published project name).

Verified with `python3 scripts/check_redaction.py` (fail-closed, exit code 0). **The
checker was itself injection-verified**: inserting a `/home/<user>/`-style path or an
internal host name into this file makes it report `UNCLASSIFIED BLOCKER-CLASS HITS` and
exit 1; removing it restores 0.