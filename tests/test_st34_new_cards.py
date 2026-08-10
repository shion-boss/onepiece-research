# -*- coding: utf-8 -*-
"""ST-34 (紫カタクリ スタートデッキ) ST34-001〜005 の効果 回帰テスト。

各カードについて:
  (1) 効果が 公式テキスト通り 盤面で 正しく発火する
  (2) 対象選択 / 任意コスト を持つカードは 人間 actor で pending_choice が 立つ + resolve できる
  (3) AI 文脈 (human_player_idx=None) で crash せず 解決する

新弾追加時に engine / overlay が退行した場合、このテストが常設ガードになる。
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    resolve_triggers,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_attack,
    trigger_on_ko,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent

# ビッグ・マム海賊団 特徴を持つリーダー / 持たないリーダー
BM_LEADER = "OP03-077"       # シャーロット・リンリン (四皇 / ビッグ・マム海賊団)
NON_BM_LEADER = "OP01-001"   # モンキー・D・ルフィ (超新星 / 麦わらの一味) = BM 特徴なし
BM_CHARA = "OP06-047"        # シャーロット・プリン (ビッグ・マム海賊団) = サーチ対象
FILLER = "OP01-013"          # サンジ (デッキ埋め用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, *, human=None):
    """2 人対戦の最小 state。 human=0/1 で人間文脈、 None で AI 文脈。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(NON_BM_LEADER), sickness=False))
    p0.deck = [repo.get(FILLER)] * 30
    p1.deck = [repo.get(FILLER)] * 30
    st = GameState(
        players=[p0, p1],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay,
    )
    st.turn_player_idx = 0
    st.human_player_idx = human
    return st


# ---------------------------------------------------------------------------
# ST34-001 シャーロット・カタクリ (5c 7000)
#   【自分のターン中】【ターン1回】自分の場のドンがドンデッキに戻された時、
#     自リーダーが《ビッグ・マム海賊団》なら ドンデッキから2枚までレストで追加。
#   【KO時】自分の手札からパワー8000以下のキャラ1枚までを登場させる。
# ---------------------------------------------------------------------------
def test_st34_001_don_returned_adds_rested_don_with_bm_leader():
    """ドン戻し時: BM リーダーなら レストドン +2 (add_rested_don)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    katakuri = InPlay.of(repo.get("ST34-001"), sickness=False)
    me.characters = [katakuri]
    # ドンを場に出しておく (= 戻す原資)。 don_active から pay_don でドンデッキに戻す。
    me.don_active = 5
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested

    # ドン!!-1 (場のドンをドンデッキに戻す) → on_self_don_returned_to_deck が発火
    execute_effect({"pay_don": 1}, st, me, opp, None)

    assert me.don_rested == rested_before + 2, (
        f"BM リーダー下で ドン戻し時 レストドン +2 のはず: {me.don_rested}")


def test_st34_001_don_returned_no_op_without_bm_leader():
    """ドン戻し時: 非 BM リーダーなら condition 不成立で レストドン 追加なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NON_BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    katakuri = InPlay.of(repo.get("ST34-001"), sickness=False)
    me.characters = [katakuri]
    me.don_active = 5
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested

    execute_effect({"pay_don": 1}, st, me, opp, None)

    assert me.don_rested == rested_before, (
        f"非 BM リーダーでは レストドン 追加されない: {me.don_rested}")


def test_st34_001_don_returned_once_per_turn():
    """【ターン1回】: 同一ターンで 2 回目のドン戻しでは 追加ドンが発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST34-001"), sickness=False)]
    me.don_active = 6
    me.don_remaining_in_deck = 4
    rested_before = me.don_rested

    execute_effect({"pay_don": 1}, st, me, opp, None)
    after_first = me.don_rested
    assert after_first == rested_before + 2, "1 回目は +2"

    execute_effect({"pay_don": 1}, st, me, opp, None)
    assert me.don_rested == after_first, "2 回目 (同ターン) は once_per_turn で追加なし"


def test_st34_001_on_ko_plays_low_power_chara_ai():
    """【KO時】: パワー8000以下のキャラを手札から登場 (AI 文脈で自動 pick)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈 (human=None)
    me, opp = st.players[0], st.players[1]
    # 手札に パワー5000 (=8000以下) の ST34-002 を用意
    playable = repo.get("ST34-002")
    me.hand = [playable]
    chara_before = len(me.characters)

    # ST34-001 が KO された (= 場から消えた後に on_ko 発火)
    trigger_on_ko(st, me, opp, repo.get("ST34-001"), overlay, by_opp_effect=True)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン

    assert len(me.characters) == chara_before + 1, (
        "KO時 手札から パワー8000以下キャラを登場させるはず")
    assert playable not in me.hand, "登場したキャラは手札から消える"


def test_st34_001_on_ko_human_gets_choice():
    """【KO時】登場: 人間 actor では pending_choice (play_from_hand_pick) が立ち resolve できる。

    候補が複数 (limit=1 < 候補数) のとき 人間に「どれを/登場するか」 を選ばせる modal が立つ。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay, human=0)  # 人間 文脈
    me, opp = st.players[0], st.players[1]
    # パワー8000以下のキャラを 2 枚 (= 候補 > limit) 用意し、 人間に選ばせる
    me.hand = [repo.get("ST34-002"), repo.get(BM_CHARA)]
    chara_before = len(me.characters)

    trigger_on_ko(st, me, opp, repo.get("ST34-001"), overlay, by_opp_effect=True)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン

    # 人間: どれを登場させるか (0枚見送りも含め) 選ばせる modal が立つ (= 勝手に登場しない)
    assert st.pending_choice is not None, "人間 KO時登場は modal で確認するはず"
    assert st.pending_choice.get("kind") == "play_from_hand_pick"
    assert len(me.characters) == chara_before, "modal 段階では まだ登場しない"

    # 1 枚 選んで登場 → 盤面が増える
    resolve_pending_choice(st, [0])
    assert st.pending_choice is None
    assert len(me.characters) == chara_before + 1, "resolve で登場する"


# ---------------------------------------------------------------------------
# ST34-002 シャーロット・クラッカー (4c 5000)
#   【登場時】BM リーダーなら ドンデッキから1枚までレストで追加。
#     その後、相手のコスト2以下のキャラ1枚までを KO。
# ---------------------------------------------------------------------------
def test_st34_002_on_play_adds_don_and_kos_cost2_ai():
    """登場時: レストドン +1 + 相手コスト2以下を KO (AI 文脈で自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested
    # 相手にコスト2キャラ (OP01-039 キラー cost2) を置く
    victim = InPlay.of(repo.get("OP01-039"), sickness=False)
    opp.characters = [victim]

    ip = InPlay.of(repo.get("ST34-002"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert me.don_rested == rested_before + 1, "BM リーダー下で レストドン +1"
    assert victim not in opp.characters, "コスト2以下キャラは KO されるはず"


def test_st34_002_on_play_no_don_without_bm_leader():
    """登場時 if 条件: 非 BM リーダーなら 効果ブロック全体が発火しない (ドン追加も KO もなし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NON_BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested
    victim = InPlay.of(repo.get("OP01-039"), sickness=False)
    opp.characters = [victim]

    ip = InPlay.of(repo.get("ST34-002"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert me.don_rested == rested_before, "非 BM リーダーでは ドン追加なし"
    assert victim in opp.characters, "非 BM リーダーでは KO も発火しない (if でブロック)"


def test_st34_002_on_play_respects_cost2_limit():
    """KO 対象は コスト2以下 限定: コスト3以上の相手キャラは KO できない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 5
    big = InPlay.of(repo.get("OP06-047"), sickness=False)  # cost4 プリン
    opp.characters = [big]

    ip = InPlay.of(repo.get("ST34-002"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert big in opp.characters, "コスト4キャラは コスト2以下制限で KO されない"


def test_st34_002_on_play_ko_human_gets_target_choice():
    """KO 対象選択: 人間 actor では target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay, human=0)  # 人間 文脈
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 5
    v1 = InPlay.of(repo.get("OP01-039"), sickness=False)  # cost2
    opp.characters = [v1]

    ip = InPlay.of(repo.get("ST34-002"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    # レストドン追加は先に済むが、 KO は人間 target_pick で halt するはず
    assert st.pending_choice is not None, "KO 対象は 人間に選ばせる modal が立つ"
    assert st.pending_choice.get("kind") == "target_pick"
    assert st.pending_choice.get("primitive_kind") == "ko"
    assert v1 in opp.characters, "modal 段階では まだ KO されない"

    resolve_pending_choice(st, [0])
    assert st.pending_choice is None
    assert v1 not in opp.characters, "resolve で KO される"


# ---------------------------------------------------------------------------
# ST34-003 シャーロット・ブリュレ (1c 2000)
#   【登場時】デッキ上3枚を見て《ビッグ・マム海賊団》1枚までを公開し手札に加える。
#     残りを好きな順番でデッキの下に置く。
# ---------------------------------------------------------------------------
def test_st34_003_on_play_search_bm_to_hand_ai():
    """登場時: 上3枚から BM 特徴カードを手札に加える (AI 文脈で自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈
    me, opp = st.players[0], st.players[1]
    # デッキ上3枚のうち1枚を BM 特徴カードにする
    me.deck = [repo.get(BM_CHARA), repo.get(FILLER), repo.get(FILLER)] + [repo.get(FILLER)] * 20
    hand_before = len(me.hand)

    ip = InPlay.of(repo.get("ST34-003"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert len(me.hand) == hand_before + 1, "BM 特徴カード1枚を手札に加えるはず"
    assert any(c.card_id == BM_CHARA for c in me.hand), "手札に加わったのは BM 特徴カード"


def test_st34_003_on_play_search_no_bm_in_top3():
    """上3枚に BM 特徴カードが無ければ 手札は増えない (残りをデッキ下へ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈
    me, opp = st.players[0], st.players[1]
    # FILLER (サンジ = 麦わらの一味) は BM 特徴を持たない
    me.deck = [repo.get(FILLER)] * 23
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    ip = InPlay.of(repo.get("ST34-003"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert len(me.hand) == hand_before, "該当なしなら手札は増えない"
    assert len(me.deck) == deck_before, "残り3枚はデッキ下に戻るのでデッキ枚数は不変"


def test_st34_003_on_play_search_human_gets_choice():
    """登場時サーチ: 人間 actor では search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay, human=0)  # 人間 文脈
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(BM_CHARA), repo.get(FILLER), repo.get(FILLER)] + [repo.get(FILLER)] * 20
    hand_before = len(me.hand)

    ip = InPlay.of(repo.get("ST34-003"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert st.pending_choice is not None, "人間サーチは modal で公開・選択するはず"
    assert st.pending_choice.get("kind") == "search_top_n"
    assert len(me.hand) == hand_before, "modal 段階では まだ手札に加わらない"

    # 公開3枚のうち BM 特徴カード (idx 0) を選ぶ → 手札に加わる
    resolve_pending_choice(st, [0])
    assert len(me.hand) == hand_before + 1, "resolve で手札に加わる"
    assert any(c.card_id == BM_CHARA for c in me.hand)

    # 「その後、残りを好きな順番でデッキの下に置く」 = 残り2枚の並べ替え modal が連鎖する。
    # 人間はここでも順序を選べる (search_top_n_bottom_reorder)。
    if st.pending_choice is not None:
        assert st.pending_choice.get("kind") == "search_top_n_bottom_reorder"
        resolve_pending_choice(st, [0, 1])
    assert st.pending_choice is None, "並べ替え resolve 後は 選択が全て解消される"


# ---------------------------------------------------------------------------
# ST34-004 シャーロット・リンリン (10c 12000)
#   【登場時】ドン-4, 手札1枚を捨てることができる:
#     デッキ上1枚までをライフの上に加える。
#     その後、相手のキャラ1枚までを このターン中 元々のパワー0にする。
# ---------------------------------------------------------------------------
def test_st34_004_on_play_optional_cost_life_and_power0_ai():
    """登場時: ドン-4 + 手札1捨て → ライフ+1 & 相手キャラ 元々パワー0 (AI 文脈で自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈
    me, opp = st.players[0], st.players[1]
    me.don_active = 8              # ドン-4 の原資
    me.hand = [repo.get(FILLER)]   # 捨てる手札
    me.deck = [repo.get(FILLER)] * 10
    life_before = len(me.life)
    target = InPlay.of(repo.get("OP11-015"), sickness=False)  # 印刷 6000
    opp.characters = [target]

    ip = InPlay.of(repo.get("ST34-004"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert len(me.life) == life_before + 1, "デッキ上1枚をライフに加えるはず (put_top_to_life)"
    assert target.power == 0, (
        f"相手キャラは このターン中 元々のパワー0 になるはず: {target.power}")


def test_st34_004_on_play_optional_cost_human_confirm():
    """登場時 任意コスト: 人間 actor では optional_cost_confirm modal が立つ (払う/払わない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay, human=0)  # 人間 文脈
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    me.hand = [repo.get(FILLER)]
    me.deck = [repo.get(FILLER)] * 10
    life_before = len(me.life)
    opp.characters = [InPlay.of(repo.get("OP11-015"), sickness=False)]

    ip = InPlay.of(repo.get("ST34-004"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert st.pending_choice is not None, "任意コストは 人間に払うか確認する modal が立つ"
    assert st.pending_choice.get("kind") == "optional_cost_confirm"
    assert len(me.life) == life_before, "modal 段階では まだライフに加えない"


def test_st34_004_on_play_optional_cost_human_decline():
    """任意コスト 見送り: 人間が [] を resolve すると コスト未払い・効果不発。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay, human=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    me.hand = [repo.get(FILLER)]
    me.deck = [repo.get(FILLER)] * 10
    life_before = len(me.life)
    hand_before = len(me.hand)
    don_before = me.don_active

    ip = InPlay.of(repo.get("ST34-004"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)
    assert st.pending_choice is not None

    resolve_pending_choice(st, [])  # 見送り
    assert st.pending_choice is None
    assert len(me.life) == life_before, "見送りなら ライフに加えない"
    assert len(me.hand) == hand_before, "見送りなら 手札は捨てない"
    assert me.don_active == don_before, "見送りなら ドンは払わない"


# ---------------------------------------------------------------------------
# ST34-005 タマゴ男爵＆ペコムズ (3c 4000)
#   【アタック時】ドン-1: 相手の元々のパワー2000以下のキャラ1枚までを KO。
# ---------------------------------------------------------------------------
def test_st34_005_on_attack_kos_low_power_ai():
    """アタック時: ドン-1 で 相手 元々パワー2000以下を KO (AI 文脈で自動支払・発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # ドン-1 の原資
    victim = InPlay.of(repo.get("OP01-039"), sickness=False)  # 印刷 2000
    survivor = InPlay.of(repo.get("OP11-015"), sickness=False)  # 印刷 6000
    opp.characters = [victim, survivor]

    attacker = InPlay.of(repo.get("ST34-005"), sickness=False)
    me.characters = [attacker]
    trigger_on_attack(st, me, opp, attacker, overlay)

    assert victim not in opp.characters, "元々パワー2000以下は KO されるはず"
    assert survivor in opp.characters, "元々パワー6000は KO されない"


def test_st34_005_on_attack_uses_truly_original_power():
    """KO 判定は 元々のパワー (印刷値) 基準: バフ後の現在値では判定しない (公式 4-9)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay)  # AI 文脈
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    # 印刷 2000 だが バフで現在 5000 → 元々2000以下判定で KO されるべき
    pumped = InPlay.of(repo.get("OP01-039"), sickness=False)
    pumped.turn_buff = 3000
    assert pumped.power == 5000
    opp.characters = [pumped]

    attacker = InPlay.of(repo.get("ST34-005"), sickness=False)
    me.characters = [attacker]
    trigger_on_attack(st, me, opp, attacker, overlay)

    assert pumped not in opp.characters, (
        "元々パワー2000 (現在5000) は truly_original_power_le=2000 で KO される")


def test_st34_005_on_attack_human_confirms_cost():
    """アタック時 コスト持ち: 人間 actor では on_attack_optional modal が立つ (使う/使わない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BM_LEADER, overlay, human=0)  # 人間 文脈
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    victim = InPlay.of(repo.get("OP01-039"), sickness=False)
    opp.characters = [victim]

    attacker = InPlay.of(repo.get("ST34-005"), sickness=False)
    me.characters = [attacker]
    trigger_on_attack(st, me, opp, attacker, overlay)

    # 人間: コスト持ちアタック時効果は「使うか」を確認する modal が立ち、 即 KO しない
    assert st.pending_choice is not None, "コスト持ちアタック時効果は 人間に確認する modal が立つ"
    assert victim in opp.characters, "modal 段階では まだ KO しない"
