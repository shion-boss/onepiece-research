# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 055):
OP05-016 / OP05-017 / OP05-018 / OP05-019 / OP05-020 / OP05-021 /
OP05-023 / OP05-025 / OP05-026 / OP05-027 の 10 枚
(赤 革命軍 系 + 緑 ドンキホーテ海賊団 / ベラミー海賊団 系)。

目的 (= test_backfill_auto_001〜054.py と同一方針):
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
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 革命軍 非所持 / 単色)
_LEADER_REVO = "OP07-001"      # モンキー・D・ドラゴン (赤、 特徴 革命軍)
_LEADER_MULTI = "EB04-001"     # ジュエリー・ボニー (赤/黄 = 多色 leader)
_RED_C3 = "EB02-003"           # トニートニー・チョッパー 赤 cost3 power3000
_NAMI = "OP01-016"             # ナミ 赤 cost1 power2000
_PLAIN_C2 = "ST01-004"         # サンジ 赤 cost2 power4000 (汎用ダミー)
_KOALA_REVO = "OP05-006"       # コアラ 赤 cost2 power3000 革命軍 (登場/サーチ先)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_PLAIN_C2)] * 30
    p1.deck = [repo.get(_PLAIN_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"]
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


def _granted(ip):
    return ip.granted_keywords | ip.static_granted_keywords


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave55_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-016", "OP05-017", "OP05-018", "OP05-019", "OP05-020",
           "OP05-021", "OP05-023", "OP05-025", "OP05-026", "OP05-027"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-016 モーリー (CHARACTER 赤 cost3 power5000):
#    【アタック時】このキャラのパワーが7000以上の場合、 相手は、 このバトル中、
#      【ブロッカー】を発動できない。
#    【トリガー】自分の手札1枚を捨てることができる：自分のリーダーが多色の場合、
#      このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op05_016_on_attack_grants_blocker_disable_ai():
    """アタック時: 自身に「ブロック不可」キーワードが付与される (= 相手はブロッカー不可)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP05-016"), sickness=False)
    me.characters = [attacker]

    for prim in _do(overlay, "OP05-016", "on_attack"):
        execute_effect(prim, st, me, opp, attacker)

    assert "ブロック不可" in _granted(attacker), \
        f"アタック時 ブロック不可 が付与されていない: {_granted(attacker)}"


def test_op05_016_trigger_play_self_multicolor_ai():
    """【トリガー】手札1枚を捨て 自リーダーが多色なら このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay)  # ボニー 赤/黄 (多色)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_PLAIN_C2)]           # 捨てるコスト用
    me.trash = [repo.get("OP05-016")]
    st.current_source_card_id = "OP05-016"

    for prim in _do(overlay, "OP05-016", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert any(c.card.card_id == "OP05-016" for c in me.characters), \
        "多色リーダー時 トリガーで OP05-016 が登場していない"
    assert len(me.hand) == 0, "手札1枚を捨てるコストが支払われていない"


# --------------------------------------------------------------------------- #
#  OP05-017 リンドバーグ (CHARACTER 赤 cost4 power5000):
#    【アタック時】このキャラのパワーが7000以上の場合、 相手のパワー3000以下の
#      キャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op05_017_on_attack_ko_power_le_3000_ai():
    """アタック時: 相手のパワー3000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # power2000 (<= 3000)
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-017", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-017"), sickness=False))

    assert victim not in opp.characters, "パワー3000以下キャラが KO されていない"


def test_op05_017_on_attack_high_power_survives():
    """アタック時: パワー3000超のキャラ (power4000) は対象外 → 残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    strong = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # power4000 (> 3000)
    opp.characters = [strong]

    for prim in _do(overlay, "OP05-017", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-017"), sickness=False))

    assert strong in opp.characters, "パワー4000のキャラが KO されている (対象外のはず)"


def test_op05_017_on_attack_human_ko_pick():
    """人間 + 相手のパワー3000以下キャラ複数 → ko の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)
    b = InPlay.of(repo.get(_RED_C3), sickness=False)  # power3000 (<= 3000)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-017", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-017"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
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
#  OP05-018 エンポリオ・テンションホルモン (EVENT 赤 cost3):
#    【カウンター】自分のリーダーかキャラ1枚までを、 このバトル中、 パワー+3000。
#      その後、 自分の手札からパワー5000以下の特徴《革命軍》を持つキャラカード1枚
#      までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op05_018_counter_pump_and_play_revo_ai():
    """【カウンター】自リーダー +3000 → 手札から革命軍キャラ (コアラ) を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_KOALA_REVO)]  # 革命軍 power3000 (<= 5000)

    power_before = me.leader.power
    for prim in _do(overlay, "OP05-018", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
    assert any(c.card.card_id == _KOALA_REVO for c in me.characters), \
        "手札から革命軍キャラ (コアラ) が登場していない"


def test_op05_018_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ複数 → +3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_NAMI), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP05-018", "counter")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st)
    assert friend.power == friend_before + 3000, \
        "人間が選んだキャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-019 火拳 (EVENT 赤 cost2):
#    【メイン】相手のキャラ1枚までを、 このターン中、 パワー-4000。 その後、
#      自分のライフが2枚以下の場合、 相手のパワー0以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op05_019_main_debuff_and_ko_when_life_le_2_ai():
    """メイン: 相手キャラ -4000 → 自ライフ2以下なら power0以下を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # power4000 → 0
    opp.characters = [victim]
    me.life = [repo.get(_PLAIN_C2)] * 2  # ライフ 2 (= 条件成立)

    for prim in _do(overlay, "OP05-019", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert victim not in opp.characters, \
        "ライフ2以下 + power0以下 の相手キャラが KO されていない"


def test_op05_019_main_no_ko_when_life_ge_3():
    """メイン: 自ライフ3枚 (> 2) → KO 条件不成立。 -4000 のみ適用され キャラは残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # power4000 → 0
    opp.characters = [victim]
    me.life = [repo.get(_PLAIN_C2)] * 3  # ライフ 3 (= KO 条件不成立)

    power_before = victim.power
    for prim in _do(overlay, "OP05-019", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert victim in opp.characters, "ライフ3枚なのに KO されている (条件不成立のはず)"
    assert victim.power == power_before - 4000, \
        f"-4000 が適用されていない: {victim.power} (before {power_before})"


def test_op05_019_main_debuff_human_pick():
    """人間 + 相手キャラ複数 → -4000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_PLAIN_C2), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-019", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a.power == a_before - 4000, \
        "人間が選んだ相手キャラに -4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-020 四千枚瓦正拳 (EVENT 赤 cost2):
#    【メイン】自分のリーダーかキャラ1枚までを、 このターン中、 パワー+2000。
#      その後、 相手のパワー2000以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op05_020_main_pump_and_ko_ai():
    """メイン: 自リーダー +2000 → 相手のパワー2000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # power2000 (<= 2000)
    opp.characters = [victim]

    power_before = me.leader.power
    for prim in _do(overlay, "OP05-020", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert me.leader.power == power_before + 2000, \
        f"自リーダー +2000 が反映されていない: {me.leader.power}"
    assert victim not in opp.characters, "パワー2000以下キャラが KO されていない"


def test_op05_020_main_pump_human_pick():
    """人間 + 自リーダー/キャラ複数 → +2000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_NAMI), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP05-020", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st)
    assert friend.power == friend_before + 2000, \
        "人間が選んだ自キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-021 革命軍総本部 (STAGE 赤 cost1):
#    【起動メイン】自分の手札1枚を捨て、 このステージをレストにできる：自分の
#      デッキの上から3枚を見て、 特徴《革命軍》を持つカード1枚までを公開し、
#      手札に加える。 その後、 残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_021_activate_search_revo_ai():
    """起動メイン: 手札1枚を捨て デッキ上3枚から革命軍カードを手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP05-021"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get(_PLAIN_C2)]  # 捨てるコスト用 (非革命軍)
    me.deck = [repo.get(_KOALA_REVO)] + [repo.get(_PLAIN_C2)] * 10  # 上に革命軍

    options = list_activate_main_effects(st, me, overlay)
    stage_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "OP05-021"]
    assert len(stage_opts) == 1, \
        f"OP05-021 (ステージ) の起動メインが legal に出ない: {len(stage_opts)}"
    fire_activate_main(st, me, opp, *stage_opts[0])
    _drain(st, pick=[0])

    assert any(c.card_id == _KOALA_REVO for c in me.hand), \
        "デッキ上3枚から革命軍カードが手札に加わっていない"


def test_op05_021_activate_human_flow():
    """人間: 起動メインで まず 捨てるカードの choice が立ち、 解決チェーンで革命軍が手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP05-021"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get(_PLAIN_C2)]  # 捨てるコスト
    me.deck = [repo.get(_KOALA_REVO), repo.get(_PLAIN_C2), repo.get("OP05-016")] \
        + [repo.get(_PLAIN_C2)] * 10  # 上3枚に革命軍 2 枚

    options = list_activate_main_effects(st, me, overlay)
    stage_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "OP05-021"]
    assert len(stage_opts) == 1
    fire_activate_main(st, me, opp, *stage_opts[0])

    assert st.pending_choice is not None, "人間 起動メインで modal が立たない"
    assert st.pending_choice.get("kind") == "activate_main_discard_pick", \
        f"最初の modal が discard cost choice でない: {st.pending_choice.get('kind')}"
    # discard → search → reorder のチェーンを解決
    _drain(st, pick=[0])
    assert any(c.card_id in (_KOALA_REVO, "OP05-016") for c in me.hand), \
        "人間の解決後 デッキ上3枚から革命軍カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP05-023 ヴェルゴ (CHARACTER 緑 cost3 power4000):
#    【ドン!!×1】【アタック時】相手のレストのコスト3以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op05_023_on_attack_ko_rested_cost_le_3_ai():
    """アタック時 (ドン1ゲート): 相手のレストのコスト3以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    victim.rested = True
    opp.characters = [victim]

    on_attack_eff = overlay.get("OP05-023").effects[0]
    assert on_attack_eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-023"), sickness=False))

    assert victim not in opp.characters, "相手のレストコスト3キャラが KO されていない"


def test_op05_023_on_attack_active_survives():
    """アタック時: 相手のコスト3キャラが アクティブ (非レスト) なら 対象外 → 残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    for prim in overlay.get("OP05-023").effects[0]["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-023"), sickness=False))

    assert victim in opp.characters, "アクティブなキャラが KO されている (対象外のはず)"


def test_op05_023_on_attack_human_ko_pick():
    """人間 + 相手のレストコスト3以下キャラ複数 → ko の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_RED_C3), sickness=False)
    a.rested = True
    b = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1
    b.rested = True
    opp.characters = [a, b]

    execute_effect(overlay.get("OP05-023").effects[0]["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP05-023"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
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
#  OP05-025 グラディウス (CHARACTER 緑 cost5 power6000):
#    【起動メイン】このキャラをレストにできる：相手のコスト3以下のキャラ1枚までを、
#      レストにする。
# --------------------------------------------------------------------------- #
def test_op05_025_activate_rest_opp_cost_le_3_ai():
    """起動メイン: 自身をレスト (コスト) → 相手のコスト3以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    gladius = InPlay.of(repo.get("OP05-025"), sickness=False)
    me.characters = [gladius]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3, active
    victim.rested = False
    opp.characters = [victim]

    options = list_activate_main_effects(st, me, overlay)
    g_opts = [(src, eff) for (src, eff) in options
              if src.card.card_id == "OP05-025"]
    assert len(g_opts) == 1, f"OP05-025 の起動メインが legal に出ない: {len(g_opts)}"
    fire_activate_main(st, me, opp, *g_opts[0])
    _drain(st, pick=[0])

    assert victim.rested is True, "相手のコスト3以下キャラがレストされていない"
    assert gladius.rested is True, "起動メインコストで グラディウス がレストされていない"


def test_op05_025_activate_human_rest_pick():
    """人間 + 相手のコスト3以下キャラ複数 → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    gladius = InPlay.of(repo.get("OP05-025"), sickness=False)
    me.characters = [gladius]
    a = InPlay.of(repo.get(_RED_C3), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    g_opts = [o for o in list_activate_main_effects(st, me, overlay)
              if o[0].card.card_id == "OP05-025"]
    fire_activate_main(st, me, opp, *g_opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP05-026 サーキース (CHARACTER 緑 cost4 power4000):
#    【ドン!!×1】【アタック時】【ターン1回】自分のコスト3以上のキャラ1枚を
#      レストにできる：このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op05_026_on_attack_untap_self_via_rest_cost3_ally_ai():
    """アタック時 (ドン1ゲート): 自コスト3以上キャラをレスト → 自身をアクティブ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    surquiss = InPlay.of(repo.get("OP05-026"), sickness=False)
    surquiss.rested = True          # アタック後 (= レスト状態) を再現
    surquiss.attached_dons = 1      # 【ドン!!×1】ゲート
    ally = InPlay.of(repo.get(_RED_C3), sickness=False)  # コスト3 (>= 3), active
    me.characters = [surquiss, ally]

    on_attack_eff = overlay.get("OP05-026").effects[0]
    assert on_attack_eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack_eff["do"]:
        execute_effect(prim, st, me, opp, surquiss)
    _drain(st, pick=[0])

    assert surquiss.rested is False, "サーキース がアクティブ化されていない"
    assert ally.rested is True, "コスト支払いで コスト3以上キャラがレストされていない"


def test_op05_026_on_attack_no_untap_without_cost3_ally():
    """アタック時: コスト3以上の味方が居なければ コスト不能 → 自身はアクティブ化されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    surquiss = InPlay.of(repo.get("OP05-026"), sickness=False)
    surquiss.rested = True
    surquiss.attached_dons = 1
    low = InPlay.of(repo.get(_NAMI), sickness=False)  # コスト1 (< 3) = 対象外
    me.characters = [surquiss, low]

    for prim in overlay.get("OP05-026").effects[0]["do"]:
        execute_effect(prim, st, me, opp, surquiss)
    _drain(st, pick=[0])

    assert surquiss.rested is True, \
        "コスト3以上の味方が居ないのに 自身がアクティブ化されている"
    assert low.rested is False, "コスト1キャラがレストされている (対象外のはず)"


# --------------------------------------------------------------------------- #
#  OP05-027 トラファルガー・ロー (CHARACTER 緑 cost1 power2000):
#    【起動メイン】このキャラをトラッシュに置くことができる：相手のコスト3以下の
#      キャラ1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op05_027_activate_trash_self_rest_opp_ai():
    """起動メイン: 自身をトラッシュ (コスト) → 相手のコスト3以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("OP05-027"), sickness=False)
    me.characters = [law]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    victim.rested = False
    opp.characters = [victim]

    options = list_activate_main_effects(st, me, overlay)
    law_opts = [(src, eff) for (src, eff) in options
                if src.card.card_id == "OP05-027"]
    assert len(law_opts) == 1, f"OP05-027 の起動メインが legal に出ない: {len(law_opts)}"
    fire_activate_main(st, me, opp, *law_opts[0])
    _drain(st, pick=[0])

    assert victim.rested is True, "相手のコスト3以下キャラがレストされていない"
    assert law not in me.characters, "コストで ロー がトラッシュに置かれていない"
    assert any(c.card_id == "OP05-027" for c in me.trash), \
        "ロー がトラッシュに置かれていない"


def test_op05_027_activate_human_rest_pick():
    """人間 + 相手のコスト3以下キャラ複数 → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("OP05-027"), sickness=False)
    me.characters = [law]
    a = InPlay.of(repo.get(_RED_C3), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    law_opts = [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "OP05-027"]
    fire_activate_main(st, me, opp, *law_opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"
