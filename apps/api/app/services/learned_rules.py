"""The learned-rules block (approved weekly distillations) is capped at 1,200
characters in the prompt. When it is full, the NEWEST rules stay (audit,
2026-11-05): the old `[:1200]` kept the oldest text and silently dropped
every approval after the block filled."""
from __future__ import annotations


def keep_newest(rules: str, cap: int) -> str:
    """The last whole lines of `rules` that fit in `cap` characters."""
    text = (rules or "").strip()
    if len(text) <= cap:
        return text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    kept: list[str] = []
    size = 0
    for ln in reversed(lines):
        add = len(ln) + (1 if kept else 0)
        if size + add > cap:
            break
        kept.append(ln)
        size += add
    if not kept:                      # one rule longer than the cap: keep its head
        return lines[-1][:cap]
    return "\n".join(reversed(kept))
