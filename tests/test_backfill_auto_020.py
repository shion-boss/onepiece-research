# -*- coding: utf-8 -*-
"""OP01 弾 効果 回帰テスト バックフィル (自動生成 wave 020):
OP01-009 / OP01-011 / OP01-014 / OP01-015 / OP01-019 / OP01-020 /
OP01-021 / OP01-022 / OP01-030 / OP01-031 の 10 枚。

目的 (= test_backfill_auto_001〜019.py と同一方針):
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
from engine.deck import CardRepository
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキ filler は OP01-020 (ワノ国、 麦わらの一味 でない) = search/draw フィルタ誤爆防止。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-020")] * 30
    p1.deck = [repo.get("OP01-020")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
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
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave20_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP01-009", "OP01-011", "OP01-014", "OP01-015", "OP01-019",
           "OP01-020", "OP01-021", "OP01-022", "OP01-030", "OP01-031"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP01-009 キャロット (CHARACTER 赤 cost2 power3000 ミンク族):
#    【トリガー】このカードを登場させる (play_self)
# --------------------------------------------------------------------------- #
def test_op01_009_carrot_trigger_play_self_ai():
    """トリガー: このカード (キャロット) を手札から登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-009")]
    st.current_source_card_id = "OP01-009"
    chars_before = len(me.characters)

    do, _ = _do(overlay, "OP01-009", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.characters) == chars_before + 1, "トリガーでキャロットが登場していない"
    assert any(c.card.card_id == "OP01-009" for c in me.characters), \
        "登場したキャラがキャロット (OP01-009) でない"
    assert not any(c.card_id == "OP01-009" for c in me.hand), \
        "登場後も手札にキャロットが残っている"


# --------------------------------------------------------------------------- #
#  OP01-011 ゴードン (CHARACTER 赤 cost2 power3000 FILM):
#    【登場時】自分の手札1枚をデッキの下に置くことができる：カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op01_011_gordon_on_play_deck_bottom_then_draw_ai():
    """登場時: 手札1枚をデッキ下に置き → 1ドロー (AI)。 net 手札枚数不変・内容入替。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-009")]                 # デッキ下に送る 1 枚
    me.deck = [repo.get("OP01-016")] + [repo.get("OP01-020")] * 10  # top = ナミ
    hand_before = len(me.hand)

    do, _ = _do(overlay, "OP01-011", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-011"), sickness=True))

    assert len(me.hand) == hand_before, "手札 net (デッキ下-1 + ドロー+1) が不変でない"
    assert me.hand[0].card_id == "OP01-016", "ドローでデッキ上 (ナミ) が手札に来ていない"
    assert me.deck[-1].card_id == "OP01-009", "手札 1 枚がデッキの下に置かれていない"


def test_op01_011_gordon_on_play_human_deck_pick():
    """人間 + 手札複数 → self_hand_to_deck_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-009"), repo.get("OP01-016")]  # 2 枚 → 選択が生じる
    me.deck = [repo.get("OP01-020")] * 10

    do, _ = _do(overlay, "OP01-011", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-011"), sickness=True))

    # ⚠ 公式 「自分の手札1枚をデッキの下に置くことができる：カード1枚を引く。」 は
    #   コロン前が **発動コスト** (cardqa_st_06)。 人間はまず 払う/見送る を選ぶ。
    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"任意コスト確認 modal が先に立たない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])   # 払う

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_to_deck_pick", \
        f"kind が self_hand_to_deck_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2枚でない: {len(cands)}"
    resolve_pending_choice(st, [0])  # 先頭 (キャロット) をデッキ下へ
    assert me.deck[-1].card_id == "OP01-009", "人間が選んだ手札がデッキ下に置かれていない"


def test_op01_011_gordon_on_play_declined_costs_nothing():
    """⚠ 対照: 人間が任意コストを見送ったら 手札もデッキも動かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-009"), repo.get("OP01-016")]
    me.deck = [repo.get("OP01-020")] * 10

    do, _ = _do(overlay, "OP01-011", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-011"), sickness=True))
    assert st.pending_choice.get("kind") == "optional_cost_confirm"
    resolve_pending_choice(st, [0])   # 見送る

    assert st.pending_choice is None, "見送り後に modal が残る"
    assert len(me.hand) == 2, "見送ったのに手札が動いている"
    assert len(me.deck) == 10, "見送ったのにデッキが動いている"


# --------------------------------------------------------------------------- #
#  OP01-014 ジンベエ (CHARACTER 赤 cost4 power5000):
#    【ブロッカー】【ドン‼×1】【ブロック時】自分の手札からコスト2以下の
#                  赤のキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op01_014_jinbe_on_block_play_red_cost2_ai():
    """ブロック時: 手札の赤コスト2以下キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("OP01-014"), sickness=False)
    me.characters = [jinbe]
    me.hand = [repo.get("OP01-016")]  # ナミ 赤 cost1 → 登場対象
    chars_before = len(me.characters)

    do, _ = _do(overlay, "OP01-014", "on_block")
    for prim in do:
        execute_effect(prim, st, me, opp, jinbe)

    assert any(c.card.card_id == "OP01-016" for c in me.characters), \
        "手札の赤コスト2以下キャラ (ナミ) が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_op01_014_jinbe_on_block_human_play_pick():
    """人間 + 手札に赤コスト2以下キャラ複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("OP01-014"), sickness=False)
    me.characters = [jinbe]
    me.hand = [repo.get("OP01-016"), repo.get("OP01-024")]  # 赤 cost1 / 赤 cost2

    do, _ = _do(overlay, "OP01-014", "on_block")
    execute_effect(do[0], st, me, opp, jinbe)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id in ("OP01-016", "OP01-024") for c in me.characters), \
        "人間が選んだ赤キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP01-015 トニートニー・チョッパー (CHARACTER 赤 cost3 power4000):
#    【ドン‼×1】【アタック時】自分の手札1枚を捨てることができる：自分のトラッシュの
#    「トニートニー・チョッパー」以外のコスト4以下の特徴《麦わらの一味》を持つ
#    キャラカード1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_op01_015_chopper_attack_optional_trash_to_hand_ai():
    """アタック時: 手札1枚捨て → トラッシュの麦わらキャラ (cost4以下) を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    chopper = InPlay.of(repo.get("OP01-015"), sickness=False)
    me.characters = [chopper]
    me.hand = [repo.get("OP01-020")]   # 捨てるコスト用 (ヒョウ五郎)
    me.trash = [repo.get("OP01-013")]  # サンジ 麦わらの一味 cost2 → 回収対象

    do, _ = _do(overlay, "OP01-015", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, chopper)

    assert any(c.card_id == "OP01-013" for c in me.hand), \
        "トラッシュの麦わらキャラ (サンジ) が手札に加わっていない"
    assert not any(c.card_id == "OP01-013" for c in me.trash), \
        "回収後もトラッシュにサンジが残っている"


def test_op01_015_chopper_attack_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で回収まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    chopper = InPlay.of(repo.get("OP01-015"), sickness=False)
    me.characters = [chopper]
    me.hand = [repo.get("OP01-020")]
    me.trash = [repo.get("OP01-013"), repo.get("OP01-016")]  # 麦わら 2 種

    do, _ = _do(overlay, "OP01-015", "on_attack")
    execute_effect(do[0], st, me, opp, chopper)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, pick=[0])
    assert any(c.card_id in ("OP01-013", "OP01-016") for c in me.hand), \
        "人間承諾後 麦わらキャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP01-019 バルトロメオ (CHARACTER 赤 cost2 power2000):
#    【ブロッカー】【ドン‼×2】【相手のターン中】このキャラはパワー+3000。
# --------------------------------------------------------------------------- #
def test_op01_019_barto_static_pump_opp_turn():
    """静的 (on_attached_don n=2、 相手ターン中): 自身 static_buff +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= me_idx=0 視点で opp_turn)
    barto = InPlay.of(repo.get("OP01-019"), sickness=False)
    barto.attached_dons = 2  # ドン2 ゲート成立
    me.characters = [barto]

    assert eval_condition({"opp_turn": True}, st, me) is True, \
        "テスト前提: 相手ターンでない"
    evaluate_static_effects(st, overlay)
    assert barto.static_buff == 3000, \
        f"相手ターン中 ドン2 で static_buff +3000 が乗っていない: {barto.static_buff}"


def test_op01_019_barto_static_no_pump_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    barto = InPlay.of(repo.get("OP01-019"), sickness=False)
    barto.attached_dons = 2
    me.characters = [barto]

    evaluate_static_effects(st, overlay)
    assert barto.static_buff == 0, \
        f"自分のターンで +3000 が乗ってはいけない: {barto.static_buff}"


# --------------------------------------------------------------------------- #
#  OP01-020 ヒョウ五郎 (CHARACTER 赤 cost2 power3000 ワノ国):
#    【起動メイン】このキャラをレストにできる：自分のリーダーかキャラ1枚までを、
#                  このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op01_020_hyogoro_activate_main_pump_ai():
    """起動メイン: 自レスト → 自リーダー/キャラ1枚に +2000 (AI、 高パワー=リーダー選好)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hyo = InPlay.of(repo.get("OP01-020"), sickness=False)
    me.characters = [hyo]
    leader_before = me.leader.power

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-020"]
    assert len(opts) == 1, f"OP01-020 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.power == leader_before + 2000, \
        f"起動メインの +2000 がリーダーに乗っていない: {me.leader.power}"
    assert hyo.rested is True, "起動メインコストで ヒョウ五郎 がレストされるべき"


def test_op01_020_hyogoro_activate_main_human_pick():
    """人間 + リーダー/キャラ 複数 → +2000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hyo = InPlay.of(repo.get("OP01-020"), sickness=False)
    me.characters = [hyo]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-020"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+ヒョウ五郎) が 2 件でない: {len(cands)}"
    hyo_idx = next(i for i, c in enumerate(cands) if c["iid"] == hyo.instance_id)
    hyo_before = hyo.power
    resolve_pending_choice(st, [hyo_idx])
    _drain(st, pick=[hyo_idx])
    assert hyo.power == hyo_before + 2000, "人間が選んだキャラに +2000 が乗っていない"


# --------------------------------------------------------------------------- #
#  OP01-021 フランキー (CHARACTER 赤 cost3 power4000):
#    【ドン‼×1】このキャラは、相手のアクティブのキャラにもアタックできる。
# --------------------------------------------------------------------------- #
def test_op01_021_franky_static_attack_active_chara():
    """静的 (on_attached_don n=1): 自身に「アクティブアタック可」キーワード付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("OP01-021"), sickness=False)
    franky.attached_dons = 1  # ドン1 ゲート成立
    me.characters = [franky]

    evaluate_static_effects(st, overlay)
    assert "アクティブアタック可" in franky.granted_keywords, \
        "ドン1 で「アクティブアタック可」 が付与されていない"


def test_op01_021_franky_no_grant_without_don():
    """ドンが付与されていなければ (n=1 未満) キーワードは付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("OP01-021"), sickness=False)
    franky.attached_dons = 0
    me.characters = [franky]

    evaluate_static_effects(st, overlay)
    assert "アクティブアタック可" not in franky.granted_keywords, \
        "ドン無しで「アクティブアタック可」 が付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP01-022 ブルック (CHARACTER 赤 cost4 power5000):
#    【ドン‼×1】【アタック時】相手のキャラ2枚までを、このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_op01_022_brook_attack_debuff_two_ai():
    """アタック時: 相手キャラ2枚まで -2000 (AI、 上限内なので全体に適用)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [a, b]
    a_before, b_before = a.power, b.power

    do, _ = _do(overlay, "OP01-022", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-022"), sickness=False))

    assert a.power == a_before - 2000, f"相手キャラA -2000 が乗っていない: {a.power}"
    assert b.power == b_before - 2000, f"相手キャラB -2000 が乗っていない: {b.power}"


def test_op01_022_brook_attack_debuff_human_pick():
    """人間 + 相手キャラ3体 (上限2超) → target_pick modal が立ち resolve で2体 -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    c = InPlay.of(repo.get("OP01-024"), sickness=False)
    opp.characters = [a, b, c]

    do, _ = _do(overlay, "OP01-022", "on_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-022"), sickness=False))

    assert st.pending_choice is not None, "人間 + 上限超過で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補が3体でない: {len(cands)}"
    a_before, b_before = a.power, b.power
    a_idx = next(i for i, x in enumerate(cands) if x["iid"] == a.instance_id)
    b_idx = next(i for i, x in enumerate(cands) if x["iid"] == b.instance_id)
    resolve_pending_choice(st, [a_idx, b_idx])
    _drain(st)
    assert a.power == a_before - 2000 and b.power == b_before - 2000, \
        "人間が選んだ2体に -2000 が乗っていない"
    assert c.power == repo.get("OP01-024").power, "選ばなかった3体目に -2000 が乗ってはいけない"


# --------------------------------------------------------------------------- #
#  OP01-030 2年後に‼!シャボンディ諸島で!!! (EVENT 赤 cost1):
#    【メイン】自分のデッキの上から5枚を見て、特徴《麦わらの一味》を持つキャラカード
#    1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op01_030_shabondy_main_search_strawhat_ai():
    """メイン: デッキ上5枚から麦わらキャラ1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 上5枚に麦わらキャラ (ナミ) を1枚仕込み、 残りはワノ国 filler
    me.deck = [repo.get("OP01-020"), repo.get("OP01-016"),
               repo.get("OP01-020"), repo.get("OP01-020"),
               repo.get("OP01-020")] + [repo.get("OP01-020")] * 15
    me.hand = []

    do, _ = _do(overlay, "OP01-030", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card_id == "OP01-016" for c in me.hand), \
        "デッキ上5枚から麦わらキャラ (ナミ) が手札に加わっていない"


def test_op01_030_shabondy_main_search_human_pick():
    """人間 + 上5枚に麦わらキャラ複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016"), repo.get("OP01-013"),
               repo.get("OP01-020"), repo.get("OP01-020"),
               repo.get("OP01-020")] + [repo.get("OP01-020")] * 15
    me.hand = []

    do, _ = _do(overlay, "OP01-030", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ナミ) を選択
    _drain(st)
    assert any(c.card_id in ("OP01-016", "OP01-013") for c in me.hand), \
        "人間が選んだ麦わらキャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP01-031 光月おでん (LEADER 緑 ワノ国/光月家):
#    【起動メイン】【ターン1回】自分の手札から特徴《ワノ国》を持つカード1枚を
#    捨てることができる：自分のドン‼2枚までをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op01_031_oden_activate_main_untap_don_ai():
    """起動メイン: ワノ国カード1枚捨て → レストドン2枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-031", overlay)  # リーダー = 光月おでん
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")]  # ヒョウ五郎 = ワノ国 (捨てコスト)
    me.don_active = 0
    me.don_rested = 3
    hand_before = len(me.hand)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-031"]
    assert len(opts) == 1, f"OP01-031 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.don_active == 2, f"レストドン2枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"レストドンが2枚減っていない: {me.don_rested}"
    assert len(me.hand) == hand_before - 1, "ワノ国カード1枚が捨てられていない"


def test_op01_031_oden_activate_main_human_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾でドンアクティブまで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-031", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020"), repo.get("OP01-020")]  # ワノ国 2 枚
    me.don_active = 0
    me.don_rested = 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-031"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, pick=[0])
    assert me.don_active == 2, f"人間承諾後 ドン2枚がアクティブになっていない: {me.don_active}"
