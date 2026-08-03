# -*- coding: utf-8 -*-
"""overlay のキーを Python / Rust が **同じように読んでいるか** の恒久ガード。

なぜテストにするか (2026-08-03 の実例):
  overlay に正しく書いてあっても、 エンジン側がそのキーを読んでいなければ効果は出ない。
  しかもこの型は **バックフィルテストでも差分検証でも検出できない**:

  - バックフィルテストは 「overlay の通りに動くか」 を見るので、 overlay が正しく
    エンジンが読んでいない場合は そもそも assert が書かれない。
  - 差分検証 (Python↔Rust bit 一致) は **両エンジンが同じように読んでいない** 場合に
    一致してしまう (= 両方とも同じだけ間違っている)。

  実際に見つかった例:
    OP04-112 ヤマト  `cost_le_self_plus_opp_life` を誰も読まず、 Python は
                     「未知キーは無視」 = **コスト制限なしで任意のキャラを KO**
    OP08-001 チョッパー `max_targets` を誰も読まず、 「3枚まで」 が **全キャラ** にドン付与
    OP02-019 ラクヨウ  Python は `feature`、 Rust は `feature_filter` (overlay に存在しない
                     死にキー) を読んでおり、 特徴フィルタが Rust で効かず全キャラに buff

判定の分類は scripts/scan_engine_key_asymmetry.py に集約している。
このテストは 「両エンジンに無い」 と 「AI 経路に効く非対称」 が 0 であることだけを見る。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_engine_key_asymmetry():
    """overlay のキーを片方のエンジンしか読んでいない / 誰も読んでいない状態が無い。

    新しいキーを overlay に足したら **両エンジンに実装する** か、 実装しないなら
    scan スクリプトの HUMAN_ONLY / RUST_UNIMPLEMENTED_PRIMITIVES / KNOWN_BENIGN の
    いずれかに理由付きで登録する (= 意図的だと明示する)。
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "scan_engine_key_asymmetry.py"), "--assert"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300,
    )
    assert r.returncode == 0, (
        "overlay のキーに エンジン間の非対称 がある。\n"
        "  『両エンジンに無い』 = overlay のキー名誤り か 両方の実装漏れ\n"
        "  『AI 経路に効く非対称』 = 片方だけ実装 (= 効果が片側で不発 or 過剰)\n"
        f"{r.stdout}\n{r.stderr}"
    )
