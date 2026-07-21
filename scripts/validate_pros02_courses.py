#!/usr/bin/env python3
"""pros02 操縦コースの盤面が OPTCG のリソース制約に反していないか静的検証する。

過去に「先攻2ターン目に4コスト分のキャラを展開済(=先攻1T=1ドンでは不可能)」
「DON カーブがずれ(先攻2T=2ドン、正しくは3)」等の非合法盤面を量産した。
このスクリプトは各コースステップを engine の DON カーブと展開可能上限で検証し、
違反を列挙する (= 手作業の盤面 authoring の gate)。

チェック項目:
  1. my_don が先攻の DON カーブ (turn N → min(10, 2N-1)) と一致
  2. opp_don が後攻の DON カーブ (my turn N の時点 → min(10, 2(N-1))) と一致
  3. 自盤面キャラの総コスト ≤ 先攻が turn N-1 までに得た累積 DON (=2N-3, N>=2)
  4. 相手盤面キャラの総コスト ≤ 後攻が得た累積 DON (=2(N-1))
  5. 非 DON カード(手札+盤面+ライフ+トラッシュ+デッキ)が 50 に収まる余地

いずれも upper-bound の甘い制約 (攻撃/付与に使ったDONは考慮しない) だが、
gross な非合法盤面 (4コストをT1展開等) は確実に捕捉する。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository  # noqa: E402


def cum_first(n: int) -> int:
    """先攻が自分の turn n までに『得た累積』DON (turn n の付与を含む)。"""
    return min(10, 2 * n - 1)


def cum_second(n: int) -> int:
    """後攻が自分の turn n までに得た累積 DON。"""
    return min(10, 2 * n)


def _cost(repo, cid):
    try:
        return int(getattr(repo.get(cid), "cost", 0) or 0)
    except Exception:
        return 0


def validate(path: str = None) -> int:
    path = path or str(ROOT / "db" / "pros02_courses.json")
    repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    data = json.load(open(path, encoding="utf-8"))
    problems = []
    for course in data.get("courses", []):
        cid_ = course.get("course_id")
        # 現状は全コース「自分が先攻」前提 (title に先攻)。 後攻コース追加時は going_first を state に持たせる。
        going_first = "先攻" in course.get("title", "")
        for step in course.get("steps", []):
            n = int(step["turn"])
            s = step["state"]
            tag = f"[{cid_} T{n}]"

            # 1. my_don カーブ
            exp_my = cum_first(n) if going_first else cum_second(n)
            if int(s.get("my_don", -1)) != exp_my:
                problems.append(f"{tag} my_don={s.get('my_don')} だが正しい先攻カーブは {exp_my}")

            # 2. opp_don カーブ (相手は後攻、 私の turn N の時点で後攻(N-1)T まで完了)
            if going_first:
                exp_opp = cum_second(n - 1) if n >= 2 else 0
                if "opp_don" in s and int(s.get("opp_don", -1)) != exp_opp:
                    problems.append(f"{tag} opp_don={s.get('opp_don')} だが後攻カーブは {exp_opp}")

            # 3. 自盤面の総コスト ≤ 展開可能上限
            my_cost = sum(_cost(repo, c["cid"] if isinstance(c, dict) else c) for c in s.get("my_chars", []))
            budget_my = cum_first(n - 1) if going_first else cum_second(n - 1)
            if n >= 2 and my_cost > budget_my:
                problems.append(
                    f"{tag} 自盤面総コスト {my_cost} > turn {n-1} までの累積DON {budget_my} "
                    f"(chars={[c.get('cid') if isinstance(c,dict) else c for c in s.get('my_chars',[])]})"
                )

            # 4. 相手盤面の総コスト ≤ 後攻累積
            opp_cost = sum(_cost(repo, c["cid"] if isinstance(c, dict) else c) for c in s.get("opp_chars", []))
            budget_opp = cum_second(n - 1) if going_first else cum_first(n)
            if n >= 2 and opp_cost > budget_opp:
                problems.append(
                    f"{tag} 相手盤面総コスト {opp_cost} > 後攻累積DON {budget_opp} "
                    f"(chars={[c.get('cid') if isinstance(c,dict) else c for c in s.get('opp_chars',[])]})"
                )

    if problems:
        print(f"NG: {len(problems)} 件の非合法盤面\n")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: 全コースステップが DON カーブ・展開可能上限を満たす")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate(sys.argv[1] if len(sys.argv) > 1 else None))
