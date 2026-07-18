# -*- coding: utf-8 -*-
"""EB01 弾 効果 回帰テスト バックフィル (自動生成 wave 001):
EB01-002 / EB01-003 / EB01-006 / EB01-007 / EB01-008 / EB01-011 /
EB01-013 / EB01-014 / EB01-016 / EB01-019 の 10 枚。

目的 (= 永続的 pytest による担保、 test_st36_new_cards.py と同一方針):
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
    try_replace_ko,
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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_eb01_wave1_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB01-002", "EB01-003", "EB01-006", "EB01-007", "EB01-008",
           "EB01-011", "EB01-013", "EB01-014", "EB01-016", "EB01-019"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB01-002 イゾウ: 【登場時】自リーダー/キャラにレストドン1まで付与 /
#                    【相手のアタック時】手札1捨てる → ワノ国/白ひげ leader なら相手1体 -2000
# --------------------------------------------------------------------------- #
def test_eb01_002_izou_on_play_attach_rested_don_ai():
    """【登場時】 AI: 自リーダー(既定)にレストドン1枚を付与する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国/光月家)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2  # レストドン供給源

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    on_play_eff = next(e for e in overlay.get("EB01-002").effects
                       if e["when"] == "on_play")
    for prim in on_play_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-002"), sickness=True))

    assert me.leader.attached_dons == don_before + 1, \
        "登場時に自リーダーへレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_eb01_002_izou_on_play_human_target_pick():
    """【登場時】 人間 + 自リーダー/キャラ 複数候補 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    # キャラを 1 体置いて 候補を リーダー + キャラ の 2 件にする
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    on_play_eff = next(e for e in overlay.get("EB01-002").effects
                       if e["when"] == "on_play")
    execute_effect(on_play_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("EB01-002"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    # キャラ (= 2 件目) を選択して付与
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"


def test_eb01_002_izou_opp_attack_power_debuff_ai():
    """【相手のアタック時】手札1捨てる → ワノ国 leader なら相手キャラ1体 -2000。
    AI: cost 支払い後 do の power_pump で相手キャラの power が -2000 される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # ワノ国 leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power 2000
    opp.characters = [victim]

    power_before = victim.power
    opp_eff = next(e for e in overlay.get("EB01-002").effects
                   if e["when"] == "opp_attack")
    # do (= power_pump) を直接発火 (cost/条件は overlay 側で別途 gate)
    for prim in opp_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-002"), sickness=False))

    assert victim.power == power_before - 2000, \
        f"相手キャラの power が -2000 されていない: {victim.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  EB01-003 キッド&キラー: 【速攻】【アタック時】相手ライフ2以下で 自身 +2000
# --------------------------------------------------------------------------- #
def test_eb01_003_kid_killer_attack_self_pump():
    """【アタック時】相手ライフ2以下 → このキャラ(自身)は このターン中 パワー+2000。
    対象選択なし (target: self) の単純 pump。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 2  # ライフ 2 (= 条件成立)
    attacker = InPlay.of(repo.get("EB01-003"), sickness=False)  # power 5000
    me.characters = [attacker]

    power_before = attacker.power
    on_attack_eff = overlay.get("EB01-003").effects[0]
    assert on_attack_eff.get("if", {}).get("opp_life_le") == 2, \
        "overlay の トリガー条件 opp_life_le=2 が無い"
    for prim in on_attack_eff["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert attacker.power == power_before + 2000, \
        f"アタック時 自己 +2000 が反映されていない: {attacker.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  EB01-006 チョッパー: 【ドン!!×2】【アタック時】相手キャラ1体 -3000
# --------------------------------------------------------------------------- #
def test_eb01_006_chopper_attack_debuff_ai():
    """【アタック時】(ドン2ゲート) 相手キャラ1体を このターン中 パワー-3000。 AI 自動選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power 2000
    opp.characters = [victim]

    power_before = victim.power
    on_attack_eff = overlay.get("EB01-006").effects[0]
    assert on_attack_eff.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    for prim in on_attack_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-006"), sickness=False))

    assert victim.power == power_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {power_before})"


def test_eb01_006_chopper_attack_debuff_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で 1 体に -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    opp.characters = [a, b]

    on_attack_eff = overlay.get("EB01-006").effects[0]
    execute_effect(on_attack_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("EB01-006"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB01-007 ヤマト: 【起動メイン】【ターン1回】自リーダー/キャラにレストドン1まで付与
# --------------------------------------------------------------------------- #
def test_eb01_007_yamato_activate_main_attach_rested_don_ai():
    """起動メイン: 自リーダーにレストドン1付与 (AI 自動)。 face 状態でなく attached_dons 検証。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    yamato = InPlay.of(repo.get("EB01-007"), sickness=False)
    me.characters = [yamato]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    options = list_activate_main_effects(st, me, overlay)
    yamato_opts = [(src, eff) for (src, eff) in options
                   if src.card.card_id == "EB01-007"]
    assert len(yamato_opts) == 1, \
        f"EB01-007 の起動メインが legal に出ない: {len(yamato_opts)}"
    src, eff = yamato_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_eb01_007_yamato_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    yamato = InPlay.of(repo.get("EB01-007"), sickness=False)
    me.characters = [yamato]
    me.don_rested = 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "EB01-007"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "EB01-007"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB01-008 リトルオーズJr.: 【ターン1回】効果KOされる時、代わりに手札の
#                             イベント/ステージ1枚を捨てられる (replace_ko)
# --------------------------------------------------------------------------- #
def test_eb01_008_little_oars_replace_ko_ai():
    """効果KO時: 手札のイベント/ステージを1枚捨てて KO を置換 (代わりに耐える)。
    AI: 手札に捨てられる EVENT/STAGE があれば置換が成立し、 KO がキャンセルされる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    oars = InPlay.of(repo.get("EB01-008"), sickness=False)
    me.characters = [oars]
    # 捨てるコスト用: EB01-011 (STAGE) と EB01-019 (EVENT) を手札に
    me.hand = [repo.get("EB01-011"), repo.get("EB01-019")]

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, oars, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "EVENT/STAGE を捨てられるのに KO が置換されていない"
    assert oars in me.characters, "置換成立時 リトルオーズは場に残るべき"
    assert len(me.hand) == hand_before - 1, "置換コストで手札 EVENT/STAGE が1枚捨てられるべき"


def test_eb01_008_little_oars_replace_ko_no_event_stage():
    """手札に EVENT/STAGE が無ければ cost 不能 → 置換できない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    oars = InPlay.of(repo.get("EB01-008"), sickness=False)
    me.characters = [oars]
    me.hand = [repo.get("OP01-013")]  # CHARACTER のみ = 捨てられない

    replaced = try_replace_ko(
        st, me, opp, oars, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "EVENT/STAGE が無いのに置換が成立してはいけない"


def test_eb01_008_little_oars_replace_ko_human_confirm():
    """人間 actor: replace_ko は 任意 (optional) → replace_ko_optional modal が立ち、
    承諾すると EVENT/STAGE 1 枚を捨てて KO を代替する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    oars = InPlay.of(repo.get("EB01-008"), sickness=False)
    me.characters = [oars]
    me.hand = [repo.get("EB01-011")]  # STAGE 1 枚

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, oars, overlay, by_opp_effect=True, leave_kind="ko",
    )
    # 人間は「置換する?」の modal を立てて halt (= True で KO を保留)
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert oars in me.characters, "人間承諾後 リトルオーズは場に残るべき"
    assert len(me.hand) == hand_before - 1, "承諾後 EVENT/STAGE が1枚捨てられるべき"


# --------------------------------------------------------------------------- #
#  EB01-011 ミニメリー2号 (STAGE): 【起動メイン】自レスト + 元々P1000キャラ1枚を
#                                   デッキ下 → 1ドロー
# --------------------------------------------------------------------------- #
def test_eb01_011_mini_merry_activate_main_draw_ai():
    """起動メイン: このステージをレストにし (コスト) → 1 枚引く。 AI 自動発動。
    (overlay は rest_self コストのみ + draw1。 元々P1000キャラ→デッキ下は未モデル化の
     追加コストだが、 overlay 忠実に rest_self + draw を検証。)"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    merry = InPlay.of(repo.get("EB01-011"), sickness=False)  # STAGE
    me.stages = [merry]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10

    options = list_activate_main_effects(st, me, overlay)
    merry_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "EB01-011"]
    assert len(merry_opts) == 1, \
        f"EB01-011 (ステージ) の起動メインが legal に出ない: {len(merry_opts)}"
    src, eff = merry_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert len(me.hand) == 1, "起動メインの draw が起きていない"
    assert merry.rested is True, "起動メインコストでステージがレストされるべき"


# --------------------------------------------------------------------------- #
#  EB01-013 光月日和: 【起動メイン】自トラッシュ → 手札からワノ国 cost5以下
#                    (光月日和以外) 1枚登場 → その後1ドロー
# --------------------------------------------------------------------------- #
def test_eb01_013_hiyori_activate_main_play_from_hand_ai():
    """起動メイン: 自身をトラッシュに置き (コスト) → 手札からワノ国 cost5以下を登場 + 1ドロー。
    AI: 手札に該当キャラ (マルコ ワノ国 cost4) があれば登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国 leader)
    me, opp = st.players[0], st.players[1]
    hiyori = InPlay.of(repo.get("EB01-013"), sickness=False)
    me.characters = [hiyori]
    marco = repo.get("PRB02-008")  # マルコ ワノ国/元白ひげ海賊団 cost4
    assert "ワノ国" in (marco.features or ""), "テスト前提: PRB02-008 は ワノ国"
    me.hand = [marco]
    me.deck = [repo.get("OP01-013")] * 10

    hand_before = len(me.hand)
    chars_before = len(me.characters)
    options = list_activate_main_effects(st, me, overlay)
    hiyori_opts = [(src, eff) for (src, eff) in options
                   if src.card.card_id == "EB01-013"]
    assert len(hiyori_opts) == 1, \
        f"EB01-013 の起動メインが legal に出ない: {len(hiyori_opts)}"
    src, eff = hiyori_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    # コスト: 日和自身が場から消える。 マルコが登場。 その後 1 ドロー。
    assert hiyori not in me.characters, "コストで光月日和がトラッシュに置かれるべき"
    assert any(c.card.card_id == "PRB02-008" for c in me.characters), \
        "手札からワノ国キャラ (マルコ) が登場していない"
    # net キャラ: -1 (日和 trash) + 1 (マルコ登場) = ±0
    assert len(me.characters) == chars_before, \
        f"キャラ枚数 net が合わない: {len(me.characters)} (before {chars_before})"
    # 手札: -1 (マルコ登場) + 1 (ドロー) = ±0
    assert len(me.hand) == hand_before - 1 + 1, \
        f"手札 net (登場 -1 + ドロー +1) が合わない: {len(me.hand)}"


def test_eb01_013_hiyori_activate_main_human_play_pick():
    """人間 + 手札にワノ国 cost5以下 複数 → 登場先を選ぶ play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hiyori = InPlay.of(repo.get("EB01-013"), sickness=False)
    me.characters = [hiyori]
    # 2 種の ワノ国 cost5以下 キャラ を手札に
    me.hand = [repo.get("PRB02-008"), repo.get("EB01-016")]  # マルコ / びん豪
    me.deck = [repo.get("OP01-013")] * 10

    options = list_activate_main_effects(st, me, overlay)
    hiyori_opts = [(src, eff) for (src, eff) in options
                   if src.card.card_id == "EB01-013"]
    assert len(hiyori_opts) == 1
    fire_activate_main(st, me, opp, *hiyori_opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    # resolve できること (先頭候補を選ぶ) + 後続 (ドロー等) を流す
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    # 何かしら 1 体 が登場している
    assert any(c.card.card_id in ("PRB02-008", "EB01-016")
               for c in me.characters), \
        "人間が選んだワノ国キャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB01-014 サンジ: 【ドン!!×1】【自分のターン中】自分のレストドン3枚につき +1000
# --------------------------------------------------------------------------- #
def test_eb01_014_sanji_static_power_per_rested_don():
    """静的効果 (on_attached_don n=1、 自ターン中): 自分のレストドン3枚につき パワー+1000。
    ドン付与 1 + レストドン 3 → base +1000。 evaluate_static_effects で検証。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    sanji_def = repo.get("EB01-014")  # power 5000
    sanji = InPlay.of(sanji_def, sickness=False)
    p0.characters = [sanji]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0  # 自分のターン (= self_turn 条件成立)
    st.human_player_idx = None

    sanji.attached_dons = 1   # n=1 ゲート成立
    p0.don_rested = 3         # レストドン 3 → +1000
    evaluate_static_effects(st, overlay)

    # 印刷 5000 + DON1枚(+1000) + 効果(レスト3で+1000) = 7000
    assert sanji.power == sanji_def.power + 1000 + 1000, \
        f"レストドン3で +1000 が反映されていない: {sanji.power} (base {sanji_def.power})"


def test_eb01_014_sanji_static_no_pump_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → 効果 +0 (DON分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    sanji_def = repo.get("EB01-014")
    sanji = InPlay.of(sanji_def, sickness=False)
    p0.characters = [sanji]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 1  # 相手ターン → self_turn False
    st.human_player_idx = None

    sanji.attached_dons = 1
    p0.don_rested = 3
    evaluate_static_effects(st, overlay)

    # DON1枚(+1000) のみ、 効果 pump は 乗らない
    assert sanji.power == sanji_def.power + 1000, \
        f"相手ターンで効果 pump が乗ってはいけない: {sanji.power} (base {sanji_def.power})"


# --------------------------------------------------------------------------- #
#  EB01-016 びん豪: 【起動メイン】自レスト → 相手のレストのコスト1以下キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_eb01_016_bingou_activate_main_ko_rested_cost1_ai():
    """起動メイン: 自レスト → 相手のレストのコスト1以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    bingou = InPlay.of(repo.get("EB01-016"), sickness=False)
    me.characters = [bingou]
    # 相手にレストのコスト1キャラ (EB04-002 ボニー cost1)
    victim = InPlay.of(repo.get("EB04-002"), sickness=False)
    victim.rested = True
    opp.characters = [victim]

    options = list_activate_main_effects(st, me, overlay)
    bingou_opts = [(src, eff) for (src, eff) in options
                   if src.card.card_id == "EB01-016"]
    assert len(bingou_opts) == 1, \
        f"EB01-016 の起動メインが legal に出ない: {len(bingou_opts)}"
    src, eff = bingou_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert victim not in opp.characters, "相手のレストコスト1キャラが KO されていない"
    assert bingou.rested is True, "起動メインコストで びん豪 がレストされるべき"


def test_eb01_016_bingou_activate_main_no_active_target():
    """相手のコスト1キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    bingou = InPlay.of(repo.get("EB01-016"), sickness=False)
    me.characters = [bingou]
    victim = InPlay.of(repo.get("EB04-002"), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    src, eff = [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "EB01-016"][0]
    fire_activate_main(st, me, opp, src, eff)
    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_eb01_016_bingou_activate_main_human_ko_pick():
    """人間 + 相手のレストコスト1キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bingou = InPlay.of(repo.get("EB01-016"), sickness=False)
    me.characters = [bingou]
    a = InPlay.of(repo.get("EB04-002"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (ナミ)
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    src, eff = [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "EB01-016"][0]
    fire_activate_main(st, me, opp, src, eff)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  EB01-019 盾白糸 (EVENT): 【カウンター】自リーダー/キャラ1枚 +4000 →
#                          デッキ上3枚からドンキホーテ海賊団キャラ1枚を公開手札 → 残りデッキ下
# --------------------------------------------------------------------------- #
def test_eb01_019_tate_shiraito_counter_pump_ai():
    """【カウンター】(1) 自リーダーorキャラ1枚 +4000。 AI 自動選択 (リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB02-011", overlay)  # ドフラミンゴ (ドンキホーテ海賊団 leader)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    counter_pump = next(e for e in overlay.get("EB01-019").effects
                        if e["when"] == "counter"
                        and "power_pump" in e["do"][0])
    for prim in counter_pump["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_eb01_019_tate_shiraito_counter_search_ai():
    """【カウンター】(2) デッキ上3枚を見て ドンキホーテ海賊団キャラ1枚を手札へ、 残りデッキ下。
    AI: 上3枚に該当キャラ (シュガー) を仕込むと手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB02-011", overlay)
    me, opp = st.players[0], st.players[1]
    sugar = repo.get("EB03-005")  # シュガー ドンキホーテ海賊団
    assert "ドンキホーテ海賊団" in (sugar.features or ""), "テスト前提: EB03-005 は ドンキホーテ海賊団"
    me.deck = [sugar] + [repo.get("OP01-013")] * 20
    me.hand = []

    counter_search = next(e for e in overlay.get("EB01-019").effects
                          if e["when"] == "counter"
                          and "search_top_n" in e["do"][0])
    for prim in counter_search["do"]:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card_id == "EB03-005" for c in me.hand), \
        "デッキ上3枚から ドンキホーテ海賊団キャラが手札に加わっていない"


def test_eb01_019_tate_shiraito_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB02-011", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    counter_pump = next(e for e in overlay.get("EB01-019").effects
                        if e["when"] == "counter"
                        and "power_pump" in e["do"][0])
    execute_effect(counter_pump["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


def test_eb01_019_tate_shiraito_counter_search_human_pick():
    """人間 + デッキ上3枚に ドンキホーテ海賊団 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB02-011", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sugar = repo.get("EB03-005")
    # 上3枚のうち複数を ドンキホーテ海賊団 に
    me.deck = [sugar, repo.get("OP01-013"), sugar] + [repo.get("OP01-013")] * 15
    me.hand = []

    counter_search = next(e for e in overlay.get("EB01-019").effects
                          if e["when"] == "counter"
                          and "search_top_n" in e["do"][0])
    execute_effect(counter_search["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (シュガー) を選択
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == "EB03-005" for c in me.hand), \
        "人間が選んだ ドンキホーテ海賊団キャラが手札に加わっていない"
