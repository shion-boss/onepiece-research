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


def test_rust_static_effects_idempotent():
    """R3: Rust evaluate_static_effects が Python の静的値を再現 (冪等)。 全 primitive/条件/target が
    既知のデッキ (cardrush_1574) では 100% 一致。 未 build 環境では skip。"""
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

    eng.load_overlay(str((ROOT / "db" / "card_effects.json").resolve()))
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def dl(s):
        return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), repo)

    reset_iid()
    st = setup_game(dl("cardrush_1574"), dl("cardrush_1574"),
                    rng=random.Random(3), first_player=0, effects_overlay=ov)
    play_until_main(st)
    ais = [GreedyAI(rng=random.Random(10)), GreedyAI(rng=random.Random(11))]
    checked = 0
    for _ in range(40):
        if st.game_over:
            break
        d_rust = eng.recompute_static_digest(json.dumps(full_dump(st)))
        assert state_digest(st) == d_rust, "cardrush_1574 静的効果 冪等でない (Rust 再評価が Python と不一致)"
        checked += 1
        a = ais[st.turn_player_idx].choose_action(st)
        if a is None:
            break
        apply_action(st, a)
    assert checked >= 10


def _iid_kind_idx(player, iid):
    if iid == player.leader.instance_id:
        return "leader", 0
    for i, c in enumerate(player.characters):
        if c.instance_id == iid:
            return "char", i
    return None, None


def _encode_attack(state, action):
    """AttackLeader/AttackCharacter を canonical dict (iid → kind/idx) へ。"""
    from engine.game import AttackCharacter
    me, opp = state.turn_player, state.opponent
    ak, ai = _iid_kind_idx(me, action.attacker_iid)
    if ak is None:
        return None
    d = {
        "attacker_kind": ak, "attacker_idx": ai,
        "counter_card_idxs": list(action.counter_card_idxs),
        "counter_event_idxs": list(action.counter_event_idxs),
    }
    if action.blocker_iid is not None:
        bk, bi = _iid_kind_idx(opp, action.blocker_iid)
        d["blocker"] = {"kind": bk, "idx": bi} if bk else None
    else:
        d["blocker"] = None
    if isinstance(action, AttackCharacter):
        tk, ti = _iid_kind_idx(opp, action.target_iid)
        if tk is None:
            return None
        d["t"], d["target_kind"], d["target_idx"] = "AttackCharacter", tk, ti
    else:
        d["t"] = "AttackLeader"
    return d


def _build_defended(state, action, ai_opp):
    """play_one_action の防御注入 (choose_defense → counter/blocker) を再現した最終 action。"""
    from engine.game import AttackLeader, AttackCharacter, _find_attacker_or_none
    me, opp = state.turn_player, state.opponent
    attacker = _find_attacker_or_none(me, action.attacker_iid)
    if attacker is None:
        return None
    is_leader = isinstance(action, AttackLeader)
    target = opp.leader if is_leader else next(
        (c for c in opp.characters if c.instance_id == action.target_iid), None)
    if target is None:
        return None
    block_iid, counters = ai_opp.choose_defense(state, attacker, target, is_leader, opp)
    events, cards = [], []
    for idx in counters:
        if not (0 <= idx < len(opp.hand)):
            continue
        c = opp.hand[idx]
        (events if str(getattr(c, "category", "")).endswith("EVENT") else cards).append(idx)
    kw = dict(attacker_iid=action.attacker_iid, counter_card_idxs=tuple(cards),
              counter_event_idxs=tuple(events), blocker_iid=block_iid)
    return AttackLeader(**kw) if is_leader else AttackCharacter(target_iid=action.target_iid, **kw)


def test_rust_apply_attack_fidelity():
    """R3 戦闘: Rust apply_action(AttackLeader/AttackCharacter) が Python と bit 一致。

    counter card + blocker + KO 判定 + 属性ボーナス + life 移動 の math を検証。 trigger cascade
    (on_attack/opp_attack/counter event/life trigger/KO cascade) を要するケースは Rust が Err で
    bail する = 差分テスト境界 (fidelity 原則)。 入力 state が既に静的効果(R3)で乖離するケースも除外。
    未 build 環境では skip。"""
    try:
        eng = importlib.import_module("optcg_engine")
    except ImportError:
        pytest.skip("optcg_engine 未 build")
    import json
    import random
    from engine.core import reset_iid
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.game import setup_game, play_until_main, apply_action, AttackLeader, AttackCharacter
    from engine.ai import GreedyAI
    from engine.plan_search import fast_clone
    from engine.state_snapshot import state_digest, full_dump

    eng.load_overlay(str((ROOT / "db" / "card_effects.json").resolve()))
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def dl(s):
        return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), repo)

    checked_leader = 0
    checked_char = 0
    for deck_a, deck_b, seed in [
        ("cardrush_1385", "cardrush_1385", 7),
        ("cardrush_1454", "cardrush_1454", 9),
        ("cardrush_1548", "cardrush_1548", 5),
        ("tcgportal_calgara", "cardrush_1385", 11),
    ]:
        reset_iid()
        st = setup_game(dl(deck_a), dl(deck_b), rng=random.Random(seed),
                        first_player=0, effects_overlay=ov)
        play_until_main(st)
        ais = [GreedyAI(rng=random.Random(seed * 3 + 1)), GreedyAI(rng=random.Random(seed * 5 + 2))]
        for _ in range(200):
            if st.game_over:
                break
            mi = st.turn_player_idx
            action = ais[mi].choose_action(st)
            if action is None:
                break
            if isinstance(action, (AttackLeader, AttackCharacter)):
                defended = _build_defended(st, action, ais[1 - mi])
                if defended is not None:
                    enc = _encode_attack(st, defended)
                    if enc is not None:
                        dump = json.dumps(full_dump(st))
                        # 静的効果が既に乖離する入力は combat の責任外 → skip
                        if eng.recompute_static_digest(dump) == state_digest(st):
                            c = fast_clone(st)
                            apply_action(c, defended)
                            if c.pending_choice is None:
                                try:
                                    d_rust = eng.apply_action_digest(dump, json.dumps(enc))
                                except Exception:
                                    d_rust = None  # trigger cascade 要 = Rust bail (境界)
                                if d_rust is not None:
                                    assert state_digest(c) == d_rust, (
                                        f"{enc['t']} digest 不一致 ({deck_a} vs {deck_b} seed={seed}): "
                                        f"{json.dumps(enc, ensure_ascii=False)}")
                                    if enc["t"] == "AttackLeader":
                                        checked_leader += 1
                                    else:
                                        checked_char += 1
                    action = defended
            if not st.game_over:
                apply_action(st, action)
    # counter/blocker/KO を含む戦闘が bit 一致で複数検証されている
    assert checked_leader >= 15, f"AttackLeader 検証数不足: {checked_leader}"
    assert checked_char >= 1, f"AttackCharacter 検証数不足: {checked_char}"


def test_rust_legal_actions_fidelity():
    """R2 self-play 前提: Rust legal_actions が Python legal_actions と完全一致 (canonical 集合)。
    合法手生成は Rust 単独対戦の必須部品。 全 action 種を canonical encode して集合比較。 未 build は skip。"""
    try:
        eng = importlib.import_module("optcg_engine")
    except ImportError:
        pytest.skip("optcg_engine 未 build")
    import json
    import random
    from engine.core import reset_iid
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.game import (
        setup_game, play_until_main, apply_action, legal_actions,
        EndPhase, PlayCharacter, PlayEvent, PlayStage,
        AttachDonToLeader, AttachDonToCharacter, AttackLeader, AttackCharacter, ActivateMain,
    )
    from engine.ai import GreedyAI
    from engine.state_snapshot import full_dump

    eng.load_overlay(str((ROOT / "db" / "card_effects.json").resolve()))
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def dl(s):
        return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), repo)

    def kidx(player, iid):
        if iid == player.leader.instance_id:
            return "leader", 0
        for i, c in enumerate(player.characters):
            if c.instance_id == iid:
                return "char", i
        for i, c in enumerate(player.stages):
            if c.instance_id == iid:
                return "stage", i
        return None, None

    def canon(state, a):
        me, opp = state.turn_player, state.opponent
        if isinstance(a, EndPhase):
            return {"t": "EndPhase"}
        if isinstance(a, PlayCharacter):
            d = {"t": "PlayCharacter", "hand_idx": a.hand_idx}
            if a.sacrifice_iid is not None:
                d["sacrifice_idx"] = kidx(me, a.sacrifice_iid)[1]
            return d
        if isinstance(a, PlayEvent):
            return {"t": "PlayEvent", "hand_idx": a.hand_idx}
        if isinstance(a, PlayStage):
            return {"t": "PlayStage", "hand_idx": a.hand_idx}
        if isinstance(a, AttachDonToLeader):
            return {"t": "AttachDonToLeader", "n": a.n}
        if isinstance(a, AttachDonToCharacter):
            return {"t": "AttachDonToCharacter", "target_idx": kidx(me, a.target_iid)[1], "n": a.n}
        if isinstance(a, AttackLeader):
            k, i = kidx(me, a.attacker_iid)
            return {"t": "AttackLeader", "attacker_kind": k, "attacker_idx": i}
        if isinstance(a, AttackCharacter):
            k, i = kidx(me, a.attacker_iid)
            return {"t": "AttackCharacter", "attacker_kind": k, "attacker_idx": i,
                    "target_idx": kidx(opp, a.target_iid)[1]}
        if isinstance(a, ActivateMain):
            k, i = kidx(me, a.source_iid)
            return {"t": "ActivateMain", "source_kind": k, "source_idx": i, "effect_index": a.effect_index}
        return {"t": "?"}

    def cstr(d):
        return json.dumps(d, sort_keys=True, ensure_ascii=False)

    checked = 0
    for deck_a, deck_b, seed in [
        ("cardrush_1385", "cardrush_1466", 1),
        ("cardrush_1491", "cardrush_1574", 5),
        ("tcgportal_hancock", "pros02_kid_y", 1),
        ("cardrush_1512", "cardrush_1466", 5),
    ]:
        reset_iid()
        st = setup_game(dl(deck_a), dl(deck_b), rng=random.Random(seed),
                        first_player=seed % 2, effects_overlay=ov)
        play_until_main(st)
        ais = [GreedyAI(rng=random.Random(seed * 3 + 1)), GreedyAI(rng=random.Random(seed * 5 + 2))]
        for _ in range(200):
            if st.game_over:
                break
            py = {cstr(canon(st, a)) for a in legal_actions(st)}
            rust = {cstr(d) for d in json.loads(eng.legal_actions_json(json.dumps(full_dump(st))))}
            assert py == rust, (
                f"legal_actions 不一致 ({deck_a} vs {deck_b} seed={seed}): "
                f"PY-only={sorted(py - rust)} RUST-only={sorted(rust - py)}")
            checked += 1
            a = ais[st.turn_player_idx].choose_action(st)
            if a is None:
                break
            apply_action(st, a)
    assert checked >= 40, f"legal_actions 検証数不足: {checked}"
