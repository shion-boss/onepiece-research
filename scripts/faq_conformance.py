# -*- coding: utf-8 -*-
"""公式裁定 (cardqa/FAQ) の **runtime conformance** ハーネス — curated seed (= 2026-06-05)。

⚠ スコープ: db/faq の cardqa は自然言語 Q&A 2,500+ 件で、 各裁定を game scenario へ自動変換
するには NL→シナリオ (LLM/手作業) が要り **全自動化は非現実的**。 overlay レベルの cardqa 整合は
既存 `verify_overlay_vs_cardqa.py` で担保済。 本ハーネスは **中核ルールを手で scenario 化して
engine の挙動を直接アサート** する curated seed。 1 裁定 = 1 関数で追加していく拡張点。

各 check は (公式ルール条文 / cardqa の趣旨, 構築, 期待) を 1 関数にまとめ、 engine の実挙動と
照合する (= 決定論的・false-positive ゼロ、 [[project_human_play_auto_qa]] の原則)。

  python scripts/faq_conformance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import InPlay, Player  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import _matches_filter, load_effect_overlay  # noqa: E402
from engine.game import legal_actions, setup_game, Phase, AttackLeader  # noqa: E402

repo = CardRepository.from_json(ROOT / "db" / "cards.json")
overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))


# --------------------------------------------------------------------------- #
def faq_don_buff_owner_turn_only():
    """公式 6-5-5 + cardqa 頻出: 付与ドン!! の パワー+1000 は **自分のターン中のみ** 有効。
    相手ターン中は +1000 されない。"""
    base = repo.get("OP01-016")  # 任意のキャラ (= 印刷パワー)
    ip = InPlay.of(base, sickness=False)
    ip.attached_dons = 2
    ip.is_owners_turn = True
    p_own = ip.power
    ip.is_owners_turn = False
    p_opp = ip.power
    check("DON+1000 は自ターンのみ (6-5-5)",
          p_own == base.power + 2000 and p_opp == base.power,
          f"自ターン={p_own} (期待 {base.power+2000}) / 相手ターン={p_opp} (期待 {base.power})")


def _advance_to_turn(state, target):
    """EndPhase を適用して target ターンまで進める (= setup は turn1、 turn1 先攻は攻撃不可)。"""
    from engine.game import apply_action, EndPhase, play_until_main
    guard = 0
    while state.turn_number < target and guard < 60:
        guard += 1
        if state.phase == Phase.MAIN:
            apply_action(state, EndPhase())
        else:
            play_until_main(state)
    if state.phase != Phase.MAIN:
        play_until_main(state)


def faq_summoning_sickness_no_attack():
    """公式 5-2 + cardqa: 登場ターンの 非【速攻】キャラは アタックできない (召喚酔い)。
    【速攻】キャラは 登場ターンでも アタックできる。 (= turn3 = 先攻2ターン目で検査、
    turn1 は先攻が一律攻撃不可なので不可)。"""
    a, b = _two_decks()
    state = setup_game(a, b, effects_overlay=overlay)
    _advance_to_turn(state, 3)
    me = state.players[state.turn_player_idx]
    sick = InPlay.of(repo.get("OP01-013"), sickness=True)  # 非速攻の素キャラ
    me.characters.append(sick)
    sick_can = any(isinstance(x, AttackLeader) and x.attacker_iid == sick.instance_id
                   for x in legal_actions(state))
    check("召喚酔い: 非速攻は登場ターン攻撃不可 (5-2)", not sick_can,
          f"turn={state.turn_number} sick attacker が legal に {'居る(NG)' if sick_can else '居ない(OK)'}")
    sick.granted_keywords.add("速攻")
    rush_can = any(isinstance(x, AttackLeader) and x.attacker_iid == sick.instance_id
                   for x in legal_actions(state))
    check("速攻は登場ターン攻撃可 (5-2例外)", rush_can,
          f"turn={state.turn_number} rush attacker が legal に {'居る(OK)' if rush_can else '居ない(NG)'}")


def faq_rested_blocker_cannot_block():
    """公式 10-1-4: 【ブロッカー】は **アクティブ (= レストでない)** な時のみ ブロック可能。
    防御候補ロジック (human_session.choose_defense / AI choose_defense) の
    `is_blocker_now and not rested` を 直接照合。"""
    bc = repo.get("OP11-067")  # シャーロット・カタクリ (= 素ブロッカー)
    active = InPlay.of(bc, sickness=False)
    rested = InPlay.of(bc, sickness=False)
    rested.rested = True
    active_eligible = active.is_blocker_now and not active.rested
    rested_eligible = rested.is_blocker_now and not rested.rested
    check("レストブロッカーはブロック不可 (10-1-4)",
          active_eligible and not rested_eligible,
          f"active 可={active_eligible} / rested 可={rested_eligible} (rested は不可であるべき)")


def faq_exact_cost_filter():
    """cardqa/効果文: 「コスト1の…を登場」 は コスト1 **ぴったり** のみ対象 (≠ コスト以下)。
    (= 2026-06-05 _matches_filter が厳密 cost を無視するバグの回帰)。"""
    filt = {"feature": "B・W", "cost": 1}
    ok = (_matches_filter(repo.get("OP14-083"), filt)        # cost1 → True
          and not _matches_filter(repo.get("OP14-084"), filt)  # cost7 → False
          and not _matches_filter(repo.get("OP14-094"), filt))  # cost5 → False
    check("厳密 cost:N はコストぴったりのみ", ok,
          "OP14-083(c1)=T / OP14-084(c7)=F / OP14-094(c5)=F を期待")


def _two_decks():
    # 任意の2デッキ (= setup_game 用、 内容は不問)
    da = DeckList.from_json(ROOT / "decks" / "cardrush_1342.json", repo)
    db = DeckList.from_json(ROOT / "decks" / "cardrush_1385.json", repo)
    return da, db


CHECKS = [
    faq_don_buff_owner_turn_only,
    faq_summoning_sickness_no_attack,
    faq_rested_blocker_cannot_block,
    faq_exact_cost_filter,
]


def main():
    for fn in CHECKS:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            check(fn.__name__, False, f"例外: {type(e).__name__}: {e} | {traceback.format_exc().splitlines()[-1][:60]}")
    print("=== FAQ runtime conformance (curated seed) ===")
    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        mark = "OK " if ok else "NG "
        print(f"  [{mark}] {name}" + (f"  — {detail}" if (detail and not ok) else ""))
    print(f"\n{n_ok}/{len(RESULTS)} 裁定 conformance pass")
    sys.exit(0 if n_ok == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
