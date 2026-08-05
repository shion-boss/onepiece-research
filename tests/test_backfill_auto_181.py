# -*- coding: utf-8 -*-
"""ST19 / ST20 / ST21 弾 効果 回帰テスト バックフィル (自動生成 wave 181):
ST19-002 / ST19-003 / ST19-004 / ST19-005 / ST20-001 / ST20-002 /
ST20-003 / ST20-004 / ST20-005 / ST21-001 の 10 枚。

目的 (= test_backfill_auto_001〜180.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave181_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST19-002", "ST19-003", "ST19-004", "ST19-005", "ST20-001",
           "ST20-002", "ST20-003", "ST20-004", "ST20-005", "ST21-001"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST19-002 センゴク (CHARACTER 黒 cost1):
#    【登場時】自分の手札から黒の特徴《海軍》を持つカード2枚を捨てることができる：
#    自分のリーダーが特徴《海軍》を持つ場合、カード3枚を引く。
# --------------------------------------------------------------------------- #
def test_st19_002_on_play_discard2_draw3_ai():
    """【登場時】黒海軍2枚を捨てて 海軍リーダーなら3枚引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-001", overlay)  # コビー (海軍/SWORD)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP03-089"), repo.get("OP02-103")]  # 黒海軍 2 枚
    me.deck = [repo.get("OP01-016")] * 10

    deck_before = len(me.deck)
    do, _ = _do(overlay, "ST19-002", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST19-002"), sickness=True))
    _drain(st, [0])

    # 手札: -2 (捨て) +3 (ドロー) = 元 2 → 3。 deck -3。 trash に 2 枚。
    assert len(me.hand) == 3, \
        f"手札 net (捨て -2 + ドロー +3) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 3, "3 ドローでデッキが 3 枚減っていない"
    assert len([c for c in me.trash if "海軍" in (c.features or "")]) == 2, \
        "捨てた黒海軍 2 枚がトラッシュに置かれていない"


def test_st19_002_on_play_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で
    黒海軍2枚を捨てて3枚引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP03-089"), repo.get("OP02-103")]
    me.deck = [repo.get("OP01-016")] * 10

    do, _ = _do(overlay, "ST19-002", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("ST19-002"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払って発動)
    _drain(st, [0])
    assert len(me.hand) == 3, "人間承諾後 3 ドローが反映されていない"


# --------------------------------------------------------------------------- #
#  ST19-003 たしぎ (CHARACTER 黒 cost5):
#    【登場時】自分のリーダーが「スモーカー」の場合、相手のキャラ1枚までを、
#    このターン中、コスト-4。
#    【起動メイン】【ターン1回】このキャラが登場したターンの場合、相手のコスト0の
#    キャラ1枚までを、トラッシュに置く。
# --------------------------------------------------------------------------- #
def test_st19_003_on_play_cost_minus_smoker_ai():
    """【登場時】スモーカーリーダー → 相手キャラを このターン中 コスト-4 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-093", overlay)  # スモーカー (黒)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP03-089"), sickness=False)  # 印刷コスト2
    opp.characters = [victim]

    do, eff = _do(overlay, "ST19-003", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "スモーカーリーダーで on_play 条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST19-003"), sickness=True))
    _drain(st, [0])
    assert victim.cost_minus_until_turn_end == 4, \
        f"相手キャラの コスト-4 が反映されていない: {victim.cost_minus_until_turn_end}"
    assert victim.base_cost == 0, \
        f"コスト-4 後の base_cost が 0 でない: {victim.base_cost}"


def test_st19_003_on_play_leader_gate():
    """on_play の【リーダー「スモーカー」】ゲートが正しく効く。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "ST19-003", "on_play")
    st_ok = _state(repo, "OP02-093", overlay)  # スモーカー
    assert eval_condition(eff.get("if", {}), st_ok, st_ok.players[0]) is True, \
        "スモーカーリーダーで条件が成立していない"
    st_ng = _state(repo, "OP01-001", overlay)  # ゾロ (非スモーカー)
    assert eval_condition(eff.get("if", {}), st_ng, st_ng.players[0]) is False, \
        "非スモーカーリーダーで条件が成立してはいけない"


def test_st19_003_activate_main_gated_by_summoning_sickness():
    """【起動メイン】は「このキャラが登場したターンの場合」限定。
    召喚酔い中のみ legal、 酔いが抜けたら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-093", overlay)
    me, opp = st.players[0], st.players[1]
    # 相手にコスト>0 のキャラ (printed cost 判定なので cost0 のみ実対象、 ここでは no-op 確認)
    opp.characters = [InPlay.of(repo.get("OP03-089"), sickness=False)]

    sick = InPlay.of(repo.get("ST19-003"), sickness=True)  # 登場したターン
    me.characters = [sick]
    opts_sick = [o for o in list_activate_main_effects(st, me, overlay)
                 if o[0].card.card_id == "ST19-003"]
    assert len(opts_sick) == 1, \
        f"召喚酔い中に起動メインが legal に出ない: {len(opts_sick)}"

    sick.summoning_sickness = False  # 登場ターンを過ぎた
    opts_notsick = [o for o in list_activate_main_effects(st, me, overlay)
                    if o[0].card.card_id == "ST19-003"]
    assert len(opts_notsick) == 0, \
        "登場ターン以外で起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST19-004 ヒナ (CHARACTER 黒 cost4):
#    【ドン‼×1】【相手のターン中】このキャラのコスト+4。
#    【起動メイン】【ターン1回】自分のトラッシュのカード1枚をデッキの下に置くことが
#    できる：自分のリーダーかキャラ1枚にレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_st19_004_activate_main_trash_to_deck_attach_don_ai():
    """【起動メイン】トラッシュ1枚をデッキ下へ (コスト) → 自リーダーにレストドン1付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay)  # 黒 クロコダイル
    me, opp = st.players[0], st.players[1]
    hina = InPlay.of(repo.get("ST19-004"), sickness=False)
    me.characters = [hina]
    me.trash = [repo.get("OP01-016")]  # デッキ下に置くコスト用
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST19-004"]
    assert len(opts) == 1, f"ST19-004 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 1, \
        f"自リーダーへ レストドン1が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"
    assert len(me.trash) == trash_before - 1, "トラッシュ1枚がデッキ下へ移るべき (コスト)"
    assert len(me.deck) == deck_before + 1, "コストで1枚がデッキに戻るべき"


def test_st19_004_static_cost_plus4_opp_turn():
    """【ドン‼×1】【相手のターン中】このキャラのコスト+4 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay, turn_player=1)  # 相手 (P1) のターン
    me = st.players[0]
    hina = InPlay.of(repo.get("ST19-004"), sickness=False)  # 印刷コスト4
    hina.attached_dons = 1  # 【ドン‼×1】 ゲート成立
    me.characters = [hina]

    evaluate_static_effects(st, overlay)
    assert hina.base_cost == 4 + 4, \
        f"相手ターン中の コスト+4 が反映されていない: {hina.base_cost}"


def test_st19_004_static_no_cost_plus_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → コスト+4 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay, turn_player=0)  # 自分 (P0) のターン
    me = st.players[0]
    hina = InPlay.of(repo.get("ST19-004"), sickness=False)
    hina.attached_dons = 1
    me.characters = [hina]

    evaluate_static_effects(st, overlay)
    assert hina.base_cost == 4, \
        f"自ターンで コスト+4 が乗ってはいけない: {hina.base_cost}"


# --------------------------------------------------------------------------- #
#  ST19-005 モンキー・D・ガープ (CHARACTER 黒 cost3):
#    【ブロッカー】【起動メイン】【ターン1回】自分のトラッシュのカード1枚をデッキの下に
#    置くことができる：相手のキャラ1枚までを、このターン中、コスト-1。
# --------------------------------------------------------------------------- #
def test_st19_005_activate_main_trash_to_deck_cost_minus_ai():
    """【起動メイン】トラッシュ1枚をデッキ下へ (コスト) → 相手キャラ このターン中 コスト-1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("ST19-005"), sickness=False)
    me.characters = [garp]
    me.trash = [repo.get("OP01-016")]  # デッキ下コスト用
    victim = InPlay.of(repo.get("OP03-089"), sickness=False)  # 印刷コスト2
    opp.characters = [victim]

    trash_before = len(me.trash)
    deck_before = len(me.deck)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST19-005"]
    assert len(opts) == 1, f"ST19-005 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert victim.cost_minus_until_turn_end == 1, \
        f"相手キャラの コスト-1 が反映されていない: {victim.cost_minus_until_turn_end}"
    assert len(me.trash) == trash_before - 1, "トラッシュ1枚がデッキ下へ移るべき (コスト)"
    assert len(me.deck) == deck_before + 1, "コストで1枚がデッキに戻るべき"


def test_st19_005_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("ST19-005"), sickness=False)
    me.characters = [garp]
    me.trash = [repo.get("OP01-016"), repo.get("OP01-016")]
    opp.characters = [InPlay.of(repo.get("OP03-089"), sickness=False)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST19-005"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST19-005"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST20-001 シャーロット・カタクリ (CHARACTER 黄 cost5):
#    【ブロッカー】【起動メイン】【ターン1回】自分のライフの上から1枚を表向きにできる：
#    自分のリーダーかキャラ1枚にレストのドン!!1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_st20_001_activate_main_flip_life_attach_don_ai():
    """【起動メイン】ライフ上1枚を表向き (コスト) → 自リーダーにレストドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay)  # 黄 エネル
    me, opp = st.players[0], st.players[1]
    kata = InPlay.of(repo.get("ST20-001"), sickness=False)
    me.characters = [kata]
    me.life = [repo.get("OP01-016"), repo.get("OP01-016")]  # 裏向きライフ 2
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    faceup_before = me.face_up_life_count

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST20-001"]
    assert len(opts) == 1, f"ST20-001 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 1, \
        f"自リーダーへ レストドン1が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"
    assert me.face_up_life_count == faceup_before + 1, \
        "コストでライフ上1枚が表向きになっていない"


# --------------------------------------------------------------------------- #
#  ST20-002 シャーロット・クラッカー (CHARACTER 黄 cost4):
#    【ターン1回】このキャラが効果でKOされる場合、代わりに自分のライフの上から1枚を
#    トラッシュに置いてもよい。 / 【トリガー】手札1枚を捨てて自身を登場。
# --------------------------------------------------------------------------- #
def test_st20_002_replace_ko_mill_life_ai():
    """効果KO時: 代わりに自ライフ上1枚をトラッシュへ置き KO を代替 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay)
    me, opp = st.players[0], st.players[1]
    cracker = InPlay.of(repo.get("ST20-002"), sickness=False)
    me.characters = [cracker]
    me.life = [repo.get("OP01-016"), repo.get("OP01-016")]  # ライフ 2

    life_before = len(me.life)
    trash_before = len(me.trash)
    replaced = try_replace_ko(
        st, me, opp, cracker, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "効果KO を ライフトラッシュで代替できていない"
    assert cracker in me.characters, "置換成立時 クラッカーは場に残るべき"
    assert len(me.life) == life_before - 1, "代替コストで自ライフが1枚減るべき"
    assert len(me.trash) == trash_before + 1, "減ったライフがトラッシュへ置かれるべき"


def test_st20_002_replace_ko_human_confirm():
    """人間 actor: replace_ko は 任意 → replace_ko_optional modal が立ち、
    承諾で ライフ1枚を捨てて KO を代替する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    cracker = InPlay.of(repo.get("ST20-002"), sickness=False)
    me.characters = [cracker]
    me.life = [repo.get("OP01-016"), repo.get("OP01-016")]

    replaced = try_replace_ko(
        st, me, opp, cracker, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 代替する)
    _drain(st, [1])
    assert cracker in me.characters, "人間承諾後 クラッカーは場に残るべき"


def test_st20_002_trigger_discard_play_self_ai():
    """【トリガー】手札1枚を捨てて 自身を登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay)
    me, opp = st.players[0], st.players[1]
    # trigger 発火文脈: 自身は trash にあり (= ライフから捲れた後想定)、 手札に捨てコスト1枚。
    st.current_source_card_id = "ST20-002"
    me.trash = [repo.get("ST20-002")]
    me.hand = [repo.get("OP01-016")]  # 捨てるコスト用

    do, _ = _do(overlay, "ST20-002", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert any(c.card.card_id == "ST20-002" for c in me.characters), \
        "トリガーで クラッカー自身が登場していない"
    assert len(me.hand) == 0, "登場コストで手札1枚が捨てられるべき"


# --------------------------------------------------------------------------- #
#  ST20-003 シャーロット・ブリュレ (CHARACTER 黄 cost3):
#    【トリガー】自分か相手のライフの上から1枚を見て、上か下に置く → このカードを手札に。
# --------------------------------------------------------------------------- #
def test_st20_003_trigger_view_life_ai():
    """【トリガー】ライフ上1枚を見て並べ替え → crash せず ライフ枚数保存 + keep フラグ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016"), repo.get("OP01-016")]
    opp.life = [repo.get("OP01-016"), repo.get("OP01-016")]
    st.last_trigger_kept_in_hand = False

    self_life_before = len(me.life)
    opp_life_before = len(opp.life)
    do, _ = _do(overlay, "ST20-003", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0, 0])

    assert len(me.life) == self_life_before, "ライフ並べ替えで自ライフ枚数が変化してはいけない"
    assert len(opp.life) == opp_life_before, "ライフ並べ替えで相手ライフ枚数が変化してはいけない"
    assert st.last_trigger_kept_in_hand is True, \
        "トリガーで『このカードを手札に加える』フラグが立っていない"


def test_st20_003_trigger_view_life_human_modal():
    """人間 actor: owner=either → view_life_top_choose_position modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016"), repo.get("OP01-016")]
    opp.life = [repo.get("OP01-016"), repo.get("OP01-016")]

    do, _ = _do(overlay, "ST20-003", "trigger")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + ライフ確認で modal が立たない"
    assert st.pending_choice.get("kind") == "view_life_top_choose_position", \
        f"kind が view_life_top_choose_position でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0, 0])  # 自ライフ・上に戻す
    assert st.pending_choice is None, "解決後も modal が残る"


# --------------------------------------------------------------------------- #
#  ST20-004 シャーロット・プリン (CHARACTER 黄 cost3):
#    【登場時】自分のライフの上から1枚を手札に加えることができる：自分のコスト3以下の
#    特徴《ビッグ・マム海賊団》を持つキャラ1枚までを、アクティブにする。
#    【トリガー】相手のコスト3以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_st20_004_on_play_life_to_hand_untap_ai():
    """【登場時】ライフ1枚を手札へ (コスト) → 自 BM cost3以下キャラをアクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay)
    me, opp = st.players[0], st.players[1]
    bm = InPlay.of(repo.get("OP08-104"), sickness=False)  # ポワール BM cost1
    bm.rested = True  # レスト状態 → untap 対象
    me.characters = [bm]
    me.life = [repo.get("OP01-016"), repo.get("OP01-016")]

    hand_before = len(me.hand)
    life_before = len(me.life)
    do, _ = _do(overlay, "ST20-004", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST20-004"), sickness=True))
    _drain(st, [0])

    assert len(me.hand) == hand_before + 1, "ライフ1枚が手札に加わるべき (コスト)"
    assert len(me.life) == life_before - 1, "コストでライフが1枚減るべき"
    assert bm.rested is False, "BM cost3以下キャラがアクティブになっていない"


def test_st20_004_trigger_rest_opp_ai():
    """【トリガー】相手のコスト3以下キャラ1枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP03-089"), sickness=False)  # 印刷コスト2 ≤ 3
    victim.rested = False
    opp.characters = [victim]

    do, _ = _do(overlay, "ST20-004", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.rested is True, "トリガーで相手コスト3以下キャラがレストになっていない"


# --------------------------------------------------------------------------- #
#  ST20-005 シャーロット・リンリン (CHARACTER 黄 cost6):
#    【登場時】自分の手札1枚を捨てることができる：相手は以下から1つを選ぶ。
#    ・相手は自身の手札2枚を捨てる。 ・相手のライフの上から1枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_st20_005_on_play_opp_choice_ai():
    """【登場時】相手が『手札2枚捨て』か『ライフ1枚トラッシュ』を選ぶ (相手=AI 自動解決)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098_p3", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("OP01-016")] * 3
    opp.life = [repo.get("OP01-016")] * 3

    hand_before = len(opp.hand)
    life_before = len(opp.life)
    do, _ = _do(overlay, "ST20-005", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST20-005"), sickness=True))
    _drain(st, [0])

    # 相手が 2 択の 片方 を選ぶ: 手札 -2 のみ or ライフ -1 のみ の どちらか。
    hand_branch = (len(opp.hand) == hand_before - 2 and len(opp.life) == life_before)
    life_branch = (len(opp.life) == life_before - 1 and len(opp.hand) == hand_before)
    assert hand_branch or life_branch, (
        f"choice_effect の どちらの分岐も成立していない: "
        f"hand {hand_before}->{len(opp.hand)} / life {life_before}->{len(opp.life)}"
    )
    assert len(opp.trash) >= 1, "選ばれた効果でトラッシュが増えていない"


# --------------------------------------------------------------------------- #
#  ST21-001 モンキー・D・ルフィ (LEADER 赤):
#    【ドン‼×1】【起動メイン】【ターン1回】自分のキャラ1枚にレストのドン!!2枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_st21_001_leader_activate_main_attach_don_ai():
    """【起動メイン】自キャラにレストドン2枚を付与 (AI 自動)。 ドン‼×1 ゲート成立時。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST21-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # 【ドン‼×1】 ゲート成立
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]
    me.don_rested = 2

    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST21-001"]
    assert len(opts) == 1, f"ST21-001 リーダーの起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert friend.attached_dons == 2, \
        f"自キャラへ レストドン2枚が付与されていない: {friend.attached_dons}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_st21_001_leader_activate_main_don_gate():
    """【ドン‼×1】ゲート: リーダーに付与ドンが無ければ起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST21-001", overlay)
    me = st.players[0]
    me.leader.attached_dons = 0  # ドン付与なし → ゲート不成立
    me.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST21-001"]
    assert len(opts) == 0, \
        "ドン‼×1 ゲート不成立でも起動メインが legal に出てはいけない"
