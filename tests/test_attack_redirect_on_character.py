# -*- coding: utf-8 -*-
"""キャラへのアタックでも 「アタック対象変更」 が適用される (公式)。

公式 (OP14-060 紫ドフラミンゴ /【相手のアタック時】、 EB01-038): 「**その**アタックの対象を、
選んだカードにする」。 = リーダーへのアタックだけでなく **キャラへのアタック** でも差し替わる。

⚠ 2026-08-24 まで engine は AttackLeader 経路でしか差し替えを実装しておらず、 キャラ戦では
  立った `pending_attack_redirect` を **破棄** していた (2026-08-21 の 「持ち越しバグ」 是正の
  副作用で、 未実装のまま残っていた)。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import load_effect_overlay
from engine.game import AttackCharacter, _recompute_static, apply_action

ROOT = Path(__file__).resolve().parent.parent
FILLER = "OP01-013"


def _setup():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(FILLER)] * 10
        p.life = [repo.get(FILLER)] * 3
        p.life_face_up = [False] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(5),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    return repo, st, p0, p1


def test_redirect_to_other_character_on_character_attack():
    """キャラ A へのアタックを キャラ B に差し替えると、 **B が戦う**。"""
    repo, st, me, opp = _setup()
    attacker = InPlay.of(repo.get("OP01-025"), sickness=False)  # power 5000
    me.characters.append(attacker)
    weak = InPlay.of(repo.get("OP01-016"), sickness=False)      # power 2000 (元の対象)
    strong = InPlay.of(repo.get("OP01-025"), sickness=False)    # power 5000 (差し替え先)
    opp.characters += [weak, strong]
    _recompute_static(st)
    st.pending_attack_redirect = strong.instance_id
    apply_action(st, AttackCharacter(attacker_iid=attacker.instance_id,
                                    target_iid=weak.instance_id))
    ids = [c.instance_id for c in opp.characters]
    assert weak.instance_id in ids, (
        "元の対象 (power 2000) が KO されている = 対象変更が適用されていない")
    # 公式: アタック側の power が **同値以上** なら防御キャラは KO (7-2-1)。
    assert strong.instance_id not in ids, "差し替え先 (5000 vs 5000) が KO されていない"
    assert st.pending_attack_redirect is None, "持ち越してはいけない"


def test_redirect_makes_the_weaker_target_survive():
    """差し替えで **元の対象が生き残る** ことを power 差で確認する。"""
    repo, st, me, opp = _setup()
    attacker = InPlay.of(repo.get("OP01-025"), sickness=False)  # 5000
    me.characters.append(attacker)
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    opp.characters += [a, b]
    _recompute_static(st)
    st.pending_attack_redirect = b.instance_id
    apply_action(st, AttackCharacter(attacker_iid=attacker.instance_id,
                                    target_iid=a.instance_id))
    ids = [c.instance_id for c in opp.characters]
    assert a.instance_id in ids, "差し替えたのに元の対象が KO された"
    assert b.instance_id not in ids, "差し替え先が KO されていない"


def test_redirect_to_leader_takes_life():
    """キャラへのアタックを **リーダー** に差し替えると ライフが減る。

    ⭐ ライフダメージ解決は AttackLeader 経路を再利用する (複製すると
      ダブルアタック/バニッシュ/【トリガー】/人間の受け確認 を二重実装することになる)。
    """
    repo, st, me, opp = _setup()
    attacker = InPlay.of(repo.get("OP01-025"), sickness=False)  # 5000 >= leader power
    me.characters.append(attacker)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters.append(victim)
    _recompute_static(st)
    life_before = len(opp.life)
    st.pending_attack_redirect = opp.leader.instance_id
    apply_action(st, AttackCharacter(attacker_iid=attacker.instance_id,
                                    target_iid=victim.instance_id))
    assert len(opp.life) == life_before - 1, (
        f"リーダーへ差し替えたのにライフが減っていない: {life_before} → {len(opp.life)}")
    assert victim.instance_id in [c.instance_id for c in opp.characters], (
        "リーダーに差し替えたのに元のキャラが KO されている")
    assert st.pending_attack_redirect is None


def test_redirect_target_gone_aborts():
    """差し替え先が既に場にない → バトルは成立しない (黙って元対象を殴らない)。"""
    repo, st, me, opp = _setup()
    attacker = InPlay.of(repo.get("OP01-025"), sickness=False)
    me.characters.append(attacker)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters.append(victim)
    _recompute_static(st)
    st.pending_attack_redirect = 999999  # 存在しない iid
    apply_action(st, AttackCharacter(attacker_iid=attacker.instance_id,
                                    target_iid=victim.instance_id))
    assert victim.instance_id in [c.instance_id for c in opp.characters], (
        "差し替え先が居ないのに元対象を殴っている")
    assert st.pending_attack_redirect is None
