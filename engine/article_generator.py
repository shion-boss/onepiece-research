# -*- coding: utf-8 -*-
"""
note.com 向けデッキ分析記事ジェネレーター (完全ローカル)
Claude API 不要。deck_analyzer の出力 + matchup matrix + 実戦ログ解析 から Markdown 記事を組み立てる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MatchupCell:
    deck_b_name: str
    winrate: float
    wins: int
    losses: int
    avg_turns: float


def generate_article(
    strategy: dict,
    matchup_rows: list[dict],
    deck_name_map: dict[str, str],
) -> str:
    """デッキ戦略データとマッチアップ行から note 記事 (Markdown) を生成する。

    Args:
        strategy: /api/decks/{slug}/strategy の返り値 dict
        matchup_rows: matchup_matrix の該当デッキ行 (row リスト)
        deck_name_map: slug -> デッキ名 の対応辞書
    """
    deck_name    = strategy.get("deck_name", "不明")
    leader_name  = strategy.get("leader_name", "")
    leader_color = "・".join(strategy.get("leader_color", []))
    archetype    = strategy.get("archetype", "")
    speed        = strategy.get("speed", "")
    defense      = strategy.get("defense", "")
    consistency  = strategy.get("consistency", "")
    summary      = strategy.get("strategy_summary", "")
    avg_cost     = strategy.get("avg_cost", 0)
    counter_total = strategy.get("counter_total", 0)
    blocker_count = strategy.get("blocker_count", 0)
    strengths    = strategy.get("strengths", [])
    weaknesses   = strategy.get("weaknesses", [])
    key_cards    = strategy.get("key_cards", [])
    mulligan_keep  = strategy.get("mulligan_keep_criteria", [])
    mulligan_throw = strategy.get("mulligan_throw_criteria", [])
    ideal_moves  = strategy.get("ideal_moves", [])
    ai_hints     = strategy.get("ai_hints", [])

    # マッチアップ集計
    cells: list[MatchupCell] = []
    for cell in matchup_rows:
        wr = cell.get("winrate")
        if wr is None:
            continue
        name = deck_name_map.get(cell["deck_b"], cell["deck_b"])
        cells.append(MatchupCell(
            deck_b_name=name,
            winrate=wr,
            wins=cell.get("wins", 0),
            losses=cell.get("losses", 0),
            avg_turns=cell.get("avg_turns", 0),
        ))
    cells.sort(key=lambda c: -c.winrate)

    valid_cells = [c for c in cells if c.wins + c.losses > 0]
    overall_wr = (
        sum(c.winrate for c in valid_cells) / len(valid_cells) * 100
        if valid_cells else 0
    )
    favorable   = [c for c in valid_cells if c.winrate >= 0.6]
    unfavorable = [c for c in valid_cells if c.winrate < 0.5]

    lines: list[str] = []

    # タイトル
    lines.append(f"# 【{deck_name}】デッキ研究 ― AIシミュレーション分析レポート\n")

    # 結論
    lines.append("## 結論から言う\n")
    tier = _tier_label(overall_wr)
    lines.append(
        f"**{deck_name}** は現在の環境で {tier}（対メタ平均勝率 **{overall_wr:.1f}%**）に位置します。"
    )
    lines.append(
        f"アーキタイプは **{archetype}**、速度 **{speed}**、防御力 **{defense}**、安定性 **{consistency}** です。"
    )
    lines.append(f"\n{summary}\n")

    # デッキ概要表
    lines.append("## デッキ概要\n")
    lines.append("| 項目 | 詳細 |")
    lines.append("|---|---|")
    lines.append(f"| リーダー | {leader_name}（{leader_color}） |")
    lines.append(f"| アーキタイプ | {archetype} |")
    lines.append(f"| 速度 | {speed} |")
    lines.append(f"| 防御力 | {defense} |")
    lines.append(f"| 安定性 | {consistency} |")
    lines.append(f"| 平均コスト | {avg_cost:.2f} |")
    lines.append(f"| カウンター総量 | {counter_total:,} |")
    lines.append(f"| ブロッカー枚数 | {blocker_count}枚 |")
    lines.append("")

    # 強み・弱点
    lines.append("## 強みと弱点\n")
    lines.append("### 強み\n")
    for s in strengths:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("### 弱点\n")
    for w in weaknesses:
        lines.append(f"- {w}")
    lines.append("")

    # マッチアップ表
    if valid_cells:
        lines.append("## 対メタ勝率（AIシミュレーション / n=20）\n")
        lines.append("| 対戦相手 | 勝率 | 戦績 | 平均ターン |")
        lines.append("|---|---|---|---|")
        for c in cells:
            if c.wins + c.losses == 0:
                continue
            mark = " ✓" if c.winrate >= 0.6 else (" ✗" if c.winrate < 0.5 else "")
            lines.append(
                f"| {c.deck_b_name}{mark} | **{c.winrate*100:.0f}%** "
                f"| {c.wins}勝{c.losses}敗 | {c.avg_turns:.1f}T |"
            )
        lines.append("")

        if favorable:
            lines.append(
                f"**有利マッチ（60%以上）**: {', '.join(c.deck_b_name for c in favorable)}"
            )
        if unfavorable:
            lines.append(
                f"**不利マッチ（50%未満）**: {', '.join(c.deck_b_name for c in unfavorable)}"
            )
        lines.append("")

    # キーカード
    if key_cards:
        lines.append("## キーカード\n")
        role_groups: dict[str, list[dict]] = {}
        for k in key_cards:
            role_groups.setdefault(k.get("role", "other"), []).append(k)
        role_order = ["finisher", "removal", "draw", "search", "ramp", "blocker", "counter", "synergy", "other"]
        role_label = {
            "finisher": "フィニッシャー", "removal": "除去",
            "draw": "ドロー加速", "search": "サーチ",
            "ramp": "ランプ", "blocker": "ブロッカー",
            "counter": "カウンター要員", "synergy": "シナジー",
            "other": "その他",
        }
        for role in role_order:
            cards = role_groups.get(role, [])
            if not cards:
                continue
            lines.append(f"### {role_label.get(role, role)}\n")
            for k in cards:
                lines.append(
                    f"**{k['name']}**（{k['card_id']}）×{k['count']} / "
                    f"コスト{k.get('cost', '?')}  \n{k.get('reason', '')}"
                )
                lines.append("")

    # マリガン
    lines.append("## マリガン基準\n")
    lines.append("### キープ\n")
    for c in mulligan_keep:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("### 戻す\n")
    for c in mulligan_throw:
        lines.append(f"- {c}")
    lines.append("")

    # 理想ムーブ
    if ideal_moves:
        lines.append("## 理想の立ち回り\n")
        lines.append("| ターン | 行動 |")
        lines.append("|---|---|")
        for m in ideal_moves:
            desc = m.get("description", "")
            candidates = m.get("candidate_cards", [])
            cell = desc
            if candidates:
                cell += f"（候補: {', '.join(candidates[:3])}）"
            lines.append(f"| T{m['turn']} | {cell} |")
        lines.append("")

    # 立ち回りのコツ（デッキ固有ポイントのみ）
    if ai_hints:
        lines.append("## 立ち回りのコツ\n")
        for h in ai_hints:
            lines.append(f"- {h}")
        lines.append("")

    # まとめ
    lines.append("## まとめ\n")
    lines.append(
        f"{deck_name}は **{archetype}** 寄りのデッキで、"
        f"対メタ平均勝率は **{overall_wr:.1f}%**（{tier}）です。"
    )
    if favorable:
        lines.append(
            f"{', '.join(c.deck_b_name for c in favorable[:3])} などに対して優位に立てる一方、"
        )
    if unfavorable:
        lines.append(
            f"{', '.join(c.deck_b_name for c in unfavorable[:3])} には注意が必要です。"
        )
    lines.append(
        f"\n防御力「{defense}」・安定性「{consistency}」という特性を活かした"
        "プレイングを意識してください。"
    )
    lines.append("")

    # 免責事項
    lines.append("---\n")
    lines.append(
        "> **免責事項**: 本記事の勝率データは非公式のAIシミュレーター（GreedyAI）による近似値です（各対戦n=20）。"
        "実際の人間のプレイや最新環境とは異なる場合があります。参考情報としてご活用ください。"
    )

    return "\n".join(lines)


def _tier_label(wr: float) -> str:
    if wr >= 85:
        return "Tier S（勝率85%以上）"
    if wr >= 75:
        return "Tier A（勝率75%以上）"
    if wr >= 50:
        return "Tier B（勝率50〜74%）"
    if wr >= 25:
        return "Tier C（勝率25〜49%）"
    return "Tier D（勝率25%未満）"
