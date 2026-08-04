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

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_play,
)
from engine.game import AttackCharacter, AttackLeader, apply_action

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
