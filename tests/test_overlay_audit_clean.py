# -*- coding: utf-8 -*-
"""overlay 監査 (`scripts/audit_overlay_vs_faq.py`) の severity が **0** であること。

⚠ 2026-08-24 まで sev1-2 が 31〜33 件残っていた。 内訳を精査すると:
  - `don_count_condition_unmodeled` x2 (P-159) = **監査側の誤検出**
    (`self_leader_attached_don_ge` を認識していなかった。 条件は effects.py:1734 で実装済) → 監査を是正
  - 残り 31 件 = `faq_negation` / `faq_attention_N` (= 公式 FAQ 本文に否定表現/注意語がある
    という heuristic フラグ)。 該当カードの公式 Q&A は `db/faq_qa_status.json` で
    **全件決着済** (conform/fixed/n-a) を機械照合して確認 → acknowledged へ

このテストは 「新しい issue 種別が出たら落ちる」 ためのもの。 acknowledged は
(card_id, issue) 単位なので、 **同じカードの別 issue** も検出できる。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_overlay_audit_has_no_open_severity():
    path = ROOT / "db" / "overlay_audit.json"
    if not path.exists():
        import pytest
        pytest.skip("overlay_audit.json が無い (scripts/audit_overlay_vs_faq.py を先に実行)")
    d = json.loads(path.read_text())
    items = d if isinstance(d, list) else (d.get("items") or [])
    open_items = [
        {"card_id": it.get("card_id"), "name": it.get("name"),
         "severity": it.get("severity"), "issues": it.get("issues")}
        for it in items if int(it.get("severity") or 0) >= 1
    ]
    assert not open_items, (
        f"未処理の overlay 監査 issue が {len(open_items)} 件ある。 "
        "実バグなら overlay/engine を直し、 heuristic な誤検出なら "
        "**根拠を書いて** db/audit_acknowledged.json へ登録すること: "
        f"{open_items[:5]}"
    )


def test_acknowledged_entries_are_documented():
    """acknowledged には **理由メモ** が併記されていること (無言の抑制を防ぐ)。"""
    ack = json.loads((ROOT / "db" / "audit_acknowledged.json").read_text())
    notes = [k for k in ack if k.startswith("_")]
    assert notes, "acknowledged に理由メモ (_comment / _acknowledge_note_*) が無い"
    cards = [k for k in ack if not k.startswith("_")]
    assert cards, "acknowledged が空"
