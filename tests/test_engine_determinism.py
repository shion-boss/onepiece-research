# -*- coding: utf-8 -*-
"""Engine 決定論 + 差分同期ハーネスの回帰ガード (2026-07-29、 Rust engine 土台)。

canonical state serializer (engine/state_snapshot) + iid reset (engine/core.reset_iid) が
「同一 seed → 同一 canonical digest 列」を保つことを守る。 これが崩れると Rust engine の
ground truth が非決定論になり差分テストが成立しなくなる。
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine_diff_trace import record_trace, compare_traces  # noqa: E402


@pytest.mark.parametrize("deck_a,deck_b,seed", [
    ("cardrush_1385", "cardrush_1385", 1),
    ("cardrush_1454", "tcgportal_calgara", 7),
    ("cardrush_1385", "cardrush_1454", 42),
])
def test_python_engine_deterministic(deck_a, deck_b, seed):
    """同一 seed で 2 run が bit 一致 (canonical digest 列が完全一致) = 決定論。"""
    t1 = record_trace(deck_a, deck_b, seed)
    t2 = record_trace(deck_a, deck_b, seed)
    div = compare_traces(t1, t2)
    assert div is None, f"{deck_a} vs {deck_b} seed={seed}: step {div} で非決定論的乖離"
    # 意味のあるゲームが再生されている (自明な空 trace でない)
    assert t1["n_steps"] >= 5


def test_iid_reset_makes_snapshots_reproducible():
    """iid reset 前後で同一 seed の初期 digest が一致 (グローバル offset を除去)。"""
    from engine.state_snapshot import state_digest
    from engine.core import reset_iid
    import random
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.game import setup_game, play_until_main
    import json

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def dl(s):
        return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), repo)

    digs = []
    for _ in range(2):
        reset_iid()
        st = setup_game(dl("cardrush_1385"), dl("cardrush_1385"),
                        rng=random.Random(3), first_player=0, effects_overlay=ov)
        play_until_main(st)
        digs.append(state_digest(st))
    assert digs[0] == digs[1], "iid reset 後も初期状態 digest が不一致 = serializer に非決定論漏れ"


def test_rust_engine_import_smoke():
    """Rust engine (optcg_engine) が import でき疎通する。 未 build 環境では skip。"""
    try:
        eng = importlib.import_module("optcg_engine")
    except ImportError:
        pytest.skip("optcg_engine 未 build (rust_engine で maturin develop)")
    assert "optcg_engine" in eng.version()


def test_rust_state_model_fidelity():
    """R1: Rust 状態モデル (全147field) が Python engine と同じ canonical digest を出す。
    = Rust の状態表現が忠実。 未 build 環境では skip。"""
    try:
        eng = importlib.import_module("optcg_engine")
    except ImportError:
        pytest.skip("optcg_engine 未 build")
    import json
    import random
    from engine.core import reset_iid
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.game import setup_game, play_until_main, apply_action
    from engine.ai import GreedyAI
    from engine.state_snapshot import state_digest, full_dump

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def dl(s):
        return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), repo)

    for seed, nacts in [(1, 0), (1, 8), (7, 15), (1, 30)]:
        reset_iid()
        st = setup_game(dl("cardrush_1385"), dl("cardrush_1385"),
                        rng=random.Random(seed), first_player=0, effects_overlay=ov)
        play_until_main(st)
        ais = [GreedyAI(rng=random.Random(seed * 3 + 1)), GreedyAI(rng=random.Random(seed * 5 + 2))]
        for _ in range(nacts):
            if st.game_over:
                break
            a = ais[st.turn_player_idx].choose_action(st)
            if a is None:
                break
            apply_action(st, a)
        d_py = state_digest(st)
        d_rust = eng.canonical_digest(json.dumps(full_dump(st)))
        assert d_py == d_rust, f"seed={seed} nacts={nacts}: Rust 状態 digest 不一致 (py={d_py} rust={d_rust})"


def test_rust_apply_don_fidelity():
    """R2: Rust apply_action (AttachDon) が Python と同じ digest を出す。 未 build 環境では skip。"""
    try:
        eng = importlib.import_module("optcg_engine")
    except ImportError:
        pytest.skip("optcg_engine 未 build")
    import json
    import random
    from engine.core import reset_iid
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.game import setup_game, play_until_main, apply_action, AttachDonToLeader, EndPhase
    from engine.ai import GreedyAI
    from engine.plan_search import fast_clone
    from engine.state_snapshot import state_digest, full_dump

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def dl(s):
        return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), repo)

    reset_iid()
    st = setup_game(dl("cardrush_1385"), dl("cardrush_1385"),
                    rng=random.Random(1), first_player=0, effects_overlay=ov)
    play_until_main(st)
    ais = [GreedyAI(rng=random.Random(4)), GreedyAI(rng=random.Random(7))]
    checked_don = 0
    checked_end = 0
    for _ in range(40):
        if st.game_over:
            break
        me = st.players[st.turn_player_idx]
        if me.don_active > 0:
            c = fast_clone(st)
            apply_action(c, AttachDonToLeader(1))
            d_rust = eng.apply_action_digest(
                json.dumps(full_dump(st)), json.dumps({"t": "AttachDonToLeader", "n": 1}))
            assert state_digest(c) == d_rust, "AttachDonToLeader digest 不一致"
            checked_don += 1
        # EndPhase (phase 機械 = untap/draw/don/turn切替) の fidelity
        ce = fast_clone(st)
        apply_action(ce, EndPhase())
        if ce.pending_choice is None:
            d_rust_e = eng.apply_action_digest(
                json.dumps(full_dump(st)), json.dumps({"t": "EndPhase"}))
            assert state_digest(ce) == d_rust_e, "EndPhase digest 不一致 (phase 機械)"
            checked_end += 1
        a = ais[st.turn_player_idx].choose_action(st)
        if a is None:
            break
        apply_action(st, a)
    assert checked_don >= 3 and checked_end >= 5


def test_rust_apply_playcharacter_fidelity():
    """R2: Rust apply_action(PlayCharacter) 機構が Python と一致 (静的効果なしデッキ cardrush_1548 で
    効果なしキャラ登場は 100% 一致)。 ⚠ 静的効果は R3 (evaluate_static_effects) で埋める。"""
    try:
        eng = importlib.import_module("optcg_engine")
    except ImportError:
        pytest.skip("optcg_engine 未 build")
    import json
    import random
    from engine.core import reset_iid, Category
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.game import setup_game, play_until_main, apply_action, PlayCharacter
    from engine.ai import GreedyAI
    from engine.plan_search import fast_clone
    from engine.state_snapshot import state_digest, full_dump

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def dl(s):
        return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), repo)

    def has_onplay(cid):
        b = ov.get(cid)
        return b is not None and any(e.get("when") == "on_play" for e in b.effects)

    reset_iid()
    st = setup_game(dl("cardrush_1548"), dl("cardrush_1548"),
                    rng=random.Random(3), first_player=0, effects_overlay=ov)
    play_until_main(st)
    ais = [GreedyAI(rng=random.Random(10)), GreedyAI(rng=random.Random(11))]
    checked = 0
    for _ in range(40):
        if st.game_over:
            break
        me = st.players[st.turn_player_idx]
        for hi, card in enumerate(me.hand):
            if card.category != Category.CHARACTER or len(me.characters) >= 5 or has_onplay(card.card_id):
                continue
            if me.don_active < max(0, card.cost - me.play_cost_reduction):
                continue
            c = fast_clone(st)
            apply_action(c, PlayCharacter(hand_idx=hi, sacrifice_iid=None))
            if c.pending_choice is not None:
                continue
            d_rust = eng.apply_action_digest(
                json.dumps(full_dump(st)), json.dumps({"t": "PlayCharacter", "hand_idx": hi}))
            assert state_digest(c) == d_rust, f"PlayCharacter({card.card_id}) digest 不一致 (機構)"
            checked += 1
        a = ais[st.turn_player_idx].choose_action(st)
        if a is None:
            break
        apply_action(st, a)
    assert checked >= 8
