# -*- coding: utf-8 -*-
"""バックフィルテスト自身の品質ガード。

新しく書かれる `tests/test_backfill_auto_*.py` が **overlay を読んで overlay を assert
しているだけ** (= overlay が公式テキストと違っていても green になる自作自演) にならないよう、
静的に見張る。 分類ロジックは `scripts/audit_test_circularity.py` に集約。

⚠ このガードが 「循環でない」 と判定するのは、 テストが engine の 状態 / 判断 / legal 列挙
   のいずれかに触れている場合。 overlay の JSON を直接 assert してよいのは
   **overlay-faithfulness guard** (= 公式の条件節/パラメータが落ちていないかを見る、
   CLAUDE.md 「条件節は省略しない」 の自動チェック) だけで、 その場合は関数名を
   `*_gate` / `*_structure` / `*_overlay_shape` / `*_in_overlay` 等にすること
   (= scripts 側の FAITHFULNESS_NAME にマッチさせ、 意図を名前で明示する)。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_circular_backfill_tests():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_test_circularity.py"), "--assert"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    assert r.returncode == 0, (
        "overlay の JSON だけを assert しているテストがある。\n"
        "  engine を動かして状態差分を assert するか、 意図的な faithfulness guard なら\n"
        "  関数名を *_gate / *_structure / *_overlay_shape 等にして意図を明示すること。\n"
        f"{r.stdout}\n{r.stderr}"
    )
