#!/usr/bin/env python3
"""effects.py 内 outer_kind 未付与 _resolve_target call に outer_kind を 一括追加。

各 call は 直近 上 elif k == "XXX" の primitive 名 を outer_kind に、
第 1 引数 (= target_spec 変数) を outer_value に。
"""
from __future__ import annotations
import re
from pathlib import Path

PATH = Path("engine/effects.py")
text = PATH.read_text(encoding="utf-8")
lines = text.split("\n")

new_lines: list[str] = []
i = 0
current_primitive: str = "?"
edits = 0
while i < len(lines):
    line = lines[i]
    m_elif = re.match(r'\s+elif k == "([^"]+)":', line)
    if m_elif:
        current_primitive = m_elif.group(1)
    # _resolve_target( ... ) を 1 行 or 複数行 で 検出
    if (
        "_resolve_target(" in line
        and "def _resolve_target" not in line
    ):
        # call snippet を 取得 (= 行 末 ")" まで 連結)
        snippet_lines = [line]
        if line.count("(") - line.count(")") > 0:
            # multi-line call
            j = i + 1
            while j < len(lines) and "_resolve_target" not in lines[j]:
                snippet_lines.append(lines[j])
                paren = sum(s.count("(") - s.count(")") for s in snippet_lines)
                if paren <= 0:
                    break
                j += 1
            snippet = "\n".join(snippet_lines)
        else:
            snippet = line
        if "outer_kind=" in snippet:
            new_lines.append(line)
            i += 1
            continue
        # single-line replace: _resolve_target(VAR, state, me, opp, self_inplay)
        single_pat = re.compile(
            r"_resolve_target\(\s*([^,()]+),\s*state,\s*me,\s*opp,\s*self_inplay\s*\)"
        )
        m_single = single_pat.search(line)
        if m_single and current_primitive != "?":
            target_var = m_single.group(1).strip()
            replacement = (
                f"_resolve_target({target_var}, state, me, opp, self_inplay, "
                f'outer_kind="{current_primitive}", outer_value={target_var})'
            )
            new_line = line[: m_single.start()] + replacement + line[m_single.end():]
            new_lines.append(new_line)
            edits += 1
            i += 1
            continue
    new_lines.append(line)
    i += 1

PATH.write_text("\n".join(new_lines), encoding="utf-8")
print(f"edits: {edits}")
