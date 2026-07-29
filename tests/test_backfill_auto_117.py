# -*- coding: utf-8 -*-
"""OP11 (黄 しらほし / 魚人島 + 青/黒 8cost) + OP12 (赤 ロジャー海賊団 / イベント連動) 系
効果 回帰テスト バックフィル (自動生成 wave 117):
OP11-115 / OP11-116 / OP11-117 / OP11-118 / OP11-119 /
OP12-004 / OP12-006 / OP12-008 / OP12-009 / OP12-012 の 10 枚。

目的 (= test_backfill_auto_001.py と同一方針):
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
    trigger_on_play,
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
    """指定 card_id の overlay から when 一致の最初の効果の (do リスト, entry) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _do_with(overlay, cid, when, needle):
    """when 一致 + do の要素に needle キーを含む効果の (do, entry) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when and any(needle in prim for prim in e["do"]):
            return e["do"], e
    raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"        # ロロノア・ゾロ (赤 leader、 条件なし汎用)
_SHIRAHOSHI = "OP11-022"     # しらほし (緑/黄 / 人魚族/魚人島) leader
_VICTIM = "OP01-016"         # ナミ (cost1 / power2000) = KO 対象 (cost<=2/4/5/6 すべて満たす)
_FILLER = "OP01-013"         # サンジ (cost2 / power3000)
_MERMAID = "OP11-102"        # ケイミー (人魚族/魚人島 cost1) = OP11-117 pump 対象
_EVENT = "EB04-008"          # 歪んだ未来 (赤 EVENT cost1) = reveal コスト / 赤イベントサーチ対象
_ROGER = "OP13-064"          # ゴール・D・ロジャー (ロジャー海賊団、 バギー以外) = OP12-012 対象


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave117_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-115", "OP11-116", "OP11-117", "OP11-118", "OP11-119",
           "OP12-004", "OP12-006", "OP12-008", "OP12-009", "OP12-012"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-115 タイプじゃないんですっ…………!! (EVENT 黄):
#    【カウンター】自リーダーが「しらほし」なら 自リーダーかキャラ1枚を +4000 (battle)。
#    【トリガー】相手のコスト2以下キャラ1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op11_115_counter_pump_ai():
    """【カウンター】自リーダーを このバトル中 +4000 (AI 既定 = リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP11-115", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンター +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op11_115_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP11-115", "counter")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


def test_op11_115_trigger_ko_cost_le_2_ai():
    """【トリガー】相手のコスト2以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP11-115", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"
    assert victim.card in opp.trash, "KO したキャラがトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP11-116 人魚柔術 ウルトラマリン (EVENT 黄):
#    【メイン】コスト6以下キャラ1枚までを 持ち主のライフの上か下に表向きで加える。
#    【トリガー】コスト4以下キャラ1枚までを ライフに加える。
# --------------------------------------------------------------------------- #
def test_op11_116_main_to_opp_life_ai():
    """【メイン】相手コスト6以下キャラを 場から取り除き 相手ライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=6)
    opp.characters = [victim]
    opp.life = []

    do, _ = _do(overlay, "OP11-116", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手キャラが場から取り除かれていない"
    assert any(c.card_id == _FILLER for c in opp.life), \
        "取り除いたキャラが持ち主 (相手) のライフに加えられていない"


def test_op11_116_main_human_target_pick():
    """人間 + 相手キャラ 複数 → to_opp_life の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)   # cost1
    b = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2
    opp.characters = [a, b]
    opp.life = []

    do, _ = _do(overlay, "OP11-116", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが場から取り除かれていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"
    assert any(c.card_id == _FILLER for c in opp.life), \
        "選んだキャラが相手ライフに加えられていない"


def test_op11_116_trigger_to_opp_life_cost_le_4_ai():
    """【トリガー】相手コスト4以下キャラを ライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=4)
    opp.characters = [victim]
    opp.life = []

    do, _ = _do(overlay, "OP11-116", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "トリガーで相手キャラが取り除かれていない"
    assert any(c.card_id == _VICTIM for c in opp.life), \
        "取り除いたキャラが相手ライフに加えられていない"


# --------------------------------------------------------------------------- #
#  OP11-117 魚人島 (STAGE 黄):
#    【起動メイン】【ターン1回】自リーダーが「しらほし」なら 自ライフ上1枚を
#      表向きにできる：自分の《海王類》/《魚人族》/《人魚族》キャラ1枚までを +1000 (turn)。
# --------------------------------------------------------------------------- #
def test_op11_117_activate_main_pump_mermaid_ai():
    """AI: しらほし leader → ライフ表向き (コスト) → 人魚族キャラ +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP11-117"), sickness=False)
    me.stages = [stage]
    mermaid = InPlay.of(repo.get(_MERMAID), sickness=False)  # ケイミー 人魚族
    me.characters = [mermaid]
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 0  # 全て裏向き = flip_life_face_up コスト可

    power_before = mermaid.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-117"]
    assert len(opts) == 1, f"OP11-117 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.face_up_life_count == 1, "ライフ 1 枚が表向きになっていない (コスト未払い)"
    assert mermaid.power == power_before + 1000, \
        f"人魚族キャラ +1000 が反映されていない: {mermaid.power} (before {power_before})"


def test_op11_117_no_activate_when_wrong_leader():
    """自リーダーが「しらほし」でなければ 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # 非しらほし
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP11-117"), sickness=False)
    me.stages = [stage]
    me.characters = [InPlay.of(repo.get(_MERMAID), sickness=False)]
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-117"]
    assert len(opts) == 0, "非しらほし leader で起動メインが legal に出てはいけない"


def test_op11_117_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP11-117"), sickness=False)
    me.stages = [stage]
    me.characters = [InPlay.of(repo.get(_MERMAID), sickness=False)]
    me.life = [repo.get(_FILLER)] * 3
    me.face_up_life_count = 0

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-117"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-117"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP11-118 モンキー・D・ルフィ (CHARACTER 青):
#    【速攻】【アタック時】自手札1枚を捨てることができる：コスト4以下キャラ1枚を
#      持ち主の手札に戻す。 その後、 自リーダーかキャラ1枚にレストのドン1枚までを付与。
# --------------------------------------------------------------------------- #
def test_op11_118_on_attack_bounce_and_attach_ai():
    """AI: 手札1捨て → 相手コスト4以下キャラを手札に戻し、 自リーダーにレストドン付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP11-118"), sickness=False)  # cost8 (>4)
    me.characters = [luffy]
    me.hand = [repo.get(_FILLER)]     # 捨てコスト用
    me.don_rested = 2                 # レストドン供給源
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=4)
    opp.characters = [victim]
    opp.hand = []

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP11-118", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, luffy)
    _drain(st, [0])

    assert victim not in opp.characters, "相手コスト4以下キャラが手札に戻されていない"
    assert any(c.card_id == _VICTIM for c in opp.hand), \
        "戻したキャラが持ち主 (相手) の手札に来ていない"
    assert any(c.card_id == _FILLER for c in me.trash), \
        "捨てコストの手札がトラッシュに置かれていない"
    assert me.leader.attached_dons == don_before + 1, \
        "その後の レストドン付与が自リーダーに反映されていない"
    assert me.don_rested == rested_before - 1, "レストドンが 1 枚消費されるべき"


def test_op11_118_on_attack_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal → pay で bounce まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP11-118"), sickness=False)
    me.characters = [luffy]
    me.hand = [repo.get(_FILLER)]
    me.don_rested = 2
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (相手キャラは 1 体)
    opp.characters = [victim]
    opp.hand = []

    do, _ = _do(overlay, "OP11-118", "on_attack")
    execute_effect(do[0], st, me, opp, luffy)

    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert victim not in opp.characters, \
        "人間が任意コストを払った後、 相手キャラが戻されていない"


def test_op11_118_on_attack_no_hand_no_fire():
    """手札が無い → 任意コスト払えず 効果不発 (相手キャラは残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP11-118"), sickness=False)
    me.characters = [luffy]
    me.hand = []  # 捨てられない
    me.don_rested = 2
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP11-118", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, luffy)
    _drain(st, [0])
    assert victim in opp.characters, \
        "手札が無いのに 相手キャラが戻された (任意コスト不能なら不発のはず)"


# --------------------------------------------------------------------------- #
#  OP11-119 コビー (CHARACTER 黒):
#    【登場時】自分のキャラ1枚までは このターン中 アクティブのキャラにもアタックできる。
#    【アタック時】自トラッシュから2枚をデッキ下に置くことができる：
#      自リーダーかキャラ1枚を 次の相手ターン終了時まで +1000。
# --------------------------------------------------------------------------- #
def test_op11_119_on_play_give_active_attack_ai():
    """AI: 登場時 自キャラ1枚に「アクティブアタック可」を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    src = InPlay.of(repo.get("OP11-119"), sickness=True)
    me.characters = [friend, src]

    trigger_on_play(st, me, opp, src, overlay)

    granted = any("アクティブアタック可" in c.granted_keywords for c in me.characters)
    assert granted, "登場時に 自キャラへ「アクティブアタック可」が付与されていない"


def test_op11_119_on_attack_trash_to_deck_pump_ai():
    """AI: アタック時 トラッシュ2枚をデッキ下 (コスト) → 自リーダーかキャラ +1000
    (次相手ターン終了時まで)。 AI 既定 = 最高パワーの自キャラ (= コビー自身)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    kobi = InPlay.of(repo.get("OP11-119"), sickness=False)  # power9000
    me.characters = [kobi]
    me.trash = [repo.get(_FILLER), repo.get(_VICTIM)]  # デッキ下 コスト用 2 枚
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    power_before = kobi.power

    do, _ = _do(overlay, "OP11-119", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, kobi)
    _drain(st, [0])

    assert len(me.trash) == trash_before - 2, "トラッシュ 2 枚が デッキに戻されていない"
    assert len(me.deck) == deck_before + 2, "デッキ下に 2 枚が加えられていない"
    assert kobi.power == power_before + 1000, \
        f"自キャラ +1000 が反映されていない: {kobi.power} (before {power_before})"


def test_op11_119_on_attack_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal → pay で pump まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    kobi = InPlay.of(repo.get("OP11-119"), sickness=False)
    me.characters = [kobi]
    me.trash = [repo.get(_FILLER), repo.get(_VICTIM)]
    power_before = me.leader.power

    do, _ = _do(overlay, "OP11-119", "on_attack")
    execute_effect(do[0], st, me, opp, kobi)

    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay → +1000 の対象選択 modal へ

    # 自リーダーかキャラ 1 枚 (= 自リーダー + コビー) の target_pick から自リーダーを選ぶ
    assert st.pending_choice is not None, "pay 後に +1000 の対象選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"pay 後の kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    leader_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == me.leader.instance_id)
    resolve_pending_choice(st, [leader_idx])
    _drain(st, [0])
    assert me.leader.power == power_before + 1000, \
        "人間が選んだ自リーダーに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-004 光月おでん (CHARACTER 赤):
#    【起動メイン】【ターン1回】自手札からイベント2枚を公開できる：
#      このキャラは このターン中 +2000。
# --------------------------------------------------------------------------- #
def test_op12_004_activate_main_reveal_events_pump_ai():
    """AI: 手札イベント2枚を公開 (コスト) → このキャラ +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("OP12-004"), sickness=False)  # power3000
    me.characters = [oden]
    me.hand = [repo.get(_EVENT), repo.get(_EVENT)]  # イベント 2 枚

    power_before = oden.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-004"]
    assert len(opts) == 1, f"OP12-004 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert oden.power == power_before + 2000, \
        f"イベント2公開で +2000 が反映されていない: {oden.power} (before {power_before})"


def test_op12_004_no_pump_without_two_events():
    """手札にイベントが 2 枚未満 → 任意コスト払えず +2000 が乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("OP12-004"), sickness=False)
    me.characters = [oden]
    me.hand = [repo.get(_EVENT)]  # イベント 1 枚だけ

    power_before = oden.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-004"]
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
    assert oden.power == power_before, \
        "イベント不足なのに +2000 が乗ってはいけない"


# --------------------------------------------------------------------------- #
#  OP12-006 シャクヤク (CHARACTER 赤):
#    【登場時】デッキ上5枚を見て、「モンキー・D・ルフィ」か赤イベント1枚までを公開し
#      手札に加える。 残りを好きな順でデッキ下へ。
# --------------------------------------------------------------------------- #
def test_op12_006_on_play_search_red_event_ai():
    """AI: デッキ上5枚から 赤イベント1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_EVENT)] + [repo.get(_FILLER)] * 10  # 上5枚に赤イベント
    me.hand = []
    src = InPlay.of(repo.get("OP12-006"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)

    assert any(c.card_id == _EVENT for c in me.hand), \
        "デッキ上5枚から 赤イベントが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が 1 枚増えていない"


def test_op12_006_on_play_search_human_pick():
    """人間 + デッキ上5枚に該当 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_EVENT), repo.get(_FILLER), repo.get(_EVENT)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []
    src = InPlay.of(repo.get("OP12-006"), sickness=True)
    me.characters = [src]

    do, _ = _do(overlay, "OP12-006", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (赤イベント) を選択
    _drain(st, [])
    assert any(c.card_id == _EVENT for c in me.hand), \
        "人間が選んだ 赤イベントが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-008 シャンクス (CHARACTER 赤):
#    【ブロッカー】【相手のアタック時】【ターン1回】自手札1枚を捨てることができる：
#      相手のリーダーかキャラ1枚を このターン中 -2000。
# --------------------------------------------------------------------------- #
def test_op12_008_opp_attack_debuff_ai():
    """AI: 手札1捨て → 相手キャラ1枚を -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    shanks = InPlay.of(repo.get("OP12-008"), sickness=False)
    me.characters = [shanks]
    me.hand = [repo.get(_FILLER)]  # 捨てコスト用
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000
    opp.characters = [victim]

    power_before = victim.power
    do, _ = _do(overlay, "OP12-008", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, shanks)
    _drain(st, [0])

    assert any(c.card_id == _FILLER for c in me.trash), \
        "捨てコストの手札がトラッシュに置かれていない"
    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op12_008_opp_attack_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal → pay で debuff まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    shanks = InPlay.of(repo.get("OP12-008"), sickness=False)
    me.characters = [shanks]
    me.hand = [repo.get(_FILLER)]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # 相手キャラ 1 体
    opp.characters = [victim]

    do, _ = _do(overlay, "OP12-008", "opp_attack")
    execute_effect(do[0], st, me, opp, shanks)

    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    power_before = victim.power
    resolve_pending_choice(st, [1])  # pay → -2000 の対象選択 modal へ

    # 相手リーダーかキャラ 1 枚 (= 相手リーダー + victim) の target_pick から victim を選ぶ
    assert st.pending_choice is not None, "pay 後に -2000 の対象選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"pay 後の kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    victim_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == victim.instance_id)
    resolve_pending_choice(st, [victim_idx])
    _drain(st, [0])
    assert victim.power == power_before - 2000, \
        "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-009 ジンベエ (CHARACTER 赤):
#    【登場時】自手札からイベント2枚を公開できる：このキャラは このターン中【速攻】を得る。
#      その後、 次の相手エンドフェイズ終了時まで このキャラ +1000。
# --------------------------------------------------------------------------- #
def test_op12_009_on_play_reveal_gives_rush_and_pump_ai():
    """AI: イベント2公開 (コスト) → 自身が【速攻】を得て +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-009"), sickness=True)  # power4000
    me.characters = [src]
    me.hand = [repo.get(_EVENT), repo.get(_EVENT)]  # イベント 2 枚

    power_before = src.power
    trigger_on_play(st, me, opp, src, overlay)

    assert "速攻" in src.granted_keywords, "登場時に【速攻】が付与されていない"
    assert src.power == power_before + 1000, \
        f"登場時 +1000 が反映されていない: {src.power} (before {power_before})"


def test_op12_009_on_play_no_events_no_effect():
    """手札にイベントが 2 枚未満 → 任意コスト払えず 速攻/+1000 が乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-009"), sickness=True)
    me.characters = [src]
    me.hand = [repo.get(_EVENT)]  # 1 枚だけ

    power_before = src.power
    trigger_on_play(st, me, opp, src, overlay)
    assert "速攻" not in src.granted_keywords, "イベント不足なのに【速攻】が乗った"
    assert src.power == power_before, "イベント不足なのに +1000 が乗った"


def test_op12_009_on_play_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal → pay で 速攻/+1000 まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-009"), sickness=True)
    me.characters = [src]
    me.hand = [repo.get(_EVENT), repo.get(_EVENT)]

    do, _ = _do(overlay, "OP12-009", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    power_before = src.power
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert "速攻" in src.granted_keywords, \
        "人間が任意コストを払った後、【速攻】が付与されていない"
    assert src.power == power_before + 1000, \
        "人間が任意コストを払った後、 +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-012 バギー (CHARACTER 赤):
#    【登場時】自分の「バギー」以外の『ロジャー海賊団』を含む特徴を持つキャラ1枚までは
#      次の相手エンドフェイズ終了時まで【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op12_012_on_play_gives_blocker_to_roger_ai():
    """AI: 自分の『ロジャー海賊団』キャラ (バギー以外) に【ブロッカー】を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    roger = InPlay.of(repo.get(_ROGER), sickness=False)  # ロジャー海賊団
    src = InPlay.of(repo.get("OP12-012"), sickness=True)
    me.characters = [roger, src]

    trigger_on_play(st, me, opp, src, overlay)

    assert "ブロッカー" in roger.granted_keywords_through_opp_turn, \
        "ロジャー海賊団キャラに【ブロッカー】が付与されていない"


def test_op12_012_on_play_human_target_pick():
    """人間 + 対象『ロジャー海賊団』複数 → target_pick modal が立ち resolve で付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    r1 = InPlay.of(repo.get(_ROGER), sickness=False)
    r2 = InPlay.of(repo.get("OP13-061"), sickness=False)  # イヌアラシ (ロジャー海賊団)
    src = InPlay.of(repo.get("OP12-012"), sickness=True)
    me.characters = [r1, r2, src]

    do, _ = _do(overlay, "OP12-012", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ロジャー海賊団 2 体) が 2 件でない: {len(cands)}"

    r2_idx = next(i for i, c in enumerate(cands) if c["iid"] == r2.instance_id)
    resolve_pending_choice(st, [r2_idx])
    _drain(st, [0])
    assert "ブロッカー" in r2.granted_keywords_through_opp_turn, \
        "人間が選んだキャラに【ブロッカー】が付与されていない"


def test_op12_012_on_play_no_roger_no_grant():
    """『ロジャー海賊団』キャラが居なければ 付与対象なし (crash せず不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    other = InPlay.of(repo.get(_FILLER), sickness=False)  # 麦わらの一味 (非ロジャー)
    src = InPlay.of(repo.get("OP12-012"), sickness=True)
    me.characters = [other, src]

    trigger_on_play(st, me, opp, src, overlay)
    assert "ブロッカー" not in other.granted_keywords_through_opp_turn, \
        "ロジャー海賊団でないキャラに【ブロッカー】が付与された"
