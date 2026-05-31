# -*- coding: utf-8 -*-
"""overlay に engine 未読の「dead gate」 自作キーが混入していないことを保証する invariant。

[[project_16deck_inline_audit_done]] の DB-wide sweep で、 entry-level の条件節を
engine が読まないキー名で書いてしまう bug を複数発見した:
- `condition` (singular): engine は `if` / `conditions` のみ評価 (eval_all_conditions)。
  `condition` は silently-ignored → gate が効かず効果が無条件発火する。
- `_if_clause` / `_chain` / `_condition`: 自作の conditional 表現。 engine は dispatch しない
  ので do-item として dead (= 効果が無条件 or 一度も発火しない)。

これらは eval_condition 単体テストでは masked される (= 条件ロジック自体は正しく動くため)。
overlay の key 名レベルで静的に弾くことで、 「修正したつもりで dead gate」 の再発を防ぐ。
正しい entry-gate は `if` (単一 dict) もしくは `conditions` (dict の list)。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# engine が entry-level gate として読まない = 使ってはいけないキー。
_DEAD_ENTRY_GATE_KEYS = {"condition"}
# do-item / entry に紛れ込ませてはいけない自作 conditional マーカー。
_DEAD_INLINE_KEYS = {"_if_clause", "_chain", "_condition"}


def _load():
    return json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))


def test_no_singular_condition_entry_gate():
    """entry に `condition` (singular) が無い (= `if`/`conditions` を使うべき)。"""
    eff = _load()
    offenders = []
    for cid, entries in eff.items():
        for e in entries or []:
            if isinstance(e, dict) and any(k in e for k in _DEAD_ENTRY_GATE_KEYS):
                offenders.append(cid)
    assert not offenders, (
        f"`condition` (singular, engine 未読) を使う overlay: {sorted(set(offenders))} "
        f"→ `if` に直すこと"
    )


def test_no_dead_inline_conditional_keys():
    """do-item に `_if_clause`/`_chain`/`_condition` 等の自作 dead キーが無い。"""
    eff = _load()
    offenders = []
    for cid, entries in eff.items():
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            for d in e.get("do", []) or []:
                if isinstance(d, dict) and any(k in d for k in _DEAD_INLINE_KEYS):
                    offenders.append(cid)
    assert not offenders, (
        f"engine 未 dispatch の自作 conditional キーを含む overlay: {sorted(set(offenders))} "
        f"→ entry 分離 + `if` gate に直すこと"
    )
