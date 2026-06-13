# -*- coding: utf-8 -*-
"""OP14-061 ヴェルゴ の replace_leave がヴェルゴ自身も保護することの退行ガード。

公式テキスト: 「自分の特徴《ドンキホーテ海賊団》を持つキャラが相手の効果で場を離れる場合、
代わりに自分の場のドン1枚をドンデッキに戻すことができる」。 「このキャラ以外」 の限定が無く、
ヴェルゴ自身が《ドンキホーテ海賊団》を持つ ので 自身も保護対象。 旧 overlay は target=other_self_chara
(= 自身除外) で、 マーカス・マーズ聖 (OP13-091、 コスト5以下を効果KO) が ヴェルゴ自身 (cost5) を
KO する時 に 置換が発火しないバグ → any_self_chara に修正 (2026-06-13)。
"""
from __future__ import annotations

from pathlib import Path

from engine.deck import CardRepository
from engine.effects import _replace_ko_match, load_effect_overlay
from engine.core import InPlay

ROOT = Path(__file__).resolve().parent.parent
_repo = CardRepository.from_json(ROOT / "db" / "cards.json")
_overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _vergo_replace_cond(card_id: str = "OP14-061") -> dict:
    bundle = _overlay.get(card_id)
    effs = bundle.effects if hasattr(bundle, "effects") else bundle
    rl = [e for e in effs if e.get("when") == "replace_leave"]
    assert rl, f"{card_id} に replace_leave が無い"
    return rl[0]["if"]


def test_overlay_target_is_any_self_chara():
    """base + parallel 両方の overlay が any_self_chara (= 自身含む) になっている。"""
    for cid in ("OP14-061", "OP14-061_p1"):
        cond = _vergo_replace_cond(cid)
        assert cond["target"] == "any_self_chara", (
            f"{cid}: target={cond['target']} (期待 any_self_chara = 自身も保護)"
        )
        assert cond.get("target_feature") == "ドンキホーテ海賊団"
        assert cond.get("by_opp_effect") is True


def test_vergo_protects_itself():
    """ヴェルゴ自身が相手効果で離れる時、 置換条件が match する (= 自身保護)。"""
    cond = _vergo_replace_cond()
    vergo = InPlay.of(_repo.get("OP14-061"), sickness=False)
    # holder == victim (= ヴェルゴ自身が KO される) で match する
    assert _replace_ko_match(cond, vergo, vergo, by_opp_effect=True) is True


def test_vergo_still_protects_other_donquixote():
    """他の《ドンキホーテ海賊団》キャラ も従来どおり保護 (= any_self_chara は他も含む)。"""
    cond = _vergo_replace_cond()
    holder = InPlay.of(_repo.get("OP14-061"), sickness=False)
    other = InPlay.of(_repo.get("OP14-061"), sickness=False)  # 別インスタンス・同特徴
    assert holder is not other
    assert _replace_ko_match(cond, holder, other, by_opp_effect=True) is True


def test_other_self_chara_would_exclude_self_regression():
    """旧 target=other_self_chara は自身を除外していた (= バグ再現で fix の意味を固定)。"""
    bug_cond = {"target": "other_self_chara", "target_feature": "ドンキホーテ海賊団",
                "by_opp_effect": True}
    vergo = InPlay.of(_repo.get("OP14-061"), sickness=False)
    assert _replace_ko_match(bug_cond, vergo, vergo, by_opp_effect=True) is False


def test_not_triggered_by_battle_ko():
    """by_opp_effect=False (= バトルKO等) では発火しない (= 効果由来限定)。"""
    cond = _vergo_replace_cond()
    vergo = InPlay.of(_repo.get("OP14-061"), sickness=False)
    assert _replace_ko_match(cond, vergo, vergo, by_opp_effect=False) is False
