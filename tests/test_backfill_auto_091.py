# -*- coding: utf-8 -*-
"""OP08 / OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 091):
OP08-113 / OP08-114 / OP08-115 / OP08-116 / OP08-117 / OP08-118 /
OP08-119 / OP09-001 / OP09-003 / OP09-007 の 10 枚
(黄 シャンドラの戦士 / 空島 系 + 赤 デバフ 系 + 紫 全 KO)。

目的 (= test_backfill_auto_001〜090.py と同一方針):
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_SHANDIA = "OP08-098"  # カルガラ (leader、 特徴 ジャヤ/空島/シャンドラの戦士)
_LEADER_NEUTRAL = "OP01-001"  # モンキー・D・ルフィ (中立 leader、 power5000)
_LEADER_SHANKS = "OP09-001"   # シャンクス (leader、 OP09-001 本体)
_UPPER_YARD = "OP05-117"      # アッパーヤード (STAGE cost1)
_SHANDIA_CHAR = "OP06-113"    # ラキ (CHARACTER cost1 power1000 空島/シャンドラの戦士)
_OPP_C6 = "PRB02-014"         # サボ cost6 power6000
_OPP_C4 = "PRB02-006"         # ロロノア・ゾロ cost4 power4000
_OPP_SMALL = "OP01-016"       # ナミ cost1 power2000 (小型 KO 対象)
_FILLER = "OP01-013"          # サンジ cost2 power3000 (デッキ/手札 埋め用、 vanilla)


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
def test_all_wave91_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-113", "OP08-114", "OP08-115", "OP08-116", "OP08-117",
           "OP08-118", "OP08-119", "OP09-001", "OP09-003", "OP09-007"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-113 S-ベア (CHARACTER 黄 cost3):
#    【トリガー】自分の手札1枚を捨てることができる：自ライフ2枚以下なら
#      このカードを登場させ、 相手のコスト3以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op08_113_sbear_trigger_play_and_ko_ai():
    """トリガー (ライフ2以下): 手札1捨て → 自身を登場 + 相手コスト3以下1枚KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2       # ライフ2 (= 条件成立)
    me.hand = [repo.get(_FILLER)]           # 捨てるコスト用
    me.trash = [repo.get("OP08-113")]       # トリガー元は トラッシュに置かれている
    st.current_source_card_id = "OP08-113"
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=3 → KO)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP08-113", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert any(c.card.card_id == "OP08-113" for c in me.characters), \
        "トリガーで S-ベア が登場していない"
    assert len(opp.characters) == 0, "相手のコスト3以下キャラがKOされていない"
    assert len(me.hand) == 0, "任意コストで手札1枚が捨てられていない"


def test_op08_113_sbear_trigger_condition_fail_life3():
    """ライフ3枚 (>2) なら 条件不成立 → 登場も KO も 起きない (コストは払う)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3       # ライフ3 (= 条件不成立)
    me.hand = [repo.get(_FILLER)]
    me.trash = [repo.get("OP08-113")]
    st.current_source_card_id = "OP08-113"
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP08-113", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert not any(c.card.card_id == "OP08-113" for c in me.characters), \
        "ライフ3枚では S-ベア は登場してはいけない"
    assert victim in opp.characters, "ライフ3枚では 相手キャラが KO されてはいけない"


def test_op08_113_sbear_trigger_human_optional_confirm():
    """人間: 任意コスト (手札1捨て) の確認 modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = [repo.get(_FILLER)]
    me.trash = [repo.get("OP08-113")]
    st.current_source_card_id = "OP08-113"
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]

    execute_effect(_eff(overlay, "OP08-113", "trigger")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  OP08-114 S-ホーク (CHARACTER 黄 cost4):
#    【トリガー】自分の手札1枚を捨てることができる：自ライフ2枚以下なら
#      このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op08_114_shawk_trigger_play_self_ai():
    """トリガー (ライフ2以下): 手札1捨て → 自身を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = [repo.get(_FILLER)]
    me.trash = [repo.get("OP08-114")]
    st.current_source_card_id = "OP08-114"

    for prim in _eff(overlay, "OP08-114", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert any(c.card.card_id == "OP08-114" for c in me.characters), \
        "トリガーで S-ホーク が登場していない"
    assert len(me.hand) == 0, "任意コストで手札1枚が捨てられていない"


def test_op08_114_shawk_trigger_condition_fail_life3():
    """ライフ3枚 (>2) なら 登場しない (コストは払う)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_FILLER)]
    me.trash = [repo.get("OP08-114")]
    st.current_source_card_id = "OP08-114"

    for prim in _eff(overlay, "OP08-114", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert not any(c.card.card_id == "OP08-114" for c in me.characters), \
        "ライフ3枚では S-ホーク は登場してはいけない"


# --------------------------------------------------------------------------- #
#  OP08-115 大地は敗けない!!! (EVENT 黄 cost1):
#    【カウンター】自リーダーが《シャンドラの戦士》なら 自リーダー/キャラ1枚 +3000。
#      その後、 手札から「アッパーヤード」1枚までを登場。
#    【トリガー】カード2枚引き、 手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op08_115_counter_pump_and_play_stage_ai():
    """カウンター (シャンドラ leader): 自リーダー +3000 + 手札の「アッパーヤード」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANDIA, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_UPPER_YARD)]  # アッパーヤード (STAGE)

    power_before = me.leader.power
    for prim in _eff(overlay, "OP08-115", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
    assert any(s.card.card_id == _UPPER_YARD for s in me.stages), \
        "手札の「アッパーヤード」が登場していない"


def test_op08_115_trigger_draw2_discard1_ai():
    """トリガー: カード2枚引き、 手札1枚を捨てる (AI)。 deck-2 / trash+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in _eff(overlay, "OP08-115", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert len(me.deck) == deck_before - 2, "2ドローでデッキが2枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1枚の捨てが起きていない (trash+1)"


def test_op08_115_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANDIA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    execute_effect(_eff(overlay, "OP08-115", "counter")["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st, pick=[0])
    assert friend.power == friend_before + 3000, \
        "人間が選んだキャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP08-116 燃焼砲 (EVENT 黄 cost2):
#    【カウンター】自リーダー/キャラ1枚 +4000。 その後、 自ライフの上か下から1枚を
#      手札に加えてもよい。 そうした場合、 手札の《シャンドラの戦士》1枚までを
#      ライフの上に表向きで加える。
# --------------------------------------------------------------------------- #
def test_op08_116_counter_pump_ai():
    """カウンター (1): 自リーダー1枚 +4000 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANDIA, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2

    power_before = me.leader.power
    execute_effect(_eff(overlay, "OP08-116", "counter")["do"][0], st, me, opp, None)
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op08_116_counter_life_manip_ai():
    """カウンター (2): 自ライフ上下1枚を手札へ → 手札のシャンドラ1枚をライフ表向きに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANDIA, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = [repo.get(_SHANDIA_CHAR)]  # ラキ (空島/シャンドラの戦士)

    # do[1] = optional_cost_then (life→手札 → シャンドラを表向きでライフへ)
    for prim in _eff(overlay, "OP08-116", "counter")["do"][1:]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert any(c.card_id == _SHANDIA_CHAR for c in me.life), \
        "手札のシャンドラの戦士がライフの上に加わっていない"
    assert not any(c.card_id == _SHANDIA_CHAR for c in me.hand), \
        "シャンドラの戦士は手札からライフへ移るべき"
    assert me.face_up_life_count >= 1, "ライフに加えたカードが表向きになっていない"


# --------------------------------------------------------------------------- #
#  OP08-117 燃焼剣 (EVENT 黄 cost5):
#    【メイン】自ライフの上から1枚をトラッシュに置くことができる：
#      相手のコスト7以下のキャラ1枚までを、 KOする。
#    【トリガー】自ライフの上から1枚を手札に加えることができる：手札1枚までをライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op08_117_main_ko_ai():
    """メイン: 自ライフ上1枚をトラッシュ → 相手コスト7以下1枚をKO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)  # cost6 (<=7 → KO)
    opp.characters = [victim]

    life_before = len(me.life)
    trash_before = len(me.trash)
    for prim in _eff(overlay, "OP08-117", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert len(opp.characters) == 0, "相手のコスト7以下キャラがKOされていない"
    assert len(me.life) == life_before - 1, "任意コストで自ライフ上1枚がトラッシュされていない"
    assert len(me.trash) == trash_before + 1, "トラッシュが1枚増えていない"


def test_op08_117_trigger_life_to_hand_ai():
    """トリガー: 自ライフ上1枚を手札に加える (AI)。 life-1 / hand+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []

    life_before = len(me.life)
    for prim in _eff(overlay, "OP08-117", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert len(me.life) == life_before - 1, "ライフ上1枚が手札に加わっていない (life-1)"
    assert len(me.hand) == 1, "ライフ上1枚が手札に加わっていない (hand+1)"


def test_op08_117_main_human_optional_confirm():
    """人間: 任意コスト (自ライフ上1枚トラッシュ) の確認 modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    opp.characters = [InPlay.of(repo.get(_OPP_C6), sickness=False)]

    execute_effect(_eff(overlay, "OP08-117", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  OP08-118 シルバーズ･レイリー (CHARACTER 赤 cost8 power8000):
#    【登場時】相手のキャラ2枚までを選び、 次の相手ターン終了時まで、
#      1枚を -3000、 残りを -2000。 その後、 相手のパワー3000以下1枚をKO。
# --------------------------------------------------------------------------- #
def test_op08_118_rayleigh_on_play_debuff_minus3000_ai():
    """登場時 do[0]: 相手キャラ1枚を -3000 (AI)。 サボ 6000 → 3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)  # power6000
    opp.characters = [victim]

    power_before = victim.power
    execute_effect(_eff(overlay, "OP08-118", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-118"), sickness=True))
    _drain(st, pick=[0])
    assert victim.power == power_before - 3000, \
        f"相手キャラへの -3000 が反映されていない: {victim.power} (before {power_before})"


def test_op08_118_rayleigh_on_play_ko_small_ai():
    """登場時 do[2]: 相手のパワー3000以下キャラ1枚をKO (AI)。 ナミ 2000 → KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_SMALL), sickness=False)  # power2000 (<=3000)
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP08-118", "on_play")["do"][2], st, me, opp,
                   InPlay.of(repo.get("OP08-118"), sickness=True))
    _drain(st, pick=[0])
    assert len(opp.characters) == 0, "相手のパワー3000以下キャラがKOされていない"


def test_op08_118_rayleigh_on_play_debuff_human_pick():
    """人間 + 相手キャラ複数 → -3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP08-118", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-118"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[0])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP08-119 カイドウ＆リンリン (CHARACTER 紫 cost10 power12000):
#    【アタック時】ドン‼-10：このキャラ以外のキャラすべてをKO。 その後、
#      自デッキ上1枚までをライフの上に加え、 相手ライフ上1枚までをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op08_119_kaido_linlin_on_attack_wipe_and_life_ai():
    """アタック時: 自身以外の全キャラKO + 自デッキ上1ライフ + 相手ライフ上1トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    kaido = InPlay.of(repo.get("OP08-119"), sickness=False)
    friend = InPlay.of(repo.get(_FILLER), sickness=False)  # 自身以外 → KO 対象
    me.characters = [kaido, friend]
    o1 = InPlay.of(repo.get(_OPP_C4), sickness=False)
    o2 = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [o1, o2]
    me.life = [repo.get(_FILLER)] * 2
    opp.life = [repo.get(_FILLER)] * 2

    deck_before = len(me.deck)
    life_before = len(me.life)
    opp_life_before = len(opp.life)
    opp_trash_before = len(opp.trash)
    for prim in _eff(overlay, "OP08-119", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, kaido)
    _drain(st, pick=[0])

    assert kaido in me.characters, "アタッカー自身 (カイドウ＆リンリン) は残るべき"
    assert friend not in me.characters, "自身以外の自キャラが KO されていない"
    assert len(opp.characters) == 0, "相手キャラ全てが KO されていない"
    assert len(me.deck) == deck_before - 1, "自デッキ上1枚がライフへ移っていない (deck-1)"
    assert len(me.life) == life_before + 1, "自ライフが1枚増えていない (life+1)"
    assert len(opp.life) == opp_life_before - 1, "相手ライフ上1枚がトラッシュされていない"
    # 相手トラッシュ: KO された相手キャラ 2 枚 + ライフから落ちた 1 枚 = +3
    assert len(opp.trash) == opp_trash_before + 3, \
        f"相手トラッシュが KO2枚 + ライフ1枚 = +3 でない: {len(opp.trash)}"


# --------------------------------------------------------------------------- #
#  OP09-001 シャンクス (LEADER 赤):
#    【ターン1回】相手がアタックした時、 相手のリーダーかキャラ1枚まで、
#      このターン中、 パワー-1000。
# --------------------------------------------------------------------------- #
def test_op09_001_shanks_opp_attack_debuff_leader_ai():
    """相手アタック時: 相手リーダー1枚 -1000 (AI、 相手キャラ不在 → リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = opp.leader.power
    for prim in _eff(overlay, "OP09-001", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert opp.leader.power == power_before - 1000, \
        f"相手リーダーへの -1000 が反映されていない: {opp.leader.power} (before {power_before})"


def test_op09_001_shanks_opp_attack_human_pick():
    """人間 + 相手リーダー/キャラ 複数 → -1000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    foe = InPlay.of(repo.get(_OPP_C4), sickness=False)
    opp.characters = [foe]

    execute_effect(_eff(overlay, "OP09-001", "opp_attack")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    foe_idx = next(i for i, c in enumerate(cands) if c["iid"] == foe.instance_id)
    foe_before = foe.power
    resolve_pending_choice(st, [foe_idx])
    _drain(st, pick=[0])
    assert foe.power == foe_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP09-003 シャチ＆ペンギン (CHARACTER 赤 cost4):
#    【アタック時】相手のキャラ1枚までを、 このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op09_003_shachi_penguin_on_attack_debuff_ai():
    """アタック時: 相手キャラ1枚を このターン中 -2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP09-003", "on_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-003"), sickness=False))
    _drain(st, pick=[0])

    assert victim.power == power_before - 2000, \
        f"相手キャラへの -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op09_003_shachi_penguin_on_attack_human_pick():
    """人間 + 相手キャラ複数 → -2000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP09-003", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-003"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[0])
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP09-007 ヒート (CHARACTER 赤 cost3):
#    【ブロッカー】【登場時】自分のパワー4000以下のリーダー1枚までを、
#      このターン中、 パワー+1000。
# --------------------------------------------------------------------------- #
def test_op09_007_heat_on_play_pump_self_leader_ai():
    """登場時: 自リーダーを このターン中 +1000 (AI)。 overlay の条件 gate も確認。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    eff = _eff(overlay, "OP09-007", "on_play")
    assert eff.get("if", {}).get("self_leader_power_le") == 4000, \
        "overlay の 条件 self_leader_power_le=4000 が無い"

    power_before = me.leader.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-007"), sickness=True))
    _drain(st, pick=[0])

    assert me.leader.power == power_before + 1000, \
        f"登場時の 自リーダー +1000 が反映されていない: {me.leader.power} (before {power_before})"
