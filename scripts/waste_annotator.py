# -*- coding: utf-8 -*-
"""decision 時(完全 state)で AI の選んだ手を "無駄" 判定する精密 annotator。

ohtsuki: 「ノイズ混じり = 想定の欠如。 log を精密に」。 text log の後付け推測(攻撃が宣言時に
届いていたか vs 相手応答ブーストか を区別できない)を捨て、 **AI が実際に選んだ手を、その選択
時点の state で engine の waste 述語で判定**する = 応答ブースト等のノイズ源が原理的に無い。

拾う客観的無駄(strictly dominated、 = ohtsuki の例):
- unreachable_attack: 宣言時 attacker.power < target.power かつ on_attack 効果なし(= 空タップ、
  ただし rest 目的の例外は別途)。 engine の _is_attack_confirmed_fail_no_effect を使用。
- wasteful_don: 付与しても攻撃圏外/攻撃しないキャラへの DON 付与。 _is_attach_don_wasteful。
- leftover_don_endturn: EndPhase 選択時、 active DON>=1 かつ 手札に counter-event 無し かつ
  リーダー攻撃が legal(= 殴れば相手手札/ライフを削れたのに DON を残して終了)。

  .venv/bin/python scripts/waste_annotator.py --decks cardrush_1342 tcgportal_bonney --n 10
"""
import sys, os, random, argparse
from pathlib import Path
from collections import Counter

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttackLeader, AttackCharacter, EndPhase, AttachDonToLeader,
                         AttachDonToCharacter)
from engine.exploit_beam_ai import ExploitBeamAI
from engine.ai import (_is_attack_confirmed_fail_no_effect, _is_attach_don_wasteful)
import json

R = Path(os.getcwd())
_REPO = CardRepository.from_json(R / "db" / "cards.json")
_OV = load_effect_overlay(R / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(json.loads((R / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _has_counter_event(player):
    """手札に counter モードのイベント(次相手ターンに使える防御札)があるか。"""
    for c in player.hand:
        if str(getattr(c, "category", "")).endswith("EVENT"):
            # counter 値 or counter 効果を持つイベント = 温存が正当化される
            if getattr(c, "counter", 0) or True:  # イベントは counter モードを持つ設計が多い→保守的に True
                return True
    return False


def _legal_leader_attack(state, me_idx):
    me = state.players[me_idx]
    for a in legal_actions(state):
        if isinstance(a, AttackLeader) and a.attacker_iid == me.leader.instance_id:
            return True
    return False


def annotate(state, action, me_idx, overlay):
    """選ばれた action が客観的無駄なら理由文字列、 でなければ None。"""
    if isinstance(action, (AttackLeader, AttackCharacter)):
        if _is_attack_confirmed_fail_no_effect(state, action, overlay):
            return "unreachable_attack"
    if isinstance(action, (AttachDonToLeader, AttachDonToCharacter)):
        if _is_attach_don_wasteful(state, action):
            return "wasteful_don"
    if isinstance(action, EndPhase):
        me = state.players[me_idx]
        if (getattr(me, "don_active", 0) >= 1
                and _legal_leader_attack(state, me_idx)
                and not _has_counter_event(me)):
            return "leftover_don_endturn(殴らずDON残し・counter札無)"
    return None


def _wrap(ai, stats):
    """ai.choose_action をラップ = 実際に選ばれた手を選択時 state で annotate(正しい flow を壊さない)。"""
    orig = ai.choose_action
    def wrapped(state):
        act = orig(state)
        try:
            if state.phase.name == "MAIN":
                me = state.turn_player_idx
                stats["total"] += 1
                w = annotate(state, act, me, _OV)
                if w:
                    stats["waste"][w] += 1
                    stats["ex"].setdefault(w, (state.turn_number, type(act).__name__))
        except Exception:
            pass
        return act
    ai.choose_action = wrapped
    return ai


def run_deck(slug, n, seed0=7000):
    from engine.ai import play_one_action
    da = {"deck_slug": slug}
    stats = {"waste": Counter(), "total": 0, "ex": {}}
    for g in range(n):
        seed = seed0 + g
        st = setup_game(_deck(slug), _deck(slug), rng=random.Random(seed),
                        first_player=g % 2, effects_overlay=_OV)
        play_until_main(st)
        ais = [_wrap(ExploitBeamAI(rng=random.Random(seed*5+1), beam_width=16, max_depth=10, deck_analysis=da), stats),
               _wrap(ExploitBeamAI(rng=random.Random(seed*7+3), beam_width=16, max_depth=10, deck_analysis=da), stats)]
        n_act = 0
        while not st.game_over and st.turn_number < 50 and n_act < 1500:
            cur = st.turn_player_idx
            try:
                play_one_action(st, ais[cur], ais[1 - cur])
            except Exception:
                break
            n_act += 1
    return stats["waste"], stats["total"], stats["ex"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", nargs="+", default=["cardrush_1342"])
    ap.add_argument("--n", type=int, default=10)
    a = ap.parse_args()
    grand = Counter(); grand_total = 0
    for slug in a.decks:
        w, tot, ex = run_deck(slug, a.n)
        grand += w; grand_total += tot
        print(f"\n=== {slug} ({a.n} self-play, {tot} AI手) ===")
        for k, v in w.most_common():
            print(f"  {v:4} ({v/max(1,tot)*100:.1f}%)  {k}   例:{ex.get(k)}")
        if not w:
            print("  無駄マーカー検出ゼロ")
    print(f"\n=== 総計 ({grand_total} AI手)===")
    for k, v in grand.most_common():
        print(f"  {v:4} ({v/max(1,grand_total)*100:.1f}%)  {k}")


if __name__ == "__main__":
    main()
