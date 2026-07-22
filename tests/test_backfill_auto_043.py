# -*- coding: utf-8 -*-
"""OP03 弾 (黄 ビッグ・マム海賊団) 効果 回帰テスト バックフィル (自動生成 wave 043):
OP03-109 / OP03-110 / OP03-112 / OP03-113 / OP03-114 / OP03-115 /
OP03-116 / OP03-117 / OP03-118 / OP03-119 の 10 枚。

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


def _bm_feature_char_id(repo):
    """特徴《ビッグ・マム海賊団》を持つ CHARACTER (パラレル/レア除外) を1つ返す。"""
    for c in repo._by_id.values():
        if c.category.name == "CHARACTER" \
                and "ビッグ・マム海賊団" in (c.features or []) \
                and "_p" not in c.card_id and "_r" not in c.card_id \
                and c.name not in ("シャーロット・プリン", "シャーロット・ペロスペロー"):
            return c.card_id
    raise AssertionError("BM 特徴キャラが見つからない")


def _trigger_char_cost_le4_id(repo):
    """【トリガー】を持つ コスト4以下 CHARACTER を1つ返す。"""
    for c in repo._by_id.values():
        if c.category.name == "CHARACTER" and (getattr(c, "trigger", "") or "").strip() \
                and "_p" not in c.card_id and "_r" not in c.card_id:
            try:
                if int(c.cost) <= 4:
                    return c.card_id
            except (TypeError, ValueError):
                continue
    raise AssertionError("トリガー持ちコスト4以下キャラが見つからない")


def _trigger_card_id(repo):
    for c in repo._by_id.values():
        if (getattr(c, "trigger", "") or "").strip() and "_p" not in c.card_id \
                and "_r" not in c.card_id:
            return c.card_id
    raise AssertionError("トリガー持ちカードが見つからない")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op03_wave43_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-109", "OP03-110", "OP03-112", "OP03-113", "OP03-114",
           "OP03-115", "OP03-116", "OP03-117", "OP03-118", "OP03-119"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-109 シャーロット・シフォン (CHARACTER 黄 cost2):
#    【登場時】自分のライフの上か下から1枚をトラッシュに置くことができる：
#      自分のデッキの上から1枚までを、 ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op03_109_on_play_life_swap_ai():
    """【登場時】(任意) ライフ1→トラッシュ + デッキ上1→ライフ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    life_before = len(me.life)
    trash_before = len(me.trash)
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-109", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-109"), sickness=True))

    # ライフ1枚トラッシュ (-1) → デッキ上1枚をライフへ (+1) = ライフ枚数不変
    assert len(me.life) == life_before, f"ライフ枚数が不変でない: {len(me.life)}"
    assert len(me.trash) == trash_before + 1, "トラッシュにライフ1枚が置かれていない"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフへ動いていない"


def test_op03_109_on_play_no_life_no_effect():
    """自ライフが無ければ 任意コスト不能 → デッキは減らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-109", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-109"), sickness=True))

    assert len(me.deck) == deck_before, "ライフが無いのにデッキが減っている"


def test_op03_109_on_play_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-109", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-109"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "人間承諾後 デッキ上1枚がライフへ動いていない"


# --------------------------------------------------------------------------- #
#  OP03-110 シャーロット・スムージー (CHARACTER 黄 cost4):
#    【アタック時】自分のライフの上か下から1枚を手札に加えることができる：
#      このキャラは、 このバトル中、 パワー+2000。
#    【トリガー】自分の手札1枚を捨てることができる：このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op03_110_on_attack_life_to_hand_pump_ai():
    """【アタック時】(任意) ライフ1→手札 → 自身 +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    attacker = InPlay.of(repo.get("OP03-110"), sickness=False)
    me.characters = [attacker]
    hand_before = len(me.hand)
    life_before = len(me.life)
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP03-110", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert len(me.hand) == hand_before + 1, "ライフ1枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "ライフが1枚減っていない"
    assert attacker.power == power_before + 2000, \
        f"自身 +2000 が反映されていない: {attacker.power} (before {power_before})"


def test_op03_110_trigger_play_self_ai():
    """【トリガー】手札1捨て → 自身を登場 (AI 自動、 探索元はトラッシュ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-110")]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト (別カード)
    st.current_source_card_id = "OP03-110"

    on_trig = _get_eff(overlay, "OP03-110", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-110"), sickness=True))

    assert any(c.card.card_id == "OP03-110" for c in me.characters), \
        "トリガーで自身が登場していない"
    assert len(me.hand) == 0, "コストで手札1枚が捨てられていない"


def test_op03_110_on_attack_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    attacker = InPlay.of(repo.get("OP03-110"), sickness=False)
    me.characters = [attacker]
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP03-110", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert attacker.power == power_before + 2000, "人間承諾後 +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP03-112 シャーロット・プリン (CHARACTER 黄 cost1):
#    【登場時】自分のデッキの上から4枚を見て、「シャーロット・プリン」以外の
#      特徴《ビッグ・マム海賊団》を持つカードか「サンジ」1枚までを公開し、
#      手札に加える。 その後、 残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op03_112_on_play_search_bm_ai():
    """【登場時】デッキ上4枚から BM 特徴キャラを手札へ、 残りは下 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bm_id = _bm_feature_char_id(repo)
    me.deck = [repo.get(bm_id)] + [repo.get("OP01-013")] * 10  # 先頭に BM 特徴
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-112", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-112"), sickness=True))

    assert any(c.card_id == bm_id for c in me.hand), \
        "デッキ上4枚から BM 特徴キャラが手札に加わっていない"
    # 4枚公開 → 1枚手札 / 残り3枚は下 = デッキ -1
    assert len(me.deck) == deck_before - 1, \
        f"手札1枚分だけデッキが減っていない: {len(me.deck)}"


def test_op03_112_on_play_human_search_modal():
    """人間 actor: 上4枚を公開して選ばせる search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bm_id = _bm_feature_char_id(repo)
    me.deck = [repo.get(bm_id)] + [repo.get("OP01-013")] * 10

    on_play = _get_eff(overlay, "OP03-112", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-112"), sickness=True))

    assert st.pending_choice is not None, "人間 + BM候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _drain(st, [0])  # 解決できること (crash しない)


# --------------------------------------------------------------------------- #
#  OP03-113 シャーロット・ペロスペロー (CHARACTER 黄 cost3):
#    【KO時】自分のデッキの上から3枚を見て、 特徴《ビッグ・マム海賊団》を持つ
#      カード1枚までを公開し、 手札に加える。 その後、 残りを好きな順番でデッキの下に置く。
#    【トリガー】自分の手札1枚を捨てることができる：このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op03_113_on_ko_search_bm_ai():
    """【KO時】デッキ上3枚から BM 特徴カードを手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bm_id = _bm_feature_char_id(repo)
    me.deck = [repo.get(bm_id)] + [repo.get("OP01-013")] * 10
    deck_before = len(me.deck)

    on_ko = _get_eff(overlay, "OP03-113", "on_ko")
    for prim in on_ko["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-113"), sickness=True))

    assert any(c.card_id == bm_id for c in me.hand), \
        "デッキ上3枚から BM 特徴カードが手札に加わっていない"
    assert len(me.deck) == deck_before - 1, \
        f"手札1枚分だけデッキが減っていない: {len(me.deck)}"


def test_op03_113_trigger_play_self_ai():
    """【トリガー】手札1捨て → 自身を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-113")]
    me.hand = [repo.get("OP01-013")]
    st.current_source_card_id = "OP03-113"

    on_trig = _get_eff(overlay, "OP03-113", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-113"), sickness=True))

    assert any(c.card.card_id == "OP03-113" for c in me.characters), \
        "トリガーで自身が登場していない"
    assert len(me.hand) == 0, "コストで手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP03-114 シャーロット・リンリン (CHARACTER 黄 cost10):
#    【登場時】自分のリーダーが特徴《ビッグ・マム海賊団》を持つ場合、
#      自分のデッキの上から1枚までを、 ライフの上に加える。
#      その後、 相手のライフの上から1枚までを、 トラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op03_114_on_play_life_pump_and_mill_ai():
    """【登場時】(リーダー BM) デッキ上1→自ライフ + 相手ライフ1→トラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-077", overlay)  # リンリン (BM) リーダー
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    opp.life = [repo.get("OP01-013")] * 3
    my_life_before = len(me.life)
    my_deck_before = len(me.deck)
    opp_life_before = len(opp.life)
    opp_trash_before = len(opp.trash)

    on_play = _get_eff(overlay, "OP03-114", "on_play")
    assert on_play.get("if", {}).get("leader_feature") == "ビッグ・マム海賊団", \
        "overlay の リーダー特徴 BM 条件が無い"
    assert eval_condition(on_play["if"], st, me) is True, \
        "テスト前提: リーダーが BM で条件成立していない"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-114"), sickness=True))

    assert len(me.life) == my_life_before + 1, "自ライフが1枚増えていない"
    assert len(me.deck) == my_deck_before - 1, "デッキ上1枚がライフへ動いていない"
    assert len(opp.life) == opp_life_before - 1, "相手ライフが1枚減っていない"
    assert len(opp.trash) == opp_trash_before + 1, "相手ライフがトラッシュに置かれていない"


def test_op03_114_on_play_condition_false_non_bm_leader():
    """リーダーが《ビッグ・マム海賊団》を持たない場合、【登場時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (BM でない)
    me = st.players[0]
    on_play = _get_eff(overlay, "OP03-114", "on_play")
    assert eval_condition(on_play["if"], st, me) is False, \
        "リーダーが BM でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-115 シュトロイゼン (CHARACTER 黄 cost1):
#    【登場時】自分の手札から【トリガー】を持つカード1枚を捨てることができる：
#      相手のコスト1以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op03_115_on_play_discard_trigger_ko_ai():
    """【登場時】トリガー持ち手札1捨て → 相手コスト1以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_trigger_card_id(repo))]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=1)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-115", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-115"), sickness=True))

    assert len(me.hand) == 0, "トリガー持ち手札1枚がコストで捨てられていない"
    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"


def test_op03_115_on_play_no_trigger_card_no_ko():
    """手札にトリガー持ちが無ければ 任意コスト不能 → KO は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # トリガー無し (サンジ)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-115", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-115"), sickness=True))

    assert victim in opp.characters, \
        "トリガー持ちが無いのに KO が起きている (コスト未払いで発火してはならない)"


def test_op03_115_on_play_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_trigger_card_id(repo))]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-115", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-115"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert victim not in opp.characters, "人間承諾後 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP03-116 しらほし (CHARACTER 黄 cost5):
#    【登場時】カード3枚を引き、 自分の手札2枚を捨てる。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op03_116_on_play_draw3_discard2_ai():
    """【登場時】3ドロー + 手札2捨て (AI 自動、 差引 手札+1 / デッキ-3)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-116", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-116"), sickness=True))

    assert len(me.hand) == hand_before + 3 - 2, \
        f"3ドロー-2捨てで手札が+1でない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 3, f"3ドローでデッキが-3でない: {len(me.deck)}"


def test_op03_116_trigger_play_self_ai():
    """【トリガー】このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-116")]
    st.current_source_card_id = "OP03-116"
    chars_before = len(me.characters)

    on_trig = _get_eff(overlay, "OP03-116", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-116"), sickness=True))

    assert len(me.characters) == chars_before + 1, "トリガーで自身が登場していない"
    assert any(c.card.card_id == "OP03-116" for c in me.characters), \
        "登場したキャラが OP03-116 でない"


# --------------------------------------------------------------------------- #
#  OP03-117 ナポレオン (CHARACTER 黄 cost3):
#    【起動メイン】このキャラをレストにできる：自分の「シャーロット・リンリン」
#      1枚までを、 次の自分のターン開始時まで、 パワー+1000。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op03_117_activate_main_pump_linlin_ai():
    """【起動メイン】ナポレオンをレスト → リンリンを +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    napoleon = InPlay.of(repo.get("OP03-117"), sickness=False)
    linlin = InPlay.of(repo.get("OP03-114"), sickness=False)  # シャーロット・リンリン
    me.characters = [napoleon, linlin]
    power_before = linlin.power

    options = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in options if s.card.card_id == "OP03-117"]
    assert len(mine) == 1, f"OP03-117 の起動メインが legal に出ない: {len(mine)}"
    src, eff = mine[0]
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, [0])

    assert napoleon.rested is True, "起動コストでナポレオンがレストになっていない"
    assert linlin.power == power_before + 1000, \
        f"リンリンに +1000 が反映されていない: {linlin.power} (before {power_before})"


def test_op03_117_trigger_play_self_ai():
    """【トリガー】このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-117")]
    st.current_source_card_id = "OP03-117"
    chars_before = len(me.characters)

    on_trig = _get_eff(overlay, "OP03-117", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-117"), sickness=True))

    assert len(me.characters) == chars_before + 1, "トリガーで自身が登場していない"
    assert any(c.card.card_id == "OP03-117" for c in me.characters), \
        "登場したキャラが OP03-117 でない"


# --------------------------------------------------------------------------- #
#  OP03-118 威国 (EVENT 黄 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、 このバトル中、 パワー+5000。
#    【トリガー】自分の手札2枚を捨てることができる：自分のデッキの上から1枚までを、
#      ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op03_118_counter_pump_leader_ai():
    """【カウンター】自リーダーを このバトル中 パワー+5000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # target = 自リーダー
    power_before = me.leader.power

    on_counter = _get_eff(overlay, "OP03-118", "counter")
    for prim in on_counter["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert me.leader.power == power_before + 5000, \
        f"自リーダーに +5000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op03_118_trigger_discard2_put_life_ai():
    """【トリガー】(任意) 手札2捨て → デッキ上1→ライフ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016"), repo.get("OP01-013")]
    me.life = [repo.get("OP01-013")] * 2
    hand_before = len(me.hand)
    life_before = len(me.life)
    deck_before = len(me.deck)

    on_trig = _get_eff(overlay, "OP03-118", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-118"), sickness=True))

    assert len(me.hand) == hand_before - 2, f"手札2枚が捨てられていない: {len(me.hand)}"
    assert len(me.life) == life_before + 1, "デッキ上1枚がライフに加わっていない"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフへ動いていない"


def test_op03_118_trigger_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016"), repo.get("OP01-013")]
    me.life = [repo.get("OP01-013")] * 2
    deck_before = len(me.deck)

    on_trig = _get_eff(overlay, "OP03-118", "trigger")
    execute_effect(on_trig["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-118"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "人間承諾後 デッキ上1枚がライフへ動いていない"


# --------------------------------------------------------------------------- #
#  OP03-119 斬・切・餅 (EVENT 黄 cost2):
#    【メイン】自分のライフが相手より少ない場合、 相手のコスト4以下のキャラ1枚までを、 KOする。
#    【トリガー】自分の手札からコスト4以下の【トリガー】を持つキャラカード1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op03_119_main_ko_when_life_lt_opp_ai():
    """【メイン】(自ライフ<相手) 相手コスト4以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 1
    opp.life = [repo.get("OP01-013")] * 3
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4 (<=4)
    opp.characters = [victim]

    on_main = _get_eff(overlay, "OP03-119", "main")
    assert on_main.get("if", {}).get("self_life_lt_opp") is True, \
        "overlay の 自ライフ<相手 条件が無い"
    assert eval_condition(on_main["if"], st, me) is True, \
        "テスト前提: 自ライフ<相手 で条件成立していない"
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-119"), sickness=True))
        _drain(st, [0])

    assert victim not in opp.characters, "相手コスト4以下キャラが KO されていない"


def test_op03_119_main_condition_false_life_ge_opp():
    """自ライフが相手以上なら【メイン】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    opp.life = [repo.get("OP01-013")] * 1
    on_main = _get_eff(overlay, "OP03-119", "main")
    assert eval_condition(on_main["if"], st, me) is False, \
        "自ライフ>=相手なのに条件が成立している"


def test_op03_119_trigger_play_from_hand_ai():
    """【トリガー】手札からコスト4以下トリガー持ちキャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    trig_char = _trigger_char_cost_le4_id(repo)
    me.hand = [repo.get(trig_char)]
    chars_before = len(me.characters)

    on_trig = _get_eff(overlay, "OP03-119", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-119"), sickness=True))
        _drain(st, [0])

    assert len(me.characters) == chars_before + 1, \
        "手札からコスト4以下トリガー持ちキャラが登場していない"
    assert any(c.card.card_id == trig_char for c in me.characters), \
        "登場したキャラが想定 (トリガー持ち) でない"
