# -*- coding: utf-8 -*-
"""OP12 弾 (黒 革命軍 / SMILE / 黄 サボ 系) 効果 回帰テスト
バックフィル (自動生成 wave 123):
OP12-089 / OP12-090 / OP12-091 / OP12-093 / OP12-094 /
OP12-095 / OP12-096 / OP12-097 / OP12-098 / OP12-100 の 10 枚。

目的 (= test_backfill_auto_001〜122.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)

⚠ overlay 不備メモ (= engine/overlay は本タスクでは編集せず、 人間レビューへ回す):
  - OP12-096 / OP12-098 の【トリガー】は公式では「カード1枚を引き、デッキ上1枚をトラッシュ」
    だが overlay の trigger do は {"mill_self_top": 1} のみで **draw が欠落**。 → 該当
    トリガーのテストは @pytest.mark.skip で理由明記 (main / counter の主効果は忠実に検証)。
  - OP12-100 の静的「【ブロッカー】を得て、コスト+3」は overlay do に give_keyword のみで
    **set_base_cost +3 が欠落**。 → cost+3 のテストは skip で明記 (ブロッカー付与は検証)。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_attack,
    trigger_on_ko,
    trigger_on_play,
    trigger_counter_event,
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
_NEUTRAL = "OP01-001"       # ロロノア・ゾロ (赤、 革命軍でない汎用 leader)
_REVO_LEADER = "OP12-081"   # コアラ (黒/黄、 features ドレスローザ/革命軍)
_VICTIM = "OP01-016"        # ナミ (麦わらの一味 cost1 pow2000 CHARACTER)
_FILLER = "OP01-013"        # サンジ (麦わらの一味 cost2 pow3000 CHARACTER)
_BIG6 = "OP12-087"          # ニコ・ロビン (cost6 pow7000 CHARACTER)
_BIG8 = "EB04-003"          # スモーカー＆たしぎ (cost8 pow8000 CHARACTER)
_GINNY = "EB04-045"         # ジニー (黒 cost1 pow2000 CHARACTER, features 革命軍)
_SMILE = "EB01-024"         # ハムレット (cost3 pow4000, features 百獣海賊団/SMILE)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op12_wave123_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-089", "OP12-090", "OP12-091", "OP12-093", "OP12-094",
           "OP12-095", "OP12-096", "OP12-097", "OP12-098", "OP12-100"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-089 ハック (CHARACTER 黒 cost4 pow5000):
#    静的: 革命軍 leader なら【ブロッカー】+コスト+4。
#    【KO時】革命軍 leader なら 相手の元々コスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op12_089_on_ko_ko_cost_le_4_ai():
    """【KO時】 革命軍 leader → 相手コスト4以下キャラを KO、 コスト6は残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REVO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    small = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=4)
    big = InPlay.of(repo.get(_BIG6), sickness=False)       # cost6 (対象外)
    opp.characters = [small, big]

    trigger_on_ko(st, me, opp, repo.get("OP12-089"), overlay)
    _drain(st)

    assert small not in opp.characters, "コスト4以下の相手キャラが KO されていない"
    assert big in opp.characters, "コスト6の相手キャラは KO 対象外で残るべき"


def test_op12_089_on_ko_no_ko_when_not_revolutionary():
    """負例: 非革命軍 leader なら【KO時】の KO が発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    small = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [small]

    trigger_on_ko(st, me, opp, repo.get("OP12-089"), overlay)
    _drain(st)

    assert small in opp.characters, "非革命軍 leader で KO が発火してはいけない"


def test_op12_089_on_ko_human_pick():
    """人間 + コスト4以下の相手キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REVO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [a, b]

    trigger_on_ko(st, me, opp, repo.get("OP12-089"), overlay)

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


def test_op12_089_static_blocker_and_cost_plus4_when_revolutionary():
    """静的: 革命軍 leader → ブロッカー付与 + コスト 4→8。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REVO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    hack_def = repo.get("OP12-089")
    hack = InPlay.of(hack_def, sickness=False)
    me.characters = [hack]

    evaluate_static_effects(st, overlay)
    assert hack.is_blocker_now, "革命軍 leader で【ブロッカー】が付与されていない"
    assert hack.base_cost == hack_def.cost + 4, \
        f"革命軍 leader で cost+4 されていない: {hack.base_cost} (base {hack_def.cost})"


def test_op12_089_static_no_buff_when_not_revolutionary():
    """負例: 非革命軍 leader → ブロッカーも cost+4 も付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    hack_def = repo.get("OP12-089")
    hack = InPlay.of(hack_def, sickness=False)
    me.characters = [hack]

    evaluate_static_effects(st, overlay)
    assert not hack.is_blocker_now, "非革命軍 leader でブロッカーが付いてはいけない"
    assert hack.base_cost == hack_def.cost, "非革命軍 leader で cost が変わってはいけない"


# --------------------------------------------------------------------------- #
#  OP12-090 ベロ・ベティ (CHARACTER 黒 cost3 pow4000):
#    【アタック時】自分のデッキ上2枚をトラッシュに置ける (任意コスト)：
#      相手のキャラ1枚まで、このターン中、コスト-2。
# --------------------------------------------------------------------------- #
def test_op12_090_on_attack_optional_cost_human():
    """人間: アタック時 任意コスト → optional_cost_confirm → 承諾で mill2 + 相手 cost-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get("OP12-090"), sickness=False)
    me.characters = [atk]
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []
    victim = InPlay.of(repo.get(_BIG6), sickness=False)  # cost6
    opp.characters = [victim]

    deck_before = len(me.deck)
    cost_before = victim.base_cost
    trigger_on_attack(st, me, opp, atk, overlay)

    assert st.pending_choice is not None, "人間のアタック時 任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)  # 承諾 → mill2 → (単一候補) 相手 cost-2

    assert len(me.trash) == 2, f"コストでデッキ上2枚がトラッシュされていない: {len(me.trash)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減るべき"
    assert victim.base_cost == cost_before - 2, \
        f"相手キャラの cost-2 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op12_090_on_attack_ai_no_crash():
    """AI 文脈: アタック時 効果を回しても crash しない (自動解決)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    atk = InPlay.of(repo.get("OP12-090"), sickness=False)
    me.characters = [atk]
    me.deck = [repo.get(_FILLER)] * 10
    opp.characters = [InPlay.of(repo.get(_BIG6), sickness=False)]

    trigger_on_attack(st, me, opp, atk, overlay)
    _drain(st)
    assert st.pending_choice is None, "AI 文脈で pending_choice が残ってはいけない"


# --------------------------------------------------------------------------- #
#  OP12-091 ポーカー (CHARACTER 黒 cost3 pow4000, features SMILE):
#    【起動メイン】【ターン1回】自分のトラッシュからカード3枚をデッキの下に置ける (任意コスト)：
#      自分の特徴《SMILE》を持つキャラ2枚まで、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op12_091_activate_main_pump_smile_human():
    """人間 起動メイン: 任意コスト承諾 → 自 SMILE キャラ2枚まで +2000。"""
    from engine.effects import list_activate_main_effects, fire_activate_main
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    poker = InPlay.of(repo.get("OP12-091"), sickness=False)   # 自身 SMILE
    hamlet = InPlay.of(repo.get(_SMILE), sickness=False)      # SMILE
    me.characters = [poker, hamlet]
    me.trash = [repo.get(_FILLER)] * 3   # コスト (トラッシュ3枚)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-091"]
    assert len(opts) == 1, \
        f"OP12-091 の起動メインが legal に出ない: {len(opts)}"
    # baseline は静的効果 (他 SMILE キャラの常在バフ等) を反映した後で取り、
    # power_pump 分 (+2000) の差分だけを検証する。
    evaluate_static_effects(st, overlay)
    poker_before = poker.power
    hamlet_before = hamlet.power
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)

    assert poker.power == poker_before + 2000, \
        f"ポーカー (SMILE) に +2000 されていない: {poker.power}"
    assert hamlet.power == hamlet_before + 2000, \
        f"ハムレット (SMILE) に +2000 されていない: {hamlet.power}"
    assert len(me.trash) == 0, "コストでトラッシュ3枚がデッキ下に置かれるべき"


def test_op12_091_activate_main_ai_no_crash():
    """AI 起動メイン: crash せず自動解決 (トラッシュ3枚あり)。"""
    from engine.effects import list_activate_main_effects, fire_activate_main
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    poker = InPlay.of(repo.get("OP12-091"), sickness=False)
    me.characters = [poker]
    me.trash = [repo.get(_FILLER)] * 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-091"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert st.pending_choice is None, "AI 文脈で pending_choice が残ってはいけない"


# --------------------------------------------------------------------------- #
#  OP12-093 モーリー (CHARACTER 黒 cost4 pow5000):
#    静的: 革命軍 leader なら このキャラのコスト+4。
# --------------------------------------------------------------------------- #
def test_op12_093_static_cost_plus4_when_revolutionary():
    """静的: 革命軍 leader → コスト 4→8。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REVO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    morley_def = repo.get("OP12-093")
    morley = InPlay.of(morley_def, sickness=False)
    me.characters = [morley]

    evaluate_static_effects(st, overlay)
    assert morley.base_cost == morley_def.cost + 4, \
        f"革命軍 leader で cost+4 されていない: {morley.base_cost}"


def test_op12_093_static_no_cost_when_not_revolutionary():
    """負例: 非革命軍 leader → cost は変わらない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    morley_def = repo.get("OP12-093")
    morley = InPlay.of(morley_def, sickness=False)
    me.characters = [morley]

    evaluate_static_effects(st, overlay)
    assert morley.base_cost == morley_def.cost, \
        "非革命軍 leader で cost が変わってはいけない"


# --------------------------------------------------------------------------- #
#  OP12-094 モンキー・Ｄ・ドラゴン (CHARACTER 黒 cost8 pow8000):
#    【登場時】自分のトラッシュから特徴《革命軍》カード3枚をデッキ下に置ける (任意コスト)：
#      革命軍 leader なら 自トラッシュからコスト6以下のキャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op12_094_on_play_play_from_trash_ai():
    """【登場時】 革命軍 leader → 革命軍3枚デッキ下 (コスト) → トラッシュから登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REVO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-094"), sickness=True)
    me.characters = [src]
    # 革命軍 (ジニー) を 4 枚: 3 枚 = コストでデッキ下、 残り 1 枚 = 登場対象
    me.trash = [repo.get(_GINNY)] * 4
    me.deck = [repo.get(_FILLER)] * 10

    chara_before = len(me.characters)
    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    ginny_in_play = [c for c in me.characters if c.card.card_id == _GINNY]
    assert len(ginny_in_play) == 1, \
        f"トラッシュから革命軍キャラが登場していない: {[c.card_id for c in me.characters]}"
    assert len(me.characters) == chara_before + 1, "キャラが1枚増えるべき"


def test_op12_094_on_play_human_optional_cost():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REVO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-094"), sickness=True)
    me.characters = [src]
    me.trash = [repo.get(_GINNY)] * 4
    me.deck = [repo.get(_FILLER)] * 10

    trigger_on_play(st, me, opp, src, overlay)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)
    assert any(c.card.card_id == _GINNY for c in me.characters), \
        "人間承諾後 トラッシュから革命軍キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP12-095 リンドバーグ (CHARACTER 黒 cost4 pow5000):
#    静的: 革命軍 leader なら このキャラのコスト+4。
#    【登場時】カード1枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op12_095_on_play_draw_then_discard_ai():
    """【登場時】 1 ドロー → 手札1枚を捨てる (deck-1 / trash+1 / hand=0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-095"), sickness=True)
    me.characters = [src]
    me.hand = []
    me.trash = []
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert len(me.deck) == deck_before - 1, "登場時に 1 ドローされていない"
    assert len(me.trash) == 1, "捨てた 1 枚がトラッシュに置かれていない"
    assert len(me.hand) == 0, "引いた1枚を捨てた後 手札は 0 のはず"


def test_op12_095_static_cost_plus4_when_revolutionary():
    """静的: 革命軍 leader → コスト 4→8。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REVO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    lind_def = repo.get("OP12-095")
    lind = InPlay.of(lind_def, sickness=False)
    me.characters = [lind]

    evaluate_static_effects(st, overlay)
    assert lind.base_cost == lind_def.cost + 4, \
        f"革命軍 leader で cost+4 されていない: {lind.base_cost}"


# --------------------------------------------------------------------------- #
#  OP12-096 熊の衝撃 (EVENT 黒 cost4):
#    【メイン】相手コスト4以下1枚KO。 自コスト8以上のキャラがいれば コスト6以下を代わりに選ぶ。
# --------------------------------------------------------------------------- #
def test_op12_096_main_ko_cost_le_4_default():
    """【メイン】 自コスト8以上なし → コスト4以下KO (cost6 は対象外で残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_BIG6), sickness=False)  # cost6
    opp.characters = [big]

    do, _ = _do(overlay, "OP12-096", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert big in opp.characters, "自コスト8以上不在なら cost6 は KO 対象外で残るべき"


def test_op12_096_main_ko_cost_le_6_when_have_cost8():
    """【メイン】 自コスト8以上あり → コスト6以下KO (cost6 を KO できる)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_BIG8), sickness=False)]  # 自 cost8
    big = InPlay.of(repo.get(_BIG6), sickness=False)              # 相手 cost6
    opp.characters = [big]

    do, _ = _do(overlay, "OP12-096", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert big not in opp.characters, "自コスト8以上ありなら cost6 を KO できるべき"


def test_op12_096_main_ko_human_pick():
    """人間 + 自コスト8以上あり + 相手コスト6以下複数 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_BIG8), sickness=False)]  # 自 cost8
    a = InPlay.of(repo.get(_BIG6), sickness=False)   # cost6
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP12-096", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだキャラが KO されていない"
    assert b in opp.characters, "選ばなかったキャラは残るべき"


@pytest.mark.skip(reason="overlay 不備: OP12-096【トリガー】は公式で draw1+mill1 だが "
                         "overlay trigger do は {mill_self_top:1} のみで draw が欠落。 "
                         "engine/overlay 修正は人間レビューへ (本タスクでは data 編集しない)。")
def test_op12_096_trigger_draw_and_mill():
    """【トリガー】カード1枚を引き、デッキ上1枚をトラッシュ (現 overlay では draw 未実装)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []
    do, _ = _do(overlay, "OP12-096", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, "トリガーで 1 ドローされるべき"


# --------------------------------------------------------------------------- #
#  OP12-097 軍隊長集結 (EVENT 黒 cost1):
#    【メイン】デッキ上3枚を見て「軍隊長集結」以外の特徴《革命軍》1枚まで公開手札、 残りトラッシュ。
# --------------------------------------------------------------------------- #
def test_op12_097_main_search_revolutionary_ai():
    """【メイン】 デッキ上3枚から 革命軍カード (ジニー) を手札 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_GINNY), repo.get(_FILLER), repo.get(_VICTIM)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []
    me.trash = []

    do, _ = _do(overlay, "OP12-097", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert any(c.card_id == _GINNY for c in me.hand), \
        f"革命軍カード (ジニー) が手札に加わっていない: {[c.card_id for c in me.hand]}"
    assert len(me.trash) == 2, "見た3枚のうち手札1枚以外はトラッシュに置かれるべき"


def test_op12_097_main_search_human_modal():
    """人間 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_GINNY), repo.get(_FILLER), repo.get(_VICTIM)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    do, _ = _do(overlay, "OP12-097", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _GINNY for c in me.hand), \
        "人間が選んだ革命軍カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-098 夢打撃処裏拳 (EVENT 黒 cost1):
#    【カウンター】自分のリーダーかキャラ1枚まで、このバトル中、パワー+2000。
#      その後、自コスト8以上の革命軍キャラがいれば そのカードを更に +2000。
# --------------------------------------------------------------------------- #
def test_op12_098_counter_pump_ai():
    """【カウンター】 AI: 自リーダーかキャラに このバトル +2000 (既定=リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    trigger_counter_event(st, me, opp, repo.get("OP12-098"), overlay)
    _drain(st)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op12_098_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP12-098", "counter")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st)
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


@pytest.mark.skip(reason="overlay 不備: OP12-098【トリガー】は公式で draw1+mill1 だが "
                         "overlay trigger do は {mill_self_top:1} のみで draw が欠落。 "
                         "engine/overlay 修正は人間レビューへ (本タスクでは data 編集しない)。")
def test_op12_098_trigger_draw_and_mill():
    """【トリガー】カード1枚を引き、デッキ上1枚をトラッシュ (現 overlay では draw 未実装)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []
    do, _ = _do(overlay, "OP12-098", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, "トリガーで 1 ドローされるべき"


# --------------------------------------------------------------------------- #
#  OP12-100 サボ (CHARACTER 黄 cost5 pow6000):
#    静的: 自ライフ3枚以下なら【ブロッカー】を得て、コスト+3。
#    【登場時】自ライフ上1枚を手札に加えられる (任意コスト)：カード2枚を引き、手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op12_100_on_play_life_to_hand_draw2_discard_ai():
    """【登場時】 AI: 任意コスト (ライフ上1枚手札) → 2ドロー + 手札1枚捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-100"), sickness=True)
    me.characters = [src]
    me.life = [repo.get(_FILLER)] * 4
    me.hand = []
    me.trash = []
    me.deck = [repo.get(_FILLER)] * 10

    life_before = len(me.life)
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    # 任意コストを AI が支払った場合: life-1 / (手札+1)+(draw2)-(discard1) = hand+2 / trash+1
    if len(me.life) == life_before - 1:
        assert len(me.deck) == deck_before - 2, "2ドローされていない"
        assert len(me.hand) == 2, \
            f"ライフ1枚+2ドロー-1捨て = 手札2枚のはず: {len(me.hand)}"
        assert len(me.trash) == 1, "捨てた1枚がトラッシュに置かれていない"
    else:
        # AI が任意コストを見送った場合も crash しないことのみ担保
        assert st.pending_choice is None, "pending_choice が残ってはいけない"


def test_op12_100_on_play_human_optional_cost():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で 2ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-100"), sickness=True)
    me.characters = [src]
    me.life = [repo.get(_FILLER)] * 4
    me.hand = []
    me.trash = []
    me.deck = [repo.get(_FILLER)] * 10

    life_before = len(me.life)
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)  # 承諾

    assert len(me.life) == life_before - 1, "コストで自ライフ上1枚が手札に加わるべき"
    assert len(me.deck) == deck_before - 2, "承諾で 2 ドローされていない"
    assert len(me.hand) == 2, f"ライフ1枚+2ドロー-1捨て = 手札2枚のはず: {len(me.hand)}"


def test_op12_100_static_blocker_when_life_le_3():
    """静的: 自ライフ3枚以下 → ブロッカー付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("OP12-100"), sickness=False)
    me.characters = [sabo]
    me.life = [repo.get(_FILLER)] * 3   # 3枚以下 = 条件成立

    evaluate_static_effects(st, overlay)
    assert sabo.is_blocker_now, "自ライフ3枚以下で【ブロッカー】が付与されていない"


def test_op12_100_static_no_blocker_when_life_high():
    """負例: 自ライフ4枚 → ブロッカーは付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("OP12-100"), sickness=False)
    me.characters = [sabo]
    me.life = [repo.get(_FILLER)] * 4   # 4枚 = 条件不成立

    evaluate_static_effects(st, overlay)
    assert not sabo.is_blocker_now, "ライフ4枚でブロッカーが付いてはいけない"


@pytest.mark.skip(reason="overlay 不備: OP12-100 静的は公式で「ブロッカーを得て、コスト+3」だが "
                         "overlay do は give_keyword のみで set_base_cost +3 が欠落。 "
                         "engine/overlay 修正は人間レビューへ (本タスクでは data 編集しない)。")
def test_op12_100_static_cost_plus3_when_life_le_3():
    """静的: 自ライフ3枚以下 → コスト+3 (現 overlay では未実装)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    sabo_def = repo.get("OP12-100")
    sabo = InPlay.of(sabo_def, sickness=False)
    me.characters = [sabo]
    me.life = [repo.get(_FILLER)] * 3

    evaluate_static_effects(st, overlay)
    assert sabo.base_cost == sabo_def.cost + 3, "自ライフ3枚以下で cost+3 されるべき"
