# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 162):
P-098 / P-099 / P-100 / P-101 / P-102 /
P-103 / P-105 / P-107 / P-108 / P-109 の 10 枚。

目的 (= test_backfill_auto_001〜161.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"            # ナミ (cost1 power2000) フィラー / 相手キャラ
COST2 = "OP01-013"           # サンジ (cost2 power3000) フィラー
COST5A = "OP15-030"          # ヒョウゾウ (cost5 power6000) cost>=5 素材
COST5B = "EB04-016"          # トリ (cost5 power7000) cost>=5 素材
BIG = "OP02-004"             # エドワード・ニューゲート (cost9 power10000) cost>=5 素材
STRAWHAT_LEADER = "PRB01-001"    # サンジ (麦わらの一味 LEADER)
NON_STRAWHAT_LEADER = "OP15-002"  # ルーシー (ドレスローザ/革命軍 LEADER、 麦わらなし)
REVO_LEADER = "OP15-002"     # ルーシー (革命軍 LEADER)


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
def test_all_wave162_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-098", "P-099", "P-100", "P-101", "P-102",
           "P-103", "P-105", "P-107", "P-108", "P-109"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-098 バギー (CHARACTER cost10):
#    【ブロッカー】【登場時】自分のコスト5以上のキャラが5枚いない場合、
#    このキャラを持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_p098_buggy_on_play_return_when_few_big_charas():
    """【登場時】コスト5以上キャラが5枚未満 → このキャラをデッキ下に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("P-098"), sickness=True)  # cost10 (>=5)
    # バギー含め コスト5以上 は 4 枚 (= 5 枚未満 → 条件不成立 → デッキ下)
    others = [InPlay.of(repo.get(COST5A), sickness=False),
              InPlay.of(repo.get(COST5B), sickness=False),
              InPlay.of(repo.get(BIG), sickness=False)]
    me.characters = [buggy] + others
    deck_before = len(me.deck)

    for prim in _eff(overlay, "P-098", "on_play")["do"]:
        execute_effect(prim, st, me, opp, buggy)

    assert buggy not in me.characters, \
        "コスト5以上キャラ5枚未満なら バギー はデッキ下に戻るべき"
    assert len(me.deck) == deck_before + 1, "バギー がデッキに戻っていない"
    assert me.deck[-1].card_id == "P-098", "バギー がデッキ下 (末尾) に置かれていない"


def test_p098_buggy_on_play_stay_when_five_big_charas():
    """【登場時】コスト5以上キャラが5枚 (条件成立) → このキャラは場に残る (デッキ下しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("P-098"), sickness=True)
    # バギー + コスト5以上 4 枚 = 計 5 枚 (= 条件成立 → 戻さない)
    others = [InPlay.of(repo.get(COST5A), sickness=False),
              InPlay.of(repo.get(COST5B), sickness=False),
              InPlay.of(repo.get(BIG), sickness=False),
              InPlay.of(repo.get(COST5A), sickness=False)]
    me.characters = [buggy] + others
    deck_before = len(me.deck)

    for prim in _eff(overlay, "P-098", "on_play")["do"]:
        execute_effect(prim, st, me, opp, buggy)

    assert buggy in me.characters, "コスト5以上キャラ5枚なら バギー は場に残るべき"
    assert len(me.deck) == deck_before, "条件成立時 デッキ枚数は変わらないべき"


# --------------------------------------------------------------------------- #
#  P-099 モンキー・D・ルフィ (CHARACTER cost10):
#    【アタック時】ドン‼-10：このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_p099_luffy_on_attack_untap_self_ai():
    """【アタック時】(ドン-10 コスト) このキャラをアクティブにする。
    do (= untap self) を発火すると レストの自身が アクティブに戻る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("P-099"), sickness=False)
    luffy.rested = True  # アタック後のレスト状態
    me.characters = [luffy]

    for prim in _eff(overlay, "P-099", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, luffy)

    assert luffy.rested is False, "アタック時効果で 自身がアクティブに戻っていない"


# --------------------------------------------------------------------------- #
#  P-100 マーシャル・D・ティーチ (CHARACTER cost10):
#    【アタック時】相手のリーダーとキャラすべてを、このターン中、効果を無効にする。
# --------------------------------------------------------------------------- #
def test_p100_teach_on_attack_disable_all_opp_ai():
    """【アタック時】相手リーダー + 相手キャラ全体を このターン中 効果無効にする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("P-100"), sickness=False)
    me.characters = [teach]
    a = InPlay.of(repo.get(COST2), sickness=False)
    b = InPlay.of(repo.get(COST5A), sickness=False)
    opp.characters = [a, b]

    for prim in _eff(overlay, "P-100", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, teach)

    assert "効果無効" in opp.leader.granted_keywords, \
        "相手リーダーが効果無効になっていない"
    assert "効果無効" in a.granted_keywords, "相手キャラ a が効果無効になっていない"
    assert "効果無効" in b.granted_keywords, "相手キャラ b が効果無効になっていない"


# --------------------------------------------------------------------------- #
#  P-101 トニートニー・チョッパー (CHARACTER cost4):
#    【ブロッカー】【登場時】自分のリーダーにレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_p101_chopper_on_play_attach_rested_don_to_leader_ai():
    """【登場時】自リーダーにレストのドン1枚を付与する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _eff(overlay, "P-101", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-101"), sickness=True))

    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  P-102 ナミ (CHARACTER cost4):
#    【登場時】自分のリーダーが特徴《麦わらの一味》を持つ場合、
#    自分のドン‼2枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_p102_nami_on_play_untap_don_with_strawhat_leader_ai():
    """【登場時】(麦わらの一味 leader) レストドン2枚をアクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.don_active = 0

    eff = _eff(overlay, "P-102", "on_play")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "麦わらの一味 leader で条件が成立していない"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-102"), sickness=True))

    assert me.don_active == 2, f"レストドン2枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 0, "レストドンが2枚消費されるべき"


def test_p102_nami_condition_false_non_strawhat_leader():
    """リーダーが《麦わらの一味》を持たなければ 条件不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NON_STRAWHAT_LEADER, overlay)  # ルーシー (麦わらなし)
    me, opp = st.players[0], st.players[1]

    eff = _eff(overlay, "P-102", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非・麦わらの一味 leader で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-103 ポートガス・D・エース (CHARACTER cost4):
#    【登場時】カード2枚を引き、自分の手札2枚を好きな順番に並び替え、デッキの上か下に
#    置く。その後、自分のリーダーにレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_p103_ace_on_play_draw_reorder_attach_ai():
    """【登場時】2ドロー → 手札2枚をデッキへ (net 手札±0) → 自リーダーにレストドン1付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2)]
    me.deck = [repo.get(COST2)] * 10
    me.don_rested = 2

    hand_before = len(me.hand)
    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _eff(overlay, "P-103", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-103"), sickness=True))
    _drain(st, [0])

    # 手札 net: 元1 + ドロー2 - デッキ戻し2 = 1
    assert len(me.hand) == hand_before + 2 - 2, \
        f"手札 net (ドロー+2 デッキ戻し-2) が合わない: {len(me.hand)}"
    assert me.leader.attached_dons == don_before + 1, \
        "その後の自リーダーへのレストドン付与が行われていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  P-105 サボ (CHARACTER cost4):
#    自分のリーダーが特徴《革命軍》を持つ場合、このキャラは【ブロッカー】を得て、コスト+4。
#    【登場時】自分のライフの上か下から1枚を手札に加えることができる：
#    自分のリーダーかキャラ1枚にレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_p105_sabo_on_play_optional_cost_attach_ai():
    """【登場時】(任意コスト: ライフ1枚を手札へ) 自リーダーかキャラ1枚にレストドン1付与。
    AI: コストを払える (ライフあり) なら発動 → 自リーダー (既定) にレストドン付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, REVO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 2
    me.hand = []
    me.don_rested = 2

    life_before = len(me.life)
    don_before = me.leader.attached_dons
    for prim in _eff(overlay, "P-105", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-105"), sickness=True))
    _drain(st, [0])

    assert len(me.life) == life_before - 1, "任意コストで自ライフが1枚減っていない"
    assert len(me.hand) == 1, "ライフから加えたカードが手札に入っていない"
    assert me.leader.attached_dons == don_before + 1, \
        "その後の自リーダーへのレストドン付与が行われていない"


def test_p105_sabo_static_blocker_and_cost_up_with_revo_leader():
    """常在: 革命軍 leader なら 自身は【ブロッカー】を得て コスト+4。
    evaluate_static_effects で is_blocker_now / base_cost_override を検証。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, REVO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("P-105"), sickness=False)  # base cost 4
    me.characters = [sabo]

    evaluate_static_effects(st, overlay)

    assert sabo.is_blocker_now is True, "革命軍 leader で サボ が【ブロッカー】を得ていない"
    assert sabo.base_cost_override == sabo.card.cost + 4, \
        f"革命軍 leader で コスト+4 が反映されていない: {sabo.base_cost_override}"


def test_p105_sabo_static_no_buff_non_revo_leader():
    """リーダーが《革命軍》でなければ ブロッカー付与もコスト+4も起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, STRAWHAT_LEADER, overlay)  # 麦わらの一味 (革命軍なし)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("P-105"), sickness=False)
    me.characters = [sabo]

    evaluate_static_effects(st, overlay)

    assert sabo.is_blocker_now is False, "非・革命軍 leader で ブロッカーが付与されてはいけない"
    assert sabo.base_cost_override is None, \
        "非・革命軍 leader で コスト変更が起きてはいけない"


def test_p105_sabo_on_play_human_optional_then_target_pick():
    """人間: 任意コスト確認 modal → 承諾で 自リーダー/キャラ から付与先を選ぶ target_pick。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, REVO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 2
    me.hand = []
    me.don_rested = 2
    friend = InPlay.of(repo.get(NAMI), sickness=False)
    me.characters = [friend]

    execute_effect(_eff(overlay, "P-105", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-105"), sickness=True))

    # 任意コスト (ライフ1枚) の確認 modal → 承諾 ([1]) で対象選択へ
    assert st.pending_choice is not None, "人間で 任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾

    assert st.pending_choice is not None, "承諾後に付与先選択の target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [friend_idx])
    assert friend.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  P-107 ゴール・Ｄ・ロジャー (CHARACTER cost8):
#    【登場時】自分か相手の場のドン‼が10枚ある場合、自分のリーダーを、
#    次の相手のエンドフェイズ終了時まで、パワー+2000。
# --------------------------------------------------------------------------- #
def test_p107_roger_on_play_pump_leader_when_10_don_ai():
    """【登場時】(場ドン10) 自リーダーを次の相手エンド終了時まで +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 10  # 場ドン 10 → 条件成立

    eff = _eff(overlay, "P-107", "on_play")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "場ドン10で条件が成立していない"

    power_before = me.leader.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-107"), sickness=True))

    assert me.leader.power == power_before + 2000, \
        f"自リーダーに +2000 が反映されていない: {me.leader.power} (before {power_before})"


def test_p107_roger_condition_false_under_10_don():
    """場ドンが10枚未満なら self_don_ge=10 が不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5  # 10 枚未満

    eff = _eff(overlay, "P-107", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "場ドン10未満で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-108 モンキー・D・ルフィ (CHARACTER cost3):
#    【ブロッカー】【KO時】自分のドン‼2枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_p108_luffy_on_ko_untap_don_ai():
    """【KO時】自分のレストドン2枚をアクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    me.don_active = 0

    for prim in _eff(overlay, "P-108", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-108"), sickness=False))

    assert me.don_active == 2, f"KO時にレストドン2枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, "レストドンが2枚消費されるべき"


# --------------------------------------------------------------------------- #
#  P-109 ポートガス・D・エース (CHARACTER cost5):
#    【ブロッカー】【登場時】自分のデッキの上から3枚を見て、好きな順番に並び替え、
#    デッキの上か下に置く。その後、自分のリーダーかキャラ1枚にレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_p109_ace_on_play_reorder_then_attach_ai():
    """【登場時】デッキ上3枚を並び替え → その後 自リーダー (既定) にレストドン1付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(BIG), repo.get(NAMI), repo.get(COST2)] + [repo.get(COST2)] * 10
    me.don_rested = 2

    deck_before = len(me.deck)
    don_before = me.leader.attached_dons
    for prim in _eff(overlay, "P-109", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-109"), sickness=True))
    _drain(st, [0])

    assert len(me.deck) == deck_before, "デッキ並び替えでデッキ枚数が変わってはいけない"
    assert me.leader.attached_dons == don_before + 1, \
        "その後の自リーダーへのレストドン付与が行われていない"
    assert me.don_rested == 1, "レストドンが1枚消費されるべき"


def test_p109_ace_on_play_human_attach_target_pick():
    """人間 + 自リーダー/キャラ 複数 → 付与先を選ぶ target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(COST2)] * 10
    me.don_rested = 2
    friend = InPlay.of(repo.get(NAMI), sickness=False)
    me.characters = [friend]

    # do[0] = look_top_reorder (choice=ヒューリスティック、 modal なし)、 do[1] = attach 対象選択
    for prim in _eff(overlay, "P-109", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-109"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [friend_idx])
    assert friend.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"
