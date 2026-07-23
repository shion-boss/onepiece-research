# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 060):
OP05-075 / OP05-076 / OP05-078 / OP05-079 / OP05-080 / OP05-081 /
OP05-084 / OP05-085 / OP05-086 / OP05-087 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_059.py と同一方針):
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
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 単色)
_NAMI = "OP01-016"             # ナミ cost1 power2000
_RED_C2 = "ST01-004"           # サンジ cost2 power4000 (デッキ/汎用フィラー)
_RED_C3 = "EB02-003"           # トニートニー・チョッパー cost3 power3000
_ISSHO_C6 = "OP05-042"         # イッショウ cost6 power6000
_BW_C2 = "EB03-047"            # ミス・バレンタイン cost2 B・W (play_from_hand 対象)
_BW_C3 = "EB01-034"            # ミス・ウェンズデー cost3 B・W (play_from_hand 対象)
_KID_C5 = "OP05-074"           # ユースタス・キッド 紫 cost5 キッド海賊団 (power_pump 対象)
_MUGI_C3 = "OP05-067"          # ゾロ十郎 紫 cost3 麦わらの一味 (search 対象)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_RED_C2)] * 30
    p1.deck = [repo.get(_RED_C2)] * 30
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
def test_all_wave60_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-075", "OP05-076", "OP05-078", "OP05-079", "OP05-080",
           "OP05-081", "OP05-084", "OP05-085", "OP05-086", "OP05-087"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-075 Mr.1(ダズ・ボーネス) (CHARACTER 紫 cost1 power1000 B・W):
#    【相手のアタック時】【ターン1回】ドン!!-1：自分の手札からコスト3以下の
#      特徴《B・W》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op05_075_opp_attack_play_from_hand_ai():
    """相手のアタック時 (AI): 手札の B・W (cost3以下) キャラを1体登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_BW_C2)]  # B・W cost2 → 対象
    chars_before = len(me.characters)
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP05-075", "opp_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-075"), sickness=False))

    assert len(me.characters) == chars_before + 1, "B・W キャラが登場していない"
    assert any(c.card.card_id == _BW_C2 for c in me.characters), \
        "手札の B・W キャラが場に出ていない"
    assert len(me.hand) == hand_before - 1, "登場でコスト分の手札が減っていない"


def test_op05_075_opp_attack_no_bw_in_hand():
    """手札に B・W cost3以下 が無ければ登場は起きない (不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_ISSHO_C6)]  # cost6 → 対象外 (B・W でもない)
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP05-075", "opp_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-075"), sickness=False))

    assert len(me.characters) == chars_before, "対象外なのにキャラが登場した"


def test_op05_075_opp_attack_human_play_pick():
    """相手のアタック時 (人間): 手札に B・W 複数 → play_from_hand_pick modal → 1体登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_BW_C2), repo.get(_BW_C3)]  # B・W cost2 / cost3 の 2 候補

    for prim in _do(overlay, "OP05-075", "opp_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-075"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2枚でない: {len(cands)}"

    # cost3 (= _BW_C3) を 選んで 登場
    pick = next(i for i, c in enumerate(cands) if c["card_id"] == _BW_C3)
    resolve_pending_choice(st, [cands[pick]["hand_idx"]])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id == _BW_C3 for c in me.characters), \
        "人間が選んだ B・W キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP05-076 海は海賊が相手だ!!! (EVENT 紫 cost1 ワノ国):
#    【メイン】自分のデッキの上から3枚を見て、特徴《麦わらの一味》か《キッド海賊団》か
#      《ハートの海賊団》を持つカード1枚までを公開し、手札に加える。残りをデッキの下に。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op05_076_main_search_ai():
    """メイン (AI): 上3枚に該当特徴カードを仕込む → 手札に加わり、 残りはデッキ下。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # デッキ上3枚に 麦わらの一味 (ゾロ十郎) を1枚だけ仕込む。 他は該当特徴を持たない
    # 中立フィラー (_ISSHO_C6 = 海軍) にする (= _RED_C2 は 麦わらの一味 なので誤 hit する)。
    neutral = repo.get(_ISSHO_C6)  # 海軍 (麦わら/キッド/ハート いずれも持たない)
    me.deck = [neutral, repo.get(_MUGI_C3), neutral] + [neutral] * 27
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP05-076", "main"):
        execute_effect(prim, st, me, opp, None)

    assert _MUGI_C3 in {c.card_id for c in me.hand}, \
        "該当特徴カードが手札に加わっていない"
    assert len(me.deck) == deck_before - 1, \
        f"デッキが1枚 (手札へ) 減っていない: {len(me.deck)} (before {deck_before})"


def test_op05_076_main_human_search_modal():
    """メイン (人間): 該当カードあり → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_MUGI_C3)] + [repo.get(_RED_C2)] * 29

    for prim in _do(overlay, "OP05-076", "main"):
        execute_effect(prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 該当カードで search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"


def test_op05_076_has_trigger_effect():
    """【トリガー】が overlay に登録され、 fire_self_main で自身のメインを発動する構造。"""
    overlay = _overlay()
    trig = _eff(overlay, "OP05-076", "trigger")
    assert any("fire_self_main" in p for p in trig["do"]), \
        "トリガーが fire_self_main を含まない"


# --------------------------------------------------------------------------- #
#  OP05-078 磁気魔人 (EVENT 紫 cost2 キッド海賊団):
#    【メイン】ドン!!-1：自分の特徴《キッド海賊団》を持つ、リーダーかキャラ1枚までを、
#      このターン中、パワー+5000。
#    【トリガー】ドン!!デッキからドン!!1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op05_078_main_power_pump_ai():
    """メイン (AI): 自分の キッド海賊団 キャラ1体を このターン中 パワー+5000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    kid = InPlay.of(repo.get(_KID_C5), sickness=False)  # キッド海賊団 power6000
    me.characters = [kid]

    power_before = kid.power
    for prim in _do(overlay, "OP05-078", "main"):
        execute_effect(prim, st, me, opp, None)

    assert kid.power == power_before + 5000, \
        f"キッド海賊団キャラに +5000 が反映されていない: {kid.power} (before {power_before})"


def test_op05_078_main_human_target_pick():
    """メイン (人間): キッド海賊団 キャラ複数 → target_pick modal → 選んだ1体に +5000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_KID_C5), sickness=False)
    b = InPlay.of(repo.get(_KID_C5), sickness=False)
    me.characters = [a, b]

    for prim in _do(overlay, "OP05-078", "main"):
        execute_effect(prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before + 5000, "人間が選んだキャラに +5000 が反映されていない"


def test_op05_078_trigger_add_don():
    """トリガー (AI): ドンデッキからドン1枚をアクティブで追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    for prim in _do(overlay, "OP05-078", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == active_before + 1, \
        f"アクティブドンが+1されていない: {me.don_active} (before {active_before})"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキ残数が-1されていない"


# --------------------------------------------------------------------------- #
#  OP05-079 ヴィオラ (CHARACTER 黒 cost2 power3000 ドレスローザ):
#    【登場時】相手は自身のトラッシュのカード3枚を、好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_079_on_play_opp_trash_to_deck():
    """登場時 (AI): 相手トラッシュ3枚が相手デッキ下に置かれる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.trash = [repo.get(_NAMI), repo.get(_RED_C2), repo.get(_RED_C3)]
    opp_deck_before = len(opp.deck)

    for prim in _do(overlay, "OP05-079", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-079"), sickness=False))

    assert len(opp.trash) == 0, "相手トラッシュ3枚が除かれていない"
    assert len(opp.deck) == opp_deck_before + 3, \
        f"相手デッキが3枚増えていない: {len(opp.deck)} (before {opp_deck_before})"


def test_op05_079_on_play_empty_trash_noop():
    """相手トラッシュが空なら何も起きない (不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.trash = []
    opp_deck_before = len(opp.deck)

    for prim in _do(overlay, "OP05-079", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-079"), sickness=False))

    assert len(opp.deck) == opp_deck_before, "空トラッシュなのにデッキが増えた"


# --------------------------------------------------------------------------- #
#  OP05-080 エリザベローⅡ世 (CHARACTER 黒 cost4 power5000 プロデンス王国/ドレスローザ):
#    【アタック時】【ターン1回】自分のトラッシュのカード20枚をデッキに戻しシャッフル
#      できる：このキャラは、このバトル中、【ダブルアタック】を得て、パワー+10000。
# --------------------------------------------------------------------------- #
def test_op05_080_on_attack_optional_cost_ai():
    """アタック時 (AI): トラッシュ20枚戻し → 自身が【ダブルアタック】+ パワー+10000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    eliza = InPlay.of(repo.get("OP05-080"), sickness=False)  # power5000
    me.characters = [eliza]
    me.trash = [repo.get(_RED_C2)] * 20  # コスト分のトラッシュ

    power_before = eliza.power
    for prim in _do(overlay, "OP05-080", "on_attack"):
        execute_effect(prim, st, me, opp, eliza)

    assert "ダブルアタック" in eliza.granted_keywords, "【ダブルアタック】が付与されていない"
    assert eliza.power == power_before + 10000, \
        f"パワー+10000 が反映されていない: {eliza.power} (before {power_before})"


def test_op05_080_on_attack_cost_unpayable():
    """トラッシュが20枚未満ならコスト不能 → 効果不発 (キーワードもパンプも無し)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    eliza = InPlay.of(repo.get("OP05-080"), sickness=False)
    me.characters = [eliza]
    me.trash = [repo.get(_RED_C2)] * 19  # 20枚に満たない

    power_before = eliza.power
    for prim in _do(overlay, "OP05-080", "on_attack"):
        execute_effect(prim, st, me, opp, eliza)

    assert "ダブルアタック" not in eliza.granted_keywords, \
        "コスト不能なのに【ダブルアタック】が付与された"
    assert eliza.power == power_before, "コスト不能なのにパンプされた"


def test_op05_080_on_attack_human_confirm():
    """アタック時 (人間): optional_cost_confirm modal → pay で 効果発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    eliza = InPlay.of(repo.get("OP05-080"), sickness=False)
    me.characters = [eliza]
    me.trash = [repo.get(_RED_C2)] * 20

    power_before = eliza.power
    for prim in _do(overlay, "OP05-080", "on_attack"):
        execute_effect(prim, st, me, opp, eliza)

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # pay
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert "ダブルアタック" in eliza.granted_keywords, "支払い後に【ダブルアタック】が付与されていない"
    assert eliza.power == power_before + 10000, "支払い後にパワー+10000が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-081 片足の兵隊 (CHARACTER 黒 cost2 ドレスローザ):
#    【起動メイン】このキャラをトラッシュに置くことができる：相手のキャラ1枚までを、
#      このターン中、コスト-3。
# --------------------------------------------------------------------------- #
def test_op05_081_activate_main_cost_minus_ai():
    """起動メイン (AI): 自身をトラッシュに置き → 相手キャラ1体を このターン中 コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    soldier = InPlay.of(repo.get("OP05-081"), sickness=False)
    me.characters = [soldier]
    victim = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6
    opp.characters = [victim]

    cost_before = victim.base_cost
    options = list_activate_main_effects(st, me, overlay)
    soldier_opts = [(src, eff) for (src, eff) in options
                    if src.card.card_id == "OP05-081"]
    assert len(soldier_opts) == 1, \
        f"OP05-081 の起動メインが legal に出ない: {len(soldier_opts)}"
    fire_activate_main(st, me, opp, *soldier_opts[0])

    assert soldier not in me.characters, "コストで片足の兵隊がトラッシュに置かれていない"
    assert victim.base_cost == cost_before - 3, \
        f"相手キャラ コスト-3 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op05_081_activate_main_human_pick():
    """起動メイン (人間): 相手キャラ複数 → target_pick modal → 選んだ1体に コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    soldier = InPlay.of(repo.get("OP05-081"), sickness=False)
    me.characters = [soldier]
    a = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6
    b = InPlay.of(repo.get(_RED_C3), sickness=False)    # cost3
    opp.characters = [a, b]

    src, eff = [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "OP05-081"][0]
    fire_activate_main(st, me, opp, src, eff)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.base_cost
    resolve_pending_choice(st, [a_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [a_idx])
        guard += 1
    assert a.base_cost == a_before - 3, "人間が選んだ相手キャラに コスト-3 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-084 チャルロス聖 (CHARACTER 黒 cost3 天竜人):
#    【自分のターン中】自分の場のキャラが、特徴《天竜人》を持つキャラのみの場合、
#      相手のキャラすべてをコスト-4。
# --------------------------------------------------------------------------- #
def test_op05_084_static_opp_cost_minus4():
    """静的 (自ターン + 自場天竜人のみ): 相手キャラすべてを コスト-4。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)  # turn_player=0 = 自分のターン
    me, opp = st.players[0], st.players[1]
    charloss = InPlay.of(repo.get("OP05-084"), sickness=False)  # 天竜人
    me.characters = [charloss]  # 自場は天竜人のみ
    v1 = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6
    v2 = InPlay.of(repo.get(_RED_C3), sickness=False)    # cost3
    opp.characters = [v1, v2]

    eff = _eff(overlay, "OP05-084", "on_attached_don")
    assert eff.get("if", {}).get("self_turn") is True, "overlay の self_turn 条件が無い"
    assert eval_condition(eff.get("if", {}), st, me), \
        "自ターン + 自場天竜人のみで条件成立のはず"

    evaluate_static_effects(st, overlay)

    assert v1.base_cost == 6 - 4, f"相手 cost6 が -4 されていない: {v1.base_cost}"
    assert v2.base_cost == max(0, 3 - 4), f"相手 cost3 が -4 (下限0) されていない: {v2.base_cost}"


def test_op05_084_gate_not_met_non_tenryu_on_board():
    """自場に非天竜人キャラが居ると self_chara_only_feature が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    charloss = InPlay.of(repo.get("OP05-084"), sickness=False)
    intruder = InPlay.of(repo.get(_NAMI), sickness=False)  # 天竜人でない
    me.characters = [charloss, intruder]

    eff = _eff(overlay, "OP05-084", "on_attached_don")
    assert not eval_condition(eff.get("if", {}), st, me), \
        "非天竜人が居るのに条件成立している"


# --------------------------------------------------------------------------- #
#  OP05-085 ネフェルタリ・コブラ (CHARACTER 黒 cost2 power1000 アラバスタ王国):
#    【ブロッカー】【登場時】自分のデッキの上から1枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op05_085_on_play_mill_self_top():
    """登場時 (AI): 自デッキ上1枚をトラッシュに置く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_NAMI)] + [repo.get(_RED_C2)] * 29
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    for prim in _do(overlay, "OP05-085", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-085"), sickness=False))

    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"
    assert len(me.trash) == trash_before + 1, "トラッシュが1枚増えていない"
    assert me.trash[-1].card_id == _NAMI, "デッキ上の1枚がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP05-086 ネフェルタリ・ビビ (CHARACTER 黒 cost1 power1000 アラバスタ王国):
#    自分のトラッシュが10枚以上ある場合、このキャラは【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op05_086_gives_blocker_when_trash_ge10():
    """自トラッシュ10枚以上 → 自身が【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_RED_C2)] * 10  # トラッシュ10枚
    bibi = InPlay.of(repo.get("OP05-086"), sickness=False)
    me.characters = [bibi]

    eff = _eff(overlay, "OP05-086", "on_attached_don")
    assert eff.get("if", {}).get("self_trash_count_ge") == 10, \
        "overlay の self_trash_count_ge 10 が無い"
    assert eval_condition(eff.get("if", {}), st, me), "トラッシュ10枚で条件成立のはず"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, bibi)

    assert bibi.is_blocker_now, "【ブロッカー】が付与されていない"


def test_op05_086_gate_not_met_trash9():
    """トラッシュ9枚では self_trash_count_ge 10 が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    me.trash = [repo.get(_RED_C2)] * 9
    eff = _eff(overlay, "OP05-086", "on_attached_don")
    assert not eval_condition(eff.get("if", {}), st, me), "トラッシュ9枚では条件不成立のはず"


# --------------------------------------------------------------------------- #
#  OP05-087 ハクバ (CHARACTER 黒 cost5 power6000 ドレスローザ/美しき海賊団):
#    【ドン!!×1】【アタック時】このキャラ以外の自分のキャラ1枚をKOできる：
#      相手のキャラ1枚までを、このターン中、コスト-5。
# --------------------------------------------------------------------------- #
def test_op05_087_on_attack_ko_cost_then_ai():
    """アタック時 (AI、 ドン1ゲート): 自キャラ1体をKO → 相手キャラ1体を コスト-5。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    hakuba = InPlay.of(repo.get("OP05-087"), sickness=False)
    hakuba.attached_dons = 1  # ドン1ゲート成立
    fodder = InPlay.of(repo.get(_NAMI), sickness=False)  # KO 生贄
    me.characters = [hakuba, fodder]
    victim = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6
    opp.characters = [victim]

    eff = _eff(overlay, "OP05-087", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    assert eval_condition(eff.get("if", {}), st, me, hakuba), \
        "ドン1で条件成立のはず"

    cost_before = victim.base_cost
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, hakuba)

    assert fodder not in me.characters, "コストで自キャラ (このキャラ以外) がKOされていない"
    assert hakuba in me.characters, "ハクバ自身はKOコスト対象外なので場に残るべき"
    assert victim.base_cost == cost_before - 5, \
        f"相手キャラ コスト-5 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op05_087_on_attack_no_other_chara_unpayable():
    """このキャラ以外の自キャラが居なければコスト不能 → コスト-5 は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    hakuba = InPlay.of(repo.get("OP05-087"), sickness=False)
    hakuba.attached_dons = 1
    me.characters = [hakuba]  # 生贄になる他キャラが居ない
    victim = InPlay.of(repo.get(_ISSHO_C6), sickness=False)
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _do(overlay, "OP05-087", "on_attack"):
        execute_effect(prim, st, me, opp, hakuba)

    assert victim.base_cost == cost_before, "コスト不能なのに相手キャラが コスト-5 された"


def test_op05_087_on_attack_human_confirm():
    """アタック時 (人間): optional_cost_confirm modal → pay で 効果発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hakuba = InPlay.of(repo.get("OP05-087"), sickness=False)
    hakuba.attached_dons = 1
    fodder = InPlay.of(repo.get(_NAMI), sickness=False)
    me.characters = [hakuba, fodder]
    victim = InPlay.of(repo.get(_ISSHO_C6), sickness=False)
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _do(overlay, "OP05-087", "on_attack"):
        execute_effect(prim, st, me, opp, hakuba)

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # pay → コスト (自キャラKO) 実行後、 cost_minus の対象選択へ
    assert fodder not in me.characters, "支払い後に生贄キャラがKOされていない"
    # cost_minus (相手キャラ) の target_pick modal を 対象1体で解決
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"支払い後に cost_minus の target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    v_idx = next(i for i, c in enumerate(cands) if c["iid"] == victim.instance_id)
    resolve_pending_choice(st, [v_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert victim.base_cost == cost_before - 5, "支払い後に相手キャラ コスト-5 が反映されていない"
