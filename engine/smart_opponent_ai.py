# -*- coding: utf-8 -*-
"""SmartOpponentAI: deck別に「検証済みで強い方」を使う実用ラッパ (= 2026-06-04)。

ExploitBeam は大半のデッキで greedy より強いが、 一部 (bonney 36% / 1399 47% / calgara 47%)
で beam-base が噛み合わず greedy 以下。 そこで db/deploy_results.json の検証 winrate を見て、
**閾値以上のデッキは ExploitBeam、 未満は GreedyAI** に自動フォールバック → 全デッキで
「手強い相手 ≥ greedy」 を保証する。

deck_slug は deck_analysis or state.deck_slugs から解決、 初回 choose_action で inner AI を確定。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RESULTS_PATH = _REPO_ROOT / "db" / "deploy_results.json"


def _load_results() -> dict:
    try:
        return json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


class SmartOpponentAI:
    """検証 winrate ≥ threshold なら ExploitBeam、 さもなくば GreedyAI。"""

    name = "SmartOpponent"

    def __init__(self, rng=None, deck_analysis: Optional[dict] = None, *,
                 threshold: float = 0.55, results: Optional[dict] = None, **kwargs):
        import random
        self.rng = rng or random.Random()
        self.deck_analysis = deck_analysis
        self._threshold = threshold
        self._results = results if results is not None else _load_results()
        self._inner = None  # lazy (= deck_slug が要る)

    def _resolve_slug(self, state: Any) -> Optional[str]:
        if isinstance(self.deck_analysis, dict) and self.deck_analysis.get("deck_slug"):
            return self.deck_analysis["deck_slug"]
        slugs = getattr(state, "deck_slugs", None)
        me = state.turn_player_idx
        if slugs and me < len(slugs) and slugs[me]:
            return slugs[me]
        return None

    def _ensure_inner(self, state: Any):
        if self._inner is not None:
            return self._inner
        slug = self._resolve_slug(state)
        wr = self._results.get(slug, -1.0) if slug else -1.0
        if wr >= self._threshold:
            from .exploit_beam_ai import ExploitBeamAI
            self._inner = ExploitBeamAI(rng=self.rng, deck_analysis=self.deck_analysis)
            self._chosen = ("ExploitBeam", slug, wr)
        else:
            from .ai import GreedyAI
            self._inner = GreedyAI(rng=self.rng, deck_analysis=self.deck_analysis)
            self._chosen = ("Greedy(fallback)", slug, wr)
        return self._inner

    def choose_action(self, state: Any):
        return self._ensure_inner(state).choose_action(state)

    def choose_defense(self, state: Any, attacker: Any, target: Any,
                       is_leader_attack: bool, defender: Any):
        return self._ensure_inner(state).choose_defense(
            state, attacker, target, is_leader_attack, defender)
