# -*- coding: utf-8 -*-
"""overlay が「engine が黙って無視する primitive+param」を使っていないことの回帰ガード
— 2026-07-24。

背景 (2026-07-24 の bug): overlay が `search` primitive に `source:"trash"` を書いても、
engine の `search` は me.deck のみ探索し source を読まない → トラッシュ回収が不発になる。
これは engine のバグではなく overlay の primitive 選択ミスで、 `search_from_trash` に
差し替えれば直る (= optcg-effect-bugfix ルーティンの担当領域)。

この guard は `scripts/overlay_primitive_swap.py` の RULES (機械修正の登録アンチパターン) を
使って overlay を走査し、 未修正のアンチパターンが 1 件でもあれば FAIL する。
→ 新しいカードが誤 primitive で追加されても full-suite が赤くなり、 gate が捕捉、
   ルーティンが `overlay_primitive_swap.py --apply` で自動 self-heal できる。

新パターンを RULES に足せば、 このガードが自動でその class もカバーする (single source of truth)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from overlay_primitive_swap import scan_overlay  # noqa: E402


def test_overlay_has_no_engine_ignored_primitives():
    """overlay に engine が無視する primitive+param が残っていない (= 全て自動修正済み)。"""
    hits = scan_overlay()   # data=None → ファイルをロードして検査のみ (書き込まない)
    if hits:
        lines = [f"  {cid}: {name} @ {path}"
                 for cid, ch in sorted(hits.items()) for path, name in ch]
        raise AssertionError(
            "overlay に engine が無視する primitive+param が残存 "
            f"({sum(len(v) for v in hits.values())} 箇所)。 "
            "`.venv/bin/python scripts/overlay_primitive_swap.py --apply` で機械修正できる:\n"
            + "\n".join(lines)
        )
