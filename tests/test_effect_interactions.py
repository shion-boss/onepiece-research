# -*- coding: utf-8 -*-
"""効果 **同士** の相互作用の回帰テスト。

単体テスト (`tests/test_backfill_auto_*.py`) は 1 枚のカードが公式テキストどおり動くかを見る。
このファイルは **複数の効果が噛み合った時のルール解釈** を固定する。
2026-08-04 に Rust↔Python の全カード差分掃引で実際に露見した乖離を、 公式一次情報
(`db/faq/cardqa_*.json`) と Python engine の挙動で固定したもの
([[reference_rust_mismatch_root_cause_taxonomy]])。

ここが崩れると Rust ミラーとの差分検証も同時に崩れる = engine の正しさの土台。
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    resolve_triggers,
    trigger_on_attack,
    trigger_on_play,
)
from engine.game import AttackCharacter, AttackLeader, EndPhase, apply_action, _fire_counter_events

ROOT = Path(__file__).resolve().parent.parent
_FILLER = "OP01-013"


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, overlay, leader0="OP01-001", leader1="OP01-001", human_idx=None):
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader0), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(leader1), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 25
    p1.deck = [repo.get(_FILLER)] * 25
    p0.life = [repo.get(_FILLER)] * 3
    p1.life = [repo.get(_FILLER)] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 9
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


# --------------------------------------------------------------------------- #
#  A. 効果無効 × 【KO時】
#     公式 Q&A (cardqa_op_09 / cardqa_op_10):
#       「効果を無効にされたキャラがKOされた場合、そのキャラの【KO時】効果は発動できますか？」
#       → 「いいえ、できません」
# --------------------------------------------------------------------------- #
def test_negated_character_ko_does_not_fire_on_ko():
    """効果無効を付与されたキャラがバトルで KO されても【KO時】は発動しない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # OP14-093 Mr.4 (power5000) が OP14-100 アブサロム (power5000) を殴って KO する。
    # OP14-100 の【KO時】= 自デッキ上3枚から《スリラーバーク海賊団》1枚を手札へ。
    me.characters = [InPlay.of(repo.get("OP14-093"), sickness=False)]
    victim = InPlay.of(repo.get("OP14-100"), sickness=False)
    victim.granted_keywords.add("効果無効")
    opp.characters = [victim]
    opp.deck = [repo.get(x) for x in ("OP14-104", "OP14-104", "OP14-104")] + opp.deck

    hand_before, deck_before = len(opp.hand), len(opp.deck)
    apply_action(st, AttackCharacter(attacker_iid=me.characters[0].instance_id,
                                     target_iid=victim.instance_id))

    assert victim not in opp.characters, "バトルで KO されていない (前提が崩れている)"
    assert len(opp.hand) == hand_before, "効果無効なのに【KO時】のサーチが走っている"
    assert len(opp.deck) == deck_before, "効果無効なのに【KO時】がデッキを触っている"


def test_non_negated_character_ko_does_fire_on_ko():
    """対照: 無効化されていなければ同じ状況で【KO時】は発動する (テストの妥当性確認)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP14-093"), sickness=False)]
    victim = InPlay.of(repo.get("OP14-100"), sickness=False)
    opp.characters = [victim]
    opp.deck = [repo.get(x) for x in ("OP14-104", "OP14-104", "OP14-104")] + opp.deck

    hand_before = len(opp.hand)
    apply_action(st, AttackCharacter(attacker_iid=me.characters[0].instance_id,
                                     target_iid=victim.instance_id))
    assert len(opp.hand) == hand_before + 1, "【KO時】のサーチが発動していない"


# --------------------------------------------------------------------------- #
#  B. 【アタック時】が対象を除去 → 「空打ち」 (バトルは起きない)
#     ⚠ 対象が消えた後に **後ろのキャラが繰り上がって代わりに殴られてはいけない**。
# --------------------------------------------------------------------------- #
def test_on_attack_removing_target_makes_attack_fizzle():
    """【アタック時】KO が対象自身を除去したら、 バトルは起きず 後続キャラも巻き込まない。

    OP15-036 の【アタック時】= 相手の **レストの** コスト4以下のキャラ1枚までを KO。
    レスト1体 (= アタック対象、 効果の唯一の候補) + アクティブ1体 を並べる。
    効果がアタック対象を KO → バトルは空打ち → **アクティブの方は無傷**。
    ⚠ 位置 index で追っていると、 対象が消えて後ろが繰り上がり
      アクティブの方を殴ってしまう (2026-08-04 に Rust で実際に起きていた)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP13-079_p1", leader1="OP13-100")
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP15-036"), sickness=False)]
    target = InPlay.of(repo.get("OP15-050"), sickness=False)     # cost3、 レスト = 効果の対象
    bystander = InPlay.of(repo.get("OP15-051"), sickness=False)  # cost3、 アクティブ = 対象外
    target.rested = True
    opp.characters = [target, bystander]
    evaluate_static_effects(st, overlay)

    apply_action(st, AttackCharacter(attacker_iid=me.characters[0].instance_id,
                                     target_iid=target.instance_id))

    assert target not in opp.characters, "【アタック時】の KO が効いていない (前提が崩れている)"
    assert bystander in opp.characters, (
        "アタック対象が【アタック時】で消えた後、 繰り上がった別のキャラが殴られている。"
        " 対象は object/一意トークンで追い、 消えたら 空打ち にしなければならない"
    )
    assert opp.chara_ko_taken_this_turn == 1, \
        f"このターンの被 KO 数が 1 でない: {opp.chara_ko_taken_this_turn}"


# --------------------------------------------------------------------------- #
#  C. トリガーの解決タイミング = 「効果の解決中は後回し」
#     Python の trigger_* は enqueue → _maybe_resolve で、 resolving 中は no-op。
#     → **同じ do の後続 primitive は、 カスケードが起きる前の盤面を見る**。
# --------------------------------------------------------------------------- #
def test_don_return_cascade_is_deferred_until_do_completes():
    """ドン返却トリガーは do の途中では解決されない (対象がその場で減らない)。

    OP06-075 の【登場時】= 「ドン‼-1：相手のコスト2以下のキャラ2枚までをレストにする」。
    自分の場に OP06-076 (自分の場のドン‼が戻された時、相手のコスト2以下1枚を KO) がいると、
    ドン返却でカスケードが走る。 ⚠ Python はこれを **後回し** にする。

    相手のコスト2キャラ 3 体 (同一) で:
      - **後回し (正)**: rest_multi が先頭 2 体 (idx0,1) をレスト → その後 KO が idx0 を除去
        → 生存は 「レスト済 idx1」 と 「アクティブ idx2」 = **レスト 1 体**
      - inline 発火 (誤): 先に idx0 が KO → 残り 2 体を rest_multi がレスト
        → 生存 2 体とも レスト = **レスト 2 体**
    レスト数がそのまま 発火タイミングの判別子になる。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP06-080_p1", leader1="OP06-080")
    me, opp = st.players[0], st.players[1]
    me.don_active = 10
    # me の場に トリガー持ち (OP06-076、 自分のターン中・ターン1回)
    me.characters = [InPlay.of(repo.get("OP06-076"), sickness=False)]
    # opp の場に コスト2 のキャラ 3 体
    victims = [InPlay.of(repo.get("OP06-068"), sickness=False) for _ in range(3)]
    opp.characters = list(victims)

    src = InPlay.of(repo.get("OP06-075"), sickness=True)
    me.characters.append(src)
    trigger_on_play(st, me, opp, src, overlay)

    survivors = [c for c in opp.characters]
    assert len(survivors) == 2, \
        f"カスケードの KO が 1 体に効くはず (3→2) だが {len(survivors)} 体残っている"
    rested = sum(1 for c in survivors if c.rested)
    assert rested == 1, (
        f"生存 2 体のうちレストが {rested} 体。 1 体でなければ カスケードが **後回し** に"
        " なっていない (inline 発火だと 先に 1 体 KO されてから 残り 2 体がレストになり 2 体)"
    )


# --------------------------------------------------------------------------- #
#  D. 置換効果 (replace_ko / replace_leave) のコスト手札捨ても 「効果で手札が捨てられた」
#     ⚠ 公式 cardqa_op_12 (2026-08-07 是正):
#       「相手のカードの効果で自分の場の『OP12-053 ボルサリーノ』が場を離れるときに、
#         『ボルサリーノ』の効果で代わりに自分の手札1枚を捨てました。この時、自分のリーダー
#         『OP12-040 クザン』の効果でカードを引くことはできますか？」 → 「はい、できます。」
#     = 置換コストの手札捨ても on_self_hand_discarded を発火し、 hand_discarded_by_effect_this_turn
#       を立てる (選び方=random/worst/filter は 「捨てられた」 事実に無関係)。
#     旧テストは「フラグは立たない」と誤って固定していた (= backfill が engine の当時挙動をそのまま
#     正解にしていた circularity。 外部オラクル=公式 Q&A で初めて誤りと判明)。
# --------------------------------------------------------------------------- #
def test_replace_ko_cost_discard_sets_hand_discarded_flag():
    """KO 置換のコストで手札を捨てたら 「効果で手札を捨てた」 フラグが立つ (公式 cardqa_op_12)。"""
    from engine.effects import try_replace_ko

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # OP15-003 アルビダ: KO されそうな時、 手札のパワー6000以下キャラ1枚を捨てて KO を代替 (filter discard)。
    albida = InPlay.of(repo.get("OP15-003"), sickness=False)
    me.characters = [albida]
    me.hand = [repo.get(_FILLER)]           # power3000 CHARACTER = コストに使える
    hand_before = len(me.hand)

    replaced = try_replace_ko(st, me, opp, albida, overlay, by_opp_effect=True, leave_kind="ko")

    assert replaced is True, "コストを払えるのに KO 置換が成立していない"
    assert len(me.hand) == hand_before - 1, "置換コストの手札捨てが行われていない"
    assert getattr(me, "hand_discarded_by_effect_this_turn", False) is True, (
        "置換コストの手札捨てでも hand_discarded_by_effect_this_turn が立つべき (公式 cardqa_op_12)"
    )


def test_replace_leave_cost_discard_fires_kuzan_leader_draw():
    """OP12-053 ボルサリーノが相手効果で場を離れる際の手札1捨てで、 リーダー OP12-040 クザン
    (自海軍カードの効果で手札が捨てられた時ドロー) が発火する (公式 cardqa_op_12)。"""
    from engine.effects import try_replace_ko

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP12-040")   # クザン
    me, opp = st.players[0], st.players[1]
    bors = InPlay.of(repo.get("OP12-053"), sickness=False)   # ボルサリーノ = 海軍
    me.characters = [bors]
    me.hand = [repo.get(_FILLER)]
    deck_before = len(me.deck)

    replaced = try_replace_ko(st, me, opp, bors, overlay, by_opp_effect=True, leave_kind="ko")

    assert replaced is True, "ボルサリーノの離脱置換 (手札1捨て) が成立していない"
    assert len(me.deck) == deck_before - 1, (
        "クザンの on_self_hand_discarded がドローしていない (公式は『はい、引ける』)"
    )


def test_replace_leave_cost_discard_no_draw_for_non_navy_leader():
    """対照: リーダーが海軍でなければ (actor_source_feature_contains 海軍 が偽) ドローしない。"""
    from engine.effects import try_replace_ko

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP01-001")   # 麦わらの一味 (海軍でない)
    me, opp = st.players[0], st.players[1]
    bors = InPlay.of(repo.get("OP12-053"), sickness=False)
    me.characters = [bors]
    me.hand = [repo.get(_FILLER)]
    deck_before = len(me.deck)

    try_replace_ko(st, me, opp, bors, overlay, by_opp_effect=True, leave_kind="ko")

    assert len(me.deck) == deck_before, "海軍でないリーダーでドローしてはいけない"


def test_all_replace_cost_hand_discards_fire_the_trigger():
    """overlay 全走査: replace_* コストに手札捨て (discard_hand / trash_self_hand_random /
    discard_hand_with_filter) を持つ全カードで、 その捨てが hand_discarded_by_effect_this_turn
    を立てる (= 「一部だけ実装」 の防波堤)。 現状の対象は EB03-001 / OP12-048 / OP12-053。"""
    from engine.effects import try_replace_ko

    repo, overlay = _repo(), _overlay()
    raw = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    targets = []
    for cid, effs in raw.items():
        if not isinstance(effs, list):
            continue
        for e in effs:
            if e.get("when") not in ("replace_ko", "replace_leave", "replace_rest"):
                continue
            cost = e.get("cost", [])
            cost = cost if isinstance(cost, list) else [cost]
            keys = set()
            for cs in cost:
                if isinstance(cs, dict):
                    keys |= set(cs.keys())
            if keys & {"discard_hand", "trash_self_hand_random", "discard_hand_with_filter"}:
                targets.append(cid)
                break
    assert targets, "前提が崩れている: 手札捨て replace コストのカードが 1 枚も無い"

    for cid in targets:
        # パラレル (_p1) 等は base の overlay を継承。 base_id で試験。
        base = cid.split("_")[0]
        try:
            card = repo.get(base)
        except Exception:
            continue
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        holder = InPlay.of(card, sickness=False)
        me.characters = [holder]
        # 捨てるコストを払えるだけの手札を積む (CHARACTER power低め、 filter 適合)。
        me.hand = [repo.get(_FILLER)] * 3
        me.hand_discarded_by_effect_this_turn = False
        replaced = try_replace_ko(st, me, opp, holder, overlay, by_opp_effect=True, leave_kind="ko")
        if not replaced:
            # このカードは KO 置換対象条件を満たさない構成 (target=self 以外等) → skip
            continue
        assert getattr(me, "hand_discarded_by_effect_this_turn", False) is True, (
            f"{cid}: replace コストの手札捨てが hand_discarded フラグを立てていない"
        )


# --------------------------------------------------------------------------- #
#  E. 【ターン1回】が無い【起動メイン】は コストを払える限り何度でも
#     ⚠ かつて engine が 「起動メインは一般にターン1回」 という近似で 1 回に制限していた
#       ([[project_approximation_hides_bugs]])。
# --------------------------------------------------------------------------- #
def test_activate_main_without_once_per_turn_is_repeatable():
    """【ターン1回】表記が無い起動メインは、 コスト (手札1捨て) が続く限り再発動できる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP09-081")
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER)]

    def opts():
        return [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "OP09-081"]

    eff = next(e for e in overlay.get("OP09-081").effects if e.get("when") == "activate_main")
    assert "once_per_turn" not in (eff.get("cost") or {}), \
        "前提が崩れている: OP09-081 の起動メインに【ターン1回】が付いている"

    assert len(opts()) == 1
    fire_activate_main(st, me, opp, *opts()[0])
    assert len(opts()) == 1, "【ターン1回】が無いのに 2 回目が legal から消えた"
    fire_activate_main(st, me, opp, *opts()[0])
    assert len(opts()) == 0, "手札が尽きたらコスト未払いで legal から消えるはず"


# --------------------------------------------------------------------------- #
#  F. 「〜することができる：」 の任意コストは 人間が **拒否** できる
#     ([[feedback_optional_cost_then_human_decline]] / [[feedback_human_ai_option_parity]])
# --------------------------------------------------------------------------- #
def test_optional_cost_is_declinable_by_human():
    """任意コストを拒否したら 効果もコストも一切起きない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("P-033"), sickness=False)   # 「デッキの下に置くことができる：1ドロー」
    me.characters = [luffy]
    me.hand = []
    deck_before = len(me.deck)

    opt = [o for o in list_activate_main_effects(st, me, overlay)
           if o[0].card.card_id == "P-033"][0]
    fire_activate_main(st, me, opp, *opt)
    assert st.pending_choice is not None, "人間に任意コストの可否が問われていない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm"
    resolve_pending_choice(st, [0])   # 拒否

    assert me.hand == [], "拒否したのにドローしている"
    assert luffy in me.characters, "拒否したのに自身がデッキの下に置かれている"
    assert len(me.deck) == deck_before, "拒否したのにデッキが動いている"


# --------------------------------------------------------------------------- #
#  F2. 払えない任意コストは **効果ごと不発** (タダ撃ちさせない)
#      ⚠ 「A か B をレストにできる：」 型は 「A も B も出せない」 局面がある。
#        ST32-001 錦えもんで、 リーダーがレスト済 + ドンを登場コストで使い切った状態だと
#        どちらも払えない。 Rust がこの判定を持たず draw2+手札1捨てをタダで撃っていた
#        (2026-08-04 の全カード掃引で発覚)。
# --------------------------------------------------------------------------- #
def test_unpayable_optional_cost_does_not_fire_effect():
    """リーダーがレスト済 + アクティブドン 0 なら 「リーダーかドン1枚をレスト」 は払えず不発。"""
    repo, overlay = _repo(), _overlay()
    eff = next(e for e in overlay.get("ST32-001").effects if e.get("when") == "on_play")

    # (a) 払えない: リーダー rested + don_active 0
    st = _state(repo, overlay, leader0="EB01-001_p2")
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True
    me.don_active = 0
    me.hand = []
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 0 and len(me.deck) == deck_before, (
        "コストを払えないのに draw が起きている (タダ撃ち)"
    )

    # (b) 払える: アクティブドンが 1 枚あればレストして発動する
    st2 = _state(repo, overlay, leader0="EB01-001_p2")
    me2, opp2 = st2.players[0], st2.players[1]
    me2.leader.rested = True
    me2.don_active = 1
    me2.hand = []
    src2 = InPlay.of(repo.get("ST32-001"), sickness=True)
    me2.characters.append(src2)
    for prim in eff["do"]:
        execute_effect(prim, st2, me2, opp2, src2)
    assert me2.don_active == 0 and me2.don_rested >= 1, "ドン1枚をレストして払っていない"
    assert len(me2.hand) == 1, f"draw2 → 手札1捨て で手札 1 枚のはず: {len(me2.hand)}"


# --------------------------------------------------------------------------- #
#  F3. 「このバトル終了時」 は リーダー戦でも成立する
#      ⚠ flush が AttackCharacter 分岐にだけ書かれており、 リーダーへアタックした場合は
#        フラグが残留していた (後続の別バトル終了時に誤爆する)。 公式は 「このバトル終了時」
#        なのでリーダー戦もバトル。 2026-08-04 に バトル終了フック本体 (公式 7-1-5-1) へ移した。
# --------------------------------------------------------------------------- #
def _bon_clay_state(repo, overlay):
    """OP02-064 ボン・クレー (ドン‼×1 で【アタック時】が有効) が攻撃できる盤面。"""
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    bon = InPlay.of(repo.get("OP02-064"), sickness=False)
    bon.attached_dons = 1                              # 【ドン‼×1】 ゲート
    me.characters = [bon]
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]  # cost1 = 対象
    me.hand = [repo.get(_FILLER)]                      # 「手札1枚を捨てる」 コスト用
    return st, me, opp, bon


def test_return_at_battle_end_fires_on_leader_attack():
    """リーダーにアタックした場合も バトル終了時にデッキの下へ行く。"""
    repo, overlay = _repo(), _overlay()
    st, me, opp, bon = _bon_clay_state(repo, overlay)
    deck_before = len(me.deck)

    apply_action(st, AttackLeader(attacker_iid=bon.instance_id))

    assert bon not in me.characters, "リーダー戦で 「このバトル終了時」 が処理されていない"
    assert any(c.card_id == "OP02-064" for c in me.deck), "デッキの下に置かれていない"
    assert len(me.deck) == deck_before + 1
    assert bon.return_to_deck_bottom_at_battle_end is False, "フラグが残留している (後続バトルで誤爆する)"


def test_return_at_battle_end_fires_on_character_attack():
    """キャラにアタックした場合も同じ (従来から動いていた経路の回帰)。"""
    repo, overlay = _repo(), _overlay()
    st, me, opp, bon = _bon_clay_state(repo, overlay)
    deck_before = len(me.deck)

    apply_action(st, AttackCharacter(attacker_iid=bon.instance_id,
                                     target_iid=opp.characters[0].instance_id))

    assert bon not in me.characters, "キャラ戦で 「このバトル終了時」 が処理されていない"
    assert len(me.deck) == deck_before + 1
    assert bon.return_to_deck_bottom_at_battle_end is False


# --------------------------------------------------------------------------- #
#  F4. 「公開したカードのうち1枚を登場させ、 残りがコストN以下ならレストで登場」
#      OP10-058 レベッカ。 コスト超のカードはレスト登場できないので **公開のみで手札に残る**。
# --------------------------------------------------------------------------- #
def test_reveal_hand_play_split_active_and_rested():
    """コスト7 を active、 コスト4 を rested で登場させる (2 枚とも手札から出る)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-053"),  # ドレスローザ cost7 → active 枠
               repo.get("EB03-042"),  # ドレスローザ cost4 → rested 枠
               repo.get(_FILLER)]     # 特徴違い = 対象外
    hand_before = len(me.hand)

    do = next(e for e in overlay.get("OP10-058").effects if e.get("when") == "on_play")["do"]
    spec = next(p for p in do if "reveal_hand_play_split" in p)
    execute_effect(spec, st, me, opp, None)

    played = {c.card.card_id: c for c in me.characters}
    assert "OP16-053" in played, "コスト7 のキャラが登場していない"
    assert "EB03-042" in played, "コスト4 のキャラがレストで登場していない"
    assert played["OP16-053"].rested is False, "active 枠がレストになっている"
    assert played["EB03-042"].rested is True, "「残り」 はレストで登場するはず"
    assert len(me.hand) == hand_before - 2, "登場した 2 枚が手札から抜けていない"
    assert me.hand[0].card_id == _FILLER, "対象外のカードまで抜けている"


def test_reveal_hand_play_split_over_cost_stays_in_hand():
    """コスト上限超のカードしか残らない場合、 2 枚目は登場せず手札に残る。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-053"), repo.get("OP15-046")]  # 両方 cost7 (>4)
    do = next(e for e in overlay.get("OP10-058").effects if e.get("when") == "on_play")["do"]
    spec = next(p for p in do if "reveal_hand_play_split" in p)
    execute_effect(spec, st, me, opp, None)

    assert len(me.characters) == 1, (
        "コスト4超は 「残り」 節が適用外でレスト登場できない = 登場は 1 枚のはず"
        f" (現在 {[c.card.card_id for c in me.characters]})"
    )
    assert len(me.hand) == 1, "登場しなかった 1 枚は手札に残るはず"


# --------------------------------------------------------------------------- #
#  G. 【相手のアタック時】が複数枚同時に自身をトラッシュする時の順序
#     公式上は 場の並び順に処理される = トラッシュへの到着順も場の並び順。
# --------------------------------------------------------------------------- #
def test_multiple_self_trash_opp_attack_go_to_trash_in_board_order():
    """自身をトラッシュする【相手のアタック時】が 2 体並ぶと、 場の並び順にトラッシュへ入る。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="ST21-001_p2", leader1="ST21-001_r1")
    me, opp = st.players[0], st.players[1]
    # ST22-002 イゾウ: 【相手のアタック時】このキャラをトラッシュに置くことができる：
    #                  カード1枚を引き、自分の手札1枚をデッキの下に置く。
    first = InPlay.of(repo.get("ST22-002"), sickness=False)
    second = InPlay.of(repo.get("ST22-002_p1"), sickness=False)
    opp.characters = [first, second]
    opp.hand = [repo.get(_FILLER)] * 4

    apply_action(st, AttackLeader(attacker_iid=me.leader.instance_id))

    trashed = [c.card_id for c in opp.trash]
    if len(trashed) >= 2:
        assert trashed[0] == "ST22-002" and trashed[1] == "ST22-002_p1", (
            f"トラッシュ到着順が場の並び順でない: {trashed[:2]}"
        )


# --------------------------------------------------------------------------- #
#  G2. 「トラッシュに置く」 は KO ではない
#      公式は 「KOする」 と 「トラッシュに置く」 を書き分けている。 後者は 場を離れるだけで
#      【KO時】は発動せず、 このターンの被 KO 数にも数えない。
#      ⚠ OP03-043 ガイモンの overlay が `self_ko` になっており (公式は 「トラッシュに置く」)、
#        被 KO 数が誤って増えていた。 2026-08-04 に `trash_self` へ是正。
# --------------------------------------------------------------------------- #
def test_trash_self_is_not_a_ko():
    """自身を 「トラッシュに置く」 は KO ではない (被 KO 数が増えない)。

    ⚠ 2026-08-13 に OP03-043 ガイモンの overlay を作り直した。 公式テキストは
      「デッキの上から3枚をトラッシュに置いて**もよい**。**そうした場合**、このキャラを
      トラッシュに置く」 = ① 任意 ② 自身を落とすのは mill の **後** (結果) であって
      発動コストではない。 旧 overlay は entry の cost に trash_self を置いており
      **順序が逆 (自身が先に落ちる) で、 しかも任意でなかった**。
    """
    from engine.effects import run_do_array

    repo, overlay = _repo(), _overlay()
    eff = next(e for e in overlay.get("OP03-043").effects
               if e.get("when") == "on_opp_life_taken")
    assert "cost" not in eff, (
        f"自身のトラッシュは発動コストではない (「そうした場合」 = 結果): {eff.get('cost')}"
    )
    oct_spec = eff["do"][0]["optional_cost_then"]
    assert oct_spec["cost"] == [], "任意効果なのでコストは空のはず"
    assert any("return_self_to_trash" in e for e in oct_spec["effect"]), \
        "「そうした場合、このキャラをトラッシュに置く」 が effect 側に無い"

    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-043"), sickness=False)
    me.characters = [src]
    deck_before = len(me.deck)
    run_do_array(list(eff["do"]), st, me, opp, src)
    resolve_triggers(st)

    assert len(me.deck) == deck_before - 3, "デッキ上3枚がトラッシュされていない"
    assert src not in me.characters, "「そうした場合」 で自身がトラッシュに置かれていない"
    assert any(c.card_id == "OP03-043" for c in me.trash), "自身がトラッシュに無い"
    assert me.chara_ko_taken_this_turn == 0, (
        "「トラッシュに置く」 は KO ではないので 被 KO 数を増やしてはいけない"
        f" (現在 {me.chara_ko_taken_this_turn})"
    )


def test_no_card_uses_self_ko_cost_against_official_text():
    """`self_ko` コストは 公式テキストに 「KO」 とあるカードにしか使わない。

    「トラッシュに置く」 を self_ko で書くと 【KO時】が誤発動し 被 KO 数もズレる。
    overlay 全体を走査して 恒久的に見張る。
    """
    import json as _json

    ov = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in _json.loads(
        (ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    bad = []

    def walk(cid, x):
        if isinstance(x, dict):
            if x.get("self_ko"):
                if "KO" not in (cards.get(cid, {}).get("text") or ""):
                    bad.append(cid)
            for v in x.values():
                walk(cid, v)
        elif isinstance(x, list):
            for v in x:
                walk(cid, v)

    for cid, effs in ov.items():
        walk(cid, effs)
    assert not bad, (
        "公式テキストに 「KO」 が無いのに self_ko コストを使っているカード: "
        f"{sorted(set(bad))} → 「トラッシュに置く」 なら trash_self にする"
    )


# --------------------------------------------------------------------------- #
#  I. 表向きライフ枚数は ライフ枚数を超えない (状態の正規化)
#     ⚠ face_up_life_count は **増やす側も読む側も** clamp していたが、 ライフが減る時に
#       減らしていなかった。 「ライフ 0 なのに表向き 1」 が残り、 後でライフが増えると
#       **新しく置いた裏向きのライフを表向きと誤認** する潜在バグだった。
#       Rust の保存則チェック (INV-face-up-life) が検出 = 両エンジンが同じ間違いをしていて
#       差分検証では原理的に見えなかったクラス ([[reference_rust_mismatch_root_cause_taxonomy]])。
# --------------------------------------------------------------------------- #
def test_face_up_life_is_tracked_per_card():
    """表向きライフは **1 枚ごと** に追跡される (枚数だけのモデルではない)。

    ⭐ 2026-08-11 に per-card 化。 旧モデルは 「表向きは上から N 枚」 という **枚数だけ** を持ち、
    ライフが減っても減らし忘れる / 並べ替えで位置がずれる といった壊れ方をした。
    公式 (cardqa_st_13 / ST13-003 ルフィ 「ルール上、 自分の表向きのライフは手札に加わる代わりに
    デッキの下に置かれる」) を再現するには **どの札が表向きか** が要る。
    ⚠ 「上から N 枚」 の近似は使えない: ST13-012 マキノ 「自分のライフすべてを見て、 好きな順番で
      置く」 が全体を並べ替えるため。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]

    # 3 枚のうち **真ん中だけ** 表向き (= 位置ベースでは表せない状態)
    me.life = [repo.get(_FILLER) for _ in range(3)]
    me.life_face_up = [False, True, False]
    assert me.face_up_life_count == 1

    # ライフが尽きても 「表向き枚数」 は構造的に 0 (= 導出値なのでずれようがない)
    me.life = []
    assert me.face_up_life_count == 0, "ライフ 0 なのに表向きが残っている"

    # 積み直したライフは裏向き (= 古い表向き情報が引き継がれない)
    me.life = [repo.get(_FILLER)]
    assert me.face_up_life_count == 0, "新しく置いた裏向きのライフが表向き扱いになっている"
    assert len(me.life_face_up) == len(me.life), "フラグ長がライフ枚数と一致していない"


def test_life_face_up_desync_is_loud():
    """`life` と `life_face_up` の長さが食い違ったら **アクション境界で落とす**。

    ⚠ 黙って埋めると 「表向きだったはずの札が裏向きになる」 誤りを隠す
    ([[project_approximation_hides_bugs]])。 同期漏れは必ず露出させる。
    """
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER) for _ in range(3)]
    _recompute_static(st)                     # 正常時は通る
    me.life.append(repo.get(_FILLER))         # フラグを更新し忘れた操作を再現
    try:
        _recompute_static(st)
    except AssertionError as e:
        assert "life_face_up desync" in str(e)
    else:
        raise AssertionError("同期漏れが検出されていない (黙って通っている)")


# --------------------------------------------------------------------------- #
#  H. 効果無効は 「相手がキャラを登場させた時」 のような場のトリガーにも効く
# --------------------------------------------------------------------------- #
def test_negated_source_does_not_fire_on_play():
    """効果無効を持つキャラの【登場時】は発動しない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # OP01-016 ナミ: 【登場時】デッキ上5枚から《麦わらの一味》1枚を手札へ。
    nami = InPlay.of(repo.get("OP01-016"), sickness=True)
    nami.granted_keywords.add("効果無効")
    me.characters.append(nami)
    hand_before = len(me.hand)

    trigger_on_play(st, me, opp, nami, overlay)
    assert len(me.hand) == hand_before, "効果無効なのに【登場時】のサーチが走っている"


def test_negated_source_does_not_fire_activate_main():
    """効果無効を持つキャラの【起動メイン】は発動しない (発動しても状態が変わらない)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    ip = InPlay.of(repo.get("ST01-007"), sickness=False)   # 自リーダー/キャラにレストドン1付与
    ip.granted_keywords.add("効果無効")
    me.characters = [ip]
    me.don_active = 5
    me.don_rested = 0

    for src, eff in list_activate_main_effects(st, me, overlay):
        if src.card.card_id == "ST01-007":
            fire_activate_main(st, me, opp, src, eff)

    total_attached = ip.attached_dons + me.leader.attached_dons
    assert total_attached == 0, \
        f"効果無効なのに起動メインでドンが付与された: {total_attached}"


# --------------------------------------------------------------------------- #
#  J. バトル中に当事者が場を離れたら **バトルは中断** される (公式裁定)
#     cardqa_op_01 / op_05 / op_12 / st_02 / st_03 で繰り返し明示:
#       「カウンターステップの終了時に、 アタックしているキャラやアタックされているキャラが
#         場に存在しない場合、 ダメージステップには移行せず、 バトルは終了します」
#     ⚠ 2026-08-04 まで engine は アタッカーを object 参照で保持して **バトルを続行** して
#       いた (= カウンターで KO されたアタッカーがダメージを与えていた)。 Rust も忠実に
#       ミラーしていたので **差分検証では原理的に検出できず**、 公式 Q&A 突合で発覚した。
# --------------------------------------------------------------------------- #
def test_battle_aborts_when_counter_kos_the_attacker():
    """【カウンター】でアタッカーが KO されたら ダメージステップに移行しない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP01-001", leader1="OP01-001")
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get(_FILLER), sickness=False)   # 元々パワー3000 (≤6000 = KO 対象)
    atk.attached_dons = 2                                # → 現在 5000 = リーダーと互角 (通れば 1 ダメージ)
    me.characters = [atk]
    opp.hand = [repo.get("EB01-010")]                    # 【カウンター】元々パワー6000以下を KO
    opp.don_active = 5
    life_before = len(opp.life)

    apply_action(st, AttackLeader(attacker_iid=atk.instance_id, counter_event_idxs=(0,)))

    assert atk not in me.characters, "前提が崩れている: カウンターでアタッカーが KO されていない"
    assert len(opp.life) == life_before, (
        "アタッカーが場を離れたのにダメージが通っている"
        f" (ライフ {life_before} → {len(opp.life)})。 公式はバトル中断"
    )


def test_battle_resolves_normally_when_attacker_survives():
    """対照: アタッカーが生き残れば通常どおりダメージが通る (テストの妥当性確認)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP01-001", leader1="OP01-001")
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get(_FILLER), sickness=False)
    atk.attached_dons = 2
    me.characters = [atk]
    opp.hand = []                                        # カウンターしない
    life_before = len(opp.life)

    apply_action(st, AttackLeader(attacker_iid=atk.instance_id))

    assert atk in me.characters
    assert len(opp.life) == life_before - 1, "通常のバトルでダメージが通っていない"


# --------------------------------------------------------------------------- #
#  K. 「レストにできない」 は **アタックも【ブロッカー】発動も** できなくする
#     公式 Q&A: 「「レストにできない」と書かれた効果は、そのキャラが【ブロッカー】を発動する
#     ことができなくなる効果ですか？」 →「はい、発動できません。この効果は、**アタックや
#     【ブロッカー】の発動などの、レストにすることが必要な行動をできない状態にする**効果です。」
#     ⚠ アタック側は列挙で止めていたが、 **ブロッカー発動は素通り** していた (2026-08-04)。
# --------------------------------------------------------------------------- #
def test_cannot_be_rested_blocks_attacking():
    """「レストにできない」 キャラは自分からアタックできない。"""
    from engine.game import legal_actions

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    c = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [c]

    def own_attacks():
        return [a for a in legal_actions(st)
                if isinstance(a, (AttackLeader, AttackCharacter)) and a.attacker_iid == c.instance_id]

    assert len(own_attacks()) == 1, "前提が崩れている: 通常はアタックできるはず"
    c.cannot_be_rested_buff = True
    assert own_attacks() == [], "「レストにできない」 のにアタックできてしまう"


def test_cannot_be_rested_blocks_blocker_activation():
    """「レストにできない」 キャラは【ブロッカー】を発動できない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [atk]
    blk = InPlay.of(repo.get("OP01-014"), sickness=False)   # ジンベエ = ブロッカー
    opp.characters = [blk]
    assert blk.is_blocker_now and not blk.rested, "前提が崩れている"

    blk.cannot_be_rested_buff = True
    apply_action(st, AttackLeader(attacker_iid=atk.instance_id, blocker_iid=blk.instance_id))

    assert blk.rested is False, (
        "「レストにできない」 のに【ブロッカー】が発動している"
        " (ブロックはレストにすることが必要な行動)"
    )


# --------------------------------------------------------------------------- #
#  L. 「A。 その後、 B」 の解決順と 後段の強制性
#     公式: 「-4000しなかった場合も、 **可能な限り**ライフ1枚を手札に加えます」
#     (cardqa_op_02 / st_15) = 前段が空振りでも後段は実行される。
#     ⚠ overlay の do 順が公式と逆になっていた 19 件を 2026-08-04 に是正
#       (`scripts/audit_sonogo_order.py` が恒久監査)。
# --------------------------------------------------------------------------- #
def test_sonogo_tail_runs_even_when_head_finds_no_target():
    """前段 (相手キャラへのパワー-2000) が空振りでも 後段 (ライフ→手札) は実行される。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="ST15-001")
    me, opp = st.players[0], st.players[1]
    opp.characters = []                       # 前段の対象なし
    src = InPlay.of(repo.get("ST15-004"), sickness=True)
    me.characters = [src]
    life_before, hand_before = len(me.life), len(me.hand)

    eff = next(e for e in overlay.get("ST15-004").effects if e.get("when") == "on_play")
    assert [next(iter(d)) for d in eff["do"]] == ["power_pump", "life_to_hand"], \
        "公式は 「パワー-2000。 その後、 ライフを手札に」 の順"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.life) == life_before - 1 and len(me.hand) == hand_before + 1, \
        "前段が空振りでも後段は 「可能な限り」 実行されるはず"


# --------------------------------------------------------------------------- #
#  M. ライフ 0 の扱い
#     公式: 「自分のライフが0枚のときに 『ライフの上から1枚を手札に加える』 ことはできますか？」
#           →「いいえ、できません」 (cardqa_op_12)
#           一方 「デッキの上から1枚をライフの上に加える」 は ライフ0でも **できる** (op_15/op_06)
# --------------------------------------------------------------------------- #
def test_life_to_hand_does_nothing_at_zero_life():
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []
    hand_before = len(me.hand)
    execute_effect({"life_to_hand": 1}, st, me, opp, None)
    assert len(me.hand) == hand_before, "ライフ 0 なのに手札が増えている"


def test_put_top_to_life_works_at_zero_life():
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []
    deck_before = len(me.deck)
    execute_effect({"put_top_to_life": 1}, st, me, opp, None)
    assert len(me.life) == 1 and len(me.deck) == deck_before - 1, \
        "ライフ 0 でも デッキ上→ライフ は行える (公式)"


def test_cannot_be_rested_blocks_rest_self_cost():
    """「レストにできない」 は **レストを要するコストの支払い** もできなくする。

    公式 (3 弾で繰り返し): 「「レストにできない」と書かれた効果は、 そのキャラが
    「このキャラをレストにする」 などと書かれた効果を発動することができなくなる効果ですか？」
    →「はい、発動できません。 この効果は、 アタックや【ブロッカー】の発動などの、
       **レストにすることが必要な行動**をできない状態にする効果です。」
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # OP05-025 グラディウス =【起動メイン】このキャラをレストにできる：相手のコスト3以下をレスト。
    # ⚠ 以前は _FILLER (OP01-013 サンジ) を使っていたが、 サンジの公式コストは **ライフ1枚を
    #   手札に加える** でレストではない (2026-08-11 に overlay を是正)。 レストコストの検査には
    #   公式テキストが実際に 「このキャラをレストにできる：」 のカードを使う。
    c = InPlay.of(repo.get("OP05-025"), sickness=False)
    me.characters = [c]
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]

    def opts():
        return [o for o in list_activate_main_effects(st, me, overlay) if o[0] is c]

    assert len(opts()) == 1, "前提が崩れている: 通常は起動メインが出るはず"
    c.cannot_be_rested_buff = True
    assert opts() == [], "「レストにできない」 のに レストを要するコストが払えてしまう"


def test_cannot_be_rested_blocks_rest_by_other_effect():
    """「レストにできない」 は 他のカードの効果によるレストも防ぐ (公式、 既に実装済の確認)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    victim.cannot_be_rested_buff = True
    execute_effect({"rest": "one_opponent_character_any"}, st, me, opp, None)
    assert victim.rested is False, "「レストにできない」 のに他効果でレストされている"


# --------------------------------------------------------------------------- #
#  N. 「(効果)：相手は手札を捨てる」 の後段は 効果が起きた場合のみ (OP09-101 クザン)
#     公式 (cardqa): 「このキャラを登場させ、相手のコスト3以下のキャラ1枚を相手のライフに
#                    置かない事はできますか？」→「はい、できます。その場合、相手は手札1枚を
#                    捨てることはありません。」
#     = ライフに置く後段の手札破棄は、 実際に置いた時だけ発火する (置けない/置かないなら破棄なし)。
# --------------------------------------------------------------------------- #
def test_op09_101_no_discard_when_no_life_target():
    """OP09-101: 相手にコスト3以下のキャラが居なければ 相手の手札破棄は起きない。

    是正前の overlay は `[trash_opp_hand_random, chara_to_opp_life]` の 2 段独立で、
    ライフに置けない (対象なし) 場合でも 手札を捨てさせていた = 公式違反。
    修正後は chara_to_opp_life の `then` に 破棄を入れ、 実際に置いた時だけ発火する。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 4
    opp.characters = []                       # ライフに置く対象 (コスト3以下) が居ない
    src = InPlay.of(repo.get("OP09-101"), sickness=True)
    me.characters = [src]
    hand_before = len(opp.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(opp.hand) == hand_before, \
        "ライフに置けないのに相手が手札を捨てている (公式: 置かない場合は捨てない)"


def test_op09_101_discards_when_life_target_placed():
    """対照: コスト3以下のキャラが居れば ライフに置き、 その場合のみ 相手は手札1枚を捨てる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 4
    victim = InPlay.of(repo.get(_FILLER), sickness=False)   # OP01-013 = コスト2 (<=3)
    assert victim.card.cost <= 3, "前提: 対象は コスト3以下"
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP09-101"), sickness=True)
    me.characters = [src]
    hand_before, life_before = len(opp.hand), len(opp.life)
    trigger_on_play(st, me, opp, src, overlay)
    assert victim not in opp.characters and len(opp.life) == life_before + 1, \
        "コスト3以下のキャラが相手ライフに置かれるはず"
    assert len(opp.hand) == hand_before - 1, \
        "ライフに置いた場合は相手が手札1枚を捨てるはず"
# ---------------------------------------------------------------------------
# 公式のコスト意味論 (2026-08-04 是正)
#   素の 「コスト N 以下」    → **効果修正後の現在コスト** (cardqa_op_02 / 公式ルール 1-3-6-2)
#   「元々のコスト N 以下」   → **印刷コスト**            (cardqa_eb_03 / cardqa_promo)
# ---------------------------------------------------------------------------

def test_plain_cost_uses_current_cost_and_truly_original_uses_printed():
    """コスト修正を受けたキャラに対し、 2 つの表記が別々に効く。"""
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def board():
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        victim = InPlay.of(repo.get("OP02-004"), sickness=False)   # 印刷コスト 9
        victim.cost_minus_until_turn_end = 8                        # → 現在コスト 1
        p1.characters = [victim]
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        return st, p0, p1, victim

    st, p0, p1, victim = board()
    assert victim.card.cost == 9 and victim.base_cost == 1
    execute_effect({"ko": "one_opponent_character_cost_le_2cost"}, st, p0, p1, None)
    assert victim not in p1.characters, (
        "素の 「コスト2以下」 は 現在コスト(1) で判定するので当たるはず "
        "(公式 cardqa_op_02: コストを下げた後は下がった値で参照する)"
    )

    st, p0, p1, victim = board()
    execute_effect({"ko": "one_opponent_character_truly_original_cost_le_2"}, st, p0, p1, None)
    assert victim in p1.characters, (
        "「元々のコスト2以下」 は 印刷コスト(9) で判定するので当たらないはず "
        "(公式 cardqa_eb_03)"
    )


def test_overlay_cost_wording_matches_spec_key():
    """overlay の コスト判定キーが 公式テキストの表記 (元々の / 素) と一致している。

    素の 「コスト」 に `truly_original_cost_*` を使うと 印刷値で判定してしまい、
    逆に 「元々のコスト」 に素の spec を使うと 現在値で判定してしまう。 どちらも
    差分検証 (Python↔Rust) では **両エンジンが同じ間違いをする** ので沈黙する。
    """
    import re

    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    # ⚠ 【トリガー】の文面は `text` でなく `trigger` フィールド (820 枚)。 効果エントリごとに
    #   対応するテキスト欄と突き合わせる。
    # ⚠ 「相手の元々の、パワーN以下のキャラとコストM以下のキャラ」 のように **読点で 「元々の」 が
    #   両方に係る** 書き方がある (EB03-021 / OP10-098)。 「元々のコスト」 の literal 検索だけでは
    #   取りこぼすので 「元々の」 + 読点 も 「元々の」 扱いにする。
    # 1 枚のカード内で 「元々のコスト/パワー」 節と 素の 「コスト/パワー」 節が同居するもの。
    # 節ごとに正しく書き分けてあることを個別に確認済 (2026-08-04)。
    MIXED_WORDING = {
        # 【相手のターン中】= 「自分のアクティブの元々のコストが5のキャラ」 (盤面 → truly_original)
        # 【登場時】       = 「自分の手札からコスト5の緑のキャラカード」 (手札 → 素の cost_eq で正)
        "OP04-119": "手札の「コスト5」と盤面の「元々のコスト5」が同居",
        # replace_leave = 「自分の元々のコスト6以下のキャラ」 / 【相手のターン中】= 「元々のコスト2」
        # どちらも truly_original。 素の cost 表記は無いが 「元々の」 が複数節にある。
        "OP12-102": "複数節すべて「元々のコスト」で、節ごとに明示キー化済",
    }
    bad: list[str] = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list):
            continue
        if cid.split("_")[0] in MIXED_WORDING:
            continue
        card = cards.get(cid) or {}
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            src = "trigger" if eff.get("when") == "trigger" else "text"
            # ⚠ overlay の `_text` は要約なので (「元々cost5」 等) 判定源にできない。 公式本文を使う。
            #   1 枚に 「元々のコスト」 節と素の 「コスト」 節が同居するカードは MIXED_WORDING で除外。
            text = re.sub(r"[(（][^)）]*[)）]", "", re.sub(r"\s+", "", card.get(src) or ""))
            # ⚠ `_text` / `_doc` は spec 名を引用していることがあるので blob から除く
            #   (OP05-001 の `_doc` が truly_original_power_ge を引用していて誤検出した)。
            blob = json.dumps({k: v for k, v in eff.items() if not k.startswith("_")},
                              ensure_ascii=False)
            for word, key in (("コスト", "cost"), ("パワー", "power")):
                # `_by_truly_power_le_N` は 「元々のパワー」 を意味する既存の明示 spec
                uses_orig = (f"truly_original_{key}_" in blob) or (f"_by_truly_{key}_" in blob)
                says_orig = (f"元々の{word}" in text) or ("元々の、" in text and f"{word}" in text)
                plain_rx = re.compile(rf"(?<!元々の){word}[+\-−]?\d+(以下|以上)")
                uses_plain = bool(
                    re.search(rf"(?<!truly_original)(?<!_by_truly)_{key}_(le|ge|eq)_\d", blob)
                    or re.search(rf'"{key}_(le|ge|eq)"', blob)
                )
                if uses_orig and not says_orig:
                    bad.append(f"{cid}[{src}]: truly_original_{key}_* だが 公式に 「元々の{word}」 が無い")
                elif says_orig and uses_plain and plain_rx.search(text) is None:
                    bad.append(f"{cid}[{src}]: 公式は 「元々の{word}」 だが overlay が素の {key} spec")
    assert not bad, "コスト/パワー表記と spec キーの不一致:\n  " + "\n  ".join(bad[:40])


def test_no_card_needs_plain_cost_attack_restriction():
    """`set_cannot_attack_target_cost_le` の消費側は **印刷コスト** 固定。

    game.py の `_can_attack_target` は `tgt.card.cost` と比べるので、 素の
    「コスト N 以下のキャラへアタックできない」 カードが登場したら **消費側を
    `base_cost` に切り替える分岐が要る**。 現状そういうカードが無いことを固定する。
    """
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    offenders = [
        cid for cid, effs in ov.items()
        if isinstance(effs, list)
        and "set_cannot_attack_target_cost_le" in json.dumps(effs, ensure_ascii=False)
        and "元々のコスト" not in ((cards.get(cid, {}) or {}).get("text") or "")
    ]
    assert not offenders, (
        "素の 「コスト」 でアタック制限するカードが現れた。 消費側 (game.py:_can_attack_target) を "
        f"現在コストで判定する分岐に拡張すること: {offenders}"
    )


# ---------------------------------------------------------------------------
# 公式の対象範囲 (2026-08-04 是正)
#   「**相手の** コスト3以下のキャラ1枚まで」 → 相手のみ
#   「コスト3以下のキャラ1枚まで」          → **両陣営** (自分のキャラ / 発動元自身も選べる)
# 一次情報は docs/official_rulings.md を参照 (複数弾で繰り返された一般則)。
# ---------------------------------------------------------------------------

def _either_board(repo, ov, mine: list[str], theirs: list[str]):
    import random
    from engine.core import GameState, InPlay, Phase, Player
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p0.characters = [InPlay.of(repo.get(c), sickness=False) for c in mine]
    p1.characters = [InPlay.of(repo.get(c), sickness=False) for c in theirs]
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 10
        p.life = [repo.get("OP01-013")] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 5
    return st, p0, p1


def test_unqualified_character_target_can_hit_own_board():
    """修飾なし 「キャラ1枚まで」 は 相手が居なくても **自分のキャラ** を対象にできる。

    ここが片側限定だと 「自キャラを戻して【登場時】を撃ち直す」 「KO から逃がす」 という
    実在ラインが engine から丸ごと消える。 しかも overlay は Python/Rust 共通なので
    **差分検証では永久に沈黙する** クラスのバグ。
    """
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    cheap = "OP01-013"

    specs = [
        ("cost_le", {"return_to_deck_bottom": "one_character_either_cost_le_5"}),
        ("any", {"return_to_deck_bottom": "one_character_either_any"}),
        ("filtered", {"return_to_deck_bottom": {
            "type": "one_character_either_filtered", "filter": {"cost_le": 5}}}),
    ]
    # ⚠ 「自陣も対象になりうる」 の検証は **人間経路** で行う。
    #   AI の auto-pick は 「相手が居なければ 0 枚」 が正しい (公式 「N枚まで」 = 0 枚可、
    #   自陣を送るのはほぼ常に悪手)。 AI が自陣を選ぶことを期待値にすると自滅を固定してしまう。
    for label, eff in specs:
        st, p0, p1 = _either_board(repo, ov, [cheap], [])
        st.human_player_idx = 0
        execute_effect(eff, st, p0, p1, None)
        pc = st.pending_choice
        assert pc is not None, f"{label}: 相手の場が空でも自陣が候補になるはず (modal が立たない)"
        raw = pc.get("cards") or pc.get("candidates") or []
        iids = {c.get("iid") if isinstance(c, dict) else c for c in raw}
        assert p0.characters[0].instance_id in iids, (
            f"{label}: 自分のキャラが候補に入っていない "
            "(公式: 修飾なし 「キャラ1枚まで」 は両陣営)"
        )

    # 対照: 相手が居れば AI は相手を優先する (= 自陣を巻き込まない)
    st, p0, p1 = _either_board(repo, ov, [cheap], [cheap])
    execute_effect({"return_to_deck_bottom": "one_character_either_cost_le_5"}, st, p0, p1, None)
    assert not p1.characters and len(p0.characters) == 1, (
        "相手キャラが居る時は相手を優先すべき (AI の除去価値)"
    )


def test_target_scope_audit_is_clean():
    """公式テキストの 「相手の」 修飾の有無と overlay の spec 片側限定が一致している。"""
    import subprocess
    import sys as _sys
    r = subprocess.run(
        [_sys.executable, str(ROOT / "scripts" / "audit_target_scope.py"), "--assert"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    assert r.returncode == 0, (
        "公式が 「相手の」 と書いていない対象を overlay が片側限定にしている:\n"
        f"{r.stdout}\n{r.stderr}"
    )


def test_filter_dict_cost_also_uses_current_cost():
    """filter dict の `cost_le` も **場のキャラに対しては現在コスト** で判定する。

    `_matches_filter` は CardDef しか受け取らないので、 素で使うと 印刷コスト固定になり
    「コストを下げてから除去する」 実在ラインが filter 経路だけ機能しない (= 経路ごとの
    取りこぼし)。 盤面は `_matches_filter_ip` を通すことで target spec 文字列版と揃える。
    """
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def board():
        st, p0, p1 = _either_board(repo, ov, [], [])
        from engine.core import InPlay
        v = InPlay.of(repo.get("OP02-004"), sickness=False)   # 印刷 9
        v.cost_minus_until_turn_end = 8                        # → 現在 1
        p1.characters = [v]
        return st, p0, p1, v

    st, p0, p1, v = board()
    assert v.card.cost == 9 and v.base_cost == 1
    execute_effect({"ko": {"type": "one_opponent_character_filtered",
                           "filter": {"cost_le": 2}}}, st, p0, p1, None)
    assert v not in p1.characters, "filter の cost_le は現在コスト(1)で当たるべき"

    st, p0, p1, v = board()
    execute_effect({"ko": {"type": "one_opponent_character_filtered",
                           "filter": {"truly_original_cost_le": 2}}}, st, p0, p1, None)
    assert v in p1.characters, "filter の truly_original_cost_le は印刷コスト(9)で当たらないべき"


def test_no_board_filter_uses_carddef_only_matcher():
    """盤面 (InPlay) に対する filter 判定が `_matches_filter(x.card, ...)` に退行していない。

    `.card` を渡すと CardDef ベース = 印刷コスト固定に戻る。 新しい盤面 filter を書く時は
    必ず `_matches_filter_ip(ip, filt)` を使うこと。
    """
    import re
    src = (ROOT / "engine" / "effects.py").read_text(encoding="utf-8")
    # `_matches_filter_ip` 自身の委譲 (= CardDef 版を呼ぶのが正しい) は除外する
    start = src.index("def _matches_filter_ip(")
    end = src.index("def _matches_filter(", start)
    src = src[:start] + src[end:]
    bad = re.findall(r"_matches_filter\([A-Za-z_][A-Za-z0-9_\.\[\]]*\.card,", src)
    assert not bad, (
        "盤面 InPlay に CardDef 専用の _matches_filter を使っている (印刷コスト固定に退行):\n  "
        + "\n  ".join(sorted(set(bad)))
    )


def test_plain_power_uses_current_and_truly_original_uses_printed():
    """パワーも コストと同じ書き分け (2026-08-04)。

    一次情報 (cardqa): 「元々のパワーが6000以下のキャラが効果で7000以上となっている場合、
    この【メイン】効果でKOできますか？」 → **「いいえ、できません。現在のパワーが6000以下の
    キャラをKOできます。」** 対照で 「元々のパワーが3000以下で、 ドン!!の付与などによって
    パワー4000以上になったキャラをトラッシュに置くことはできますか？」 → 「はい、できます。」
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def board():
        st, p0, p1 = _either_board(repo, ov, [], [])
        v = InPlay.of(repo.get("OP01-013"), sickness=False)
        v.turn_buff = 3000                       # 印刷 3000 → 現在 6000
        p1.characters = [v]
        return st, p0, p1, v

    st, p0, p1, v = board()
    cap = v.card.power + 1000                    # 印刷 < cap < 現在
    assert v.card.power < cap < v.power
    execute_effect({"ko": {"type": "one_opponent_character_filtered",
                           "filter": {"power_le": cap}}}, st, p0, p1, None)
    assert v in p1.characters, "素の 「パワーN以下」 は現在パワーで判定するので当たらないはず"

    st, p0, p1, v = board()
    execute_effect({"ko": {"type": "one_opponent_character_filtered",
                           "filter": {"truly_original_power_le": cap}}}, st, p0, p1, None)
    assert v not in p1.characters, "「元々のパワーN以下」 は印刷パワーで判定するので当たるはず"


# --------------------------------------------------------------------------- #
#  P. 「自分の場のキャラが特徴Xを持つキャラのみの場合」 は **キャラ 0 枚では不成立**
#     公式 (cardqa_op_13, OP13-097「世界の均衡など…永遠には保てぬのだ」):
#       「自分の場にキャラが0枚の場合、この【メイン】効果で相手のキャラをKOできますか？」
#       →「いいえ、できません。」
#     是正前は all(空集合) が vacuously True になり、 0 枚でも KO できてしまっていた。
#     Python/Rust とも同じ overlay 条件 (self_all_chara_feature) を読むので差分検証では沈黙。
# --------------------------------------------------------------------------- #
def test_self_all_chara_feature_not_vacuously_true_at_zero_characters():
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]

    eff = next(e for e in overlay.get("OP13-097").effects if e.get("when") == "main")
    # ⚠ 公式は 「自分のドン‼5枚をレストにできる：…の場合、…KOする」 = **コロン後**の条件。
    #   条件は効果のみを gate するので overlay では `conditional` の中にある
    #   (top-level `if` にすると任意コストの支払いごと消える、 cardqa_eb_04 の一般則)。
    assert eff.get("if") is None, "条件が top-level `if` に戻っている (任意コストを妨げる)"
    inner = next(x["conditional"] for x in eff["do"] if "conditional" in x)
    cond = inner.get("if")
    assert cond == {"self_all_chara_feature": "天竜人"}, \
        "前提が崩れた: OP13-097 の main 条件が変わっている"
    ko_prim = inner["do"][0]
    assert "ko" in ko_prim, "前提が崩れた: OP13-097 main の先頭が KO ではない"

    # 相手にコスト6以下のキャラ (KO 候補) を 1 体
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # OP01-013 cost2

    # (1) 自分の場にキャラ 0 枚 → 条件不成立 → KO は起きない
    me.characters = []
    assert eval_condition(cond, st, me) is False, \
        "キャラ 0 枚なのに条件が成立している (vacuous-true バグ)"
    before = len(opp.characters)
    if eval_condition(cond, st, me):            # engine と同じく条件成立時のみ do を回す
        execute_effect(ko_prim, st, me, opp, None)
    assert len(opp.characters) == before, \
        "0 枚では KO できないはずなのに相手キャラが消えた"

    # (2) 自分の場に 天竜人 キャラ 1 体 → 条件成立 → KO できる (対照)
    me.characters = [InPlay.of(repo.get("OP13-083"), sickness=False)]  # サターン聖 (天竜人)
    assert eval_condition(cond, st, me) is True
    if eval_condition(cond, st, me):
        execute_effect(ko_prim, st, me, opp, None)
    assert len(opp.characters) == before - 1, \
        "天竜人 が 1 体でも居れば KO できるはず"


# --------------------------------------------------------------------------- #
#  Q. OP16-081 お玉「コスト8以上のキャラがいる場合」 は **自他両陣営** を数える
#     公式 (cardqa_op_16, OP16-081):
#       「自分のコスト8以上のキャラがおらず、相手のコスト8以上のキャラがいる場合でも、
#         『相手のキャラ1枚までを、このターン中、パワー-2000』することはできますか？」
#       →「はい、できます。」
#     是正前は self_chara_filtered_count_ge (自陣のみ) だったので、 相手だけ cost8+ だと
#     起動メインが legal に出ず -2000 を撃てなかった。 exists_chara_cost_ge (両陣営) に是正。
# --------------------------------------------------------------------------- #
def test_op16_081_cost8_condition_counts_both_players():
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]

    otama = InPlay.of(repo.get("OP16-081"), sickness=False)   # お玉 = cost2 (自陣に cost8+ 無し)
    me.characters = [otama]
    big = InPlay.of(repo.get("OP07-015_r1"), sickness=False)  # cost8 (相手陣のみ)
    opp.characters = [big]
    power_before = big.power

    opt = [o for o in list_activate_main_effects(st, me, overlay)
           if o[0].card.card_id == "OP16-081"]
    assert len(opt) == 1, \
        "相手だけ cost8+ でも 起動メインは legal であるべき (自陣のみ判定だと 0 件になる)"
    fire_activate_main(st, me, opp, *opt[0])
    assert big.power == power_before - 2000, \
        "相手キャラに -2000 が入っていない (条件が自陣のみで発動を落としている)"


# --------------------------------------------------------------------------- #
#  Q2. 対照: 自他どちらにも cost8+ が居なければ OP16-081 の起動メインは発動できない
# --------------------------------------------------------------------------- #
def test_op16_081_cost8_condition_false_when_neither_has_cost8():
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP16-081"), sickness=False)]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # cost2

    # ⚠ 2026-08-05: 公式は 「このキャラをレストにできる：**コスト8以上のキャラがいる場合**、…」。
    #   コロン後の条件は **効果のみ** を gate する (cardqa_eb_04 の一般則) ので、
    #   cost8+ が居なくても **任意コスト (このキャラをレスト) は払える = legal のまま**。
    #   「条件不成立なら legal に出ない」 を期待値にすると、 行動の合法性ごと消す旧バグを固定する。
    opt = [o for o in list_activate_main_effects(st, me, overlay)
           if o[0].card.card_id == "OP16-081"]
    assert len(opt) == 1, "任意コストは条件不成立でも払えるので legal に残るべき"

    # 効果側 (パワー-2000) は条件不成立なので起きない、 が本質。
    from engine.effects import execute_effect
    eff = next(e for e in overlay.get("OP16-081").effects
               if e.get("when") == "activate_main")
    power_before = opp.characters[0].power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.characters[0])
    assert opp.characters[0].power == power_before, \
        "cost8+ が両陣営に居ないのに パワー-2000 が起きている"


# --------------------------------------------------------------------------- #
#  任意コスト「〜することができる：<条件>の場合、<効果>」 (2026-08-04 是正)
#
#  一次情報 (db/faq/cardqa_eb_04.json、 EB04-022 イッショウ):
#    「この【登場時】効果で、相手の手札が5枚以下の時に『自分の手札2枚を捨てる』ことは
#      できますか？」
#    → 「はい、できます。この場合、『相手は自身の手札2枚を好きな順番でデッキの下に置く。』は
#        行いません。」
#
#  = コロン後の「相手の手札が6枚以上ある場合」は **効果のみ** を gate する。 任意コスト
#    (自分の手札2枚を捨てる) は条件不成立でも支払える。
#
#  是正前: overlay が top-level `if: opp_hand_count_ge` を持ち、 これが _execute_event で
#    **コスト支払いの手前で** entry ごと skip していた (= 条件不成立ならコストすら払えない)。
#    Python/Rust とも同じ overlay を読むので差分検証では原理的に沈黙するクラス。
#  是正後: top-level if を除去し、 opp_hand_to_deck_bottom 等の効果を `conditional` で包む
#    (= 43 枚が既に使う Pattern B に統一)。
# --------------------------------------------------------------------------- #
def _play_setup(repo, overlay, opp_hand_n, self_hand_n=4, self_trash_n=0,
                self_deck_n=25, human=None):
    st = _state(repo, overlay, human_idx=human)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * self_hand_n
    opp.hand = [repo.get(_FILLER)] * opp_hand_n
    me.trash = [repo.get(_FILLER)] * self_trash_n
    me.deck = [repo.get(_FILLER)] * self_deck_n
    return st, me, opp


def test_eb04_022_optional_cost_payable_when_condition_false():
    """EB04-022: 相手手札 5 (=6未満) でも 自分の手札2枚を捨てられる (= コストは払える)。
    ただし『相手はデッキ下に置く』 効果は起きない (条件不成立)。"""
    repo, overlay = _repo(), _overlay()
    st, me, opp = _play_setup(repo, overlay, opp_hand_n=5, self_hand_n=4)
    src = InPlay.of(repo.get("EB04-022"), sickness=True)
    me.characters = [src]
    self_before, opp_before = len(me.hand), len(opp.hand)
    trigger_on_play(st, me, opp, src, overlay)
    # AI は任意コストを auto-pay する → 手札 2 枚は捨てられる (公式: 「はい、できます」)
    assert len(me.hand) == self_before - 2, \
        "相手手札<6 でも 自分の手札2枚を捨てる (任意コスト) は払えるべき"
    # 効果 (相手デッキ下) は条件不成立で起きない
    assert len(opp.hand) == opp_before, \
        "相手手札<6 なのに『相手はデッキ下に置く』が起きている (効果 gate 漏れ)"


def test_eb04_022_effect_fires_when_condition_true():
    """対照: 相手手札 6 なら コスト後に『相手はデッキ下に置く』 が起きる。"""
    repo, overlay = _repo(), _overlay()
    st, me, opp = _play_setup(repo, overlay, opp_hand_n=6, self_hand_n=4)
    src = InPlay.of(repo.get("EB04-022"), sickness=True)
    me.characters = [src]
    self_before, opp_before = len(me.hand), len(opp.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.hand) == self_before - 2, "コスト (手札2枚捨て) が払われていない"
    assert len(opp.hand) == opp_before - 2, "相手手札>=6 なのにデッキ下効果が起きていない"


def test_eb04_022_human_is_offered_cost_even_when_condition_false():
    """人間操作: 相手手札 5 でも 任意コストの pay/skip を提示されるべき
    (= 公式『はい、できます』 の直接検証。 是正前は entry skip で提示すらされなかった)。"""
    repo, overlay = _repo(), _overlay()
    st, me, opp = _play_setup(repo, overlay, opp_hand_n=5, self_hand_n=4, human=0)
    src = InPlay.of(repo.get("EB04-022"), sickness=True)
    me.characters = [src]
    trigger_on_play(st, me, opp, src, overlay)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        "相手手札<6 でも 人間は任意コストの支払い可否を提示されるべき (公式: はい、できます)"


def test_op10_118_on_attack_optional_cost_payable_when_condition_false():
    """OP10-118 (on_attack 経路): 相手手札 4 (=5未満) でも トラッシュ3枚をデッキ下に
    置く任意コストは払える。 効果 (相手手札1枚捨て) は条件不成立で起きない。"""
    repo, overlay = _repo(), _overlay()
    st, me, opp = _play_setup(repo, overlay, opp_hand_n=4, self_trash_n=5)
    atk = InPlay.of(repo.get("OP10-118"), sickness=False)
    me.characters = [atk]
    trash_before, opp_before = len(me.trash), len(opp.hand)
    trigger_on_attack(st, me, opp, atk, overlay)
    assert len(me.trash) == trash_before - 3, \
        "相手手札<5 でも トラッシュ3枚をデッキ下 (任意コスト) は払えるべき"
    assert len(opp.hand) == opp_before, \
        "相手手札<5 なのに『相手は手札1枚を捨てる』が起きている (効果 gate 漏れ)"
    # 対照: 相手手札5 なら効果も起きる
    st2, me2, opp2 = _play_setup(repo, overlay, opp_hand_n=5, self_trash_n=5)
    atk2 = InPlay.of(repo.get("OP10-118"), sickness=False)
    me2.characters = [atk2]
    opp2_before = len(opp2.hand)
    trigger_on_attack(st2, me2, opp2, atk2, overlay)
    assert len(opp2.hand) == opp2_before - 1, "相手手札>=5 なのに手札破棄が起きていない"


# --------------------------------------------------------------------------- #
#  素の 「コストN」 は OR (or_clauses) の中でも **現在コスト** で判定する。
#  一次情報 (cardqa、 P-084 バギー):
#    「自分のリーダーが『バギー』の場合に、 元々のコストが3か4で、 他の効果によって
#     現在のコストが2以下や5以上になっているキャラは、 アタックすることはできますか？」
#    → 「はい、できます。 …現在のコストが3か4であるキャラによるアタックが宣言できなく
#       なる効果です。」
#  P-084 の overlay は `{"or_clauses": [{"cost_eq": 3}, {"cost_eq": 4}]}`。 OR の中の
#  cost_eq が印刷コストで判定されると、 現在コスト2に下げたキャラも 「印刷4」 のまま
#  アタック不可になり公式に反する (Python/Rust とも同じ overlay を読むので差分検証では沈黙)。
# --------------------------------------------------------------------------- #
def _p084_board(repo, overlay, cost_minus):
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP09-042"), sickness=False))  # バギー
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    baggy = InPlay.of(repo.get("P-084"), sickness=False)
    victim = InPlay.of(repo.get("PRB02-003"), sickness=False)  # 印刷コスト 4
    if cost_minus:
        victim.cost_minus_until_turn_end = cost_minus
    p0.characters = [baggy, victim]
    for p in (p0, p1):
        p.deck = [repo.get(_FILLER)] * 10
        p.life = [repo.get(_FILLER)] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=overlay)
    st.turn_player_idx, st.turn_number = 0, 5
    evaluate_static_effects(st, overlay)
    return victim


def test_p084_cannot_attack_filter_uses_current_cost_inside_or_clauses():
    """P-084 「コスト3と4のキャラはアタック不可」 は OR の中でも現在コストで判定する。"""
    repo, overlay = _repo(), _overlay()
    # 印刷コスト4 → 現在コスト2: 公式は 「アタックできる」 = アタック不可にしてはいけない。
    v_reduced = _p084_board(repo, overlay, cost_minus=2)
    assert v_reduced.card.cost == 4 and v_reduced.base_cost == 2
    assert not v_reduced.cannot_attack_static, (
        "現在コスト2のキャラが 印刷コスト4 のままアタック不可にされている。 "
        "or_clauses 内の cost_eq が印刷値で判定されている (公式 cardqa: 現在コストで判定)"
    )


def test_p084_cannot_attack_filter_restricts_current_cost_match():
    """対照: 現在コストが実際に4なら アタック不可 (静的効果が効いていることの確認)。"""
    repo, overlay = _repo(), _overlay()
    v = _p084_board(repo, overlay, cost_minus=0)  # 印刷=現在=4
    assert v.base_cost == 4
    assert v.cannot_attack_static, "現在コスト4のキャラは P-084 でアタック不可のはず"
# ---------------------------------------------------------------------------
# 任意コスト 「〜できる：<条件>の場合、<効果>」 (2026-08-04、 cron 是正の残り分)
#   cardqa_eb_04 の一般則: コロン後の条件は **効果のみ** を gate する。
#   任意コストは条件不成立でも支払える (支払って何も起きない、 が公式)。
#   cron は EB04-022 系 4 枚を是正したが、 **同じ opp_hand 系が 4 枚残っていた**。
# ---------------------------------------------------------------------------

def _opt_cost_board(repo, ov, card_id: str, opp_hand: int, *, face_up_life: int = 0):
    import random
    from engine.core import GameState, InPlay, Phase, Player
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    src = InPlay.of(repo.get(card_id), sickness=False)
    p0.characters = [src]
    p0.hand = [repo.get("OP01-013")] * 3
    p1.hand = [repo.get("OP01-013")] * opp_hand
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 20
        p.life = [repo.get("OP01-013")] * 3
    p0.trash = [repo.get("OP01-013")] * 4
    p0.don_active = 8
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    p0.life_face_up = [i < (face_up_life) for i in range(len(p0.life))]
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 5
    return st, p0, p1, src


def test_activate_main_optional_cost_not_gated_by_post_colon_condition():
    """【起動メイン】「コスト：相手の手札がN枚以上ある場合、効果」 は条件不成立でも起動できる。

    是正前は top-level `if` が **legal_actions の段階で** 起動メインを消しており、
    「相手の手札が少ないとローを手札に戻せない」 等、 実在ラインが engine から消えていた。
    """
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay
    from engine.game import legal_actions

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    for card_id, threshold in (("OP05-082", 6), ("OP07-047", 6), ("OP16-047", 8)):
        for opp_hand in (threshold - 1, threshold):
            st, p0, p1, src = _opt_cost_board(repo, ov, card_id, opp_hand)
            acts = [a for a in legal_actions(st) if type(a).__name__ == "ActivateMain"]
            assert acts, (
                f"{card_id}: 相手手札 {opp_hand} で起動メインが legal に出ない "
                "(コロン後の条件がコスト支払いを妨げている)"
            )


def test_activate_main_effect_still_gated_when_condition_false():
    """対照: コストは払えるが、 条件不成立なら **効果は起きない**。"""
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay
    from engine.game import legal_actions, apply_action

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    st, p0, p1, src = _opt_cost_board(repo, ov, "OP16-047", 7)   # 閾値 8 未満
    before = len(p1.hand)
    acts = [a for a in legal_actions(st) if type(a).__name__ == "ActivateMain"]
    assert acts
    apply_action(st, acts[0])
    assert len(p1.hand) == before, "条件不成立なのに相手の手札が減っている"
    assert src.rested, "コスト (このキャラをレスト) が支払われていない"


def test_st13_009_optional_cost_is_implemented_not_free():
    """ST13-009: 「自分の表向きのライフ1枚を裏向きにできる：」 が **未実装でタダ撃ち** だった。

    公式は任意コスト。 表向きライフが 0 枚なら払えない = 効果も起きない。
    """
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_on_play

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    # 表向きライフ 0 = コストを払えない → 相手ライフは減らない
    st, p0, p1, src = _opt_cost_board(repo, ov, "ST13-009", 8, face_up_life=0)
    before = len(p1.life)
    trigger_on_play(st, p0, p1, src, ov)
    assert len(p1.life) == before, "表向きライフ 0 でコストを払えないのに効果が起きている (タダ撃ち)"

    # 表向きライフ 1 + 条件成立 = コストを払って効果が起きる
    st, p0, p1, src = _opt_cost_board(repo, ov, "ST13-009", 8, face_up_life=1)
    before = len(p1.life)
    trigger_on_play(st, p0, p1, src, ov)
    assert len(p1.life) == before - 1, "条件成立なのに相手ライフが減っていない"
    assert p0.face_up_life_count == 0, "コスト (表向きライフ 1 枚を裏向き) が支払われていない"

    # 表向きライフ 1 + 条件不成立 = コストは払えるが効果は起きない
    st, p0, p1, src = _opt_cost_board(repo, ov, "ST13-009", 6, face_up_life=1)
    before = len(p1.life)
    trigger_on_play(st, p0, p1, src, ov)
    assert len(p1.life) == before, "条件不成立なのに相手ライフが減っている"


_WHEN_MARK = {
    "on_play": "登場時", "activate_main": "起動メイン", "main": "メイン",
    "counter": "カウンター", "on_attack": "アタック時", "on_ko": "KO時",
    "end_of_turn": "自分のターン終了時", "opp_attack": "相手のアタック時",
    "on_block": "ブロック時",
}


def _clause_for(text: str, when: str):
    """公式テキストから **その効果の節だけ** を切り出す。

    ⚠ 1 枚のカードは複数の節を持ち、 節ごとに 「〜できる：」 の有無が違う。
    カード全体の text で判定すると **別の節の 「できる：」 を拾って誤変換する**
    (2026-08-05 に EB03-006 で実際に起きた: 【登場時】に 「できる：」 があり、
     【起動メイン】の発動条件を誤って効果側へ移してしまった)。
    """
    import re as _re
    t = _re.sub(r"[(（][^)）]*[)）]", "", _re.sub(r"\s+", "", text or ""))
    mk = _WHEN_MARK.get(when)
    if not mk:
        return t
    m = _re.search(r"【" + _re.escape(mk) + r"】", t)
    if not m:
        return None
    rest = t[m.end():]
    # 直後に続く 【ターン1回】【ドン‼×N】 等の修飾マーカーは読み飛ばす
    while True:
        mm = _re.match(r"【[^】]{1,10}】", rest)
        if mm and ("ターン" in mm.group(0) or "ドン" in mm.group(0)):
            rest = rest[mm.end():]
            continue
        break
    nxt = _re.search(r"【", rest)
    return rest[:nxt.start()] if nxt else rest


def test_no_optional_cost_remains_gated_by_post_colon_condition():
    """「〜できる：<条件>の場合、効果」 に top-level `if` が残っていない (全語彙・全カード)。

    コロン後の条件は **効果のみ** を gate する (cardqa_eb_04 の一般則)。 top-level `if` に
    置くと **行動の合法性ごと消える** ので、 任意コストを払う選択が engine から無くなる。

    ⚠ `cost` ブロックを持たないエントリは除外する。 そちらは 「任意コスト自体が overlay に
    未実装 (= 効果がタダ撃ちできる)」 という **別の欠陥** で、 カードごとにコストを実装する
    必要がある (ST13-009 で実施)。 残数は
    `test_optional_cost_missing_backlog_is_tracked` で固定している。
    """
    import re
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    bad = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list):
            continue
        card = cards.get(cid) or {}
        for eff in effs:
            if not isinstance(eff, dict) or not isinstance(eff.get("if"), dict):
                continue
            if not eff.get("cost"):
                continue          # 任意コスト未実装 = 別 issue (下のテストで数を固定)
            # ⚠ replace_* / 静的 when の `if` は **構造的な対象指定** (target / by_opp_effect 等)
            #   であってコロン後の条件ではない。 節マーカーも無く全文照合になるため除外する
            #   (2026-08-05 に OP05-032 を誤変換した)。
            if eff.get("when") not in _WHEN_MARK and eff.get("when") != "trigger":
                continue
            src = "trigger" if eff.get("when") == "trigger" else "text"
            # ⚠ **その効果の節だけ** で判定する。 カード全体の text を見ると別の節の
            #   「できる：」 を拾う (EB03-006 で実際に誤変換した)。
            clause = _clause_for(card.get(src) or "", eff.get("when"))
            if not clause:
                continue
            # ⚠ 目印は 「できる」 ではなく **「：」** (cardqa_st_06:「「：」以前に表記されている
            #   指示はすべて "発動コスト"」)。 「できる[：:]」 で探すと **コスト記号形**
            #   (「③(…できる)：」「ドン!!-1：」) を取りこぼす — 注釈括弧を除去すると
            #   「③：」 になり 「できる」 が消えるため。 2026-08-05 に 84 エントリ / 55 枚を
            #   この盲点で見落としていた (cron が検出)。
            m = re.search(r"[：:]", clause)
            if not m or "場合" not in clause[m.end():]:
                continue
            if "場合" in clause[:m.start()]:
                continue          # コロン前にも条件 = top-level if が妥当
            # ⚠ entry `if` が **発動元自身のコスト閾値** (self_inplay_cost_*) の時は、
            #   それは 「コストN以上のこのキャラをトラッシュ…」 のような **コロン前=コスト節** の
            #   条件 (= どのコストを払えるか) であって、 コロン後の効果条件ではない。
            #   OP16-084 モモの助: 「コスト20以上のこのキャラをトラッシュに置くことができる：
            #   場のドン9枚以上ある場合、…登場」 — コロン後 (ドン9枚) は do の conditional、
            #   entry `if:{self_inplay_cost_ge:20}` は前段のコスト制限 (cardqa_op_16 57ce5506a587)。
            if any(k in ("self_inplay_cost_ge", "self_inplay_cost_le", "self_inplay_cost_eq")
                   for k in eff.get("if", {})):
                continue
            bad.append(f"{cid}[{src}]: {clause[:80]}")
    assert not bad, (
        "コロン後の条件が top-level `if` のままで、 任意コストの支払いを妨げている:\n  "
        + "\n  ".join(bad[:40])
    )


def test_optional_cost_missing_backlog_is_tracked():
    """「〜できる：」 の任意コストが overlay に **未実装** な残数を固定する。

    この形は 「コストを払わずに効果だけ起きる」 = タダ撃ち。 条件を conditional へ移しても
    直らない (コスト自体が無い) ので、 カードごとにコストを実装するしかない。
    残数が **増えたら** 新弾等で同じ欠陥が入ったということなので落とす。
    """
    import re
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    missing = set()
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list):
            continue
        card = cards.get(cid) or {}
        for eff in effs:
            if not isinstance(eff, dict) or not isinstance(eff.get("if"), dict):
                continue
            if eff.get("cost"):
                continue
            src = "trigger" if eff.get("when") == "trigger" else "text"
            clause = _clause_for(card.get(src) or "", eff.get("when"))
            if not clause:
                continue
            # ⚠ `optional_cost_then` の中にコストを持つ形も 「実装済」 (cost ブロックが無いだけ)
            if "optional_cost_then" in json.dumps(eff, ensure_ascii=False):
                continue
            m = re.search(r"できる[：:]", clause)
            if m and "場合" in clause[m.end():] and "場合" not in clause[:m.start()]:
                missing.add(cid.split("_")[0])
    # 2026-08-05: 節単位 + optional_cost_then を数えると **実測 0 枚**。
    #   当初 26 枚と見えたのは (a) カード全体の text で別の節の 「できる：」 を拾った
    #   (b) `optional_cost_then` 内のコストを見落とした、 の 2 つの誤検出だった。
    # 増えたら退行。
    assert len(missing) == 0, (
        f"任意コスト未実装 (タダ撃ち) が {len(missing)} 枚に増えた:\n  "
        + "\n  ".join(sorted(missing))
    )


# --------------------------------------------------------------------------- #
#  「相手がイベントを発動した時」 の reactive は、 反応対象のイベント効果を
#   **処理した後** に解決する (発動そのものへの割り込みではない)。
#  一次情報 (db/faq/cardqa_op_06、 OP06-044 ギオン):
#    「相手がイベントの【カウンター】効果を発動した時、 この【自分のターン中】効果で相手は
#      自身の手札1枚をデッキの下に置くのは、 その【カウンター】効果の処理を行う前ですか？」
#    → 「いいえ、 相手が使用したイベントの【カウンター】効果を処理した後、 この【自分のターン中】
#        効果で相手が自身の手札1枚をデッキの下に置きます。」
#  是正前: _pop_next_event が turn_player 側イベントを優先するため、 ギオン (=攻撃側=turn) の
#         reactive が counter (=防御側=非turn) より先に pop され、 順序が逆転していた。
#         Python/Rust とも同じ overlay を読むので差分検証では原理的に沈黙する型。
# --------------------------------------------------------------------------- #
def test_gion_reactive_resolves_after_counter_event_effect():
    """OP06-044 ギオンの reactive は 相手カウンターの効果を処理した **後** に発火する。"""
    from engine.effects import trigger_counter_event
    repo, overlay = _repo(), _overlay()
    p0 = Player(name="ATK", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="DEF", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(_FILLER)] * 25
        p.life = [repo.get(_FILLER)] * 3
    # 攻撃側 (turn player) に ギオン + カウンターの -3000 対象になる素キャラ。
    gion = InPlay.of(repo.get("OP06-044"), sickness=False)
    extra = InPlay.of(repo.get(_FILLER), sickness=False)
    p0.characters = [gion, extra]
    # 防御側は手札4枚 + カウンターコスト (ドン-1) を払える場のドン。
    p1.hand = [repo.get(_FILLER)] * 4
    p1.don_active, p1.don_rested = 3, 0
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=overlay)
    st.turn_player_idx, st.turn_number = 0, 9
    st.log = []
    # OP02-089 地獄の審判 (【カウンター】相手2枚 パワー-3000)。 防御側 p1 が使用。
    trigger_counter_event(st, p1, p0, repo.get("OP02-089_p1"), overlay)
    order = [l for l in st.log if "パワー-3000" in l or "デッキ下" in l]
    assert len(order) >= 2, f"両効果のログが揃っていない: {order}"
    # 是正前は ['...デッキ下', '...パワー-3000'] の逆順だった → この assert が落ちる。
    assert "パワー-3000" in order[0], (
        f"カウンター効果が先に解決していない (公式違反): {order}"
    )
    assert "デッキ下" in order[1], (
        f"ギオンの reactive がカウンター効果より先に発火している (公式違反): {order}"
    )


# ---------------------------------------------------------------------------
# 両陣営 target の AI auto-pick (2026-08-04)
#   公式は 「キャラN枚**まで**」 = 0 枚を選べる (overlay 64 件すべてこの形、 必須形は無い)。
#   → **AI は相手が居なければ何も選ばない**。 自陣を送るのはほぼ常に悪手。
#   → **人間は両陣営から選べる** (option parity は維持する)。
# ---------------------------------------------------------------------------

def test_ai_does_not_auto_target_own_board_when_opponent_is_empty():
    """相手の場が空の時、 AI が自分のキャラを巻き込まない。

    両陣営 target 化 (2026-08-04) の副作用で、 相手候補が無いと自陣を auto-pick して
    自分のキャラをデッキの下/手札へ送る自滅が 46 枚に広がっていた。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_on_play

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    for cid in ("OP01-070", "ST03-009", "OP06-046"):
        st, p0, p1 = _either_board(repo, ov, ["OP01-013", "OP01-016"], [])
        src = InPlay.of(repo.get(cid), sickness=True)
        p0.characters.append(src)
        before = len(p0.characters)
        trigger_on_play(st, p0, p1, src, ov)
        assert len(p0.characters) == before, (
            f"{cid}: 相手の場が空なのに自分のキャラを巻き込んだ "
            "(公式は 「N枚まで」 = 0 枚可なので、 AI は何も選ばないのが正しい)"
        )


def test_human_can_still_pick_either_side():
    """AI の skip は **人間の選択肢を削らない** (両陣営が modal に出る)。"""
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _either_board(repo, ov, ["OP01-013"], ["OP01-016"])
    st.human_player_idx = 0

    execute_effect({"return_to_deck_bottom": "one_character_either_cost_le_5"},
                   st, p0, p1, None)
    pc = st.pending_choice
    assert pc is not None, "人間なのに選択 modal が立っていない"
    raw = pc.get("cards") or pc.get("candidates") or []
    iids = {c.get("iid") if isinstance(c, dict) else c for c in raw}
    assert p0.characters[0].instance_id in iids, "自陣のキャラが modal に出ていない"
    assert p1.characters[0].instance_id in iids, "相手のキャラが modal に出ていない"


def test_all_either_target_cards_are_optional_up_to_n():
    """両陣営 spec を使う効果が全て 公式 「N枚**まで**」 (= 0 枚可) であることを固定。

    もし 「N枚を」 の必須形カードがこの spec 群を使い始めたら、 「相手が居なければ
    何も選ばない」 という AI の auto-pick は **ルール違反** になる (可能な限り解決する義務)。
    その時は 「必須なら自陣から選ぶ」 分岐が要る。
    """
    import re
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    either = re.compile(r"one_character_either|one_inplay_either|one_inplay(_except_self)?_cost_le")
    mandatory = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list):
            continue
        card = cards.get(cid) or {}
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            if not either.search(json.dumps(eff, ensure_ascii=False)):
                continue
            src = "trigger" if eff.get("when") == "trigger" else "text"
            text = re.sub(r"[(（][^)）]*[)）]", "",
                          re.sub(r"\s+", "", card.get(src) or ""))
            m = re.search(r"キャラ\d*枚(まで)?", text)
            # ⭐ spec に "mandatory": true があれば 「相手が居なければ自陣から選ぶ」 分岐が
            #   実装済 (= この監査が求めている対応そのもの) なので対象外。
            #   OP06-043 アラマキ が第 1 号 (2026-08-10、 発動コストの必須両陣営ターゲット)。
            has_mandatory_flag = '"mandatory": true' in json.dumps(eff, ensure_ascii=False)
            if m and not m.group(1) and not has_mandatory_flag:
                mandatory.append(f"{cid}: {text[:70]}")
    assert not mandatory, (
        "必須形 「キャラN枚を」 が両陣営 spec を使っている。 AI の 「相手が居なければ 0 枚」 は "
        "この形ではルール違反になるので、 必須なら自陣から選ぶ分岐が要る:\n  "
        + "\n  ".join(mandatory)
    )


# --------------------------------------------------------------------------- #
#  条件付き【速攻】は 相手の場のドン枚数を毎回再評価する
#     公式 Q&A (cardqa_eb_02、 EB02-061 モンキー・D・ルフィ):
#       「自分のターン中、相手のドン!!が5枚あるときにこのキャラを登場し、その後他の効果で
#         相手のドン!!が4枚になりました。この場合、このキャラはアタックできますか？」
#       → 「いいえ、できません。」
#     カードテキスト = 「自分のリーダーが多色で、相手の場のドン!!が5枚以上ある場合、
#                       このキャラは【速攻】を得る。」 (= 2 条件の AND)
#     是正前の overlay は if に leader_color_multi しか持たず opp_don_count_ge:5 が欠落 →
#     相手ドン4枚でも【速攻】を得て、 召喚酔いキャラがアタックできてしまっていた (公式違反)。
#     Python/Rust とも同じ overlay を読むので差分検証では沈黙する class。
# --------------------------------------------------------------------------- #
def test_eb02_061_conditional_rush_requires_opp_don_ge_5():
    """EB02-061 の条件付き【速攻】は 相手の場のドンが5枚未満なら付与されない。"""
    repo, overlay = _repo(), _overlay()

    def _rush_when_opp_don(opp_don: int) -> bool:
        # 多色リーダー (EB04-001 赤/黄) の下に EB02-061 を召喚酔いで置く。
        st = _state(repo, overlay, leader0="EB04-001")
        me, opp = st.players[0], st.players[1]
        ruffy = InPlay.of(repo.get("EB02-061"), sickness=True)
        me.characters = [ruffy]
        opp.don_active = opp_don
        evaluate_static_effects(st, overlay)
        granted = set(ruffy.granted_keywords) | set(
            getattr(ruffy, "static_granted_keywords", set())
        )
        return "速攻" in granted

    # 相手ドン5枚 → 【速攻】あり (登場ターンにアタック可)
    assert _rush_when_opp_don(5), "相手ドン5枚で【速攻】が付与されていない (前提崩れ)"
    # 相手ドン4枚 → 【速攻】なし = 召喚酔いでアタック不可 (公式「いいえ」)
    # 是正前 (opp_don_count_ge 欠落) はここが True になり落ちる。
    assert not _rush_when_opp_don(4), (
        "相手ドン4枚でも【速攻】が付与されている (公式違反: opp_don_count_ge:5 欠落)"
    )

def test_converted_cost_not_gated_entries_really_have_optional_cost():
    """`[cost-not-gated]` と印を付けた効果が、 **自分の節に** 「〜できる：<条件>」 を持つ。

    ⚠ カード全体の text で判定すると **別の節の 「できる：」 を拾って誤変換する**。
    2026-08-05 に EB03-006 で実際に起きた (【登場時】の 「できる：」 を見て、
    【起動メイン】の発動条件を効果側へ移してしまい、 条件不成立でも起動可能になっていた)。
    """
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    bad = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list):
            continue
        card = cards.get(cid) or {}
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            if "[cost-not-gated]" not in (eff.get("_text") or ""):
                continue
            when = eff.get("when")
            src = "trigger" if when == "trigger" else "text"
            text = card.get(src) or ""
            if not text:
                # ⚠ overlay にあるが cards.json に無い card_id がある (P-081)。
                #   同 base の パラレルの本文で補う。
                base = cid.split("_")[0]
                sib = next((c for c in cards
                            if c.split("_")[0] == base and (cards[c].get(src) or "")), None)
                text = (cards.get(sib) or {}).get(src, "") if sib else ""
            clause = _clause_for(text, when)
            if clause is None:
                bad.append(f"{cid}[{when}]: 該当節が見つからない")
                continue
            # ⚠ 目印は 「できる」 ではなく **「：」** (cardqa_st_06)。 コスト記号形
            #   (「③(…できる)：」「ドン!!-1：」) は注釈括弧を除去すると 「できる」 が消える。
            m = re.search(r"[：:]", clause)
            if not m or "場合" not in clause[m.end():]:
                bad.append(f"{cid}[{when}]: 自分の節にコロン後の条件が無い — {clause[:70]}")
    assert not bad, (
        "別の節の 「できる：」 を拾って誤変換している (発動条件を効果側へ移すと "
        "条件不成立でも発動できてしまう):\n  " + "\n  ".join(bad[:30])
    )


# =========================================================================== #
#  公式 Q&A 全件保証 (2026-08-05 バッチ)。 各テストは overlay/engine が公式どおりかを
#  engine を実際に動かして盤面差分で確認する。 docstring に一次情報 (cardqa) を引用。
# =========================================================================== #


def test_op08_019_pump_self_runs_when_opponent_has_no_character():
    """OP08-019 バクバク食 【メイン】/【カウンター】= 「相手のキャラ1枚までを、この
    ターン中、パワー-3000。その後、自分のキャラ1枚までを、このターン中、パワー+3000。」
    一次情報 (cardqa_op_08): 「相手の場にキャラが無いとき、この【メイン】/【カウンター】
    効果で自分のキャラ1枚をパワー+3000できますか？」→「はい、できます。」
    前段 (相手 -3000) が対象不在で空振りでも、後段 (自分 +3000) は独立実行される
    (settled その後 tail 原則)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    ally = InPlay.of(repo.get("OP01-013"), sickness=False)  # 印刷パワー 3000
    me.characters = [ally]
    opp.characters = []  # 相手キャラ無し
    base = ally.power
    execute_effect({"power_pump": {"target": "one_opponent_character_any",
                                   "amount": -3000, "duration": "turn"}}, st, me, opp, None)
    execute_effect({"power_pump": {"target": "one_self_character_any",
                                   "amount": 3000, "duration": "turn"}}, st, me, opp, None)
    assert ally.power == base + 3000, (
        "相手キャラ0でも自分のキャラ+3000は入るべき (公式 cardqa_op_08: はい、できます)"
    )


def test_st34_002_ko_tail_runs_when_don_deck_is_empty():
    """ST34-002 クラッカー 【登場時】= 「ドン!!デッキからドン!!1枚までを、レストで追加する。
    その後、相手のコスト2以下のキャラ1枚までを、KOする。」
    一次情報 (cardqa_st_34): 「ドン!!デッキが0枚の場合、この【登場時】効果で相手のコスト
    2以下のキャラ1枚をKOできますか？」→「はい、できます。」
    前段 (ドン追加) がドンデッキ0で空振りでも、後段 (KO) は独立実行される。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 0  # ドンデッキ空
    don_before = me.don_rested
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # 印刷コスト 2
    opp.characters = [victim]
    execute_effect({"add_rested_don": 1}, st, me, opp, None)
    assert me.don_rested == don_before, "ドンデッキ0なのにドンが増えている (前提崩れ)"
    execute_effect({"ko": "one_opponent_character_cost_le_2cost"}, st, me, opp, None)
    assert victim not in opp.characters, (
        "ドンデッキ0でも後段のKOは実行されるべき (公式 cardqa_st_34: はい、できます)"
    )


def test_op11_013_disable_blocker_snapshots_board_at_effect_time():
    """OP11-013 プリンス・グルス 【アタック時】= 「相手のパワー2000以下のキャラすべては、
    このターン中、【ブロッカー】を発動できない。」
    一次情報 (cardqa_op_11): 「この【アタック時】効果を発動し、その後そのターン中に
    登場した相手のパワー2000以下のキャラは、そのターン中【ブロッカー】を発動できますか？」
    →「はい、できます。」
    効果は発動時点に居た該当キャラにのみフラグを立てる (スナップショット)。後から登場した
    キャラは対象外なのでブロック可能。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    present = InPlay.of(repo.get("OP01-016"), sickness=False)  # 印刷パワー 2000
    opp.characters = [present]
    execute_effect({"disable_blocker": {"target": {"type": "all_opponent_chara_filtered",
                    "filter": {"power_le": 2000}}, "duration": "turn"}}, st, me, opp, None)
    assert present.blocker_disabled_until_turn_end, (
        "発動時点に居たパワー2000以下のキャラはブロッカー無効になるべき (前提崩れ)"
    )
    later = InPlay.of(repo.get("OP01-016"), sickness=True)  # 効果後に登場、 パワー 2000
    opp.characters.append(later)
    assert not later.blocker_disabled_until_turn_end, (
        "効果発動後に登場したキャラはブロッカー無効の対象外 = ブロック可能 "
        "(公式 cardqa_op_11: はい、できます)"
    )


def test_op02_069_draw_to_hand_size_never_forces_discard():
    """OP02-069 DEATH WINK 【カウンター】= 「...その後、自分の手札が2枚になるように
    カードを引く。」
    一次情報 (cardqa_op_02): 「手札が3枚以上の場合、この【カウンター】効果で手札が2枚に
    なるようにカードを捨てる必要がありますか？」→「いいえ、捨てる必要はありません。」
    draw_to_hand_size は不足分のみドロー。手札が既に目標以上なら 0 ドロー・捨てもしない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 10
    execute_effect({"draw_to_hand_size": 2}, st, me, opp, None)
    assert len(me.hand) == 3, (
        "手札3枚 (>目標2) では捨てもドローもしないべき (公式 cardqa_op_02: 捨てる必要なし)"
    )
    me.hand = [repo.get(_FILLER)] * 1  # 対照: 1枚 → 2枚になるよう +1 ドロー
    execute_effect({"draw_to_hand_size": 2}, st, me, opp, None)
    assert len(me.hand) == 2, "手札1枚なら2枚になるようドローするべき (対照)"


def test_op13_119_opp_play_requires_prior_bounce():
    """OP13-119 エース 【登場時】= 「...その後、相手のコスト5以下のキャラ1枚までを、
    持ち主の手札に戻してもよい。そうした場合、相手は自身の手札からコスト4以下のキャラ
    カードを登場させる。」
    一次情報 (cardqa_op_13): 「この【登場時】効果で相手のコスト5以下のキャラ1枚を手札に
    戻さなかった場合、相手は自身の手札からコスト4以下のキャラカードを登場させることは
    できますか？」→「いいえ、できません。」
    「そうした場合」= 実際に戻した場合のみ相手の登場が発動 (require_prior_bounce)。"""
    repo, overlay = _repo(), _overlay()
    # bounce なし: 相手の場にキャラ無し → 戻す対象0 → 相手は登場しない
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = []
    opp.hand = [repo.get("OP01-013")] * 3  # cost2 (≤4) = 登場可能な候補
    chars_before = len(opp.characters)
    execute_effect({"return_to_hand": "one_opponent_character_cost_le_5"}, st, me, opp, None)
    assert st.last_return_to_hand_success is False, "戻す対象0なら bounce 不成立のはず"
    execute_effect({"force_opp_play_from_hand": {"cost_le": 4, "count": 1,
                    "require_prior_bounce": True}}, st, me, opp, None)
    assert len(opp.characters) == chars_before, (
        "手札に戻さなかった場合、相手はコスト4以下を登場できない "
        "(公式 cardqa_op_13: いいえ、できません)"
    )
    # 対照: bounce あり → 相手は登場する
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    opp2.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]  # cost2 (≤5) 戻せる
    opp2.hand = [repo.get("OP01-013")] * 3
    execute_effect({"return_to_hand": "one_opponent_character_cost_le_5"}, st2, me2, opp2, None)
    assert st2.last_return_to_hand_success is True, "戻す対象ありなら bounce 成立のはず"
    n_after_bounce = len(opp2.characters)
    execute_effect({"force_opp_play_from_hand": {"cost_le": 4, "count": 1,
                    "require_prior_bounce": True}}, st2, me2, opp2, None)
    assert len(opp2.characters) == n_after_bounce + 1, (
        "手札に戻した場合、相手はコスト4以下を登場する (対照)"
    )


def test_op06_074_negate_does_not_strip_external_power_buff():
    """OP06-074 ゼファー 【登場時】= 「相手のキャラ1枚までを、このターン中、効果を無効に
    する。その後、そのキャラのパワーが5000以下の場合、KOする。」
    一次情報 (cardqa_op_06): 「この【登場時】効果で選んだキャラが、他のカードやドン!!
    カードによって『このターン中、パワー+1000。』などの効果を受けている場合、この
    【登場時】効果でパワーは元の値に戻りますか？」→「いいえ、元の値に戻りません。」
    効果無効は当該カード自身の効果のみを無効化し、他カード由来の +1000 は残る。その後の
    KO 判定は現在パワー (5000+1000=6000 > 5000) で行うので KO されない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST34-002"), sickness=False)  # 印刷パワー 5000
    victim.turn_buff = 1000  # 他カード由来の「このターン中 +1000」
    opp.characters = [victim]
    assert victim.power == 6000, "前提: 5000 + 外部 1000 = 6000"
    execute_effect({"negate_effect": "one_opponent_character_any"}, st, me, opp, None)
    assert victim.power == 6000, (
        "効果無効で外部 +1000 が剥がれてはならない (公式 cardqa_op_06: 元の値に戻らない)"
    )
    execute_effect({"ko": "opp_just_negated_power_le_5000"}, st, me, opp, None)
    assert victim in opp.characters, (
        "現在パワー6000 (>5000) なので KO されないべき (公式 cardqa_op_06)"
    )
    # 対照: +1000 が無ければ 5000 ≤5000 で KO される
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    victim2 = InPlay.of(repo.get("ST34-002"), sickness=False)  # 5000
    opp2.characters = [victim2]
    execute_effect({"negate_effect": "one_opponent_character_any"}, st2, me2, opp2, None)
    execute_effect({"ko": "opp_just_negated_power_le_5000"}, st2, me2, opp2, None)
    assert victim2 not in opp2.characters, "現在パワー5000 (≤5000) なら KO される (対照)"


def test_op02_069_trigger_return_can_target_own_character():
    """OP02-069 DEATH WINK 【トリガー】= 「コスト7以下のキャラ1枚までを、持ち主の手札に
    戻す。」(「相手の」修飾なし = 両陣営が対象)
    一次情報 (cardqa_op_02): 「この【トリガー】効果で自分のキャラを手札に戻すことは
    できますか？」→「はい、できます。」

    ⚠ 検証は **人間経路** で行う (既存 test_unqualified_character_target_can_hit_own_board
    と同じ理由)。 「1枚まで」= 0 枚可なので AI の auto-pick は 「相手が居なければ 0 枚」 が
    正しく、 自陣を戻すことを期待値にすると自滅を固定してしまう。 公式が問うのは 「自キャラを
    対象に **できる** か」 = 候補に入るか、 なので modal の候補集合で検証する。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.human_player_idx = 0
    me, opp = st.players[0], st.players[1]
    ally = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost 2 ≤7
    me.characters = [ally]
    opp.characters = []  # 相手キャラ無し → 自キャラしか候補になりえない
    execute_effect({"return_to_hand": "one_character_either_cost_le_7"}, st, me, opp, None)
    pc = st.pending_choice
    assert pc is not None, "相手の場が空でも自キャラが候補になるはず (modal が立たない)"
    raw = pc.get("cards") or pc.get("candidates") or []
    iids = {c.get("iid") if isinstance(c, dict) else c for c in raw}
    assert ally.instance_id in iids, (
        "「相手の」無しの『持ち主の手札に戻す』は自分のキャラも対象になれるべき "
        "(公式 cardqa_op_02: はい、できます)"
    )


def test_st06_004_double_attack_reevaluated_when_cost0_char_leaves():
    """ST06-004 スモーカー 【ドン!!×1】= 「コスト0のキャラがいる場合、このキャラは
    【ダブルアタック】を得る。」
    一次情報 (cardqa_st_06): 「ダメージステップより前にコスト0のキャラが場にいない状態に
    なった場合、このキャラは【ダブルアタック】を失い、リーダーへ与えるダメージは1になります。」
    【ドン!!×1】は静的効果 (evaluate_static_effects で毎回再評価) なので、条件のコスト0
    キャラが離れると【ダブルアタック】も外れる。ダメージは damage step (カウンターフェイズ
    後) に is_double_attack_now を読む (engine/game.py) ので、この再評価が反映される。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("ST06-004"), sickness=False)
    smoker.attached_dons = 1  # 【ドン!!×1】成立
    zero = InPlay.of(repo.get("OP01-013"), sickness=False)  # 印刷コスト 2
    zero.cost_minus_until_turn_end = 2  # → 現在コスト 0
    me.characters = [smoker, zero]
    evaluate_static_effects(st, overlay)
    assert smoker.is_double_attack_now, "コスト0キャラが居れば【ダブルアタック】取得 (前提)"
    me.characters = [smoker]  # コスト0キャラが場を離れる
    evaluate_static_effects(st, overlay)
    assert not smoker.is_double_attack_now, (
        "コスト0キャラが離れたら【ダブルアタック】を失うべき (公式 cardqa_st_06)"
    )


# =========================================================================== #
#  FAQ 全件保証 バッチ (2026-08-05): cardqa_op_16 / st_10 / op_12 / st_09 /
#  eb_01 / st_33 ほか。 外部オラクル (公式 Q&A) と engine 挙動を突き合わせる。
# =========================================================================== #
def test_op16_094_attach_rested_don_restricted_to_wano():
    """OP16-094 エース【起動メイン】: レストのドン付与は《ワノ国》キャラ/リーダー限定。

    一次情報 (cardqa_op_16): 「この【起動メイン】効果で、自分の特徴《ワノ国》を持たない
    キャラ1枚にレストのドン!!1枚を付与することはできますか？」→「いいえ、できません。」
    """
    from engine.effects import _resolve_target
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP16-094"), sickness=False)   # 《ワノ国》
    nonwano = InPlay.of(repo.get("OP01-013"), sickness=False)  # 麦わらの一味 (非ワノ国)
    me.characters = [src, nonwano]
    tgt = _resolve_target({"type": "one_self_chara_or_leader_filtered",
                           "filter": {"feature": "ワノ国"}}, st, me, opp, src)
    assert nonwano not in tgt, "非《ワノ国》キャラが付与対象になってはいけない"
    assert all("ワノ国" in t.card.features for t in tgt), "対象は《ワノ国》のみ"


def test_st10_004_rush_once_granted_persists_when_condition_lost():
    """ST10-004 サンジ【登場時】: 相手パワー5000以上がいる時に得た【速攻】は、
    その後相手キャラが居なくなっても そのターン中 保持される。

    一次情報 (cardqa_st_10): 「このキャラを登場させ、この【登場時】効果で【速攻】を得た後、
    そのターン中に相手の場にパワー5000以上のキャラがいない状態になりました。このとき、
    そのターンにこのキャラはアタックできますか？」→「はい、できます。」
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get("EB01-012"), sickness=False)]  # power 6000
    sanji = InPlay.of(repo.get("ST10-004"), sickness=True)
    me.characters = [sanji]
    trigger_on_play(st, me, opp, sanji, overlay)
    assert "速攻" in sanji.granted_keywords, "相手 5000+ が居れば【速攻】付与 (前提)"
    opp.characters = []  # 相手キャラが場を離れる
    assert "速攻" in sanji.granted_keywords, (
        "一度得た【速攻】は条件消失後も そのターン保持される (cardqa_st_10)"
    )


def test_st10_004_rush_not_granted_when_no_opp_5000():
    """対照: 登場時に相手パワー5000以上が居なければ【速攻】は付かない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("ST10-004"), sickness=True)
    me.characters = [sanji]
    trigger_on_play(st, me, opp, sanji, overlay)
    assert "速攻" not in sanji.granted_keywords


def test_p111_replace_leave_requires_active_don():
    """P-111 ロビン: アクティブのドンが無ければ 場離れ置換 (ドンをレスト) は行えない。

    一次情報 (cardqa_): 「自分の場にアクティブのドン!!がない場合、この【ターン1回】効果で
    自分の特徴《麦わらの一味》を持つキャラが相手の効果で場を離れる代わりに自分のドン‼1枚を
    レストにできますか？」→「いいえ、できません。」

    是正前は rest_self_don が do 側にあり、 アクティブドン 0 でも置換が成立 (キャラを保護) して
    しまっていた。 rest_self_don を cost に移し、 アクティブドン払えない時は置換不成立にした。
    """
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="P-111")
    me, opp = st.players[0], st.players[1]
    straw = InPlay.of(repo.get("OP01-013"), sickness=False)  # 麦わらの一味
    me.characters = [straw]
    me.don_active = 0
    replaced = try_replace_ko(st, me, opp, straw, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is False, "アクティブドン 0 で置換が成立してはいけない (cardqa_)"


def test_p111_replace_leave_rests_don_when_active_don_present():
    """対照: アクティブドンが有れば置換が成立し、 ドン1枚がレストになる。"""
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="P-111")
    me, opp = st.players[0], st.players[1]
    straw = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [straw]
    me.don_active = 1
    me.don_rested = 0
    replaced = try_replace_ko(st, me, opp, straw, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True, "アクティブドンが有れば置換成立"
    assert me.don_active == 0 and me.don_rested == 1, "コストでアクティブドン1枚がレストへ"
    assert straw in me.characters, "置換成立でキャラは場に残る"


def test_st09_010_replace_ko_requires_life():
    """ST09-010 エース: ライフが無ければ KO 置換 (ライフをトラッシュ) は行えない。

    一次情報 (cardqa_st_09): 「自分のライフが無い時、このキャラがKOされる場合、代わりに
    自分のライフの上か下から1枚をトラッシュに置くことができますか？」→「いいえ、できません。」
    """
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST09-010"), sickness=False)
    me.characters = [ace]
    me.life = []  # ライフ 0
    replaced = try_replace_ko(st, me, opp, ace, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is False, "ライフ 0 で KO 置換が成立してはいけない (cardqa_st_09)"
    # 対照: ライフ有りなら置換成立 (ライフ1枚がトラッシュへ)
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST09-010"), sickness=False)
    me.characters = [ace]
    me.life = [repo.get(_FILLER)] * 2
    trash_before = len(me.trash)
    replaced = try_replace_ko(st, me, opp, ace, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True and len(me.life) == 1 and len(me.trash) == trash_before + 1


def test_op12_024_attached_don_condition_counts_leader_and_all_chars():
    """OP12-024 牛鬼丸: 「付与ドン合計3枚以上」 はリーダー+全キャラの合算。

    一次情報 (cardqa_op_12): 「この【アタック時】効果の『自分の付与されているドン!!が合計3枚
    以上ある場合』の条件は、異なるキャラやリーダーに1～2枚ずつ、合計3枚のドン!!が付与されて
    いる状態でも満たせますか？」→「はい、満たせます。」
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-024"), sickness=False)
    me.characters = [src]
    me.leader.attached_dons = 1
    src.attached_dons = 2
    assert eval_condition({"self_attached_don_ge": 3}, st, me, src), \
        "リーダー1+キャラ2=合計3 で条件成立 (cardqa_op_12)"
    me.leader.attached_dons = 1
    src.attached_dons = 1
    assert not eval_condition({"self_attached_don_ge": 3}, st, me, src), "合計2 では不成立"


def test_op03_036_untap_can_target_leader_kuro():
    """OP03-036 杓死【メイン】: 「自分の『クロ』」 はリーダーの『クロ』も対象。

    一次情報 (cardqa_op_03): 「自分の『クロ』とは、自分のリーダーの『クロ』と自分のキャラの
    『クロ』のどちらを指しますか？」→「自分のリーダーと自分のキャラの『クロ』のどちらも指します。」

    是正前は target が one_self_chara_filtered (キャラ限定) でリーダーを対象に取れなかった。
    one_self_chara_or_leader_filtered に是正。
    """
    from engine.effects import _resolve_target
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP03-021")  # リーダー『クロ』
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True
    me.characters = []  # リーダーのみが『クロ』
    eff = next(e for e in overlay.get("OP03-036").effects if e.get("when") == "main")
    tgt_spec = eff["do"][0]["optional_cost_then"]["effect"][0]["untap_chara"]["target"]
    assert tgt_spec["type"] == "one_self_chara_or_leader_filtered", \
        "target がリーダーを含む型でなければならない"
    tgt = _resolve_target(tgt_spec, st, me, opp, None)
    assert me.leader in tgt, "リーダー『クロ』が untap 対象になるべき (cardqa_op_03)"


def test_op02_024_moby_buffs_leader_edward_newgate():
    """OP02-024 モビー・ディック号【自分のターン中】: 「自分の『エドワード・ニューゲート』」
    はリーダーの同名も対象。

    一次情報 (cardqa_op_02): 「この【自分のターン中】効果によって、自分のリーダーの
    「エドワード・ニューゲート」はパワー+2000されますか？」→「はい、されます。」

    是正前は target が all_self_chara_filtered (キャラ限定) で、 リーダー名が
    エドワード・ニューゲート でも buff されなかった。 leader_name gate の self_leader
    entry を追加。 「『白ひげ海賊団』を含む特徴を持つキャラ」 clause はキャラのみなので、
    白ひげ海賊団だが エドワード・ニューゲート でない リーダー (マルコ 等) は 非対象。
    """
    repo, overlay = _repo(), _overlay()
    # リーダー = エドワード・ニューゲート (OP02-001)、 ライフ1、 自ターン
    st = _state(repo, overlay, leader0="OP02-001")
    me = st.players[0]
    me.life = [repo.get(_FILLER)]  # life<=1
    me.stages = [InPlay.of(repo.get("OP02-024"), sickness=False)]
    base = me.leader.card.power
    evaluate_static_effects(st, overlay)
    assert me.leader.static_buff == 2000, \
        "リーダー『エドワード・ニューゲート』は +2000 されるべき (cardqa_op_02)"
    assert me.leader.power == base + 2000

    # 対照: 白ひげ海賊団 だが エドワード・ニューゲート でない リーダー (マルコ) は 非対象
    st2 = _state(repo, overlay, leader0="OP08-002")  # マルコ (白ひげ, not EN)
    me2 = st2.players[0]
    me2.life = [repo.get(_FILLER)]
    me2.stages = [InPlay.of(repo.get("OP02-024"), sickness=False)]
    evaluate_static_effects(st2, overlay)
    assert me2.leader.static_buff == 0, \
        "白ひげ海賊団の非エドワード・ニューゲート リーダーは buff されない (白ひげ clause はキャラのみ)"


def test_eb01_029_reveal_returns_to_top_when_cost_le_3():
    """EB01-029 わりいおれ死んだ【カウンター】: 公開カードがコスト3以下なら デッキの上へ戻す。

    一次情報 (cardqa_eb_01): 「この【カウンター】効果で公開したカードのコストが3以下だった
    場合、公開したカードはどうなりますか？」→「この場合、公開したカードはデッキの上に裏向きで
    戻します。」

    是正前は rest_remain="bottom" 固定で コスト3以下でもデッキの下へ送っていた。
    rest_remain_unmatched="top" を追加し、 「その後デッキの下に置く」 が コスト4以上の条件節内で
    あることを反映した。
    """
    repo, overlay = _repo(), _overlay()
    rt = next(e for e in overlay.get("EB01-029").effects
              if e.get("when") == "counter")["do"][0]
    # コスト3以下を上に積む → 公開後 デッキの上へ戻る
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    low = repo.get(_FILLER)  # cost2
    assert low.cost <= 3
    me.deck = [low] + [repo.get("OP15-025")] * 20
    top_id = me.deck[0].card_id
    execute_effect(rt, st, me, opp, None)
    assert me.deck[0].card_id == top_id, "コスト3以下は デッキの上に戻す (cardqa_eb_01)"

    # 対照: コスト4以上なら then (自キャラ手札戻し) + 公開カードはデッキの下へ
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    high = repo.get("ST10-004")  # cost6
    assert high.cost >= 4
    me.deck = [high] + [repo.get("OP15-025")] * 20
    top_id = me.deck[0].card_id
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    hand_before = len(me.hand)
    execute_effect(rt, st, me, opp, None)
    assert me.deck[-1].card_id == top_id, "コスト4以上は デッキの下へ"
    assert len(me.hand) == hand_before + 1 and not me.characters, "自キャラが手札へ戻る"


def test_st33_002_optional_cost_payable_when_opp_hand_le_5():
    """ST33-002 サカズキ【アタック時】: 相手手札5枚以下でも 自分の手札1枚は捨てられる
    (相手は6枚以上でないので捨てない)。

    一次情報 (cardqa_st_33): 「相手の手札が5枚以下のときに、この【アタック時】効果で自分の
    手札1枚を捨てることはできますか？」→「はい、できます。この場合、相手の手札が6枚以上では
    ないので、相手は自身の手札を捨てません。」
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)  # 人間 = 任意コストが提示される
    me, opp = st.players[0], st.players[1]
    sakazuki = InPlay.of(repo.get("ST33-002"), sickness=False)
    me.characters = [sakazuki]
    me.hand = [repo.get(_FILLER)]
    opp.hand = [repo.get(_FILLER)] * 5  # 相手手札 5 (<6)
    trigger_on_attack(st, me, opp, sakazuki, overlay)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        "相手手札<6 でも任意コストが人間に提示される (cardqa_st_33)"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    assert len(me.hand) == 0, "自分の手札1枚を捨てられる"
    assert len(opp.hand) == 5, "相手手札は6枚以上でないので減らない"


# ---------------------------------------------------------------------------
# escalated だった 4 件の決着 (2026-08-05)
# ---------------------------------------------------------------------------

def test_opp_life_leaving_by_effect_fires_on_opp_life_taken():
    """「相手のライフが離れた時」 は **効果経由でも** 発火する (OP08-105 ボニー)。

    一次情報 (`cardqa_op_08`): 「相手のライフが**相手の効果によって**手札やトラッシュに
    移動した時、 この【自分のターン中】効果でカード2枚を引き手札1枚を捨てることは
    できますか？」 → **「はい、できます。」**

    是正前は `trigger_on_opp_life_taken` が **アタックダメージ経路にしか配線されておらず**、
    効果によるライフ除去では発火しなかった。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    for prim in ({"mill_opp_life_to_hand": 1}, {"mill_opp_life_to_trash": 1},
                 {"deal_opp_leader_damage": 1}):
        st, p0, p1 = _either_board(repo, ov, [], [])
        bonney = InPlay.of(repo.get("OP08-105"), sickness=False)
        bonney.attached_dons = 1                  # 【ドン‼×1】
        p0.characters = [bonney]
        p0.hand = [repo.get("OP01-013")] * 2
        st.turn_player_idx, st.turn_number = 0, 6   # 【自分のターン中】
        hand_before, life_before = len(p0.hand), len(p1.life)
        execute_effect(prim, st, p0, p1, None)
        assert len(p1.life) == life_before - 1, f"{prim}: 相手ライフが減っていない"
        # ボニー = 2 ドロー + 1 捨て = net +1
        assert len(p0.hand) == hand_before + 1, (
            f"{prim}: 効果で相手ライフが離れたのに 「相手のライフが離れた時」 が発火していない"
        )


def test_optional_cost_cannot_be_partially_paid():
    """任意コストは **一部だけ払えない** (OP04-055 疫災弾)。

    一次情報 (`cardqa_op_04`): 「この【メイン】効果を発動し、 コスト4以下のキャラをデッキの下に
    置かずに、 自分の手札から「氷鬼」1枚を捨てることや、 自分のトラッシュから「氷鬼」1枚を
    登場させることはできますか？」 → **「いいえ、できません。」**
    定義 (`cardqa_st_06`): 「「：」以前に表記されている指示はすべて "発動コスト" であり、
    "発動コスト" はその一部のみを支払うことはできません。」

    是正前は コスト4以下キャラが不在でも 氷鬼 を捨てて登場できていた (= 部分支払い)。
    """
    import json as _json
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    hyouki = next(c["card_id"] for c in
                  _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
                  if c["name"] == "氷鬼" and "_" not in c["card_id"])
    eff = next(e for e in ov.get("OP04-055").effects if e.get("when") == "main")

    def board(opp_has_target: bool):
        st, p0, p1 = _either_board(repo, ov, [], [])
        p0.hand = [repo.get(hyouki)]
        p0.trash = [repo.get(hyouki)]
        p0.don_active = 10
        if opp_has_target:
            p1.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]  # cost2
        return st, p0, p1

    # 対象不在 → コスト全体が払えない = 氷鬼も捨てないし登場もしない
    st, p0, p1 = board(False)
    h0, c0 = len(p0.hand), len(p0.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, p0, p1, None)
    assert len(p0.hand) == h0 and len(p0.characters) == c0, (
        "コスト4以下のキャラが不在なのに 氷鬼を捨てて登場できている (= 部分支払い)"
    )

    # 対照: 対象が居れば通常どおり発動する
    st, p0, p1 = board(True)
    h0, c0 = len(p0.hand), len(p0.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, p0, p1, None)
    assert len(p0.hand) < h0 and len(p0.characters) > c0, "対象が居るのに発動していない"


def test_replacement_sacrifice_does_not_cancel_battled_trigger():
    """身代わり置換でバトル当事者以外が離れても 「バトルした場合」 は発動する。

    一次情報 (`cardqa_op_05`): 「このキャラと相手の「ST02-010 バジル・ホーキンス」がバトルした時、
    この【相手のターン中】効果で代わりにトラッシュに置いた場合、 相手の「ST02-010」の
    【自分のターン中】効果を発動できますか？」 → **「はい、できます。」**

    OP05-030 ロシナンテが身代わりでトラッシュへ行っても、 **バトルの当事者は場に残る** ので
    バトルは中断されず、 ホーキンスの `on_self_battled` (untap) が発動する。
    (= 2026-08-04 の 「バトル中断」 是正が過剰適用されていないことの確認でもある)
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay
    from engine.game import legal_actions, apply_action

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="HAWK", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="ROSI", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    hawk = InPlay.of(repo.get("ST02-010"), sickness=False)
    hawk.attached_dons = 1
    p0.characters = [hawk]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    victim.rested = True
    rosi = InPlay.of(repo.get("OP05-030"), sickness=False)
    p1.characters = [victim, rosi]
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 25
        p.life = [repo.get("OP01-013")] * 3
        p.hand = []
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 6

    acts = [a for a in legal_actions(st)
            if type(a).__name__ == "AttackCharacter"
            and getattr(a, "target_iid", None) == victim.instance_id]
    assert acts, "レストキャラへのアタックが legal に出ない"
    apply_action(st, acts[0])

    alive = {c.instance_id for c in p1.characters}
    assert victim.instance_id in alive, "身代わりが働いたのに victim が KO されている"
    assert rosi.instance_id not in alive, "ロシナンテが身代わりになっていない"
    assert not hawk.rested, (
        "身代わり置換でバトルが中断扱いになり `on_self_battled` (untap) が発動していない"
    )


def test_character_removed_by_opponent_event_does_not_draw():
    """相手イベントで場を離れたキャラの reactive ドローは発動しない (OP01-004 ウソップ)。

    一次情報 (`cardqa_op_01`): 「相手が使用したイベントによってこのキャラがバトルエリアを
    離れた場合、 このキャラの効果でカードを引けますか？」 → **「いいえ、できません。」**

    = reactive (「相手がイベントを発動した時」) は **反応対象の効果を処理した後** に解決する。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_counter_event

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="ME", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="OPP", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    usopp = InPlay.of(repo.get("OP01-004"), sickness=False)   # 元々のパワー 3000
    usopp.attached_dons = 1                                    # 【ドン‼×1】
    p0.characters = [usopp]
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 25
        p.life = [repo.get("OP01-013")] * 3
    p1.hand = [repo.get("EB01-010")]      # 【カウンター】元々のパワー6000以下を KO
    p1.don_active = 5
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 6

    hand_before = len(p0.hand)
    trigger_counter_event(st, p1, p0, repo.get("EB01-010"), ov)
    assert usopp.instance_id not in {c.instance_id for c in p0.characters}, \
        "前提が崩れた: ウソップが KO されていない"
    assert len(p0.hand) == hand_before, \
        "相手イベントで場を離れたのにドローしている (公式: いいえ)"


def test_op08_079_kaido_activate_main_only_on_summon_turn():
    """OP08-079 カイドウ: 【起動メイン】は **登場したターンのみ** 効果が起きる。

    一次情報 (`cardqa_op_08`): 「このキャラが登場したターンの次以降のターンに、この
    【起動メイン】効果を発動し自分の手札を捨てることはできますか？」 →
    **「はい、できます。この場合、自分の手札1枚を捨てた後、何も起こりません。」**

    是正前の overlay には 3 重の違反があった (2026-08-05):
      (1) 「このキャラが登場したターンの場合」 条件が **欠落** → 登場ターン外でも発動していた
      (2) 相手手札破棄が **2 回** → 公式は 1 回
      (3) 順序が逆 → 公式は 「キャラをトラッシュ → **その後** 相手手札1枚を捨てる」
    ⚠ コロン後の条件なので **任意コスト (自分の手札1枚を捨てる) は条件不成立でも払える**。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(e for e in ov.get("OP08-079").effects if e.get("when") == "activate_main")

    def board(played_this_turn: bool):
        st, p0, p1 = _either_board(repo, ov, [], [])
        kaido = InPlay.of(repo.get("OP08-079"), sickness=played_this_turn)
        p0.characters = [kaido]
        p0.hand = [repo.get("OP01-013")] * 2
        p1.hand = [repo.get("OP01-013")] * 4
        p1.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]   # cost2 ≤ 7
        return st, p0, p1, kaido

    # 登場したターン → キャラ 1 トラッシュ + 相手手札 1 捨て (各 1 回ずつ)
    st, p0, p1, kaido = board(True)
    mh, oh, oc = len(p0.hand), len(p1.hand), len(p1.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, p0, p1, kaido)
    assert len(p0.hand) == mh - 1, "任意コスト (自分の手札1枚) が払われていない"
    assert len(p1.characters) == oc - 1, "相手キャラがトラッシュされていない"
    assert len(p1.hand) == oh - 1, (
        f"相手の手札破棄が 1 回でない: {oh} → {len(p1.hand)} (是正前は 2 回捨てていた)"
    )

    # 次以降のターン → コストは払えるが **何も起こらない**
    st, p0, p1, kaido = board(False)
    mh, oh, oc = len(p0.hand), len(p1.hand), len(p1.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, p0, p1, kaido)
    assert len(p0.hand) == mh - 1, "コストは払えるはず (公式: はい、できます)"
    assert len(p1.characters) == oc and len(p1.hand) == oh, (
        "登場ターン外なのに効果が起きている (公式: 何も起こりません)"
    )


# --------------------------------------------------------------------------- #
#  公式 Q&A 全件保証バッチ (2026-08-05)
#  台帳 db/faq_qa_status.json の pending を 1 バッチ処理した際の回帰テスト。
#  各テストは一次情報 (cardqa_*) の Q&A 原文をコメントに引用し、 「公式どおりか」 を
#  engine の盤面差分で固定する。
# --------------------------------------------------------------------------- #
def test_op03_122_mandatory_tail_runs_without_return_target():
    """OP03-122 そげキング: 「コスト6以下のキャラを戻さない」を選んでも draw2+discard2 は走る。

    一次情報 (cardqa_op_03):
      「このキャラを登場させ【登場時】効果を発動し、コスト6以下のキャラを戻さない事を
        選べますか？」→「はい、できます。その場合も、カードを2枚引き、手札2枚を捨てます。」
    = 前段 (return_to_hand 1枚まで) が空振りでも 後段 (draw2 → discard2) は独立に実行される。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 3
    src = InPlay.of(repo.get("OP03-122"), sickness=True)
    me.characters = [src]                      # 盤面に戻せるキャラは居ない (前段空振り)
    deck_before, trash_before = len(me.deck), len(me.trash)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.deck) == deck_before - 2, "後段 draw2 が走っていない"
    assert len(me.trash) >= trash_before + 2, "後段 discard2 が走っていない"


def test_st30_016_named_power_condition_requires_exact_printed_6000():
    """ST30-016 戦えるかルフィ: 「元々のパワー6000」は **ちょうど6000** で、5000以下は含まない。

    一次情報 (cardqa_st_30):
      「この効果の「元々のパワー6000のキャラ」に、元々のパワー5000以下のキャラは
        含まれますか？」→「いいえ、…元々のパワーが6000ちょうどのキャラの「エース」と
        「ルフィ」の両方が自分の場にいる場合、カード1枚を引く効果です。」

    是正前バグ: overlay の key が `truly_original_power_eq` で、engine (Python/Rust とも) は
    `power_eq` しか読まないため power 制約が **黙って無視** され、5000パワーのエースでも
    条件成立していた (= 差分検証では両エンジン同一挙動なので沈黙する型の乖離)。
    """
    repo, overlay = _repo(), _overlay()
    cond = next(e for e in overlay.get("ST30-016").effects
                if e.get("if", {}).get("self_field_named_all_with_power"))["if"]
    ace6, ace5, luffy6 = "OP13-002", "OP16-001", "OP09-036"   # 印刷パワー 6000 / 5000 / 6000
    assert repo.get(ace6).power == 6000 and repo.get(ace5).power == 5000

    st = _state(repo, overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get(ace6)), InPlay.of(repo.get(luffy6))]
    assert eval_condition(cond, st, me) is True, "6000ちょうどのペアは条件成立するはず"

    st2 = _state(repo, overlay)
    me2 = st2.players[0]
    me2.characters = [InPlay.of(repo.get(ace5)), InPlay.of(repo.get(luffy6))]
    assert eval_condition(cond, st2, me2) is False, (
        "元々のパワー5000のエースは 6000 に含まれない (是正前は True = 公式違反)"
    )


def test_op15_079_trigger_ko_effect_sources_only_from_own_trash():
    """OP15-079 アブサロム: 【トリガー】で発動する【KO時】は トラッシュからしか手札に加えない。

    一次情報 (cardqa_op_15):
      「この【トリガー】効果でこのカード自身を手札に加えることはできますか？」
      →「いいえ、できません。」
    = ライフから【トリガー】発動したアブサロム自身はトラッシュに居ないので対象にならない。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    absalom = InPlay.of(repo.get("OP15-079"), sickness=True)   # トリガー発動 = ライフ由来 = トラッシュに無い
    me.trash = []
    hand_before = len(me.hand)
    execute_effect({"trash_to_hand": {"filter": {"feature": "スリラーバーク海賊団"},
                                      "limit": 1}}, st, me, opp, absalom)
    assert len(me.hand) == hand_before, "トラッシュが空なのに手札に加わっている (= 自身を加えた)"


def test_op14_001_swap_self_power_never_targets_opponent():
    """OP14-001 ロー: 元々のパワー入れ替えは **自分のキャラ2枚** のみ。相手キャラは対象外。

    一次情報 (cardqa_op_14):
      「この【起動メイン】効果で、自分のキャラと相手のキャラや、相手のキャラ同士の
        パワーを入れ替えることはできますか？」→「いいえ、できません。」
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    a, b = "EB01-015", "ST24-004"              # 印刷 1000 / 11000、 いずれも 超新星/ハートの海賊団
    ca, cb = InPlay.of(repo.get(a)), InPlay.of(repo.get(b))
    me.characters = [ca, cb]
    oc = InPlay.of(repo.get(_FILLER))
    opp.characters = [oc]
    execute_effect({"swap_self_power": {"filter": {"or": [{"feature": "超新星"},
                                                          {"feature": "ハートの海賊団"}]}}},
                   st, me, opp, ca)
    assert {ca.turn_base_power_override, cb.turn_base_power_override} == {1000, 11000}, \
        "自分のキャラ2枚の元々パワーが入れ替わっていない"
    assert oc.turn_base_power_override is None, "相手キャラが swap_self_power の影響を受けている"


def test_p040_ko_immunity_lifts_when_opp_don_drops_below_10():
    """P-040 カイドウ: 「相手の場にドン10枚ある場合KOされない」は DON 枚数に追随する。

    一次情報 (cardqa promo):
      相手ドン10枚+百獣リーダーで OP01-094 の【登場時】(ドン-6) を発動しドン6枚を戻した時、
      この P-040 カイドウを KO できるか → 「はい、KOできます。」
    = ドン-6 で相手の場のドンが 4 になり、KO 耐性条件 (ドン10) が崩れるため KO 可能。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    p040 = InPlay.of(repo.get("P-040"))
    me.characters = [p040]
    opp.don_active, opp.don_rested = 10, 0
    evaluate_static_effects(st, overlay)
    assert p040.static_ko_immune is True, "相手ドン10枚なら KO 耐性が立つはず"
    opp.don_active = 4                          # OP01-094 が ドン-6 を払った後
    evaluate_static_effects(st, overlay)
    assert p040.static_ko_immune is False, "相手ドンが4枚に減れば KO 耐性は消えるはず"


def test_op02_051_draw_to_hand_size_is_mandatory():
    """OP02-051 イワンコフ: 手札が3枚未満なら 3 になるまで **必ず** 引く (引かない選択不可)。

    一次情報 (cardqa_op_02):
      「手札が2枚以下の場合、この【登場時】効果でカードを引かないことを選べますか？」
      →「いいえ、できません。可能な限り3枚になるようにカードを引きます。」
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]               # 1 枚
    src = InPlay.of(repo.get("OP02-051"), sickness=True)
    me.characters = [src]
    execute_effect({"draw_to_hand_size": 3}, st, me, opp, src)
    assert len(me.hand) == 3, "手札3枚になるまで引いていない (= 強制ドロー)"


def test_st19_003_activate_main_not_gated_by_leader():
    """ST19-003 たしぎ: 【起動メイン】(相手コスト0をトラッシュ) は リーダー名の制約を受けない。

    一次情報 (cardqa_st_19):
      「自分のリーダーが「スモーカー」ではない場合、この【起動メイン】効果で相手のコスト0の
        トラッシュに置くことはできますか？」→「はい、できます。」
    = リーダー「スモーカー」条件は【登場時】側のみ。【起動メイン】は登場ターン条件のみ。
    """
    repo, overlay = _repo(), _overlay()
    # リーダー ≠ スモーカー (OP01-001) + 登場ターン (召喚酔い)
    st = _state(repo, overlay, leader0="OP01-001")
    me = st.players[0]
    tashigi = InPlay.of(repo.get("ST19-003"), sickness=True)
    me.characters = [tashigi]
    opts = [o for o in list_activate_main_effects(st, me, overlay) if o[0] is tashigi]
    assert len(opts) >= 1, "リーダー≠スモーカーでも起動メインは使えるはず (公式: はい)"
    # 対照: 登場ターン外なら (登場ターン条件で) 起動メインは出ない
    st2 = _state(repo, overlay, leader0="OP01-001")
    me2 = st2.players[0]
    tashigi2 = InPlay.of(repo.get("ST19-003"), sickness=False)
    me2.characters = [tashigi2]
    opts2 = [o for o in list_activate_main_effects(st2, me2, overlay) if o[0] is tashigi2]
    assert opts2 == [], "登場ターン外なのに起動メインが出ている (= 登場ターン条件の欠落)"


def test_op16_103_trigger_ko_effect_gated_by_opp_turn():
    """OP16-103 ヴァン・オーガー: 【相手のターン中】【KO時】は 自分のターン中は発動しない。

    一次情報 (cardqa_op_16):
      「自分のターン中に自分のリーダーがダメージを受けて、この【トリガー】を発動した場合、
        この【KO時】効果はどうなりますか？」→「この場合、この【KO時】効果は発動せず、
        このカードはトラッシュに置かれます。」
    = 【トリガー】が【KO時】を発動しても、自分のターン中は opp_turn 条件不成立で不発。
    """
    repo, overlay = _repo(), _overlay()
    # リーダーは 黒ひげ海賊団 (OP16-080)
    # 自分のターン (turn_player_idx = 0 = me) → opp_turn False → KO時 不発
    st = _state(repo, overlay, leader0="OP16-080", leader1="OP16-080")
    st.turn_player_idx = 0
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_FILLER))]
    hand_before = len(me.hand)
    execute_effect({"fire_self_effect": {"when_kind": "on_ko"}}, st, me, opp,
                   InPlay.of(repo.get("OP16-103")))
    assert len(me.hand) == hand_before, "自分のターン中なのに【KO時】が発動している (公式違反)"

    # 対照: 相手のターン中 (turn_player_idx = 1) なら 発動する
    st2 = _state(repo, overlay, leader0="OP16-080", leader1="OP16-080")
    st2.turn_player_idx = 1
    me2, opp2 = st2.players[0], st2.players[1]
    opp2.characters = [InPlay.of(repo.get(_FILLER))]
    hand_before2 = len(me2.hand)
    execute_effect({"fire_self_effect": {"when_kind": "on_ko"}}, st2, me2, opp2,
                   InPlay.of(repo.get("OP16-103")))
    assert len(me2.hand) == hand_before2 + 1, "相手のターン中は【KO時】が発動するはず"


def test_optional_cost_is_not_trapped_inside_conditional():
    """`optional_cost_then` の **cost が conditional の内側に入っていない**。

    ⚠ 2026-08-05 に実際にやらかした形: top-level `if` を `conditional` へ移す際、
    `do` 全体を包むと `optional_cost_then` ごと条件の内側に入り、
    **条件不成立でコストを払えなくなる** (= 直そうとした違反そのものを再現してしまう)。
    正しい形は cost はそのまま、 `effect` 配列だけを `conditional` で包む。
    """
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    bad = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list):
            continue
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            do = eff.get("do")
            if not (isinstance(do, list) and len(do) == 1 and "conditional" in do[0]):
                continue
            inner_do = (do[0]["conditional"] or {}).get("do")
            if (isinstance(inner_do, list) and len(inner_do) == 1
                    and isinstance(inner_do[0], dict) and "optional_cost_then" in inner_do[0]):
                bad.append(cid)
    assert not bad, (
        "optional_cost_then が conditional の内側にある = 条件不成立でコストを払えない:\n  "
        + "\n  ".join(sorted(set(bad))[:30])
    )


def test_colon_prefix_cost_is_actually_gated():
    """公式のコロン前 (= 発動コスト) が overlay に実装され、 払えなければ効果も起きない。

    一次情報 (`cardqa_st_06`): 「「：」以前に表記されている指示はすべて "発動コスト" であり、
    …その一部あるいは全部が支払えない場合、 その効果を発動することができません。」
    一次情報 (`cardqa_op_01`, OP01-011 ゴードン): 「自分の手札が他にない場合、 このキャラを
    登場できますか？」 → 登場はできるが 効果 (1ドロー) は起きない。

    2026-08-05 是正前は overlay が **コストと効果を平坦に並べていて gate が効かず**、
    コストを払えない盤面でも効果だけ起きていた (= タダ撃ち)。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_on_play

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def board(*, hand: int = 0, don: int = 0, mates: tuple = ()):
        st, p0, p1 = _either_board(repo, ov, list(mates), [])
        p0.hand = [repo.get("OP01-013")] * hand
        p0.don_active = don
        return st, p0, p1

    # ① OP01-011 ゴードン: 手札0 (自分が最後の1枚だった) → コスト不能 → ドローしない
    st, p0, p1 = board(hand=0)
    src = InPlay.of(repo.get("OP01-011"), sickness=True)
    p0.characters.append(src)
    h0, d0 = len(p0.hand), len(p0.deck)
    trigger_on_play(st, p0, p1, src, ov)
    assert len(p0.hand) == h0 and len(p0.deck) == d0, \
        "手札0でコストを払えないのにドローしている (タダ撃ち)"

    # ② OP01-093: ① (ドン1レスト) を払えない → ドンが増えない
    st, p0, p1 = board(don=0)
    src = InPlay.of(repo.get("OP01-093"), sickness=True)
    p0.characters.append(src)
    tot0 = p0.don_active + p0.don_rested
    trigger_on_play(st, p0, p1, src, ov)
    assert p0.don_active + p0.don_rested == tot0, \
        "アクティブドン0で ① を払えないのにドンが増えている"

    # ③ OP05-056: 「**このキャラ以外**の」 自キャラが居ない → コスト不能 → ドローしない
    st, p0, p1 = board()
    src = InPlay.of(repo.get("OP05-056"), sickness=True)
    p0.characters.append(src)
    h0 = len(p0.hand)
    trigger_on_play(st, p0, p1, src, ov)
    assert len(p0.hand) == h0, \
        "他の自キャラが居ないのにコストを払えている (except_self が効いていない)"


def test_op11_058_attack_ban_uses_hand_before_paying_attack_cost():
    """OP11-058: アタック可否は **コスト支払い前の手札** で判定する。

    一次情報 (`cardqa_op_11`): 「直前の相手のターンに相手が「OP08-043 エドワード・ニューゲート」の
    【登場時】効果を発動しており、 次の自分のターン中に、 自分の手札が6枚の場合、 自分の手札2枚を
    捨ててこのキャラでアタックすることができますか？」 → **「いいえ、できません。」**

    OP11-058 は 「自分の手札が5枚以上ある場合、 このキャラはアタックできない」。
    手札 6 枚なら **アタック宣言自体ができない** ので、 「2枚捨てれば 4 枚になるから撃てる」
    とはならない (= 制限の判定はコスト支払いより前)。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, evaluate_static_effects
    from engine.game import legal_actions

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def board(hand_n: int, attack_cost: bool):
        st, p0, p1 = _either_board(repo, ov, [], [])
        luffy = InPlay.of(repo.get("OP11-058"), sickness=False)
        if attack_cost:      # OP08-043 の効果 = アタック時に手札2枚を捨てる必要
            luffy.attack_cost_discard_hand = 2
        p0.characters = [luffy]
        p0.hand = [repo.get("OP01-013")] * hand_n
        st.turn_player_idx, st.turn_number = 0, 6
        evaluate_static_effects(st, ov)
        return st, p0, p1, luffy

    def can_attack(st, luffy):
        return any(type(a).__name__ in ("AttackLeader", "AttackCharacter")
                   and getattr(a, "attacker_iid", None) == luffy.instance_id
                   for a in legal_actions(st))

    st, p0, p1, luffy = board(6, True)
    assert not can_attack(st, luffy), (
        "手札6枚なら OP11-058 はアタックできないはず "
        "(2枚捨てて4枚になることを見越して撃つことはできない)"
    )
    st, p0, p1, luffy = board(4, True)
    assert can_attack(st, luffy), "手札4枚なら制限外なのでアタックできるはず"


# --------------------------------------------------------------------------- #
#  コスト節の 対象範囲 (2026-08-05)
#    公式は **コスト節でも** 「自分の」/「相手の」/(修飾なし) を書き分ける:
#      自分のみ  OP05-104 コニス 「**自分の**ステージ1枚をデッキの下に置くことができる：」
#      相手のみ  OP15-003 アルビダ 「**相手の**キャラ1枚に相手のレストのドン‼1枚を付与できる：」
#      両陣営    OP06-102/111/114 「コスト1のステージ1枚を持ち主のデッキの下に置くことができる：」
#    「相手の」 を明示するコストが 41 件 実在する = コストでも相手のカードは使える。
#    ⚠ 「持ち主の」 は根拠にならない (OP12-080 バラティエは自分のステージにも使う)。
#    ⚠ 対象範囲監査 (`audit_target_scope.py`) は **target spec しか見ない** ので、
#      コスト spec のこのクラスは監査の穴だった。 下の全走査ガードで塞ぐ。
# --------------------------------------------------------------------------- #
def test_unqualified_stage_cost_can_use_opponent_stage():
    """OP06-102: 「コスト1のステージ1枚を…」 は **相手のステージ** でも払える。"""
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _either_board(repo, ov, [], ["OP01-013"])
    # 自分にステージ無し / 相手にコスト1のステージ (OP02-048 ワノ国 = cost1)
    stage = repo.get("OP02-048")
    assert stage.cost == 1, f"テスト前提: OP02-048 は cost1 (実際 {stage.cost})"
    p1.stages = [InPlay.of(stage, sickness=False)]
    victim = p1.characters[0]

    eff = next(e for e in ov.get("OP06-102").effects if e.get("when") == "activate_main")
    src = InPlay.of(repo.get("OP06-102"), sickness=False)
    p0.characters.append(src)
    execute_effect(eff["do"][0], st, p0, p1, src)

    assert not p1.stages, "相手のステージがコストとして支払われていない"
    assert p1.deck[-1].card_id == "OP02-048", \
        "相手のステージは **持ち主 (= 相手) の** デッキの下に置かれるべき"
    assert victim not in p1.characters, "コストを払ったのに効果 (KO) が発動していない"


def test_unqualified_stage_cost_is_not_free_without_any_stage():
    """⚠ 対照: 両陣営どちらにもステージが無ければ 払えず 効果も発動しない。"""
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _either_board(repo, ov, [], ["OP01-013"])
    victim = p1.characters[0]

    eff = next(e for e in ov.get("OP06-102").effects if e.get("when") == "activate_main")
    src = InPlay.of(repo.get("OP06-102"), sickness=False)
    p0.characters.append(src)
    execute_effect(eff["do"][0], st, p0, p1, src)

    assert victim in p1.characters, "ステージが無いのに KO が発動している (タダ撃ち)"


def test_self_qualified_stage_cost_cannot_use_opponent_stage():
    """⚠ 逆向き: OP05-104 コニスは 「**自分の**ステージ」 なので 相手のステージでは払えない。"""
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _either_board(repo, ov, [], [])
    p0.hand = [repo.get("OP01-013")]
    p1.stages = [InPlay.of(repo.get("OP02-048"), sickness=False)]
    deck_before = len(p0.deck)

    eff = next(e for e in ov.get("OP05-104").effects if e.get("when") == "on_play")
    src = InPlay.of(repo.get("OP05-104"), sickness=False)
    p0.characters.append(src)
    execute_effect(eff["do"][0], st, p0, p1, src)

    assert len(p1.stages) == 1, "「自分の」 指定なのに相手のステージが払われている"
    assert len(p0.deck) == deck_before, "払えないのにドローしている"


def test_cost_clause_scope_matches_overlay_side_whole_corpus():
    """⭐ 全走査: コスト節の修飾 と cost spec の side が corpus 全体で一致する。

    対照テストだけでは 「別のカードに同じ取りこぼしが残っている」 を検出できない
    (= 過去に コスト/パワー是正で 6 枚 + 2 枚 の取りこぼしが全走査でだけ出た)。
    """
    import json
    import re

    cards = {c["card_id"]: c
             for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    def clauses(text: str) -> list[str]:
        t = re.sub(r"[(（][^)）]*[)）]", "", text or "").replace("\n", "")
        out, cur = [], ""
        for p in re.split(r"(【[^】]+】)", t):
            if p.startswith("【"):
                if p.strip("【】").startswith(("ターン1回", "ドン‼")) or "ドン‼×" in p:
                    cur += p
                    continue
                if cur.strip():
                    out.append(cur)
                cur = p
            else:
                cur += p
        if cur.strip():
            out.append(cur)
        return out

    bad: list[str] = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list) or cid.startswith("_"):
            continue
        card = cards.get(cid)
        if not card:
            continue
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            blob = json.dumps(eff, ensure_ascii=False)
            if '"stage_to_deck_bottom"' not in blob:
                continue
            src = "trigger" if eff.get("when") == "trigger" else "text"
            either_spec = '"side": "either"' in blob or '"side":"either"' in blob
            for cl in clauses(card.get(src) or ""):
                if "：" not in cl or "できる" not in cl.split("：", 1)[0]:
                    continue
                head = cl.split("：", 1)[0]
                if "ステージ" not in head:
                    continue
                qualified = ("自分の" in head) or ("このステージ" in head)
                if qualified and either_spec:
                    bad.append(f"{cid}: 「自分の」 指定なのに side=either")
                if not qualified and not either_spec:
                    bad.append(f"{cid}: 修飾なし (= 両陣営) なのに自陣限定 — {head[-46:]}")
                break

    assert not bad, "コスト節の対象範囲が overlay と不一致:\n  " + "\n  ".join(bad)


def test_eb03_054_trigger_plays_itself_after_paying_discard():
    """EB03-054 トリガー: 手札1枚を捨てて **このカードを登場させる**。

    公式: 「【トリガー】自分の手札1枚を捨てることができる：このカードを登場させる。」
    ⚠ 2026-08-05 まで overlay は `do: [trash_self_hand_random]` だけで、
      **コスト gate も無く、 効果 (登場) が丸ごと欠落** していた
      (= 手札を 1 枚失うだけで何も起きない)。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(e for e in ov.get("EB03-054").effects if e.get("when") == "trigger")

    # 手札に (ライフから加わった) 自身 + 捨てる用の 1 枚 → コストを払って登場する
    st, p0, p1 = _either_board(repo, ov, [], [])
    p0.hand = [repo.get("EB03-054"), repo.get("OP01-013")]
    st.current_source_card_id = "EB03-054"
    execute_effect(eff["do"][0], st, p0, p1, None)
    assert any(c.card.card_id == "EB03-054" for c in p0.characters), \
        "コストを払ったのに 「このカードを登場させる」 が発動していない"
    assert not any(c.card_id == "EB03-054" for c in p0.hand), \
        "登場したのに手札に残っている"
    # ⚠ 登場すると EB03-054 自身の【登場時】(ライフ→トラッシュ / デッキ→ライフ) も連鎖するので、
    #   trash/life の枚数は 「捨てた1枚」 だけでは決まらない。 ここは登場したことのみを見る。

    # 手札が自身のみ (= 捨てる札が無い) → 払えないので登場しない
    st2, q0, q1 = _either_board(repo, ov, [], [])
    q0.hand = []
    st2.current_source_card_id = "EB03-054"
    execute_effect(eff["do"][0], st2, q0, q1, None)
    assert not q0.characters, "手札0でコストを払えないのに登場している (タダ撃ち)"


def test_op12_017_search_filter_matches_official_or_clause():
    """OP12-017: 「**赤の**イベントか**赤の**コスト3以上のキャラカード」 の or を両方満たす。

    ⚠ 2026-08-05 まで filter が `{"cost_ge": 3}` だけで、 赤のイベントが引けず
      コスト3以上のイベント/ステージが誤って引けた。 コストも未実装 (タダ撃ち) だった。
    ⚠ 2026-08-12: さらに **キャラ側に color が無く、 赤以外のコスト3以上キャラを拾えていた**。
      公式 (cardqa_op_12) は 「赤以外のコスト3以上のキャラカードを手札に加えられますか？」 →
      「**いいえ**。 この効果は 『赤のイベント』 か 『赤のコスト3以上のキャラカード』」。
      = 「赤の」 は **両方に係る**。 この assert はその是正を固定する。
    """
    import json
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    eff = next(e for e in ov["OP12-017"] if e.get("when") == "main")
    oct_ = eff["do"][0]["optional_cost_then"]

    assert oct_["cost"] == [{"attach_active_don_to_named_chara":
                             {"name": "シルバーズ・レイリー", "count": 1}}], \
        f"コロン前 (= 発動コスト) が実装されていない: {oct_['cost']}"
    filt = oct_["effect"][0]["search_top_n"]["filter"]
    assert filt.get("or_clauses") == [
        {"category": "EVENT", "color": "赤"},
        {"category": "CHARACTER", "cost_ge": 3, "color": "赤"},
    ], f"公式の 「赤のイベントか 赤のコスト3以上のキャラカード」 と一致しない: {filt}"


def test_op12_017_not_free_without_rayleigh_or_active_don():
    """⚠ 対照: レイリーが居ない / アクティブドンが無いと サーチは発動しない。"""
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(e for e in ov.get("OP12-017").effects if e.get("when") == "main")

    # レイリー不在 → 払えない
    st, p0, p1 = _either_board(repo, ov, [], [])
    p0.hand, p0.don_active = [], 1
    execute_effect(eff["do"][0], st, p0, p1, None)
    assert not p0.hand, "レイリーが居ないのにサーチが発動している"

    # レイリー居るがアクティブドン0 → 払えない
    rayleigh = repo.get("OP09-005")
    assert rayleigh.name == "シルバーズ・レイリー", "テスト前提: OP09-005 = シルバーズ・レイリー"
    st2, q0, q1 = _either_board(repo, ov, [], [])
    q0.hand, q0.don_active = [], 0
    q0.characters = [InPlay.of(rayleigh, sickness=False)]
    execute_effect(eff["do"][0], st2, q0, q1, None)
    assert not q0.hand, "アクティブドンが無いのにサーチが発動している"


# --------------------------------------------------------------------------- #
#  optional_cost_then の payability 網羅 (2026-08-05)
#    公式 (cardqa_st_06): 「「：」以前に表記されている指示はすべて "発動コスト"」 +
#    「コストは一部だけ払うことはできない」。 = 払えないなら効果は発動しない。
#    ⚠ payability handler が **無い** cost キーは 「払える」 扱いで素通りし、 資源が無くても
#      効果が発火する。 しかも **Python も Rust も同じ overlay を読む** ので、
#      差分検証 (MISMATCH) では永久に沈黙する。 公式 Q&A だけが検出できるクラス。
# --------------------------------------------------------------------------- #
def test_optional_cost_then_all_cost_keys_have_payability():
    """⭐ 全走査: overlay が使う全 cost キーに payability handler がある。

    2026-08-05 に この走査で **43 枚 / 7 キー** の抜けが出た
    (rest_self_cards / rest_self_cards_filtered / mill_self_top / hand_to_deck_bottom /
     play_from_hand_named_set / return_attached_don_to_cost_rested / rest_own_card)。
    実測でも OP14-036 が 「レストにできる自カード 0」 で相手をレストできていた。
    """
    import json
    import re

    src = (ROOT / "engine" / "effects.py").read_text(encoding="utf-8")
    i = src.index('k == "optional_cost_then"')
    seg = src[i:i + 40000]
    a = seg.index("for cs in cost_specs:")
    b = seg.index("# effect が空回りするケース")
    handled = set(re.findall(r'"([a-z_0-9]+)"\s+in\s+cs', seg[a:b]))

    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    def walk(node, out):
        if isinstance(node, dict):
            oc = node.get("optional_cost_then")
            if isinstance(oc, dict):
                for c in oc.get("cost", []) or []:
                    if isinstance(c, dict):
                        out.update(c.keys())
            for v in node.values():
                walk(v, out)
        elif isinstance(node, list):
            for v in node:
                walk(v, out)

    per_key: dict[str, list[str]] = {}
    for cid, effs in ov.items():
        if not isinstance(effs, list):
            continue
        keys: set[str] = set()
        walk(effs, keys)
        for k in keys:
            per_key.setdefault(k, []).append(cid)

    # {"rest": "self"} は 「このカードをレストにできる」 = 発動元レスト。 payability は
    # rest primitive 側の no-op で担保済 (実測で 既レスト時に効果不発を確認)。
    ACK = {"rest"}
    missing = {k: v for k, v in per_key.items()
               if not k.startswith("_") and k not in handled and k not in ACK}
    assert not missing, (
        "optional_cost_then の cost に payability handler が無い (= 資源不足でも発動する):\n  "
        + "\n  ".join(f"{k}: {len(v)} 枚 例 {v[:5]}" for k, v in sorted(missing.items()))
    )


def test_rest_self_cards_cost_is_gated_when_nothing_can_rest():
    """OP14-036 トリガー: レストにできる自カードが 0 なら 相手をレストできない。"""
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(e for e in ov.get("OP14-036").effects if e.get("when") == "trigger")

    st, p0, p1 = _either_board(repo, ov, [], ["OP01-013"])
    p0.leader.rested = True          # 自陣にアクティブなカードが無い
    victim = p1.characters[0]
    execute_effect(eff["do"][0], st, p0, p1, None)
    assert not victim.rested, "コストを払えないのに相手をレストしている (タダ撃ち)"

    # 対照: アクティブな自キャラが 1 枚あれば発動する
    st2, q0, q1 = _either_board(repo, ov, ["OP01-013"], ["OP01-013"])
    victim2 = q1.characters[0]
    execute_effect(eff["do"][0], st2, q0, q1, None)
    assert victim2.rested, "コストを払えるのに効果が発動していない"


def test_play_from_hand_named_set_cost_is_gated_without_the_named_card():
    """OP05-111 ホトリ: 手札に 「コトリ」 が無ければ 相手キャラをライフに送れない。"""
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(e for e in ov.get("OP05-111").effects if e.get("when") == "on_play")

    st, p0, p1 = _either_board(repo, ov, [], ["OP01-013"])
    p0.hand = []
    victim = p1.characters[0]
    src = InPlay.of(repo.get("OP05-111"), sickness=False)
    p0.characters.append(src)
    life_before = len(p1.life)
    execute_effect(eff["do"][0], st, p0, p1, src)
    assert victim in p1.characters, "「コトリ」 が無いのに相手キャラがライフへ送られている"
    assert len(p1.life) == life_before, "コストを払えないのに相手ライフが増えている"
# --------------------------------------------------------------------------- #
#  公式 Q&A conformance batch (2026-08-05、 cron optcg-faq-conformance)
#  cardqa 一次情報を各テストの docstring に逐語引用する。 全て「違反なし=conform」の
#  回帰ロック (= 記録しておかないと同じ調査を繰り返す + 挙動が黙って回帰しても気づけない)。
# --------------------------------------------------------------------------- #
def test_op06_083_self_negate_does_not_strip_external_power_buff():
    """OP06-083 オーズ 【起動メイン】= 「自分の特徴《スリラーバーク海賊団》を持つキャラ1枚を
    KOできる：このキャラは、このターン中、効果が無効になる。」
    一次情報 (cardqa_op_06, qid 19a6fe8c9b5f): 「このキャラが、他のカードやドン!!カードに
    よって『このターン中、パワー+1000。』などの効果を受けている場合、この【起動メイン】効果で
    パワーは元の値に戻りますか？」→「いいえ、元の値に戻りません。」
    効果無効は当該カード自身の効果のみを止め、外部由来の turn_buff (+1000) は残る。
    OP06-074 ゼファーと同原則の自己付与版。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    oz = InPlay.of(repo.get("OP06-083"), sickness=False)  # 印刷パワー 7000
    oz.turn_buff = 1000  # 他カード由来の「このターン中 +1000」
    me.characters = [oz]
    assert oz.power == 8000, "前提: 印刷7000 + 外部1000 = 8000"
    execute_effect({"give_keyword": {"target": "self", "keyword": "効果無効"}}, st, me, opp, oz)
    assert oz.power == 8000, (
        "自己効果無効で外部 +1000 が剥がれてはならない (公式 cardqa_op_06: 元の値に戻らない)"
    )


def test_op16_040_condition_counts_only_own_field():
    """OP16-040 ゴムゴムのトンカチ回転銃 【メイン】= 「自分の、『モンキー・Ｄ・ルフィ』と
    『Mr.3(ギャルディーノ)』がいる場合、相手のレストのコスト6以下のキャラ1枚までは、次の相手の
    リフレッシュフェイズでアクティブにならない。」
    一次情報 (cardqa_op_16, qid 182e8c480524): 「相手の場にのみ『Mr.3(ギャルディーノ)』が
    あり、自分の場に『モンキー・Ｄ・ルフィ』がある場合、この【メイン】効果で〔…〕を行うことは
    できますか？」→「いいえ、できません。」
    条件『自分の場に Luffy と Mr.3 がいる』は **自分の場のみ** を数える。相手の Mr.3 は無関係。"""
    repo, overlay = _repo(), _overlay()
    cond = {"self_field_named_all_with_power":
            {"names": ["モンキー・Ｄ・ルフィ", "Mr.3(ギャルディーノ)"]}}
    # モンキー・Ｄ・ルフィ = PRB02-005, Mr.3(ギャルディーノ) = PRB02-009 (どちらもキャラ)
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("PRB02-005"), sickness=False)]   # 自分は Luffy のみ
    opp.characters = [InPlay.of(repo.get("PRB02-009"), sickness=False)]  # 相手に Mr.3
    assert eval_condition(cond, st, me, me.characters[0]) is False, (
        "相手の場の Mr.3 を数えて条件が成立してはいけない (公式 cardqa_op_16: できません)"
    )
    # 対照: 自分の場に Mr.3 も加えれば条件成立
    me.characters.append(InPlay.of(repo.get("PRB02-009"), sickness=False))
    assert eval_condition(cond, st, me, me.characters[0]) is True, (
        "自分の場に Luffy と Mr.3 が揃えば条件成立するはず (対照)"
    )


def test_op06_016_activate_main_pays_cost_with_zero_opp_targets():
    """OP06-016 レイズ・マックス 【起動メイン】= 「このキャラを持ち主のデッキの下に置くことが
    できる：相手のキャラ1枚までを、このターン中、パワー-3000。」
    一次情報 (cardqa, qid 1a2eda8b6e9b): 「この【起動メイン】効果で相手のキャラをパワー-3000
    せずに、このキャラをデッキの下に置くことはできますか？」→「はい、できます。」
    「1枚まで」= 0枚可なので、相手キャラ 0 でもコスト(自身をデッキ下)を払って発動できる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 10
    rm = InPlay.of(repo.get("OP06-016"), sickness=False)
    me.characters = [rm]
    opp.characters = []  # 相手キャラ 0
    deck_before = len(me.deck)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-016"]
    assert len(opts) == 1, "相手キャラ0でも起動メインは legal であるべき (1枚まで=0可)"
    fire_activate_main(st, me, opp, *opts[0])
    assert rm not in me.characters, "自身がデッキの下に置かれていない"
    assert len(me.deck) == deck_before + 1, "デッキの下に 1 枚 (自身) が加わっていない"


def test_st33_002_attack_effect_no_op_when_cost_unpayable_at_zero_hand():
    """ST33-002 サカズキ 【アタック時】= 「自分の手札1枚を捨てることができる：相手の手札が
    6枚以上ある場合、相手は自身の手札1枚を捨てる。」
    一次情報 (cardqa_st_33, qid 1a3098230031): 「自分の手札が0枚のときに、この【アタック時】で
    自分の手札1枚を捨てずに相手の手札を捨てさせることはできますか？」→「いいえ、できません。」
    「：」以前は発動コスト。手札0でコストを払えないので効果(相手discard)は一切起きない。"""
    repo, overlay = _repo(), _overlay()
    # 違反(タダ撃ち)なら手札0でも opp が捨てる → このテストが落ちる
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    sk = InPlay.of(repo.get("ST33-002"), sickness=False)
    me.characters = [sk]
    me.hand = []                              # 手札0 = コスト払えず
    opp.hand = [repo.get(_FILLER)] * 6        # 相手6枚 (効果条件は満たす)
    trigger_on_attack(st, me, opp, sk, overlay)
    assert len(opp.hand) == 6, (
        "手札0でコスト未払いなのに相手が手札を捨てている (公式 cardqa_st_33: できません)"
    )
    # 対照: 自分の手札1枚あればコストを払い相手も捨てる
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    sk2 = InPlay.of(repo.get("ST33-002"), sickness=False)
    me2.characters = [sk2]
    me2.hand = [repo.get(_FILLER)]
    opp2.hand = [repo.get(_FILLER)] * 6
    trigger_on_attack(st2, me2, opp2, sk2, overlay)
    assert len(me2.hand) == 0 and len(opp2.hand) == 5, (
        "コストを払えれば自分1捨て + 相手1捨てが起きるはず (対照)"
    )


def test_st04_008_activates_with_empty_don_deck_cost_still_paid():
    """ST04-008 ジャック 【登場時】= 「自分の手札1枚を捨てることができる：ドン!!デッキから
    ドン!!1枚までをアクティブで追加する。」
    一次情報 (cardqa_st_04, qid 1ac4cb7272bb): 「ドン!!デッキにカードがない場合も効果は
    発動できますか？」→「はい。発動できます。手札を1枚捨てた後、何も起きません。」
    ドンデッキが空でも発動: コスト(手札1捨て)は払われ、追加ドンは 0 枚 (何も起きない)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    jk = InPlay.of(repo.get("ST04-008"), sickness=True)
    me.characters = [jk]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER)]
    me.don_remaining_in_deck = 0             # ドンデッキ空
    me.don_active = 0
    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, jk, overlay)
    assert len(me.hand) == hand_before - 1, "コストの手札1捨てが行われていない (公式: 手札を1枚捨てた)"
    assert me.don_active == 0, "ドンデッキ空なのにドンが追加されている (公式: 何も起きません)"


def test_st03_017_event_leaves_hand_before_self_hand_count_check():
    """ST03-017 メロメロ甘風 【カウンター】= 「自分のリーダーかキャラ1枚までを、このバトル中、
    パワー+4000。その後、自分の手札が3枚以下の場合、カード1枚を引く。」
    一次情報 (cardqa_st_03, qid 18cbf71ad63a): 「このカードを合わせて手札が4枚の場合、この効果で
    カードは引けますか？」→「はい、カードを1枚引く効果も発動します。イベントカードの発動時、
    そのカードはトラッシュに置かれ、手札の枚数には含まれません。」
    メロメロ甘風を含めて手札4枚 → 発動でトラッシュ行き → 手札3枚 → 3以下 → ドロー。"""
    repo, overlay = _repo(), _overlay()
    melo = repo.get("ST03-017")
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [melo, repo.get(_FILLER), repo.get(_FILLER), repo.get(_FILLER)]  # melo含め4枚
    me.don_active = melo.cost + 2
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # +4000 の対象
    deck_before = len(me.deck)
    _fire_counter_events(st, me, opp, (0,))   # melo は idx0
    assert len(me.deck) == deck_before - 1, (
        "イベントは発動時に手札から抜けるので手札3枚→ドローが発動するはず (公式 cardqa_st_03)"
    )
    # 対照: melo含め5枚なら発動後4枚 (>3) でドローしない
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    me2.hand = [melo] + [repo.get(_FILLER)] * 4  # 5枚
    me2.don_active = melo.cost + 2
    me2.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    deck_before2 = len(me2.deck)
    _fire_counter_events(st2, me2, opp2, (0,))
    assert len(me2.deck) == deck_before2, "発動後4枚(>3)ならドローしないはず (対照)"


def test_op01_054_ko_up_to_one_activates_with_exactly_one_target():
    """OP01-054 X・ドレーク 【登場時】= 「相手のレストのコスト4以下のキャラ1枚までを、KOする。」
    一次情報 (cardqa_op_01, qid 197c26eeb0a4): 「この【登場時】効果でKOできるキャラが1枚の場合、
    この効果を発動できますか？」→「はい、発動できます。」
    「1枚まで」は 0〜1 枚。対象が丁度1枚でも発動でき、その1枚をKOする。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    drake = InPlay.of(repo.get("OP01-054"), sickness=True)
    me.characters = [drake]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # OP01-013 cost2 (<=4)
    victim.rested = True                                    # 「相手のレスト」条件
    opp.characters = [victim]
    trigger_on_play(st, me, opp, drake, overlay)
    assert victim not in opp.characters, (
        "対象が丁度1枚のとき KO が発動していない (公式 cardqa_op_01: はい、発動できます)"
    )


def test_op06_065_cost_le_4_return_option_can_target_cost2_char():
    """OP06-065 ヴィンスモーク・ニジ 【登場時】= 「自分の場のドン!!が相手の場のドン!!の枚数
    以下の場合、以下から1つを選ぶ。・相手のコスト2以下のキャラ1枚までを、KOする。・相手の
    コスト4以下のキャラ1枚までを、持ち主の手札に戻す。」
    一次情報 (cardqa_op_06, qid 1941777d5f2e): 「この【登場時】効果で、相手のコスト2以下のキャラを
    相手の手札に戻すことはできますか？」→「はい、できます。」
    手札戻しは「コスト4以下」なので、コスト2のキャラも当然その対象に含まれる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    c2 = InPlay.of(repo.get(_FILLER), sickness=False)   # OP01-013 cost2
    opp.characters = [c2]
    opp_hand_before = len(opp.hand)
    execute_effect({"return_to_hand": "one_opponent_character_cost_le_4cost"},
                   st, me, opp, None)
    assert c2 not in opp.characters and len(opp.hand) == opp_hand_before + 1, (
        "コスト4以下の手札戻しでコスト2キャラを戻せていない (公式 cardqa_op_06: はい、できます)"
    )


def test_op16_045_self_bounce_cost_can_target_source_itself():
    """OP16-045 クロコダイル 【登場時】= 「自分のコスト2以上のキャラ1枚を持ち主の手札に戻す
    ことができる：自分の手札からコスト2以下の特徴《インペルダウン》を持つキャラカード1枚まで
    を、登場させる。」
    一次情報 (cardqa_op_16, qid 185d21c3c2e5): 「この【登場時】効果で、このキャラ自身を手札に
    戻し、自分の手札からコスト2以下の特徴《インペルダウン》を持つキャラカード1枚を登場させる
    ことはできますか？」→「はい、できます。」
    クロコダイル (コスト4≧2) 自身がコスト『自分のコスト2以上のキャラ』の対象になれる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    croc = InPlay.of(repo.get("OP16-045"), sickness=True)   # cost4 ≥2, 特徴インペルダウン
    me.characters = [croc]                                   # 場には自身のみ = 自身を戻すしかない
    me.hand = [repo.get("EB01-026")]                         # インペルダウン cost2 キャラ
    me.don_active = 10
    trigger_on_play(st, me, opp, croc, overlay)
    assert any(c.card_id == "OP16-045" for c in me.hand), (
        "クロコダイル自身がコストで手札に戻せていない (公式 cardqa_op_16: はい、できます)"
    )
    assert any(c.card.card_id == "EB01-026" for c in me.characters), (
        "コスト後にインペルダウンキャラが登場していない"
    )
    assert croc not in me.characters, "自身は場から離れているはず"


def test_st08_005_kos_all_cost1_on_both_sides_after_discard():
    """ST08-005 シャンクス 【登場時】= 「自分の手札1枚を捨てることができる：コスト1以下の
    キャラすべてを、KOする。」

    一次情報 (cardqa_st_08, qid 1d4b5518f164):
      Q「この【登場時】効果を発動し、自分の手札1枚を捨てたあと、自分のコスト1以下のキャラを
        KOするかどうか選ぶことはできますか？」
      A「いいえ、できません。この効果では、コスト1以下のキャラが、自分のキャラも相手のキャラも
        すべてKOされます。」

    退行の背景: overlay が `ko_multi` に dict (all_chara_filtered/scope:both) を渡していたが、
    `ko_multi` は list 前提 (`isinstance(v, list)` でなければ即 continue) かつ opp 側しか KO しない
    実装で、 コスト支払いだけ済ませて **一切 KO しない** silent no-op だった。 Python/Rust とも
    同じ overlay を読むため差分検証では原理的に沈黙。 公式オラクルでのみ検出。
    現在コストで両陣営の cost1 を ko + ko_self_chara に是正。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    my_c1 = InPlay.of(repo.get("EB04-002"), sickness=False)   # cost1
    my_c2 = InPlay.of(repo.get(_FILLER), sickness=False)      # OP01-013 cost2 (survivor)
    op_c1 = InPlay.of(repo.get("EB04-002"), sickness=False)   # cost1
    op_c3 = InPlay.of(repo.get("PRB02-004"), sickness=False)  # cost3 (survivor)
    src = InPlay.of(repo.get("ST08-005"), sickness=True)
    me.characters = [my_c1, my_c2, src]
    opp.characters = [op_c1, op_c3]
    me.hand = [repo.get(_FILLER)]                             # 任意コスト (手札1捨て) の弾
    trigger_on_play(st, me, opp, src, overlay)
    assert my_c1 not in me.characters, "自分の cost1 が KO されていない (公式: 自分のキャラもすべて KO)"
    assert op_c1 not in opp.characters, "相手の cost1 が KO されていない (公式: 相手のキャラもすべて KO)"
    assert my_c2 in me.characters, "cost2 まで巻き込んで KO している (対象は cost1 以下のみ)"
    assert op_c3 in opp.characters, "cost3 まで巻き込んで KO している (対象は cost1 以下のみ)"


def test_st08_005_no_ko_when_optional_discard_cost_unpayable():
    """ST08-005: 任意コスト (手札1枚を捨てる) を払えない (手札0) 時は KO 効果ごと不発。
    「〜できる：」の効果はコスト未払いなら一切起きない (タダ撃ちさせない)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    my_c1 = InPlay.of(repo.get("EB04-002"), sickness=False)
    op_c1 = InPlay.of(repo.get("EB04-002"), sickness=False)
    src = InPlay.of(repo.get("ST08-005"), sickness=True)
    me.characters = [my_c1, src]
    opp.characters = [op_c1]
    me.hand = []                                              # 捨てる弾が無い = コスト払えない
    trigger_on_play(st, me, opp, src, overlay)
    assert my_c1 in me.characters and op_c1 in opp.characters, (
        "コスト未払いなのに KO が発動している (任意コストのタダ撃ち)"
    )


# --------------------------------------------------------------------------- #
#  公式 Q&A 全件保証 バッチ (2026-08-05): 手札コスト修正 × 登場 filter / 二重ライフ
# --------------------------------------------------------------------------- #
def test_st23_001_hand_cost_reduction_counts_for_play_from_hand_cost_filter():
    """ST23-001 ウタ 「手札のこのカードは、自分のパワー10000以上のキャラがいる場合、コスト-4」。

    公式 (cardqa_st_23):
      「自分のパワー10000以上のキャラがいるときに、このキャラをコスト2として、
        『OP01-047 トラファルガー・ロー』の効果 (= 手札からコスト3以下のキャラを登場) で
        登場させることはできますか？」 → 「はい、できます」

    = 「コストN以下」 の登場 filter は **手札での現在コスト** (印字6 − 手札コスト修正4 = 2) で
    判定する。 是正前は `_matches_filter` が印字コスト6固定で cost_le:3 を弾き、 公式違反だった。
    """
    repo, overlay = _repo(), _overlay()
    from engine.effects import execute_effect
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # パワー10000以上のキャラを1体置く (= ウタの手札コスト-4 条件を満たす)
    big = InPlay.of(repo.get(_FILLER), sickness=False)
    big.static_buff = 10000
    me.characters = [big]
    me.hand = [repo.get("ST23-001")]
    assert repo.get("ST23-001").cost == 6, "前提: ウタ印字コスト6"
    # OP01-047 ロー の内側 effect (= 手札からコスト3以下キャラ1枚を登場)
    execute_effect({"play_from_hand": {"filter": {"category": "CHARACTER", "cost_le": 3}, "limit": 1}},
                   st, me, opp, None)
    assert any(c.card.card_id == "ST23-001" for c in me.characters), (
        "パワー10000+キャラ在場で ウタ(印字6→手札2) が cost3以下 の登場効果で登場できていない (公式: はい)"
    )


def test_st23_001_hand_cost_reduction_inactive_without_power10000_char():
    """対照: パワー10000以上のキャラが居ない場合、 ウタの手札コスト-4 は発動せず
    印字コスト6 のまま = cost3以下 の登場効果では登場できない (= 条件付きコスト修正の gate)。"""
    repo, overlay = _repo(), _overlay()
    from engine.effects import execute_effect
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # パワー10000+ キャラ 無し
    me.hand = [repo.get("ST23-001")]
    execute_effect({"play_from_hand": {"filter": {"category": "CHARACTER", "cost_le": 3}, "limit": 1}},
                   st, me, opp, None)
    assert not any(c.card.card_id == "ST23-001" for c in me.characters), (
        "パワー10000+キャラ不在で ウタの手札コスト-4 が効いていない (印字6 なら cost3以下 で登場不可)"
    )


def test_st23_001_normal_hand_card_unaffected_by_cost_filter_fix():
    """回帰: 手札コスト修正を持たない通常カード (in_hand_cost_minus=0) は挙動不変。
    印字コスト6 の通常キャラは cost3以下 の登場効果では依然として登場できない。"""
    repo, overlay = _repo(), _overlay()
    from engine.effects import execute_effect
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # OP02-013 エース (印字コスト7) を手札に = 手札コスト修正なし
    me.hand = [repo.get("OP02-013")]
    execute_effect({"play_from_hand": {"filter": {"category": "CHARACTER", "cost_le": 3}, "limit": 1}},
                   st, me, opp, None)
    assert not any(c.card.card_id == "OP02-013" for c in me.characters), (
        "手札コスト修正なしの印字7キャラが cost3以下 filter を通ってしまっている (fix が過剰適用)"
    )


def test_op15_109_moves_exactly_one_life_to_hand_not_two():
    """OP15-109 ニコ・ロビン: 「ライフ上1枚を手札に加える (= コスト)：麦わらリーダーなら
    デッキ上1枚をライフへ。その後、手札からコスト5以下《空島》を登場」。

    是正前は cost フィールドと do 配列の両方に life_to_hand:1 があり、 **ライフが2枚**
    手札へ移る二重発火バグだった (= カードテキストは1枚のみ)。 do 側の重複を除去。
    """
    repo, overlay = _repo(), _overlay()
    # 空島 コスト5以下キャラを手札に用意
    sky_id = None
    for c in repo.all_cards() if hasattr(repo, "all_cards") else []:
        pass
    import json as _json
    cards = _json.load(open(ROOT / "db" / "cards.json"))
    for c in cards:
        if c.get("category") == "CHARACTER" and "空島" in (c.get("features") or "") \
                and str(c.get("cost")) not in ("None", "", "-"):
            try:
                if int(c["cost"]) <= 5:
                    sky_id = c["card_id"]; break
            except (TypeError, ValueError):
                pass
    assert sky_id, "テスト前提: コスト5以下の空島キャラが存在する"
    # リーダーは麦わらの一味を持つ OP01-001
    st = _state(repo, overlay, leader0="OP01-001")
    me, opp = st.players[0], st.players[1]
    assert "麦わらの一味" in repo.get("OP01-001").features
    robin = InPlay.of(repo.get("OP15-109"), sickness=True)
    me.characters = [robin]
    me.hand = [repo.get(sky_id)]
    me.life = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 10
    trigger_on_play(st, me, opp, robin, overlay)
    g = 0
    while st.pending_choice is not None and g < 12:
        g += 1
        resolve_pending_choice(st, [0])
    # ライフ: -1 (cost で手札へ) +1 (put_top_to_life) = 3 のまま。 是正前は -2+1 = 2 になっていた。
    assert len(me.life) == 3, (
        f"ライフが {len(me.life)} 枚 = life_to_hand が二重発火している (公式: 手札へ移すのは1枚のみ)"
    )
    assert any(c.card.card_id == sky_id for c in me.characters), "空島キャラが登場していない"


def test_op15_109_life_zero_blocks_whole_effect():
    """OP15-109: ライフ0では コスト (ライフ上1枚を手札へ) を払えず、 効果全体が不発。
    公式 (cardqa_op_15): 「自分のライフが0枚の場合、この【登場時】効果で
    『デッキの上から1枚までをライフの上に加える』や『空島キャラを登場』を
    行うことはできますか？」 → 「いいえ、できません」。"""
    repo, overlay = _repo(), _overlay()
    import json as _json
    cards = _json.load(open(ROOT / "db" / "cards.json"))
    sky_id = None
    for c in cards:
        if c.get("category") == "CHARACTER" and "空島" in (c.get("features") or "") \
                and str(c.get("cost")) not in ("None", "", "-"):
            try:
                if int(c["cost"]) <= 5:
                    sky_id = c["card_id"]; break
            except (TypeError, ValueError):
                pass
    st = _state(repo, overlay, leader0="OP01-001")
    me, opp = st.players[0], st.players[1]
    robin = InPlay.of(repo.get("OP15-109"), sickness=True)
    me.characters = [robin]
    me.hand = [repo.get(sky_id)]
    me.life = []  # ライフ0
    me.deck = [repo.get(_FILLER)] * 10
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, robin, overlay)
    g = 0
    while st.pending_choice is not None and g < 12:
        g += 1
        resolve_pending_choice(st, [0])
    assert not any(c.card.card_id == sky_id for c in me.characters), (
        "ライフ0でコスト未払いなのに 空島キャラが登場している (タダ撃ち)"
    )
    assert len(me.deck) == deck_before, "ライフ0なのに put_top_to_life が走っている"


def test_op15_073_summon_cost_restricted_to_exactly_one():
    """OP15-073 ヤマ: 【登場時】「手札からコスト1の『神兵』か特徴《神官》キャラ1枚まで登場」。
    公式 (cardqa_op_15): 「コスト2以上の『神兵』や、コスト2以上で特徴《神官》を持つ
    キャラカードを登場できますか？」 → 「いいえ、できません」 (= コスト1 ちょうど のみ)。"""
    repo, overlay = _repo(), _overlay()
    import json as _json
    cards = _json.load(open(ROOT / "db" / "cards.json"))
    c2 = c1 = None
    for c in cards:
        if c.get("category") != "CHARACTER":
            continue
        is_k = "神官" in (c.get("features") or "") or c.get("name") == "神兵"
        if not is_k:
            continue
        try:
            cost = int(c["cost"])
        except (TypeError, ValueError):
            continue
        if cost == 2 and not c2:
            c2 = c["card_id"]
        if cost == 1 and not c1:
            c1 = c["card_id"]
    assert c2 and c1, "テスト前提: コスト1 と コスト2 の 神官/神兵 が存在する"
    # コスト2 は登場できない
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    yama = InPlay.of(repo.get("OP15-073"), sickness=True)
    me.characters = [yama]
    me.hand = [repo.get(c2)]
    trigger_on_play(st, me, opp, yama, overlay)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    assert not any(c.card.card_id == c2 for c in me.characters), (
        "コスト2以上の 神官/神兵 が登場している (公式: いいえ、 コスト1ちょうどのみ)"
    )
    # 対照: コスト1 は登場できる
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    yama = InPlay.of(repo.get("OP15-073"), sickness=True)
    me.characters = [yama]
    me.hand = [repo.get(c1)]
    trigger_on_play(st, me, opp, yama, overlay)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    assert any(c.card.card_id == c1 for c in me.characters), "コスト1の 神官/神兵 が登場できていない"


# --- 2026-08-05 (concurrent-run followup): OP02-013 -3000 の白ひげleader誤gate是正 ---
def test_op02_013_power_debuff_unconditional_and_distinct_targets():
    """OP02-013 ポートガス・D・エース 【登場時】= 「相手のキャラ2枚までを、このターン中、
    パワー-3000。その後、自分のリーダーが『白ひげ海賊団』を含む特徴を持つ場合、このキャラは、
    このターン中、【速攻】を得る。」

    一次情報 (cardqa_op_02, qid 20355f3c0542): 「この【登場時】効果で同じキャラを2回選び、
    パワーを-6000することはできますか？」→「いいえ、できません。」
    → 「2枚まで」= 相異なる2枚 (同一キャラの二重選択で -6000 は不可)。

    ⚠ 是正: overlay が -3000 の power_pump 自体に `if leader_features_any 白ひげ海賊団` を
    付けており、 白ひげリーダー以外だと -3000 が **一切かからない** silent no-op だった。
    公式テキストでは -3000 は無条件で、 条件がかかるのは後段の【速攻】のみ。
    Python/Rust とも同じ overlay を読むため差分検証では沈黙 = 公式オラクルでのみ検出。
    このテストは非・白ひげリーダーで -3000 を assert = 旧 overlay なら落ちる。"""
    repo, overlay = _repo(), _overlay()
    # 非・白ひげリーダー (OP01-001 = 麦わらの一味) でも -3000 は無条件でかかる
    st = _state(repo, overlay, leader0="OP01-001")
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # OP01-013 power3000
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]
    pa0, pb0 = a.power, b.power
    ace = InPlay.of(repo.get("OP02-013"), sickness=True)
    me.characters = [ace]
    trigger_on_play(st, me, opp, ace, overlay)
    assert a.power == pa0 - 3000 and b.power == pb0 - 3000, (
        "非・白ひげリーダーで -3000 が2枚に無条件でかかっていない "
        "(旧 overlay は power_pump を白ひげ leader に gate していた)"
    )
    # 相異なる2枚に分散 (同一キャラに -6000 スタックしていない)
    assert a.power == pa0 - 3000 and b.power == pb0 - 3000, (
        "同一キャラに -6000 が乗っている (公式: 同じキャラを2回は選べない)"
    )


def test_op02_013_rush_only_with_whitebeard_leader():
    """OP02-013: 後段【速攻】は『白ひげ海賊団』リーダーの時のみ (条件は速攻側にのみ残す)。"""
    repo, overlay = _repo(), _overlay()
    # 白ひげ (OP02-001) → 速攻付与
    st = _state(repo, overlay, leader0="OP02-001")
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("OP02-013"), sickness=True)
    me.characters = [ace]
    trigger_on_play(st, me, opp, ace, overlay)
    assert "速攻" in ace.granted_keywords, "白ひげリーダーで速攻が付いていない"
    # 非・白ひげ (OP01-001) → 速攻なし
    st2 = _state(repo, overlay, leader0="OP01-001")
    me2, opp2 = st2.players[0], st2.players[1]
    ace2 = InPlay.of(repo.get("OP02-013"), sickness=True)
    me2.characters = [ace2]
    trigger_on_play(st2, me2, opp2, ace2, overlay)
    assert "速攻" not in ace2.granted_keywords, "非・白ひげリーダーで速攻が付いている (条件無視)"




# --------------------------------------------------------------------------- #
#  OP13-106 コニー: 自身の【トリガー】(このカードを登場させる) で登場した時、
#  その **同じ【トリガー】発動** を自身の【相手のターン中】(【トリガー】発動時
#  【ブロッカー】を得る) で拾ってはならない。
#
#  一次情報 (db/faq/cardqa_op_13):
#    「このキャラが【トリガー】効果で登場した時、このキャラ自身の【相手のターン中】
#      効果で【ブロッカー】を得ることはできますか？」
#    → 「いいえ、できません。この【相手のターン中】効果は、このキャラが場にある間に
#        【トリガー】効果を発動した際に発動できる効果です。」
#
#  是正前バグ (Python/Rust 同一 overlay = 差分検証では沈黙):
#    (1) overlay に `when:"trigger"` で自身へ【ブロッカー】を付与する誤エントリがあり、
#        コニー自身のライフトリガー解決中に直接ブロッカーが付いていた。
#    (2) engine が `on_self_trigger_fired` を play_self 解決の **後** に発火するため、
#        自身を登場させたトリガー発動を登場後のコニーが拾ってブロッカーを得ていた。
#  是正: (1) 誤 overlay エントリを削除。 (2) trigger 解決の前に場の iid を snapshot し、
#        その集合に居るカードだけ on_self_trigger_fired を発火する (登場元は除外)。
# --------------------------------------------------------------------------- #
def test_op13_106_connie_no_blocker_when_played_by_own_trigger():
    """コニーを自身の【トリガー】で登場させても【ブロッカー】は得ない (公式: いいえ)。"""
    from engine.game import _resolve_life_taken
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.turn_player_idx = 1  # 相手(P1)のターン = コニー所有者(P0)から見て「相手のターン中」
    defender, attacker = st.players[0], st.players[1]
    # ライフ札としてコニーを引かれ、 【トリガー】(このカードを登場させる) を発動。
    _resolve_life_taken(st, attacker, defender, repo.get("OP13-106"), use_trigger=True)
    on_field = [c for c in defender.characters if c.card.card_id == "OP13-106"]
    assert len(on_field) == 1, "コニーが【トリガー】で登場していない (前提が崩れている)"
    assert "ブロッカー" not in on_field[0].granted_keywords, (
        "自身の【トリガー】で登場したコニーが【ブロッカー】を得ている (公式: いいえ)"
    )


def test_op13_106_connie_gets_blocker_when_already_on_field():
    """対照: 既に場にいるコニーは、別のカードの【トリガー】発動でブロッカーを得る (公式: はい)。"""
    from engine.game import _resolve_life_taken
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.turn_player_idx = 1
    defender, attacker = st.players[0], st.players[1]
    connie = InPlay.of(repo.get("OP13-106"), sickness=False)
    defender.characters = [connie]
    # 別の【トリガー】持ちカード (EB02-018 バギー) をライフから発動させる。
    _resolve_life_taken(st, attacker, defender, repo.get("EB02-018"), use_trigger=True)
    still = [c for c in defender.characters if c.card.card_id == "OP13-106"]
    assert len(still) == 1, "場のコニーが消えている (前提が崩れている)"
    assert "ブロッカー" in still[0].granted_keywords, (
        "場にいたコニーが【トリガー】発動でブロッカーを得ていない (公式: はい)"
    )


# --------------------------------------------------------------------------- #
#  OP09-118 ゴール・D・ロジャー vs ST09-007 しのぶ — ブロッカー宣言時トリガーの
#  同時解決順 (= ターンプレイヤー先)。
#
#  一次情報 (db/faq/cardqa_op_09.json、 OP09-118):
#    「お互いのライフが1枚の時、 自分がこのキャラでアタックし、 相手が『ST09-007 しのぶ』で
#      ブロックしました。 この時、 相手が『ST09-007 しのぶ』の【ブロック時】効果を発動し
#      ライフが0枚になった場合、 このキャラの効果で自分はゲームに勝利しますか？」
#    → 「いいえ、 勝利しません。」
#
#  ロジャーの【相手が【ブロッカー】を発動した時】(= アタッカー = ターンプレイヤー) の勝利判定は
#  しのぶの【ブロック時】(= ブロッカー = 非ターンプレイヤー) より **先に** 解決する。 その時点で
#  相手ライフは 1 枚なので勝利条件 (自分か相手のライフ0) を満たさない。
#  是正前は on_block を先に処理していた (= しのぶが自ライフを0にした後にロジャーが判定 → 誤って
#  勝利)。 Python/Rust 共有バグ (= 差分検証では原理的に沈黙する)。
# --------------------------------------------------------------------------- #
def test_blocker_declaration_triggers_resolve_turn_player_first():
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP01-001", leader1="OP01-001")
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 1          # 自分のライフ 1
    opp.life = [repo.get(_FILLER)] * 1          # 相手のライフ 1
    roger = InPlay.of(repo.get("OP09-118"), sickness=False)   # 速攻・勝利効果
    me.characters = [roger]
    shinobu = InPlay.of(repo.get("ST09-007"), sickness=False)  # ブロッカー + 自ライフ→手札
    opp.characters = [shinobu]
    opp.don_active = 5

    apply_action(
        st,
        AttackLeader(attacker_iid=roger.instance_id, blocker_iid=shinobu.instance_id),
    )

    # ロジャーの勝利判定が先 → その時点で相手ライフ 1 = 勝利しない。
    assert not st.game_over and st.winner is None, (
        "しのぶの【ブロック時】(非ターンプレイヤー) がロジャーの勝利判定 (ターンプレイヤー) より "
        "先に解決し、 誤って勝利している (公式 cardqa_op_09: いいえ)"
    )
    # 前提が崩れていない (= しのぶが実際に自ライフを0にした = テストが空回りでない) ことを確認。
    assert len(opp.life) == 0, "しのぶの【ブロック時】が発動していない (テストの妥当性が崩れている)"


# --------------------------------------------------------------------------- #
#  EB02-030 「仲間の夢を笑われた時だ!!!!」 — 「自分のキャラすべては…バトルでKOされる場合、
#  代わりに手札1枚を捨てる」 の範囲 = **発動時点で場にいるキャラのみ**。
#
#  一次情報 (db/faq/cardqa_eb_02.json、 EB02-030):
#    「相手のターン中、 この【カウンター】効果を発動した後に登場した自分のキャラは、 バトルで
#      KOされる場合に代わりに手札1枚を捨てることはできますか？」
#    → 「いいえ、 できません。」
#
#  是正前は player 単位の turn フラグ (turn_battle_ko_save_discard) で救済しており、 発動後に
#  登場したキャラも救済していた (= 違反)。 per-InPlay フラグに変更し、 発動時に場にいた各キャラ
#  だけに付与する。 Python/Rust 共有バグ。
# --------------------------------------------------------------------------- #
def _eb02_setup(repo, overlay):
    # P1 (index1) がターンプレイヤー (アタッカー)、 P0 が EB02-030 を撃った防御側。
    st = _state(repo, overlay, leader0="OP01-001", leader1="OP01-001")
    st.turn_player_idx = 1
    st.turn_number = 8
    p0, p1 = st.players[0], st.players[1]
    p1.don_active = 5
    atk = InPlay.of(repo.get(_FILLER), sickness=False)   # 元々パワー3000
    atk.attached_dons = 2                                 # → 現在 5000 (3000 の防御キャラを KO)
    p1.characters = [atk]
    return st, p0, p1, atk


def test_eb02_030_saves_character_present_at_activation():
    """発動時に場にいたキャラは バトルKO 代替で 手札1捨てて生存する (= テスト妥当性 + 救済の実在)。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1, atk = _eb02_setup(repo, overlay)
    c_old = InPlay.of(repo.get(_FILLER), sickness=False)  # 現在 3000 (rested = 直接アタック可)
    c_old.rested = True
    p0.characters = [c_old]
    p0.hand = [repo.get(_FILLER)] * 2
    # EB02-030 の【カウンター】救済を発動 (発動時 c_old が場にいる)
    grant = next(e for e in overlay.get("EB02-030").effects if e.get("when") == "counter")
    for prim in grant["do"]:
        execute_effect(prim, st, p0, p1, None)
    hand_before = len(p0.hand)
    apply_action(st, AttackCharacter(attacker_iid=atk.instance_id,
                                     target_iid=c_old.instance_id))
    assert c_old in p0.characters, "発動時に居たキャラが バトルKO 代替で救済されていない"
    assert len(p0.hand) == hand_before - 1, "救済の手札1捨てが起きていない"


def test_eb02_030_does_not_save_character_played_after_activation():
    """発動 **後** に登場したキャラは救済されず、 通常どおり バトルKO される (公式: いいえ)。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1, atk = _eb02_setup(repo, overlay)
    c_old = InPlay.of(repo.get(_FILLER), sickness=False)
    p0.characters = [c_old]
    p0.hand = [repo.get(_FILLER)] * 2
    grant = next(e for e in overlay.get("EB02-030").effects if e.get("when") == "counter")
    for prim in grant["do"]:
        execute_effect(prim, st, p0, p1, None)
    # 救済 発動 **後** に登場したキャラ
    c_new = InPlay.of(repo.get(_FILLER), sickness=False)
    c_new.rested = True
    p0.characters.append(c_new)
    hand_before = len(p0.hand)
    apply_action(st, AttackCharacter(attacker_iid=atk.instance_id,
                                     target_iid=c_new.instance_id))
    assert c_new not in p0.characters, (
        "発動後に登場したキャラが バトルKO 代替で救済されている (公式 cardqa_eb_02: いいえ)"
    )
    assert len(p0.hand) == hand_before, "救済されないはずなのに手札を捨てている"
# --------------------------------------------------------------------------- #
#  効果ダメージ (「Nダメージを与える」) でも ライフ札の【トリガー】は発動できる
#     一次情報 (`db/faq/cardqa_eb_03.json`、 EB03-055 ニコ・ロビン 【KO時】相手に1ダメージ):
#       「相手のこのカードの【KO時】効果で自分がダメージを受け、ライフから【トリガー】を
#         持つカードを手札に加える場合、その【トリガー】効果を発動することはできますか？」
#       → 「はい、できます。」
#     rules 7-1-4-1-1-2 / SKILL.md line 180:「効果 1 ダメージ → 相手はライフ上1枚を手札へ
#       (or トリガー発動)」。 = 「ダメージを与える」 は 「ライフを手札に加える」 (=移動、
#       トリガー無し) と区別され、 damage 経路なので【トリガー】が発動する。
#     旧実装 (deal_opp_leader_damage): opp.hand.append 直行で【トリガー】を握り潰していた。
#     Python/Rust とも同型なので差分検証では原理的に沈黙 (= FAQ 台帳でしか摘出できない型)。
# --------------------------------------------------------------------------- #
def _first_unconditional_draw_trigger_card(overlay) -> str:
    """条件なしの【トリガー】= draw だけを持つカードを 1 枚返す (無ければ None)。"""
    for cid, bundle in overlay.items():
        if "_" in cid:
            continue
        for e in bundle.effects:
            # ⚠ **発動コストを持つものは除外**する。 コストを払えない【トリガー】は そもそも
            #   発動できない (公式 10-1-5 + 4-10、 2026-08-11 に engine が payability を見るように
            #   なった) ので、 「無条件で発動する」 例には使えない (実際 EB01-038 は pay_don:1 を
            #   持ち、 ドン 0 の最小 state では発動しない = テストの前提が崩れる)。
            _cost = e.get("cost") or {}
            if any(k != "once_per_turn" for k in _cost):
                continue
            if (e.get("when") == "trigger" and not e.get("if") and not e.get("conditions")
                    and len(e.get("do") or []) == 1 and "draw" in (e["do"][0])):
                return cid
    return None


def test_effect_damage_fires_lifecard_trigger():
    """効果ダメージで手札に加わるライフ札が【トリガー】を持てば発動する (公式 cardqa_eb_03)。"""
    repo, overlay = _repo(), _overlay()
    trig_cid = _first_unconditional_draw_trigger_card(overlay)
    assert trig_cid is not None, "前提が崩れている: 無条件 draw トリガーのカードが存在しない"

    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # 相手ライフの一番上を「トリガー(draw)持ち」に、 残りは効果なしバニラに。
    opp.life = [repo.get(trig_cid), repo.get(_FILLER), repo.get(_FILLER)]
    opp.hand = []
    deck0 = len(opp.deck)
    trash0 = len(opp.trash)

    execute_effect({"deal_opp_leader_damage": 1}, st, me, opp, None)

    # 【トリガー】が発動 = デッキから draw (deck -1) + トリガー札は トラッシュへ (hand ではない)。
    assert len(opp.deck) == deck0 - 1, (
        "効果ダメージでライフ札の【トリガー】(draw) が発動していない "
        "(旧実装は opp.hand.append 直行でトリガーを握り潰していた)"
    )
    assert len(opp.trash) == trash0 + 1, "発動した【トリガー】札がトラッシュに置かれていない"
    assert repo.get(trig_cid) not in opp.hand, "発動したのにトリガー札が手札に残っている"


def test_effect_damage_vanilla_life_goes_to_hand_no_trigger():
    """対照: トリガーを持たないライフ札は 効果ダメージで 手札へ入るだけ (draw しない)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3   # OP01-013 = バニラ (トリガー無し)
    opp.hand = []
    deck0 = len(opp.deck)
    hand0 = len(opp.hand)

    execute_effect({"deal_opp_leader_damage": 1}, st, me, opp, None)

    assert len(opp.hand) == hand0 + 1, "バニラのライフ札が手札に加わっていない"
    assert len(opp.deck) == deck0, "トリガーが無いのに draw している"
    assert len(opp.life) == 2, "ライフが 1 枚減っていない"


# =========================================================================== #
#  公式 Q&A conformance (2026-08-05 batch) — 全件保証 routine で検査した 9 件。
#  いずれも engine が公式裁定どおりに動くことを確認した conform ケースを
#  回帰テストで固定する (原文を各テストにコメント引用)。
# =========================================================================== #

def test_op15_097_event_placed_in_trash_before_main_counts_itself():
    """OP15-097 「人として恥ずかしいわ」 の【メイン】(トラッシュ10枚以上) は、
    手札から使うと 自身が先にトラッシュへ入る (8-4-2) ので トラッシュ9枚でも成立する。

    cardqa_op_15 (原文):
      Q: 自分のトラッシュが9枚の時に、このイベントカードの【メイン】や【トリガー】の効果を
         使うことはできますか？
      A: この場合、このイベントを手札から使用して【メイン】効果を発動した場合は、…アタックできない。
         を行うことができますが、この【トリガー】効果によって発動した場合はトラッシュがまだ9枚のため、
         この【メイン】効果でなにも起こりません。

    手札プレイ経路 (公開→コスト→トラッシュ→効果) が守られていないと、 効果解決時に
    トラッシュ = 9 のままとなり cannot_attack が入らない = 公式違反。
    """
    from engine.game import PlayEvent
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER)] * 9          # トラッシュ = 9 (10 未満)
    me.hand = [repo.get("OP15-097")]
    me.don_active = 5
    victim = InPlay.of(repo.get(_FILLER), sickness=False)   # OP01-013 = cost2 (<=5)
    opp.characters = [victim]

    apply_action(st, PlayEvent(hand_idx=0))

    assert len(me.trash) == 10, "イベントが効果解決前にトラッシュへ置かれていない (8-4-2 違反)"
    assert victim.cannot_attack_through_opp_turn, (
        "トラッシュ9枚でも 手札から使えば 自身が10枚目に入り メイン が成立するはず"
    )


def test_op15_097_main_does_nothing_when_trash_below_threshold_without_self():
    """対照: 自身がトラッシュに入らない文脈 (= トリガー解決時点) で トラッシュ9枚なら 不発。

    上の cardqa_op_15 後段 (【トリガー】発動時は トラッシュ9枚のまま = 何も起こらない) を固定。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER)] * 9          # 自身を数えない = 9 のまま
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    eff = next(e for e in overlay.get("OP15-097").effects if e.get("when") == "main")
    assert eval_condition(eff.get("if"), st, me) is False, \
        "トラッシュ9枚で メイン条件(>=10) が成立している"
    if eval_condition(eff.get("if"), st, me):
        for prim in eff["do"]:
            execute_effect(prim, st, me, opp, None)
    assert not victim.cannot_attack_through_opp_turn, \
        "条件不成立なのに cannot_attack が入っている"


def test_op09_037_end_of_turn_activates_only_itself():
    """OP09-037 リム の【自分のターン終了時】は 「このキャラ」 1枚のみアクティブにする。

    cardqa_op_09 (原文):
      Q: 自分の場にレストのこのキャラが3枚あり、他に自分のキャラが無い場合、この
         【自分のターン終了時】効果でこのキャラ3枚をアクティブにできますか？
      A: いいえ、1枚のみアクティブにできます。

    untap 対象が 「self」 でなく all_self 等に化けると 3枚とも起きる = 違反。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP09-037"), sickness=False) for _ in range(3)]
    for c in me.characters:
        c.rested = True
    eff = next(e for e in overlay.get("OP09-037").effects if e.get("when") == "end_of_turn")
    assert eval_condition(eff.get("if"), st, me), "レスト3枚 = 条件成立のはず"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.characters[0])
    active = [i for i, c in enumerate(me.characters) if not c.rested]
    assert active == [0], f"発動元 1 枚のみ起きるはず (実際に起きた: {active})"


def test_op05_008_don_attach_is_single_target_no_split():
    """OP05-008 チャカ は 「リーダーかキャラ1枚」 に レストのドン2枚を付与 = 分配不可。

    cardqa_op_05 (原文):
      Q: 自分のリーダーとキャラに1枚ずつドン!!を付与できますか？
      A: いいえ、できません。

    単一 target に count 2 が入る = リーダー1 + キャラ1 の分配は起きない。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    me.don_rested = 3
    chaka = InPlay.of(repo.get("OP05-008"), sickness=False)
    chaka.attached_dons = 1                     # gate self_attached_don_ge:1
    other = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [chaka, other]
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP05-008"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    pc = st.pending_choice
    assert pc is not None and pc.get("kind") == "target_pick", "単一 target 選択が立たない"
    resolve_pending_choice(st, [0])             # リーダーを選ぶ
    assert me.leader.attached_dons == 2, "選んだ 1 対象に 2 枚まとめて付くはず"
    assert chaka.attached_dons == 1 and other.attached_dons == 0, \
        "他の対象にドンが漏れている (分配になっている)"


def test_st17_002_bounce_cost_payable_without_shichibukai_leader():
    """ST17-002 ロー の【登場時】は コロン前 (自キャラ1枚を手札に戻す) が発動コスト。
    リーダーが《王下七武海》を持たなくても コストは支払える (コロン後だけ gate)。

    cardqa_st_17 (原文):
      Q: 自分のリーダーが特徴《王下七武海》を持たない場合、この【登場時】効果で
         自分のキャラ1枚を手札に戻すことはできますか？
      A: はい、できます。この場合、相手のコスト4以下のキャラ1枚を手札に戻すことはできません。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP01-001", human_idx=0)  # OP01-001 = 非・王下七武海
    me, opp = st.players[0], st.players[1]
    assert "王下七武海" not in (me.leader.card.features or ()), "前提: リーダーは非七武海"
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]   # cost2 (<=4)
    src = InPlay.of(repo.get("ST17-002"), sickness=False)
    me.characters = [src]
    opp_before = len(opp.characters)

    trigger_on_play(st, me, opp, src, overlay)
    guard = 0
    while st.pending_choice and guard < 8:
        pc = st.pending_choice
        guard += 1
        raw = pc.get("cards") or pc.get("candidates") or []
        if pc.get("kind") == "optional_cost_confirm":
            resolve_pending_choice(st, [1])     # コスト支払いを承諾
        elif raw:
            resolve_pending_choice(st, [0])
        else:
            resolve_pending_choice(st, [])
    # コストは支払えた (自キャラが場を離れて手札へ戻った)
    assert src not in me.characters, "コスト (自キャラを手札に戻す) が支払えていない"
    # コロン後 (相手コスト4以下を戻す) は 七武海でないので 発動しない
    assert len(opp.characters) == opp_before, \
        "リーダーが非七武海なのに 相手キャラが手札へ戻された (gate 漏れ)"


def test_op16_115_search_excludes_yamimizu_by_name():
    """OP16-115 闇水 の【メイン】は トラッシュから 「闇水」以外の【トリガー】持ちを手札へ。
    別番号でも 名前が 「闇水」 のカード (OP09-097) は除外される。

    cardqa_op_16 (原文):
      Q: この【メイン】効果で、自分のトラッシュの「OP09-097 闇水」を手札に加えることは
         できますか？
      A: いいえ、できません。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP09-081", human_idx=0)   # 黒ひげ海賊団 リーダー
    me, opp = st.players[0], st.players[1]
    assert "黒ひげ海賊団" in (me.leader.card.features or ())
    # トラッシュに 別番号の 「闇水」(OP09-097, トリガー持ち) と 別名のトリガー持ち (対照) を置く。
    yami = repo.get("OP09-097")
    import json as _json
    cards = {c["card_id"]: c for c in _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))}
    ctrl_id = next(cid for cid, c in cards.items()
                   if c.get("trigger") and c["name"] != "闇水" and "_" not in cid)
    ctrl = repo.get(ctrl_id)
    me.trash = [yami, ctrl]

    eff = next(e for e in overlay.get("OP16-115").effects if e.get("when") == "main")
    assert eval_condition(eff.get("if"), st, me)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    # 有効候補は 対照1枚のみ (闇水は名前除外) → 自動で手札へ。 闇水はトラッシュに残る。
    hand_names = [c.name for c in me.hand]
    assert "闇水" not in hand_names, f"「闇水」が手札に加わった (名前除外が効いていない): {hand_names}"
    assert ctrl.name in hand_names, f"別名のトリガー札が手札に加わっていない: {hand_names}"
    assert yami in me.trash, "闇水が除外されずトラッシュから移動している"


def test_op15_001_leader_debuff_not_applied_at_zero_characters():
    """OP15-001 クリーク の【相手のターン中】(自キャラが《東の海》のみ) は、
    自キャラ0枚では成立しない (vacuous-true にしない)。

    cardqa_op_15 (原文):
      Q: 自分のキャラが0枚の時、この【相手のターン中】効果で相手のキャラすべては
         パワー-2000されますか？
      A: いいえ、されません。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP15-001")
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    st.turn_player_idx = 1                       # 相手のターン
    eff = next(e for e in overlay.get("OP15-001").effects
               if e.get("when") == "on_attached_don")
    cond = eff.get("if")
    me.characters = []
    assert eval_condition(cond, st, me) is False, \
        "自キャラ0枚で条件が成立している (vacuous-true バグ)"
    # 対照: 東の海 キャラ 1 体なら成立
    me.characters = [InPlay.of(repo.get("OP15-008"), sickness=False)]   # クリーク (東の海)
    assert eval_condition(cond, st, me) is True


def test_st24_004_stay_rested_can_target_already_rested_opponent():
    """ST24-004 ロー&ベポ の【登場時】は 既にレストの相手キャラも対象にでき、
    次の相手リフレッシュでアクティブにならない状態にできる。

    cardqa_st_24 (原文):
      Q: この【登場時】効果で相手のレストのキャラ1枚を選び、次の相手のリフレッシュ
         フェイズでアクティブにならない状態にすることはできますか？
      A: はい、できます。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True                         # 既にレスト
    opp.characters = [victim]
    src = InPlay.of(repo.get("ST24-004"), sickness=False)
    me.characters = [src]

    trigger_on_play(st, me, opp, src, overlay)
    guard = 0
    while st.pending_choice and guard < 8:
        pc = st.pending_choice
        guard += 1
        raw = pc.get("cards") or pc.get("candidates") or []
        resolve_pending_choice(st, [0] if raw else [])
    assert getattr(victim, "stay_rested_next_refresh", False), \
        "既レストの相手キャラに 『次のリフレッシュで起きない』 が付与されていない"


def test_st26_001_in_hand_cost_minus_enables_law_summon():
    """ST26-001 おそばマスク の手札コスト-5 (元々パワー7000以上のサンジ/サン五郎が居る場合) は、
    OP01-047 ロー の cost3以下 登場 filter に反映される (= 現在の手札コストで判定)。

    cardqa_st_26 (原文):
      Q: 自分の元々のパワー7000以上のキャラの、「サン五郎」か「サンジ」がいるときに、
         このキャラカードをコスト2として、「OP01-047 トラファルガー・ロー」の効果で
         登場させることはできますか？
      A: はい、できます。
    """
    from engine.game import _compute_in_hand_cost_minus
    from engine.effects import _matches_filter_hand
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    osoba = repo.get("ST26-001")                 # 印刷コスト 7
    law_filter = {"category": "CHARACTER", "cost_le": 3}

    # サンジ (印刷パワー7000) を置く → 手札コスト -5 = 2
    me.characters = [InPlay.of(repo.get("OP09-065"), sickness=False)]
    me.hand = [osoba]
    ihm = _compute_in_hand_cost_minus(st, me, osoba)
    assert ihm == 5, f"手札コスト -5 が効いていない (ihm={ihm})"
    assert _matches_filter_hand(osoba, law_filter, ihm), \
        "コスト2 (=7-5) なのに ロー の cost3以下 登場対象にならない"

    # 対照: 7000以上のサンジ/サン五郎が居なければ 減額なし = コスト7 = 対象外
    me.characters = []
    ihm0 = _compute_in_hand_cost_minus(st, me, osoba)
    assert ihm0 == 0 and not _matches_filter_hand(osoba, law_filter, ihm0), \
        "条件を満たさないのに 手札コストが下がっている"

    # end-to-end: OP01-047 ロー の play_from_hand (cost3以下 CHARACTER登場) の候補に
    # おそばマスクが 実際に載る (= 登場経路が手札コスト減算を honor する)。
    st.human_player_idx = 0
    st.forced_human_actor_idx = 0
    me.characters = [InPlay.of(repo.get("OP09-065"), sickness=False)]   # サンジ (P7000)
    me.hand = [osoba, repo.get(_FILLER)]
    me.don_active = 10
    execute_effect({"play_from_hand": {"filter": law_filter, "limit": 1}},
                   st, me, opp, me.characters[0])
    pc = st.pending_choice
    cands = (pc.get("candidates") or pc.get("cards") or []) if pc else []
    assert any(c.get("card_id") == "ST26-001" for c in cands), \
        "OP01-047 ロー の cost3以下 登場候補に おそばマスク(現在cost2) が載っていない"


def test_op14_060_redirect_can_target_own_blocker():
    """OP14-060 ドフラミンゴ の【相手のアタック時】redirect は 自分の【ブロッカー】キャラも
    対象にできる (効果によるアタック対象変更は 「ブロック」 とは別物)。

    cardqa_st_29 (原文):
      Q: 【ブロック不可】を持つカードがキャラにアタックした場合、…OP14-060…の
         【相手のアタック時】効果や…EB01-038 オカマ道…の【カウンター】効果で、そのアタックの
         対象を【ブロッカー】を持つキャラに変更することはできますか？
      A: はい、できます。効果によるアタック対象の変更は「【ブロッカー】によるブロック」とは
         異なります。
    """
    from engine.effects import _resolve_target
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]   # me = 防御側 (OP14-060 保持)
    st.turn_player_idx = 1                    # 相手のターン
    dofla = InPlay.of(repo.get("OP14-060"), sickness=False)
    blocker = InPlay.of(repo.get("OP09-031"), sickness=False)  # ブロッカー + ドンキホーテ海賊団
    assert "ブロッカー" in (blocker.card.text or ""), "前提: OP09-031 はブロッカー"
    me.characters = [dofla, blocker]
    spec = {"type": "all_self_chara_filtered", "filter": {"feature": "ドンキホーテ海賊団"}}
    targets = _resolve_target(spec, st, me, opp, dofla,
                              outer_kind="redirect_attack", outer_value=spec)
    assert any(t.instance_id == blocker.instance_id for t in targets), \
        "ブロッカーが redirect の対象候補に入っていない (ブロックと混同している)"


def test_op02_025_filtered_turn_cost_reduction_applies_at_payment():
    """OP02-025 錦えもん 【起動メイン】: 「このターン中、次に登場させるコスト3以上《ワノ国》キャラの
    支払うコストは1少なくなる」割引が、 legal_actions だけでなく **実際の支払い (apply_action)** でも効く。

    公式 Q&A (cardqa_op_02, qid 27f57268a683):
      Q: 自分のキャラが0枚のときにこの【起動メイン】を発動したあと、手札から《ワノ国》を持たない
         キャラを登場させました。この次に手札から登場させるコスト3の《ワノ国》を持つキャラのコストは
         1少なくなりますか？
      A: はい、少なくなります。

    是正前バグ: 割引は play_cost_reductions_filtered_turn に登録されるが、 支払い経路の
    _compute_filtered_cost_reduction が **静的リストしか読まず** ターン限定リストを無視していた。
    legal_actions._eff_cost は両リストを読むため「2ドンで登場可」 と表示するのに、 apply_action は
    全コスト(3)を要求して not enough don で失敗する不整合だった。
    """
    from engine.effects import list_activate_main_effects, fire_activate_main
    from engine.game import (_compute_filtered_cost_reduction, _compute_in_hand_cost_minus,
                             legal_actions, apply_action, PlayCharacter)
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP02-025")
    me, opp = st.players[0], st.players[1]
    me.characters = []  # 自キャラ0枚 (条件 self_chara_count_le:1 を満たす)

    # 錦えもんリーダーの【起動メイン】を発動 = 割引を登録
    fired = False
    for o in list_activate_main_effects(st, me, overlay):
        fire_activate_main(st, me, opp, *o)
        fired = True
        break
    assert fired, "OP02-025 の【起動メイン】が発動できていない"
    assert me.play_cost_reductions_filtered_turn, "ターン限定割引が登録されていない"

    # コスト3のワノ国キャラを探す
    import json
    from pathlib import Path
    cards = json.loads((Path(__file__).resolve().parent.parent / "db" / "cards.json").read_text())
    wano3 = next(c["card_id"] for c in cards
                 if not c.get("variant") and c.get("category") == "CHARACTER"
                 and (c.get("cost") or "").isdigit() and int(c["cost"]) == 3
                 and "ワノ国" in (c.get("features") or ""))
    card = repo.get(wano3)

    # 非・ワノ国キャラを1枚登場 (割引を消費しないことを確認)
    nonwano = next(c["card_id"] for c in cards
                   if not c.get("variant") and c.get("category") == "CHARACTER"
                   and (c.get("cost") or "").isdigit() and int(c["cost"]) == 2
                   and "ワノ国" not in (c.get("features") or ""))
    me.don_active = 10
    me.hand = [repo.get(nonwano)]
    apply_action(st, PlayCharacter(hand_idx=0))

    # 支払い経路のコスト計算 = 印字3 - 割引1 = 2 (是正前は割引が効かず 3)
    pay_cost = (card.cost - me.play_cost_reduction
                - _compute_in_hand_cost_minus(st, me, card)
                - _compute_filtered_cost_reduction(me, card))
    assert pay_cost == 2, (
        f"ワノ国コスト3キャラの支払いコストが {pay_cost} (期待2)。 "
        "ターン限定 filter 割引が支払い経路に反映されていない (非ワノ国登場でも消費されない)"
    )

    # 2 ドンちょうどで実際に登場できる (legal_actions と apply_action が整合)
    me.hand = [card]
    me.don_active = 2
    plays = [a for a in legal_actions(st) if isinstance(a, PlayCharacter)]
    assert plays, "2ドンでワノ国コスト3が legal になっていない"
    apply_action(st, plays[0])  # 是正前は not enough don で ValueError
    assert any(c.card.card_id == wano3 for c in me.characters), "ワノ国コスト3が登場していない"


# --------------------------------------------------------------------------- #
#  「相手がイベントを発動した時」 は イベント **発動** のみ、 ライフ【トリガー】発動では発火しない
#  (2026-08-05 是正、 cardqa_op_11)
#     公式 (cardqa_op_11): 「自分のターン中に、 相手がイベントの【トリガー】効果を発動した時、
#                          このキャラの効果を発動できますか？」 →「いいえ、 できません。」
#     = 「相手がイベントを発動した時」 (OP11-012 フランキー / OP06-044 ギオン / OP01-004 ウソップ)
#       は 相手が **イベントカードを発動** (手札/カウンター) した時のみ。 ライフに置かれた
#       イベントの【トリガー】キーワードを発動しても発火しない。
#     ⚠ 是正前は フランキー等も OP11-102 ケイミー (「イベントか【トリガー】」) と同じ
#       `opp_event_or_trigger_fired` に配線され、 ライフ【トリガー】でも誤発火していた。
#       overlay は Python/Rust 共通 = 差分検証では永久に沈黙するクラスのバグ。
# --------------------------------------------------------------------------- #
def _event_react_board(repo, ov, reactor_id):
    import random
    from engine.core import GameState, InPlay, Phase, Player
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(_FILLER)] * 10
        p.life = [repo.get(_FILLER)] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 9
    reactor = InPlay.of(repo.get(reactor_id), sickness=False)
    ally = InPlay.of(repo.get(_FILLER), sickness=False)   # 印字パワー 3000
    p0.characters = [reactor, ally]
    return st, p0, p1, reactor, ally


def test_opp_event_only_reactive_fires_on_event_play():
    """OP11-012 フランキー 「相手がイベントを発動した時」 は 相手のイベント発動で発火する。"""
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_main_event

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    # OP08-036 = 【トリガー】を持つイベント (= 発動対象カードとして使う)
    st, p0, p1, franky, ally = _event_react_board(repo, ov, "OP11-012")
    before = ally.power
    # p1 (=相手) がイベントを発動 → p0 (=フランキー所有) の opp_event_played が発火
    trigger_main_event(st, p1, p0, repo.get("OP08-036"), ov)
    assert ally.power == before + 2000, (
        "相手のイベント発動でフランキー (相手がイベントを発動した時: 自キャラ+2000) が発火していない"
    )


def test_opp_event_only_reactive_does_not_fire_on_life_trigger():
    """OP11-012 フランキー は ライフの【トリガー】発動では発火しない (公式 cardqa_op_11 = いいえ)。

    是正前は `opp_event_or_trigger_fired` 配線で ライフ【トリガー】でも誤って +2000 していた。
    """
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_lifecard_trigger

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1, franky, ally = _event_react_board(repo, ov, "OP11-012")
    before = ally.power
    # p0 のターン中に p1 のライフ【トリガー】(OP08-036) が発動する状況
    trigger_lifecard_trigger(st, p1, p0, repo.get("OP08-036"), ov)
    assert ally.power == before, (
        "ライフ【トリガー】発動なのにフランキーが発火している "
        "(公式 cardqa_op_11: イベントの【トリガー】発動では発火しない)"
    )


def test_event_or_trigger_reactive_still_fires_on_life_trigger():
    """OP11-102 ケイミー 「イベントか【トリガー】を発動した時」 は ライフ【トリガー】でも発火する。

    フランキー 是正が「トリガー反応」 まで巻き添えにしていないことの対照 (回帰ガード)。
    """
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_lifecard_trigger

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1, kaimi, ally = _event_react_board(repo, ov, "OP11-102")
    p1.life = [repo.get(_FILLER)] * 3        # opp_life_ge 2 を満たす
    self_life0, opp_life0 = len(p0.life), len(p1.life)
    trigger_lifecard_trigger(st, p1, p0, repo.get("OP08-036"), ov)
    assert len(p0.life) == self_life0 - 1 and len(p1.life) == opp_life0 - 1, (
        "ケイミー (イベントか【トリガー】を発動した時: 両者ライフ-1) が ライフ【トリガー】で発火していない"
    )


# --------------------------------------------------------------------------- #
#  EB02-059 「お前がいねェと…!!」 【カウンター】 の「その後」 登場 filter
#     公式一次情報 (cardqa_eb_02):
#       「この【カウンター】効果で、コスト6以上の「サンジ」や黄以外の色の「サンジ」を
#        登場できますか？」 → 「いいえ、できません」
#     公式テキスト: 「…自分の手札からコスト5以下の黄の、特徴《麦わらの一味》を持つ
#       キャラカードか「サンジ」1枚までを、登場させる。」
#     = 「コスト5以下の黄の」 は 麦わらの一味キャラ **と サンジ の両方** に掛かる。
#     是正前は overlay の or ブランチが {"name":"サンジ"} のみで、 cost/color 制約が抜けており
#       コスト9・青の「サンジ」(OP06-119) 等が登場できた (= タダで大型サンジを踏み倒す違反)。
# --------------------------------------------------------------------------- #
def test_eb02_059_sanji_summon_respects_cost_and_color():
    repo, overlay = _repo(), _overlay()
    play_eff = next(e for e in overlay.get("EB02-059").effects
                    if e.get("if", {}).get("self_life_le") == 1)
    prims = play_eff["do"]
    assert any("play_from_hand" in p for p in prims)

    def _summon_ids(hand_card_id):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        me.life = [repo.get(_FILLER)]           # self_life <= 1 (その後 の発動条件)
        me.hand = [repo.get(hand_card_id)]
        for p in prims:
            execute_effect(p, st, me, opp, None)
        return [ip.card.card_id for ip in me.characters]

    # 違反サンジは登場できない
    assert "OP06-119" not in _summon_ids("OP06-119"), (
        "コスト9・青の「サンジ」が登場した (公式違反: 黄・コスト5以下でない)"
    )
    assert "P-120" not in _summon_ids("P-120"), (
        "コスト6・黄の「サンジ」が登場した (公式違反: コスト5以下でない)"
    )
    # 黄・コスト5以下の正当な「サンジ」は登場できる (over-restriction でないことの対照)
    assert "EB02-054" in _summon_ids("EB02-054"), (
        "黄・コスト5の「サンジ」が登場できていない (制約の掛けすぎ)"
    )


# --------------------------------------------------------------------------- #
#  FAQ 全件保証 2026-08-05 バッチ (cardqa 10 件、 うち 9 conform / 1 escalated)。
#  各テストは 公式 Q&A 原文をコメントに引用し、 「違反していたら落ちる」 形で固定する。
#  外部オラクル = 公式 Q&A のみ (Python/Rust 差分検証では原理的に沈黙する領域)。
# --------------------------------------------------------------------------- #
def _board_fi(repo, ov, mine, theirs, l0="OP01-001", l1="OP01-001", turn=0):
    """簡易 board (両陣営キャラ + 空手札/ライフ)。 turn=1 で相手ターン。"""
    import random
    p0 = Player(name="P0", leader=InPlay.of(repo.get(l0), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(l1), sickness=False))
    p0.characters = [InPlay.of(repo.get(c), sickness=False) for c in mine]
    p1.characters = [InPlay.of(repo.get(c), sickness=False) for c in theirs]
    for p in (p0, p1):
        p.deck = [repo.get(_FILLER)] * 15
        p.life = [repo.get(_FILLER)] * 3
        p.hand = []
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = turn, 9
    return st, p0, p1


def test_st03_016_counter_return_can_target_own_character():
    """ST03-016 つっぱり圧力砲【カウンター】「コスト3以下のキャラ1枚までを、持ち主の手札に戻す」。

    公式 (cardqa_st_03, qid 2f462b39833b):
      Q: この【カウンター】効果で自分のキャラを手札に戻すことはできますか？
      A: はい、戻すことができます。
    → 「相手の」修飾が無い = 両陣営。 自陣限定なら 候補から自キャラが消える = 落ちる。
    """
    repo, ov = _repo(), _overlay()
    st, p0, p1 = _board_fi(repo, ov, [_FILLER], [])  # 自キャラのみ、 相手場は空
    st.human_player_idx = 0
    execute_effect({"return_to_hand": "one_character_either_cost_le_3"}, st, p0, p1, None)
    pc = st.pending_choice
    assert pc is not None, "相手場が空でも自キャラが候補になるはず (modal が立たない)"
    raw = pc.get("cards") or pc.get("candidates") or []
    iids = {c.get("iid") if isinstance(c, dict) else c for c in raw}
    assert p0.characters[0].instance_id in iids, (
        "自分のキャラが候補に入っていない (公式: 自キャラも手札に戻せる)"
    )


def test_st03_004_search_excludes_same_named_card():
    """ST03-004 ゲッコー・モリア【登場時】「トラッシュの『ゲッコー・モリア』以外のコスト4以下の
    特徴《王下七武海》か《スリラーバーク海賊団》キャラ1枚を手札に加える」。

    公式 (cardqa_st_03, qid 307eb466d570):
      Q: 「ST03-004 ゲッコー・モリア」以外のカード名が「ゲッコー・モリア」のカードを手札に
         加えられますか？
      A: いいえ、できません。カード名が「ゲッコー・モリア」であるすべてのカードはこの効果で
         手札に加えられません。
    → exclude_name が効いていないと モリア (OP09-085) が手札に来て 落ちる。
    """
    repo, ov = _repo(), _overlay()
    st, p0, p1 = _board_fi(repo, ov, [], [])
    # トラッシュ: モリア (OP09-085, スリラーバーク c4 = cost/feature は適合) + 正当な非モリア (EB03-045 ペローナ)
    p0.trash = [repo.get("OP09-085"), repo.get("EB03-045")]
    src = InPlay.of(repo.get("ST03-004"), sickness=False)
    p0.characters = [src]
    trigger_on_play(st, p0, p1, src, ov)  # AI 経路 = 唯一の正当候補を auto-pick
    hand_names = {c.name for c in p0.hand}
    trash_names = [c.name for c in p0.trash]
    assert "ゲッコー・モリア" not in hand_names, (
        "同名『ゲッコー・モリア』が手札に加わった (公式: 加えられない)"
    )
    assert "ゲッコー・モリア" in trash_names, "モリアはトラッシュに残るはず"
    assert "ペローナ" in hand_names, "正当な非モリア候補は手札に加わるはず (over-restriction でない)"


def test_op12_046_discards_available_hand_when_fewer_than_two():
    """OP12-046 ゼファー【登場時】「自分の手札2枚を捨てる」。

    公式 (cardqa_op_12, qid 318a76562346):
      Q: 自分の手札がこのカードを含めて2枚の状態でこれをプレイし登場させた場合、この【登場時】
         効果で、1枚だけの手札は捨てますか？
      A: はい、捨てます。
    → プレイ後の手札は1枚。 2枚捨てを要求されても在る1枚は捨てる (捨てられる分だけ捨てる)。
    """
    repo, ov = _repo(), _overlay()
    st, p0, p1 = _board_fi(repo, ov, [], [])
    p0.hand = [repo.get(_FILLER)]  # 登場後の残り手札 = 1 枚
    src = InPlay.of(repo.get("OP12-046"), sickness=False)
    p0.characters = [src]
    trigger_on_play(st, p0, p1, src, ov)
    assert len(p0.hand) == 0, "在る1枚を捨てていない (公式: 捨てられる分は捨てる)"
    assert len(p0.trash) == 1, "捨てた1枚がトラッシュに無い"


def test_op15_100_declining_optional_cost_skips_whole_effect():
    """OP15-100 カマキリ【登場時】「このキャラをトラッシュに置き、自分のライフの上から1枚を手札に
    加えることができる：相手のコスト6以下のキャラ1枚までを、KOする」。

    公式 (cardqa_op_15, qid 2f83f2adddb9):
      Q: この【登場時】効果で、このキャラをトラッシュに置かないことはできますか？
      A: はい、できます。この場合、自分のライフの上から1枚を手札に加えることはできず、相手の
         コスト6以下のキャラをKOすることもできません。
    → 任意コストを拒否したら ライフ移動も KO も起きず、 自身も場に残る。
    """
    repo, ov = _repo(), _overlay()
    st, p0, p1 = _board_fi(repo, ov, [], ["OP01-016"])  # 相手にコスト6以下キャラ
    life_before, opp_before = len(p0.life), len(p1.characters)
    src = InPlay.of(repo.get("OP15-100"), sickness=False)
    p0.characters = [src]
    st.human_player_idx = 0
    trigger_on_play(st, p0, p1, src, ov)
    pc = st.pending_choice
    assert pc is not None and pc.get("kind") == "optional_cost_confirm", (
        "任意コストの可否が人間に問われていない"
    )
    resolve_pending_choice(st, [0])  # 0 = 拒否 (既存 test_optional_cost_is_declinable_by_human 準拠)
    assert len(p0.life) == life_before, "拒否したのにライフが手札へ移った"
    assert len(p1.characters) == opp_before, "拒否したのに相手キャラが KO された"
    assert any(c.instance_id == src.instance_id for c in p0.characters), (
        "拒否したのに自身がトラッシュへ置かれた (コスト未払いなら場に残る)"
    )


def test_st20_005_opp_choice_discards_the_choosing_players_own_hand():
    """ST20-005 リンリン【登場時】「自分の手札1枚を捨てることができる：相手は以下から1つを選ぶ。
    ・相手は自身の手札2枚を捨てる。・相手のライフの上から1枚をトラッシュに置く」。

    公式 (cardqa qid 2f7c55e92f71):
      Q: 自分がこの【登場時】効果を発動し、対戦相手が「相手は自身の手札2枚を捨てる。」を選んだ
         場合、どちらのプレイヤーが手札を2枚捨てますか？
      A: この【登場時】効果を発動していない側のプレイヤーが、そのプレイヤーの手札から2枚を
         トラッシュに置きます。
    → 選んだ側 (= 発動者の相手) が 自分の手札を 2 枚捨てる。 発動者は捨てない。
    """
    repo, ov = _repo(), _overlay()
    st, p0, p1 = _board_fi(repo, ov, [], [])
    p0.hand = [repo.get(_FILLER)]        # コスト discard_hand:1 用
    p1.hand = [repo.get(_FILLER)] * 4    # 相手 (選ぶ側) の手札
    src = InPlay.of(repo.get("ST20-005"), sickness=False)
    p0.characters = [src]
    trigger_on_play(st, p0, p1, src, ov)
    guard = 0
    while st.pending_choice is not None and guard < 8:
        resolve_pending_choice(st, [0]); guard += 1
    assert len(p1.hand) == 2, (
        f"選んだ側の手札が 4→{len(p1.hand)} = 2枚捨てていない (捨てるのは発動者の相手)"
    )
    assert len(p1.trash) == 2, "相手のトラッシュに捨てた2枚が無い"
    # 発動者 (p0) は コスト1枚のみ、 効果本体では捨てない
    assert len(p0.trash) == 1, "発動者が本体効果で手札を捨てている (捨てるのは相手のみ)"


def test_eb03_055_ko_damage_has_no_block_or_counter_window():
    """EB03-055 ニコ・ロビン【相手のターン中】【KO時】「相手に1ダメージを与えてもよい」。

    公式 (cardqa_eb_03, qid 30ac7cf8798c):
      Q: 相手のこのカードの【KO時】効果に対して、自分は【ブロッカー】を発動したり、手札から
         【カウンター】を発動するなどでダメージを防ぐことはできますか？
      A: いいえ、できません。
    → 【KO時】ダメージはバトルではない = 防御ウィンドウ (pending_choice) が一切立たず、
      相手ライフが直接1減る。 防御選択が立ったら 落ちる。
    """
    repo, ov = _repo(), _overlay()
    from engine.effects import trigger_on_ko
    st, p0, p1 = _board_fi(repo, ov, [], [], turn=1)  # 相手 (p1) のターン = p0 視点で【相手のターン中】
    opp_life_before = len(p1.life)
    victim = InPlay.of(repo.get("EB03-055"), sickness=False)
    trigger_on_ko(st, p0, p1, victim.card, ov, by_opp_effect=True,
                  victim_attached_don=0, victim_effect_negated=False)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    assert len(p1.life) == opp_life_before - 1, "KO時ダメージで相手ライフが1減っていない"
    assert st.pending_choice is None, (
        "KO時ダメージにブロック/カウンターの防御ウィンドウが立った (公式: 防げない)"
    )


def test_op01_051_two_copies_both_become_attack_taunts():
    """OP01-051 ユースタス・キッド【ドン‼×1】【相手のターン中】「このキャラがレストの場合、相手は
    キャラの『ユースタス・キッド』以外にアタックできない」。

    公式 (cardqa_op_01, qid 30e46a63da7a):
      Q: この【相手のターン中】効果を発動している「OP01-051 ユースタス・キッド」が相手の場に
         2枚ある場合はどうなりますか？
      A: 相手のキャラのうち、カード名が「ユースタス・キッド」であるキャラのいずれかにアタック
         ができます。
    → 2枚とも条件成立 (レスト + ドン付与) なら 両方が taunt = どちらの キッド にもアタック可、
      リーダーには不可。 片方しか taunt にならなければ 落ちる。
    """
    repo, ov = _repo(), _overlay()
    from engine.game import legal_actions
    st, p0, p1 = _board_fi(repo, ov, [_FILLER], [])  # p0 の攻撃側キャラ、 p0 のターン
    p0.characters[0].rested = False  # アクティブ攻撃可
    kidd1 = InPlay.of(repo.get("OP01-051"), sickness=False)
    kidd1.rested = True; kidd1.attached_dons = 1
    kidd2 = InPlay.of(repo.get("OP01-051"), sickness=False)
    kidd2.rested = True; kidd2.attached_dons = 1
    p1.characters = [kidd1, kidd2]
    evaluate_static_effects(st, ov)
    assert kidd1.attack_taunt and kidd2.attack_taunt, "2枚とも taunt になっていない"
    la = legal_actions(st)
    assert not any(isinstance(a, AttackLeader) for a in la), (
        "taunt がいるのにリーダーへアタックできる"
    )
    char_iids = {a.target_iid for a in la if isinstance(a, AttackCharacter)}
    assert char_iids == {kidd1.instance_id, kidd2.instance_id}, (
        "どちらの キッド にもアタックできる状態になっていない"
    )


def test_op15_098_simultaneous_leave_saves_both_sky_characters():
    """OP15-098 モンキー・Ｄ・ルフィ (リーダー):「自分の元々のパワー6000以上の特徴《空島》を持つ
    キャラが相手によって場を離れる場合、代わりに自分のライフの上から1枚を手札に加えることができる」。

    公式 (cardqa_op_15, qid 2f50adf29553):
      Q: 自分の元々のパワー6000以上の特徴《空島》を持つキャラが2枚同時に相手の効果で場を離れる
         場合、代わりに自分のライフを手札に加えることはできますか？
      A: はい、できます。（…）2枚をどちらも場に残すことができます。
    → 置換効果は 離脱キャラごとに独立適用 (公式一般則)。 2枚同時離脱でも 両方が場に残る。
      どちらかでも KO されたら 落ちる。
    """
    repo, ov = _repo(), _overlay()
    st, p0, p1 = _board_fi(
        repo, ov,
        ["OP15-107", "OP15-099"],  # 空島 pow6000 / pow7000
        [], l0="OP15-098", turn=1,  # リーダー = 置換元、 相手 (p1) のターン
    )
    life_before = len(p0.life)
    # p1 (相手) が p0 のキャラ全てを KO (= 相手の効果で 2 枚同時離脱)。
    execute_effect({"ko_multi": ["all_opponent_characters"]}, st, p1, p0, None)
    guard = 0
    while st.pending_choice is not None and guard < 10:
        resolve_pending_choice(st, [0]); guard += 1
    surviving = {c.card.card_id for c in p0.characters}
    assert surviving == {"OP15-107", "OP15-099"}, (
        f"空島キャラが両方残っていない (残: {surviving}) = 置換効果が両方に適用されていない"
    )
    assert len(p0.life) < life_before, "置換 (ライフ→手札) が発火していない (無償で残っている)"


# --------------------------------------------------------------------------- #
#  公式 Q&A conformance バッチ (2026-08-05、 faq_qa_manifest)
#  ここから下は 「違反ではなかった (conform)」 を回帰で固定するテスト群。
#  overlay/engine の構造が偶然そう振る舞うだけの箇所を、 公式裁定として明示ロックする。
# --------------------------------------------------------------------------- #
def test_op16_035_second_clause_runs_even_when_no_opp_to_rest():
    """OP16-035 ゾロ: 相手のカードをレストにしなくても 後段 (手札1捨て→リーダーにレストドン3付与) は行える。

    公式 (cardqa_op_16, qid 32a980922374):
      Q: この効果で相手のカードをレストにしなかった場合に、自分の手札1枚を捨て、
         自分のリーダーにレストのドン!!3枚までを付与することはできますか？
      A: はい、できます。
    「相手のカード1枚まで」= レスト0枚も可、 「その後」の任意コストは独立。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = []                 # レストする相手カードが居ない
    me.hand = [repo.get(_FILLER)] * 2
    me.don_rested = 5                    # 付与元のレストドン
    src = InPlay.of(repo.get("OP16-035"), sickness=True)
    me.characters = [src]
    don_before, hand_before = me.leader.attached_dons, len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert me.leader.attached_dons == don_before + 3, \
        "レスト0でも 後段の レストドン3付与 が行われるはず"
    assert len(me.hand) == hand_before - 1, "後段の 手札1捨て が行われるはず"


def test_op10_030_self_lock_does_not_block_leader_untap():
    """OP10-030 スモーカー(キャラ)の自己ロックは リーダーのドンアクティブ化を妨げない。

    公式 (cardqa_op_10, qid 32c4c25da85c):
      Q: この【起動メイン】効果を発動したあと、そのターンにリーダー「OP10-001 スモーカー」の
         効果でドン!!2枚をアクティブにすることはできますか？
      A: はい、できます。
    OP10-030 は「このターン中 **キャラの効果で** ドンをアクティブにできない」= リーダー効果は対象外。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP10-001")
    me, opp = st.players[0], st.players[1]
    me.don_rested, me.don_active = 4, 0
    big = InPlay.of(repo.get(_FILLER), sickness=False)
    big.base_power_override = 7000      # リーダーの起動メイン条件 (7000+ キャラ)
    smoker = InPlay.of(repo.get("OP10-030"), sickness=False)
    me.characters = [big, smoker]
    op = [(ip, e) for (ip, e) in list_activate_main_effects(st, me, overlay) if ip is smoker]
    assert op, "OP10-030 の起動メインが列挙されていない"
    fire_activate_main(st, me, opp, op[0][0], op[0][1])
    assert me.block_chara_effect_untap_don_until_turn_end is True, "自己ロックが立っていない"
    me.don_rested += 3
    lo = [(ip, e) for (ip, e) in list_activate_main_effects(st, me, overlay) if ip is me.leader]
    assert lo, "リーダーの起動メイン (ドンアクティブ化) が キャラ自己ロックで消えている = 違反"
    before = me.don_active
    fire_activate_main(st, me, opp, lo[0][0], lo[0][1])
    assert me.don_active == before + 2, "リーダーのドンアクティブ化が阻害されている = 違反"


def test_op02_102_power_pump_is_boolean_not_per_count():
    """OP02-102 スモーカー: コスト0のキャラが2枚でも パワーは+2000 (+4000 にならない)。

    公式 (cardqa_op_02, qid 320695305fc9):
      Q: コスト0のキャラが2枚ある場合、このキャラのパワーは+4000されますか？
      A: いいえ、されません。
    「コスト0のキャラがいる場合」= 存在の真偽 (boolean)、 枚数倍ではない。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    c0a = InPlay.of(repo.get(_FILLER), sickness=False); c0a.base_cost_override = 0
    c0b = InPlay.of(repo.get(_FILLER), sickness=False); c0b.base_cost_override = 0
    src = InPlay.of(repo.get("OP02-102"), sickness=False)
    me.characters = [c0a, c0b, src]
    before = src.battle_buff
    trigger_on_attack(st, me, opp, src, overlay)
    assert src.battle_buff == before + 2000, \
        f"コスト0キャラ2枚で +{src.battle_buff-before} = 枚数倍になっている (公式は +2000 固定)"


def test_st13_002_end_of_turn_trashes_all_face_up_life_any_source():
    """ST13-002 エース: 【起動メイン】以外で表向きになったライフも【ターン終了時】でトラッシュ。

    公式 (cardqa_st_13, qid 32b0ead1a01e):
      Q: この【起動メイン】以外の方法で自分のライフに置かれた表向きのカードは、
         この【自分のターン終了時】効果でトラッシュに置かれますか？
      A: はい、トラッシュに置かれます。
    engine は face_up_life_count の count-only モデル = 由来を問わず表向き札すべてが対象。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="ST13-002")
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    # 別経路 (flip_life_face_up_effect) で 2 枚を表向きに
    execute_effect({"flip_life_face_up_effect": 2}, st, me, opp, None)
    assert me.face_up_life_count == 2
    trash_before = len(me.trash)
    execute_effect({"trash_all_face_up_life": True}, st, me, opp, None)
    assert len(me.trash) == trash_before + 2 and me.face_up_life_count == 0, \
        "別経路で表向きにしたライフが【ターン終了時】でトラッシュされない = 違反"


def test_op01_014_blocker_usable_with_empty_hand():
    """OP01-014 ジンベエ: 手札に登場可能キャラが無くても【ブロッカー】は発動できる。

    公式 (cardqa_op_01, qid 31c2d92dfcb1):
      Q: この【ブロック時】効果で登場できるキャラカードが手札にない時、
         このキャラの【ブロッカー】効果を発動できますか？
      A: はい、発動できます。
    【ブロッカー】キーワードは【ブロック時】の実行可否と独立。 空手札の on_block は no-op。
    """
    from engine.effects import trigger_on_block
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    blk = InPlay.of(repo.get("OP01-014"), sickness=False)
    blk.attached_dons = 1                # 【ドン!!×1】条件
    opp.characters = [blk]               # ブロッカーは 防御側 (opp) の場
    opp.hand = []                        # 登場できるキャラが手札に無い
    assert blk.is_blocker_now is True and blk.rested is False, \
        "空手札だと【ブロッカー】自体が使えなくなっている = 違反"
    hand_before = len(opp.hand)
    trigger_on_block(st, opp, me, blk, overlay)   # 例外を出さず no-op であること
    assert len(opp.hand) == hand_before, "空手札の【ブロック時】が不正なプレイをしている"


def test_give_attack_active_chara_does_not_bypass_summoning_sickness():
    """「アクティブのキャラにもアタックできる」効果は 召喚酔いを解除しない (OP11-014/082)。

    公式 (cardqa_op_11, qid 3200dcd72841):
      Q: この【起動メイン】効果で、そのターンに登場した自分のキャラを選んだ場合、
         そのキャラはアクティブのキャラにアタックできますか？
      A: いいえ、できません。（登場ターンは そもそもアタック宣言ができない）
    give_attack_active_chara は攻撃対象を広げるだけ。 召喚酔いチェックが先に効く。
    """
    from engine.game import legal_actions, AttackCharacter
    repo, overlay = _repo(), _overlay()
    # 召喚酔いキャラに buff を付けても アタックは一切出ない
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    sick = InPlay.of(repo.get(_FILLER), sickness=True)
    sick.granted_keywords.add("アクティブアタック可")
    me.characters = [sick]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # アクティブな相手キャラ
    acts = legal_actions(st)
    assert not [a for a in acts if getattr(a, "attacker_iid", None) == sick.instance_id], \
        "召喚酔いキャラが アクティブアタック可 buff でアタックできてしまう = 違反"
    # 対照: 酔っていなければ 同 buff で アクティブな相手キャラにアタック可
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    ok = InPlay.of(repo.get(_FILLER), sickness=False)
    ok.granted_keywords.add("アクティブアタック可")
    me2.characters = [ok]
    opp2.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    acts2 = legal_actions(st2)
    char_atk = [a for a in acts2 if getattr(a, "attacker_iid", None) == ok.instance_id
                and isinstance(a, AttackCharacter)]
    assert char_atk, "酔っていなければ アクティブな相手キャラにアタックできるはず (対照が壊れている)"


def test_op06_018_two_pump_clauses_pick_targets_independently():
    """OP06-018: +3000 の対象と +1000 の対象は 別々に選べる (異なるキャラ可)。

    公式 (cardqa_op_06, qid 324d7c6a1b4e):
      Q: この【メイン】効果でパワーを+3000するキャラとパワーを+1000するキャラは、
         異なるものを選べますか？
      A: はい、できます。
    2 つの main 節は それぞれ独立に target_pick を出す (人間は別対象を選べる)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False),
                     InPlay.of(repo.get(_FILLER), sickness=False)]
    big = InPlay.of(repo.get(_FILLER), sickness=False); big.base_power_override = 8000
    opp.characters = [big]              # 2 節目の条件 (相手7000+キャラ) を満たす
    main_effs = [e for e in overlay.get("OP06-018").effects if e.get("when") == "main"]
    assert len(main_effs) == 2, "OP06-018 の main 節が 2 つでない"
    for prim in main_effs[0]["do"]:
        execute_effect(prim, st, me, opp, None)
    assert st.pending_choice is not None and st.pending_choice.get("kind") == "target_pick", \
        "1 節目が独立の target_pick を出していない = 別対象を選べない可能性"


def test_st02_007_search_no_match_puts_all_viewed_to_deck_bottom():
    """ST02-007 ボニー: 《超新星》が無ければ 見た札すべてを好きな順でデッキ下に置く。

    公式 (cardqa_st_02, qid 32aa45212c09):
      Q: 《超新星》を持つカードがなかった場合はどうなりますか？
      A: デッキの上から見たカード全てを好きな順番に並び替え、デッキの下に置きます。
    search_top_n(rest_remain=bottom): マッチ0なら 手札増えず デッキ枚数不変 (全て下へ)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10   # _FILLER に 超新星 特徴なし
    deck_before, hand_before = len(me.deck), len(me.hand)
    execute_effect({"search_top_n": {"depth": 5, "filter": {"category": "CHARACTER",
                    "feature": "超新星"}, "limit": 1, "destination": "hand",
                    "rest_remain": "bottom", "public": True}}, st, me, opp, None)
    assert len(me.deck) == deck_before, "超新星が無いのにデッキ枚数が減っている"
    assert len(me.hand) == hand_before, "超新星が無いのに手札に加わっている = 違反"


# =========================================================================== #
#  公式 Q&A conformance バッチ 2026-08-05 #2 (faq_qa_manifest, cron)
#  8 件 conform を実測で固定 (engine/overlay 無変更、 挙動の回帰テストのみ)。
#  一次情報は各 test の docstring に qid + Q/A 原文を引用。
# =========================================================================== #
def test_op14_115_takes_1_damage_even_when_no_card_added_to_life():
    """OP14-115 リンドウ: ライフに加えなくても 1 ダメージは受ける。

    公式 (cardqa_op_14, qid 32c70b593ae1):
      Q: この【相手のターン中】効果で自分のデッキの上のカードをライフに加えなかった
         場合でも、自分は1ダメージを受けますか？
      A: はい、受けます。
    on_ko の do は [put_top_to_life:1, take-1-damage] の 2 独立節。 デッキ0で
    put_top_to_life が 0 枚でも、 後段のダメージは無条件で 1 枚ライフを減らす。
    ⚠ ダメージの行き先 (手札/トラッシュ) は本 Q の対象外なので assert しない
      (ライフ枚数が 1 減ることだけを固定する)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.turn_player_idx = 1                 # 相手のターン (p0 から見て opp_turn=True)
    me = st.players[0]
    me.deck = []                           # デッキ0 → put_top_to_life は 0 枚
    life_before = len(me.life)
    lindou = InPlay.of(repo.get("OP14-115"))
    execute_effect({"put_top_to_life": 1}, st, me, st.players[1], self_inplay=lindou)
    assert len(me.life) == life_before, "前提が崩れている: デッキ0なのにライフが増えた"
    execute_effect({"mill_self_life_to_trash": 1}, st, me, st.players[1], self_inplay=lindou)
    assert len(me.life) == life_before - 1, (
        "ライフに加えなかった場合でも 1 ダメージ (ライフ-1) を受けるべき"
    )


def test_op01_062_crocodile_no_draw_when_hand_5_at_resolution():
    """OP01-062 クロコダイル: イベント解決後に手札5枚なら【ドン!!×1】は引けない。

    公式 (cardqa_op_01, qid 32c854fbd2f9):
      Q: 手札5枚→イベント発動で4枚→その効果で再び5枚。この【ドン!!×1】効果で引けますか？
      A: いいえ、イベント発動後に手札が5枚以上のため引けません。
    on_self_event_played は game.py/effects.py の event 解決 (hand 再充填) の **後** に
    発火し、 `self_hand_count_le:4` を解決時点で評価する。 hand=5 なら不発、 hand=4 なら発火。
    """
    from engine.effects import trigger_self_event_played
    repo, overlay = _repo(), _overlay()
    # hand=5 → 引けない
    st = _state(repo, overlay, leader0="OP01-062")
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.hand = [repo.get(_FILLER)] * 5
    deck_before = len(me.deck)
    trigger_self_event_played(st, me, opp, overlay)
    assert len(me.deck) == deck_before, "手札5枚なのに引いている = 違反 (条件は解決時に評価)"
    # hand=4 → 引ける (前提の健全性チェック = 条件が実際に効いている)
    st2 = _state(repo, overlay, leader0="OP01-062")
    me2, opp2 = st2.players[0], st2.players[1]
    me2.leader.attached_dons = 1
    me2.hand = [repo.get(_FILLER)] * 4
    deck_before2 = len(me2.deck)
    trigger_self_event_played(st2, me2, opp2, overlay)
    assert len(me2.deck) == deck_before2 - 1, "手札4枚なら引けるはず (条件が死んでいないか確認)"


def test_op13_120_sabo_cost_plus_is_uncapped_above_10():
    """OP13-120 サボ: コスト+2 は 10 で頭打ちにならない (9→11)。

    公式 (cardqa_op_13, qid 32d15a15dc83):
      Q: この【起動メイン】効果で、9コスト以上のキャラを選んだ場合、そのキャラのコストは
         10より大きい値になりますか？
      A: はい、なります。
    cost_minus(amount=-2) は base_cost を +2 する。 コスト上限は無いので 9→11 (>10)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get("OP06-118"), sickness=False)   # コスト9キャラ
    me.characters = [target]
    assert target.base_cost == 9, "前提が崩れている: 対象がコスト9でない"
    execute_effect({"cost_minus": {"target": "one_self_character_any", "amount": -2,
                    "duration": "next_opp_turn_end"}}, st, me, opp, self_inplay=me.leader)
    assert target.base_cost == 11, "9+2=11 になるべき (10で頭打ちしない)"
    assert target.base_cost > 10, "コストは10より大きくなる (公式回答=はい)"


def test_op02_051_ivankov_can_play_character_when_hand_ge_3():
    """OP02-051 イワンコフ: 手札3枚以上でも【登場時】でキャラを登場できる。

    公式 (cardqa_op_02, qid 32d8bb5cc44e):
      Q: 手札が3枚以上の場合、この【登場時】効果でキャラカードを登場できますか？
      A: はい、登場できます。
    do は [draw_to_hand_size:3, play_from_hand]。 hand≥3 で引きは0枚でも、 後段の
    登場は独立に成立する (= 引き0が登場を妨げない)。 human で 登場を選べることを固定。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-045"), repo.get(_FILLER), repo.get(_FILLER)]  # 青インペルダウンcost4 + 2枚 = 3枚
    deck_before = len(me.deck)
    iva = InPlay.of(repo.get("OP02-051"), sickness=False)
    me.characters = [iva]
    trigger_on_play(st, me, opp, iva, overlay)
    guard = 0
    while st.pending_choice is not None and guard < 6:
        pc = st.pending_choice
        cands = pc.get("candidates", [])
        pick = [0]
        for i, c in enumerate(cands):
            if c.get("card_id") == "OP16-045":
                pick = [i]
        resolve_pending_choice(st, pick)
        guard += 1
    assert len(me.deck) == deck_before, "手札3枚なので引きは0枚のはず (前提)"
    assert any(c.card.card_id == "OP16-045" for c in me.characters), (
        "手札3枚以上でも登場時のキャラ登場が可能であるべき"
    )


def test_op08_045_thatch_replacement_suppresses_ko_triggers():
    """OP08-045 サッチ: KO 置換 (トラッシュ+1ドロー) では KO したことにならない。

    公式 (cardqa_op_08, qid 33204b854702):
      Q: このカードがKOされ、代わりにトラッシュに置きカード1枚を引いたとき、他のカードの
         持つ「キャラがKOされた時」の効果は発動しますか？
      A: いいえ、発動しません。
    try_replace_ko が成立すると caller は continue し、 trigger_on_ko / on_*_chara_ko を
    一切 dispatch しない。 chara_ko_taken_this_turn が 0 のままであることで KO 未発生を固定。
    """
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    thatch = InPlay.of(repo.get("OP08-045"), sickness=False)
    me.characters = [thatch]
    me.hand = []
    ko_before = int(getattr(me, "chara_ko_taken_this_turn", 0) or 0)
    replaced = try_replace_ko(st, me, opp, thatch, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True, "置換 (トラッシュ+ドロー) が成立していない"
    assert repo.get("OP08-045") in me.trash, "置換でトラッシュに置かれていない"
    assert len(me.hand) == 1, "置換で1枚引いていない"
    assert int(getattr(me, "chara_ko_taken_this_turn", 0) or 0) == ko_before, (
        "置換なのに KO カウンタが増えた = 『キャラがKOされた時』が発火しうる状態 (違反)"
    )


def test_op08_043_newgate_condition_checked_at_play_not_continuously():
    """OP08-043 白ひげ: ライフ3枚以上で登場すると 手札2捨て制約は付かない (後でライフ2以下でも)。

    公式 (cardqa_op_08, qid 338ca846c203):
      Q: ライフ3枚以上でこの【登場時】を発動後、次の相手ターン中にライフが2枚以下になった。
         相手キャラは手札2枚を捨てなければアタックできない状態になりますか？
      A: いいえ、手札2枚を捨てずにアタックできます。
    if(self_life_le:2) は登場時に一度だけ評価。 ライフ3枚なら不成立で制約を付与せず、
    後からライフが減っても遡って付与されない (登場時効果は継続再評価しない)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP08-002")   # マルコ = 白ひげ海賊団 リーダー
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3                 # ライフ3枚 (>=3)
    opp_ch = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [opp_ch]
    ng = InPlay.of(repo.get("OP08-043"), sickness=False)
    me.characters = [ng]
    trigger_on_play(st, me, opp, ng, overlay)
    assert opp_ch.attack_cost_discard_hand_n == 0, "ライフ3枚なのに制約が付いた = if 評価が誤り"
    me.life = [repo.get(_FILLER)] * 2                 # 後からライフ2枚に
    assert opp_ch.attack_cost_discard_hand_n == 0, (
        "登場時にライフ3枚だったので、 後からライフ2以下でも制約は付かないべき"
    )


def test_eb01_061_mr2_copy_power_then_don_bonus_applies_on_top():
    """EB01-061 Mr.2: 元々のパワーを5000にコピー + ドン付与1枚 = 6000。

    公式 (cardqa_eb_01, qid 33c1d8c18e2e):
      Q: ドン!!1枚付与のこのキャラでアタックし、この【アタック時】効果で相手のパワー5000の
         キャラを選んだ時、このキャラのパワーは6000になりますか？
      A: はい、6000になります。
    set_base_power_copy は base を 5000 に上書き。 ドン+1000 は base の上に加算される。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    mr2 = InPlay.of(repo.get("EB01-061"), sickness=False)
    mr2.attached_dons = 1
    me.characters = [mr2]
    opp_ch = InPlay.of(repo.get("OP01-078"), sickness=False)   # 印刷パワー5000
    opp.characters = [opp_ch]
    assert opp_ch.power == 5000, "前提が崩れている: 相手キャラのパワーが5000でない"
    trigger_on_attack(st, me, opp, mr2, overlay)
    if st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    assert mr2.base_power == 5000, "元々のパワーが5000にコピーされていない"
    assert mr2.power == 6000, "コピー5000 + ドン+1000 = 6000 になるべき"


def test_op03_001_ace_when_attacked_fires_before_counter_step_structurally():
    """OP03-001 エース: 「アタックされた時」はカウンターステップより前 (後から発動不可)。

    公式 (cardqa_op_03, qid 33e605eb9dc1):
      Q: カウンターステップにカウンターを発動した後、リーダーの「アタックされた時」効果で
         パワーを上げられますか？
      A: いいえ、できません。
    構造で担保 (既存 30be7538d5d5 と同型): apply_action の AttackLeader 経路で
    trigger_on_opp_attack_on_leader (アタックされた時) が _fire_counter_events より前に
    発火・解決する。 カウンター発動後にその窓は既に閉じている。
    """
    import inspect
    from engine import game
    # AttackLeader 処理の実体は _apply_action_impl (apply_action のラップ先)。
    src = inspect.getsource(game._apply_action_impl)
    # AttackLeader 経路で opp_attack トリガーが counter events より前に呼ばれること
    i_trig = src.find("trigger_on_opp_attack_on_leader")
    i_counter = src.find("_fire_counter_events")
    assert i_trig != -1 and i_counter != -1, "前提が崩れている: 呼び出しが見つからない"
    assert i_trig < i_counter, (
        "『アタックされた時』トリガーがカウンター処理より後に配置されている = "
        "カウンター後にリーダー効果を発動できてしまう (違反)"
    )


# --------------------------------------------------------------------------- #
#  Z. 公式 Q&A conformance バッチ (2026-08-05, cron optcg-faq-conformance)
#     10 件を engine 実測で検証。 9 件 conform を以下で固定、 1 件 (OP15-090
#     同時離脱の置換) は アーキ変更が要るため escalated (docs/official_rulings.md)。
# --------------------------------------------------------------------------- #
def test_eb01_008_replace_ko_unpayable_when_no_event_or_stage_in_hand():
    """EB01-008 リトルオーズJr.: 手札にイベント/ステージが無ければ KO を代替できない。

    公式 (cardqa_eb_01, qid 33ece02d4726):
      Q: 手札にイベントもステージカードも無い時、この【ターン1回】効果で このキャラが
         効果によって KO されないことはできますか？
      A: いいえ、できません。
    置換コスト (イベント/ステージ 1 捨て) が払えない → 置換不成立 = 通常どおり KO。
    """
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()

    # (a) 手札に CHARACTER のみ (= コスト不可) → replaced False
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("EB01-008"), sickness=False)
    me.characters = [c]
    me.hand = [repo.get(_FILLER)]                       # CHARACTER = イベント/ステージでない
    assert try_replace_ko(st, me, opp, c, overlay, by_opp_effect=True, leave_kind="ko") is False, \
        "イベント/ステージが無いのに KO を代替できている (タダで KO 回避)"

    # (b) 手札に EVENT があれば代替成立 (対照)
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    c2 = InPlay.of(repo.get("EB01-008"), sickness=False)
    me2.characters = [c2]
    me2.hand = [repo.get("EB01-009")]                   # EVENT
    hb = len(me2.hand)
    assert try_replace_ko(st2, me2, opp2, c2, overlay, by_opp_effect=True, leave_kind="ko") is True, \
        "イベントを捨てられるのに KO 代替が成立していない"
    assert len(me2.hand) == hb - 1, "代替コストのイベント 1 捨てが行われていない"


def test_op04_111_activate_main_can_trash_the_other_copy():
    """OP04-111 ヘラ: 同名 2 枚のうち一方の【起動メイン】がもう一方を コストで トラッシュにできる。

    公式 (cardqa_op_04, qid 346402667b7a):
      Q: 自分の場にこのカードが 2 枚あるとき、一方の【起動メイン】効果で もう一方を
         トラッシュに置けますか？  A: はい、できます。
    コストは 「このキャラ以外の《ホーミーズ》1 枚をトラッシュ」。 もう 1 枚の ヘラ は
    《ホーミーズ》かつ自身でない → 正当な対象。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    h1 = InPlay.of(repo.get("OP04-111"), sickness=False)
    h2 = InPlay.of(repo.get("OP04-111"), sickness=False)
    me.characters = [h1, h2]
    trash_before = len(me.trash)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP04-111"]
    assert len(opts) == 2, "2 枚それぞれの起動メインが legal でない"
    fire_activate_main(st, me, opp, *opts[0])
    while st.pending_choice:
        resolve_pending_choice(st, [0])

    assert len(me.characters) == 1, "もう 1 枚をコストでトラッシュできていない"
    assert len(me.trash) == trash_before + 1, "トラッシュに 1 枚移っていない"


def test_op01_030_search_filter_has_no_color_restriction():
    """OP01-030: 【メイン】の検索は 特徴《麦わらの一味》のみ、 色で絞らない。

    公式 (cardqa_op_01, qid 34671783ab18):
      Q: この【メイン】効果で、赤以外の 特徴《麦わらの一味》を持つ キャラカードを
         手札に加えられますか？  A: はい、加えられます。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP01-030"), sickness=True)
    me.characters = [src]
    # デッキトップに 緑 (= 赤以外) の《麦わらの一味》キャラ (OP06-118 ゾロ)
    me.deck = [repo.get("OP06-118")] + [repo.get(_FILLER)] * 10
    assert "赤" not in (repo.get("OP06-118").color or ""), "前提が崩れている: OP06-118 が赤"
    hb = len(me.hand)

    eff = next(e for e in overlay.get("OP01-030").effects if e.get("when") == "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)
    while st.pending_choice:
        resolve_pending_choice(st, [0])

    assert any(c.card_id == "OP06-118" for c in me.hand), \
        "赤以外の《麦わらの一味》が検索で手札に加わっていない (色で誤って絞っている)"
    assert len(me.hand) == hb + 1


def test_op07_107_trigger_draws_and_goes_to_trash_when_life_2():
    """OP07-107 フランキー【トリガー】: ライフ 2 枚以上でも 1 ドローする (その後 登場は不成立)。

    公式 (cardqa_op_07, qid 346e1e1ac578):
      Q: 自分のライフが 2 枚以上の場合、この【トリガー】効果で カードを引くことは
         できますか？
      A: はい、この場合 カード 1 枚を引き、このカードをトラッシュに置きます。
    do 順は draw → (自ライフ 1 以下なら) play_self。 ライフ 2 では条件不成立 = 登場せず。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2                   # ライフ 2
    me.deck = [repo.get(_FILLER)] * 10
    hb, cb = len(me.hand), len(me.characters)

    eff = next(e for e in overlay.get("OP07-107").effects if e.get("when") == "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice:
            resolve_pending_choice(st, [0])

    assert len(me.hand) == hb + 1, "ライフ 2 でも 1 ドローするはず"
    assert len(me.characters) == cb, "ライフ 2 で条件不成立なのに このキャラが登場している"
    # 条件節の対照
    assert eval_condition({"self_life_le": 1}, st, me, opp) is False, "ライフ 2 で self_life_le(1) が真"


def test_op16_026_second_play_runs_even_when_search_adds_nothing():
    """OP16-026 イワンコフ【登場時】: 検索で 0 枚しか加えなくても 後段の 手札からの登場は行える。

    公式 (cardqa_op_16, qid 351b9ec7f7a5):
      Q: この【登場時】効果で、特徴《インペルダウン》1 枚までを 手札に加えなかった場合、
         自分の手札から コスト 2 以下のキャラ 1 枚までを登場させることはできますか？
      A: はい、できます。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP16-026"), sickness=True)
    me.characters = [src]
    me.deck = [repo.get(_FILLER)] * 10                  # トップに《インペルダウン》なし
    me.hand = [repo.get("OP01-016")]                    # cost1 キャラ = 後段の登場対象
    cb = len(me.characters)

    eff = next(e for e in overlay.get("OP16-026").effects if e.get("when") == "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)
        guard = 0
        while st.pending_choice and guard < 6:
            kind = st.pending_choice.get("kind")
            if "search" in str(kind):
                resolve_pending_choice(st, [])          # 手札に加えない
            else:
                resolve_pending_choice(st, [0])         # 手札から登場させる
            guard += 1

    assert len(me.characters) == cb + 1, \
        "検索で 0 枚でも 後段の 「手札から登場」 が実行されるはず"


def test_op14_041_leader_draws_per_simultaneous_chara_on_opp_turn():
    """OP14-041 ハンコック: 相手ターン中に自キャラが複数 同時登場したら 枚数分ドローする。

    公式 (cardqa_op_14, qid 35efcda7c42d):
      Q: 相手のターン中、キャラを 2 枚以上登場させる効果で 自分のキャラが 2 枚以上同時に
         登場した場合、このリーダーの効果で 何枚引きますか？
      A: 同時登場したキャラ 1 枚ごとに発動 (3 枚同時なら 合計 3 ドロー)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP14-041")
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1                              # 相手ターン
    me.deck = [repo.get(_FILLER)] * 10
    hb = len(me.hand)
    for _ in range(2):                                  # 2 枚 同時登場を逐次で再現
        c = InPlay.of(repo.get(_FILLER), sickness=True)
        me.characters.append(c)
        trigger_on_play(st, me, opp, c, overlay)
        while st.pending_choice:
            resolve_pending_choice(st, [0])
    assert len(me.hand) == hb + 2, "2 枚同時登場で 2 ドローになっていない"

    # 対照: 自ターンでは発動しない (【相手のターン中】)
    st2 = _state(repo, overlay, leader0="OP14-041")
    me2, opp2 = st2.players[0], st2.players[1]
    st2.turn_player_idx = 0
    me2.deck = [repo.get(_FILLER)] * 10
    hb2 = len(me2.hand)
    c2 = InPlay.of(repo.get(_FILLER), sickness=True)
    me2.characters.append(c2)
    trigger_on_play(st2, me2, opp2, c2, overlay)
    while st2.pending_choice:
        resolve_pending_choice(st2, [0])
    assert len(me2.hand) == hb2, "自ターンなのにドローしている (【相手のターン中】ゲート漏れ)"


def test_op07_095_counter_card_counts_toward_its_own_trash_condition():
    """OP07-095 鉄塊【カウンター】: トラッシュ 9 枚で撃つと 鉄塊自身が 10 枚目になり +6000 総計。

    公式 (cardqa_op_07, qid 35fd0c818381):
      Q: 自分のトラッシュが 9 枚の時に この【カウンター】を発動しました。 この時、 リーダーか
         キャラ 1 枚を 合計で パワー+6000 できますか？  A: はい、できます。
    「+4000。 その後、 トラッシュが 10 以上なら +2000」。 カウンター解決時に 鉄塊が既に
    トラッシュへ移り 9→10 になるため 後段も成立。 攻撃側 10000 vs 守備リーダー 5000 を、
    +6000 (=11000) で耐えるかで判定する。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get(_FILLER), sickness=False)  # base 3000
    atk.attached_dons = 7                               # 3000 + 7000 = 10000
    me.characters = [atk]
    opp.trash = [repo.get(_FILLER)] * 9                 # 発動前トラッシュ 9
    opp.hand = [repo.get("OP07-095")]
    opp.don_active = 5
    life_before = len(opp.life)

    apply_action(st, AttackLeader(attacker_iid=atk.instance_id, counter_event_idxs=(0,)))

    assert len(opp.trash) >= 10, "前提が崩れている: 鉄塊がトラッシュに移っていない"
    assert len(opp.life) == life_before, (
        "+6000 (総計) が乗らず 守備リーダーが 10000 を耐えられていない"
        " (鉄塊自身をトラッシュ枚数に数えていない)"
    )


def test_eb01_024_static_smile_buff_includes_self():
    """EB01-024 ハムレット: 手札 4 枚以下で 自《SMILE》キャラ全員 +1000 = 自身も +1000。

    公式 (cardqa_eb_01, qid 368229976579):
      Q: 自分の手札が 4 枚以下の場合、このカードの効果で このカード自身のパワーは
         +1000 されますか？  A: はい、されます。
    ハムレット自身が 特徴《SMILE》を持つため 「自《SMILE》キャラすべて」 に含まれる。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    ham = InPlay.of(repo.get("EB01-024"), sickness=False)  # base power 4000
    me.characters = [ham]

    me.hand = [repo.get(_FILLER)] * 3                   # 手札 3 (≤4)
    evaluate_static_effects(st, overlay)
    assert ham.power == 5000, f"手札 4 以下で 自身に +1000 されていない (power={ham.power})"

    me.hand = [repo.get(_FILLER)] * 5                   # 手札 5 (>4)
    evaluate_static_effects(st, overlay)
    assert ham.power == 4000, f"手札 5 で 静的バフが解けていない (power={ham.power})"


def test_op11_001_replace_leave_requires_3_trash():
    """OP11-001 コビー: トラッシュが 3 枚未満なら 「代わりにトラッシュから 3 枚をデッキ下」
    の離脱置換は行えない (= 通常どおり場を離れる)。

    一次情報 (cardqa_op_11, qid 36f9b12bb5f4):
      Q: 自分のトラッシュが2枚以下の時に、自分の元々のパワー7000以下の特徴《海軍》を持つ
         キャラが場を離れる場合、このリーダーの【ターン1回】効果で代わりに場を離れない
         ことはできますか？  A: いいえ、できません。

    是正前 (2026-08-06): 置換の「トラッシュから 3 枚」が do 側にあり payability gate が無く、
    トラッシュ 0-2 でも置換が成立してキャラを保護していた (さらに int 形 `trash_to_deck: 3`
    が do primitive では dict 既定 limit=1 に化けて 1 枚しか動かなかった)。
    `if.self_trash_count_ge: 3` を追加し、 do を dict 形 {"limit": 3} に是正。
    """
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP11-001")
    st.turn_player_idx = 1  # 相手のターン (by_opp_effect の KO)
    me, opp = st.players[0], st.players[1]
    kaigun = InPlay.of(repo.get("OP05-030_r1"), sickness=False)  # 特徴《海軍》base power 1000
    me.characters = [kaigun]

    # トラッシュ 2 枚 → 置換できない
    me.trash = [repo.get(_FILLER)] * 2
    replaced = try_replace_ko(st, me, opp, kaigun, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is False, "トラッシュ2枚 (≤2) で置換が成立してはいけない (cardqa_op_11)"

    # トラッシュ 3 枚 → 置換成立、 ちょうど 3 枚がデッキ下へ
    me.trash = [repo.get(_FILLER)] * 3
    replaced = try_replace_ko(st, me, opp, kaigun, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True, "トラッシュ3枚あれば置換成立"
    assert kaigun in me.characters, "置換成立でキャラは場に残る"
    assert len(me.trash) == 0, f"トラッシュから 3 枚が動くべき (残り={len(me.trash)})"


def test_eb04_043_kaku_replace_ko_requires_3_trash():
    """EB04-043 カク: 同型 (元々コスト5以下の黒キャラが相手効果でKO → 代わりにトラッシュ3枚を
    デッキ下)。 トラッシュ<3 では置換不成立 (= OP11-001 と同じ一般則)。"""
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP01-002", leader1="OP01-001")
    st.turn_player_idx = 1
    me, opp = st.players[0], st.players[1]
    kaku = InPlay.of(repo.get("EB04-043"), sickness=False)  # holder
    victim = InPlay.of(repo.get("PRB02-015"), sickness=False)  # 黒 CHARACTER 元々コスト4
    assert victim.card.color and "黒" in victim.card.color
    me.characters = [kaku, victim]

    me.trash = [repo.get(_FILLER)] * 2
    replaced = try_replace_ko(st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is False, "トラッシュ2枚で置換が成立してはいけない"

    me.trash = [repo.get(_FILLER)] * 3
    replaced = try_replace_ko(st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True and len(me.trash) == 0, "トラッシュ3枚で置換成立し 3 枚がデッキ下へ"


def test_op14_092_mr3_replace_ko_requires_3_trash():
    """OP14-092 Mr.3: 同型 (このキャラがKO → 代わりにトラッシュ3枚をデッキ下、 相手ターン中)。
    トラッシュ<3 では置換不成立。"""
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.turn_player_idx = 1  # 相手ターン (opp_turn)
    me, opp = st.players[0], st.players[1]
    mr3 = InPlay.of(repo.get("OP14-092"), sickness=False)
    me.characters = [mr3]

    me.trash = [repo.get(_FILLER)] * 2
    replaced = try_replace_ko(st, me, opp, mr3, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is False, "トラッシュ2枚で置換が成立してはいけない"

    me.trash = [repo.get(_FILLER)] * 3
    replaced = try_replace_ko(st, me, opp, mr3, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True and len(me.trash) == 0, "トラッシュ3枚で置換成立し 3 枚がデッキ下へ"


def test_replace_trash_to_deck_do_is_payability_gated_fullscan():
    """全走査ガード: replace_ko / replace_leave の do に 「トラッシュから N 枚をデッキ下」
    (trash_to_deck) を持つ効果は、 必ず `if.self_trash_count_ge >= N` の payability gate を
    持たねばならない。 gate が無いと 「N 枚払えないのに置換が成立してキャラを保護」 する
    タダ撃ちになる (cardqa_op_11 qid 36f9b12bb5f4 が禁じる挙動)。

    同型が OP11-001 / EB04-043 / OP14-092 の 3 種で見つかった (2026-08-06)。 将来 同じ型の
    取りこぼしが overlay に混入したら ここで落ちる。 int 形 `trash_to_deck: N` は do primitive
    では dict 既定 limit=1 に化けるので、 do 側では dict 形のみ許す。
    """
    overlay_path = ROOT / "db" / "card_effects.json"
    ov = json.loads(overlay_path.read_text(encoding="utf-8"))
    offenders = []
    for cid, effs in ov.items():
        if cid == "_meta" or not isinstance(effs, list):
            continue
        for e in effs:
            if e.get("when") not in ("replace_ko", "replace_leave"):
                continue
            for d in e.get("do", []):
                if not isinstance(d, dict) or "trash_to_deck" not in d:
                    continue
                v = d["trash_to_deck"]
                # do 側では int 形 (silently limit=1) を禁止
                assert isinstance(v, dict), (
                    f"{cid}: replace の do の trash_to_deck は dict 形にすること "
                    f"(int 形は limit=1 に化ける): {d}"
                )
                need = int(v.get("limit", 0))
                gate = int((e.get("if") or {}).get("self_trash_count_ge", 0))
                if gate < need:
                    offenders.append((cid, need, gate))
    assert not offenders, (
        "replace do の trash_to_deck に self_trash_count_ge gate が不足 "
        f"(タダ撃ち): {offenders}"
    )


def test_op16_118_counter_boost_is_set_not_add():
    """OP16-118 エース: 「パワー8000キャラは カウンター+2000 になる」 は印刷 counter を置換 (SET)。

    一次情報 (cardqa_op_16, qid 37c3a1f9cb07):
      Q: 手札の「カウンター+1000」を持ちパワー8000のキャラを「カウンター+1000」として
         使用できますか？  A: いいえ。この場合は「カウンター+2000」として使用します。

    印刷 +1000 の札でも使用値は +2000 (= +3000 ではない)。 是正前は `base += 2000` で 3000 に
    なっていた (公式違反)。 対照: パワー8000でない札 / OP16-118 不在では素の印刷 counter。
    """
    from engine.game import _spend_counters
    repo, overlay = _repo(), _overlay()
    # 印刷 counter 1000・パワー8000 の CHARACTER を探す
    cid = None
    for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8")):
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == "CHARACTER" and int(cd.power or 0) == 8000 and int(cd.counter or 0) == 1000:
            cid = c["card_id"]
            break
    assert cid is not None, "テスト前提の 8000/counter1000 キャラが見つからない"

    st = _state(repo, overlay)
    st.turn_player_idx = 1
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP16-118"), sickness=False)]
    me.hand = [repo.get(cid)]
    evaluate_static_effects(st, overlay)
    assert _spend_counters(me, (0,)) == 2000, "SET (置換) されず +3000 になっている (公式違反)"

    # 対照: OP16-118 不在なら素の 1000
    st2 = _state(repo, overlay)
    st2.turn_player_idx = 1
    me2 = st2.players[0]
    me2.hand = [repo.get(cid)]
    evaluate_static_effects(st2, overlay)
    assert _spend_counters(me2, (0,)) == 1000, "boost 不在なのに値が変わっている"


# ============================================================================
# 公式 Q&A conformance バッチ (2026-08-06 #2、 cron optcg-faq-conformance)
# 20 件処理 = conform 16 / n-a 2 / escalated 1 / (1 は他バッチ既記)。
# engine/overlay は無変更。 下記は conform を将来の黙った回帰から守る lock。
# 一次情報は各 cardqa。 いずれも engine 実測で公式どおりを確認済。
# ============================================================================

def test_op01_091_don_count_includes_attached_dons():
    # cardqa_op_01 3953d4e2f831: 「場のドン10枚ある場合」はリーダー/キャラ付与ドンも数える→はい
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.don_active = 6
    me.leader.attached_dons = 2
    me.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]
    me.characters[0].attached_dons = 2  # active6 + leader2 + char2 = 10
    assert eval_condition({"self_don_ge": 10}, st, me) is True
    me.characters[0].attached_dons = 1  # total 9
    assert eval_condition({"self_don_ge": 10}, st, me) is False


def test_eb02_047_discarded_cp_char_is_summonable_from_trash():
    # cardqa_eb_02 39e61328cfc5: 起動メインのコストで捨てたコスト5以下CPキャラを登場できる→はい
    repo, overlay = _repo(), _overlay()
    cand = None
    for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8")):
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        feats = getattr(cd, "features", []) or []
        if isinstance(feats, str):
            feats = [feats]
        if (cat == "CHARACTER" and any("CP" in (f or "") for f in feats)
                and int(cd.cost or 99) <= 5 and cd.name != "ブルーノ"
                and "_p" not in c["card_id"] and "_r" not in c["card_id"]):
            cand = c["card_id"]
            break
    assert cand is not None
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    bruno = InPlay.of(repo.get("EB02-047"), sickness=False)
    me.characters = [bruno]
    me.hand = [repo.get(cand)]  # 唯一の手札 = discard コストで捨てられる CP キャラ
    me.trash = []
    effs = list_activate_main_effects(st, me, overlay)
    te = [(i, e) for (i, e) in effs if i.instance_id == bruno.instance_id]
    assert te
    fire_activate_main(st, me, opp, te[0][0], te[0][1])
    assert any(c.card.card_id == cand for c in me.characters), \
        "コストで捨てた CP キャラがトラッシュから登場していない"


def test_op07_119_rush_when_life_le_2_and_no_card_added():
    # cardqa_op_07 3a5a9f89ea9a: ライフ2以下で登場、ライフに加えなかった場合も速攻を得る→はい
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = []          # デッキ空 → put_top_to_life は 0 枚
    me.life = [repo.get(_FILLER)] * 2
    e = InPlay.of(repo.get("OP07-119"), sickness=True)
    me.characters = [e]
    trigger_on_play(st, me, opp, e, overlay)
    assert "速攻" in e.granted_keywords
    # 対照: 1 枚加えて life 3 → 速攻なし
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    me2.deck = [repo.get(_FILLER)] * 3
    me2.life = [repo.get(_FILLER)] * 2
    e2 = InPlay.of(repo.get("OP07-119"), sickness=True)
    me2.characters = [e2]
    trigger_on_play(st2, me2, opp2, e2, overlay)
    assert "速攻" not in e2.granted_keywords


def test_op07_017_kos_character_even_without_stage_target():
    # cardqa_op_07 3b18e4e32dda: 相手にコスト1以下ステージが無くてもパワー3000以下キャラをKO→はい
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]  # power 3000
    opp.stages = []
    bundle = overlay.get("OP07-017")
    entries = bundle.effects if hasattr(bundle, "effects") else bundle
    for entry in entries:
        if (entry.get("when") if isinstance(entry, dict) else getattr(entry, "when", None)) == "main":
            for prim in (entry.get("do") if isinstance(entry, dict) else entry.do):
                execute_effect(prim, st, me, opp, None)
    assert len(opp.characters) == 0, "ステージ不在で chara KO が空振りしている"


def test_op16_111_trigger_life_condition_true_after_life_card_popped():
    # cardqa_op_15/16 3b8f66194c5f: このカードを含めライフ3枚でも【トリガー】で登場できる→はい
    # トリガー発火時、このライフ札は既に pop 済 (3→2) なので self_life_le:2 が成立する。
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)] * 2  # 3 枚のうち発火札を pop した後の状態
    assert eval_condition({"self_life_le": 2}, st, me) is True


def test_st06_016_prevent_ko_is_snapshot_at_activation():
    # cardqa_st_06 3bc4ddb9257c: 【トリガー】後に登場した自キャラはKOされない効果を受けない→いいえ
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    present = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [present]
    bundle = overlay.get("ST06-016")
    entries = bundle.effects if hasattr(bundle, "effects") else bundle
    trig = [e for e in entries
            if (e.get("when") if isinstance(e, dict) else getattr(e, "when", None)) == "trigger"][0]
    for prim in (trig.get("do") if isinstance(trig, dict) else trig.do):
        execute_effect(prim, st, me, opp, None)
    assert getattr(present, "ko_immune_until_turn_end", False) is True
    later = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(later)
    assert getattr(later, "ko_immune_until_turn_end", False) is False, \
        "発動後に登場したキャラが KO 耐性を得ている (スナップショット違反)"


def test_op01_052_attacker_counts_in_self_rested_chara_count():
    # cardqa_op_01 3c4617bee1c1: アタック中のこのキャラを含めレストキャラ2枚で引ける→はい
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    attacker = InPlay.of(repo.get("OP01-052"), sickness=False)
    other = InPlay.of(repo.get("OP01-016"), sickness=False)
    other.rested = True
    attacker.rested = True  # アタック宣言でレスト
    me.characters = [attacker, other]
    assert eval_condition({"self_rested_chara_count_ge": 2}, st, me, attacker) is True


# =========================================================================== #
#  人間レビュー行き (escalated) 8 件の是正 — 2026-08-06
#  いずれも 「アーキ変更が要る」 として自動修正を見送られていたもの。
# =========================================================================== #
def _tb(repo, ov, leader_a="OP01-001", leader_b="OP01-001"):
    import random
    from engine.core import GameState, InPlay, Phase, Player
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_a), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(leader_b), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 10
        p.life = [repo.get("OP01-013")] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 5
    return st, p0, p1


def _eff_of(ov, cid, when):
    return next(e for e in ov.get(cid).effects if e.get("when") == when)


def test_opp_card_rest_covers_stage_and_don():
    """OP14-024: 「相手の**カード**1枚をレスト」 は リーダー/キャラ/ステージ/ドン の 4 ゾーン。

    一次情報 (cardqa_op_14): 「この効果は、 相手の場にある、 **リーダー、 キャラ、 ステージ、
    ドン!!のうち1枚**をアクティブからレストにします。」
    ⚠ 是正前は one_opponent_inplay_any (= リーダー+キャラのみ) で ステージ/ドンが選べなかった。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = _eff_of(ov, "OP14-024", "on_ko")

    # ステージしか残っていない盤面 → ステージがレストされる
    st, p0, p1 = _tb(repo, ov)
    p1.characters, p1.don_active = [], 0
    p1.leader.rested = True
    stage = InPlay.of(repo.get("OP02-048"), sickness=False)
    p1.stages = [stage]
    execute_effect(eff["do"][0], st, p0, p1, None)
    assert stage.rested, "相手ステージがレストされていない (対象範囲が狭い)"

    # ドンしか無い盤面 → アクティブドンが 1 枚レストへ
    st, p0, p1 = _tb(repo, ov)
    p1.characters, p1.stages = [], []
    p1.leader.rested = True
    p1.don_active, p1.don_rested = 3, 0
    execute_effect(eff["do"][0], st, p0, p1, None)
    assert (p1.don_active, p1.don_rested) == (2, 1), \
        f"相手のドンがレストされていない: active={p1.don_active} rested={p1.don_rested}"


def test_opponent_chooses_which_of_their_own_characters_leaves():
    """OP09-058: 「**相手は**自身のコスト6以下のキャラ1枚を戻す」 = **選ぶのは相手**。

    一次情報 (cardqa_op_09): 「このカードを使用したプレイヤーの**対戦相手が**、 自身の場の
    コスト6以下のキャラの中から1枚を選び、 手札に戻します。」
    ⚠ 是正前は行動側が選んでおり **相手の最強キャラを bounce できた** (= 除去として過大)。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = _eff_of(ov, "OP09-058", "main")

    lo, hi = "EB01-015", "OP08-099"          # cost1/power1000, cost6/power8000
    st, p0, p1 = _tb(repo, ov)
    L = InPlay.of(repo.get(lo), sickness=False)
    H = InPlay.of(repo.get(hi), sickness=False)
    p1.characters = [H, L]                    # 強い方を先頭 = 順序に釣られないことも見る
    execute_effect(eff["do"][0], st, p0, p1, None)
    assert H in p1.characters and L not in p1.characters, \
        "相手が選ぶなら 最も惜しくない (低価値の) キャラが戻るはず"

    # 対照: chooser 指定が無ければ 行動側が選ぶ = 高価値が戻る (= 分岐が効いている証拠)
    st, p0, p1 = _tb(repo, ov)
    L2 = InPlay.of(repo.get(lo), sickness=False)
    H2 = InPlay.of(repo.get(hi), sickness=False)
    p1.characters = [L2, H2]
    execute_effect({"return_to_hand": "one_opponent_character_cost_le_6cost"},
                   st, p0, p1, None)
    assert H2 not in p1.characters, "chooser 無しでは行動側が高価値を選ぶはず (対照)"


def test_don_attach_target_covers_both_sides():
    """OP15-012: 「リーダーかキャラ1枚に**持ち主の**レストのドン‼」 = 修飾なし = 両陣営。

    一次情報 (cardqa_op_15): 「…自分のリーダーやキャラに自分のレストのドン!!を付与することや、
    **相手のリーダーやキャラに相手のレストのドン!!を付与すること**はできますか？」 → 「はい」。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _tb(repo, ov)
    st.human_player_idx = 0
    st.forced_human_actor_idx = 0
    p0.don_rested = p1.don_rested = 2
    p1.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
    execute_effect(_eff_of(ov, "OP15-012", "on_attack")["do"][0], st, p0, p1, None)

    pc = st.pending_choice
    assert pc is not None, "人間 acting なのに対象選択 modal が立たない"
    owners = {c.get("owner") for c in pc.get("candidates", [])}
    assert "opp" in owners and "self" in owners, \
        f"両陣営が候補に出ていない: {owners}"


def test_actor_opp_effect_resolves_on_the_opponent_side():
    """OP12-075: 「その後、 **相手は**ドン‼…を追加してもよい」 = 相手の側で解決し相手が決める。

    一次情報 (cardqa_op_12): 「相手がドン!!を追加するかどうかを決めるのは自分ですか？
    相手ですか？」 → 「この場合、 **相手が**ドン!!を追加するかどうかを決めます。」
    ⚠ 是正前は bundle 直下の actor/optional が無視され、 **発動者にドンが追加され**
      しかも **任意でもなかった** (二重違反)。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_on_play

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _tb(repo, ov)
    src = InPlay.of(repo.get("OP12-075"), sickness=True)
    p0.characters = [src]
    a0, a1 = p0.don_active, p1.don_active
    trigger_on_play(st, p0, p1, src, ov)
    assert p0.don_active == a0, "発動者にドンが追加されている (actor が反転していない)"
    assert p1.don_active == a1 + 1, "相手にドンが追加されていない"


def test_simultaneous_leave_pays_replacement_cost_only_once():
    """OP15-090 ペローナ: 2 枚同時離脱でも 置換コストは **手札1枚**、 2 枚とも残る。

    一次情報 (cardqa_op_15): 「自分の元々のパワー7000以下のキャラが2枚同時に相手の効果で
    場を離れる場合、 代わりに自分の手札2枚を捨てることはできますか？」 →
    「自分の手札**1枚**を捨てることで場を離れるキャラを**2枚とも**場に残すか、 何もせず
     キャラ2枚が場を離れるかを選びます。」
    ⚠ 是正前は ko_multi が victim 毎に置換を呼び **手札 2 枚** 捨てていた。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _tb(repo, ov)
    perona = InPlay.of(repo.get("OP15-090"), sickness=False)
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v2 = InPlay.of(repo.get("OP01-013"), sickness=False)
    p1.characters = [perona, v1, v2]
    p1.hand = [repo.get("OP01-013")] * 4
    src = InPlay.of(repo.get("OP01-016"), sickness=False)
    p0.characters = [src]
    hand_before = len(p1.hand)

    execute_effect({"ko_multi": ["one_opponent_character_power_le_3000",
                                 "one_opponent_character_power_le_3000"]},
                   st, p0, p1, src)

    assert hand_before - len(p1.hand) == 1, \
        f"置換コストが victim 数だけ払われている: 手札 -{hand_before - len(p1.hand)}"
    assert v1 in p1.characters and v2 in p1.characters, \
        "1 枚のコストで 2 枚とも残っていない"


def test_deferred_deck_out_loses_at_end_of_turn_and_can_be_simultaneous():
    """OP15-022 ブルック: デッキ0 でも即敗北せず、 そのターン終了時に敗北 (両者なら同時敗北)。

    一次情報 (cardqa_op_15): 「自分と相手がこのリーダーを使用していて、 自分のターン中に
    自分と相手のデッキがどちらも0枚になった場合、 このターンの終了時にどのプレイヤーが
    敗北しますか？」 → 「**どちらのプレイヤーも同時にゲームに敗北します。**」
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, evaluate_static_effects
    from engine.game import advance_phase

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def mk(both: bool):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP15-022"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(
            repo.get("OP15-022" if both else "OP01-001"), sickness=False))
        for p in (p0, p1):
            p.life = [repo.get("OP01-013")] * 3
            p.deck = []
        st = GameState(players=[p0, p1], phase=Phase.END,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        evaluate_static_effects(st, ov)
        return st, p0, p1

    st, p0, p1 = mk(True)
    assert p0.deck_out_defer and p1.deck_out_defer, "常在ルール改変が付いていない"
    advance_phase(st)
    assert st.game_over and st.winner is None, \
        f"両者デッキ0 は同時敗北 (引き分け) のはず: winner={st.winner}"

    st, p0, p1 = mk(False)
    p1.deck = [repo.get("OP01-013")] * 5
    advance_phase(st)
    assert st.game_over and st.winner == 1, \
        f"片方だけデッキ0 なら相手の勝ち: winner={st.winner}"


def test_attached_don_returns_rested_and_can_fuel_the_same_effect():
    """OP12-014: コストで自身がトラッシュ → 付与ドンがレストで戻り、 その効果の源になる。

    一次情報 (cardqa_op_12): 「このキャラにドン!!が付与されている状態で、 この【起動メイン】
    効果を発動した場合、 **このキャラ自身に付与されていたドン!!を、 効果で付与するドン!!と
    して選ぶことはできますか？**」 → 「はい、 できます。」
    ⭐ これは attach 源に attached_dons を含める必要があるという話ではなく、
      **コストを先に払う → 自身がトラッシュ → 付与ドンが公式 6-5-5-4 でコストエリアに
      レストで戻る → その「レストのドン」が効果の源になる** という順序の帰結。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay
    from engine.game import legal_actions, apply_action

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _tb(repo, ov)
    h = InPlay.of(repo.get("OP12-014"), sickness=False)
    h.attached_dons = 2
    p0.characters = [h]
    p0.don_rested = p0.don_active = 0     # コストエリアにレストのドンは無い

    acts = [a for a in legal_actions(st) if type(a).__name__ == "ActivateMain"]
    assert acts, "起動メインが legal に出ていない"
    apply_action(st, acts[0])
    assert p0.leader.attached_dons == 2, (
        "自身の付与ドンがコストエリアにレストで戻って効果の源になっていない: "
        f"leader.attached={p0.leader.attached_dons} don_rested={p0.don_rested}"
    )
# --------------------------------------------------------------------------- #
#  2026-08-06 batch (cron optcg-faq-conformance)
# --------------------------------------------------------------------------- #
def test_op10_098_kaihou_ko_uses_printed_cost():
    """OP10-098 解放【メイン】「相手の**元々の**、コスト6以下…とコスト4以下…をKO」。

    一次情報 (cardqa_op_10 3cba8f85f333):
      「この【メイン】効果で、元々のコストが7以上で他の効果によってコストが下がっている
        相手のキャラをKOできますか？」→「いいえ、できません。…元々のコストが6以下…と
        元々のコストが4以下…を、それぞれ1枚までKOする効果です」

    是正前は ko_multi target が現在コスト spec (one_opponent_character_cost_le_6/4) で、
    元々コスト7を効果で6に下げるとKOできてしまっていた (公式違反)。
    truly_original_cost_le_6/4 (= 印刷コスト判定) に是正済。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # 印刷コスト7 のキャラを効果で現在6に下げる → 元々(印刷)7 なので KO されないはず。
    victim7 = InPlay.of(repo.get("OP01-067"), sickness=False)   # 印刷コスト 7
    victim7.cost_minus_until_turn_end = 1                        # 現在コスト 6
    victim4 = InPlay.of(repo.get("OP01-005"), sickness=False)   # 印刷コスト 4
    opp.characters = [victim7, victim4]
    me.characters = []   # 自キャラ0 vs 相手2 → chara_diff = -2 ≤ -2 (if 成立)

    assert victim7.base_cost == 6 and victim7.card.cost == 7
    bundle = overlay.get("OP10-098")
    entries = bundle.effects if hasattr(bundle, "effects") else bundle
    main = [e for e in entries
            if (e.get("when") if isinstance(e, dict) else getattr(e, "when", None)) == "main"][0]
    for prim in (main.get("do") if isinstance(main, dict) else main.do):
        execute_effect(prim, st, me, opp, None)

    assert victim7 in opp.characters, \
        "元々コスト7(現在6)が KO された = 現在コスト判定の違反 (truly_original でないと落ちる)"
    assert victim4 not in opp.characters, "元々コスト4 は KO されるはず (対照)"


def test_original_cost_wording_uses_truly_original_spec_fullscan():
    """全走査ガード: overlay entry の `_text` が 「元々の…コスト」 を含むなら、
    その entry の target spec は truly_original_cost_* でなければならない
    (素の *_cost_le/ge/eq_N は現在コスト判定 = 「元々の」 の公式意味に反する)。"""
    import re as _re
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    bad = []
    for cid, entries in ov.items():
        if cid == "_meta" or not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            txt = e.get("_text", "")
            if "元々の" not in txt or "コスト" not in txt:
                continue
            blob = json.dumps(e, ensure_ascii=False)
            plain = [p for p in _re.findall(r'"[a-z_]*_cost_(?:le|ge|eq)_\d+(?:cost)?"', blob)
                     if "truly_original" not in p]
            if plain:
                bad.append((cid, set(plain)))
    assert not bad, f"「元々の…コスト」なのに現在コスト spec を使う entry: {bad}"


def test_st22_016_reveal_returns_card_to_top():
    """ST22-016【カウンター】: デッキ上1枚を公開 (移動指示テキストなし)。

    一次情報 (cardqa_st_22 4033ff7d15df):
      「この【カウンター】効果で、自分のデッキの上から公開したカードはどうなりますか？」
      →「この場合、そのまま公開したカードをデッキの一番上に裏向きで戻します。」

    是正前は rest_remain:bottom でデッキ下送りしていた (公式違反)。top に是正済。
    マッチ (白ひげ) / 非マッチ どちらでも公開札はデッキトップに残る。
    """
    repo, overlay = _repo(), _overlay()
    bundle = overlay.get("ST22-016")
    entries = bundle.effects if hasattr(bundle, "effects") else bundle
    counter = [e for e in entries
               if (e.get("when") if isinstance(e, dict) else getattr(e, "when", None)) == "counter"][0]
    do = counter.get("do") if isinstance(counter, dict) else counter.do

    for top_id, label in (("ST22-002", "マッチ(白ひげ)"), ("OP01-013", "非マッチ")):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        me.deck = [repo.get(top_id)] + [repo.get(_FILLER)] * 10
        deck_len = len(me.deck)
        for prim in do:
            execute_effect(prim, st, me, opp, None)
        assert len(me.deck) == deck_len, f"{label}: デッキ枚数が変化 (公開札が消えた/移動した)"
        assert me.deck[0].card_id == top_id, \
            f"{label}: 公開札がデッキトップに戻っていない (rest_remain=bottom 違反)"


def test_reveal_top_then_no_bottom_text_returns_to_top_fullscan():
    """全走査ガード: reveal_top_then で、カードテキストに 「デッキの下」/「下に置く」 の
    移動指示が **無い** entry は rest_remain=bottom にしてはならない (= 公開札はトップに戻る)。"""
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    bad = []
    for cid, entries in ov.items():
        if cid == "_meta" or not isinstance(entries, list):
            continue
        x = cards.get(cid) or cards.get(cid.split("_")[0])
        if not x:
            continue
        t = (x.get("text") or "") + " " + (x.get("trigger") or "")
        has_bottom = ("デッキの下" in t) or ("下に置" in t)
        for e in entries:
            if not isinstance(e, dict):
                continue
            for d in (e.get("do") or []):
                if isinstance(d, dict) and "reveal_top_then" in d:
                    rr = d["reveal_top_then"].get("rest_remain", "bottom")
                    if rr == "bottom" and not has_bottom:
                        bad.append((cid, rr))
    assert not bad, f"移動指示テキスト無しなのに rest_remain=bottom: {bad}"


# =========================================================================== #
#  「〜できる」 = **コスト無しの任意効果** の辞退経路 (2026-08-07、 escalated 3 件)
#  公式は 文末の 「できる」 / 「してもよい」 / 「N枚まで」 で **辞退できる** ことを示す。
#  ⚠ engine は 「コロン前のできる：」 (= 発動コスト) だけを任意扱いしており、
#    **効果側の 「できる」 に辞退経路が無かった**。
# =========================================================================== #
def test_costless_optional_effect_can_be_declined():
    """EB04-001: 「その後、…ライフの上から1枚を手札に加えることが**できる**」 は辞退できる。

    空コストの `optional_cost_then` (cost: []) で表現する = 新機構を足さずに
    「コスト無しの任意効果」 を表せる (payability 常真 → 人間は確認 modal / AI は発動)。
    """
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect, resolve_pending_choice

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = _eff_of(ov, "EB04-001", "activate_main")

    st, p0, p1 = _tb(repo, ov, leader_a="EB04-001")
    st.human_player_idx = 0
    st.forced_human_actor_idx = 0
    from engine.core import InPlay
    p1.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
    life_before = len(p0.life)
    for prim in eff["do"]:
        execute_effect(prim, st, p0, p1, p0.leader)

    pc = st.pending_choice
    assert pc is not None and pc.get("kind") == "optional_cost_confirm", \
        f"任意効果の確認 modal が立たない: {pc.get('kind') if pc else None}"
    assert "任意コスト" not in (pc.get("prompt") or ""), \
        f"コスト無しなのに 「任意コスト」 と表示している: {pc.get('prompt')}"
    resolve_pending_choice(st, [0])          # 辞退
    assert len(p0.life) == life_before, "辞退したのにライフが減っている"


def test_opponent_can_decline_forced_play_from_hand():
    """OP13-119: 「相手は自身の手札から…キャラカード1枚**まで**を、 登場させる」。

    「まで」 = **0 枚 (= 登場させない) も選べる**し、 **どれを出すかも相手が決める**。
    ⚠ 是正前は候補があれば最善を強制登場させており辞退経路が無かった。
    AI 相手は 「無料でキャラを出せる = 出すのが最善」 なので自動 (= 挙動不変)。
    """
    from engine.core import InPlay
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect, resolve_pending_choice

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(e for e in ov.get("OP13-119").effects
               if e.get("when") == "on_play" and e.get("optional"))

    def run(picks):
        st, p0, p1 = _tb(repo, ov)
        st.human_player_idx = 1                      # 相手が人間
        p1.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
        p1.hand = [repo.get("OP01-013"), repo.get("OP01-016")]
        for prim in eff["do"]:
            execute_effect(prim, st, p0, p1, None)
            if st.pending_choice:
                break
        pc = st.pending_choice
        assert pc is not None and pc.get("kind") == "opp_optional_play_from_hand", \
            f"相手に選択 modal が立たない: {pc.get('kind') if pc else None}"
        assert pc.get("actor_idx") == 1, "modal の actor が相手になっていない"
        resolve_pending_choice(st, picks)
        return len(p1.characters), len(p1.hand)

    c_no, h_no = run([])          # 辞退 (= 0 枚)
    c_yes, h_yes = run([0])       # 1 枚 登場
    # bounce で 1 枚が手札へ戻る → 辞退なら 場 0 / 手札 3、 登場なら 場 1 / 手札 2
    assert (c_no, h_no) == (0, 3), f"辞退できていない: chars={c_no} hand={h_no}"
    assert (c_yes, h_yes) == (1, 2), f"承諾で 1 枚登場していない: chars={c_yes} hand={h_yes}"


def test_costless_optional_sweep_has_no_forced_follow_up_clause():
    """⭐ 全走査: 公式が 「その後、…できる/してもよい」 と書くカードに **任意表現がある**。

    ⚠ 判定は **カード単位**。 1 枚のカードは複数の effect entry を持ち、 どの entry が
      どの節に対応するかは overlay からは一意に決まらない (= entry 単位で見ると
      静的効果 entry まで巻き込んで誤検出する。 2026-08-07 に実際に踏んだ)。
      「この節を表現しうる entry がカード内に 1 つでもあるか」 を見るのが正しい粒度。
    ⚠ 「代わりに…できる」 (置換 = replace_* の optional) と
      「アタック/ブロックできる」 (= 能力付与であって任意行動ではない) は除外する。
    """
    import json
    import re

    cards = {c["card_id"]: c
             for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    rx = re.compile(r"その後、([^。]*?(?:できる|してもよい))。")
    # 任意性を表す表現 (いずれかがカード内にあれば その節は表現済とみなす)
    OPTIONAL_MARKS = ("optional_cost_then", "force_opp_play_from_hand",
                      '"optional": true', '"optional":true', '"actor": "opp"', '"actor":"opp"')

    bad: list[str] = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list) or cid.startswith("_"):
            continue
        card = cards.get(cid)
        if not card:
            continue
        text = re.sub(r"\s+", "", (card.get("text") or "") + (card.get("trigger") or ""))
        clauses = [m.group(1) for m in rx.finditer(text)]
        clauses = [c for c in clauses
                   if "代わりに" not in c and "アタックできる" not in c
                   and "ブロックできる" not in c]
        if not clauses:
            continue
        blob = json.dumps(effs, ensure_ascii=False)
        if any(mk in blob for mk in OPTIONAL_MARKS):
            continue
        bad.append(f"{cid}: その後、{clauses[0][:52]}")

    assert not bad, (
        "公式が 「その後、…できる」 と書くのに overlay に任意表現が無い:\n  "
        + "\n  ".join(bad)
    )


def test_self_chara_cost_ge_count_uses_current_cost_and_includes_source():
    """「自分のコストN以上のキャラがいる場合」 は **現在コスト** (= base_cost、 コスト修正込み)
    で判定し、 発動元キャラ自身も数える。

    一次情報 (db/cardqa_tagged.json series=st_14):
      Q: 「このキャラ自身のコストが6以上の場合、このキャラの【相手のターン中】効果によって、
          このキャラは相手の効果でKOされずパワー+2000されますか？」 → A: 「はい、されます。」
      (ST14-009 フランキー / ST14-003 サンジ = 印刷コスト5。 コスト+1 修正で現在コスト6 の時、
       自分自身を 「コスト6以上のキャラ」 として数える)

    是正前 (self_chara_cost_ge_count が c.card.cost = 印刷コストを見ていた) は、 base_cost を
    6 に上げても印刷5のままで False = 違反。 現在は c.base_cost で判定する為 True になる。
    """
    repo = _repo()
    ov = _overlay()
    st = _state(repo, ov, leader0="ST14-001")
    frank = InPlay.of(repo.get("ST14-009"), sickness=False)  # 印刷コスト5
    st.players[0].characters = [frank]
    cond = {"self_chara_cost_ge_count": {"cost_ge": 6, "n": 1}}
    # 印刷コスト5 のまま = 条件不成立 (自身もコスト6未満)
    assert frank.base_cost == 5
    assert eval_condition(cond, st, st.players[0]) is False
    # コスト+1 修正で現在コスト6 = 発動元自身を数えて条件成立
    frank.base_cost_override = 6
    assert frank.base_cost == 6
    assert eval_condition(cond, st, st.players[0]) is True


def test_self_chara_cost_ge_count_overlays_are_plain_cost_not_printed():
    """全走査ガード: self_chara_cost_ge_count を使う overlay は すべて 素の 「コスト以上」
    (= 現在コスト判定が正しい) であり、 「元々のコスト」 (= 印刷コスト) を意図した節は無い。

    素の 「コストN以上」 は現在コストで見る (docs/official_rulings.md)。 もし将来 「元々の
    コストN以上」 のカードが self_chara_cost_ge_count を使うよう追加されたら、 現在コスト判定は
    そのカードにとって誤りになる為、 このガードで気付けるようにする。
    """
    import json as _json
    ov = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    # ⚠ 判定は カード全体でなく **primitive を含む効果エントリ単位** で行う。 同じカードの
    #   別エントリ (例: OP12-081 コアラ の 「元々のコスト8以上のキャラを登場させた時」 の
    #   reactive) を巻き込むと誤検出する (docs/official_rulings.md の記録どおり entry 粒度が正しい)。
    entries = []
    for cid, effs in ov.items():
        if not isinstance(effs, list) or cid.startswith("_"):
            continue
        for e in effs:
            if isinstance(e, dict) and "self_chara_cost_ge_count" in _json.dumps(e, ensure_ascii=False):
                entries.append((cid, e))
    assert entries, "self_chara_cost_ge_count を使う overlay entry が 0 = テストが空回り"
    bad = [f"{cid}: {e.get('_text','')[:60]}"
           for cid, e in entries if "元々" in _json.dumps(e, ensure_ascii=False)]
    assert not bad, (
        "self_chara_cost_ge_count (= 現在コスト判定) の効果エントリが 「元々の」 を意図:\n  "
        + "\n  ".join(bad)
    )


# =========================================================================== #
#  手札の chooser 帰属 (2026-08-07)
#    公式は 盤面と同じく 手札でも 「相手は」 と 「相手の」 を書き分ける:
#      「**相手は**(自身の)手札N枚を捨てる」 → **手札の持ち主 (相手) が選ぶ**
#        cardqa_op_01「この【登場時】効果で捨てるカードは相手が選びますか？」
#                   → 「はい、 **手札の持ち主である相手が選びます**。」
#        cardqa_st_18「…この【登場時】効果を発動していない側のプレイヤーが、 そのプレイヤーの
#                     手札からカードを2枚選び、 そのプレイヤーのトラッシュに置きます。」
#      「**相手の**手札N枚を捨てる」 → **発動者が裏向きで選ぶ** (= ランダムが忠実)
#        cardqa_op_03 / cardqa_st_10「発動したプレイヤーが、 相手の手札を裏向きの状態で2枚選びます」
#    ⚠ 2026-08-07 まで両方を trash_opp_hand_random (= ランダム) にしており、
#      「相手が選ぶ」 型が **本来より強かった** (相手は惜しくない札を捨てられるはずが
#      キーカードがランダムで飛んでいた)。 対象 20 枚。
# =========================================================================== #
def test_opponent_chooses_which_of_their_own_hand_cards_to_discard():
    """「相手は自身の手札1枚を捨てる」 は **決定的に相手の選択** で解決する (ランダムでない)。"""
    import json
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    raw = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    hi = next(c for c in raw
              if c["category"] == "CHARACTER" and str(c.get("counter") or "") == "2000")
    lo = next(c for c in raw
              if c["category"] == "CHARACTER" and str(c.get("counter") or "0") in ("", "0", "-"))

    def run(seed, prim):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(seed), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        p1.hand = [repo.get(hi["card_id"]), repo.get(lo["card_id"])]
        execute_effect(prim, st, p0, p1, None)
        return p1.trash[0].card_id

    chosen = {run(s, {"opp_discard_own_choice": 1}) for s in range(8)}
    assert len(chosen) == 1, f"相手の選択が seed で変わる (= ランダムのまま): {chosen}"
    assert hi["card_id"] not in chosen, \
        "相手が高カウンターの防御札を捨てている (= 惜しくない札を選べていない)"
    # 対照: 「相手の手札」 (= 発動者が裏向きで選ぶ) は random のままが忠実
    rnd = {run(s, {"trash_opp_hand_random": 1}) for s in range(8)}
    assert len(rnd) > 1, "trash_opp_hand_random が決定的になっている (裏向き選択の忠実性が壊れた)"


def test_hand_chooser_attribution_matches_official_wording_whole_corpus():
    """⭐ 全走査: 「相手は自身の手札…捨てる」 = opp_discard_own_choice /
    「相手の手札…捨てる」 = trash_opp_hand_random (= 裏向き) の書き分けが崩れていない。"""
    import json
    import re

    cards = {c["card_id"]: c
             for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    # 「相手の手札が N 枚以上」 は **条件節** なので対象指定と混同しない
    SELF = re.compile(r"相手は[、]?(?:自身の|自分の)?手札[^。]{0,24}?捨て")
    ACTOR = re.compile(r"相手の手札(?!が)[^。]{0,20}?捨て")

    bad: list[str] = []
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list) or cid.startswith("_"):
            continue
        card = cards.get(cid)
        if not card:
            continue
        full = re.sub(r"\s+", "", (card.get("text") or "") + (card.get("trigger") or ""))
        blob = json.dumps(effs, ensure_ascii=False)
        has_self, has_actor = bool(SELF.search(full)), bool(ACTOR.search(full))
        uses_rand = ("trash_opp_hand_random" in blob) or ("force_opp_discard" in blob)
        uses_choice = "opp_discard_own_choice" in blob
        if has_self and not has_actor and uses_rand and not uses_choice:
            bad.append(f"{cid}: 「相手は自身の手札…捨てる」 なのにランダム")
        if has_actor and not has_self and uses_choice:
            bad.append(f"{cid}: 「相手の手札…捨てる」 (裏向き) なのに相手選択になっている")

    assert not bad, "手札 chooser の書き分けが overlay と不一致:\n  " + "\n  ".join(bad)


def test_opponent_returns_rested_don_not_active():
    """「**相手は**自身の場のドン‼1枚をドン‼デッキに戻す」 = **相手が選ぶ** → レストから返す。

    ⚠ 是正前は **アクティブ優先** = 行動側に都合のよい選択だった。 相手は当然
    アクティブ (= このターンまだ使える。 こちらのターンならカウンターイベントの支払いに要る)
    を残し、 レストのドンから返す。 対象 5 枚 (OP02-085/089/090/091 / OP14-065)。
    ⚠ 「相手の**アクティブの**ドン」 と明示するカード (OP15-059 / PRB02-005) は別 primitive。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 10
        p.life = [repo.get("OP01-013")] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 5
    p1.don_active, p1.don_rested = 3, 2

    execute_effect({"return_opp_don": 1}, st, p0, p1, None)
    assert (p1.don_active, p1.don_rested) == (3, 1), (
        "相手はレストのドンから返すはず (アクティブを温存): "
        f"active={p1.don_active} rested={p1.don_rested}"
    )
    # レストが尽きたらアクティブから (= 枚数は必ず満たす)
    p1.don_active, p1.don_rested = 2, 0
    execute_effect({"return_opp_don": 1}, st, p0, p1, None)
    assert (p1.don_active, p1.don_rested) == (1, 0), \
        "レストが無いときにアクティブから返せていない"


def test_opponent_picks_the_least_bad_option_including_a_no_op():
    """「**相手は**以下から1つを選ぶ」 (actor="opp") は **相手が選ぶ** = 損の小さい方。

    一次情報 (cardqa_st_20): 「対戦相手のライフが0枚のときに、 自分はこの【登場時】効果を
    発動し…対戦相手は『・相手のライフの上から1枚をトラッシュに置く。』を選ぶことは
    できますか？」 → 「**はい、 できます。** この場合、 トラッシュに置くことができる
    ライフがないため、 **何も起きません。**」
    ⚠ 是正前は actor に関わらず発動者視点の max = **発動者に最も都合のよい選択肢** を
      選んでおり、 相手が選ぶはずの不利益を発動者が決めていた。 対象 3 枚。
    """
    import json
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(x for x in ov.get("ST20-005").effects
               if "choice_effect" in json.dumps(x, ensure_ascii=False))

    def run(opp_life_n: int):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
        p0.life = [repo.get("OP01-013")] * 3
        p1.life = [repo.get("OP01-013")] * opp_life_n
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        p1.hand = [repo.get("OP01-013")] * 4
        for prim in eff["do"]:
            execute_effect(prim, st, p0, p1, None)
        return len(p1.hand), len(p1.life)

    # 相手ライフ 0 → 「ライフをトラッシュ」 は空振り。 相手はそれを選べる (= 手札は減らない)
    hand_after, life_after = run(0)
    assert hand_after == 4 and life_after == 0, (
        "相手が空振りの選択肢を選べていない (= 発動者最適のまま): "
        f"hand={hand_after} life={life_after}"
    )


def test_opponent_chooses_which_trash_cards_go_to_deck_bottom():
    """「**相手は**自身のトラッシュからカードN枚を…デッキの下に置く」 = **相手が選ぶ**。

    ⚠ 是正前は **トラッシュ順の先頭** から取っており相手の選択になっていなかった
      (= 蘇生の的になる高コスト札が先に抜けうる)。
    ⚠ `_worst_hand_idx` (counter 基準) は流用できない — **トラッシュからカウンターは切れない**
      ので counter は価値と無関係。 cost 低 → power 低 が正しい基準 (_worst_trash_order)。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 10
        p.life = [repo.get("OP01-013")] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 5

    big, small = repo.get("OP08-099"), repo.get("EB01-015")   # cost6 / cost1
    assert int(big.cost) > int(small.cost), "テスト前提: cost が異なる"
    p1.trash = [big, small]          # **高コストを先頭** に置く (= 順序に釣られないか)

    execute_effect({"opp_trash_to_deck_bottom": 1}, st, p0, p1, None)
    assert p1.deck[-1].card_id == small.card_id, (
        "相手は最も惜しくない (低コストの) 札を出すはず: "
        f"deck底={p1.deck[-1].card_id}"
    )
    assert [c.card_id for c in p1.trash] == [big.card_id], \
        "高コスト札 (蘇生の的) がトラッシュに残っていない"


def test_human_opponent_gets_the_choice_when_official_says_they_choose():
    """「**相手は**以下から1つを選ぶ」 で **相手が人間** ならその人に modal が立つ。

    ⚠ 選択肢の文面は **発動者視点** (「相手は自身の手札2枚を捨てる」 = 選ぶ人自身のこと)。
      したがって **do は発動者フレームで実行** する必要があり、 pending_choice の
      `_actor_idx` には **発動者** の index を入れる。 modal を出す相手と do のフレームは別物。
    """
    import json
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect, resolve_pending_choice

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(x for x in ov.get("ST20-005").effects
               if "choice_effect" in json.dumps(x, ensure_ascii=False))

    def run(human_idx, picks=None):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
        p0.life = [repo.get("OP01-013")] * 3
        p1.life = [repo.get("OP01-013")] * 2
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        st.human_player_idx = human_idx
        p1.hand = [repo.get("OP01-013")] * 4
        for prim in eff["do"]:
            execute_effect(prim, st, p0, p1, None)
            if st.pending_choice:
                break
        pc = st.pending_choice
        if pc is not None and picks is not None:
            resolve_pending_choice(st, picks)
        return pc, len(p1.hand), len(p1.life)

    # 相手 (P1) が人間 → その人に modal。 _actor_idx は **発動者 (P0)**
    pc, hand, life = run(1, [1])       # option 1 = ライフをトラッシュ
    assert pc is not None and pc.get("kind") == "option_pick", \
        f"相手が人間なのに modal が立たない: {pc.get('kind') if pc else None}"
    assert pc.get("_actor_idx") == 0, \
        f"do の実行フレームが発動者になっていない: _actor_idx={pc.get('_actor_idx')}"
    assert (hand, life) == (4, 1), \
        f"人間が選んだ選択肢どおりに解決していない: hand={hand} life={life}"

    # 発動者が人間 = 相手は AI → modal は立たず AI が相手最適で選ぶ
    pc2, _, _ = run(0)
    assert pc2 is None, "相手が AI なのに発動者へ modal が立っている"
def test_st31_002_include_stage_summons_a_stage_card():
    """ST31-002 ジンベエ 【登場時】: 素の 「カード…登場させる」 は ステージも 対象。

    一次情報 (db/faq/cardqa_st_31): 「この【登場時】効果で『ST31-005 サウザンド・サニー号』を
    登場させることはできますか？」 → 「はい、できます。」
    公式テキストは 「コスト1の特徴《麦わらの一味》を持つ**カード**1枚まで」 = キャラ限定でない為
    STAGE の サニー号 (ST31-005、 cost1・麦わらの一味) も 登場できる。

    是正前: play_from_hand が CHARACTER のみを候補にしていたので STAGE は silent no-op で
    登場できなかった (公式違反)。 include_stage flag で STAGE も候補+登場に含める。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST31-005")]  # STAGE、 cost1、 麦わらの一味
    jinbe = InPlay.of(repo.get("ST31-002"), sickness=True)
    me.characters.append(jinbe)
    trigger_on_play(st, me, opp, jinbe, overlay)
    assert [s.card.card_id for s in me.stages] == ["ST31-005"], (
        "ST31-002 の【登場時】で STAGE の サニー号 が 登場できていない "
        f"(stages={[s.card.card_id for s in me.stages]})"
    )
    # サニー号 は 手札から 場へ移った (draw:1 で引いた別カードは手札に残る)
    assert "ST31-005" not in [c.card_id for c in me.hand], "登場した サニー号 が 手札に残っている"


def test_eb03_048_places_dressrosa_stage_from_hand():
    """EB03-048 【登場時】後段: 「ステージカード1枚まで…登場させる」 は STAGE を 場に置く。

    是正前: overlay が play_from_hand (= CHARACTER 専用) を使っていたので STAGE が
    silent no-op で 置けなかった。 play_stage_from_hand へ是正。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # search 段が引く先 (デッキ上) と、 play 段が置く手札 の両方に ドレスローザ stage を置く
    me.deck = [repo.get("OP04-096")] + [repo.get(_FILLER)] * 24
    me.hand = [repo.get("OP04-096")]  # コリーダコロシアム、 ドレスローザ、 cost1
    eb = InPlay.of(repo.get("EB03-048"), sickness=True)
    me.characters.append(eb)
    trigger_on_play(st, me, opp, eb, overlay)
    assert [s.card.card_id for s in me.stages] == ["OP04-096"], (
        "EB03-048 が ドレスローザ stage を 場に置けていない "
        f"(stages={[s.card.card_id for s in me.stages]})"
    )


def test_play_from_hand_bare_card_summon_can_place_stage():
    """全走査ガード: 公式テキストが 素の 「…カード1枚まで(を)…登場させる」 (= キャラ限定でない)
    で、 かつ その filter に STAGE が一致しうる overlay は、 include_stage を持つ か
    play_stage_from_hand を使うこと (= STAGE を silent drop しない)。

    play_from_hand は CHARACTER 専用。 公式が 「キャラカード」 でなく 素の 「カード」 と書く
    登場効果 (= ST31-002 ジンベエ、 cardqa_st_31 で サニー号 STAGE 登場が 「はい」) は STAGE も
    対象なので、 include_stage 無しの play_from_hand だと STAGE が黙って登場できず違反になる。
    「キャラカード」 と書く効果は CHARACTER 専用が正しいので、 **公式テキスト** を判別子にする。
    """
    import json as _json
    import re as _re
    ov = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cards = {c["base_id"]: c for c in
             _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    repo = _repo()
    from engine.effects import _matches_filter
    stages = []
    seen = set()
    for c in cards.values():
        if c["category"] != "STAGE" or c["base_id"] in seen:
            continue
        seen.add(c["base_id"]); stages.append(repo.get(c["base_id"]))

    def _bare_card_summon(txt: str) -> bool:
        # 「…を、登場させる」 の直前の節に 「カード」 が有り 「キャラ」 が無い (= 素のカード)
        for m in _re.finditer(r"([^。]*?)を、?登場させる", txt or ""):
            seg = m.group(1)
            if "カード" in seg and "キャラ" not in seg:
                return True
        return False

    checked = 0
    bad = []
    for cid, effs in ov.items():
        if not isinstance(effs, list) or cid.startswith("_"):
            continue
        txt = (cards.get(cid, {}) or {}).get("text") or ""
        for e in effs:
            for prim in e.get("do", []) or []:
                if not (isinstance(prim, dict) and "play_from_hand" in prim):
                    continue
                spec = prim["play_from_hand"]
                if not isinstance(spec, dict):
                    continue
                checked += 1
                if spec.get("include_stage"):
                    continue
                if not _bare_card_summon(txt):
                    continue  # 「キャラカード」 = CHARACTER 専用が正しい
                filt = spec.get("filter", {}) or {}
                if any(isinstance(vv, str) and vv.endswith("_dynamic") for vv in filt.values()):
                    continue
                hit = next((s.card_id for s in stages if _matches_filter(s, filt)), None)
                if hit:
                    bad.append(f"{cid}: 素の「カード」登場 + filter={filt} が STAGE {hit} に一致 "
                               f"(include_stage 未指定 = STAGE を silent drop)")
    assert checked, "play_from_hand を持つ overlay が 0 = テストが空回り"
    assert not bad, (
        "公式が 素の「カード」登場 なのに STAGE を silent drop する play_from_hand:\n  "
        + "\n  ".join(bad)
    )


def test_st03_001_return_can_target_opponent_character():
    """ST03-001 クロコダイル 【起動メイン】: 「コスト5以下のキャラ1枚まで…**持ち主の**手札に
    戻す」 は 相手のキャラも 対象 (= 両陣営、 docs/official_rulings.md 「相手のなし=両陣営」)。

    一次情報 (db/faq/cardqa_st_03): 「この【起動メイン】効果で自分のキャラを手札に戻すことが
    できますか？」 → 「はい、戻すことができます。」 = 自分側も対象 = 修飾なし = 両陣営。
    「持ち主の手札に戻す」 と所有者を明示するのは どちらの側も対象になりうる為。

    是正前: overlay が `one_self_chara_filtered` (= 自分のみ) で、 除去カードなのに 相手キャラを
    バウンスできなかった (公式違反)。 `one_character_either_filtered` へ是正 (EB02-024 / OP05-059 /
    ST03-001 の 3 枚。 全走査ガード = scripts/audit_target_scope.py、 SELF_ONLY 正規表現に
    one_self_chara を追加して chara/character 綴りの穴を塞いだ)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("ST03-001"), sickness=False)
    me.characters.append(src)
    opp.characters.append(InPlay.of(repo.get("OP01-013"), sickness=False))  # 相手 cost2 キャラ
    from engine.effects import execute_effect
    execute_effect(
        {"return_to_hand": {"type": "one_character_either_filtered", "filter": {"cost_le": 5}}},
        st, me, opp, src,
    )
    assert len(opp.characters) == 0, "ST03-001 が 相手キャラを 手札に戻せていない (= 自分限定のまま)"
    assert len(opp.hand) == 1, "戻した相手キャラが 相手の手札に入っていない"


def test_op04_094_ko_cost_threshold_upgrades_with_trash_and_counts_self():
    """OP04-094 雷の破壊剣: 「コスト4以下をKO。 自分のトラッシュが15枚以上なら 代わりに
    コスト6以下を選ぶ」。 イベント自身も 発動時には トラッシュ済 (公式 8-4-2 の順)。

    一次情報 (db/faq/cardqa_op_04): 「自分のトラッシュが14枚の時にこの【メイン】効果を発動
    しました。 コスト6のキャラを選ぶことはできますか？」 → 「このカードを含めてトラッシュが
    15枚になり、 コスト6以下のキャラを選ぶことができます。」

    是正前: overlay が `do:[ko cost_le_4], if: trash>=15` = (a) trash<15 で 何もKOしない
    (base 効果消失) (b) trash>=15 でも cost6 でなく cost4 しかKOできない = 二重の公式違反。
    """
    import random
    import json as _json
    from engine.game import PlayEvent, apply_action
    repo, overlay = _repo(), _overlay()
    allc = [repo.get(c["base_id"]) for c in
            _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
            if c["category"] == "CHARACTER"]
    c6 = next(c for c in allc if c.cost == 6)
    c4 = next(c for c in allc if c.cost == 4)

    def _play(hand_trash_n, opp_char):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        me.don_active = 10
        me.trash = [repo.get(_FILLER)] * hand_trash_n
        me.hand = [repo.get("OP04-094")]
        opp.characters = [InPlay.of(opp_char, sickness=False)]
        apply_action(st, PlayEvent(hand_idx=0))
        return len(opp.characters), len(me.trash)

    # Q シナリオ: 手札発動前トラッシュ14 → イベント自身で15 → cost6 KO 可
    remain6, trash_after = _play(14, c6)
    assert trash_after == 15, f"イベント自身が トラッシュに入っていない (trash={trash_after})"
    assert remain6 == 0, "trash 14→15 で コスト6キャラを KO できていない (= 15以上upgrade 未動作)"
    # base 効果: trash<15 でも コスト4以下は KO できる
    remain4, _ = _play(5, c4)  # 発動後 trash=6 (<15)
    assert remain4 == 0, "trash<15 で コスト4キャラを KO できていない (= base 効果が消えている)"
    # trash<15 で コスト6キャラは 対象外
    remain6b, _ = _play(5, c6)  # 発動後 trash=6 (<15)
    assert remain6b == 1, "trash<15 なのに コスト6キャラを KO している (= upgrade が誤発火)"


def test_play_by_field_character_effect_vs_trigger_effect():
    """OP12-081 コアラ: 「**キャラの効果で**キャラを登場させた時」 = **場にあるキャラ** の効果のみ。

    一次情報 (cardqa_op_12): 「相手がキャラカードの【トリガー】効果で元々のコスト7以下の
    キャラを登場させた時、 この【ターン1回】効果は発動できますか？」 → 「**いいえ**。
    『場にあるキャラの効果』以外の効果によって…登場したときには…発動できません。
    そのため、 【トリガー】効果による…登場では発動できません。」

    ⚠ engine は Q&A の答え自体は満たしていたが、 それは overlay が **この分岐を丸ごと
      未実装だった** ため。 正しくは 「場のキャラの効果による登場では **発動する**」 が
      抜けており、 別の違反 (under-firing) だった。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_on_play

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def run(by_field_chara: bool):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP12-081"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        if by_field_chara:
            src = InPlay.of(repo.get("OP01-016"), sickness=False)
            p0.characters = [src]
            st._effect_source_ip = src
        else:
            st._effect_source_ip = None      # 【トリガー】効果 = 場のキャラの効果ではない
        ip = InPlay.of(repo.get("OP01-013"), sickness=True)   # cost2 (= 8 未満)
        p0.characters.append(ip)
        life_before = len(p0.life)
        trigger_on_play(st, p0, p1, ip, ov)
        return len(p0.life) < life_before

    assert run(True), "場のキャラの効果による登場で発動していない (= 分岐が未実装)"
    assert not run(False), \
        "【トリガー】効果による登場で発動している (公式=いいえ、 cardqa_op_12)"


def test_once_per_turn_is_not_consumed_when_the_optional_cost_is_declined():
    """⭐ **【ターン1回】は 「実際に発動した」 時だけ消費される**。

    一次情報 (cardqa_op_03): 「…手札2枚を捨てずにこの【自分のターン中】【ターン1回】効果を
    **発動しないことを選びました**。 そのターン中、 次に相手のキャラがKOされた時、
    この効果を発動することはできますか？」 → 「**はい、 できます。**」

    対照 (cardqa_op_02): 「できる」 が無い = **必ず発動** する効果は 「発動しないこと」 を
    選べない → 「いいえ、 可能な限り必ず発動します」。
    対照 (cardqa_prb02 / PRB02-004): 「N枚まで」 で 0 枚を選んでも **効果自体は発動している**
    ので 【ターン1回】 は消費される (= engine は元から conform)。

    ⚠ engine は **発動前に** 消費しており、 見送ると 1 回分を失っていた。 対象 59 枚
      (optional_cost_then + 【ターン1回】)。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, resolve_pending_choice
    from engine.game import legal_actions, apply_action

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def board():
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        st.human_player_idx = 0
        st.forced_human_actor_idx = 0
        p0.hand = [repo.get("OP01-013")] * 3
        p0.don_active = 5
        return st, p0, p1

    def n_acts(st):
        return len([a for a in legal_actions(st) if type(a).__name__ == "ActivateMain"])

    # 見送り → 消費されない
    st, _, _ = board()
    acts = [a for a in legal_actions(st) if type(a).__name__ == "ActivateMain"]
    assert acts, "起動メインが legal に出ていない"
    apply_action(st, acts[0])
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"任意コスト確認 modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])          # 見送る
    assert n_acts(st) >= 1, \
        "見送ったのに【ターン1回】が消費された (cardqa_op_03 違反)"

    # 承諾 → 消費される (= 対照。 これが崩れると 1 ターンに複数回撃ててしまう)
    st, _, _ = board()
    acts = [a for a in legal_actions(st) if type(a).__name__ == "ActivateMain"]
    apply_action(st, acts[0])
    resolve_pending_choice(st, [1])          # 払う
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    assert n_acts(st) == 0, "発動したのに【ターン1回】が消費されていない"


# --------------------------------------------------------------------------- #
#  公式 Q&A 全件保証 (2026-08-07): 効果KO免疫のキャラは 自KOコストの弾にできない
# --------------------------------------------------------------------------- #
def test_ko_self_chara_cost_excludes_effect_ko_immune_char():
    """OP05-087 ハクバ 【アタック時】「このキャラ以外の自分のキャラ1枚をKOできる：
    相手のキャラ1枚までを、このターン中、コスト-5。」

    一次情報 (cardqa_op_05, qid 4c7f708a98f4):
      Q「この【アタック時】効果で自分のキャラ1枚をKOするとき、自分の
        『OP03-088 フクロウ』(= このキャラは効果でKOされない) を選んだ場合はどうなりますか？」
      A「この場合、自分の『OP03-088 フクロウ』はKOされず、この【アタック時】効果で
        相手のキャラ1枚をコスト-5することはできません。」

    = 効果でKOされないキャラは 自KO **コスト** の弾にできない。 弾が居なければコスト未払い
      → 後段の -5 は起きない。 退行前は cost ループが免疫を無視して フクロウ をトラッシュ送りし、
      -5 も適用していた (Python/Rust とも同じ overlay を読むため差分検証では沈黙、公式オラクル
      でのみ検出)。 通常の ko primitive (effects.py:~3833) と同じ免疫則を cost 側にも適用。
    """
    repo, overlay = _repo(), _overlay()
    # (1) 弾が フクロウ (免疫) だけ → コスト払えず -5 も起きない
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    hakuba = InPlay.of(repo.get("OP05-087"), sickness=False)
    hakuba.attached_dons = 1                                   # if: self_attached_don_ge 1
    fukurou = InPlay.of(repo.get("OP03-088"), sickness=False)  # 効果でKOされない
    me.characters = [hakuba, fukurou]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    evaluate_static_effects(st, overlay)
    assert fukurou.static_ko_immune is True, "フクロウの静的KO耐性が立っていない (前提)"
    trigger_on_attack(st, me, opp, hakuba, overlay)
    assert fukurou in me.characters, "免疫の フクロウ が自KOコストで KO された (cardqa_op_05 違反)"
    assert not any(c.card_id == "OP03-088" for c in me.trash), "フクロウ がトラッシュに送られている"
    assert victim.cost_minus_until_turn_end == 0, \
        "弾が免疫キャラだけでコスト未払いなのに -5 が適用された (タダ撃ち)"

    # (2) 対照: 免疫でないキャラが弾なら KO され -5 も適用される
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    hakuba2 = InPlay.of(repo.get("OP05-087"), sickness=False)
    hakuba2.attached_dons = 1
    fodder = InPlay.of(repo.get(_FILLER), sickness=False)      # 免疫なし
    me2.characters = [hakuba2, fodder]
    victim2 = InPlay.of(repo.get(_FILLER), sickness=False)
    opp2.characters = [victim2]
    evaluate_static_effects(st2, overlay)
    trigger_on_attack(st2, me2, opp2, hakuba2, overlay)
    assert fodder not in me2.characters, "免疫でない弾が KO されていない (対照が壊れている)"
    assert victim2.cost_minus_until_turn_end == 5, "コストを払ったのに -5 が適用されていない"

    # 全走査: ko_self_chara を **コスト** に持つカードの網羅 (この修正の適用範囲を固定)。
    import json as _json
    ov = _json.load(open(ROOT / "db" / "card_effects.json"))
    def _walk(o):
        if isinstance(o, dict):
            yield o
            for vv in o.values():
                yield from _walk(vv)
        elif isinstance(o, list):
            for vv in o:
                yield from _walk(vv)
    cost_cards = set()
    for cid, node in ov.items():
        for d in _walk(node):
            oct_ = d.get("optional_cost_then")
            if isinstance(oct_, dict):
                for c in (oct_.get("cost") or []):
                    if isinstance(c, dict) and "ko_self_chara" in c:
                        cost_cards.add(cid)
            c2 = d.get("cost")
            if isinstance(c2, list):
                for x in c2:
                    if isinstance(x, dict) and "ko_self_chara" in x:
                        cost_cards.add(cid)
    assert "OP05-087" in cost_cards and len(cost_cards) >= 10, \
        f"ko_self_chara-as-cost の網羅が想定外 (現状 {len(cost_cards)} 件): {sorted(cost_cards)}"


# ---------------------------------------------------------------------------
# 「登場できない」 ペナルティは **効果による登場も** 禁止する (2026-08-08、 cardqa_op_13)
#
# 一次情報 (OP13-023 ウタ、 qid 52c406ba1a7b):
#   「この【登場時】効果を発動したターン中にこのキャラがKOされた場合、この【KO時】効果で
#    自分の手札からコストが5のキャラを登場させることはできますか？」 → 「いいえ、できません。」
# = 登場時に付与した 「元々のコスト5以上のキャラカードを登場できない」 (block_chara_play_cost_ge:5)
#   は、 同ターンの【KO時】play_from_hand (コスト5以下) にも効き、 コスト5は登場できない。
# 是正前は play_from_hand 等の効果登場が block_chara_play_cost_ge_threshold /
# block_chara_play_until_turn_end を一切見ておらず、 タダで登場していた (Python/Rust 同型)。
# ---------------------------------------------------------------------------
def test_char_summon_blocked_by_cost_ge_restriction_via_play_from_hand():
    import random as _r
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    import json as _j
    cards = _j.load(open(ROOT / "db" / "cards.json"))
    c5 = next(c["card_id"] for c in cards
              if c.get("category") == "CHARACTER" and str(c.get("cost")) == "5" and "_" not in c["card_id"])
    c4 = next(c["card_id"] for c in cards
              if c.get("category") == "CHARACTER" and str(c.get("cost")) == "4" and "_" not in c["card_id"])

    def _mk():
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 12
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=_r.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        return st, p0, p1

    # 制限あり: 元々のコスト5以上は登場できない (OP13-023 の登場時ペナルティ相当)
    st, p0, p1 = _mk()
    execute_effect({"block_chara_play_cost_ge": 5}, st, p0, p1, None)
    p0.hand = [repo.get(c5), repo.get(c4)]
    execute_effect({"play_from_hand": {"filter": {"truly_original_cost_le": 5}, "limit": 1, "rested": True}},
                   st, p0, p1, None)
    played = [c.card.card_id for c in p0.characters]
    assert c5 not in played, "コスト5は 「元々のコスト5以上を登場できない」 で登場できないはず (公式いいえ)"
    assert c4 in played, "コスト4は制限外なので登場できるはず"

    # 対照: 制限が無ければ コスト5 も登場できる (旧挙動 = 制限を見ていなかった時と一致)
    st, p0, p1 = _mk()
    p0.hand = [repo.get(c5)]
    execute_effect({"play_from_hand": {"filter": {"truly_original_cost_le": 5}, "limit": 1, "rested": True}},
                   st, p0, p1, None)
    assert c5 in [c.card.card_id for c in p0.characters], "制限が無ければ コスト5 は登場できる"

    # block_chara_play_until_turn_end (OP14-020 ミホーク型): 全キャラの効果登場を止める
    st, p0, p1 = _mk()
    p0.block_chara_play_until_turn_end = True
    p0.hand = [repo.get(c4)]
    execute_effect({"play_from_hand": {"filter": {"truly_original_cost_le": 9}, "limit": 1, "rested": True}},
                   st, p0, p1, None)
    assert c4 not in [c.card.card_id for c in p0.characters], \
        "「キャラカードを登場できない」 は効果登場も全て止める (OP14-020)"


def test_simultaneous_ko_replacement_is_order_independent():
    """OP10-032 たしぎ: **同時KO** の置換は iteration 順に依存しない。

    一次情報 (cardqa_op_10): 「アクティブのこのキャラと、 これ以外の自分の緑のキャラが
    **同時にKOされるとき**、 この効果で代わりにこのキャラをレストにできますか？」
    → 「**はい、 できます。** この場合、 この自分の緑のキャラはKOされず、
      「たしぎ」 はKOされます。」

    ⚠ 是正前は **たしぎを先に処理すると** たしぎが場を離れた後で緑キャラを見るため
      holder が見つからず **両方KO** になっていた (= 盤面上の並び順で結果が変わる)。
      同時離脱は 1 事象なので、 置換の可否は **バッチ開始時の盤面** で決める。
    ⚠ `ko` (all_* target) も同時離脱 primitive。 これを集合から外していたのが原因だった。
    """
    import json
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    cards = {c["card_id"]: c
             for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    green = next(cid for cid, c in cards.items()
                 if c["category"] == "CHARACTER" and "緑" in (c.get("color") or "")
                 and c["name"] != "たしぎ" and str(c.get("power")) == "3000"
                 and not cid.endswith(("_p1", "_p2", "_r1")))

    def run(tashigi_first: bool):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        t = InPlay.of(repo.get("OP10-032"), sickness=False)
        g = InPlay.of(repo.get(green), sickness=False)
        p1.characters = [t, g] if tashigi_first else [g, t]
        src = InPlay.of(repo.get("OP01-016"), sickness=False)
        p0.characters = [src]
        execute_effect({"ko": "all_opponent_characters"}, st, p0, p1, src)
        return (t in p1.characters, g in p1.characters)

    for first in (False, True):
        tashigi_alive, green_alive = run(first)
        label = "たしぎ先" if first else "緑先"
        assert not tashigi_alive, f"{label}: たしぎは KO されるはず (自身は置換対象外)"
        assert green_alive, (
            f"{label}: 緑キャラは置換で残るはず (順序依存になっている)"
        )


def test_eb02_019_conditional_chara_rush_reevaluated_at_attack_time():
    """EB02-019 ロロノア・ゾロ: 「相手のキャラが2枚以上いる場合、 このキャラは登場した
    ターンにキャラへアタックできる」。

    一次情報 (db/faq/cardqa_eb_02): 「相手のキャラが2枚いるときにこのキャラを登場し、
    その後他の効果で相手のキャラが1枚になりました。 この場合、 このキャラは相手のキャラに
    アタックできますか？」 → 「**いいえ、 できません。**」
    = 登場時の判定を保持するのではなく **アタック時点で毎回判定** する。

    従って 静的効果 (static_self_attack_chara_if) として static_granted_keywords に
    付与し、 _recompute_static ごとに再評価されなければならない。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, evaluate_static_effects
    from engine.game import legal_actions, AttackCharacter, AttackLeader

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def build(n_opp: int):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 10
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        # 登場したばかり (召喚酔い) の ゾロ
        zoro = InPlay.of(repo.get("EB02-019"), sickness=True)
        p0.characters = [zoro]
        for _ in range(n_opp):
            c = InPlay.of(repo.get("OP01-013"), sickness=False)
            c.rested = True  # アタック対象になれるのは レスト のキャラのみ
            p1.characters.append(c)
        evaluate_static_effects(st, ov)
        return st, zoro

    def counts(st, zoro):
        acts = legal_actions(st)
        ch = [a for a in acts
              if isinstance(a, AttackCharacter) and a.attacker_iid == zoro.instance_id]
        ld = [a for a in acts
              if isinstance(a, AttackLeader) and a.attacker_iid == zoro.instance_id]
        return len(ch), len(ld)

    # 相手キャラ 1 枚 = 条件未達 → 召喚酔いのまま アタック不可
    st, zoro = build(1)
    assert not zoro.is_rush_chara_only_now
    assert counts(st, zoro) == (0, 0)

    # 相手キャラ 2 枚 = 条件達成 → **キャラへのみ** アタック可 (リーダーへは不可)
    st, zoro = build(2)
    assert zoro.is_rush_chara_only_now
    n_chara, n_leader = counts(st, zoro)
    assert n_chara == 2, f"相手キャラ 2 枚全てを狙えるはず (got {n_chara})"
    assert n_leader == 0, "速攻：キャラ はリーダーへアタックできない"

    # 2 枚 → 1 枚に減った後は アタック不可 に戻る (cardqa_eb_02 そのもの)
    st, zoro = build(2)
    st.players[1].characters.pop()
    evaluate_static_effects(st, ov)
    assert not zoro.is_rush_chara_only_now, (
        "相手キャラが 1 枚に減ったらアタック不可に戻るはず (cardqa_eb_02)"
    )
    assert counts(st, zoro) == (0, 0)


def test_op08_046_own_departure_to_public_zone_fires_its_leave_trigger():
    """OP08-046 シャクヤク: 【自分のターン中】【ターン1回】キャラが自分の効果で場を離れた時…

    一次情報 (db/faq/cardqa_op_08): 「このキャラが自分の効果で場を離れたとき、
    この【自分のターン中】効果は発動できますか？」 →
    「この場合、 **このキャラがトラッシュに置かれた時か、 ライフに表向きで置かれた時**、
    この【自分のターン中】効果を発動できます。」

    = 離脱した **本人** も反応する。 ただし行き先が **公開領域** (トラッシュ / 表向きライフ)
    の時だけで、 手札 / デッキ (= 非公開) へ戻った場合は発動しない。

    engine の _enqueue_field_when は離脱 **後** の盤面を走査するので本人を含まない。
    _note_public_departure の台帳で補う (effects.py)。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def run(prim):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 20
            p.life = [repo.get("OP01-013")] * 3
        p1.hand = [repo.get("OP01-013")] * 6      # 「相手の手札が5枚以上」 条件を満たす
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5   # 【自分のターン中】
        shakuyaku = InPlay.of(repo.get("OP08-046"), sickness=False)
        src = InPlay.of(repo.get("OP01-016"), sickness=False)
        p0.characters = [shakuyaku, src]
        before = (len(p1.hand), len(p1.deck))
        execute_effect(prim, st, p0, p1, src)
        after = (len(p1.hand), len(p1.deck))
        # 発動すると 「相手は自身の手札1枚をデッキの下に置く」 = 手札-1 / デッキ+1
        return (after[0] - before[0], after[1] - before[1])

    # 自身がトラッシュ (= 公開領域) へ → 発動できる
    assert run({"other_self_charas_to_trash": True}) == (-1, 1), (
        "シャクヤク自身がトラッシュへ置かれた場合は発動できるはず (cardqa_op_08)"
    )
    # 自身が手札 (= 非公開領域) へ戻る → 発動できない
    assert run({"return_to_hand": "all_self_characters"}) == (0, 0), (
        "手札へ戻った場合は発動できないはず (公式は トラッシュ / 表向きライフ のみ)"
    )
# --------------------------------------------------------------------------- #
#  公式 Q&A conformance バッチ (2026-08-08、 faq_qa_manifest)
# --------------------------------------------------------------------------- #
def test_op16_084_activate_main_requires_self_cost_ge_20():
    """OP16-084 光月モモの助: 【起動メイン】は **このキャラの現在コストが20以上** の時のみ発動可。

    一次情報 (cardqa_op_16, qid 57ce5506a587):
      Q: このキャラのコストが19以下の時に、この【起動メイン】でこのキャラをトラッシュに
         置くことはできますか？
      A: いいえ、できません。この場合、コスト9の「光月モモの助」を登場させることもできません。
    → 「コスト20以上の…トラッシュに置くことができる」 の 「コスト20以上」 はコロン前=コスト節。
       印刷コスト<20 なので OP16-087 しのぶ 等で現在コスト20以上にした時のみ発動できる。
    """
    repo, overlay = _repo(), _overlay()
    # 印刷コスト5 (<20) → 起動メインが legal に出ない (= トラッシュできない)
    st = _state(repo, overlay)
    me = st.players[0]
    momo = InPlay.of(repo.get("OP16-084"), sickness=False)
    me.characters = [momo]
    me.don_active = 10
    me.trash = [repo.get("OP06-107")]
    ams = [(ip, e) for ip, e in list_activate_main_effects(st, me, overlay) if ip is momo]
    assert len(ams) == 0, "コスト19以下でも起動メインが legal に出ている (= 自身をトラッシュできてしまう)"

    # 現在コスト25 (>=20) + 場のドン9以上 → 発動でき、自身がトラッシュへ
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    momo = InPlay.of(repo.get("OP16-084"), sickness=False)
    momo.base_cost_override = 25
    me.characters = [momo]
    me.don_active = 10
    me.trash = [repo.get("OP06-107")]
    ams = [(ip, e) for ip, e in list_activate_main_effects(st, me, overlay) if ip is momo]
    assert len(ams) == 1, "現在コスト20以上なら起動メインは発動できるべき"
    fire_activate_main(st, me, opp, momo, ams[0][1])
    from engine.effects import _maybe_resolve
    _maybe_resolve(st)
    assert momo not in me.characters, "コスト20以上ならコスト(自身トラッシュ)を払える"


def test_op16_074_don_minus_opp_returns_rested_don_first():
    """OP16-074 マゼラン: 「相手は自身の場のドン!!を戻す」 は 持ち主 (相手) が選ぶ = レストから返す。

    一次情報 (cardqa_op_16, qid 59c4ab538c2d):
      Q: このキャラの効果で戻す相手のドン!!は、どちらのプレイヤーが選びますか？
      A: デッキに戻すドン!!の持ち主である相手が選びます。
    → 相手はアクティブのドン (このターンまだ使える / カウンター支払いに要る) を温存し、
       レストのドンから返す (return_opp_don と同じ chooser 帰属)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 3
    opp.don_rested = 3
    remain_before = opp.don_remaining_in_deck
    execute_effect({"don_minus_opp": 1}, st, me, opp, None)
    assert opp.don_rested == 2, f"レストのドンから返していない (rested={opp.don_rested})"
    assert opp.don_active == 3, f"アクティブのドンを温存できていない (active={opp.don_active})"
    assert opp.don_remaining_in_deck == remain_before + 1

    # レストが尽きたらアクティブから (足りない分)
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 4
    opp.don_rested = 1
    execute_effect({"don_minus_opp": 3}, st, me, opp, None)
    assert opp.don_rested == 0 and opp.don_active == 2, \
        f"レスト優先→不足分アクティブ が守れていない (active={opp.don_active} rested={opp.don_rested})"


# --------------------------------------------------------------------------- #
#  公式 Q&A conformance バッチ (2026-08-08 #2、 cron optcg-faq-conformance)
# --------------------------------------------------------------------------- #
def test_op15_023_don_attach_targets_both_players_owner_matched():
    """OP15-023 アーロン【起動メイン】「リーダーかキャラ1枚に持ち主のコストエリアのドン付与」
    は 両陣営 が対象で、 ドン源は 対象の所有者 (= owner_of_target)。

    一次情報 (cardqa_op_15):
      #9 (qid 5b454d23df75): 「自分に自分のドン / 相手に相手のドン を付与できるか」→ はい。
      #17 (qid 5cf7f863bc3a): 「自分に相手のドン / 相手に自分のドン (cross) を付与できるか」→ いいえ。
    OP15-003/010/017 の レストドン是正 (2026-08-06) が この コストエリア variant を取りこぼしていた
    (target=self_inplay_choice = 自陣限定 = 相手に付与できず #9 違反)。one_team_any_either +
    owner_of_target へ是正 (from_cost_area は据置)。
    """
    from engine.core import InPlay
    repo, overlay = _repo(), _overlay()

    # #9: 相手のキャラに 相手のコストエリアのドン を付与できる (両陣営)
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    aaron = InPlay.of(repo.get("OP15-023"), sickness=False)
    me.characters = [aaron]
    oppc = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [oppc]
    opp.don_rested, opp.don_active, me.don_rested = 2, 0, 3
    spec = {"attach_rested_don": {
        "target": {"_iid_picks": [oppc.instance_id]},
        "count": 1, "from_cost_area": True, "owner_of_target": True}}
    execute_effect(spec, st, me, opp, aaron)
    assert oppc.attached_dons == 1, "相手キャラに付与できていない (両陣営 #9 違反)"
    assert opp.don_rested == 1, "ドン源が相手のコストエリアでない (owner_of_target 違反)"
    assert me.don_rested == 3, "cross: 自分のドンが減った (owner_of_target が cross を許した #17 違反)"

    # #17: 自陣キャラへ付与すると 自分のコストエリアのドン から取る (cross 不可)
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    aaron = InPlay.of(repo.get("OP15-023"), sickness=False)
    myc = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [aaron, myc]
    me.don_rested, me.don_active, opp.don_rested = 2, 0, 3
    spec = {"attach_rested_don": {
        "target": {"_iid_picks": [myc.instance_id]},
        "count": 1, "from_cost_area": True, "owner_of_target": True}}
    execute_effect(spec, st, me, opp, aaron)
    assert myc.attached_dons == 1, "自陣キャラに付与できていない"
    assert me.don_rested == 1, "ドン源が自分のコストエリアでない"
    assert opp.don_rested == 3, "cross: 相手のドンが減った (owner_of_target が cross を許した #17 違反)"


def test_op15_105_simultaneous_leave_pays_replacement_cost_once():
    """OP15-105 ボニー / OP15-098 ルフィ / OP15-090 ペローナ:
    「自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、 代わりに
     自分のライフの上から1枚を手札に加えることができる。」

    一次情報 (db/faq/cardqa_op_15):
      Q: 元々のパワー7000以下のキャラが **2枚同時に** 相手の効果で場を離れる場合、
         代わりに自分のライフの上から **2枚** を手札に加えることはできますか？
      A: この場合、 自分のライフの上から **1枚** を手札に加えることで場を離れるキャラを
         **2枚とも** 場に残すか、 何もせずキャラ2枚が場を離れるかを選びます。

    = 同時離脱は 1 事象なので **支払いは 1 回** で全員残る。

    ⚠ engine の同時離脱 dedup (_LeaveBatch) は **cost フィールドしか** dedup しない。
      この 3 枚は支払いを `do` に持っていたので victim ごとに払っていた (2枚 = ライフ2消費)。
      → 支払いを cost へ移し、 life_to_hand を replace-cost handler 化して是正。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def run(n_victims: int):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 20
            p.life = [repo.get("OP01-013")] * 4
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 1, 5      # 相手のターン = 相手の効果で離脱
        holder = InPlay.of(repo.get("OP15-105"), sickness=False)
        p0.characters = [holder]
        victims = []
        for _ in range(n_victims):
            v = InPlay.of(repo.get("OP01-013"), sickness=False)   # 元々パワー 7000 以下
            p0.characters.append(v)
            victims.append(v)
        src = InPlay.of(repo.get("OP01-016"), sickness=False)
        p1.characters = [src]
        life_before, hand_before = len(p0.life), len(p0.hand)
        execute_effect({"ko": "all_opponent_characters"}, st, p1, p0, src)
        return (
            life_before - len(p0.life),                       # 消費したライフ枚数
            len(p0.hand) - hand_before,                        # 手札に加わった枚数
            sum(1 for v in victims if v in p0.characters),     # 生存した victim 数
        )

    for n in (1, 2, 3):
        life_paid, hand_gained, survived = run(n)
        assert life_paid == 1, (
            f"victim {n} 枚でもライフ支払いは 1 回のはず (実測 {life_paid}、 cardqa_op_15)"
        )
        assert hand_gained == 1, f"手札に加わるのも 1 枚のはず (実測 {hand_gained})"
        assert survived == n, f"支払えば victim {n} 枚とも残るはず (実測 {survived})"


def test_op14_029_rest_self_cards_covers_four_zones():
    """OP14-029 たしぎ 【起動メイン】「自分のカード2枚をレストにできる：…」

    一次情報 (db/faq/cardqa_op_14):
      Q: この【起動メイン】効果の「自分のカード2枚をレストにできる」とは、 どのカードを
         レストにする効果ですか？
      A: この効果は、 自分の場にある、 **リーダー、 キャラ、 ステージ、 ドン!!** のうち
         **合計2枚** をアクティブからレストにすることで発動します。

    ⚠ engine の rest_self_cards は leader + characters しか候補にしておらず、
      ステージ / ドンで払える局面を弾いて **合法な発動を阻害** していた。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def run(extra_chars: int, don_active: int):
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 20
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        p0.leader.rested = True                     # リーダーはレスト済 = 候補外
        tashigi = InPlay.of(repo.get("OP14-029"), sickness=False)
        p0.characters = [tashigi]
        for _ in range(extra_chars):
            p0.characters.append(InPlay.of(repo.get("OP01-013"), sickness=False))
        p0.don_active = don_active
        power_before = tashigi.power
        execute_effect(
            {"optional_cost_then": {
                "cost": [{"rest_self_cards": 2}],
                "effect": [{"power_pump": {"target": "self", "amount": 2000,
                                           "duration": "turn"}}]}},
            st, p0, p1, tashigi,
        )
        return tashigi.power > power_before, p0.don_active, p0.don_rested

    # 場のキャラだけで足りる → 従来どおりキャラをレスト、 ドンは減らない
    fired, don_a, don_r = run(extra_chars=3, don_active=0)
    assert fired and don_a == 0 and don_r == 0

    # アクティブなキャラが たしぎ 1 枚のみ → **ドンで不足分を払えるので発動できる**
    fired, don_a, don_r = run(extra_chars=0, don_active=5)
    assert fired, "ドンで払えるので発動できるはず (cardqa_op_14)"
    assert (don_a, don_r) == (4, 1), f"不足 1 枚をドンで払うはず (active={don_a} rested={don_r})"

    # 場のカード + ドン の合計が 2 未満 → 払えないので発動しない
    fired, _, _ = run(extra_chars=0, don_active=0)
    assert not fired, "合計 1 枚しか無いので払えない = 発動しないはず"


def test_op08_105_opp_life_taken_fires_when_owner_moves_own_life():
    """OP08-105 ボニー: 【ドン‼×1】【自分のターン中】【ターン1回】相手のライフが離れた時、…

    一次情報 (db/faq/cardqa_op_08):
      Q: 自分のターン中に、 **相手が効果でライフを1枚手札に加え**、 その後カードを
         ライフの上に加えました。 この時、 この【自分のターン中】効果でカード2枚を引き、
         手札1枚を捨てることはできますか？   A: **はい、 できます。**

    = 「相手のライフが離れた時」 は **離れ方を問わない**。 engine は 「自分が相手のライフを
      取り除く」 経路にしか on_opp_life_taken を配線しておらず、 **持ち主が自分でライフを
      手札へ移す** 経路では観測側が発火しなかった。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 20
        p.life = [repo.get("OP01-013")] * 4
    p0.hand = [repo.get("OP01-013")] * 2
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=ov)
    st.turn_player_idx, st.turn_number = 0, 5      # 自分 (P0) のターン
    bonney = InPlay.of(repo.get("OP08-105"), sickness=False)
    bonney.attached_dons = 1                       # 【ドン‼×1】
    p0.characters = [bonney]
    src = InPlay.of(repo.get("OP01-016"), sickness=False)
    p1.characters = [src]

    deck_before = len(p0.deck)
    # 相手 (P1) が **自分の** ライフを手札に加える
    execute_effect({"life_to_hand": 1}, st, p1, p0, src)
    assert deck_before - len(p0.deck) == 2, (
        "相手が自ライフを手札に加えた時も 「相手のライフが離れた時」 = 2 枚ドローするはず"
    )


def test_op10_030_lock_blocks_scheduled_untap_don():
    """OP10-030 スモーカー: 「自分はこのターン中、 キャラの効果でドン‼をアクティブにできない。」

    一次情報 (db/faq/cardqa_eb_02 + cardqa_st_24):
      Q: スモーカーの【起動メイン】を起動したターンの終了時、 (EB02-015 ボニー /
         ST24-005 ドレークの)【登場時】効果でドン!!1枚をアクティブにできますか？
      A: **いいえ、 できません。**

    = ターン終了時に予約された untap_don も 「**キャラの効果**」 なのでロックの対象。
      engine は予約効果の flush を self_inplay=None で実行しており、 gate
      (発動元がキャラか) が通らず 公式違反になっていた。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, execute_effect, trigger_end_of_turn

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def run(locked: bool) -> int:
        p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 20
            p.life = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 0, 5
        bonney = InPlay.of(repo.get("EB02-015"), sickness=False)   # キャラ
        p0.characters = [bonney]
        p0.don_rested, p0.don_active = 3, 0
        # 【登場時】後半 = 「このターン終了時、 自分のドン‼1枚までを、 アクティブにする」
        execute_effect({"schedule_at_self_turn_end": {"do": [{"untap_don": 1}]}},
                       st, p0, p1, bonney)
        if locked:
            p0.block_chara_effect_untap_don_until_turn_end = True
        trigger_end_of_turn(st, ov)
        return p0.don_active

    assert run(locked=False) == 1, "ロックが無ければ予約どおりドン1枚アクティブ"
    assert run(locked=True) == 0, (
        "スモーカーのロック中は **キャラの効果** の予約 untap_don も不発のはず "
        "(cardqa_eb_02 / cardqa_st_24)"
    )


def test_op12_057_trigger_discard_feeds_navy_leader_draw():
    """OP12-057 アイス塊暴雉嘴 (青/特徴《海軍》 event) の【トリガー】
    「自分の手札1枚を捨てることができる：カード1枚を引く。」

    一次情報 (db/faq/cardqa_op_12):
      Q: この【トリガー】効果で手札を1枚捨てカード1枚を引いた時、 自分のリーダー
         「クザン」 (= OP12-040、 特徴《海軍》/ 「自分の特徴《海軍》を持つカードの効果で
         自分の手札からカードが捨てられた時、 捨てた枚数分カードを引く」) の効果で
         さらにカード1枚を引くことはできますか？   A: **はい、 できます。**

    ⚠ 2 段の欠陥があった:
      1. 発動元がイベント (= InPlay を持たない) なので actor_source_feature_contains が
         source を掴めない → CardDef 由来の特徴に fallback。
      2. **より深い原因**: trigger_on_self_hand_discarded が context (捨てた枚数 / 発動元)
         を _maybe_resolve の直後に消していた。 ネスト中 (既に resolving) の _maybe_resolve は
         **drain せずに返る** ので、 クザンの効果が実際に解決される頃には
         last_discard_count=0 になっており、 条件が真でも 0 枚ドローだった。
         → on_ko の by_opp_effect と同じく **payload で持ち回る** 方式に統一。
    """
    import random
    from engine.core import GameState, InPlay, Phase, Player
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay, trigger_lifecard_trigger

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    def run(leader_id: str) -> int:
        p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
        p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        for p in (p0, p1):
            p.deck = [repo.get("OP01-013")] * 25
            p.life = [repo.get("OP01-013")] * 3
        p0.hand = [repo.get("OP01-013")] * 3
        st = GameState(players=[p0, p1], phase=Phase.MAIN,
                       rng=random.Random(1), effects_overlay=ov)
        st.turn_player_idx, st.turn_number = 1, 5    # 相手のターン (= ライフを取られた側)
        deck_before = len(p0.deck)
        trigger_lifecard_trigger(st, p0, p1, repo.get("OP12-057"), ov)
        return deck_before - len(p0.deck)

    assert run("OP12-040") == 2, (
        "海軍リーダー クザン なら トリガーの1枚 + クザンの1枚 = 2枚 引くはず (cardqa_op_12)"
    )
    assert run("OP01-001") == 1, "非海軍リーダーなら トリガーの1枚だけ"


def test_activate_main_cost_ko_trigger_fires_after_the_effect():
    """発動コストの支払いで誘発した【KO時】は **本体を解決した後** に発動する。

    一次情報 (cardqa_op_14、 OP14-080 ゲッコー・モリア):
      Q「この【起動メイン】効果でKOした自分のキャラが【KO時】効果を持っていた場合、
        それは発動できますか？」
      A「はい、できます。この場合、『自分のリーダーとキャラすべてを、このターン中、
        パワー+1000。』を **実行した後で**、そのキャラの【KO時】効果が発動します。」

    公式 8-4-1-3〜8-4-1-5 (コスト支払い → 発動 → 解決) の順序。 engine は コスト支払い中の
    enqueue を即ドレインしており **順序が逆** だった (= 【KO時】で登場したキャラまで +1000 を
    受けていた)。 _cost_trigger_buffer で本体 enqueue の後にコスト由来を流すよう是正。

    観測点: KO時 (OP14-110 ホグバック) がトラッシュから登場させたキャラが +1000 を **受けない**
    (= パワー加算は既に解決済)。 ※【起動メイン】の +1000 が 「発動時点のキャラのみ」 の
    スナップショットであることは docs/official_rulings.md に既記載。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP14-080")   # ゲッコー・モリア
    me, opp = st.players[0], st.players[1]
    hogback = InPlay.of(repo.get("OP14-110"), sickness=False)  # 特徴 スリラーバーク海賊団 + 【KO時】登場
    me.characters = [hogback]
    me.trash = [repo.get("OP14-102")]                # クマシー (cost1/2000、【トリガー】持ち = 登場候補)

    source, eff = list_activate_main_effects(st, me, overlay)[0]
    fire_activate_main(st, me, opp, source, eff)

    assert me.leader.power == 6000, "リーダーが +1000 を受けていない (本体が解決していない)"
    assert [c.card.card_id for c in me.characters] == ["OP14-102"], \
        "【KO時】でトラッシュのクマシーが登場していない"
    assert me.characters[0].power == 2000, (
        "コスト由来の【KO時】で登場したキャラが +1000 を受けている = "
        "【KO時】が本体より先に解決している (cardqa_op_14 / OP14-080 違反)"
    )


def test_activate_main_cost_ko_trigger_order_survives_human_modal():
    """同上 (cardqa_op_14) を **人間のコスト対象選択 modal を跨いで** 保証する。

    コスト由来トリガーの退避バッファは 「モーダルで中断 → 選択 → 再入」 を跨いで生き残る
    必要がある (= 過去の実装試行が繰り返し落ちた経路)。 閉じ忘れると 全トリガーが止まり、
    早く閉じると 【KO時】 が本体より先に解決する。

    観測点: 発動時に場に居た キャラ は +1000 を受け、 【KO時】 で **後から登場した** キャラは
    受けない。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP14-080", human_idx=0)
    me, opp = st.players[0], st.players[1]
    hogback = InPlay.of(repo.get("OP14-110"), sickness=False)
    kumacy = InPlay.of(repo.get("OP14-102"), sickness=False)   # 特徴 スリラーバーク海賊団 = KO 候補にもなる
    me.characters = [hogback, kumacy]
    me.trash = [repo.get("OP14-102")]

    source, eff = list_activate_main_effects(st, me, overlay)[0]
    fire_activate_main(st, me, opp, source, eff)
    assert st.pending_choice is not None, "候補 2 枚なのに人間の自KO対象 modal が出ていない"
    assert st.pending_choice["cost_kind"] == "ko_self_with_filter"

    resolve_pending_choice(st, [0])   # ホグバック を KO 対象に選ぶ

    assert st.pending_choice is None
    assert not st.event_queue, "トリガーキューが残っている (= バッファを閉じ忘れ)"
    assert me.leader.power == 6000
    powers = [c.power for c in me.characters]
    assert powers == [3000, 2000], (
        f"powers={powers}: 発動時に居たキャラは 2000+1000、【KO時】で登場したキャラは素の 2000 "
        f"のはず (cardqa_op_14 / OP14-080)"
    )
# --------------------------------------------------------------------------- #
#  同時離脱の置換コスト (return_self_don_to_deck) は 1 回だけ (2026-08-08)
#     ⚠ 公式 cardqa_op_15 (OP15-069 ノラ):
#       Q「自分の元々のパワー7000以下のキャラが2枚同時に相手の効果で場を離れる場合、
#         代わりに自分のドン!!2枚をドン!!デッキに戻すことはできますか？」
#       A「この場合、自分のドン!!1枚をドン!!デッキに戻すことでこの場を離れるキャラを2枚とも
#         場に残すか、何もせずキャラ2枚が場を離れるかを選びます。」
#     = 同時離脱は 1 事象なので置換コストは holder ごとに 1 回。 payment を do に置くと
#       victim ごとに走って 2 枚払う (= 違反)。 cost に置いて batch dedup を効かせる。
#     旧 overlay は return_self_don_to_deck を do に持っていた (= 2 枚返す bug)。
# --------------------------------------------------------------------------- #
def test_op15_069_nora_simultaneous_leave_returns_one_don():
    """OP15-069 ノラ: 自元々パワー7000以下キャラが2枚同時に相手効果で離れても、
    返すドンは 1 枚だけで 2 枚とも救う (公式 cardqa_op_15)。"""
    from engine.effects import try_replace_ko, _LeaveBatch

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    nora = InPlay.of(repo.get("OP15-069"), sickness=False)      # holder (power2000)
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)         # サンジ power3000 (<=7000)
    v2 = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [nora, v1, v2]
    me.don_active = 3
    don_active_before = me.don_active
    don_deck_before = me.don_remaining_in_deck

    with _LeaveBatch(st):
        r1 = try_replace_ko(st, me, opp, v1, overlay, by_opp_effect=True, leave_kind="ko")
        r2 = try_replace_ko(st, me, opp, v2, overlay, by_opp_effect=True, leave_kind="ko")

    assert r1 is True and r2 is True, "2 枚とも置換で救われるべき (ドンがあれば)"
    assert me.don_active == don_active_before - 1, (
        f"返したドンは 1 枚のはず (2 枚同時離脱でも 1 回払い)。 実際 {don_active_before - me.don_active} 枚"
    )
    assert me.don_remaining_in_deck == don_deck_before + 1, "ドンデッキに戻ったのは 1 枚のはず"


def test_no_multivictim_replace_pays_consumable_don_in_do():
    """overlay 全走査: return_self_don_to_deck (= 消費リソースの置換コスト) は、 複数 victim を
    救いうる holder (target が self でない = other_self_chara / any_self_chara) では **必ず cost に
    置く**。 do に置くと同時離脱で victim ごとに払う (= cardqa_op_15 違反)。"""
    raw = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    offenders = []
    for cid, effs in raw.items():
        if not isinstance(effs, list):
            continue
        for e in effs:
            if e.get("when") not in ("replace_ko", "replace_leave"):
                continue
            tgt = (e.get("if", {}) or {}).get("target", "self")
            if tgt in ("self", "this"):
                continue   # 単一 victim (= 本人のみ) なら do でも 1 回
            do = e.get("do", []) or []
            if any(isinstance(d, dict) and "return_self_don_to_deck" in d for d in do):
                offenders.append(cid)
    assert not offenders, (
        f"複数 victim holder が return_self_don_to_deck を do に持つ (同時離脱で二重払い): {offenders}"
    )


# --------------------------------------------------------------------------- #
#  効果無効 × 【自分のターン終了時】 (2026-08-08)
#     ⚠ 公式 cardqa_op_10 (OP10-112 ユースタス・キッド):
#       Q「このカードが直前の相手のターンに OP09-093 マーシャル・D・ティーチの【起動メイン】で
#         選ばれ、このターン終了時まで効果が無効になっています。この【自分のターン終了時】効果は
#         発動できますか？」
#       A「いいえ、できません。エンドフェイズでは、はじめに【自分のターン終了時】が発動し、次に
#         『ターン終了時まで』を期限とする効果が無効になります。」
#     = 効果無効中の【自分のターン終了時】は発動しない。 _execute_event の disable gate は
#       end_of_turn / opp_end_of_turn を含んでいなかった (= 発火してしまう bug、 2026-08-08 是正)。
# --------------------------------------------------------------------------- #
def test_disabled_character_end_of_turn_does_not_fire():
    """効果無効 (effect_disabled_through_opp_turn) のキャラの【自分のターン終了時】は
    エンドフェイズ内でまだ無効なため発動しない (公式 cardqa_op_10)。"""
    from engine.effects import trigger_end_of_turn

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP10-099")   # ユースタス・キッド (リーダー)
    st.phase = Phase.END
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 2               # 相手ライフ2以下 = キッドの end_of_turn 条件成立
    kid = InPlay.of(repo.get("OP10-112"), sickness=False)   # ユースタス・キッド (キャラ)
    kid.effect_disabled_through_opp_turn = True
    me.characters = [kid]
    me.hand = [repo.get(_FILLER)] * 2
    deck_before = len(me.deck)

    trigger_end_of_turn(st, overlay)

    assert len(me.deck) == deck_before, (
        "効果無効中のキャラの【自分のターン終了時】が発動してしまった (公式=いいえ、発動しない)"
    )


def test_non_disabled_character_end_of_turn_does_fire():
    """対照: 無効化されていなければ【自分のターン終了時】は通常どおり発動する。"""
    from engine.effects import trigger_end_of_turn

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP10-099")
    st.phase = Phase.END
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 2
    kid = InPlay.of(repo.get("OP10-112"), sickness=False)
    me.characters = [kid]
    me.hand = [repo.get(_FILLER)] * 2
    deck_before = len(me.deck)

    trigger_end_of_turn(st, overlay)

    assert len(me.deck) == deck_before - 1, "無効でないキッドの end_of_turn はドローするはず"


# --------------------------------------------------------------------------- #
#  R. 発動コストの取りこぼし (2026-08-09、 FAQ 全件保証バッチ)
# --------------------------------------------------------------------------- #
def test_eb01_011_activate_main_requires_returning_a_printed_power_1000_chara():
    """EB01-011 ミニメリー2号 の【起動メイン】は 「自分の元々のパワー1000のキャラ1枚を
    デッキの下に置く」 を発動コストに含む。 対象キャラが居なければドローできない (タダ撃ち禁止)。

    一次情報 (cardqa_eb_01, qid 651d177800d2):
      「元々のパワーが1000で、 ドン!!が付与され現在のパワーが2000以上となっているキャラを、
        この【起動メイン】効果で自分のデッキの下に置きカード1枚を引くことはできますか？」
      → 「はい、できます。」  (= 対象は **印刷パワー** 1000。 ドン付与で現在値が動いても対象)
    是正前: overlay の cost が rest_self のみで、 対象キャラを戻さずに draw できた (タダ撃ち)。
    """
    repo, overlay = _repo(), _overlay()

    # (a) 印刷パワー1000のキャラ (ドン付与で現在2000+) を場に持つ → 発動でき、 draw 1 + 戻す
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("EB01-011"), sickness=False)
    me.stages = [stage]
    p1000 = next(c for c in repo._by_id.values()
                 if c.category.name == "CHARACTER" and str(c.power) == "1000")
    tgt = InPlay.of(p1000, sickness=False)
    tgt.attached_dons = 2                       # 現在パワー = 3000 だが元々は 1000
    me.characters = [tgt]
    hand_before = len(me.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "EB01-011"]
    assert opts, "対象キャラが居るのに起動メインが legal に出ない"
    fire_activate_main(st, me, opp, *opts[0])
    assert len(me.hand) == hand_before + 1, "コストを払ったのにドローしていない"
    assert tgt not in me.characters, "元々パワー1000のキャラがデッキ下に置かれていない"
    assert stage.rested, "コストの self rest が行われていない"

    # (b) 印刷パワー1000のキャラが居ない → コスト不成立 = draw させない (タダ撃ち禁止)
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    stage2 = InPlay.of(repo.get("EB01-011"), sickness=False)
    me2.stages = [stage2]
    other = next(c for c in repo._by_id.values()
                 if c.category.name == "CHARACTER" and str(c.power) not in ("1000", "-", ""))
    me2.characters = [InPlay.of(other, sickness=False)]
    hand_before2 = len(me2.hand)
    for o in [o for o in list_activate_main_effects(st2, me2, overlay)
              if o[0].card.card_id == "EB01-011"]:
        fire_activate_main(st2, me2, opp2, *o)
    assert len(me2.hand) == hand_before2, "対象不在なのにドローした (タダ撃ち)"
    assert not stage2.rested, "対象不在なのに self rest だけ払っている"


def test_st22_005_replace_leave_needs_full_two_card_discard():
    """ST22-005 光月おでん の離脱置換は 「代わりに手札2枚を捨てる」 が発動コスト。
    手札が1枚しかなければ払えず、 置換は成立せず場を離れる。

    一次情報 (cardqa_st_22, qid 645ccc31a2c2):
      「自分の手札が1枚だけの時にこのキャラが相手の効果で場を離れる場合、 手札1枚を捨てる
        ことで場を離れないことはできますか？」
      → 「この場合、 手札2枚を捨てることができないため効果は使えず、 場を離れることになります。」
    是正前: 捨てが `do` にあり payability が効かず、 手札1枚でも 1 枚だけ捨てて置換成立していた。
    """
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()

    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("ST22-005"), sickness=False)
    me.characters = [oden]
    me.hand = [repo.get(_FILLER)]               # 1 枚 = 2 枚捨てられない
    replaced = try_replace_ko(st, me, opp, oden, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is False, "手札1枚では置換できないはず (公式=場を離れる)"
    assert len(me.hand) == 1, "払えないのに手札を捨てている"

    # 対照: 手札2枚あれば置換成立し 2 枚とも捨てる
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    oden2 = InPlay.of(repo.get("ST22-005"), sickness=False)
    me2.characters = [oden2]
    me2.hand = [repo.get(_FILLER), repo.get(_FILLER)]
    replaced2 = try_replace_ko(st2, me2, opp2, oden2, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced2 is True and len(me2.hand) == 0, "手札2枚なら置換成立し2枚捨てるはず"


def test_no_replace_effect_hides_a_payment_cost_inside_do():
    """全走査: replace_ko/leave/rest の 「代わりに<支払>できる/てもよい」 は必ず `cost` に置く。
    `do` に支払プリミティブがあると payability が効かず、 資源不足でも置換が成立してしまう
    (ST22-005 / ST22-012 / OP12-061 等で 2026-08-09 に是正)。 同型の取りこぼしを禁止する番人。
    """
    _, overlay = _repo(), _overlay()
    PAY = {"trash_self_hand_random", "discard_hand", "discard_hand_with_filter",
           "life_to_hand", "return_self_don_to_deck", "mill_self_life_to_trash",
           "rest_self_don"}
    offenders = []
    for cid, bundle in overlay.items():
        if cid == "_meta" or not hasattr(bundle, "effects"):
            continue
        for e in bundle.effects:
            if not isinstance(e, dict):
                continue
            if e.get("when") not in ("replace_ko", "replace_leave", "replace_rest"):
                continue
            for prim in (e.get("do") or []):
                if isinstance(prim, dict) and (set(prim.keys()) & PAY):
                    offenders.append((cid, list(prim.keys())))
    assert not offenders, (
        "置換の支払コストが do に埋もれている (payability が効かない): "
        f"{offenders[:10]}"
    )


# --------------------------------------------------------------------------- #
#  I. on_self_rested はアタック宣言 (自己レスト) でも発火する
#     公式 Q&A (cardqa_op_14 677c149d0045):
#       「『このキャラがレストになった時』の効果は、このキャラがアタックした時に発動しますか？」
#       → 「はい、発動します」
#     ⚠ 2026-08-09 まで engine のアタック経路が trigger_on_self_rested を呼んでおらず、
#       全 on_self_rested カード (OP14-027/028/032/035/119 / ST32-003 等) が
#       アタックでは silent 不発だった (実測: シャンクスが相手キャラをレストにしなかった)。
# --------------------------------------------------------------------------- #
def test_on_self_rested_fires_on_attack():
    """OP14-027 シャンクス: 【自分のターン中】このキャラがレストになった時、相手の元々パワー
    7000以下のキャラ1枚までをレストにする。 アタック=自己レストで発火し、相手アクティブキャラを
    レストにする。 (修正前はここが不発 = active のまま)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    shanks = InPlay.of(repo.get("OP14-027"), sickness=False)
    shanks.rested = False
    me.characters = [shanks]
    foe = InPlay.of(repo.get("OP01-016"), sickness=False)  # 印刷パワー 2000 (<=7000)
    foe.rested = False
    opp.characters = [foe]
    apply_action(st, AttackLeader(attacker_iid=shanks.instance_id))
    assert opp.characters and opp.characters[0].rested, (
        "アタック(自己レスト)で on_self_rested が発火せず相手キャラがレストにならない"
    )


def test_on_self_rested_costless_effect_fires_on_attack_scan():
    """全走査: costless で条件が self_turn/無条件の on_self_rested カードは、アタックすると
    trigger_on_self_rested が発火する (wiring 保証)。 cost 持ち (OP14-021 任意 / OP14-070
    相手キャラ効果 / PRB02-009 by_opp) は自己アタックでは発火してはいけない。"""
    import json as _json
    from unittest import mock
    from pathlib import Path as _Path
    repo, overlay = _repo(), _overlay()
    raw = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    def _costless(eff):
        cost = eff.get("cost") or {}
        return not any(ck != "once_per_turn" for ck in cost)

    fired, skipped = [], []
    for cid, bundle in raw.items():
        if cid == "_meta" or not isinstance(bundle, list):
            continue
        rested_effs = [e for e in bundle if isinstance(e, dict) and e.get("when") == "on_self_rested"]
        if not rested_effs:
            continue
        try:
            base_cid = cid.split("_")[0]
            card = repo.get(cid)
        except Exception:
            continue
        # キャラのみ (leader/stage は attacker にならない、 parallel は本体で代表)
        if "_p" in cid:
            continue
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        atk = InPlay.of(card, sickness=False)
        atk.rested = False
        me.characters = [atk]
        me.don_active = 6
        # スパイ: trigger_on_self_rested が attacker で呼ばれたか
        calls = {"n": 0}
        import engine.game as _g
        real = _g.trigger_on_self_rested if hasattr(_g, "trigger_on_self_rested") else None
        # game.py は関数内で from .effects import するので effects 側を patch
        import engine.effects as _e
        orig = _e.trigger_on_self_rested
        def _spy(state, m, o, rested_ip, ov, costless_only=False):
            if rested_ip is atk and costless_only:
                calls["n"] += 1
            return orig(state, m, o, rested_ip, ov, costless_only=costless_only)
        with mock.patch.object(_e, "trigger_on_self_rested", _spy):
            try:
                apply_action(st, AttackLeader(attacker_iid=atk.instance_id))
            except Exception:
                continue
        # trigger_on_self_rested はアタック経路から必ず呼ばれる (発火するか skip かは costless 次第)
        assert calls["n"] >= 1, f"{cid}: アタック経路から on_self_rested が呼ばれていない (wiring 欠落)"

    # cost 持ちの代表 (OP14-070) はアタックで自身をアクティブに戻してはいけない
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    buf = InPlay.of(repo.get("OP14-070"), sickness=False)
    buf.rested = False
    me.characters = [buf]
    me.don_active = 6
    apply_action(st, AttackLeader(attacker_iid=buf.instance_id))
    assert me.characters[0].rested, "OP14-070(相手キャラ効果でレスト時)が自己アタックで誤発火し untap した"
    assert me.don_active == 6, "OP14-070 が自己アタックでコスト(ドン返却)を誤って支払った"


# --------------------------------------------------------------------------- #
#  J. 条件節「相手の手札が5枚以上ある場合」は その後のミルまで gate する
#     公式 Q&A (cardqa_op_10 670c9ed2c408): OP10-087 チョッパー
#       「相手の手札が4枚以下の場合、この【起動メイン】効果で自分のデッキの上から2枚を
#        トラッシュに置くことはできますか？」→「いいえ、できません」
# --------------------------------------------------------------------------- #
def test_op10_087_mill_gated_by_opponent_hand():
    """OP10-087 の起動メインの mill (デッキ上2枚トラッシュ) は『相手の手札5枚以上』条件の
    内側にあり、 相手手札4枚以下では発動しない。 (修正前は conditional の外でタダ撃ちできた)。"""
    repo, overlay = _repo(), _overlay()
    cond_prim = {"conditional": {"if": {"opp_hand_count_ge": 5},
                                 "do": [{"opp_discard_own_choice": 1}, {"mill_self_top": 2}]}}
    for opp_hand, expect in [(4, 0), (5, 2)]:
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        opp.hand = [repo.get(_FILLER)] * opp_hand
        src = InPlay.of(repo.get("OP10-087"), sickness=False)
        me.characters = [src]
        before = len(me.deck)
        execute_effect(cond_prim, st, me, opp, src)
        milled = before - len(me.deck)
        assert milled == expect, f"opp_hand={opp_hand}: milled={milled} (expect {expect})"


def test_op10_087_overlay_mill_inside_conditional():
    """回帰防止 (overlay 構造): OP10-087 の mill_self_top は conditional(opp_hand>=5)の内側にある。"""
    import json as _json
    raw = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    e = raw["OP10-087"][0]
    oct = e["do"][0]["optional_cost_then"]["effect"]
    # トップレベルの effect に mill_self_top が裸で置かれていないこと
    top_keys = [k for prim in oct for k in prim.keys()]
    assert "mill_self_top" not in top_keys, "mill_self_top が conditional の外にある (タダ撃ち回帰)"
    cond = next(p for p in oct if "conditional" in p)
    inner = [k for prim in cond["conditional"]["do"] for k in prim.keys()]
    assert "mill_self_top" in inner, "mill_self_top が conditional 内に無い"


# --------------------------------------------------------------------------- #
#  K. OP02-089 の【トリガー】return_opp_don は『相手の場にドン6枚以上』で gate される
#     兄弟カード OP02-090/091 と同文。 2026-08-09 まで OP02-089 だけ if 欠落。
# --------------------------------------------------------------------------- #
def test_op02_089_trigger_don_return_gate():
    """OP02-089 の【トリガー】は相手のドンが6枚以上ある時だけ相手ドン1枚を戻す。"""
    import json as _json
    raw = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    trig = next(e for e in raw["OP02-089"] if e.get("when") == "trigger")
    assert trig.get("if") == {"opp_don_count_ge": 6}, "OP02-089 トリガーの opp_don_count_ge gate 欠落"


# --------------------------------------------------------------------------- #
#  L. 相手の効果で自分の手札が捨てられた時も on_self_hand_discarded / flag は発火する
#     公式 (cardqa_st_33 / cardqa_op_14):
#       「相手の効果で自分の手札が捨てられている場合、そのターン中手札のこのカードは
#         コスト-3されますか？」→「はい、コスト-3されます」(ST33-004 ボルサリーノ)
#       「相手の効果 (OP09-111 ブルック の【トリガー】等) で自分が手札を捨てた場合、
#         このキャラは【速攻】を得ることはできますか？」→「はい、できます」(OP14-045 クロオビ)
#     2026-08-09: trash_opp_hand_random / force_opp_discard / opp_discard_own_choice が
#       victim (= 手札の持ち主) の hand_discarded_by_effect_this_turn を立てず、
#       on_self_hand_discarded トリガーも発火していなかった一般則バグを是正。
# --------------------------------------------------------------------------- #
def _fresh_state_with_opp_hand(repo, overlay, opp_hand_n=4):
    st = _state(repo, overlay)
    st.players[1].hand = [repo.get(_FILLER)] * opp_hand_n
    return st


def test_opp_effect_hand_discard_sets_victim_flag_all_primitives():
    """相手手札を捨てる 3 primitive すべてが victim の hand_discarded フラグを立てる。

    バグ回帰: 修正前は 3 primitive とも flag=False のまま = ST33-004 のコスト-3 が効かず、
    OP14-045 クロオビ の【速攻】も発火しなかった。 全走査で取りこぼしを防ぐ。
    """
    repo, overlay = _repo(), _overlay()
    for prim in ({"trash_opp_hand_random": 2},
                 {"force_opp_discard": 1},
                 {"opp_discard_own_choice": 2}):
        st = _fresh_state_with_opp_hand(repo, overlay)
        me, opp = st.players[0], st.players[1]
        assert opp.hand_discarded_by_effect_this_turn is False
        execute_effect(prim, st, me, opp, me.leader)
        assert opp.hand_discarded_by_effect_this_turn is True, (
            f"{list(prim)[0]}: 相手効果の手札破棄で victim の hand_discarded フラグが立たない")


def test_op14_045_gains_rush_when_opponent_discards_my_hand():
    """OP14-045 クロオビ は相手効果で自分の手札が捨てられた時に【速攻】を得る。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # 自分 (P0) の場に登場したての クロオビ (召喚酔い) を置く。
    kurobi = InPlay.of(repo.get("OP14-045"), sickness=True)
    me.characters = [kurobi]
    me.hand = [repo.get(_FILLER)] * 3
    assert kurobi.summoning_sickness is True
    # 相手 (P1) の効果が P0 の手札を捨てさせる (= me=opp 視点で trash_opp_hand_random)。
    # 発動者は opp、 対象は me。
    execute_effect({"trash_opp_hand_random": 1}, st, opp, me, opp.leader)
    assert me.hand_discarded_by_effect_this_turn is True
    # クロオビ が【速攻】を得て 召喚酔いでもアタック可能になっている。
    kws = set(getattr(kurobi, "granted_keywords", set()) or []) \
        | set(getattr(kurobi, "static_granted_keywords", set()) or [])
    assert "速攻" in kws, f"クロオビ が速攻を得ていない (granted={kws})"


# --------------------------------------------------------------------------- #
#  M. 「自分のドン‼すべてがレストの場合」 は 付与ドンが 1 枚でもあれば不成立
#     公式 (cardqa_op_02): 「自分のキャラやリーダーにドン‼が付与されている場合、
#       『自分のドン‼すべてがレストの場合』の条件を満たすことはできますか？」
#       →「いいえ、できません」(OP02-027 イヌアラシ)
#     2026-08-09: self_don_active_eq:0 (コストエリアのアクティブドンのみ判定) は付与ドンを
#       無視して条件成立させていた。 self_all_don_rested (active0 かつ 付与ドン0) を新設。
# --------------------------------------------------------------------------- #
def test_self_all_don_rested_false_when_don_attached():
    """付与ドンがあると self_all_don_rested は False (アクティブドン0でも)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    inu = InPlay.of(repo.get("OP02-027"), sickness=False)
    me.characters = [inu]
    me.don_active = 0
    me.don_rested = 3
    cond = {"self_all_don_rested": True}
    # 付与ゼロ → 全ドンレスト成立
    assert eval_condition(cond, st, me, inu) is True
    # キャラに 1 枚付与 → 不成立 (バグ回帰: 修正前は True のまま)
    inu.attached_dons = 1
    assert eval_condition(cond, st, me, inu) is False
    # リーダーに付与でも不成立
    inu.attached_dons = 0
    me.leader.attached_dons = 1
    assert eval_condition(cond, st, me, inu) is False
    # アクティブドンが残っていても不成立
    me.leader.attached_dons = 0
    me.don_active = 1
    assert eval_condition(cond, st, me, inu) is False


def test_op02_027_overlay_uses_self_all_don_rested():
    """OP02-027 の overlay は self_don_active_eq でなく self_all_don_rested を使う。"""
    import json as _json
    raw = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    ent = raw["OP02-027"][0]
    assert "self_all_don_rested" in ent.get("if", {}), "OP02-027 が self_all_don_rested 未使用"
    assert "self_don_active_eq" not in ent.get("if", {}), "旧 self_don_active_eq が残存"


# --------------------------------------------------------------------------- #
#  L. OP09-103 コアラ: 「登場させた場合、カード1枚を引く」 は登場0枚なら draw 不発。
#     一次情報 cardqa_op_09: 「この【登場時】効果を発動し、手札からコスト4以下の特徴
#     《革命軍》を持つキャラカード0枚を登場させることを選んだ場合、カード1枚を引くこと
#     はできますか？」 → 「いいえ、できません。」
#     修正前は play_from_hand の後に裸の {"draw":1} があり、登場0枚でも引けた (タダ引き)。
# --------------------------------------------------------------------------- #
def test_op09_103_draw_gated_on_character_played():
    """OP09-103: 登場できた時のみ draw。 該当キャラ不在 (登場0枚) では引かない。"""
    import json as _json
    repo, overlay = _repo(), _overlay()
    # コスト4以下 革命軍 キャラを1枚探す (positive case 用)
    rev = None
    for c in _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8")):
        if (c["category"] == "CHARACTER" and "革命軍" in (c.get("features") or "")
                and c.get("cost") and int(c["cost"]) <= 4):
            rev = c["base_id"]
            break
    assert rev is not None

    def run(hand_ids):
        st = _state(repo, overlay, leader0="OP09-001")
        me, opp = st.players[0], st.players[1]
        me.hand = [repo.get(x) for x in hand_ids]
        me.deck = [repo.get(_FILLER)] * 20
        me.life = [repo.get(_FILLER)] * 3
        koala = InPlay.of(repo.get("OP09-103"), sickness=True)
        me.characters.append(koala)
        before_hand, before_chars = len(me.hand), len(me.characters)
        trigger_on_play(st, me, opp, koala, overlay)
        return before_hand, len(me.hand), before_chars, len(me.characters)

    # 0-play: 手札に 革命軍 コスト4以下 が無い → ライフ→手札コストのみ (+1)、 draw 不発。
    bh, ah, bc, ac = run([_FILLER])
    assert ac == bc, "登場0枚のはずがキャラが増えた"
    assert ah == bh + 1, f"登場0枚で draw が発火した (hand {bh}->{ah}, 期待 +1=ライフコストのみ)"

    # 1-play: 革命軍 コスト4以下 を登場 → draw 発火。
    bh2, ah2, bc2, ac2 = run([rev])
    assert ac2 == bc2 + 1, "革命軍キャラが登場していない"
    # +1 (life cost) -1 (played from hand) +1 (draw) = net +1
    assert ah2 == bh2 + 1, f"登場1枚で draw が発火していない (hand {bh2}->{ah2})"


def test_op09_103_overlay_uses_then_draw():
    """回帰防止 (overlay 構造): OP09-103 の draw は play_from_hand の then_draw であって、
    裸の {'draw':1} で無条件発火していないこと。"""
    import json as _json
    raw = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    for cid in ("OP09-103", "OP09-103_p1"):
        eff = raw[cid][0]["do"][0]["optional_cost_then"]["effect"]
        top_keys = [k for prim in eff for k in prim.keys()]
        assert "draw" not in top_keys, f"{cid}: 裸の draw が残存 (タダ引き回帰)"
        pfh = next(p["play_from_hand"] for p in eff if "play_from_hand" in p)
        assert pfh.get("then_draw") == 1, f"{cid}: play_from_hand.then_draw 未設定"


def test_next_opp_turn_end_applied_during_opp_turn_expires_same_turn():
    """「次の相手のターン終了時まで」 は **適用後 最初に訪れる相手のターン終了** で切れる。

    一次情報 (cardqa_op_01、 OP01-085 Mr.3):
      Q「このキャラを **相手のターン中に** 登場させ、【登場時】効果を発動した場合、
        次の相手のターン終了時とはいつまでですか？」 → A「**そのターンの終了時です**」

    退行前は applier-tracking の解除条件が `applied_turn < turn_number` (strict) で
    「必ず 1 ターン経過」 を要求しており、 相手ターン中に適用した効果が **1 サイクル長く**
    残っていた (turn 9 適用 → turn 11 終了まで持続)。
    """
    repo, overlay = _repo(), _overlay()

    def run(turn_player: int) -> list[int]:
        st = _state(repo, overlay)
        st.turn_player_idx = turn_player
        me = st.players[0]
        c = InPlay.of(repo.get(_FILLER), sickness=False)
        me.characters = [c]
        execute_effect(
            {"power_pump": {"target": "self", "amount": 1000,
                            "duration": "next_opp_turn_end"}},
            st, me, st.players[1], c,
        )
        seq = [c.next_opp_turn_end_buff]
        for _ in range(3):
            apply_action(st, EndPhase())
            seq.append(c.next_opp_turn_end_buff)
        return seq

    # P0 が **相手 (P1) のターン中** に適用 → そのターン終了で切れる
    assert run(turn_player=1) == [1000, 0, 0, 0], (
        "相手ターン中に適用した 「次の相手のターン終了時まで」 が そのターン終了で切れていない "
        "(cardqa_op_01 / OP01-085)"
    )
    # P0 が **自分のターン中** に適用 → 自ターン終了では切れず、 次の相手ターン終了で切れる
    assert run(turn_player=0) == [1000, 1000, 0, 0], "自ターン適用時の挙動が変わってしまっている"


def test_op12_020_activate_main_requires_battling_opp_character():
    """OP12-020 ゾロ 起動メインは 「このターン中、 このリーダーが **相手のキャラと** バトルして
    いる場合」 のみ発動できる (cardqa_op_12)。

    公式 Q&A 2 件:
      - 相手リーダー「OP05-022 ロシナンテ」の【ブロッカー】でリーダーとバトルした場合 → **いいえ**
      - 【相手のアタック時】でアタック対象を自分のリーダーへ変更された場合 → **いいえ**
    = 判定は **実際にバトルした相手** で行う。 退行前は overlay の if が
    `self_attached_don_ge: 3` だけで、 バトルの有無に関係なくアクティブにできていた。
    """
    repo, overlay = _repo(), _overlay()

    def build():
        st = _state(repo, overlay, leader0="OP12-020")
        st.players[0].leader.attached_dons = 3
        return st, st.players[0], st.players[1]

    def can_activate(st, me) -> bool:
        return bool(list_activate_main_effects(st, me, overlay))

    # (1) 何ともバトルしていない → 発動できない
    st, me, opp = build()
    assert not can_activate(st, me), "バトル前なのに起動メインが候補に出ている"

    # (2) リーダーが相手 **キャラ** とバトル → 発動できる
    st, me, opp = build()
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    opp.characters = [victim]
    apply_action(st, AttackCharacter(attacker_iid=me.leader.instance_id,
                                     target_iid=victim.instance_id))
    assert me.leader_battled_opp_chara_this_turn is True
    assert can_activate(st, me), "相手キャラとバトルしたのに起動メインが出ない"

    # (3) リーダーが相手 **リーダー** とバトル → 発動できない (公式 いいえ)
    st, me, opp = build()
    apply_action(st, AttackLeader(attacker_iid=me.leader.instance_id))
    assert me.leader_battled_opp_chara_this_turn is False
    assert not can_activate(st, me), (
        "リーダーとバトルしただけで起動メインが発動できている (cardqa_op_12 違反)"
    )


def test_op05_098_enel_fires_when_life_hits_zero_even_if_trigger_restores_it():
    """OP05-098 エネル 【相手のターン中】「自分のライフが0枚になった時」 は **0 になった瞬間の事象**。

    一次情報 (cardqa_op_05): 「自分のライフが1枚の時にダメージを受け、 そのライフが
    『OP03-118 威国』 だったため【トリガー】効果を発動しライフが0枚から1枚になりました。
    この時、 この【相手のターン中】効果は発動できますか？」 → 「はい、 発動できます」

    退行前は 「アタック **開始時** にライフ0」 でしか発火しておらず、 ライフが戻ると
    発動タイミングを永久に取り逃していた。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader1="OP05-098")
    st.turn_player_idx = 0
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP03-118")]          # ライフ 1 枚 (= 威国)
    opp.hand = [repo.get(_FILLER)] * 4
    deck_before = len(opp.deck)

    apply_action(st, AttackLeader(attacker_iid=me.leader.instance_id))

    assert not st.game_over, "エネルでライフを補充したのに敗北になっている"
    assert len(opp.life) >= 1, "ライフ0のまま = エネルが発動していない (cardqa_op_05 違反)"
    assert len(opp.deck) < deck_before, "デッキ上をライフに置く処理が走っていない"


def test_op16_041_buggy_fires_on_leave_by_own_effect():
    """OP16-041 バギー: **自分の効果で** インペルダウンキャラが場を離れた時も発動できる。

    一次情報 (cardqa_op_16): 「自分の『OP07-056 虜の矢』などの効果によって、 自分の特徴
    《インペルダウン》を持つキャラが手札に戻りました。 この時、 このリーダーの効果で
    『インペルダウンの囚人』1枚を登場させることはできますか？」 → 「はい、 できます」

    退行前は (a) overlay が KO / 相手効果離脱しか配線せず (b) 任意コストの離脱経路が
    leave-by-self トリガーを一切発火していなかった、 の 2 段で発動しなかった。
    """
    repo, overlay = _repo(), _overlay()

    def run(victim_id: str) -> bool:
        st = _state(repo, overlay, leader0="OP16-041")
        st.turn_player_idx = 1              # 相手ターン (= 虜の矢はカウンター)
        me, opp = st.players[0], st.players[1]
        me.leader.attached_dons = 1         # 【ドン!!×1】
        me.characters = [InPlay.of(repo.get(victim_id), sickness=False)]
        me.hand = [repo.get("OP16-042")]    # インペルダウンの囚人
        execute_effect(
            {"optional_cost_then": {
                "cost": [{"return_self_chara_to_hand": {"count": 1, "filter": {"cost_ge": 2}}}],
                "effect": [{"power_pump": {"target": "self_leader", "amount": 4000,
                                           "duration": "battle"}}]}},
            st, me, opp, me.leader,
        )
        resolve_triggers(st)
        return any(c.card.card_id == "OP16-042" for c in me.characters)

    assert run("EB02-038") is True, (
        "インペルダウンキャラが自分の効果で場を離れたのに『囚人』が登場していない (cardqa_op_16 違反)"
    )
    assert run("EB01-012_r1") is False, (
        "非インペルダウンキャラの離脱で発動してしまっている (victim 特徴の判定漏れ)"
    )


def test_op06_043_activate_main_cost_is_all_or_nothing():
    """OP06-043 アラマキ: 「手札1枚を捨て、 コスト2以下のキャラ1枚をデッキの下に置くことが
    できる：」 は **コロン前が全て発動コスト** = 部分支払い不可 (cardqa_op_06)。

    Q「コスト2以下のキャラ1枚をデッキの下に置かずに、 自分の手札1枚を捨てることは
      できますか？」 → 「いいえ、 できません」
    """
    repo, overlay = _repo(), _overlay()

    def run(with_target: bool):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        src = InPlay.of(repo.get("OP06-043"), sickness=False)
        me.characters = [src]
        me.hand = [repo.get(_FILLER)] * 3
        if with_target:
            opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]  # コスト1
        cands = list_activate_main_effects(st, me, overlay)
        if not cands:
            return src.power, len(me.hand)
        s, e = cands[0]
        fire_activate_main(st, me, opp, s, e)
        resolve_triggers(st)
        return src.power, len(me.hand)

    pumped, hand_after = run(True)
    base, hand_kept = run(False)
    assert pumped == base + 3000, "弾が居る時は +3000 されるはず"
    assert hand_after == 2, "弾が居る時は手札1枚を捨てるはず"
    assert hand_kept == 3, (
        "コスト2以下のキャラが居ないのに手札だけ捨てている (= 部分支払い、 cardqa_op_06 違反)"
    )


def test_simultaneous_leave_replacement_condition_is_frozen_at_batch_start():
    """同時離脱では victim に依らない条件を **バッチ開始時の状態** で 1 度だけ判定する。

    一次情報 (cardqa_op_11、 OP11-001 コビー = 【ターン1回】自分の元々のパワー7000以下の
    《海軍》キャラが相手の効果で場を離れる場合、 代わりに自分のトラッシュから3枚をデッキ下に):
      Q「自分のトラッシュが **2枚以下** の時に、 (該当) キャラA と キャラB が **同時にKO**
        された場合、 まず キャラA をトラッシュに置き、 キャラB をこの効果で代わりに場を
        離れないことはできますか？」 → A「**いいえ、 できません**」

    退行前は `self_trash_count_ge: 3` を victim ごとに **現在のトラッシュ** で評価しており、
    先に落ちた A の分でトラッシュが 3 枚になり B だけ救われていた (= 実測で残キャラ 1)。
    """
    repo, overlay = _repo(), _overlay()

    def survivors(trash_n: int) -> int:
        st = _state(repo, overlay, leader0="OP11-001")
        st.turn_player_idx = 1                      # 相手ターン = 相手の効果で離脱
        me, opp = st.players[0], st.players[1]
        me.trash = [repo.get(_FILLER)] * trash_n
        me.characters = [
            InPlay.of(repo.get("PRB02-001"), sickness=False),   # 海軍 / 元々5000
            InPlay.of(repo.get("EB04-022"), sickness=False),    # 海軍 / 元々7000
        ]
        execute_effect(
            {"ko_multi": [{"type": "one_opponent_character_filtered", "filter": {}},
                          {"type": "one_opponent_character_filtered", "filter": {}}]},
            st, opp, me, opp.leader,
        )
        resolve_triggers(st)
        return len(me.characters)

    assert survivors(2) == 0, (
        "トラッシュ2枚 (コスト3枚に不足) なのにキャラが生き残っている = 先に離れた victim が "
        "増やしたトラッシュで後の victim を救っている (cardqa_op_11 違反)"
    )
    # 対照: トラッシュ3枚なら 1 回払って **2 枚とも** 残る (cardqa_op_15 の 「コストは holder ごとに1回」)
    assert survivors(3) == 2, "トラッシュ3枚なら同時離脱の2枚とも残るはず (cardqa_op_15)"
    assert survivors(0) == 0, "トラッシュ0枚なら条件不成立で2枚とも離れるはず"


def test_op08_001_chopper_attaches_don_only_to_filtered_characters():
    """OP08-001 チョッパー 起動メイン: 対象は 「自分の **特徴《動物》か《ドラム王国》を持つ
    キャラ**」 だけ。 特徴を持たないキャラや **自リーダー** には付与しない。

    一次情報 (cardqa_op_08) の裁定中に発覚: overlay の target が `all_self_team`
    (= 特徴フィルタ無し + リーダーも対象) で、 公式が対象外としているカードにもドンを
    付与していた。 併せて 「1枚ずつまで」 (= 1 キャラに 2 枚以上は不可) も固定する。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP08-001")
    me, opp = st.players[0], st.players[1]
    me.don_rested = 5
    target = InPlay.of(repo.get("EB04-018"), sickness=False)   # 特徴《動物》
    other = InPlay.of(repo.get(_FILLER), sickness=False)       # 麦わらの一味 = 対象外
    me.characters = [target, other]

    source, eff = list_activate_main_effects(st, me, overlay)[0]
    fire_activate_main(st, me, opp, source, eff)
    resolve_triggers(st)

    assert target.attached_dons == 1, "対象キャラに 1 枚付与されていない (「1枚ずつまで」)"
    assert other.attached_dons == 0, "特徴を持たないキャラにドンが付与されている (公式違反)"
    assert me.leader.attached_dons == 0, "リーダーにドンが付与されている (公式は 「キャラ」 限定)"
def test_op08_039_end_of_turn_untap_mink_only():
    """OP08-039 ゾウ(ステージ)の【自分のターン終了時】は 特徴《ミンク族》を持つキャラだけを
    アクティブにできる。 非ミンク族キャラは対象外。

    公式 (cardqa_op_08, qid 7c2b32d9c030):
      Q: 自分のリーダーが特徴《ミンク族》を持たない場合、この【自分のターン終了時】効果で
         自分の特徴《ミンク族》を持つキャラ1枚をアクティブにできますか？
      A: はい、できます。
    → リーダーの特徴に依らず発動する (leader gate 無し) のは元から conform。
      ただし overlay が target=one_self_character_any で **非ミンク族も** 起こせていた (2026-08-10 是正)。
      対象は card テキストどおり 特徴《ミンク族》 に限定される。 非ミンク族が起きたら落ちる。
    """
    repo, ov = _repo(), _overlay()
    spec = ov["OP08-039"].effects[1]["do"][0]   # end_of_turn untap_chara
    assert ov["OP08-039"].effects[1].get("when") == "end_of_turn"

    def _untap(char_id):
        st, p0, p1 = _board_fi(repo, ov, [char_id], [])
        p0.characters[0].rested = True
        execute_effect(dict(spec), st, p0, p1, None)
        guard = 0
        while st.pending_choice is not None and guard < 5:
            resolve_pending_choice(st, [0]); guard += 1
        return p0.characters[0].rested

    # 非ミンク族 (PRB02-001 コビー) は対象外 → レストのまま
    assert _untap("PRB02-001") is True, "非ミンク族が起こされた (target が広すぎる)"
    # ミンク族 (EB04-013) は対象 → アクティブ化
    assert _untap("EB04-013") is False, "ミンク族キャラが起きていない"


def test_op08_039_overlay_target_is_mink_filtered():
    """回帰防止 (overlay 構造): OP08-039 end_of_turn の untap 対象は ミンク族 filter であって
    無差別の one_self_character_any でないこと。"""
    import json as _json
    raw = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    tgt = raw["OP08-039"][1]["do"][0]["untap_chara"]["target"]
    assert isinstance(tgt, dict), "target が文字列 (無差別) に戻っている"
    assert tgt.get("filter", {}).get("feature") == "ミンク族", \
        "untap 対象が 特徴《ミンク族》 に絞られていない"


def test_truly_original_power_is_rewritten_by_moto_effects():
    """「元々のパワー」 は **「元々のパワーを◯◯にする」 効果で書き換わる** (公式 4-9-2-1)。

    一次情報 (cardqa_op_10、 EB01-061 Mr.2・ボン・クレー = 【アタック時】「このキャラの
    **元々のパワー** は、 このターン中、 選んだキャラと同じパワーになる」):
      Q「…【アタック時】効果によって元々のパワーが2000以上になった場合に、 相手の効果に
        よってKOされますか？」 → A「**いいえ、 KOされません**」
    根拠: 総合ルール 4-9-2-1 「**元々のパワーをある数値にする効果**が複数あり…数値の高い
    効果を適用します」 = 元々のパワーは効果で書き換わる。

    ⭐ 「パワーが◯◯になる」 (= 特定値に SET する効果) は 語に 「元々の」 が **無くても**
      元々のパワーを書き換える (cardqa Q1085 = OP06-009 シュライヤ 「相手のリーダーと同じ
      パワーになる」 も 元々のパワーが変わる)。 「元々の」 の有無で 印刷値/現在値 を書き分ける
      のは **条件** (「パワーN以下」 等) の話であって、 SET 効果には効かない。 例外は
      「パワー0にする」 (公式 4-12 = 現在パワー分のマイナス)。
    """
    repo, overlay = _repo(), _overlay()

    def setup(card_id: str):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        src = InPlay.of(repo.get(card_id), sickness=False)
        me.characters = [src]
        opp.characters = [InPlay.of(repo.get("OP01-002"), sickness=False)]  # コピー元
        return st, me, opp, src

    def is_targetable(st, opp, me) -> bool:
        from engine.effects import _resolve_target
        got = _resolve_target(
            {"type": "one_opponent_character_filtered",
             "filter": {"truly_original_power_le": 2000}},
            st, opp, me, opp.leader,
        ) or []
        return bool(got)

    # --- 「元々のパワー」 を書き換える効果 (EB01-061) ---
    st, me, opp, mr2 = setup("EB01-061")
    assert mr2.truly_original_power == mr2.card.power, "発動前は印刷値のはず"
    assert is_targetable(st, opp, me), "発動前は 「元々2000以下」 の対象のはず (前提崩れ)"
    trigger_on_attack(st, me, opp, mr2, overlay)
    resolve_triggers(st)
    assert mr2.truly_original_power > 2000, (
        "「元々のパワーは…同じパワーになる」 が truly_original_power に反映されていない (公式 4-9-2-1)"
    )
    assert not is_targetable(st, opp, me), (
        "元々のパワーが2000超になったのに 「元々2000以下」 でKO対象のまま (cardqa_op_10 違反)"
    )

    # --- 「パワーになる」 (OP06-009 シュライヤ) も元々のパワーを書き換える (cardqa Q1085) ---
    #   シュライヤの 「相手のリーダーと同じパワーになる」 は 「元々の」 の語が無くても
    #   元々のパワーを書き換える (= 特定値 SET は 4-9-2-1)。 旧テストは original:false を
    #   前提に 「印刷値のまま」 を assert していたが、 Q1085 で公式違反と判明し是正 (2026-08-13)。
    st2, me2, opp2, shu = setup("OP06-009")
    printed = shu.card.power
    trigger_on_attack(st2, me2, opp2, shu, overlay)
    resolve_triggers(st2)
    assert shu.truly_original_power == opp2.leader.power, (
        "「パワーになる」 が truly_original_power を 相手リーダーと同じに書き換えていない "
        "(cardqa Q1085: 特定値 SET は元々のパワーを書き換える)"
    )
    assert shu.truly_original_power != printed, (
        "元々のパワーが印刷値のまま (Q1085 違反 = original:false のバグ)"
    )


def test_op05_109_pagaya_reacts_to_both_players_triggers():
    """OP05-109 パガヤ 「【ターン1回】【トリガー】が発動した時、 カード2枚を引き、 手札2枚を捨てる」
    は **両陣営** の【トリガー】発動に反応する。

    一次情報 (cardqa_op_05): 「相手が【トリガー】を発動した時にもこのキャラの効果は発動
    しますか？」 → 「**はい、 発動します**」 (= 「自分の/相手の」 の修飾が無い = 両陣営)。

    退行前は overlay が `when: "trigger"` = **このカード自身のライフトリガー** として登録され
    (cards.json の trigger 欄は空 = 持っていない【トリガー】を捏造)、 場では何も起きなかった。
    """
    repo, overlay = _repo(), _overlay()
    from engine.effects import trigger_lifecard_trigger

    def deck_drawn_by_pagaya(owner_idx: int) -> int:
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        owner = st.players[owner_idx]
        owner.characters = [InPlay.of(repo.get("OP05-109"), sickness=False)]
        for p in (me, opp):
            p.hand = [repo.get(_FILLER)] * 4
        before = len(owner.deck)
        # defender = P1 が 【トリガー】 (OP07-057 = 無条件 draw1) を発動する
        fired = trigger_lifecard_trigger(st, opp, me, repo.get("OP07-057"), overlay, auto_fire=True)
        assert fired, "前提の【トリガー】が発動していない"
        resolve_triggers(st)
        return before - len(owner.deck)

    # パガヤが「発動した側」(P1) → トリガーの draw1 + パガヤの draw2 = 3
    assert deck_drawn_by_pagaya(1) == 3, "自分が【トリガー】を発動した時に発動していない"
    # パガヤが「相手側」(P0) → パガヤの draw2 のみ
    assert deck_drawn_by_pagaya(0) == 2, (
        "相手が【トリガー】を発動した時に発動していない (cardqa_op_05 違反)"
    )


def test_on_life_zero_resolves_after_life_card_processing():
    """「自分のライフが0枚になった時」 は **ライフ処理 (【トリガー】発動) が終わってから** 発動する。

    一次情報 (cardqa_op_11、 OP11-102 ケイミー × 相手リーダー OP05-098 エネル ×
    相手ライフ OP06-115「お前が消えろ」):
      Q「ライフが1枚の相手にダメージを与え、 相手の「お前が消えろ」の【トリガー】効果が発動した時、
        この【自分のターン中】効果と相手「エネル」の効果はどのように処理すればよいですか？」
      A「**ターンプレイヤーの効果を優先するため、 まずこのカードの効果が発動し、 その後「エネル」の
        効果が発動します**。 このカードの効果が発動した時点では、 相手のライフは「お前が消えろ」の
        【トリガー】効果で増えた1枚だけなので、 **何も起きません**。 その後、「エネル」の効果により、
        相手は自身のデッキの上から1枚を、 ライフの上に加え、 自身の手札1枚を捨てます」

    退行前は 「ライフが 0 になった瞬間」 に **即解決** していたため、 非ターンプレイヤー (エネル) が
    【トリガー】より先に走り、 ライフが 2 枚になった状態で ターンプレイヤーの反応 (ケイミーの
    「相手のライフが2枚以上の場合」) が **誤って成立** して お互いのライフが 1 枚ずつ減っていた。
    """
    import engine.effects as _E
    repo, overlay = _repo(), _overlay()
    _orig = _E.should_fire_trigger
    _E.should_fire_trigger = lambda *a, **k: True   # 発動意思は固定 (順序だけを見る)
    try:
        st = _state(repo, overlay, leader1="OP05-098")
        me, opp = st.players[0], st.players[1]
        atk = InPlay.of(repo.get("EB01-018_p1"), sickness=False)   # power7000 バニラ
        me.characters = [atk, InPlay.of(repo.get("OP11-102"), sickness=False)]
        me.life = [repo.get(_FILLER)] * 3
        opp.life = [repo.get("OP06-115")]           # 唯一のライフ = お前が消えろ
        opp.hand = [repo.get(_FILLER)] * 3
        opp.deck = [repo.get(_FILLER)] * 20
        opp.trash = []
        apply_action(st, AttackLeader(attacker_iid=atk.instance_id), overlay)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
    finally:
        _E.should_fire_trigger = _orig

    assert len(me.life) == 3, (
        "ケイミーの 「お互いのライフの上から1枚をトラッシュ」 が誤って発動している "
        "(= 相手ライフが2枚以上になってから解決した)"
    )
    assert len(opp.life) == 2, (
        "相手ライフが 2 枚 (【トリガー】+1 / エネル+1) になっていない: "
        f"{len(opp.life)} 枚"
    )
    assert len(opp.hand) == 1, (
        "相手の手札が 3 → 1 (トリガー捨て1 + エネル捨て1) になっていない: "
        f"{len(opp.hand)} 枚"
    )


def test_rest_paid_as_activation_cost_fires_rested_triggers():
    """**発動コストでレストになった場合も** 「レストになった時」 は発動する。

    一次情報 (cardqa_op_07、 OP07-031 バルトロメオ
    「【自分のターン中】【ターン1回】キャラが自分の効果でレストになった時、 カード1枚を引き、
      自分の手札1枚を捨てる」):
      Q「自分のターン中に、 「【起動メイン】このキャラをレストにする：」 などの効果を発動し
        自分のキャラがレストになった時、 このキャラの【自分のターン中】効果を発動できますか？」
      → A「**はい、 できます**」

    退行前は `rest` **primitive** (= 効果としてのレスト) からしか発火せず、 コスト由来のレストを
    丸ごと取りこぼしていた。

    ⚠ 併せて 対象範囲も是正: 公式は 「**キャラ**が自分の効果でレストになった時」 = **持ち主を
      修飾していない** ので 相手キャラをレストにした場合も発動する (docs/official_rulings.md の
      一般則: 「相手の」 が無ければ両陣営)。 修飾されているのは 「自分の効果で」 の方。
    """
    repo, overlay = _repo(), _overlay()

    def run_cost_rest():
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        barto = InPlay.of(repo.get("OP07-031"), sickness=False)
        grad = InPlay.of(repo.get("OP05-025"), sickness=False)  # 【起動メイン】自レスト：相手をレスト
        me.characters = [barto, grad]
        me.hand = [repo.get(_FILLER)] * 3
        opp.characters = []                       # 相手対象なし = コスト由来レストだけを見る
        d0, h0 = len(me.deck), len(me.hand)
        effs = [(ip, e) for ip, e in list_activate_main_effects(st, me, overlay) if ip is grad]
        assert effs, "グラディウスの【起動メイン】が候補に出ていない (前提崩れ)"
        fire_activate_main(st, me, opp, grad, effs[0][1])
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
        resolve_triggers(st)
        assert grad.rested, "コストの自レストが払われていない (前提崩れ)"
        return d0 - len(me.deck), len(me.hand) - h0

    drew, hand_delta = run_cost_rest()
    assert drew == 1 and hand_delta == 0, (
        "【起動メイン】のコストでレストになった時に バルトロメオが発動していない "
        f"(引いた={drew} / 手札増減={hand_delta}、 公式は 1 引いて 1 捨てる)"
    )

    # 相手キャラを 自分の効果で レストにした場合 (= 「キャラが」 修飾なし → 両陣営)
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP07-031"), sickness=False)]
    me.hand = [repo.get(_FILLER)] * 3
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]
    d0 = len(me.deck)
    execute_effect({"rest": "one_opponent_character_any"}, st, me, opp, None)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    resolve_triggers(st)
    assert opp.characters[0].rested, "相手キャラがレストになっていない (前提崩れ)"
    assert d0 - len(me.deck) == 1, (
        "相手キャラを 自分の効果で レストにした時に発動していない "
        "(公式テキストは 「キャラが」 = 持ち主無修飾 → 両陣営)"
    )


def test_ko_triggers_resolve_before_effects_they_spawn():
    """1 回の KO から **同時に発動する** 効果は、 その解決中に新しく誘発した効果より必ず先に発動する。

    一次情報 (cardqa_op_10、 OP10-042 ウソップ(L)【相手のターン中】自分の《ドレスローザ》キャラが
    KO された時 1 ドロー × OP10-090 フランキー【KO時】トラッシュから《ドレスローザ》を登場 ×
    登場した OP04-092 レベッカ【登場時】デッキ上3枚サーチ):
      Q「フランキーの【KO時】効果をリーダーの効果よりも先に発動してレベッカを登場させました。
        この場合、 リーダーの【相手のターン中】効果とレベッカの【登場時】はどちらが先ですか？」
      → A「このリーダーの【相手のターン中】効果が、 【KO時】効果で登場したキャラの【登場時】効果
        よりも、 **必ず先に発動します**」

    退行前は `trigger_on_ko` と `trigger_on_*_chara_ko` が **1 つ enqueue するたびにドレイン** して
    いたため、 リーダーの効果が enqueue される前に フランキーの【KO時】が走り切り、 そこで登場した
    レベッカの【登場時】まで解決されていた。

    検証は 「どちらがデッキの先頭を取るか」 で行う: デッキ先頭にだけ《ドレスローザ》を置くと、
      正: リーダーがドローで先頭を取る → レベッカは非対象3枚を見て 0 枚取得 → 手札 1 枚
      誤: レベッカが先に先頭を手札へ + リーダーが 4 枚目をドロー → 手札 2 枚
    """
    repo, overlay = _repo(), _overlay()
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    filler = next(cid for cid, c in cards.items()
                  if c.get("category") == "CHARACTER" and "ドレスローザ" not in (c.get("features") or ""))
    dressrosa = next(cid for cid, c in cards.items()
                     if c.get("category") == "CHARACTER"
                     and "ドレスローザ" in (c.get("features") or "") and c["name"] != "レベッカ")

    st = _state(repo, overlay, leader0="OP10-042")
    st.turn_player_idx = 1                       # 相手のターン中
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("OP10-090"), sickness=False)
    me.characters = [franky]
    me.trash = [repo.get("OP04-092")]            # フランキーが登場させる レベッカ
    me.hand = []
    me.deck = [repo.get(dressrosa)] + [repo.get(filler)] * 10
    attacker = InPlay.of(repo.get("EB01-018_p1"), sickness=False)   # power7000 バニラ
    opp.characters = [attacker]

    apply_action(st, AttackCharacter(attacker_iid=attacker.instance_id,
                                     target_iid=franky.instance_id), overlay)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])

    assert any(c.card.card_id == "OP04-092" for c in me.characters), \
        "フランキーの【KO時】でレベッカが登場していない (前提崩れ)"
    assert [c.card_id for c in me.hand] == [dressrosa], (
        "リーダー効果が 【KO時】で登場したキャラの【登場時】より後に解決している "
        f"(手札={[c.card_id for c in me.hand]}、 公式はリーダーのドロー 1 枚だけ)"
    )


def test_ko_victim_context_survives_deferred_resolution():
    """KO の victim 文脈 (「元々のパワーN以上」 等) は **解決を遅らせても** 失われない。

    KO グループを 「全部 enqueue してから解決」 に変えた時 (上記 cardqa_op_10)、 victim 文脈を
    transient な state に置いたままだと 解決時には既に消えていて、
    OP14-041 ボア・ハンコック 「【ドン‼×1】【ターン1回】自分の**元々のパワー5000以上**の、
    特徴《アマゾン・リリー》か《九蛇海賊団》を持つキャラがKOされた時、 相手のライフの上から1枚
    までを、 持ち主の手札に加える」 が **丸ごと不発** になった (Rust 差分ハーネスが検出)。
    → victim は イベントの payload に載せて運ぶ。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP14-041")
    st.turn_player_idx = 1                       # 相手のターン (ハンコックは【相手のターン中】でない
                                                 #  = 条件は don/victim のみ) だが KO は相手が起こす
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1                  # 【ドン‼×1】
    victim = InPlay.of(repo.get("OP14-114"), sickness=False)   # 九蛇海賊団 / 元々パワー5000以上
    assert int(repo.get("OP14-114").power or 0) >= 5000, "victim の印刷パワー前提が崩れている"
    me.characters = [victim]
    opp.life = [repo.get(_FILLER)] * 3
    opp.hand = []
    attacker = InPlay.of(repo.get("EB01-018_p1"), sickness=False)
    opp.characters = [attacker]
    life_before, hand_before = len(opp.life), len(opp.hand)

    apply_action(st, AttackCharacter(attacker_iid=attacker.instance_id,
                                     target_iid=victim.instance_id), overlay)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])

    assert len(opp.life) == life_before - 1 and len(opp.hand) == hand_before + 1, (
        "ハンコックの 「元々のパワー5000以上のキャラがKOされた時」 が発動していない "
        f"(相手ライフ {life_before}→{len(opp.life)} / 手札 {hand_before}→{len(opp.hand)}) "
        "= victim 文脈が遅延解決で失われている"
    )


def test_op01_013_sanji_activation_cost_is_life_not_rest():
    """OP01-013 サンジ の【起動メイン】は **ライフ1枚を手札に加える** のがコスト (レストではない)。

    公式テキスト逐語: 「【起動メイン】【ターン1回】自分のライフ1枚を手札に加えることができる：
    このキャラは、 このターン中、 パワー+2000。 その後、 このキャラにレストのドン‼**2枚まで**を付与する。」

    ⚠ 2026-08-11 是正。 旧 overlay は
      - cost が **公式に存在しない `rest_self`**、 本来の発動コスト (ライフ→手札) は `do` に落ちていた
        → **ライフ0でもタダ撃ち** できた (「できる：」 の前は発動コスト)
      - `attach_rested_don{count:2}` が **6 回重複** → レストのドンが潤沢だと **12 枚付与**
        (実測パワー 17000、 公式は 2 枚 = 7000)
    """
    repo, overlay = _repo(), _overlay()

    def run(life_n: int, rested_don: int):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
        me.characters = [sanji]
        me.life = [repo.get(_FILLER)] * life_n
        me.hand = []
        me.don_active, me.don_rested = 0, rested_don
        effs = [(ip, e) for ip, e in list_activate_main_effects(st, me, overlay) if ip is sanji]
        if not effs:
            return None
        fire_activate_main(st, me, opp, sanji, effs[0][1])
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
        resolve_triggers(st)
        return sanji, me

    # ライフ 0 → 発動コストを払えない = 起動メインの候補に出ない
    assert run(0, 12) is None, "ライフ0でも【起動メイン】が撃てている (= 発動コストが do に落ちている)"

    sanji, me = run(3, 12)
    assert not sanji.rested, "公式に無い 「レストにする」 コストを取っている"
    assert len(me.life) == 2 and len(me.hand) == 1, (
        f"ライフ1枚を手札に加える発動コストが払われていない (life={len(me.life)} hand={len(me.hand)})"
    )
    assert sanji.attached_dons == 2, (
        f"レストのドンが 2 枚でない: {sanji.attached_dons} 枚 "
        "(= attach_rested_don の重複)"
    )
    assert sanji.power == 3000 + 2000 + 2000, (
        f"パワーが 印刷3000 + 効果+2000 + ドン2枚 = 7000 でない: {sanji.power}"
    )


def test_op10_116_and_st07_003_scry_life_is_not_omitted():
    """「自分か相手のライフの上から1枚までを見て、 ライフの上か下に置く」 は省略できない。

    同文のカードは 7 枚が `scry_life` で実装済だったが、 **OP10-116 電磁砲** と
    **ST07-003 シャーロット・カタクリ** だけ overlay から丸ごと落ちていた (2026-08-11 是正)。
    ライフの順序を変える実効果なので 「その後」 の本体だけ実装するのは公式テキスト忠実主義に反する。

    ⚠ ST07-003 は **条件の位置** も誤っていた。 公式は 「…見て、 ライフの上か下に置く。 **その後**、
      自分のライフの枚数が相手より少ない場合、 …【速攻】を得る」 = scry は無条件で、 条件が掛かるのは
      【速攻】付与だけ。 旧 overlay は effect 全体を gate しており、 ライフが相手以上だと
      **scry ごと不発** だった。
    """
    repo, overlay = _repo(), _overlay()
    for cid in ("OP10-116", "ST07-003"):
        prims = {k for e in overlay.get(cid).effects for p in (e.get("do") or []) for k in p}
        assert "scry_life" in prims, f"{cid} に scry_life が無い (公式テキストの前半が欠落)"

    # ST07-003: 速攻の条件を満たさなくても scry は走る
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4
    opp.life = [repo.get(_FILLER)] * 2          # 自ライフ > 相手 = 速攻の条件は不成立
    kata = InPlay.of(repo.get("ST07-003"), sickness=True)
    me.characters = [kata]
    log_before = len(st.log)
    trigger_on_play(st, me, opp, kata, overlay)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    resolve_triggers(st)
    assert any("ライフ上" in l for l in st.log[log_before:]), (
        "速攻の条件が不成立だと scry ごと不発になっている (= 条件が effect 全体に掛かっている)"
    )
    assert "速攻" not in (kata.granted_keywords or []), "条件不成立なのに【速攻】が付いている"


def test_trigger_cannot_be_activated_when_cost_unpayable():
    """発動コストを払えない【トリガー】は **発動できない** (= カードは手札に加わる)。

    公式 (総合ルール 10-1-5 + 4-10): 【トリガー】は 「公開して効果を発動する」 か 「手札に加える」 かの
    選択で、 発動を選べるのは **効果を発動できる時だけ**。 コストを払えないなら発動できない。

    退行前は 発動可否判定が `if` 条件しか見ておらず **コストの payability を見ていなかった** ため、
    「ドン‼-2：このカードを登場させる」 (OP04-064 ミス・オールサンデー) を **ドン 0 でも発動宣言** でき、
    カードはライフを離れてトラッシュへ行き、 支払いに失敗して **何も起きずにカードだけ失う** 状態だった。
    """
    from engine.effects import should_fire_trigger, trigger_lifecard_trigger
    repo, overlay = _repo(), _overlay()

    def run(don: int):
        st = _state(repo, overlay)
        me, opp = st.players[1], st.players[0]   # me = defender (ライフを取られた側)
        me.don_active, me.don_rested = don, 0
        me.life, me.characters, me.trash, me.hand = [], [], [], []
        want = should_fire_trigger(st, me, repo.get("OP04-064"), overlay)
        fired = trigger_lifecard_trigger(st, me, opp, repo.get("OP04-064"), overlay, auto_fire=True)
        resolve_triggers(st)
        return want, fired

    want0, fired0 = run(0)
    assert want0 is False and fired0 is False, (
        "ドンを払えないのに【トリガー】を発動宣言している "
        f"(should_fire={want0} / fired={fired0}) = カードを無駄に失う"
    )
    want10, fired10 = run(10)
    assert want10 is True and fired10 is True, (
        f"払える時に発動できていない (should_fire={want10} / fired={fired10})"
    )


def test_op08_114_don_gated_static_is_implemented():
    """OP08-114 S-ホーク の【ドン‼×1】静的効果 (斬耐性 + パワー+2000) が実装されている。

    公式: 「【ドン‼×1】自分のライフの枚数が相手より少ない場合、 このキャラは属性(斬)を持つ
    カードとのバトルでKOされず、 このキャラのパワー+2000。」
    ⚠ 2026-08-11 まで overlay に **trigger entry しか無く**、 静的効果が丸ごと欠落していた。
      全カード掃引で 「【ドン‼×N】の静的効果があるのに on_attached_don entry が無い」 のは
      このカードだけ = 孤立。
    """
    repo, overlay = _repo(), _overlay()

    def run(don: int, my_life: int, opp_life: int):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        h = InPlay.of(repo.get("OP08-114"), sickness=False)
        h.attached_dons = don
        me.characters = [h]
        me.life = [repo.get(_FILLER)] * my_life
        opp.life = [repo.get(_FILLER)] * opp_life
        evaluate_static_effects(st, overlay)
        return h

    h = run(1, 1, 3)   # ドン1 + 自ライフ < 相手
    assert h.power == 5000 + 1000 + 2000, f"+2000 が乗っていない: {h.power}"
    assert "斬" in (h.ko_immune_battle_attributes_in or set()), "斬とのバトル KO 耐性が無い"
    h2 = run(1, 3, 1)  # ライフ条件を満たさない
    assert h2.power == 5000 + 1000 and not h2.ko_immune_battle_attributes_in, \
        "ライフ条件を満たさないのに効果が乗っている"
    h3 = run(0, 1, 3)  # ドン無し
    assert h3.power == 5000 and not h3.ko_immune_battle_attributes_in, \
        "【ドン‼×1】の gate が効いていない"


def test_scry_all_life_reorder_honors_owner():
    """「**相手の**ライフすべてを見て、 好きな順番で置く」 は相手のライフを並び替える。

    ⚠ 2026-08-11 是正: `owner` キーが **完全に無視** されており、 EB01-052 ヴィオラ
    (「相手のライフ…」) が **自分のライフを並び替えて** いた。 使用カードは 2 枚だけで、
    ST13-012 マキノ (「自分のライフ…」) は owner 既定 = self。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016"), repo.get("OP01-022"), repo.get(_FILLER)]
    opp.life = [repo.get("OP01-025"), repo.get("OP01-024"), repo.get(_FILLER)]
    mine_before = [c.card_id for c in me.life]
    execute_effect({"scry_all_life_reorder": {"owner": "opp"}}, st, me, opp, None)
    assert [c.card_id for c in me.life] == mine_before, \
        "owner=opp なのに **自分の** ライフが並び替えられている"

    # EB01-052 の選択肢② (自ライフすべて裏向き) が no-op でないこと
    bundle = overlay.get("EB01-052")
    opts = bundle.effects[0]["do"][0]["choice_effect"]["options"]
    assert all(o["do"] for o in opts), "選択肢に do:[] の no-op が残っている"


def test_ko_victim_original_power_uses_rewritten_value():
    """【KO時】系の 「元々のパワーN以上」 は **KO 時点の (書き換わった) 元々のパワー** で判定する。

    一次情報 (cardqa_op_14、 OP14-053 ビスタ 「【相手のターン中】自分の手札が7枚以下の場合、
    このキャラの元々のパワーは、 自分のリーダーの元々のパワーと同じパワーになる」 ×
    リーダー OP13-002 エース 「【ドン‼×1】…自分の**元々のパワー6000以上**のキャラがKOされた時、
    カード1枚を引く」):
      Q「…元々のパワーが6000の状態でKOされたことになり、 …カードを引くことはできますか？」
      → 「**はい、 できます**」

    退行前は 2 つの違反があった:
      ① `set_base_power_copy` が **コピー元も現在パワー** で写しており、 公式 「自分のリーダーの
         **元々の** パワーと同じ」 に反して リーダーの付与ドンぶんまで乗っていた (元々6000 → 7000)。
      ② `victim_truly_original_power_ge` が victim の **印刷値** を見ており、 書き換えを無視していた。
    """
    repo, overlay = _repo(), _overlay()

    from engine.effects import trigger_on_ko, trigger_on_self_chara_ko

    def run(hand_n: int):
        st = _state(repo, overlay, leader0="OP13-002")
        me, opp = st.players[0], st.players[1]
        st.turn_player_idx = 1               # 相手のターン中
        me.leader.attached_dons = 1          # 【ドン‼×1】
        me.hand = [repo.get(_FILLER)] * hand_n
        bista = InPlay.of(repo.get("OP14-053"), sickness=False)
        me.characters = [bista]
        evaluate_static_effects(st, overlay)
        top = bista.truly_original_power
        deck0 = len(me.deck)
        me.characters.remove(bista)
        me.trash.append(bista.card)
        trigger_on_ko(st, me, opp, bista.card, overlay, by_opp_effect=True,
                      victim_attached_don=0, victim_truly_original_power=top)
        trigger_on_self_chara_ko(st, me, opp, overlay, victim_card=bista.card)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        return top, deck0 - len(me.deck)

    top, drew = run(3)     # 手札7以下 = 元々のパワーが書き換わる
    assert top == 6000, (
        f"コピー元が 「元々のパワー」 になっていない: {top} "
        "(リーダーの現在パワー = 付与ドン込み を写している)"
    )
    assert drew == 1, "書き換わった元々のパワー6000 で【KO時】ドローが発動していない"

    top2, drew2 = run(9)   # 手札8枚以上 = 書き換わらない (印刷 4000)
    assert top2 == 4000 and drew2 == 0, \
        f"書き換えが無い時に発動している (元々={top2} / 引いた={drew2})"


def test_original_power_rewrite_takes_highest_value():
    """「元々のパワーを◯◯にする」 が複数適用されたら **最も高い値** (公式 4-9-2-1)。

    一次情報 (総合ルール 4-9-2-1 逐語 + cardqa_st_34 / ST34-004 シャーロット・リンリン
    「相手のキャラ1枚までを、 このターン中、 元々のパワー0にする」):
      Q「選んだ相手のキャラが 「元々のパワー6000にする」 などの他の効果で元々のパワーを変更されて
        いる場合、 そのキャラの元々のパワーはどうなりますか？」
      → 「同じキャラに適用されている元々のパワーを変更する効果のうち、 **最も高い値** である
        元々のパワーに適用されます」

    退行前は **後勝ち (last-wins)** で、 後から掛けた 0 が 6000 を潰していた。
    ⚠ 素の 「パワーが◯◯になる」 (= 「元々の」 が無い) は 4-9-2-1 の対象外 = 後勝ちのまま。
    """
    repo, overlay = _repo(), _overlay()

    def apply(order, original: bool):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        v = InPlay.of(repo.get("OP01-016"), sickness=False)
        opp.characters = [v]
        for amt in order:
            execute_effect({"set_base_power_timed": {
                "target": "one_opponent_character_any", "amount": amt,
                "duration": "turn", "original": original}}, st, me, opp, None)
            while st.pending_choice is not None:
                resolve_pending_choice(st, [0])
        return v

    assert apply([6000, 0], True).truly_original_power == 6000, "後から掛けた 0 が 6000 を潰している"
    assert apply([0, 6000], True).truly_original_power == 6000, "高い方が適用されていない"
    # 対照: 素の 「パワーになる」 は 4-9-2-1 の対象外
    assert apply([6000, 0], False).power == 0, "original=False まで max になっている (対象外のはず)"


def test_chara_only_feature_condition_requires_at_least_one():
    """「自分のキャラが特徴《X》を持つキャラ **のみの場合**」 は **キャラ0枚では成立しない**。

    一次情報 (cardqa_op_16 / OP16-022 ルフィ): 「自分のキャラが0枚の時、 この【起動メイン】効果で
    ドン‼をアクティブにできますか？」 → 「**いいえ、 できません**」
    (cardqa_eb_03 / EB03-038 ごち♡ も同旨: 「自分の場にキャラが0枚の場合、 …ドン‼2枚までを
     レストで追加することはできますか？」 → 「**いいえ**」)

    退行前は 空集合を vacuous True にしており、 キャラ0枚でも成立していた。
    同型条件を使う 6 枚 (EB02-010 / OP05-084 / OP05-092 / OP16-022 / EB03-038 / OP11-043) に効く。
    """
    repo, overlay = _repo(), _overlay()
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    jerma = next(cid for cid, c in cards.items()
                 if c.get("category") == "CHARACTER" and "ジェルマ" in "".join(c.get("features") or ""))
    st = _state(repo, overlay)
    me = st.players[0]

    me.characters = []
    assert eval_condition({"self_chara_only_feature_contains": "ジェルマ"}, st, me, None) is False, \
        "キャラ0枚で 「〜のみの場合」 が成立している"
    me.characters = [InPlay.of(repo.get(jerma), sickness=False)]
    assert eval_condition({"self_chara_only_feature_contains": "ジェルマ"}, st, me, None) is True, \
        "該当キャラのみなのに成立していない"
    me.characters.append(InPlay.of(repo.get(_FILLER), sickness=False))
    assert eval_condition({"self_chara_only_feature_contains": "ジェルマ"}, st, me, None) is False, \
        "非該当が混ざっているのに成立している"


def test_op04_081_mill_after_ko_is_not_omitted():
    """OP04-081 キャベンディッシュ の 「その後、 自分のデッキの上から2枚をトラッシュに置く」 は必須。

    公式 (cardqa_op_04): 「この【アタック時】効果を発動し、 自分のデッキのカードをトラッシュに
    置かないことはできますか？」 → 「**いいえ、 できません**」
    ⚠ 2026-08-11 まで overlay から **丸ごと欠落** していた (KO しか実装が無かった)。
      コロン前が発動コストなので mill は `optional_cost_then` の effect 末尾 = 払わなければ起きない。
      掃引で同型は OP04-081 / OP04-091 の 2 枚のみ。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP04-081"), sickness=False)
    c.attached_dons = 1
    me.characters = [c]
    v = InPlay.of(repo.get("OP01-016"), sickness=False)
    v.base_cost_override = 1
    opp.characters = [v]
    deck0, trash0 = len(me.deck), len(me.trash)
    trigger_on_attack(st, me, opp, c, overlay)
    resolve_triggers(st)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
        resolve_triggers(st)
    assert not opp.characters, "コスト1以下の相手キャラが KO されていない (前提崩れ)"
    assert len(me.deck) == deck0 - 2 and len(me.trash) == trash0 + 2, (
        f"「その後 デッキ上2枚をトラッシュ」 が実行されていない "
        f"(deck {deck0}→{len(me.deck)} / trash {trash0}→{len(me.trash)})"
    )


def test_op15_003_activate_main_requires_payable_cost():
    """「相手のキャラ1枚に相手のレストのドン‼1枚を付与できる：」 は **発動コスト**。

    一次情報 (cardqa_op_15 / OP15-003 アルビダ): 「相手のキャラが0枚のときや、 相手のレストの
    ドン‼が相手のコストエリアに無い時に、 この【起動メイン】効果で自分のリーダーやキャラに
    自分のドン‼を付与することはできますか？」 → 「**いいえ、 できません**」

    退行前は `_optional_cost_payable_in_do` が `attach_opp_don_to_opp_chara` を見ておらず、
    **発動できてしまい 何も起きないまま【ターン1回】だけ消費** していた。
    """
    repo, overlay = _repo(), _overlay()

    def n_options(opp_chara: int, opp_rested_don: int) -> int:
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        a = InPlay.of(repo.get("OP15-003"), sickness=False)
        me.characters = [a]
        me.don_rested = 3
        opp.characters = ([InPlay.of(repo.get("OP01-016"), sickness=False)]
                          if opp_chara else [])
        opp.don_rested = opp_rested_don
        return len([1 for ip, _e in list_activate_main_effects(st, me, overlay) if ip is a])

    assert n_options(0, 3) == 0, "相手キャラ0枚なのに【起動メイン】が出ている"
    assert n_options(1, 0) == 0, "相手のレストドン0なのに【起動メイン】が出ている"
    assert n_options(1, 3) == 1, "コストを払える時に【起動メイン】が出ていない"


def test_op10_119_attaches_don_only_to_supernova_leader():
    """OP10-119 ロー: 前半 (ライフに加える) はリーダーの特徴を問わず、 後半のドン付与だけが
    《超新星》リーダー限定。

    一次情報 (cardqa_op_10): 「自分のリーダーが特徴《超新星》を持たない場合、 この【登場時】効果で
    手札から特徴《超新星》を持つキャラカード1枚をライフに加えることはできますか？」 → 「**はい**」
    ⚠ 2026-08-11 まで **後半 「その後、 自分の特徴《超新星》を持つリーダー1枚にレストのドン‼1枚
      までを、 付与する」 が overlay から丸ごと欠落** していた。
    """
    repo, overlay = _repo(), _overlay()
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    sn_chara = next(cid for cid, c in cards.items()
                    if c.get("category") == "CHARACTER" and "超新星" in "".join(c.get("features") or ""))

    def run(leader_id: str):
        st = _state(repo, overlay, leader0=leader_id)
        me, opp = st.players[0], st.players[1]
        me.hand = [repo.get(sn_chara)]
        me.life = []
        me.don_rested = 3
        law = InPlay.of(repo.get("OP10-119"), sickness=True)
        me.characters = [law]
        trigger_on_play(st, me, opp, law, overlay)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        return len(me.life), me.leader.attached_dons

    life_n, don_n = run("PRB01-001")            # 超新星を持たないリーダー
    assert life_n == 1, "リーダーが超新星でないとライフに加えられていない (公式 はい)"
    assert don_n == 0, "超新星でないリーダーにドンが付与されている"
    life_n2, don_n2 = run("OP01-001")           # 超新星を持つリーダー
    assert life_n2 == 1 and don_n2 == 1, (
        f"超新星リーダーへの 「その後」 のドン付与が実行されていない (life={life_n2} don={don_n2})"
    )


# --------------------------------------------------------------------------- #
#  2026-08-11 #5 FAQ conformance バッチの回帰テスト
# --------------------------------------------------------------------------- #
def test_op07_002_power_to_zero_is_minus_of_current():
    """素の「パワー0にする」= 現在パワー分の固定マイナス (代入でない)。

    一次情報 (cardqa_op_07、 OP07-002 アイン × OP12-070 サンジ):
      「パワー8000のサンジを『0にする』とこのターン中 -8000され、 トラッシュのイベントが
       20枚になり元パワーが 9000 になると パワーは 1000 になる」。
    是正前は power_pump amount:-99999 で -90999 になっていた (公式は 1000)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    import json as _json
    cards = _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    ev = next(c["card_id"] for c in cards if c.get("category") == "EVENT")
    sanji = InPlay.of(repo.get("OP12-070"), sickness=False)
    opp.characters = [sanji]
    opp.trash = [repo.get(ev)] * 19
    from engine.game import _recompute_static
    from engine.effects import execute_effect
    _recompute_static(st)
    assert sanji.power == 8000, f"前提: サンジ @19 events = 8000 (実際 {sanji.power})"
    execute_effect({"power_pump": {"to_zero": True, "duration": "turn",
                                   "target": "one_opponent_character_any"}},
                   st, me, opp, None)
    _recompute_static(st)
    assert sanji.power == 0, f"アイン後 @19 events = 0 のはず (実際 {sanji.power})"
    opp.trash = [repo.get(ev)] * 20
    _recompute_static(st)
    assert sanji.power == 1000, (
        f"元パワーが 9000 に増えたら -8000 で 1000 のはず (実際 {sanji.power})。 "
        f"代入や -99999 だと 1000 にならない"
    )


def test_no_overlay_power_pump_uses_huge_negative_for_set_to_zero():
    """掃引: 素の「パワー0にする」 は to_zero で表現し、 -99999 の近似を残さない。"""
    import json as _json
    ov = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    offenders = []
    for cid, ents in ov.items():
        if not isinstance(ents, list):
            continue
        for e in ents:
            if not isinstance(e, dict):
                continue
            for prim in (e.get("do") or []):
                pp = prim.get("power_pump") if isinstance(prim, dict) else None
                if isinstance(pp, dict) and pp.get("amount") in (-99999, -9999):
                    offenders.append(cid)
    assert not offenders, f"power_pump の巨大マイナス近似が残っている: {offenders}"


def test_op10_032_replace_rest_requires_active_holder():
    """「代わりにこのキャラをレストにできる」 は holder が既レストだと置換できない。

    一次情報 (cardqa_op_10、 OP10-032 たしぎ):
      「このキャラがレストの時、 自分の緑のキャラが相手の効果で場を離れる場合に、
       代わりにこのキャラをレストにできますか？」 → 「いいえ、 できません」。
    """
    import json as _json
    from engine.effects import try_replace_ko
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    cards = _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    green = next(c["card_id"] for c in cards
                 if c.get("category") == "CHARACTER" and "緑" in (c.get("color") or "")
                 and c.get("name") != "たしぎ" and "_" not in c["card_id"])
    for rested, expect in [(False, True), (True, False)]:
        st = _state(repo, overlay)
        st.turn_player_idx = 1  # 相手ターン (by_opp_effect の離脱)
        me, opp = st.players[0], st.players[1]
        tashigi = InPlay.of(repo.get("OP10-032"), sickness=False)
        tashigi.rested = rested
        victim = InPlay.of(repo.get(green), sickness=False)
        me.characters = [tashigi, victim]
        _recompute_static(st)
        saved = try_replace_ko(st, me, opp, victim, overlay,
                               by_opp_effect=True, leave_kind="ko")
        assert saved is expect, (
            f"たしぎ rested={rested}: 置換={saved} 期待={expect} "
            f"(既レストなら救済不可 = 公式いいえ)"
        )


def test_st06_004_effect_ko_immune_survives_effect_ko():
    """ST06-004 スモーカー「このキャラは効果でKOされない」 は効果KOで生き残る。

    一次情報 (cardqa_st_06): 「このキャラは OP01-094 カイドウの【登場時】効果によって
    KOされますか？」 → 「いいえ、 KOされません」。
    """
    import json as _json
    from engine.effects import execute_effect
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    cards = _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    lead = next(c["card_id"] for c in cards if c.get("category") == "LEADER"
                and "百獣海賊団" in ((c.get("feature") or "") + "".join(c.get("features") or [])))
    st = _state(repo, overlay, leader0=lead)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP01-094"), sickness=False)]
    smoker = InPlay.of(repo.get("ST06-004"), sickness=False)
    plain = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [smoker, plain]
    _recompute_static(st)
    execute_effect({"conditional": {"do": [{"ko_all_others": True}],
                                    "if": {"leader_feature": "百獣海賊団"}}},
                   st, me, opp, me.characters[0])
    names = [c.card.name for c in opp.characters]
    assert "スモーカー" in names, f"効果KO耐性のスモーカーが KO されている: {names}"


def test_unconditional_effect_ko_immune_has_overlay_entry():
    """掃引: 無条件「このキャラは効果でKOされない」 は overlay で set_ko_immune を持つ。"""
    import json as _json
    cards = _json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    ov = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    offenders = []
    for c in cards:
        t = c.get("text") or ""
        if "このキャラは効果でKOされない" not in t:
            continue
        s = _json.dumps(ov.get(c["card_id"]), ensure_ascii=False)
        if "set_ko_immune" not in s and "prevent_ko" not in s:
            offenders.append(c["card_id"])
    assert not offenders, (
        f"無条件『効果でKOされない』なのに overlay に immune が無い: {offenders}"
    )


def test_replace_rest_self_in_do_is_gated_by_cost():
    """掃引: replace_ko/leave の do に「このキャラをレストにする」があるなら、

    cost に rest_self (払える判定 = holder がアクティブ) を必ず持つ。 これが無いと
    holder が既レストでも置換がタダで成立し、 場を離れるキャラを救済してしまう
    (OP10-032 たしぎ の違反)。 実レスト自体は do 側 (トリガー発火のため) に残す。
    """
    import json as _json
    ov = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    offenders = []
    for cid, ents in ov.items():
        if not isinstance(ents, list):
            continue
        for e in ents:
            if not isinstance(e, dict):
                continue
            if e.get("when") not in ("replace_ko", "replace_leave"):
                continue
            do = e.get("do") or []
            if not any(isinstance(p, dict) and p.get("rest") == "self" for p in do):
                continue
            cost = e.get("cost") or []
            if isinstance(cost, dict):
                cost = [cost]
            if not any(isinstance(c, dict) and c.get("rest_self") for c in cost):
                offenders.append(cid)
    assert not offenders, (
        f"replace の do に rest:self があるのに cost の rest_self ゲートが無い: {offenders}"
    )


def test_counter_events_apply_their_sonogo_clause():
    """【カウンター】の 「その後、 …」 は power_pump だけで終わらない。

    節カバレッジ監査 (`scripts/audit_text_clause_coverage.py`) が検出した 3 枚。 いずれも
    overlay に **power_pump しか無く**、 公式テキストの後半 (除去/バウンス) が丸ごと落ちていた:
      - ST06-014 衝撃波 「その後、 相手の **アクティブの** コスト3以下のキャラ1枚までを、 KOする」
      - OP07-055 蛇ダンス 「その後、 自分のキャラ1枚までを、 持ち主の手札に戻す」
      - OP07-094 剃 「その後、 自分のトラッシュが10枚以上ある場合、 自分の『CP』キャラ1枚までを戻す」
    """
    repo, overlay = _repo(), _overlay()
    from engine.effects import trigger_counter_event

    # ST06-014: アクティブのみが対象 (レストは残る)
    st = _state(repo, overlay)
    me, opp = st.players[1], st.players[0]
    st.turn_player_idx = 0
    active = InPlay.of(repo.get("OP01-016"), sickness=False)
    rested = InPlay.of(repo.get("OP01-016"), sickness=False)
    rested.rested = True
    opp.characters = [active, rested]
    trigger_counter_event(st, me, opp, repo.get("ST06-014"), overlay)
    resolve_triggers(st)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
        resolve_triggers(st)
    assert len(opp.characters) == 1 and opp.characters[0].rested, (
        "「その後」 の KO が実行されていない、 または **レストのキャラ** を誤って KO している"
    )

    # OP07-055: 自分のキャラが手札に戻る
    st2 = _state(repo, overlay)
    me2, opp2 = st2.players[1], st2.players[0]
    st2.turn_player_idx = 0
    me2.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]
    me2.hand = []
    trigger_counter_event(st2, me2, opp2, repo.get("OP07-055"), overlay)
    resolve_triggers(st2)
    while st2.pending_choice is not None:
        resolve_pending_choice(st2, [0])
        resolve_triggers(st2)
    assert not me2.characters and len(me2.hand) == 1, "「その後」 の手札バウンスが実行されていない"

    # OP07-094: トラッシュ10枚以上でのみ戻る
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    cp = next(cid for cid, c in cards.items()
              if c.get("category") == "CHARACTER" and "CP" in "".join(c.get("features") or ""))

    def run_cp(trash_n: int) -> int:
        st3 = _state(repo, overlay)
        me3, opp3 = st3.players[1], st3.players[0]
        st3.turn_player_idx = 0
        me3.trash = [repo.get(_FILLER)] * trash_n
        me3.characters = [InPlay.of(repo.get(cp), sickness=False)]
        me3.hand = []
        trigger_counter_event(st3, me3, opp3, repo.get("OP07-094"), overlay)
        resolve_triggers(st3)
        while st3.pending_choice is not None:
            resolve_pending_choice(st3, [0])
            resolve_triggers(st3)
        return len(me3.characters)

    assert run_cp(9) == 1, "トラッシュ9枚で条件を満たさないのに戻している"
    assert run_cp(10) == 0, "トラッシュ10枚で 「その後」 のバウンスが実行されていない"


def test_static_cost_modifiers_are_implemented():
    """「このキャラのコスト+N」 / 「手札のこのカードは…コスト-N」 の静的コスト修正。

    節カバレッジ監査 (`scripts/audit_text_clause_coverage.py`) が検出した 3 枚。 いずれも
    公式テキストの当該節が overlay から **丸ごと落ちていた**:
      - OP15-088 パイレーツドッキング6 「このキャラのコスト+6」 (印刷5 → 実効11)
      - OP12-042 アルビダ 「自分の**元々の**コスト5以上のキャラが2枚以上いる場合、 コスト+1」
      - ST23-002 シャンクス 「手札のこのカードは、 相手の**元々の**パワー8000以上のキャラが
        いる場合、 コスト-3」
    """
    repo, overlay = _repo(), _overlay()
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}

    # OP15-088: 無条件 +6
    st = _state(repo, overlay)
    me = st.players[0]
    c = InPlay.of(repo.get("OP15-088"), sickness=False)
    me.characters = [c]
    evaluate_static_effects(st, overlay)
    assert c.base_cost == int(c.card.cost) + 6, (
        f"「このキャラのコスト+6」 が効いていない: {c.base_cost} (印刷 {c.card.cost})"
    )

    # OP12-042: 元々コスト5以上が2枚以上いる時だけ +1
    cost5 = next(cid for cid, cc in cards.items()
                 if cc.get("category") == "CHARACTER" and str(cc.get("cost")) == "5")

    def albida_cost(n_big: int) -> int:
        st2 = _state(repo, overlay)
        me2 = st2.players[0]
        a = InPlay.of(repo.get("OP12-042"), sickness=False)
        me2.characters = [a] + [InPlay.of(repo.get(cost5), sickness=False) for _ in range(n_big)]
        evaluate_static_effects(st2, overlay)
        return a.base_cost

    assert albida_cost(0) == 4, "条件を満たさないのにコストが上がっている"
    assert albida_cost(2) == 5, "元々コスト5以上が2枚いるのに コスト+1 が効いていない"

    # ST23-002: 手札コスト-3 の条件 (元々のパワー基準)
    st3 = _state(repo, overlay)
    me3, opp3 = st3.players[0], st3.players[1]
    weak = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp3.characters = [weak]
    assert eval_condition({"exists_opp_chara_truly_original_power_ge": 8000},
                          st3, me3, None) is False
    weak.base_power_override = 9000
    weak.base_power_override_is_original = True
    assert eval_condition({"exists_opp_chara_truly_original_power_ge": 8000},
                          st3, me3, None) is True, (
        "「元々のパワー」 を書き換えた相手キャラが条件に反映されていない (公式 4-9-2-1)"
    )


def test_op07_091_trash_to_deck_pump_is_per_three():
    """OP07-091 ルフィ: 「置いた枚数 **3枚につき** パワー+1000」 (固定 +1000 ではない)。

    公式: 「【アタック時】相手のコスト2以下のキャラ1枚までをトラッシュに置く。 その後、 自分の
    トラッシュからコスト4以上のキャラカードを任意の枚数好きな順番でデッキの下に置く。
    **置いた枚数3枚につき**、 このキャラは、 このターン中、 パワー+1000。」

    ⚠ 2026-08-11 まで overlay は **トラッシュ→デッキ下が丸ごと欠落** し、 パンプも
      「置いた枚数に依らない固定 +1000」 だった (= 0 枚しか置けなくても +1000 された)。
    """
    repo, overlay = _repo(), _overlay()
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    cost4 = next(cid for cid, c in cards.items()
                 if c.get("category") == "CHARACTER" and str(c.get("cost")) == "4")

    def run(n_big: int):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        luffy = InPlay.of(repo.get("OP07-091"), sickness=False)
        me.characters = [luffy]
        # cost4 以上 n_big 枚 + 対象外 (cost1) 2 枚
        me.trash = [repo.get(cost4)] * n_big + [repo.get("OP01-016")] * 2
        v = InPlay.of(repo.get("OP01-016"), sickness=False)
        v.base_cost_override = 2
        opp.characters = [v]
        deck0, p0 = len(me.deck), luffy.power
        trigger_on_attack(st, me, opp, luffy, overlay)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        return len(me.deck) - deck0, luffy.power - p0, len(me.trash)

    moved, gain, trash_left = run(2)
    assert moved == 2 and gain == 0, f"2枚では +0 のはず (置いた={moved} 上昇={gain})"
    assert trash_left == 2, "対象外 (コスト4未満) のカードまでデッキに戻している"
    moved, gain, _ = run(3)
    assert moved == 3 and gain == 1000, f"3枚で +1000 のはず (置いた={moved} 上昇={gain})"
    moved, gain, _ = run(7)
    assert moved == 7 and gain == 2000, f"7枚で +2000 のはず (置いた={moved} 上昇={gain})"


def test_damage_dealt_trigger_fires_once_per_attack():
    """「相手のライフに **ダメージを与えた時**」 は 1 アタックにつき **1 回**。

    一次情報 (cardqa_op_03): 「この 『相手のライフにダメージを与えた時』 の効果は、
    【ダブルアタック】を持つキャラが相手のライフに2ダメージを与えた時に2回発動できますか？」
    → 「**いいえ、 できません。 1回のみ**」

    【ダブルアタック】は 「このカードが与えるダメージは2になる」 = **1 つのダメージ事象** なので、
    ライフが 2 枚離れても attacker 側の when は 1 回だけ発火する。
    退行前は hit ごとに発火し、 OP03-041 ウソップ が 7 枚 → **14 枚** mill していた。

    ⚠ defender 側 (ライフが手札/トラッシュへ移動した時) は **カードごとの事象** なので毎 hit 発火。
    """
    repo, overlay = _repo(), _overlay()

    def milled(double: bool) -> int:
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        u = InPlay.of(repo.get("OP03-041"), sickness=False)
        u.attached_dons = 1          # 【ドン‼×1】
        u.turn_buff = 10000          # リーダーを確実に上回る
        if double:
            u.granted_keywords.add("ダブルアタック")
        me.characters = [u]
        me.deck = [repo.get(_FILLER)] * 40
        opp.life = [repo.get(_FILLER)] * 4
        deck0 = len(me.deck)
        apply_action(st, AttackLeader(attacker_iid=u.instance_id), overlay)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
        return deck0 - len(me.deck)

    assert milled(False) == 7, "通常アタックで 7 枚 mill されていない (前提崩れ)"
    assert milled(True) == 7, (
        "【ダブルアタック】で 2 回発動している "
        f"(mill={milled(True)} 枚、 公式は 1 回のみ = 7 枚)"
    )


def test_st13_003_face_up_life_goes_to_deck_bottom_and_blocks_trigger():
    """ST13-003 ルフィ(L): 表向きライフは **手札に加わる代わりにデッキの下** = 【トリガー】不発。

    一次情報 (cardqa_st_13): 「自分のリーダーがこのカードの場合、 自分の表向きのライフの
    【トリガー】効果は発動できますか？」 → 「**いいえ、 発動できません**」
    根拠: 【トリガー】は 「ライフを手札に加える代わりに公開して効果を発動する」 置換 (公式 10-1-5)。
    手札に加わらない (= デッキの下へ行く) なら その置換自体が起きない。

    ⚠ この再現には ライフの **per-card 表向きフラグ** が要る (2026-08-11 に移行)。
      「表向きは上から N 枚」 の近似では ST13-012 マキノ の並べ替えで壊れる。
    """
    import engine.effects as _E
    repo, overlay = _repo(), _overlay()
    _orig = _E.should_fire_trigger
    _E.should_fire_trigger = lambda *a, **k: True
    try:
        def run(leader_id: str, face_up: bool):
            st = _state(repo, overlay, leader1=leader_id)
            me, opp = st.players[0], st.players[1]
            atk = InPlay.of(repo.get("EB01-018_p1"), sickness=False)
            me.characters = [atk]
            opp.life = [repo.get("OP07-057")]      # 無条件 draw の【トリガー】持ち
            opp.life_face_up = [face_up]
            opp.deck = [repo.get(_FILLER)] * 20
            opp.hand, opp.trash = [], []
            evaluate_static_effects(st, overlay)
            deck0 = len(opp.deck)
            apply_action(st, AttackLeader(attacker_iid=atk.instance_id), overlay)
            while st.pending_choice is not None:
                resolve_pending_choice(st, [0])
            return len(opp.hand), len(opp.deck) - deck0, len(opp.trash)

        hand_n, deck_d, trash_n = run("ST13-003", True)
        assert (hand_n, deck_d, trash_n) == (0, 1, 0), (
            f"表向きライフがデッキの下に行っていない / トリガーが発動している "
            f"(hand={hand_n} deck差={deck_d} trash={trash_n})"
        )
        # 対照: 裏向きなら通常どおり【トリガー】が発動する
        hand_n2, deck_d2, trash_n2 = run("ST13-003", False)
        assert deck_d2 == -1 and trash_n2 == 1, "裏向きライフの【トリガー】まで止めている"
        # 対照: 通常リーダーなら表向きでも通常どおり
        hand_n3, deck_d3, _ = run("OP01-001", True)
        assert deck_d3 == -1, "ST13-003 以外のリーダーにまでルール置換が効いている"
    finally:
        _E.should_fire_trigger = _orig


def test_st13_003_blocks_life_to_hand_cost_payment():
    """ST13-003 下では 「ライフ1枚を **手札に加える**」 コストが **支払えない**。

    一次情報 (cardqa_st_13): ST13-012 マキノ 「【登場時】自分のライフの上か下から1枚を手札に
    加えることができる：自分のライフすべてを見て、 好きな順番で置く」 との相互作用
    → 「デッキの下に置くことはできますが、 **コストとして…支払えていない為、 何も起きません**」
    """
    repo, overlay = _repo(), _overlay()

    def run(leader_id: str, flags: list[bool]):
        st = _state(repo, overlay, leader0=leader_id)
        me, opp = st.players[0], st.players[1]
        me.life = [repo.get("OP01-016"), repo.get("OP01-022"), repo.get(_FILLER)]
        me.life_face_up = list(flags)
        me.hand, me.deck = [], [repo.get(_FILLER)] * 10
        evaluate_static_effects(st, overlay)
        makino = InPlay.of(repo.get("ST13-012"), sickness=True)
        me.characters = [makino]
        log0, deck0 = len(st.log), len(me.deck)
        trigger_on_play(st, me, opp, makino, overlay)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        reordered = any("並べ替え" in l for l in st.log[log0:])
        return len(me.hand), len(me.deck) - deck0, reordered

    hand_n, deck_d, reordered = run("ST13-003", [True, True, True])
    assert hand_n == 0 and deck_d == 1, "表向きライフがデッキの下に行っていない"
    assert not reordered, (
        "コストを支払えていないのに効果 (ライフの並べ替え) が実行されている "
        "(公式: 「何も起きません」)"
    )
    # 対照: 裏向きなら払えて効果も走る
    hand_n2, deck_d2, reordered2 = run("ST13-003", [False, False, False])
    assert hand_n2 == 1 and deck_d2 == 0 and reordered2, "裏向きライフでも払えなくなっている"


def test_st13_003_hard_life_cost_is_unpayable_and_moves_nothing():
    """ST13-003 下では 「ライフ1枚を手札に加える：」 型の **硬いコスト** は そもそも発動できない。

    ⚠ ST13-012 マキノ (「加えることが**できる**：」) との **書き分け**:
      公式 (cardqa_st_13) は マキノ について 「デッキの下に置くことはできますが、 コストとして
      支払えていない為、 何も起きません」 = **札は動く**。 一方 コロン前が任意でない硬いコストは
      公式 4-10 (支払えないコストは払えない) で **発動自体ができない** = 札も動かない。
      同じ 「ライフ→手札」 でも結果が違うので、 payability を一律にしてはいけない。
    """
    repo, overlay = _repo(), _overlay()

    def offers(leader_id: str, flags: list[bool]):
        st = _state(repo, overlay, leader0=leader_id)
        me = st.players[0]
        me.life = [repo.get(_FILLER)] * 3
        me.life_face_up = list(flags)
        evaluate_static_effects(st, overlay)
        nami = InPlay.of(repo.get("OP01-013"), sickness=False)   # 起動メイン: ライフ1枚を手札に
        me.characters = [nami]
        life0, hand0 = len(me.life), len(me.hand)
        opts = [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "OP01-013"]
        assert (len(me.life), len(me.hand)) == (life0, hand0), "列挙しただけで札が動いている"
        return len(opts)

    assert offers("ST13-003", [True, False, False]) == 0, (
        "表向きのライフを コストとして手札に加えられないのに 起動メインが発動可能になっている"
    )
    assert offers("ST13-003", [False, True, True]) == 1, (
        "上から取るのは 1 枚目 (裏向き) なので払えるはず"
    )
    assert offers("ST13-003", [False, False, False]) == 1, "裏向きだけなのに払えない"
    assert offers("OP01-001", [True, True, True]) == 1, (
        "ST13-003 以外のリーダーにまでルール置換が効いている"
    )


def test_st13_003_life_to_hand_effect_sends_face_up_to_deck_bottom():
    """効果 (コストでない) の 「自分のライフ1枚を手札に加える」 も同じルール置換を受ける。

    置換は 「ライフ→手札」 という **移動そのもの** にかかる (ST13-003 のテキスト)。
    ダメージ経路だけ直して効果経路を直さないと、 同じ移動が経路で違う結果になる。
    """
    repo, overlay = _repo(), _overlay()

    def run(leader_id: str, flags: list[bool]):
        st = _state(repo, overlay, leader0=leader_id)
        me = st.players[0]
        me.life = [repo.get(_FILLER)] * 2
        me.life_face_up = list(flags)
        me.hand, me.deck = [], [repo.get(_FILLER)] * 5
        evaluate_static_effects(st, overlay)
        execute_effect({"life_to_hand": 1}, st, me, st.players[1], None)
        return len(me.hand), len(me.deck), len(me.life)

    assert run("ST13-003", [True, False]) == (0, 6, 1), "表向きライフがデッキの下に行っていない"
    assert run("ST13-003", [False, True]) == (1, 5, 1), "裏向きライフまでデッキの下に行っている"
    assert run("OP01-001", [True, False]) == (1, 5, 1), "無関係なリーダーで置換が効いている"


def test_life_reorder_carries_face_up_flag_with_the_card():
    """ライフの **並べ替え** は表向きフラグをカードと一緒に動かす。

    ⭐ 2026-08-11 の per-card 化で顕在化した罠。 `pl.life = [...]` と書くと
    `Player.__setattr__` が `life_face_up` を全裏向きに張り直すので、 **表向きの札を
    並べ替えた瞬間に表向きが消える** (Rust 側は逆に古いフラグが残って位置がずれる)。
    どちらも 「表向きライフ」 を参照する効果 (ST13-003 のルール置換 / しらほし系の条件) に
    直撃するので、 位置ではなく **札** にフラグが付いていることを固定する。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    # 並べ替えキー = (トリガー有無, カウンター, パワー) 降順。
    #   OP01-025 (0/5000) < OP01-016 (1000/2000) < _FILLER=OP01-013 (2000/3000)
    #   → 表向きにした OP01-025 は **先頭から末尾へ動く** = 位置ベースなら必ず壊れる並び。
    me.life = [repo.get("OP01-025"), repo.get("OP01-016"), repo.get(_FILLER)]
    me.life_face_up = [True, False, False]
    face_up_card = me.life[0].card_id

    execute_effect({"scry_all_life_reorder": {"owner": "self"}}, st, me, st.players[1], None)

    assert len(me.life) == len(me.life_face_up) == 3, "並べ替えで枚数/フラグ数が壊れた"
    assert me.life[0].card_id != face_up_card, "テスト前提: 並べ替えで順番が変わること"
    up = [c.card_id for c, f in zip(me.life, me.life_face_up) if f]
    assert up == [face_up_card], (
        f"表向きフラグがカードに追随していない (表向き={up}, 期待={[face_up_card]})"
    )


def test_scry_life_keeps_face_up_card_face_up():
    """`scry_life` (上から N 枚を見て上か下に置く) でも表向きは札に追随する。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    # OP01-025 = カウンター 0 = 「不要札」 → 下へ / _FILLER = カウンター 2000 = 上へ。
    me.life = [repo.get("OP01-025"), repo.get(_FILLER)]
    me.life_face_up = [True, False]

    execute_effect({"scry_life": {"depth": 2, "owner": "self"}}, st, me, st.players[1], None)

    assert len(me.life) == len(me.life_face_up) == 2
    assert me.life[0].card_id == _FILLER, "テスト前提: 上下が入れ替わること"
    up = [c.card_id for c, f in zip(me.life, me.life_face_up) if f]
    assert up == ["OP01-025"], f"表向きフラグが別の札に移っている (表向き={up})"


# --------------------------------------------------------------------------- #
#  search_top_n destination=play の【登場時】は「その後、残りを置く」の後に発動する
#  一次情報 (cardqa_op_03 / 8fba21f82b0d、 OP03-094 空気開扉):
#    Q:「この【メイン】効果で登場したキャラの【登場時】効果は、この【メイン】効果の
#       『その後、残りをトラッシュに置く。』を行う前に発動しますか？」
#    A:「いいえ、残りのカードをトラッシュにおいた後に【登場時】効果が発動します。」
#  是正前: search_top_n が登場ループ内で即 trigger_on_play しており、 remaining を
#          トラッシュに置く **前** に登場時が解決していた (Python/Rust とも同じ誤り =
#          差分検証では沈黙)。
# --------------------------------------------------------------------------- #
def test_search_top_n_play_on_play_fires_after_remaining_to_trash():
    """登場したキャラの【登場時】は、残りをトラッシュに置いた後に発動する。

    観測方法: 登場キャラ A の【登場時】を「トラッシュからコスト2以下のキャラ1枚を登場」に
    差し替える。 A と一緒に見た残り4枚 (コスト2のキャラ) がトラッシュに置かれた後に A の
    登場時が走るなら、 その4枚のうち1枚を釣り上げられる。 是正前は登場時がトラッシュ化の
    前に走り、 (空トラッシュから) 何も釣れなかった。
    """
    from engine.effects import CardEffectBundle

    repo, overlay = _repo(), _overlay()
    A_ID = "OP02-042"   # ヤマト (キャラ)。 登場時を下記に差し替える
    T_ID = "OP01-013"   # コスト2キャラ (on_play なし = 釣り上げても再帰しない)
    # A の overlay を「登場時: トラッシュからコスト2以下のキャラ1枚を登場」に差し替え
    overlay = dict(overlay)
    overlay[A_ID] = CardEffectBundle(card_id=A_ID, effects=[{
        "when": "on_play",
        "do": [{"play_from_trash": {
            "filter": {"category": "CHARACTER", "cost_le": 2},
            "limit": 1, "rested": False,
        }}],
    }])

    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.trash = []                       # トラッシュは空から始める (= 釣り上げ元は remaining のみ)
    # デッキ上5枚 = [A, T, T, T, T]。 filter=name:ヤマト で A だけ拾い、 残り4枚の T を trash へ
    me.deck = [repo.get(A_ID)] + [repo.get(T_ID)] * 4 + me.deck

    execute_effect(
        {"search_top_n": {
            "depth": 5, "filter": {"name": "ヤマト"}, "limit": 1,
            "destination": "play", "rest_remain": "trash",
        }},
        st, me, opp, None,
    )
    resolve_triggers(st)

    played_a = [c for c in me.characters if c.card.card_id == A_ID]
    grabbed = [c for c in me.characters if c.card.card_id == T_ID]
    assert len(played_a) == 1, "A (ヤマト) が登場していない (前提が崩れている)"
    # ★ 是正の核心: remaining の T が先にトラッシュへ → A の登場時が 1 枚釣り上げる。
    #   是正前は登場時がトラッシュ化前に走り grabbed==0 で落ちる。
    assert len(grabbed) == 1, (
        "登場時が『残りをトラッシュに置く』前に走っている "
        f"(釣り上げ数={len(grabbed)}、 trash残={len(me.trash)})"
    )
    assert len(me.trash) == 3, f"trash に 3 枚残るはず (実際 {len(me.trash)})"


def test_opp_life_reorder_preserves_each_card_orientation():
    """EB01-052 ヴィオラ: **相手の**ライフを並べ替えても 表は表・裏は裏 のまま。

    一次情報 (cardqa_eb_01 / 8e1dae473363): 「この【登場時】効果で相手のライフすべてを見て
    順番を変える際、 表向きのライフは裏向きに戻しますか？」
    → 「**いいえ、 表向きのライフは表向きのまま、 裏向きのライフは裏向きのまま置きます**」

    ⚠ 旧モデル (表向き **枚数** だけを持つ) では原理的に再現できず escalated だった。
      per-card 化 (2026-08-11) 後は 「フラグが札に追随するか」 の問題になる。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # 相手ライフ並べ替えは 「弱い札を上」 = 昇順。 降順で置いて必ず並べ替えが起きるようにする。
    opp.life = [repo.get(_FILLER), repo.get("OP01-016"), repo.get("OP01-025")]
    opp.life_face_up = [True, False, True]
    before = {c.card_id: f for c, f in zip(opp.life, opp.life_face_up)}

    execute_effect({"scry_all_life_reorder": {"owner": "opp"}}, st, me, opp, None)

    after = [(c.card_id, f) for c, f in zip(opp.life, opp.life_face_up)]
    assert [c for c, _ in after] != list(before), "テスト前提: 並べ替えで順番が変わること"
    assert all(before[cid] == f for cid, f in after), (
        f"並べ替えで表裏が入れ替わっている (前={before} 後={after})"
    )


def test_face_up_count_is_derived_from_per_card_flags():
    """`face_up_life_count` は per-card フラグの **導出値** で、 単独では持たない。

    ⚠ 2026-08-11 の per-card 化で、 旧モデルの 2 本 (ライフ 0 なのに表向き 1 が残る /
      古いカウントが新しい裏向きライフを表向きにする) は **構造的に起こりえなく** なったので
      削除した。 その意図をこの 1 本に畳んで残す (= 削りっぱなしにしない)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)]
    me.life_face_up = [True]
    assert me.face_up_life_count == 1

    me.life.clear()
    me.life_face_up.clear()               # ライフが尽きた = フラグも一緒に消える
    evaluate_static_effects(st, overlay)
    assert me.face_up_life_count == 0, "ライフ 0 なのに表向きが残っている"

    me.life.append(repo.get(_FILLER))     # 効果でライフを積み直す (裏向き)
    me.life_face_up.append(False)
    evaluate_static_effects(st, overlay)
    assert me.face_up_life_count == 0, "新しく置いた裏向きのライフが表向き扱いになっている"

    # 書き込み専用の旧フィールドは残っていない (= 二重の真実を作らない)
    import pytest as _pytest
    with _pytest.raises(AttributeError):
        me.face_up_life_count = 3


# --------------------------------------------------------------------------- #
#  ライフを表/裏にするコストは 公式テキストの **位置指定** どおりに払う
#  (2026-08-12。 それまでは全部 「上から順に最初の該当」 = 位置無視だった)
# --------------------------------------------------------------------------- #
def test_flip_life_face_up_cost_targets_only_the_top_card():
    """「自分のライフの **上から** 1枚を表向きにできる：」 は 一番上が表向きなら払えない。

    一次情報 (cardqa_st_20 / ST20-001 カタクリ、 cardqa_op_10 / OP10-099 キッド):
    「自分のライフの一番上が表向きの場合、 この効果で…付与することはできますか？」 → 「いいえ」
    ⚠ 「表向きの札が 1 枚でもあるか」 ではなく **一番上そのもの** を見る。
    """
    repo, overlay = _repo(), _overlay()

    def offers(flags):
        st = _state(repo, overlay)
        me = st.players[0]
        me.life = [repo.get(_FILLER)] * len(flags)
        me.life_face_up = list(flags)
        evaluate_static_effects(st, overlay)
        me.characters = [InPlay.of(repo.get("ST20-001"), sickness=False)]
        return len([o for o in list_activate_main_effects(st, me, overlay)
                    if o[0].card.card_id == "ST20-001"])

    assert offers([False, False, False]) == 1, "一番上が裏向きなら払えるはず"
    assert offers([True, False, False]) == 0, (
        "一番上が既に表向きなのに発動できている (下段の裏向きを見てしまっている)"
    )
    assert offers([False, True, True]) == 1, "一番上が裏向きなら下段が表向きでも払える"


def test_flip_life_cost_top_or_bottom_uses_both_ends_only():
    """「自分のライフの **上か下から** 1枚を…」 (ST36-005 キッド) は **両端のみ**。

    一次情報 (cardqa_st_36): 「自分のライフの一番上と一番下がどちらも表向きの場合、
    この【起動メイン】効果を発動することはできますか？」 → 「いいえ」
    (= 中段が裏向きでも、 端が両方とも表向きなら 「表向きにする」 コストは払えない)
    """
    repo, overlay = _repo(), _overlay()

    def offers(flags):
        st = _state(repo, overlay)
        me = st.players[0]
        me.life = [repo.get(_FILLER)] * len(flags)
        me.life_face_up = list(flags)
        evaluate_static_effects(st, overlay)
        me.characters = [InPlay.of(repo.get("ST36-005"), sickness=False)]
        return len([o for o in list_activate_main_effects(st, me, overlay)
                    if o[0].card.card_id == "ST36-005"])

    assert offers([True, False, True]) == 0, (
        "上下とも表向きなのに発動できている (中段の裏向きを掴んでいる)"
    )
    assert offers([True, False, False]) == 1, "一番下が裏向きなら払えるはず"
    assert offers([False, True, True]) == 1, "一番上が裏向きなら払えるはず"


def test_flip_life_face_down_any_position_for_shanks():
    """「自分の **表向きのライフ** 1枚を裏向きにできる：」 (ST13-009) は **位置自由**。

    一次情報 (cardqa_st_13): 「この【登場時】効果で、 自分のライフの好きな位置にある
    表向きのカードを裏向きにすることはできますか？」 → 「**はい**」
    """
    repo, overlay = _repo(), _overlay()

    def run(flags):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        me.life = [repo.get(_FILLER)] * len(flags)
        me.life_face_up = list(flags)
        opp.hand = [repo.get(_FILLER)] * 8      # 相手の手札 7 枚以上 = 後文の条件
        opp.life = [repo.get(_FILLER)] * 3
        evaluate_static_effects(st, overlay)
        src = InPlay.of(repo.get("ST13-009"), sickness=True)
        me.characters = [src]
        trigger_on_play(st, me, opp, src, overlay)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        return list(me.life_face_up), len(opp.life)

    flags, opp_life = run([False, False, True])   # 表向きは **一番下** だけ
    assert flags == [False, False, False], f"下段の表向きを裏返せていない ({flags})"
    assert opp_life == 2, "コストを払えたのに後文 (相手ライフ1枚トラッシュ) が走っていない"

    flags2, opp_life2 = run([False, False, False])  # 表向きが 1 枚も無い = 払えない
    assert flags2 == [False, False, False]
    assert opp_life2 == 3, "表向きライフが無いのにコストを払えたことになっている"


#  FAQ conformance (2026-08-11 batch): コストエリアのドン付与 と 「相手の」条件スコープ
# --------------------------------------------------------------------------- #

def test_op15_028_attaches_from_active_don_in_cost_area():
    """cardqa_op_15 (qid 93d5946f56d6):
        「この【登場時】効果で、相手のアクティブのドン!!を付与することはできますか？」
        → 「はい、できます。アクティブかレストかに関わらず、コストエリアのドン‼を付与できます」

    OP15-028 ニャーバン兄弟【登場時】は「相手のコストエリアのドン‼1枚まで」を付与する。
    コストエリア = アクティブ/レスト問わず。 from_cost_area=true で active も source する。
    是正前は attach_rested_don が don_rested のみを見ており、 相手のドンが全て
    アクティブだと 0 枚しか付与できなかった (= タダ空振り)。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players
    raw = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    # 相手のコストエリアのドンは全てアクティブ (レスト 0) の状態
    opp.don_active = 2
    opp.don_rested = 0
    spec = raw["OP15-028"][0]["do"][0]  # {"attach_rested_don": {...}}
    assert "from_cost_area" in spec["attach_rested_don"]
    execute_effect(spec, st, me, opp, me.leader)
    assert victim.attached_dons == 1, victim.attached_dons
    # active ドンから source した (from_cost_area) → コストエリアの active が 1 減る
    assert opp.don_active == 1, opp.don_active
    assert opp.don_rested == 0, opp.don_rested


def test_cost_area_don_attach_cards_source_from_active_scan():
    """全走査ガード: テキストが「コストエリアのドン」を付与するカードは
    from_cost_area=true (= active も source) でなければならない。
    「レストのドン」明記カードは rested のみが正しい (from_cost_area 無しで可)。
    """
    overlay = _overlay()
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    byid = {c["card_id"]: c for c in (cards if isinstance(cards, list) else cards["cards"])}

    def attach_specs(entry):
        found = []
        def walk(o):
            if isinstance(o, dict):
                for kk, vv in o.items():
                    if kk == "attach_rested_don" and isinstance(vv, dict):
                        found.append(vv)
                    walk(vv)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(entry)
        return found

    offenders = []
    for cid, c in byid.items():
        t = c.get("text", "") or ""
        if "コストエリアのドン" not in t:
            continue
        for spec in attach_specs(overlay.get(cid) or []):
            if not spec.get("from_cost_area"):
                offenders.append(cid)
    assert not offenders, f"コストエリアのドン付与で from_cost_area 欠落: {sorted(set(offenders))}"


def test_op14_120_draw_condition_counts_only_opponent_characters():
    """cardqa_op_14 (qid 9493e614d556):
        「相手の場にコスト10以上のキャラだけがいる場合、この【登場時】効果で
         カード1枚を引くことはできますか？」→ 「はい、できます」

    OP14-120 クロコダイル: 「その後、**相手の**コスト0か8以上のキャラがいる場合、
    カード1枚を引く」= 相手陣営のみ数える。 是正前は両陣営を数える
    exists_chara_cost_0_or_ge_8 を使っており、 自分だけ該当キャラがいても引けてしまった。
    OP14-090/094 は「相手の」修飾が無く両陣営 = exists_chara_cost_0_or_ge_8 のまま。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players
    raw = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cond = raw["OP14-120"][0]["do"][1]["conditional"]["if"]
    assert "exists_opp_chara_cost_0_or_ge_8" in cond

    # 自分だけ cost8、 相手は cost3 のみ → 相手陣営に該当なし → 引けない
    me.characters = [InPlay.of(repo.get("EB04-003"), sickness=False)]   # base_cost 8
    opp.characters = [InPlay.of(repo.get("PRB02-004"), sickness=False)]  # base_cost 3
    assert eval_condition(cond, st, me) is False

    # 相手が cost8 (= 8以上) → 引ける (公式 Q&A の cost10 以上シナリオと同型)
    opp.characters = [InPlay.of(repo.get("EB04-003"), sickness=False)]   # base_cost 8
    assert eval_condition(cond, st, me) is True

    # OP14-090 (「相手の」無し) は両陣営を数える → 自分だけ cost8 でも True
    cond90 = raw["OP14-090"][0]["if"]
    assert "exists_chara_cost_0_or_ge_8" in cond90
    me.characters = [InPlay.of(repo.get("EB04-003"), sickness=False)]    # base_cost 8
    opp.characters = [InPlay.of(repo.get("PRB02-004"), sickness=False)]  # base_cost 3
    assert eval_condition(cond90, st, me) is True


def test_simultaneous_ko_replace_chain_tashigi_rosinante():
    """同時 KO の置換連鎖は 「持ち主が最も損しない順」 で解決できる (公式 cardqa_op_10)。

    Q: アクティブの OP10-032 たしぎ と OP05-030 ロシナンテ が同時に KO される時、
       たしぎ の効果で ロシナンテ が場を離れる代わりに たしぎ をレストにした。 さらに
       ロシナンテ の効果で、 今レストになった たしぎ が KO される代わりに ロシナンテ を
       トラッシュに置けますか？
    A: 「**はい、 できます。 この場合、 レストの『たしぎ』だけが場に残り、
       『ドンキホーテ・ロシナンテ』はトラッシュに置かれることになります**」

    ⚠ engine は victim を **盤面順** で処理していたので、 たしぎ が先だと
      「たしぎ が先にトラッシュ → ロシナンテ だけ助かる」 = **公式と逆** になり、
      公式の線が盤面の並び次第で到達不能だった。 並び順に依らないことまで固定する。
    """
    repo, overlay = _repo(), _overlay()

    def run(order, prim):
        st = _state(repo, overlay)
        me, opp = st.players[1], st.players[0]   # opp(=P0) が victim の持ち主
        st.turn_player_idx = 1                    # 相手 (P1) のターン中
        st.turn_number = 10
        ips = {"t": InPlay.of(repo.get("OP10-032"), sickness=False),
               "r": InPlay.of(repo.get("OP05-030"), sickness=False)}
        opp.characters = [ips[k] for k in order]
        evaluate_static_effects(st, overlay)
        execute_effect(prim, st, me, opp, None)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        return ([(c.card.name, c.rested) for c in opp.characters],
                [c.name for c in opp.trash])

    for prim in ({"ko_multi": ["all_opponent_characters"]},
                 {"ko": "all_opponent_characters"}):
        for order in (("t", "r"), ("r", "t")):
            board, trash = run(order, prim)
            assert board == [("たしぎ", True)], (
                f"{prim} 並び{order}: 場に残るのが 「レストのたしぎ」 でない ({board})"
            )
            assert trash == ["ドンキホーテ・ロシナンテ"], (
                f"{prim} 並び{order}: トラッシュが ロシナンテ でない ({trash})"
            )


def test_reveal_top_then_draw_includes_the_revealed_card():
    """「デッキの上から1枚を公開し…カード2枚を引く」 は **公開したカードを含めて** 引く。

    一次情報 (cardqa_st_17 / ST17-001 クロコダイル): 「その公開したカードはどうなりますか？」
    → 「**公開したカードを含めて** デッキの上から2枚のカードを引き、 その後自分の手札1枚を
       デッキの上に置きます」

    ⚠ 「公開し」 はカードを動かさない。 engine は公開カードを先にデッキから抜いてから
      then を実行していたので、 公開カードの **下 2 枚** を引いていた
      (ST17-001 / OP14-044 / ST22-003 / ST22-006 が同型)。
    """
    repo, overlay = _repo(), _overlay()
    WB = "OP07-119_r1"          # 『白ひげ海賊団』 を持つキャラ
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(WB), repo.get("OP01-016"), repo.get("OP01-022")] + [repo.get(_FILLER)] * 10
    me.hand = []
    evaluate_static_effects(st, overlay)
    src = InPlay.of(repo.get("ST22-003"), sickness=True)   # 【登場時】公開→白ひげなら2ドロー
    me.characters = [src]

    trigger_on_play(st, me, opp, src, overlay)
    resolve_triggers(st)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
        resolve_triggers(st)

    assert [c.card_id for c in me.hand] == [WB, "OP01-016"], (
        f"公開カードを含めて 2 枚引けていない (手札={[c.card_id for c in me.hand]})"
    )
    assert me.deck[0].card_id == "OP01-022", "デッキの残りがずれている"


def test_life_leave_trigger_fires_for_either_side():
    """「【自分のターン中】ライフが離れた時」 は **自分/相手どちらのライフでも** 発動する。

    一次情報 (cardqa_op_11 / OP11-041 ナミ): 「この【自分のターン中】効果は、 自分のライフが
    離れた時にも発動できますか？」 → 「**はい、 できます。 自分のライフか相手のライフかに
    かかわらず、 発動できます**」

    ⚠ overlay は on_self_life_to_hand だけを配線しており、 **相手のライフが離れた時
      (= 自分のアタック) に発動していなかった**。 【ターン1回】は when 横断で共有する。
    """
    repo, overlay = _repo(), _overlay()

    def mk():
        st = _state(repo, overlay, leader0="OP11-041")
        me = st.players[0]
        me.hand = []
        evaluate_static_effects(st, overlay)
        return st, me, st.players[1]

    # (1) 相手のライフが離れた時 (= 自分がリーダーにアタック)
    st, me, opp = mk()
    atk = InPlay.of(repo.get("EB01-018_p1"), sickness=False)
    me.characters = [atk]
    apply_action(st, AttackLeader(attacker_iid=atk.instance_id), overlay)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    assert len(me.hand) == 1, (
        f"相手のライフが離れたのに発動していない (手札={len(me.hand)})"
    )

    # (2) 自分のライフが手札に加わった時 (従来から動く経路)
    st, me, opp = mk()
    execute_effect({"life_to_hand": 1}, st, me, opp, None)
    resolve_triggers(st)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
        resolve_triggers(st)
    assert len(me.hand) == 2, f"自ライフ→手札 + ドロー1 で 2 枚のはず ({len(me.hand)})"

    # (3) 【ターン1回】は when を跨いで共有される (= 1 ターンに 2 回引けない)
    st, me, opp = mk()
    atk = InPlay.of(repo.get("EB01-018_p1"), sickness=False)
    me.characters = [atk]
    apply_action(st, AttackLeader(attacker_iid=atk.instance_id), overlay)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    n1 = len(me.hand)
    execute_effect({"life_to_hand": 1}, st, me, opp, None)
    resolve_triggers(st)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
        resolve_triggers(st)
    assert len(me.hand) == n1 + 1, (
        "別の when で 2 回目が発動している (【ターン1回】が when 横断で共有されていない)"
    )


def test_life_to_hand_cost_blocked_while_life_gain_is_locked():
    """「自分の効果でライフを手札に加えられない」 間は **コストとしても払えない**。

    一次情報 (cardqa_op_02 / OP02-004 ニューゲート): 「この【登場時】効果を発動したターンに
    『自分のライフの上から1枚を手札に加えることができる：』 のコストを支払うことは
    できますか？」 → 「**いいえ、 支払うことはできません。 その発動コストを支払えないため、
    効果の発動もできません**」
    ⚠ ST13-003 の置換 (= 札は動くが未払い) と違い、 こちらは **札が動かない**。
    """
    repo, overlay = _repo(), _overlay()

    def offers(lock: bool):
        st = _state(repo, overlay, leader0="OP02-001")
        me, opp = st.players[0], st.players[1]
        evaluate_static_effects(st, overlay)
        me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # 起動メイン: ライフ1枚を手札に
        if lock:
            ng = InPlay.of(repo.get("OP02-004"), sickness=True)
            me.characters.append(ng)
            trigger_on_play(st, me, opp, ng, overlay)
            resolve_triggers(st)
            while st.pending_choice is not None:
                resolve_pending_choice(st, [0])
                resolve_triggers(st)
        life0 = len(me.life)
        n = len([o for o in list_activate_main_effects(st, me, overlay)
                 if o[0].card.card_id == _FILLER])
        return n, len(me.life) == life0

    assert offers(False) == (1, True), "ロック無しで発動できないのはおかしい"
    assert offers(True) == (0, True), (
        "ライフ→手札がロックされているのに 「ライフを手札に加える：」 コストの効果を発動できている"
    )


def test_taunt_locks_all_attacks_even_with_active_attack_grant():
    """taunt (「『X』以外にアタックできない」) は 「アクティブにもアタック可」 でも解けない。

    一次情報 (cardqa_op_11): 「相手の場にレストの OP01-051 ユースタス・キッドがありドン‼が
    付与されている場合に、 【アタック時】効果でアクティブのキャラにもアタックできるように
    なった自分のリーダーは、 相手のアクティブの『ユースタス・キッド』ではないキャラに
    アタックできますか？」 → 「**いいえ、 できません**」
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP11-001")
    me, opp = st.players[0], st.players[1]
    kid = InPlay.of(repo.get("OP01-051"), sickness=False, rested=True)
    kid.attached_dons = 1                       # 【ドン‼×1】で taunt が立つ
    other = InPlay.of(repo.get("OP01-016"), sickness=False)   # アクティブ、 キッド以外
    opp.characters = [kid, other]
    hibari = InPlay.of(repo.get("OP11-010"), sickness=False)
    me.characters = [hibari]
    me.don_active = 5
    evaluate_static_effects(st, overlay)
    assert kid.attack_taunt, "テスト前提: taunt が立っていること"

    trigger_on_attack(st, me, opp, hibari, overlay)   # リーダーに 「アクティブにもアタック可」
    resolve_triggers(st)
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
        resolve_triggers(st)

    from engine.game import legal_actions
    targets = [a.target_iid for a in legal_actions(st)
               if isinstance(a, AttackCharacter) and a.attacker_iid == me.leader.instance_id]
    assert targets == [kid.instance_id], (
        "taunt 中なのに キッド 以外のアクティブキャラにアタックできる"
    )


def test_replace_ko_target_rested_is_honoured():
    """置換の 「自分の **レストの** キャラがKOされる場合」 は レスト状態を見る。

    OP05-030 ロシナンテ 【相手のターン中】自分のレストのキャラがKOされる場合、 代わりに
    このキャラをトラッシュに置くことができる。
    ⚠ **アクティブ** のキャラが KO される時は置換できない。 2026-08-12 まで Rust 側は
      `target_rested` を読んでおらず (Python は読んでいた)、 アクティブ victim にも
      一致していた = **差分掃引の合成デッキに該当ペアが無く見えなかった** 乖離。
    """
    repo, overlay = _repo(), _overlay()

    def run(victim_rested: bool):
        st = _state(repo, overlay)
        me, opp = st.players[1], st.players[0]
        st.turn_player_idx = 1
        st.turn_number = 10
        victim = InPlay.of(repo.get("OP01-016"), sickness=False, rested=victim_rested)
        rosi = InPlay.of(repo.get("OP05-030"), sickness=False)
        opp.characters = [victim, rosi]
        evaluate_static_effects(st, overlay)
        execute_effect({"ko": "all_opponent_characters"}, st, me, opp, None)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        return [c.card.name for c in opp.characters], [c.name for c in opp.trash]

    board_r, trash_r = run(True)
    assert "ナミ" in board_r and "ドンキホーテ・ロシナンテ" in trash_r, (
        f"レストの victim を ロシナンテ が身代わりで救えていない (場={board_r} trash={trash_r})"
    )
    board_a, trash_a = run(False)
    assert "ナミ" not in board_a, (
        f"アクティブの victim なのに置換が成立している (場={board_a} trash={trash_a})"
    )


def test_op12_017_red_applies_to_both_or_clauses():
    """OP12-017 見聞色の覇気: 「**赤の**イベントかコスト3以上のキャラカード」 の 「赤の」 は両方に係る。

    一次情報 (cardqa_op_12): 「この【メイン】効果で、 赤以外のコスト3以上のキャラカード1枚を
    手札に加えることはできますか？」 → 「**いいえ、 できません。 この効果は、『赤のイベント』か
    『赤のコスト3以上のキャラカード』を手札に加えることができる効果です**」

    ⚠ overlay の or_clauses はキャラ側に color が無く、 **青などのコスト3以上キャラを拾えていた**
      (2026-08-12 是正)。
    """
    repo, overlay = _repo(), _overlay()
    spec = overlay.get("OP12-017").effects[0]["do"][0]["optional_cost_then"]["effect"][0]

    def take(card_id):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        me.deck = [repo.get(card_id)] + [repo.get(_FILLER)] * 20
        me.hand = []
        evaluate_static_effects(st, overlay)
        execute_effect(spec, st, me, opp, None)
        return [c.card_id for c in me.hand]

    _cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    blue = next(c["card_id"] for c in _cards
                if c["category"] == "CHARACTER" and c.get("color") == "青"
                and str(c.get("cost")) == "4")
    red = next(c["card_id"] for c in _cards
               if c["category"] == "CHARACTER" and c.get("color") == "赤"
               and str(c.get("cost")) == "4")
    assert take(blue) == [], "赤以外のコスト3以上キャラを手札に加えられている"
    assert take(red) == [red], "赤のコスト3以上キャラを加えられない"


def test_put_top_to_life_goes_on_top_not_bottom():
    """「デッキの上から N 枚を **ライフの上** に加える」 は 一番上に置く (該当 50 枚)。

    ⚠ 2026-08-12 まで engine は `life.append` = **ライフの一番下** に置いていた
      (コード内にも 「技術的には先頭追加だが簡略」 と近似が明記されていた)。
      上下は実挙動に効く: 次のダメージで最初に離れるのは **上** の札なので、
      どの【トリガー】が出るか / ST13 系の表向き参照 / ライフ mill 順 がすべて変わる。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.deck = [repo.get("OP01-016"), repo.get("OP01-022")] + [repo.get(_FILLER)] * 20
    me.life = [repo.get("OP01-025")] * 2
    me.life_face_up = [False, False]

    execute_effect({"put_top_to_life": 2}, st, me, st.players[1], None)

    assert [c.card_id for c in me.life] == [
        "OP01-016", "OP01-022", "OP01-025", "OP01-025"
    ], f"ライフの上に (取った順で) 積まれていない: {[c.card_id for c in me.life]}"
    assert me.life_face_up == [False] * 4, "既定は裏向きのはず"


def test_hand_to_self_life_top_and_face_up_flag():
    """「手札1枚をライフの **上** に加える」 / 「**表向きで** 加える」 を書き分ける。

    ⚠ 2026-08-12 まで engine は 一番下に **裏向きで** 置いていた。 「表向きで加える」 は
      公式テキストにそう書いてある 7 枚 (EB03-059 / EB04-060 / OP07-097 / OP08-116 /
      OP09-104 / OP10-103 / OP10-107) だけ。 表向きかどうかは ST13-002 の
      「表向きライフ全トラッシュ」 / ST13-003 のルール置換 / しらほし系の条件 に直結する。
    """
    repo, overlay = _repo(), _overlay()

    def run(face_up):
        st = _state(repo, overlay)
        me = st.players[0]
        me.life = [repo.get("OP01-025")] * 2
        me.life_face_up = [False, False]
        me.hand = [repo.get("OP01-022")]
        spec = {"count": 1, "filter": {}}
        if face_up:
            spec["face_up"] = True
        execute_effect({"hand_to_self_life": spec}, st, me, st.players[1], None)
        return [c.card_id for c in me.life], list(me.life_face_up)

    ids, flags = run(False)
    assert ids[0] == "OP01-022", f"手札の札がライフの **上** に来ていない: {ids}"
    assert flags == [False, False, False], "指定が無いのに表向きになっている"

    ids2, flags2 = run(True)
    assert ids2[0] == "OP01-022" and flags2 == [True, False, False], (
        f"「表向きで加える」 が反映されていない: {ids2} {flags2}"
    )


def test_face_up_overlay_matches_official_text():
    """overlay の `hand_to_self_life.face_up` は 公式テキストの 「表向きで」 と 1:1。"""
    import re as _re
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    def specs(effs):
        out = []

        def walk(n):
            if isinstance(n, list):
                for x in n:
                    walk(x)
            elif isinstance(n, dict):
                if "hand_to_self_life" in n:
                    out.append(n["hand_to_self_life"])
                for v in n.values():
                    walk(v)
        walk(effs)
        return out

    bad = []
    for cid, effs in ov.items():
        sp = specs(effs)
        if not sp:
            continue
        text = (cards.get(cid, {}).get("text") or "").replace("\n", " ")
        if "ライフの上に" not in text:
            continue          # 別の文脈で使っている (トリガー等) は _text 側で判断済
        want = "ライフの上に表向きで加え" in text
        for s in sp:
            got = bool(s.get("face_up")) if isinstance(s, dict) else False
            if got != want:
                bad.append((cid, want, got))
    assert not bad, f"公式テキストの表向き指定と overlay の face_up が食い違う: {bad[:6]}"


# --------------------------------------------------------------------------- #
#  return_self_don_to_match_opp も「ドンがドンデッキに戻された時」を誘発する
#  一次情報 (cardqa_op_08 / OP08-074 ブラックマリア):
#    Q: この【起動メイン】効果で自分のターン終了時にドン!!をドン!!デッキに戻した時、
#       自分のカードの「自分の場のドン!!がドン!!デッキに戻された時、」などの効果は
#       発動できますか？
#    A: はい、できます。
#  是正前: return_self_don_to_match_opp は trigger_on_self_don_returned_to_deck を
#          呼んでおらず (return_self_don_to_deck / pay_don は呼ぶ)、 両エンジンとも
#          「戻された時」が沈黙 = 差分検証では検出できない共通バグだった。
# --------------------------------------------------------------------------- #
def test_return_don_to_match_opp_fires_on_don_returned_trigger():
    """自ドン超過分を戻す effect でも on_self_don_returned_to_deck が発火する。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # OP06-042 = 【自分の場のドン!!がドン!!デッキに戻された時】(自分のターン中) カード1枚を引く。
    me.characters = [InPlay.of(repo.get("OP06-042"), sickness=False)]
    me.don_active, me.don_rested = 8, 0
    opp.don_active, opp.don_rested = 4, 0

    hand_before = len(me.hand)
    execute_effect({"return_self_don_to_match_opp": True}, st, me, opp, None)

    # 超過 4 枚がドンデッキへ戻り、相手枚数(4)に合わせる
    assert me.don_active + me.don_rested == 4, "相手のドン枚数に合わせて戻っていない"
    # 戻された時トリガーで OP06-042 が 1 枚引く
    assert len(me.hand) == hand_before + 1, (
        "return_self_don_to_match_opp が on_self_don_returned_to_deck を誘発していない"
    )


def test_return_don_to_match_opp_no_excess_no_trigger():
    """対照: 相手とドン枚数が同じ (超過なし) なら戻らず、トリガーも発火しない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP06-042"), sickness=False)]
    me.don_active, me.don_rested = 4, 0
    opp.don_active, opp.don_rested = 4, 0

    hand_before = len(me.hand)
    execute_effect({"return_self_don_to_match_opp": True}, st, me, opp, None)

    assert me.don_active + me.don_rested == 4, "超過なしなのにドンが動いた"
    assert len(me.hand) == hand_before, "超過0枚なのにトリガーが発火した"


def test_return_opp_don_can_take_attached_don():
    """「相手は自身の **場の** ドン‼N枚をドン‼デッキに戻す」 の 「場の」 には **付与されたドン** も含む。

    一次情報 (cardqa_op_02 / OP02-089・090・091): 「この【トリガー】効果で相手はキャラや
    リーダーに **付与された** ドン!!を戻すことはできますか？」 → 「**はい、 できます**」

    ⚠ 2026-08-12 まで コストエリア (自由プール) しか減らしておらず、 自由ドンが足りない盤面で
      **規定枚数を戻せなかった**。 選ぶのは相手なので、 損の小さい順
      (レスト → アクティブ → 付与、 付与の中は キャラ → リーダー) で返す。
    """
    repo, overlay = _repo(), _overlay()

    def run(free_r, free_a, ch_don, ld_don, n=1):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        opp.don_rested, opp.don_active, opp.don_remaining_in_deck = free_r, free_a, 0
        c = InPlay.of(repo.get("OP01-016"), sickness=False)
        c.attached_dons = ch_don
        opp.characters = [c]
        opp.leader.attached_dons = ld_don
        execute_effect({"return_opp_don": n}, st, me, opp, None)
        return (opp.don_rested, opp.don_active, c.attached_dons,
                opp.leader.attached_dons, opp.don_remaining_in_deck)

    # レストがあるなら まずレストから (= 相手にとって損が小さい)
    assert run(1, 2, 1, 1) == (0, 2, 1, 1, 1), "レストのドンより先に他を返している"
    # 自由ドン 0 でも **キャラの付与ドン** から戻せる (公式 「はい」)
    assert run(0, 0, 1, 1) == (0, 0, 0, 1, 1), "付与ドンを戻せていない (規定枚数を返せない)"
    # キャラに付与が無ければ リーダーの付与から
    assert run(0, 0, 0, 1) == (0, 0, 0, 0, 1), "リーダーの付与ドンを戻せていない"
    # 場にドンが1枚も無ければ戻せない
    assert run(0, 0, 0, 0) == (0, 0, 0, 0, 0), "無いドンを戻している"


def test_op13_109_replace_needs_face_down_top_life():
    """「代わりに自分のライフの上から1枚を **表向きにできる**」 は 代償が実行できなければ選べない。

    一次情報 (cardqa_op_13 / OP13-109 ボニー): 「自分のライフの一番上が表向きの場合、
    このキャラが相手の効果で場を離れる代わりに自分のライフの上から1枚を表向きにできますか？」
    → 「**いいえ、 できません**」

    ⚠ 2026-08-12 まで overlay は `do` に `flip_life_face_up_effect` を置いており、
      一番上が既に表向きでも **置換が成立して KO を免れて** いた。 cost に移して
      payability (pos:top) で gate する。
    """
    repo, overlay = _repo(), _overlay()

    def survives(flags):
        st = _state(repo, overlay)
        me, opp = st.players[1], st.players[0]   # opp(=P0) が ボニー の持ち主
        st.turn_player_idx = 1
        me.deck = [repo.get(_FILLER)] * 20
        opp.life = [repo.get(_FILLER)] * len(flags)
        opp.life_face_up = list(flags)
        boni = InPlay.of(repo.get("OP13-109"), sickness=False)
        opp.characters = [boni]
        evaluate_static_effects(st, overlay)
        execute_effect({"ko": "all_opponent_characters"}, st, me, opp, None)
        resolve_triggers(st)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
            resolve_triggers(st)
        return len(opp.characters) == 1, list(opp.life_face_up)

    ok, flags = survives([False, False, False])
    assert ok and flags[0] is True, "一番上が裏向きなら 置換して場に残るはず"
    ok2, _ = survives([True, False, False])
    assert not ok2, "一番上が既に表向きなのに置換が成立して KO を免れている"
    ok3, _ = survives([])
    assert not ok3, "ライフ 0 なのに置換が成立している"


def test_eb02_035_don_comparison_gate():
    """EB02-035 サンジ&プリン【登場時】は「自分の場のドン‼が相手の場のドン‼の枚数以下の場合」
    にのみ 1 ドローする。この don-比較条件が overlay から欠落していた (2026-08-12 是正)。

    一次情報 (cardqa_eb_02, qid `ac39489df89b`, EB02-035):
      Q: 自分の場のドン7、相手の場のドン6のとき ST18-005 ルフィ太郎の【登場時】ドン-1で
         自分のドン1枚をドンデッキに戻して このカードを登場させた。この場合、この
         【登場時】効果でカード1枚を引くことはできますか？
      A: はい、できます。(ドン-1 で 自ドンが 6 になり 6≦6 を満たすため)

    ⚠ 是正前は条件が `[{self_turn: true}]` のみで、self_don > opp_don でも常にドローしていた。
    """
    from engine.effects import trigger_on_play
    repo, overlay = _repo(), _overlay()

    def draw_count(self_don, opp_don):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        me.don_active = self_don
        opp.don_active = opp_don
        ip = InPlay.of(repo.get("EB02-035"), sickness=True)
        me.characters.append(ip)
        h0 = len(me.hand)
        trigger_on_play(st, me, opp, ip, overlay)
        resolve_triggers(st)
        return len(me.hand) - h0

    assert draw_count(7, 6) == 0, "self_don(7) > opp_don(6) なのにドローしている (条件欠落)"
    assert draw_count(6, 6) == 1, "self_don(6) <= opp_don(6) はドローするはず"
    assert draw_count(3, 6) == 1, "self_don < opp_don はドローするはず"


def test_don_le_opp_don_gate_present_all_cards():
    """全走査ガード: 「自分の場のドン‼が相手の場のドン‼の枚数以下の場合」を持つ overlay エントリは
    必ず don-比較条件 (`don_diff_le`) を伴う。EB02-035 で欠落が見つかったため、同型の取りこぼしを防ぐ。
    """
    import json as _json
    from pathlib import Path as _Path
    ov = _json.load(open(_Path(__file__).resolve().parent.parent / "db" / "card_effects.json"))
    marker = "自分の場のドン"
    tail = "以下の場合"
    missing = []
    for cid, effs in ov.items():
        if not isinstance(effs, list):
            continue
        for e in effs:
            t = (e.get("_text") or "").replace(" ", "").replace("!", "‼").replace("！", "‼")
            # 「自分の場のドン(‼) が相手の場のドン(‼) の枚数以下の場合」 パターンのみ対象
            if "相手の場のドン" in t and "枚数以下の場合" in t and marker in t:
                if "don_diff" not in _json.dumps(e, ensure_ascii=False):
                    missing.append(cid)
    assert not missing, f"don-比較条件が欠落: {missing}"


def test_keep_opp_rested_picks_leader_and_character_independently():
    """「相手のレストの、 **リーダーとキャラ1枚まで**」 は **独立した 2 枠** (合計 2 枚まで)。

    一次情報 (cardqa_op_07 / OP07-059):
    - 「レストのリーダーとレストのキャラそれぞれ1枚ずつ、 合計2枚を選ぶことはできますか？」
      → 「**はい、 できます**」
    - 「相手のリーダーがアクティブの場合、 レストのキャラ1枚を選ぶことはできますか？」
      → 「**はい、 できます**」

    ⚠ 2026-08-13 まで 「リーダー + キャラ から 1 枚だけ」 の単一選択でモデル化しており、
      **リーダーを選ぶとキャラを選べなかった** (= 合計 1 枚)。
    """
    repo, overlay = _repo(), _overlay()

    def run(leader_rested, n_chara_rested):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        opp.leader.rested = leader_rested
        opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False,
                                    rested=(i < n_chara_rested)) for i in range(2)]
        evaluate_static_effects(st, overlay)
        execute_effect({"keep_opp_rested_inplay_next_refresh":
                        {"target_rest": "one_opp_chara_or_leader"}}, st, me, opp, None)
        return (opp.leader.stay_rested_next_refresh,
                [c.stay_rested_next_refresh for c in opp.characters])

    ld, ch = run(True, 2)
    assert ld and ch[0], f"リーダーとキャラの **両方** を選べていない (計2枚): {ld} {ch}"
    ld2, ch2 = run(False, 2)
    assert (not ld2) and ch2[0], "リーダーがアクティブでもキャラ1枚は選べるはず"
    ld3, ch3 = run(True, 0)
    assert ld3 and not any(ch3), "レストのキャラが居ないのに選んでいる"


def test_op06009_shuraiya_power_becomes_sets_truly_original_power():
    """cardqa Q1085 (EB03-004 カリーナ / OP06-009 シュライヤ):

    Q: 自分の「OP06-009 シュライヤ」が【アタック時】/【ブロック時】効果によって元々のパワー
       6000以上になっている場合、このキャラは【相手のターン中】効果でパワー+4000されますか？
    A: いいえ、されません。この場合、「シュライヤ」の元々のパワーが6000以上であるため、
       「自分の元々のパワー6000以上のキャラクター」がいることになり、「カリーナ」の
       パワーは+4000されません。

    = 「(相手のリーダーと)同じパワーになる」 は **元々のパワーを書き換える** 効果。
    旧 overlay は set_base_power_copy に original:false を付けており、現在パワーだけ変えて
    truly_original_power を更新しなかったため、上記条件を崩せず違反していた (2026-08-13 是正)。
    """
    repo = _repo()
    overlay = _overlay()
    # カリーナのリーダー = 多色 (EB04-001 赤/黄)。 相手リーダーは任意。
    st = _state(repo, overlay, leader0="EB04-001", leader1="OP01-001")
    me, opp = st.players[0], st.players[1]

    # 相手リーダーの現在パワーを 6000 にしておく (シュライヤの copy 元)
    opp.leader.turn_base_power_override = 6000

    shu = InPlay.of(repo.get("OP06-009"), sickness=False)
    me.characters.append(shu)
    kar = InPlay.of(repo.get("EB03-004"), sickness=False)
    me.characters.append(kar)

    # シュライヤの on_attack overlay 効果を実行 (= 相手リーダーと同じパワー=6000 になる)
    bundle = overlay["OP06-009"].effects
    on_attack = next(e for e in bundle if e.get("when") == "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, shu)

    assert shu.truly_original_power >= 6000, (
        f"シュライヤの元々のパワーが書き換わっていない: {shu.truly_original_power} "
        "(original:false のままだと 4000 のまま = 違反)"
    )

    # 相手のターン中、 カリーナの静的 +4000 を評価
    st.turn_player_idx = 1
    evaluate_static_effects(st, overlay)
    assert kar.power == repo.get("EB03-004").power, (
        f"カリーナに +4000 が乗っている: {kar.power} "
        "(元々のパワー6000以上のシュライヤがいるので +4000 されないのが公式)"
    )


def test_op06009_shuraiya_control_low_power_karina_gets_pump():
    """対照テスト: シュライヤの元々のパワーが 6000 未満なら、カリーナは +4000 される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader0="EB04-001", leader1="OP01-001")
    me, opp = st.players[0], st.players[1]
    # 相手リーダー 5000 (< 6000)
    opp.leader.turn_base_power_override = 5000
    shu = InPlay.of(repo.get("OP06-009"), sickness=False)
    me.characters.append(shu)
    kar = InPlay.of(repo.get("EB03-004"), sickness=False)
    me.characters.append(kar)
    bundle = overlay["OP06-009"].effects
    on_attack = next(e for e in bundle if e.get("when") == "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, shu)
    assert shu.truly_original_power < 6000
    st.turn_player_idx = 1
    evaluate_static_effects(st, overlay)
    assert kar.power == repo.get("EB03-004").power + 4000, (
        f"6000未満のキャラしかいないのにカリーナが +4000 されていない: {kar.power}"
    )


def test_set_base_power_copy_always_sets_original_power_all_cards():
    """全走査ガード: 「(選んだキャラと)同じパワーになる」= set_base_power_copy は **常に**
    元々のパワーを書き換える (cardqa Q1085)。 overlay の全 set_base_power_copy ノードは
    original:true でなければならない (original:false / 欠落 = 現在パワーのみ = 違反)。
    """
    import json as _json
    from pathlib import Path as _Path

    ov = _json.load(open(_Path(__file__).resolve().parent.parent / "db" / "card_effects.json"))

    def _walk(o):
        if isinstance(o, dict):
            yield o
            for v in o.values():
                yield from _walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from _walk(v)

    bad = []
    for cid, effs in ov.items():
        for node in _walk(effs):
            if isinstance(node, dict) and isinstance(node.get("set_base_power_copy"), dict):
                if node["set_base_power_copy"].get("original") is not True:
                    bad.append(cid)
    assert not bad, f"set_base_power_copy が元々のパワーを書き換えない (original!=true): {bad}"


# --------------------------------------------------------------------------- #
#  「自分の手札 N 枚**まで**を捨てる」 は 0 枚を選べる (2026-08-13)
#
#  一次情報 (cardqa_op_02、 OP02-059 ボア・ハンコック / OP02-070 ニューカマーランド):
#    Q: 「その後、自分の手札3枚までを捨てる。」の効果で、捨てる枚数に0枚を選べますか？
#    A: はい、できます。**0枚から3枚まで**のうち好きな枚数の手札を捨てます。
#
#  是正前: overlay が [approx: 手札3枚まで=最大3として trash_self_hand_random:3] と
#  近似を明記しており、 実測で **常に 3 枚強制**。 0 枚を選べなかった。
# --------------------------------------------------------------------------- #
def test_up_to_hand_discard_human_can_choose_zero():
    """人間は 「手札3枚まで捨てる」 で 0 枚 (= modal で何も選ばない) を選べる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.hand = [repo.get(_FILLER) for _ in range(5)]
    execute_effect({"trash_self_hand_random": {"amount": 3, "up_to": True}},
                   st, me, st.players[1], None)
    assert st.pending_choice is not None, "「まで」 なのに人間に枚数の選択が出ていない"
    assert st.pending_choice["kind"] == "self_hand_discard_pick"
    assert st.pending_choice.get("up_to") is True
    resolve_pending_choice(st, [])          # = 0 枚を選ぶ
    assert len(me.hand) == 5, "0 枚を選んだのに手札が減っている"
    assert len(me.trash) == 0


def test_up_to_hand_discard_human_can_choose_partial():
    """同じ効果で 1 枚だけ捨てる (= 0 < k < N) も選べる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.hand = [repo.get(_FILLER) for _ in range(5)]
    execute_effect({"trash_self_hand_random": {"amount": 3, "up_to": True}},
                   st, me, st.players[1], None)
    resolve_pending_choice(st, [2])
    assert len(me.hand) == 4 and len(me.trash) == 1


def test_plain_hand_discard_is_still_forced():
    """対照: 「まで」 の無い 「手札N枚を捨てる」 は 0 枚を選べない (= 強制)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.hand = [repo.get(_FILLER) for _ in range(5)]
    execute_effect({"trash_self_hand_random": 2}, st, me, st.players[1], None)
    assert st.pending_choice is not None
    assert not st.pending_choice.get("up_to")
    resolve_pending_choice(st, [])          # 見送ろうとしても
    assert len(me.hand) == 3, "強制のはずの手札破棄をスキップできている"


def test_op02_059_hancock_attack_does_not_force_three_discards():
    """OP02-059 ハンコック【アタック時】: draw1 + 強制1捨て の後、 3枚までは AI 既定 0 枚。

    公式は 0〜3 から選べる。 見返り (【自分の手札が捨てられた時】) が場に無いので
    AI は 0 枚を選ぶ = 手札は draw+1 / 強制捨て-1 で増減なし。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP02-059"), sickness=False)]
    me.hand = [repo.get(_FILLER) for _ in range(5)]
    trigger_on_attack(st, me, st.players[1], me.characters[0], overlay)
    resolve_triggers(st)
    assert len(me.hand) == 5, f"0〜3 の選択なのに強制で捨てている (手札 {len(me.hand)})"
    assert len(me.trash) == 1, "強制の 1 枚捨てが起きていない"


def test_op09_059_mills_exactly_as_many_as_discarded():
    """OP09-059 湯けむり殺人事件: 「捨てた枚数と同じ枚数」 をデッキ上からトラッシュ。

    是正前は mill が固定 2 枚で、 捨てた枚数と連動していなかった。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.hand = [repo.get(_FILLER) for _ in range(4)]
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    deck_before = len(me.deck)
    ent = [e for e in overlay["OP09-059"].effects if e.get("when") == "counter"][0]
    from engine.effects import run_do_array
    run_do_array(list(ent["do"]), st, me, st.players[1], me.characters[0])
    # 1 段目 = power_pump の対象選択 modal → 自キャラを選ぶ
    while st.pending_choice is not None and st.pending_choice["kind"] != "self_hand_discard_pick":
        resolve_pending_choice(st, [0])
    assert st.pending_choice is not None, "手札破棄の選択が出ていない"
    resolve_pending_choice(st, [1])          # 1 枚だけ捨てる
    assert len(me.hand) == 3, "捨て枚数が選択どおりでない"
    assert len(me.deck) == deck_before - 1, (
        f"mill が捨てた枚数と一致しない (deck {deck_before} → {len(me.deck)}、 捨て 1 枚)"
    )


def test_up_to_hand_discard_ai_uses_max_when_payoff_on_board():
    """AI は【自分の手札が捨てられた時】の見返りが場にある時だけ最大まで捨てる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    payoff = next(
        (cid for cid, b in overlay.items()
         if any(e.get("when") == "on_self_hand_discarded" for e in b.effects)
         and str(getattr(repo.get(cid).category, "value", repo.get(cid).category)).upper()
             == "CHARACTER"),
        None,
    )
    assert payoff, "on_self_hand_discarded を持つキャラが overlay に無い (前提が崩れている)"
    me.characters = [InPlay.of(repo.get(payoff), sickness=False)]
    me.hand = [repo.get(_FILLER) for _ in range(5)]
    execute_effect({"trash_self_hand_random": {"amount": 3, "up_to": True}},
                   st, me, st.players[1], None)
    assert len(me.hand) == 2, f"見返りがあるのに捨てていない (手札 {len(me.hand)})"


def test_no_approx_marker_left_for_up_to_hand_discard():
    """全走査: 公式テキストが 「手札N枚までを捨てる」 のカードは overlay も up_to。"""
    import re as _re
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))}
    effs = json.loads((ROOT / "db" / "card_effects.json").read_text("utf-8"))
    pat = _re.compile(r"手札(\d+)枚まで(?:を)?[^。]{0,4}?捨て")

    def _walk_nodes(o):
        if isinstance(o, dict):
            yield o
            for vv in o.values():
                yield from _walk_nodes(vv)
        elif isinstance(o, list):
            for vv in o:
                yield from _walk_nodes(vv)

    bad = []
    for cid, card in cards.items():
        txt = " ".join(filter(None, [card.get("text"), card.get("trigger")]))
        m = pat.search(txt)
        if not m:
            continue
        n = int(m.group(1))
        ok = False
        for node in _walk_nodes(effs.get(cid, [])):
            if isinstance(node, dict):
                spec = node.get("trash_self_hand_random")
                if isinstance(spec, dict) and spec.get("up_to") and int(spec.get("amount", 0)) == n:
                    ok = True
        if not ok:
            bad.append(cid)
    assert not bad, f"「手札N枚までを捨てる」 が up_to になっていない: {bad}"


# --------------------------------------------------------------------------- #
#  「相手の、レストのキャラかドン‼1枚まで」 = キャラ と ドン の混在単一選択
#  (2026-08-13 是正、 OP07-026 ジュエリー・ボニー)
#
#  一次情報 (cardqa_op_07 Q654/Q655):
#    Q: この【登場時】効果で、相手の**アクティブ**のドン!!1枚を選ぶことはできますか？ → いいえ
#    Q: この【登場時】効果で、相手の**付与された状態**のドン!!1枚を選ぶことはできますか？ → いいえ
#  = 候補は 相手の **レストのキャラ** と **コストエリアのレストのドン** のみ。
#
#  是正前: overlay が キャラ branch のみ (one_opponent_character_filtered) で
#  「かドン‼」 が丸ごと欠落していた。
# --------------------------------------------------------------------------- #
def test_op07_026_prefers_rested_character():
    """レストのキャラが居ればそれを選ぶ (AI 優先順位: キャラ > ドン)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    opp.characters = [victim]
    opp.don_active, opp.don_rested = 3, 2
    me.characters = [InPlay.of(repo.get("OP07-026"), sickness=False)]
    trigger_on_play(st, me, opp, me.characters[0], overlay)
    resolve_triggers(st)
    assert victim.stay_rested_next_refresh is True
    assert opp.next_refresh_kept_rested_don == 0, "キャラを選んだのにドンも止めている"


def test_op07_026_falls_back_to_rested_don():
    """レストのキャラが居なければ **レストのドン** 1 枚を止める (是正前は不発だった)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = []
    opp.don_active, opp.don_rested = 3, 2
    me.characters = [InPlay.of(repo.get("OP07-026"), sickness=False)]
    trigger_on_play(st, me, opp, me.characters[0], overlay)
    resolve_triggers(st)
    assert opp.next_refresh_kept_rested_don == 1, "レストのドンを止められていない"


def test_op07_026_active_don_is_never_a_target():
    """公式 Q654: **アクティブ** のドンは選べない (= レストのドンが 0 なら不発)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = []
    opp.don_active, opp.don_rested = 5, 0
    me.characters = [InPlay.of(repo.get("OP07-026"), sickness=False)]
    trigger_on_play(st, me, opp, me.characters[0], overlay)
    resolve_triggers(st)
    assert opp.next_refresh_kept_rested_don == 0
    assert opp.don_active == 5 and opp.don_rested == 0, "アクティブのドンを触っている"


def test_op07_026_human_can_choose_don_over_character():
    """人間は modal でキャラを選ばない (= skip) ことで **ドン** を選べる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    opp.characters = [victim]
    opp.don_active, opp.don_rested = 1, 2
    me.characters = [InPlay.of(repo.get("OP07-026"), sickness=False)]
    trigger_on_play(st, me, opp, me.characters[0], overlay)
    resolve_triggers(st)
    assert st.pending_choice is not None, "混在選択なのに人間に modal が出ていない"
    resolve_pending_choice(st, [])          # = キャラを選ばない
    assert victim.stay_rested_next_refresh is False
    assert opp.next_refresh_kept_rested_don == 1, "skip したのにドンが選ばれていない"


def test_op07_026_kept_don_actually_stays_rested_through_refresh():
    """止めたドンが 次のリフレッシュフェイズで実際にアクティブにならない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    opp = st.players[1]
    opp.don_active, opp.don_rested = 0, 3
    opp.next_refresh_kept_rested_don = 1
    # 自ターンを終える → 相手ターン開始 (= リフレッシュフェイズ) まで進める
    st.turn_player_idx = 0
    apply_action(st, EndPhase())
    assert opp.next_refresh_kept_rested_don == 0, "リフレッシュを通過していない (前提が崩れている)"
    # レスト 3 枚 のうち 1 枚 は 起きない。 active 側 は ドンフェイズ の 追加 を 含むので
    # 「レストが 1 枚 残る」 ことだけを見る (= 効果の本体)。
    assert opp.don_rested == 1, (
        f"止めたドンがアクティブになっている (rested={opp.don_rested}、 期待 1)"
    )


def test_op06_020_hordy_can_rest_opponent_don():
    """OP06-020 ホーディ (リーダー)【起動メイン】も 「キャラかドン‼」 = ドンをレストにできる。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP06-020")
    me, opp = st.players[0], st.players[1]
    opp.characters = []
    opp.don_active, opp.don_rested = 4, 0
    me.don_active = 5
    effs = list_activate_main_effects(st, me, overlay)
    assert effs, "OP06-020 の起動メインが候補に出ていない"
    fire_activate_main(st, me, opp, effs[0][0], effs[0][1])
    resolve_triggers(st)
    assert opp.don_active == 3 and opp.don_rested == 1, (
        f"相手ドンをレストにできていない (active={opp.don_active} rested={opp.don_rested})"
    )


# --------------------------------------------------------------------------- #
#  デッキ 0 枚 = 敗北条件 (公式 9-2-1-2)、 判定は **即座** (2026-08-13 是正)
#
#  一次情報 (総合ルール rule_comprehensive_20260109):
#    1-2-1-1-2 / 1-2-2-2 / 9-2-1-2  「自分のデッキのカードが０枚になる」 = 敗北条件
#    1-2-2                          敗北条件を満たしたら **次にルール処理を行う時点** で敗北
#    9-1-2                          ルール処理は 「他の行動の実行中であっても、 それが発生した
#                                    時点で即座に解決」
#    9-2-1                          複数プレイヤーが同時に満たせば **全員** 敗北 (= 引き分け)
#  cardqa_st_03 (ST03-005): 「デッキが0枚となり、 デッキが0枚になったプレイヤーはゲームに敗北します」
#
#  是正前: engine はドローフェイズで draw に失敗した時だけ敗北させており、 デッキを 0 枚に
#  しても **その場では負けなかった** (= 次の自分のドローまで生き延びた)。
# --------------------------------------------------------------------------- #
def _deckout_state(repo, overlay, leader0, deck0=2):
    st = _state(repo, overlay, leader0=leader0)
    st.players[0].deck = [repo.get(_FILLER)] * deck0
    from engine.game import _recompute_static
    _recompute_static(st)
    return st


def test_deck_zero_is_immediate_defeat():
    """自分の効果でデッキを 0 枚にしたら **その場で** 敗北する。"""
    repo, overlay = _repo(), _overlay()
    st = _deckout_state(repo, overlay, "OP01-001")
    me, opp = st.players[0], st.players[1]
    execute_effect({"mill_self_top": 2}, st, me, opp, None)
    from engine.game import _recompute_static
    _recompute_static(st)
    assert not me.deck
    assert st.game_over is True, "デッキ0枚でも敗北していない (公式 9-2-1-2)"
    assert st.winner == 1, f"敗北したのは P0 のはず (winner={st.winner})"


def test_op15_022_brook_defers_deck_out_defeat():
    """OP15-022 ブルック: 「デッキが0枚でも敗北せず、 0枚になったターン終了時に敗北」。"""
    repo, overlay = _repo(), _overlay()
    st = _deckout_state(repo, overlay, "OP15-022")
    me, opp = st.players[0], st.players[1]
    assert me.deck_out_defer is True, "ブルックのルール置換が張られていない"
    execute_effect({"mill_self_top": 2}, st, me, opp, None)
    from engine.game import _recompute_static
    _recompute_static(st)
    assert st.game_over is False, "ブルックなのに即敗北している"
    apply_action(st, EndPhase())
    assert st.game_over is True and st.winner == 1, "ターン終了時に敗北していない"


def test_op15_022_brook_loses_immediately_when_leader_negated():
    """公式 cardqa_op_15: ブルックの効果が **無効になった時点** でデッキ0枚なら敗北する。

    Q: 自分のデッキが1枚から0枚になった。その後 このターン中に相手が「OP09-097 闇水」を
       発動しこのリーダーの効果を無効にした場合、自分はゲームに敗北しますか？
    A: はい、このリーダーの効果が無効になった時点でデッキが0枚の場合、ゲームに敗北します。
    """
    repo, overlay = _repo(), _overlay()
    st = _deckout_state(repo, overlay, "OP15-022")
    me, opp = st.players[0], st.players[1]
    execute_effect({"mill_self_top": 2}, st, me, opp, None)
    from engine.game import _recompute_static
    _recompute_static(st)
    assert st.game_over is False, "前提: ブルックが効いている間は敗北しない"
    me.leader.granted_keywords.add("効果無効")     # = OP09-097 闇水
    _recompute_static(st)
    assert me.deck_out_defer is False, "無効化されてもルール置換が残っている"
    assert st.game_over is True and st.winner == 1, \
        "リーダーが無効になった時点で敗北していない (cardqa_op_15)"


def test_op03_040_nami_wins_on_deck_out():
    """OP03-040 ナミ: 「デッキが0枚になった場合、 敗北する代わりに勝利する」。"""
    repo, overlay = _repo(), _overlay()
    st = _deckout_state(repo, overlay, "OP03-040")
    me, opp = st.players[0], st.players[1]
    execute_effect({"mill_self_top": 2}, st, me, opp, None)
    from engine.game import _recompute_static
    _recompute_static(st)
    assert st.game_over is True and st.winner == 0, "ナミがデッキ0で勝利していない"


def test_op03_040_nami_loses_when_negated():
    """公式 cardqa_op_09 / cardqa_op_10: ナミの効果を無効にされたターンにデッキ0 → **敗北**。"""
    repo, overlay = _repo(), _overlay()
    st = _deckout_state(repo, overlay, "OP03-040")
    me, opp = st.players[0], st.players[1]
    me.leader.granted_keywords.add("効果無効")     # = OP09-097 闇水 / OP10-098
    from engine.game import _recompute_static
    _recompute_static(st)
    assert me.deck_out_wins is False, "無効化されても勝利置換が残っている"
    execute_effect({"mill_self_top": 2}, st, me, opp, None)
    _recompute_static(st)
    assert st.game_over is True and st.winner == 1, \
        "無効化されたナミがデッキ0で勝ってしまっている (公式=敗北)"


def test_both_players_deck_zero_is_a_draw():
    """公式 9-2-1: 敗北条件を満たしている **全員** が敗北 = 引き分け。"""
    repo, overlay = _repo(), _overlay()
    st = _deckout_state(repo, overlay, "OP01-001")
    me, opp = st.players[0], st.players[1]
    opp.deck = []
    execute_effect({"mill_self_top": 2}, st, me, opp, None)
    from engine.game import _recompute_static
    _recompute_static(st)
    assert st.game_over is True and st.winner is None, \
        f"両者デッキ0 は引き分けのはず (winner={st.winner})"


# --------------------------------------------------------------------------- #
#  人間の選択権 (= [[feedback_human_ai_option_parity]]) の穴 2 件 (2026-08-13 是正)
# --------------------------------------------------------------------------- #
def test_rest_self_cards_cost_is_always_paid_in_full():
    """「自分のカードN枚をレストにできる：」 は **発動コスト** = N 枚ぴったり払う。

    ⚠ 是正前: 人間が modal で N 枚未満しか選ばないと **その枚数しかレストされずに効果だけ発動**
      していた。 原因は modal 解決側 (target_pick) が 非 dict の primitive_value を
      {"_iid_picks": ...} に置き換えるため **count が落ちて 1 になる** こと
      (overlay は {"rest_self_cards": 2} = 素の int)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP14-029"), sickness=False),
                     InPlay.of(repo.get(_FILLER), sickness=False)]
    me.don_active, me.don_rested = 0, 0
    execute_effect({"rest_self_cards": 2}, st, me, st.players[1], me.characters[0])
    assert st.pending_choice is not None
    resolve_pending_choice(st, [0])          # 1 枚しか選ばない
    board_rested = sum(1 for ip in [me.leader, *me.characters] if ip.rested)
    assert board_rested + me.don_rested == 2, (
        f"コスト2枚が払い切られていない (場 {board_rested} + ドン {me.don_rested})"
    )


def test_rest_self_cards_human_can_pay_entirely_with_don():
    """公式 cardqa_op_14: 「自分のカード」 は リーダー/キャラ/ステージ/**ドン‼** の 4 ゾーン。
    人間は場のカードを選ばないことで **あえてドンだけで払える**。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP14-029"), sickness=False),
                     InPlay.of(repo.get(_FILLER), sickness=False)]
    me.don_active, me.don_rested = 5, 0
    execute_effect({"rest_self_cards": 2}, st, me, st.players[1], me.characters[0])
    assert "ドン" in st.pending_choice.get("description", ""), \
        "ドンで払える旨が modal に出ていない"
    resolve_pending_choice(st, [])           # 場から 1 枚も選ばない
    assert all(not ip.rested for ip in [me.leader, *me.characters]), "場が勝手にレストされた"
    assert me.don_active == 3 and me.don_rested == 2, \
        f"ドン 2 枚で払えていない (active={me.don_active} rested={me.don_rested})"


def test_effect_damage_lets_human_decline_life_trigger():
    """公式 10-1-5-2 「【トリガー】は発動しないことも選べる」 を **効果ダメージ** でも人間に渡す。

    ⚠ 是正前: 戦闘ダメージ経路だけ life_taken_choice modal を出しており、
      効果ダメージ (deal_opp_leader_damage) は should_fire_trigger で自動発動していた。
    """
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.human_player_idx = 1                   # = 防御側が人間
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP09-059"), repo.get("OP09-059"), repo.get(_FILLER)]
    opp.life_face_up = [False] * 3
    run_do_array([{"deal_opp_leader_damage": 2}, {"draw": 1}], st, me, opp, None)
    assert st.pending_choice is not None, "効果ダメージで人間に確認が出ていない"
    assert st.pending_choice["kind"] == "life_taken_choice"
    assert st.pending_choice["has_trigger"] is True
    assert st.pending_attack_hits["remaining_damage"] == 1, "残り発数が保持されていない"
    hand_before = len(opp.hand)
    resolve_pending_choice(st, [0])           # 1 発目: トリガーを **使わない**
    assert len(opp.hand) == hand_before + 1, "使わないなら手札に加わるはず"
    assert st.pending_choice is not None, "2 発目の確認が出ていない"
    resolve_pending_choice(st, [1])           # 2 発目: トリガーを **使う**
    assert st.pending_choice is None
    assert len(opp.life) == 1, f"2 発分ライフが減っていない (life={len(opp.life)})"
    assert len(me.hand) == 1, "選択で中断した do 配列の後続 (draw) が再開されていない"


def test_effect_damage_ai_defender_is_unchanged():
    """対照: 防御側が AI なら従来どおり自動 (= modal を挟まない)。"""
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP09-059"), repo.get("OP09-059"), repo.get(_FILLER)]
    opp.life_face_up = [False] * 3
    run_do_array([{"deal_opp_leader_damage": 2}, {"draw": 1}], st, me, opp, None)
    assert st.pending_choice is None, "AI 防御なのに選択待ちで止まっている"
    assert len(opp.life) == 1 and len(me.hand) == 1


# --------------------------------------------------------------------------- #
#  公式 Q&A conformance 実測 (2026-08-13 バッチ、 台帳 末尾から)
#  「公式どおりで問題なかった」 ものも、 後から壊れないよう固定する。
# --------------------------------------------------------------------------- #
def test_op13_077_uses_printed_power_not_current():
    """OP13-077: 「相手の**元々の**、パワー4000以下」 = 印刷パワー (公式 4-9)。

    元々 7000 / 現在 3000 のキャラは KO できない (cardqa_op_13 = 「いいえ、できません」)。
    """
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP02-013"), sickness=False)   # 印刷 7000
    victim.turn_buff = -4000                                    # 現在 3000
    opp.characters = [victim]
    me.leader.attached_dons = 1
    me.don_active = 3
    ent = [e for e in overlay["OP13-077"].effects if e.get("when") == "main"][0]
    run_do_array(list(ent["do"]), st, me, opp, None)
    resolve_triggers(st)
    assert victim in opp.characters, "元々のパワー 7000 のキャラを KO してしまっている"


def test_op14_069_second_option_needs_no_leader_feature():
    """OP14-069 の 2 つ目の選択肢 (レスト不可) はリーダー特徴に依存しない (cardqa_op_14 = はい)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP01-001")      # 非《ドンキホーテ海賊団》
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP14-069"), sickness=False)
    me.characters = [src]
    trigger_on_play(st, me, opp, src, overlay)
    resolve_triggers(st)
    assert victim in opp.characters, "リーダー特徴が無いのに KO 側が走っている"
    assert victim.cannot_be_rested_buff is True, "レスト不可の選択肢が実行されていない"


def test_op09_084_granted_blocker_survives_effect_negation():
    """付与済みの【ブロッカー】は 「効果を無効にする」 で消えない (cardqa_op_09 = いいえ)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP09-001")
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP09-084"), sickness=False)
    me.characters = [c]
    execute_effect({"give_keyword": {"duration": "next_opp_turn_end",
                                     "keywords": ["ブロッカー"], "target": "self"}},
                   st, me, opp, c)
    from engine.game import _recompute_static
    _recompute_static(st)
    assert c.is_blocker_now is True, "前提: ブロッカーが付与されていない"
    execute_effect({"disable_effect": {"duration": "turn", "target": "one_opponent_character_any"}},
                   st, opp, me, None)
    _recompute_static(st)
    assert "効果無効" in c.granted_keywords, "前提: 無効化が乗っていない"
    assert c.is_blocker_now is True, "付与済みブロッカーが無効化で消えている"


def test_op03_099_pump_applies_even_with_no_life_to_scry():
    """OP03-099: 見るライフが 0 枚でも 「その後 +1000」 は走る (cardqa_op_03 = はい)。"""
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP03-099")
    me, opp = st.players[0], st.players[1]
    me.life, me.life_face_up = [], []
    opp.life, opp.life_face_up = [], []
    me.leader.attached_dons = 1
    from engine.game import _recompute_static
    _recompute_static(st)
    before = me.leader.power
    ent = [e for e in overlay["OP03-099"].effects if e.get("when") == "on_attack"][0]
    run_do_array(list(ent["do"]), st, me, opp, me.leader)
    assert me.leader.power == before + 1000, \
        f"ライフ 0 枚で +1000 が乗っていない ({before} → {me.leader.power})"


def test_on_play_does_not_fire_when_source_sacrificed_by_field_limit():
    """場 5 枚上限 (公式 3-7-6-1) で犠牲になったキャラの【登場時】は発動しない。

    cardqa_op_06 / cardqa_op_10: 「キャラA」 をアクティブ登場 → 「キャラB」 登場の犠牲で
    「キャラA」 がトラッシュ → 「キャラA」 の【登場時】は発動できない (= いいえ)。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    big = "OP02-013"          # power 7000 = 犠牲に選ばれにくい埋め草
    me.deck = [repo.get(big)] * 20
    me.characters = [InPlay.of(repo.get(big), sickness=False) for _ in range(3)]
    moria = InPlay.of(repo.get("OP06-086"), sickness=False)
    me.characters.append(moria)                       # = モリア込みで 4 枚
    me.trash = [repo.get("OP04-101"),                 # A: cost2 power1000【登場時】1ドロー
                repo.get("OP01-010")]                 # B: cost1 power3000 効果なし
    hand_before = len(me.hand)
    trigger_on_play(st, me, st.players[1], moria, overlay)
    resolve_triggers(st)
    board = [ip.card.card_id for ip in me.characters]
    assert "OP04-101" not in board, "前提: キャラA が犠牲になっていない (テストの前提が崩れた)"
    assert "OP01-010" in board, "前提: キャラB が登場していない"
    assert len(me.hand) == hand_before, \
        "犠牲になったキャラの【登場時】が発動している (公式=発動できない)"


def test_op01_080_on_ko_draw_cannot_be_declined():
    """OP01-080【KO時】カード1枚を引く は強制 (cardqa_op_01 = 引かない選択はできない)。"""
    from engine.effects import trigger_on_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP01-080"), sickness=False)
    me.characters = [c]
    hand_before = len(me.hand)
    me.characters.remove(c)
    me.trash.append(c.card)
    trigger_on_ko(st, me, opp, c.card, overlay, by_opp_effect=True)
    resolve_triggers(st)
    assert st.pending_choice is None, "強制のはずの【KO時】に拒否 modal が出ている"
    assert len(me.hand) == hand_before + 1, "【KO時】のドローが起きていない"


def test_leader_deck_construction_restrictions():
    """リーダーの 「ルール上、〜デッキに入れることができない」 を構築チェックで弾く。

    一次情報 (cardqa_op_12、 OP12-001 シルバーズ・レイリー): 「元々のコストが5以上で、
    効果によってコストが4以下に下がるカード (ST23-001 ウタ) を入れられますか」 → **いいえ**。
    = 判定は **印刷コスト**。
    """
    from engine.deck import DeckList
    repo = _repo()

    def _deck(leader, card_ids):
        return DeckList(name="t", leader=repo.get(leader),
                        main=[repo.get(c) for c in card_ids], slug="t")

    bad = _deck("OP12-001", ["ST23-001"] * 4 + ["OP01-016"] * 46)
    assert repo.get("ST23-001").cost >= 5, "前提: ST23-001 の印刷コストが 5 以上でない"
    assert any("コスト5以上" in p for p in bad.validate(banlist={})), \
        "OP12-001 でコスト5以上のカードが弾かれていない"
    ok = _deck("OP12-001", ["OP01-016"] * 50)
    assert not any("コスト5以上" in p for p in ok.validate(banlist={})), \
        "コスト4以下のみの構築が誤って弾かれている"
    nami = _deck("P-117", ["OP01-016"] * 50)
    assert any("東の海" in p for p in nami.validate(banlist={})), \
        "P-117 で非《東の海》カードが弾かれていない"


def test_scry_all_life_preserves_face_up_flags():
    """ライフを並べ替える効果は 表向き/裏向きを **札ごとに** 保つ (cardqa_st_13)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.life = [repo.get("OP01-016"), repo.get("OP02-013"), repo.get("OP01-025")]
    me.life_face_up = [True, False, True]
    execute_effect({"scry_all_life_one_to_deck": True}, st, me, st.players[1], None)
    resolve_triggers(st)
    face_up_ids = {"OP01-016", "OP01-025"}
    for card, flag in zip(me.life, me.life_face_up):
        assert (card.card_id in face_up_ids) == flag, \
            f"{card.card_id} の表向きフラグが入れ替わっている (flag={flag})"


def test_op05_084_static_turns_off_when_non_tenryubito_enters():
    """OP05-084: 自場が《天竜人》のみでなくなった瞬間にコスト-4 は消える (cardqa_op_05 = いいえ)。"""
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP05-084"), sickness=False)]
    opp.characters = [InPlay.of(repo.get("OP02-013"), sickness=False)]   # 印刷コスト 7
    _recompute_static(st)
    assert opp.characters[0].base_cost == 3, "前提: 天竜人のみでコスト-4 が乗っていない"
    me.characters.append(InPlay.of(repo.get(_FILLER), sickness=False))   # 非《天竜人》
    _recompute_static(st)
    assert opp.characters[0].base_cost == 7, \
        "非《天竜人》が場に出たのにコスト-4 が残っている"


# --------------------------------------------------------------------------- #
#  「デッキの上からN枚をトラッシュに置いて**もよい**」 は任意 (2026-08-13 是正)
#
#  一次情報 (cardqa_op_03、 OP03-054): 「この【カウンター】効果で自分のリーダーを+2000し、
#    自分のデッキを1枚トラッシュに置かないことを選べますか？」 → **はい、選べます。**
#  総合ルール 1-3-5-1 も 「上限が定められている場合、 下限指定が無い限り 0 を選べる」。
#
#  是正前: overlay が素の mill_self_top = **強制**。 2026-08-13 に 「デッキ0枚=即敗北」 を
#  実装したので、 強制の自デッキ削り (OP03-041 ウソップ 7 枚) は **自滅を強制** しうる。
# --------------------------------------------------------------------------- #
def _op03_041_do(overlay):
    return [e for e in overlay["OP03-041"].effects
            if e.get("when") == "on_opp_life_taken"][0]["do"]


def test_optional_self_mill_human_can_decline():
    """人間は 「デッキの上から7枚をトラッシュに置いてもよい」 を見送れる。"""
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.deck = [repo.get(_FILLER)] * 20
    run_do_array(list(_op03_041_do(overlay)), st, me, st.players[1], None)
    assert st.pending_choice is not None, "任意なのに人間に確認が出ていない"
    assert st.pending_choice["kind"] == "optional_cost_confirm"
    resolve_pending_choice(st, [0])           # 見送り
    assert len(me.deck) == 20, "見送ったのにデッキが削れている"


def test_optional_self_mill_human_can_accept():
    """対照: 発動を選べば公式どおり 7 枚トラッシュされる。"""
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me = st.players[0]
    me.deck = [repo.get(_FILLER)] * 20
    run_do_array(list(_op03_041_do(overlay)), st, me, st.players[1], None)
    resolve_pending_choice(st, [1])           # 発動
    assert len(me.deck) == 13, f"7 枚トラッシュされていない (deck={len(me.deck)})"


def test_ai_declines_optional_self_mill_that_would_deck_out():
    """AI は 「撃つと自分が負ける」 任意の自デッキ削りを見送る (公式 9-2-1-2)。"""
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.deck = [repo.get(_FILLER)] * 5          # 7 > 5 = 撃つと 0 枚
    run_do_array(list(_op03_041_do(overlay)), st, me, st.players[1], None)
    resolve_triggers(st)
    assert len(me.deck) == 5, "自滅する自デッキ削りを撃っている"
    assert st.game_over is False


def test_ai_still_fires_optional_self_mill_when_safe():
    """対照: デッキに余裕があれば AI は従来どおり撃つ (= self-play / matrix 中立)。"""
    from engine.effects import run_do_array
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.deck = [repo.get(_FILLER)] * 20
    run_do_array(list(_op03_041_do(overlay)), st, me, st.players[1], None)
    resolve_triggers(st)
    assert len(me.deck) == 13, f"安全な局面で撃っていない (deck={len(me.deck)})"


def test_deck_out_wins_leader_still_mills_itself_to_zero():
    """OP03-040 ナミ (デッキ0で勝利) は残り少なくても撃つ = そのまま勝つ。"""
    from engine.effects import run_do_array
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP03-040")
    me = st.players[0]
    me.deck = [repo.get(_FILLER)] * 1
    _recompute_static(st)
    assert me.deck_out_wins is True, "前提: 勝利置換が張られていない"
    ent = [e for e in overlay["OP03-040"].effects
           if e.get("when") == "on_opp_life_taken"][0]
    run_do_array(list(ent["do"]), st, me, st.players[1], None)
    resolve_triggers(st)
    _recompute_static(st)
    assert not me.deck
    assert st.game_over is True and st.winner == 0, "ナミがデッキ0で勝っていない"


def test_all_optional_self_mill_texts_are_optional_in_overlay():
    """全走査: 公式テキストが 「…トラッシュに置いてもよい」 の mill は overlay でも任意。"""
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))}
    effs = json.loads((ROOT / "db" / "card_effects.json").read_text("utf-8"))

    def _walk(o):
        if isinstance(o, dict):
            yield o
            for vv in o.values():
                yield from _walk(vv)
        elif isinstance(o, list):
            for vv in o:
                yield from _walk(vv)

    bad = []
    for cid, ents in effs.items():
        card = cards.get(cid)
        if not card:
            continue
        txt = " ".join(filter(None, [card.get("text"), card.get("trigger")]))
        if "トラッシュに置いてもよい" not in txt:
            continue
        # optional_cost_then の中に入っていない素の mill_self_top が残っていないか
        for ent in ents:
            for node in _walk(ent.get("do") or []):
                if isinstance(node, dict) and "mill_self_top" in node and "optional_cost_then" not in node:
                    if not any("mill_self_top" in str(o.get("optional_cost_then", ""))
                               for o in _walk(ent.get("do") or []) if "optional_cost_then" in o):
                        bad.append(cid)
    assert not bad, f"「置いてもよい」 なのに強制の mill_self_top が残っている: {sorted(set(bad))}"


# --------------------------------------------------------------------------- #
#  公式 Q&A conformance 実測 (2026-08-13 バッチ 3)
# --------------------------------------------------------------------------- #
def test_op05_087_cost_ko_replaced_by_kyros_makes_effect_fizzle():
    """発動コストの自KO が置換されたら **コスト未払い** = 効果は起きない。

    一次情報 (cardqa_op_05、 OP05-087 ハクバ × OP04-082 キュロス):
      Q: 【アタック時】で自キャラ1枚をKOするとき「キュロス」を選び、KOする代わりに
         自分のリーダーか「コリーダコロシアム」をレストにした場合はどうなりますか？
      A: この場合、自分の「キュロス」はKOされず、**この効果で相手のキャラ1枚を
         コスト-5することはできません**。

    是正前: 発動コストの自KO が置換効果 (replace_ko) を一切見ておらず、 キュロスが
    問答無用でトラッシュされ、 コスト-5 まで走っていた。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get("OP05-087"), sickness=False)
    atk.attached_dons = 1                     # 【ドン!!×1】gate
    kyros = InPlay.of(repo.get("OP04-082"), sickness=False)
    me.characters = [atk, kyros]
    victim = InPlay.of(repo.get("OP02-013"), sickness=False)
    opp.characters = [victim]
    from engine.game import _recompute_static
    _recompute_static(st)
    printed = victim.base_cost

    trigger_on_attack(st, me, opp, atk, overlay)
    resolve_triggers(st)

    assert kyros in me.characters, "置換したのにキュロスが KO されている"
    assert me.leader.rested is True, "置換のコスト (リーダーをレスト) が払われていない"
    assert victim.base_cost == printed, \
        f"コスト未払いなのにコスト-5 が適用されている ({printed} → {victim.base_cost})"


def test_op05_087_without_replacement_pays_and_applies():
    """対照: 置換を持たないキャラを犠牲にすればコスト-5 は通る。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get("OP05-087"), sickness=False)
    atk.attached_dons = 1
    fodder = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [atk, fodder]
    victim = InPlay.of(repo.get("OP02-013"), sickness=False)
    opp.characters = [victim]
    from engine.game import _recompute_static
    _recompute_static(st)
    printed = victim.base_cost
    trigger_on_attack(st, me, opp, atk, overlay)
    resolve_triggers(st)
    assert fodder not in me.characters, "犠牲が KO されていない"
    assert victim.base_cost == printed - 5, "コスト-5 が適用されていない"


def test_op02_025_next_reduction_applies_to_only_one_card():
    """OP02-025: 「このターン中、**次に**登場させる…1枚」 = 1 枚だけ割引 (cardqa_op_02)。

    ⚠ 是正前は primitive のコメントに 「(近似: 当ターン中の該当全play)」 と明記されたまま
      消費しておらず、 2 枚目以降も割引されていた。
    """
    import json as _json
    from engine.effects import list_activate_main_effects, fire_activate_main
    from engine.game import PlayCharacter, apply_action
    repo, overlay = _repo(), _overlay()

    def _i(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return None

    cards = _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
    wano = [c for c in cards
            if c["category"] == "CHARACTER" and "ワノ国" in (c.get("features") or "")
            and _i(c.get("cost")) is not None
            and "_p" not in c["card_id"] and "_r" not in c["card_id"]]
    w1 = next(c["card_id"] for c in wano if _i(c["cost"]) == 1)
    w3 = next(c["card_id"] for c in wano if _i(c["cost"]) == 3)

    def _setup(hand_ids):
        st = _state(repo, overlay, leader0="OP02-025")
        me = st.players[0]
        me.hand = [repo.get(c) for c in hand_ids]
        me.don_active = 12
        effs = list_activate_main_effects(st, me, overlay)
        fire_activate_main(st, me, st.players[1], *effs[0])
        resolve_triggers(st)
        return st, me

    st, me = _setup([w3, w3])
    d = me.don_active
    apply_action(st, PlayCharacter(hand_idx=0))
    assert me.don_active == d - 2, "1 枚目に -1 の割引が効いていない"
    d = me.don_active
    apply_action(st, PlayCharacter(hand_idx=0))
    assert me.don_active == d - 3, "「次に」 なのに 2 枚目も割引されている"

    # 対象外 (コスト3未満) のワノ国を挟んでも割引は残る (= 公式 「はい、少なくなります」)
    st, me = _setup([w1, w3])
    d = me.don_active
    apply_action(st, PlayCharacter(hand_idx=0))
    assert me.don_active == d - 1, "対象外カードが割引を受けている"
    d = me.don_active
    apply_action(st, PlayCharacter(hand_idx=0))
    assert me.don_active == d - 2, "対象外カードを挟んだら割引が消えている"


def test_st21_003_blocker_ban_is_per_selected_attacker():
    """ST21-003 の 「ブロッカーを発動できない」 は **選んだキャラのアタック限定** (cardqa_st_21)。"""
    import json as _json
    repo, overlay = _repo(), _overlay()
    cards = _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))

    def _i(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return None

    mugi = next(c["card_id"] for c in cards
                if c["category"] == "CHARACTER"
                and "麦わらの一味" in (c.get("features") or "")
                and (_i(c.get("power")) or 0) >= 6000
                and "_p" not in c["card_id"])
    st = _state(repo, overlay)
    me = st.players[0]
    chosen = InPlay.of(repo.get(mugi), sickness=False)
    other = InPlay.of(repo.get(_FILLER), sickness=False)
    src = InPlay.of(repo.get("ST21-003"), sickness=False)
    me.characters = [chosen, other, src]
    trigger_on_play(st, me, st.players[1], src, overlay)
    resolve_triggers(st)
    assert chosen.attacker_prevents_blocker_until_turn_end is True, \
        "選んだキャラにブロッカー封じが乗っていない"
    assert other.attacker_prevents_blocker_until_turn_end is False, \
        "選んでいないキャラまでブロッカー封じになっている"
    assert me.leader.attacker_prevents_blocker_until_turn_end is False, \
        "リーダーまでブロッカー封じになっている"


def test_st13_003_life_to_hand_goes_to_deck_bottom_after_effect_damage():
    """ST13-003 下では 「自分のライフの上から1枚を手札に加える」 が **デッキの下** になる。

    一次情報 (cardqa_st_13 × OP06-116 排撃): 「相手に1ダメージ与えたあと、自分のライフを
    1枚デッキの下に置きます」。
    """
    from engine.effects import run_do_array
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="ST13-003")
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016")]
    me.life_face_up = [True]
    opp.life = [repo.get(_FILLER)]
    opp.life_face_up = [False]
    _recompute_static(st)
    assert me.face_up_life_to_deck_bottom is True, "前提: ルール置換が張られていない"
    deck_before, hand_before = len(me.deck), len(me.hand)

    ent = [e for e in overlay["OP06-116"].effects if e.get("when") == "main"][0]
    opt2 = ent["do"][0]["choice_effect"]["options"][1]
    run_do_array(list(opt2["do"]), st, me, opp, None)
    resolve_triggers(st)

    assert len(opp.life) == 0, "相手に 1 ダメージが入っていない"
    assert len(me.hand) == hand_before, "表向きライフが手札に加わってしまっている"
    assert len(me.deck) == deck_before + 1 and me.deck[-1].card_id == "OP01-016", \
        "表向きライフがデッキの下に置かれていない"


def test_op01_014_on_block_play_works_with_full_field():
    """自キャラ5枚でも【ブロック時】の登場は発動でき、 1 枚をトラッシュして登場する。"""
    from engine.effects import trigger_on_block
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    blocker = InPlay.of(repo.get("OP01-014"), sickness=False)
    blocker.attached_dons = 1                  # 【ドン!!×1】gate
    me.characters = [blocker] + [InPlay.of(repo.get("OP02-013"), sickness=False)
                                 for _ in range(4)]
    me.hand = [repo.get("OP01-016")]
    _recompute_static(st)
    assert len(me.characters) == 5, "前提: 場が 5 枚でない"
    trigger_on_block(st, me, st.players[1], blocker, overlay)
    resolve_triggers(st)
    assert len(me.characters) == 5, "場が 5 枚を超えている"
    assert any(ip.card.card_id == "OP01-016" for ip in me.characters), \
        "場が満杯だと登場が空振りしている (公式=1枚トラッシュして登場)"
    assert len(me.trash) == 1, "差し替えでトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  公式 Q&A conformance 実測 (2026-08-13 バッチ 4)
# --------------------------------------------------------------------------- #
def test_op01_047_bounces_exactly_once():
    """OP01-047 ロー: 「自分のキャラ1枚を手札に戻すことができる：手札からコスト3以下を登場」。

    ⚠ 是正前は overlay の do に **optional_cost_then の後ろに素の return_to_hand が残って
      おり、 バウンスが 2 回起きていた** (= コストで戻した上に、 もう 1 枚を無償で戻す)。
    公式 (cardqa_op_01): 「戻したキャラカードをそのまま登場させることはできますか」 → はい。
    """
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    src = InPlay.of(repo.get("OP01-047"), sickness=False)
    a = InPlay.of(repo.get("OP01-016"), sickness=False)   # cost1 = コストで戻る側
    b = InPlay.of(repo.get(_FILLER), sickness=False)      # cost2 = 巻き添えになってはいけない
    me.characters = [src, a, b]
    me.don_active = 10
    trigger_on_play(st, me, st.players[1], src, overlay)
    resolve_triggers(st)
    board = [ip.card.card_id for ip in me.characters]
    assert board.count("OP01-016") == 1, "戻したキャラが登場し直していない"
    assert _FILLER in board, "2 枚目のキャラまで手札に戻されている (二重バウンス)"
    assert len(me.characters) == 3, f"場のキャラ数が変わっている: {board}"


def test_st10_001_play_clause_runs_even_without_bounce_target():
    """ST10-001: 相手にパワー3000以下が居なくても 「登場させる」 側は実行できる (cardqa_st_10)。"""
    from engine.effects import list_activate_main_effects, fire_activate_main
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="ST10-001")
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get("OP02-013"), sickness=False)]   # power 7000
    me.hand = [repo.get("OP01-016")]
    me.don_active = 8
    effs = list_activate_main_effects(st, me, overlay)
    assert effs, "起動メインが候補に出ていない"
    fire_activate_main(st, me, opp, *effs[0])
    resolve_triggers(st)
    assert any(ip.card.card_id == "OP01-016" for ip in me.characters), \
        "対象が居ないと登場側まで不発になっている"
    assert len(opp.characters) == 1, "対象外の相手キャラを動かしている"


def test_op02_110_selecting_current_attacker_does_not_cancel_battle():
    """OP02-110【ブロック時】でアタック中のキャラを選んでもバトルは進行する (cardqa_op_02)。"""
    from engine.game import AttackCharacter, _recompute_static
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.turn_player_idx = 1                       # 相手のターン
    me, opp = st.players[0], st.players[1]
    blocker = InPlay.of(repo.get("OP02-110"), sickness=False)   # power 6000
    weak = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [blocker, weak]
    attacker = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 = 効果の対象になれる
    attacker.attached_dons = 6                                  # power 8000
    opp.characters = [attacker]
    _recompute_static(st)
    apply_action(st, AttackCharacter(attacker_iid=attacker.instance_id,
                                     target_iid=weak.instance_id,
                                     blocker_iid=blocker.instance_id))
    assert attacker.cannot_attack_until_turn_end is True, \
        "アタッカーに 「このターン中アタックできない」 が乗っていない"
    assert blocker not in me.characters, \
        "宣言済のバトルが中断されている (公式=通常通り進行してブロッカーが KO される)"


def test_eb03_055_on_ko_damage_wins_against_zero_life():
    """EB03-055【KO時】1 ダメージ: ライフ0 の相手に与えれば勝利する (cardqa_eb_03)。"""
    from engine.effects import trigger_on_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.turn_player_idx = 1                       # 【相手のターン中】
    me, opp = st.players[0], st.players[1]
    opp.life, opp.life_face_up = [], []
    c = InPlay.of(repo.get("EB03-055"), sickness=False)
    me.characters = [c]
    me.characters.remove(c)
    me.trash.append(c.card)
    trigger_on_ko(st, me, opp, c.card, overlay, by_opp_effect=True)
    resolve_triggers(st)
    assert st.game_over is True and st.winner == 0, \
        f"ライフ0 への効果ダメージで勝てていない (winner={st.winner})"


def test_op03_047_on_play_both_clauses_are_optional():
    """OP03-047【登場時】: 「1枚まで戻す」 も 「置いてもよい」 も人間は見送れる (cardqa_op_03)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-047"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [src]
    opp.characters = [victim]
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)
    resolve_triggers(st)
    kinds = []
    for _ in range(5):
        if st.pending_choice is None:
            break
        kinds.append(st.pending_choice.get("kind"))
        resolve_pending_choice(st, [])           # 戻さない / 置かない
    assert "target_pick" in kinds and "optional_cost_confirm" in kinds, \
        f"どちらかの選択が人間に出ていない: {kinds}"
    assert victim in opp.characters, "見送ったのにキャラが戻されている"
    assert len(me.deck) == deck_before, "見送ったのにデッキが削れている"


# --------------------------------------------------------------------------- #
#  公式 Q&A conformance 実測 (2026-08-13 バッチ 5)
# --------------------------------------------------------------------------- #
def test_op12_061_discount_is_filtered_and_one_shot():
    """OP12-061: 「次に登場させる**コスト4以上の「トラファルガー・ロー」**のコストは2少なくなる」。

    ⚠ 是正前は overlay が **filter 無しの素の reduce_play_cost** で、
      ① 「ロー」 以外にも効き ② コスト3の「ロー」 (対象外) が割引を食い潰していた。
    公式 (cardqa_op_12): コスト3の「ロー」 を挟んでも 次のコスト4以上の「ロー」 は -2 される。
    """
    import json as _json
    from engine.effects import list_activate_main_effects, fire_activate_main
    from engine.game import PlayCharacter, apply_action
    repo, overlay = _repo(), _overlay()

    def _i(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return None

    cards = _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
    low = next(c["card_id"] for c in cards
               if c["name"] == "トラファルガー・ロー" and c["category"] == "CHARACTER"
               and _i(c.get("cost")) == 3)
    high = next(c["card_id"] for c in cards
                if c["name"] == "トラファルガー・ロー" and c["category"] == "CHARACTER"
                and (_i(c.get("cost")) or 0) >= 4)

    def _setup(hand_ids):
        st = _state(repo, overlay, leader0="OP12-061")
        me = st.players[0]
        me.hand = [repo.get(c) for c in hand_ids]
        me.don_active = 14
        effs = list_activate_main_effects(st, me, overlay)
        fire_activate_main(st, me, st.players[1], *effs[0])
        resolve_triggers(st)
        return st, me

    st, me = _setup([low, high])
    d = me.don_active
    apply_action(st, PlayCharacter(hand_idx=0))
    assert me.don_active == d - repo.get(low).cost, \
        "コスト3の「ロー」 (対象外) が割引を受けている"
    d = me.don_active
    apply_action(st, PlayCharacter(hand_idx=0))
    assert me.don_active == d - (repo.get(high).cost - 2), \
        "対象外カードを挟んだら割引が消えている"

    # 「ロー」 以外は割引されない
    st, me = _setup(["OP02-013"])
    d = me.don_active
    apply_action(st, PlayCharacter(hand_idx=0))
    assert me.don_active == d - repo.get("OP02-013").cost, \
        "名前が違うカードまで割引されている"


def test_op06_009_copies_leader_power_then_adds_don():
    """OP06-009 シュライヤ: 相手リーダー 5000 + 付与ドン1 → パワー 6000 (cardqa_op_06)。"""
    import json as _json
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    cards = _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
    l5000 = next(c["card_id"] for c in cards
                 if c["category"] == "LEADER" and c.get("power") == "5000")
    st = _state(repo, overlay, leader1=l5000)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP06-009"), sickness=False)
    c.attached_dons = 1
    me.characters = [c]
    _recompute_static(st)
    assert opp.leader.power == 5000, "前提: 相手リーダーが 5000 でない"
    trigger_on_attack(st, me, opp, c, overlay)
    resolve_triggers(st)
    _recompute_static(st)
    assert c.power == 6000, f"パワーが 6000 になっていない ({c.power})"
    assert c.truly_original_power == 5000, \
        "「同じパワーになる」 は元々のパワーを書き換えるはず"


def test_st02_008_cannot_rest_attached_don():
    """ST02-008: レストにできるのは **コストエリア** のドンだけ (cardqa_st_02 = 付与ドンは不可)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    victim.attached_dons = 3
    opp.characters = [victim]
    opp.don_active, opp.don_rested = 0, 0
    atk = InPlay.of(repo.get("ST02-008"), sickness=False)
    atk.attached_dons = 1
    me.characters = [atk]
    trigger_on_attack(st, me, opp, atk, overlay)
    resolve_triggers(st)
    assert victim.attached_dons == 3, "付与ドンをレストにしている"
    assert opp.don_active == 0 and opp.don_rested == 0, "コストエリアが動いている"


def test_op12_034_search_accepts_non_green_slash_card():
    """OP12-034: 「属性(斬)を持つカード**か**緑のイベント」 = 緑以外の斬カードも可 (cardqa_op_12)。"""
    import json as _json
    repo, overlay = _repo(), _overlay()
    cards = _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
    slash = next(c["card_id"] for c in cards
                 if c.get("attribute") == "斬" and "緑" not in (c.get("color") or "")
                 and c["category"] == "CHARACTER")
    lslash = next(c["card_id"] for c in cards
                  if c["category"] == "LEADER" and c.get("attribute") == "斬")
    st = _state(repo, overlay, leader0=lslash)
    me = st.players[0]
    me.deck = [repo.get(slash)] + [repo.get(_FILLER)] * 20
    src = InPlay.of(repo.get("OP12-034"), sickness=False)
    me.characters = [src]
    trigger_on_play(st, me, st.players[1], src, overlay)
    resolve_triggers(st)
    assert any(c.card_id == slash for c in me.hand), \
        f"緑以外の 属性(斬) カード ({slash}) が手札に加わっていない"


def test_op15_075_pump_applies_with_no_opponent_characters():
    """OP15-075: 相手キャラ 0 枚でも 「自リーダーかキャラ +1000」 は実行できる (cardqa_op_15)。"""
    import json as _json
    from engine.effects import run_do_array
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    cards = _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
    enel = next(c["card_id"] for c in cards
                if c["category"] == "LEADER" and c["name"] == "エネル")
    st = _state(repo, overlay, leader0=enel)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    opp.characters = []
    _recompute_static(st)
    before = me.leader.power
    ent = [e for e in overlay["OP15-075"].effects if e.get("when") == "main"][0]
    run_do_array(list(ent["do"]), st, me, opp, None)
    resolve_triggers(st)
    assert me.leader.power == before + 1000, \
        f"相手キャラが居ないと pump まで不発になっている ({before} → {me.leader.power})"


def test_op01_047_cost_bounce_replaced_by_enel_makes_effect_fizzle():
    """発動コストの 「自キャラを手札に戻す」 が置換されたら **コスト未払い** = 効果は起きない。

    一次情報 (cardqa_op_05、 OP01-047 ロー × OP05-100 エネル):
      Q: 「自分のキャラ1枚を持ち主の手札に戻すことができる:」 でこのキャラ (エネル) を選び、
         代わりに自分のライフを1枚トラッシュに置いた場合、 コスト3以下のキャラを手札から
         登場できますか？
      A: **いいえ、できません。**

    ⚠ AI 経路 (cost handler) だけでなく **人間 modal の解決経路 (self_chara_cost_pick) も
      独自にカードを動かしており置換を迂回していた**。 置換の 「使う/使わない」 は modal で
      後から決まるので、 その解決後に盤面を見てコストの成否を判定する。
    """
    repo, overlay = _repo(), _overlay()

    def _run(pick_card_id, use_replace):
        st = _state(repo, overlay, human_idx=0)
        me = st.players[0]
        src = InPlay.of(repo.get("OP01-047"), sickness=False)
        enel = InPlay.of(repo.get("OP05-100"), sickness=False)
        other = InPlay.of(repo.get(_FILLER), sickness=False)
        me.characters = [src, enel, other]
        me.hand = [repo.get("OP01-016")]        # cost1 = 登場候補
        me.don_active = 10
        life_before = len(me.life)
        trigger_on_play(st, me, st.players[1], src, overlay)
        resolve_triggers(st)
        for _ in range(8):
            pc = st.pending_choice
            if pc is None:
                break
            kind = pc.get("kind")
            if kind == "self_chara_cost_pick":
                cands = pc.get("candidates", [])
                idx = [i for i, c in enumerate(cands) if c.get("card_id") == pick_card_id]
                picks = [idx[0]] if idx else [0]
            elif kind in ("replace_ko_optional", "replace_leave_optional"):
                picks = [1 if use_replace else 0]
            elif kind in ("optional_cost_confirm",):
                picks = [1]
            elif kind == "play_from_hand_pick":
                picks = [0]
            else:
                picks = []
            resolve_pending_choice(st, picks)
        return st, me, life_before

    # A) エネルを選び 置換を使う → エネルは場に残り、 コスト3以下の登場は **起きない**
    st, me, life_before = _run("OP05-100", use_replace=True)
    assert any(ip.card.card_id == "OP05-100" for ip in me.characters), \
        "置換したのにエネルが場を離れている"
    assert len(me.life) == life_before - 1, "置換のコスト (ライフ1枚トラッシュ) が払われていない"
    assert not any(ip.card.card_id == "OP01-016" for ip in me.characters), \
        "コスト未払いなのに手札からキャラが登場している"
    assert any(c.card_id == "OP01-016" for c in me.hand), "登場候補が手札から消えている"

    # B) 対照: 置換を使わなければ 手札に戻り、 効果は通る
    st, me, life_before = _run("OP05-100", use_replace=False)
    assert any(c.card_id == "OP05-100" for c in me.hand), "エネルが手札に戻っていない"
    assert len(me.life) == life_before, "置換していないのにライフが減っている"
    assert any(ip.card.card_id == "OP01-016" for ip in me.characters), \
        "コストを払ったのに登場していない"


# --------------------------------------------------------------------------- #
#  公式 Q&A conformance 実測 (2026-08-13 バッチ 6)
# --------------------------------------------------------------------------- #
def test_trigger_can_be_declared_even_when_its_condition_fails():
    """【トリガー】は 「〜の場合」 が不成立でも **発動できる** (カードはトラッシュへ)。

    一次情報 (cardqa_op_03、 OP03-033 はっちゃん):
      Q: 自分のリーダーが特徴《東の海》を持たない場合、この【トリガー】を発動できますか？
      A: **はい、発動できます。**【トリガー】を発動した場合、このカードは登場せず
         **トラッシュ**に置きます。

    ⭐ 「効果の条件が不成立」 と 「発動コストが払えない」 は別物:
      コスト不払い → 発動できない (4-10) / 条件不成立 → 発動はできて何も起きない。
    ⚠ 是正前は条件も合法性 gate に混ぜており、 条件不成立だと **カードが手札に加わって**
      いた (= 公式より得をしていた)。
    """
    import json as _json
    from engine.game import _resolve_life_taken
    from engine.effects import should_fire_trigger
    repo, overlay = _repo(), _overlay()
    cards = _json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
    east = next(c["card_id"] for c in cards
                if c["category"] == "LEADER" and "東の海" in (c.get("features") or ""))

    def _run(east_leader, use_trigger):
        st = _state(repo, overlay, leader1=(east if east_leader else "OP01-001"))
        me, opp = st.players[0], st.players[1]
        opp.life = [repo.get("OP03-033")]
        opp.life_face_up = [False]
        ai_choice = should_fire_trigger(st, opp, repo.get("OP03-033"), overlay)
        taken = opp.life.pop(0)
        opp.life_face_up.pop(0)
        _resolve_life_taken(st, me, opp, taken, use_trigger=use_trigger)
        resolve_triggers(st)
        return opp, ai_choice

    # 条件不成立 + 人間が発動を選ぶ → 登場せず **トラッシュ**
    opp, _ = _run(False, True)
    assert not opp.characters, "条件不成立なのに登場している"
    assert not opp.hand, "発動したのに手札に加わっている (公式=トラッシュ)"
    assert any(c.card_id == "OP03-033" for c in opp.trash), "トラッシュに置かれていない"

    # 条件不成立 + 発動しない → 手札 (対照)
    opp, _ = _run(False, False)
    assert any(c.card_id == "OP03-033" for c in opp.hand), "発動しないなら手札のはず"

    # 条件成立 + 発動 → 登場 (対照)
    opp, _ = _run(True, True)
    assert any(ip.card.card_id == "OP03-033" for ip in opp.characters), "条件成立で登場していない"

    # ⚠ AI は条件不成立なら見送る (= 自動対戦の挙動は不変)
    opp, ai_choice = _run(False, None)
    assert ai_choice is False, "AI が条件不成立の【トリガー】を発動しようとしている"
    assert any(c.card_id == "OP03-033" for c in opp.hand), "AI 経路で手札に入っていない"


def test_st31_003_blocker_is_lost_when_attached_don_drops_mid_attack():
    """ST31-003: 付与ドン合計が 3 未満になった瞬間に【ブロッカー】と +3000 を失う。"""
    from engine.game import _recompute_static
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    st.turn_player_idx = 1                       # 【相手のターン中】
    me = st.players[0]
    b = InPlay.of(repo.get("ST31-003"), sickness=False)
    b.attached_dons = 2
    other = InPlay.of(repo.get(_FILLER), sickness=False)
    other.attached_dons = 1
    me.characters = [b, other]
    _recompute_static(st)
    assert b.is_blocker_now is True and b.power == 6000, "前提: 合計3で条件成立していない"
    me.characters.remove(other)                  # = 相手の【アタック時】で場を離れた
    _recompute_static(st)
    assert b.is_blocker_now is False, "合計2 になってもブロッカーを保持している"
    assert b.power == 3000, f"+3000 が残っている (power={b.power})"


def test_op13_082_trashes_itself_too():
    """OP13-082「自分のキャラすべてをトラッシュに置き」 は **このキャラ自身も含む** (cardqa_op_13)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    src = InPlay.of(repo.get("OP13-082"), sickness=False)
    other = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [src, other]
    execute_effect({"trash_all_self_chara": True}, st, me, st.players[1], src)
    resolve_triggers(st)
    assert not me.characters, f"自身が場に残っている: {[c.card.card_id for c in me.characters]}"
    assert any(c.card_id == "OP13-082" for c in me.trash), "自身がトラッシュに無い"


def test_op11_086_can_be_played_with_empty_hand():
    """OP11-086: 手札0枚でも登場できる (【登場時】の強制1枚捨ては空振り、 cardqa_op_11)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    src = InPlay.of(repo.get("OP11-086"), sickness=False)
    me.characters = [src]
    me.hand = []
    trigger_on_play(st, me, st.players[1], src, overlay)
    resolve_triggers(st)
    assert src in me.characters, "手札0枚で登場が巻き戻されている"
    assert not me.hand


def test_op06_035_life_to_hand_is_mandatory_even_without_rest_targets():
    """OP06-035: レスト対象が居なくても 「その後、自ライフ1枚を手札に加える」 は必須 (cardqa_op_06)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP06-035"), sickness=False)
    me.characters = [src]
    opp.characters = []
    opp.don_active, opp.don_rested = 0, 0        # レストできる対象ゼロ
    hand_before, life_before = len(me.hand), len(me.life)
    trigger_on_play(st, me, opp, src, overlay)
    resolve_triggers(st)
    assert len(me.hand) == hand_before + 1, "ライフが手札に加わっていない"
    assert len(me.life) == life_before - 1, "ライフが減っていない"


# ─────────────────────────────────────────────────────────────────────────────
#  置換効果 (replace_ko / replace_leave) の **代替行動 (do) が遂行不能なら置換を選べない**
#  一次情報 (cardqa_op_07):
#   - OP07-042 ゲッコー・モリア 「自分の『ゲッコー・モリア』以外のキャラがいない時、
#       この【ターン1回】効果でこのキャラが場を離れない事はできますか？」→「いいえ、できません。」
#   - OP07-029 バジル・ホーキンス 「相手の場にアクティブのキャラがない場合、この【ターン1回】
#       効果でこのキャラが場を離れない事はできますか？」→「いいえ、できません。」
#  = 「代わりに X をレスト/デッキ下/KO する」 の対象が居なければ 代替行動を遂行できず、
#    置換を選べない (= 本来の離脱が起こる)。 是正前は do の対象0でも try_replace_ko が True を
#    返し KO/離脱を回避できていた (= Python も Rust も同じ穴を共有 = 差分検証では沈黙、
#    公式 Q&A だけが検出できた領域)。
# ─────────────────────────────────────────────────────────────────────────────
def test_op07_042_replace_leave_needs_valid_deck_bottom_target():
    """OP07-042: 「ゲッコー・モリア」以外のキャラが居なければ 置換 (デッキ下) を選べない。"""
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader0="OP06-080")  # 王下七武海 リーダー
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP07-042"), sickness=False)
    me.characters = [moria]  # モリア自身のみ = 「以外のキャラ」不在
    replaced = try_replace_ko(st, me, opp, moria, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is False, "対象不在で置換成立してはいけない (cardqa_op_07)"
    assert moria in me.characters, "置換不成立でも本来の離脱はこの後 呼出側が行う"
    # 対照: 別キャラが居れば置換成立 (別キャラがデッキ下へ、 モリアは残る)
    st = _state(repo, overlay, leader0="OP06-080")
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP07-042"), sickness=False)
    other = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [moria, other]
    replaced = try_replace_ko(st, me, opp, moria, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True, "別キャラが居れば置換成立"
    assert other not in me.characters, "別キャラがデッキ下へ"


def test_op07_029_replace_leave_needs_active_opp_target():
    """OP07-029: 相手のアクティブキャラが居なければ 置換 (相手キャラをレスト) を選べない。"""
    from engine.effects import try_replace_ko
    repo, overlay = _repo(), _overlay()
    # 相手キャラ皆無 → 置換不成立
    st = _state(repo, overlay, leader0="OP06-080")
    me, opp = st.players[0], st.players[1]
    hawkins = InPlay.of(repo.get("OP07-029"), sickness=False)
    me.characters = [hawkins]
    opp.characters = []
    assert try_replace_ko(st, me, opp, hawkins, overlay, by_opp_effect=True, leave_kind="ko") is False
    # 相手キャラは居るが全てレスト済 → レストにできない = 置換不成立
    st = _state(repo, overlay, leader0="OP06-080")
    me, opp = st.players[0], st.players[1]
    hawkins = InPlay.of(repo.get("OP07-029"), sickness=False)
    me.characters = [hawkins]
    rested = InPlay.of(repo.get("OP01-013"), sickness=False)
    rested.rested = True
    opp.characters = [rested]
    assert try_replace_ko(st, me, opp, hawkins, overlay, by_opp_effect=True, leave_kind="ko") is False
    # 対照: 相手アクティブキャラが居れば置換成立 (そのキャラがレストに)
    st = _state(repo, overlay, leader0="OP06-080")
    me, opp = st.players[0], st.players[1]
    hawkins = InPlay.of(repo.get("OP07-029"), sickness=False)
    me.characters = [hawkins]
    active = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [active]
    assert try_replace_ko(st, me, opp, hawkins, overlay, by_opp_effect=True, leave_kind="ko") is True
    assert active.rested is True, "相手アクティブキャラがレストされる"


def test_replace_do_target_gate_full_scan():
    """overlay 全走査: do が **対象を取る primitive のみ** で構成される replace_ko/replace_leave
    は、 空盤面 (= 対象皆無) では _replace_do_performable が False を返す (= 置換不可) こと。
    self/victim 参照・非対象 primitive・判定不能 spec を含む do は 従来どおり True (許可)。
    同型の取りこぼし (= 対象0でもタダで KO/離脱を回避) が他カードに残らないことを保証する。
    """
    from engine.effects import (
        _replace_do_performable,
        _REPLACE_DO_TARGETED,
    )
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    opp.characters = []
    me.don_active = 0
    opp.don_active = 0

    def _self_or_victim(v):
        t = v.get("target") if isinstance(v, dict) else v
        if isinstance(v, dict) and v.get("type") in ("self", "victim"):
            return True
        return t in ("self", "victim")

    checked = 0
    for cid, bundle in overlay.items():
        for eff in bundle.effects:
            if eff.get("when") not in ("replace_ko", "replace_leave"):
                continue
            do = eff.get("do", [])
            if not do:
                continue
            # do が 「対象を取る primitive のみ」 かつ self/victim 参照を含まないか
            keys = [k for prim in do if isinstance(prim, dict) for k in prim]
            if not keys or any(k not in _REPLACE_DO_TARGETED for k in keys):
                continue
            if any(
                _self_or_victim(v)
                for prim in do if isinstance(prim, dict)
                for v in prim.values()
            ):
                continue
            # 空盤面 (対象皆無) では 遂行不能 = False であるべき
            assert _replace_do_performable(do, me, opp) is False, (
                f"{cid}: 空盤面で置換 do が遂行可能と判定された "
                f"(対象0でも KO/離脱を回避できる穴)"
            )
            checked += 1
    # OP07-042 / OP07-029 / OP05-032 / OP10-037 / OP14-034 等が該当
    assert checked >= 4, f"走査対象が少なすぎる (checked={checked}) = スキャン失効の疑い"


# --------------------------------------------------------------------------- #
#  OP09-081 ティーチ: 「相手の【登場時】効果は無効になる」 は【トリガー】経由の
#  自身【登場時】再発火にも及ぶ (fire_self_effect when_kind="on_play")。
#  一次情報 (cardqa_op_09 / bc3c4dfda176):
#    「自分がこの【起動メイン】効果を使用したターンに、相手がダメージを受け、そのライフが
#     「OP08-106 ナミ」でした。この場合、「OP08-106 ナミ」の「【トリガー】このカードの
#     【登場時】効果を発動する。」の効果はどうなりますか？」
#    →「この場合、相手は…【トリガー】を発動することを選ぶことはできますが、【登場時】効果は
#      発動しないため何も起きず…トラッシュに置かれます。」
#  = 無効化中は トリガー経由の【登場時】も不発。 コピー経路 (fire_self_effect) が gate を
#    素通りしていた (trigger_on_play にはあるが fire_self_effect には無かった) のを是正。
# --------------------------------------------------------------------------- #
def test_op09_081_disable_covers_trigger_fired_on_play():
    repo, overlay = _repo(), _overlay()

    def _fire(disable: bool):
        st = _state(repo, overlay)
        me, opp = st.players[0], st.players[1]
        # me = ナミ所有者。 手札に【トリガー】持ち (発動コストの捨て札) + 相手にコスト2キャラ。
        me.hand = [repo.get("EB04-020")]
        opp.characters = [InPlay.of(repo.get(_FILLER))]
        me.opp_on_play_disabled_through_opp_turn = disable
        nami = InPlay.of(repo.get("OP08-106"))
        execute_effect({"fire_self_effect": {"when_kind": "on_play"}}, st, me, opp, nami)
        return len(opp.characters)

    # 対照: 無効化されていなければ【登場時】が発動し 相手コスト2キャラが KO される
    assert _fire(disable=False) == 0, "前提が崩れている: ナミ【登場時】が KO を発火していない"
    # 本題: OP09-081 の無効化中は トリガー経由の【登場時】も不発 = KO は起きない
    assert _fire(disable=True) == 1, (
        "OP09-081 無効化中なのに【トリガー】経由の【登場時】が発動して KO した (公式違反)"
    )
