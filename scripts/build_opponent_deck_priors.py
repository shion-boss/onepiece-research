"""相手デッキ belief モデルの前計算 artifact を作る。

対戦相手の leader (公開情報) から「50 枚 main に何が入っているか」を推定するための
prior を、実大会レシピ (decks/*.json の meta + decks/_archive/cardrush_raw/*.json) から
leader 単位で集計して db/opponent_deck_priors.json に書き出す。

設計方針:
- leader ごとに「観測された実デッキリスト集合」をそのまま保持する (marginal だけでなく)。
  これにより runtime で
    (1) marginal P(card|leader) を feature に使う
    (2) 相手が見せた札 (seen) と整合するレシピだけに絞る事後更新
    (3) determinization 用に coherent な 1 デッキをサンプリング
  の 3 つを同じ artifact から賄える。
- 独立 per-card サンプリングは非合法/非整合な組み合わせを生むので採らない。実レシピ bootstrap。

一次データ:
- decks/*.json                       (現行 meta。.analysis./.target 派生は除外)
- decks/_archive/cardrush_raw/*.json  (過去 3 ヶ月の大会優勝レシピ、deck classifier 学習用に保管済)
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OUT_PATH = _REPO_ROOT / "db" / "opponent_deck_priors.json"


def _iter_decklist_paths() -> Iterable[Path]:
    """corpus に含めるデッキ JSON のパスを列挙する。"""
    meta_dir = _REPO_ROOT / "decks"
    archive_dir = meta_dir / "_archive" / "cardrush_raw"
    for p in sorted(meta_dir.glob("*.json")):
        name = p.name
        # 派生ファイル (静的分析 / target spec) は実デッキリストではないので除外
        if name.endswith(".analysis.json") or ".target" in name:
            continue
        yield p
    for p in sorted(archive_dir.glob("*.json")):
        yield p
    # 学習プール (= EIV1 self-play が実際に回している 153 デッキ)。 ⚠ これを入れないと
    # プールが使う 36 leader のうち 16 が belief 未収録 → v18 の belief 特徴が
    # 「常に 0」 になり、 配備済みなのに実質死ぬ (2026-07-23 実測で発覚)。
    for p in sorted((meta_dir / "_train_pool").glob("*.json")):
        if p.name.endswith(".analysis.json") or ".target" in p.name:
            continue
        yield p


def _parse_decklist(path: Path) -> dict[str, Any] | None:
    """デッキ JSON を読み、leader + main を持つ実デッキなら正規化して返す。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    leader = raw.get("leader")
    main = raw.get("main")
    if not isinstance(leader, str) or not isinstance(main, list):
        return None
    entries: list[list[Any]] = []
    for item in main:
        if not isinstance(item, dict):
            return None
        cid = item.get("card_id")
        cnt = item.get("count")
        if not isinstance(cid, str) or not isinstance(cnt, int):
            return None
        entries.append([cid, cnt])
    if not entries:
        return None
    return {
        "slug": raw.get("slug") or path.stem,
        "leader": leader,
        "leader_name": raw.get("leader_name", ""),
        "date": raw.get("tournament_date", ""),
        "main": entries,
    }


def _collect() -> list[dict[str, Any]]:
    """全 corpus を読み、slug で重複排除したデッキリスト一覧を返す。"""
    by_slug: dict[str, dict[str, Any]] = {}
    for path in _iter_decklist_paths():
        deck = _parse_decklist(path)
        if deck is None:
            continue
        # 先勝ち (meta を archive より優先) だが slug が異なれば別レシピとして両方残す
        by_slug.setdefault(deck["slug"], deck)
    return list(by_slug.values())


def _marginals(decklists: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    """レシピ集合から per-card の marginal 統計を計算する。"""
    n = len(decklists)
    present: dict[str, int] = defaultdict(int)  # そのカードを含むデッキ数
    sum_count: dict[str, int] = defaultdict(int)  # 全デッキ合計枚数
    for deck in decklists:
        for cid, cnt in deck["main"]:
            present[cid] += 1
            sum_count[cid] += cnt
    out: dict[str, dict[str, float | int]] = {}
    for cid, decks_with in present.items():
        out[cid] = {
            "prob": round(decks_with / n, 4),              # P(このカードを積む | leader)
            "exp_count": round(sum_count[cid] / n, 4),      # E[枚数 | leader] (不在は 0)
            "mean_present": round(sum_count[cid] / decks_with, 4),  # 積む時の平均枚数
            "n": decks_with,
        }
    return out


def build() -> dict[str, Any]:
    decks = _collect()
    by_leader: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for deck in decks:
        by_leader[deck["leader"]].append(deck)

    leaders: dict[str, Any] = {}
    for leader_id, dlist in sorted(by_leader.items()):
        # leader_name は空でない最初のものを採用
        leader_name = next((d["leader_name"] for d in dlist if d["leader_name"]), "")
        leaders[leader_id] = {
            "leader_name": leader_name,
            "n_decks": len(dlist),
            "decklists": [
                {"slug": d["slug"], "date": d["date"], "main": d["main"]}
                for d in dlist
            ],
            "marginals": _marginals(dlist),
        }

    return {
        "meta": {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_decks_total": len(decks),
            "n_leaders": len(leaders),
            "note": "P(card|leader) prior + 実レシピ bootstrap pool。runtime=engine/opponent_deck_model.py",
        },
        "leaders": leaders,
    }


def main() -> None:
    data = build()
    _OUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta = data["meta"]
    print(f"wrote {_OUT_PATH.relative_to(_REPO_ROOT)}")
    print(f"  decks={meta['n_decks_total']}  leaders={meta['n_leaders']}")
    # leader 別のサンプル数を多い順に表示 (confidence の目安)
    rows = sorted(
        data["leaders"].items(), key=lambda kv: kv[1]["n_decks"], reverse=True
    )
    for leader_id, entry in rows:
        name = entry["leader_name"] or "?"
        print(f"  {leader_id:12s} n={entry['n_decks']:2d}  {name}")


if __name__ == "__main__":
    main()
