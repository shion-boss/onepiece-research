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


def test_rust_selfplay_meta_pool_no_bail():
    """メタデッキ self-play で Rust が bail しない (= 実デッキを最後まで正しく回せる) ことの gate。

    差分ハーネスが見ない「Rust 単独で完走できるか」を守る。 Python 側の変更で Rust が追従できなく
    なると bail (= 明示降参) が増えるので、 0 を維持することで追従漏れを検出する。
    ⚠ 実行時間を抑えるため少数ゲーム。 広域は scripts/rust_fullsweep.py / meta 広域 sweep で。
    """
    import json
    import random

    import optcg_engine as eng

    from scripts.rust_parity_check import _load, deck_value

    _load()  # overlay 読み込み (未 load だと全効果 no-op で false negative になる)
    pool = ["cardrush_1342", "cardrush_1454", "pros02_enel"]
    pool = [s for s in pool if _deck_exists(s)]
    if len(pool) < 2:
        pytest.skip("メタデッキが見つからない")

    eng.reset_coverage_stats(True)
    for g in range(12):
        seed = 4242 + g
        a = pool[seed % len(pool)]
        b = pool[(seed // len(pool) + 1) % len(pool)]
        if a == b:
            b = pool[(seed + 1) % len(pool)]
        rng_state = json.dumps(list(random.Random(seed).getstate()[1]))
        try:
            eng.self_play(
                deck_value(a), deck_value(b), rng_state, seed % 2,
                "greedy", None, 8, 12, 40, False, 80,
            )
        except BaseException as e:  # noqa: BLE001 - pyo3 panic は Exception でない
            raise AssertionError(f"Rust self-play が異常終了: {type(e).__name__}: {e}") from e

    cv = json.loads(eng.coverage_stats())
    acts = cv.get("actions") or {}
    bail = sum(v["bail"] for v in acts.values())
    total = sum(v["ok"] + v["bail"] for v in acts.values())
    reasons = sorted(
        (cv.get("bail_reasons") or {}).items(), key=lambda kv: -kv[1]
    )[:5]
    assert total > 1000, f"action={total} が異常に少ない (ハーネス破損?)"
    assert bail == 0, (
        f"Rust self-play bail={bail}/{total} (Python 追従漏れ)。 上位理由: {reasons}"
    )
    inv = cv.get("invariant_violations") or {}
    assert not inv, f"保存則違反: {dict(list(inv.items())[:5])}"


def _deck_exists(slug: str) -> bool:
    import pathlib as _pl

    return (_pl.Path(__file__).resolve().parents[1] / "decks" / f"{slug}.json").exists()


def test_rust_parity_activate_main_cost_ko_trigger_order():
    """発動コスト由来の【KO時】は本体解決後 (cardqa_op_14 / OP14-080) — Rust も bit 一致か。

    16 デッキ差分ではこの局面 (自KOコスト + 【KO時】持ちの弾 + 反応する場) が毎回出るとは
    限らないので、 盤面を直接組んで両エンジンに同じ ActivateMain を適用し digest を比べる。
    ⚠ Rust が 「解決順が違うのに黙って進む」 と MISMATCH、 未実装なら Err (= bail) になる。
    """
    import json
    import random

    import optcg_engine as eng

    import scripts.rust_parity_check as P
    from engine.core import GameState, InPlay, Phase, Player, reset_iid
    from engine.effects import list_activate_main_effects
    from engine.game import ActivateMain, apply_action
    from engine.state_snapshot import full_dump, state_digest

    repo, ov = P._load()
    reset_iid()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP14-080"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 25
        p.life = [repo.get("OP01-013")] * 3
    p0.characters = [InPlay.of(repo.get("OP14-110"), sickness=False)]  # 【KO時】trash→登場
    p0.trash = [repo.get("OP14-102")]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 9

    cands = list_activate_main_effects(st, p0, ov)
    assert cands, "OP14-080 の起動メインが候補に出ていない (前提崩れ)"
    src, eff = cands[0]
    eff_index = next(i for i, e in enumerate(ov[src.card.card_id].effects) if e is eff)
    dump = json.dumps(full_dump(st))
    act = ActivateMain(source_iid=src.instance_id, effect_index=eff_index)
    action = P._enc(st, act)
    assert action["t"] == "ActivateMain", f"action encode 失敗: {action}"

    apply_action(st, act)
    assert st.pending_choice is None
    dr = eng.apply_action_digest(dump, json.dumps(action))   # Err (bail) なら例外 = テスト失敗
    assert dr == state_digest(st), (
        "コスト由来【KO時】の解決順で Python↔Rust が乖離 (cardqa_op_14 / OP14-080)"
    )
