# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 160):
P-072 / P-073 / P-074 / P-075 / P-076 /
P-077 / P-078 / P-079 / P-083 / P-084 の 10 枚。

目的 (= test_backfill_auto_001〜159.py と同一方針):
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
    eval_condition,
    evaluate_static_effects,
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
NAMI = "OP01-016"            # ナミ (cost1 power2000) フィラー / 相手キャラ (cost1)
COST2 = "OP01-013"           # サンジ (cost2 power3000) フィラー
COST3 = "P-048"              # アーロン (cost3 power4000) 中コスト (= cost3 対象)
COST4 = "OP11-015"           # モチャ (cost4 power6000) 中コスト (= cost4 対象)
BIG = "OP02-004"             # エドワード・ニューゲート (cost9 power10000) 高コスト
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (LEADER)
BAGGY_LEADER = "OP09-042"    # バギー (青 LEADER) = leader_name 条件用
ODY1 = "OP10-033"            # ナミ (ODYSSEY cost2 power2000) = レスト ODYSSEY フィラー
ODY2 = "OP09-030"            # トラファルガー・ロー (ODYSSEY cost3 power4000)
PURPLE_STAGE = "OP09-080"    # サウザンド・サニー号 (紫 STAGE)
CROSSGUILD = "OP09-056"      # Mr.3(ギャルディーノ) (クロスギルド cost1 power2000)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(COST2)] * 30
    p1.deck = [repo.get(COST2)] * 30
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
def test_all_wave160_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-072", "P-073", "P-074", "P-075", "P-076",
           "P-077", "P-078", "P-079", "P-083", "P-084"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-072 リューマ (CHARACTER):
#    【登場時】/【KO時】相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_p072_ryuma_on_play_rest_cost4_ai():
    """【登場時】 AI: 相手コスト4以下キャラ1枚をレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST4), sickness=False)  # cost4 (= 対象)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-072", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-072"), sickness=True))
    _drain(st, [0])

    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"


def test_p072_ryuma_on_ko_rest_cost4_ai():
    """【KO時】 AI: 相手コスト4以下キャラ1枚をレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-072", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-072"), sickness=False))
    _drain(st, [0])

    assert victim.rested is True, "KO時に相手コスト4以下キャラがレストされていない"


def test_p072_ryuma_on_play_high_cost_survives():
    """相手キャラが コスト4超のみなら 対象外 → レストされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tough = InPlay.of(repo.get(BIG), sickness=False)  # cost9 (= 対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-072", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-072"), sickness=True))
    _drain(st, [0])

    assert tough.rested is False, "コスト4超のキャラがレストされてはいけない (対象外)"


def test_p072_ryuma_on_play_human_rest_pick():
    """人間 + 相手のコスト4以下 複数 → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(COST3), sickness=False)  # cost3
    b = InPlay.of(repo.get(COST4), sickness=False)  # cost4
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-072", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-072"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  P-073 サボ (CHARACTER):
#    【起動メイン】【ターン1回】自分のライフの上か下から1枚を手札に加えることが
#    できる：このキャラは、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_p073_sabo_activate_main_life_to_hand_pump_ai():
    """起動メイン: ライフ1枚を手札 (任意コスト) → 自身+1000。 AI 自動発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("P-073"), sickness=False)  # power 5000
    me.characters = [sabo]
    me.life = [repo.get(COST2)] * 2
    me.hand = []

    power_before = sabo.power
    life_before = len(me.life)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-073"]
    assert len(opts) == 1, f"P-073 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert sabo.power == power_before + 1000, \
        f"自身 +1000 が反映されていない: {sabo.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "ライフ1枚が手札コストで消費されていない (life -1)"
    assert len(me.hand) == 1, "ライフ1枚が手札に加わっていない"


def test_p073_sabo_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("P-073"), sickness=False)
    me.characters = [sabo]
    me.life = [repo.get(COST2)] * 2
    me.hand = []

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-073"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-073"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  P-074 ポートガス・D・エース (CHARACTER):
#    【起動メイン】このキャラを持ち主の手札に戻すことができる：自分のデッキの上から
#    5枚を見て、好きな順番に並び替え、デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_p074_ace_activate_main_return_self_reorder_ai():
    """起動メイン: 自身を手札に戻す (コスト) → デッキ上5枚を コスト昇順に並び替え。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("P-074"), sickness=False)
    me.characters = [ace]
    me.hand = []
    # 上5枚を コスト バラバラ (9,1,4,2,3) に仕込む → 昇順 (1,2,3,4,9) を期待
    top5 = [repo.get(BIG), repo.get(NAMI), repo.get(COST4),
            repo.get(COST2), repo.get(COST3)]
    me.deck = list(top5) + [repo.get(COST2)] * 15
    deck_before = len(me.deck)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-074"]
    assert len(opts) == 1, f"P-074 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert ace not in me.characters, "コストで P-074 が場から戻るべき"
    assert any(c.card_id == "P-074" for c in me.hand), \
        "コストで P-074 が持ち主の手札に戻っていない"
    assert len(me.deck) == deck_before, \
        "look_top_reorder はデッキ枚数を変えてはいけない (見て並べ替えるだけ)"
    costs = [c.cost for c in me.deck[:5]]
    assert costs == sorted(costs), \
        f"デッキ上5枚が コスト昇順に並び替わっていない: {costs}"


# --------------------------------------------------------------------------- #
#  P-075 モンキー・D・ルフィ (CHARACTER):
#    【登場時】自分のリーダーかキャラ1枚にレストのドン!!1枚までを、付与する。
#    【アタック時】自分の場にコスト8以上のキャラがいる場合、カード1枚を引き、
#    自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_p075_luffy_on_play_attach_rested_don_ai():
    """【登場時】 AI: 自リーダー(既定)にレストのドン1枚を付与する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2  # レストドン供給源

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _eff(overlay, "P-075", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-075"), sickness=True))
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 1, \
        "登場時に自リーダーへレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_p075_luffy_on_attack_draw_discard_when_cost8_ai():
    """【アタック時】(自場にコスト8以上キャラ有) → 1ドロー + 手札1捨て。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("P-075"), sickness=False)
    big = InPlay.of(repo.get(BIG), sickness=False)  # cost9 (= 条件成立)
    me.characters = [luffy, big]
    me.hand = [repo.get(COST2)]
    me.deck = [repo.get(COST2)] * 10
    me.trash = []

    eff = _eff(overlay, "P-075", "on_attack")
    assert eval_condition(eff["if"], st, me, luffy) is True, \
        "自場にコスト8以上キャラ有 で条件が成立していない"

    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, luffy)
    _drain(st, [0])

    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert len(me.trash) == 1, "手札1枚が捨てられてトラッシュに移っていない"
    # 手札 net: 元1 + ドロー1 - 捨て1 = 1
    assert len(me.hand) == 1, f"手札 net (ドロー+1 捨て-1) が合わない: {len(me.hand)}"


def test_p075_luffy_on_attack_condition_false_no_cost8():
    """自場にコスト8以上キャラが居なければ 条件不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("P-075"), sickness=False)
    small = InPlay.of(repo.get(COST3), sickness=False)  # cost3 (= 対象外)
    me.characters = [luffy, small]

    eff = _eff(overlay, "P-075", "on_attack")
    assert eval_condition(eff["if"], st, me, luffy) is False, \
        "コスト8以上キャラ不在で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-076 サカズキ (LEADER):
#    【起動メイン】【ターン1回】自分の手札から特徴《海軍》を持つカード1枚を捨てる
#    ことができる：相手のキャラ1枚までを、このターン中、コスト-1。
# --------------------------------------------------------------------------- #
def test_p076_sakazuki_activate_main_cost_minus_ai():
    """起動メイン: 相手キャラ1枚を このターン中 コスト-1。 AI 自動発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "P-076", overlay)  # リーダー = サカズキ
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST4), sickness=False)  # cost4
    opp.characters = [victim]

    cost_before = victim.base_cost
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-076"]
    assert len(opts) == 1, f"P-076 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert victim.cost_minus_until_turn_end == 1, \
        f"相手キャラに コスト-1 が乗っていない: {victim.cost_minus_until_turn_end}"
    assert victim.base_cost == cost_before - 1, \
        f"相手キャラの実効コストが -1 されていない: {victim.base_cost} (before {cost_before})"


def test_p076_sakazuki_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "P-076", overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(COST4), sickness=False)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-076"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-076"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  P-077 うるティ (CHARACTER):
#    【ターン1回】自分の場のドン‼が2枚以上ドン‼デッキに戻された時、ドン‼デッキから
#    ドン‼1枚までを、レストで追加する。その後、自分の紫のステージ1枚までを
#    アクティブにする。
# --------------------------------------------------------------------------- #
def test_p077_ulti_add_rested_don_untap_purple_stage_ai():
    """効果 do: レストドン+1 追加 → 自紫ステージ1枚をアクティブに。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get(PURPLE_STAGE), sickness=False)  # 紫 STAGE
    stage.rested = True
    me.stages = [stage]
    me.don_rested = 0
    me.don_remaining_in_deck = 5

    eff = _eff(overlay, "P-077", "on_self_don_returned_to_deck")
    assert eff.get("if", {}).get("returned_don_count_ge") == 2, \
        "overlay の 条件 returned_don_count_ge=2 が無い"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-077"), sickness=False))
    _drain(st, [0])

    assert me.don_rested == 1, f"レストドンが1枚追加されていない: {me.don_rested}"
    assert stage.rested is False, "自紫ステージがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  P-078 アディオ (CHARACTER):
#    自分のレストの特徴《ODYSSEY》を持つキャラが2枚以上いる場合、
#    このキャラのパワー+1000。
# --------------------------------------------------------------------------- #
def test_p078_adio_static_pump_when_two_rested_odyssey():
    """静的 (レスト ODYSSEY 2枚以上): このキャラ +1000。 evaluate_static_effects で検証。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    adio_def = repo.get("P-078")  # ODYSSEY power 5000
    adio = InPlay.of(adio_def, sickness=False)  # 条件カウント用でなく pump 対象 (active)
    ody1 = InPlay.of(repo.get(ODY1), sickness=False)  # ODYSSEY
    ody2 = InPlay.of(repo.get(ODY2), sickness=False)  # ODYSSEY
    ody1.rested = True
    ody2.rested = True
    me.characters = [adio, ody1, ody2]

    evaluate_static_effects(st, overlay)
    assert adio.power == adio_def.power + 1000, \
        f"レスト ODYSSEY 2枚以上で +1000 が乗っていない: {adio.power} (base {adio_def.power})"


def test_p078_adio_static_no_pump_when_one_rested():
    """レスト ODYSSEY が1枚のみなら 条件不成立 → +1000 なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    adio_def = repo.get("P-078")
    adio = InPlay.of(adio_def, sickness=False)
    ody1 = InPlay.of(repo.get(ODY1), sickness=False)
    ody1.rested = True  # レスト ODYSSEY 1枚のみ
    me.characters = [adio, ody1]

    evaluate_static_effects(st, overlay)
    assert adio.power == adio_def.power, \
        f"レスト ODYSSEY 1枚で効果 pump が乗ってはいけない: {adio.power}"


# --------------------------------------------------------------------------- #
#  P-079 リム (CHARACTER):
#    【ブロッカー】【自分のターン終了時】自分のレストの特徴《ODYSSEY》を持つキャラが
#    2枚以上いる場合、このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_p079_rim_end_of_turn_untap_when_two_rested_odyssey_ai():
    """自ターン終了時 (レスト ODYSSEY 2枚以上): このキャラをアクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rim = InPlay.of(repo.get("P-079"), sickness=False)  # ODYSSEY (rested)
    rim.rested = True
    ody = InPlay.of(repo.get(ODY1), sickness=False)  # ODYSSEY (rested)
    ody.rested = True
    me.characters = [rim, ody]  # レスト ODYSSEY = rim + ody = 2 枚 (= 条件成立)

    eff = _eff(overlay, "P-079", "end_of_turn")
    assert eval_condition(eff["if"], st, me, rim) is True, \
        "レスト ODYSSEY 2枚以上 で条件が成立していない"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, rim)
    assert rim.rested is False, "自ターン終了時に このキャラがアクティブになっていない"


def test_p079_rim_end_of_turn_condition_false_one_rested():
    """レスト ODYSSEY が1枚のみなら 条件不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rim = InPlay.of(repo.get("P-079"), sickness=False)
    rim.rested = True  # レスト ODYSSEY = rim のみ = 1 枚
    me.characters = [rim]

    eff = _eff(overlay, "P-079", "end_of_turn")
    assert eval_condition(eff["if"], st, me, rim) is False, \
        "レスト ODYSSEY 1枚で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-083 シャンクス (CHARACTER):
#    【ドン!!×1】【アタック時】自分の手札からキャラカード1枚を捨てることができる：
#    相手のキャラ1枚までを、このターン中、パワー-1000。その後、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_p083_shanks_on_attack_discard_debuff_draw_ai():
    """【アタック時】(ドン1ゲート) 手札キャラ1捨て → 相手キャラ-1000 + 1ドロー。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shanks = InPlay.of(repo.get("P-083"), sickness=False)
    shanks.attached_dons = 1  # ドンゲート成立
    me.characters = [shanks]
    me.hand = [repo.get(COST2)]  # 捨てる CHARACTER コスト用
    me.deck = [repo.get(COST2)] * 10
    me.trash = []
    victim = InPlay.of(repo.get(COST4), sickness=False)  # power 6000
    opp.characters = [victim]

    eff = _eff(overlay, "P-083", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"

    power_before = victim.power
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, shanks)
    _drain(st, [0])

    assert victim.power == power_before - 1000, \
        f"相手キャラ -1000 が反映されていない: {victim.power} (before {power_before})"
    assert len(me.deck) == deck_before - 1, "その後の1ドローが起きていない"
    assert len(me.trash) == 1, "コストで手札キャラ1枚がトラッシュに捨てられていない"
    # 手札 net: 元1 - コスト捨て1 + ドロー1 = 1
    assert len(me.hand) == 1, f"手札 net (捨て-1 ドロー+1) が合わない: {len(me.hand)}"


def test_p083_shanks_on_attack_no_character_in_hand_noop():
    """手札にキャラカードが無ければ 任意コスト不能 → 相手 power 不変 (効果不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shanks = InPlay.of(repo.get("P-083"), sickness=False)
    shanks.attached_dons = 1
    me.characters = [shanks]
    me.hand = []  # 捨てられるキャラ無し
    me.deck = [repo.get(COST2)] * 10
    victim = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "P-083", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, shanks)
    _drain(st, [0])

    assert victim.power == power_before, \
        "コスト不能なのに相手キャラの power が下がってはいけない"


# --------------------------------------------------------------------------- #
#  P-084 バギー (CHARACTER):
#    このキャラはアタックできない。自分のリーダーが「バギー」の場合、コスト3と4の
#    キャラすべては、アタックできない。【登場時】自分の手札からコスト6以下の
#    特徴《クロスギルド》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_p084_buggy_static_self_cannot_attack():
    """静的: このキャラ (バギー) 自身はアタックできない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("P-084"), sickness=False)
    me.characters = [buggy]

    evaluate_static_effects(st, overlay)
    assert buggy.cannot_attack_static is True, \
        "バギー自身に cannot_attack_static が立っていない"


def test_p084_buggy_static_cost34_cannot_attack_with_baggy_leader():
    """静的 (リーダー=バギー): コスト3と4のキャラすべてがアタックできない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BAGGY_LEADER, overlay)  # リーダー = バギー
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("P-084"), sickness=False)
    c3 = InPlay.of(repo.get(COST3), sickness=False)  # cost3
    c4 = InPlay.of(repo.get(COST4), sickness=False)  # cost4
    me.characters = [buggy, c3, c4]

    evaluate_static_effects(st, overlay)
    assert c3.cannot_attack_static is True, "コスト3キャラがアタック不可になっていない"
    assert c4.cannot_attack_static is True, "コスト4キャラがアタック不可になっていない"


def test_p084_buggy_static_cost34_free_without_baggy_leader():
    """リーダーが「バギー」でなければ コスト3/4 制約は発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)  # ゾロ leader
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("P-084"), sickness=False)
    c3 = InPlay.of(repo.get(COST3), sickness=False)
    me.characters = [buggy, c3]

    evaluate_static_effects(st, overlay)
    assert c3.cannot_attack_static is False, \
        "バギー以外の leader で コスト3制約が発動してはいけない"


def test_p084_buggy_on_play_summon_crossguild_ai():
    """【登場時】 AI: 手札からコスト6以下《クロスギルド》キャラ1枚を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    mr3 = repo.get(CROSSGUILD)  # クロスギルド cost1
    me.hand = [mr3]

    for prim in _eff(overlay, "P-084", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-084"), sickness=True))
    _drain(st, [0])

    assert any(c.card.card_id == CROSSGUILD for c in me.characters), \
        "手札からクロスギルドキャラが登場していない"
    assert not any(c.card_id == CROSSGUILD for c in me.hand), \
        "登場した クロスギルドキャラは手札から除かれるべき"
