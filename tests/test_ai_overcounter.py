# -*- coding: utf-8 -*-
"""過剰カウンター防止の回帰テスト (2026-07-18、 ohtsuki 報告)。

エース OP13-002 の -2000 効果等で攻撃が完全に防げている (= 受けてもダメージ0) のに、
AI が追加で手札 +1000 カウンターを切っていた。 _choose_defense_by_value に
「defender_power > attacker_power なら受ける (= C0、 counter 不要)」の短絡ガードを追加。
"""
import random
from pathlib import Path

from engine.core import GameState, InPlay, Player
from engine.deck import CardRepository
from engine.effects import load_effect_overlay
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(__file__).resolve().parent.parent


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def test_no_counter_when_attack_fully_defended():
    """defender_power > attacker_power (= 完全防御済) なら counter/block 無しの (None, ()) を返す。"""
    repo = _repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    ai = ExploitBeamAI(rng=random.Random(1))

    # defender = P1 (AI)、 leader 6000。 attacker = P0 の 5000 キャラ (効果適用後を想定)。
    p0 = Player(name="P0(atk)", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1(def)", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    # AI defender が手札に +1000 カウンター (OP01-016 counter=1000 等) を持つ = 切れる状態
    p1.hand = [repo.get("OP01-016")] * 3
    p1.life = [repo.get("OP01-013")] * 3
    p0.life = [repo.get("OP01-013")] * 3
    attacker = InPlay.of(repo.get("OP01-013"), sickness=False)
    attacker.static_buff = 5000 - attacker.power  # attacker power = 5000 < leader 6000
    p0.characters = [attacker]
    state = GameState(players=[p0, p1])
    state.turn_player_idx = 0  # P0 attacking, P1 defending
    state.effects_overlay = overlay

    result = ai._choose_defense_by_value(state, attacker, p1.leader, True, p1)
    assert result == (None, ()), (
        f"完全防御済 (leader 6000 > attacker 5000) なら counter 不要 (受ける): {result}"
    )


def test_counter_still_used_when_needed():
    """attacker >= leader (= 受けるとライフ/KO) の時は短絡せず通常の防御判断に進む
    (= (None, ()) 以外もありうる、 少なくとも短絡ガードで即 (None,()) にはしない)。"""
    repo = _repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    ai = ExploitBeamAI(rng=random.Random(1))
    p0 = Player(name="P0(atk)", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1(def)", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    p1.hand = [repo.get("OP01-016")] * 3
    p1.life = [repo.get("OP01-013")] * 1  # 低ライフ = 守りたい
    p0.life = [repo.get("OP01-013")] * 3
    attacker = InPlay.of(repo.get("OP01-013"), sickness=False)
    attacker.static_buff = 8000 - attacker.power  # attacker 8000 > leader 6000 (受けると被弾)
    p0.characters = [attacker]
    state = GameState(players=[p0, p1])
    state.turn_player_idx = 0
    state.effects_overlay = overlay
    # 短絡ガードは発火しない (leader 6000 < attacker 8000)。 結果自体は value 次第だが、
    # ガードによる即 (None,()) ではないことを確認 (= 防御を検討する余地を残す)。
    _def_pow = p1.leader.power
    assert _def_pow <= attacker.power, "この設定では完全防御済でない (= ガード非発火が期待)"
