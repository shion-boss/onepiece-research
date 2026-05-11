# -*- coding: utf-8 -*-
"""
GreedyAI 対戦ログの解析モジュール。
相手デッキを固定した上で勝ち試合・負け試合を比較し、
行動パターンの差分から「vs 相手 攻略のポイント」を抽出する。
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# ── 正規表現 ────────────────────────────────────────────────────────
_LINE_RE = re.compile(r'^T(\d+) P(\d+): (.+)$')
_PLAY_RE = re.compile(r'^play: (.+?) \(cost \d+ pay \d+\)')
_EVENT_RE = re.compile(r'^event: (.+?) \(cost \d+ pay \d+\)')
_ATK_RE = re.compile(r'^atk: (.+?)\(P=\d+\) -> (.+?)\(P=\d+\)')
_COUNTER_RE = re.compile(r'counter \+(\d+)')
_KO_RE = re.compile(r'^KO: (.+)$')
_BLOCKER_RE = re.compile(r'^blocker: (.+)$')


@dataclass
class GameStats:
    turns: int
    won: bool
    mulligan: bool = False
    first_play_turn: Optional[int] = None
    first_hit_given_turn: Optional[int] = None   # 我々が相手ライフを最初に削ったターン
    first_hit_taken_turn: Optional[int] = None   # 相手が我々ライフを最初に削ったターン
    cards_played: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    events_played: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # 自分の攻撃
    attacks_total: int = 0
    attacks_blocked: int = 0
    attacks_life_hit: int = 0
    attacks_ko: int = 0
    # 相手の攻撃（防御側の挙動を正規化するために追跡）
    opp_attacks_total: int = 0
    # 防御行動
    defense_counter_uses: int = 0
    defense_counter_amount: int = 0
    defense_blocked: int = 0
    defense_ko_taken: int = 0
    blocker_uses: int = 0
    # KO詳細
    ko_sources: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    ko_targets: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    ko_lost: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def parse_game_log(log: list[str], winner: int, turns: int, our_idx: int = 0) -> GameStats:
    """単一ゲームのログを解析して GameStats を返す。

    our_idx: デッキAのプレイヤーインデックス（通常 0）
    """
    stats = GameStats(turns=turns, won=(winner == our_idx))

    last_our_attack = False
    last_attacker_name = ""

    for line in log:
        m = _LINE_RE.match(line)
        if not m:
            continue
        turn_n = int(m.group(1))
        player_n = int(m.group(2))
        action = m.group(3)
        is_our_turn = (player_n == our_idx)
        is_sub = action.startswith('  ')
        body = action.strip()

        if not is_sub:
            # ── メインアクション ──
            if 'マリガン' in body and is_our_turn:
                stats.mulligan = True

            pm = _PLAY_RE.match(body)
            if pm and is_our_turn:
                name = pm.group(1).strip()
                stats.cards_played[name] += 1
                if stats.first_play_turn is None:
                    stats.first_play_turn = turn_n

            em = _EVENT_RE.match(body)
            if em and is_our_turn:
                stats.events_played[em.group(1).strip()] += 1

            am = _ATK_RE.match(body)
            if am:
                last_attacker_name = am.group(1).strip()
                if is_our_turn:
                    stats.attacks_total += 1
                    last_our_attack = True
                else:
                    stats.opp_attacks_total += 1   # 相手の攻撃をカウント
                    last_our_attack = False

        else:
            # ── サブアクション ──
            if body == 'blocked':
                if last_our_attack:
                    stats.attacks_blocked += 1
                else:
                    stats.defense_blocked += 1

            elif body == 'survived':
                if not last_our_attack:
                    stats.defense_blocked += 1

            elif body.startswith('KO:'):
                km = _KO_RE.match(body)
                if km:
                    ko_name = km.group(1).strip()
                    if last_our_attack:
                        stats.attacks_ko += 1
                        stats.ko_sources[last_attacker_name] += 1
                        stats.ko_targets[ko_name] += 1
                    else:
                        stats.defense_ko_taken += 1
                        stats.ko_lost[ko_name] += 1

            elif body.startswith('hit:'):
                parts = body.split()
                if len(parts) >= 2 and parts[1].startswith('P'):
                    try:
                        hit_player = int(parts[1][1:])
                        if hit_player != our_idx:
                            stats.attacks_life_hit += 1
                            if stats.first_hit_given_turn is None:
                                stats.first_hit_given_turn = turn_n
                        else:
                            if stats.first_hit_taken_turn is None:
                                stats.first_hit_taken_turn = turn_n
                    except ValueError:
                        pass

            elif body.startswith('counter +') and not last_our_attack:
                # 相手の攻撃に対して我々がカウンターを使用
                cm = _COUNTER_RE.search(body)
                if cm:
                    stats.defense_counter_uses += 1
                    stats.defense_counter_amount += int(cm.group(1))

            elif body.startswith('blocker:') and not last_our_attack:
                stats.blocker_uses += 1

    return stats


# ── 集計 ─────────────────────────────────────────────────────────────

def _mean(vals: list[float | int]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def aggregate_group(games: list[GameStats]) -> dict:
    """同一グループ（勝ち/負け）の GameStats リストを集計して dict を返す。"""
    n = len(games)
    if n == 0:
        return {}

    cards_total: dict[str, int] = defaultdict(int)
    events_total: dict[str, int] = defaultdict(int)
    ko_src_total: dict[str, int] = defaultdict(int)
    ko_tgt_total: dict[str, int] = defaultdict(int)
    ko_lost_total: dict[str, int] = defaultdict(int)

    turns_list, first_play, first_hit_given, first_hit_taken = [], [], [], []

    for g in games:
        turns_list.append(g.turns)
        if g.first_play_turn is not None:
            first_play.append(g.first_play_turn)
        if g.first_hit_given_turn is not None:
            first_hit_given.append(g.first_hit_given_turn)
        if g.first_hit_taken_turn is not None:
            first_hit_taken.append(g.first_hit_taken_turn)
        for k, v in g.cards_played.items():
            cards_total[k] += v
        for k, v in g.events_played.items():
            events_total[k] += v
        for k, v in g.ko_sources.items():
            ko_src_total[k] += v
        for k, v in g.ko_targets.items():
            ko_tgt_total[k] += v
        for k, v in g.ko_lost.items():
            ko_lost_total[k] += v

    total_atk      = sum(g.attacks_total for g in games)
    total_opp_atk  = sum(g.opp_attacks_total for g in games)
    total_life     = sum(g.attacks_life_hit for g in games)
    total_ko       = sum(g.attacks_ko for g in games)
    total_blk      = sum(g.attacks_blocked for g in games)
    total_cnt      = sum(g.defense_counter_uses for g in games)
    total_cnt_amt  = sum(g.defense_counter_amount for g in games)
    total_def_blk  = sum(g.defense_blocked for g in games)
    total_ko_lost  = sum(g.defense_ko_taken for g in games)
    total_blocker  = sum(g.blocker_uses for g in games)
    mull_n         = sum(1 for g in games if g.mulligan)

    def _top(d: dict[str, int], k: int = 6) -> list[tuple[str, float]]:
        return [(name, cnt / n) for name, cnt in sorted(d.items(), key=lambda x: -x[1])[:k]]

    return {
        "n": n,
        "avg_turns":               _mean(turns_list),
        "avg_first_play_turn":     _mean(first_play),
        "avg_first_hit_given_turn": _mean(first_hit_given),
        "avg_first_hit_taken_turn": _mean(first_hit_taken),
        "mulligan_rate":           mull_n / n,
        "avg_attacks":             total_atk / n,
        "avg_opp_attacks":         total_opp_atk / n,
        "attack_life_rate":        total_life / total_atk if total_atk else 0.0,
        "attack_ko_rate":          total_ko / total_atk if total_atk else 0.0,
        "attack_blocked_rate":     total_blk / total_atk if total_atk else 0.0,
        # 防御カウンター：生回数と「相手攻撃1回あたり率」の両方を持つ
        "avg_counter_uses":        total_cnt / n,
        "counter_per_opp_attack":  total_cnt / total_opp_atk if total_opp_atk else 0.0,
        "avg_counter_amount":      total_cnt_amt / total_cnt if total_cnt else 0.0,
        "avg_defense_blocked":     total_def_blk / n,
        "avg_ko_taken":            total_ko_lost / n,
        "avg_blocker_uses":        total_blocker / n,
        "top_cards":     _top(cards_total),
        "top_events":    _top(events_total, 4),
        "top_ko_sources": _top(ko_src_total, 4),
        "top_ko_targets": _top(ko_tgt_total, 4),
        "top_ko_lost":   _top(ko_lost_total, 4),
    }


# ── レポート生成 ─────────────────────────────────────────────────────

def _summarize_board_analyses(
    analyses: list,  # list[GameAnalysis]
    won_indices: list[int],
) -> dict:
    """GameAnalysis リストを勝ち/負けグループに分けて集計する。

    Returns:
        {
            "win": {"avg_score": float, "max_lead": float, "max_deficit": float, "comeback_rate": float},
            "loss": {...},
            "top_turning_points_win": list[str],   # 上位3ターニングポイントのlog
            "top_turning_points_loss": list[str],
        }
    """
    if not analyses:
        return {}

    def _agg(idxs: list[int]) -> dict:
        group = [analyses[i] for i in idxs if i < len(analyses)]
        if not group:
            return {}
        summaries = [a.summary for a in group if a.summary is not None]
        if not summaries:
            return {}
        return {
            "avg_score":   sum(s.avg_score   for s in summaries) / len(summaries),
            "max_lead":    sum(s.max_lead     for s in summaries) / len(summaries),
            "max_deficit": sum(s.max_deficit  for s in summaries) / len(summaries),
            "comeback_rate": sum(1 for s in summaries if s.comeback) / len(summaries),
        }

    lost_indices = [i for i in range(len(analyses)) if i not in won_indices]

    def _top_tps(idxs: list[int], side: str, top: int = 3) -> list[str]:
        """side でフィルタしてから delta 絶対値の大きい順に返す。"""
        tps = []
        for i in idxs:
            if i < len(analyses):
                tps.extend(t for t in analyses[i].turning_points if t.side == side)
        tps.sort(key=lambda t: -abs(t.delta))
        return [tp.log for tp in tps[:top] if tp.log.strip()]

    return {
        "win":  _agg(won_indices),
        "loss": _agg(lost_indices),
        # 勝ち試合: 自分が優勢になった局面 / 負け試合: 自分が不利になった局面
        "top_turning_points_win":  _top_tps(won_indices, side="self_gain"),
        "top_turning_points_loss": _top_tps(lost_indices, side="self_loss"),
    }


def generate_battle_report(
    all_stats: list[GameStats],
    deck_name: str,
    opponent_name: str,
    board_analyses: list | None = None,  # list[GameAnalysis] | None
) -> str:
    """相手固定のゲームログ統計から note 攻略記事用 Markdown を生成する。

    勝ち/負け試合の行動差分を「vs {opponent_name} 攻略のポイント」として抽出する。
    同一の相手と戦ったログだけを渡すことで、相性要因を除いた行動の差を読み取れる。
    board_analyses: 各試合の GameAnalysis (record_snapshots=True で取得可能)。渡すと盤面評価セクションが追加される。
    """
    wins = [g for g in all_stats if g.won]
    losses = [g for g in all_stats if not g.won]
    wa = aggregate_group(wins)
    la = aggregate_group(losses)

    n_total  = len(all_stats)
    n_wins   = len(wins)
    n_losses = len(losses)
    overall_wr = n_wins / n_total * 100 if n_total else 0.0

    lines: list[str] = []

    # タイトル＆イントロ
    lines.append(f"# 【{deck_name}】vs {opponent_name} 攻略 — AIシミュレーション分析\n")
    lines.append(
        f"> **分析条件**: 対戦相手を {opponent_name} に固定して{n_total}戦シミュレーション。"
        f"結果は **{n_wins}勝 / {n_losses}敗**（勝率 **{overall_wr:.0f}%**）。"
        f"勝ち試合と負け試合の行動パターンを比較することで、"
        f"相性要因ではなく **プレイングの差** として現れる攻略ポイントを抽出します。\n"
    )

    # ── 勝ち/負け比較サマリー ──────────────────────────────────────
    lines.append("## 勝ち試合 vs 負け試合 サマリー\n")
    lines.append(f"| 指標 | 勝ち試合（{n_wins}戦） | 負け試合（{n_losses}戦） |")
    lines.append("|---|---|---|")

    def _fmt(val: float, fmt: str, suffix: str) -> str:
        return "—" if val == 0 else f"{val:{fmt}}{suffix}"

    rows = [
        ("平均ターン数",             wa.get("avg_turns", 0),                   la.get("avg_turns", 0),                   ".1f", "T"),
        ("初キャラ登場ターン",        wa.get("avg_first_play_turn", 0),        la.get("avg_first_play_turn", 0),        ".1f", "T"),
        ("初ライフダメージ(与)",      wa.get("avg_first_hit_given_turn", 0),   la.get("avg_first_hit_given_turn", 0),   ".1f", "T"),
        ("初ライフダメージ(被)",      wa.get("avg_first_hit_taken_turn", 0),   la.get("avg_first_hit_taken_turn", 0),   ".1f", "T"),
        ("自分の平均攻撃数",          wa.get("avg_attacks", 0),                la.get("avg_attacks", 0),                ".1f", "回"),
        ("相手の平均攻撃数",          wa.get("avg_opp_attacks", 0),            la.get("avg_opp_attacks", 0),            ".1f", "回"),
        ("攻撃→ライフ到達率",         wa.get("attack_life_rate", 0) * 100,     la.get("attack_life_rate", 0) * 100,     ".0f", "%"),
        ("攻撃→KO率",                wa.get("attack_ko_rate", 0) * 100,        la.get("attack_ko_rate", 0) * 100,       ".0f", "%"),
        ("カウンター使用回数",         wa.get("avg_counter_uses", 0),           la.get("avg_counter_uses", 0),           ".1f", "回"),
        ("カウンター率(被攻撃1回あたり)", wa.get("counter_per_opp_attack", 0), la.get("counter_per_opp_attack", 0),     ".2f", "回"),
        ("平均カウンター量",           wa.get("avg_counter_amount", 0),         la.get("avg_counter_amount", 0),         ".0f", ""),
        ("マリガン率",                wa.get("mulligan_rate", 0) * 100,         la.get("mulligan_rate", 0) * 100,         ".0f", "%"),
        ("平均KO喪失数",              wa.get("avg_ko_taken", 0),               la.get("avg_ko_taken", 0),               ".1f", "体"),
    ]
    for label, wv, lv, fmt_s, suffix in rows:
        lines.append(f"| {label} | {_fmt(wv, fmt_s, suffix)} | {_fmt(lv, fmt_s, suffix)} |")
    lines.append("")

    # ── カード使用頻度 ────────────────────────────────────────────
    card_w = dict(wa.get("top_cards", []))
    card_l = dict(la.get("top_cards", []))
    all_card_keys = set(card_w) | set(card_l)
    if all_card_keys:
        lines.append("## キャラ登場頻度（1試合あたり）\n")
        lines.append("| カード | 勝ち試合 | 負け試合 |")
        lines.append("|---|---|---|")
        for k in sorted(all_card_keys, key=lambda k: -(card_w.get(k, 0) + card_l.get(k, 0)))[:8]:
            wv = f"{card_w[k]:.1f}回" if k in card_w else "—"
            lv = f"{card_l[k]:.1f}回" if k in card_l else "—"
            lines.append(f"| {k} | {wv} | {lv} |")
        lines.append("")

    # ── イベント頻度 ──────────────────────────────────────────────
    ev_w = dict(wa.get("top_events", []))
    ev_l = dict(la.get("top_events", []))
    all_ev_keys = set(ev_w) | set(ev_l)
    if all_ev_keys:
        lines.append("## イベント使用頻度（1試合あたり）\n")
        lines.append("| イベント | 勝ち試合 | 負け試合 |")
        lines.append("|---|---|---|")
        for k in sorted(all_ev_keys, key=lambda k: -(ev_w.get(k, 0) + ev_l.get(k, 0)))[:6]:
            wv = f"{ev_w[k]:.1f}回" if k in ev_w else "—"
            lv = f"{ev_l[k]:.1f}回" if k in ev_l else "—"
            lines.append(f"| {k} | {wv} | {lv} |")
        lines.append("")

    # ── KO分析 ───────────────────────────────────────────────────
    ko_src_w  = dict(wa.get("top_ko_sources", []))
    ko_src_l  = dict(la.get("top_ko_sources", []))
    ko_lost_w = dict(wa.get("top_ko_lost", []))
    ko_lost_l = dict(la.get("top_ko_lost", []))

    if ko_src_w or ko_src_l:
        lines.append("## KO分析\n")
        lines.append("### KOを取った主力キャラ（アタッカー / 1試合あたり）\n")
        lines.append("| キャラ | 勝ち試合 | 負け試合 |")
        lines.append("|---|---|---|")
        for k in sorted(set(ko_src_w) | set(ko_src_l),
                        key=lambda k: -(ko_src_w.get(k, 0) + ko_src_l.get(k, 0)))[:5]:
            wv = f"{ko_src_w[k]:.1f}体" if k in ko_src_w else "—"
            lv = f"{ko_src_l[k]:.1f}体" if k in ko_src_l else "—"
            lines.append(f"| {k} | {wv} | {lv} |")
        lines.append("")

        if ko_lost_w or ko_lost_l:
            lines.append("### よくKOされた自分のキャラ（1試合あたり）\n")
            lines.append("| キャラ | 勝ち試合 | 負け試合 |")
            lines.append("|---|---|---|")
            for k in sorted(set(ko_lost_w) | set(ko_lost_l),
                            key=lambda k: -(ko_lost_w.get(k, 0) + ko_lost_l.get(k, 0)))[:5]:
                wv = f"{ko_lost_w[k]:.1f}体" if k in ko_lost_w else "—"
                lv = f"{ko_lost_l[k]:.1f}体" if k in ko_lost_l else "—"
                lines.append(f"| {k} | {wv} | {lv} |")
            lines.append("")

    # ── 盤面評価の視点 ──────────────────────────────────────────
    if board_analyses:
        won_indices = [i for i, s in enumerate(all_stats) if s.won]
        bd = _summarize_board_analyses(board_analyses, won_indices)
        bw = bd.get("win", {})
        bl = bd.get("loss", {})
        tp_win  = bd.get("top_turning_points_win", [])
        tp_loss = bd.get("top_turning_points_loss", [])

        if bw or bl:
            lines.append("## 盤面評価の視点（9指標スコア分析）\n")
            lines.append(
                "> 盤面スコアはライフ・場のキャラ数・場のパワー合計・手札・DON・"
                "ブロッカー・アクティブキャラ・リーサル兆候の9指標を重み付きで合計した値です。\n"
            )

            def _sfmt(v: float | None) -> str:
                if v is None:
                    return "—"
                sign = "+" if v > 0 else ""
                return f"{sign}{v:,.0f}"

            if bw and bl:
                # 両グループある場合: 比較表
                lines.append("| 指標 | 勝ち試合 | 負け試合 |")
                lines.append("|---|---|---|")
                lines.append(f"| 平均盤面スコア | {_sfmt(bw.get('avg_score'))} | {_sfmt(bl.get('avg_score'))} |")
                lines.append(f"| 最大リード（瞬間） | {_sfmt(bw.get('max_lead'))} | {_sfmt(bl.get('max_lead'))} |")
                lines.append(f"| 最大劣勢（瞬間） | {_sfmt(bw.get('max_deficit'))} | {_sfmt(bl.get('max_deficit'))} |")
                cr_w = bw.get("comeback_rate", 0)
                cr_l = bl.get("comeback_rate", 0)
                lines.append(f"| 逆転勝ち率 | {cr_w*100:.0f}% | {cr_l*100:.0f}% |")
            else:
                # 片方のみ（全勝 or 全敗）: 単一グループを表示
                grp = bw or bl
                label = "勝ち試合" if bw else "負け試合"
                lines.append(f"| 指標 | {label} |")
                lines.append("|---|---|")
                lines.append(f"| 平均盤面スコア | {_sfmt(grp.get('avg_score'))} |")
                lines.append(f"| 最大リード（瞬間） | {_sfmt(grp.get('max_lead'))} |")
                lines.append(f"| 最大劣勢（瞬間） | {_sfmt(grp.get('max_deficit'))} |")
                cr = grp.get("comeback_rate", 0)
                lines.append(f"| 逆転勝ち率 | {cr*100:.0f}% |")
            lines.append("")

            if tp_win:
                lines.append("### 勝ち試合の主要ターニングポイント\n")
                lines.append(
                    "盤面スコアが最も大きく動いた局面のログです。"
                    "これらのアクションが試合の流れを決定づけました。\n"
                )
                for log_line in tp_win:
                    lines.append(f"```\n{log_line}\n```")
                lines.append("")

            if tp_loss:
                lines.append("### 負け試合の主要ターニングポイント\n")
                lines.append(
                    "負け試合でスコアが最も大きく動いた局面です。"
                    "これらの局面が崩壊点となっています。\n"
                )
                for log_line in tp_loss:
                    lines.append(f"```\n{log_line}\n```")
                lines.append("")

    # ── vs {opponent_name} 攻略のポイント ────────────────────────
    lines.append(f"## vs {opponent_name} 攻略のポイント\n")
    lines.append(
        "> 以下は「相手を固定した上での勝ち/負け比較」から読み取った行動の差です。"
        "同じ相手と戦ったログ内での差なので、相性ではなくプレイングに起因する傾向と見なせます。\n"
    )

    findings: list[str] = []

    # ゲーム長
    w_turns = wa.get("avg_turns", 0)
    l_turns = la.get("avg_turns", 0)
    if w_turns and l_turns:
        if w_turns < l_turns - 1.0:
            findings.append(
                f"**短期決戦で勝つ**: 勝ち試合の平均{w_turns:.1f}Tは負け試合({l_turns:.1f}T)より短い。"
                f"{opponent_name}戦は長引くほど不利になる傾向があり、早期決着を狙う意識が重要。"
            )
        elif w_turns > l_turns + 1.0:
            findings.append(
                f"**長期戦で逆転**: 勝ち試合の平均{w_turns:.1f}Tは負け試合({l_turns:.1f}T)より長い。"
                f"{opponent_name}の序盤の圧力を耐えて中盤以降に逆転する展開が勝ちパターン。"
            )

    # 初キャラ登場
    w_fp = wa.get("avg_first_play_turn", 0)
    l_fp = la.get("avg_first_play_turn", 0)
    if w_fp and l_fp and abs(w_fp - l_fp) > 1.0:
        if w_fp < l_fp:
            findings.append(
                f"**序盤展開が鍵**: 勝ち試合では平均T{w_fp:.1f}にキャラを登場させているが、"
                f"負け試合はT{l_fp:.1f}と遅い。{opponent_name}に対しては序盤の盤面形成が直接勝敗に影響する。"
            )
        else:
            findings.append(
                f"**焦らず手札を整える**: 勝ち試合の初キャラ登場T{w_fp:.1f}は、"
                f"負け試合(T{l_fp:.1f})より遅い。{opponent_name}相手では早出しより手札の質を優先する方が有効。"
            )

    # マリガン
    w_mull = wa.get("mulligan_rate", 0)
    l_mull = la.get("mulligan_rate", 0)
    if n_losses > 0 and l_mull > w_mull + 0.15:
        findings.append(
            f"**初手が勝敗を決める**: 負け試合のマリガン率({l_mull*100:.0f}%)が"
            f"勝ち試合({w_mull*100:.0f}%)より高い。{opponent_name}戦では初手の質が特に重要。"
            "積極的にマリガンして理想の初手を狙うべき。"
        )

    # 自分の攻撃回数
    w_atk = wa.get("avg_attacks", 0)
    l_atk = la.get("avg_attacks", 0)
    if w_atk and l_atk and abs(w_atk - l_atk) > 1.5:
        if w_atk > l_atk:
            findings.append(
                f"**アタック回数を増やす**: 勝ち試合では平均{w_atk:.1f}回攻撃しているのに対し、"
                f"負け試合は{l_atk:.1f}回。{opponent_name}戦ではアタックの機会を積極的に作ることが勝率に直結する。"
            )

    # 先制ライフダメージ
    w_hit = wa.get("avg_first_hit_given_turn", 0)
    l_hit = la.get("avg_first_hit_given_turn", 0)
    if w_hit and l_hit and w_hit < l_hit - 1.0:
        findings.append(
            f"**先にライフを削る**: 勝ち試合では平均T{w_hit:.1f}に最初のライフダメージを与えており、"
            f"負け試合(T{l_hit:.1f})より{l_hit - w_hit:.1f}ターン早い。"
            f"{opponent_name}戦では先手を取ることが重要なマッチアップ。"
        )

    # カウンター：正規化レートで判断（相性ではなく行動の差として読む）
    w_cnt_rate = wa.get("counter_per_opp_attack", 0)
    l_cnt_rate = la.get("counter_per_opp_attack", 0)
    w_cnt      = wa.get("avg_counter_uses", 0)
    l_cnt      = la.get("avg_counter_uses", 0)
    w_opp_atk  = wa.get("avg_opp_attacks", 0)
    l_opp_atk  = la.get("avg_opp_attacks", 0)

    if w_cnt_rate and l_cnt_rate:
        rate_diff = l_cnt_rate - w_cnt_rate
        if rate_diff > 0.15:
            # 同じ攻撃圧力でも勝ち試合はカウンターを切る頻度が低い
            findings.append(
                f"**カウンターは温存が吉**: {opponent_name}から受けた攻撃1回あたりのカウンター使用率を見ると、"
                f"勝ち試合は{w_cnt_rate:.2f}回に対して負け試合は{l_cnt_rate:.2f}回と高い。"
                "同じ攻撃圧力を受けても、勝ち試合ではカウンターを切り控えている。"
                "カウンターはライフが危機的になるまで温存する意識が有効。"
            )
        elif rate_diff < -0.15:
            findings.append(
                f"**積極的に守る**: {opponent_name}からの攻撃1回あたりのカウンター使用率は、"
                f"勝ち試合{w_cnt_rate:.2f}回 vs 負け試合{l_cnt_rate:.2f}回と、"
                "勝ち試合の方がしっかりカウンターを使っている。"
                f"{opponent_name}の攻撃を安易に受けてライフを失うと逆転が難しい。"
            )
    elif w_cnt and l_cnt and abs(w_cnt - l_cnt) > 0.5 and w_opp_atk and l_opp_atk:
        # 相手の攻撃回数も勝ち/負けで差がある場合は注記
        if abs(w_opp_atk - l_opp_atk) > 1.0:
            findings.append(
                f"**カウンター回数の差は攻撃圧力の差**: 勝ち試合と負け試合でカウンター使用回数が異なるが、"
                f"相手の攻撃回数も勝ち試合{w_opp_atk:.1f}回 vs 負け試合{l_opp_atk:.1f}回と違う。"
                "カウンター回数の生値ではなく攻撃圧力に対する比率で判断すること。"
            )

    # KO喪失
    w_ko_lost = wa.get("avg_ko_taken", 0)
    l_ko_lost = la.get("avg_ko_taken", 0)
    if l_ko_lost and (not w_ko_lost or l_ko_lost > w_ko_lost + 0.5):
        findings.append(
            f"**盤面を守りきる**: 負け試合では平均{l_ko_lost:.1f}体のキャラがKOされているが、"
            f"勝ち試合は{w_ko_lost:.1f}体にとどまる。"
            f"{opponent_name}の除去ラインを意識して、KOされにくいキャラ配置を心がけよう。"
        )

    # 攻撃精度
    w_lr = wa.get("attack_life_rate", 0)
    l_lr = la.get("attack_life_rate", 0)
    if w_lr and l_lr and w_lr > l_lr + 0.1:
        findings.append(
            f"**攻撃の通し方を工夫する**: 勝ち試合の攻撃→ライフ到達率({w_lr*100:.0f}%)が"
            f"負け試合({l_lr*100:.0f}%)より高い。{opponent_name}のカウンターをくぐる弱→強の攻撃順が重要。"
        )

    if not findings:
        findings.append(
            f"今回の{n_total}戦では明確な行動差を検出できませんでした。"
            "試合数を増やす（15戦以上推奨）とより精度が上がります。"
        )

    for f in findings:
        lines.append(f"- {f}")
    lines.append("")

    lines.append("---\n")
    lines.append(
        "> **免責事項**: 本データはAIシミュレーター（GreedyAI）のログ解析によるものです。"
        "各プレイングは最適戦略を目指したヒューリスティックに基づきますが、"
        "人間のプレイや最新環境とは異なる場合があります。参考情報としてご活用ください。"
    )

    return "\n".join(lines)
