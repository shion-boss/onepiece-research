# -*- coding: utf-8 -*-
"""OP08 弾 (白ひげ海賊団 / 百獣海賊団 / ビッグ・マム海賊団) 効果 回帰テスト
バックフィル (自動生成 wave 086):
OP08-051 / OP08-052 / OP08-053 / OP08-054 / OP08-055 / OP08-056 /
OP08-057 / OP08-058 / OP08-060 / OP08-061 の 10 枚。

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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_self_chara_leave_by_self_effect,
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


def _do(overlay, cid, when):
    return [p for e in overlay.get(cid).effects if e["when"] == when for p in e["do"]]


def _drain(st, pick=0, guard=10):
    """pending_choice を pick を選び続けて解決しきる (後続の reorder 等を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        cands = st.pending_choice.get("candidates")
        cards = st.pending_choice.get("cards")
        if cands is not None and len(cands) == 0:
            resolve_pending_choice(st, [])
        elif cards is not None and not cands:
            resolve_pending_choice(st, [pick] if any(
                c.get("matches_filter") for c in cards) else [])
        else:
            resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op08_wave086_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-051", "OP08-052", "OP08-053", "OP08-054", "OP08-055",
           "OP08-056", "OP08-057", "OP08-058", "OP08-060", "OP08-061"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-051 バッキン (青 cost1):
#    【自分のターン中】【登場時】自分の「エドワード・ウィーブル」1枚までを
#      このターン中 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op08_051_on_play_pump_weevil_ai():
    """【登場時】自分の「エドワード・ウィーブル」1枚に このターン中 +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    weevil = InPlay.of(repo.get("OP08-042"), sickness=False)  # エドワード・ウィーブル pow5000
    me.characters = [weevil]

    pow_before = weevil.power
    for prim in _do(overlay, "OP08-051", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-051"), sickness=True))
    _drain(st)

    assert weevil.power == pow_before + 2000, \
        f"「エドワード・ウィーブル」に +2000 されていない: {weevil.power} (before {pow_before})"


def test_op08_051_on_play_self_turn_condition():
    """overlay の 発動条件が【自分のターン中】(self_turn) である。"""
    overlay = _overlay()
    on_play = next(e for e in overlay.get("OP08-051").effects
                   if e["when"] == "on_play")
    conds = on_play.get("conditions", [])
    assert any(c.get("self_turn") for c in conds), \
        "OP08-051 の on_play に self_turn 条件が無い"


def test_op08_051_on_play_human_pick_two_weevils():
    """人間 + 「エドワード・ウィーブル」複数 → target_pick modal が立ち resolve で 1 体に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    w1 = InPlay.of(repo.get("OP08-042"), sickness=False)  # pow5000
    w2 = InPlay.of(repo.get("OP07-039"), sickness=False)  # pow5000
    me.characters = [w1, w2]

    execute_effect(_do(overlay, "OP08-051", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-051"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ウィーブル 2 体) が 2 件でない: {len(cands)}"

    w2_idx = next(i for i, c in enumerate(cands) if c["iid"] == w2.instance_id)
    resolve_pending_choice(st, [w2_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert w2.power == 7000, f"人間が選んだウィーブルに +2000 されていない: {w2.power}"


# --------------------------------------------------------------------------- #
#  OP08-052 ポートガス・D・エース (青 cost5):
#    【登場時】デッキ上1枚公開、コスト4以下の『白ひげ海賊団』キャラ1枚までを登場。
#      残りをデッキ上か下へ。
# --------------------------------------------------------------------------- #
def test_op08_052_on_play_reveal_top_play_whitebeard_ai():
    """【登場時】デッキ上の コスト4以下『白ひげ海賊団』キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP14-053")] + [repo.get("OP01-013")] * 10  # 上に ビスタ (白ひげ cost3)
    me.characters = []

    for prim in _do(overlay, "OP08-052", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-052"), sickness=True))
    _drain(st)

    assert any(c.card.card_id == "OP14-053" for c in me.characters), \
        f"デッキ上の『白ひげ海賊団』キャラが登場していない: {[c.card.card_id for c in me.characters]}"


def test_op08_052_reveal_non_matching_no_play():
    """negative: デッキ上が対象外 (白ひげでない) なら登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] + [repo.get("OP01-016")] * 10  # 上は麦わら (非白ひげ)
    me.characters = []

    for prim in _do(overlay, "OP08-052", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-052"), sickness=True))
    _drain(st)

    assert not any(c.card.card_id == "OP01-013" for c in me.characters), \
        "対象外カードが登場してはいけない"


# --------------------------------------------------------------------------- #
#  OP08-053 愛してくれて………ありがとう!!! (青 EVENT cost1):
#    【メイン】自リーダーが『白ひげ海賊団』なら デッキ上3枚を見て
#      『白ひげ海賊団』か「モンキー・D・ルフィ」1枚までを手札へ、 残りをデッキ下へ。
# --------------------------------------------------------------------------- #
def test_op08_053_main_search_top3_whitebeard_ai():
    """【メイン】デッキ上3枚から『白ひげ海賊団』カードを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-002", overlay)  # マルコ (白ひげ leader → 条件成立)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP14-053"), repo.get("OP01-013"),
               repo.get("OP01-016")] + [repo.get("OP01-013")] * 10  # 上3に ビスタ (白ひげ)
    me.hand = []

    eff = next(e for e in overlay.get("OP08-053").effects if e["when"] == "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-053"), sickness=False))
    _drain(st)

    assert any(c.card_id == "OP14-053" for c in me.hand), \
        f"デッキ上3枚から『白ひげ海賊団』カードが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op08_053_leader_feature_gate():
    """overlay の 発動条件が 自リーダー『白ひげ海賊団』(leader_features_any) である。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-053").effects if e["when"] == "main")
    assert "白ひげ海賊団" in eff.get("if", {}).get("leader_features_any", []), \
        "OP08-053 の main に 自リーダー白ひげ海賊団 条件が無い"


def test_op08_053_main_search_human_modal():
    """人間: デッキ上3枚に候補 → search_top_n modal が立ち resolve で手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-002", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP14-053"), repo.get("OP01-013"),
               repo.get("OP01-016")] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = next(e for e in overlay.get("OP08-053").effects if e["when"] == "main")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-053"), sickness=False))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == "OP14-053" for c in me.hand), \
        "人間が選んだ『白ひげ海賊団』カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP08-054 いきなり“キング”は取れねェだろうよい (青 EVENT cost3):
#    【カウンター】自リーダーかキャラ1枚に このバトル中 +3000。 その後 デッキ上1公開し
#      コスト3以下『白ひげ海賊団』キャラ1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op08_054_counter_pump_leader_and_play_whitebeard_ai():
    """【カウンター】自リーダーに +3000 + デッキ上の コスト3以下『白ひげ海賊団』を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-002", overlay)  # マルコ (白ひげ leader)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP14-053")] + [repo.get("OP01-013")] * 10  # 上に ビスタ (白ひげ cost3)
    me.characters = []

    leader_pow_before = me.leader.power
    for prim in _do(overlay, "OP08-054", "counter"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert me.leader.power == leader_pow_before + 3000, \
        f"自リーダーに +3000 されていない: {me.leader.power} (before {leader_pow_before})"
    assert any(c.card.card_id == "OP14-053" for c in me.characters), \
        f"デッキ上の コスト3以下『白ひげ海賊団』キャラが登場していない: {[c.card.card_id for c in me.characters]}"


# --------------------------------------------------------------------------- #
#  OP08-055 鳳凰印 (青 EVENT cost4):
#    【メイン】手札から『白ひげ海賊団』カード2枚を公開できる：コスト6以下キャラ1枚までを
#      持ち主のデッキ下へ置く。
# --------------------------------------------------------------------------- #
def test_op08_055_main_optional_return_opp_chara_to_deck_bottom_ai():
    """【メイン】(手札の白ひげ2枚公開) 相手コスト6以下キャラを デッキ下へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)  # エドワード・ニューゲート (白ひげ leader)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP13-045"), repo.get("OP14-053")]  # 白ひげ 2 枚 (公開コスト)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 6
    opp.characters = [victim]

    deck_before = len(opp.deck)
    for prim in _do(overlay, "OP08-055", "main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-055"), sickness=False))
    _drain(st)

    assert not any(c.instance_id == victim.instance_id for c in opp.characters), \
        "相手キャラが場から取り除かれていない"
    assert len(opp.deck) == deck_before + 1, \
        f"相手デッキ下に1枚戻っていない: {len(opp.deck)} (before {deck_before})"


def test_op08_055_main_human_optional_cost_modal():
    """人間: 任意コスト (白ひげ2枚公開) の optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP13-045"), repo.get("OP14-053")]
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]

    execute_effect(_do(overlay, "OP08-055", "main")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-055"), sickness=False))
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  OP08-056 モビー・ディック号 (青 STAGE cost2):
#    【自分のターン中】【ターン1回】自分の『白ひげ海賊団』キャラが効果で場を離れた時、
#      カード1枚を引く。 その後 自分の手札1枚をデッキ上か下へ。
# --------------------------------------------------------------------------- #
def test_op08_056_leave_trigger_draw_then_hand_to_deck_ai():
    """『白ひげ海賊団』キャラが効果で離脱 → draw 1 + 手札1をデッキへ (AI、 net 不変・crash なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-002", overlay)
    me, opp = st.players[0], st.players[1]
    me.stages = [InPlay.of(repo.get("OP08-056"), sickness=False)]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("OP08-004")] + [repo.get("OP01-013")] * 20  # 上に クロマーリモ (distinct)
    st.last_chara_ko_victim_card = repo.get("OP14-053")  # 白ひげ victim 文脈

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trigger_on_self_chara_leave_by_self_effect(st, me, opp, overlay)
    _drain(st)

    # draw 1 + 手札1をデッキへ = 手札枚数/デッキ枚数は net 不変 (= 引いて置き戻す)
    assert len(me.hand) == hand_before, \
        f"draw + 手札→デッキ で 手札枚数が net 不変でない: {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before, \
        f"draw + 手札→デッキ で デッキ枚数が net 不変でない: {len(me.deck)} (before {deck_before})"
    assert st.pending_choice is None, "AI 文脈で pending_choice が残ってはいけない"


def test_op08_056_hand_to_deck_human_pick():
    """人間: draw 後の 手札→デッキ で self_hand_to_deck_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-002", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.stages = [InPlay.of(repo.get("OP08-056"), sickness=False)]
    me.hand = [repo.get("OP01-016"), repo.get("OP01-048")]
    me.deck = [repo.get("OP08-004")] + [repo.get("OP01-013")] * 20

    eff = next(e for e in overlay.get("OP08-056").effects
               if e["when"] == "on_self_chara_leave_by_self_effect")
    stage = me.stages[0]
    # draw
    execute_effect(eff["do"][0], st, me, opp, stage)
    assert repo.get("OP08-004").card_id in [c.card_id for c in me.hand], \
        "draw でデッキ上のカードが手札に加わっていない"
    # 手札→デッキ (人間 modal)
    execute_effect(eff["do"][1], st, me, opp, stage)
    assert st.pending_choice is not None, "人間 手札→デッキ で modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_to_deck_pick", \
        f"kind が self_hand_to_deck_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert st.pending_choice is None, "解決後も modal が残る"


# --------------------------------------------------------------------------- #
#  OP08-057 キング (LEADER 紫/黒):
#    【起動メイン】【ターン1回】ドン‼-2：以下から1つ選ぶ。
#      ・手札5枚以下なら 1 ドロー / ・相手キャラ1枚までを このターン中 コスト-2。
# --------------------------------------------------------------------------- #
def test_op08_057_activate_main_choice_draw_ai():
    """起動メイン: ドン2支払い、 手札5以下なら 1 ドロー (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-057", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.hand = [repo.get("OP01-013")] * 3  # 5 枚以下 → draw option 有効

    options = list_activate_main_effects(st, me, overlay)
    king_opts = [(src, eff) for (src, eff) in options
                 if src.card.card_id == "OP08-057"]
    assert len(king_opts) == 1, \
        f"OP08-057 の起動メインが legal に出ない: {len(king_opts)}"

    hand_before = len(me.hand)
    don_before = me.don_active
    fire_activate_main(st, me, opp, *king_opts[0])
    _drain(st)

    assert len(me.hand) == hand_before + 1, \
        f"手札5以下で 1 ドローされていない: {len(me.hand)} (before {hand_before})"
    assert me.don_active == don_before - 2, "ドン‼-2 が支払われていない"


def test_op08_057_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-057", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 4
    me.hand = [repo.get("OP01-013")] * 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-057"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-057"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op08_057_activate_main_human_option_pick():
    """人間: 2 択 (ドロー / 相手コスト-2) の option_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-057", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.hand = [repo.get("OP01-013")] * 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-057"]
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("options", [])) == 2, \
        "選択肢が 2 つでない"


# --------------------------------------------------------------------------- #
#  OP08-058 シャーロット・プリン (LEADER 紫/黄):
#    【アタック時】自ライフ上2枚を表向きにできる：ドンデッキからドン‼1枚までをレストで追加。
# --------------------------------------------------------------------------- #
def test_op08_058_on_attack_optional_flip_life_add_rested_don_ai():
    """【アタック時】(ライフ2枚表向き) ドン‼1枚をレストで追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-058", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3  # 表向きにする 2 枚を確保
    me.don_rested = 0
    me.don_active = 0

    rested_before = me.don_rested
    faceup_before = me.face_up_life_count
    for prim in _do(overlay, "OP08-058", "on_attack"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert me.don_rested == rested_before + 1, \
        f"レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"
    assert me.face_up_life_count == faceup_before + 2, \
        f"ライフ2枚が表向きになっていない: {me.face_up_life_count} (before {faceup_before})"


def test_op08_058_on_attack_human_optional_cost_modal():
    """人間: 任意コスト (ライフ2枚表向き) の optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-058", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3

    execute_effect(_do(overlay, "OP08-058", "on_attack")[0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  OP08-060 キング (紫 CHARACTER cost7):
#    【登場時】ドン‼-1：相手の場のドン‼が5枚以上なら このターン中【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op08_060_on_play_give_rush_ai():
    """【登場時】相手ドン5以上 → このキャラ(自身)に【速攻】付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)  # カイドウ (紫 百獣)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 5  # 相手ドン 5 枚以上 → 条件成立
    me.don_active = 3
    king = InPlay.of(repo.get("OP08-060"), sickness=True)
    me.characters = [king]

    for prim in _do(overlay, "OP08-060", "on_play"):
        execute_effect(prim, st, me, opp, king)

    assert "速攻" in king.granted_keywords, \
        f"【速攻】が付与されていない: {king.granted_keywords}"


def test_op08_060_don_gate_and_opp_don_condition():
    """overlay の コストゲート pay_don=1 + 条件 opp_don_count_ge=5 が正しく登録されている。"""
    overlay = _overlay()
    on_play = next(e for e in overlay.get("OP08-060").effects
                   if e["when"] == "on_play")
    assert on_play.get("cost", {}).get("pay_don") == 1, \
        "OP08-060 の ドン‼-1 ゲート (pay_don=1) が無い"
    assert on_play.get("if", {}).get("opp_don_count_ge") == 5, \
        "OP08-060 の 相手ドン5以上 条件 (opp_don_count_ge=5) が無い"


# --------------------------------------------------------------------------- #
#  OP08-061 シャーロット・オーブン (紫 CHARACTER cost5):
#    【アタック時】ドン‼-1：相手のコスト3以下キャラ1枚までを KO する。
# --------------------------------------------------------------------------- #
def test_op08_061_on_attack_ko_cost_le3_ai():
    """【アタック時】相手コスト3以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    for prim in _do(overlay, "OP08-061", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-061"), sickness=False))
    _drain(st)

    assert not any(c.instance_id == victim.instance_id for c in opp.characters), \
        "相手コスト3以下キャラが KO されていない"
    assert any(c.card_id == "OP01-013" for c in opp.trash), \
        "KO されたキャラがトラッシュに置かれていない"


def test_op08_061_on_attack_cost_ge4_no_target():
    """negative: 相手が コスト4以上キャラのみ → KO 対象にならず場に残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    big = InPlay.of(repo.get("OP08-004"), sickness=False)  # cost4 (> 3)
    opp.characters = [big]

    for prim in _do(overlay, "OP08-061", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-061"), sickness=False))
    _drain(st)

    assert any(c.instance_id == big.instance_id for c in opp.characters), \
        "コスト4以上キャラが KO されてはいけない"


def test_op08_061_on_attack_ko_human_pick():
    """人間 + 相手コスト3以下 複数 → target_pick modal が立ち resolve で 1 体 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP08-061", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-061"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert not any(c.instance_id == b.instance_id for c in opp.characters), \
        "人間が選んだキャラが KO されていない"
