# -*- coding: utf-8 -*-
"""人間 vs AI 対戦 で 発見 した bug の regression test (= 2026-05-28 ohtsuki さん 報告)。

報告元 log: db/human_play_log/20260528T135048Z_cardrush_1342_vs_cardrush_1342_humanW_0ee2f9cd.json

Bug 1: set_cannot_rest 中 の キャラ が 攻撃 できてしまう (= 攻撃で REST 化 する はずなのに 飛ぶ)。
       公式 OP14-069 option 1 「コスト7以下のキャラ3枚までは、次の相手のエンドフェイズ終了時まで、
       レストにできない」 = 攻撃 (= rest 化) も 不可。 修正 で legal_actions の attacker filter に
       cannot_be_rested_buff check を 追加。

Bug 2: 自陣 optional replace_ko (OP14-061 ヴェルゴ) が 人間 owner に対して 自動発火 した。
       公式 「戻すことができる」 = optional だが overlay 側 marker 無し、 engine 側 も
       human-owner 判定 無し で 強制 発火 → 修正 で `optional: true` overlay marker +
       try_replace_ko で owner=human 時に skip (= TODO: 将来 modal 実装)。
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _make_state(repo, leader_id="OP01-001", overlay=None):
    leader = repo.get(leader_id)
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay or {},
    )


# ============================================================
# Bug 1: cannot_be_rested_buff が attack を ブロック
# ============================================================
def test_cannot_be_rested_blocks_attack_legal_action():
    """legal_actions: cannot_be_rested_buff = True の chara は attack 候補 から 除外。"""
    from engine.game import legal_actions

    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    state.turn_number = 5  # turn>2 で battle 可
    state.phase = Phase.MAIN

    # 攻撃 可能 chara を 2 体 配置
    chara_normal = InPlay.of(repo.get("OP01-013"), sickness=False)
    chara_blocked = InPlay.of(repo.get("OP01-013"), sickness=False)
    # blocked 側 に レスト不能 buff を つける
    chara_blocked.cannot_be_rested_buff = True
    chara_blocked.cannot_be_rested_applier_idx = 1
    chara_blocked.cannot_be_rested_applied_turn = 4
    me.characters = [chara_normal, chara_blocked]
    me.don_active = 5

    actions = legal_actions(state)
    attackers = set()
    for a in actions:
        if hasattr(a, "attacker_iid"):
            attackers.add(a.attacker_iid)

    assert chara_normal.instance_id in attackers, "normal chara は attack 候補に いる"
    assert chara_blocked.instance_id not in attackers, (
        "cannot_be_rested_buff=True の chara は attack 候補 から 除外 されるべき"
    )


def test_cannot_be_rested_blocks_leader_attack():
    """leader にも cannot_be_rested_buff があれば 攻撃 不可。"""
    from engine.game import legal_actions

    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    state.turn_number = 5
    state.phase = Phase.MAIN
    me.leader.cannot_be_rested_buff = True
    me.leader.cannot_be_rested_applier_idx = 1
    me.leader.cannot_be_rested_applied_turn = 4
    me.don_active = 5

    actions = legal_actions(state)
    leader_iid = me.leader.instance_id
    attackers = set(getattr(a, "attacker_iid", None) for a in actions)
    assert leader_iid not in attackers, (
        "leader が cannot_be_rested_buff の時 leader attack 不可"
    )


def test_cannot_be_rested_normal_chara_can_attack():
    """control: cannot_be_rested_buff = False の chara は 通常通り attack 可。"""
    from engine.game import legal_actions

    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    state.turn_number = 5
    state.phase = Phase.MAIN
    chara = InPlay.of(repo.get("OP01-013"), sickness=False)
    chara.cannot_be_rested_buff = False  # explicit
    me.characters = [chara]
    me.don_active = 5

    actions = legal_actions(state)
    attackers = set(getattr(a, "attacker_iid", None) for a in actions)
    assert chara.instance_id in attackers, "通常 chara は attack 候補"


# ============================================================
# Bug 2: optional replace_ko (OP14-061) は 人間 owner で 自動 発火 しない
# ============================================================
def test_op14_061_marked_optional():
    """OP14-061 ヴェルゴ overlay は optional=True で marking されている。"""
    import json

    o = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    for cid in ("OP14-061", "OP14-061_p1"):
        entries = o.get(cid, [])
        replace_entries = [
            e for e in entries
            if isinstance(e, dict) and e.get("when") in ("replace_ko", "replace_leave")
        ]
        assert replace_entries, f"{cid} should have replace_ko entry"
        for e in replace_entries:
            assert e.get("optional") is True, (
                f"{cid} replace_ko must be marked optional=True (公式 「戻すことができる」)"
            )


def test_optional_replace_ko_skipped_when_owner_is_human():
    """optional=True の replace_ko は owner=human で 自動 発火 しない (= 公式 「もよい」)。"""
    from engine.effects import execute_effect

    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]   # AI
    opp = state.players[1]  # 人間
    state.human_player_idx = 1  # opp = 人間

    # opp (= 人間 側) の場 に ヴェルゴ + ドフラ海賊団 chara
    vergo = InPlay.of(repo.get("OP14-061"), sickness=False)
    # ドフラ海賊団 chara: OP04-031 ドフラ (= victim 候補)
    doflamingo = InPlay.of(repo.get("OP04-031"), sickness=False)
    opp.characters = [vergo, doflamingo]
    opp.don_active = 3  # cost (= return_self_don_to_deck 1) 払える 状態
    initial_don_total = opp.don_active + opp.don_rested

    initial_field = len(opp.characters)

    # me (= AI) が KO 効果 で ドフラ を ターゲット
    execute_effect({"ko": "all_opponent_characters"}, state, me, opp, None)

    # 期待 (= bug fix): optional 効果 は 人間 owner では skip → ドフラ は KO される、
    # opp の don は 減らない (= cost 払われていない)
    survivors_iids = [c.instance_id for c in opp.characters]
    assert doflamingo.instance_id not in survivors_iids, (
        "optional replace_ko は 人間 owner では skip → ドフラ は 通常通り KO されるべき"
    )
    assert opp.don_active + opp.don_rested == initial_don_total, (
        "skip された ので cost (return_self_don) は 払われない"
    )


def test_mandatory_replace_ko_still_fires_for_human():
    """control: optional=False (= mandatory) の replace_ko は 人間 owner でも 自動 発火 する。

    既存 replace_ko (= optional flag 無し) の 後方互換 確認。
    OP12-027 コウシロウ は 公式 text 「代わりに〜できる」 (= 「ことができる」 ではない) で
    overlay 上 optional 無し = mandatory。 人間 owner でも 自動発火 OK。

    注意 (= 2026-05-28 audit_overlay_static.py 適用後):
      OP15-003 アルビダ 等 「ことができる」 含む 43 cards は optional: true mark 済 で
      ここでは 不適切。 代わりに OP12-027 (= 既存 test_effects.py:test_replace_ko_other_chara
      と 同 card) を control に 採用。
    """
    import json as _json
    from engine.effects import execute_effect

    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    state.human_player_idx = 1  # opp が 人間

    # OP12-027 は 「自分の 他 の コスト5以下 属性《斬》 chara が KO される 時 代替」 → victim 別途必要
    cards = _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    def _ci(v):
        if v in (None, "", "-"): return 0
        try: return int(str(v).replace(",", ""))
        except ValueError: return 0
    target_cid = next(
        c["card_id"] for c in cards
        if c.get("attribute") == "斬"
        and 1 <= _ci(c.get("cost")) <= 5
        and c.get("category") == "CHARACTER"
        and c["card_id"] != "OP12-027"
    )
    target_card = repo.get(target_cid)
    target_ip = InPlay.of(target_card, sickness=False)
    koushiro_ip = InPlay.of(repo.get("OP12-027"), sickness=False)
    opp.characters = [target_ip, koushiro_ip]

    execute_effect({"ko": "all_opponent_characters"}, state, me, opp, None)

    # 期待: target は 代替 で 生存、 コウシロウ も 生存 (rest 化 する) →
    # 「自分の他」 が KO される 時 protect なので target が 生存 する
    survivors = {c.card.card_id for c in opp.characters}
    assert target_cid in survivors, (
        f"mandatory replace_ko は 人間 owner でも 発火 する はず: target={target_cid} "
        f"survivors={survivors}"
    )
