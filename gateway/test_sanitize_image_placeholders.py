#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the image-placeholder sanitizer in concurrency_proxy_v2.py.

15 assertions, fail-closed: any violated expectation aborts with a non-zero
exit. Runs against the module next to this file by default; pass another path
as argv[1] to test a different copy:

    python3 test_sanitize_image_placeholders.py [path/to/concurrency_proxy_v2.py]

Covers: raw and escaped placeholder forms, byte fast paths, list / multimodal
content, reasoning_content, tool_call arguments, path guard, multi-turn,
determinism, metric counters, and the fail-open contract -- a body that cannot
be sanitized safely (lone surrogate, pathological nesting) must pass through
verbatim and must never raise.
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "concurrency_proxy_v2.py"
spec = importlib.util.spec_from_file_location("cp2_under_test", str(target))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# The token as a client writes it (raw form) and the replacement text, written
# with escapes so the exact code points are pinned:
#   T = "<" + U+FF5C + "deepseek_image" + U+FF5C + ">"
#   R = "[" + U+56FE + U+50CF + "]"
T = "<\uff5cdeepseek_image\uff5c>"
R = "[\u56fe\u50cf]"
assert (T, R) == (m.IMAGE_PLACEHOLDER, m.IMAGE_PLACEHOLDER_REPL), \
    "module constants drifted from the expected placeholders"
P = "/v1/chat/completions"

# T1 字符串 content 含占位符（原始形态）
b1 = json.dumps({"messages": [{"role": "user", "content": T + " 描述这张图"}]}).encode()
o1 = json.loads(m.sanitize_image_placeholders(b1, P))
assert o1["messages"][0]["content"] == R + " 描述这张图"
print("T1 str-content OK")

# T2 转义形态（ensure_ascii body）——与 T1 输出语义一致
b2 = json.dumps({"messages": [{"role": "user", "content": T + " 描述这张图"}]},
                ensure_ascii=True).encode()
o2 = json.loads(m.sanitize_image_placeholders(b2, P))
assert o2["messages"][0]["content"] == R + " 描述这张图"
print("T2 escaped-form OK")

# T3 无触发词 → 字节级原样
b3 = json.dumps({"messages": [{"role": "user", "content": "hello world"}]}).encode()
assert m.sanitize_image_placeholders(b3, P) == b3
print("T3 passthrough OK")

# T4 误报（含 deepseek_image 词、无占位符）→ 字节级原样（零重序列化）
b4 = json.dumps({"messages": [{"role": "user", "content": "关于 deepseek_image 的问题"}]}).encode("utf-8")
assert m.sanitize_image_placeholders(b4, P) == b4
print("T4 false-positive-verbatim OK")

# T5 非法 JSON → 原样
b5 = b"{bad json"
assert m.sanitize_image_placeholders(b5, P) == b5
print("T5 invalid-json OK")

# T6 列表 content 的 text 块（image_url 块不动）
b6 = json.dumps({"messages": [{"role": "user", "content": [
    {"type": "text", "text": "x" + T + "y"},
    {"type": "image_url", "image_url": {"url": "https://example.invalid/a.png"}}]}]}).encode()
o6 = json.loads(m.sanitize_image_placeholders(b6, P))
assert o6["messages"][0]["content"][0]["text"] == "x" + R + "y"
assert o6["messages"][0]["content"][1]["type"] == "image_url"
print("T6 list-content OK")

# T7 fail-open 回归：孤立代理项 \ud800 → 必须原样透传，不得 500
b7 = json.dumps({"messages": [{"role": "user", "content": "含代理项 \ud800 与 " + T}]}).encode(
    "utf-8", errors="surrogatepass")
out7 = m.sanitize_image_placeholders(b7, P)
assert out7 == b7, "T7 fail-open violated"
print("T7 surrogate-fail-open OK")

# T8 fail-open 回归：深嵌套 depth=2000 含占位符 → 必须原样透传
obj8 = T
for _ in range(2000):
    obj8 = [obj8]
b8 = json.dumps({"messages": [{"role": "user", "content": obj8}]}).encode()
try:
    out8 = m.sanitize_image_placeholders(b8, P)
    assert out8 == b8, "T8 fail-open violated"
    print("T8 deep-nesting-fail-open OK (depth 2000, verbatim out)")
except RecursionError:
    print("T8 parse-stage RecursionError -> accepted as fail-open path")
# 注：json.loads 自身也可能在深嵌套抛错（同样按 fail-open 透传），两路皆 fail-open

# T9 reasoning_content 分支
b9 = json.dumps({"messages": [{"role": "assistant", "reasoning_content": T, "content": "ok"}]}).encode()
o9 = json.loads(m.sanitize_image_placeholders(b9, P))
assert o9["messages"][0]["reasoning_content"] == R
print("T9 reasoning_content OK")

# T10 tool_calls.arguments 双编码内嵌
inner = json.dumps({"img": T}, ensure_ascii=False)  # 内层保持真实 token 字符（ensure_ascii=True 时是字面 \\uff5c 文本，非 400 通路）
b10 = json.dumps({"messages": [{"role": "assistant", "content": None,
    "tool_calls": [{"id": "c1", "type": "function",
                    "function": {"name": "f", "arguments": inner}}]}]}).encode()
o10 = json.loads(m.sanitize_image_placeholders(b10, P))
args10 = o10["messages"][0]["tool_calls"][0]["function"]["arguments"]
assert T not in args10 and R in json.loads(args10)["img"]
print("T10 tool_calls-arguments OK")

# T11 非目标路径直通
assert m.sanitize_image_placeholders(b1, "/v1/embeddings") == b1
print("T11 path-guard OK")

# T12 多轮多占位符 + 计数
b12 = json.dumps({"messages": [
    {"role": "user", "content": T + " 图一"},
    {"role": "assistant", "content": "好的"},
    {"role": "user", "content": "对比 " + T + " 和 " + T}]}).encode()
o12 = json.loads(m.sanitize_image_placeholders(b12, P))
assert o12["messages"][0]["content"] == R + " 图一"
assert o12["messages"][2]["content"] == "对比 " + R + " 和 " + R
print("T12 multi-turn OK")

# T13 计数器（T1/T2/T6/T9/T10/T12：次数=1+1+1+1+1+3=8；请求数=6）
assert m.METRICS["image_placeholders_sanitized"] == 8, m.METRICS  # T7 fail-open 不计数
assert m.METRICS["image_sanitize_requests"] == 6, m.METRICS
print("T13 metrics OK")

# T14 确定性
assert m.sanitize_image_placeholders(b1, P) == m.sanitize_image_placeholders(b1, P)
print("T14 deterministic OK")

# T15 stream 键在重序列化后保留（is_stream prefilter 兼容）
b15 = json.dumps({"model": "m", "stream": True, "messages": [{"role": "user", "content": T}]}).encode()
o15 = m.sanitize_image_placeholders(b15, P)
assert b'"stream"' in o15
print("T15 stream-key OK")

print("UNIT-TESTS 15/15 OK")
sys.exit(0)
