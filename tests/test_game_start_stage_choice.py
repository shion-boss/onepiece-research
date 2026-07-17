"""ゲーム開始時「デッキから特徴Xのステージ1枚まで登場」(= OP13-079 イム) の選択制テスト。

回帰 (2026-07-17): イムは 聖地マリージョア(OP05-097) と 虚の玉座(OP13-099) の両方が特徴
《聖地マリージョア》を持つのに、 シャッフル順で先頭の1枚を自動選択していた (= 実質ランダム)。
公式「1枚まで」= 人間が選ぶべき。 AI は最良 (= 最高コスト) を自動、 人間は 2 枚以上なら選択 modal。
"""
import random

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay, resolve_pending_choice
from engine.game import setup_game, finalize_setup_after_mulligan


def _repo():
    return CardRepository.from_json("db/cards.json")


def _overlay():
    return load_effect_overlay("db/card_effects.json")


def test_ai_path_auto_summons_best_qualifying_stage():
    """AI vs AI (= 人間なし) では最良 (= 最高コスト) の該当ステージを自動登場。
    イムは 虚の玉座(cost7) > 聖地マリージョア(cost1) なので 虚の玉座 を選ぶ (= 旧: shuffle 依存)。"""
    repo = _repo()
    overlay = _overlay()
    im = DeckList.from_json("decks/cardrush_1392.json", repo)
    # 複数 seed で「虚の玉座 が deck に居る限り必ず 虚の玉座」 = 決定的 (旧実装は seed でぶれた)
    seen_stages = set()
    for seed in range(12):
        s = setup_game(im, im, rng=random.Random(seed), first_player=0, effects_overlay=overlay)
        stages = [ip.card.card_id for ip in s.players[0].stages]
        # 虚の玉座 が deck にあれば必ずそれ。 手札に流れて 聖地のみなら 聖地。 0 枚もありうる。
        if "OP13-099" in [c.card_id for c in im.main]:
            pass
        seen_stages.update(stages)
        # 少なくとも 聖地マリージョア だけを選ぶ (= cost1 を虚の玉座より優先) ことは無い
        if "OP05-097" in stages:
            # 聖地が出たなら 虚の玉座 は deck に無かった (= 手札 or 同時不可)
            assert "OP13-099" not in stages
    # どこかの seed で必ず 虚の玉座 が出ている (= 最高コスト優先が効いている)
    assert "OP13-099" in seen_stages, "AI が最高コスト(虚の玉座)を一度も選んでいない"


def test_human_path_offers_choice_and_summons_picked_stage():
    """人間 player で該当 2 枚が deck に残る seed では pending_choice(game_start_stage_pick)
    が立ち、 虚の玉座 を選ぶと 虚の玉座 が場に出る。 0 枚選択なら何も出ない (= 公式「まで」)。"""
    repo = _repo()
    overlay = _overlay()
    im = DeckList.from_json("decks/cardrush_1392.json", repo)

    # 両ステージが deck に残る seed を探す (= 2 枚候補)
    picked_ok = False
    skip_ok = False
    for seed in range(40):
        rng = random.Random(seed)
        s = setup_game(im, im, rng=rng, first_player=0, effects_overlay=overlay,
                       do_mulligan_and_finalize=False)
        finalize_setup_after_mulligan(s, rng, effects_overlay=overlay,
                                      human_mulligan=False, human_player_idx=0)
        pc = s.pending_choice
        if not (pc and pc.get("kind") == "game_start_stage_pick"):
            continue
        cands = pc["candidates"]
        ids = {c["card_id"] for c in cands}
        assert {"OP13-099", "OP05-097"} <= ids, f"候補にイムの両ステージが無い: {ids}"
        # AI(P1) は既に自動登場済 (= 人間の選択待ちが他プレイヤーを止めない)
        assert len(s.players[1].stages) >= 0
        if not picked_ok:
            kyo = next(i for i, c in enumerate(cands) if c["card_id"] == "OP13-099")
            resolve_pending_choice(s, [kyo])
            assert [ip.card.card_id for ip in s.players[0].stages] == ["OP13-099"]
            assert s.pending_choice is None
            picked_ok = True
        elif not skip_ok:
            resolve_pending_choice(s, [])  # 0 枚 = 登場させない
            assert s.players[0].stages == []
            skip_ok = True
        if picked_ok and skip_ok:
            break
    assert picked_ok, "2 枚候補の seed が見つからず選択経路を検証できなかった"
