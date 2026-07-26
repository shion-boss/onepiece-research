# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 097):
OP09-074 / OP09-075 / OP09-076 / OP09-077 / OP09-078 /
OP09-079 / OP09-081 / OP09-083 / OP09-085 / OP09-086 の 10 枚
(紫 ドン返却/ドンデッキ加速・KO・バウンス系 + 黒 黒ひげ海賊団 妨害/トラッシュ参照系)。

目的 (= test_backfill_auto_001〜096.py と同一方針):
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
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_KUROHIGE = "OP09-081"  # マーシャル・D・ティーチ (leader、 四皇/黒ひげ海賊団)
_LEADER_MUGIWARA = "OP01-001"  # ロロノア・ゾロ (leader、 超新星/麦わらの一味)
_LEADER_KID = "ST02-001"       # ユースタス・キッド (leader、 超新星/キッド海賊団)
_FILLER = "ST01-004"           # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SMALL = "OP01-016"            # ナミ cost1 power2000 (バニラ)
_THRILLER_C1 = "OP01-077"      # ペローナ cost1 (スリラーバーク海賊団)
_THRILLER_C1B = "OP06-091"     # ビクトリア・シンドリー cost1 (スリラーバーク海賊団)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op09_wave097_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-074", "OP09-075", "OP09-076", "OP09-077", "OP09-078",
           "OP09-079", "OP09-081", "OP09-083", "OP09-085", "OP09-086"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-074 ベポ (CHARACTER): 【自分のターン中】【ターン1回】自分の場のドン!!が
#          ドン!!デッキに戻された時、 自リーダーかキャラ1枚までを このターン中 +1000。
# --------------------------------------------------------------------------- #
def test_op09_074_don_returned_pump_leader_ai():
    """ドン返却トリガー: AI は自リーダーに +1000 (turn_buff)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    eff = _eff(overlay, "OP09-074", "on_self_don_returned_to_deck")
    assert eff.get("if", {}).get("self_turn") is True, \
        "overlay の 自ターン条件 (self_turn) が無い"
    assert eff.get("cost", {}).get("once_per_turn") is True, \
        "overlay の 【ターン1回】制限が無い"
    power_before = me.leader.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-074"), sickness=False))
    assert me.leader.power == power_before + 1000, \
        f"自リーダーに +1000 が乗っていない: {me.leader.power} (before {power_before})"
    assert me.leader.turn_buff == 1000, \
        f"turn_buff が +1000 でない: {me.leader.turn_buff}"


def test_op09_074_don_returned_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → target_pick modal が立ち、 選んだキャラに +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    prim = _eff(overlay, "OP09-074", "on_self_don_returned_to_deck")["do"][0]
    execute_effect(prim, st, me, opp,
                   InPlay.of(repo.get("OP09-074"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    fi = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    before = friend.power
    resolve_pending_choice(st, [fi])
    _drain(st, [fi])
    assert friend.power == before + 1000, \
        "人間が選んだキャラに +1000 が乗っていない"


# --------------------------------------------------------------------------- #
#  OP09-075 ユースタス・キッド (CHARACTER): 【登場時】自分のライフの上から1枚を
#          手札に加えることができる：自リーダーが《キッド海賊団》なら、 ドン!!デッキから
#          ドン!!1枚までを アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op09_075_on_play_life_to_hand_add_don_ai():
    """【登場時】(任意ライフコスト): ライフ1枚を手札へ → キッド海賊団 leader で アクティブドン+1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KID, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = []
    me.don_active = 0
    me.don_remaining_in_deck = 5

    eff = _eff(overlay, "OP09-075", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "キッド海賊団", \
        "overlay の リーダー条件 (キッド海賊団) が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-075"), sickness=True))
    assert len(me.life) == 2, f"ライフ1枚が手札に加わっていない: life={len(me.life)}"
    assert len(me.hand) == 1, f"ライフ由来の手札が加わっていない: hand={len(me.hand)}"
    assert me.don_active == 1, \
        f"キッド海賊団 leader で アクティブドンが +1 されていない: {me.don_active}"


def test_op09_075_on_play_human_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal → 承諾で ライフ→手札 + ドン+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KID, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = []
    me.don_active = 0
    me.don_remaining_in_deck = 5

    prim = _eff(overlay, "OP09-075", "on_play")["do"][0]
    execute_effect(prim, st, me, opp,
                   InPlay.of(repo.get("OP09-075"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.life) == 2, "承諾後 ライフが手札に加わっていない"
    assert me.don_active == 1, "承諾後 アクティブドンが +1 されていない"


# --------------------------------------------------------------------------- #
#  OP09-076 ロロノア・ゾロ (CHARACTER): 【登場時】自分の場のドン!!を1枚以上
#          ドン!!デッキに戻すことができる：ドン!!デッキからドン!!1枚までを アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op09_076_on_play_don_recycle_ai():
    """【登場時】(任意ドン返却): レストドン1枚を返却 → アクティブドン1枚を追加 (= レスト→アクティブ変換、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 2
    me.don_remaining_in_deck = 0

    prim = _eff(overlay, "OP09-076", "on_play")["do"][0]
    execute_effect(prim, st, me, opp,
                   InPlay.of(repo.get("OP09-076"), sickness=True))
    # レストドン1枚がドンデッキに戻り (rested 2→1)、 アクティブで1枚追加 (active 0→1)。
    assert me.don_active == 1, \
        f"アクティブドンが1枚追加されていない: {me.don_active}"
    assert me.don_rested == 1, \
        f"レストドンが1枚返却されていない: {me.don_rested}"


def test_op09_076_on_play_human_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal → 承諾で ドン変換が成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 2
    me.don_remaining_in_deck = 0

    prim = _eff(overlay, "OP09-076", "on_play")["do"][0]
    execute_effect(prim, st, me, opp,
                   InPlay.of(repo.get("OP09-076"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert me.don_active == 1, "承諾後 アクティブドンが追加されていない"


# --------------------------------------------------------------------------- #
#  OP09-077 ゴムゴムの雷 (EVENT): 【メイン】ドン!!-2：相手のパワー6000以下のキャラ1枚
#          までを KO する。 【トリガー】ドン!!デッキからドン!!1枚までを アクティブで追加。
# --------------------------------------------------------------------------- #
def test_op09_077_main_ko_power_le_6000_ai():
    """【メイン】相手のパワー6000以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000 (≤6000)
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-077", "main")
    assert eff.get("cost", {}).get("pay_don") == 2, "overlay の ドン-2 コストが無い"
    trash_before = len(opp.trash)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "相手パワー6000以下キャラが KO されていない"
    assert len(opp.trash) == trash_before + 1, "KO キャラがトラッシュに置かれていない"


def test_op09_077_main_ko_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち、 選んだ1枚だけ KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    b = InPlay.of(repo.get(_SMALL), sickness=False)   # power 2000 (両方 ≤6000)
    opp.characters = [a, b]

    prim = _eff(overlay, "OP09-077", "main")["do"][0]
    execute_effect(prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかった相手キャラは残るべき"


def test_op09_077_trigger_add_don_ai():
    """【トリガー】ドン!!デッキからアクティブドン1枚を追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 5

    for prim in _eff(overlay, "OP09-077", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.don_active == 1, \
        f"トリガーで アクティブドンが +1 されていない: {me.don_active}"


# --------------------------------------------------------------------------- #
#  OP09-078 ゴムゴムの巨人 (EVENT): 【カウンター】ドン!!-2, 手札1枚を捨てられる：
#          自リーダーが《麦わらの一味》なら、 自リーダーかキャラ1枚まで このバトル中 +4000。
#          その後、 カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_078_counter_pump_draw_ai():
    """【カウンター】麦わらリーダー: 自リーダー +4000 (battle) + カード2枚ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.hand = [repo.get(_FILLER)]  # 捨てコスト用 (overlay 側で gate)
    me.deck = [repo.get(_FILLER)] * 6

    eff = _eff(overlay, "OP09-078", "counter")
    assert eff.get("cost", {}).get("pay_don") == 2, "overlay の ドン-2 コストが無い"
    assert eff.get("cost", {}).get("discard_hand") == 1, \
        "overlay の 手札1捨てコストが無い"
    assert eff.get("if", {}).get("leader_feature") == "麦わらの一味", \
        "overlay の リーダー条件 (麦わらの一味) が無い"
    hand_before = len(me.hand)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.battle_buff == 4000, \
        f"バトル中 自リーダー +4000 が乗っていない: {me.leader.battle_buff}"
    # 手札: 引き2枚 (捨てコストは overlay gate 側なので do 本体では引きのみ)
    assert len(me.hand) == hand_before + 2, \
        f"カード2枚が引けていない: {len(me.hand)} (before {hand_before})"


def test_op09_078_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 対象の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]
    me.deck = [repo.get(_FILLER)] * 6

    do = _eff(overlay, "OP09-078", "counter")["do"]
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 自チーム複数対象で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    fi = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    before = friend.power
    resolve_pending_choice(st, [fi])
    _drain(st, [fi])
    assert friend.power == before + 4000, \
        "人間が選んだキャラに +4000 が乗っていない"


# --------------------------------------------------------------------------- #
#  OP09-079 ゴムゴムの縄跳び (EVENT): 【メイン】ドン!!-2：相手のコスト5以下のキャラ1枚
#          までを レストにする。 その後、 カード1枚を引く。 【トリガー】アクティブドン+1。
# --------------------------------------------------------------------------- #
def test_op09_079_main_rest_and_draw_ai():
    """【メイン】相手コスト5以下キャラを レスト → カード1枚ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤5)
    victim.rested = False
    opp.characters = [victim]
    me.deck = [repo.get(_FILLER)] * 5
    me.hand = []

    eff = _eff(overlay, "OP09-079", "main")
    assert eff.get("cost", {}).get("pay_don") == 2, "overlay の ドン-2 コストが無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim.rested is True, "相手コスト5以下キャラがレストになっていない"
    assert len(me.hand) == 1, f"その後の1枚ドローが起きていない: hand={len(me.hand)}"


def test_op09_079_main_rest_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal で選んだ1枚だけレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_SMALL), sickness=False)
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    prim = _eff(overlay, "OP09-079", "main")["do"][0]
    execute_effect(prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b.rested is True, "人間が選んだ相手キャラがレストになっていない"
    assert a.rested is False, "選ばなかった相手キャラはアクティブのままであるべき"


def test_op09_079_trigger_add_don_ai():
    """【トリガー】ドン!!デッキからアクティブドン1枚を追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 5

    for prim in _eff(overlay, "OP09-079", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.don_active == 1, \
        f"トリガーで アクティブドンが +1 されていない: {me.don_active}"


# --------------------------------------------------------------------------- #
#  OP09-081 マーシャル・D・ティーチ (LEADER): 自分の【登場時】効果は無効になる。
#          【起動メイン】手札1枚を捨てられる：次の相手のターン終了時まで、
#          相手の【登場時】効果は無効になる。
# --------------------------------------------------------------------------- #
def test_op09_081_activate_main_disable_opp_on_play_ai():
    """【起動メイン】(手札1捨てコスト): 相手 on_play 無効フラグを立てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]

    eff = _eff(overlay, "OP09-081", "activate_main")
    assert eff.get("cost", {}).get("once_per_turn") is True, \
        "overlay の 【ターン1回】制限が無い"
    assert eff.get("cost", {}).get("discard_hand") == 1, \
        "overlay の 手札1捨てコストが無い"
    options = list_activate_main_effects(st, me, overlay)
    teach_opts = [(src, e) for (src, e) in options
                  if src.card.card_id == "OP09-081"]
    assert len(teach_opts) == 1, \
        f"OP09-081 の起動メインが legal に出ない: {len(teach_opts)}"
    hand_before = len(me.hand)
    fire_activate_main(st, me, opp, *teach_opts[0])
    assert getattr(opp, "opp_on_play_disabled_through_opp_turn", False) is True, \
        "相手 on_play 無効フラグが立っていない"
    assert len(me.hand) == hand_before - 1, "手札1捨てコストが消費されていない"


def test_op09_081_activate_main_once_per_turn():
    """【起動メイン】は【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 2

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP09-081"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP09-081"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP09-083 ヴァン・オーガー (CHARACTER): 【起動メイン】このキャラをレストにできる：
#          自リーダーが《黒ひげ海賊団》なら、 相手のキャラ1枚まで このターン中 コスト-3。
#          【KO時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_083_activate_main_cost_minus_ai():
    """【起動メイン】(自レストコスト): 黒ひげ海賊団 leader で 相手キャラを コスト-3 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    ogre = InPlay.of(repo.get("OP09-083"), sickness=False)
    me.characters = [ogre]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-083", "activate_main")
    assert eff.get("if", {}).get("leader_feature") == "黒ひげ海賊団", \
        "overlay の リーダー条件 (黒ひげ海賊団) が無い"
    options = list_activate_main_effects(st, me, overlay)
    ogre_opts = [(src, e) for (src, e) in options
                 if src.card.card_id == "OP09-083"]
    assert len(ogre_opts) == 1, \
        f"OP09-083 の起動メインが legal に出ない: {len(ogre_opts)}"
    fire_activate_main(st, me, opp, *ogre_opts[0])
    assert victim.cost_minus_until_turn_end == 3, \
        f"相手キャラの コスト-3 が反映されていない: {victim.cost_minus_until_turn_end}"
    assert ogre.rested is True, "起動メインコストで ヴァン・オーガー がレストされるべき"


def test_op09_083_activate_main_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal で選んだ1枚だけ コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ogre = InPlay.of(repo.get("OP09-083"), sickness=False)
    me.characters = [ogre]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_SMALL), sickness=False)
    opp.characters = [a, b]

    ogre_opts = [o for o in list_activate_main_effects(st, me, overlay)
                 if o[0].card.card_id == "OP09-083"]
    fire_activate_main(st, me, opp, *ogre_opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b.cost_minus_until_turn_end == 3, "人間が選んだ相手キャラに コスト-3 が乗っていない"
    assert a.cost_minus_until_turn_end == 0, "選ばなかった相手キャラは変化しないべき"


def test_op09_083_on_ko_draw_ai():
    """【KO時】カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 5
    me.hand = []

    for prim in _eff(overlay, "OP09-083", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-083"), sickness=False))
    assert len(me.hand) == 1, f"KO時の1枚ドローが起きていない: hand={len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP09-085 ゲッコー・モリア (CHARACTER): 【登場時】自分のトラッシュからコスト2以下の
#          特徴《スリラーバーク海賊団》を持つキャラ1枚までを、 レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op09_085_on_play_revive_from_trash_ai():
    """【登場時】トラッシュのコスト2以下スリラーバークキャラを レストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_THRILLER_C1)]  # ペローナ cost1 (スリラーバーク海賊団)
    me.characters = []

    for prim in _eff(overlay, "OP09-085", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-085"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == _THRILLER_C1 for c in me.characters), \
        "トラッシュのスリラーバークキャラが登場していない"
    revived = next(c for c in me.characters if c.card.card_id == _THRILLER_C1)
    assert revived.rested is True, "登場したキャラは レスト状態であるべき"
    assert not any(c.card_id == _THRILLER_C1 for c in me.trash), \
        "登場したキャラがトラッシュから取り除かれていない"


def test_op09_085_on_play_revive_human_pick():
    """人間 + トラッシュに該当キャラ複数 → play_from_trash_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_THRILLER_C1), repo.get(_THRILLER_C1B)]  # cost1 x2 種
    me.characters = []

    for prim in _eff(overlay, "OP09-085", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-085"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_trash modal が立たない"
    assert "play_from_trash" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_trash 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in (_THRILLER_C1, _THRILLER_C1B)
               for c in me.characters), \
        "人間が選んだスリラーバークキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-086 ジーザス・バージェス (CHARACTER): このキャラは相手の効果で KO されない。
#          自リーダーが《黒ひげ海賊団》なら、 このキャラは 自分のトラッシュ4枚につき +1000。
# --------------------------------------------------------------------------- #
def test_op09_086_static_ko_immune_and_trash_pump():
    """静的: 相手効果 KO 耐性 (常時) + 黒ひげ海賊団 leader で トラッシュ4枚につき +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    burgess = InPlay.of(repo.get("OP09-086"), sickness=False)
    me.characters = [burgess]
    me.trash = [repo.get(_FILLER)] * 8  # 8/4 = +2000

    evaluate_static_effects(st, overlay)
    base = repo.get("OP09-086").power  # 5000
    assert burgess.static_ko_immune is True, "相手効果 KO 耐性が付いていない"
    assert burgess.power == base + 2000, \
        f"黒ひげ leader + トラッシュ8枚で +2000 が乗っていない: {burgess.power} (base {base})"


def test_op09_086_static_no_trash_pump_off_leader():
    """自リーダーが《黒ひげ海賊団》でない場合、 トラッシュ参照 pump は乗らない (KO耐性は常時)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 麦わら leader (= 黒ひげでない)
    me, opp = st.players[0], st.players[1]
    burgess = InPlay.of(repo.get("OP09-086"), sickness=False)
    me.characters = [burgess]
    me.trash = [repo.get(_FILLER)] * 8

    evaluate_static_effects(st, overlay)
    base = repo.get("OP09-086").power
    assert burgess.static_ko_immune is True, "KO 耐性は leader 条件に関係なく常時であるべき"
    assert burgess.power == base, \
        f"黒ひげでない leader で トラッシュ pump が乗ってはいけない: {burgess.power} (base {base})"
