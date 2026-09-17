#!/usr/bin/env python3
"""v6 贪心循环探针 — SGLang 栈上的输出退化判定。

对照系（R8 证据）：
  - 我方 vLLM fork（FI 0.6.18, spec-on/off 均）: 7/7 重复循环
  - tonyd2wild 干净栈: 0/8 循环
判定: 循环率显著为 0 ⇒ 输出退化 bug 不存在于本栈。
"""
import json, sys, time, urllib.request
from collections import Counter

PORT = 8899
KEY = open('<REPO>/state-tp4/api-key').read().strip()

PROBES = [
    ("math-gsm", "A bakery sold 45 croissants in the morning and 37 in the afternoon. "
                 "If each croissant costs $3, how much money did the bakery make in total? "
                 "Think step by step and give the final number."),
    ("counting", "Count the number of times the letter 'r' appears in the word "
                 "'strawberry ripple'. Answer with just the number and a short explanation."),
    ("code", "Write a Python function `def is_palindrome(s: str) -> bool` that ignores "
             "case and non-alphanumeric characters. Include two example calls."),
    ("prose", "Write a paragraph (120+ words) explaining why the sky is blue at noon "
              "but red at sunset."),
    ("reasoning", "Sara has twice as many apples as Miguel. Miguel has 5 more apples "
                  "than Lin. Lin has 12 apples. How many apples do they have in total? "
                  "Show your work."),
    ("algorithm", "Explain the difference between BFS and DFS, and when each is "
                  "preferred. Give one concrete use case for each."),
    ("echo", "What is the capital of France? Describe its most famous landmark in "
             "two sentences."),
]

def loop_score(text: str):
    """返回 (is_loop, 尾部重复单元样本)。4-gram 计数法：尾部 160 词内最高频 4-gram 出现 ≥4 次即循环。"""
    words = text.split()
    tail = words[-160:] if len(words) > 160 else words
    grams = Counter(tuple(tail[i:i+4]) for i in range(len(tail) - 3))
    if not grams:
        return False, ""
    (gram, n), = grams.most_common(1)
    if n >= 4 and len(set(tail)) < len(tail) * 0.72:
        return True, " ".join(gram)
    # 句级循环
    sents = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    stail = sents[-12:]
    (s, sn), = Counter(stail).most_common(1)
    if sn >= 4:
        return True, s[:60]
    return False, ""

def ask(content, max_tokens=420):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
        data=json.dumps({
            "model": "deepseek-v4.1-flash", "temperature": 0, "max_tokens": max_tokens,
            "chat_template_kwargs": {"thinking": False},
            "messages": [{"role": "user", "content": content}],
        }).encode())
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())

loops, results = 0, []
for name, q in PROBES:
    t0 = time.time()
    r = ask(q)
    text = r["choices"][0]["message"]["content"]
    is_loop, unit = loop_score(text)
    loops += is_loop
    usage = r.get("usage", {})
    results.append((name, is_loop, unit, len(text.split()), usage.get("completion_tokens"), round(time.time()-t0, 1)))
    flag = "★LOOP" if is_loop else "clean"
    print(f"[{flag}] {name:9s} len={len(text.split()):4d}w ctok={usage.get('completion_tokens')} {round(time.time()-t0,1)}s 重复单元={unit[:40]!r}")
    print(f"    开头: {text[:110]!r}")

print(f"\n===== 循环率 {loops}/7 =====")
math_ok = "45" in dict((r[0], r) for r in {}).keys() or None
sys.exit(0 if loops <= 1 else 1)
