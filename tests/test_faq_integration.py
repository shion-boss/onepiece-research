# -*- coding: utf-8 -*-
"""公式 FAQ (cardqa) を **実行可能な検査** に結び付けるテスト。

⚠ **2026-08-10 に全面書き換え**。 それまでこのファイルは 200 件の
``pytest.skip("placeholder — implementation pending")`` だった = **テスト数だけ 200 増えて
中身は 1 つも検証していない** 状態 (= カバレッジの幻)。 実際、 同日に摘出した 7 件の
公式違反は、 この 200 件をいくら回しても永久に検出できなかった。

**何が本当のオラクルか**
    公式 Q&A の裁定は `db/faq_qa_status.json` (台帳) + `scripts/faq_qa_manifest.py` +
    毎時 cron `optcg-faq-conformance` で 1 件ずつ行い、 違反なら engine/overlay を直して
    `docs/official_rulings.md` に一次情報つきで記録し、 **個別の回帰テスト** を
    `tests/test_effect_interactions.py` 等に置く、 という運用が実体。
    このファイルの役割は **その運用から Q&A が こぼれ落ちないことの保証** に絞る。

**このファイルがやること (全件が実際に走る)**
    1. 抽出された Q&A が **全件 台帳に存在** する (= 取りこぼしゼロ)
    2. 裁定済 (conform/fixed/n/a) の Q&A は **根拠 (note) を持つ** (= status だけ書き換えて
       済ませていない)
    3. 未裁定 (pending) の件数が **増えない** (= 退行ラチェット)
    4. シナリオが一意に定まる Q&A は **engine レベルの実テスト** にする (末尾)

⚠ 「200 件の Q&A を機械的に自動テスト化する」 のは **やらない**。 cardqa の Q は
  「このカード」 「キャラA」 のように **card_id を持たない** ものが大半 (200 件中 182 件) で、
  対象カードの特定自体が裁定作業の本体だから。 雑に自動生成すると
  **overlay のバグを 「正解」 として固定する** (= backfill テストで実際に起きた事故)。

参照:
- ``scripts/extract_faq_test_cases.py``: 抽出ロジック / CLI / スコアリング
- ``db/faq/cardqa_*.json``: 公式 Q&A 一次情報 (gitignore 済み、 scraper 取得)
- ``db/faq_qa_status.json``: 全 1,205 件の裁定台帳 (= 進捗の真)
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

# プロジェクトルートを sys.path に通す (conftest.py と同じ。 import の安定化)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.extract_faq_test_cases import FaqCase, extract_test_cases  # noqa: E402

_LIMIT = int(os.environ.get("FAQ_TEST_LIMIT", "200"))
_CASES: list[FaqCase] = extract_test_cases(limit=_LIMIT)
_LEDGER_PATH = _ROOT / "db" / "faq_qa_status.json"

# 未裁定 (pending) 件数の上限 = 退行ラチェット。 cron が裁定を進めたら **下げる**。
# 上げるのは 「新弾で Q&A が増えた」 時だけ (その時は理由をコミットメッセージに書く)。
_PENDING_CEILING = 56


def _qid(q: str, a: str) -> str:
    """台帳のキー (scripts/faq_qa_manifest.py:qid_of と同一定義)。"""
    return hashlib.sha1((q + "\n" + a).encode("utf-8")).hexdigest()[:12]


def _ledger() -> dict:
    if not _LEDGER_PATH.exists():
        pytest.skip("db/faq_qa_status.json が無い (台帳未生成)")
    return json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))


def _unique_cases() -> dict[str, FaqCase]:
    """qid でユニーク化した Q&A。

    ⚠ 抽出器は パラレル違いの同一 Q&A を重複して返す (200 件 → ユニーク 99 件)。
      重複したまま数えると 「テスト件数」 が実態の 2 倍に見える。
    """
    out: dict[str, FaqCase] = {}
    for c in _CASES:
        out.setdefault(_qid(c.q, c.a), c)
    return out


def test_extracted_cases_are_all_tracked_in_ledger():
    """抽出された Q&A が **全件 台帳にある** = conformance 運用から漏れていない。

    抽出器 (= 「テストにしやすい」 スコアで上位を選ぶ) が拾った Q&A を台帳が知らない、
    という状態は 「重要そうな Q&A が永久に未裁定」 を意味する。
    """
    if not _CASES:
        pytest.skip("cardqa が見つからない (db/faq/cardqa_*.json)")
    led = _ledger()
    missing = [c.case_id for k, c in _unique_cases().items() if k not in led]
    assert not missing, (
        f"抽出された Q&A {len(missing)} 件が台帳に無い (= 裁定対象から漏れている): "
        f"{missing[:10]}\n"
        f"→ `.venv/bin/python scripts/faq_qa_manifest.py` で台帳を同期する"
    )


def test_adjudicated_cases_carry_evidence():
    """裁定済 (conform/fixed/n/a) の Q&A は **根拠 (note) を持つ**。

    status だけ書き換えて note を空のままにすると 「調べた」 と 「調べたことにした」 の
    区別が付かなくなる (= 台帳が信用できなくなる)。 実測では裁定済の note は
    最短 43 文字 / 中央値 165 文字なので、 40 文字を下限にする。
    """
    if not _CASES:
        pytest.skip("cardqa が見つからない")
    led = _ledger()
    thin = []
    for k, c in _unique_cases().items():
        e = led.get(k) or {}
        if e.get("status") in ("conform", "fixed", "n/a"):
            note = (e.get("note") or "").strip()
            if len(note) < 40:
                thin.append(f"{c.case_id} [{e['status']}] note={note[:30]!r}")
    assert not thin, (
        "裁定済なのに根拠 (note) が薄い Q&A がある = 「調べたことにした」 と区別が付かない:\n  "
        + "\n  ".join(thin[:10])
    )


def test_fixed_cases_reference_a_concrete_card_or_rule():
    """`fixed` (= engine/overlay を直した) の note は **具体物** を指す。

    「直した」 とだけ書かれた note は 半年後に検証できない。 card_id (OP12-020 等) か
    公式ルール条番号 (8-4-1-3 等) か cardqa の出典 (cardqa_op_12) のいずれかを含むこと。
    """
    if not _CASES:
        pytest.skip("cardqa が見つからない")
    led = _ledger()
    concrete = re.compile(r"(?:[A-Z]{2,4}\d{2}-\d{3}|\d+-\d+-\d+|cardqa_[a-z]{2}_\d{2})")
    vague = []
    for k, c in _unique_cases().items():
        e = led.get(k) or {}
        if e.get("status") == "fixed" and not concrete.search(e.get("note") or ""):
            vague.append(f"{c.case_id}: {(e.get('note') or '')[:60]}")
    assert not vague, (
        "fixed の note が具体物 (card_id / ルール条番号 / cardqa 出典) を指していない:\n  "
        + "\n  ".join(vague[:10])
    )


def test_pending_backlog_does_not_grow():
    """未裁定 (pending) の件数が **増えない** = 退行ラチェット。

    cron が裁定を進めたら `_PENDING_CEILING` を下げる。 上げてよいのは新弾で Q&A が
    増えた時だけ (理由をコミットメッセージに残す)。
    """
    if not _CASES:
        pytest.skip("cardqa が見つからない")
    led = _ledger()
    stats = Counter(
        (led.get(k) or {}).get("status", "missing") for k in _unique_cases()
    )
    pending = stats.get("pending", 0)
    assert pending <= _PENDING_CEILING, (
        f"未裁定が増えている: pending={pending} > 上限 {_PENDING_CEILING} (内訳 {dict(stats)})。\n"
        f"新弾で Q&A が増えたなら _PENDING_CEILING を上げ、 理由をコミットに書く。"
    )


# ============================================================ #
#  engine レベルの実テスト
#  = 対象カードとシナリオが **Q&A の文面から一意に定まる** ものだけを書く。
#    (「このカード」 しか書かれていない Q&A は 対象特定が裁定作業の本体なので
#     台帳側で扱う。 ここで雑に推測すると overlay のバグを正解として固定する)
# ============================================================ #

def _repo_overlay():
    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay

    return (
        CardRepository.from_json(_ROOT / "db" / "cards.json"),
        load_effect_overlay(_ROOT / "db" / "card_effects.json"),
    )


def _state(repo, overlay, leader0: str, leader1: str = "OP01-001"):
    from engine.core import GameState, InPlay, Phase, Player, reset_iid

    reset_iid()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader0), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(leader1), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get("OP01-013")] * 25
        p.life = [repo.get("OP01-013")] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=overlay)
    st.turn_player_idx, st.turn_number = 0, 9
    return st, p0, p1


def test_prb01_002_op05_005_karasu_requires_kakumeigun_leader():
    """`prb_01#002` (台帳 conform): OP05-005 カラスの【登場時】は
    **自分のリーダーが特徴《革命軍》を持つ場合** のみ発動する。

    公式 Q&A: 「特徴《革命軍》を持たないこのリーダーを使用している場合、 (パワー-1000 の)
    効果を発動できますか？」 → 「**いいえ、 できません**」
    """
    from engine.core import InPlay
    from engine.effects import trigger_on_play, resolve_triggers

    repo, overlay = _repo_overlay()

    def minus_applied(leader_id: str) -> int:
        st, me, opp = _state(repo, overlay, leader0=leader_id)
        karasu = InPlay.of(repo.get("OP05-005"), sickness=True)
        me.characters = [karasu]
        victim = InPlay.of(repo.get("OP01-013"), sickness=False)
        opp.characters = [victim]
        before = victim.power
        trigger_on_play(st, me, opp, karasu, overlay)
        resolve_triggers(st)
        return before - victim.power

    # 革命軍リーダー (OP05-001 サボ = 革命軍) なら -1000 が乗る
    assert minus_applied("OP05-001") == 1000, "革命軍リーダーで -1000 が適用されていない (前提崩れ)"
    # 非革命軍リーダー (OP01-001 = 麦わらの一味) では発動しない
    assert minus_applied("OP01-001") == 0, (
        "革命軍でないリーダーなのに OP05-005 の【登場時】が発動している (prb_01#002 違反)"
    )


def test_op11_028_attack_legality_is_judged_before_paying_cost():
    """`op_11#028` (台帳 conform): アタック可否は **コスト支払い前の手札** で判定する。

    公式 Q&A: 「直前の相手のターンに相手が『OP08-043 エドワード・ニューゲート』の【登場時】
    効果を発動しており、 次の自分のターン中に、 自分の手札が6枚の場合、 自分の手札2枚を捨てて
    このキャラでアタックすることができますか？」 → 「**いいえ、 できません**」

    ⭐ この Q&A の争点は OP08-043 の持続時間 **ではない** (台帳の裁定より):
      「このキャラ」 = OP11-058 ルフィ (「自分の手札が5枚以上ある場合、 このキャラはアタック
      できない」)。 手札6枚では **アタック宣言の時点で** 不可なので、 手札2枚を捨てて 4 枚に
      できるかどうかは関係ない。 = 「手札を捨てれば 5 枚未満になるから撃てる」 は誤り。

    ⚠ 台帳の note を読まずに 「OP08-043 の duration の話」 と読むと **engine が正しいのに
      テストが落ちる**。 対象カードの特定が裁定作業の本体、 という実例そのもの。
    """
    from engine.core import InPlay
    from engine.game import legal_actions, AttackLeader

    repo, overlay = _repo_overlay()

    def can_attack(hand_n: int) -> bool:
        st, me, opp = _state(repo, overlay, leader0="OP01-001")
        luffy = InPlay.of(repo.get("OP11-058"), sickness=False)
        me.characters = [luffy]
        me.hand = [repo.get("OP01-013")] * hand_n
        from engine.effects import evaluate_static_effects
        evaluate_static_effects(st, overlay)
        return any(
            isinstance(a, AttackLeader) and a.attacker_iid == luffy.instance_id
            for a in legal_actions(st)
        )

    assert can_attack(6) is False, (
        "手札6枚 (=5枚以上) なのに OP11-058 でアタックできてしまう "
        "(公式: アタック可否はコスト支払い **前** の手札で判定、 op_11#028)"
    )
    assert can_attack(4) is True, "手札4枚 (=5枚未満) ならアタックできるはず (前提崩れ)"
