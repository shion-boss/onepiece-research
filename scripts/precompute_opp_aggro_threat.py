"""相手 leader → aggro/rush threat index を precompute(belief × カード keyword)。

value の「ブロッカーで殴っていいターンか」判定に、 相手デッキの速攻圧を deck-level belief から出す。
opponent_deck_priors の belief_for_leader(=P(card|leader))× 各カードの is_rush / 低コスト攻撃力
を掛けて期待値化 → db/opp_aggro_threat.json {leader_id: {rush_exp, aggro_exp}}。

feature 側は これを **単独でなく interaction**(× 自分の available-blocker、 手ごとに変わる)で使う
(v6 教訓: ゲーム内定数は手の順位を変えず null)。

  .venv/bin/python scripts/precompute_opp_aggro_threat.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository
from engine.opponent_deck_model import load_model

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")


def _card(cid):
    try:
        return _REPO.get(cid)
    except Exception:
        return None


def _rush(cd) -> bool:
    try:
        return bool(cd.is_rush or cd.is_rush_chara_only)
    except Exception:
        return False


def _aggro_weight(cd) -> float:
    """低コスト高パワーの攻撃キャラ = aggro 圧。 cost<=3 かつ power>=3000 を 1、 cost<=4/power>=5000 を 0.5。"""
    try:
        if "CHARACTER" not in str(cd.category).upper() and "キャラ" not in str(cd.category):
            return 0.0
        cost = int(cd.cost or 0)
        power = int(cd.power or 0)
    except Exception:
        return 0.0
    if cost <= 3 and power >= 3000:
        return 1.0
    if cost <= 4 and power >= 5000:
        return 0.5
    return 0.0


def main():
    model = load_model()
    out = {}
    leaders = model.leaders() if callable(model.leaders) else model.leaders
    for lid in leaders:
        belief = model.belief_for_leader(lid)  # {cid: {exp_count, prob, ...}}
        rush_exp = 0.0
        aggro_exp = 0.0
        for cid, info in belief.items():
            cd = _card(cid)
            if cd is None:
                continue
            ec = float(info.get("exp_count", 0.0))
            if _rush(cd):
                rush_exp += ec
            aggro_exp += ec * _aggro_weight(cd)
        out[lid] = {"rush_exp": round(rush_exp, 3), "aggro_exp": round(aggro_exp, 3)}
    dst = ROOT / "db" / "opp_aggro_threat.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    ranked = sorted(out.items(), key=lambda kv: kv[1]["rush_exp"] + kv[1]["aggro_exp"], reverse=True)
    print(f"[done] {len(out)} leaders -> {dst}")
    print("  最も aggro な leader (rush_exp + aggro_exp):")
    for lid, v in ranked[:8]:
        print(f"    {lid}: rush={v['rush_exp']:.1f} aggro={v['aggro_exp']:.1f}")
    print("  最も control な leader:")
    for lid, v in ranked[-5:]:
        print(f"    {lid}: rush={v['rush_exp']:.1f} aggro={v['aggro_exp']:.1f}")


if __name__ == "__main__":
    main()
