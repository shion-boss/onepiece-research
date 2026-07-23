# -*- coding: utf-8 -*-
"""OP04 弾 効果 回帰テスト バックフィル (自動生成 wave 053):
OP04-105 / OP04-106 / OP04-108 / OP04-109 / OP04-110 / OP04-112 /
OP04-113 / OP04-115 / OP04-116 / OP04-117 の 10 枚 (黄 ビッグ・マム / ワノ国 系)。

目的 (= test_backfill_auto_001〜052.py と同一方針):
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
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_ODEN = "OP01-031"      # 光月おでん (赤、 特徴 ワノ国)
_WANO_CHAR = "PRB02-008"       # マルコ ワノ国/元白ひげ海賊団 cost4 power6000
_ANIMAL_C3 = "EB02-003"        # トニートニー・チョッパー 動物 cost3
_ANIMAL_C3B = "EB01-006"       # トニートニー・チョッパー 動物 cost3 (別 iid 用)
_TRIGGER_CARD = "OP04-116"     # 【トリガー】を持つ EVENT (OP04-105 の捨てコスト用)
_PLAIN_C2 = "ST01-004"         # ゾロ cost2 (汎用ダミー / 捨てコストにならない非トリガー)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave53_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-105", "OP04-106", "OP04-108", "OP04-109", "OP04-110",
           "OP04-112", "OP04-113", "OP04-115", "OP04-116", "OP04-117"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-105 シャーロット・アマンド (CHARACTER 黄 cost3):
#    【起動メイン】【ターン1回】手札から【トリガー】1枚を捨てられる：
#      相手のコスト2以下のキャラ1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op04_105_activate_rest_opp_cost2_ai():
    """起動メイン: 【トリガー】カードを捨て → 相手のコスト2以下キャラを レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_TRIGGER_CARD)]     # 捨てコスト用の【トリガー】カード
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # cost2 相手キャラ
    opp.characters = [victim]

    for prim in _do(overlay, "OP04-105", "activate_main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-105"), sickness=False))

    assert victim.rested is True, "相手のコスト2以下キャラが レストになっていない"
    assert len(me.hand) == 0, "任意コストの【トリガー】カードが捨てられていない"


def test_op04_105_activate_no_trigger_card_no_cost():
    """手札に【トリガー】が無ければ 任意コストを払えず → 相手キャラは レストにならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_PLAIN_C2)]         # 非【トリガー】カードのみ
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP04-105", "activate_main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-105"), sickness=False))

    assert victim.rested is False, "コストを払えないのに 相手キャラが レストになっている"
    assert len(me.hand) == 1, "非トリガーカードが誤って捨てられている"


def test_op04_105_activate_human_flow():
    """人間: 任意コスト確認 → 承諾 → rest 対象選択 modal が立ち、 選んだ相手キャラが レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_TRIGGER_CARD)]
    v1 = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    v2 = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    opp.characters = [v1, v2]

    execute_effect(_do(overlay, "OP04-105", "activate_main")[0], st, me, opp,
                   InPlay.of(repo.get("OP04-105"), sickness=False))

    assert st.pending_choice is not None, "人間で 任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    assert st.pending_choice is not None, "承諾後 rest 対象選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"承諾後の kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert v1.rested or v2.rested, "人間が選んだ相手キャラが レストになっていない"


# --------------------------------------------------------------------------- #
#  OP04-106 シャーロット・ババロア (CHARACTER 黄 cost3 power4000):
#    【ドン!!×1】自ライフ枚数が相手より少ない場合、 このキャラはパワー+1000。
#    【トリガー】手札1枚を捨てて このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op04_106_static_pump_when_life_behind():
    """静的: ドン1 + 自ライフ < 相手ライフ → DON分+1000 と 効果+1000 = base+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP04-106"), sickness=False)
    c.attached_dons = 1
    me.characters = [c]
    me.life = [repo.get("ST01-004")] * 1     # 自ライフ 1
    opp.life = [repo.get("ST01-004")] * 4     # 相手ライフ 4 (= 自 < 相手)

    evaluate_static_effects(st, overlay)
    assert c.power == c.card.power + 2000, \
        f"自ライフ劣勢で DON1000+効果1000 = base+2000 になっていない: {c.power}"


def test_op04_106_static_no_pump_when_not_behind():
    """静的: 自ライフ >= 相手ライフ なら 効果条件不成立 → DON分+1000 のみ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP04-106"), sickness=False)
    c.attached_dons = 1
    me.characters = [c]
    me.life = [repo.get("ST01-004")] * 4      # 自ライフ 4
    opp.life = [repo.get("ST01-004")] * 1      # 相手ライフ 1 (= 自 >= 相手)

    evaluate_static_effects(st, overlay)
    assert c.power == c.card.power + 1000, \
        f"劣勢でないのに 効果 pump が乗っている: {c.power} (base {c.card.power})"


def test_op04_106_trigger_play_self_ai():
    """【トリガー】このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 2
    me.trash = [repo.get("OP04-106")]
    st.current_source_card_id = "OP04-106"

    for prim in _do(overlay, "OP04-106", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-106" for c in me.characters), \
        "トリガーで OP04-106 が登場していない"


# --------------------------------------------------------------------------- #
#  OP04-108 シャーロット・モスカート (CHARACTER 黄 cost3):
#    【ドン!!×1】このキャラは【バニッシュ】を得る。
#    【トリガー】手札1枚を捨てて このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op04_108_static_grants_banish_with_don():
    """静的: ドン1付与で【バニッシュ】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP04-108"), sickness=False)
    c.attached_dons = 1
    me.characters = [c]

    evaluate_static_effects(st, overlay)
    granted = c.granted_keywords | c.static_granted_keywords
    assert "バニッシュ" in granted, f"ドン1で バニッシュ が付与されていない: {granted}"


def test_op04_108_static_no_banish_without_don():
    """静的: ドン0 なら【バニッシュ】は付かない (ドン×1 ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get("OP04-108"), sickness=False)
    c.attached_dons = 0
    me.characters = [c]

    evaluate_static_effects(st, overlay)
    granted = c.granted_keywords | c.static_granted_keywords
    assert "バニッシュ" not in granted, \
        f"ドン0 なのに バニッシュ が付いている: {granted}"


def test_op04_108_trigger_play_self_pays_discard_ai():
    """【トリガー】手札1枚を捨てて このカードを登場 (任意コスト、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 2
    me.trash = [repo.get("OP04-108")]
    st.current_source_card_id = "OP04-108"

    hand_before = len(me.hand)
    for prim in _do(overlay, "OP04-108", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-108" for c in me.characters), \
        "トリガーで OP04-108 が登場していない"
    assert len(me.hand) == hand_before - 1, "登場コストの手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP04-109 トの康 (CHARACTER 黄 cost2):
#    【起動メイン】このキャラをトラッシュに置ける：自分の《ワノ国》リーダー/キャラ1枚まで
#      を、 このターン中、 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op04_109_activate_pump_wano_ai():
    """起動メイン: 自《ワノ国》キャラに このターン +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODEN, overlay)  # おでん ワノ国 leader
    me, opp = st.players[0], st.players[1]
    wano = InPlay.of(repo.get(_WANO_CHAR), sickness=False)
    me.characters = [wano]

    power_before = wano.power
    for prim in _do(overlay, "OP04-109", "activate_main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-109"), sickness=False))

    assert wano.power == power_before + 3000, \
        f"《ワノ国》キャラに +3000 が反映されていない: {wano.power} (before {power_before})"


def test_op04_109_activate_human_pick():
    """人間 + 《ワノ国》リーダー/キャラ 複数 → +3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODEN, overlay, human_idx=0)  # おでん自身も《ワノ国》
    me, opp = st.players[0], st.players[1]
    wano = InPlay.of(repo.get(_WANO_CHAR), sickness=False)
    me.characters = [wano]

    execute_effect(_do(overlay, "OP04-109", "activate_main")[0], st, me, opp,
                   InPlay.of(repo.get("OP04-109"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    wano_idx = next(i for i, c in enumerate(cands) if c["iid"] == wano.instance_id)
    power_before = wano.power
    resolve_pending_choice(st, [wano_idx])
    _drain(st)
    assert wano.power == power_before + 3000, \
        "人間が選んだ《ワノ国》キャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP04-110 パウンド (CHARACTER 黄 cost3):
#    【ブロッカー】【KO時】相手のコスト3以下のキャラ1枚までを、 相手ライフの上か下に
#      表向きで加える。
# --------------------------------------------------------------------------- #
def test_op04_110_on_ko_chara_to_opp_life_ai():
    """KO時: 相手のコスト3以下キャラを 相手ライフへ表向きで移動 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_ANIMAL_C3), sickness=False)  # cost3
    opp.characters = [victim]
    life_before = len(opp.life)

    for prim in _do(overlay, "OP04-110", "on_ko"):
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "対象キャラが場から除かれていない"
    assert len(opp.life) == life_before + 1, "相手ライフが1枚増えていない"


def test_op04_110_on_ko_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → to_opp_life の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_ANIMAL_C3), sickness=False)
    b = InPlay.of(repo.get(_ANIMAL_C3B), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP04-110", "on_ko")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "to_opp_life", \
        "primitive_kind が to_opp_life でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだキャラが相手ライフへ移動していない"


# --------------------------------------------------------------------------- #
#  OP04-112 ヤマト (CHARACTER 黄 cost9):
#    【登場時】お互いのライフ合計以下のコストを持つ相手キャラ1枚までを、 KO。
#      その後、 自ライフ1枚以下なら デッキ上1枚までを ライフ上に加える。
# --------------------------------------------------------------------------- #
def test_op04_112_on_play_ko_then_life_ai():
    """登場時: ライフ合計以下の相手キャラを KO → 自ライフ1以下で デッキ上1枚をライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 1      # 自ライフ 1 (= 条件成立)
    opp.life = [repo.get("ST01-004")] * 1      # ライフ合計 2 → cost<=2 KO 可
    me.deck = [repo.get("ST01-004")] * 10
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # cost2 <= 2
    opp.characters = [victim]

    life_before = len(me.life)
    for prim in _do(overlay, "OP04-112", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-112"), sickness=True))

    assert victim not in opp.characters, "ライフ合計以下コストの相手キャラが KO されていない"
    assert len(me.life) == life_before + 1, \
        "自ライフ1以下でデッキ上1枚がライフに加わっていない"


def test_op04_112_on_play_human_ko_pick():
    """人間 + 対象複数 → ko の target_pick modal が立ち、 選んだキャラが KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 1
    opp.life = [repo.get("ST01-004")] * 3      # 合計 4 → cost<=4 KO 可
    me.deck = [repo.get("ST01-004")] * 10
    a = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    b = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP04-112", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP04-112"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", \
        "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだキャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP04-113 ラビヤン (CHARACTER 黄 cost2):
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op04_113_trigger_play_self_ai():
    """【トリガー】このカードを場に登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP04-113")]
    st.current_source_card_id = "OP04-113"

    for prim in _do(overlay, "OP04-113", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-113" for c in me.characters), \
        "トリガーで OP04-113 が登場していない"


# --------------------------------------------------------------------------- #
#  OP04-115 銃・擬鬼 (EVENT 黄 cost1):
#    【メイン】自ライフ上か下1枚を手札に加えられる：自《ワノ国》キャラ1枚までは
#      このターン中【ダブルアタック】を得る。
#    【トリガー】自リーダー/キャラ1枚までを このターン +1000。
# --------------------------------------------------------------------------- #
def test_op04_115_main_grant_double_attack_ai():
    """メイン: 任意コスト (ライフ→手札) → 自《ワノ国》キャラに【ダブルアタック】(AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    wano = InPlay.of(repo.get(_WANO_CHAR), sickness=False)
    me.characters = [wano]

    hand_before = len(me.hand)
    for prim in _do(overlay, "OP04-115", "main"):
        execute_effect(prim, st, me, opp, None)

    granted = wano.granted_keywords | wano.static_granted_keywords
    assert "ダブルアタック" in granted, \
        f"《ワノ国》キャラに ダブルアタック が付与されていない: {granted}"
    assert len(me.hand) == hand_before + 1, "任意コストの ライフ→手札 が反映されていない"


def test_op04_115_trigger_pump_ai():
    """【トリガー】自リーダー/キャラ1枚に このターン +1000 (AI 自動、 リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _do(overlay, "OP04-115", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, \
        f"トリガーの +1000 が反映されていない: {me.leader.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP04-116 悪魔風脚 ほほ肉シュート (EVENT 黄 cost3):
#    【カウンター】自リーダー/キャラ1枚まで このバトル +6000。 その後、
#      お互いのライフ合計4枚以下なら 相手のコスト2以下キャラ1枚までを KO。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op04_116_counter_pump_and_ko_ai():
    """カウンター: +6000、 その後 ライフ合計4以下で 相手コスト2以下を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    opp.life = [repo.get("ST01-004")] * 2      # 合計 4 (= 条件成立)
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # cost2
    opp.characters = [victim]

    power_before = me.leader.power
    for prim in _do(overlay, "OP04-116", "counter"):
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 6000, \
        f"カウンターの +6000 が反映されていない: {me.leader.power}"
    assert victim not in opp.characters, \
        "ライフ合計4以下で 相手コスト2以下キャラが KO されていない"


def test_op04_116_counter_no_ko_when_life_high():
    """カウンター: ライフ合計 > 4 なら 条件不成立 → KO は起きない (+6000 のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 3
    opp.life = [repo.get("ST01-004")] * 3      # 合計 6 (= 条件不成立)
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP04-116", "counter"):
        execute_effect(prim, st, me, opp, None)

    assert victim in opp.characters, \
        "ライフ合計 > 4 なのに 相手キャラが KO されている"


def test_op04_116_trigger_draw_ai():
    """【トリガー】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 10

    hand_before = len(me.hand)
    for prim in _do(overlay, "OP04-116", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, \
        f"トリガーで 1 枚 引けていない: {hand_before} -> {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP04-117 天上の火 (EVENT 黄 cost1):
#    【メイン】相手のコスト3以下のキャラ1枚までを、 相手ライフの上か下に表向きで加える。
#    【トリガー】自ライフ上か下1枚を手札に加えられる：自分の手札1枚までを ライフ上へ。
# --------------------------------------------------------------------------- #
def test_op04_117_main_chara_to_opp_life_ai():
    """メイン: 相手のコスト3以下キャラを 相手ライフへ移動 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_ANIMAL_C3), sickness=False)  # cost3
    opp.characters = [victim]
    life_before = len(opp.life)

    for prim in _do(overlay, "OP04-117", "main"):
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "対象キャラが場から除かれていない"
    assert len(opp.life) == life_before + 1, "相手ライフが1枚増えていない"


def test_op04_117_main_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → to_opp_life の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_ANIMAL_C3), sickness=False)
    b = InPlay.of(repo.get(_ANIMAL_C3B), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP04-117", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "to_opp_life", \
        "primitive_kind が to_opp_life でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだキャラが相手ライフへ移動していない"


def test_op04_117_trigger_optional_hand_to_life_ai():
    """【トリガー】任意コスト (自ライフ→手札) → 手札1枚を ライフ上へ (AI 自動、 crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.hand = [repo.get("ST01-004")] * 2

    for prim in _do(overlay, "OP04-117", "trigger"):
        execute_effect(prim, st, me, opp, None)

    # 任意コストとして ライフ1枚を手札に加え、 手札1枚を ライフ上へ戻す → ライフ枚数は保存
    assert len(me.life) >= 1, "トリガー解決後 ライフが不正に消えている"
