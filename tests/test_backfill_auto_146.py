# -*- coding: utf-8 -*-
"""OP15/OP16 弾 効果 回帰テスト バックフィル (自動生成 wave 146):
OP15-110 / OP15-111 / OP15-112 / OP15-113 / OP15-115 /
OP15-116 / OP15-117 / OP15-118 / OP16-003 / OP16-006 の 10 枚。

目的 (= test_backfill_auto_001〜145.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
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
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
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
def test_all_op15_op16_wave146_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-110", "OP15-111", "OP15-112", "OP15-113", "OP15-115",
           "OP15-116", "OP15-117", "OP15-118", "OP16-003", "OP16-006"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-110 ブラハム (CHARACTER 黄 cost3):
#    【KO時】自分のリーダーが特徴《シャンドラの戦士》を持つ場合、
#      自分のデッキの上から1枚までを、ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op15_110_on_ko_put_top_to_life_ai():
    """【KO時】《シャンドラの戦士》リーダーで デッキ上1枚をライフへ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-098", overlay)  # カルガラ (ジャヤ/空島/シャンドラの戦士)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    life_before = len(me.life)
    do, _ = _do(overlay, "OP15-110", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, \
        f"デッキ上1枚がライフへ移っていない: deck={len(me.deck)}"
    assert len(me.life) == life_before + 1, \
        f"ライフが1枚増えていない: life={len(me.life)}"


def test_op15_110_on_ko_condition_leader_shandora():
    """KO時条件: 《シャンドラの戦士》リーダーで成立、 非該当で不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-110", "on_ko")
    st_ok = _state(repo, "OP08-098", overlay)   # カルガラ (シャンドラの戦士)
    st_ng = _state(repo, "OP01-001", overlay)   # ゾロ (麦わらの一味、 非シャンドラ)
    assert eval_condition(eff.get("if", {}), st_ok, st_ok.players[0]) is True, \
        "《シャンドラの戦士》リーダーでKO時条件が成立していない"
    assert eval_condition(eff.get("if", {}), st_ng, st_ng.players[0]) is False, \
        "非《シャンドラの戦士》リーダーで条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP15-111 モンブラン・ノーランド (CHARACTER 黄 cost4):
#    【ドン‼×1】【アタック時】自分の「カルガラ」1枚までは、このターン中、【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op15_111_on_attack_give_rush_to_karugara_ai():
    """【アタック時】自分の「カルガラ」に【速攻】を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    noland = InPlay.of(repo.get("OP15-111"), sickness=False)
    karugara = InPlay.of(repo.get("OP15-101"), sickness=True)  # カルガラ cost3
    me.characters = [noland, karugara]
    do, _ = _do(overlay, "OP15-111", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, noland)
    _drain(st, [0])
    assert "速攻" in karugara.granted_keywords, \
        f"「カルガラ」に【速攻】が付与されていない: {karugara.granted_keywords}"


def test_op15_111_on_attack_don_gate():
    """overlay の ドンゲート self_attached_don_ge=1 が存在する。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-111", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "ドンゲート self_attached_don_ge=1 が overlay に無い"


def test_op15_111_on_attack_human_pick():
    """人間 + 「カルガラ」複数 → target_pick modal → 選んだ 1 枚に【速攻】。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    noland = InPlay.of(repo.get("OP15-111"), sickness=False)
    a = InPlay.of(repo.get("OP15-101"), sickness=True)  # カルガラ
    b = InPlay.of(repo.get("OP15-101"), sickness=True)  # カルガラ (2 枚目)
    me.characters = [noland, a, b]
    do, _ = _do(overlay, "OP15-111", "on_attack")
    execute_effect(do[0], st, me, opp, noland)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"「カルガラ」候補が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert "速攻" in b.granted_keywords, "人間が選んだ「カルガラ」に【速攻】が付与されていない"
    assert "速攻" not in a.granted_keywords, "選ばなかった「カルガラ」に付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP15-112 ラキ (CHARACTER 黄 cost4):
#    【ブロッカー】【登場時】自分の手札からコスト3以下の特徴《シャンドラの戦士》を持つ
#      キャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op15_112_on_play_play_shandora_from_hand_ai():
    """【登場時】手札のコスト3以下《シャンドラの戦士》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-110")]  # ブラハム cost3 シャンドラの戦士 (登場時効果なし)
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP15-112", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-112"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP15-110" for c in me.characters), \
        "手札のコスト3以下《シャンドラの戦士》キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_op15_112_on_play_human_play_pick():
    """人間 + 手札に対象 複数 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 種の シャンドラの戦士 cost≤3 (登場時効果なし)
    me.hand = [repo.get("OP15-110"), repo.get("OP15-103")]  # ブラハム / ゲンボウ
    do, _ = _do(overlay, "OP15-112", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-112"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in ("OP15-110", "OP15-103") for c in me.characters), \
        "人間が選んだ《シャンドラの戦士》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP15-113 ロロノア・ゾロ (CHARACTER 黄 cost4):
#    【登場時】自分の手札1枚を捨てることができる：自分のデッキの上から1枚までを、ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op15_113_on_play_put_top_to_life_ai():
    """【登場時】(手札1捨てコスト後) デッキ上1枚をライフへ (do 発火、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    life_before = len(me.life)
    do, _ = _do(overlay, "OP15-113", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-113"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, \
        f"デッキ上1枚がライフへ移っていない: deck={len(me.deck)}"
    assert len(me.life) == life_before + 1, \
        f"ライフが1枚増えていない: life={len(me.life)}"


# --------------------------------------------------------------------------- #
#  OP15-115 衝撃貝 (EVENT 黄 cost2):
#    【メイン】相手のコスト4以下のキャラ1枚までを、KOする。その後、自分のライフの上から1枚を手札に加える。
#    【トリガー】相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op15_115_main_ko_and_life_to_hand_ai():
    """【メイン】相手コスト4以下1枚KO + 自ライフ上1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤4)
    opp.characters = [victim]
    me.life = [repo.get("OP01-016")] * 2
    me.hand = []
    life_before = len(me.life)
    do, _ = _do(overlay, "OP15-115", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "相手コスト4以下キャラがKOされていない"
    assert len(me.hand) == 1, "自ライフ上1枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "自ライフが1枚減っていない"


def test_op15_115_main_ko_human_pick():
    """人間 + 相手コスト4以下 複数 → target_pick modal → 選んだ 1 枚のみKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [a, b]
    me.life = [repo.get("OP01-016")] * 2
    me.hand = []
    do, eff = _do(overlay, "OP15-115", "main")
    # ko primitive を発火 (do 配列内で ko を含む primitive を選ぶ)
    ko_prim = next(p for p in do if "ko" in p)
    execute_effect(ko_prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op15_115_trigger_ko_ai():
    """【トリガー】相手コスト4以下1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (≤4)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP15-115", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "トリガーで相手コスト4以下キャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP15-116 ゴムゴムの黄金回転弾 (EVENT 黄 cost1):
#    【メイン】自リーダーが《麦わらの一味》なら、自ライフ上1枚をトラッシュ。その後、
#      デッキ上1枚をライフへ、自分の手札1枚を捨てる。
#    【カウンター】自リーダーを、このバトル中、パワー+4000。
# --------------------------------------------------------------------------- #
def test_op15_116_main_mill_life_put_top_discard_ai():
    """【メイン】自ライフ1トラッシュ → デッキ上1ライフ → 手札1捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016")] * 2
    me.hand = [repo.get("OP01-016")]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    life_before = len(me.life)
    do, _ = _do(overlay, "OP15-116", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    # mill_self_life_to_trash(life -1, trash +1) + put_top_to_life(deck -1, life +1)
    # + trash_self_hand_random(hand -1, trash +1)
    assert len(me.deck) == deck_before - 1, f"デッキ上1枚がライフへ移っていない: deck={len(me.deck)}"
    assert len(me.hand) == 0, f"手札1枚が捨てられていない: hand={len(me.hand)}"
    assert len(me.trash) == trash_before + 2, \
        f"トラッシュが2枚 (ライフ削り+手札捨て) 増えていない: trash={len(me.trash)}"
    assert len(me.life) == life_before, \
        f"ライフ枚数 net (削り-1 + 加え+1 = ±0) が合わない: life={len(me.life)}"


def test_op15_116_main_condition_leader_strawhat():
    """メイン条件: 《麦わらの一味》リーダーで成立、 非該当で不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-116", "main")
    st_ok = _state(repo, "OP01-001", overlay)   # ゾロ (麦わらの一味)
    st_ng = _state(repo, "OP08-098", overlay)   # カルガラ (シャンドラの戦士、 非麦わら)
    assert eval_condition(eff.get("if", {}), st_ok, st_ok.players[0]) is True, \
        "《麦わらの一味》リーダーでメイン条件が成立していない"
    assert eval_condition(eff.get("if", {}), st_ng, st_ng.players[0]) is False, \
        "非《麦わらの一味》リーダーで条件が成立してはいけない"


def test_op15_116_counter_pump_leader_ai():
    """【カウンター】自リーダーを +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power
    do, _ = _do(overlay, "OP15-116", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP15-117 へそ!! (EVENT 黄 cost1):
#    【メイン】カード1枚を引く。その後、自分の特徴《空島》を持つ、リーダーかキャラ1枚に
#      レストのドン‼1枚までを、付与する。
#    【トリガー】自リーダーが《空島》なら、カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op15_117_main_draw_and_attach_rested_don_ai():
    """【メイン】1ドロー → 《空島》リーダーにレストドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-098", overlay)  # カルガラ (空島 leader)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.don_rested = 2
    deck_before = len(me.deck)
    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP15-117", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "メインの 1ドローが起きていない"
    assert len(me.hand) == 1, "1ドローで手札が1枚増えていない"
    assert me.leader.attached_dons == don_before + 1, \
        "《空島》リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_op15_117_main_attach_human_pick():
    """人間 + 《空島》リーダー/キャラ 複数 → attach 先の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-098", overlay, human_idx=0)  # 空島 leader
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.don_rested = 2
    friend = InPlay.of(repo.get("EB01-054"), sickness=False)  # ガン・フォール 空島
    me.characters = [friend]
    do, _ = _do(overlay, "OP15-117", "main")
    # draw を先に消化してから attach primitive で modal を立てる
    execute_effect(do[0], st, me, opp, None)
    _drain(st, [0])
    execute_effect(do[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+《空島》キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [friend_idx])
    assert friend.attached_dons == 1, "人間が選んだ《空島》キャラにレストドンが付与されていない"


def test_op15_117_trigger_draw2_when_leader_skyisland_ai():
    """【トリガー】《空島》リーダーで カード2枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-098", overlay)  # 空島 leader
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    do, eff = _do(overlay, "OP15-117", "trigger")
    assert eff.get("if", {}).get("leader_feature") == "空島", \
        "トリガー条件 leader_feature=空島 が overlay に無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, "トリガーの 2ドローが起きていない"
    assert len(me.hand) == 2, "トリガーで手札が2枚増えていない"


# --------------------------------------------------------------------------- #
#  OP15-118 エネル (CHARACTER 紫 cost6 power8000):
#    自分の場のドン‼が6枚以下の場合、このキャラは相手の効果で場を離れず、パワー+2000。(静的)
#    【登場時】ドン‼-1：自デッキ上5枚を見て、1枚まで手札に加える。その後、残りをデッキの下に置き、
#      自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op15_118_static_ko_immune_and_pump_when_don_le_6():
    """自場ドン6以下 → 静的に相手効果KO耐性 + パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-058", overlay)  # エネル (空島) leader
    me = st.players[0]
    enel_def = repo.get("OP15-118")
    enel = InPlay.of(enel_def, sickness=False)
    me.characters = [enel]
    me.don_active = 5  # 自場ドン 5 (≤6) → 条件成立
    evaluate_static_effects(st, overlay)
    assert enel.static_ko_immune is True, \
        "自場ドン6以下で相手効果KO耐性 (static_ko_immune) が付いていない"
    assert enel.power == enel_def.power + 2000, \
        f"自場ドン6以下で パワー+2000 が反映されていない: {enel.power} (base {enel_def.power})"


def test_op15_118_static_no_effect_when_don_gt_6():
    """自場ドン7以上 → 静的効果は乗らない (耐性なし / +0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-058", overlay)
    me = st.players[0]
    enel_def = repo.get("OP15-118")
    enel = InPlay.of(enel_def, sickness=False)
    me.characters = [enel]
    me.don_active = 7  # 自場ドン 7 (>6) → 条件不成立
    evaluate_static_effects(st, overlay)
    assert enel.static_ko_immune is False, \
        "自場ドン7以上で相手効果KO耐性が付いてはいけない"
    assert enel.power == enel_def.power, \
        f"自場ドン7以上で パワー+2000 が乗ってはいけない: {enel.power} (base {enel_def.power})"


def test_op15_118_on_play_search_top_5_ai():
    """【登場時】デッキ上5枚を見て1枚手札 + 残りデッキ下 + 手札1捨て (AI、 crash なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-058", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]  # 手札1捨てコスト用
    me.deck = [repo.get("OP01-016")] * 10
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP15-118", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-118"), sickness=True))
    _drain(st, [0])
    # 上5枚を見て1枚手札 (残り4枚デッキ下) → デッキ net -1
    assert len(me.deck) == deck_before - 1, \
        f"search_top_n (5枚見て1枚手札) でデッキが1枚減っていない: deck={len(me.deck)}"
    # trash_self_hand_random で1枚トラッシュ
    assert len(me.trash) == trash_before + 1, \
        f"手札1枚がトラッシュに置かれていない: trash={len(me.trash)}"


def test_op15_118_on_play_search_human_pick():
    """人間 → 【登場時】search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-058", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("OP01-016")] * 10
    do, _ = _do(overlay, "OP15-118", "on_play")
    search_prim = next(p for p in do if "search_top_n" in p)
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP15-118"), sickness=True))
    assert st.pending_choice is not None, "人間文脈で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])


# --------------------------------------------------------------------------- #
#  OP16-003 エドワード・ニューゲート (CHARACTER 赤 cost8 power10000):
#    【自分のターン中】自リーダーは【ダブルアタック】を得て、パワー+2000。(静的)
#    【登場時】手札からパワー8000のキャラ2枚を公開できる：相手のキャラ1枚まで、このターン中、パワー-6000。
# --------------------------------------------------------------------------- #
def test_op16_003_static_leader_double_attack_and_pump_self_turn():
    """【自分のターン中】自リーダーに【ダブルアタック】+ パワー+2000 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=0)  # 自分のターン
    me = st.players[0]
    newgate = InPlay.of(repo.get("OP16-003"), sickness=False)
    me.characters = [newgate]
    power_before = me.leader.power
    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" in me.leader.static_granted_keywords, \
        "自分のターン中に自リーダーへ【ダブルアタック】が静的付与されていない"
    assert me.leader.power == power_before + 2000, \
        f"自分のターン中に自リーダー +2000 が反映されていない: {me.leader.power}"


def test_op16_003_static_no_effect_off_turn():
    """相手のターン中は【自分のターン中】条件が不成立 → リーダー効果なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手のターン
    me = st.players[0]
    newgate = InPlay.of(repo.get("OP16-003"), sickness=False)
    me.characters = [newgate]
    power_before = me.leader.power
    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" not in me.leader.static_granted_keywords, \
        "相手のターン中に【ダブルアタック】が付与されてはいけない"
    assert me.leader.power == power_before, \
        f"相手のターン中に +2000 が乗ってはいけない: {me.leader.power}"


def test_op16_003_on_play_reveal_cost_debuff_ai():
    """【登場時】手札のパワー8000キャラ2枚公開 → 相手キャラ1枚 -6000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 公開コスト用: パワー8000 の キャラ 2 枚
    me.hand = [repo.get("EB04-003"), repo.get("EB04-004")]  # 共に power 8000
    victim = InPlay.of(repo.get("OP15-118"), sickness=False)  # power 8000
    opp.characters = [victim]
    power_before = victim.power
    do, _ = _do(overlay, "OP16-003", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-003"), sickness=True))
    _drain(st, [0])
    assert victim.power == power_before - 6000, \
        f"相手キャラ -6000 が反映されていない: {victim.power} (before {power_before})"


def test_op16_003_on_play_no_reveal_no_debuff():
    """手札にパワー8000キャラが2枚無ければ 任意コスト不能 → デバフ発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-003")]  # パワー8000 が1枚だけ (2枚必要)
    victim = InPlay.of(repo.get("OP15-118"), sickness=False)
    opp.characters = [victim]
    power_before = victim.power
    do, _ = _do(overlay, "OP16-003", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-003"), sickness=True))
    _drain(st, [0])
    assert victim.power == power_before, \
        "公開コストを払えないのにデバフが発動してはいけない"


def test_op16_003_on_play_human_optional_cost_confirm():
    """人間 → 【登場時】optional_cost_confirm modal が立つ (任意コストの承諾委譲)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-003"), repo.get("EB04-004")]
    victim = InPlay.of(repo.get("OP15-118"), sickness=False)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-003", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-003"), sickness=True))
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間文脈で optional_cost_confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  OP16-006 シャンクス (CHARACTER 赤 cost4 power5000):
#    【登場時】自分のドン!!2枚をレストにできる：相手のパワー4000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op16_006_on_play_rest_don_ko_ai():
    """【登場時】ドン2レスト → 相手パワー4000以下キャラ1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # レストコスト2 を払える
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power2000 (≤4000)
    opp.characters = [victim]
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP16-006", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-006"), sickness=True))
    _drain(st, [0])
    assert victim not in opp.characters, "相手パワー4000以下キャラがKOされていない"
    assert me.don_rested == rested_before + 2, "ドン2枚がレストされていない"
    assert me.don_active == 1, "アクティブドンが2枚消費されていない"


def test_op16_006_on_play_no_don_no_ko():
    """アクティブドンが2枚未満なら 任意コスト不能 → KO発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1  # 2枚未満 → 払えない
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-006", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-006"), sickness=True))
    _drain(st, [0])
    assert victim in opp.characters, "ドン不足なのにKOが発動してはいけない"


def test_op16_006_on_play_power_over_4000_not_target():
    """相手キャラのパワーが4000超なら 対象外 → KOされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    big = InPlay.of(repo.get("OP15-118"), sickness=False)  # power 8000 (>4000)
    opp.characters = [big]
    do, _ = _do(overlay, "OP16-006", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-006"), sickness=True))
    _drain(st, [0])
    assert big in opp.characters, "パワー4000超のキャラがKOされてはいけない (対象外)"


def test_op16_006_on_play_human_optional_cost_confirm():
    """人間 → 【登場時】optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-006", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-006"), sickness=True))
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間文脈で optional_cost_confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
