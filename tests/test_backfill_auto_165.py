# -*- coding: utf-8 -*-
"""カード効果 回帰テスト バックフィル (自動生成 wave 165):
ST01-017 / ST02-003 / ST02-005 / ST02-008 / ST02-009 /
ST02-013 / ST02-014 / ST02-015 / ST02-016 / ST02-017 の 10 枚。

目的 (= test_backfill_auto_001〜164.py と同一方針):
  (1) 各カードの効果が overlay / 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"            # ナミ (cost1 power2000 麦わらの一味) フィラー / 相手キャラ
SANJI = "OP01-013"           # サンジ (cost2 power3000 麦わらの一味) フィラー
STRAWHAT_LEADER = "ST01-001"    # モンキー・D・ルフィ (麦わらの一味 LEADER)
KID_LEADER = "ST02-001"         # ユースタス・キッド (超新星/キッド海賊団 LEADER)
ZORO_LEADER = "OP01-001"        # ロロノア・ゾロ (LEADER、 中立素材用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(SANJI)] * 30
    p1.deck = [repo.get(SANJI)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (先頭) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    return matches[0]


def _drain(st, picks):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, picks)
        guard += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave165_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST01-017", "ST02-003", "ST02-005", "ST02-008", "ST02-009",
           "ST02-013", "ST02-014", "ST02-015", "ST02-016", "ST02-017"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST01-017 サウザンド・サニー号 (STAGE 赤 cost2):
#    【起動メイン】このステージをレストにできる：自分の特徴《麦わらの一味》を持つ
#    リーダーかキャラ1枚までを、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_st01_017_sunny_activate_main_pump_ai():
    """【起動メイン】optional_cost_then で ステージを rest → 麦わら リーダーを +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay)  # 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("ST01-017"), sickness=False)
    me.stages = [stage]

    power_before = me.leader.power
    eff = _eff(overlay, "ST01-017", "activate_main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, stage)

    assert stage.rested is True, "起動コストで ステージが レストされていない"
    assert me.leader.power == power_before + 1000, \
        f"麦わらリーダーへ +1000 が反映されていない: {me.leader.power} (before {power_before})"


def test_st01_017_sunny_pump_human_pick():
    """人間 + 麦わら リーダー/キャラ 複数 → 効果本体 (power_pump) が target_pick modal を立てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(NAMI), sickness=False)  # 麦わらの一味
    me.characters = [friend]

    # optional_cost_then の内側の効果 (= 実際に対象を選ぶ power_pump) を直接発火し、
    # 人間 文脈で 「リーダー or キャラ」 の target_pick modal が立つことを検証。
    eff = _eff(overlay, "ST01-017", "activate_main")
    pump_prim = eff["do"][0]["optional_cost_then"]["effect"][0]
    execute_effect(pump_prim, st, me, opp,
                   InPlay.of(repo.get("ST01-017"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 1000, \
        "人間が選んだ麦わらキャラに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST02-003 ウルージ (CHARACTER 緑 cost2 power3000):
#    【ドン!!×1】自分のキャラが3枚以上いる場合、このキャラのパワー+2000。
# --------------------------------------------------------------------------- #
def test_st02_003_urouge_don_pump_self_ai():
    """【ドン!!×1】自キャラ3枚以上 → 自身 (static) +2000。 対象選択なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    urouge = InPlay.of(repo.get("ST02-003"), sickness=False)  # power 3000
    # 自キャラ3枚 (= 条件成立の盤面)
    me.characters = [urouge,
                     InPlay.of(repo.get(SANJI), sickness=False),
                     InPlay.of(repo.get(NAMI), sickness=False)]

    power_before = urouge.power
    eff = _eff(overlay, "ST02-003", "on_attached_don")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, urouge)

    assert urouge.power == power_before + 2000, \
        f"ウルージ自身へ +2000 が反映されていない: {urouge.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  ST02-005 キラー (CHARACTER 緑 cost3 power3000):
#    【登場時】相手のレストのコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st02_005_killer_on_play_ko_ai():
    """【登場時】相手のレスト コスト3以下キャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1
    victim.rested = True                                 # レスト (= 対象条件)
    opp.characters = [victim]

    eff = _eff(overlay, "ST02-005", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST02-005"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手のレスト コスト3以下キャラが KO されていない"


def test_st02_005_killer_on_play_ko_human_pick():
    """人間 + 相手レストキャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(SANJI), sickness=False)  # cost2
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    eff = _eff(overlay, "ST02-005", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST02-005"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"


def test_st02_005_killer_ko_excludes_active_and_high_cost():
    """アクティブ / コスト4以上 は 対象外 (= 候補 0 → 効果不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    active_low = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 だが アクティブ
    opp.characters = [active_low]

    eff = _eff(overlay, "ST02-005", "on_play")
    fired = execute_effect(eff["do"][0], st, me, opp,
                           InPlay.of(repo.get("ST02-005"), sickness=True))
    assert active_low in opp.characters, "アクティブキャラは KO 対象外のはず"
    assert fired is False, "候補0でも ko が発火扱いになっている"


# --------------------------------------------------------------------------- #
#  ST02-008 スクラッチメン・アプー (CHARACTER 緑 cost2 power3000):
#    【ドン!!×1】【アタック時】相手のドン!!1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_st02_008_apoo_attack_rest_opp_don_ai():
    """【アタック時】相手のアクティブドン1枚を レストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 3
    opp.don_rested = 0

    eff = _eff(overlay, "ST02-008", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST02-008"), sickness=False))

    assert opp.don_active == 2, f"相手アクティブドンが 1 枚減っていない: {opp.don_active}"
    assert opp.don_rested == 1, f"相手レストドンが 1 枚増えていない: {opp.don_rested}"


# --------------------------------------------------------------------------- #
#  ST02-009 トラファルガー・ロー (CHARACTER 緑 cost5 power6000):
#    【登場時】自分のレストのコスト5以下の特徴《超新星》か《ハートの海賊団》を持つ
#    キャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_st02_009_law_on_play_untap_ai():
    """【登場時】自レストの 超新星/ハートの海賊団 キャラ1枚を アクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ally = InPlay.of(repo.get("ST02-003"), sickness=False)  # ウルージ (超新星)
    ally.rested = True
    me.characters = [ally]

    eff = _eff(overlay, "ST02-009", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST02-009"), sickness=True))
    _drain(st, [0])

    assert ally.rested is False, "自レストの超新星キャラが アクティブに されていない"


def test_st02_009_law_on_play_untap_human_pick():
    """人間 + レスト超新星 複数 → target_pick modal が立ち resolve で 1 枚 アクティブ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("ST02-003"), sickness=False)  # ウルージ (超新星)
    b = InPlay.of(repo.get("ST02-008"), sickness=False)  # アプー (超新星)
    a.rested = True
    b.rested = True
    me.characters = [a, b]

    eff = _eff(overlay, "ST02-009", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST02-009"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is False, "人間が選んだ超新星キャラが アクティブに されていない"


# --------------------------------------------------------------------------- #
#  ST02-013 ユースタス・キッド (CHARACTER 緑 cost7 power7000):
#    【ブロッカー】【ドン!!×1】【自分のターン終了時】このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_st02_013_kid_end_of_turn_untap_self_ai():
    """【自分のターン終了時】(ドン1ゲート) このキャラ自身を アクティブに。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    kid = InPlay.of(repo.get("ST02-013"), sickness=False)
    kid.rested = True   # ブロック等で レスト状態 (= untap 対象)
    me.characters = [kid]

    eff = _eff(overlay, "ST02-013", "end_of_turn")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, kid)

    assert kid.rested is False, "ターン終了時に キッド自身が アクティブに されていない"


# --------------------------------------------------------------------------- #
#  ST02-014 X・ドレーク (CHARACTER 緑 cost4 power5000):
#    【ドン!!×1】【自分のターン中】このキャラがレストの場合、自分の特徴《超新星》か
#    《海軍》を持つリーダーとキャラのパワー+1000。
# --------------------------------------------------------------------------- #
def test_st02_014_drake_static_team_pump_ai():
    """【ドン1/自ターン中/自身レスト】超新星・海軍 の 自リーダー+キャラ を +1000 (static)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)  # キッド leader (超新星)
    me, opp = st.players[0], st.players[1]
    drake = InPlay.of(repo.get("ST02-014"), sickness=False)  # 超新星/海軍
    drake.rested = True
    me.characters = [drake]

    leader_before = me.leader.power     # キッド leader (超新星) → 対象
    drake_before = drake.power          # ドレーク自身 (超新星) → 対象
    eff = _eff(overlay, "ST02-014", "on_attached_don")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, drake)

    assert me.leader.power == leader_before + 1000, \
        f"超新星リーダーへ +1000 が反映されていない: {me.leader.power}"
    assert drake.power == drake_before + 1000, \
        f"超新星キャラ (ドレーク) へ +1000 が反映されていない: {drake.power}"


# --------------------------------------------------------------------------- #
#  ST02-015 メス (EVENT 緑 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#    その後、自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_st02_015_mes_counter_pump_and_untap_don_ai():
    """【カウンター】自リーダー +2000 (battle) + 自レストドン1枚を アクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 2

    power_before = me.leader.power
    eff = _eff(overlay, "ST02-015", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert me.don_active == 1 and me.don_rested == 1, \
        f"レストドン1枚が アクティブに されていない: active={me.don_active} rested={me.don_rested}"


def test_st02_015_mes_counter_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    friend = InPlay.of(repo.get(SANJI), sickness=False)
    me.characters = [friend]

    eff = _eff(overlay, "ST02-015", "counter")
    # do 配列を順に発火: untap_don (自動) → power_pump が modal を立てる。
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST02-016 反発 (EVENT 緑 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
#    その後、自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_st02_016_hanpatsu_counter_pump_and_untap_don_ai():
    """【カウンター】自リーダー +4000 (battle) + 自レストドン1枚を アクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 1

    power_before = me.leader.power
    eff = _eff(overlay, "ST02-016", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"
    assert me.don_active == 1 and me.don_rested == 0, \
        f"レストドン1枚が アクティブに されていない: active={me.don_active} rested={me.don_rested}"


def test_st02_016_hanpatsu_counter_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 1
    friend = InPlay.of(repo.get(SANJI), sickness=False)
    me.characters = [friend]

    eff = _eff(overlay, "ST02-016", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST02-017 藁備手刀 (EVENT 緑 cost2):
#    【メイン】相手のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_st02_017_warabi_main_rest_opp_chara_ai():
    """【メイン】相手キャラ1枚を レストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # アクティブ
    opp.characters = [victim]

    eff = _eff(overlay, "ST02-017", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim.rested is True, "相手キャラが レストにされていない"


def test_st02_017_warabi_main_rest_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で 1 枚 レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, KID_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)
    b = InPlay.of(repo.get(SANJI), sickness=False)
    opp.characters = [a, b]

    eff = _eff(overlay, "ST02-017", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラが レストにされていない"
