# -*- coding: utf-8 -*-
"""回帰テスト: 「自分の「X」」 (= カード名 X を指定) の対象は リーダーカードも含む。

バグ (2026-06-10 発見, cardrush_1454 紫エネル を Claude がプレイ中):
  放電 OP15-074 / 雷獣 OP15-076 / 神の裁き OP15-075 の 【カウンター】
  「自分の「エネル」1枚までを、このバトル中、パワー+2000」 が、 overlay 上で
  target `self_chara_named` (= 自キャラのみ) と encode されていたため、
  エネル LEADER (場に エネル キャラが居ない通常状況) を 対象に取れず +0 で whiff。
  life0 で この whiff が repel 失敗 → 敗北の主因になった。

  公式: 「「カード名」を指定する効果は、その名前を持つリーダーカードも対象になる」。
  「自分の「X」」 = leader + 同名キャラ。 「自分のキャラの「X」」 (= EB01-044 スパンダム
  等) のみ character-only。 overlay の 「自分の「X」」 系 27 entry を
  `self_chara_or_leader_named` に是正した。
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import _resolve_target

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _enel_state(repo):
    # 自リーダー = エネル (OP15-058)、 場に エネル キャラは無し
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP15-058"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st = GameState(players=[p0, p1])
    st.turn_player_idx = 0
    st.phase = Phase.MAIN
    return st, p0, p1


def test_self_named_target_includes_leader():
    repo = _repo()
    st, p0, p1 = _enel_state(repo)
    # 是正後 spec: エネル leader を 対象に取れる
    r = _resolve_target({"type": "self_chara_or_leader_named", "name": "エネル"},
                        st, p0, p1, None)
    assert r == [p0.leader], f"自分の「エネル」 は エネル leader を対象にすべき: {r}"
    # 旧バグ spec (char-only): leader を取りこぼす = whiff の再現
    old = _resolve_target({"type": "self_chara_named", "name": "エネル"},
                          st, p0, p1, None)
    assert old == [], f"char-only spec は leader を含まず whiff していた: {old}"


def test_overlay_enel_counters_target_leader_inclusive():
    """放電/雷獣/神の裁き の counter が leader-inclusive target を使うこと。"""
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    for cid in ["OP15-074", "OP15-076", "OP15-075", "OP15-075_p1"]:
        s = json.dumps(ov[cid], ensure_ascii=False)
        assert "self_chara_or_leader_named" in s, f"{cid} は leader-inclusive であるべき"
        assert '"self_chara_named"' not in s, f"{cid} に char-only が残存"


def test_overlay_chara_named_stays_character_only():
    """「自分のキャラの「X」」 (= スパンダム等) は character-only のまま。"""
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    # EB01-044 スパンダム = 「自分のキャラの「スパンダム」」 → char-only 維持
    s = json.dumps(ov["EB01-044"], ensure_ascii=False)
    assert '"self_chara_named"' in s, "キャラの「X」 は char-only を維持すべき"
