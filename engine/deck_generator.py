# -*- coding: utf-8 -*-
"""デッキ自動生成 (= 2026-06-15、 ohtsuki「deck_combo_strength を使って」)。

要件:
  - **使いたいカードを 5 枚まで先に固定** できる (= build_with_core の core)。
  - **特定のデッキに勝てる** デッキを作る (= target mode、 候補を target と sim して勝率最大化)。
  - **環境デッキに対応** できる (= meta mode、 候補を meta pool sample と sim して平均勝率最大化)。
  - **deck_combo_strength を使う** (= 候補を「コンボの噛み合い」 で pre-rank し sim 予算を集中、
    かつ sim が同点なら combo の強い方を採る)。 → コンボ検出の品質改善が deck-gen に波及する
    ([[project_combo_finder_quality]] の共有コア原則)。

設計 (v1 = candidate-select):
  1. leader + 固定カード(≤5) を core に、 ランダムな合法カードを少量足した core を n_candidates 通り
     作り、 build_with_core で 50 枚に埋める (= 多様性は「足すカード」 で出す)。
  2. 各候補を deck_combo_strength で pre-rank (= 安い静的指標)。
  3. 上位 n_sim_eval を target / meta sample と run_matchup で sim → 勝率。
  4. 合成スコア (= 勝率 主、 combo_strength 従) で最良を返す。

⚠ v1 の探索は浅い (= 固定カード周辺の差し替えのみ)。 hill-climb / 大きな摂動は将来拡張。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .deck import CardRepository, DeckList, Category
from .deckbuilder import build_with_core, _base_id
from .combo_finder import deck_combo_strength, find_combos
from .harness import run_matchup


@dataclass
class CandidateDeck:
    deck: DeckList
    combo_strength: float
    win_rate: Optional[float]      # target/meta との sim 勝率 (= 未 sim は None)
    score: float
    core: list[str] = field(default_factory=list)       # build に使った core (= 固定+追加)
    extras: list[str] = field(default_factory=list)      # 多様性のために足したカード
    warnings: list[str] = field(default_factory=list)


def _legal_bases(repo: CardRepository, block_min: int) -> Optional[set[str]]:
    """block_min>0 なら、 スタンダード合法 (= 再録含む最大 block_icon >= block_min) な base_id 集合。"""
    if block_min <= 0:
        return None
    from .deck import _load_max_block_by_base_id
    mb = _load_max_block_by_base_id()
    out: set[str] = set()
    for cid, c in repo._by_id.items():
        bid = _base_id(cid)
        if mb.get(bid, c.block_icon) >= block_min:
            out.add(bid)
    return out


def _legal_fill_pool(
    repo: CardRepository, leader, exclude: set[str], legal_bases: Optional[set[str]] = None
) -> list[str]:
    """leader 色に完全に収まる main 用カード (= base_id) のプール。 legal_bases 指定で規制も絞る。"""
    leader_colors = set(leader.color)
    out: list[str] = []
    seen: set[str] = set()
    for cid, c in repo._by_id.items():
        bid = _base_id(cid)
        if bid in seen:
            continue
        seen.add(bid)
        if c.category not in (Category.CHARACTER, Category.EVENT, Category.STAGE):
            continue
        cols = set(c.color)
        if not cols or not cols.issubset(leader_colors):
            continue
        if c.cost <= 0:
            continue
        if bid in exclude:
            continue
        if legal_bases is not None and bid not in legal_bases:
            continue
        out.append(bid)
    return out


def _deck_signature(deck: DeckList) -> tuple:
    from collections import Counter
    return tuple(sorted(Counter(_base_id(c.card_id) for c in deck.main).items()))


def _combo_partner_pool(
    repo: CardRepository, seed_ids: list[str], leader, legal_bases: Optional[set[str]] = None
) -> list[str]:
    """seed カード (= 固定カード + リーダー) の **コンボ相棒** を、 leader 色 (と規制) に合う範囲で
    強い順に返す。 ⭐ これが deck-gen の核 = 共有コンボコア (find_combos) で「噛む相棒」 を
    引き込み、 build に combo を assemble させる (= deck_combo_strength が効くようになる)。"""
    leader_colors = set(leader.color)
    best: dict[str, float] = {}
    for sid in seed_ids:
        try:
            res = find_combos(repo, sid, per_group=10)
        except Exception:
            continue
        for g in res.groups:
            if g.key not in ("enabler", "payoff", "amplifier", "accelerant", "tribal"):
                continue
            for c in g.cards:
                bid = _base_id(c.card_id)
                cd = repo._by_id.get(bid)
                if cd is None or cd.category == Category.LEADER:
                    continue
                cols = set(cd.color)
                if not cols or not cols.issubset(leader_colors):
                    continue
                if legal_bases is not None and bid not in legal_bases:
                    continue
                best[bid] = max(best.get(bid, 0.0), c.score)
    return sorted(best, key=lambda b: -best[b])


def _deck_from_recipe(repo: CardRepository, leader, recipe: dict, name: str = "auto") -> DeckList:
    """{base_id: count} → DeckList (= main を展開)。 hill-climb の差し替えに使う。"""
    main = []
    for bid, n in recipe.items():
        c = repo._by_id.get(bid)
        if c is not None:
            main.extend([c] * n)
    return DeckList(name=name, leader=leader, main=main)


def _winrate(deck: DeckList, opponents: list[DeckList], n_games: int, overlay) -> float:
    """deck の opponents 平均勝率。"""
    wrs = []
    for i, opp in enumerate(opponents):
        rep = run_matchup(deck, opp, n_games=n_games, seed=42 + i, effects_overlay=overlay)
        wrs.append(rep.deck1_winrate)
    return sum(wrs) / len(wrs) if wrs else 0.0


def _hill_climb(
    repo, deck, opponents, fixed_bases, swap_pool, *,
    overlay, n_games, iters, rng,
):
    """非固定カードを 1 枚ずつ swap_pool のカードに差し替え、 sim 勝率が上がれば採用、 を反復。

    build_with_core の決定的 fill を超えて「勝てる 50 枚」 を局所探索する。 swap_pool は
    コンボ相棒 (= 共有コア) + 合法 tech の mix なので、 コンボ強化と対 target tech の両方を探る。
    ⚠ sim は確率的なので strict 改善のみ採用 + adequate n_games で noise を緩和 (= 完全最適でない)。"""
    from collections import Counter
    cur = Counter(_base_id(c.card_id) for c in deck.main)
    cur_wr = _winrate(deck, opponents, n_games, overlay)
    cur_cs = deck_combo_strength(deck.main, deck.leader)
    base_issues = len(deck.validate())  # 固定カード由来の既存問題は許容 (= 新規違反のみ弾く)
    pool = [b for b in swap_pool if b in repo._by_id]
    for _ in range(iters):
        removable = [b for b in cur if b not in fixed_bases and cur[b] > 0]
        if not removable or not pool:
            break
        rem = rng.choice(removable)
        add = rng.choice(pool)
        if add == rem:
            continue
        cand = Counter(cur)
        cand[rem] -= 1
        if cand[rem] <= 0:
            del cand[rem]
        if cand.get(add, 0) >= 4:
            continue  # 4 枚上限
        cand[add] = cand.get(add, 0) + 1
        if sum(cand.values()) != 50:
            continue
        cand_deck = _deck_from_recipe(repo, deck.leader, dict(cand))
        if len(cand_deck.validate()) > base_issues:
            continue  # swap が新規違反 (= 禁止ペア/規制) を増やすなら skip (base 由来は許容)
        w = _winrate(cand_deck, opponents, n_games, overlay)
        cs = deck_combo_strength(cand_deck.main, cand_deck.leader)
        # 辞書式: 勝率 主 (= 動いた時)、 同点なら combo_strength (= 常に signal がある reliable な
        # 勾配)。 単発 swap は n_games の量子化で勝率が動きにくいので、 combo を tiebreak にして
        # 「勝率を落とさず噛み合いを上げる」 方向に確実に進める (= deck_combo_strength を最適化に活用)。
        if w > cur_wr or (abs(w - cur_wr) < 1e-9 and cs > cur_cs):
            cur, cur_wr, cur_cs = cand, w, cs
    return _deck_from_recipe(repo, deck.leader, dict(cur)), round(cur_wr, 4)


def generate_deck(
    repo: CardRepository,
    leader_id: str,
    must_include: Optional[list[str]] = None,
    *,
    target_deck: Optional[DeckList] = None,
    meta_decks: Optional[list[DeckList]] = None,
    n_candidates: int = 10,
    n_sim_eval: int = 5,
    n_games: int = 16,
    hill_climb_iters: int = 0,
    block_min: int = 2,
    overlay: Optional[dict] = None,
    rng: Optional[random.Random] = None,
    name: str = "auto",
) -> list[CandidateDeck]:
    """leader + 固定カード から、 combo_strength と (target/meta との) sim 勝率でランクした
    候補デッキを返す (= 先頭が最良)。

    target_deck 指定時 = その 1 デッキとの勝率を最大化 (= 特定デッキに勝つ)。
    meta_decks 指定時 = それらとの平均勝率を最大化 (= 環境対応)。 両方 None なら combo_strength のみ。"""
    rng = rng or random.Random(0)
    must_include = list(dict.fromkeys(must_include or []))[:5]  # 重複除去・最大5
    leader = repo.get(leader_id)
    if leader.category != Category.LEADER:
        raise ValueError(f"{leader_id} はリーダーではない")

    legal_bases = _legal_bases(repo, block_min)  # スタンダード合法 (= block②+) に絞る
    fill_pool = _legal_fill_pool(repo, leader, set(must_include), legal_bases)
    # ⭐ 固定カード + リーダー のコンボ相棒を引き込む (= 共有コアで deck に combo を assemble)。
    partner_pool = _combo_partner_pool(repo, must_include + [leader_id], leader, legal_bases)
    partner_top = partner_pool[:24]

    # ① 多様な core を作る: 固定カード + コンボ相棒の sample (+ 少量のランダム合法)。
    #    先頭は「固定 + 上位相棒」 (= combo を最大限 assemble した base)。
    cores: list[list[str]] = [list(must_include) + partner_pool[:8]]
    for _ in range(max(0, n_candidates - 1)):
        extras: list[str] = []
        if partner_top:
            extras += rng.sample(partner_top, min(rng.randint(4, 8), len(partner_top)))
        if fill_pool:
            extras += rng.sample(fill_pool, min(rng.randint(1, 3), len(fill_pool)))
        cores.append(list(must_include) + list(dict.fromkeys(extras)))

    # ② build + combo_strength。 同一デッキは畳む。
    built: list[CandidateDeck] = []
    seen_sigs: set[tuple] = set()
    for core in cores:
        # 固定カードは 4 枚、 多様性の追加カードは 2 枚 (= 過剰コミットを避ける)。
        counts = {cid: 4 for cid in must_include}
        for cid in core:
            if cid not in counts:
                counts[cid] = 2
        deck, warns = build_with_core(
            leader_id, core, repo, core_counts=counts,
            rng=random.Random(rng.randrange(1 << 30)), name=name, block_min=block_min,
        )
        sig = _deck_signature(deck)
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        cs = deck_combo_strength(deck.main, deck.leader)
        built.append(CandidateDeck(
            deck=deck, combo_strength=cs, win_rate=None, score=0.0,
            core=list(core), extras=[c for c in core if c not in must_include], warnings=warns,
        ))

    # ③ combo_strength で pre-rank → 上位を sim
    built.sort(key=lambda c: -c.combo_strength)
    opponents: list[DeckList] = []
    if target_deck is not None:
        opponents = [target_deck]
    elif meta_decks:
        opponents = list(meta_decks)

    n_simmed = 0
    for cand in built:
        if opponents and n_simmed < n_sim_eval:
            cand.win_rate = round(_winrate(cand.deck, opponents, n_games, overlay), 4)
            n_simmed += 1

    # ④ 合成スコア: 勝率 主 (×100)、 combo_strength 従 (正規化 ×10)。 未 sim は中立 prior 0.5。
    cs_max = max((c.combo_strength for c in built), default=0.0) or 1.0

    def _rescore(c: CandidateDeck) -> None:
        wr = c.win_rate if c.win_rate is not None else 0.5
        c.score = round(wr * 100.0 + (c.combo_strength / cs_max) * 10.0, 2)

    for c in built:
        _rescore(c)

    if not opponents:
        built.sort(key=lambda c: -c.score)
        return built

    # opponents 指定時は「勝率の根拠がある (= sim 済)」 候補を優先。
    simmed = [c for c in built if c.win_rate is not None]
    simmed.sort(key=lambda c: -c.score)

    # ⑤ hill-climb: 最良候補を、 非固定カードを差し替えながら sim 勝率を直接最適化 (opt-in)。
    if hill_climb_iters > 0 and simmed:
        best = simmed[0]
        fixed_bases = {_base_id(cid) for cid in must_include}
        swap_pool = list(dict.fromkeys(partner_top + (fill_pool[:60] if fill_pool else [])))
        refined_deck, refined_wr = _hill_climb(
            repo, best.deck, opponents, fixed_bases, swap_pool,
            overlay=overlay, n_games=n_games, iters=hill_climb_iters, rng=rng,
        )
        if refined_wr >= (best.win_rate or 0.0):
            refined = CandidateDeck(
                deck=refined_deck,
                combo_strength=deck_combo_strength(refined_deck.main, refined_deck.leader),
                win_rate=refined_wr, score=0.0, core=best.core,
                extras=best.extras, warnings=best.warnings,
            )
            _rescore(refined)
            simmed = [refined] + simmed  # 磨いた版を先頭に
    return simmed
