# -*- coding: utf-8 -*-
"""Python↔Rust engine パリティの pytest ガード。

Python engine を変更したら Rust (optcg_engine) が同期崩れしていないかを自動検出する。
不変条件: **MISMATCH=0** (= Rust は「Python と bit 一致」か「Err で明示 bail」の二択のみ)。
bail 数は Rust 未実装の量なので閾値チェックしない (機能追加で増減する)。

Rust 未ビルド時は skip (= optcg_engine import 失敗)。 詳細ツール: scripts/rust_parity_check.py。
"""
import pytest

pytest.importorskip("optcg_engine", reason="Rust engine 未ビルド (maturin develop)")


def test_rust_parity_no_mismatch():
    """小規模 (数ゲーム) の差分で MISMATCH=0 を保証。 Python↔Rust 同期の CI ガード。"""
    from scripts.rust_parity_check import run_parity

    tot, _bail_msgs, mismatch = run_parity(n_games=6)
    assert tot["MISMATCH"] == 0, (
        f"Python↔Rust 同期崩れ: MISMATCH={tot['MISMATCH']} "
        f"(内訳 top: {mismatch.most_common(5)})。 "
        f"Python 変更に Rust (rust_engine/) が追従していない。 "
        f"詳細: python scripts/rust_parity_check.py"
    )
    # サニティ: 実際に action が流れている (match が十分ある)
    assert tot["match"] > 100, f"match={tot['match']} が異常に少ない (ハーネス破損?)"


def test_rust_parity_no_mismatch_broad():
    """全 16 deck × 6 seed (~6000 action) の広域差分で MISMATCH=0 を保証 (~35s)。 default seed だけでは
    通らないカード (life trigger ko / OP08-098 on_attack then_life / conditional set_base_power_timed /
    counter cost pay_don cascade 等) の追従漏れを恒久的に捕捉する。 bail は Rust 未実装量なので閾値なし。"""
    from scripts.rust_parity_check import run_parity

    tot, _bail_msgs, mismatch = run_parity(seeds=(1, 7, 13, 21, 42, 99))
    assert tot["MISMATCH"] == 0, (
        f"Python↔Rust 広域同期崩れ: MISMATCH={tot['MISMATCH']} "
        f"(内訳 top: {mismatch.most_common(5)})。 "
        f"詳細: python scripts/rust_parity_check.py"
    )
    assert tot["match"] > 3000, f"match={tot['match']} が異常に少ない (ハーネス破損?)"
