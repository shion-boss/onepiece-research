# -*- coding: utf-8 -*-
"""OP04 (青 百獣海賊団 / 東の海 / 麦わらの一味) 効果 回帰テスト
バックフィル (自動生成 wave 048):
OP04-045 / OP04-046 / OP04-047 / OP04-048 / OP04-049 /
OP04-050 / OP04-051 / OP04-052 / OP04-055 / OP04-056 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_condition,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# 百獣海賊団 特徴を持つ LEADER (= 青/紫 カイドウ OP01-061)。
HYAKUJU_LEADER = "OP01-061"
# 氷鬼 (= OP04-047)、 疫災弾 (= OP04-055)。 OP04-046 / 055 が名指しするカード。
HYOUKI = "OP04-047"
EKISAIDAN = "OP04-055"


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


def _get_eff(overlay, cid, when, needle=None):
    for e in overlay.get(cid).effects:
        if e["when"] == when and (needle is None or needle in str(e["do"])):
            return e
    raise KeyError(cid, when, needle)


def _drain(st, sel=None, guard=8):
    """pending_choice を sel (既定 [0]) で解決し続ける (人間チェーン用)。"""
    if sel is None:
        sel = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, sel)
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave48_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-045", "OP04-046", "OP04-047", "OP04-048", "OP04-049",
           "OP04-050", "OP04-051", "OP04-052", "OP04-055", "OP04-056"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-045 キング (CHARACTER 青 cost7):
#    【登場時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op04_045_on_play_draw_ai():
    """【登場時】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP04-045", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-045"), sickness=False))
        _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"【登場時】カード1枚を引いていない: hand={len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP04-046 クイーン (CHARACTER 青 cost4):
#    【登場時】自分のリーダーが特徴《百獣海賊団》を持つ場合、自分のデッキの上から7枚を見て、
#      「疫災弾」か「氷鬼」合計2枚までを公開し、手札に加える。その後、残りを好きな順番で
#      デッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op04_046_on_play_condition_hyakuju_leader():
    """【登場時】効果の if = 百獣海賊団 リーダー。"""
    repo = _repo()
    overlay = _overlay()
    eff = _get_eff(overlay, "OP04-046", "on_play")
    st_ok = _state(repo, HYAKUJU_LEADER, overlay)
    assert eval_condition(eff["if"], st_ok, st_ok.players[0]) is True, \
        "百獣海賊団リーダーで条件成立しない"
    st_ng = _state(repo, "OP01-001", overlay)
    assert eval_condition(eff["if"], st_ng, st_ng.players[0]) is False, \
        "非百獣海賊団リーダーで条件が成立している"


def test_op04_046_on_play_search_ai():
    """【登場時】(百獣リーダー) 上7枚から「疫災弾」「氷鬼」を2枚まで手札に (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, HYAKUJU_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(EKISAIDAN), repo.get(HYOUKI)] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = _get_eff(overlay, "OP04-046", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-046"), sickness=False))
        _drain(st, [0])
    assert any(c.card_id == EKISAIDAN for c in me.hand), \
        "上7枚から「疫災弾」が手札に加わっていない"
    assert any(c.card_id == HYOUKI for c in me.hand), \
        "上7枚から「氷鬼」が手札に加わっていない"


def test_op04_046_on_play_human_search_modal():
    """人間: 上7枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, HYAKUJU_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(HYOUKI)] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = _get_eff(overlay, "OP04-046", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-046"), sickness=False))
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card_id == HYOUKI for c in me.hand), \
        "人間が選んだ「氷鬼」が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-047 氷鬼 (CHARACTER 青 cost8):
#    (overlay proxy) 相手のコスト5以下のキャラ1枚を、持ち主のデッキの下に置く。
#      (公式は「バトル終了時」 trigger だが engine は on_attack + self_turn で近似発火)
# --------------------------------------------------------------------------- #
def test_op04_047_return_cost_le_5_ai():
    """相手のコスト5以下キャラ1枚を持ち主のデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]
    opp.deck = []

    eff = _get_eff(overlay, "OP04-047", "on_attack")
    assert eval_condition(eff["if"], st, me) is True, \
        "自分のターン中で self_turn 条件が成立しない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-047"), sickness=False))
        _drain(st, [0])
    assert victim not in opp.characters, \
        "相手のコスト5以下キャラが場から戻されていない"
    assert any(c.card_id == "OP01-013" for c in opp.deck), \
        "戻したキャラが持ち主のデッキに置かれていない"


def test_op04_047_human_return_target_pick():
    """人間 actor: 戻す対象の target_pick modal が立ち、 解決で1枚デッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v2 = InPlay.of(repo.get("OP01-013"), sickness=False)  # 複数候補で modal
    opp.characters = [v1, v2]

    eff = _get_eff(overlay, "OP04-047", "on_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-047"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert len(opp.characters) == 1, "人間選択後 相手キャラ1枚が場から戻されていない"


# --------------------------------------------------------------------------- #
#  OP04-048 ササキ (CHARACTER 青 cost3):
#    【登場時】自分の手札すべてをデッキに戻し、デッキをシャッフルする。その後、
#      デッキに戻した枚数分カードを引く。
# --------------------------------------------------------------------------- #
def test_op04_048_on_play_hand_recycle_ai():
    """【登場時】手札全戻し + 戻した枚数ドロー (AI 自動)。 手札枚数は保存される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]  # 打 サンジ 2枚
    me.deck = [repo.get("OP01-016")] * 30  # 特 ナミ (別カード) をデッキに
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP04-048", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-048"), sickness=False))
        _drain(st, [0])
    assert len(me.hand) == hand_before, \
        f"戻した枚数分ドローしておらず手札枚数が保存されていない: hand={len(me.hand)}"
    # 元手札 (OP01-013) はデッキ下へ戻り、 上から別カード (OP01-016) を引く。
    assert all(c.card_id == "OP01-016" for c in me.hand), \
        "デッキ上から引き直されていない (手札が入れ替わっていない)"


# --------------------------------------------------------------------------- #
#  OP04-049 ジャック (CHARACTER 青 cost2):
#    【KO時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op04_049_on_ko_draw_ai():
    """【KO時】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP04-049", "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-049"), sickness=False))
        _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"【KO時】カード1枚を引いていない: hand={len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP04-050 ハンガーさん (CHARACTER 青 cost2):
#    【起動メイン】自分の手札1枚を捨て、このキャラをレストにできる：カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op04_050_activate_main_draw_ai():
    """【起動メイン】(コスト後) カード1枚を引く (AI 自動、 do=draw を発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP04-050", "activate_main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-050"), sickness=False))
        _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"起動メインの draw が発火していない: hand={len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP04-051 フーズ・フー (CHARACTER 青 cost1):
#    【登場時】自分のデッキの上から5枚を見て、「フーズ・フー」以外の特徴《百獣海賊団》を
#      持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op04_051_on_play_search_hyakuju_ai():
    """【登場時】上5枚から《百獣海賊団》(フーズ・フー以外)1枚を手札に (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(HYOUKI)] + [repo.get("OP01-013")] * 10  # 氷鬼=百獣海賊団 top
    me.hand = []

    eff = _get_eff(overlay, "OP04-051", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-051"), sickness=False))
        _drain(st, [0])
    assert any(c.card_id == HYOUKI for c in me.hand), \
        "上5枚から《百獣海賊団》カードが手札に加わっていない"


def test_op04_051_on_play_no_search_when_only_self_name():
    """上5枚が「フーズ・フー」のみ (= exclude_name) なら手札に加わらない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 百獣海賊団 だが フーズ・フー (OP04-051) 自身のみ → 除外され対象なし。
    me.deck = [repo.get("OP04-051")] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = _get_eff(overlay, "OP04-051", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-051"), sickness=False))
        _drain(st, [0])
    assert not any(c.card_id == "OP04-051" for c in me.hand), \
        "「フーズ・フー」自身が exclude_name されず手札に加わっている"


def test_op04_051_on_play_human_search_modal():
    """人間: 上5枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(HYOUKI)] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = _get_eff(overlay, "OP04-051", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-051"), sickness=False))
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card_id == HYOUKI for c in me.hand), \
        "人間が選んだ《百獣海賊団》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-052 ブラックマリア (CHARACTER 青 cost3):
#    【起動メイン】➁，このキャラをレストにできる：カード1枚を引く。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op04_052_activate_main_draw_ai():
    """【起動メイン】(コスト後) カード1枚を引く (AI 自動、 do=draw を発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP04-052", "activate_main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-052"), sickness=False))
        _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"起動メインの draw が発火していない: hand={len(me.hand)}"


def test_op04_052_trigger_play_self_ai():
    """【トリガー】このカードを登場させる (AI 自動、 探索元はトラッシュ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP04-052")]
    st.current_source_card_id = "OP04-052"

    eff = _get_eff(overlay, "OP04-052", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-052"), sickness=True))
    assert any(c.card.card_id == "OP04-052" for c in me.characters), \
        "トリガーで自身が登場していない"


# --------------------------------------------------------------------------- #
#  OP04-055 疫災弾 (EVENT 青 cost2):
#    【メイン】自分の手札から「氷鬼」1枚を捨て、コスト4以下のキャラ1枚を、持ち主の
#      デッキの下に置くことができる：自分のトラッシュから「氷鬼」1枚を登場させる。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op04_055_main_optional_cost_play_hyouki_ai():
    """【メイン】氷鬼捨て + コスト4以下キャラをデッキ下 → トラッシュから氷鬼登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(HYOUKI)]           # 捨てる用 氷鬼
    me.trash = [repo.get(HYOUKI)]          # 登場させる用 氷鬼
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]
    opp.deck = []

    eff = _get_eff(overlay, "OP04-055", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get(EKISAIDAN), sickness=False))
        _drain(st, [0])
    assert any(c.card.card_id == HYOUKI for c in me.characters), \
        "トラッシュから「氷鬼」が登場していない"
    assert victim not in opp.characters, \
        "コスト4以下キャラが持ち主のデッキ下に置かれていない"


def test_op04_055_main_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で氷鬼登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(HYOUKI)]
    me.trash = [repo.get(HYOUKI)]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]
    opp.deck = []

    eff = _get_eff(overlay, "OP04-055", "main")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get(EKISAIDAN), sickness=False))
    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert any(c.card.card_id == HYOUKI for c in me.characters), \
        "人間承諾後 「氷鬼」が登場していない"


def test_op04_055_trigger_fires_main():
    """【トリガー】fire_self_effect で【メイン】効果 (氷鬼登場) が発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(HYOUKI)]
    me.trash = [repo.get(HYOUKI)]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]
    opp.deck = []
    st.current_source_card_id = EKISAIDAN

    eff = _get_eff(overlay, "OP04-055", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get(EKISAIDAN), sickness=False))
        _drain(st, [0])
    assert any(c.card.card_id == HYOUKI for c in me.characters), \
        "トリガー経由で【メイン】効果 (氷鬼登場) が発動していない"


# --------------------------------------------------------------------------- #
#  OP04-056 ゴムゴムの業火拳銃 (EVENT 青 cost6):
#    【メイン】キャラ1枚までを、持ち主のデッキの下に置く。
#    【トリガー】コスト4以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op04_056_main_return_chara_ai():
    """【メイン】相手キャラ1枚を持ち主のデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP04-034"), sickness=False)  # cost4 キャラ
    opp.characters = [victim]
    opp.deck = []

    eff = _get_eff(overlay, "OP04-056", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-056"), sickness=False))
        _drain(st, [0])
    assert victim not in opp.characters, \
        "相手キャラが場から戻されていない"
    assert any(c.card_id == "OP04-034" for c in opp.deck), \
        "戻したキャラが持ち主のデッキに置かれていない"


def test_op04_056_trigger_return_cost_le_4_ai():
    """【トリガー】相手のコスト4以下キャラ1枚を持ち主のデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]
    opp.deck = []

    eff = _get_eff(overlay, "OP04-056", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-056"), sickness=False))
        _drain(st, [0])
    assert victim not in opp.characters, \
        "相手のコスト4以下キャラが場から戻されていない"


def test_op04_056_main_human_target_pick():
    """人間 actor: 戻す対象の target_pick modal が立ち、 解決で1枚デッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get("OP04-034"), sickness=False)
    v2 = InPlay.of(repo.get("OP04-034"), sickness=False)  # 複数候補で modal
    opp.characters = [v1, v2]

    eff = _get_eff(overlay, "OP04-056", "main")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-056"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert len(opp.characters) == 1, "人間選択後 相手キャラ1枚が場から戻されていない"
