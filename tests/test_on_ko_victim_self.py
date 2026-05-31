# -*- coding: utf-8 -*-
"""「このキャラ自身が KO された時」 効果が on_ko で正しく発火する regression。

[[project_16deck_inline_audit_done]] 横展開で発見: 15 entry が on_self_chara_ko +
victim_iid_eq_self (= engine 未handled condition) で「自身の KO」 を表現していたが、
victim は trigger_on_self_chara_ko (= 場 broadcast) の前に場から除去されるため
**一度も発火しない dead 状態**だった。 正しい trigger は on_ko (= KO された本人の reaction、
trigger_on_ko が victim card_id で発火) なので on_ko へ変換/統合した。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import load_effect_overlay, resolve_triggers, trigger_on_ko

ROOT = Path(__file__).resolve().parent.parent


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _ko_during(cid, turn_idx):
    repo = _repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 10
    p2.deck = [repo.get("OP01-013")] * 10
    p1.life = [repo.get("OP01-013")] * 2
    victim = InPlay.of(repo.get(cid), sickness=False)
    p1.characters = [victim]
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_idx
    life0 = len(p1.life)
    # 公式 KO sequence: 場から除去 → trigger_on_ko
    p1.characters.remove(victim)
    p1.trash.append(victim.card)
    trigger_on_ko(st, p1, p2, victim.card, overlay, by_opp_effect=True)
    resolve_triggers(st)
    return life0, len(p1.life)


def test_op12_119_kuma_on_ko_fires_during_opp_turn():
    """OP12-119 くま 【相手のターン中】【KO時】: 相手ターン中の自KOで デッキ上→ライフ が発火。"""
    life0, life1 = _ko_during("OP12-119", turn_idx=1)  # opp turn
    assert life1 == life0 + 1, "相手ターン中の自KO で put_top_to_life が発火するべき (旧 dead bug)"


def test_op12_119_kuma_on_ko_gated_by_opp_turn():
    """自分のターン中の KO では opp_turn 条件で発火しない。"""
    life0, life1 = _ko_during("OP12-119", turn_idx=0)  # own turn
    assert life1 == life0, "自ターン中の自KO は opp_turn 条件で発火しないべき"


def test_no_victim_iid_eq_self_remains():
    """overlay に victim_iid_eq_self (engine 未handled = silently-ignored) が残っていない。"""
    import json
    eff = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    s = json.dumps(eff, ensure_ascii=False)
    assert "victim_iid_eq_self" not in s, "victim_iid_eq_self が残存 (on_ko へ移行すべき)"
