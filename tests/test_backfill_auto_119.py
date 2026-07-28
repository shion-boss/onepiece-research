# -*- coding: utf-8 -*-
"""OP12 弾 (ゾロ軸 緑) 効果 回帰テスト バックフィル (自動生成 wave 119):
OP12-024 / OP12-026 / OP12-028 / OP12-029 / OP12-030 / OP12-031 /
OP12-033 / OP12-037 / OP12-038 / OP12-039 の 10 枚。

  OP12-024 牛鬼丸 (CHARACTER 緑) = 【アタック時】付与ドン合計3以上なら 相手の元々コスト6以下
     キャラ1枚をレスト (on_attack rest one_opponent_character_cost_le_6cost, if self_attached_don_ge3)
  OP12-026 くいな (CHARACTER 緑) = 【起動メイン】自レスト：相手の元々コスト4以下キャラ1枚レスト →
     リーダーが「ロロノア・ゾロ」ならレストドン3までを自リーダーに付与
     (activate_main rest one_opponent_character_cost_le_4cost + conditional attach_rested_don self_leader×3)
  OP12-028 光月日和 (CHARACTER 緑) = 【起動メイン】自ドン1+自レスト：ゾロなら上5枚→属性(斬)か緑イベント
     1枚を手札 残りデッキ下 (activate_main search_top_n depth5 or_clauses[attribute斬 / EVENT緑])
  OP12-029 霜月コウ三郎 (CHARACTER 緑) = 【登場時】相手コスト2以下1枚レスト → 相手レストの元々コスト1以下
     1枚KO (on_play rest one_opponent_character_cost_le_2cost + ko one_opponent_rested_character_cost_le_1cost)
  OP12-030 ジュラキュール・ミホーク (CHARACTER 緑) = 【ブロッカー】【登場時】自ドン4までアクティブに
     (on_play untap_don 4)
  OP12-031 たしぎ (CHARACTER 緑) = 【登場時】相手の元々コスト6以下キャラ1枚レスト
     (on_play rest one_opponent_character_cost_le_6cost)
  OP12-033 ヘルメッポ (CHARACTER 緑) = 【ブロッカー】【ブロック時】相手コスト5以下キャラ1枚レスト
     (on_block rest one_opponent_character_cost_le_5cost)
  OP12-037 鬼気 九刀流 阿修羅 抜剣 亡者戯 (EVENT 緑) = 【メイン】自ドン3レスト：相手のキャラかドン合計2まで
     レスト /【カウンター】自リーダー +3000 (main rest one_opp_chara_or_don ×2 / counter power_pump self_leader)
  OP12-038 二刀流 居合 羅生門 (EVENT 緑) = 【メイン】自ドン2レスト：相手レストの元々コスト4以下キャラ2枚KO /
     【カウンター】自リーダー +3000 (main ko_multi rested cost_le_4 ×2 / counter power_pump self_leader)
  OP12-039 ルフィは海賊王になる男だ!!! (EVENT 緑) = 【メイン】ゾロならリーダーをアクティブに /
     【トリガー】自リーダーかキャラ +1000 (main untap self_leader / trigger power_pump self_inplay +1000)

目的 (= test_backfill_auto_001〜118.py と同一方針):
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
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GENERIC = "OP01-001"   # ロロノア・ゾロ (LEADER, 名前 = ロロノア・ゾロ)
_LEADER_ZORO_G = "OP12-020"    # ロロノア・ゾロ LEADER 緑 (属性 斬、 名前 = ロロノア・ゾロ)
_FILLER = "ST01-004"           # サンジ cost2 power4000
_C2 = "OP01-013"               # サンジ cost2 power3000
_C1 = "OP01-016"               # ナミ cost1 power2000
_C1B = "EB04-002"              # ジュエリー・ボニー cost1 power2000
_GREEN_EVENT = "OP12-039"      # ルフィは海賊王になる男だ (緑 EVENT、 search filter 用)


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


def _drain(st, pick=None, guard=10):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave119_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-024", "OP12-026", "OP12-028", "OP12-029", "OP12-030",
           "OP12-031", "OP12-033", "OP12-037", "OP12-038", "OP12-039"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-024 牛鬼丸: 【アタック時】付与ドン3以上なら 相手コスト6以下1枚レスト
# --------------------------------------------------------------------------- #
def test_op12_024_on_attack_rest_opp_ai():
    """【アタック時】付与ドン3の attacker → 相手の元々コスト6以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP12-024"), sickness=False)
    attacker.attached_dons = 3
    me.characters = [attacker]
    victim = InPlay.of(repo.get(_C2), sickness=False)  # cost2 (<=6)
    opp.characters = [victim]

    on_attack = _eff(overlay, "OP12-024", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 3, \
        "overlay の ドンゲート self_attached_don_ge=3 が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])

    assert victim.rested is True, "アタック時に相手キャラがレストされていない"


def test_op12_024_on_attack_rest_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP12-024"), sickness=False)
    attacker.attached_dons = 3
    me.characters = [attacker]
    a = InPlay.of(repo.get(_C2), sickness=False)
    b = InPlay.of(repo.get(_C1), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP12-024", "on_attack")["do"][0],
                   st, me, opp, attacker)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP12-026 くいな: 【起動メイン】自レスト → 相手コスト4以下1枚レスト → ゾロなら レストドン3付与
# --------------------------------------------------------------------------- #
def test_op12_026_activate_main_rest_and_attach_don_ai():
    """起動メイン: 自レスト → 相手コスト4以下1枚レスト → ゾロleaderにレストドン3付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZORO_G, overlay)  # 緑ゾロ leader (名前 ロロノア・ゾロ)
    me, opp = st.players[0], st.players[1]
    kuina = InPlay.of(repo.get("OP12-026"), sickness=False)
    me.characters = [kuina]
    me.don_rested = 3  # 付与用レストドン
    victim = InPlay.of(repo.get(_C2), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]

    don_before = me.leader.attached_dons
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-026"]
    assert len(opts) == 1, f"OP12-026 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert kuina.rested is True, "起動メインコストで くいな がレストされるべき"
    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"
    assert me.leader.attached_dons == don_before + 3, \
        "ゾロリーダーにレストドン3枚が付与されていない"
    assert me.don_rested == 0, "レストドンが3枚消費されるべき"


def test_op12_026_no_attach_when_not_zoro():
    """リーダーが「ロロノア・ゾロ」でなければ 付与部分 (conditional) が発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, opp_leader_id="OP01-001")
    # opp_leader は無関係。 自リーダーを 非ゾロ に差し替え
    from engine.core import InPlay as _IP
    st.players[0].leader = _IP.of(repo.get("OP16-043"), sickness=False)  # ウソップ (非リーダーだが名前でゲート)
    me, opp = st.players[0], st.players[1]
    kuina = InPlay.of(repo.get("OP12-026"), sickness=False)
    me.characters = [kuina]
    me.don_rested = 3
    victim = InPlay.of(repo.get(_C2), sickness=False)
    opp.characters = [victim]

    don_before = me.leader.attached_dons
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-026"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert victim.rested is True, "レスト部分は条件無しで発火するべき"
    assert me.leader.attached_dons == don_before, \
        "非ゾロなのにレストドンが付与されてはいけない"


def test_op12_026_activate_main_human_rest_pick():
    """人間 + 相手キャラ複数 → レスト対象の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZORO_G, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    kuina = InPlay.of(repo.get("OP12-026"), sickness=False)
    me.characters = [kuina]
    me.don_rested = 3
    a = InPlay.of(repo.get(_C2), sickness=False)
    b = InPlay.of(repo.get(_C1), sickness=False)
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-026"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert me.leader.attached_dons == 3, "解決後 ゾロリーダーにレストドン3付与されるべき"


# --------------------------------------------------------------------------- #
#  OP12-028 光月日和: 【起動メイン】自ドン1+自レスト → ゾロなら上5枚→斬/緑イベント1枚を手札
# --------------------------------------------------------------------------- #
def test_op12_028_activate_main_search_ai():
    """起動メイン: 自ドン1レスト+自レスト → 上5枚から緑イベント1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZORO_G, overlay)
    me, opp = st.players[0], st.players[1]
    hiyori = InPlay.of(repo.get("OP12-028"), sickness=False)
    me.characters = [hiyori]
    me.don_active = 2  # コスト rest_self_don 1 用の アクティブドン
    me.hand = []
    me.deck = [repo.get(_GREEN_EVENT)] + [repo.get(_FILLER)] * 20  # 上に緑イベント

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-028"]
    assert len(opts) == 1, f"OP12-028 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert hiyori.rested is True, "起動メインコストで 光月日和 がレストされるべき"
    assert any(c.card_id == _GREEN_EVENT for c in me.hand), \
        "上5枚から緑イベントが手札に加わっていない"


def test_op12_028_activate_main_search_human_pick():
    """人間 + 上5枚に緑イベント → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZORO_G, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hiyori = InPlay.of(repo.get("OP12-028"), sickness=False)
    me.characters = [hiyori]
    me.don_active = 2
    me.hand = []
    me.deck = [repo.get(_GREEN_EVENT), repo.get(_FILLER), repo.get(_GREEN_EVENT)] \
        + [repo.get(_FILLER)] * 15

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-028"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (緑イベント) を選択
    _drain(st, [])
    assert any(c.card_id == _GREEN_EVENT for c in me.hand), \
        "人間が選んだ緑イベントが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-029 霜月コウ三郎: 【登場時】相手コスト2以下1枚レスト → 相手レストの元々コスト1以下1枚KO
# --------------------------------------------------------------------------- #
def test_op12_029_on_play_rest_then_ko_ai():
    """【登場時】相手コスト2以下1枚レスト → 相手レストの元々コスト1以下1枚KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    # 大きめ (cost2) を rest 対象、 既に rested の cost1 を KO 対象に
    rest_target = InPlay.of(repo.get(_C2), sickness=False)   # cost2 (<=2) active
    ko_target = InPlay.of(repo.get(_C1), sickness=False)     # cost1 (<=1)
    ko_target.rested = True
    opp.characters = [rest_target, ko_target]

    for prim in _eff(overlay, "OP12-029", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-029"), sickness=True))
    _drain(st, [0])

    assert ko_target not in opp.characters, \
        "相手レストの元々コスト1以下キャラが KO されていない"


def test_op12_029_on_play_human_rest_pick():
    """人間 + 相手コスト2以下複数 → レスト対象の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_C2), sickness=False)   # cost2
    b = InPlay.of(repo.get(_C1), sickness=False)   # cost1
    opp.characters = [a, b]

    # 第1段 (rest one_opponent_character_cost_le_2cost) を実行
    execute_effect(_eff(overlay, "OP12-029", "on_play")["do"][0],
                   st, me, opp, InPlay.of(repo.get("OP12-029"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert a.rested is True, "人間が選んだ相手キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP12-030 ジュラキュール・ミホーク: 【登場時】自ドン4までアクティブに
# --------------------------------------------------------------------------- #
def test_op12_030_on_play_untap_don_ai():
    """【登場時】自分のレストドン4枚をアクティブにする (untap_don 4)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 5
    me.don_active = 0

    for prim in _eff(overlay, "OP12-030", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-030"), sickness=True))

    assert me.don_active == 4, f"レストドン4枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"レストドンが4枚消費されるべき: {me.don_rested}"


def test_op12_030_on_play_untap_don_capped():
    """レストドンが4未満 (=2) なら ある分 (2枚) だけアクティブになる (最大4)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.don_active = 0

    for prim in _eff(overlay, "OP12-030", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-030"), sickness=True))
    assert me.don_active == 2, f"手持ちレストドン分だけアクティブになるべき: {me.don_active}"
    assert me.don_rested == 0, "レストドンが尽きるべき"


# --------------------------------------------------------------------------- #
#  OP12-031 たしぎ: 【登場時】相手の元々コスト6以下キャラ1枚レスト
# --------------------------------------------------------------------------- #
def test_op12_031_on_play_rest_ai():
    """【登場時】相手の元々コスト6以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_C2), sickness=False)  # cost2 (<=6)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP12-031", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-031"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "登場時に相手キャラがレストされていない"


def test_op12_031_on_play_rest_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_C2), sickness=False)
    b = InPlay.of(repo.get(_C1), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP12-031", "on_play")["do"][0],
                   st, me, opp, InPlay.of(repo.get("OP12-031"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP12-033 ヘルメッポ: 【ブロッカー】【ブロック時】相手コスト5以下キャラ1枚レスト
# --------------------------------------------------------------------------- #
def test_op12_033_on_block_rest_ai():
    """【ブロック時】相手コスト5以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    helmeppo = InPlay.of(repo.get("OP12-033"), sickness=False)
    me.characters = [helmeppo]
    victim = InPlay.of(repo.get(_C2), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP12-033", "on_block")["do"]:
        execute_effect(prim, st, me, opp, helmeppo)
    _drain(st, [0])
    assert victim.rested is True, "ブロック時に相手キャラがレストされていない"


def test_op12_033_on_block_rest_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    helmeppo = InPlay.of(repo.get("OP12-033"), sickness=False)
    me.characters = [helmeppo]
    a = InPlay.of(repo.get(_C2), sickness=False)
    b = InPlay.of(repo.get(_C1), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP12-033", "on_block")["do"][0],
                   st, me, opp, helmeppo)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP12-037 鬼気 九刀流 阿修羅 抜剣 亡者戯 (EVENT):
#     【メイン】相手のキャラかドン合計2までレスト /【カウンター】自リーダー +3000
# --------------------------------------------------------------------------- #
def test_op12_037_main_rest_two_ai():
    """【メイン】相手キャラ2体をレスト (キャラかドン合計2、 opp don=0 なので両方キャラ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 0  # ドン対象を無くしキャラに限定
    a = InPlay.of(repo.get(_C2), sickness=False)
    b = InPlay.of(repo.get(_C1), sickness=False)
    opp.characters = [a, b]

    for prim in _eff(overlay, "OP12-037", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert a.rested is True and b.rested is True, \
        "相手キャラ2体がレストされていない"


def test_op12_037_counter_pump_leader_ai():
    """【カウンター】自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    counter = _eff(overlay, "OP12-037", "counter")
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP12-038 二刀流 居合 羅生門 (EVENT):
#     【メイン】相手レストの元々コスト4以下キャラ2枚KO /【カウンター】自リーダー +3000
# --------------------------------------------------------------------------- #
def test_op12_038_main_ko_two_rested_ai():
    """【メイン】相手レストの元々コスト4以下キャラ2枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_C2), sickness=False)   # cost2 (<=4)
    b = InPlay.of(repo.get(_C1), sickness=False)   # cost1 (<=4)
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    for prim in _eff(overlay, "OP12-038", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert a not in opp.characters and b not in opp.characters, \
        "相手レストのコスト4以下キャラ2体が KO されていない"


def test_op12_038_main_ko_ignores_active():
    """アクティブ (非レスト) の相手キャラは 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    active = InPlay.of(repo.get(_C2), sickness=False)  # active = 対象外
    opp.characters = [active]

    for prim in _eff(overlay, "OP12-038", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert active in opp.characters, "アクティブなキャラは KO されてはいけない (対象外)"


def test_op12_038_counter_pump_leader_ai():
    """【カウンター】自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP12-038", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP12-039 ルフィは海賊王になる男だ!!! (EVENT):
#     【メイン】ゾロならリーダーをアクティブに /【トリガー】自リーダーかキャラ +1000
# --------------------------------------------------------------------------- #
def test_op12_039_main_untap_leader_ai():
    """【メイン】自リーダー (ロロノア・ゾロ) をアクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZORO_G, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True  # レスト状態から

    main = _eff(overlay, "OP12-039", "main")
    assert main.get("if", {}).get("leader_name") == "ロロノア・ゾロ", \
        "overlay の リーダー名ゲート leader_name=ロロノア・ゾロ が無い"
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.rested is False, "メインで自リーダーがアクティブになっていない"


def test_op12_039_trigger_pump_ai():
    """【トリガー】自リーダーかキャラ1枚を このターン中 パワー+1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZORO_G, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP12-039", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    # リーダーのみの盤面なら リーダーに +1000 が乗る
    assert me.leader.power == power_before + 1000, \
        f"トリガーの +1000 が自リーダーに反映されていない: {me.leader.power}"


def test_op12_039_trigger_pump_human_pick():
    """人間 + 自リーダー+キャラ → +1000 対象の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZORO_G, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_C2), sickness=False)
    me.characters = [friend]

    execute_effect(_eff(overlay, "OP12-039", "trigger")["do"][0],
                   st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    fi = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [fi])
    assert friend.power == friend_before + 1000, \
        "人間が選んだキャラに +1000 が反映されていない"
