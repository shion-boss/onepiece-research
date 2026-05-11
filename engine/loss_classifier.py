# -*- coding: utf-8 -*-
"""
敗因タグ分類
============

`db/match_replays/<pair>/*.json.gz` の replay を読み込み、 敗北側プレイヤーの
行動パターンから「敗因タグ」 を付与する。 タグは `scripts/learn_ai_params.py` で
「動かすべき AIParams フィールド」 の選定ヒントになる。

タグ判定はすべて純関数で、 副作用なし (= テストしやすい)。

タグ → 関連 AIParams 対応 (TAG_TO_PARAMS):
- `activate_main_overused`  → activate_main_min_payoff_global / activate_main_don_compensated_strict
- `finisher_starved`        → w_hand
- `life_burst_lost`         → w_life / defense_threshold_life_ge_4
- `counter_starved`         → defense_threshold_life_eq_2 / _eq_3
- `attack_dispersed`        → attack_gap_tolerance_default
- `defense_overreact`       → defense_threshold_life_le_1
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .log_analyzer import _LINE_RE, _ATK_RE, parse_game_log
from .replay_recorder import load_replay


@dataclass
class LossTags:
    tags: list[str] = field(default_factory=list)
    evidence: dict[str, dict] = field(default_factory=dict)  # tag -> metric dict
    loser_deck: Optional[str] = None
    winner_deck: Optional[str] = None
    turns: int = 0


TAG_TO_PARAMS: dict[str, list[str]] = {
    "activate_main_overused": [
        "activate_main_min_payoff_global",
        "activate_main_don_compensated_strict",
    ],
    "finisher_starved": ["w_hand"],
    "life_burst_lost": ["w_life", "defense_threshold_life_ge_4"],
    "counter_starved": [
        "defense_threshold_life_eq_2",
        "defense_threshold_life_eq_3",
    ],
    "attack_dispersed": ["attack_gap_tolerance_default"],
    "defense_overreact": ["defense_threshold_life_le_1"],
}


def _loser_idx_from_meta(meta: dict) -> Optional[int]:
    """state.players 上での敗北側 idx (0/1) を返す。 draw/不明なら None。"""
    winner = meta.get("winner_for_deck_a", -1)
    if winner not in (0, 1):
        return None
    first_player = int(meta.get("first_player", 0))
    # winner_for_deck_a==0: deck_a 勝ち。 deck_b が敗北。
    # players[0] は first_player 側 → first_player==0 なら P0=deck_a, P1=deck_b。
    if winner == 0:
        # 敗者 = deck_b
        return 1 if first_player == 0 else 0
    else:
        # 敗者 = deck_a
        return 0 if first_player == 0 else 1


def _is_activate_main_overused(
    log: list[str], loser_idx: int, turns: int, stats
) -> tuple[bool, dict]:
    """起動メインの DON 浪費パターン: 敗北側が pay_don > 0 起動メインを多用。

    判定: am_with_cost_count / turns > 0.4 かつ leader_attack 回数 < turns * 0.5
    (= リーダーが攻撃にあまり参加していないのに起動メインだけ焚いてる)。
    """
    am_cost_count = 0
    leader_atk_count = 0
    for line in log:
        m = _LINE_RE.match(line)
        if not m:
            continue
        player_n = int(m.group(2))
        body = m.group(3)
        if player_n != loser_idx:
            continue
        # サブログで「起動メインコスト: ドン-」 が含まれていれば pay_don > 0 発動
        if "起動メインコスト: ドン-" in body:
            am_cost_count += 1
        # リーダー攻撃: メインログで attacker 名前がリーダー (= ko_sources でリーダー名)
        am = _ATK_RE.match(body.strip())
        if am:
            attacker_name = am.group(1).strip()
            # リーダー識別: 「リーダー」「Leader」 を含むか、 ko_sources の attacker でリーダーが top
            # 簡易: リーダー攻撃かどうかは判定難。 stats.attacks_total を turns で割って指標化
            # → 別途 attacks_total / turns 比率で代用
            pass

    if turns < 4:
        return False, {}
    am_rate = am_cost_count / max(1, turns)
    atk_rate = stats.attacks_total / max(1, turns)
    triggered = am_rate >= 0.4 and atk_rate < 1.2
    return triggered, {
        "am_cost_count": am_cost_count,
        "turns": turns,
        "am_rate": round(am_rate, 3),
        "attacks_total": stats.attacks_total,
        "atk_rate": round(atk_rate, 3),
    }


def _is_finisher_starved(stats, key_card_ids: list[str], cards_played_names: dict) -> tuple[bool, dict]:
    """フィニッシャー temp が出ず長期戦で敗北。

    判定:
    - turns >= 12 (= 長期戦)
    - key_card_ids が cards_played に 1 件も無い (名前一致は厳密ではないので、card_id 一致比較不可)
    - 簡易代用: 最終ターン時点で stats.attacks_total < turns (= 攻撃機会 1/turn 未満)
    """
    if stats.turns < 12:
        return False, {}
    if stats.attacks_total >= stats.turns:
        return False, {}
    triggered = True
    return triggered, {
        "turns": stats.turns,
        "attacks_total": stats.attacks_total,
        "attack_per_turn": round(stats.attacks_total / max(1, stats.turns), 3),
    }


def _is_life_burst_lost(stats) -> tuple[bool, dict]:
    """序盤にライフを削られすぎて敗北。

    判定: first_hit_taken_turn ≤ 3 かつ turns ≤ 10。
    """
    if stats.first_hit_taken_turn is None:
        return False, {}
    triggered = stats.first_hit_taken_turn <= 3 and stats.turns <= 10
    return triggered, {
        "first_hit_taken_turn": stats.first_hit_taken_turn,
        "turns": stats.turns,
    }


def _is_counter_starved(stats, snapshots: list[dict], loser_idx: int) -> tuple[bool, dict]:
    """カウンターを切らされて手札が枯渇 → 防御できず敗北。

    判定: 敗北時の loser 手札枚数 ≤ 2 かつ 平均 counter 投入額 > 1500 (= 切らされ気味)。
    """
    if not snapshots:
        return False, {}
    last_snap = snapshots[-1]
    players = last_snap.get("players", [])
    if loser_idx >= len(players):
        return False, {}
    hand_left = len(players[loser_idx].get("hand", []))
    avg_counter = stats.defense_counter_amount / max(1, stats.defense_counter_uses)
    triggered = hand_left <= 2 and avg_counter > 1500
    return triggered, {
        "hand_left": hand_left,
        "avg_counter_amount": round(avg_counter, 1),
        "counter_uses": stats.defense_counter_uses,
    }


def _is_attack_dispersed(stats) -> tuple[bool, dict]:
    """攻撃の通り率が低い (= ブロッカー / KO で吸われ続けた)。

    判定: attacks_blocked / attacks_total > 0.5 かつ attacks_life_hit / max(1, attacks_total) < 0.3
    """
    if stats.attacks_total < 4:
        return False, {}
    block_rate = stats.attacks_blocked / stats.attacks_total
    life_rate = stats.attacks_life_hit / stats.attacks_total
    triggered = block_rate > 0.5 and life_rate < 0.3
    return triggered, {
        "block_rate": round(block_rate, 3),
        "life_rate": round(life_rate, 3),
        "attacks_total": stats.attacks_total,
    }


def _is_defense_overreact(stats) -> tuple[bool, dict]:
    """防御で counter を切りすぎて手札枯渇。

    判定: defense_counter_uses / max(1, opp_attacks_total) > 0.8 かつ
          attacks_total / max(1, turns) < 0.8 (= 守りすぎて攻撃機会逃した)
    """
    if stats.opp_attacks_total < 3:
        return False, {}
    cnt_rate = stats.defense_counter_uses / stats.opp_attacks_total
    atk_rate = stats.attacks_total / max(1, stats.turns)
    triggered = cnt_rate > 0.8 and atk_rate < 0.8
    return triggered, {
        "counter_per_opp_attack": round(cnt_rate, 3),
        "atk_per_turn": round(atk_rate, 3),
    }


def classify_loss(replay_id: int, db_path: Optional[Path] = None) -> LossTags:
    """1 試合分の replay (= row id) を読み込み、 敗北側視点でタグを判定。"""
    data = load_replay(replay_id, db_path=db_path)
    meta = data.get("meta", {})
    log = data.get("log", [])
    snapshots = data.get("snapshots", [])
    turns = int(meta.get("turns", 0))

    loser_idx = _loser_idx_from_meta(meta)
    if loser_idx is None:
        return LossTags(turns=turns)

    winner_state_idx = 1 - loser_idx
    stats = parse_game_log(log, winner=winner_state_idx, turns=turns, our_idx=loser_idx)
    # stats.won は False (= 敗北側視点)

    tags: list[str] = []
    evidence: dict[str, dict] = {}

    triggered, ev = _is_activate_main_overused(log, loser_idx, turns, stats)
    if triggered:
        tags.append("activate_main_overused")
        evidence["activate_main_overused"] = ev

    triggered, ev = _is_finisher_starved(stats, [], {})
    if triggered:
        tags.append("finisher_starved")
        evidence["finisher_starved"] = ev

    triggered, ev = _is_life_burst_lost(stats)
    if triggered:
        tags.append("life_burst_lost")
        evidence["life_burst_lost"] = ev

    triggered, ev = _is_counter_starved(stats, snapshots, loser_idx)
    if triggered:
        tags.append("counter_starved")
        evidence["counter_starved"] = ev

    triggered, ev = _is_attack_dispersed(stats)
    if triggered:
        tags.append("attack_dispersed")
        evidence["attack_dispersed"] = ev

    triggered, ev = _is_defense_overreact(stats)
    if triggered:
        tags.append("defense_overreact")
        evidence["defense_overreact"] = ev

    winner_deck = meta.get("deck_a") if meta.get("winner_for_deck_a") == 0 else meta.get("deck_b")
    loser_deck = meta.get("deck_b") if meta.get("winner_for_deck_a") == 0 else meta.get("deck_a")
    return LossTags(
        tags=tags,
        evidence=evidence,
        loser_deck=loser_deck,
        winner_deck=winner_deck,
        turns=turns,
    )


def aggregate_loss_tags(
    replay_ids: list[int],
    db_path: Optional[Path] = None,
) -> dict[str, dict]:
    """複数 replay (= row id 列) のタグを集計。

    返り値:
      {
        "tag_counts": {"activate_main_overused": 14, ...},
        "tag_rates": {"activate_main_overused": 0.46, ...},  # 全敗北数に対する出現率
        "total_losses": 30,
        "loser_decks": {"cardrush_1273": 30},  # 敗北側デッキの集計
        "evidence_samples": {"activate_main_overused": [{...}, ...]},  # 上位 3 件のメトリクス
      }
    """
    tag_counts: Counter = Counter()
    loser_counts: Counter = Counter()
    evidence_by_tag: dict[str, list[dict]] = defaultdict(list)
    total = 0
    for rid in replay_ids:
        try:
            lt = classify_loss(rid, db_path=db_path)
        except Exception:
            continue
        if lt.loser_deck is None:
            continue
        total += 1
        loser_counts[lt.loser_deck] += 1
        for t in lt.tags:
            tag_counts[t] += 1
            if len(evidence_by_tag[t]) < 3:
                evidence_by_tag[t].append(lt.evidence.get(t, {}))
    tag_rates = {t: round(c / max(1, total), 3) for t, c in tag_counts.items()}
    return {
        "tag_counts": dict(tag_counts),
        "tag_rates": tag_rates,
        "total_losses": total,
        "loser_decks": dict(loser_counts),
        "evidence_samples": dict(evidence_by_tag),
    }


def params_to_tune(tag_aggregate: dict, top_k: int = 3) -> list[str]:
    """敗因タグ集計から、 学習対象 AIParams フィールド名のリストを返す (重複除去)。

    上位 top_k タグの TAG_TO_PARAMS をマージ。
    """
    counts = tag_aggregate.get("tag_counts", {})
    sorted_tags = sorted(counts.items(), key=lambda x: -x[1])[:top_k]
    seen: list[str] = []
    for tag, _ in sorted_tags:
        for param in TAG_TO_PARAMS.get(tag, []):
            if param not in seen:
                seen.append(param)
    return seen
