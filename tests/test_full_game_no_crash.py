"""Regression: ランダム全ゲームが engine 例外なく完走することを担保する。

2026-06-03 発見: card-100% で AttackCharacter 分岐に on_self_battled hook (ST02-010)
を追加した際、 is_blocked (= AttackLeader 専用ローカル) を誤参照し、 AttackCharacter
アクション時に UnboundLocalError。 harness が握り潰して "engine error" で異常終了する
ため、 self-play 全 game の ~90% が壊れていた (= 勝敗ノイズ化、 AI 評価が無意味に)。

unit test は crafted state 単位で個別効果を見るため、 full random game で初めて踏む
この種の分岐スコープ bug を取り逃していた。 本テストは「全ゲーム完走」 の最低保証。
"""
from pathlib import Path
import random

import pytest

from engine.deck import CardRepository, DeckList
from engine.game import setup_game, play_until_main
from engine.effects import load_effect_overlay
from engine.ai import play_one_action, RandomAI

_ROOT = Path(__file__).resolve().parent.parent
_REPO = CardRepository.from_json(str(_ROOT / "db" / "cards.json"))
_OVERLAY = load_effect_overlay(str(_ROOT / "db" / "card_effects.json"))

# AttackCharacter / blocker / battle-end hook を踏みやすい代表デッキ
_DECKS = ["cardrush_1342", "cardrush_1456", "tcgportal_op11_luffy"]


@pytest.mark.parametrize("slug", _DECKS)
def test_random_full_games_no_crash(slug):
    """RandomAI 同型対戦を複数回回し、 例外ゼロ + 完走を確認する。"""
    deck = DeckList.from_json(str(_ROOT / "decks" / f"{slug}.json"), _REPO)
    for g in range(8):
        rng = random.Random(9000 + g)
        state = setup_game(
            deck, deck, rng=rng, first_player=0, effects_overlay=_OVERLAY
        )
        play_until_main(state)
        ais = [RandomAI(rng=rng), RandomAI(rng=rng)]
        n = 0
        # play_one_action が raise したら test 失敗 (= 旧 is_blocked bug の再発検出)
        while not state.game_over and n < 500:
            me = state.turn_player_idx
            play_one_action(state, ais[me], ais[1 - me], referee=None)
            n += 1
        assert state.game_over or n >= 500
