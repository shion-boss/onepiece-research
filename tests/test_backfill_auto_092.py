# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 092):
OP09-008 / OP09-010 / OP09-011 / OP09-012 / OP09-013 /
OP09-017 / OP09-018 / OP09-019 / OP09-020 / OP09-021 の 10 枚
(赤 赤髪海賊団 系 デバフ / 登場 / サーチ + キッド海賊団 静的 速攻)。

目的 (= test_backfill_auto_001〜091.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_SHANKS = "OP09-001"   # シャンクス (leader、 特徴 四皇/赤髪海賊団、 power5000)
_LEADER_KID = "OP10-099"      # ユースタス・キッド (leader、 特徴 キッド海賊団、 power5000)
_LEADER_NEUTRAL = "OP01-001"  # モンキー・D・ルフィ (中立 leader、 power5000)
_AKAGAMI_SMALL = "OP16-018"   # ロックスター (CHARACTER cost1 赤髪海賊団、 サーチ対象)
_OPP_C6 = "PRB02-014"         # サボ cost6 power6000
_OPP_C4 = "PRB02-006"         # ロロノア・ゾロ cost4 power4000
_OPP_SMALL = "OP01-016"       # ナミ cost1 power2000 (小型 KO 対象)
_FILLER = "OP01-013"          # サンジ cost2 power3000 (デッキ/手札 埋め用、 vanilla)


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


def _amain(st, me, overlay, cid):
    """cid の起動メイン (src, eff) を legal option から取り出す。"""
    opts = [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]
    assert len(opts) == 1, f"{cid} の起動メインが legal に 1 件出ない: {len(opts)}"
    return opts[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave92_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-008", "OP09-010", "OP09-011", "OP09-012", "OP09-013",
           "OP09-017", "OP09-018", "OP09-019", "OP09-020", "OP09-021"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-008 ビルディング・スネイク (CHARACTER 赤 cost1 power2000):
#    【起動メイン】このキャラを持ち主のデッキの下に置くことができる：
#      相手のキャラ1枚までを、 このターン中、 パワー-3000。
# --------------------------------------------------------------------------- #
def test_op09_008_building_snake_activate_main_debuff_ai():
    """起動メイン: 相手キャラ1枚を このターン中 -3000 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    snake = InPlay.of(repo.get("OP09-008"), sickness=False)
    me.characters = [snake]
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)  # power6000
    opp.characters = [victim]

    power_before = victim.power
    src, eff = _amain(st, me, overlay, "OP09-008")
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, pick=[0])

    assert victim.power == power_before - 3000, \
        f"起動メインの -3000 が反映されていない: {victim.power} (before {power_before})"


def test_op09_008_building_snake_activate_main_human_pick():
    """人間: 任意コスト承諾 → -3000 の target_pick modal が立ち resolve できる。

    ⚠ 公式は 「このキャラを持ち主のデッキの下に置く**ことができる**：」 = 任意コスト。
      overlay が このコストを欠いていた のを 2026-08-04 に修正 → 人間経路は
      optional_cost_confirm が先に立つ。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    snake = InPlay.of(repo.get("OP09-008"), sickness=False)
    me.characters = [snake]
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [a, b]

    src, eff = _amain(st, me, overlay, "OP09-008")
    fire_activate_main(st, me, opp, src, eff)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 = デッキの下に置く

    assert st.pending_choice is not None, "承諾後に target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[0])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP09-010 ボンク・パンチ (CHARACTER 赤 cost4 power5000):
#    【登場時】自分の手札から「モンスター」1枚までを、 登場させる。
#    【ドン‼×1】【アタック時】このキャラは、 このターン中、 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op09_010_bonk_punch_on_play_summon_monster_ai():
    """登場時: 手札の「モンスター」を登場させる (AI)。 hand-1 / chara+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP09-012")]  # モンスター (CHARACTER 赤髪海賊団)

    for prim in _eff(overlay, "OP09-010", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-010"), sickness=True))
    _drain(st, pick=[0])

    assert any(c.card.card_id == "OP09-012" for c in me.characters), \
        "手札の「モンスター」が登場していない"
    assert not any(c.card_id == "OP09-012" for c in me.hand), \
        "登場した「モンスター」は手札から消えるべき"


def test_op09_010_bonk_punch_on_attack_self_pump_ai():
    """アタック時 (ドン1ゲート): 自身を このターン中 +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    bonk = InPlay.of(repo.get("OP09-010"), sickness=False)  # power5000
    me.characters = [bonk]

    on_attack = _eff(overlay, "OP09-010", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    power_before = bonk.power
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, bonk)
    _drain(st, pick=[0])

    assert bonk.power == power_before + 2000, \
        f"アタック時の 自己 +2000 が反映されていない: {bonk.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP09-011 ホンゴウ (CHARACTER 赤 cost3 power3000):
#    【起動メイン】このキャラをレストにできる：自分のリーダーが特徴《赤髪海賊団》を
#      持つ場合、 相手のキャラ1枚までを、 このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op09_011_hongou_activate_main_debuff_ai():
    """起動メイン (赤髪 leader): 自レスト → 相手キャラ1枚 -2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)  # 赤髪海賊団 leader
    me, opp = st.players[0], st.players[1]
    hongou = InPlay.of(repo.get("OP09-011"), sickness=False)
    me.characters = [hongou]
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    src, eff = _amain(st, me, overlay, "OP09-011")
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, pick=[0])

    assert victim.power == power_before - 2000, \
        f"起動メインの -2000 が反映されていない: {victim.power} (before {power_before})"
    assert hongou.rested is True, "起動メインコストで ホンゴウ がレストされるべき"


def test_op09_011_hongou_activate_main_no_akagami_leader():
    """赤髪 でない leader なら 条件不成立 → 起動メインが legal に出ない (発動不可)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)  # 中立 leader (= 条件不成立)
    me, opp = st.players[0], st.players[1]
    hongou = InPlay.of(repo.get("OP09-011"), sickness=False)
    me.characters = [hongou]
    opp.characters = [InPlay.of(repo.get(_OPP_C6), sickness=False)]

    opts = [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == "OP09-011"]
    assert len(opts) == 0, \
        "赤髪でない leader では ホンゴウ の起動メインは legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP09-012 モンスター (CHARACTER 赤 cost3 power4000 動物/赤髪海賊団):
#    自分のキャラの「ボンク・パンチ」が効果でKOされる場合、 代わりに
#    このキャラをトラッシュに置いてもよい。 (replace_ko、 任意)
# --------------------------------------------------------------------------- #
def test_op09_012_monster_replace_ko_bonk_ai():
    """ボンク・パンチが相手効果でKOされる時、 代わりにモンスターがトラッシュへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    bonk = InPlay.of(repo.get("OP09-010"), sickness=False)      # ボンク・パンチ
    monster = InPlay.of(repo.get("OP09-012"), sickness=False)   # モンスター (holder)
    me.characters = [bonk, monster]

    replaced = try_replace_ko(
        st, me, opp, bonk, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "モンスターが居るのに ボンク・パンチ の KO が置換されていない"
    assert bonk in me.characters, "置換成立時 ボンク・パンチ は場に残るべき"
    assert monster not in me.characters, "代わりに モンスター がトラッシュへ置かれるべき"
    assert any(c.card_id == "OP09-012" for c in me.trash), \
        "モンスター がトラッシュに置かれていない"


def test_op09_012_monster_replace_ko_not_for_other_victim():
    """ボンク・パンチ 以外の自キャラの KO では 置換対象にならない (target_name 限定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    other = InPlay.of(repo.get(_FILLER), sickness=False)        # ボンク以外
    monster = InPlay.of(repo.get("OP09-012"), sickness=False)
    me.characters = [other, monster]

    replaced = try_replace_ko(
        st, me, opp, other, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "ボンク・パンチ 以外の KO で置換が成立してはいけない"
    assert monster in me.characters, "対象外の時 モンスター は場に残るべき"


def test_op09_012_monster_replace_ko_human_confirm():
    """人間 actor: replace_ko は 任意 → replace_ko_optional modal が立ち、
    承諾すると モンスター 1 枚をトラッシュして ボンク の KO を代替する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bonk = InPlay.of(repo.get("OP09-010"), sickness=False)
    monster = InPlay.of(repo.get("OP09-012"), sickness=False)
    me.characters = [bonk, monster]

    replaced = try_replace_ko(
        st, me, opp, bonk, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    _drain(st, pick=[1], guard=5)
    assert bonk in me.characters, "人間承諾後 ボンク・パンチ は場に残るべき"
    assert monster not in me.characters, "承諾後 モンスター がトラッシュへ置かれるべき"


# --------------------------------------------------------------------------- #
#  OP09-013 ヤソップ (CHARACTER 赤 cost5 power6000):
#    【登場時】自分のリーダー1枚までを、 次の相手のターン終了時まで、 パワー+1000。
#    【ドン‼×1】【アタック時】相手のキャラ1枚までを、 このターン中、 パワー-1000。
# --------------------------------------------------------------------------- #
def test_op09_013_yasopp_on_play_pump_leader_ai():
    """登場時: 自リーダーを 次の相手ターン終了時まで +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP09-013", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-013"), sickness=True))
    _drain(st, pick=[0])

    assert me.leader.power == power_before + 1000, \
        f"登場時の 自リーダー +1000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op09_013_yasopp_on_attack_debuff_ai():
    """アタック時 (ドン1ゲート): 相手キャラ1枚を このターン中 -1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP09-013", "on_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-013"), sickness=False))
    _drain(st, pick=[0])

    assert victim.power == power_before - 1000, \
        f"アタック時の -1000 が反映されていない: {victim.power} (before {power_before})"


def test_op09_013_yasopp_on_attack_human_pick():
    """人間 + 相手キャラ複数 → -1000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP09-013", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-013"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[0])
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP09-017 ワイヤー (CHARACTER 赤 cost4 power4000 キッド海賊団):
#    【ドン‼×1】自分のリーダーが、 パワー7000以上でかつ特徴《キッド海賊団》を
#      持つ場合、 このキャラは【速攻】を得る。 (静的)
# --------------------------------------------------------------------------- #
def test_op09_017_wire_static_rush_when_leader_strong():
    """キッド leader が power7000以上 + ドン1付与 → 静的に【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_LEADER_KID), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_LEADER_NEUTRAL), sickness=False))
    wire = InPlay.of(repo.get("OP09-017"), sickness=True)  # 召喚酔いでも速攻なら攻撃可
    p0.characters = [wire]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    wire.attached_dons = 1        # ドン1ゲート成立
    p0.leader.attached_dons = 2   # 5000 + 2000 = 7000 (>=7000 成立)
    evaluate_static_effects(st, overlay)

    assert wire.is_rush_now is True, \
        "キッド leader 7000 + ドン1 で ワイヤー が【速攻】を得ていない"


def test_op09_017_wire_no_rush_when_leader_weak():
    """リーダー power が 7000 未満 (ドン無し 5000) なら 速攻を得ない。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_LEADER_KID), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_LEADER_NEUTRAL), sickness=False))
    wire = InPlay.of(repo.get("OP09-017"), sickness=True)
    p0.characters = [wire]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    wire.attached_dons = 1
    p0.leader.attached_dons = 0   # power 5000 (<7000)
    evaluate_static_effects(st, overlay)

    assert wire.is_rush_now is False, \
        "リーダー 5000 では ワイヤー は【速攻】を得てはいけない"


# --------------------------------------------------------------------------- #
#  OP09-018 失せろ (EVENT 赤 cost3):
#    【メイン】相手のキャラ2枚までを、 パワーの合計が4000以下になるようにKOする。
# --------------------------------------------------------------------------- #
def test_op09_018_useiro_ko_total_le_ai():
    """メイン: 相手のキャラをパワー合計4000以下でKO。 2000+2000=4000 → 両方KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_SMALL), sickness=False)  # power2000
    b = InPlay.of(repo.get(_OPP_SMALL), sickness=False)  # power2000
    opp.characters = [a, b]

    for prim in _eff(overlay, "OP09-018", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert len(opp.characters) == 0, "合計4000以下 (2000+2000) の2枚がKOされていない"


def test_op09_018_useiro_big_char_protected():
    """単独 power5000超 のキャラは 合計制約 (4000以下) で KO 不可 → 残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_OPP_C6), sickness=False)  # power6000 (>4000)
    opp.characters = [big]

    for prim in _eff(overlay, "OP09-018", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert big in opp.characters, "power6000 の単独キャラは合計4000制約でKOされてはいけない"


# --------------------------------------------------------------------------- #
#  OP09-019 おれは友達を傷つける奴は許さない!!!! (EVENT 赤 cost2):
#    【メイン】自リーダーが《赤髪海賊団》なら 相手キャラ1枚 -3000。 その後、
#      相手のパワー5000以上のキャラがいる場合、 カード1枚を引く。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_019_main_debuff_and_conditional_draw_ai():
    """メイン (赤髪 leader): 相手1枚 -3000 → 残りに5000以上が居れば1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C6), sickness=False)  # power6000
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)  # power6000 (debuff 後も5000以上)
    opp.characters = [a, b]

    deck_before = len(me.deck)
    hand_before = len(me.hand)
    for prim in _eff(overlay, "OP09-019", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    # 1 枚が -3000 (6000 → 3000)、 もう1枚は6000 のまま
    powers = sorted(c.power for c in opp.characters)
    assert powers == [3000, 6000], \
        f"相手キャラの -3000 が想定通りでない: {powers}"
    # 残りに power5000以上 (= 6000) が居る → 1ドロー
    assert len(me.deck) == deck_before - 1, "条件付き1ドローでデッキが1枚減っていない"
    assert len(me.hand) == hand_before + 1, "条件付き1ドローで手札が1枚増えていない"


def test_op09_019_trigger_draw_ai():
    """トリガー: カード1枚を引く (AI)。 deck-1 / hand+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    deck_before = len(me.deck)
    hand_before = len(me.hand)
    for prim in _eff(overlay, "OP09-019", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert len(me.deck) == deck_before - 1, "トリガーの1ドローでデッキが1枚減っていない"
    assert len(me.hand) == hand_before + 1, "トリガーの1ドローで手札が1枚増えていない"


def test_op09_019_main_debuff_human_pick():
    """人間 + 相手キャラ複数 → -3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP09-019", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[0])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP09-020 来い…!!!おれ達が相手をしてやる!!! (EVENT 赤 cost1):
#    【メイン】自デッキ上5枚を見て、 自身以外の《赤髪海賊団》1枚までを公開し手札へ。
#      その後、 残りを好きな順番でデッキ下へ。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_020_search_akagami_ai():
    """メイン: デッキ上5枚から《赤髪海賊団》1枚を手札へ (AI)。 上に赤髪を仕込む。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)
    me, opp = st.players[0], st.players[1]
    akagami = repo.get(_AKAGAMI_SMALL)  # ロックスター (赤髪海賊団)
    assert "赤髪海賊団" in (akagami.features or ""), "テスト前提: 対象は 赤髪海賊団"
    me.deck = [akagami] + [repo.get(_FILLER)] * 20
    me.hand = []

    for prim in _eff(overlay, "OP09-020", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert any(c.card_id == _AKAGAMI_SMALL for c in me.hand), \
        "デッキ上5枚から 赤髪海賊団キャラが手札に加わっていない"


def test_op09_020_trigger_draw_ai():
    """トリガー: カード1枚を引く (AI)。 deck-1 / hand+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    deck_before = len(me.deck)
    hand_before = len(me.hand)
    for prim in _eff(overlay, "OP09-020", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert len(me.deck) == deck_before - 1, "トリガーの1ドローでデッキが1枚減っていない"
    assert len(me.hand) == hand_before + 1, "トリガーの1ドローで手札が1枚増えていない"


def test_op09_020_search_human_modal():
    """人間 + デッキ上5枚に 赤髪 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    akagami = repo.get(_AKAGAMI_SMALL)
    me.deck = [akagami, repo.get(_FILLER), akagami] + [repo.get(_FILLER)] * 15
    me.hand = []

    execute_effect(_eff(overlay, "OP09-020", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (赤髪) を選択
    _drain(st, pick=[])
    assert any(c.card_id == _AKAGAMI_SMALL for c in me.hand), \
        "人間が選んだ 赤髪海賊団キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-021 レッド・フォース号 (STAGE 赤 cost2):
#    【起動メイン】このステージをレストにできる：自リーダーが《赤髪海賊団》なら
#      相手のキャラ1枚までを、 このターン中、 パワー-1000。
# --------------------------------------------------------------------------- #
def test_op09_021_red_force_activate_main_debuff_ai():
    """起動メイン (赤髪 leader): 自ステージをレスト → 相手キャラ1枚 -1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay)  # 赤髪海賊団 leader
    me, opp = st.players[0], st.players[1]
    red_force = InPlay.of(repo.get("OP09-021"), sickness=False)  # STAGE
    me.stages = [red_force]
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    src, eff = _amain(st, me, overlay, "OP09-021")
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, pick=[0])

    assert victim.power == power_before - 1000, \
        f"起動メインの -1000 が反映されていない: {victim.power} (before {power_before})"
    assert red_force.rested is True, "起動メインコストで レッド・フォース号 がレストされるべき"


def test_op09_021_red_force_activate_main_human_pick():
    """人間 + 相手キャラ複数 → -1000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    red_force = InPlay.of(repo.get("OP09-021"), sickness=False)
    me.stages = [red_force]
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)
    opp.characters = [a, b]

    src, eff = _amain(st, me, overlay, "OP09-021")
    fire_activate_main(st, me, opp, src, eff)

    # optional_cost_then のため、 まず 任意コスト (レスト) 確認 modal が立つ
    assert st.pending_choice is not None, "人間で 任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コスト (レスト) を払う

    # 続いて -1000 の対象選択 modal
    assert st.pending_choice is not None, "コスト承認後に target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[0])
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"
    assert red_force.rested is True, "任意コスト承認で レッド・フォース号 がレストされるべき"
