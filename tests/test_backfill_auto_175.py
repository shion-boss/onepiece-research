# -*- coding: utf-8 -*-
"""カード効果 回帰テスト バックフィル (自動生成 wave 175):
ST11-002 / ST11-003 / ST11-004 / ST11-005 /
ST12-002 / ST12-003 / ST12-006 / ST12-007 / ST12-008 / ST12-010 の 10 枚
(= ST11 緑「ウタ / FILM」 + ST12 緑「シモツキ村 / 東の海」 + 青 イワンコフ の効果カード群)。

目的 (= test_backfill_auto_001〜174.py と同一方針):
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
NAMI = "OP01-016"       # ナミ (cost1 power2000 麦わらの一味) フィラー / 相手キャラ
SANJI = "OP01-013"      # サンジ (cost2 power3000 麦わらの一味) フィラー / cost2 char
LEADER = "OP01-001"     # ロロノア・ゾロ (緑 LEADER)
UTA_LEADER = "ST11-001"  # ウタ (緑 FILM LEADER) — ST11 の leader_name 条件用
KARINA = "EB03-004"     # カリーナ (cost3 power2000 FILM) — FILM untap 対象
ZORO_ZAN = "PRB02-006"  # ロロノア・ゾロ (cost4 斬 麦わらの一味) — 斬属性 cost4 素材
FILM_EVENT = "ST11-004"  # 新時代 (cost1 EVENT 音楽/FILM) — 捨てコスト用 EVENT


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
def test_all_wave175_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST11-002", "ST11-003", "ST11-004", "ST11-005",
           "ST12-002", "ST12-003", "ST12-006", "ST12-007", "ST12-008", "ST12-010"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST11-002 ウタ (CHARACTER 緑 cost3 power4000 FILM):
#    【ブロッカー】【自分のターン終了時】自分の手札からイベント1枚を捨てることができる：
#    自分の特徴《FILM》を持つキャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_st11_002_end_of_turn_discard_event_untap_film_ai():
    """【ターン終了時】手札のイベント1枚を捨て → FILM キャラ1枚をアクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    karina = InPlay.of(repo.get(KARINA), sickness=False)  # FILM
    karina.rested = True
    me.characters = [karina]
    me.hand = [repo.get(FILM_EVENT)]  # 捨てる EVENT 1 枚
    me.trash = []

    eff = _eff(overlay, "ST11-002", "end_of_turn")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST11-002"), sickness=False))
    _drain(st, [1])  # 万一 confirm が立っても pay して解決

    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"
    assert karina.rested is False, "FILM キャラがアクティブになっていない"
    assert len(me.hand) == 0, "コストの EVENT が手札から捨てられていない"
    assert any(c.card_id == FILM_EVENT for c in me.trash), \
        "捨てた EVENT がトラッシュにない"


def test_st11_002_end_of_turn_human_optional_cost_confirm():
    """人間 actor: 任意コストは optional_cost_confirm modal が立ち、 pay で FILM を untap。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    karina = InPlay.of(repo.get(KARINA), sickness=False)
    karina.rested = True
    me.characters = [karina]
    me.hand = [repo.get(FILM_EVENT)]

    eff = _eff(overlay, "ST11-002", "end_of_turn")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST11-002"), sickness=False))

    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert karina.rested is False, "承諾後 FILM キャラがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  ST11-003 逆光 (EVENT 緑 cost2 音楽/FILM):
#    【メイン】自分のリーダーが「ウタ」の場合、以下から1つを選ぶ。
#    ・相手のコスト5以下のキャラ1枚までを、レストにする。
#    ・相手のレストのコスト5以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st11_003_main_choice_ai_no_crash():
    """AI: メイン choice_effect → 自動で 1 択を発動し crash / modal 残しなし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 active
    opp.characters = [victim]

    eff = _eff(overlay, "ST11-003", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"


def test_st11_003_main_rest_option_ai():
    """option 0 (相手コスト5以下を レスト) の do を直接発火 → 対象がレストされる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=5) active
    victim.rested = False
    opp.characters = [victim]

    eff = _eff(overlay, "ST11-003", "main")
    opts = eff["do"][0]["choice_effect"]["options"]
    for prim in opts[0]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim.rested is True, "相手のコスト5以下キャラがレストされていない"


def test_st11_003_main_ko_option_ai():
    """option 1 (相手のレスト コスト5以下を KO) の do を直接発火 → 対象が KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=5)
    victim.rested = True  # レスト = KO 対象
    opp.characters = [victim]

    eff = _eff(overlay, "ST11-003", "main")
    opts = eff["do"][0]["choice_effect"]["options"]
    for prim in opts[1]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "相手のレスト コスト5以下キャラが KO されていない"


def test_st11_003_main_choice_human_option_pick():
    """人間: メイン → option_pick modal が 2 択で立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)
    opp.characters = [victim]

    eff = _eff(overlay, "ST11-003", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 choice で modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("options", [])) == 2, \
        f"2 択の option が立っていない: {st.pending_choice.get('options')}"
    resolve_pending_choice(st, [0])  # レスト option
    _drain(st, [0])
    assert st.pending_choice is None, "解決後も modal が残る"


# --------------------------------------------------------------------------- #
#  ST11-004 新時代 (EVENT 緑 cost1 音楽/FILM):
#    【メイン】自分のリーダーが「ウタ」の場合、自分のデッキの上から3枚を見て、
#    「新時代」以外の特徴《FILM》を持つカード1枚までを公開し、手札に加える。
#    その後、残りを好きな順番でデッキの下に置き、自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_st11_004_main_search_film_and_untap_don_ai():
    """【メイン】デッキ上3枚から FILM カード1枚を手札 + レストドン1枚をアクティブ化 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    film = repo.get(KARINA)  # FILM (「新時代」以外)
    me.deck = [film] + [repo.get(SANJI)] * 20
    me.hand = []
    me.don_rested = 1
    me.don_active = 0

    eff = _eff(overlay, "ST11-004", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert any(c.card_id == KARINA for c in me.hand), \
        "デッキ上3枚から FILM カードが手札に加わっていない"
    assert me.don_active == 1, f"ドン1枚がアクティブ化されていない: active={me.don_active}"
    assert me.don_rested == 0, "レストドンが1枚消費されるべき"


def test_st11_004_main_search_human_pick():
    """人間 + デッキ上3枚に FILM 複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    film = repo.get(KARINA)
    me.deck = [film, repo.get(SANJI), film] + [repo.get(SANJI)] * 15
    me.hand = []
    me.don_rested = 1

    eff = _eff(overlay, "ST11-004", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (カリーナ) を選択
    _drain(st, [])
    assert any(c.card_id == KARINA for c in me.hand), \
        "人間が選んだ FILM カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST11-005 私は最強 (EVENT 緑 cost3 音楽/FILM):
#    【メイン】自分のリーダーの「ウタ」1枚までを、アクティブにする。
#    【トリガー】自分のリーダーかキャラ1枚までを、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_st11_005_main_untap_leader_ai():
    """【メイン】自リーダー (ウタ) をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True

    eff = _eff(overlay, "ST11-005", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.rested is False, "自リーダーがアクティブになっていない"


def test_st11_005_trigger_leader_pump_ai():
    """【トリガー】自リーダー1枚に +1000 (AI 既定: 最大パワー = リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST11-005", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, \
        f"トリガーで自リーダー +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  ST12-002 くいな (CHARACTER 緑 cost3 power2000 シモツキ村):
#    【起動メイン】このキャラをレストにできる：相手のコスト4以下のキャラ1枚までを、レストにする。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_st12_002_activate_main_rest_opp_ai():
    """起動メイン: 自身をレスト (コスト) → 相手コスト4以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    kuina = InPlay.of(repo.get("ST12-002"), sickness=False)
    me.characters = [kuina]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=4) active バニラ
    victim.rested = False
    opp.characters = [victim]

    options = list_activate_main_effects(st, me, overlay)
    kuina_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "ST12-002"]
    assert len(kuina_opts) == 1, \
        f"ST12-002 の起動メインが legal に出ない: {len(kuina_opts)}"
    fire_activate_main(st, me, opp, *kuina_opts[0])
    _drain(st)

    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"
    assert kuina.rested is True, "起動メインコストで くいな がレストされるべき"


def test_st12_002_trigger_play_self_ai():
    """【トリガー】このカードを登場させる → 手札の くいな が場に出る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST12-002")]
    st.current_source_card_id = "ST12-002"

    chars_before = len(me.characters)
    eff = _eff(overlay, "ST12-002", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "ST12-002" for c in me.characters), \
        "トリガー play_self で くいな が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  ST12-003 ジュラキュール・ミホーク (CHARACTER 緑 cost3 power4000 王下七武海/シッケアール王国):
#    【登場時】自分のキャラが2枚以下の場合、自分の手札から「ジュラキュール・ミホーク」以外で、
#    コスト4以下の、特徴《シッケアール王国》か属性(斬)を持つキャラカード1枚までを、レストで登場させる。
# --------------------------------------------------------------------------- #
def test_st12_003_on_play_play_from_hand_ai():
    """【登場時】手札から 斬 or シッケアール王国 cost4以下キャラをレストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    mihawk = InPlay.of(repo.get("ST12-003"), sickness=True)
    me.characters = [mihawk]  # field count 1 (<= 2)
    me.hand = [repo.get(ZORO_ZAN)]  # 斬 cost4 キャラ

    chars_before = len(me.characters)
    eff = _eff(overlay, "ST12-003", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, mihawk)
    _drain(st, [0])

    played = [c for c in me.characters if c.card.card_id == ZORO_ZAN]
    assert played, "手札から 斬 cost4 キャラが登場していない"
    assert played[0].rested is True, "登場したキャラはレスト状態であるべき"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_st12_003_on_play_human_play_pick():
    """人間 + 手札に該当キャラ 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mihawk = InPlay.of(repo.get("ST12-003"), sickness=True)
    me.characters = [mihawk]
    me.hand = [repo.get(ZORO_ZAN), repo.get(ZORO_ZAN)]  # 斬 cost4 を2枚

    eff = _eff(overlay, "ST12-003", "on_play")
    execute_effect(eff["do"][0], st, me, opp, mihawk)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id == ZORO_ZAN for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  ST12-006 ヨサク＆ジョニー (CHARACTER 緑 cost2 power3000 東の海):
#    【ドン!!×1】【アタック時】以下から1つを選ぶ。
#    ・相手のコスト2以下のキャラ1枚までを、レストにする。
#    ・相手のレストのコスト2以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st12_006_on_attack_choice_ai_no_crash():
    """AI: アタック時 choice_effect → 自動で 1 択を発動し crash / modal 残しなし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (<=2) active
    opp.characters = [victim]

    eff = _eff(overlay, "ST12-006", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-006"), sickness=False))
    _drain(st, [0])
    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"


def test_st12_006_on_attack_rest_option_ai():
    """option 0 (相手コスト2以下を レスト) の do を直接発火 → 対象がレストされる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 active
    victim.rested = False
    opp.characters = [victim]

    eff = _eff(overlay, "ST12-006", "on_attack")
    opts = eff["do"][0]["choice_effect"]["options"]
    for prim in opts[0]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim.rested is True, "相手のコスト2以下キャラがレストされていない"


def test_st12_006_on_attack_ko_option_ai():
    """option 1 (相手のレスト コスト2以下を KO) の do を直接発火 → 対象が KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (<=2)
    victim.rested = True
    opp.characters = [victim]

    eff = _eff(overlay, "ST12-006", "on_attack")
    opts = eff["do"][0]["choice_effect"]["options"]
    for prim in opts[1]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "相手のレスト コスト2以下キャラが KO されていない"


def test_st12_006_on_attack_choice_human_option_pick():
    """人間: アタック時 → option_pick modal が 2 択で立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)
    opp.characters = [victim]

    eff = _eff(overlay, "ST12-006", "on_attack")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 choice で modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("options", [])) == 2, \
        f"2 択の option が立っていない: {st.pending_choice.get('options')}"


# --------------------------------------------------------------------------- #
#  ST12-007 リカ (CHARACTER 緑 cost2 power- 東の海):
#    【登場時】➁(コストエリアのドン!!を指定の数レストにできる)：相手のライフが3枚以上の場合、
#    自分のコスト4以下の属性(斬)を持つキャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_st12_007_on_play_optional_cost_untap_zan_ai():
    """【登場時】ドン2レスト (任意コスト) → 自分の 斬 cost4以下キャラ1枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.don_rested = 0
    opp.life = [repo.get(SANJI)] * 3  # 相手ライフ 3 (= 条件成立)
    zan = InPlay.of(repo.get(ZORO_ZAN), sickness=False)  # 斬 cost4
    zan.rested = True
    me.characters = [zan]

    eff = _eff(overlay, "ST12-007", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-007"), sickness=True))
    _drain(st, [1])  # 万一 confirm が立っても pay して解決

    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"
    assert zan.rested is False, "斬 cost4以下キャラがアクティブになっていない"
    assert me.don_rested == 2, f"コストで2ドンがレストされていない: {me.don_rested}"
    assert me.don_active == 1, f"active ドンが2枚消費されるべき: {me.don_active}"


def test_st12_007_on_play_human_optional_cost_confirm():
    """人間 actor: 任意コストは optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    opp.life = [repo.get(SANJI)] * 3
    zan = InPlay.of(repo.get(ZORO_ZAN), sickness=False)
    zan.rested = True
    me.characters = [zan]

    eff = _eff(overlay, "ST12-007", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST12-007"), sickness=True))

    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert zan.rested is False, "承諾後 斬 cost4以下キャラがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  ST12-008 ロロノア・ゾロ (CHARACTER 緑 cost4 power6000 麦わらの一味):
#    【ドン!!×1】【アタック時】相手のコスト6以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_st12_008_on_attack_rest_opp_ai():
    """【アタック時】(ドン1ゲート) 相手コスト6以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=6) active バニラ
    victim.rested = False
    opp.characters = [victim]

    eff = _eff(overlay, "ST12-008", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-008"), sickness=False))
    _drain(st)

    assert victim.rested is True, "相手のコスト6以下キャラがレストされていない"


def test_st12_008_on_attack_rest_human_pick():
    """人間 + 相手コスト6以下キャラ 複数 → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(SANJI), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    eff = _eff(overlay, "ST12-008", "on_attack")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  ST12-010 エンポリオ・イワンコフ (CHARACTER 青 cost3 power4000 インペルダウン/革命軍):
#    【登場時】自分のデッキの上から1枚を公開し、コスト2のキャラカード1枚までを、登場させる。
#    その後、残りをデッキの上か下に置く。
#    【アタック時】【ターン1回】自分の手札が6枚以下の場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_st12_010_on_play_reveal_top_play_ai():
    """【登場時】デッキ上1枚を公開 → コスト2キャラなら登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(SANJI)] + [repo.get(NAMI)] * 20  # top = サンジ cost2 CHARACTER
    me.characters = []

    eff = _eff(overlay, "ST12-010", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-010"), sickness=True))
    _drain(st, [0])

    assert any(c.card.card_id == SANJI for c in me.characters), \
        "デッキ上のコスト2キャラが登場していない"


def test_st12_010_on_play_reveal_human_confirm():
    """人間 + デッキ上がコスト2キャラ → reveal_top_play_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(SANJI)] + [repo.get(NAMI)] * 20
    me.characters = []

    eff = _eff(overlay, "ST12-010", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST12-010"), sickness=True))

    assert st.pending_choice is not None, "人間で reveal_top_play modal が立たない"
    assert st.pending_choice.get("kind") == "reveal_top_play_confirm", \
        f"kind が reveal_top_play_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 登場させる
    _drain(st, [0])
    assert any(c.card.card_id == SANJI for c in me.characters), \
        "人間承諾後 コスト2キャラが登場していない"


def test_st12_010_on_attack_draw_ai():
    """【アタック時】自手札6枚以下 → カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(NAMI)] * 3  # 3 枚 (<= 6)
    me.deck = [repo.get(SANJI)] * 10

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    eff = _eff(overlay, "ST12-010", "on_attack")
    assert eff.get("if", {}).get("self_hand_count_le") == 6, \
        "overlay の 条件 self_hand_count_le=6 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-010"), sickness=False))

    assert len(me.hand) == hand_before + 1, "アタック時に1枚引けていない"
    assert len(me.deck) == deck_before - 1, "山札が1枚減っていない"
