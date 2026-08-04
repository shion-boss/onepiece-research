# -*- coding: utf-8 -*-
"""Rust engine を **Python をオラクルにせず** 検証する層の恒久ガード。

差分ハーネス (`tests/test_rust_parity.py`) は 「Python が正」 を前提にしているので、
**両エンジンが同じ間違いをしている領域は原理的に検出できない**。 実際 2026-08-04 に
そのクラスのバグが 2 件見つかった:

  - OP03-043: 公式 「トラッシュに置く」 を overlay が `self_ko` (KO) にしていた
    → 公式テキストとの突合で発覚
  - `face_up_life_count` がライフ減少時に正規化されず、 ライフ 0 で表向き 1 が残っていた
    → **保存則チェック (INV-face-up-life)** で発覚

ここでは Python 非依存の 2 軸を CI で回す:
  1. 座席入替対称性 (metamorphic) — 席を入れ替えても同じことが起きるか
  2. 保存則 / 絶対条件 — カード集合・ドン総数・場の上限・表向きライフ枚数
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_seat_swap_symmetry():
    """盤面の 2 人を入れ替えても結果が鏡像になる (= player index の取り違えが無い)。

    ⚠ この検査が 「空」 でないことは mutation で確認済み: `owner_idx` の remap を 1 つ
      落とすと 30 件の非対称を検出する。
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rust_seat_symmetry.py"),
         "--synthetic", "12", "--games", "1", "--assert"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=1800,
    )
    assert r.returncode == 0, (
        "座席を入れ替えると結果が変わる = どちらかの席でしか通らない経路がある。\n"
        f"{r.stdout}\n{r.stderr}"
    )


def test_invariants_hold_in_selfplay():
    """Rust 単独 self-play で保存則違反が 0 (Python を一切参照しない検証)。"""
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rust_fullsweep.py"), "--limit", "12"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=1800,
    )
    assert r.returncode == 0, f"fullsweep が異常終了:\n{r.stdout}\n{r.stderr}"
    out = json.loads((ROOT / "db" / "rust_selfplay" / "fullsweep.json").read_text(encoding="utf-8"))
    viol = out["coverage"]["invariant_violations"]
    assert not viol, (
        "保存則違反 = 言語非依存の絶対条件が破れている (Python 一致より強い誤り):\n"
        f"{json.dumps(viol, ensure_ascii=False, indent=1)}"
    )
    bail = sum(v["bail"] for v in out["coverage"]["actions"].values())
    assert bail == 0, f"Rust が action を再現できず bail した: {out['coverage']['bail_reasons']}"


def test_sonogo_order_matches_official_text():
    """overlay の `do` 順が 公式テキストの 「その後、」 と一致している。

    順序が効くのは 前段が盤面を変えて後段の対象が変わる / 前段のトリガーが先に走る /
    人間 modal の提示順 が変わるため。 2026-08-04 に 19 件の逆順を是正した。
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_sonogo_order.py"), "--assert"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    assert r.returncode == 0, (
        "公式テキストの 「その後、」 と overlay の do 順が食い違っている:\n"
        f"{r.stdout}\n{r.stderr}"
    )


def test_target_scope_matches_official_wording():
    """公式が 「相手の」 と書いていない 「キャラ1枚まで」 を overlay が片側限定にしていない。

    修飾なし = **両陣営** (自分のキャラ / 発動元自身も選べる) が公式。 複数弾の Q&A で
    繰り返し明示された一般則で、 間違えると選択肢が丸ごと消える。 overlay は Python/Rust
    共通なので **差分検証では原理的に沈黙する** クラス (2026-08-04 に 46 枚を是正)。
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_target_scope.py"), "--assert"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    assert r.returncode == 0, (
        "公式テキストの対象範囲と overlay の spec が食い違っている:\n"
        f"{r.stdout}\n{r.stderr}"
    )
