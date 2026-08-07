# -*- coding: utf-8 -*-
"""EB02 弾 効果 回帰テスト バックフィル (自動生成 wave 006):
EB02-013 / EB02-015 / EB02-016 / EB02-017 / EB02-018 / EB02-019 /
EB02-020 / EB02-021 / EB02-022 / EB02-024 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _on_play(overlay, cid):
    """cid の on_play 効果 dict を返す。"""
    return next(e for e in overlay.get(cid).effects if e.get("when") == "on_play")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_eb02_wave6_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB02-013", "EB02-015", "EB02-016", "EB02-017", "EB02-018",
           "EB02-019", "EB02-020", "EB02-021", "EB02-022", "EB02-024"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB02-013 キャロット: 【登場時】場のドン3枚以上で デッキ上7枚から「ゾウ」1枚を手札 →
#                       手札から「ゾウ」(ステージ) を登場
# --------------------------------------------------------------------------- #
def test_eb02_013_carrot_on_play_search_and_play_zou_ai():
    """AI: ドン3枚以上 → デッキ上の「ゾウ」を手札に加え、 ステージとして登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # 場のドン3枚 (= self_don_ge 3 成立)
    zou_stage = repo.get("OP08-039")  # STAGE「ゾウ」
    assert zou_stage.name == "ゾウ" and zou_stage.category.value == "STAGE"
    me.deck = [zou_stage] + [repo.get("OP01-013")] * 20

    carrot = InPlay.of(repo.get("EB02-013"), sickness=True)
    me.characters.append(carrot)
    trigger_on_play(st, me, opp, carrot, overlay)

    assert any(s.card.card_id == "OP08-039" for s in me.stages), \
        "デッキ上の「ゾウ」を手札経由でステージ登場できていない"


def test_eb02_013_carrot_on_play_no_don_gate():
    """ドンが3枚未満 (条件不成立) なら 何も起きない (デッキ/ステージ不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2  # 3 枚未満
    zou_stage = repo.get("OP08-039")
    me.deck = [zou_stage] + [repo.get("OP01-013")] * 20
    deck_before = len(me.deck)

    carrot = InPlay.of(repo.get("EB02-013"), sickness=True)
    me.characters.append(carrot)
    trigger_on_play(st, me, opp, carrot, overlay)

    assert len(me.stages) == 0, "ドン不足で条件不成立なのにステージが登場している"
    assert len(me.deck) == deck_before, "ドン不足なのにデッキが操作されている"


def test_eb02_013_carrot_search_human_modal():
    """人間: search_top_n の primitive を直接発火 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    zou_stage = repo.get("OP08-039")
    me.deck = [zou_stage] + [repo.get("OP01-013")] * 10
    me.hand = []

    search_prim = _on_play(overlay, "EB02-013")["do"][0]
    assert "search_top_n" in search_prim
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("EB02-013"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ゾウ) を選択
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == "OP08-039" for c in me.hand), \
        "人間が選んだ「ゾウ」が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-015 ジュエリー・ボニー: 【登場時】相手レストキャラ1枚を次リフレッシュで
#            非アクティブ + このターン終了時 自ドン1枚アクティブを予約
# --------------------------------------------------------------------------- #
def test_eb02_015_bonney_on_play_stay_rested_and_schedule_ai():
    """AI: 相手のレストキャラに stay_rested_next_refresh、 ターン終了時 untap_don を予約。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ
    victim.rested = True
    opp.characters = [victim]

    bonney = InPlay.of(repo.get("EB02-015"), sickness=True)
    me.characters.append(bonney)
    trigger_on_play(st, me, opp, bonney, overlay)

    assert victim.stay_rested_next_refresh is True, \
        "相手のレストキャラが次リフレッシュ非アクティブになっていない"
    scheduled = getattr(me, "scheduled_at_self_turn_end", [])
    assert len(scheduled) >= 1, "ターン終了時 (自ドンアクティブ) の予約が積まれていない"


def test_eb02_015_bonney_on_play_active_chara_not_targeted():
    """相手キャラがアクティブ (非レスト) なら 対象外 → stay_rested は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    active = InPlay.of(repo.get("OP01-016"), sickness=False)
    active.rested = False
    opp.characters = [active]

    bonney = InPlay.of(repo.get("EB02-015"), sickness=True)
    me.characters.append(bonney)
    trigger_on_play(st, me, opp, bonney, overlay)

    assert active.stay_rested_next_refresh is False, \
        "アクティブなキャラは対象外なのに stay_rested が付いている"


def test_eb02_015_bonney_stay_rested_human_modal():
    """人間 + 相手レストキャラ 2 枚 → stay_rested の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    stay_prim = _on_play(overlay, "EB02-015")["do"][0]
    assert "stay_rested_next_refresh" in stay_prim
    execute_effect(stay_prim, st, me, opp,
                   InPlay.of(repo.get("EB02-015"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数レストで target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (レスト2枚) が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.stay_rested_next_refresh is True, "人間が選んだレストキャラに stay_rested が付かない"
    assert a.stay_rested_next_refresh is False, "選ばなかったキャラには付かないべき"


# --------------------------------------------------------------------------- #
#  EB02-016 チョッパーマン: 【登場時】手札からコスト3以下の《動物》キャラ1枚を登場
# --------------------------------------------------------------------------- #
def test_eb02_016_choppaman_on_play_play_animal_ai():
    """AI: 手札のコスト3以下《動物》キャラ (リュウ爺) を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    animal = repo.get("EB02-029")  # リュウ爺 動物 cost3 (効果なし)
    assert "動物" in (animal.features or "") and animal.cost <= 3
    me.hand = [animal]

    choppa = InPlay.of(repo.get("EB02-016"), sickness=True)
    me.characters.append(choppa)
    trigger_on_play(st, me, opp, choppa, overlay)

    assert any(c.card.card_id == "EB02-029" for c in me.characters), \
        "手札の《動物》キャラが登場していない"
    assert animal not in me.hand, "登場したキャラは手札から抜けるべき"


def test_eb02_016_choppaman_on_play_no_animal():
    """手札に該当《動物》キャラが無ければ 不発 (キャラ枚数 = チョッパーマンのみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 麦わら (動物でない)

    choppa = InPlay.of(repo.get("EB02-016"), sickness=True)
    me.characters.append(choppa)
    trigger_on_play(st, me, opp, choppa, overlay)

    assert not any(c.card.card_id == "OP01-013" for c in me.characters), \
        "《動物》でないキャラが登場してはいけない"


def test_eb02_016_choppaman_human_play_pick():
    """人間 + 手札にコスト3以下《動物》 2 枚 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB02-029"), repo.get("EB01-047")]  # リュウ爺 / ラブーン (共に動物)

    play_prim = _on_play(overlay, "EB02-016")["do"][0]
    assert "play_from_hand" in play_prim
    execute_effect(play_prim, st, me, opp,
                   InPlay.of(repo.get("EB02-016"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in ("EB02-029", "EB01-047") for c in me.characters), \
        "人間が選んだ《動物》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB02-017 ナミ: 【登場時】デッキ上5枚から「ナミ」以外の《麦わらの一味》1枚を手札
# --------------------------------------------------------------------------- #
def test_eb02_017_nami_on_play_search_strawhat_ai():
    """AI: デッキ上5枚から「ナミ」以外の《麦わらの一味》(ゾロ) を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    zoro = repo.get("OP01-025")  # ゾロ 麦わらの一味 (名前はナミでない)
    assert "麦わらの一味" in (zoro.features or "") and zoro.name != "ナミ"
    me.deck = [zoro] + [repo.get("OP01-013")] * 10
    me.hand = []

    nami = InPlay.of(repo.get("EB02-017"), sickness=True)
    me.characters.append(nami)
    trigger_on_play(st, me, opp, nami, overlay)

    assert any(c.card_id == "OP01-025" for c in me.hand), \
        "デッキ上の《麦わらの一味》が手札に加わっていない"


def test_eb02_017_nami_search_human_modal():
    """人間 + デッキ上5枚に《麦わらの一味》 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    zoro = repo.get("OP01-025")
    me.deck = [zoro, repo.get("OP01-013"), repo.get("OP01-024")] + [repo.get("OP01-013")] * 8
    me.hand = []

    search_prim = _on_play(overlay, "EB02-017")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("EB02-017"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == "OP01-025" for c in me.hand), \
        "人間が選んだ《麦わらの一味》が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-018 バギー: 【登場時】他の「バギー」がいない場合 自リーダーに【ダブルアタック】
# --------------------------------------------------------------------------- #
def test_eb02_018_buggy_on_play_grant_double_attack_ai():
    """AI: 他の「バギー」がいなければ 自リーダーに【ダブルアタック】(このターン中)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]

    buggy = InPlay.of(repo.get("EB02-018"), sickness=True)
    me.characters.append(buggy)
    trigger_on_play(st, me, opp, buggy, overlay)

    assert "ダブルアタック" in me.leader.granted_keywords, \
        "他バギー不在で 自リーダーに ダブルアタックが付与されていない"


def test_eb02_018_buggy_on_play_blocked_by_other_buggy():
    """自場に 別の「バギー」が既にいる場合 条件不成立 → ダブルアタックは付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    other_buggy = InPlay.of(repo.get("EB02-018"), sickness=False)  # 既存の別バギー
    me.characters = [other_buggy]

    buggy = InPlay.of(repo.get("EB02-018"), sickness=True)
    me.characters.append(buggy)
    trigger_on_play(st, me, opp, buggy, overlay)

    assert "ダブルアタック" not in me.leader.granted_keywords, \
        "他バギーがいるのに ダブルアタックが付与されている (条件不成立のはず)"


# --------------------------------------------------------------------------- #
#  EB02-019 ロロノア・ゾロ: 【登場時】自リーダーが《麦わらの一味》なら
#                          相手のコスト4以下キャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_eb02_019_zoro_on_play_rest_opp_ai():
    """AI: 麦わら leader → 相手のコスト4以下キャラ (ナミ cost1) をレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ leader (麦わらの一味)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    victim.rested = False
    opp.characters = [victim]

    zoro = InPlay.of(repo.get("EB02-019"), sickness=True)
    me.characters.append(zoro)
    trigger_on_play(st, me, opp, zoro, overlay)

    assert victim.rested is True, "麦わら leader で 相手コスト4以下キャラがレストされていない"


def test_eb02_019_zoro_on_play_non_strawhat_leader():
    """リーダーが《麦わらの一味》でなければ 条件不成立 → 相手はレストされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)  # 麦わらでない leader
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    victim.rested = False
    opp.characters = [victim]

    zoro = InPlay.of(repo.get("EB02-019"), sickness=True)
    me.characters.append(zoro)
    trigger_on_play(st, me, opp, zoro, overlay)

    assert victim.rested is False, "非麦わら leader で相手がレストされてはいけない"


def test_eb02_019_zoro_rest_human_modal():
    """人間 + 相手コスト4以下 2 枚 → レストの target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    rest_prim = _on_play(overlay, "EB02-019")["do"][0]
    assert "rest" in rest_prim
    execute_effect(rest_prim, st, me, opp,
                   InPlay.of(repo.get("EB02-019"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (相手2枚) が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  EB02-020 ウィーアー！ (EVENT): 【メイン】デッキ上4枚からコスト4以上1枚を手札
# --------------------------------------------------------------------------- #
def test_eb02_020_weare_main_search_cost_ge4_ai():
    """AI: デッキ上4枚から コスト4以上のカード (ゾロ cost4) を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    big = repo.get("EB02-019")  # ゾロ cost4
    assert big.cost >= 4
    me.deck = [big] + [repo.get("OP01-016")] * 10  # 残りは cost1
    me.hand = []

    main_eff = next(e for e in overlay.get("EB02-020").effects if e.get("when") == "main")
    for prim in main_eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card_id == "EB02-019" for c in me.hand), \
        "デッキ上のコスト4以上カードが手札に加わっていない"


def test_eb02_020_weare_main_search_human_modal():
    """人間 + デッキ上4枚に コスト4以上 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB02-019"), repo.get("OP01-016")] + [repo.get("OP01-016")] * 8
    me.hand = []

    main_eff = next(e for e in overlay.get("EB02-020").effects if e.get("when") == "main")
    execute_effect(main_eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == "EB02-019" for c in me.hand), \
        "人間が選んだコスト4以上カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-021 ゴムゴムの巨人の銃 (EVENT): 【メイン】自《麦わらの一味》1枚 +6000 →
#                                       その後 選んだキャラは次リフレッシュ非アクティブ
# --------------------------------------------------------------------------- #
def test_eb02_021_giant_pistol_main_pump_and_stay_rested_ai():
    """AI: 自《麦わらの一味》キャラを +6000 し、 その後 次リフレッシュ非アクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ 麦わら power5000
    me.characters = [zoro]
    power_before = zoro.power

    main_eff = next(e for e in overlay.get("EB02-021").effects if e.get("when") == "main")
    for prim in main_eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert zoro.power == power_before + 6000, \
        f"《麦わらの一味》キャラに +6000 が反映されていない: {zoro.power} (before {power_before})"
    assert zoro.stay_rested_next_refresh is True, \
        "その後 選んだキャラが次リフレッシュ非アクティブになっていない"


def test_eb02_021_giant_pistol_main_pump_human_modal():
    """人間 + 自《麦わらの一味》 2 枚 → +6000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ 麦わら
    b = InPlay.of(repo.get("OP01-024"), sickness=False)  # ルフィ 麦わら
    me.characters = [a, b]

    main_eff = next(e for e in overlay.get("EB02-021").effects if e.get("when") == "main")
    execute_effect(main_eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (麦わら2枚) が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before + 6000, "人間が選んだキャラに +6000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB02-022 ウソップ: 【登場時】自パワー5000以上のキャラ2枚以下なら
#            手札のパワー6000以下・元々効果なしキャラ1枚を登場
# --------------------------------------------------------------------------- #
def test_eb02_022_usopp_on_play_play_vanilla_ai():
    """AI: 条件成立 (5000以上0枚) → 手札の 元々効果なし・パワー6000以下キャラを登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    vanilla = repo.get("EB02-029")  # リュウ爺 power5000 効果なし
    me.hand = [vanilla]

    usopp = InPlay.of(repo.get("EB02-022"), sickness=True)
    me.characters.append(usopp)
    trigger_on_play(st, me, opp, usopp, overlay)

    assert any(c.card.card_id == "EB02-029" for c in me.characters), \
        "手札の 元々効果なしキャラが登場していない"


def test_eb02_022_usopp_on_play_blocked_when_three_strong():
    """パワー5000以上のキャラが 3 枚 (= 2枚超) なら 条件不成立 → 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    # power5000 の キャラを 3 体 場に (= 条件 count>2 で 不成立)
    strong = [InPlay.of(repo.get("OP01-025"), sickness=False) for _ in range(3)]
    me.characters = list(strong)
    vanilla = repo.get("EB02-029")
    me.hand = [vanilla]

    usopp = InPlay.of(repo.get("EB02-022"), sickness=True)
    me.characters.append(usopp)
    trigger_on_play(st, me, opp, usopp, overlay)

    assert not any(c.card.card_id == "EB02-029" for c in me.characters), \
        "パワー5000以上が3枚 (条件不成立) なのに登場している"
    assert vanilla in me.hand, "条件不成立なら手札のキャラは残るべき"


# --------------------------------------------------------------------------- #
#  EB02-024 そげキング: 【登場時】2ドロー → 手札2枚をデッキ下 →
#            コスト1以下キャラ1枚を持ち主の手札に戻す
# --------------------------------------------------------------------------- #
def test_eb02_024_sogeking_on_play_draw_deckbottom_bounce_ai():
    """AI: 2ドロー → 手札2枚をデッキ下 → コスト1以下キャラを手札に戻す。

    「コスト1以下のキャラ1枚まで…**持ち主の**手札に戻す」 は 修飾なし = 両陣営 (docs
    official_rulings、 cardqa_st_03 系)。 AI は 相手のキャラを優先し 自分のキャラは巻き込まない。
    ⚠ 是正前は self 限定 (one_self_chara_filtered) だった。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]  # 手札2枚
    me.deck = [repo.get("OP01-016")] * 10
    small = InPlay.of(repo.get("OP01-016"), sickness=False)  # 自分 ナミ cost1
    me.characters = [small]
    foe = InPlay.of(repo.get("OP01-016"), sickness=False)  # 相手 cost1
    opp.characters = [foe]

    hand_before = len(me.hand)
    sogeking = InPlay.of(repo.get("EB02-024"), sickness=True)
    me.characters.append(sogeking)
    trigger_on_play(st, me, opp, sogeking, overlay)

    # +2 draw, -2 deck bottom, bounce は相手キャラ (相手の手札へ) = 自分の手札は net 0
    assert len(me.hand) == hand_before, \
        f"2ドロー-2デッキ下 で 自分の手札は net 0 のはず: {len(me.hand)} (before {hand_before})"
    assert foe not in opp.characters, "AI が 相手のコスト1以下キャラを手札に戻していない"
    assert small in me.characters, "AI が 相手より 自分のキャラを戻してしまっている"
    assert any(c.card_id == "OP01-016" for c in opp.hand), \
        "戻した相手キャラが 相手の手札にない"


def test_eb02_024_sogeking_bounce_human_modal():
    """人間 + 自コスト1以下キャラ 2 枚 → 手札に戻す target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    b = InPlay.of(repo.get("EB04-002"), sickness=False)  # ボニー cost1
    me.characters = [a, b]

    bounce_prim = _on_play(overlay, "EB02-024")["do"][2]
    assert "return_to_hand" in bounce_prim
    execute_effect(bounce_prim, st, me, opp,
                   InPlay.of(repo.get("EB02-024"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (コスト1以下2枚) が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b not in me.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in me.characters, "選ばなかったキャラは場に残るべき"
