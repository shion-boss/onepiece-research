# -*- coding: utf-8 -*-
"""
デッキ改善提案エンジン
======================

過去の対戦ログ (= match_replays.sqlite + match_history.jsonl) を解析し、
- カード別出現試合数 / 勝率 / プレイ頻度 を集計
- 弱いカード → 同 role 高 effectiveness 札への swap 提案
- トップドローされにくいカード → 枚数 -1 提案
- よく引かれて活躍するカード → 枚数 +1 提案

公開 API:
- compute_card_stats(deck_slug, deck, repo) -> list[CardStat]
- generate_proposals(stats, deck, target_archetype_hint, ...) -> list[Proposal]
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import card_role
from .core import CardDef
from .deck import CardRepository, DeckList, _base_id


_REPLAY_DB_PATH = Path(__file__).resolve().parent.parent / "db" / "match_replays.sqlite"
_HISTORY_PATH = Path(__file__).resolve().parent.parent / "db" / "match_history.jsonl"


# ============================================================================ #
# データ型
# ============================================================================ #

@dataclass
class CardStat:
    card_id: str
    base_id: str
    name: str
    n_in_deck: int                   # デッキでの採用枚数
    n_appearances: int               # 出現試合数 (= プレイされた試合数)
    n_total_plays: int               # 全試合での総プレイ回数
    n_matches: int                   # 全マッチ数 (デッキ視点)
    winrate_when_played: float       # このカードを 1 回でもプレイした試合の勝率
    deck_winrate_baseline: float     # デッキ全体の勝率


@dataclass
class CardChange:
    card_id: str
    delta: int                       # +N or -N
    name: str


@dataclass
class Proposal:
    proposal_id: str                 # client が apply 時に指定
    proposal_type: str               # "swap" | "count_decrease" | "count_increase"
    changes: list[CardChange] = field(default_factory=list)  # net delta = 0
    reason: str = ""
    impact_estimate: int = 50        # 0..100


# ============================================================================ #
# log 解析
# ============================================================================ #

def _decode_payload(raw: bytes) -> dict:
    """sqlite payload (gzip 圧縮 or plain) → dict。"""
    try:
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    except (gzip.BadGzipFile, OSError):
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


def _extract_played_cards(log_lines: list[str], player_idx: int) -> Counter[str]:
    """log から指定プレイヤーがプレイしたカード名 (= カウント) を抽出。

    log フォーマット例:
      "T1 P0: play: シュラ (cost 1 pay 1)"
      "T1 P0: event: 雷龍 (cost 0 pay 0)"
      "T1 P0: stage: ホーリー (cost 3)"
    """
    pattern_prefix = f"P{player_idx}:"
    counter: Counter[str] = Counter()
    for line in log_lines:
        if pattern_prefix not in line:
            continue
        # play / event / stage のいずれか
        for keyword in ("play:", "event:", "stage:"):
            idx = line.find(keyword)
            if idx == -1:
                continue
            after = line[idx + len(keyword):].strip()
            # "<name> (cost N..." → name 抽出
            paren = after.find("(")
            if paren > 0:
                name = after[:paren].strip()
                counter[name] += 1
            break
    return counter


def _name_to_card_id(deck: DeckList) -> dict[str, str]:
    """デッキ内カードの name → card_id マップ。 同名は最初の card_id を採用。"""
    out: dict[str, str] = {}
    seen: set[str] = set()
    for c in deck.main:
        if c.card_id in seen:
            continue
        seen.add(c.card_id)
        if c.name and c.name not in out:
            out[c.name] = c.card_id
    return out


# ============================================================================ #
# 主要 API: compute_card_stats
# ============================================================================ #

def _load_history_for_deck(deck_slug: str) -> list[dict]:
    """match_history.jsonl から該当デッキを含むエントリを抽出。"""
    if not _HISTORY_PATH.exists():
        return []
    out = []
    with open(_HISTORY_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("deck_a_id") == deck_slug or e.get("deck_b_id") == deck_slug:
                out.append(e)
    return out


def _load_replays_for_deck(deck_slug: str) -> list[dict]:
    """match_replays.sqlite から該当デッキを含むリプレイを抽出。

    Returns: [{deck_a, deck_b, winner_for_deck_a, log_lines, target_player_idx}, ...]
    target_player_idx: deck_slug が deck_a なら 0、 deck_b なら 1
    """
    if not _REPLAY_DB_PATH.exists():
        return []
    con = sqlite3.connect(str(_REPLAY_DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT deck_a, deck_b, winner_for_deck_a, payload FROM replays "
            "WHERE deck_a = ? OR deck_b = ?",
            (deck_slug, deck_slug),
        )
        out = []
        for row in cur.fetchall():
            payload = row["payload"]
            if not payload:
                continue
            try:
                data = _decode_payload(payload)
            except Exception:
                continue
            log_lines = data.get("log", [])
            if not log_lines:
                # snapshots[*].log を結合する fallback
                snaps = data.get("snapshots", [])
                log_lines = [s.get("log", "") for s in snaps if s.get("log")]
            target_player_idx = 0 if row["deck_a"] == deck_slug else 1
            out.append({
                "deck_a": row["deck_a"],
                "deck_b": row["deck_b"],
                "winner_for_deck_a": row["winner_for_deck_a"],
                "log_lines": log_lines,
                "target_player_idx": target_player_idx,
            })
        return out
    finally:
        con.close()


def compute_card_stats(
    deck_slug: str, deck: DeckList
) -> tuple[list[CardStat], int, float]:
    """デッキの過去対戦から card 別統計を計算。

    Returns:
        (card_stats: list[CardStat], n_matches: int, deck_winrate: float)
    """
    replays = _load_replays_for_deck(deck_slug)
    n_matches = len(replays)
    if n_matches == 0:
        return [], 0, 0.0

    # デッキ視点の勝敗
    n_wins = 0
    for r in replays:
        winner_for_a = r["winner_for_deck_a"]
        target_idx = r["target_player_idx"]
        # winner_for_deck_a: 1 = deck_a 勝ち、 0 = deck_b 勝ち、 -1 = 引分
        if winner_for_a == 1 and target_idx == 0:
            n_wins += 1
        elif winner_for_a == 0 and target_idx == 1:
            n_wins += 1
    deck_winrate = n_wins / n_matches

    # name → card_id マップ
    name_to_cid = _name_to_card_id(deck)
    # main の枚数集計 (= n_in_deck)
    counts_in_deck: Counter[str] = Counter()
    for c in deck.main:
        counts_in_deck[c.card_id] += 1

    # カード別: 出現試合数 + 勝ち試合数 + 総プレイ回数
    card_appearances: dict[str, int] = defaultdict(int)
    card_appearances_in_wins: dict[str, int] = defaultdict(int)
    card_total_plays: dict[str, int] = defaultdict(int)

    for r in replays:
        played_names = _extract_played_cards(r["log_lines"], r["target_player_idx"])
        # win 判定 (target 視点)
        target_won = (
            (r["winner_for_deck_a"] == 1 and r["target_player_idx"] == 0)
            or (r["winner_for_deck_a"] == 0 and r["target_player_idx"] == 1)
        )
        for name, n_plays in played_names.items():
            cid = name_to_cid.get(name)
            if cid is None:
                continue
            card_appearances[cid] += 1
            card_total_plays[cid] += n_plays
            if target_won:
                card_appearances_in_wins[cid] += 1

    # 各カードの統計を生成 (deck の main にあるカードのみ)
    out: list[CardStat] = []
    seen_cids: set[str] = set()
    for c in deck.main:
        if c.card_id in seen_cids:
            continue
        seen_cids.add(c.card_id)
        n_app = card_appearances.get(c.card_id, 0)
        n_wins_app = card_appearances_in_wins.get(c.card_id, 0)
        wr_played = (n_wins_app / n_app) if n_app > 0 else 0.0
        out.append(CardStat(
            card_id=c.card_id,
            base_id=_base_id(c.card_id),
            name=c.name,
            n_in_deck=counts_in_deck.get(c.card_id, 0),
            n_appearances=n_app,
            n_total_plays=card_total_plays.get(c.card_id, 0),
            n_matches=n_matches,
            winrate_when_played=wr_played,
            deck_winrate_baseline=deck_winrate,
        ))
    return out, n_matches, deck_winrate


# ============================================================================ #
# 提案生成
# ============================================================================ #

# 閾値定数
_MIN_APPEARANCES_FOR_SWAP = 3        # swap 判定には少なくとも 3 試合の出現が必要
_SWAP_WINRATE_DELTA = -0.10          # baseline - 10pt 以下なら swap 候補
_DECREASE_PLAY_RATIO_THRESHOLD = 0.4 # 試合あたり平均 0.4 回未満 = decrement 候補
_INCREASE_WINRATE_DELTA = 0.10       # baseline + 10pt 以上なら increment 候補


def generate_proposals(
    stats: list[CardStat],
    deck: DeckList,
    repo: CardRepository,
    target_archetype: str = "ミッドレンジ",
    *,
    role_db: Optional[dict] = None,
    eff_db: Optional[dict] = None,
) -> list[Proposal]:
    """card_stats から swap / count 調整提案を生成。

    Args:
        stats: compute_card_stats の戻り値
        deck: 対象デッキ (= 色制約 / 既存採用カード参照用)
        repo: CardRepository
        target_archetype: 想定する相手アーキタイプ (= 集計対象の主な敵)
        role_db / eff_db: card_role の DB
    """
    if role_db is None:
        role_db = card_role.load_card_role_db()
    if eff_db is None:
        eff_db = card_role.load_effectiveness_db()

    if not stats:
        return []

    baseline = stats[0].deck_winrate_baseline
    leader_colors = list(deck.leader.color)
    used_base_ids: set[str] = {_base_id(c.card_id) for c in deck.main}

    out: list[Proposal] = []

    for stat in stats:
        # === Swap 提案: 弱いカードを同 role 高 effectiveness と差し替え ===
        is_swap_candidate = (
            stat.n_appearances >= _MIN_APPEARANCES_FOR_SWAP
            and (stat.winrate_when_played - baseline) <= _SWAP_WINRATE_DELTA
        )
        if is_swap_candidate:
            # 同 role の代替候補
            try:
                card = repo.get(stat.card_id)
                role_info = role_db.get(stat.card_id, {})
                primary_role = role_info.get("primary_role", "synergy")
                # 同 role + 同色 + コスト近似 で best_cards_against
                cost_lo = max(1, card.cost - 1)
                cost_hi = card.cost + 1
                alts = card_role.best_cards_against(
                    target_archetype,
                    target_role=primary_role,
                    color_filter=leader_colors,
                    cost_range=(cost_lo, cost_hi),
                    top_k=10,
                    role_db=role_db,
                    eff_db=eff_db,
                )
                # 既に採用していないもの + leader でないもの + 同名 (= variant) でないもの
                alt = next(
                    (a for a in alts if _base_id(a.card_id) not in used_base_ids
                     and a.card_id != deck.leader.card_id
                     and a.name != stat.name),
                    None,
                )
                if alt:
                    delta_pct = int((stat.winrate_when_played - baseline) * 100)
                    proposal_id = f"swap_{stat.card_id}_{alt.card_id}"
                    out.append(Proposal(
                        proposal_id=proposal_id,
                        proposal_type="swap",
                        changes=[
                            CardChange(card_id=stat.card_id, delta=-stat.n_in_deck,
                                       name=stat.name),
                            CardChange(card_id=alt.card_id, delta=stat.n_in_deck,
                                       name=alt.name),
                        ],
                        reason=(
                            f"{stat.name} はプレイ試合の勝率 {stat.winrate_when_played:.0%} "
                            f"(基準 {baseline:.0%}, {delta_pct:+d}pt)。 "
                            f"同 role の {alt.name} (effectiveness {alt.effectiveness}) に差替え提案。"
                        ),
                        impact_estimate=min(100, max(10, abs(delta_pct) * 5 + 30)),
                    ))
            except KeyError:
                pass

        # === Count 増加提案: よく勝つカードを +1 ===
        if (
            stat.n_appearances >= _MIN_APPEARANCES_FOR_SWAP
            and (stat.winrate_when_played - baseline) >= _INCREASE_WINRATE_DELTA
            and stat.n_in_deck < 4
        ):
            # 既存の弱いカードを 1 枚減らす相手を探す (= 同 deck から swap 元探索)
            decrement_target = _find_decrement_target(stats, baseline, exclude_cid=stat.card_id)
            if decrement_target is None:
                continue
            delta_pct = int((stat.winrate_when_played - baseline) * 100)
            proposal_id = f"increase_{stat.card_id}"
            out.append(Proposal(
                proposal_id=proposal_id,
                proposal_type="count_increase",
                changes=[
                    CardChange(card_id=stat.card_id, delta=+1, name=stat.name),
                    CardChange(card_id=decrement_target.card_id, delta=-1,
                               name=decrement_target.name),
                ],
                reason=(
                    f"{stat.name} はプレイ試合の勝率 {stat.winrate_when_played:.0%} "
                    f"(基準 {baseline:.0%}, {delta_pct:+d}pt)。 "
                    f"枚数を {stat.n_in_deck} → {stat.n_in_deck + 1} に増やし、 "
                    f"代わりに {decrement_target.name} (出現 {decrement_target.n_appearances}/{stat.n_matches}) を 1 枚減らす提案。"
                ),
                impact_estimate=min(100, max(10, delta_pct * 4 + 20)),
            ))

        # === Count 減少提案: 試合あたりプレイ頻度低 = ドローされにくい ===
        avg_plays = stat.n_total_plays / stat.n_matches if stat.n_matches > 0 else 0
        if (
            avg_plays < _DECREASE_PLAY_RATIO_THRESHOLD
            and stat.n_in_deck >= 2
            and stat.n_matches >= 5
        ):
            # 増やす相手 (= よく使われて勝つカード) を探す
            increment_target = _find_increment_target(stats, baseline, exclude_cid=stat.card_id)
            if increment_target is None:
                continue
            proposal_id = f"decrease_{stat.card_id}"
            out.append(Proposal(
                proposal_id=proposal_id,
                proposal_type="count_decrease",
                changes=[
                    CardChange(card_id=stat.card_id, delta=-1, name=stat.name),
                    CardChange(card_id=increment_target.card_id, delta=+1,
                               name=increment_target.name),
                ],
                reason=(
                    f"{stat.name} は試合あたり平均 {avg_plays:.1f} 回しかプレイされない "
                    f"(出現 {stat.n_appearances}/{stat.n_matches})。 "
                    f"枚数を {stat.n_in_deck} → {stat.n_in_deck - 1} に減らし、 "
                    f"代わりに {increment_target.name} (勝率 {increment_target.winrate_when_played:.0%}) を 1 枚増やす提案。"
                ),
                impact_estimate=min(100, max(5, int((1.0 - avg_plays) * 60))),
            ))

    # impact_estimate 降順、 上位 10 件
    out.sort(key=lambda p: -p.impact_estimate)
    return out[:10]


def _find_decrement_target(
    stats: list[CardStat], baseline: float, exclude_cid: str
) -> Optional[CardStat]:
    """count_increase の対として「減らす対象」 を探す: 弱い + 出現多 + 採用 ≥ 2 枚。"""
    candidates = [
        s for s in stats
        if s.card_id != exclude_cid
        and s.n_in_deck >= 2
        and s.n_appearances >= 3
        and (s.winrate_when_played - baseline) <= -0.05
    ]
    candidates.sort(key=lambda s: s.winrate_when_played)
    return candidates[0] if candidates else None


def _find_increment_target(
    stats: list[CardStat], baseline: float, exclude_cid: str
) -> Optional[CardStat]:
    """count_decrease の対として「増やす対象」 を探す: 強い + 採用 < 4 枚。"""
    candidates = [
        s for s in stats
        if s.card_id != exclude_cid
        and s.n_in_deck < 4
        and s.n_appearances >= 3
        and (s.winrate_when_played - baseline) >= 0.05
    ]
    candidates.sort(key=lambda s: -s.winrate_when_played)
    return candidates[0] if candidates else None
