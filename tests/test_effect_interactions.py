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
    trigger_on_attack,
    trigger_on_play,
)
from engine.game import AttackCharacter, AttackLeader, apply_action, _fire_counter_events

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
#  D. 置換効果 (replace_ko) のコスト手札捨ては 「効果で捨てた」 扱いにしない
#     ⚠ hand_discarded_by_effect_this_turn を立てず on_self_hand_discarded も発火しない。
# --------------------------------------------------------------------------- #
def test_replace_ko_cost_discard_does_not_set_hand_discarded_flag():
    """KO 置換のコストで手札を捨てても 「効果で手札を捨てた」 フラグは立たない。"""
    from engine.effects import try_replace_ko

    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # OP15-003 アルビダ: KO されそうな時、 手札のパワー6000以下キャラ1枚を捨てて KO を代替。
    albida = InPlay.of(repo.get("OP15-003"), sickness=False)
    me.characters = [albida]
    me.hand = [repo.get(_FILLER)]           # power3000 CHARACTER = コストに使える
    hand_before = len(me.hand)

    replaced = try_replace_ko(st, me, opp, albida, overlay, by_opp_effect=True, leave_kind="ko")

    assert replaced is True, "コストを払えるのに KO 置換が成立していない"
    assert len(me.hand) == hand_before - 1, "置換コストの手札捨てが行われていない"
    assert getattr(me, "hand_discarded_by_effect_this_turn", False) is False, (
        "置換コストの手札捨てで hand_discarded_by_effect_this_turn が立ってはいけない"
        " (Python _pay_replace_cost はフラグを立てない)"
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
def test_trash_self_cost_is_not_a_ko():
    """自身をトラッシュに置くコストは KO ではない (被 KO 数が増えない)。"""
    from engine.effects import _pay_counter_cost

    repo, overlay = _repo(), _overlay()
    eff = next(e for e in overlay.get("OP03-043").effects
               if e.get("when") == "on_opp_life_taken")
    assert eff["cost"] == {"trash_self": True}, (
        f"公式は 「このキャラをトラッシュに置く」 なので trash_self のはず: {eff['cost']}"
    )

    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-043"), sickness=False)
    me.characters = [src]
    _pay_counter_cost(st, me, opp, src, eff["cost"])

    assert src not in me.characters, "コストで自身が場を離れていない"
    assert me.trash and me.trash[-1].card_id == "OP03-043", "トラッシュに置かれていない"
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
def test_face_up_life_never_exceeds_life_count():
    """ライフが減ったら表向き枚数もそれ以下に正規化される。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)]
    me.face_up_life_count = 1

    me.life.clear()                       # ダメージ等でライフが尽きた状況
    evaluate_static_effects(st, overlay)  # = 両エンジンが回す正規化フック

    assert me.face_up_life_count == 0, (
        f"ライフ 0 なのに表向き {me.face_up_life_count} 枚が残っている"
    )


def test_stale_face_up_does_not_mark_new_life_as_face_up():
    """ライフが再び増えた時、 古い表向きカウントが新しい裏向きライフを表向きにしない。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)]
    me.face_up_life_count = 1
    me.life.clear()
    evaluate_static_effects(st, overlay)          # ここで 0 に正規化される

    me.life.append(repo.get(_FILLER))             # 効果でライフを 1 枚積み直す (裏向き)
    evaluate_static_effects(st, overlay)
    assert me.face_up_life_count == 0, (
        "新しく置いた裏向きのライフが表向き扱いになっている"
        f" (face_up={me.face_up_life_count})"
    )


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
    me = st.players[0]
    c = InPlay.of(repo.get(_FILLER), sickness=False)   # rest_self コストの起動メインを持つ
    me.characters = [c]

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
    p0.face_up_life_count = face_up_life
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
            if m and not m.group(1):
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
    """OP12-017: 「**赤のイベント**かコスト3以上の**キャラカード**」 の or を両方満たす。

    ⚠ 2026-08-05 まで filter が `{"cost_ge": 3}` だけで、 赤のイベントが引けず
      コスト3以上のイベント/ステージが誤って引けた。 コストも未実装 (タダ撃ち) だった。
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
        {"category": "CHARACTER", "cost_ge": 3},
    ], f"公式の 「赤のイベントか コスト3以上のキャラカード」 と一致しない: {filt}"


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
