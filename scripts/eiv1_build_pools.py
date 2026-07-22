"""EIV1 学習プール生成 — 2026-07-24。

在庫全体 (meta/配備 decks/*.json + 歴代 decks/_train_pool/ + 優勝 decks/_archive/cardrush_raw/) から
**構造的に合法な** デッキのパス一覧を db/eiv1/pool_all.txt に書き出す。 eiv1_collect が hero/opp 両方
これを回転させる (= デッキ在庫フル活用)。

- 構造チェック = validate(banlist={}) (50枚・色・4枚制限)。 これを通れば含める。 旧メタで現 banlist 違反の
  デッキも「相手なら旧デッキもノイズでない」(ohtsuki 洞察) ので **構造合法なら採用** (banlist 違反は報告のみ)。
- 同一内容 (leader + main 構成が一致) は dedup (meta と archive の重複を除く。 アーキタイプ冗長は残す)。
- card-aware value は cell を暗記せず card で汎化するので、 広プール (多 hero × 多 opp) が転移に効く。

  .venv/bin/python scripts/eiv1_build_pools.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList

REPO = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
OUT = ROOT / "db" / "eiv1" / "pool_all.txt"


def _sources():
    paths = []
    paths += sorted(p for p in (ROOT / "decks").glob("*.json") if not p.name.endswith(".analysis.json"))
    paths += sorted((ROOT / "decks" / "_train_pool").glob("*.json"))
    paths += sorted((ROOT / "decks" / "_archive" / "cardrush_raw").glob("*.json"))
    return paths


def _content_key(dl: DeckList):
    from collections import Counter
    main = tuple(sorted(Counter(c.card_id for c in dl.main).items()))
    return (dl.leader.card_id, main)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    found = _sources()
    valid, seen = [], {}
    n_broken = n_dup = n_banlist = 0
    leaders = set()
    for p in found:
        try:
            dl = DeckList.from_json(str(p), REPO)
        except Exception:
            n_broken += 1
            continue
        if dl.validate(banlist={}):     # 構造チェック (banlist は skip)
            n_broken += 1
            continue
        key = _content_key(dl)
        if key in seen:
            n_dup += 1
            continue
        seen[key] = True
        if dl.validate():               # banlist 込み (報告のみ、 除外しない)
            n_banlist += 1
        rel = p.relative_to(ROOT).as_posix()
        valid.append(rel)
        leaders.add(dl.leader.card_id)
    OUT.write_text("\n".join(valid) + "\n", encoding="utf-8")
    print(f"=== EIV1 pool 生成 ===")
    print(f"  走査 {len(found)} ファイル → 採用 {len(valid)} デッキ")
    print(f"    (構造不良 skip {n_broken} / 内容重複 dedup {n_dup} / うち現banlist違反 {n_banlist}=採用)")
    print(f"  リーダー多様性 = {len(leaders)} 種")
    print(f"  → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
