# -*- coding: utf-8 -*-
"""ST07 / ST08 弾 効果 回帰テスト バックフィル (自動生成 wave 171):
ST07-013 / ST07-015 / ST07-016 / ST07-017 / ST08-001 / ST08-002 /
ST08-004 / ST08-006 / ST08-007 / ST08-008 の 10 枚。

目的 (= test_backfill_auto_001〜170.py と同一方針):
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
    eval_all_conditions,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# 汎用 (効果の薄い) 埋めカード
_FILLER = "ST01-004"          # サンジ cost2 power4000 (バニラ気味)
_NEUTRAL_LEADER = "OP10-099"  # ユースタス・キッド (中立枠として利用)
_BM_LEADER = "ST07-001"       # シャーロット・リンリン (四皇/ビッグ・マム海賊団)
_LINLIN_CHARA = "ST07-010"    # シャーロット・リンリン (CHARACTER cost7)
_COST3_CHARA = "EB02-029"     # リュウ爺 (バニラ cost3 CHARACTER)


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
    """指定 card_id の overlay から when 一致の効果 dict を返す (needle で do 内絞り込み)。"""
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
def test_all_wave171_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST07-013", "ST07-015", "ST07-016", "ST07-017", "ST08-001",
           "ST08-002", "ST08-004", "ST08-006", "ST08-007", "ST08-008"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST07-013 プロメテウス (CHARACTER 黄 cost3):
#    【起動メイン】このキャラをレストにできる：自分の「シャーロット・リンリン」1枚までは
#      このターン中【ダブルアタック】を得る。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_st07_013_activate_main_grant_double_attack_to_linlin_ai():
    """起動メイン: 自レスト → 自分の「シャーロット・リンリン」に【ダブルアタック】付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)  # 非リンリンleader → 候補はキャラ1体のみ
    me, opp = st.players[0], st.players[1]
    prometheus = InPlay.of(repo.get("ST07-013"), sickness=False)
    linlin = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)
    me.characters = [prometheus, linlin]

    assert not linlin.has_keyword_active("ダブルアタック"), "前提: 付与前は ダブルアタック 無し"
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST07-013"]
    assert len(opts) == 1, f"ST07-013 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert linlin.has_keyword_active("ダブルアタック"), \
        "自分の「シャーロット・リンリン」に【ダブルアタック】が付与されていない"
    assert prometheus.rested is True, "起動メインコストで プロメテウス がレストされるべき"


def test_st07_013_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    prometheus = InPlay.of(repo.get("ST07-013"), sickness=False)
    linlin = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)
    me.characters = [prometheus, linlin]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST07-013"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST07-013"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_st07_013_activate_main_human_pick():
    """人間 + 「シャーロット・リンリン」複数 (リーダー+キャラ) → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay, human_idx=0)  # リーダーも シャーロット・リンリン
    me, opp = st.players[0], st.players[1]
    prometheus = InPlay.of(repo.get("ST07-013"), sickness=False)
    linlin = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)
    me.characters = [prometheus, linlin]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST07-013"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数「リンリン」候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    char_idx = next(i for i, c in enumerate(cands) if c["iid"] == linlin.instance_id)
    resolve_pending_choice(st, [char_idx])
    _drain(st, [0])
    assert linlin.has_keyword_active("ダブルアタック"), \
        "人間が選んだ「シャーロット・リンリン」に【ダブルアタック】が付与されていない"


# --------------------------------------------------------------------------- #
#  ST07-015 ソウル・ポーカス (EVENT 黄 cost5):
#    【メイン】相手は以下から1つを選ぶ。
#      ・相手のライフ上1枚をトラッシュに置く。 ・自デッキ上1枚をライフの上に加える。
# --------------------------------------------------------------------------- #
def test_st07_015_main_opp_choice_ai():
    """【メイン】相手 (opp=AI) が 2 択を自動解決。 いずれか一方のみが起きる:
    (A) 相手ライフ→トラッシュ (opp.life-1 / opp.trash+1)、 または
    (B) 自デッキ上→ライフ (me.deck-1 / me.life+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 2
    me.life = [repo.get(_FILLER)] * 2

    opp_life_before = len(opp.life)
    opp_trash_before = len(opp.trash)
    my_life_before = len(me.life)
    my_deck_before = len(me.deck)
    for prim in _eff(overlay, "ST07-015", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    opt_a = (len(opp.life) == opp_life_before - 1
             and len(opp.trash) == opp_trash_before + 1)
    opt_b = (len(me.life) == my_life_before + 1
             and len(me.deck) == my_deck_before - 1)
    assert opt_a != opt_b, \
        ("相手選択の 2 択の いずれか一方 のみが起きるべき "
         f"(A={opt_a}, B={opt_b})")
    # ⚠ actor=opp の choice_effect は engine 仕様上 常に AI が自動解決する
    #    (人間 modal を立てない = ST07-010 と同一設計、 effects.py の choice_effect 参照)。
    #    よって 人間 選択 modal のテストは 該当しない (= AI 自動解決のみ検証)。


# --------------------------------------------------------------------------- #
#  ST07-016 力餅 (EVENT 黄 cost1):
#    【カウンター】自か相手ライフ上1枚を見て上下に置く。 その後 自リーダーかキャラ1枚
#      このバトル中パワー+2000。
# --------------------------------------------------------------------------- #
def test_st07_016_counter_scry_and_pump_leader_ai():
    """【カウンター】scry_life (self_or_opp) の後、 自リーダーに +2000 (AI: 候補=リーダーのみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # 候補を リーダー のみ に絞る
    me.life = [repo.get(_FILLER)] * 2
    opp.life = [repo.get(_FILLER)] * 2

    power_before = me.leader.power
    life_before = len(me.life)
    for prim in _eff(overlay, "ST07-016", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.life) == life_before, "scry でライフ枚数が変わってはいけない"


# --------------------------------------------------------------------------- #
#  ST07-017 クイーン・ママ・シャンテ号 (STAGE 黄 cost2):
#    【起動メイン】このステージをレストにし、自ライフ上下1→手札できる：
#      自分のコスト3のキャラ1枚までを、持ち主のライフの上に表向きで加える。
# --------------------------------------------------------------------------- #
def test_st07_017_activate_main_chara_to_life_ai():
    """起動メイン: 任意コスト (ステージレスト + ライフ上1→手札) → コスト3キャラ1枚を自ライフへ。
    net: 対象キャラは場から消え me.life に移る。 ライフ枚数 = 復帰 (cost-1 + 効果+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("ST07-017"), sickness=False)
    me.stages = [stage]
    me.life = [repo.get(_FILLER)] * 2
    cost3 = InPlay.of(repo.get(_COST3_CHARA), sickness=False)  # cost3 キャラ
    me.characters = [cost3]

    life_before = len(me.life)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST07-017"]
    assert len(opts) == 1, f"ST07-017 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert stage.rested is True, "起動メインの任意コストでステージがレストされるべき"
    assert cost3 not in me.characters, "コスト3キャラが場から消えるべき (自ライフへ移動)"
    assert any(getattr(c, "card_id", None) == _COST3_CHARA for c in me.life), \
        "コスト3キャラが自ライフの上に加わっていない"
    assert len(me.life) == life_before, \
        f"ライフ枚数が復帰していない (cost-1 + 効果+1): {len(me.life)}"


# --------------------------------------------------------------------------- #
#  ST08-001 モンキー・D・ルフィ (LEADER 黒):
#    【自分のターン中】キャラがKOされた時、このリーダーにレストのドン!!1枚までを付与する。
# --------------------------------------------------------------------------- #
def test_st08_001_leader_ko_attach_rested_don_ai():
    """自ターン中、 キャラKO時: 自リーダーにレストドン1付与 (on_self / on_opp どちらも)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST08-001", overlay)  # 自身が ルフィ leader
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    for when in ("on_self_chara_ko", "on_opp_chara_ko"):
        eff = _eff(overlay, "ST08-001", when)
        assert eff.get("conditions", [{}])[0].get("self_turn") is True, \
            f"{when} の 自ターン条件 self_turn が無い"
        assert eval_all_conditions(eff, st, me, opp) is True, \
            f"自ターン中なら {when} 条件成立すべき"

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _eff(overlay, "ST08-001", "on_self_chara_ko")["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    assert me.leader.attached_dons == don_before + 1, \
        "キャラKO時に自リーダーへレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_st08_001_leader_ko_condition_off_turn():
    """相手ターン中は【自分のターン中】条件不成立 → 発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST08-001", overlay)
    st.turn_player_idx = 1  # 相手ターン → self_turn False
    me, opp = st.players[0], st.players[1]

    eff = _eff(overlay, "ST08-001", "on_self_chara_ko")
    assert eval_all_conditions(eff, st, me, opp) is False, \
        "相手ターン中は self_turn 条件が不成立のはず"


# --------------------------------------------------------------------------- #
#  ST08-002 ウタ (CHARACTER 黒 cost2):
#    このキャラはリーダーとのバトルでKOされない (static)。
#    【起動メイン】このキャラをレストにできる：相手のキャラ1枚まで このターン中コスト-2。
# --------------------------------------------------------------------------- #
def test_st08_002_static_ko_immune_vs_leader():
    """静的効果: リーダーとのバトルで KO されない (battle_ko_immune_vs_leader)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me = st.players[0]
    uta = InPlay.of(repo.get("ST08-002"), sickness=False)
    uta.attached_dons = 0  # on_attached_don n=0 static ゲート成立
    me.characters = [uta]

    assert uta.battle_ko_immune_vs_leader is False, "前提: 静的評価前は False"
    evaluate_static_effects(st, overlay)
    assert uta.battle_ko_immune_vs_leader is True, \
        "リーダーとのバトル KO 耐性 (静的) が付与されていない"


def test_st08_002_activate_main_cost_minus_ai():
    """起動メイン: 自レスト → 相手キャラ1枚を このターン中 コスト-2 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get("ST08-002"), sickness=False)
    me.characters = [uta]
    victim = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7
    opp.characters = [victim]

    cost_before = victim.base_cost
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST08-002"]
    assert len(opts) == 1, f"ST08-002 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert victim.base_cost == cost_before - 2, \
        f"起動メインの コスト-2 が反映されていない: {victim.base_cost} (before {cost_before})"
    assert uta.rested is True, "起動メインコストで ウタ がレストされるべき"


def test_st08_002_activate_main_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体を コスト-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get("ST08-002"), sickness=False)
    me.characters = [uta]
    a = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7
    b = InPlay.of(repo.get("OP01-016"), sickness=False)     # ナミ cost1
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST08-002"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.base_cost
    resolve_pending_choice(st, [a_idx])
    _drain(st, [0])
    assert a.base_cost == a_before - 2, "人間が選んだ相手キャラに コスト-2 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST08-004 コビー (CHARACTER 黒 cost4):
#    【起動メイン】このキャラをレストにできる：相手のコスト2以下のキャラ1枚を KO。
# --------------------------------------------------------------------------- #
def test_st08_004_activate_main_ko_cost2_ai():
    """起動メイン: 自レスト → 相手のコスト2以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    coby = InPlay.of(repo.get("ST08-004"), sickness=False)
    me.characters = [coby]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=2)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST08-004"]
    assert len(opts) == 1, f"ST08-004 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"
    assert coby.rested is True, "起動メインコストで コビー がレストされるべき"


def test_st08_004_activate_main_no_valid_target():
    """相手にコスト3以上のキャラしか居ない場合、 KO 対象外 (KO されない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    coby = InPlay.of(repo.get("ST08-004"), sickness=False)
    me.characters = [coby]
    big = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7 (>2)
    opp.characters = [big]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST08-004"]
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
        _drain(st, pick=[0])
    assert big in opp.characters, "コスト3以上のキャラが KO されてはいけない (対象外)"


def test_st08_004_activate_main_human_ko_pick():
    """人間 + 相手のコスト2以下キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    coby = InPlay.of(repo.get("ST08-004"), sickness=False)
    me.characters = [coby]
    a = InPlay.of(repo.get(_FILLER), sickness=False)      # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)   # ナミ cost1
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST08-004"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST08-006 しらほし (CHARACTER 黒 cost4):
#    【ブロッカー】【登場時】相手のキャラ1枚まで このターン中コスト-4。
# --------------------------------------------------------------------------- #
def test_st08_006_on_play_cost_minus_ai():
    """【登場時】相手キャラ1枚を このターン中 コスト-4 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _eff(overlay, "ST08-006", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST08-006"), sickness=True))
    _drain(st, [0])
    assert victim.base_cost == cost_before - 4, \
        f"登場時のコスト-4が反映されていない: {victim.base_cost} (before {cost_before})"


def test_st08_006_is_blocker():
    """【ブロッカー】が intrinsic に付いている (公式テキスト忠実)。"""
    repo = _repo()
    shirahoshi = InPlay.of(repo.get("ST08-006"), sickness=False)
    assert shirahoshi.is_blocker_now, "ST08-006 は【ブロッカー】を持つべき"


def test_st08_006_on_play_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体を コスト-4。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7
    b = InPlay.of(repo.get("OP01-013"), sickness=False)     # cost5
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST08-006", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST08-006"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.base_cost
    resolve_pending_choice(st, [a_idx])
    assert a.base_cost == a_before - 4, "人間が選んだ相手キャラに コスト-4 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST08-007 ネフェルタリ・ビビ (CHARACTER 黒 cost3):
#    【ブロッカー】。 overlay: 【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_st08_007_is_blocker():
    """【ブロッカー】が intrinsic に付いている (公式テキスト忠実)。"""
    repo = _repo()
    vivi = InPlay.of(repo.get("ST08-007"), sickness=False)
    assert vivi.is_blocker_now, "ST08-007 は【ブロッカー】を持つべき"


def test_st08_007_trigger_self_play_ai():
    """【トリガー】このカードを登場させる (AI)。 trash から場に出る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.trash = [repo.get("ST08-007")]
    st.current_source_card_id = "ST08-007"

    for prim in _eff(overlay, "ST08-007", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST08-007"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "ST08-007" for c in me.characters), \
        "トリガーで ネフェルタリ・ビビ が登場していない"


# --------------------------------------------------------------------------- #
#  ST08-008 ヒグマ (CHARACTER 黒 cost1):
#    【登場時】相手のキャラ1枚まで このターン中コスト-2。
# --------------------------------------------------------------------------- #
def test_st08_008_on_play_cost_minus_ai():
    """【登場時】相手キャラ1枚を このターン中 コスト-2 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _eff(overlay, "ST08-008", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST08-008"), sickness=True))
    _drain(st, [0])
    assert victim.base_cost == cost_before - 2, \
        f"登場時のコスト-2が反映されていない: {victim.base_cost} (before {cost_before})"


def test_st08_008_on_play_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体を コスト-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7
    b = InPlay.of(repo.get("OP01-013"), sickness=False)     # cost5
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST08-008", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST08-008"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    assert b.base_cost == b_before - 2, "人間が選んだ相手キャラに コスト-2 が反映されていない"
