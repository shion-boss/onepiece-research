# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 075):
OP07-026 / OP07-029 / OP07-030 / OP07-031 / OP07-032 / OP07-033 /
OP07-034 / OP07-035 / OP07-036 / OP07-037 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_074.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"       # ロロノア・ゾロ (赤、 特徴《超新星》/《麦わらの一味》)
_NON_SS_LEADER = "OP03-001"  # ポートガス・D・エース (白ひげ海賊団、 超新星なし)
_FILLER = "OP01-013"       # サンジ cost2 power3000 麦わらの一味 (汎用フィラー)
_GYOJIN_LEADER = "OP11-021"  # ジンベエ 緑 魚人族/麦わらの一味 (魚人族リーダー)
_KAMI = "OP06-025"         # ケイミー 緑 cost1 power2000 (OP07-030 の条件用)
_SS_CHAR = "PRB02-006"     # ロロノア・ゾロ 緑 cost4 CHARACTER 超新星 (超新星サーチ対象)
_SELF3 = "EB02-002"        # サボ 緑 cost4 power5000 (コスト3以上の自キャラ)


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


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


def _drain(st, pick=0, guard=15):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave75_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-026", "OP07-029", "OP07-030", "OP07-031", "OP07-032",
           "OP07-033", "OP07-034", "OP07-035", "OP07-036", "OP07-037"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-026 ジュエリー・ボニー (CHARACTER 緑 cost5):
#    【登場時】相手の、レストのキャラかドン!!1枚までは、次の相手のリフレッシュフェイズで
#      アクティブにならない。
# --------------------------------------------------------------------------- #
def test_op07_026_on_play_stay_rested_ai():
    """登場時: 相手のレストキャラ1枚に stay_rested_next_refresh フラグを立てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    opp.characters = [victim]
    assert victim.stay_rested_next_refresh is False
    src = InPlay.of(repo.get("OP07-026"), sickness=True)

    for prim in _do(overlay, "OP07-026", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim.stay_rested_next_refresh is True, \
        "相手のレストキャラに stay_rested_next_refresh が立っていない"


def test_op07_026_on_play_only_rested_target():
    """登場時 negative: 相手キャラがアクティブなら対象外 → フラグは立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-026", "on_play"):
        execute_effect(prim, st, me, opp, InPlay.of(repo.get("OP07-026"), sickness=True))
    _drain(st)

    assert victim.stay_rested_next_refresh is False, \
        "アクティブなキャラに stay_rested_next_refresh が立ってはいけない (対象外)"


def test_op07_026_on_play_human_target_pick():
    """登場時 (人間): 相手のレストキャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP07-026", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP07-026"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.stay_rested_next_refresh is True, \
        "人間が選んだレストキャラにフラグが立っていない"


# --------------------------------------------------------------------------- #
#  OP07-029 バジル・ホーキンス (CHARACTER 緑 cost6):
#    自リーダーが特徴《超新星》を持つ場合【ブロッカー】を得る。
#    【ターン1回】このキャラが相手の効果で場を離れる場合、代わりに相手のキャラ1枚を
#      レストにできる。(replace_leave)
# --------------------------------------------------------------------------- #
def test_op07_029_static_blocker_when_supernova_leader():
    """静的: 自リーダーが超新星 → ブロッカーを得る (is_blocker_now True)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # 超新星 リーダー
    me, opp = st.players[0], st.players[1]
    hawkins = InPlay.of(repo.get("OP07-029"), sickness=False)
    me.characters = [hawkins]
    evaluate_static_effects(st, overlay)
    assert hawkins.is_blocker_now is True, \
        "超新星 リーダーなのに ブロッカーを得ていない"


def test_op07_029_no_blocker_when_non_supernova_leader():
    """静的 negative: 自リーダーが超新星でなければ ブロッカーを得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NON_SS_LEADER, overlay)  # 白ひげ海賊団 (超新星なし)
    me, opp = st.players[0], st.players[1]
    hawkins = InPlay.of(repo.get("OP07-029"), sickness=False)
    me.characters = [hawkins]
    evaluate_static_effects(st, overlay)
    assert hawkins.is_blocker_now is False, \
        "超新星でないリーダーなのに ブロッカーを得ている"


def test_op07_029_replace_leave_rest_opponent_ai():
    """replace_leave: 相手の効果で場を離れる時、代わりに相手キャラ1枚をレストにして残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    hawkins = InPlay.of(repo.get("OP07-029"), sickness=False)
    me.characters = [hawkins]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    assert victim.rested is False

    replaced = try_replace_ko(
        st, me, opp, hawkins, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st)
    assert replaced is True, "相手キャラをレストできるのに離脱が置換されていない"
    assert hawkins in me.characters, "置換成立時 ホーキンスは場に残るべき"
    assert victim.rested is True, "置換で相手キャラがレストされるべき"


# --------------------------------------------------------------------------- #
#  OP07-030 パッパグ (CHARACTER 緑 cost2):
#    自分のキャラの「ケイミー」がいる場合【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op07_030_static_blocker_with_kaimi():
    """静的: 自分のキャラ「ケイミー」がいる → ブロッカーを得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    pappag = InPlay.of(repo.get("OP07-030"), sickness=False)
    kaimi = InPlay.of(repo.get(_KAMI), sickness=False)  # ケイミー
    me.characters = [pappag, kaimi]
    evaluate_static_effects(st, overlay)
    assert pappag.is_blocker_now is True, \
        "「ケイミー」がいるのに パッパグが ブロッカーを得ていない"


def test_op07_030_no_blocker_without_kaimi():
    """静的 negative: 「ケイミー」がいなければ ブロッカーを得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    pappag = InPlay.of(repo.get("OP07-030"), sickness=False)
    me.characters = [pappag, InPlay.of(repo.get(_FILLER), sickness=False)]
    evaluate_static_effects(st, overlay)
    assert pappag.is_blocker_now is False, \
        "「ケイミー」不在なのに パッパグが ブロッカーを得ている"


# --------------------------------------------------------------------------- #
#  OP07-031 バルトロメオ (CHARACTER 緑 cost3):
#    【自分のターン中】【ターン1回】キャラが自分の効果でレストになった時、
#      カード1枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op07_031_on_rest_draw_and_discard_ai():
    """自効果でキャラがレスト時: 1 枚引き、 手札1枚を捨てる (AI、 手札枚数 net ±0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    barto = InPlay.of(repo.get("OP07-031"), sickness=False)
    me.characters = [barto]
    me.hand = [repo.get(_FILLER)]  # 捨てる用の手札
    me.deck = [repo.get(_FILLER)] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    for prim in _do(overlay, "OP07-031", "on_self_chara_rested_by_self_effect"):
        execute_effect(prim, st, me, opp, barto)
    _drain(st)

    # draw +1 / discard -1 → 手札 net ±0
    assert len(me.hand) == hand_before, \
        f"draw+discard 後の手札枚数が合わない: {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれるべき"
    assert len(me.trash) == trash_before + 1, "捨てた1枚がトラッシュに置かれるべき"


# --------------------------------------------------------------------------- #
#  OP07-032 フィッシャー・タイガー (CHARACTER 緑 cost5):
#    このキャラは登場したターンにキャラへアタックできる (速攻：キャラ)。
#    【登場時】自リーダーが特徴《魚人族》か《人魚族》を持つ場合、相手のコスト6以下の
#      キャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op07_032_on_play_rest_opp_when_gyojin_leader_ai():
    """登場時 (魚人族リーダー): 相手のコスト6以下キャラをレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _GYOJIN_LEADER, overlay)  # ジンベエ (魚人族)
    me, opp = st.players[0], st.players[1]
    rest_eff = _eff(overlay, "OP07-032", "on_play")
    # rest を含む on_play (= 登場時 レスト) を明示的に選ぶ
    rest_do = next(e["do"] for e in overlay.get("OP07-032").effects
                   if e.get("when") == "on_play" and "rest" in e["do"][0]
                   and e.get("if"))
    cond = next(e.get("if") for e in overlay.get("OP07-032").effects
                if e.get("when") == "on_play" and e.get("if"))
    assert eval_condition(cond, st, me) is True, "魚人族リーダーで条件が成立していない"
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 6
    opp.characters = [victim]

    src = InPlay.of(repo.get("OP07-032"), sickness=True)
    for prim in rest_do:
        execute_effect(prim, st, me, opp, src)
    _drain(st)
    assert victim.rested is True, "相手のコスト6以下キャラがレストされていない"


def test_op07_032_on_play_grant_rush_chara():
    """登場時: このキャラは【速攻：キャラ】を得る (登場ターンにキャラへアタック可)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP07-032"), sickness=True)
    me.characters = [src]
    grant_do = next(e["do"] for e in overlay.get("OP07-032").effects
                    if e.get("when") == "on_play"
                    and "give_keyword" in e["do"][0])
    for prim in grant_do:
        execute_effect(prim, st, me, opp, src)
    _drain(st)
    assert any("速攻" in kw for kw in getattr(src, "granted_keywords", set())), \
        f"速攻：キャラ を得ていない: {getattr(src, 'granted_keywords', None)}"


def test_op07_032_on_play_human_rest_pick():
    """登場時 (人間): 相手コスト6以下キャラ 複数 → target_pick modal → レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _GYOJIN_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_KAMI), sickness=False)  # cost1
    opp.characters = [a, b]
    rest_do = next(e["do"] for e in overlay.get("OP07-032").effects
                   if e.get("when") == "on_play" and "rest" in e["do"][0]
                   and e.get("if"))

    execute_effect(rest_do[0], st, me, opp, InPlay.of(repo.get("OP07-032"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP07-033 モンキー・D・ルフィ (CHARACTER 緑 cost5):
#    自分のキャラが3枚以上いる場合、自分の、「モンキー・D・ルフィ」以外のコスト3以下の
#      キャラは相手の効果でKOされない。
# --------------------------------------------------------------------------- #
def test_op07_033_static_ko_immune_when_3_chara():
    """静的: 自キャラ3枚以上 → ルフィ以外のコスト3以下キャラが 効果KO耐性を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP07-033"), sickness=False)   # cost5 ルフィ
    small = InPlay.of(repo.get(_FILLER), sickness=False)       # cost2 <= 3
    third = InPlay.of(repo.get(_KAMI), sickness=False)         # cost1 (3体目)
    me.characters = [luffy, small, third]
    evaluate_static_effects(st, overlay)
    assert small.static_ko_immune is True, \
        "自キャラ3枚以上でコスト3以下キャラが 効果KO耐性を得ていない"
    assert luffy.static_ko_immune is False, \
        "ルフィ自身 (exclude_name) は耐性対象外のはず"


def test_op07_033_no_ko_immune_when_few_chara():
    """静的 negative: 自キャラが3枚未満なら 耐性は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP07-033"), sickness=False)
    small = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [luffy, small]  # 2 体 = 条件不成立
    evaluate_static_effects(st, overlay)
    assert small.static_ko_immune is False, \
        "自キャラ2枚 (条件不成立) なのに 耐性が付いている"


# --------------------------------------------------------------------------- #
#  OP07-034 ロロノア・ゾロ (CHARACTER 緑 cost1):
#    【アタック時】自分のキャラが3枚以上いる場合、このキャラは このターン中 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op07_034_attack_self_pump_when_3_chara_ai():
    """アタック時: 自キャラ3枚以上なら 自身 +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP07-034"), sickness=False)  # power2000
    me.characters = [zoro, InPlay.of(repo.get(_FILLER), sickness=False),
                     InPlay.of(repo.get(_KAMI), sickness=False)]  # 3 体
    cond = _eff(overlay, "OP07-034", "on_attack").get("if")
    assert eval_condition(cond, st, me) is True, "自キャラ3枚で条件が成立していない"
    before = zoro.power

    for prim in _do(overlay, "OP07-034", "on_attack"):
        execute_effect(prim, st, me, opp, zoro)
    _drain(st)
    assert zoro.power == before + 2000, \
        f"アタック時 自己 +2000 が反映されていない: {zoro.power} (before {before})"


def test_op07_034_attack_condition_false_when_few_chara():
    """アタック時 negative: 自キャラが3枚未満なら 条件不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP07-034"), sickness=False)
    me.characters = [zoro]  # 1 体 = 条件不成立
    cond = _eff(overlay, "OP07-034", "on_attack").get("if")
    assert eval_condition(cond, st, me) is False, \
        "自キャラ1枚なのに 条件が成立している"


# --------------------------------------------------------------------------- #
#  OP07-035 因果晒し (EVENT 緑 cost1):
#    【カウンター】自リーダーかキャラ1枚までを このバトル中 パワー+2000。
#    【トリガー】相手のレストのコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_035_counter_pump_ai():
    """カウンター: 自リーダー (既定) を このバトル中 +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    before = me.leader.power

    for prim in _do(overlay, "OP07-035", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.leader.power == before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op07_035_trigger_ko_rested_cost4_ai():
    """トリガー: 相手のレストのコスト4以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SELF3), sickness=False)  # cost4 <= 4
    victim.rested = True
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-035", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "相手のレストコスト4以下キャラが KO されていない"


def test_op07_035_trigger_no_ko_active_chara():
    """トリガー negative: 相手キャラがアクティブなら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SELF3), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-035", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_op07_035_counter_human_target_pick():
    """カウンター (人間): 自リーダー + キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP07-035", "counter")[0], st, me, opp, None)
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


# --------------------------------------------------------------------------- #
#  OP07-036 鬼気 九刀流 阿修羅 魔九閃 (EVENT 緑 cost2):
#    【メイン】自リーダーかキャラ1枚までを このターン中 パワー+3000。その後、自分の
#      コスト3以上のキャラ1枚をレストにできる。そうした場合、相手のコスト5以下のキャラ
#      1枚までを、レストにする。
#    【トリガー】相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op07_036_main_pump_ai():
    """メイン: 自リーダー (既定) を このターン中 +3000 (AI、 do[0] の power_pump)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    before = me.leader.power

    execute_effect(_do(overlay, "OP07-036", "main")[0], st, me, opp, None)
    _drain(st)
    assert me.leader.power == before + 3000, \
        f"メインの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_op07_036_main_optional_rest_full_ai():
    """メイン全体 (AI): +3000 → コスト3以上の自キャラをレスト → 相手コスト5以下をレスト。
    AI は有利なので任意コストを支払う想定 (crash せず解決)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get(_SELF3), sickness=False)  # cost4 >= 3 (レスト対象)
    me.characters = [sabo]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 5
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-036", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    # AI が任意コストを支払った場合: 自キャラがレスト & 相手キャラがレスト
    if sabo.rested:
        assert victim.rested is True, \
            "コストを支払った (自キャラレスト) のに 相手キャラがレストされていない"


def test_op07_036_main_human_optional_cost_modal():
    """メイン (人間): その後の任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get(_SELF3), sickness=False)  # コスト3以上 (支払い可能)
    me.characters = [sabo]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    # do[1] = optional_cost_then (任意コスト)
    execute_effect(_do(overlay, "OP07-036", "main")[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op07_036_trigger_rest_opp_cost4_ai():
    """トリガー: 相手のコスト4以下キャラをレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SELF3), sickness=False)  # cost4 <= 4
    opp.characters = [victim]
    assert victim.rested is False

    for prim in _do(overlay, "OP07-036", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP07-037 ピザお～か～わ～り～!!! (EVENT 緑 cost1):
#    【メイン】自分のデッキの上から5枚を見て、「ピザお～か～わ～り～!!!」以外の
#      特徴《超新星》を持つカード1枚までを公開し、手札に加える。その後、残りを
#      好きな順番でデッキの下に置く。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op07_037_main_search_supernova_ai():
    """メイン: デッキ上5枚から特徴《超新星》のカードを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SS_CHAR)] + [repo.get(_FILLER)] * 10  # 上に超新星
    me.hand = []

    for prim in _do(overlay, "OP07-037", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card_id == _SS_CHAR for c in me.hand), \
        f"デッキ上5枚から超新星カードが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op07_037_main_human_search_modal():
    """メイン (人間): デッキ上5枚に超新星 複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SS_CHAR), repo.get(_FILLER), repo.get(_SS_CHAR)] \
        + [repo.get(_FILLER)] * 8
    me.hand = []

    execute_effect(_do(overlay, "OP07-037", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _SS_CHAR for c in me.hand), \
        "人間が選んだ超新星カードが手札に加わっていない"


def test_op07_037_trigger_draw_ai():
    """トリガー: カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP07-037", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == 1, "トリガーの draw が起きていない"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれるべき"
