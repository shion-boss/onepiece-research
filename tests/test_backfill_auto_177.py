# -*- coding: utf-8 -*-
"""カード効果 回帰テスト バックフィル (自動生成 wave 177):
ST13-010 / ST13-011 / ST13-012 / ST13-013 / ST13-014 / ST13-015 /
ST13-016 / ST13-017 / ST13-018 / ST14-001 の 10 枚
(= ST13 黄「エース&白ひげ / ルフィ」系の効果カード群 + ST14-001 黒リーダー)。

目的 (= test_backfill_auto_001〜176.py と同一方針):
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
    eval_all_conditions,
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
NAMI = "OP01-016"       # ナミ (cost1 power2000 麦わらの一味) フィラー / cost1 char
SANJI = "OP01-013"      # サンジ (cost2 power3000 麦わらの一味) フィラー / cost2 char
LEADER = "OP01-001"     # モンキー・D・ルフィ (赤 LEADER) — 素材用 leader
COST8_CHAR = "OP07-015"  # モンキー・D・ドラゴン (cost8 power9000 CHARACTER)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id=LEADER):
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
    needle 指定時は do[0] に needle キーを含む効果を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    if needle is not None:
        matches = [e for e in matches if needle in e["do"][0]]
        assert matches, f"{cid} の when={when} に do[0]={needle} の効果がない"
    return matches[0]


def _act(st, me, overlay, cid):
    """指定 card_id の起動メイン option を 1 件返す (無ければ assert)。"""
    opts = [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]
    assert len(opts) == 1, f"{cid} の起動メインが legal に 1 件出ない: {len(opts)}"
    return opts[0]


def _drain(st, picks=None, guard=8):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    if picks is None:
        picks = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, list(picks))
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave177_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST13-010", "ST13-011", "ST13-012", "ST13-013", "ST13-014",
           "ST13-015", "ST13-016", "ST13-017", "ST13-018", "ST14-001"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST13-010 ポートガス・D・エース (CHARACTER 黄 cost2 power2000):
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のライフの上から1枚を
#    公開し、そのカードがコスト5の「ポートガス・D・エース」の場合、登場させてもよい。
#    登場させた場合、自分のリーダー1枚までを、次の相手のターン終了時まで、パワー+2000。
# --------------------------------------------------------------------------- #
def test_st13_010_activate_main_reveal_ace_play_and_pump():
    """起動メイン: このキャラをトラッシュ (コスト) → ライフ上が cost5 エースなら登場 + リーダー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ace2 = InPlay.of(repo.get("ST13-010"), sickness=False)
    me.characters = [ace2]
    # ライフ上に cost5 エース (ST13-011) を仕込む
    me.life = [repo.get("ST13-011"), repo.get(SANJI), repo.get(SANJI)]

    leader_power_before = me.leader.power
    src, eff = _act(st, me, overlay, "ST13-010")
    fire_activate_main(st, me, opp, src, eff)

    assert ace2 not in me.characters, "コストでエース(cost2)がトラッシュに置かれるべき"
    assert any(c.card.card_id == "ST13-011" for c in me.characters), \
        "ライフ上の cost5 エースが登場していない"
    assert me.leader.power == leader_power_before + 2000, \
        f"登場後のリーダー +2000 が反映されていない: {me.leader.power} (before {leader_power_before})"


def test_st13_010_activate_main_reveal_no_match_no_play():
    """ライフ上が cost5 エースでない場合は登場せず、 リーダー +2000 も乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ace2 = InPlay.of(repo.get("ST13-010"), sickness=False)
    me.characters = [ace2]
    me.life = [repo.get(SANJI), repo.get(SANJI), repo.get(SANJI)]  # 非マッチ

    leader_power_before = me.leader.power
    life_before = len(me.life)
    src, eff = _act(st, me, overlay, "ST13-010")
    fire_activate_main(st, me, opp, src, eff)

    assert not any(c.card.card_id == "ST13-011" for c in me.characters), \
        "非マッチなのにエースが登場している"
    assert me.leader.power == leader_power_before, "非マッチなのにリーダー +2000 が乗っている"
    assert len(me.life) == life_before, "非マッチではライフ枚数が変わらないべき (公開のみ)"


# --------------------------------------------------------------------------- #
#  ST13-011 ポートガス・D・エース (CHARACTER 黄 cost5 power7000):
#    【登場時】自分のライフが2枚以下の場合、このキャラは【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_st13_011_on_play_gives_rush_when_life_le2():
    """【登場時】自ライフ2以下 → このキャラは【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(SANJI), repo.get(SANJI)]  # 2 枚 (= 条件成立)
    ace5 = InPlay.of(repo.get("ST13-011"), sickness=True)
    me.characters = [ace5]

    eff = _eff(overlay, "ST13-011", "on_play")
    assert eval_all_conditions(eff, st, me, ace5) is True, \
        "ライフ2枚で on_play 条件 (self_life_le 2) が成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, ace5)

    assert "速攻" in ace5.granted_keywords, "ライフ2以下で【速攻】が付与されていない"


def test_st13_011_on_play_no_rush_when_life_ge3():
    """自ライフ3枚以上 → 条件不成立 → 【速攻】を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(SANJI)] * 3  # 3 枚 (= 条件不成立)
    ace5 = InPlay.of(repo.get("ST13-011"), sickness=True)
    me.characters = [ace5]

    eff = _eff(overlay, "ST13-011", "on_play")
    assert eval_all_conditions(eff, st, me, ace5) is False, \
        "ライフ3枚で on_play 条件が誤って成立している"


# --------------------------------------------------------------------------- #
#  ST13-012 マキノ (CHARACTER 黄 cost1):
#    【登場時】自分のライフの上か下から1枚を手札に加えることができる：
#    自分のライフすべてを見て、好きな順番で置く。
# --------------------------------------------------------------------------- #
def test_st13_012_on_play_optional_life_to_hand_ai():
    """【登場時】(任意) ライフ上下1枚を手札へ → ライフ並び替え。 AI: cost 払って発動 (手札+1 / ライフ-1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(SANJI), repo.get(NAMI), repo.get(SANJI)]  # 3 枚
    me.hand = []

    life_before = len(me.life)
    eff = _eff(overlay, "ST13-012", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST13-012"), sickness=True))

    assert len(me.hand) == 1, "任意コストで ライフ1枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "ライフが1枚減っていない (手札へ移動分)"


def test_st13_012_on_play_human_reorder_modal():
    """人間 actor: cost 支払い後 ライフ並び替え (scry_life_reorder) modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(SANJI), repo.get(NAMI), repo.get(SANJI)]
    me.hand = []

    eff = _eff(overlay, "ST13-012", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST13-012"), sickness=True))

    # 任意コスト (= 「〜できる：」) なので まず pay/skip の確認 modal が立つ。
    assert st.pending_choice is not None, "人間 actor で 任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay (= コストを払う)

    # コスト支払い後 ライフ並び替え (scry_life_reorder) modal が続く。
    assert st.pending_choice is not None, "コスト支払い後 並び替え modal が立たない"
    assert st.pending_choice.get("kind") == "scry_life_reorder", \
        f"kind が scry_life_reorder でない: {st.pending_choice.get('kind')}"
    _drain(st, picks=[0])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.hand) == 1, "人間解決後 ライフ1枚が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST13-013 モンキー・D・ガープ (CHARACTER 黄 cost1 power2000):
#    【登場時】自分のデッキの上から5枚を見て、コスト5以下の、「サボ」か
#    「ポートガス・D・エース」か「モンキー・D・ルフィ」1枚までを公開し、手札に加える。
#    その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_st13_013_on_play_search_top5_to_hand_ai():
    """【登場時】デッキ上5枚から cost5以下の サボ/エース/ルフィ 1枚を手札へ。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ace5 = repo.get("ST13-011")  # cost5 ポートガス・D・エース (= 該当)
    me.deck = [repo.get(SANJI), ace5] + [repo.get(SANJI)] * 15
    me.hand = []

    eff = _eff(overlay, "ST13-013", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST13-013"), sickness=True))

    assert any(c.card_id == "ST13-011" for c in me.hand), \
        "デッキ上5枚から該当キャラ (エース) が手札に加わっていない"


def test_st13_013_on_play_human_search_modal():
    """人間 actor + デッキ上5枚に該当 → search_top_n modal が立ち resolve で手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ace5 = repo.get("ST13-011")
    me.deck = [ace5, repo.get(SANJI)] + [repo.get(SANJI)] * 15
    me.hand = []

    eff = _eff(overlay, "ST13-013", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST13-013"), sickness=True))

    assert st.pending_choice is not None, "人間 actor で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, picks=[])
    assert any(c.card_id == "ST13-011" for c in me.hand), \
        "人間が選んだ該当キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST13-014 モンキー・D・ルフィ (CHARACTER 黄 cost2 power2000):
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のライフの上から1枚を
#    公開し、そのカードがコスト5の「モンキー・D・ルフィ」の場合、登場させてもよい。
#    登場させた場合、自分のリーダー1枚までを、次の相手のターン終了時まで、パワー+2000。
# --------------------------------------------------------------------------- #
def test_st13_014_activate_main_reveal_luffy_play_and_pump():
    """起動メイン: このキャラをトラッシュ → ライフ上が cost5 ルフィなら登場 + リーダー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy2 = InPlay.of(repo.get("ST13-014"), sickness=False)
    me.characters = [luffy2]
    me.life = [repo.get("ST13-015"), repo.get(SANJI), repo.get(SANJI)]  # cost5 ルフィ

    leader_power_before = me.leader.power
    src, eff = _act(st, me, overlay, "ST13-014")
    fire_activate_main(st, me, opp, src, eff)

    assert luffy2 not in me.characters, "コストでルフィ(cost2)がトラッシュに置かれるべき"
    assert any(c.card.card_id == "ST13-015" for c in me.characters), \
        "ライフ上の cost5 ルフィが登場していない"
    assert me.leader.power == leader_power_before + 2000, \
        f"登場後のリーダー +2000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  ST13-015 モンキー・D・ルフィ (CHARACTER 黄 cost5 power6000):
#    【起動メイン】【ターン1回】このキャラは、次の自分のターン開始時まで、パワー+2000。
#    その後、自分のライフが1枚以上ある場合、カード1枚を引き、自分のライフの上から1枚を
#    トラッシュに置く。
# --------------------------------------------------------------------------- #
def test_st13_015_activate_main_pump_draw_mill_ai():
    """起動メイン(ターン1): 自身+2000 → ライフ1以上なら 1ドロー + ライフ上1トラッシュ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy5 = InPlay.of(repo.get("ST13-015"), sickness=False)
    me.characters = [luffy5]
    me.hand = []
    me.life = [repo.get(NAMI), repo.get(SANJI)]  # 2 枚 (= 条件成立)
    me.deck = [repo.get(SANJI)] * 10
    me.trash = []

    power_before = luffy5.power
    life_before = len(me.life)
    src, eff = _act(st, me, overlay, "ST13-015")
    fire_activate_main(st, me, opp, src, eff)

    assert luffy5.power == power_before + 2000, \
        f"起動メインの 自身+2000 が反映されていない: {luffy5.power}"
    assert len(me.hand) == 1, "1ドローが起きていない"
    assert len(me.life) == life_before - 1, "ライフ上1枚がトラッシュに置かれていない"
    assert len(me.trash) == 1, "トラッシュに 1 枚 (ライフ) が置かれていない"


def test_st13_015_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy5 = InPlay.of(repo.get("ST13-015"), sickness=False)
    me.characters = [luffy5]
    me.life = [repo.get(SANJI)]
    me.deck = [repo.get(SANJI)] * 10

    src, eff = _act(st, me, overlay, "ST13-015")
    fire_activate_main(st, me, opp, src, eff)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST13-015"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST13-016 ヤマト (CHARACTER 黄 cost5 power4000):
#    【速攻】【登場時】自分のライフすべてを見て、1枚を自分のデッキの上に置き、
#    ライフを好きな順番で置く。
# --------------------------------------------------------------------------- #
def test_st13_016_on_play_life_one_to_deck_ai():
    """【登場時】ライフ全部を見て 1枚をデッキ上へ (= ライフ-1 / デッキ+1)。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(SANJI), repo.get(NAMI), repo.get(SANJI)]  # 3 枚
    me.deck = [repo.get(SANJI)] * 10

    life_before = len(me.life)
    deck_before = len(me.deck)
    eff = _eff(overlay, "ST13-016", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST13-016"), sickness=True))

    assert len(me.life) == life_before - 1, "ライフから1枚がデッキへ移動していない"
    assert len(me.deck) == deck_before + 1, "デッキに1枚 (ライフ由来) が加わっていない"


def test_st13_016_on_play_human_reorder_modal():
    """人間 actor: ライフ→デッキ + 並び替え (scry_life_reorder) modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(SANJI), repo.get(NAMI), repo.get(SANJI)]
    me.deck = [repo.get(SANJI)] * 10

    life_before = len(me.life)
    eff = _eff(overlay, "ST13-016", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST13-016"), sickness=True))

    assert st.pending_choice is not None, "人間 actor で 並び替え modal が立たない"
    assert st.pending_choice.get("kind") == "scry_life_reorder", \
        f"kind が scry_life_reorder でない: {st.pending_choice.get('kind')}"
    _drain(st, picks=[0])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.life) == life_before - 1, "人間解決後 ライフ1枚がデッキへ移動していない"


# --------------------------------------------------------------------------- #
#  ST13-017 「火炎」竜王 (EVENT 黄 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
#    その後、自分のライフすべてを見て、好きな順番で置く。
# --------------------------------------------------------------------------- #
def test_st13_017_counter_pump_ai():
    """【カウンター】自リーダーorキャラ1枚 +4000 (バトル中)。 AI 自動選択 (リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST13-017", "counter", needle="power_pump")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_st13_017_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(SANJI), sickness=False)
    me.characters = [friend]

    eff = _eff(overlay, "ST13-017", "counter", needle="power_pump")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST13-018 ゴムゴムのJET槍 (EVENT 黄 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#    その後、自分のライフが0枚の場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_st13_018_counter_pump_and_draw_when_life0_ai():
    """【カウンター】自リーダー1枚 +2000 → 自ライフ0なら 1ドロー。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []            # 0 枚 (= ドロー条件成立)
    me.hand = []
    me.deck = [repo.get(SANJI)] * 10

    power_before = me.leader.power
    eff = _eff(overlay, "ST13-018", "counter", needle="power_pump")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == 1, "自ライフ0枚で 1ドローが起きていない"


def test_st13_018_counter_no_draw_when_life_present():
    """自ライフが残っている場合は ドローしない (+2000 のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(SANJI)]  # 1 枚 (= 条件不成立)
    me.hand = []
    me.deck = [repo.get(SANJI)] * 10

    eff = _eff(overlay, "ST13-018", "counter", needle="power_pump")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 0, "ライフが残っているのに ドローしている"


# --------------------------------------------------------------------------- #
#  ST14-001 モンキー・D・ルフィ (LEADER 黒 power5000):
#    【ドン‼×1】自分のキャラすべてを、コスト+1。自分のコスト8以上のキャラがいる場合、
#    このリーダーのパワー+1000。
# --------------------------------------------------------------------------- #
def test_st14_001_static_chara_cost_plus1_and_leader_pump():
    """常在(ドン×1): 自キャラすべて コスト+1 + cost8以上キャラがいれば リーダー+1000。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("ST14-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(LEADER), sickness=False))
    nami = InPlay.of(repo.get(NAMI), sickness=False)          # cost1
    dragon = InPlay.of(repo.get(COST8_CHAR), sickness=False)  # cost8 (= 条件成立)
    p0.characters = [nami, dragon]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    p0.leader.attached_dons = 1  # 【ドン‼×1】ゲート成立
    leader_base = p0.leader.card.power
    evaluate_static_effects(st, overlay)

    assert nami.base_cost_override == repo.get(NAMI).cost + 1, \
        f"キャラ (ナミ) のコスト+1 が反映されていない: {nami.base_cost_override}"
    assert dragon.base_cost_override == repo.get(COST8_CHAR).cost + 1, \
        f"キャラ (ドラゴン) のコスト+1 が反映されていない: {dragon.base_cost_override}"
    # リーダー power = 印刷値 + 付与ドン (×1=+1000、 6-5-5) + 効果 (cost8存在で+1000)
    assert p0.leader.power == leader_base + 1000 + 1000, \
        f"cost8以上キャラ存在で リーダー+1000 (効果) が乗っていない: {p0.leader.power} (base {leader_base})"


def test_st14_001_static_no_leader_pump_without_cost8():
    """cost8以上キャラがいなければ リーダー+1000 は乗らない (コスト+1 は継続)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("ST14-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(LEADER), sickness=False))
    nami = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 のみ
    p0.characters = [nami]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    p0.leader.attached_dons = 1
    leader_base = p0.leader.card.power
    evaluate_static_effects(st, overlay)

    assert nami.base_cost_override == repo.get(NAMI).cost + 1, \
        "コスト+1 (常在) が反映されていない"
    # 付与ドン (×1=+1000) は乗るが、 効果 (+1000) は cost8不在で乗らない
    assert p0.leader.power == leader_base + 1000, \
        f"cost8以上キャラ不在なのに 効果+1000 が乗っている: {p0.leader.power}"


def test_st14_001_static_off_without_don():
    """ドン付与 0 (【ドン‼×1】不成立) なら 常在効果は発火しない。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("ST14-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(LEADER), sickness=False))
    nami = InPlay.of(repo.get(NAMI), sickness=False)
    dragon = InPlay.of(repo.get(COST8_CHAR), sickness=False)
    p0.characters = [nami, dragon]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    p0.leader.attached_dons = 0  # ゲート不成立
    leader_base = p0.leader.card.power
    evaluate_static_effects(st, overlay)

    assert nami.base_cost_override is None, "ドン0なのに コスト+1 が乗っている"
    assert p0.leader.power == leader_base, "ドン0なのに リーダー+1000 が乗っている"
