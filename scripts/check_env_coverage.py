#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_env_coverage.py -- does the launcher actually reach every key in the template?

Why this exists
---------------
An env file and its launcher are two halves of one contract, and nothing in this
repository checked that they were the same generation.  A key can be **correct in the
file and still have no effect**: the launcher never reads it, no log mentions it, no
preflight fires, and the deployed behaviour silently differs from the documented one.
The failure is invisible from both ends -- the file looks right, the process looks
healthy, and the only evidence is a number that is not what you think it is.

This is not hypothetical here.  Two incidents produced this checker's channels:

  * `.env.tp4-600k` carried `DSV41_IDLE_RELEASE=1` as a **top-level** variable.  The
    key is real and the value was correct, but only the `EXTRA_DOCKER_ENV` value is
    forwarded to the container.  The setting did nothing.  (The same class caught
    `SGLANG_DSV4_PAGETABLE_PAGES_GRID` and `SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION`.)
  * An `EXTRA_SGLANG_ARGS` value was swallowed during an SPF arm; the engine came up
    on the default scheduler and every measurement that followed was of the wrong
    configuration.

Both are the same disease: **a value that reaches the file but not the engine.**

The contract this checks
------------------------
For every top-level `KEY=VALUE` in `.env.tp4.example`, `start.sh` must reach it by at
least one of four channels:

  A  the KEY NAME appears in start.sh's **code** (an `-e KEY` list, a `${KEY}` read,
     a whitelist arm).  The launcher knows the key exists.
  B  the KEY is a **sub-key of `EXTRA_DOCKER_ENV`**, whose value is forwarded
     wholesale.  The launcher does not need to know it.
  C  the KEY belongs to a **numbered family** the launcher builds at run time --
     `WORKER_MODEL_DIR_2` is reached as `WORKER_MODEL_DIR_${rank}`.  A whole-word text
     search cannot see this, and reporting these as inert would be a false alarm of
     exactly the kind that teaches people to ignore a checker.
  D  the KEY is listed in `DECLARED_UNUSED` below, with evidence and a reason.

A key in none of the four channels **fails the scan**.  Comments do not count as
channel A: a comment that names a key is the cheapest way to make it look wired up
when it is not, and the launcher will still never read it.

Why channel A ignores comments
------------------------------
Measured, not assumed: start.sh forwards env to the container by an explicit `-e`
list plus the `EXTRA_DOCKER_ENV` value.  There is no `env |`, no `--env-file`, and no
wholesale export -- `grep -c 'env |' start.sh` is 0.  So the only ways a key crosses
the boundary are the four above.

Scanning discipline
-------------------
A checker's lexical model is not the target's syntax.  This one was written against a
hand-verified census and is only trusted because that census agreed with it: 63 keys
by name, 8 by numbered family, 2 declared unused, 2 excluded as channel carriers.
If you change start.sh's env forwarding, re-derive that census before trusting a PASS
-- a checker that has silently stopped matching still prints PASS.

Usage
-----
    python3 scripts/check_env_coverage.py [repo_root]   # default: repo root
    python3 scripts/check_env_coverage.py --selftest    # regression cases only

Exit codes
----------
    0   every template key is reached, or declared
    1   at least one key has no channel -- the scan FAILED
    2   usage / environment error, or the scanner's own self-test failed
"""
import os
import re
import sys

# ---------------------------------------------------------------------------
# Keys present in the template that no launcher in this repository reads.
# Each entry needs evidence, not a shrug: "it is in production" is not evidence
# that anything consumes it.
# ---------------------------------------------------------------------------
DECLARED_UNUSED = {
    "ENG_SH47":
        "Engram shard 47. Written by every .env.tp4* variant including the production "
        ".env.tp4, and read by nothing: `git log -S'ENG_SH' -- start.sh` is empty "
        "across the entire history, so it was never consumed by this launcher, and no "
        "other .sh/.py in the deployment root mentions it either. The same two shards "
        "are mounted by WORKER_EXTRA_MOUNTS_2/3, which IS consumed. Kept in the "
        "template so it stays a faithful record of the production key set.",
    "ENG_SH48":
        "Engram shard 48. Same evidence as ENG_SH47.",
}

# Keys that exist to carry the other channels, or that the template defines for
# humans and other tools.  Never expected to be named in the launcher.
CHANNEL_CARRIERS = {"EXTRA_DOCKER_ENV", "EXTRA_SGLANG_ARGS"}

ENV_REL = ".env.tp4.example"
LAUNCHER_REL = "start.sh"

# `start-tp4.sh` is a 20-line wrapper: it exports ENV_FILE/ENV_EXAMPLE/STATE_DIR/
# LOG_DIR/SERVE_LOG and `exec`s start.sh.  If it ever grows beyond that, this
# check must cover it too -- hence the assertion rather than an assumption.
WRAPPER_REL = "start-tp4.sh"
WRAPPER_MAX_LINES = 40


def parse_env(path):
    """Top-level KEY=VALUE, plus the sub-keys carried by EXTRA_DOCKER_ENV."""
    top, sub = {}, {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    in_ede, ede_tail = False, []
    for raw in lines:
        line = raw.rstrip("\r")
        s = line.strip()
        if in_ede:
            ede_tail.append(s)
            if s.endswith('"'):
                in_ede = False
            continue
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", s)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        top[k] = v
        if k == "EXTRA_DOCKER_ENV":
            body = v.strip()
            if body.startswith('"'):
                body = body[1:]
            if not v.strip().endswith('"') or v.strip() == '"':
                in_ede = True
            for sk in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", body):
                sub[sk] = k
    for s in ede_tail:
        for sk in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", s):
            sub[sk] = "EXTRA_DOCKER_ENV"
    return top, sub


def split_code_comments(text):
    """(code, comments).  A `#` starts a comment only at a token boundary; `#`
    inside a word or a URL is not one.  Erring toward code is the safe direction:
    it can hide an inert key, never invent one."""
    code, comments = [], []
    for line in text.split("\n"):
        cut = None
        for m in re.finditer(r"#", line):
            before = line[:m.start()]
            if before and (before[-1].isalnum() or before[-1] in "_$}{/-"):
                continue
            cut = m.start()
            break
        if cut is None:
            code.append(line)
        else:
            code.append(line[:cut])
            comments.append(line[cut:])
    return "\n".join(code), "\n".join(comments)


def numbered_family_stem(key):
    """`WORKER_MODEL_DIR_2` -> `WORKER_MODEL_DIR_`; `PEER_HCA_RANK1` -> `PEER_HCA_RANK`.
    Returns None when the key has no trailing number."""
    m = re.match(r"^(.*?)(_?)(\d+)$", key)
    if not m:
        return None
    stem = m.group(1) + m.group(2)
    return stem if stem and len(stem) > 2 else None


def classify(top, sub, code, comments):
    by_name, by_family, by_ede, comment_only, inert = [], [], [], [], []
    for k in sorted(top):
        if k in CHANNEL_CARRIERS:
            continue
        if re.search(r"\b%s\b" % re.escape(k), code):
            by_name.append(k)
            continue
        stem = numbered_family_stem(k)
        if stem is not None and ((stem + "${") in code or (stem + "$(") in code):
            by_family.append(k)
            continue
        if k in sub:
            by_ede.append(k)
            continue
        if re.search(r"\b%s\b" % re.escape(k), comments):
            comment_only.append(k)
            continue
        inert.append(k)
    return by_name, by_family, by_ede, comment_only, inert


def _analyse(root):
    env = os.path.join(root, ENV_REL)
    launcher = os.path.join(root, LAUNCHER_REL)
    for p in (env, launcher):
        if not os.path.exists(p):
            raise SystemExit("missing %s" % p)
    top, sub = parse_env(env)
    with open(launcher, "r", encoding="utf-8", errors="replace") as f:
        code, comments = split_code_comments(f.read())
    return top, sub, code, comments


def selftest():
    """Regression cases.  Each one is a shape that a plausible-but-wrong checker
    gets wrong -- the false positives matter as much as the misses, because a
    checker that cries wolf is a checker people learn to skip."""
    fails = []
    # All three numbered families of the real file are present in the fixture.
    # Leaving one out is how this selftest first failed: the stem function was
    # right and the fixture was short, and a fixture that under-represents the
    # target tests the fixture, not the checker.
    code, comments = split_code_comments(
        'x=1  # WORKER_MODEL_DIR_9 mentioned in prose only\n'
        'url="https://example.invalid/a#b"   # trailing note\n'
        '_ov="WORKER_MODEL_DIR_${rank}"\n'
        '_ph="PEER_HCA_RANK${rank}"\n'
        '_ev="WORKER_EXTRA_MOUNTS_${rank}"\n'
        'case " A B " in *" $_k "*) ;; esac\n')

    # comment-only mention must NOT count as code
    if re.search(r"\bWORKER_MODEL_DIR_9\b", code):
        fails.append("comment-only key leaked into code text")
    if not re.search(r"\bWORKER_MODEL_DIR_9\b", comments):
        fails.append("comment text not captured")
    # a `#` inside a quoted URL must not truncate the line
    if "example.invalid/a#b" not in code:
        fails.append("'#' inside a quoted string was treated as a comment")
    # numbered families must resolve
    for k, want in (("WORKER_MODEL_DIR_2", "WORKER_MODEL_DIR_"),
                    ("PEER_HCA_RANK1", "PEER_HCA_RANK"),
                    ("WORKER_EXTRA_MOUNTS_3", "WORKER_EXTRA_MOUNTS_")):
        got = numbered_family_stem(k)
        if got != want:
            fails.append("stem(%s) = %r, want %r" % (k, got, want))
        if got and not ((got + "${") in code or (got + "$(") in code):
            fails.append("family stem %r did not resolve against code" % got)
    # a non-numbered key must NOT acquire a family stem
    if numbered_family_stem("EXTRA_SGLANG_ARGS") is not None:
        fails.append("non-numbered key got a family stem")
    # the family rule must not fire for a stem that is absent from the code
    if (numbered_family_stem("ENG_SH47") or "") and \
       (numbered_family_stem("ENG_SH47") + "${") in code:
        fails.append("ENG_SH47 wrongly resolved as a family")

    for f in fails:
        print("  [FAIL] " + f)
    print("selftest: %d failures" % len(fails))
    return 1 if fails else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    rest = [a for a in argv[1:] if not a.startswith("--")]
    root = rest[0] if rest else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))

    if selftest():
        print("\nFAIL -- the scanner itself is broken; refusing to report on a target.")
        return 2

    wrapper = os.path.join(root, WRAPPER_REL)
    if os.path.exists(wrapper):
        with open(wrapper, "r", encoding="utf-8", errors="replace") as f:
            n = f.read().count("\n") + 1
        if n > WRAPPER_MAX_LINES:
            print("NOTE: %s is now %d lines (expected <= %d) -- this check may need "
                  "to cover it too." % (WRAPPER_REL, n, WRAPPER_MAX_LINES))

    top, sub, code, comments = _analyse(root)
    by_name, by_family, by_ede, comment_only, inert = classify(top, sub, code, comments)

    print("env file : %s   (%d top-level keys, %d EXTRA_DOCKER_ENV sub-keys)"
          % (ENV_REL, len(top), len(sub)))
    print("launcher : %s   (%d lines)" % (LAUNCHER_REL, code.count("\n") + 1))
    print()
    print("  A  named in launcher code        : %d" % len(by_name))
    print("  B  sub-key of EXTRA_DOCKER_ENV   : %d" % len(by_ede))
    print("  C  numbered family, built at run time : %d" % len(by_family))
    print("  D  declared unused               : %d" % len(DECLARED_UNUSED))
    print("  -  channel carriers              : %d" % len(CHANNEL_CARRIERS))
    if by_family:
        print("\n  -- C: reached through a run-time-built name --")
        for k in by_family:
            print("       %-28s via %s${...}" % (k, numbered_family_stem(k)))

    if comment_only:
        print("\nUNCLASSIFIED -- named in a COMMENT only: %d\n" % len(comment_only))
        for k in comment_only:
            print("  %s" % k)
        print("\nFAIL -- a comment is not a channel. Wire it, or declare it.")
        return 1

    unclassified = [k for k in inert if k not in DECLARED_UNUSED]
    if unclassified:
        print("\nUNCLASSIFIED -- no channel reaches this key: %d\n" % len(unclassified))
        for k in unclassified:
            print("  %s" % k)
        print("\nFAIL -- every key above is silently inert at runtime. Wire it, remove")
        print("       it, or add a DECLARED_UNUSED entry with evidence.")
        return 1

    if inert:
        print("\n  -- D: declared unused, with evidence --")
        for k in inert:
            print("       %s" % k)
            print("         %s" % DECLARED_UNUSED[k])

    print("\nPASS -- every template key is reached, or declared.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
