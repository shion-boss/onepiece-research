# -*- coding: utf-8 -*-
"""OP03 弾 (緑 東の海 / クロネコ海賊団 / アーロン一味) 効果 回帰テスト
バックフィル (自動生成 wave 037):
OP03-026 / OP03-027 / OP03-028 / OP03-029 / OP03-030 / OP03-032 /
OP03-033 / OP03-034 / OP03-036 / OP03-037 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
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


def _get_eff(overlay, cid, when, needle=None):
    for e in overlay.get(cid).effects:
        if e["when"] == when and (needle is None or needle in str(e["do"])):
            return e
    raise KeyError(cid, when, needle)


def _drain(st, sel=None, guard=8):
    """pending_choice を sel (既定 [0]) で解決し続ける (人間チェーン用)。"""
    if sel is None:
        sel = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, sel)
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op03_wave37_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-026", "OP03-027", "OP03-028", "OP03-029", "OP03-030",
           "OP03-032", "OP03-033", "OP03-034", "OP03-036", "OP03-037"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-026 クロオビ: 【登場時】自リーダーが特徴《東の海》を持つ場合、
#    相手のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op03_026_kurobi_on_play_rest_opp_ai():
    """【登場時】(東の海リーダー) 相手キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)  # クロ = 東の海 リーダー
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-026", "on_play", "rest")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-026"), sickness=True))
    assert victim.rested is True, "登場時に相手キャラがレストされていない"


def test_op03_026_kurobi_on_play_rest_human_pick():
    """人間 + 相手キャラ複数 → rest の target_pick modal が立ち resolve で 1 体をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-026", "on_play", "rest")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-026"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかった相手キャラはレストされない"


# --------------------------------------------------------------------------- #
#  OP03-027 シャム: 【登場時】(東の海リーダー) 相手のコスト2以下キャラ1枚までを
#    レストにし、 自分の「ブチ」がいない場合、 手札から「ブチ」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op03_027_sham_on_play_rest_cost_le2_ai():
    """【登場時】(第1効果) 相手のコスト2以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)  # 東の海 リーダー
    me, opp = st.players[0], st.players[1]
    lo = InPlay.of(repo.get("OP01-013"), sickness=False)   # サンジ cost2 (<=2)
    hi = InPlay.of(repo.get("OP01-005"), sickness=False)    # ウタ cost4 (対象外)
    opp.characters = [lo, hi]

    rest_eff = _get_eff(overlay, "OP03-027", "on_play", "rest")
    for prim in rest_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-027"), sickness=True))
    assert lo.rested is True, "相手のコスト2以下キャラがレストされていない"
    assert hi.rested is False, "コスト3以上の相手キャラはレストされない"


def test_op03_027_sham_on_play_play_buchi_ai():
    """【登場時】(第2効果) 自分にブチが居ない → 手札からブチを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP03-034")]  # ブチ

    play_eff = _get_eff(overlay, "OP03-027", "on_play", "play_from_hand")
    chars_before = len(me.characters)
    for prim in play_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-027"), sickness=True))
    assert any(c.card.card_id == "OP03-034" for c in me.characters), \
        "手札からブチが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"


def test_op03_027_sham_on_play_play_buchi_human_pick():
    """人間 + 手札にブチ複数 → play_from_hand modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP03-034"), repo.get("OP03-034")]  # ブチ 2 枚

    play_eff = _get_eff(overlay, "OP03-027", "on_play", "play_from_hand")
    execute_effect(play_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-027"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id == "OP03-034" for c in me.characters), \
        "人間が選んだブチが登場していない"


# --------------------------------------------------------------------------- #
#  OP03-028 ジャンゴ: 【登場時】以下から1つを選ぶ。
#    ・自分の特徴《東の海》を持つ、リーダーかコスト6以下のキャラ1枚までを、アクティブにする。
#    ・このキャラと相手のキャラ1枚までを、レストにする。 (choice_effect)
# --------------------------------------------------------------------------- #
def test_op03_028_jango_on_play_choice_untap_ai():
    """AI: 登場時 choice_effect → 1 つ目 (東の海キャラを untap) を自動発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 非東の海リーダー → 対象は東の海キャラのみ
    me, opp = st.players[0], st.players[1]
    arlong = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 東の海 cost3
    arlong.rested = True  # untap 対象
    me.characters = [arlong]

    on_play = _get_eff(overlay, "OP03-028", "on_play", "choice_effect")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-028"), sickness=True))
    assert arlong.rested is False, \
        "choice_effect の第1効果 (東の海キャラ untap) が反映されていない"


def test_op03_028_jango_on_play_choice_human_option_pick():
    """人間: 登場時 → option_pick modal が 2 択で立ち、 option を選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay, human_idx=0)  # クロ 東の海リーダー
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True  # untap 対象 (東の海リーダー)
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]

    on_play = _get_eff(overlay, "OP03-028", "on_play", "choice_effect")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-028"), sickness=True))

    assert st.pending_choice is not None, "人間 choice で modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("options", [])) == 2, \
        f"2 択の option が立っていない: {st.pending_choice.get('options')}"
    resolve_pending_choice(st, [0])  # 1 つ目 (untap) を選ぶ
    _drain(st, [0])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert me.leader.rested is False, "人間が選んだ第1効果 (リーダー untap) が解決していない"


# --------------------------------------------------------------------------- #
#  OP03-029 チュウ: 【登場時】相手のレストのコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op03_029_chuu_on_play_ko_rested_cost_le4_ai():
    """【登場時】相手のレストのコスト4以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4 (<=4)
    victim.rested = True
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-029", "on_play", "ko")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-029"), sickness=True))
    assert victim not in opp.characters, "相手のレストコスト4以下キャラが KO されていない"


def test_op03_029_chuu_on_play_no_active_target():
    """相手キャラがアクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # cost4 active
    victim.rested = False
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-029", "on_play", "ko")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-029"), sickness=True))
    assert victim in opp.characters, "アクティブなキャラを KO してはいけない (対象外)"


def test_op03_029_chuu_on_play_ko_human_pick():
    """人間 + 相手のレストコスト4以下複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-029", "on_play", "ko")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-029"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP03-030 ナミ: 【登場時】自分のデッキの上から5枚を見て、「ナミ」以外の緑の
#    特徴《東の海》を持つカード1枚までを公開し、手札に加える。 その後、残りをデッキ下。
# --------------------------------------------------------------------------- #
def test_op03_030_nami_on_play_search_ai():
    """【登場時】上5枚から 緑・東の海 (ナミ以外) を1枚手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    buchi = repo.get("OP03-034")  # ブチ 緑 東の海 (ナミ以外)
    me.deck = [buchi] + [repo.get("OP01-013")] * 20  # OP01-013 サンジ = 赤 (対象外)
    me.hand = []

    on_play = _get_eff(overlay, "OP03-030", "on_play", "search_top_n")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-030"), sickness=True))
    assert any(c.card_id == "OP03-034" for c in me.hand), \
        "上5枚から 緑・東の海キャラが手札に加わっていない"


def test_op03_030_nami_on_play_search_human_pick():
    """人間 + 上5枚に 緑・東の海 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    buchi = repo.get("OP03-034")   # ブチ
    aarlong = repo.get("EB02-011")  # アーロン 緑 東の海
    me.deck = [buchi, repo.get("OP01-013"), aarlong] + [repo.get("OP01-013")] * 15
    me.hand = []

    on_play = _get_eff(overlay, "OP03-030", "on_play", "search_top_n")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-030"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id in ("OP03-034", "EB02-011") for c in me.hand), \
        "人間が選んだ 緑・東の海カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP03-032 バギー: このキャラは、属性(斬)を持つカードとのバトルでKOされない。
#    (静的、 on_attached_don n=0 = 常在)
# --------------------------------------------------------------------------- #
def test_op03_032_buggy_static_immune_attribute_zan():
    """静的効果: バギーは属性《斬》とのバトルで KO 免疫を得る
    (= ko_immune_battle_attributes_in に「斬」が入る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("OP03-032"), sickness=False)
    me.characters = [buggy]

    evaluate_static_effects(st, overlay)
    assert "斬" in buggy.ko_immune_battle_attributes_in, \
        f"属性《斬》のバトルKO免疫が付与されていない: {buggy.ko_immune_battle_attributes_in}"


# --------------------------------------------------------------------------- #
#  OP03-033 はっちゃん: 【トリガー】自リーダーが特徴《東の海》を持つ場合、
#    このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op03_033_hatchan_trigger_play_self_ai():
    """【トリガー】(東の海リーダー) このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)  # 東の海 リーダー
    me, opp = st.players[0], st.players[1]
    # トリガー発火 (= ライフ from) を模して 手札に置き source card id をスタック
    me.hand = [repo.get("OP03-033")]
    st.current_source_card_id = "OP03-033"

    chars_before = len(me.characters)
    trig = _get_eff(overlay, "OP03-033", "trigger", "play_self")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "OP03-033" for c in me.characters), \
        "トリガーで はっちゃん が登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"


# --------------------------------------------------------------------------- #
#  OP03-034 ブチ: 【登場時】相手のレストのコスト2以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op03_034_buchi_on_play_ko_rested_cost_le2_ai():
    """【登場時】相手のレストのコスト2以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=2)
    victim.rested = True
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-034", "on_play", "ko")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-034"), sickness=True))
    assert victim not in opp.characters, "相手のレストコスト2以下キャラが KO されていない"


def test_op03_034_buchi_on_play_cost3_not_ko():
    """相手のレストキャラがコスト3以上なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン cost3 (>2)
    victim.rested = True
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-034", "on_play", "ko")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-034"), sickness=True))
    assert victim in opp.characters, "コスト3の相手キャラを KO してはいけない (対象外)"


def test_op03_034_buchi_on_play_ko_human_pick():
    """人間 + 相手のレストコスト2以下複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-034", "on_play", "ko")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-034"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP03-036 杓死 (EVENT): 【メイン】自分の特徴《東の海》を持つキャラ1枚をレスト
#    にできる：自分の「クロ」1枚までを、アクティブにする。
#    【トリガー】相手のレストのコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op03_036_shakushi_main_untap_kuro_ai():
    """【メイン】東の海キャラ1枚レスト (コスト) → 自分のクロをアクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    cost_src = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 東の海 (active)
    kuro = InPlay.of(repo.get("OP04-023"), sickness=False)      # クロ (untap 対象)
    kuro.rested = True
    me.characters = [cost_src, kuro]

    main = _get_eff(overlay, "OP03-036", "main", "optional_cost_then")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-036"), sickness=True))
    assert cost_src.rested is True, "コストで東の海キャラがレストされていない"
    assert kuro.rested is False, "効果で自分のクロがアクティブになっていない"


def test_op03_036_shakushi_main_human_optional_cost():
    """人間: メイン → optional_cost_confirm modal → pay ([1]) で クロ untap が解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    cost_src = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 東の海
    kuro = InPlay.of(repo.get("OP04-023"), sickness=False)      # クロ
    kuro.rested = True
    me.characters = [cost_src, kuro]

    main = _get_eff(overlay, "OP03-036", "main", "optional_cost_then")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-036"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert cost_src.rested is True, "任意コスト承認後に 東の海キャラがレストされていない"
    assert kuro.rested is False, "任意コスト承認後に クロが untap されていない"


def test_op03_036_shakushi_trigger_ko_rested_cost_le3_ai():
    """【トリガー】相手のレストのコスト3以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("EB02-011"), sickness=False)  # cost3 (<=3)
    victim.rested = True
    opp.characters = [victim]

    trig = _get_eff(overlay, "OP03-036", "trigger", "ko")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-036"), sickness=True))
    assert victim not in opp.characters, "トリガーで相手のレストコスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP03-037 歯ガム (EVENT): 【メイン】自分の特徴《東の海》を持つキャラ1枚をレスト
#    にできる：相手のレストのコスト3以下のキャラ1枚までを、KOする。
#    【トリガー】自分の手札からコスト4以下の【トリガー】を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op03_037_hagamu_main_ko_rested_cost_le3_ai():
    """【メイン】東の海キャラ1枚レスト (コスト) → 相手のレストコスト3以下を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    cost_src = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 東の海 (active)
    me.characters = [cost_src]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=3)
    victim.rested = True
    opp.characters = [victim]

    main = _get_eff(overlay, "OP03-037", "main", "optional_cost_then")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-037"), sickness=True))
    assert cost_src.rested is True, "コストで東の海キャラがレストされていない"
    assert victim not in opp.characters, "効果で相手のレストコスト3以下キャラが KO されていない"


def test_op03_037_hagamu_main_human_optional_cost():
    """人間: メイン → optional_cost_confirm modal → pay ([1]) で コスト + KO が解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    cost_src = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 東の海
    me.characters = [cost_src]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    victim.rested = True
    opp.characters = [victim]

    main = _get_eff(overlay, "OP03-037", "main", "optional_cost_then")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-037"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert cost_src.rested is True, "任意コスト承認後に 東の海キャラがレストされていない"
    assert victim not in opp.characters, "任意コスト承認後に 相手キャラが KO されていない"


def test_op03_037_hagamu_trigger_play_trigger_body_ai():
    """【トリガー】手札からコスト4以下の【トリガー】持ちキャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    trigger_body = repo.get("OP13-014")  # ルージュ cost1 トリガー持ち
    me.hand = [trigger_body]

    chars_before = len(me.characters)
    trig = _get_eff(overlay, "OP03-037", "trigger", "play_from_hand")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-037"), sickness=True))
    assert any(c.card.card_id == "OP13-014" for c in me.characters), \
        "手札のコスト4以下トリガー持ちキャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"
