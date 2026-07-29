# -*- coding: utf-8 -*-
"""OP12 弾 (紫 サンジ / 黒 革命軍・コアラ 系) 効果 回帰テスト
バックフィル (自動生成 wave 122):
OP12-075 / OP12-077 / OP12-078 / OP12-079 / OP12-080 /
OP12-081 / OP12-084 / OP12-085 / OP12-086 / OP12-087 の 10 枚。

目的 (= test_backfill_auto_001〜121.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_attack,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の (do, entry) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _entry(overlay, cid, when, needle=None):
    """when 一致 (かつ needle が do 表現に含まれる) 最初の効果 entry を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") != when:
            continue
        if needle is None or any(needle in d for d in e.get("do", [])):
            return e
    raise AssertionError(f"{cid} に when={when} needle={needle} の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。
    confirm 系は承諾 ([1])、 候補選択系は先頭 ([0]) を選ぶ。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        kind = st.pending_choice.get("kind", "")
        if kind in ("optional_cost_confirm", "reveal_top_play_confirm",
                    "replace_ko_optional"):
            resolve_pending_choice(st, [1])
        else:
            cands = (st.pending_choice.get("candidates")
                     or st.pending_choice.get("cards")
                     or st.pending_choice.get("options") or [])
            resolve_pending_choice(st, [0] if len(cands) > 0 else [])
        g += 1


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"       # ルフィ (赤、 leader 条件が無い汎用)
_SANJI_LEADER = "OP12-041"  # サンジ (青/紫、 name=サンジ)
_KOALA_LEADER = "OP12-081"  # コアラ (黒/黄、 features 革命軍、 name=コアラ)
_EVENT = "EB04-008"         # 歪んだ未来 (EVENT、 手札/トラッシュ充填用)
_VICTIM = "OP01-016"        # ナミ (赤 cost1 pow2000 / CHARACTER name=ナミ)
_FILLER = "OP01-013"        # サンジ (赤 cost2 / CHARACTER name=サンジ)
_LOW = "OP01-002"           # トラファルガー・ロー (CHARACTER name=トラファルガー・ロー)
_GINNY = "EB04-045"         # ジニー (黒 cost1 CHARACTER features 革命軍)
_BIG8_A = "EB04-003"        # スモーカー＆たしぎ (cost8 CHARACTER)
_BIG8_B = "EB04-013"        # キャロット (cost8 CHARACTER)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op12_wave122_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-075", "OP12-077", "OP12-078", "OP12-079", "OP12-080",
           "OP12-081", "OP12-084", "OP12-085", "OP12-086", "OP12-087"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-075 ミス・オールサンデー (CHARACTER 紫 cost4 pow5000):
#    【登場時】相手のコスト3以下のキャラ1枚までを、KOする。
#      その後、相手はドン‼デッキからドン‼1枚を、アクティブで追加してもよい。
# --------------------------------------------------------------------------- #
def test_op12_075_on_play_ko_cost_le_3_ai():
    """【登場時】 AI: 相手のコスト3以下キャラを KO、 コスト4以上は対象外で残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    small = InPlay.of(repo.get(_VICTIM), sickness=False)   # cost1 (<=3)
    big = InPlay.of(repo.get("OP12-087"), sickness=False)  # cost6 (対象外)
    opp.characters = [small, big]
    src = InPlay.of(repo.get("OP12-075"), sickness=True)
    me.characters = [src]

    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert small not in opp.characters, "コスト3以下の相手キャラが KO されていない"
    assert big in opp.characters, "コスト4以上の相手キャラは KO 対象外で残るべき"


def test_op12_075_on_play_ko_human_pick():
    """人間 + コスト3以下の相手キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP12-075", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP12-075"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP12-077 “お前の影響で出る音は全て消えるの術”だ (EVENT 紫 cost2):
#    【メイン】自分の「トラファルガー・ロー」1枚まで +2000、 その後 選んだカードが
#      アタックする場合 相手は【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_op12_077_main_pump_low_ai():
    """【メイン】 AI: 自分の「トラファルガー・ロー」に このターン中 +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    low = InPlay.of(repo.get(_LOW), sickness=False)  # name=トラファルガー・ロー
    me.characters = [low]

    do, _ = _do(overlay, "OP12-077", "main")
    power_before = low.power
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert low.power == power_before + 2000, \
        f"ロー に +2000 されていない: {low.power} (before {power_before})"


def test_op12_077_trigger_draw():
    """【トリガー】カード1枚を引く (deck -1 / hand +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []

    do, _ = _do(overlay, "OP12-077", "trigger")
    deck_before = len(me.deck)
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 1, "トリガーで 1 ドローされていない"
    assert len(me.deck) == deck_before - 1, "デッキが 1 枚減っていない"


# --------------------------------------------------------------------------- #
#  OP12-078 串焼き (EVENT 紫 cost3):
#    【メイン】自分の場のドンが相手の場のドン枚数以下なら カード1枚を引く。
#      その後、相手のキャラ1枚まで このターン中 パワー-3000。
# --------------------------------------------------------------------------- #
def test_op12_078_main_draw_and_debuff_when_don_le():
    """【メイン】 自ドン<=相手ドン → 1ドロー + 相手キャラ -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    opp.don_active = 3           # 自ドン(2) <= 相手ドン(3) = 条件成立
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # pow2000
    opp.characters = [victim]

    do, entry = _do(overlay, "OP12-078", "main")
    assert entry.get("if", {}).get("don_diff_le") == 0, \
        "overlay のメイン条件 don_diff_le=0 が無い"
    power_before = victim.power
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(me.hand) == 1, f"メインで 1 ドローされていない: {len(me.hand)}"
    assert victim.power == power_before - 3000, \
        f"相手キャラに -3000 されていない: {victim.power} (before {power_before})"


def test_op12_078_main_condition_false_when_don_more():
    """負例: 自ドン > 相手ドン なら don_diff_le:0 条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 4
    opp.don_active = 0           # 自ドン(4) > 相手ドン(0) = 条件不成立

    from engine.effects import eval_all_conditions
    _, entry = _do(overlay, "OP12-078", "main")
    assert eval_all_conditions(entry, st, me, None) is False, \
        "自ドンが相手より多いのに条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP12-079 ルフィは“海賊王”になる男だ!!! (EVENT 紫 cost1):
#    【メイン】リーダーが「サンジ」なら デッキ上3枚を見て1枚まで手札、 残りデッキ下。
# --------------------------------------------------------------------------- #
def test_op12_079_main_search_when_sanji_ai():
    """【メイン】 サンジ leader → デッキ上3枚から1枚を手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_EVENT), repo.get(_FILLER), repo.get(_VICTIM)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    do, entry = _do(overlay, "OP12-079", "main")
    assert entry.get("if", {}).get("leader_name") == "サンジ", \
        "overlay のメイン条件 leader_name=サンジ が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(me.hand) == 1, \
        f"デッキ上3枚から手札に1枚加わっていない: {[c.card_id for c in me.hand]}"


def test_op12_079_main_search_human_modal():
    """人間 + サンジ leader → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_EVENT), repo.get(_FILLER), repo.get(_VICTIM)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    do, _ = _do(overlay, "OP12-079", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + サンジで search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭を手札に
    _drain(st)
    assert len(me.hand) == 1, "人間が選んだカードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-080 バラティエ (STAGE 紫 cost1):
#    【起動メイン】このステージをデッキ下に置ける：リーダーが「サンジ」なら
#      デッキ上3枚を見て イベント1枚まで公開手札、 残りデッキ下。
# --------------------------------------------------------------------------- #
def test_op12_080_activate_main_return_stage_and_search_event_ai():
    """起動メイン: ステージをデッキ下 (コスト) → デッキ上3枚のイベントを手札 (AI)。"""
    from engine.effects import list_activate_main_effects, fire_activate_main
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP12-080"), sickness=False)
    me.stages = [stage]
    me.deck = [repo.get(_EVENT), repo.get(_FILLER), repo.get(_FILLER)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-080"]
    assert len(opts) == 1, \
        f"OP12-080 (ステージ) の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert any(c.card_id == _EVENT for c in me.hand), \
        f"起動メインで イベントが手札に加わっていない: {[c.card_id for c in me.hand]}"
    assert stage not in me.stages, "コストでステージがデッキ下に置かれ場から消えるべき"


def test_op12_080_activate_main_human_optional_cost():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で イベント手札。"""
    from engine.effects import list_activate_main_effects, fire_activate_main
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP12-080"), sickness=False)
    me.stages = [stage]
    me.deck = [repo.get(_EVENT), repo.get(_FILLER), repo.get(_FILLER)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-080"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st)
    assert any(c.card_id == _EVENT for c in me.hand), \
        "人間承諾後 イベントが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-081 コアラ (LEADER 黒/黄 pow5000):
#    このリーダーが相手リーダーにアタックした時、自コスト8以上のキャラが2枚以上で1ドロー。
#    【ターン1回】相手が元々コスト8以上のキャラを登場させた時、
#      相手は自身のライフ上1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op12_081_on_attack_draw_when_two_cost8_ai():
    """【アタック時】 自コスト8以上キャラ2枚 → 1ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_BIG8_A), sickness=False),
                     InPlay.of(repo.get(_BIG8_B), sickness=False)]
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []

    trigger_on_attack(st, me, opp, me.leader, overlay)
    _drain(st)

    assert len(me.hand) == 1, \
        f"コスト8以上2枚でアタック時1ドローされていない: {len(me.hand)}"


def test_op12_081_on_attack_no_draw_when_one_cost8():
    """負例: 自コスト8以上キャラが1枚のみ → ドローしない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_BIG8_A), sickness=False)]  # 1枚のみ
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []

    trigger_on_attack(st, me, opp, me.leader, overlay)
    _drain(st)

    assert len(me.hand) == 0, \
        "コスト8以上が1枚しかないのにドローが起きてはいけない"


def test_op12_081_on_opp_chara_played_mill_life_to_hand():
    """【相手が元々コスト8以上のキャラを登場させた時】相手は自身のライフ上1枚を手札に。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)  # P0 leader = コアラ
    me, opp = st.players[0], st.players[1]      # opp(P1) が cost8 を登場
    opp.life = [repo.get(_FILLER)] * 3
    opp.hand = []
    big = InPlay.of(repo.get(_BIG8_A), sickness=True)  # cost8
    opp.characters = [big]

    life_before = len(opp.life)
    hand_before = len(opp.hand)
    # opp が登場させた → me(コアラ)側の on_opp_chara_played が発火
    trigger_on_play(st, opp, me, big, overlay)
    _drain(st)

    assert len(opp.hand) == hand_before + 1, \
        f"相手がコスト8登場で 相手のライフが手札に加わっていない: {len(opp.hand)}"
    assert len(opp.life) == life_before - 1, "相手のライフが1枚減るべき"


# --------------------------------------------------------------------------- #
#  OP12-084 エンポリオ・イワンコフ (CHARACTER 黒 cost3 pow4000, features 革命軍):
#    【ブロッカー】【登場時】リーダーが特徴《革命軍》を持つなら デッキ上3枚をトラッシュ。
# --------------------------------------------------------------------------- #
def test_op12_084_on_play_mill_top3_when_revolutionary_ai():
    """【登場時】 革命軍 leader → デッキ上3枚をトラッシュ (deck -3 / trash +3)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)  # コアラ = 革命軍
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []
    src = InPlay.of(repo.get("OP12-084"), sickness=True)
    me.characters = [src]

    do, entry = _do(overlay, "OP12-084", "on_play")
    assert entry.get("if", {}).get("leader_feature") == "革命軍", \
        "overlay の条件 leader_feature=革命軍 が無い"
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert len(me.trash) == 3, f"デッキ上3枚がトラッシュされていない: {len(me.trash)}"
    assert len(me.deck) == deck_before - 3, "デッキが3枚減るべき"


def test_op12_084_on_play_no_mill_when_not_revolutionary():
    """負例: 非革命軍 leader なら 登場時のトラッシュは発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ルフィ (革命軍でない)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []
    src = InPlay.of(repo.get("OP12-084"), sickness=True)
    me.characters = [src]

    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert len(me.trash) == 0, "非革命軍 leader でトラッシュが発火してはいけない"


# --------------------------------------------------------------------------- #
#  OP12-085 カラス (CHARACTER 黒 cost5 pow6000):
#    静的: リーダーが特徴《革命軍》を持つなら このキャラのコスト+3。
#    【アタック時】革命軍 leader かつ 相手手札5枚以上で 相手は手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op12_085_on_attack_discard_opp_hand_ai():
    """【アタック時】 革命軍 leader + 相手手札5枚 → 相手は手札1枚を捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)  # 革命軍 leader
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get("OP12-085"), sickness=False)
    me.characters = [atk]
    opp.hand = [repo.get(_FILLER)] * 5  # 5枚 = 条件成立

    hand_before = len(opp.hand)
    trigger_on_attack(st, me, opp, atk, overlay)
    _drain(st)

    assert len(opp.hand) == hand_before - 1, \
        f"アタック時に相手が手札1枚を捨てていない: {len(opp.hand)}"


def test_op12_085_static_cost_plus3_when_revolutionary():
    """静的: 革命軍 leader → コスト 5→8。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    karasu_def = repo.get("OP12-085")
    karasu = InPlay.of(karasu_def, sickness=False)
    me.characters = [karasu]

    evaluate_static_effects(st, overlay)
    assert karasu.base_cost == karasu_def.cost + 3, \
        f"革命軍 leader で cost+3 されていない: {karasu.base_cost} (base {karasu_def.cost})"


# --------------------------------------------------------------------------- #
#  OP12-086 コアラ (CHARACTER 黒 cost1 pow2000, features 革命軍):
#    【登場時】革命軍 leader なら デッキ上3枚を見て「コアラ」以外の革命軍か
#      「ニコ・ロビン」1枚まで公開手札、 残りトラッシュ。
# --------------------------------------------------------------------------- #
def test_op12_086_on_play_search_revolutionary_ai():
    """【登場時】 革命軍 leader → デッキ上3枚から 革命軍カード (ジニー) を手札 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_GINNY), repo.get(_FILLER), repo.get(_VICTIM)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []
    src = InPlay.of(repo.get("OP12-086"), sickness=True)
    me.characters = [src]

    do, entry = _do(overlay, "OP12-086", "on_play")
    assert entry.get("if", {}).get("leader_feature") == "革命軍", \
        "overlay の条件 leader_feature=革命軍 が無い"
    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert any(c.card_id == _GINNY for c in me.hand), \
        f"登場時に革命軍カード (ジニー) が手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op12_086_on_play_search_human_modal():
    """人間 + 革命軍 leader → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_GINNY), repo.get(_FILLER), repo.get(_VICTIM)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []
    src = InPlay.of(repo.get("OP12-086"), sickness=True)
    me.characters = [src]

    trigger_on_play(st, me, opp, src, overlay)

    assert st.pending_choice is not None, "人間 + 革命軍で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _GINNY for c in me.hand), \
        "人間が選んだ革命軍カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-087 ニコ・ロビン (CHARACTER 黒 cost6 pow7000):
#    静的: リーダーが「コアラ」か「モンキー・Ｄ・ルフィ」なら【ブロッカー】+コスト+3。
#    【登場時】自分の手札1枚を捨てられる：相手手札5枚以上で 相手は手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op12_087_on_play_discard_then_opp_discard2_ai():
    """【登場時】 AI: 手札1枚を捨て → 相手手札5枚以上なら 相手は手札2枚を捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-087"), sickness=True)
    me.characters = [src]
    me.hand = [repo.get(_EVENT)]           # 捨てるコスト用
    opp.hand = [repo.get(_FILLER)] * 5     # 5枚 = 条件成立

    hand_before = len(me.hand)
    opp_hand_before = len(opp.hand)
    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert len(me.hand) == hand_before - 1, "コストで自分の手札が1枚捨てられるべき"
    assert len(opp.hand) == opp_hand_before - 2, \
        f"相手が手札2枚を捨てていない: {len(opp.hand)} (before {opp_hand_before})"


def test_op12_087_on_play_human_optional_cost():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で 相手手札-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-087"), sickness=True)
    me.characters = [src]
    me.hand = [repo.get(_EVENT)]
    opp.hand = [repo.get(_FILLER)] * 5

    opp_hand_before = len(opp.hand)
    trigger_on_play(st, me, opp, src, overlay)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st)
    assert len(opp.hand) == opp_hand_before - 2, \
        "人間承諾後 相手が手札2枚を捨てていない"


def test_op12_087_static_blocker_and_cost_when_koala_leader():
    """静的: コアラ leader → 【ブロッカー】獲得 + コスト 6→9。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KOALA_LEADER, overlay)  # コアラ leader
    me, opp = st.players[0], st.players[1]
    robin_def = repo.get("OP12-087")
    robin = InPlay.of(robin_def, sickness=False)
    me.characters = [robin]

    evaluate_static_effects(st, overlay)
    assert robin.is_blocker_now is True, \
        f"コアラ leader で【ブロッカー】が付与されていない: {robin.static_granted_keywords}"
    assert robin.base_cost == robin_def.cost + 3, \
        f"コアラ leader で cost+3 されていない: {robin.base_cost} (base {robin_def.cost})"
