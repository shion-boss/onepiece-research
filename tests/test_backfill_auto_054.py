# -*- coding: utf-8 -*-
"""OP04 / OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 054):
OP04-118 / OP04-119 / OP05-002 / OP05-003 / OP05-006 / OP05-007 /
OP05-008 / OP05-009 / OP05-010 / OP05-011 の 10 枚
(赤 革命軍 / 緑 ロシナンテ / 黄 ビッグ・マム 系)。

目的 (= test_backfill_auto_001〜053.py と同一方針):
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
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # モンキー・D・ルフィ (赤、 革命軍 非所持)
_LEADER_REVO = "OP07-001"      # モンキー・D・ドラゴン (赤、 特徴 革命軍)
_LEADER_MULTI = "EB04-001"     # ジュエリー・ボニー (赤/黄 = 多色 leader)
_RED_C3 = "EB02-003"           # トニートニー・チョッパー 赤 cost3 power3000
_GREEN_C5 = "EB02-016"         # チョッパーマン 緑 cost5 power6000 CHARACTER
_BIG_RED = "OP05-007"          # サボ 赤 power7000 (>=7000 の大型)
_NAMI = "OP01-016"             # ナミ 赤 cost1 power2000
_PLAIN_C2 = "ST01-004"         # サンジ cost2 power4000 (汎用ダミー)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_PLAIN_C2)] * 30
    p1.deck = [repo.get(_PLAIN_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"]
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


def _granted(ip):
    return ip.granted_keywords | ip.static_granted_keywords


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave54_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-118", "OP04-119", "OP05-002", "OP05-003", "OP05-006",
           "OP05-007", "OP05-008", "OP05-009", "OP05-010", "OP05-011"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-118 ネフェルタリ・ビビ (CHARACTER 赤 cost7 power4000):
#    このキャラ以外の自分のコスト3以上の赤のキャラすべては、【速攻】を得る。 (静的)
# --------------------------------------------------------------------------- #
def test_op04_118_static_grants_rush_to_red_cost3_chars():
    """静的: 自分のコスト3以上の赤キャラ (ビビ以外) が【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    vivi = InPlay.of(repo.get("OP04-118"), sickness=False)   # 赤 cost7 (このキャラ)
    chopper = InPlay.of(repo.get(_RED_C3), sickness=False)   # 赤 cost3 → 速攻付与対象
    me.characters = [vivi, chopper]

    evaluate_static_effects(st, overlay)
    assert "速攻" in _granted(chopper), \
        f"赤 cost3 キャラに 速攻 が付与されていない: {_granted(chopper)}"
    assert "速攻" not in _granted(vivi), \
        f"「このキャラ以外」なのに ビビ自身に 速攻 が付いている: {_granted(vivi)}"


def test_op04_118_static_no_rush_for_cost2_red():
    """静的: コスト2 (< 3) の赤キャラは 速攻付与の対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    vivi = InPlay.of(repo.get("OP04-118"), sickness=False)
    low = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # 赤 cost2 (< 3)
    me.characters = [vivi, low]

    evaluate_static_effects(st, overlay)
    assert "速攻" not in _granted(low), \
        f"コスト2 の赤キャラに 速攻 が付いてはいけない: {_granted(low)}"


# --------------------------------------------------------------------------- #
#  OP04-119 ドンキホーテ・ロシナンテ (CHARACTER 緑 cost8 power8000):
#    【登場時】このキャラをレストにできる：自分の手札からコスト5の緑のキャラカード1枚
#      までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op04_119_on_play_play_cost5_green_ai():
    """登場時: レストコストを払い 手札のコスト5緑キャラを登場させる (AI 自動、 trigger_on_play)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    rosinante = InPlay.of(repo.get("OP04-119"), sickness=True)
    me.characters = [rosinante]
    me.hand = [repo.get(_GREEN_C5)]   # コスト5 緑 CHARACTER

    trigger_on_play(st, me, opp, rosinante, overlay)
    _drain(st, pick=[0])

    assert any(c.card.card_id == _GREEN_C5 for c in me.characters), \
        "手札のコスト5緑キャラが登場していない"
    assert rosinante.rested is True, "登場時コストで ロシナンテ がレストされていない"
    assert not any(c.card_id == _GREEN_C5 for c in me.hand), \
        "登場したキャラが手札に残っている"


def test_op04_119_on_play_human_pick():
    """人間 + 手札にコスト5緑キャラ複数 → 登場先を選ぶ play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 枚の コスト5 緑 CHARACTER を手札に (登場先を選べる状況)
    me.hand = [repo.get(_GREEN_C5), repo.get("EB03-017")]  # チョッパーマン / ボニー

    execute_effect(_do(overlay, "OP04-119", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP04-119"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id in (_GREEN_C5, "EB03-017") for c in me.characters), \
        "人間が選んだコスト5緑キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP05-002 ベロ・ベティ (LEADER 赤/黄):
#    【起動メイン】【ターン1回】手札から特徴《革命軍》1枚を捨てられる：自分の
#      特徴《革命軍》か【トリガー】を持つキャラ3枚までを、 このターン中、 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op05_002_activate_pump_ai():
    """起動メイン: 自キャラを このターン +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-002", overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get(_RED_C3), sickness=False)
    me.characters = [c]

    power_before = c.power
    for prim in _do(overlay, "OP05-002", "activate_main"):
        execute_effect(prim, st, me, opp, me.leader)

    assert c.power == power_before + 3000, \
        f"起動メインの +3000 が自キャラに反映されていない: {c.power} (before {power_before})"


def test_op05_002_activate_human_pick():
    """人間 + 自キャラ複数 → +3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-002", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_RED_C3), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP05-002", "activate_main")[0], st, me, opp,
                   me.leader)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a.power == a_before + 3000, \
        "人間が選んだ自キャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-003 イナズマ (CHARACTER 赤 cost3):
#    このキャラ以外の自分のパワー7000以上のキャラがいる場合、 このキャラは【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op05_003_static_rush_when_big_ally_present():
    """静的: 自分に パワー7000以上キャラ (イナズマ以外) が居れば イナズマは【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    inazuma = InPlay.of(repo.get("OP05-003"), sickness=False)
    big = InPlay.of(repo.get(_BIG_RED), sickness=False)  # サボ power7000
    me.characters = [inazuma, big]

    evaluate_static_effects(st, overlay)
    assert "速攻" in _granted(inazuma), \
        f"パワー7000以上の味方が居るのに 速攻 が付いていない: {_granted(inazuma)}"


def test_op05_003_static_no_rush_without_big_ally():
    """静的: パワー7000以上の味方が居なければ 速攻は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    inazuma = InPlay.of(repo.get("OP05-003"), sickness=False)
    me.characters = [inazuma]  # 大型味方なし

    evaluate_static_effects(st, overlay)
    assert "速攻" not in _granted(inazuma), \
        f"大型味方が居ないのに 速攻 が付いている: {_granted(inazuma)}"


# --------------------------------------------------------------------------- #
#  OP05-006 コアラ (CHARACTER 赤 cost2):
#    【登場時】自分のリーダーが特徴《革命軍》を持つ場合、 相手のキャラ1枚までを、
#      このターン中、 パワー-3000。
# --------------------------------------------------------------------------- #
def test_op05_006_on_play_debuff_when_revo_leader_ai():
    """登場時: 自リーダーが革命軍 → 相手キャラ1枚 -3000 (AI 自動、 trigger_on_play)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)  # ドラゴン (革命軍)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    koala = InPlay.of(repo.get("OP05-006"), sickness=True)
    me.characters = [koala]
    trigger_on_play(st, me, opp, koala, overlay)
    _drain(st, pick=[0])

    assert victim.power == power_before - 3000, \
        f"革命軍リーダー時 相手キャラに -3000 が反映されていない: {victim.power}"


def test_op05_006_on_play_no_debuff_when_not_revo_leader():
    """登場時: 自リーダーが革命軍でなければ 条件不成立 → 相手キャラは -3000 されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)  # 革命軍 非所持
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    koala = InPlay.of(repo.get("OP05-006"), sickness=True)
    me.characters = [koala]
    trigger_on_play(st, me, opp, koala, overlay)
    _drain(st)

    assert victim.power == power_before, \
        f"非革命軍リーダーなのに 相手キャラが -3000 されている: {victim.power}"


def test_op05_006_on_play_human_pick():
    """人間 + 相手キャラ複数 → -3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-006", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-006"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before - 3000, \
        "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-007 サボ (CHARACTER 赤 cost6 power7000):
#    【登場時】相手のキャラ2枚までを、 パワーの合計が4000以下になるようにKOする。
# --------------------------------------------------------------------------- #
def test_op05_007_on_play_ko_total_power_le_ai():
    """登場時: パワー合計4000以下になるよう 相手キャラ最大2枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)  # power2000
    b = InPlay.of(repo.get(_NAMI), sickness=False)  # power2000 (合計4000 <= 4000)
    opp.characters = [a, b]

    for prim in _do(overlay, "OP05-007", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-007"), sickness=True))

    assert a not in opp.characters and b not in opp.characters, \
        "パワー合計4000以下の相手キャラ2枚が KO されていない"


def test_op05_007_on_play_big_chara_survives():
    """登場時: 単独でパワー > 4000 のキャラは 合計制約により KO 不可 (= 残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_BIG_RED), sickness=False)  # power7000 (> 4000)
    opp.characters = [big]

    for prim in _do(overlay, "OP05-007", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-007"), sickness=True))

    assert big in opp.characters, \
        "単独で power > 4000 のキャラが KO されている (合計制約違反)"


# --------------------------------------------------------------------------- #
#  OP05-008 チャカ (CHARACTER 赤 cost5 power6000):
#    【ドン!!×1】【起動メイン】【ターン1回】自分のリーダーかキャラ1枚に
#      レストのドン!!2枚までを、 付与する。
# --------------------------------------------------------------------------- #
def test_op05_008_activate_attach_rested_don_ai():
    """起動メイン: 自リーダーへ レストのドン2枚を付与 (AI 自動、 self_inplay_choice → リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    chaka = InPlay.of(repo.get("OP05-008"), sickness=False)
    chaka.attached_dons = 1  # 【ドン!!×1】ゲート
    me.characters = [chaka]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _do(overlay, "OP05-008", "activate_main"):
        execute_effect(prim, st, me, opp, chaka)

    assert me.leader.attached_dons == don_before + 2, \
        f"自リーダーに レストドン2枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_op05_008_activate_human_pick():
    """人間 + 自リーダー/キャラ 複数 → 付与先を選ぶ target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    chaka = InPlay.of(repo.get("OP05-008"), sickness=False)
    chaka.attached_dons = 1
    me.characters = [chaka]
    me.don_rested = 2

    execute_effect(_do(overlay, "OP05-008", "activate_main")[0], st, me, opp,
                   chaka)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    chaka_idx = next(i for i, c in enumerate(cands) if c["iid"] == chaka.instance_id)
    resolve_pending_choice(st, [chaka_idx])
    _drain(st)
    assert chaka.attached_dons >= 2 + 1, \
        f"人間が選んだ チャカ に レストドン2枚が付与されていない: {chaka.attached_dons}"


# --------------------------------------------------------------------------- #
#  OP05-009 トト (CHARACTER 赤 cost1):
#    【登場時】自分のリーダーのパワーが0以下の場合、 カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op05_009_on_play_draw_when_leader_power_le_0_ai():
    """登場時: 自リーダーのパワーが0以下 → 1ドロー (AI 自動、 trigger_on_play)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.turn_buff = -6000  # base 5000 → power -1000 (<= 0)
    assert me.leader.power <= 0, "テスト前提: リーダーのパワーが0以下"
    me.deck = [repo.get(_PLAIN_C2)] * 5

    toto = InPlay.of(repo.get("OP05-009"), sickness=True)
    me.characters = [toto]
    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, toto, overlay)
    _drain(st)

    assert len(me.hand) == hand_before + 1, \
        f"リーダーパワー0以下で 1ドロー が起きていない: {hand_before} -> {len(me.hand)}"


def test_op05_009_on_play_no_draw_when_leader_power_positive():
    """登場時: 自リーダーのパワーが正 → 条件不成立で ドローしない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    assert me.leader.power > 0, "テスト前提: リーダーのパワーが正"
    me.deck = [repo.get(_PLAIN_C2)] * 5

    toto = InPlay.of(repo.get("OP05-009"), sickness=True)
    me.characters = [toto]
    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, toto, overlay)
    _drain(st)

    assert len(me.hand) == hand_before, \
        f"リーダーパワーが正なのに ドロー が起きている: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP05-010 ニコ・ロビン (CHARACTER 赤 cost1 power2000):
#    【登場時】相手のパワー1000以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op05_010_on_play_ko_power_le_1000_ai():
    """登場時: 相手のパワー1000以下キャラを KO (AI 自動)。 2000以上は対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    weak = InPlay.of(repo.get(_NAMI), sickness=False)   # power2000
    weak.turn_buff = -1000                               # → power1000 (<= 1000)
    strong = InPlay.of(repo.get(_NAMI), sickness=False)  # power2000 (> 1000)
    opp.characters = [weak, strong]

    for prim in _do(overlay, "OP05-010", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-010"), sickness=True))

    assert weak not in opp.characters, "パワー1000以下キャラが KO されていない"
    assert strong in opp.characters, "パワー2000のキャラは対象外 (残るべき)"


def test_op05_010_on_play_human_pick():
    """人間 + パワー1000以下キャラ複数 → ko の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)
    a.turn_buff = -1000  # power1000
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    b.turn_buff = -1000  # power1000
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-010", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-010"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだキャラが KO されていない"
    assert b in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP05-011 バーソロミュー・くま (CHARACTER 赤 cost2 power2000):
#    【登場時】相手のパワー2000以下のキャラ1枚までを、 KOする。
#    【トリガー】自分のリーダーが多色の場合、 このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op05_011_on_play_ko_power_le_2000_ai():
    """登場時: 相手のパワー2000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # power2000 (<= 2000)
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-011", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-011"), sickness=True))

    assert victim not in opp.characters, "パワー2000以下キャラが KO されていない"


def test_op05_011_trigger_play_self_when_multicolor_leader_ai():
    """【トリガー】自リーダーが多色 → このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay)  # ボニー 赤/黄 (多色)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP05-011")]
    st.current_source_card_id = "OP05-011"

    for prim in _do(overlay, "OP05-011", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert any(c.card.card_id == "OP05-011" for c in me.characters), \
        "多色リーダー時 トリガーで OP05-011 が登場していない"
