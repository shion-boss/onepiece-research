#!/usr/bin/env python3
"""inline 監査で正しいと確認した cluster 代表を渡すと、 (overlay+text) 等価な全メンバーを
full_db_progress.json の audited に追加し、 signature_clusters.json を再生成 (= 監査済除去)。

[[project_human_optional_cost_gate]] の等価署名フェーズの grind 用。
使い方: python scripts/mark_audited_clusters.py REP1 REP2 ...
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFF = ROOT / "db" / "card_effects.json"
CARDS = ROOT / "db" / "cards.json"
PROG = ROOT / "db" / "audit_llm" / "full_db_progress.json"
QUEUE = ROOT / "db" / "audit_llm" / "signature_clusters.json"


def main(reps: list[str]) -> None:
    eff = json.loads(EFF.read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in json.loads(CARDS.read_text(encoding="utf-8"))}
    prog = json.loads(PROG.read_text(encoding="utf-8"))
    audited = set(prog.get("audited", []))

    def sig(cid):
        e = eff.get(cid)
        o = json.dumps([{k: v for k, v in x.items() if k != "_text"} for x in e if isinstance(x, dict)],
                       ensure_ascii=False, sort_keys=True) if isinstance(e, list) else None
        c = cards.get(cid, {})
        t = re.sub(r"\s+", "", ((c.get("text") or "") + "|" + (c.get("trigger") or "")).strip())
        # ‼(U+203C)/！！(全角)/!! を畳む。 同一効果の parallel が DON 記号の表記揺れだけで
        # 署名割れ → base を mark しても片方が未マークで残る bug を防ぐ。
        t = t.replace("‼", "!!").replace("！！", "!!")
        return (o, t)

    # 全 (overlay+text) → members
    sig2 = defaultdict(list)
    for cid, e in eff.items():
        if cid in cards and e:
            sig2[sig(cid)].append(cid)

    added = set()
    for rep in reps:
        if rep not in eff:
            print(f"  ! {rep} not found")
            continue
        for m in sig2.get(sig(rep), [rep]):
            if m not in audited:
                audited.add(m); added.add(m)

    prog["audited"] = sorted(audited)
    # queue 再生成 (audited を含まない署名のみ)
    clusters = []
    for s, cs in sig2.items():
        if any(c in audited for c in cs):
            continue
        rep = sorted(cs)[0]
        clusters.append({"rep": rep, "size": len(cs), "members": sorted(cs),
                         "text": (cards[rep].get("text") or "")[:90],
                         "trigger": (cards[rep].get("trigger") or "")[:50]})
    clusters.sort(key=lambda c: -c["size"])

    # meta 更新
    eq = prog["meta"].get("equivalence_phase", {})
    eq["remaining_unique_sig"] = len(clusters)
    eq["remaining_cards"] = sum(c["size"] for c in clusters)
    prog["meta"]["equivalence_phase"] = eq
    # union で 重複排除 (audited ∩ vanilla / ∩ equivalence の二重カウント防止)。
    prog["meta"]["total_verified"] = len(
        audited
        | set(prog.get("vanilla_verified", []))
        | set(prog.get("equivalence_verified", []))
    )

    PROG.write_text(json.dumps(prog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    QUEUE.write_text(json.dumps(clusters, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"audited +{len(added)} (計 {len(audited)})、 残 cluster {len(clusters)} (= {sum(c['size'] for c in clusters)} 枚)")


if __name__ == "__main__":
    main(sys.argv[1:])
