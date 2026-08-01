# -*- coding: utf-8 -*-
"""カード効果 回帰テスト バックフィル (自動生成 wave 166):
ST03-003 / ST03-004 / ST03-005 / ST03-007 / ST03-009 /
ST03-010 / ST03-014 / ST03-015 / ST03-016 / ST03-017 の 10 枚
(= ST03 青「王下七武海」スターターの効果カード群)。

目的 (= test_backfill_auto_001〜165.py と同一方針):
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
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"            # ナミ (cost1 power2000 麦わらの一味) フィラー / 相手キャラ
SANJI = "OP01-013"           # サンジ (cost2 power3000 麦わらの一味) フィラー
CROCO_LEADER = "ST03-001"    # クロコダイル (王下七武海/B・W LEADER 青)
ZORO_LEADER = "OP01-001"     # ロロノア・ゾロ (LEADER、 相手素材用)
JINBE = "PRB02-007"          # ジンベエ (cost4 王下七武海、 ST03-004 トラッシュ回収対象)
PACIFISTA = "ST03-012"       # パシフィスタ (cost4 青、 ST03-007 デッキ登場対象)


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


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果を返す。
    needle 指定時は do[0] に needle キーを含む効果を返す (複数 when 同名時の分離)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    if needle is not None:
        matches = [e for e in matches if needle in e["do"][0]]
        assert matches, f"{cid} の when={when} に do[0]={needle} の効果がない"
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
def test_all_wave166_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST03-003", "ST03-004", "ST03-005", "ST03-007", "ST03-009",
           "ST03-010", "ST03-014", "ST03-015", "ST03-016", "ST03-017"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST03-003 クロコダイル (CHARACTER 青 cost5 power6000):
#    【ブロッカー】【ドン!!×1】【ブロック時】コスト2以下のキャラ1枚までを、
#    持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_st03_003_croco_block_return_to_deck_bottom_ai():
    """【ブロック時】相手コスト2以下キャラ1枚を 持ち主デッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (= 対象)
    opp.characters = [victim]

    deck_before = len(opp.deck)
    eff = _eff(overlay, "ST03-003", "on_block")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-003"), sickness=False))
    _drain(st, [0])

    assert victim not in opp.characters, "コスト2以下キャラがデッキ下に送られていない"
    assert len(opp.deck) == deck_before + 1, \
        f"相手デッキ末尾に1枚戻っていない: {len(opp.deck)} (before {deck_before})"


def test_st03_003_croco_block_return_human_pick():
    """人間 + 相手コスト2以下キャラ 複数 → target_pick modal が立ち resolve でデッキ下。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(SANJI), sickness=False)  # cost2
    opp.characters = [a, b]

    eff = _eff(overlay, "ST03-003", "on_block")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST03-003"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラがデッキ下に送られていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST03-004 ゲッコー・モリア (CHARACTER 青 cost4 power5000):
#    【登場時】自分のトラッシュの「ゲッコー・モリア」以外のコスト4以下の特徴
#    《王下七武海》か《スリラーバーク海賊団》を持つキャラ1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_st03_004_moria_on_play_trash_to_hand_ai():
    """【登場時】自トラッシュから 王下七武海 コスト4以下キャラ (ジンベエ) を手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # 該当キャラ (ジンベエ 王下七武海 cost4) と 非該当 (サンジ) を トラッシュに
    me.trash = [repo.get(JINBE), repo.get(SANJI)]

    eff = _eff(overlay, "ST03-004", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-004"), sickness=True))

    assert any(c.card_id == JINBE for c in me.hand), \
        "王下七武海キャラ (ジンベエ) が手札に加わっていない"
    assert any(c.card_id == SANJI for c in me.trash), \
        "非該当カード (サンジ) はトラッシュに残るべき"


def test_st03_004_moria_on_play_no_valid_target():
    """トラッシュに該当キャラが無ければ 手札に何も加わらない (= 不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(SANJI)]  # 王下七武海/スリラーバーク でない → 対象外
    me.hand = []

    eff = _eff(overlay, "ST03-004", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-004"), sickness=True))

    assert len(me.hand) == 0, "該当キャラが無いのに手札が増えてはいけない"
    assert any(c.card_id == SANJI for c in me.trash), "非該当カードはトラッシュに残る"


# --------------------------------------------------------------------------- #
#  ST03-005 ジュラキュール・ミホーク (CHARACTER 青 cost4 power5000):
#    【ドン!!×1】【アタック時】カード2枚を引き、自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_st03_005_mihawk_attack_draw2_discard2_ai():
    """【アタック時】2 枚引き 2 枚捨てる (= net 手札±0 / デッキ-2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(SANJI)] * 3
    me.deck = [repo.get(NAMI)] * 10

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    eff = _eff(overlay, "ST03-005", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-005"), sickness=False))

    assert len(me.hand) == hand_before, \
        f"手札 net が ±0 でない (draw2/discard2): {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before - 2, \
        f"デッキが 2 枚減っていない: {len(me.deck)} (before {deck_before})"
    assert len(me.trash) == trash_before + 2, \
        f"トラッシュに 2 枚捨てられていない: {len(me.trash)} (before {trash_before})"


# --------------------------------------------------------------------------- #
#  ST03-007 戦桃丸 (CHARACTER 青 cost3 power4000):
#    【ドン!!×1】【起動メイン】【ターン1回】②：自分のデッキからコスト4以下の
#    「パシフィスタ」1枚までを、登場させ、デッキをシャッフルする。
# --------------------------------------------------------------------------- #
def test_st03_007_sentomaru_activate_main_summon_ai():
    """起動メイン: ドン2レスト (コスト) → デッキから パシフィスタ を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sento = InPlay.of(repo.get("ST03-007"), sickness=False)
    sento.attached_dons = 1              # 【ドン!!×1】ゲート成立
    me.characters = [sento]
    me.don_active = 2                    # ② (= rest_self_don 2) 支払い用
    me.deck = [repo.get(PACIFISTA)] + [repo.get(NAMI)] * 20

    options = list_activate_main_effects(st, me, overlay)
    sento_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "ST03-007"]
    assert len(sento_opts) == 1, \
        f"ST03-007 の起動メインが legal に出ない: {len(sento_opts)}"
    src, eff = sento_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert any(c.card.card_id == PACIFISTA for c in me.characters), \
        "デッキから パシフィスタ が登場していない"
    assert me.don_active == 0 and me.don_rested == 2, \
        f"② コストで アクティブドン2枚がレストされていない: active={me.don_active} rested={me.don_rested}"


def test_st03_007_sentomaru_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sento = InPlay.of(repo.get("ST03-007"), sickness=False)
    sento.attached_dons = 1
    me.characters = [sento]
    me.don_active = 4  # 2 回分の ② を払える (= once_per_turn の検証用)
    me.deck = [repo.get(PACIFISTA)] * 2 + [repo.get(NAMI)] * 20

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST03-007"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST03-007"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST03-009 ドンキホーテ・ドフラミンゴ (CHARACTER 青 cost7 power7000):
#    【登場時】コスト7以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_st03_009_doflamingo_on_play_bounce_ai():
    """【登場時】相手コスト7以下キャラ1枚を 持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (= 対象)
    opp.characters = [victim]

    hand_before = len(opp.hand)
    eff = _eff(overlay, "ST03-009", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-009"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手コスト7以下キャラが手札に戻されていない"
    assert len(opp.hand) == hand_before + 1, \
        f"相手の手札に1枚戻っていない: {len(opp.hand)} (before {hand_before})"


def test_st03_009_doflamingo_on_play_bounce_human_pick():
    """人間 + 相手キャラ 複数 → return_to_hand の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(SANJI), sickness=False)  # cost2
    opp.characters = [a, b]

    eff = _eff(overlay, "ST03-009", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST03-009"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが手札に戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST03-010 バーソロミュー・くま (CHARACTER 青 cost2 power3000):
#    【登場時】自分のデッキの上から3枚を見て、好きな順番に並び変え、
#    デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_st03_010_kuma_on_play_look_top_reorder_ai():
    """【登場時】デッキ上3枚を並び替えて上に戻す (overlay = コスト昇順 heuristic)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # 上3枚を コスト 2 / 1 / 4 の順に配置 → 並び替え後は 昇順 1,2,4 になる想定
    me.deck = [repo.get(SANJI), repo.get(NAMI), repo.get(PACIFISTA)] \
        + [repo.get(NAMI)] * 10
    deck_before = len(me.deck)

    eff = _eff(overlay, "ST03-010", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-010"), sickness=True))

    top3_costs = [me.deck[i].cost for i in range(3)]
    assert top3_costs == sorted(top3_costs), \
        f"デッキ上3枚がコスト昇順に並び替えられていない: {top3_costs}"
    assert len(me.deck) == deck_before, \
        f"デッキ枚数が変わってはいけない (見て並び替えるだけ): {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  ST03-014 マーシャル・D・ティーチ (CHARACTER 青 cost4 power4000):
#    【登場時】コスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_st03_014_teach_on_play_bounce_ai():
    """【登場時】相手コスト3以下キャラ1枚を 持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (= 対象)
    opp.characters = [victim]

    hand_before = len(opp.hand)
    eff = _eff(overlay, "ST03-014", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-014"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手コスト3以下キャラが手札に戻されていない"
    assert len(opp.hand) == hand_before + 1, "相手の手札に1枚戻っていない"


def test_st03_014_teach_on_play_excludes_high_cost():
    """相手キャラがコスト4以上なら対象外 → 戻されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    high = InPlay.of(repo.get(JINBE), sickness=False)  # cost4 = 対象外
    opp.characters = [high]

    eff = _eff(overlay, "ST03-014", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST03-014"), sickness=True))

    assert high in opp.characters, "コスト4キャラ (対象外) が戻されてはいけない"


# --------------------------------------------------------------------------- #
#  ST03-015 砂嵐 (EVENT 青 cost4):
#    【メイン】コスト7以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_st03_015_sunastorm_main_bounce_ai():
    """【メイン】相手コスト7以下キャラ1枚を 持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)
    opp.characters = [victim]

    hand_before = len(opp.hand)
    eff = _eff(overlay, "ST03-015", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim not in opp.characters, "相手キャラが手札に戻されていない"
    assert len(opp.hand) == hand_before + 1, "相手の手札に1枚戻っていない"


def test_st03_015_sunastorm_main_bounce_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で 1 枚 バウンス。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)
    b = InPlay.of(repo.get(SANJI), sickness=False)
    opp.characters = [a, b]

    eff = _eff(overlay, "ST03-015", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが手札に戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST03-016 つっぱり圧力砲 (EVENT 青 cost2):
#    【カウンター】コスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_st03_016_pressure_cannon_counter_bounce_ai():
    """【カウンター】相手コスト3以下キャラ1枚を 持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay, turn=1)  # 相手ターン (= カウンター文脈)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (= 対象)
    opp.characters = [victim]

    hand_before = len(opp.hand)
    eff = _eff(overlay, "ST03-016", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim not in opp.characters, "相手コスト3以下キャラが手札に戻されていない"
    assert len(opp.hand) == hand_before + 1, "相手の手札に1枚戻っていない"


def test_st03_016_pressure_cannon_counter_bounce_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で 1 枚 バウンス。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay, human_idx=0, turn=1)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(SANJI), sickness=False)  # cost2
    opp.characters = [a, b]

    eff = _eff(overlay, "ST03-016", "counter")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが手札に戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST03-017 メロメロ甘風 (EVENT 青 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
#    その後、自分の手札が3枚以下の場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_st03_017_meromero_counter_pump_ai():
    """【カウンター】(1) 自リーダー +4000 このバトル中 (overlay = self_inplay → リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay, turn=1)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST03-017", "counter", needle="power_pump")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power} (before {power_before})"


def test_st03_017_meromero_counter_draw_when_hand_le_3():
    """【カウンター】(2) 自分の手札が3枚以下なら 1 ドロー (条件成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, CROCO_LEADER, overlay, turn=1)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(SANJI)] * 2   # 3 枚以下 (= 条件成立)
    me.deck = [repo.get(NAMI)] * 5

    hand_before = len(me.hand)
    draw_eff = _eff(overlay, "ST03-017", "counter", needle="draw")
    assert draw_eff.get("if", {}).get("self_hand_count_le") == 3, \
        "overlay の ドロー条件 self_hand_count_le=3 が無い"
    for prim in draw_eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, \
        f"手札3枚以下で 1 ドローされていない: {len(me.hand)} (before {hand_before})"
