# -*- coding: utf-8 -*-
"""OP05/OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 063):
OP05-112 / OP05-114 / OP05-115 / OP05-116 / OP05-118 / OP05-119 /
OP06-002 / OP06-003 / OP06-004 / OP06-006 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_062.py と同一方針):
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

# よく使うテスト用カード (テキストの前提固定)
_LEADER = "OP01-001"     # ロロノア・ゾロ (赤、 単色)
_NAMI = "OP01-016"       # ナミ 赤 cost1 power2000
_RED_C2 = "ST01-004"     # サンジ 赤 cost2 power4000 (汎用フィラー)
_SKY_C1 = "OP05-109"     # パガヤ 黄 cost1 空島 (on_play 無し = 登場時に nested 発火しない)
_SKY_C1B = "OP06-099"    # アイサ 黄 cost1 空島 (人間 pick の 2 件目候補)
_KAKUMEI = "OP05-006"    # コアラ 赤 cost2 power3000 革命軍 (OP06-003 サーチ対象)
_LILY = "OP06-015"       # リリーカーネーション 赤 cost4 (OP06-004 登場元)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_RED_C2)] * 30
    p1.deck = [repo.get(_RED_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave63_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-112", "OP05-114", "OP05-115", "OP05-116", "OP05-118",
           "OP05-119", "OP06-002", "OP06-003", "OP06-004", "OP06-006"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-112 マッキンリー隊長 (CHARACTER 黄 cost3 power3000 空島 / ブロッカー):
#    【KO時】自分の手札からコスト1の特徴《空島》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op05_112_on_ko_play_sky_cost1_ai():
    """KO時 (AI): 手札のコスト1・空島キャラを登場させる (chars +1 / hand -1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_SKY_C1)]  # パガヤ (cost1 空島)
    hand_before = len(me.hand)
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP05-112", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-112"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == _SKY_C1 for c in me.characters), \
        "KO時に手札のコスト1・空島キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"
    assert len(me.hand) == hand_before - 1, "登場元の手札が1枚減っていない"


def test_op05_112_on_ko_play_human_pick():
    """KO時 (人間): 候補が複数 → play_from_hand_pick modal が立ち、 選んだ1枚を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_SKY_C1), repo.get(_SKY_C1B)]  # cost1 空島 2 枚

    execute_effect(_do(overlay, "OP05-112", "on_ko")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-112"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"登場候補が 2 件でない: {len(cands)}"

    # パガヤ (= on_play 無し) を選択して nested 発火を避ける
    pagaya_idx = next(i for i, c in enumerate(cands)
                      if c.get("card_id") == _SKY_C1)
    resolve_pending_choice(st, [pagaya_idx])
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])
    assert any(c.card.card_id == _SKY_C1 for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP05-114 神の裁き (EVENT 黄 cost1 空島):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#      その後、相手のライフが2枚以下の場合、そのカードを、このバトル中、パワー+2000。
#    【トリガー】相手のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def _fire_op05_114_counter(st, me, opp):
    for prim in _do(overlay_of := _overlay(), "OP05-114", "counter"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
    assert overlay_of is not None


def test_op05_114_counter_power_pump_ai():
    """カウンター (AI): 相手ライフ 3 枚 (= 後文の条件外) なら +2000 だけ。"""
    repo = _repo()
    st = _state(repo, _LEADER, _overlay())
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 3  # 後文 (相手ライフ2枚以下) を満たさない
    power_before = me.leader.power

    _fire_op05_114_counter(st, me, opp)

    assert me.leader.power == power_before + 2000, \
        f"カウンターで +2000 が乗っていない: {me.leader.power} (before {power_before})"


def test_op05_114_counter_bonus_when_opp_life_le2():
    """カウンター後文: 相手のライフが 2 枚以下なら 「そのカード」 に さらに +2000 (合計 +4000)。

    2026-08-02: overlay に後文が実装されておらず +2000 しか乗っていなかった (実装漏れ) の回帰テスト。
    """
    repo = _repo()
    st = _state(repo, _LEADER, _overlay())
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 2  # 後文の条件を満たす
    power_before = me.leader.power

    _fire_op05_114_counter(st, me, opp)

    assert me.leader.power == power_before + 4000, \
        f"相手ライフ2枚以下で +4000 になっていない: {me.leader.power} (before {power_before})"


def test_op05_114_counter_power_pump_human_pick():
    """カウンター (人間): 自リーダー+キャラ 複数 → target_pick modal で選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_RED_C2), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP05-114", "counter")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    f_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    f_before = friend.power
    resolve_pending_choice(st, [f_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == f_before + 2000, \
        "人間が選んだキャラに +2000 が乗っていない"


def test_op05_114_trigger_ko_opp_ai():
    """トリガー (AI): 相手のキャラ1枚をKOする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-114", "trigger"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim not in opp.characters, "トリガーで相手キャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP05-115 2億V雷神 (EVENT 黄 cost2 空島):
#    【メイン】自分のリーダーかキャラ1枚までを、このターン中、パワー+3000。
#      その後、自分のライフが1枚以下の場合、相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op05_115_main_pump_and_rest_when_life_le1_ai():
    """メイン (AI): 自リーダー +3000 / 自ライフ1以下 → 相手コスト4以下キャラをレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 1  # ライフ1枚以下 = 条件成立
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 <= 4
    opp.characters = [victim]
    power_before = me.leader.power

    for prim in _do(overlay, "OP05-115", "main"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert me.leader.power == power_before + 3000, \
        f"メインで +3000 が乗っていない: {me.leader.power} (before {power_before})"
    assert victim.rested is True, "ライフ1以下なのに相手キャラがレストされていない"


def test_op05_115_no_rest_when_life_ge2():
    """自ライフ2枚以上では レスト条件が不成立 (相手キャラは アクティブのまま)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 3  # ライフ3枚 = 不成立
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-115", "main"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim.rested is False, "ライフ2枚以上なのに相手キャラがレストされた"


# --------------------------------------------------------------------------- #
#  OP05-116 3000万V雷鳥 (EVENT 黄 cost2 空島):
#    【メイン】相手のライフの枚数以下のコストを持つ相手のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op05_116_main_ko_cost_le_opp_life_ai():
    """メイン (AI): 相手ライフ枚数以下コストの相手キャラをKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 3       # ライフ3枚 → cost3以下がKO対象
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-116", "main"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim not in opp.characters, "コスト <= 相手ライフ枚数のキャラがKOされていない"


def test_op05_116_main_no_ko_when_cost_gt_life():
    """相手ライフ1枚 vs cost2キャラ → コスト超過でKO対象にならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_NAMI)] * 1        # ライフ1枚
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 > 1
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-116", "main"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim in opp.characters, "コストが相手ライフ枚数を超えるのにKOされた"


def test_op05_116_main_ko_human_pick():
    """メイン (人間): KO候補が複数 → target_pick modal で選択して解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 3
    a = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-116", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数KO候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"KO候補が 2 件でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert a not in opp.characters, "人間が選んだキャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP05-118 カイドウ (CHARACTER 青 cost10 power12000 四皇/百獣海賊団):
#    【登場時】相手のライフが3枚以下の場合、カード4枚を引く。
# --------------------------------------------------------------------------- #
def test_op05_118_on_play_draw4_when_opp_life_le3_ai():
    """登場時 (AI): 相手ライフ3以下なら 4枚ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 3   # 3枚以下 = 条件成立
    me.hand = []
    me.deck = [repo.get(_RED_C2)] * 10

    eff = _eff(overlay, "OP05-118", "on_play")
    assert eval_condition(eff.get("if", {}), st, me), \
        "相手ライフ3枚で条件成立のはず"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-118"), sickness=True))

    assert len(me.hand) == 4, f"4枚ドローされていない: hand={len(me.hand)}"


def test_op05_118_on_play_no_draw_when_opp_life_gt3():
    """相手ライフ4枚では 登場時条件が不成立 (ドローしない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    st.players[1].life = [repo.get(_RED_C2)] * 4  # 4枚 = 不成立

    eff = _eff(overlay, "OP05-118", "on_play")
    assert not eval_condition(eff.get("if", {}), st, me), \
        "相手ライフ4枚なのに条件成立している"


# --------------------------------------------------------------------------- #
#  OP05-119 モンキー・D・ルフィ (CHARACTER 紫 cost10 power12000 四皇/麦わらの一味):
#    【登場時】ドン!!-10：このキャラ以外の自分のキャラすべてを好きな順番でデッキの下に置く。
#      その後、このターンの後に自分のターンを追加で得る。
#    【起動メイン】【ターン1回】➀：ドン!!デッキからドン!!1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op05_119_on_play_bounce_others_and_extra_turn_ai():
    """登場時 (AI): このキャラ以外の自キャラをデッキ下へ + 追加ターン獲得。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_RED_C2)] * 5
    friend_a = InPlay.of(repo.get(_RED_C2), sickness=False)
    friend_b = InPlay.of(repo.get(_NAMI), sickness=False)
    luffy = InPlay.of(repo.get("OP05-119"), sickness=False)
    me.characters = [friend_a, friend_b, luffy]
    deck_before = len(me.deck)
    st.extra_turn_pending = False

    for prim in _do(overlay, "OP05-119", "on_play"):
        execute_effect(prim, st, me, opp, luffy)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert me.characters == [luffy], \
        f"このキャラ以外がデッキ下に置かれていない: {[c.card.card_id for c in me.characters]}"
    assert len(me.deck) == deck_before + 2, "他の自キャラ2体がデッキ下に戻っていない"
    assert st.extra_turn_pending is True, "追加ターンが得られていない"


def test_op05_119_activate_main_add_don():
    """起動メイン: ドンデッキから1枚をアクティブ追加 (total_don +1)。【ターン1回】。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP05-119"), sickness=False)
    me.characters = [luffy]
    me.don_active = 2
    me.don_remaining_in_deck = 5
    total_before = me.total_don

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP05-119"]
    assert len(opts) == 1, f"OP05-119 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.total_don == total_before + 1, \
        f"ドンが1枚増えていない: total_don={me.total_don} (before {total_before})"

    # 【ターン1回】: 再発動不可
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP05-119"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP06-002 イナズマ (CHARACTER 赤 cost4 power5000 革命軍):
#    このキャラのパワーが7000以上の場合、このキャラは【バニッシュ】を得る。(静的)
# --------------------------------------------------------------------------- #
def test_op06_002_static_vanish_when_power_ge7000():
    """静的: パワー7000以上で【バニッシュ】付与 / 5000では付与されない。"""
    repo = _repo()
    overlay = _overlay()

    st = _state(repo, _LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    inaz = InPlay.of(repo.get("OP06-002"), sickness=False)  # base 5000
    inaz.attached_dons = 2  # +2000 → 7000
    me.characters = [inaz]
    evaluate_static_effects(st, overlay)
    assert inaz.power == 7000, f"ドン2枚で power 7000 のはず: {inaz.power}"
    assert "バニッシュ" in inaz.static_granted_keywords, \
        "パワー7000でバニッシュが付与されていない"

    st2 = _state(repo, _LEADER, overlay)
    me2, _ = st2.players[0], st2.players[1]
    inaz2 = InPlay.of(repo.get("OP06-002"), sickness=False)  # ドン無し = 5000
    me2.characters = [inaz2]
    evaluate_static_effects(st2, overlay)
    assert inaz2.power == 5000, f"ドン無しで power 5000 のはず: {inaz2.power}"
    assert "バニッシュ" not in inaz2.static_granted_keywords, \
        "パワー7000未満なのにバニッシュが付与された"


# --------------------------------------------------------------------------- #
#  OP06-003 エンポリオ・イワンコフ (CHARACTER 赤 cost5 power6000 革命軍):
#    【登場時】自分のデッキの上から3枚を見て、パワー5000以下の特徴《革命軍》を持つ
#      キャラカード1枚までを、登場させる。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_003_on_play_search_and_play_kakumei_ai():
    """登場時 (AI): デッキ上3枚から パワー5000以下の革命軍キャラを登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_KAKUMEI)] + [repo.get(_RED_C2)] * 10  # コアラ(革命軍 pow3000) を上に

    for prim in _do(overlay, "OP06-003", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-003"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == _KAKUMEI for c in me.characters), \
        "デッキ上の革命軍キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-004 オマツリ男爵 (CHARACTER 赤 cost2 power3000 FILM/オマツリ島):
#    【登場時】自分の手札から「リリーカーネーション」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op06_004_on_play_summon_lily_ai():
    """登場時 (AI): 手札の「リリーカーネーション」を登場させる (hand -1 / chars +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_LILY)]
    hand_before = len(me.hand)
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP06-004", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-004"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == _LILY for c in me.characters), \
        "手札の「リリーカーネーション」が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"
    assert len(me.hand) == hand_before - 1, "登場元の手札が1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP06-006 サガ (CHARACTER 赤 cost4 power5000 FILM/アスカ島):
#    【ドン!!×1】【アタック時】このキャラは、次の自分のターン開始時まで、パワー+1000。
#      その後、このターン終了時、自分の特徴《FILM》を持つキャラ1枚をトラッシュに置く。
#  (schedule 側の turn-end KO は遅延効果のため、 ここでは即時の power_pump を検証)
# --------------------------------------------------------------------------- #
def test_op06_006_on_attack_self_pump_with_don():
    """アタック時 (ドン1ゲート): 自身は 次の自分ターン開始時まで パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    saga = InPlay.of(repo.get("OP06-006"), sickness=False)  # power 5000
    saga.attached_dons = 1  # ドン×1 ゲート成立
    me.characters = [saga]

    eff = _eff(overlay, "OP06-006", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    power_before = saga.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, saga)

    assert saga.power == power_before + 1000, \
        f"アタック時 自己 +1000 が反映されていない: {saga.power} (before {power_before})"
