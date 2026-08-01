# -*- coding: utf-8 -*-
"""カード効果 回帰テスト バックフィル (自動生成 wave 164):
PRB02-002 / PRB02-003 / PRB02-010 / PRB02-015 /
ST01-001 / ST01-002 / ST01-011 / ST01-014 / ST01-015 / ST01-016 の 10 枚。

目的 (= test_backfill_auto_001〜163.py と同一方針):
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
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"            # ナミ (cost1 power2000) フィラー / 相手キャラ
COST2 = "OP01-013"           # サンジ (cost2 power3000) フィラー
COST5_P6000 = "OP15-030"     # ヒョウゾウ (cost5 power6000) 6000 素材
BIGMOM_LEADER = "OP11-062"   # シャーロット・カタクリ (ビッグ・マム海賊団 LEADER)
BIGMOM_CHARA = "EB03-033"    # シャーロット・ブリュレ (cost5 power6000 ビッグ・マム海賊団)
BLACKBEARD_LEADER = "OP16-080"  # マーシャル・D・ティーチ (黒ひげ海賊団 LEADER)
STRAWHAT_LEADER = "ST01-001"    # モンキー・D・ルフィ (麦わらの一味 LEADER)


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
def test_all_wave164_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["PRB02-002", "PRB02-003", "PRB02-010", "PRB02-015",
           "ST01-001", "ST01-002", "ST01-011", "ST01-014", "ST01-015", "ST01-016"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  PRB02-002 トラファルガー・ロー (CHARACTER 赤 cost6 power7000):
#    【ターン1回】このキャラが相手の効果で場を離れる場合、代わりにこのターン中パワー-2000できる。
#    【アタック時】相手のキャラ1枚までを、このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_prb02_002_law_on_attack_debuff_ai():
    """【アタック時】相手キャラ1枚を このターン中 パワー-2000。 AI 自動選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [victim]

    power_before = victim.power
    eff = _eff(overlay, "PRB02-002", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("PRB02-002"), sickness=False))

    assert victim.power == power_before - 2000, \
        f"相手キャラの power が -2000 されていない: {victim.power} (before {power_before})"


def test_prb02_002_law_on_attack_debuff_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で 1 体に -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # power 2000
    b = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [a, b]

    eff = _eff(overlay, "PRB02-002", "on_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("PRB02-002"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


def test_prb02_002_law_replace_leave_self_debuff_ai():
    """相手効果で場を離れる代わりに 自身 パワー-2000 して場に残る (replace_leave / AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("PRB02-002"), sickness=False)  # power 7000
    me.characters = [law]

    power_before = law.power
    replaced = try_replace_ko(
        st, me, opp, law, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "相手効果離脱が置換されていない"
    assert law in me.characters, "置換成立時 ロー は場に残るべき"
    assert law.power == power_before - 2000, \
        f"置換で自身 -2000 されていない: {law.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  PRB02-003 ラッキー・ルウ (CHARACTER 赤 cost4 power2000):
#    【ブロッカー】【登場時】自分の手札からパワー6000以上のキャラカード1枚を捨てることが
#    できる：カード2枚を引く。 (optional_cost_then)
# --------------------------------------------------------------------------- #
def test_prb02_003_lucky_roux_optional_discard_draw_ai():
    """【登場時】(任意) パワー6000以上キャラを1枚捨て → 2枚引く。 AI: 払える→発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST5_P6000)]  # power6000 CHARACTER (捨てるコスト)
    me.deck = [repo.get(NAMI)] * 10

    hand_before = len(me.hand)
    eff = _eff(overlay, "PRB02-003", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("PRB02-003"), sickness=True))
    _drain(st, [0])

    # 1 枚捨てて 2 枚引く → 差引 +1 枚
    assert len(me.hand) == hand_before - 1 + 2, \
        f"捨て1 + ドロー2 の手札増減が合わない: {len(me.hand)} (before {hand_before})"
    assert not any(c.card_id == COST5_P6000 for c in me.hand), \
        "コストの power6000 キャラが手札から捨てられていない"


def test_prb02_003_lucky_roux_no_payable_no_draw():
    """パワー6000以上のキャラが手札に無い → 任意コスト不能 → 発動しない (手札不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2)]  # power3000 のみ = 捨てられない
    me.deck = [repo.get(NAMI)] * 10

    hand_before = len(me.hand)
    eff = _eff(overlay, "PRB02-003", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("PRB02-003"), sickness=True))

    assert len(me.hand) == hand_before, \
        f"払えないのに手札が変化した: {len(me.hand)} (before {hand_before})"


def test_prb02_003_lucky_roux_human_optional_confirm():
    """人間 + 払える → optional_cost_confirm modal が立つ (= 本人が pay/skip を選べる)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST5_P6000)]
    me.deck = [repo.get(NAMI)] * 10

    eff = _eff(overlay, "PRB02-003", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("PRB02-003"), sickness=True))

    assert st.pending_choice is not None, "人間 + 払える で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  PRB02-010 シャーロット・プリン (CHARACTER 紫 cost7 power5000):
#    【登場時】ドン‼-2：自リーダーが《ビッグ・マム海賊団》を持ち、相手ドン6以上の場合、
#    2枚引く。その後、手札からパワー6000-8000の《ビッグ・マム海賊団》キャラ1枚までを登場。
# --------------------------------------------------------------------------- #
def test_prb02_010_pudding_condition_true_bigmom_leader_opp_don6():
    """条件: ビッグ・マム leader + 相手ドン6以上 で成立 (eval_condition True)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BIGMOM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 6  # 相手ドン 6 枚

    eff = _eff(overlay, "PRB02-010", "on_play")
    for cond in eff.get("conditions", []):
        assert eval_condition(cond, st, me, None) is True, \
            f"ビッグ・マム leader + 相手ドン6 で条件 {cond} が成立していない"


def test_prb02_010_pudding_condition_false_non_bigmom_leader():
    """リーダーが《ビッグ・マム海賊団》でなければ leader_feature 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ルフィ leader
    me = st.players[0]
    eff = _eff(overlay, "PRB02-010", "on_play")
    leader_cond = next(c for c in eff.get("conditions", []) if "leader_feature" in c)
    assert eval_condition(leader_cond, st, me, None) is False, \
        "非・ビッグ・マム leader で leader_feature 条件が成立してはいけない"


def test_prb02_010_pudding_on_play_draw_and_play_ai():
    """【登場時】 2枚引き → 手札からビッグ・マム power6000-8000 を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BIGMOM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 6
    me.deck = [repo.get(NAMI)] * 10
    me.hand = [repo.get(BIGMOM_CHARA)]  # ブリュレ power6000 ビッグ・マム海賊団

    chars_before = len(me.characters)
    eff = _eff(overlay, "PRB02-010", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("PRB02-010"), sickness=True))
    _drain(st, [0])

    assert len(me.characters) == chars_before + 1, \
        "手札のビッグ・マムキャラ (6000-8000) が登場していない"
    assert any(c.card.card_id == BIGMOM_CHARA for c in me.characters), \
        "登場したのがブリュレ (BigMom power6000) でない"


# --------------------------------------------------------------------------- #
#  PRB02-015 シリュウ (CHARACTER 黒 cost4 power5000):
#    【KO時】自リーダーが《黒ひげ海賊団》を持つ場合、相手の元々のコスト4以下のキャラ1枚
#    までを、KOする。
# --------------------------------------------------------------------------- #
def test_prb02_015_shiryu_on_ko_condition_true_blackbeard():
    """KO時 条件: 黒ひげ海賊団 leader で成立 (eval_condition True)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BLACKBEARD_LEADER, overlay)
    me = st.players[0]
    eff = _eff(overlay, "PRB02-015", "on_ko")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "黒ひげ leader で KO時 条件が成立していない"


def test_prb02_015_shiryu_on_ko_ko_opp_cost_le4_ai():
    """【KO時】相手の元々コスト4以下のキャラ1枚を KO する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BLACKBEARD_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # cost2
    opp.characters = [victim]

    eff = _eff(overlay, "PRB02-015", "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("PRB02-015"), sickness=False))
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト4以下キャラが KO されていない"


def test_prb02_015_shiryu_on_ko_ko_opp_human_pick():
    """人間 + 相手コスト4以下 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BLACKBEARD_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(COST2), sickness=False)  # cost2
    opp.characters = [a, b]

    eff = _eff(overlay, "PRB02-015", "on_ko")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("PRB02-015"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  ST01-001 モンキー・D・ルフィ (LEADER 赤):
#    【起動メイン】【ターン1回】このリーダーか自キャラ1枚にレストのドン‼1枚までを付与。
# --------------------------------------------------------------------------- #
def test_st01_001_luffy_activate_main_attach_rested_don_ai():
    """起動メイン: 自リーダーにレストドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    options = list_activate_main_effects(st, me, overlay)
    luffy_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "ST01-001"]
    assert len(luffy_opts) == 1, \
        f"ST01-001 の起動メインが legal に出ない: {len(luffy_opts)}"
    src, eff = luffy_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_st01_001_luffy_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST01-001"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST01-001"]
    assert len(opts2) == 0, "ターン1回のはずが2回目も legal に残っている"


def test_st01_001_luffy_activate_main_human_target_pick():
    """人間 + 自リーダー/キャラ 複数候補 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    friend = InPlay.of(repo.get(COST2), sickness=False)
    me.characters = [friend]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST01-001"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  ST01-002 ウソップ (CHARACTER 赤 cost2 power2000):
#    【ドン‼×2】【アタック時】相手はこのバトル中パワー5000以上のキャラの【ブロッカー】を
#    発動できない。 (overlay: 自身に「ブロック不可」 keyword、 self_attached_don_ge=2 ゲート)
# --------------------------------------------------------------------------- #
def test_st01_002_usopp_attack_grants_keyword_ai():
    """【アタック時】(ドン2ゲート) 自身に「ブロック不可」keyword が付与される (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    usopp = InPlay.of(repo.get("ST01-002"), sickness=False)
    usopp.attached_dons = 2  # ドン×2 ゲート成立
    me.characters = [usopp]

    eff = _eff(overlay, "ST01-002", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    assert eval_condition(eff["if"], st, me, usopp) is True, \
        "ドン2付与済で ドンゲート条件が成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, usopp)

    assert "ブロック不可" in usopp.granted_keywords, \
        "アタック時に「ブロック不可」keyword が付与されていない"


def test_st01_002_usopp_attack_gate_false_without_don():
    """ドン付与が2枚未満なら ドンゲート条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    usopp = InPlay.of(repo.get("ST01-002"), sickness=False)
    usopp.attached_dons = 1
    me.characters = [usopp]

    eff = _eff(overlay, "ST01-002", "on_attack")
    assert eval_condition(eff["if"], st, me, usopp) is False, \
        "ドン1枚で ドンゲート条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST01-011 ブルック (CHARACTER 赤 cost2 power3000):
#    【登場時】自分のリーダーかキャラ1枚にレストのドン‼2枚までを付与する。
# --------------------------------------------------------------------------- #
def test_st01_011_brook_on_play_attach_rested_don_ai():
    """【登場時】自リーダーにレストドン2枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3

    don_before = me.leader.attached_dons
    eff = _eff(overlay, "ST01-011", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST01-011"), sickness=True))
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 2, \
        f"登場時に自リーダーへレストドン2枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == 1, "レストドンが2枚消費されるべき"


def test_st01_011_brook_on_play_human_target_pick():
    """人間 + 自リーダー/キャラ 複数候補 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    friend = InPlay.of(repo.get(COST2), sickness=False)
    me.characters = [friend]

    eff = _eff(overlay, "ST01-011", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST01-011"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.attached_dons == 2, "人間が選んだキャラにレストドン2枚が付与されていない"


# --------------------------------------------------------------------------- #
#  ST01-014 毛皮強化 (EVENT 赤 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+3000。
#    【トリガー】自分のリーダーかキャラ1枚までを、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_st01_014_fur_reinforcement_counter_pump_ai():
    """【カウンター】自リーダーorキャラ1枚 +3000。 AI 自動 (リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST01-014", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_st01_014_fur_reinforcement_counter_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(COST2), sickness=False)
    me.characters = [friend]

    eff = _eff(overlay, "ST01-014", "counter")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 3000, \
        "人間が選んだキャラに +3000 が反映されていない"


def test_st01_014_fur_reinforcement_trigger_pump_ai():
    """【トリガー】自リーダーorキャラ1枚 +1000 (このターン中)。 AI 自動 (リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST01-014", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, \
        f"トリガーの +1000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  ST01-015 ゴムゴムのJET銃 (EVENT 赤 cost4):
#    【メイン】相手のパワー6000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st01_015_jet_gun_main_ko_ai():
    """【メイン】相手パワー6000以下キャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # power 3000 (<=6000)
    opp.characters = [victim]

    eff = _eff(overlay, "ST01-015", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim not in opp.characters, "相手のパワー6000以下キャラが KO されていない"


def test_st01_015_jet_gun_main_ko_human_pick():
    """人間 + 相手6000以下 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # power 2000
    b = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [a, b]

    eff = _eff(overlay, "ST01-015", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  ST01-016 悪魔風脚 (EVENT 赤 cost1):
#    【メイン】自分の《麦わらの一味》を持つリーダーかキャラ1枚までを選ぶ。相手はこのターン中、
#    そのリーダーかキャラがアタックする場合【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_st01_016_devil_leg_main_prevent_blocker_ai():
    """【メイン】自麦わらリーダーを選び「ブロッカー発動禁止 (attacker)」flag を立てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay)  # 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]

    assert not me.leader.attacker_prevents_blocker_until_turn_end, \
        "テスト前提: 事前に flag が立っていない"
    eff = _eff(overlay, "ST01-016", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert me.leader.attacker_prevents_blocker_until_turn_end is True, \
        "自麦わらリーダーに ブロッカー発動禁止 flag が立っていない"


def test_st01_016_devil_leg_main_human_pick():
    """人間 + 麦わらリーダー/キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 麦わらの一味 を持つキャラを 1 体追加 (ST01-011 ブルックは麦わらの一味)
    friend = InPlay.of(repo.get("ST01-011"), sickness=False)
    assert "麦わらの一味" in (friend.card.features or ""), \
        "テスト前提: ST01-011 は 麦わらの一味"
    me.characters = [friend]

    eff = _eff(overlay, "ST01-016", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [0])
    assert friend.attacker_prevents_blocker_until_turn_end is True, \
        "人間が選んだキャラに ブロッカー発動禁止 flag が立っていない"
