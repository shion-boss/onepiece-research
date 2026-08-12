# -*- coding: utf-8 -*-
"""OP12 弾 (レイリー軸 赤 / ゾロ軸 緑) 効果 回帰テスト
バックフィル (自動生成 wave 118):
OP12-013 / OP12-014 / OP12-015 / OP12-016 / OP12-017 / OP12-018 /
OP12-019 / OP12-020 / OP12-021 / OP12-022 の 10 枚。

  OP12-013 はっちゃん (CHARACTER 赤) = 【起動メイン】このキャラをレストにし 手札のイベント2枚を
     公開：自リーダーかキャラ1枚に レストドン2枚まで付与
     (activate_main optional_cost_then [rest_self + reveal_hand EVENT×2] → attach_rested_don ×2)
  OP12-014 ボア・ハンコック (CHARACTER 赤) = 【登場時】デッキ上5枚→「ルフィ」か赤イベント1枚を手札 /
     【起動メイン】このキャラをトラッシュ：自リーダーかキャラに レストドン2枚まで付与
     (on_play search_top_n depth5 / activate_main attach_rested_don cost trash_self)
  OP12-015 モンキー・Ｄ・ルフィ (CHARACTER 赤) = 付与ドン合計2以上で +2000 (static) /
     【登場時】手札イベント2公開：手札から赤power3000以下キャラ1枚登場 + レストドン1付与
     (static on_attached_don self_attached_don_ge2 / on_play optional_cost_then play_from_hand)
  OP12-016 “疑わない事”それが“強さ”だ!!! (EVENT 赤) = 【メイン】レイリーにアクティブドン2付与：
     ブロッカー封じ /【カウンター】自キャラかレイリー1枚 +2000
     (main attach_active_don_to_named_chara / counter power_pump one_self_character_any +2000)
  OP12-017 見聞色の覇気 (EVENT 赤) = 【メイン】デッキ上4枚→赤イベントかコスト3以上キャラ1枚を手札
     (main search_top_n depth4 cost_ge3)
  OP12-018 覇王色の覇気 (EVENT 赤) = 【カウンター】自キャラかレイリー +2000 → 自ドン1レストで
     相手リーダー/キャラ全て -1000
     (counter power_pump レイリー +2000 / optional rest_self_don → all_opp -1000)
  OP12-019 武装色の覇気 (EVENT 赤) = 【メイン】レイリーにアクティブドン1付与：自リーダー/キャラ +1000 /
     【カウンター】自キャラかレイリー +2000
     (main optional attach_active_don+power_pump / counter power_pump +2000)
  OP12-020 ロロノア・ゾロ (LEADER 緑) = 【ドン‼×3】【起動メイン】【ターン1回】バトル中なら自リーダーを
     アクティブに → このターン 相手の元々コスト7以下キャラへアタック不可
     (activate_main untap self_leader + set_cannot_attack_target_cost_le7, if don_ge3, once/turn)
  OP12-021 いっぽんマツ (CHARACTER 緑) = リーダー属性(斬)+レストドン6以上なら 相手効果でレストされない
     【ブロッカー】 (static set_cannot_be_rested_static → protect_from_opp_effect)
  OP12-022 イヌアラシ (CHARACTER 緑) = 【起動メイン】このキャラをレスト：相手レストのコスト5以下キャラ
     1枚は 次の相手リフレッシュでアクティブにならない
     (activate_main stay_rested_next_refresh one_opponent_rested_character_cost_le_5)

目的 (= test_backfill_auto_001〜117.py と同一方針):
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
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GENERIC = "OP01-001"   # ロロノア・ゾロ (超新星/麦わらの一味 — 汎用埋め)
_LEADER_ZAN = "OP12-020"       # ロロノア・ゾロ LEADER 緑 (属性 斬)
_FILLER = "ST01-004"           # サンジ cost2 power4000 (麦わらの一味)
_FILLER_P1000 = "OP16-043"     # ウソップ cost2 power1000
_RED_EVENT = "EB04-008"        # 歪んだ未来 (赤 EVENT)
_RAYLEIGH = "ST32-004"         # シルバーズ・レイリー cost4 power5000 (CHARACTER、 緑)
# ⚠ 2026-08-12: OP12-017 のサーチ filter は公式どおり 「**赤の**イベントか **赤の**
#   コスト3以上のキャラカード」 (cardqa_op_12)。 緑のレイリーは **サーチ対象外** なので、
#   サーチ先には赤のコスト4キャラを使う (レイリーはコスト支払い用に場へ置くだけ)。
_RED_C4 = "EB02-002"           # サボ cost4 (CHARACTER、 赤)
_LUFFY_SMALL = "ST23-004"      # モンキー・Ｄ・ルフィ 赤 cost1 power2000


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


def _drain(st, pick=None, guard=10):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave118_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-013", "OP12-014", "OP12-015", "OP12-016", "OP12-017",
           "OP12-018", "OP12-019", "OP12-020", "OP12-021", "OP12-022"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-013 はっちゃん: 【起動メイン】自レスト+手札イベント2公開 → 自リーダー/キャラに レストドン2付与
# --------------------------------------------------------------------------- #
def test_op12_013_activate_main_attach_two_rested_don_ai():
    """起動メイン: 自レスト + 手札イベント2公開 のコストを払い 自リーダーへ レストドン2付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    hachi = InPlay.of(repo.get("OP12-013"), sickness=False)
    me.characters = [hachi]
    me.don_rested = 2  # レストドン供給源
    me.hand = [repo.get(_RED_EVENT), repo.get(_RED_EVENT)]  # 公開用イベント2枚

    don_before = me.leader.attached_dons
    hand_before = len(me.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-013"]
    assert len(opts) == 1, f"OP12-013 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 2, \
        "起動メインで自リーダーにレストドンが2枚付与されていない"
    assert me.don_rested == 0, "レストドンが2枚消費されるべき"
    assert hachi.rested is True, "コストで はっちゃん がレストされるべき"
    assert len(me.hand) == hand_before, "イベントは公開のみ (捨てない) で手札は減らない"


def test_op12_013_activate_main_needs_two_events():
    """手札に公開できるイベントが1枚のみ (< 2) なら 任意コスト不能 → 発動しても付与が起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    hachi = InPlay.of(repo.get("OP12-013"), sickness=False)
    me.characters = [hachi]
    me.don_rested = 2
    me.hand = [repo.get(_RED_EVENT)]  # イベント1枚のみ = 不足

    don_before = me.leader.attached_dons
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-013"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert me.leader.attached_dons == don_before, \
        "イベント2枚無い (コスト不能) のにレストドンが付与されてはいけない"
    assert hachi.rested is False, "コスト不能なら はっちゃん もレストされないべき"


def test_op12_013_activate_main_human_target_pick():
    """人間: 任意コスト承諾 → 付与先 (リーダー/キャラ) の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hachi = InPlay.of(repo.get("OP12-013"), sickness=False)
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [hachi, friend]
    me.don_rested = 2
    me.hand = [repo.get(_RED_EVENT), repo.get(_RED_EVENT)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-013"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間で任意コスト confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # コストを払う (承諾)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"承諾後に付与先 target_pick が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    li = next(i for i, c in enumerate(cands) if c["iid"] == me.leader.instance_id)
    resolve_pending_choice(st, [li])
    _drain(st, [0])
    assert me.leader.attached_dons == 2, \
        "人間が選んだ自リーダーにレストドン2枚が付与されていない"


# --------------------------------------------------------------------------- #
#  OP12-014 ボア・ハンコック: 【登場時】上5枚→ルフィ/赤イベント1枚を手札 /
#                             【起動メイン】自トラッシュ → 自リーダー/キャラに レストドン2付与
# --------------------------------------------------------------------------- #
def test_op12_014_on_play_search_ai():
    """【登場時】デッキ上5枚を見て「ルフィ」か赤イベント1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_RED_EVENT)] + [repo.get(_FILLER)] * 20  # 上に赤イベント

    for prim in _eff(overlay, "OP12-014", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-014"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == _RED_EVENT for c in me.hand), \
        "デッキ上5枚から 赤イベントが手札に加わっていない"


def test_op12_014_on_play_search_human_pick():
    """人間 + デッキ上5枚に赤イベント → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_RED_EVENT), repo.get(_FILLER), repo.get(_LUFFY_SMALL)] \
        + [repo.get(_FILLER)] * 15

    execute_effect(_eff(overlay, "OP12-014", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP12-014"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (赤イベント) を選択
    _drain(st, [])
    assert any(c.card_id == _RED_EVENT for c in me.hand), \
        "人間が選んだ 赤イベントが手札に加わっていない"


def test_op12_014_activate_main_trash_self_attach_don_ai():
    """起動メイン: このキャラをトラッシュ → 自リーダーへ レストドン2付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    hancock = InPlay.of(repo.get("OP12-014"), sickness=False)
    me.characters = [hancock]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-014"]
    assert len(opts) == 1, f"OP12-014 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 2, \
        "起動メインで自リーダーにレストドン2枚が付与されていない"
    assert hancock not in me.characters, "コストで ハンコック がトラッシュに置かれるべき"
    assert any(c.card_id == "OP12-014" for c in me.trash), \
        "ハンコックがトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP12-015 モンキー・Ｄ・ルフィ: 付与ドン2以上で +2000 (static) /
#                                 【登場時】手札イベント2公開 → 赤power3000以下キャラ登場
# --------------------------------------------------------------------------- #
def test_op12_015_static_pump_two_attached_don():
    """付与ドン合計2枚以上で このキャラ +2000 (static)。
    盤面 power = 素power + ドン付与分(2×1000) + 静的+2000 = 素+4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    luffy_def = repo.get("OP12-015")  # power 4000
    luffy = InPlay.of(luffy_def, sickness=False)
    luffy.attached_dons = 2
    me.characters = [luffy]

    evaluate_static_effects(st, overlay)
    assert luffy.power == luffy_def.power + 4000, \
        f"付与ドン2で 静的+2000 (+ドン+2000) が乗っていない: {luffy.power} (base {luffy_def.power})"


def test_op12_015_static_no_pump_one_don():
    """付与ドンが1枚のみなら 静的条件 (合計2以上) 不成立 → +2000 は乗らない。
    盤面 power = 素power + ドン付与分(1×1000) のみ = 素+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    luffy_def = repo.get("OP12-015")
    luffy = InPlay.of(luffy_def, sickness=False)
    luffy.attached_dons = 1
    me.characters = [luffy]

    evaluate_static_effects(st, overlay)
    assert luffy.power == luffy_def.power + 1000, \
        f"付与ドン1で 静的+2000 が乗ってはいけない: {luffy.power} (base {luffy_def.power})"


def test_op12_015_on_play_reveal_events_play_chara_ai():
    """【登場時】手札イベント2公開 → 手札の赤power3000以下キャラ1枚を登場 + レストドン1付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_RED_EVENT), repo.get(_RED_EVENT), repo.get(_LUFFY_SMALL)]
    me.don_rested = 2

    chars_before = len(me.characters)
    don_before = me.leader.attached_dons
    for prim in _eff(overlay, "OP12-015", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-015"), sickness=True))
    _drain(st, [0])

    assert any(c.card.card_id == _LUFFY_SMALL for c in me.characters), \
        "手札から 赤power3000以下キャラ (ルフィ) が登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"
    assert me.leader.attached_dons == don_before + 1, \
        "登場後に 自リーダーへ レストドン1が付与されていない"


# --------------------------------------------------------------------------- #
#  OP12-016 “疑わない事”それが“強さ”だ!!! (EVENT): メイン レイリー付与 / カウンター +2000
# --------------------------------------------------------------------------- #
def test_op12_016_main_attach_active_don_to_rayleigh_ai():
    """【メイン】自分の「シルバーズ・レイリー」にアクティブドン2枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get(_RAYLEIGH), sickness=False)
    me.characters = [rayleigh]
    me.don_active = 2

    for prim in _eff(overlay, "OP12-016", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert rayleigh.attached_dons == 2, \
        f"レイリーにアクティブドン2が付与されていない: {rayleigh.attached_dons}"
    assert me.don_active == 0, "アクティブドンが2枚消費されるべき"


def test_op12_016_counter_pump_ai():
    """【カウンター】自キャラかレイリー1枚まで このバトル中 +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [c]

    power_before = c.power
    for prim in _eff(overlay, "OP12-016", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert c.power == power_before + 2000, \
        f"カウンターの +2000 が自キャラに反映されていない: {c.power}"


def test_op12_016_counter_pump_human_pick():
    """人間 + 自キャラ複数 → target_pick modal → resolve で 1 体に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)
    me.characters = [a, b]

    execute_effect(_eff(overlay, "OP12-016", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.power == b_before + 2000, "人間が選んだ自キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-017 見聞色の覇気 (EVENT): 【メイン】上4枚 → 赤イベント/コスト3以上キャラ1枚を手札
# --------------------------------------------------------------------------- #
def test_op12_017_main_search_ai():
    """【メイン】デッキ上4枚を見て コスト3以上キャラ1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_RED_C4)] + [repo.get(_FILLER)] * 20  # 上に **赤の** cost4 キャラ
    # ⚠ 公式 「【メイン】自分の「シルバーズ・レイリー」1枚にアクティブのドン‼1枚を付与する
    #   ことができる：…」 = コロン前が発動コスト (cardqa_st_06、 2026-08-05 に実装)。
    rayleigh = InPlay.of(repo.get(_RAYLEIGH), sickness=False)
    me.characters = [rayleigh]
    me.don_active = 1

    for prim in _eff(overlay, "OP12-017", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == _RED_C4 for c in me.hand), \
        "デッキ上4枚から **赤の** コスト3以上キャラが手札に加わっていない"
    assert rayleigh.attached_dons == 1, "コスト (レイリーにアクティブドン1枚付与) が払われていない"
    assert me.don_active == 0, "アクティブドンが消費されていない"


def test_op12_017_main_not_free_without_rayleigh():
    """⚠ 対照: 「シルバーズ・レイリー」 が場に無ければ サーチしない (= タダ撃ち禁止)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_RAYLEIGH)] + [repo.get(_FILLER)] * 20
    me.don_active = 1   # ドンはあるがレイリーが居ない

    for prim in _eff(overlay, "OP12-017", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert not me.hand, "レイリーが居ないのにサーチが発動している"


def test_op12_017_search_filter_excludes_non_red_event():
    """公式 filter = 「**赤の**イベント か コスト3以上の**キャラカード**」。

    是正前は `{"cost_ge": 3}` だけで、 コスト3以上の **イベント/ステージ** も引けていた。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # デッキ上に 「コスト3以上のイベント (赤以外)」 だけ → 公式 filter では引けない
    non_red_event = repo.get("OP06-058")   # 青 EVENT cost7
    assert non_red_event.category.value == "EVENT" and "赤" not in non_red_event.color \
        and int(non_red_event.cost) >= 3, \
        f"テスト前提: OP06-058 は コスト3以上の非赤イベント (実際 {non_red_event.color}/{non_red_event.cost})"
    me.deck = [repo.get(non_red_event.card_id)] * 4 + [repo.get(_FILLER)] * 16
    me.characters = [InPlay.of(repo.get(_RAYLEIGH), sickness=False)]
    me.don_active = 1

    for prim in _eff(overlay, "OP12-017", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert not any(c.card_id == non_red_event.card_id for c in me.hand), \
        f"赤でないイベント ({non_red_event.card_id}) が引けてしまっている"


def test_op12_017_main_search_human_pick():
    """人間 + デッキ上4枚に コスト3以上キャラ → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_RED_C4), repo.get(_FILLER_P1000)] + [repo.get(_FILLER)] * 15
    me.characters = [InPlay.of(repo.get(_RAYLEIGH), sickness=False)]
    me.don_active = 1

    execute_effect(_eff(overlay, "OP12-017", "main")["do"][0], st, me, opp, None)
    # コロン前が発動コストなので、 人間はまず 払う/見送る を選ぶ
    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"任意コスト確認 modal が先に立たない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])   # 払う
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id == _RED_C4 for c in me.hand), \
        "人間が選んだ **赤の** コスト3以上キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-018 覇王色の覇気 (EVENT): 【カウンター】自キャラ/レイリー +2000 → 自ドン1レストで 相手全体 -1000
# --------------------------------------------------------------------------- #
def test_op12_018_counter_pump_and_debuff_ai():
    """【カウンター】レイリー +2000 → 自ドン1レストで 相手リーダーとキャラ全て -1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get(_RAYLEIGH), sickness=False)
    me.characters = [rayleigh]
    me.don_active = 1  # rest_self_don 用
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    ray_before = rayleigh.power
    vic_before = victim.power
    opp_leader_before = opp.leader.power
    for prim in _eff(overlay, "OP12-018", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert rayleigh.power == ray_before + 2000, \
        f"カウンターの +2000 がレイリーに反映されていない: {rayleigh.power}"
    assert victim.power == vic_before - 1000, \
        f"相手キャラ -1000 が反映されていない: {victim.power}"
    assert opp.leader.power == opp_leader_before - 1000, \
        f"相手リーダー -1000 が反映されていない: {opp.leader.power}"


def test_op12_018_counter_debuff_needs_active_don():
    """アクティブドンが無ければ rest_self_don の任意コスト不能 → 相手全体 -1000 は起きない
    (レイリーへの +2000 は前段で成立する)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get(_RAYLEIGH), sickness=False)
    me.characters = [rayleigh]
    me.don_active = 0  # rest_self_don 用のアクティブドン無し
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    ray_before = rayleigh.power
    vic_before = victim.power
    for prim in _eff(overlay, "OP12-018", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert rayleigh.power == ray_before + 2000, "レイリー +2000 は成立するべき"
    assert victim.power == vic_before, \
        "アクティブドン無し (コスト不能) で 相手キャラ -1000 が起きてはいけない"


# --------------------------------------------------------------------------- #
#  OP12-019 武装色の覇気 (EVENT): 【メイン】レイリー付与 → 自リーダー/キャラ +1000 / 【カウンター】 +2000
# --------------------------------------------------------------------------- #
def test_op12_019_main_attach_don_and_pump_ai():
    """【メイン】レイリーにアクティブドン1付与 (コスト) → 自リーダー/キャラ +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get(_RAYLEIGH), sickness=False)
    me.characters = [rayleigh]
    me.don_active = 1

    for prim in _eff(overlay, "OP12-019", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert rayleigh.attached_dons == 1, \
        f"コストで レイリーにアクティブドン1が付与されていない: {rayleigh.attached_dons}"
    assert me.don_active == 0, "アクティブドンが1枚消費されるべき"


def test_op12_019_counter_pump_ai():
    """【カウンター】自キャラかレイリー1枚まで このバトル中 +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    c = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [c]

    power_before = c.power
    for prim in _eff(overlay, "OP12-019", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert c.power == power_before + 2000, \
        f"カウンターの +2000 が自キャラに反映されていない: {c.power}"


def test_op12_019_counter_pump_human_pick():
    """人間 + 自キャラ複数 → target_pick modal → resolve で 1 体に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)
    me.characters = [a, b]

    execute_effect(_eff(overlay, "OP12-019", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.power == b_before + 2000, "人間が選んだ自キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-020 ロロノア・ゾロ (LEADER): 【ドン‼×3】起動メイン 自リーダーをアクティブに + コスト7以下へ攻撃不可
# --------------------------------------------------------------------------- #
def test_op12_020_activate_main_untap_and_restrict_ai():
    """起動メイン (ドン3): 自リーダーをアクティブに → このターン 相手コスト7以下キャラへアタック不可 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZAN, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 3  # 【ドン‼×3】ゲート成立
    me.leader.rested = True       # バトル後 レスト状態を想定
    # ⭐ 公式 (cardqa_op_12) は 「このターン中、 このリーダーが **相手のキャラと** バトルして
    #   いる場合」 が発動条件。 2026-08-10 に overlay へ条件を追加したので、 その前提を作る。
    #   (このテストは条件欠落時の overlay から生成された backfill = 旧仕様を固定していた)
    me.leader_battled_opp_chara_this_turn = True

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-020"]
    assert len(opts) == 1, f"OP12-020 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.rested is False, "起動メインで自リーダーがアクティブになっていない"
    assert me.leader.cannot_attack_target_cost_le_until_turn_end == 7, \
        "相手コスト7以下へのアタック制限が付与されていない"


def test_op12_020_activate_main_don_gate():
    """付与ドンが3未満なら【ドン‼×3】ゲート不成立 → 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZAN, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2  # < 3
    me.leader.rested = True

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-020"]
    assert len(opts) == 0, "ドン3未満で起動メインが legal に出てはいけない"


def test_op12_020_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZAN, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 3
    me.leader.rested = True
    me.leader_battled_opp_chara_this_turn = True  # 公式条件 (cardqa_op_12)、 上と同じ理由

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP12-020"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP12-020"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP12-021 いっぽんマツ (CHARACTER): リーダー属性(斬)+レストドン6以上で 相手効果でレストされない (static)
# --------------------------------------------------------------------------- #
def test_op12_021_static_cannot_be_rested_when_condition_met():
    """リーダー属性(斬) + レストドン6以上 → このキャラは相手の効果でレストされない
    (static_cannot_be_rested)。 公式文言「レストにされない」= rest 限定免疫 (KO/離脱は防がない)。
    旧テストは protect_from_opp_effect (=場を離れない) を検証していたが、 本セッションで公式通り
    set_cannot_be_rested_static に修正済 (rest 免疫であって leave 保護ではない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZAN, overlay)  # OP12-020 leader = 属性 斬
    me, opp = st.players[0], st.players[1]
    matsu = InPlay.of(repo.get("OP12-021"), sickness=False)
    me.characters = [matsu]
    me.don_rested = 6  # レストドン6以上

    evaluate_static_effects(st, overlay)
    assert matsu.static_cannot_be_rested is True, \
        "斬リーダー + レストドン6 で レスト免疫 (static_cannot_be_rested) が付与されていない"


def test_op12_021_static_no_rest_immunity_when_don_insufficient():
    """レストドンが5枚 (< 6) なら 静的条件 不成立 → レスト免疫は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ZAN, overlay)
    me, opp = st.players[0], st.players[1]
    matsu = InPlay.of(repo.get("OP12-021"), sickness=False)
    me.characters = [matsu]
    me.don_rested = 5  # < 6

    evaluate_static_effects(st, overlay)
    assert matsu.static_cannot_be_rested is False, \
        "レストドン5枚 (条件不成立) で レスト免疫が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP12-022 イヌアラシ (CHARACTER): 【起動メイン】自レスト → 相手レストのコスト5以下キャラ stay_rested
# --------------------------------------------------------------------------- #
def test_op12_022_activate_main_stay_rested_ai():
    """起動メイン: 自レスト → 相手のレストのコスト5以下キャラ1枚は 次の相手リフレッシュで
    アクティブにならない (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    inu = InPlay.of(repo.get("OP12-022"), sickness=False)
    me.characters = [inu]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 5
    victim.rested = True  # レスト = 対象
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-022"]
    assert len(opts) == 1, f"OP12-022 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert victim.stay_rested_next_refresh is True, \
        "相手レストキャラに stay_rested_next_refresh が付与されていない"
    assert inu.rested is True, "起動メインコストで イヌアラシ がレストされるべき"


def test_op12_022_activate_main_stay_rested_human_pick():
    """人間 + 相手レストのコスト5以下キャラ複数 → target_pick modal → resolve で1枚に stay_rested。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    inu = InPlay.of(repo.get("OP12-022"), sickness=False)
    me.characters = [inu]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-022"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.stay_rested_next_refresh is True, \
        "人間が選んだレストキャラに stay_rested が付いていない"
    assert a.stay_rested_next_refresh is False, "選ばなかったキャラには付かないべき"


def test_op12_022_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    inu = InPlay.of(repo.get("OP12-022"), sickness=False)
    me.characters = [inu]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    opp.characters = [victim]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP12-022"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP12-022"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"
