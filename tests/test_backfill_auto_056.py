# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 056):
OP05-028 / OP05-029 / OP05-030 / OP05-031 / OP05-032 / OP05-033 /
OP05-034 / OP05-036 / OP05-037 / OP05-039 の 10 枚
(緑 ドンキホーテ海賊団 系 + 緑 イベント 2 枚)。

目的 (= test_backfill_auto_001〜055.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 単色)
_NAMI = "OP01-016"             # ナミ cost1 power2000
_RED_C3 = "EB02-003"           # トニートニー・チョッパー cost3 power3000
_PLAIN_C2 = "ST01-004"         # サンジ cost2 power4000 (汎用ダミー)
_DONQ_C2 = "OP05-024"          # キュイーン cost2 power2000 ドンキホーテ海賊団
_DONQ_C1 = "OP10-065"          # シュガー cost1 power1000 ドンキホーテ海賊団


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_PLAIN_C2)] * 30
    p1.deck = [repo.get(_PLAIN_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"]
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave56_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-028", "OP05-029", "OP05-030", "OP05-031", "OP05-032",
           "OP05-033", "OP05-034", "OP05-036", "OP05-037", "OP05-039"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-028 ドンキホーテ・ドフラミンゴ (CHARACTER 緑 cost1 power2000):
#    【起動メイン】このキャラをトラッシュに置くことができる：相手のレストの
#      コスト2以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op05_028_activate_trash_self_ko_rested_cost_le_2_ai():
    """起動メイン: 自身をトラッシュ (コスト) → 相手のレストコスト2以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    doffy = InPlay.of(repo.get("OP05-028"), sickness=False)
    me.characters = [doffy]
    victim = InPlay.of(repo.get(_DONQ_C2), sickness=False)  # cost2
    victim.rested = True
    opp.characters = [victim]

    options = list_activate_main_effects(st, me, overlay)
    d_opts = [(src, eff) for (src, eff) in options
              if src.card.card_id == "OP05-028"]
    assert len(d_opts) == 1, f"OP05-028 の起動メインが legal に出ない: {len(d_opts)}"
    fire_activate_main(st, me, opp, *d_opts[0])
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手のレストコスト2以下キャラが KO されていない"
    assert doffy not in me.characters, "コストで ドフラミンゴ がトラッシュに置かれていない"
    assert any(c.card_id == "OP05-028" for c in me.trash), \
        "ドフラミンゴ がトラッシュに置かれていない"


def test_op05_028_activate_active_target_survives():
    """起動メイン: 相手のコスト2キャラが アクティブ (非レスト) なら 対象外 → 残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    doffy = InPlay.of(repo.get("OP05-028"), sickness=False)
    me.characters = [doffy]
    victim = InPlay.of(repo.get(_DONQ_C2), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    d_opts = [o for o in list_activate_main_effects(st, me, overlay)
              if o[0].card.card_id == "OP05-028"]
    fire_activate_main(st, me, opp, *d_opts[0])
    _drain(st, pick=[0])

    assert victim in opp.characters, "アクティブなキャラが KO されている (対象外のはず)"


def test_op05_028_activate_human_ko_pick():
    """人間 + 相手のレストコスト2以下キャラ複数 → ko の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    doffy = InPlay.of(repo.get("OP05-028"), sickness=False)
    me.characters = [doffy]
    a = InPlay.of(repo.get(_NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(_DONQ_C2), sickness=False)  # cost2
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    d_opts = [o for o in list_activate_main_effects(st, me, overlay)
              if o[0].card.card_id == "OP05-028"]
    fire_activate_main(st, me, opp, *d_opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP05-029 ドンキホーテ・ドフラミンゴ (CHARACTER 緑 cost7 power8000):
#    【相手のアタック時】【ターン1回】➀(ドンをレスト)：相手のコスト6以下の
#      キャラ1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op05_029_opp_attack_rest_opp_cost_le_6_ai():
    """相手のアタック時: ドン1レスト (コスト) → 相手のコスト6以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # ➀ コスト源
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (<= 6), active
    victim.rested = False
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-029", "opp_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-029"), sickness=False))
    _drain(st, pick=[0])

    assert victim.rested is True, "相手のコスト6以下キャラがレストされていない"
    assert me.don_active == 2, "➀ コスト (アクティブドン1レスト) が支払われていない"


def test_op05_029_opp_attack_human_rest_pick():
    """人間 + 相手のコスト6以下キャラ複数 → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    a = InPlay.of(repo.get(_RED_C3), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-029", "opp_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-029"), sickness=False))

    # 任意コスト (➀) の pay/skip 確認 modal が先に立つ → pay を選ぶ
    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # コストを払う

    # 続いて レスト対象の target_pick modal が立つ
    assert st.pending_choice is not None, "コスト承認後 target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP05-030 ドンキホーテ・ロシナンテ (CHARACTER 緑 cost2 power1000):
#    【ブロッカー】【相手のターン中】自分のレストのキャラがKOされる場合、
#      代わりにこのキャラをトラッシュに置くことができる。 (replace_ko)
# --------------------------------------------------------------------------- #
def test_op05_030_replace_ko_other_rested_self_chara_ai():
    """相手ターン中: 自分の別レストキャラが KO される時、 代わりに ロシナンテ を
    トラッシュに置き KO を代替する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    rosinante = InPlay.of(repo.get("OP05-030"), sickness=False)
    ally = InPlay.of(repo.get(_RED_C3), sickness=False)  # KO 対象 (レスト)
    ally.rested = True
    me.characters = [rosinante, ally]

    replaced = try_replace_ko(
        st, me, opp, ally, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st, pick=[1])

    assert replaced is True, "レストの別キャラ KO が ロシナンテ で置換されていない"
    assert ally in me.characters, "置換成立時 KO 対象キャラは場に残るべき"
    assert rosinante not in me.characters, "代わりに ロシナンテ がトラッシュへ置かれるべき"
    assert any(c.card_id == "OP05-030" for c in me.trash), \
        "ロシナンテ がトラッシュに置かれていない"


def test_op05_030_replace_ko_not_when_active_victim():
    """KO 対象キャラが アクティブ (非レスト) なら 置換対象外 → 置換されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1
    rosinante = InPlay.of(repo.get("OP05-030"), sickness=False)
    ally = InPlay.of(repo.get(_RED_C3), sickness=False)
    ally.rested = False  # アクティブ = 対象外 (target_rested 不成立)
    me.characters = [rosinante, ally]

    replaced = try_replace_ko(
        st, me, opp, ally, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "アクティブなキャラの KO で置換が成立してはいけない"
    assert rosinante in me.characters, "置換不成立時 ロシナンテ は場に残るべき"


def test_op05_030_replace_ko_human_confirm():
    """人間 actor: replace_ko は 任意 → replace_ko_optional modal が立ち、
    承諾すると ロシナンテ をトラッシュに置き KO を代替する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1
    rosinante = InPlay.of(repo.get("OP05-030"), sickness=False)
    ally = InPlay.of(repo.get(_RED_C3), sickness=False)
    ally.rested = True
    me.characters = [rosinante, ally]

    replaced = try_replace_ko(
        st, me, opp, ally, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    _drain(st, pick=[1])
    assert ally in me.characters, "人間承諾後 KO 対象キャラは場に残るべき"
    assert rosinante not in me.characters, "承諾後 ロシナンテ がトラッシュへ置かれるべき"


# --------------------------------------------------------------------------- #
#  OP05-031 バッファロー (CHARACTER 緑 cost3 power4000):
#    【アタック時】【ターン1回】自分のレストのキャラが2枚以上いる場合、 自分の
#      レストのコスト1のキャラ1枚までを、 アクティブにする。
# --------------------------------------------------------------------------- #
def test_op05_031_on_attack_untap_rested_cost1_ai():
    """アタック時 (自レスト2枚以上): 自分のレストコスト1キャラをアクティブ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    buffalo = InPlay.of(repo.get("OP05-031"), sickness=False)
    buffalo.rested = True  # アタック後 (= レスト状態)、 レスト計数 1
    ally = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1
    ally.rested = True     # レスト計数 2 (= 条件成立) + untap 対象
    me.characters = [buffalo, ally]

    on_attack_eff = overlay.get("OP05-031").effects[0]
    assert on_attack_eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "overlay の レスト2枚条件 self_rested_chara_count_ge=2 が無い"
    for prim in on_attack_eff["do"]:
        execute_effect(prim, st, me, opp, buffalo)
    _drain(st, pick=[0])

    assert ally.rested is False, "レストのコスト1キャラがアクティブ化されていない"


def test_op05_031_on_attack_human_untap_pick():
    """人間 + 自分のレストコスト1キャラ複数 → untap の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    buffalo = InPlay.of(repo.get("OP05-031"), sickness=False)
    buffalo.rested = True
    a = InPlay.of(repo.get(_NAMI), sickness=False)     # cost1
    b = InPlay.of(repo.get(_DONQ_C1), sickness=False)  # cost1
    a.rested = True
    b.rested = True
    me.characters = [buffalo, a, b]

    execute_effect(overlay.get("OP05-031").effects[0]["do"][0], st, me, opp, buffalo)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (cost1 レスト2体) が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is False, "人間が選んだキャラがアクティブ化されていない"
    assert a.rested is True, "選ばなかったキャラはレストのままであるべき"


# --------------------------------------------------------------------------- #
#  OP05-032 ピーカ (CHARACTER 緑 cost4 power6000):
#    【自分のターン終了時】①：このキャラをアクティブにする。
#    【ターン1回】このキャラがKOされる場合、 代わりに「ピーカ」以外の自分の
#      コスト3以上のキャラ1枚までを、 レストにできる。 (replace_ko)
# --------------------------------------------------------------------------- #
def test_op05_032_replace_ko_rest_other_cost_ge_3_ai():
    """KO される時: ピーカ以外の自コスト3以上キャラをレストして KO を代替 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    pica = InPlay.of(repo.get("OP05-032"), sickness=False)
    ally = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (>= 3), active
    ally.rested = False
    me.characters = [pica, ally]

    replaced = try_replace_ko(
        st, me, opp, pica, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st, pick=[0])

    assert replaced is True, "ピーカの KO が コスト3以上キャラのレストで置換されていない"
    assert pica in me.characters, "置換成立時 ピーカ は場に残るべき"
    assert ally.rested is True, "代わりに コスト3以上キャラがレストされるべき"


def test_op05_032_end_of_turn_untap_self_ai():
    """【自分のターン終了時】このキャラをアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    pica = InPlay.of(repo.get("OP05-032"), sickness=False)
    pica.rested = True  # ターン終了時 レスト状態
    me.characters = [pica]

    for prim in _do(overlay, "OP05-032", "end_of_turn"):
        execute_effect(prim, st, me, opp, pica)
    _drain(st)

    assert pica.rested is False, "ターン終了時 ピーカ がアクティブ化されていない"


# --------------------------------------------------------------------------- #
#  OP05-033 ベビー５ (CHARACTER 緑 cost1 power1000):
#    【起動メイン】➀，このキャラをレストにできる：自分の手札からコスト2以下の
#      特徴《ドンキホーテ海賊団》を持つキャラカード1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op05_033_activate_play_donq_cost_le_2_ai():
    """起動メイン: ➀ + 自レスト → 手札からドンキホーテ海賊団 cost2以下を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    baby5 = InPlay.of(repo.get("OP05-033"), sickness=False)
    me.characters = [baby5]
    me.don_active = 3  # ➀ コスト源
    me.hand = [repo.get(_DONQ_C2)]  # キュイーン cost2 ドンキホーテ海賊団

    chars_before = len(me.characters)
    options = list_activate_main_effects(st, me, overlay)
    b_opts = [(src, eff) for (src, eff) in options
              if src.card.card_id == "OP05-033"]
    assert len(b_opts) == 1, f"OP05-033 の起動メインが legal に出ない: {len(b_opts)}"
    fire_activate_main(st, me, opp, *b_opts[0])
    _drain(st, pick=[0])

    assert baby5.rested is True, "起動メインコストで ベビー5 がレストされていない"
    assert any(c.card.card_id == _DONQ_C2 for c in me.characters), \
        "手札からドンキホーテ海賊団 cost2以下キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"


def test_op05_033_activate_human_play_pick():
    """人間 + 手札にドンキホーテ海賊団 cost2以下 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    baby5 = InPlay.of(repo.get("OP05-033"), sickness=False)
    me.characters = [baby5]
    me.don_active = 3
    me.hand = [repo.get(_DONQ_C2), repo.get(_DONQ_C1)]  # 2 種の登場候補

    b_opts = [o for o in list_activate_main_effects(st, me, overlay)
              if o[0].card.card_id == "OP05-033"]
    fire_activate_main(st, me, opp, *b_opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id in (_DONQ_C2, _DONQ_C1) for c in me.characters), \
        "人間が選んだドンキホーテ海賊団キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP05-034 ベビー５ (CHARACTER 緑 cost1 power1000):
#    【起動メイン】➀，このキャラをレストにできる：自分のデッキの上から5枚を見て、
#      特徴《ドンキホーテ海賊団》を持つカード1枚までを公開し、 手札に加える。
#      その後、 残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_034_activate_search_donq_top5_ai():
    """起動メイン: ➀ + 自レスト → デッキ上5枚からドンキホーテ海賊団を手札に (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    baby5 = InPlay.of(repo.get("OP05-034"), sickness=False)
    me.characters = [baby5]
    me.hand = []
    me.deck = [repo.get(_DONQ_C1)] + [repo.get(_PLAIN_C2)] * 10  # 上に ドンキホーテ海賊団

    options = list_activate_main_effects(st, me, overlay)
    b_opts = [(src, eff) for (src, eff) in options
              if src.card.card_id == "OP05-034"]
    assert len(b_opts) == 1, f"OP05-034 の起動メインが legal に出ない: {len(b_opts)}"
    fire_activate_main(st, me, opp, *b_opts[0])
    _drain(st, pick=[0])

    assert baby5.rested is True, "起動メインコストで ベビー5 がレストされていない"
    assert any(c.card_id == _DONQ_C1 for c in me.hand), \
        "デッキ上5枚からドンキホーテ海賊団カードが手札に加わっていない"


def test_op05_034_activate_human_search_flow():
    """人間: 起動メインで デッキ上5枚に ドンキホーテ海賊団 複数 → search modal が立ち解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    baby5 = InPlay.of(repo.get("OP05-034"), sickness=False)
    me.characters = [baby5]
    me.hand = []
    me.deck = [repo.get(_DONQ_C1), repo.get(_PLAIN_C2), repo.get(_DONQ_C2)] \
        + [repo.get(_PLAIN_C2)] * 10  # 上5枚に ドンキホーテ海賊団 2 枚

    b_opts = [o for o in list_activate_main_effects(st, me, overlay)
              if o[0].card.card_id == "OP05-034"]
    fire_activate_main(st, me, opp, *b_opts[0])

    assert st.pending_choice is not None, "人間 起動メインで modal が立たない"
    # discard cost は無い (rest_self のみ) → 直接 search modal
    _drain(st, pick=[0])
    assert any(c.card_id in (_DONQ_C1, _DONQ_C2) for c in me.hand), \
        "人間の解決後 デッキ上5枚からドンキホーテ海賊団カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP05-036 モネ (CHARACTER 緑 cost3 power1000):
#    【ブロッカー】【ブロック時】相手のコスト4以下のキャラ1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op05_036_on_block_rest_opp_cost_le_4_ai():
    """ブロック時: 相手のコスト4以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (<= 4), active
    victim.rested = False
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-036", "on_block"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-036"), sickness=False))
    _drain(st, pick=[0])

    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"


def test_op05_036_on_block_human_rest_pick():
    """人間 + 相手のコスト4以下キャラ複数 → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_RED_C3), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-036", "on_block")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-036"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP05-037 勝者だけが正義だ!!!! (EVENT 緑):
#    【カウンター】自分の手札1枚を捨てることができる：自分のリーダーかキャラ1枚
#      までを、 このバトル中、 パワー+3000。
#    【トリガー】相手のコスト4以下のキャラ1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op05_037_counter_discard_pump_ai():
    """【カウンター】手札1枚を捨てて 自リーダー +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_PLAIN_C2)]  # 捨てるコスト用

    power_before = me.leader.power
    hand_before = len(me.hand)
    for prim in _do(overlay, "OP05-037", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == hand_before - 1, "手札1枚を捨てるコストが支払われていない"


def test_op05_037_trigger_rest_opp_cost_le_4_ai():
    """【トリガー】相手のコスト4以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3, active
    victim.rested = False
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-037", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert victim.rested is True, "トリガーで相手のコスト4以下キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP05-039 ベタベットン流星 (EVENT 緑 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、 このバトル中、 パワー+4000。
#      その後、 相手のレストのコスト3以下のキャラ1枚までを、 KOする。
#    【トリガー】相手のレストのコスト5以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op05_039_counter_pump_and_ko_rested_cost_le_3_ai():
    """【カウンター】自リーダー +4000 → 相手のレストコスト3以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (<= 3)
    victim.rested = True
    opp.characters = [victim]

    power_before = me.leader.power
    for prim in _do(overlay, "OP05-039", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"
    assert victim not in opp.characters, "相手のレストコスト3以下キャラが KO されていない"


def test_op05_039_counter_ko_active_survives():
    """【カウンター】相手のコスト3キャラが アクティブ (非レスト) なら KO 対象外 → 残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)
    victim.rested = False  # アクティブ = KO 対象外
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-039", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert victim in opp.characters, "アクティブなキャラが KO されている (対象外のはず)"


def test_op05_039_trigger_ko_rested_cost_le_5_ai():
    """【トリガー】相手のレストコスト5以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # cost2 (<= 5)
    victim.rested = True
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-039", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert victim not in opp.characters, "トリガーで相手のレストコスト5以下キャラが KO されていない"
