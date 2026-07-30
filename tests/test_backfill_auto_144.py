# -*- coding: utf-8 -*-
"""OP15 弾 効果 回帰テスト バックフィル (自動生成 wave 144):
OP15-078 / OP15-082 / OP15-083 / OP15-085 / OP15-087 /
OP15-088 / OP15-090 / OP15-091 / OP15-093 / OP15-094 の 10 枚。

目的 (= test_backfill_auto_001〜143.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op15_wave144_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-078", "OP15-082", "OP15-083", "OP15-085", "OP15-087",
           "OP15-088", "OP15-090", "OP15-091", "OP15-093", "OP15-094"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-078 万雷 (EVENT 紫):
#    【メイン】ドン‼-2：カード1枚を引く。その後、相手のパワー5000以下のキャラ1枚までを、
#      レストにする。
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+1000。その後、
#      自分の場のドン‼が6枚以下の場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op15_078_main_draw_and_rest_opp_le_5000_ai():
    """【メイン】1ドロー → 相手パワー5000以下1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000 ≤5000
    opp.characters = [victim]
    do, _ = _do(overlay, "OP15-078", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "メインの 1ドローが起きていない"
    assert len(me.hand) == 1, f"手札が1枚増えていない: {len(me.hand)}"
    assert victim.rested is True, "相手パワー5000以下キャラがレストされていない"


def test_op15_078_main_rest_over_5000_not_target():
    """相手パワー6000超のキャラは 対象外 → レストされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get("OP15-008"), sickness=False)  # power9000 (> 5000)
    opp.characters = [big]
    do, _ = _do(overlay, "OP15-078", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert big.rested is False, "パワー5000超のキャラがレストされてはいけない (対象外)"


def test_op15_078_main_rest_human_pick():
    """人間 + 相手パワー5000以下 複数 → target_pick modal → 選んだ1枚のみレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [a, b]
    do, _ = _do(overlay, "OP15-078", "main")
    # 先頭 draw を消化してから rest 対象選択 modal を立てる
    execute_effect(do[0], st, me, opp, None)
    _drain(st, [0])
    execute_effect(do[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


def test_op15_078_counter_pump_and_draw_when_don_le_6_ai():
    """【カウンター】自リーダー+1000 → 自場ドン6以下なら 1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.don_active = 6   # 6以下 → その後ドロー成立
    me.don_rested = 0
    power_before = me.leader.power
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-078", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 1000, \
        f"カウンターの +1000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.deck) == deck_before - 1, "自場ドン6以下なのに 1ドローが起きていない"


def test_op15_078_counter_no_draw_when_don_gt_6():
    """自場ドン7枚 (>6) では その後のドローは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.don_active = 7   # 7枚 → ドロー不成立
    me.don_rested = 0
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-078", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before, \
        f"自場ドン7枚でドローが起きてはいけない: deck={len(me.deck)} (before {deck_before})"


# --------------------------------------------------------------------------- #
#  OP15-082 シャーロット・ローラ (CHARACTER 黒 cost4 power5000):
#    【登場時】自分のデッキの上から3枚をトラッシュに置く。
#    【KO時】自分のトラッシュからコスト8以下のキャラカード1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_op15_082_on_play_mill_top_3_ai():
    """【登場時】自デッキ上3枚をトラッシュへ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP15-082", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-082"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 3, \
        f"デッキ上3枚がトラッシュに置かれていない: deck={len(me.deck)}"
    assert len(me.trash) == trash_before + 3, \
        f"トラッシュが3枚増えていない: trash={len(me.trash)}"


def test_op15_082_on_ko_trash_to_hand_char_le_8_ai():
    """【KO時】自トラッシュからコスト8以下のキャラ1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.trash = [repo.get("OP01-013")]  # サンジ cost2 (≤8) キャラ
    do, _ = _do(overlay, "OP15-082", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-082"), sickness=False))
    _drain(st, [0])
    assert any(c.card_id == "OP01-013" for c in me.hand), \
        "トラッシュのコスト8以下キャラが手札に加わっていない"


def test_op15_082_on_ko_trash_to_hand_human_context_auto():
    """人間文脈でも trash_to_hand は自動解決 (= modal 無し) で 1 枚だけ手札へ (crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.trash = [repo.get("OP01-013"), repo.get("OP01-016")]  # サンジ / ナミ (両方 ≤8)
    do, _ = _do(overlay, "OP15-082", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-082"), sickness=False))
    _drain(st, [0])
    # limit=1 なので 2 枚あっても 1 枚だけ手札へ (残り 1 枚はトラッシュ)
    assert len(me.hand) == 1, f"トラッシュから 1 枚だけ手札に加わるべき: {len(me.hand)}"
    assert len(me.trash) == 1, f"残り 1 枚はトラッシュに残るべき: {len(me.trash)}"


# --------------------------------------------------------------------------- #
#  OP15-083 スポイル (CHARACTER 黒 cost1):
#    【登場時】自分のデッキの上から3枚をトラッシュに置く。
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のトラッシュが15枚以上ある
#      場合、自分のリーダーかキャラ1枚にレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op15_083_on_play_mill_top_3_ai():
    """【登場時】自デッキ上3枚をトラッシュへ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-083", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-083"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 3, "デッキ上3枚がトラッシュに置かれていない"


def test_op15_083_activate_condition_trash_ge_15():
    """起動メイン条件: 自トラッシュ15枚以上で成立、 14枚では不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-083", "activate_main")
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.trash = [repo.get("OP01-016")] * 14
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "トラッシュ14枚で起動メイン条件が成立してはいけない"
    me.trash = [repo.get("OP01-016")] * 15
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "トラッシュ15枚で起動メイン条件が成立していない"


def test_op15_083_activate_attach_rested_don_ai():
    """起動メイン: 自身をトラッシュ (コスト) → 自リーダーにレストドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    spoil = InPlay.of(repo.get("OP15-083"), sickness=False)
    me.characters = [spoil]
    me.trash = [repo.get("OP01-016")] * 15  # 条件成立
    me.don_rested = 2  # レストドン供給源
    don_before = me.leader.attached_dons
    rested_before = me.don_rested

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-083"]
    assert len(opts) == 1, f"OP15-083 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert spoil not in me.characters, "コストで スポイル がトラッシュに置かれるべき"
    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  OP15-085 トニートニー・チョッパー (CHARACTER 黒 cost2 power2000):
#    【登場時】自分のデッキの上から3枚をトラッシュに置く。
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のリーダーが特徴
#      《麦わらの一味》を持つ場合、自分のトラッシュから「トニートニー・チョッパー」以外の
#      特徴《麦わらの一味》を持つキャラカード1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_op15_085_activate_condition_leader_strawhat():
    """起動メイン条件: 《麦わらの一味》リーダーで成立、 非該当で不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-085", "activate_main")
    st_ok = _state(repo, "EB02-010", overlay)  # モンキー・D・ルフィ (麦わらの一味)
    st_ng = _state(repo, "OP15-039", overlay)  # レベッカ (ドレスローザ = 非麦わらの一味)
    assert eval_condition(eff.get("if", {}), st_ok, st_ok.players[0]) is True, \
        "《麦わらの一味》リーダーで起動メイン条件が成立していない"
    assert eval_condition(eff.get("if", {}), st_ng, st_ng.players[0]) is False, \
        "非《麦わらの一味》リーダーで条件が成立してはいけない"


def test_op15_085_activate_trash_to_hand_strawhat_ai():
    """起動メイン: 自身をトラッシュ (コスト) → トラッシュの《麦わらの一味》キャラを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB02-010", overlay)  # 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]
    chopper = InPlay.of(repo.get("OP15-085"), sickness=False)
    me.characters = [chopper]
    me.hand = []
    me.trash = [repo.get("OP01-013")]  # サンジ (麦わらの一味, チョッパー以外)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-085"]
    assert len(opts) == 1, f"OP15-085 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert chopper not in me.characters, "コストで チョッパー がトラッシュに置かれるべき"
    assert any(c.card_id == "OP01-013" for c in me.hand), \
        "トラッシュの《麦わらの一味》キャラ (サンジ) が手札に加わっていない"


def test_op15_085_activate_human_context_auto():
    """人間文脈でも trash_to_hand は自動解決で 1 枚だけ手札へ (crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB02-010", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    chopper = InPlay.of(repo.get("OP15-085"), sickness=False)
    me.characters = [chopper]
    me.hand = []
    me.trash = [repo.get("OP01-013"), repo.get("OP01-016")]  # サンジ / ナミ (両方 麦わら)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-085"]
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    # limit=1 → 2 枚中 1 枚だけ手札へ。 チョッパー自身 (コストで trash 入り) は除外対象。
    assert len(me.hand) == 1, f"トラッシュから 1 枚だけ手札に加わるべき: {len(me.hand)}"
    assert not any(c.card_id == "OP15-085" for c in me.hand), \
        "チョッパー自身 (exclude_name) が手札に加わってはいけない"


# --------------------------------------------------------------------------- #
#  OP15-087 ニコ・ロビン (CHARACTER 黒 cost5 power7000):
#    自分のトラッシュが10枚以上ある場合、このキャラは【ブロッカー】を得る。
#    【登場時】カード2枚を引き、自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op15_087_on_play_draw2_discard2_ai():
    """【登場時】2ドロー → 手札2枚を捨てる (AI 自動)。 net 手札 ±0 / デッキ -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP15-087", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-087"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, f"2ドローが起きていない: deck={len(me.deck)}"
    assert len(me.hand) == 0, f"引いた2枚を捨てて手札±0 のはず: {len(me.hand)}"
    assert len(me.trash) == trash_before + 2, \
        f"捨てた2枚がトラッシュに行っていない: trash={len(me.trash)}"


def test_op15_087_static_blocker_when_trash_ge_10():
    """自トラッシュ10枚以上で【ブロッカー】を得る、 9枚では得ない (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    robin = InPlay.of(repo.get("OP15-087"), sickness=False)
    me.characters = [robin]

    me.trash = [repo.get("OP01-016")] * 10
    evaluate_static_effects(st, overlay)
    assert robin.is_blocker_now is True, "トラッシュ10枚で【ブロッカー】を得ていない"

    me.trash = [repo.get("OP01-016")] * 9
    evaluate_static_effects(st, overlay)
    assert robin.is_blocker_now is False, "トラッシュ9枚で【ブロッカー】を得てはいけない"


# --------------------------------------------------------------------------- #
#  OP15-088 パイレーツドッキング6 (CHARACTER 黒 cost5 power7000):
#    このキャラのコスト+6。
#    【登場時】自分のデッキの上から3枚をトラッシュに置くことができる：自分のトラッシュから
#      コスト2以下の特徴《麦わらの一味》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op15_088_on_play_optional_mill_then_play_from_trash_ai():
    """【登場時】(コスト:デッキ上3枚トラッシュ) → トラッシュのコスト2以下《麦わらの一味》を
    登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB02-017")]  # ナミ cost1 麦わらの一味
    me.deck = [repo.get("OP01-016")] * 10
    deck_before = len(me.deck)
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP15-088", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-088"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 3, \
        f"コスト (デッキ上3枚トラッシュ) が支払われていない: deck={len(me.deck)}"
    assert any(c.card.card_id == "EB02-017" for c in me.characters), \
        "トラッシュのコスト2以下《麦わらの一味》が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_op15_088_on_play_no_target_in_trash_ai():
    """トラッシュに対象 (コスト2以下《麦わらの一味》) が無ければ 登場しない (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # トラッシュ も デッキ も 対象外 (ボビー・ファンク cost3 非麦わら) で埋める。
    # (デッキを ナミ で埋めると mill コストで 麦わら cost1 が trash 入りし対象化するため)
    me.trash = [repo.get("OP15-050")]  # ボビー・ファンク cost3 (対象外)
    me.deck = [repo.get("OP15-050")] * 10
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP15-088", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-088"), sickness=True))
    _drain(st, [0])
    assert not any(c.card.card_id == "OP15-050" for c in me.characters), \
        "対象外のカードが登場している"
    assert len(me.characters) == chars_before, "対象なしなのにキャラが増えている"


# --------------------------------------------------------------------------- #
#  OP15-090 ペローナ (CHARACTER 黒 cost1 power2000):
#    自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、代わりに
#      自分の手札1枚を捨てることができる。 (replace_leave / 任意)
# --------------------------------------------------------------------------- #
def test_op15_090_replace_leave_discard_hand_ai():
    """元々P7000以下の自キャラが相手効果で離脱 → 代わりに手札1枚捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    perona = InPlay.of(repo.get("OP15-090"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 ≤7000
    me.characters = [perona, victim]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    hand_before = len(me.hand)

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "元々P7000以下の自キャラ離脱が置換されていない"
    assert victim in me.characters, "置換成立時 victim は場に残るべき"
    assert len(me.hand) == hand_before - 1, "置換コストで手札1枚が捨てられるべき"


def test_op15_090_replace_leave_power_over_7000_no_replace():
    """元々パワー7000超の自キャラは 対象外 → 置換されない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    perona = InPlay.of(repo.get("OP15-090"), sickness=False)
    big = InPlay.of(repo.get("OP15-008"), sickness=False)  # power9000 (> 7000)
    me.characters = [perona, big]
    me.hand = [repo.get("OP01-013")]

    replaced = try_replace_ko(
        st, me, opp, big, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "元々パワー7000超のキャラに置換が成立してはいけない (対象外)"


def test_op15_090_replace_leave_human_optional_confirm():
    """人間 actor: 任意 (optional) → replace_ko_optional modal が立ち halt する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    perona = InPlay.of(repo.get("OP15-090"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [perona, victim]
    me.hand = [repo.get("OP01-013")]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_leave の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    _drain(st, [1])
    assert victim in me.characters, "人間承諾後 victim は場に残るべき"


# --------------------------------------------------------------------------- #
#  OP15-091 マルガリータ (CHARACTER 黒 cost1):
#    【登場時】相手のトラッシュのカード1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op15_091_on_play_opp_trash_to_deck_bottom_ai():
    """【登場時】相手トラッシュ1枚を相手デッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.trash = [repo.get("OP01-013")]
    opp.deck = [repo.get("OP01-016")] * 10
    trash_before = len(opp.trash)
    deck_before = len(opp.deck)
    do, _ = _do(overlay, "OP15-091", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-091"), sickness=True))
    _drain(st, [0])
    assert len(opp.trash) == trash_before - 1, \
        f"相手トラッシュが1枚減っていない: {len(opp.trash)}"
    assert len(opp.deck) == deck_before + 1, \
        f"相手デッキ下に1枚戻っていない: {len(opp.deck)}"
    assert opp.deck[-1].card_id == "OP01-013", "戻したカードが相手デッキの一番下にない"


def test_op15_091_on_play_empty_opp_trash_noop():
    """相手トラッシュが空なら 何も起きない (発火 no-op)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.trash = []
    opp.deck = [repo.get("OP01-016")] * 10
    deck_before = len(opp.deck)
    do, _ = _do(overlay, "OP15-091", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-091"), sickness=True))
    _drain(st, [0])
    assert len(opp.deck) == deck_before, "相手トラッシュ空なのにデッキが増えている"


# --------------------------------------------------------------------------- #
#  OP15-093 リスキー兄弟 (CHARACTER 黒 cost1 power2000):
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のトラッシュが15枚以上ある
#      場合、自分のキャラの「モンキー・Ｄ・ルフィ」1枚までは、このターン中、
#      【速攻：キャラ】と属性(斬)を得る。
# --------------------------------------------------------------------------- #
def test_op15_093_activate_condition_trash_ge_15():
    """起動メイン条件: 自トラッシュ15枚以上で成立、 14枚では不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-093", "activate_main")
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.trash = [repo.get("OP01-016")] * 14
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "トラッシュ14枚で起動メイン条件が成立してはいけない"
    me.trash = [repo.get("OP01-016")] * 15
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "トラッシュ15枚で起動メイン条件が成立していない"


def test_op15_093_activate_give_rush_chara_and_attribute_ai():
    """起動メイン: 自身をトラッシュ (コスト) → 自軍「ルフィ」に【速攻：キャラ】+属性(斬) (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    risky = InPlay.of(repo.get("OP15-093"), sickness=False)
    ruffy = InPlay.of(repo.get("OP10-111"), sickness=True)  # モンキー・D・ルフィ cost1
    me.characters = [risky, ruffy]
    me.trash = [repo.get("OP01-016")] * 15  # 条件成立

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-093"]
    assert len(opts) == 1, f"OP15-093 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert risky not in me.characters, "コストで リスキー兄弟 がトラッシュに置かれるべき"
    assert ruffy.is_rush_chara_only_now is True, \
        "「ルフィ」に【速攻：キャラ】が付与されていない"
    assert "斬" in ruffy.granted_attributes, \
        f"「ルフィ」に属性(斬)が付与されていない: {ruffy.granted_attributes}"


# --------------------------------------------------------------------------- #
#  OP15-094 ロロノア・ゾロ (CHARACTER 黒 cost2 power1000):
#    このキャラ以外の自分の特徴《麦わらの一味》を持つキャラが相手の効果で場を離れる場合、
#      代わりにこのキャラをトラッシュに置くことができる。【ブロッカー】 (replace_leave / 任意)
# --------------------------------------------------------------------------- #
def test_op15_094_replace_leave_return_self_to_trash_ai():
    """他の《麦わらの一味》が相手効果で離脱 → 代わりに ゾロ自身をトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP15-094"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ (麦わらの一味)
    me.characters = [zoro, victim]
    trash_before = len(me.trash)

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "他の《麦わらの一味》キャラ離脱が置換されていない"
    assert victim in me.characters, "置換成立時 victim (麦わらの一味) は場に残るべき"
    assert zoro not in me.characters, "代わりに ゾロ自身がトラッシュへ置かれるべき"
    assert len(me.trash) == trash_before + 1, "ゾロがトラッシュに加わっていない"


def test_op15_094_replace_leave_non_strawhat_no_replace():
    """《麦わらの一味》でない自キャラ離脱は 対象外 → 置換されない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP15-094"), sickness=False)
    other = InPlay.of(repo.get("OP15-050"), sickness=False)  # ボビー・ファンク (非麦わら)
    me.characters = [zoro, other]

    replaced = try_replace_ko(
        st, me, opp, other, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, \
        "《麦わらの一味》でないキャラに置換が成立してはいけない (対象外)"
    assert zoro in me.characters, "置換不成立時 ゾロは場に残るべき"
