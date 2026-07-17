"""ゲーム開始時「デッキから特徴Xのステージ1枚まで登場」(= OP13-079 イム) の選択制 + タイミング。

回帰 (2026-07-17): イムは 聖地マリージョア(OP05-097) と 虚の玉座(OP13-099) の両方が特徴
《聖地マリージョア》を持つのに、 シャッフル順で先頭の1枚を自動選択していた (= 実質ランダム)。
公式「1枚まで」= 人間が選ぶべき。 AI は最良 (= 最高コスト) を自動、 人間は 2 枚以上なら選択 modal。

回帰 (2026-07-18): 公式 FAQ (cardqa_op_13) = ゲーム開始時のステージ登場は「先攻後攻決定後、
最初の手札を準備する前」= ライフ配置・手札ドロー・マリガンより **前**。 旧実装はマリガン後
(finalize_setup_after_mulligan) で登場させていて公式順と逆 + ステージが手札に流れて登場不可に
なりうる bug だった。 setup_game 内で draw 前に処理するよう修正。
"""
import random

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay, resolve_pending_choice
from engine.game import setup_game, finish_pre_mulligan_setup


def _repo():
    return CardRepository.from_json("db/cards.json")


def _overlay():
    return load_effect_overlay("db/card_effects.json")


def test_ai_path_summons_best_stage_before_draw():
    """AI vs AI (= 人間なし) では、 game_start が draw 前なので デッキ満杯 = 最良 (= 最高コスト)
    の 虚の玉座 が **必ず** 登場する (旧実装は draw 後で ~19% 手札に流れて出ないことがあった)。"""
    repo = _repo()
    overlay = _overlay()
    im = DeckList.from_json("decks/cardrush_1392.json", repo)
    for seed in range(20):
        s = setup_game(im, im, rng=random.Random(seed), first_player=0, effects_overlay=overlay)
        for pidx in (0, 1):
            p = s.players[pidx]
            stages = [ip.card.card_id for ip in p.stages]
            assert stages == ["OP13-099"], f"seed{seed} P{pidx}: 虚の玉座が登場していない: {stages}"
            # draw 前登場なので、 登場ステージ自身は手札にダブらない
            hand_ids = [c.card_id for c in p.hand]
            assert "OP13-099" not in hand_ids, f"seed{seed} P{pidx}: 登場ステージが手札にも"
            assert len(p.hand) == 5


def test_human_stage_choice_is_before_mulligan_and_draw():
    """人間 (human_player_idx) では setup_game が **draw 前** に game_start_stage_pick を立てる。
    選択待ちの時点で手札は空 (= まだ引いていない)。 選択 → 登場 → finish_pre_mulligan_setup で
    ライフ+手札を準備。 = 公式 FAQ「ステージ登場 → 最初の手札を準備 → マリガン」の順。"""
    repo = _repo()
    overlay = _overlay()
    im = DeckList.from_json("decks/cardrush_1392.json", repo)

    s = setup_game(im, im, rng=random.Random(0), first_player=0, effects_overlay=overlay,
                   do_mulligan_and_finalize=False, human_player_idx=0)
    pc = s.pending_choice
    assert pc is not None and pc.get("kind") == "game_start_stage_pick", (
        "draw 前に人間のステージ選択 pending が立つべき"
    )
    # 両ステージが deck 満杯から候補になる (= draw 前なので必ず 2 枚)
    ids = {c["card_id"] for c in pc["candidates"]}
    assert {"OP13-099", "OP05-097"} <= ids, f"候補にイムの両ステージが無い: {ids}"
    me = s.players[0]
    assert len(me.hand) == 0, "選択待ちは手札ドロー前 (公式 FAQ)"
    assert me.life == [], "選択待ちはライフ配置前"
    assert me.stages == [], "選択前はステージ未登場"

    # 虚の玉座を選択 → 登場
    kyo = next(i for i, c in enumerate(pc["candidates"]) if c["card_id"] == "OP13-099")
    resolve_pending_choice(s, [kyo])
    assert [ip.card.card_id for ip in me.stages] == ["OP13-099"]

    # ステージ登場後にライフ+手札を準備 (= マリガン前状態)
    finish_pre_mulligan_setup(s)
    assert len(me.hand) == 5, "ステージ選択後に手札5枚を引く"
    assert len(me.life) == me.leader.card.life
    # 登場した虚の玉座は手札にダブらない
    assert "OP13-099" not in [c.card_id for c in me.hand]


def test_human_stage_skip_summons_best():
    """空 picks (= 汎用 skip / 未対応フロント) は最良 (= 虚の玉座) を自動登場 = 無 stage 回避。"""
    repo = _repo()
    overlay = _overlay()
    im = DeckList.from_json("decks/cardrush_1392.json", repo)
    s = setup_game(im, im, rng=random.Random(1), first_player=0, effects_overlay=overlay,
                   do_mulligan_and_finalize=False, human_player_idx=0)
    assert s.pending_choice.get("kind") == "game_start_stage_pick"
    resolve_pending_choice(s, [])  # skip
    assert [ip.card.card_id for ip in s.players[0].stages] == ["OP13-099"]
