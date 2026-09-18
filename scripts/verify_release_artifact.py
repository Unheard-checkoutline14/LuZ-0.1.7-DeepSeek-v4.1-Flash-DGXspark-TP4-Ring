#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_release_artifact.py — verify the shipped image archive WITHOUT a cluster,
a docker daemon, or a GPU.

    pip install zstandard        # the only dependency
    python verify_release_artifact.py LuZ-0.1.7-DSV41F-image.tar.zst

What it proves, in order:

  1. the tar is a complete, self-consistent content-addressed store
     (every blob member's sha256 == its own filename  => nothing truncated)
  2. the reference graph closes (every blob member is referenced by the DAG)
  3. the *content identity* -- sha256[:16] of the rootfs diffID list, serialized
     exactly as `docker image inspect -f '{{join .RootFS.Layers " "}}'` emits it --
     equals the value `start.sh`'s image_preflight() asserts fleet-wide
  4. every other digest that has ever been published as "the image identity" for
     this build is accounted for as a *different serialization of the same list*
     (or reported as an orphan)

Exit status is 0 only if the content identity matches EXPECTED and every blob
verifies. The pipeline deliberately fails CLOSED: a missing file, a truncated
archive or a blob mismatch is an error, never a plausible-looking hash.

Flags:
    --md5              also compute the file md5 (reads the file twice; ~30 s on
                       14 GB) and compare with --expect-md5 if given
    --expect-md5 HEX   md5 the archive must have
    --json PATH        write the machine-readable audit result
    --blob-manifest PATH   write all tar members with sizes (evidence trail)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
from collections import Counter

try:
    import zstandard
except ImportError:  # pragma: no cover
    sys.stderr.write("missing dependency: pip install zstandard\n")
    raise SystemExit(2)

EXPECTED = "4ebef21b6aedbd70"          # start.sh IMGID_TPL, measured on all 4 nodes
EXPECTED_MD5 = "10307040cd70ab23436bf34eee829d24"
SMALL = 4 << 20

# constants that mean "nothing was there" -- must never be accepted as an identity
FALSE_EMPTY = {
    "e3b0c44298fc1c14": "sha256(b'')",
    "01ba4719c80b6fe9": "sha256(b'\\n')",
}


def h16(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def md5_file(path: str, chunk: int = 1 << 22) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def scan(path: str):
    """Single streaming pass: keep small members, hash every member."""
    members = []
    small = {}
    failures = []
    with open(path, "rb") as fh:
        reader = zstandard.ZstdDecompressor().stream_reader(fh, read_size=1 << 22)
        tf = tarfile.open(fileobj=reader, mode="r|")
        for m in tf:
            members.append((m.name, m.size, m.type))
            if not m.isfile():
                continue
            base = m.name.rsplit("/", 1)[-1]
            is_blob = m.name.startswith("blobs/sha256/") and len(base) == 64
            if m.size < SMALL:
                data = tf.extractfile(m).read()
                small[m.name] = data
                if is_blob and hashlib.sha256(data).hexdigest() != base:
                    failures.append(m.name)
            elif is_blob:
                h = hashlib.sha256()
                src = tf.extractfile(m)
                for blk in iter(lambda: src.read(1 << 22), b""):
                    h.update(blk)
                if h.hexdigest() != base:
                    failures.append(m.name)
    return members, small, failures


def blob(digest: str) -> str:
    return "blobs/sha256/" + digest.split(":", 1)[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--md5", action="store_true")
    ap.add_argument("--expect-md5", default=EXPECTED_MD5)
    ap.add_argument("--json")
    ap.add_argument("--blob-manifest")
    a = ap.parse_args()

    if not os.path.isfile(a.archive):
        sys.stderr.write("FAIL: no such file: %s\n" % a.archive)
        return 1

    size = os.path.getsize(a.archive)
    out = {"archive": os.path.basename(a.archive), "bytes": size}

    print("=" * 74)
    print("FILE")
    print("=" * 74)
    print("  path              :", a.archive)
    print("  bytes             : {:,}".format(size))
    md5 = None
    if a.md5:
        t = time.time()
        md5 = md5_file(a.archive)
        ok = (md5 == a.expect_md5)
        print("  md5               : %s   (%s, %.1fs)"
              % (md5, "MATCH" if ok else "MISMATCH expected " + a.expect_md5, time.time() - t))
        out["md5"] = md5
        out["md5_ok"] = ok
        if not ok:
            sys.stderr.write("FAIL: archive md5 mismatch\n")
            return 1
    print()

    t0 = time.time()
    members, small, failures = scan(a.archive)
    print("=" * 74)
    print("1. INTEGRITY  (single streaming pass, %.1fs)" % (time.time() - t0))
    print("=" * 74)
    blobs = [n for n, s, t in members if n.startswith("blobs/sha256/") and t == tarfile.REGTYPE]
    print("  tar members       : {}".format(len(members)))
    print("  blob members      : {}".format(len(blobs)))
    print("  payload bytes     : {:,}".format(sum(s for n, s, t in members)))
    print("  blob hash failures: {}".format(len(failures)))
    out["tar_members"] = len(members)
    out["blob_members"] = len(blobs)
    out["blob_hash_failures"] = failures
    if failures:
        for n in failures[:10]:
            print("      MISMATCH", n)
        sys.stderr.write("FAIL: blob integrity\n")
        return 1
    print("  => every blob member's sha256 equals its own filename")
    print("     the archive is a self-consistent store; nothing truncated")
    print()

    # ---------------- 2/3. DAG ----------------
    missing = [k for k in ("index.json", "manifest.json") if k not in small]
    if missing:
        sys.stderr.write("FAIL: archive is not a docker-save/OCI layout (missing %s)\n" % missing)
        return 1

    print("=" * 74)
    print("2. REFERENCE GRAPH")
    print("=" * 74)
    idx = json.loads(small["index.json"])
    top = blob(idx["manifests"][0]["digest"])
    nested = json.loads(small[top])
    refs = {top}
    layer_refs = set()
    print("  index.json         : OCI index, %d descriptor(s) -> index blob %s"
          % (len(idx["manifests"]), top.rsplit('/', 1)[-1][:16]))
    kinds = []
    for ent in nested["manifests"]:
        b = blob(ent["digest"])
        if b not in small:
            sys.stderr.write("FAIL: referenced blob absent: %s\n" % b)
            return 1
        man = json.loads(small[b])
        cfg = blob(man["config"]["digest"])
        refs.add(b)
        refs.add(cfg)
        ls = [blob(l["digest"]) for l in man.get("layers", [])]
        layer_refs |= set(ls)
        refs |= set(ls)
        kind = "attestation" if "attestation-manifest" in json.dumps(ent) else "image"
        kinds.append((kind, b, cfg, len(ls), len(set(ls))))
        print("    %-11s manifest %s  layers=%-4d distinct=%-4d config=%s"
              % (kind, b.rsplit('/', 1)[-1][:16], len(ls), len(set(ls)), cfg.rsplit('/', 1)[-1][:16]))
    unreferenced = sorted(b for b in blobs if b not in refs)
    print("  blob members referenced by the DAG : %d / %d" % (len(refs & set(blobs)), len(blobs)))
    print("  unreferenced                       : %d %s" % (len(unreferenced), unreferenced[:3]))
    out["dag"] = [{"kind": k, "manifest": b, "config": c, "layers": n, "distinct": d}
                  for k, b, c, n, d in kinds]
    out["unreferenced_blobs"] = unreferenced
    if unreferenced:
        sys.stderr.write("FAIL: %d blob(s) in the archive are not reachable from index.json\n"
                         % len(unreferenced))
        return 1
    print()

    print("=" * 74)
    print("3. CONTENT IDENTITY")
    print("=" * 74)
    legacy = json.loads(small["manifest.json"])
    cfg_path = legacy[0]["Config"]
    cfg = json.loads(small[cfg_path])
    dids = cfg["rootfs"]["diff_ids"]
    cc = Counter(dids)
    print("  image config blob  : %s (%d bytes, sha256 self-consistent)"
          % (cfg_path.rsplit('/', 1)[-1][:16], len(small[cfg_path])))
    print("  RepoTags           : %s" % legacy[0].get("RepoTags"))
    print("  created            : %s" % cfg.get("created"))
    print("  diffIDs            : %d entries, %d distinct" % (len(dids), len(cc)))
    for k, v in cc.items():
        if v > 1:
            print("      repeated %dx   : %s" % (v, k))
    print()

    J = " ".join(dids)
    L = "\n".join(dids)
    serializations = {
        "space-joined + trailing newline  [AUTHORITATIVE: docker image inspect -f '{{join .RootFS.Layers \" \"}}' | sha256sum]":
            J + "\n",
        "space-joined, no trailing newline": J,
        "newline-joined, no trailing newline": L,
        "newline-joined + trailing newline": L + "\n",
        "newline-joined + two trailing newlines": L + "\n\n",
    }
    print("  every published \"identity\" for this build, against the SAME %d-entry list:" % len(dids))
    print("  %-100s %s" % ("serialization", "sha256[:16]"))
    for k, v in serializations.items():
        val = h16(v.encode())
        tag = ""
        if val == EXPECTED:
            tag = "  <== ACCEPTED (== start.sh IMGID_TPL)"
        elif val in FALSE_EMPTY:
            tag = "  !! FALSE-EMPTY CONSTANT"
        print("  %-100s %s%s" % (k, val, tag))
    print()

    got = h16((J + "\n").encode())
    full = hashlib.sha256((J + "\n").encode()).hexdigest()
    print("  content identity   : %s" % got)
    print("  content identity, full : %s" % full)
    print("  expected           : %s" % EXPECTED)
    out["content_identity"] = got
    out["content_identity_full"] = full
    out["serializations"] = {k: h16(v.encode()) for k, v in serializations.items()}
    out["expected"] = EXPECTED
    out["config_digest"] = cfg_path.rsplit("/", 1)[-1]
    out["oci_index_digest"] = top.rsplit("/", 1)[-1]

    if got in FALSE_EMPTY:
        sys.stderr.write("FAIL: identity is a false-empty constant -- pipeline failed OPEN\n")
        return 1
    if got != EXPECTED:
        sys.stderr.write("FAIL: content identity %s != %s\n" % (got, EXPECTED))
        return 1
    print()
    print("  RESULT: PASS -- this archive is the same content the fleet runs.")
    print()

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print("wrote", a.json)
    if a.blob_manifest:
        with open(a.blob_manifest, "w", encoding="utf-8") as f:
            for n, s, t in sorted(members, key=lambda x: -x[1]):
                f.write("%16d  %s\n" % (s, n))
        print("wrote", a.blob_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
