# -*- coding: utf-8 -*-
"""OP15 弾 効果 回帰テスト バックフィル (自動生成 wave 141):
OP15-031 / OP15-032 / OP15-033 / OP15-034 / OP15-035 /
OP15-036 / OP15-037 / OP15-038 / OP15-039 / OP15-041 の 10 枚。

目的 (= test_backfill_auto_001〜140.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op15_wave141_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-031", "OP15-032", "OP15-033", "OP15-034", "OP15-035",
           "OP15-036", "OP15-037", "OP15-038", "OP15-039", "OP15-041"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-031 プリンプリン (CHARACTER 緑 cost2 power2000):
#    【登場時】相手のレストのキャラ1枚までを選ぶ。選んだキャラのコストが
#      そのキャラに付与されているドン‼の枚数と同じ場合、KOする。
# --------------------------------------------------------------------------- #
def test_op15_031_on_play_ko_don_eq_cost_ai():
    """コスト == 付与ドン枚数 のレスト相手キャラをKO (AI 自動)。cost1 + ドン1枚 → KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    oc.rested = True
    oc.attached_dons = 1  # cost1 == ドン1 → KO 対象
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-031", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-031"), sickness=True))
    _drain(st, [0])
    assert oc not in opp.characters, \
        "コスト == 付与ドン枚数 のレスト相手キャラがKOされていない"


def test_op15_031_on_play_don_ne_cost_survives():
    """コスト != 付与ドン枚数 なら KO されない (cost1 + ドン0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    oc.rested = True
    oc.attached_dons = 0  # cost1 != ドン0 → 対象外
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-031", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-031"), sickness=True))
    _drain(st, [0])
    assert oc in opp.characters, \
        "コスト != 付与ドン枚数 の相手キャラをKOしてはいけない (対象外)"


def test_op15_031_on_play_human_pick():
    """人間 + 対象複数 → target_pick modal が立ち resolve で選んだ1枚のみKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    a.rested = True
    a.attached_dons = 1
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b.rested = True
    b.attached_dons = 1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP15-031", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-031"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP15-032 ブルック (CHARACTER 緑 cost6 power6000):
#    【登場時】相手のカード1枚までを、レストにする。
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のリーダーが
#      特徴《麦わらの一味》を持つ場合、自分の元々のコスト8以下のキャラ1枚までを、
#      アクティブにする。
# --------------------------------------------------------------------------- #
def test_op15_032_on_play_rest_opp_any_ai():
    """【登場時】相手のカード1枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-032", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-032"), sickness=True))
    _drain(st, [0])
    assert oc.rested is True, "登場時に相手キャラがレストにされていない"


def test_op15_032_activate_trash_self_then_untap_ai():
    """起動メイン: このキャラをトラッシュ (コスト) → 麦わらの一味リーダーで
    自軍キャラ1枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB02-010", overlay)  # モンキー・D・ルフィ (麦わらの一味)
    me, opp = st.players[0], st.players[1]
    bruk = InPlay.of(repo.get("OP15-032"), sickness=False)
    ally = InPlay.of(repo.get("OP01-016"), sickness=False)
    ally.rested = True
    me.characters = [bruk, ally]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-032"]
    assert len(opts) == 1, \
        f"OP15-032 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert bruk not in me.characters, "コストで ブルック がトラッシュに置かれるべき"
    assert any(c.card_id == "OP15-032" for c in me.trash), \
        "ブルック がトラッシュに送られていない"
    assert ally.rested is False, "自軍のコスト8以下キャラがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP15-033 ホーディ・ジョーンズ (CHARACTER 緑 cost4 power5000):
#    【登場時】自分の特徴《魚人族》を持つリーダーを、アクティブにする。
#      その後、自分のライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op15_033_on_play_untap_leader_and_life_to_hand_ai():
    """《魚人族》リーダーで 自リーダーをアクティブに + ライフ1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay)  # ジンベエ (魚人族)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True
    me.life = [repo.get("OP01-016"), repo.get("OP01-013")]
    me.hand = []

    do, eff = _do(overlay, "OP15-033", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "《魚人族》リーダーで登場時条件が成立していない"
    life_before = len(me.life)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-033"), sickness=True))
    _drain(st, [0])
    assert me.leader.rested is False, "自リーダーがアクティブになっていない"
    assert len(me.hand) == 1, "ライフ1枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "ライフが1枚減っていない"


def test_op15_033_condition_false_non_fishman_leader():
    """非《魚人族》リーダーでは 登場時条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (魚人族でない)
    me = st.players[0]
    _, eff = _do(overlay, "OP15-033", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "非《魚人族》リーダーで登場時条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP15-034 ヨーキ (CHARACTER 緑 cost1):
#    【自分のターン中】【登場時】自分の「ブルック」1枚までを、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op15_034_on_play_pump_brook_ai():
    """【登場時】自分の「ブルック」1枚を このターン中 +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bruk = InPlay.of(repo.get("EB02-048"), sickness=False)  # ブルック power6000
    me.characters = [bruk]

    do, eff = _do(overlay, "OP15-034", "on_play")
    assert eff.get("conditions") == [{"self_turn": True}], \
        "overlay の【自分のターン中】条件 (self_turn) が無い"
    power_before = bruk.power
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-034"), sickness=True))
    _drain(st, [0])
    assert bruk.power == power_before + 2000, \
        f"「ブルック」への +2000 が反映されていない: {bruk.power} (before {power_before})"


def test_op15_034_on_play_human_pick():
    """人間 + 「ブルック」複数 → target_pick modal が立ち resolve で選んだ1枚に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("EB02-048"), sickness=False)  # ブルック
    b = InPlay.of(repo.get("EB02-048"), sickness=False)  # ブルック
    me.characters = [a, b]

    do, _ = _do(overlay, "OP15-034", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-034"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ブルック2体) が 2 件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.power == b_before + 2000, "人間が選んだ「ブルック」に +2000 が反映されていない"
    assert a.power == repo.get("EB02-048").power, "選ばなかった「ブルック」は素のパワーのままであるべき"


# --------------------------------------------------------------------------- #
#  OP15-035 ラブーン (CHARACTER 緑 cost1 power2000):
#    自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、
#      代わりに自分のカード2枚をレストにできる。 (replace_leave / 任意)
# --------------------------------------------------------------------------- #
def test_op15_035_replace_leave_rest_two_cards_ai():
    """元々P7000以下の自キャラが相手効果で離脱 → 代わりに自分のカード2枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    laboon = InPlay.of(repo.get("OP15-035"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 ≤ 7000
    me.characters = [laboon, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "元々P7000以下の自キャラ離脱が置換されていない"
    assert victim in me.characters, "置換成立時 victim は場に残るべき"
    rested = sum(1 for c in [me.leader] + me.characters if c.rested)
    assert rested == 2, f"置換コストで自分のカード2枚がレストされていない: rested={rested}"


def test_op15_035_replace_leave_power_over_7000_no_replace():
    """元々パワー7000超の自キャラは 対象外 → 置換されない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    laboon = InPlay.of(repo.get("OP15-035"), sickness=False)
    big = InPlay.of(repo.get("OP15-008"), sickness=False)  # power9000 (> 7000)
    me.characters = [laboon, big]

    replaced = try_replace_ko(
        st, me, opp, big, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "元々パワー7000超のキャラに置換が成立してはいけない (対象外)"


def test_op15_035_replace_leave_human_optional_confirm():
    """人間 actor: 任意 (optional) → replace_ko_optional modal が立ち halt する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    laboon = InPlay.of(repo.get("OP15-035"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [laboon, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_leave の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    _drain(st, [1])
    assert victim in me.characters, "人間承諾後 victim は場に残るべき"


# --------------------------------------------------------------------------- #
#  OP15-036 リューマ (CHARACTER 緑 cost6 power8000):
#    【登場時】/【アタック時】相手のレストのコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op15_036_on_play_ko_rested_cost_le_4_ai():
    """【登場時】相手のレストのコスト4以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 ≤ 4
    oc.rested = True
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-036", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-036"), sickness=True))
    _drain(st, [0])
    assert oc not in opp.characters, "登場時に相手のレストコスト4以下キャラがKOされていない"


def test_op15_036_on_attack_ko_rested_cost_le_4_ai():
    """【アタック時】相手のレストのコスト4以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)
    oc.rested = True
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-036", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-036"), sickness=False))
    _drain(st, [0])
    assert oc not in opp.characters, "アタック時に相手のレストコスト4以下キャラがKOされていない"


def test_op15_036_on_play_active_target_survives():
    """相手のコスト4以下キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)
    oc.rested = False  # アクティブ = 対象外
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-036", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-036"), sickness=True))
    _drain(st, [0])
    assert oc in opp.characters, "アクティブなキャラをKOしてはいけない (対象外)"


def test_op15_036_on_play_human_pick():
    """人間 + 対象複数 → target_pick modal が立ち resolve で選んだ1枚のみKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False); a.rested = True
    b = InPlay.of(repo.get("OP01-016"), sickness=False); b.rested = True
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP15-036", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-036"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP15-037 強ェ弱ェは結果が決めるのさ (EVENT 緑 cost1):
#    【メイン】自分のデッキの上から5枚を見て、「強ェ弱ェは結果が決めるのさ」以外の
#      特徴《東の海》を持つカード1枚までを公開し、手札に加える。残りをデッキの下に置く。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op15_037_main_search_east_blue_ai():
    """メイン: デッキ上5枚から《東の海》カード1枚を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tgt = repo.get("EB02-011")  # アーロン (東の海)
    assert "東の海" in (tgt.features or ""), "テスト前提: EB02-011 は 東の海"
    me.deck = [tgt] + [repo.get("OP01-016")] * 10  # 上5枚に該当カードを仕込む
    me.hand = []

    do, _ = _do(overlay, "OP15-037", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == "EB02-011" for c in me.hand), \
        "デッキ上5枚から《東の海》カードが手札に加わっていない"


def test_op15_037_trigger_draw_ai():
    """【トリガー】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 5

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP15-037", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, "トリガーで1枚引けていない"


def test_op15_037_main_search_human_pick():
    """人間 + 上5枚に《東の海》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    tgt = repo.get("EB02-011")
    me.deck = [tgt, repo.get("OP01-016"), tgt] + [repo.get("OP01-016")] * 10
    me.hand = []

    do, _ = _do(overlay, "OP15-037", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (アーロン) を選択
    _drain(st, [])
    assert any(c.card_id == "EB02-011" for c in me.hand), \
        "人間が選んだ《東の海》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP15-038 命令してるんだ 誰もおれに逆らうな!!! (EVENT 緑 cost1):
#    【メイン】相手のドン‼が2枚以上付与されているレストのコスト8以下のキャラ1枚までは、
#      次の相手のリフレッシュフェイズでアクティブにならない。
#    【カウンター】自分の「クリーク」1枚までを、このバトル中、パワー+4000。
# --------------------------------------------------------------------------- #
def test_op15_038_main_keep_opp_rested_next_refresh_ai():
    """メイン: 相手のドン2枚以上付与レストcost8以下キャラを 次リフレッシュで
    アクティブにさせない (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 ≤ 8
    oc.rested = True
    oc.attached_dons = 2  # ドン2枚以上 → 対象化
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-038", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert oc.stay_rested_next_refresh is True, \
        "対象キャラが 次のリフレッシュでアクティブにならない設定になっていない"


def test_op15_038_main_don_lt_2_not_kept():
    """付与ドンが2枚未満の相手キャラは 対象外 (= フラグが立たない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)
    oc.rested = True
    oc.attached_dons = 1  # ドン1枚 = 対象外
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-038", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert oc.stay_rested_next_refresh is False, \
        "付与ドン2枚未満の相手キャラを対象にしてはいけない"


def test_op15_038_counter_pump_krieg_ai():
    """【カウンター】自分の「クリーク」1枚を このバトル中 +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kr = InPlay.of(repo.get("OP01-066"), sickness=False)  # クリーク power6000
    me.characters = [kr]

    power_before = kr.power
    do, _ = _do(overlay, "OP15-038", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert kr.power == power_before + 4000, \
        f"「クリーク」への +4000 が反映されていない: {kr.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP15-039 レベッカ (LEADER 青 power5000):
#    このリーダーはアタックできない。
#    【起動メイン】このリーダーをレストにし、自分の特徴《ドレスローザ》を持つキャラ1枚を
#      持ち主の手札に戻すことができる：自分の手札からコスト3の特徴《ドレスローザ》を持つ
#      キャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op15_039_activate_return_then_play_dressrosa_ai():
    """起動メイン: 自リーダーをレスト + 自ドレスローザキャラを手札に戻す (コスト) →
    手札からコスト3ドレスローザキャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay)
    me, opp = st.players[0], st.players[1]
    on_board = InPlay.of(repo.get("EB03-048"), sickness=False)  # レベッカ (ドレスローザ)
    me.characters = [on_board]
    me.hand = [repo.get("OP15-044")]  # コアラ cost3 ドレスローザ

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-039"]
    assert len(opts) == 1, \
        f"OP15-039 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert me.leader.rested is True, "コストで自リーダーがレストされるべき"
    assert any(c.card_id == "EB03-048" for c in me.hand), \
        "コストで自ドレスローザキャラが手札に戻されていない"
    assert any(c.card.card_id == "OP15-044" for c in me.characters), \
        "手札からコスト3ドレスローザキャラが登場していない"


def test_op15_039_activate_once_per_turn():
    """起動メインは【ターン1回】相当 (自リーダーをレストにする)。一度使うと再度は legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("EB03-048"), sickness=False)]
    me.hand = [repo.get("OP15-044")]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP15-039"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP15-039"]
    assert len(opts2) == 0, \
        "自リーダーがレスト済 (once_per_turn) なら 起動メインは再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP15-041 オオロンブス (CHARACTER 青 cost3 power4000):
#    【KO時】カード1枚を引く。
#    【起動メイン】【ターン1回】自分のキャラ1枚を持ち主のデッキの下に置くことができる：
#      このキャラは、このターン中、【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op15_041_on_ko_draw_ai():
    """【KO時】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 5

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP15-041", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-041"), sickness=False))
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, "KO時に1枚引けていない"


def test_op15_041_activate_return_chara_then_rush_ai():
    """起動メイン: 自分のキャラ1枚をデッキ下に置く (コスト) → このキャラは【速攻】を得る
    (= summoning_sickness 解除、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oor = InPlay.of(repo.get("OP15-041"), sickness=True)  # まだ召喚酔い
    fodder = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [oor, fodder]
    deck_before = len(me.deck)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-041"]
    assert len(opts) == 1, \
        f"OP15-041 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert oor in me.characters, "起動元 (オオロンブス) は場に残るべき"
    assert oor.summoning_sickness is False, \
        "コスト支払い後【速攻】(召喚酔い解除) が付与されていない"
    assert len(me.deck) == deck_before + 1, \
        "コストで自キャラ1枚がデッキの下に置かれていない"


def test_op15_041_activate_human_optional_confirm():
    """人間 actor: 起動メインは 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    oor = InPlay.of(repo.get("OP15-041"), sickness=True)
    fodder = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [oor, fodder]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-041"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    # 承諾して drain (= コスト対象選択 → 速攻付与 まで流す)
    resolve_pending_choice(st, [1])
    _drain(st, [0])
    assert oor.summoning_sickness is False, \
        "人間承諾後【速攻】(召喚酔い解除) が付与されていない"
