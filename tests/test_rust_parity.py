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


def test_rust_setup_matches_python_including_mulligan():
    """Rust ネイティブ setup (game_start ステージ登場 + マリガン + ownership) が Python setup_game と
    bit 一致することを保証する。

    self-play は Python の setup を通らず Rust 側で試合を組み立てるので、 ここがズレると
    **初手の分布が実戦と違う別ゲーム**を学習してしまう (2026-07-31 まで実際にマリガンが無かった)。
    apply_action の差分検証はこの経路を通らないため、 専用のガードが要る。
    """
    import json
    import random

    import optcg_engine as eng

    import scripts.rust_parity_check as P
    from engine.core import reset_iid
    from engine.game import setup_game
    from engine.state_snapshot import state_digest

    _, ov = P._load()
    pool = ["cardrush_1385", "cardrush_1478", "cardrush_1342", "cardrush_1491",
            "cardrush_1392", "tcgportal_op13_luffy"]  # 1392 = OP13-079 イム (game_start ステージ)
    mismatched = []
    for s in range(12):
        a = pool[s % len(pool)]
        b = pool[(s // len(pool) + 1) % len(pool)]
        if a == b:
            b = pool[(s + 1) % len(pool)]
        fp = s % 2
        reset_iid()
        st = setup_game(P._dl(a), P._dl(b), rng=random.Random(s), first_player=fp,
                        effects_overlay=ov, deck1_analysis=P.deck_analysis(a),
                        deck2_analysis=P.deck_analysis(b))
        rs = json.dumps(list(random.Random(s).getstate()[1]))
        rust = eng.setup_full(P.deck_value(a), P.deck_value(b), rs, fp, False)
        if state_digest(st) != rust:
            mismatched.append((s, a, b, fp))
    assert not mismatched, (
        f"Rust setup が Python setup_game と不一致: {mismatched[:5]}。 "
        f"マリガン判定材料 (deck_value の mulligan_*_card_ids) / game_start ステージ / "
        f"rng 消費順 / ownership flags のいずれかがズレている。"
    )
