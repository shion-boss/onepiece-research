# -*- coding: utf-8 -*-
"""EB02 弾 効果 回帰テスト バックフィル (自動生成 wave 009):
EB02-051 / EB02-052 / EB02-053 / EB02-054 / EB02-055 / EB02-057 /
EB02-058 / EB02-059 / EB02-060 / EB02-061 の 10 枚。

目的 (= test_backfill_auto_001〜008.py と同一方針):
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
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
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
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。
    needle を指定した場合は do[0] に needle 文字列を含む効果を優先する
    (= 同一 when が複数ある counter/on_play 等の弁別用)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_eb02_wave9_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB02-051", "EB02-052", "EB02-053", "EB02-054", "EB02-055",
           "EB02-057", "EB02-058", "EB02-059", "EB02-060", "EB02-061"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB02-051 鼻唄三丁矢筈斬り (EVENT): 【メイン】以下から1つ:
#    ・相手のコスト2以下のキャラ1枚まで KO
#    ・相手のキャラ1枚まで このターン中 コスト-4
# --------------------------------------------------------------------------- #
def test_eb02_051_hanauta_main_choice_ko_ai():
    """メイン choice: AI は先頭 valid option (= コスト2以下 KO) を発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=2)
    assert victim.card.cost <= 2
    opp.characters = [victim]

    do, _ = _do(overlay, "EB02-051", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, \
        "AI choice の コスト2以下 KO が反映されていない"


def test_eb02_051_hanauta_main_human_option_modal():
    """人間: choice_effect の option_pick modal が 2 択で立ち、 KO を選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 → 両 option valid
    opp.characters = [victim]

    do, _ = _do(overlay, "EB02-051", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    opts = st.pending_choice.get("options", [])
    assert len(opts) == 2, f"valid option が 2 件でない: {len(opts)}"
    resolve_pending_choice(st, [0])  # KO option を選択
    # KO は「1枚まで」= 対象選択 target_pick が続くので候補0を指定して drain
    _drain_choices(st, pick=[0])
    assert victim not in opp.characters, "人間が選んだ KO が反映されていない"


# --------------------------------------------------------------------------- #
#  EB02-052 エネル: 常在(自リーダー空島で【速攻】) /
#    【アタック時】手札1捨て → 自ライフ1以下なら デッキ上1をライフ + self +1000
# --------------------------------------------------------------------------- #
def test_eb02_052_enel_static_speed_when_sky_leader():
    """常在: 自リーダーが《空島》の場合 self に【速攻】付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-058", overlay)  # エネル (空島 leader)
    me, opp = st.players[0], st.players[1]
    assert eval_condition({"leader_feature": "空島"}, st, me) is True, \
        "空島 leader で 条件が成立していない"

    enel = InPlay.of(repo.get("EB02-052"), sickness=False)
    me.characters = [enel]
    do, _ = _do(overlay, "EB02-052", "on_attached_don")
    for prim in do:
        execute_effect(prim, st, me, opp, enel)
    assert "速攻" in enel.granted_keywords, "常在の【速攻】付与が反映されていない"


def test_eb02_052_enel_on_attack_put_life_and_pump_ai():
    """アタック時 (自ライフ1以下): デッキ上1枚をライフへ + 自身 このターン +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-058", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")]  # ライフ1 (= self_life_le 1 成立)
    me.deck = [repo.get("ST01-004")] * 5
    enel = InPlay.of(repo.get("EB02-052"), sickness=False)  # power 11000
    me.characters = [enel]

    life_before = len(me.life)
    deck_before = len(me.deck)
    power_before = enel.power
    do, _ = _do(overlay, "EB02-052", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, enel)
    assert len(me.life) == life_before + 1, "デッキ上1枚がライフに加わっていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"
    assert enel.power == power_before + 1000, \
        f"アタック時 自己 +1000 が反映されていない: {enel.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  EB02-053 オルガ・ミスキナ: 【登場時】/【KO時】
#    自分か相手のライフの上から1枚までを見て、ライフの上か下に置く (scry_life)
# --------------------------------------------------------------------------- #
def test_eb02_053_orga_on_play_scry_life_ai():
    """登場時 scry_life: 自ライフ上1枚を見て並べ替え (AI は自ライフ優先、 crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016"), repo.get("ST01-004")]  # ライフ2枚

    life_before = len(me.life)
    do, _ = _do(overlay, "EB02-053", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-053"), sickness=False))
    assert len(me.life) == life_before, "scry_life でライフ枚数が変わってはいけない"


def test_eb02_053_orga_on_ko_scry_life_ai():
    """KO時 scry_life: 同じ効果が on_ko でも crash せず発火する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016"), repo.get("ST01-004")]

    life_before = len(me.life)
    do, _ = _do(overlay, "EB02-053", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-053"), sickness=False))
    assert len(me.life) == life_before, "on_ko scry_life でライフ枚数が変わってはいけない"


# --------------------------------------------------------------------------- #
#  EB02-054 サンジ: 【ブロッカー】【登場時】自ライフ2枚以下 → 2ドロー + 手札1捨て
# --------------------------------------------------------------------------- #
def test_eb02_054_sanji_on_play_draw2_discard1_ai():
    """登場時 (自ライフ2以下): カード2枚を引き、 手札1枚を捨てる (net 手札+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2  # ライフ2 (= 条件成立)
    me.deck = [repo.get("ST01-004")] * 5
    me.hand = [repo.get("OP01-016")]  # 捨てる候補が確実に存在するよう初期手札1枚

    _, eff = _do(overlay, "EB02-054", "on_play")
    assert eff.get("if", {}).get("self_life_le") == 2, \
        "overlay の 条件 self_life_le=2 が無い"
    assert eval_condition({"self_life_le": 2}, st, me) is True, \
        "ライフ2枚で self_life_le=2 が成立していない"

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-054"), sickness=False))
    assert len(me.deck) == deck_before - 2, "2枚ドローでデッキが2枚減っていない"
    assert len(me.hand) == hand_before + 2 - 1, \
        f"net 手札 (+2ドロー -1捨て = +1) が合わない: {len(me.hand)} (before {hand_before})"


# --------------------------------------------------------------------------- #
#  EB02-055 ジンベエ: 【トリガー】自リーダー《魚人族/人魚族》& 自ライフ2以下で 自身登場
# --------------------------------------------------------------------------- #
def test_eb02_055_jinbe_trigger_condition():
    """トリガー条件: 魚人族 leader + 自ライフ2以下 の 両方が成立する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay)  # ジンベエ (魚人族 leader)
    me = st.players[0]
    me.life = [repo.get("ST01-004")] * 2
    assert eval_condition({"leader_feature": ["魚人族", "人魚族"]}, st, me) is True, \
        "魚人族 leader で leader_feature 条件が成立していない"
    assert eval_condition({"self_life_le": 2}, st, me) is True, \
        "ライフ2枚で self_life_le=2 が成立していない"


def test_eb02_055_jinbe_trigger_play_self_ai():
    """トリガー: play_self で ライフから めくれた自身が場に登場する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay)
    me, opp = st.players[0], st.players[1]
    # トリガー発火時、 めくれた自身は一旦 trash 相当に置かれ current_source_card_id で参照される
    me.trash = [repo.get("EB02-055")]
    st.current_source_card_id = "EB02-055"

    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB02-055", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "EB02-055" for c in me.characters), \
        "トリガー play_self で ジンベエ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  EB02-057 マッド・トレジャー: 【アタック時】自ライフ上下1枚を手札 →
#    相手のコスト3以下キャラ1枚まで 相手ライフの上か下に表向きで加える
# --------------------------------------------------------------------------- #
def test_eb02_057_mad_treasure_attack_chara_to_life_ai():
    """アタック時 (任意コスト payable): ライフ1枚を手札 → 相手 cost3以下キャラを相手ライフへ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    treasure = InPlay.of(repo.get("EB02-057"), sickness=False)
    me.characters = [treasure]
    me.life = [repo.get("ST01-004")]  # コスト用ライフ
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=3)
    assert victim.card.cost <= 3
    opp.characters = [victim]

    hand_before = len(me.hand)
    opp_life_before = len(opp.life)
    do, _ = _do(overlay, "EB02-057", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, treasure)
    assert victim not in opp.characters, "相手 cost3以下キャラが場から取り除かれていない"
    assert len(opp.life) == opp_life_before + 1, "相手キャラが相手ライフに加わっていない"
    assert len(me.hand) == hand_before + 1, "コストで自ライフ1枚が手札に加わっていない"


def test_eb02_057_mad_treasure_attack_human_optional_modal():
    """人間: 任意コストの optional_cost_confirm modal が立ち、 承諾で効果が解決する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    treasure = InPlay.of(repo.get("EB02-057"), sickness=False)
    me.characters = [treasure]
    me.life = [repo.get("ST01-004")]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]

    do, _ = _do(overlay, "EB02-057", "on_attack")
    execute_effect(do[0], st, me, opp, treasure)
    assert st.pending_choice is not None, "人間で optional_cost_confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    # 効果 (相手キャラ→相手ライフ) は「1枚まで」= 対象選択が続くので候補0で drain
    _drain_choices(st, pick=[0])
    assert victim not in opp.characters, "承諾後 相手キャラが相手ライフへ加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-058 あーーっす！ (EVENT): 【メイン】上4枚から コスト4以上1枚まで 手札 /
#    【トリガー】このカードの【メイン】効果を発動
# --------------------------------------------------------------------------- #
def test_eb02_058_aaassu_main_search_cost_ge4_ai():
    """メイン: 上4枚から コスト4以上のカードを手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = repo.get("EB01-049")  # cost5 (= コスト4以上)
    assert big.cost >= 4
    me.deck = [big] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-058", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "上4枚から コスト4以上のカードが手札に加わっていない"


def test_eb02_058_aaassu_trigger_fires_main():
    """トリガー: fire_self_effect で【メイン】効果 (上4枚サーチ) が発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-058", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-058"), sickness=False))
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "トリガー経由で メイン効果 (サーチ) が発動していない"


def test_eb02_058_aaassu_main_human_search_modal():
    """人間: 上4枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-058", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "人間が選んだ コスト4以上カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-059 お前がいねェと…!! (EVENT): 【カウンター】自リーダー/キャラ1枚 このバトル +1000 →
#    その後 自ライフ1以下なら 手札から 黄《麦わらの一味》cost5以下 か「サンジ」1枚まで 登場
# --------------------------------------------------------------------------- #
def test_eb02_059_counter_pump_ai():
    """カウンター(1): 自リーダーかキャラ1枚 このバトル +1000 (AI 既定=リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB01-001", overlay)  # サンジ (麦わらの一味 leader)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB02-059", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 1000, \
        f"カウンターの +1000 が自リーダーに反映されていない: {me.leader.power}"


def test_eb02_059_counter_play_from_hand_ai():
    """カウンター(2) (自ライフ1以下): 手札の 黄《麦わらの一味》cost5以下を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")]  # ライフ1 (= self_life_le 1 成立)
    nami = repo.get("OP15-108")  # ナミ 黄 麦わらの一味 cost1 (<=5)
    assert "黄" in nami.color and nami.cost <= 5 \
        and any("麦わらの一味" in f for f in (nami.features or ()))
    me.hand = [nami]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB02-059", "counter", needle="play_from_hand")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-059"), sickness=False))
    assert any(c.card.card_id == "OP15-108" for c in me.characters), \
        "手札の 黄《麦わらの一味》cost5以下キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_eb02_059_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +1000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "EB02-059", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain_choices(st)
    assert friend.power == friend_before + 1000, \
        "人間が選んだキャラに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB02-060 ゴーイング・メリー号 (STAGE): 【起動メイン】自レスト + 自ライフ上1枚 表向き →
#    自《麦わらの一味》キャラ1枚まで 次の相手ターン終了時まで +1000
# --------------------------------------------------------------------------- #
def test_eb02_060_going_merry_activate_main_pump_ai():
    """起動メイン (レスト + ライフ表向きコスト): 自麦わらキャラを +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB01-001", overlay)  # 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]
    merry = InPlay.of(repo.get("EB02-060"), sickness=False)  # STAGE
    me.stages = [merry]
    me.life = [repo.get("ST01-004")] * 2  # 表向きにできる裏ライフあり
    me.face_up_life_count = 0
    friend = InPlay.of(repo.get("OP15-108"), sickness=False)  # ナミ 麦わらの一味
    assert "麦わらの一味" in (friend.card.features or "")
    me.characters = [friend]

    power_before = friend.power
    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-060"]
    assert len(mine) == 1, f"EB02-060 の起動メインが legal に出ない: {len(mine)}"
    fire_activate_main(st, me, opp, *mine[0])

    assert merry.rested is True, "起動メインコストで ステージがレストされるべき"
    assert me.face_up_life_count == 1, "コストで自ライフ1枚が表向きになるべき"
    assert friend.power == power_before + 1000, \
        f"自麦わらキャラへの +1000 が反映されていない: {friend.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  EB02-061 モンキー・D・ルフィ: 常在(多色リーダー&相手ドン5+で【速攻】) /
#    【アタック時】【ターン1回】アクティブドン2をドンデッキへ → 自身アクティブ + 自ライフ上1枚を手札
# --------------------------------------------------------------------------- #
def test_eb02_061_luffy_static_speed_when_multicolor_leader():
    """常在: 自リーダーが多色の場合 self に【速攻】付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB04-001", overlay)  # ジュエリー・ボニー (赤/黄 = 多色)
    me, opp = st.players[0], st.players[1]
    assert eval_condition({"leader_color_multi": True}, st, me) is True, \
        "多色 leader で leader_color_multi が成立していない"

    luffy = InPlay.of(repo.get("EB02-061"), sickness=False)
    me.characters = [luffy]
    do, _ = _do(overlay, "EB02-061", "on_attached_don")
    for prim in do:
        execute_effect(prim, st, me, opp, luffy)
    assert "速攻" in luffy.granted_keywords, "常在の【速攻】付与が反映されていない"


def test_eb02_061_luffy_on_attack_untap_and_life_to_hand_ai():
    """アタック時: 自身をアクティブに戻し 自ライフ上1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB04-001", overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("EB02-061"), sickness=False)
    luffy.rested = True  # アタック後を模擬 → untap で戻る
    me.characters = [luffy]
    me.life = [repo.get("OP01-016"), repo.get("ST01-004")]  # ライフ2

    hand_before = len(me.hand)
    life_before = len(me.life)
    do, _ = _do(overlay, "EB02-061", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, luffy)
    assert luffy.rested is False, "アタック時効果で 自身がアクティブに戻っていない"
    assert len(me.hand) == hand_before + 1, "自ライフ上1枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "自ライフが1枚減っていない"
