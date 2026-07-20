# -*- coding: utf-8 -*-
"""EB04 弾 効果 回帰テスト バックフィル (自動生成 wave 016):
EB04-016 / EB04-017 / EB04-018 / EB04-019 / EB04-020 / EB04-021 /
EB04-022 / EB04-023 / EB04-024 / EB04-025 の 10 枚。

目的 (= test_backfill_auto_001〜015.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
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
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _am(st, me, overlay, cid):
    """指定 card_id の legal な起動メイン (src, eff) を返す (無ければ空 list)。"""
    return [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave16_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB04-016", "EB04-017", "EB04-018", "EB04-019", "EB04-020",
           "EB04-021", "EB04-022", "EB04-023", "EB04-024", "EB04-025"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB04-016 トリ (CHARACTER 緑 cost5 power7000):
#    【起動メイン】自分のドン‼1枚までをアクティブにする (その後キャラ効果でドン活性禁止) /
#    【アタック時】自分の特徴《海王類》キャラ3枚以上で 相手のコスト8以下のキャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_eb04_016_tori_activate_main_untap_don_ai():
    """起動メイン: レストドン1枚をアクティブにする (AI)。 don_rested -1 / don_active +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tori = InPlay.of(repo.get("EB04-016"), sickness=False)
    me.characters = [tori]
    me.don_rested = 1
    me.don_active = 0

    opts = _am(st, me, overlay, "EB04-016")
    assert len(opts) == 1, f"EB04-016 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.don_active == 1 and me.don_rested == 0, \
        f"起動メインでレストドンがアクティブになっていない: active={me.don_active} rested={me.don_rested}"


def test_eb04_016_tori_on_attack_rest_opp_ai():
    """アタック時 (海王類3枚以上): 相手のコスト8以下のキャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 海王類 3 枚 (トリ自身 + ギョロ目 + マダラ)
    tori = InPlay.of(repo.get("EB04-016"), sickness=False)
    me.characters = [tori,
                     InPlay.of(repo.get("OP11-027"), sickness=False),
                     InPlay.of(repo.get("OP11-036"), sickness=False)]
    assert eval_condition(
        {"self_chara_feature_count_ge": {"feature": "海王類", "count": 3}}, st, me
    ) is True, "テスト前提: 海王類キャラ3枚の条件が成立していない"
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ cost3 (active)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-016", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, tori)

    assert victim.rested is True, "アタック時に相手のコスト8以下キャラがレストされていない"


def test_eb04_016_tori_on_attack_rest_human_pick():
    """人間 + 相手キャラ 複数 → レスト対象の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    tori = InPlay.of(repo.get("EB04-016"), sickness=False)
    me.characters = [tori]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("ST01-013"), sickness=False)  # cost3
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB04-016", "on_attack")
    execute_effect(do[0], st, me, opp, tori)
    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  EB04-017 ナゾムズ (CHARACTER 緑 cost6):
#    【登場時】自リーダーがミンク族なら 手札のコスト5以下のミンク族キャラ1枚を登場
# --------------------------------------------------------------------------- #
def test_eb04_017_nazomz_on_play_summon_mink_ai():
    """登場時 (ミンク族リーダー): 手札のコスト5以下ミンク族キャラ1枚を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)  # キャロット (ミンク族 leader)
    me, opp = st.players[0], st.players[1]
    conslot = repo.get("OP08-024")  # コンスロット ミンク族 cost3
    assert "ミンク族" in (conslot.features or ""), "テスト前提: OP08-024 は ミンク族"
    me.hand = [conslot]

    assert eval_condition({"leader_feature": "ミンク族"}, st, me) is True, \
        "テスト前提: リーダーが ミンク族 でない"
    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB04-017", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-017"), sickness=True))

    assert any(c.card.card_id == "OP08-024" for c in me.characters), \
        "手札のミンク族キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_eb04_017_nazomz_on_play_human_summon_pick():
    """人間 + 手札にミンク族 複数 → 登場先を選ぶ play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP08-024"), repo.get("OP08-025")]  # コンスロット / シシリアン

    do, _ = _do(overlay, "EB04-017", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-017"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id in ("OP08-024", "OP08-025") for c in me.characters), \
        "人間が選んだミンク族キャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB04-018 メガロ (CHARACTER 緑 cost4 power4000):
#    【登場時】このキャラをレストにできる：相手のレストのパワー8000以下のキャラ1枚をKO
# --------------------------------------------------------------------------- #
def test_eb04_018_megalo_on_play_ko_rested_opp_ai():
    """登場時: 相手のレストのパワー8000以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ power5000
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-018", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-018"), sickness=False))

    assert victim not in opp.characters, "相手のレストのパワー8000以下キャラが KO されていない"


def test_eb04_018_megalo_on_play_no_active_target():
    """相手キャラがアクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-018", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-018"), sickness=False))
    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_eb04_018_megalo_on_play_ko_human_pick():
    """人間 + 相手のレストキャラ 複数 → KO 対象の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("ST01-013"), sickness=False)  # power5000
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB04-018", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-018"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
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
#  EB04-019 エレ爪 (EVENT 緑 cost1):
#    【メイン】自カード1枚レストできる：リーダーがミンク族なら 相手キャラ1枚 このターン中 コスト-3 /
#    【カウンター】自分のミンク族のリーダーかキャラ1枚まで このバトル中 パワー+3000
# --------------------------------------------------------------------------- #
def test_eb04_019_ele_claw_counter_pump_leader_ai():
    """カウンター: 自分のミンク族リーダーを このバトル中 +3000 (AI 既定 = リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)  # キャロット (ミンク族 leader)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB04-019", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_eb04_019_ele_claw_counter_pump_human_pick():
    """人間 + ミンク族 リーダー+キャラ → +3000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP08-024"), sickness=False)  # コンスロット ミンク族
    me.characters = [friend]

    do, _ = _do(overlay, "EB04-019", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+ミンク族キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 3000, \
        "人間が選んだミンク族キャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB04-020 鮫瓦正拳 (EVENT 緑 cost1):
#    【カウンター】自分の魚人族のリーダーかキャラ1枚まで +3000、
#                  その後 自分の魚人族キャラ1枚をアクティブにする /
#    【トリガー】相手のコスト4以下のキャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_eb04_020_samegawara_counter_pump_leader_ai():
    """カウンター: 自分の魚人族リーダーを +3000 (AI 既定 = リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay)  # ジンベエ (魚人族 leader)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB04-020", "counter")
    # do[0] = power_pump (魚人族)。 do[1] = untap (魚人族キャラ 無ければ no-op)
    execute_effect(do[0], st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_eb04_020_samegawara_counter_untap_mink_chara():
    """カウンター後段: 自分の魚人族キャラ1枚をアクティブにする (レストのアーロンが起きる)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay)
    me, opp = st.players[0], st.players[1]
    aaron = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 魚人族
    aaron.rested = True
    me.characters = [aaron]

    do, _ = _do(overlay, "EB04-020", "counter")
    # untap プリミティブ (do[1]) を直接発火
    execute_effect(do[1], st, me, opp, None)

    assert aaron.rested is False, "カウンター後段で魚人族キャラがアクティブになっていない"


def test_eb04_020_samegawara_trigger_rest_opp_ai():
    """トリガー: 相手のコスト4以下のキャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ cost3 (active)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-020", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim.rested is True, "トリガーで相手のコスト4以下キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  EB04-021 イガラム (CHARACTER 青 cost3 power4000):
#    【登場時】自リーダーが「ネフェルタリ・ビビ」なら カード2枚引き 手札1枚捨てる /
#    【起動メイン】【ターン1回】手札1枚捨てられる：自リーダーかキャラにレストのドン1枚を付与
# --------------------------------------------------------------------------- #
def test_eb04_021_igaram_on_play_draw_discard_ai():
    """登場時 (リーダー = ビビ): 2ドロー → 手札1枚捨てる (AI)。 デッキ -2 / 手札 net +1 / トラッシュ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)  # ネフェルタリ・ビビ (leader)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 10

    assert eval_condition({"leader_name": "ネフェルタリ・ビビ"}, st, me) is True, \
        "テスト前提: リーダーが ネフェルタリ・ビビ でない"
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "EB04-021", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-021"), sickness=True))

    assert len(me.deck) == deck_before - 2, "2ドローが起きていない (デッキ -2)"
    assert len(me.hand) == 1, f"手札 net (2ドロー -1捨て = +1) が合わない: {len(me.hand)}"
    assert len(me.trash) == trash_before + 1, "捨てた1枚がトラッシュに置かれていない"


def test_eb04_021_igaram_activate_main_attach_rested_don_ai():
    """起動メイン: 手札1枚捨て (コスト) → 自リーダーにレストのドン1枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)
    me, opp = st.players[0], st.players[1]
    igaram = InPlay.of(repo.get("EB04-021"), sickness=False)
    me.characters = [igaram]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト用
    me.don_rested = 2  # レストドン供給源

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    hand_before = len(me.hand)
    opts = _am(st, me, overlay, "EB04-021")
    assert len(opts) == 1, f"EB04-021 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで自リーダーにレストのドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストのドンが1枚消費されるべき"
    assert len(me.hand) == hand_before - 1, "起動メインコストで手札1枚が捨てられるべき"


def test_eb04_021_igaram_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)
    me, opp = st.players[0], st.players[1]
    igaram = InPlay.of(repo.get("EB04-021"), sickness=False)
    me.characters = [igaram]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]
    me.don_rested = 3

    opts1 = _am(st, me, overlay, "EB04-021")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = _am(st, me, overlay, "EB04-021")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB04-022 イッショウ (CHARACTER 青 cost5 power7000):
#    【登場時】手札2枚捨てられる：相手の手札6枚以上なら 相手は手札2枚をデッキ下に置く /
#    【ドン‼×1】【アタック時】手札1枚捨てられる：相手キャラ1枚 このターン中 パワー-2000
# --------------------------------------------------------------------------- #
def test_eb04_022_issho_on_play_opp_hand_to_deck_bottom_ai():
    """登場時 (相手手札6枚以上): 手札2枚捨て (コスト) → 相手手札2枚をデッキ下 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 3  # 捨てるコスト用 (2枚以上)
    opp.hand = [repo.get("ST01-004")] * 6  # 6枚 (= 条件成立)
    opp.deck = [repo.get("ST01-004")] * 10

    assert eval_condition({"opp_hand_count_ge": 6}, st, me) is True, \
        "テスト前提: 相手手札6枚以上が成立していない"
    opp_hand_before = len(opp.hand)
    opp_deck_before = len(opp.deck)
    my_trash_before = len(me.trash)
    do, _ = _do(overlay, "EB04-022", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-022"), sickness=True))

    assert len(opp.hand) == opp_hand_before - 2, \
        f"相手手札2枚がデッキ下に置かれていない: {len(opp.hand)} (before {opp_hand_before})"
    assert len(opp.deck) == opp_deck_before + 2, "相手デッキ下に2枚戻っていない"
    assert len(me.trash) == my_trash_before + 2, "コストで自分の手札2枚が捨てられていない"


def test_eb04_022_issho_on_attack_power_debuff_ai():
    """アタック時 (ドン1ゲート): 手札1枚捨て (コスト) → 相手キャラ1枚 -2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    issho = InPlay.of(repo.get("EB04-022"), sickness=False)
    issho.attached_dons = 1  # ドンゲート成立
    me.characters = [issho]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power2000
    opp.characters = [victim]

    power_before = victim.power
    my_trash_before = len(me.trash)
    do, _ = _do(overlay, "EB04-022", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, issho)

    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"
    assert len(me.trash) == my_trash_before + 1, "コストで手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  EB04-023 チャカ＆ペル (CHARACTER 青 cost8 power9000):
#    【ダブルアタック】【登場時】自分のアクティブのリーダーを このターン中 パワー-5000できる：
#    カード2枚を引く
# --------------------------------------------------------------------------- #
def test_eb04_023_chaka_pell_on_play_draw_with_leader_debuff_ai():
    """登場時: 自リーダー -5000 (コスト) → 2枚引く (AI)。 リーダーパワー減 + 手札 +2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 10

    power_before = me.leader.power
    do, _ = _do(overlay, "EB04-023", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-023"), sickness=True))

    assert len(me.hand) == 2, f"2ドローが起きていない: 手札 {len(me.hand)}"
    assert me.leader.power == power_before - 5000, \
        f"コストで自リーダーが -5000 されていない: {me.leader.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  EB04-024 テラコッタ (CHARACTER 青 cost2):
#    【起動メイン】このキャラをレストにし 手札1枚捨てられる：
#    自分のアラバスタ王国キャラ1枚まで このターン中【ブロック不可】を得る
# --------------------------------------------------------------------------- #
def test_eb04_024_terracotta_activate_main_give_unblockable_ai():
    """起動メイン: 自レスト+手札1枚捨て (コスト) → アラバスタ王国キャラに【ブロック不可】(AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    terra = InPlay.of(repo.get("EB04-024"), sickness=False)  # アラバスタ王国 (active)
    igaram = InPlay.of(repo.get("EB04-021"), sickness=False)  # アラバスタ王国 power4000
    me.characters = [terra, igaram]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト用

    opts = _am(st, me, overlay, "EB04-024")
    assert len(opts) == 1, f"EB04-024 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert terra.rested is True, "起動メインコストで テラコッタ がレストされるべき"
    granted = set(igaram.granted_keywords) | set(terra.granted_keywords)
    assert "ブロック不可" in granted, \
        f"アラバスタ王国キャラに【ブロック不可】が付与されていない: {granted}"


def test_eb04_024_terracotta_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    terra = InPlay.of(repo.get("EB04-024"), sickness=False)
    igaram = InPlay.of(repo.get("EB04-021"), sickness=False)
    me.characters = [terra, igaram]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]

    opts1 = _am(st, me, overlay, "EB04-024")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = _am(st, me, overlay, "EB04-024")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB04-025 ネフェルタリ・ビビ (CHARACTER 青 cost7 power4000):
#    【登場時】手札から「ビビ」以外のコスト8以下のアラバスタ王国キャラ1枚を登場、
#              その後 相手は手札1枚をデッキ下に置く
# --------------------------------------------------------------------------- #
def test_eb04_025_vivi_on_play_summon_and_opp_hand_to_deck_ai():
    """登場時: 手札のアラバスタ王国キャラ1枚を登場 + 相手手札1枚をデッキ下 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ビビ以外のリーダー (登場カードの余計な on_play を避ける)
    me, opp = st.players[0], st.players[1]
    karoo = repo.get("EB02-001")  # カルー アラバスタ王国 cost5 (バニラ)
    assert "アラバスタ王国" in (karoo.features or ""), "テスト前提: EB02-001 は アラバスタ王国"
    me.hand = [karoo]
    opp.hand = [repo.get("ST01-004")]
    opp.deck = [repo.get("ST01-004")] * 10

    opp_hand_before = len(opp.hand)
    do, _ = _do(overlay, "EB04-025", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-025"), sickness=True))

    assert any(c.card.card_id == "EB02-001" for c in me.characters), \
        "手札のアラバスタ王国キャラ (カルー) が登場していない"
    assert len(opp.hand) == opp_hand_before - 1, \
        f"相手の手札1枚がデッキ下に置かれていない: {len(opp.hand)}"


def test_eb04_025_vivi_on_play_human_summon_pick():
    """人間 + 手札にアラバスタ王国キャラ 複数 → 登場先を選ぶ play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 種のアラバスタ王国 cost8以下 キャラ (カルー / イガラム)
    me.hand = [repo.get("EB02-001"), repo.get("EB04-021")]
    opp.hand = [repo.get("ST01-004")]
    opp.deck = [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "EB04-025", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-025"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id in ("EB02-001", "EB04-021") for c in me.characters), \
        "人間が選んだアラバスタ王国キャラが登場していない"
