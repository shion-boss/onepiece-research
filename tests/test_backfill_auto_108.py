# -*- coding: utf-8 -*-
"""OP10 弾 黒 EVENT + 黄 (革命軍・超新星・キッド海賊団) 効果 回帰テスト
バックフィル (自動生成 wave 108):
OP10-096 / OP10-097 / OP10-098 / OP10-100 / OP10-102 /
OP10-103 / OP10-104 / OP10-106 / OP10-107 / OP10-109 の 10 枚。

  OP10-096 王下七武海はもう要らねェ…!!! (EVENT 黒) = メイン 相手コスト8以下の王下七武海
     キャラ1枚までを KO / トリガー コスト4以下の王下七武海1枚までを KO
  OP10-097 ゴムゴムの犀榴弾砲 (EVENT 黒) = メイン ドレスローザキャラ1枚に +2000。
     その後 自トラッシュ10枚以上なら そのカードに【バニッシュ】(turn)
  OP10-098 解放 (EVENT 黒) = メイン 自キャラが相手より2枚以上少ない場合、 相手の
     コスト6以下1枚 + コスト4以下1枚までを KO (ko_multi)
  OP10-100 イナズマ (CHARACTER 黄) = 【ドン‼×1】【アタック時】お互いのライフ合計以下の
     コストを持つ相手キャラ1枚までを レストにする
  OP10-102 エンポリオ・イワンコフ (CHARACTER 黄) = 【起動メイン】【ターン1回】革命軍キャラ
     3枚までを +1000。 その後 自ライフの上1枚を手札に加える
  OP10-103 カポネ・ベッジ (CHARACTER 黄) = 【登場時】(任意: ライフ上か下1枚を手札に):
     手札から超新星キャラ1枚までを ライフの上に表向きで加える (optional_cost_then)
  OP10-104 カリブー (CHARACTER 黄) = 【ドン‼×1】自リーダー超新星 & 相手ライフ3枚以上なら
     このキャラはバトルでKOされない (静的 set_ko_immune_battle_only)
  OP10-106 キラー (CHARACTER 黄) = 【KO時】自リーダー超新星なら デッキ上3枚から
     超新星/キッド海賊団カード1枚までを公開手札 (search_top_n)
  OP10-107 ジュエリー・ボニー (CHARACTER 黄) = 【ブロッカー】【登場時】(任意: ライフ上か下
     1枚を手札に): 手札からコスト5の超新星キャラ1枚までを ライフの上に (optional_cost_then)
  OP10-109 バジル・ホーキンス (CHARACTER 黄) = 【KO時】相手ライフの上1枚までをトラッシュ /
     トリガー カード2枚引き手札1枚捨てる

目的 (= test_backfill_auto_001〜107.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
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
    eval_all_conditions,
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GENERIC = "OP01-001"   # ロロノア・ゾロ (超新星/麦わらの一味 — 汎用埋め用)
_LEADER_SHINSEI = "OP13-001"   # モンキー・Ｄ・ルフィ (超新星/麦わらの一味)
_LEADER_NON_SHINSEI = "OP07-001"  # モンキー・D・ドラゴン (革命軍 — 超新星を持たない)
_FILLER = "ST01-004"           # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SHICHIBUKAI_C4 = "EB02-023"   # クロコダイル cost4 (王下七武海/B・W)
_SHICHIBUKAI_C5 = "PRB02-011"  # ドンキホーテ・ドフラミンゴ cost5 (王下七武海/ドンキホーテ海賊団)
_DRESSROSA_C = "OP16-043"      # ウソップ cost2 power1000 (ドレスローザ/麦わらの一味)
_REVO_C1 = "EB04-045"          # ジニー cost1 power2000 (革命軍)
_REVO_C2 = "OP13-008"          # エンポリオ・イワンコフ cost2 power3000 (革命軍)
_SHINSEI_C5 = "EB03-017"       # ジュエリー・ボニー cost5 power6000 (超新星/ボニー海賊団)
_SHINSEI_C3 = "PRB02-004"      # ジュエリー・ボニー cost3 power3000 (超新星/ボニー海賊団)
_SHINSEI_SEARCH = "EB01-015"   # スクラッチメン・アプー cost1 (超新星/オンエア海賊団)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave108_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-096", "OP10-097", "OP10-098", "OP10-100", "OP10-102",
           "OP10-103", "OP10-104", "OP10-106", "OP10-107", "OP10-109"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-096 王下七武海はもう要らねェ…!!! (EVENT 黒):
#    メイン 相手コスト8以下の王下七武海キャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_op10_096_main_ko_shichibukai_ai():
    """【メイン】AI: 相手のコスト8以下の王下七武海キャラ1枚を KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SHICHIBUKAI_C5), sickness=False)  # cost5 王下七武海
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-096", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "コスト8以下の王下七武海キャラが KO されていない"


def test_op10_096_main_does_not_ko_non_shichibukai():
    """【メイン】王下七武海でない相手キャラは 対象にならない (filter feature)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    non_target = InPlay.of(repo.get(_FILLER), sickness=False)  # 王下七武海でない
    opp.characters = [non_target]

    for prim in _eff(overlay, "OP10-096", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert non_target in opp.characters, \
        "王下七武海を持たない相手キャラが KO されてはいけない"


def test_op10_096_main_human_target_pick():
    """人間 + 王下七武海キャラ複数 → target_pick modal → resolve で1枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_SHICHIBUKAI_C4), sickness=False)  # cost4 王下七武海
    b = InPlay.of(repo.get(_SHICHIBUKAI_C5), sickness=False)  # cost5 王下七武海
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-096", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert a not in opp.characters, "人間が選んだ王下七武海キャラが KO されていない"


def test_op10_096_trigger_ko_only_cost4_or_less():
    """【トリガー】コスト4以下限定 (filter cost_le=4)。 overlay の filter を担保。"""
    overlay = _overlay()
    trig = _eff(overlay, "OP10-096", "trigger")
    filt = trig["do"][0]["ko"]["filter"]
    assert filt.get("cost_le") == 4 and filt.get("feature") == "王下七武海", \
        f"トリガーの filter (cost_le=4 / 王下七武海) が想定と違う: {filt}"


# --------------------------------------------------------------------------- #
#  OP10-097 ゴムゴムの犀榴弾砲 (EVENT 黒):
#    メイン ドレスローザキャラ1枚に +2000。 その後 自トラッシュ10枚以上なら【バニッシュ】
# --------------------------------------------------------------------------- #
def test_op10_097_main_pump_dressrosa_2000_ai():
    """【メイン】AI: ドレスローザキャラ1枚に このターン中 +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get(_DRESSROSA_C), sickness=False)  # power1000
    me.characters = [target]

    power_before = target.power
    pump_eff = _eff(overlay, "OP10-097", "main", needle="power_pump")
    for prim in pump_eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert target.power == power_before + 2000, \
        f"ドレスローザキャラに +2000 されていない: {target.power} (before {power_before})"


def test_op10_097_banish_when_trash_ge_10():
    """その後トラッシュ10枚以上 → ドレスローザキャラに【バニッシュ】(turn)。"""
    repo = _repo()
    overlay = _overlay()
    banish_eff = _eff(overlay, "OP10-097", "main", needle="give_keyword")
    assert banish_eff.get("if", {}).get("self_trash_count_ge") == 10, \
        "overlay の 条件 self_trash_count_ge=10 が無い"

    # トラッシュ10枚 → 成立: バニッシュ付与
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get(_DRESSROSA_C), sickness=False)
    me.characters = [target]
    me.trash = [repo.get(_FILLER)] * 10
    assert eval_all_conditions(banish_eff, st, me, None) is True, \
        "トラッシュ10枚で 条件が成立するべき"
    for prim in banish_eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert "バニッシュ" in target.granted_keywords, \
        "トラッシュ10枚で【バニッシュ】が付与されていない"

    # トラッシュ9枚 → 不成立
    st2 = _state(repo, _LEADER_GENERIC, overlay)
    me2 = st2.players[0]
    me2.trash = [repo.get(_FILLER)] * 9
    assert eval_all_conditions(banish_eff, st2, me2, None) is False, \
        "トラッシュ9枚では 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP10-098 解放 (EVENT 黒):
#    メイン 自キャラが相手より2枚以上少ない場合、 相手コスト6以下1枚 + コスト4以下1枚を KO
# --------------------------------------------------------------------------- #
def test_op10_098_main_ko_multi_ai():
    """【メイン】AI: 条件成立時、 相手キャラ2枚 (コスト6以下 + コスト4以下) を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # 自キャラ0
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 → ≤6 かつ ≤4
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [a, b]  # 相手2枚 → chara_diff = 0-2 = -2

    eff = _eff(overlay, "OP10-098", "main")
    assert eff.get("if", {}).get("chara_diff_le") == -2, \
        "overlay の 条件 chara_diff_le=-2 が無い"
    assert eval_all_conditions(eff, st, me, None) is True, \
        "自0/相手2 で 条件が成立するべき"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(opp.characters) == 0, \
        f"相手キャラ2枚が KO されていない: 残 {len(opp.characters)}"


def test_op10_098_main_gated_by_chara_diff():
    """自キャラが相手と同数 (diff=0) では 条件不成立 → 発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    eff = _eff(overlay, "OP10-098", "main")
    assert eval_all_conditions(eff, st, me, None) is False, \
        "自1/相手1 (diff=0) で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP10-100 イナズマ (CHARACTER 黄):
#    【ドン‼×1】【アタック時】お互いのライフ合計以下のコストを持つ相手キャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_op10_100_on_attack_rest_opp_within_life_sum_ai():
    """【アタック時】AI: お互いのライフ合計以下のコスト を持つ相手キャラをレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    opp.life = [repo.get(_FILLER)] * 2  # 合計4
    victim = InPlay.of(repo.get(_SHICHIBUKAI_C4), sickness=False)  # cost4 ≤ 4
    victim.rested = False
    opp.characters = [victim]

    eff = _eff(overlay, "OP10-100", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    attacker = InPlay.of(repo.get("OP10-100"), sickness=False)
    attacker.attached_dons = 1
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert victim.rested is True, \
        "ライフ合計以下のコストを持つ相手キャラがレストにされていない"


def test_op10_100_on_attack_no_rest_when_cost_above_life_sum():
    """相手キャラのコストが ライフ合計を超える場合は 対象にならない (レストされない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 1
    opp.life = [repo.get(_FILLER)] * 1  # 合計2
    victim = InPlay.of(repo.get(_SHICHIBUKAI_C4), sickness=False)  # cost4 > 2
    victim.rested = False
    opp.characters = [victim]

    attacker = InPlay.of(repo.get("OP10-100"), sickness=False)
    attacker.attached_dons = 1
    for prim in _eff(overlay, "OP10-100", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert victim.rested is False, \
        "ライフ合計を超えるコストの相手キャラがレストされてはいけない"


# --------------------------------------------------------------------------- #
#  OP10-102 エンポリオ・イワンコフ (CHARACTER 黄):
#    【起動メイン】【ターン1回】革命軍キャラ3枚までを +1000。 その後 自ライフ上1枚を手札へ
# --------------------------------------------------------------------------- #
def test_op10_102_activate_main_pump_revo_and_life_to_hand_ai():
    """【起動メイン】AI: 革命軍キャラに +1000 / 自ライフ上1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    r1 = InPlay.of(repo.get(_REVO_C1), sickness=False)  # 革命軍 power2000
    r2 = InPlay.of(repo.get(_REVO_C2), sickness=False)  # 革命軍 power3000
    me.characters = [r1, r2]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []

    p1_before, p2_before = r1.power, r2.power
    life_before, hand_before = len(me.life), len(me.hand)
    eff = _eff(overlay, "OP10-102", "activate_main")
    assert eff.get("cost", {}).get("once_per_turn") is True, \
        "overlay の ターン1回 制約 (once_per_turn) が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-102"), sickness=False))
    _drain(st, [0])
    assert r1.power == p1_before + 1000 and r2.power == p2_before + 1000, \
        f"革命軍キャラに +1000 されていない: {r1.power}/{r2.power}"
    assert len(me.life) == life_before - 1 and len(me.hand) == hand_before + 1, \
        f"自ライフ上1枚が手札に加わっていない: life={len(me.life)} hand={len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP10-103 カポネ・ベッジ (CHARACTER 黄):
#    【登場時】(任意: ライフ上か下1枚を手札に): 手札から超新星キャラ1枚を ライフ上に表向き
# --------------------------------------------------------------------------- #
def test_op10_103_on_play_optional_hand_to_life_ai():
    """【登場時】AI: 任意コスト(ライフ→手札)を払い 手札の超新星キャラをライフの上に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_SHINSEI_C3)]  # 超新星キャラ (cost制限なし)

    for prim in _eff(overlay, "OP10-103", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-103"), sickness=True))
    _drain(st, [1])  # optional_cost_confirm は承諾 (idx1) 側
    assert any(c.card_id == _SHINSEI_C3 for c in me.life), \
        "手札の超新星キャラがライフに加わっていない"
    assert not any(c.card_id == _SHINSEI_C3 for c in me.hand), \
        "ライフへ移した超新星キャラが手札に残っている"


def test_op10_103_on_play_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_SHINSEI_C3)]

    execute_effect(_eff(overlay, "OP10-103", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-103"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert any(c.card_id == _SHINSEI_C3 for c in me.life), \
        "承諾後 超新星キャラがライフに加わっていない"


# --------------------------------------------------------------------------- #
#  OP10-104 カリブー (CHARACTER 黄):
#    【ドン‼×1】自リーダー超新星 & 相手ライフ3枚以上なら このキャラはバトルでKOされない
# --------------------------------------------------------------------------- #
def _karibu_static(repo, overlay, leader, opp_life, dons):
    st = _state(repo, leader, overlay)
    me, opp = st.players
    c = InPlay.of(repo.get("OP10-104"), sickness=False)
    c.attached_dons = dons
    me.characters = [c]
    opp.life = [repo.get(_FILLER)] * opp_life
    evaluate_static_effects(st, overlay)
    return c


def test_op10_104_battle_ko_immune_when_shinsei_and_opp_life_ge3():
    """自リーダー超新星 & 相手ライフ3枚以上 & ドン1 → バトルKO耐性 (static)。"""
    repo = _repo()
    overlay = _overlay()
    c = _karibu_static(repo, overlay, _LEADER_SHINSEI, opp_life=3, dons=1)
    assert c.battle_ko_immune_static is True, \
        "超新星leader & 相手ライフ3 & ドン1 で バトルKO耐性 が立っていない"


def test_op10_104_no_immune_when_opp_life_below_3():
    """相手ライフ2枚 (< 3) では 条件不成立 → 耐性は立たない。"""
    repo = _repo()
    overlay = _overlay()
    c = _karibu_static(repo, overlay, _LEADER_SHINSEI, opp_life=2, dons=1)
    assert c.battle_ko_immune_static is False, \
        "相手ライフ2枚で バトルKO耐性 が立ってはいけない"


def test_op10_104_no_immune_when_leader_not_shinsei():
    """リーダーが超新星でなければ 条件不成立 → 耐性は立たない。"""
    repo = _repo()
    overlay = _overlay()
    c = _karibu_static(repo, overlay, _LEADER_NON_SHINSEI, opp_life=3, dons=1)
    assert c.battle_ko_immune_static is False, \
        "非超新星leader で バトルKO耐性 が立ってはいけない"


# --------------------------------------------------------------------------- #
#  OP10-106 キラー (CHARACTER 黄):
#    【KO時】自リーダー超新星なら デッキ上3枚から 超新星/キッド海賊団1枚を公開手札
# --------------------------------------------------------------------------- #
def test_op10_106_on_ko_search_shinsei_ai():
    """【KO時】AI: 自リーダー超新星 → デッキ上3枚から 超新星カードを手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHINSEI, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHINSEI_SEARCH)] + [repo.get(_FILLER)] * 20  # 超新星 を上に
    me.hand = []

    eff = _eff(overlay, "OP10-106", "on_ko")
    assert eff.get("if", {}).get("leader_feature") == "超新星", \
        "overlay の 条件 leader_feature=超新星 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-106"), sickness=False))
    _drain(st, [0])
    assert any(c.card_id == _SHINSEI_SEARCH for c in me.hand), \
        "デッキ上3枚から 超新星カードが手札に加わっていない"


def test_op10_106_on_ko_gated_by_leader_shinsei():
    """リーダーが超新星でなければ【KO時】効果の条件を満たさない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NON_SHINSEI, overlay)
    me = st.players[0]
    eff = _eff(overlay, "OP10-106", "on_ko")
    assert eval_all_conditions(eff, st, me, None) is False, \
        "非超新星leader で 条件が成立してはいけない"


def test_op10_106_on_ko_search_human_pick():
    """人間 + デッキ上3枚に 超新星 複数 → search_top_n modal → resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHINSEI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHINSEI_SEARCH), repo.get(_FILLER),
               repo.get(_SHINSEI_C3)] + [repo.get(_FILLER)] * 15
    me.hand = []

    execute_effect(_eff(overlay, "OP10-106", "on_ko")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-106"), sickness=False))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id in (_SHINSEI_SEARCH, _SHINSEI_C3) for c in me.hand), \
        "人間が選んだ 超新星カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP10-107 ジュエリー・ボニー (CHARACTER 黄):
#    【ブロッカー】【登場時】(任意: ライフ上か下1枚を手札に): 手札からコスト5の超新星キャラ
#    1枚を ライフの上に表向きで加える
# --------------------------------------------------------------------------- #
def test_op10_107_on_play_optional_hand_to_life_ai():
    """【登場時】AI: 任意コストを払い 手札のコスト5超新星キャラをライフの上に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_SHINSEI_C5)]  # コスト5 超新星

    for prim in _eff(overlay, "OP10-107", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-107"), sickness=True))
    _drain(st, [1])  # optional_cost_confirm は承諾側
    assert any(c.card_id == _SHINSEI_C5 for c in me.life), \
        "手札のコスト5超新星キャラがライフに加わっていない"


def test_op10_107_on_play_only_cost5_shinsei_eligible():
    """コスト5以外の超新星キャラは 対象にならない (filter cost_eq=5)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_SHINSEI_C3)]  # cost3 超新星 → 非対象

    for prim in _eff(overlay, "OP10-107", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-107"), sickness=True))
    _drain(st, [1])
    assert not any(c.card_id == _SHINSEI_C3 for c in me.life), \
        "コスト5でない超新星キャラがライフに加わってはいけない"
    assert any(c.card_id == _SHINSEI_C3 for c in me.hand), \
        "非対象の超新星キャラは手札に残るべき"


def test_op10_107_on_play_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_SHINSEI_C5)]

    execute_effect(_eff(overlay, "OP10-107", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-107"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert any(c.card_id == _SHINSEI_C5 for c in me.life), \
        "承諾後 コスト5超新星キャラがライフに加わっていない"


# --------------------------------------------------------------------------- #
#  OP10-109 バジル・ホーキンス (CHARACTER 黄):
#    【KO時】相手ライフの上1枚までをトラッシュ / 【トリガー】カード2枚引き手札1枚捨てる
# --------------------------------------------------------------------------- #
def test_op10_109_on_ko_mill_opp_life_ai():
    """【KO時】AI: 相手ライフの上1枚をトラッシュに置く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3

    life_before = len(opp.life)
    trash_before = len(opp.trash)
    for prim in _eff(overlay, "OP10-109", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-109"), sickness=False))
    _drain(st, [0])
    assert len(opp.life) == life_before - 1, \
        f"相手ライフの上1枚がトラッシュへ移されていない: {len(opp.life)}"
    assert len(opp.trash) == trash_before + 1, \
        "捨てた相手ライフがトラッシュに置かれていない"


def test_op10_109_trigger_draw2_discard1_ai():
    """【トリガー】AI: 2枚引いて1枚捨てる → 手札 net +1、 デッキ -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    for prim in _eff(overlay, "OP10-109", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 2 - 1, \
        f"手札 net (+2 -1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"デッキが2枚減っていない: {len(me.deck)}"
