# -*- coding: utf-8 -*-
"""OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 065):
OP06-022 / OP06-024 / OP06-025 / OP06-026 / OP06-027 / OP06-028 /
OP06-029 / OP06-030 / OP06-031 / OP06-033 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_064.py と同一方針):
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

# よく使うテスト用カード (テキストの前提固定)
_LEADER = "OP01-001"      # ロロノア・ゾロ (赤、 超新星/麦わらの一味、 汎用リーダー)
_HODY = "OP06-020"        # ホーディ・ジョーンズ (緑 リーダー、 魚人族/新魚人海賊団)
_FILLER = "OP01-013"      # サンジ cost2 power3000 麦わらの一味 (汎用フィラー / cost<=3 対象)
_NAMI = "OP01-016"        # ナミ cost1 power2000 (cost<=3 対象)
_FISH1 = "OP16-023"       # アーロン cost1 緑 attr斬 魚人族 (vanilla) — 魚人族 & 斬 両用途
_FISH2 = "OP07-027"       # ジンベエ cost4 魚人族 (vanilla) — 魚人族 cost<=4 種
_FISH3 = "OP05-012"       # ハック cost3 魚人族/革命軍 (vanilla) — 魚人族 cost<=3 種
_SLASH2 = "OP12-035"      # モーガン cost3 緑 attr斬 (vanilla) — 斬 cost<=4 種


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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave65_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-022", "OP06-024", "OP06-025", "OP06-026", "OP06-027",
           "OP06-028", "OP06-029", "OP06-030", "OP06-031", "OP06-033"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-022 ヤマト (LEADER 緑/黄 ワノ国):
#    【起動メイン】【ターン1回】相手のライフが3枚以下の場合、自分のキャラ1枚に
#      レストのドン!!2枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op06_022_activate_main_attach_rested_don_ai():
    """起動メイン (AI): 相手ライフ3以下 → 自キャラ1枚にレストドン2枚付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-022", overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get(_FISH1), sickness=False)
    me.characters = [target]
    me.don_rested = 2
    opp.life = [repo.get(_FILLER)] * 3  # ライフ 3 (= 条件成立)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-022"]
    assert len(opts) == 1, f"OP06-022 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])

    assert target.attached_dons == 2, \
        f"自キャラにレストドン2枚が付与されていない: {target.attached_dons}"
    assert me.don_rested == 0, "レストドンが2枚消費されるべき"

    # 【ターン1回】: 再発動不可
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP06-022"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op06_022_activate_main_gated_by_opp_life():
    """相手ライフが4枚 (= 3以下でない) なら 起動メインは legal に出ない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-022", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_FISH1), sickness=False)]
    me.don_rested = 2
    opp.life = [repo.get(_FILLER)] * 4  # ライフ 4 (= 条件不成立)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-022"]
    assert len(opts) == 0, "相手ライフ4で条件不成立なのに起動メインが legal に出た"


def test_op06_022_activate_main_human_target_pick():
    """起動メイン (人間): 自キャラ複数 → target_pick modal で選択して2ドン付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-022", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FISH1), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [a, b]
    me.don_rested = 2
    opp.life = [repo.get(_FILLER)] * 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-022"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"自キャラ候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert b.attached_dons == 2, "人間が選んだキャラにレストドン2枚が付与されていない"
    assert a.attached_dons == 0, "選ばなかったキャラにはドンが付かないべき"


# --------------------------------------------------------------------------- #
#  OP06-024 イカロス・ムッヒ (CHARACTER 緑 cost5 魚人族/新魚人海賊団):
#    【登場時】自分のリーダーが特徴《新魚人海賊団》を持つ場合、自分の手札から
#      コスト4以下の特徴《魚人族》を持つキャラカード1枚までを、登場させる。
#      その後、自分のライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op06_024_on_play_play_fishman_and_life_ai():
    """登場時 (AI): 新魚人海賊団 leader 下 → 手札の魚人族 cost4以下を登場 + ライフ1手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HODY, overlay)  # 新魚人海賊団 leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH1)]  # アーロン 魚人族 cost1
    me.life = [repo.get(_FILLER)] * 3
    life_before = len(me.life)

    for prim in _do(overlay, "OP06-024", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-024"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == _FISH1 for c in me.characters), \
        "手札から魚人族 cost4以下キャラが登場していない"
    assert len(me.life) == life_before - 1, "ライフが1枚手札に加わっていない"


def test_op06_024_on_play_human_play_pick():
    """登場時 (人間): 手札に魚人族 cost4以下 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HODY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH1), repo.get(_FISH2)]  # 魚人族 2 種 (cost1 / cost4)
    me.life = [repo.get(_FILLER)] * 3

    execute_effect(_do(overlay, "OP06-024", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-024"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in (_FISH1, _FISH2) for c in me.characters), \
        "人間が選んだ魚人族キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-025 ケイミー (CHARACTER 緑 cost1 人魚族):
#    【登場時】自分のデッキの上から4枚を見て、「ケイミ―」以外の特徴《魚人族》か
#      《人魚族》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな
#      順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_025_on_play_search_fishman_ai():
    """登場時 (AI): デッキ上4枚から魚人族カード1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FISH1)] + [repo.get(_FILLER)] * 10  # 上に魚人族 1 枚

    for prim in _do(overlay, "OP06-025", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-025"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card_id == _FISH1 for c in me.hand), \
        "デッキ上4枚から魚人族カードが手札に加わっていない"


def test_op06_025_on_play_search_human_pick():
    """登場時 (人間): 魚人族 候補が複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 上4枚のうち 2 枚を魚人族に
    me.deck = [repo.get(_FISH1), repo.get(_FILLER), repo.get(_FISH2)] \
        + [repo.get(_FILLER)] * 10

    execute_effect(_do(overlay, "OP06-025", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-025"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (アーロン) を選択
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id in (_FISH1, _FISH2) for c in me.hand), \
        "人間が選んだ魚人族カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-026 コウシロウ (CHARACTER 緑 cost3 シモツキ村):
#    【登場時】自分のコスト4以下の属性(斬)を持つキャラ1枚までを、アクティブにする。
#      その後、自分は、このターン中、リーダーにアタックできない。
# --------------------------------------------------------------------------- #
def test_op06_026_on_play_untap_and_block_ai():
    """登場時 (AI): 斬 cost4以下キャラをアクティブ化 + 自リーダーアタック禁止フラグ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    slasher = InPlay.of(repo.get(_FISH1), sickness=False)  # アーロン 斬 cost1
    slasher.rested = True
    me.characters = [slasher]

    for prim in _do(overlay, "OP06-026", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-026"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert slasher.rested is False, "斬 cost4以下キャラがアクティブ化されていない"
    assert me.cannot_attack_leader_until_turn_end is True, \
        "「リーダーにアタックできない」フラグが立っていない"


def test_op06_026_on_play_human_untap_pick():
    """登場時 (人間): 斬 cost4以下キャラが複数 → target_pick modal で選択してアクティブ化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FISH1), sickness=False)   # 斬 cost1
    b = InPlay.of(repo.get(_SLASH2), sickness=False)  # 斬 cost3
    a.rested = True
    b.rested = True
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP06-026", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-026"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"斬 候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is False, "人間が選んだキャラがアクティブ化されていない"
    assert a.rested is True, "選ばなかったキャラはレストのままであるべき"


# --------------------------------------------------------------------------- #
#  OP06-027 ジャイロ (CHARACTER 緑 cost1 ジャイロ海賊団):
#    【KO時】相手のコスト3以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op06_027_on_ko_rest_opp_cost_le3_ai():
    """KO時 (AI): 相手のコスト3以下キャラ1枚をレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-027", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-027"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim.rested is True, "KO時に相手のコスト3以下キャラがレストされていない"


def test_op06_027_on_ko_human_rest_pick():
    """KO時 (人間): 相手コスト3以下キャラ複数 → target_pick modal で選択してレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP06-027", "on_ko")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-027"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはアクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  OP06-028 ゼオ (CHARACTER 緑 cost2 魚人族/新魚人海賊団):
#    【ドン!!×1】【アタック時】自分のリーダーが特徴《新魚人海賊団》を持つ場合、
#      自分のドン!!1枚までをアクティブにし、このキャラは、このターン中、パワー+1000。
#      その後、自分のライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op06_028_on_attack_untap_don_pump_life_ai():
    """アタック時 (AI): ドン1アクティブ化 + 自身 +1000 + ライフ1手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HODY, overlay)  # 新魚人海賊団 leader
    me, opp = st.players[0], st.players[1]
    zeo = InPlay.of(repo.get("OP06-028"), sickness=False)
    zeo.attached_dons = 1  # ドン!!×1 ゲート
    me.characters = [zeo]
    me.don_rested = 1  # untap_don 供給源
    me.life = [repo.get(_FILLER)] * 2
    power_before = zeo.power
    life_before = len(me.life)

    for prim in _do(overlay, "OP06-028", "on_attack"):
        execute_effect(prim, st, me, opp, zeo)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert zeo.power == power_before + 1000, \
        f"アタック時 自己 +1000 が反映されていない: {zeo.power} (before {power_before})"
    assert me.don_rested == 0, "レストドン1枚がアクティブ化されるべき"
    assert len(me.life) == life_before - 1, "ライフが1枚手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-029 ダルマ (CHARACTER 緑 cost3 魚人族/新魚人海賊団):
#    【ドン!!×1】【アタック時】【ターン1回】自分のリーダーが特徴《新魚人海賊団》を
#      持つ場合、このキャラをアクティブにし、このキャラは、このターン中、パワー+1000。
#      その後、自分のライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op06_029_on_attack_untap_self_pump_life_ai():
    """アタック時 (AI): 自身をアクティブ化 + 自身 +1000 + ライフ1手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HODY, overlay)
    me, opp = st.players[0], st.players[1]
    daruma = InPlay.of(repo.get("OP06-029"), sickness=False)
    daruma.attached_dons = 1
    daruma.rested = True  # アクティブ化を検出するため rested から開始
    me.characters = [daruma]
    me.life = [repo.get(_FILLER)] * 2
    power_before = daruma.power
    life_before = len(me.life)

    for prim in _do(overlay, "OP06-029", "on_attack"):
        execute_effect(prim, st, me, opp, daruma)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert daruma.rested is False, "アタック時に自身がアクティブ化されていない"
    assert daruma.power == power_before + 1000, \
        f"アタック時 自己 +1000 が反映されていない: {daruma.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "ライフが1枚手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-030 ドスン (CHARACTER 緑 cost3 魚人族/新魚人海賊団):
#    【アタック時】自分のリーダーが特徴《新魚人海賊団》を持つ場合、このキャラは、
#      次の自分のターン開始時まで、バトルでKOされずパワー+2000。その後、自分の
#      ライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op06_030_on_attack_ko_immune_pump_life_ai():
    """アタック時 (AI): 次自ターン開始まで バトルKO耐性 + 自身 +2000 + ライフ1手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HODY, overlay)
    me, opp = st.players[0], st.players[1]
    dosun = InPlay.of(repo.get("OP06-030"), sickness=False)
    me.characters = [dosun]
    me.life = [repo.get(_FILLER)] * 2
    power_before = dosun.power
    life_before = len(me.life)

    for prim in _do(overlay, "OP06-030", "on_attack"):
        execute_effect(prim, st, me, opp, dosun)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert dosun.power == power_before + 2000, \
        f"アタック時 自己 +2000 が反映されていない: {dosun.power} (before {power_before})"
    assert dosun.battle_ko_immune_through_opp_turn is True, \
        "「次の自分のターン開始時まで バトルKOされず」耐性が立っていない"
    assert len(me.life) == life_before - 1, "ライフが1枚手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-031 はっちゃん (CHARACTER 緑 cost4 魚人族/元アーロン一味):
#    【トリガー】自分の手札からコスト3以下の特徴《魚人族》か《人魚族》を持つ
#      キャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op06_031_trigger_play_fishman_ai():
    """トリガー (AI): 手札からコスト3以下の魚人族/人魚族キャラ1枚を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH1)]  # アーロン 魚人族 cost1

    for prim in _do(overlay, "OP06-031", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-031"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == _FISH1 for c in me.characters), \
        "トリガーで手札から魚人族 cost3以下キャラが登場していない"


def test_op06_031_trigger_human_play_pick():
    """トリガー (人間): 手札に魚人族/人魚族 cost3以下 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH1), repo.get(_FISH3)]  # 魚人族 cost1 / cost3

    execute_effect(_do(overlay, "OP06-031", "trigger")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-031"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in (_FISH1, _FISH3) for c in me.characters), \
        "人間が選んだ魚人族キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-033 バンダー・デッケン九世 (CHARACTER 緑 cost2 魚人族/フライング海賊団):
#    【登場時】自分の手札から特徴《魚人族》を持つカード1枚を捨てるか、自分の手札か
#      場の「方舟ノア」1枚をトラッシュに置くことができる：相手のレストのキャラ1枚
#      までを、KOする。
# --------------------------------------------------------------------------- #
def test_op06_033_on_play_choice_cost_ko_ai():
    """登場時 (AI): 魚人族捨てコストを払い → 相手のレストキャラ1枚をKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH1)]  # 魚人族 (捨てコスト用)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True  # レストのキャラ (= KO 対象条件)
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-033", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-033"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim not in opp.characters, \
        "魚人族捨てコストで相手のレストキャラがKOされていない"
    assert not any(c.card_id == _FISH1 for c in me.hand), \
        "捨てコストの魚人族カードが手札から消えていない"


def test_op06_033_on_play_choice_human_option_pick():
    """登場時 (人間): 択一コスト → option_pick modal が立ち、 選択して解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH1)]  # 魚人族 (option1 コスト)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP06-033", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-033"), sickness=False))

    assert st.pending_choice is not None, "人間 + 択一コストで option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [0])  # option1 (魚人族を捨てる) を選択
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert victim not in opp.characters, \
        "人間が選んだコスト支払後 相手のレストキャラがKOされていない"
