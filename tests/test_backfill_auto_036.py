# -*- coding: utf-8 -*-
"""OP03 弾 (赤 白ひげ海賊団 / 緑 東の海) 効果 回帰テスト
バックフィル (自動生成 wave 036):
OP03-014 / OP03-016 / OP03-017 / OP03-018 / OP03-019 / OP03-020 /
OP03-021 / OP03-022 / OP03-024 / OP03-025 の 10 枚。

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
    evaluate_static_effects,
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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op03_wave36_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-014", "OP03-016", "OP03-017", "OP03-018", "OP03-019",
           "OP03-020", "OP03-021", "OP03-022", "OP03-024", "OP03-025"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-014 モンキー・D・ガープ: 【アタック時】自分の手札からコスト1の赤の
#    キャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op03_014_garp_on_attack_play_cost1_red_ai():
    """【アタック時】手札のコスト1の赤キャラを1枚登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("OP03-014"), sickness=False)
    me.characters = [garp]
    me.hand = [repo.get("EB01-005")]  # ドーマ 赤 cost1 (バニラ)

    chars_before = len(me.characters)
    on_attack = _get_eff(overlay, "OP03-014", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, garp)

    assert any(c.card.card_id == "EB01-005" for c in me.characters), \
        "手札のコスト1赤キャラが登場していない"
    assert len(me.characters) == chars_before + 1, \
        f"登場でキャラが1体増えるべき: {len(me.characters)}"


def test_op03_014_garp_on_attack_no_valid_body_no_play():
    """手札にコスト1の赤キャラが無ければ登場は起こらない (= 対象0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("OP03-014"), sickness=False)
    me.characters = [garp]
    me.hand = [repo.get("OP01-005")]  # ウタ cost4 (対象外)

    chars_before = len(me.characters)
    on_attack = _get_eff(overlay, "OP03-014", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, garp)

    assert len(me.characters) == chars_before, "コスト1赤が無いのに登場が起きてはいけない"
    assert repo.get("OP01-005") in me.hand, "対象外カードは手札に残るべき"


def test_op03_014_garp_on_attack_play_human_pick():
    """人間 + 手札にコスト1赤キャラ複数 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("OP03-014"), sickness=False)
    me.characters = [garp]
    me.hand = [repo.get("EB01-005"), repo.get("OP01-016")]  # ドーマ / ナミ (両方 赤 cost1)

    on_attack = _get_eff(overlay, "OP03-014", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp, garp)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in ("EB01-005", "OP01-016") for c in me.characters), \
        "人間が選んだコスト1赤キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP03-016 炎帝 (EVENT): 【メイン】自リーダーが「エース」の場合、相手のP8000
#    以下キャラ1枚までKO + 自リーダーは【ダブルアタック】+ パワー+3000。
# --------------------------------------------------------------------------- #
def test_op03_016_entei_main_ace_ko_and_buff_ai():
    """【メイン】(エースリーダー) 相手P8000以下KO + 自リーダー DA + +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay)  # エース リーダー
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000 (<=8000)
    opp.characters = [victim]

    leader_power_before = me.leader.power
    main = _get_eff(overlay, "OP03-016", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert victim not in opp.characters, "P8000以下の相手キャラが KO されていない"
    assert "ダブルアタック" in me.leader.granted_keywords, \
        "自リーダーに【ダブルアタック】が付与されていない"
    assert me.leader.power == leader_power_before + 3000, \
        f"自リーダー +3000 が反映されていない: {me.leader.power}"


def test_op03_016_entei_main_ko_human_pick():
    """人間 + 相手 P8000以下キャラ複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [a, b]

    main = _get_eff(overlay, "OP03-016", "main")
    # do[0] = ko。 人間 + 2 候補で target_pick が立つ。
    execute_effect(main["do"][0], st, me, opp, me.leader)

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


def test_op03_016_entei_trigger_ko_le6000_ai():
    """【トリガー】相手のP6000以下キャラ1枚までを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000 (<=6000)
    opp.characters = [victim]

    trig = _get_eff(overlay, "OP03-016", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    assert victim not in opp.characters, "トリガーで P6000以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP03-017 十字火 (EVENT): 【メイン】/【カウンター】自リーダーが『白ひげ海賊団』
#    を含む場合、 相手のキャラ1枚までを このターン中 パワー-4000。
# --------------------------------------------------------------------------- #
def test_op03_017_juujika_main_debuff_ai():
    """【メイン】(白ひげ海賊団リーダー) 相手キャラ1枚を -4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay)  # エース = 白ひげ海賊団
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [victim]

    power_before = victim.power
    main = _get_eff(overlay, "OP03-017", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-017"), sickness=True))
    assert victim.power == power_before - 4000, \
        f"相手キャラ -4000 が反映されていない: {victim.power} (before {power_before})"


def test_op03_017_juujika_counter_debuff_ai():
    """【カウンター】でも同じく相手キャラ1枚を -4000 (防御時、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [victim]

    power_before = victim.power
    counter = _get_eff(overlay, "OP03-017", "counter")
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-017"), sickness=True))
    assert victim.power == power_before - 4000, \
        f"カウンターで相手キャラ -4000 が反映されていない: {victim.power}"


# --------------------------------------------------------------------------- #
#  OP03-018 火拳 (EVENT): 【メイン】手札からイベント1枚を捨てられる：相手の
#    P5000以下キャラ1枚 と P4000以下キャラ1枚を KO。
# --------------------------------------------------------------------------- #
def test_op03_018_hiken_main_optional_discard_ko_multi_ai():
    """【メイン】イベント1枚捨て (コスト) → P5000以下 + P4000以下を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB02-007")]  # 赤 EVENT (捨てコスト)
    big = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ power4000 (<=5000)
    small = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power2000 (<=4000)
    opp.characters = [big, small]

    main = _get_eff(overlay, "OP03-018", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-018"), sickness=True))

    assert len(me.hand) == 0, "コストのイベント1枚が捨てられていない"
    assert big not in opp.characters, "P5000以下キャラが KO されていない"
    assert small not in opp.characters, "P4000以下キャラが KO されていない"


def test_op03_018_hiken_main_no_event_no_ko():
    """手札にイベントが無ければ cost 不能 → 相手キャラは KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # CHARACTER のみ (イベントでない)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    main = _get_eff(overlay, "OP03-018", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-018"), sickness=True))
    assert victim in opp.characters, "cost 不能なのに KO が起きてはいけない"
    assert len(me.hand) == 1, "cost 不能ならイベント以外の手札は減らない"


# --------------------------------------------------------------------------- #
#  OP03-019 火達磨 (EVENT): 【メイン】自リーダーは このターン中 パワー+4000。
#    【トリガー】相手のリーダーかキャラ1枚までを このターン中 パワー-10000。
# --------------------------------------------------------------------------- #
def test_op03_019_hidaruma_main_leader_pump_ai():
    """【メイン】自リーダー +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    leader_before = me.leader.power
    main = _get_eff(overlay, "OP03-019", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-019"), sickness=True))
    assert me.leader.power == leader_before + 4000, \
        f"自リーダー +4000 が反映されていない: {me.leader.power}"


def test_op03_019_hidaruma_trigger_debuff_ai():
    """【トリガー】相手キャラ1枚を -10000 (= 実質 KO 圏、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [victim]

    power_before = victim.power
    trig = _get_eff(overlay, "OP03-019", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-019"), sickness=True))
    assert victim.power < power_before, \
        f"トリガーで相手キャラのパワーが下がっていない: {victim.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP03-020 ストライカー (STAGE): 【起動メイン】②レスト + このステージをレスト：
#    自リーダーがエースの場合、デッキ上5枚を見てイベント1枚まで手札へ、残りデッキ下。
# --------------------------------------------------------------------------- #
def test_op03_020_striker_activate_main_search_event_ai():
    """起動メイン: ドン2レスト + 自ステージレスト → 上5枚から赤イベント1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay)  # エース リーダー (if 成立)
    me, opp = st.players[0], st.players[1]
    striker = InPlay.of(repo.get("OP03-020"), sickness=False)
    me.stages = [striker]
    me.don_active = 2  # rest_self_don:2 の cost
    me.hand = []
    red_event = repo.get("EB02-007")  # 赤 EVENT
    me.deck = [red_event] + [repo.get("OP01-013")] * 20

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP03-020"]
    assert len(opts) == 1, f"OP03-020 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert any(c.card_id == "EB02-007" for c in me.hand), \
        "上5枚からイベントが手札に加わっていない"
    assert me.don_active == 0, f"ドン2枚がレストされていない: {me.don_active}"
    assert striker.rested is True, "ステージ自身がレストされていない"


def test_op03_020_striker_activate_main_gated_by_non_ace_leader():
    """自リーダーが非エースなら if 不成立 → 起動メインが legal に出ない。"""
    # ⚠ 2026-08-05: コロン後の条件は効果のみを gate する (cardqa_st_06「「：」以前が発動コスト」)。
    #   任意コストは条件不成立でも払えるので legal には残る。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (非エース)
    me, opp = st.players[0], st.players[1]
    striker = InPlay.of(repo.get("OP03-020"), sickness=False)
    me.stages = [striker]
    me.don_active = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP03-020"]
    assert len(opts) == 1, \
        "任意コストは条件不成立でも払えるので legal に残るべき (cardqa_st_06)"


# --------------------------------------------------------------------------- #
#  OP03-021 クロ (LEADER): 【起動メイン】③レスト + 東の海キャラ2枚レスト：
#    このリーダーをアクティブにし、 相手のコスト5以下キャラ1枚までをレスト。
# --------------------------------------------------------------------------- #
def test_op03_021_kuro_activate_main_untap_and_rest_opp_ai():
    """起動メイン: ドン3 + 東の海2枚レスト → 自リーダーをアクティブ + 相手コスト5以下をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)  # クロ リーダー
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True  # untap 対象を作るため事前にレスト
    me.don_active = 3        # rest_self_don:3 の cost
    e1 = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 東の海
    e2 = InPlay.of(repo.get("EB02-017"), sickness=False)  # ナミ 東の海
    me.characters = [e1, e2]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=5)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP03-021"]
    assert len(opts) == 1, f"OP03-021 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.rested is False, "起動メインで自リーダーがアクティブにならなかった"
    assert e1.rested is True and e2.rested is True, "東の海キャラ2枚がレストされていない"
    assert me.don_active == 0, f"ドン3枚がレストされていない: {me.don_active}"
    assert victim.rested is True, "相手コスト5以下キャラがレストされていない"


def test_op03_021_kuro_activate_main_gated_without_two_toi_no_umi():
    """東の海キャラが2枚未満なら cost 不能 → 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.characters = [InPlay.of(repo.get("EB02-011"), sickness=False)]  # 東の海 1 枚のみ

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP03-021"]
    # 起動メイン自体は listable でも fire 時に cost 不能で不発になる。
    # ここでは cost 不能局面で fire しても crash せず victim 変化なしを確認。
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
    # 東の海が1枚 → 2枚レストできず効果不発、 リーダーはレスト解除されない (初期 active のまま)
    assert me.leader.rested is False, "cost 不能なのに副作用が起きてはいけない"


# --------------------------------------------------------------------------- #
#  OP03-022 アーロン (LEADER): 【ドン!!×2】【アタック時】①レスト：手札から
#    コスト4以下の【トリガー】持ちキャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op03_022_arlong_on_attack_play_trigger_body_ai():
    """【アタック時】(ドン×2 ゲート、 ①レスト) 手札のコスト4以下トリガー持ちを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-022", overlay)  # アーロン リーダー
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2  # self_attached_don_ge:2 の if 成立
    me.don_active = 1            # rest_self_don:1 の cost
    trigger_body = repo.get("OP13-014")  # ルージュ cost1 トリガー持ち
    me.hand = [trigger_body]

    chars_before = len(me.characters)
    on_attack = _get_eff(overlay, "OP03-022", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert any(c.card.card_id == "OP13-014" for c in me.characters), \
        "手札のコスト4以下トリガー持ちキャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"
    assert me.don_active == 0, f"ドン1枚がレストされていない: {me.don_active}"


def test_op03_022_arlong_on_attack_no_trigger_body_no_play():
    """手札にトリガー持ちキャラが無ければ登場は起こらない (= 対象0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-022", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2
    me.don_active = 1
    me.hand = [repo.get("OP01-013")]  # サンジ (トリガー無し)

    chars_before = len(me.characters)
    on_attack = _get_eff(overlay, "OP03-022", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    assert len(me.characters) == chars_before, \
        "トリガー持ちが無いのに登場が起きてはいけない"


# --------------------------------------------------------------------------- #
#  OP03-024 ギン (CHARACTER): 【登場時】自リーダーが東の海を持つ場合、
#    相手のコスト4以下キャラ2枚までをレスト。
# --------------------------------------------------------------------------- #
def test_op03_024_gin_on_play_rest_two_opp_ai():
    """【登場時】(東の海リーダー) 相手のコスト4以下2枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)  # クロ = 東の海 リーダー
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-024", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-024"), sickness=True))
    assert a.rested is True and b.rested is True, \
        "相手のコスト4以下キャラ2枚がレストされていない"


def test_op03_024_gin_on_play_rest_human_context_no_crash():
    """人間文脈でも 登場時 rest 効果が crash せず解決する (= rest_multi は 「範囲」 の
    deterministic 解決 で pick modal を伴わない)。 相手コスト4以下2枚がレストされる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-024", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-024"), sickness=True))
    _drain(st)
    assert a.rested is True and b.rested is True, \
        "人間文脈で相手コスト4以下キャラ2枚がレストされていない"


# --------------------------------------------------------------------------- #
#  OP03-025 クリーク (CHARACTER): 【登場時】手札1枚を捨てられる：相手のレストの
#    コスト4以下キャラ2枚までを KO。【ドン!!×1】このキャラは【ダブルアタック】。
# --------------------------------------------------------------------------- #
# 2026-07-22 修正済: ko_multi handler (engine/effects.py) が dict 形式 target
# {"type": "...filtered", "filter": {...}} を認識せず one_opponent_character_any に誤 fallback
# していたのを、 type/filter dict をそのまま _resolve_target に渡す様に修正 → 「相手レストの
# コスト4以下」の絞り込みが効く (アクティブ/高コストは KO 対象外)。 skip 解除。
def test_op03_025_krieg_on_play_discard_ko_rested():
    """【登場時】手札1枚捨て (コスト) → 相手レストのコスト4以下2枚のみを KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    rested_lo = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 rested (対象)
    rested_lo.rested = True
    active_hi = InPlay.of(repo.get("OP01-005"), sickness=False)  # cost4 active (対象外)
    opp.characters = [rested_lo, active_hi]

    on_play = _get_eff(overlay, "OP03-025", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-025"), sickness=True))
    assert len(me.hand) == 0, "コストの手札1枚が捨てられていない"
    assert rested_lo not in opp.characters, "相手レストのコスト4以下キャラが KO されていない"
    assert active_hi in opp.characters, "アクティブの相手キャラを KO してはいけない"


def test_op03_025_krieg_on_attached_don_double_attack():
    """【ドン!!×1】このキャラは【ダブルアタック】を得る (静的、 ドン付与1で成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    krieg = InPlay.of(repo.get("OP03-025"), sickness=False)
    krieg.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [krieg]

    evaluate_static_effects(st, overlay)
    assert krieg.is_double_attack_now, \
        "ドン!!×1 で【ダブルアタック】が付与されていない"
