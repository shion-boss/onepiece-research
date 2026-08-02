# -*- coding: utf-8 -*-
"""2026-08-02 に監査で発見・修正した「公式ルール未実装」の回帰テスト。

いずれも **overlay / engine に効果そのものが無く、 黙って不発だった** もの。
自動生成テストは「その時点の実装」を正としてしまうため、 これらは手書きで固定する。

対象:
  1. 「ルール上、このカードはカード名を「X」としても扱う」 (16 枚) — 名前一致が別名を見ていなかった
  2. OP15-048 チンジャオ — 【相手のターン中】【KO時】 のターン条件が無く自ターンでも発動していた
  3. EB04-048 / EB01-027 — リーダー特徴条件付きの常在パワー強化が overlay に存在しなかった
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    card_names,
    eval_condition,
    evaluate_static_effects,
    load_effect_overlay,
    name_matches,
)

ROOT = Path(__file__).resolve().parent.parent
_FILLER = "ST01-004"  # サンジ 赤 cost2 power4000


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, overlay, leader_id="OP01-001", opp_leader_id="OP01-001"):
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3
    return st


# --------------------------------------------------------------------------- #
# 1. 「カード名を X としても扱う」 (公式ルール、 16 枚)
# --------------------------------------------------------------------------- #
def test_alt_name_rule_matches_both_names():
    """そげキング (OP03-122_r1) は 「ウソップ」 としても名前一致する。"""
    repo = _repo()
    card = repo.get("OP03-122_r1")
    assert name_matches(card, "そげキング"), "自身の名前で一致しない"
    assert name_matches(card, "ウソップ"), "別名 (ウソップ) で一致しない = 公式ルール未適用"
    assert not name_matches(card, "ナミ"), "無関係な名前に一致してはいけない"


def test_alt_name_rule_multiple_alt_names():
    """EB04-038 ロシナンテ＆ロー は 2 つの別名を持つ。"""
    repo = _repo()
    names = card_names(repo.get("EB04-038"))
    assert "トラファルガー・ロー" in names
    assert "ドンキホーテ・ロシナンテ" in names


def test_alt_name_rule_table_covers_all_official_text():
    """cards.json のテキストに別名ルールを持つカードが漏れなくテーブルに載っている。"""
    import json
    import re

    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    lst = cards if isinstance(cards, list) else (cards.get("cards") or [])
    pat = re.compile(r"ルール上、このカードはカード名を(.+?)としても扱う")
    expect = {c["card_id"] for c in lst if pat.search(c.get("text") or "")}
    table = json.loads((ROOT / "db" / "card_alt_names.json").read_text(encoding="utf-8"))
    got = set(table.get("alt_names") or {})
    assert expect and expect <= got, (
        f"別名テーブルに漏れ: {sorted(expect - got)[:5]} "
        "(scripts/build_card_alt_names.py を再実行する)"
    )


def test_alt_name_filter_name_in():
    """filter の name_in も別名で一致する (= サーチ/登場の対象になる)。"""
    from engine.effects import _matches_filter

    repo = _repo()
    soge = repo.get("EB02-024")  # そげキング (別名: ウソップ)
    assert _matches_filter(soge, {"name_in": ["ウソップ"]}), "name_in が別名を見ていない"
    assert _matches_filter(soge, {"name": "ウソップ"}), "name が別名を見ていない"


# --------------------------------------------------------------------------- #
# 2. OP15-048 チンジャオ 【相手のターン中】【KO時】
# --------------------------------------------------------------------------- #
def test_op15_048_on_ko_is_opp_turn_only():
    """on_ko の条件に opp_turn がある (= 自分のターンでは発動しない)。"""
    overlay = _overlay()
    effs = [e for e in overlay.get("OP15-048").effects if e.get("when") == "on_ko"]
    assert effs, "OP15-048 に on_ko 効果が無い"
    cond = effs[0].get("if") or {}
    assert cond.get("opp_turn") is True, (
        f"【相手のターン中】 が条件化されていない: {cond} "
        "(自分のターンでも KO 時効果が発動してしまう)"
    )

    repo = _repo()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # turn_player=0 (= me のターン) → opp_turn は False
    assert eval_condition(cond, st, me, None) is False, "自ターンで条件が成立している"
    st.turn_player_idx = 1  # 相手のターン
    assert eval_condition(cond, st, me, None) is True, "相手ターンで条件が成立しない"


# --------------------------------------------------------------------------- #
# 3. リーダー特徴条件つき 常在パワー強化 (EB04-048 / EB01-027)
# --------------------------------------------------------------------------- #
def _static_power(repo, overlay, card_id, leader_id, trash):
    st = _state(repo, overlay, leader_id=leader_id)
    me = st.players[0]
    ip = InPlay.of(repo.get(card_id), sickness=False)
    me.characters = [ip]
    me.trash = list(trash)
    evaluate_static_effects(st, overlay)
    return ip.power


def test_eb04_048_static_power_per_5_trash():
    """EB04-048: リーダーが『CP』を含む特徴なら 自トラッシュ5枚につき +1000。"""
    repo = _repo()
    overlay = _overlay()
    trash = [repo.get(_FILLER)] * 10
    base = repo.get("EB04-048").power
    # 『CP』 を含む特徴を持つリーダー を探す
    cp_leader = next(
        (c.card_id for c in repo._by_id.values()
         if str(getattr(c.category, "value", c.category)).upper() == "LEADER"
         and any("CP" in f for f in (c.features or ()))),
        None,
    )
    assert cp_leader, "『CP』 特徴のリーダーが cards.json に無い"
    powered = _static_power(repo, overlay, "EB04-048", cp_leader, trash)
    assert powered == base + 2000, (
        f"トラッシュ10枚で +2000 になっていない: {powered} (base {base})"
    )
    # 条件外リーダーでは強化されない
    plain = _static_power(repo, overlay, "EB04-048", "OP01-001", trash)
    assert plain == base, f"条件外リーダーで強化されている: {plain} (base {base})"


def test_eb01_027_static_power_per_2_trash_events():
    """EB01-027: リーダーが『B・W』を含む特徴なら 自トラッシュのイベント2枚につき +1000。"""
    repo = _repo()
    overlay = _overlay()
    event = next(
        (c for c in repo._by_id.values()
         if str(getattr(c.category, "value", c.category)).upper() == "EVENT"),
        None,
    )
    assert event is not None
    bw_leader = next(
        (c.card_id for c in repo._by_id.values()
         if str(getattr(c.category, "value", c.category)).upper() == "LEADER"
         and any("B・W" in f for f in (c.features or ()))),
        None,
    )
    assert bw_leader, "『B・W』 特徴のリーダーが cards.json に無い"
    base = repo.get("EB01-027").power
    powered = _static_power(repo, overlay, "EB01-027", bw_leader, [event] * 4)
    assert powered == base + 2000, (
        f"トラッシュのイベント4枚で +2000 になっていない: {powered} (base {base})"
    )
    plain = _static_power(repo, overlay, "EB01-027", "OP01-001", [event] * 4)
    assert plain == base, f"条件外リーダーで強化されている: {plain} (base {base})"
