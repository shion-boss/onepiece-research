# -*- coding: utf-8 -*-
"""ST-36 (黄キッド) 新規 5 カード (ST36-001〜005) + プロモ P-150 (クザン) / P-151 (スモーカー)
の効果 回帰テスト。

目的 (= 永続的 pytest による 担保):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する
  (2) 対象選択 / 任意コスト / flip を持つカードは 人間 actor で pending_choice が
      正しく立ち、 resolve できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず解決する
      (= AI が選べる)

最重要 = ST36-005 ユースタス・キッド:
  - 【相手のアタック時】flip_life_face_down コスト → アタック対象を 自 キッド(元々P5000+) へ redirect
  - 【起動メイン】flip_life_face_up コスト → 自リーダーに レストドン 1 枚付与
  - 両効果とも 【ターン1回】
  - 新 primitive flip_life_face_up / flip_life_face_down で ライフの表裏 (face_up_life_count)
    が実際に変化することを明示的に検証する。
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
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_st36_and_promo_cards_have_overlay():
    """7 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST36-001", "ST36-002", "ST36-003", "ST36-004", "ST36-005",
           "P-150", "P-151"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST36-001 キャベンディッシュ: 【KO時】手札1枚捨てて → デッキ上1枚をライフへ
# --------------------------------------------------------------------------- #
def test_st36_001_cavendish_on_ko_ai():
    """KO時 optional_cost_then: 手札を1枚捨て、 デッキ上1枚をライフの上に加える。
    AI (human_idx=None) は payable なら自動で払って発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]        # 捨てる手札 1 枚
    me.deck = [repo.get("OP01-016")] + [repo.get("OP01-013")] * 20  # デッキ上を識別可能に
    me.life = [repo.get("OP01-013")]

    life_before = len(me.life)
    hand_before = len(me.hand)
    cav_eff = overlay.get("ST36-001").effects[0]["do"]
    for prim in cav_eff:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before - 1, "コストの手札1捨てが起きていない"
    assert len(me.life) == life_before + 1, "デッキ上1枚がライフに加わっていない"
    assert me.life[-1].card_id == "OP01-016", "デッキ最上部がライフに乗るべき"


def test_st36_001_cavendish_human_declines():
    """人間 actor は optional_cost_then を 見送れる。 手札 0 枚 (= 払えない) では
    cost が payable でなく、 効果も起きない (= silent no-op でなく False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []          # 捨てられない
    me.life = [repo.get("OP01-013")]
    me.deck = [repo.get("OP01-016")] * 5

    life_before = len(me.life)
    prim = overlay.get("ST36-001").effects[0]["do"][0]
    result = execute_effect(prim, st, me, opp, None)
    assert result is False, "払えない optional_cost_then は False を返す"
    assert len(me.life) == life_before, "コスト不能なら効果も起きない"


# --------------------------------------------------------------------------- #
#  ST36-002 キラー: 自ターン登場時 (キッドleader) ライフ+1 / トリガー 相手ライフ3以下で登場
# --------------------------------------------------------------------------- #
def test_st36_002_killer_on_play_with_kid_leader():
    """自ターン + リーダー特徴《キッド海賊団》 → デッキ上1枚をライフへ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)  # OP10-099 = キッド海賊団 leader
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] + [repo.get("OP01-013")] * 20
    me.life = [repo.get("OP01-013")] * 2

    life_before = len(me.life)
    ip = InPlay.of(repo.get("ST36-002"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    assert len(me.life) == life_before + 1, \
        "キッドleader の自ターン登場時にライフが増えていない"
    assert me.life[-1].card_id == "OP01-016"


def test_st36_002_killer_on_play_no_kid_leader():
    """リーダーが《キッド海賊団》でない場合は条件不成立 → ライフ不変。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (麦わら) = キッド海賊団でない
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 20
    me.life = [repo.get("OP01-013")] * 2

    life_before = len(me.life)
    ip = InPlay.of(repo.get("ST36-002"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)
    assert len(me.life) == life_before, \
        "非キッドleader では条件不成立でライフが変わってはいけない"


def test_st36_002_killer_trigger_plays_self_when_opp_life_le3():
    """【トリガー】相手ライフ3以下 → このカードを登場させる (play_self)。"""
    repo = _repo()
    overlay = _overlay()
    trig = next(e for e in overlay.get("ST36-002").effects if e["when"] == "trigger")
    assert trig.get("if", {}).get("opp_life_le") == 3, \
        "トリガー条件 opp_life_le=3 が overlay に無い"

    # 相手ライフ 3 → 発火して場に登場
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 3
    # play_self は state.current_source_card_id を参照し、 trash/hand から そのカードを探す。
    # ライフトリガーは発動後カードがトラッシュに置かれる (= trash から場へ) 挙動を再現。
    me.trash = [repo.get("ST36-002")]
    st.current_source_card_id = "ST36-002"
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "ST36-002" for c in me.characters), \
        "相手ライフ3以下で キラーが場に登場していない"


# --------------------------------------------------------------------------- #
#  ST36-003 スクラッチメン・アプー: 【トリガー】 draw1 + 超新星leader を 7000 に
# --------------------------------------------------------------------------- #
def test_st36_003_apoo_trigger_draw_and_leader_power():
    """トリガー: 1枚引き、 超新星リーダーをこのターン中 元々のパワー7000 に。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)  # OP10-099 = 超新星 leader (元々 5000)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 10
    me.hand = []
    leader_base = me.leader.card.power  # 5000

    trig = overlay.get("ST36-003").effects[0]
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 1, "トリガーの draw が起きていない"
    assert me.leader.power == 7000, \
        f"超新星リーダーが7000にならない (現状 {me.leader.power}, base {leader_base})"


def test_st36_003_apoo_trigger_non_shinsei_leader():
    """リーダーが《超新星》でなければ power は 変わらない (draw のみ)。"""
    repo = _repo()
    overlay = _overlay()
    # ST10-003 = キッド海賊団のみ (超新星 なし)
    st = _state(repo, "ST10-003", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 10
    me.hand = []
    base = me.leader.power

    for prim in overlay.get("ST36-003").effects[0]["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 1, "draw は無条件で起きる"
    assert me.leader.power == base, "非超新星リーダーは power 変化しない"


# --------------------------------------------------------------------------- #
#  ST36-004 バルトロメオ: 登場時 超新星カード1枚捨てられる → 2ドロー
# --------------------------------------------------------------------------- #
def test_st36_004_barto_on_play_discard_super_rookie_draw2_ai():
    """AI: 手札に《超新星》カードがあれば 捨てて 2 ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    # ST36-005 キッドは《超新星》? → features 確認: キッドleader は超新星だが char は? 使わず
    # 手札に確実に 超新星 を持つカード = ST36-004 自身 (feature 超新星) を入れる
    super_rookie = repo.get("ST36-004")  # バルトロメオ自身も 超新星
    assert "超新星" in (super_rookie.features or ""), "テスト前提: ST36-004 は超新星"
    me.hand = [super_rookie]  # 捨てるコスト用
    me.deck = [repo.get("OP01-013")] * 10

    hand_before = len(me.hand)
    ip = InPlay.of(repo.get("ST36-004"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)

    # cost -1 (超新星捨て) + draw2 → net +1
    assert len(me.hand) == hand_before - 1 + 2, \
        f"超新星捨て→2ドローの net が合わない: {len(me.hand)}"


def test_st36_004_barto_on_play_no_super_rookie():
    """手札に《超新星》が無ければ cost 不能 → ドローしない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 超新星でない
    me.deck = [repo.get("OP01-013")] * 10

    hand_before = len(me.hand)
    ip = InPlay.of(repo.get("ST36-004"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(st, me, opp, ip, overlay)
    assert len(me.hand) == hand_before, \
        "超新星が無いのにドローしてはいけない (任意コスト不能)"


# --------------------------------------------------------------------------- #
#  ST36-005 ユースタス・キッド (最重要)
# --------------------------------------------------------------------------- #
def test_flip_life_face_down_primitive():
    """新 primitive flip_life_face_down: 表向きライフ枚数 (face_up_life_count) を 1 減らす。"""
    repo = _repo()
    st = _state(repo, "OP10-099", {})
    me = st.players[0]
    me.life = [repo.get("OP01-013")] * 3
    me.face_up_life_count = 2  # 事前に 2 枚表向き

    from engine.effects import _pay_counter_cost
    _pay_counter_cost(st, me, st.players[1], me.leader,
                      {"flip_life_face_down": True})
    assert me.face_up_life_count == 1, "flip_life_face_down で表向き枚数が1減らない"


def test_flip_life_face_up_primitive():
    """新 primitive flip_life_face_up: 表向きライフ枚数を 1 増やす (裏→表)。"""
    repo = _repo()
    st = _state(repo, "OP10-099", {})
    me = st.players[0]
    me.life = [repo.get("OP01-013")] * 3
    me.face_up_life_count = 0  # 全部裏向き (= 通常)

    from engine.effects import _pay_counter_cost
    _pay_counter_cost(st, me, st.players[1], me.leader,
                      {"flip_life_face_up": True})
    assert me.face_up_life_count == 1, "flip_life_face_up で表向き枚数が1増えない"


def test_flip_life_cost_payability_bounds():
    """flip コストの payability: 表向き/裏向きが 0 枚だと払えない。"""
    repo = _repo()
    from engine.effects import _can_pay_counter_cost
    st = _state(repo, "OP10-099", {})
    me = st.players[0]
    me.life = [repo.get("OP01-013")] * 2

    # face_up=0 → 裏向きにできる表向きが無い → flip_face_down 不能
    me.face_up_life_count = 0
    assert not _can_pay_counter_cost(st, me, me.leader, {"flip_life_face_down": True})
    # 表向きにできる裏向きはある → flip_face_up 可
    assert _can_pay_counter_cost(st, me, me.leader, {"flip_life_face_up": True})

    # face_up=2 (全表向き) → 裏向きにできる → flip_face_down 可 / 表向きにする裏が無い
    me.face_up_life_count = 2
    assert _can_pay_counter_cost(st, me, me.leader, {"flip_life_face_down": True})
    assert not _can_pay_counter_cost(st, me, me.leader, {"flip_life_face_up": True})


def _kid_char(repo):
    """元々のパワー7000 の ST36-005 = truly_original_power_ge 5000 を満たす。"""
    return InPlay.of(repo.get("ST36-005"), sickness=False)


def test_st36_005_redirect_attack_ai_auto_selects():
    """AI 文脈: redirect_attack candidates (= 元々P5000+ の キッド) が 1 体 → 自動選択。
    pending_attack_redirect にそのキャラが設定される (crash せず解決)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)  # AI (human_idx None)
    me, opp = st.players[0], st.players[1]
    kid = _kid_char(repo)
    me.characters = [kid]

    opp_eff = next(e for e in overlay.get("ST36-005").effects
                   if e["when"] == "opp_attack")
    redirect_prim = opp_eff["do"][0]  # {"redirect_attack": {...}}
    execute_effect(redirect_prim, st, me, opp, kid)

    assert st.pending_attack_redirect == kid.instance_id, \
        "AI で redirect 先 (自キッド) が自動選択されていない"


def test_st36_005_redirect_attack_human_pick_when_multiple():
    """人間 文脈 + キッド 2 体 → target_pick modal が立ち、 resolve で 1 体に確定。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    kid_a = _kid_char(repo)
    kid_b = _kid_char(repo)
    me.characters = [kid_a, kid_b]

    opp_eff = next(e for e in overlay.get("ST36-005").effects
                   if e["when"] == "opp_attack")
    redirect_prim = opp_eff["do"][0]
    execute_effect(redirect_prim, st, me, opp, kid_a)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    resolve_pending_choice(st, [1])  # 2 体目を選択
    assert st.pending_choice is None, "解決後も modal が残る"
    assert st.pending_attack_redirect == kid_b.instance_id, \
        "人間が選んだ redirect 先が反映されていない"


def test_st36_005_redirect_excludes_weak_kid():
    """redirect 候補は 元々のパワー5000以上 の「ユースタス・キッド」のみ。
    別名 / 低パワーは対象外 (= 候補 0 → 効果不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    # 名前は キッドだが 元々パワー < 5000 のカードは無いので、 別カード (非キッド) を置く
    not_kid = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ 名前違い
    me.characters = [not_kid]
    st.pending_attack_redirect = None

    opp_eff = next(e for e in overlay.get("ST36-005").effects
                   if e["when"] == "opp_attack")
    execute_effect(opp_eff["do"][0], st, me, opp, not_kid)
    assert st.pending_attack_redirect is None, \
        "非キッドが redirect 対象になってはいけない (candidate 0 で不発)"


def test_st36_005_activate_main_flip_up_attach_rested_don_ai():
    """【起動メイン】 flip_life_face_up コスト → 自リーダーに レストドン1付与。
    list_activate_main / fire_activate_main で AI が発動し、
    (1) face_up_life_count が +1 (2) リーダーに attached_dons +1 を検証。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)  # AI
    me, opp = st.players[0], st.players[1]
    kid = _kid_char(repo)
    me.characters = [kid]
    me.life = [repo.get("OP01-013")] * 3
    me.face_up_life_count = 0        # 裏向き (= 表にできる)
    me.don_rested = 2                # レストドン供給源

    fu_before = me.face_up_life_count
    don_before = me.leader.attached_dons
    rested_before = me.don_rested

    options = list_activate_main_effects(st, me, overlay)
    kid_opts = [(src, eff) for (src, eff) in options
                if src.card.card_id == "ST36-005"]
    assert len(kid_opts) == 1, \
        f"ST36-005 の起動メインが legal に出ない: {len(kid_opts)}"
    src, eff = kid_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert me.face_up_life_count == fu_before + 1, \
        "flip_life_face_up コストで表向きライフが増えていない"
    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_st36_005_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    kid = _kid_char(repo)
    me.characters = [kid]
    me.life = [repo.get("OP01-013")] * 3
    me.face_up_life_count = 0
    me.don_rested = 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST36-005"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST36-005"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_st36_005_activate_main_human_flip_confirm():
    """人間 actor: 起動メインの optional_cost_then (flip_up コスト) は「払うか？」の
    確認 modal (optional_cost_confirm) を立てる。 承諾すると flip_up→ドン付与が解決する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    kid = _kid_char(repo)
    me.characters = [kid]
    me.life = [repo.get("OP01-013")] * 3
    me.face_up_life_count = 0
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST36-005"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    # 人間は 任意コスト を 払うか 選べる (= 選択肢を持つ)
    assert st.pending_choice is not None, "人間の任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1

    assert me.leader.attached_dons == 1, "人間承諾後にドン付与が完了するべき"
    assert me.face_up_life_count == 1, "flip_up でライフ表向きが増えるべき"


def test_st36_005_activate_main_human_decline():
    """人間 actor は 任意コスト を 見送れる (= optional_cost_confirm で拒否 → 効果なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    kid = _kid_char(repo)
    me.characters = [kid]
    me.life = [repo.get("OP01-013")] * 3
    me.face_up_life_count = 0
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST36-005"]
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice.get("kind") == "optional_cost_confirm"
    resolve_pending_choice(st, [0])  # 拒否 (= 払わない)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert me.leader.attached_dons == 0, "見送ったのにドンが付与されてはいけない"
    assert me.face_up_life_count == 0, "見送ったのにライフが表向きになってはいけない"


# --------------------------------------------------------------------------- #
#  P-150 クザン: 登場時 トラッシュからコスト1【トリガー】キャラ登場 + トリガー
# --------------------------------------------------------------------------- #
def _cost1_trigger_char_ids():
    """トラッシュから登場させる用: コスト1 かつ【トリガー】を持つキャラの card_id 群。"""
    import json
    data = json.load(open(ROOT / "db" / "cards.json"))
    out = []
    for c in data:
        if (c.get("category") == "CHARACTER" and str(c.get("cost")).isdigit()
                and int(c["cost"]) == 1 and (c.get("trigger") or "").strip()):
            out.append(c["card_id"])
    return out


def test_p150_kuzan_on_play_summons_cost1_trigger_from_trash_ai():
    """自ターン登場時: トラッシュのコスト1【トリガー】キャラを登場させる。"""
    repo = _repo()
    overlay = _overlay()
    ids = _cost1_trigger_char_ids()
    assert ids, "コスト1トリガーキャラが cards に存在しない (前提失敗)"
    cid = ids[0]
    trig_card = repo.get(cid)

    st = _state(repo, "OP10-099", overlay)  # AI, 自ターン
    me, opp = st.players[0], st.players[1]
    me.trash = [trig_card]  # トラッシュに登場候補

    chars_before = len(me.characters)
    ip = InPlay.of(repo.get("P-150"), sickness=True)
    me.characters.append(ip)  # クザン自身
    trigger_on_play(st, me, opp, ip, overlay)

    # クザン(+1) と トラッシュから登場した キャラ(+1) で +2 (少なくとも 登場が起きる)
    played = [c for c in me.characters if c.card.card_id == cid]
    assert len(played) >= 1, "P-150 でトラッシュからコスト1トリガーキャラが登場していない"
    assert len(me.characters) >= chars_before + 2


def test_p150_kuzan_on_play_human_pick_when_multiple():
    """人間 + トラッシュに候補複数 → play_from_trash の pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    cids = _cost1_trigger_char_ids()
    assert len(cids) >= 1
    # 2 種類以上あれば複数候補、 無ければ同一2枚でも候補2件
    two = cids[:2] if len(cids) >= 2 else [cids[0], cids[0]]

    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(two[0]), repo.get(two[1])]

    on_play_eff = next(e for e in overlay.get("P-150").effects
                       if e["when"] == "on_play")
    execute_effect(on_play_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-150"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_trash modal が立たない"
    assert "play_from_trash" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_trash 系でない: {st.pending_choice.get('kind')}"
    # 解決できること
    resolve_pending_choice(st, [0])
    # 解決後は残 modal (bottom reorder 等) を流す
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1


def test_p150_kuzan_on_play_empty_trash_no_crash():
    """トラッシュが空 → 候補 0 で silent に何も登場せず crash しない (AI/人間 両方)。"""
    repo = _repo()
    overlay = _overlay()
    for human in (None, 0):
        st = _state(repo, "OP10-099", overlay, human_idx=human)
        me, opp = st.players[0], st.players[1]
        me.trash = []
        chars_before = len(me.characters)
        ip = InPlay.of(repo.get("P-150"), sickness=True)
        me.characters.append(ip)
        trigger_on_play(st, me, opp, ip, overlay)
        # クザン自身のみ (登場相手なし)
        assert len(me.characters) == chars_before + 1


# --------------------------------------------------------------------------- #
#  P-151 スモーカー: 登場時 任意discard → 海軍leaderでドン追加 + 海軍サーチ
# --------------------------------------------------------------------------- #
def test_p151_smoker_on_play_navy_leader_don_and_search_ai():
    """海軍リーダー + 手札を1枚捨てる → レストドン1追加 + デッキ上5枚から海軍1枚サーチ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST06-001", overlay)  # ST06-001 サカズキ = 海軍 leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]           # 捨てるコスト用
    me.don_remaining_in_deck = 5
    # デッキ上5枚に海軍カードを1枚仕込む (P-151 自身=海軍 を使う)
    navy = repo.get("P-151")
    assert "海軍" in (navy.features or ""), "テスト前提: P-151 は海軍"
    me.deck = [navy] + [repo.get("OP01-013")] * 20

    don_rested_before = me.don_rested
    hand_before = len(me.hand)

    on_play_eff = next(e for e in overlay.get("P-151").effects
                       if e["when"] == "on_play")
    execute_effect(on_play_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-151"), sickness=True))

    assert me.don_rested == don_rested_before + 1, \
        "海軍リーダーでのレストドン追加が起きていない"
    assert any(c.card_id == "P-151" for c in me.hand), \
        "デッキ上5枚から海軍カードが手札に加わっていない"
    # net: cost -1 (discard) + search +1 = ±0 だが 特定カードが手札に来ていること重要
    assert len(me.hand) == hand_before - 1 + 1


def test_p151_smoker_on_play_non_navy_leader_no_don():
    """非海軍リーダー → discard は払えるが ドン追加は条件不成立 (サーチのみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ = 非海軍
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    me.don_remaining_in_deck = 5
    me.deck = [repo.get("OP01-013")] * 20  # 海軍カードなし

    don_before = me.don_rested
    on_play_eff = next(e for e in overlay.get("P-151").effects
                       if e["when"] == "on_play")
    execute_effect(on_play_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-151"), sickness=True))
    assert me.don_rested == don_before, \
        "非海軍リーダーで ドン追加が起きてはいけない (conditional 不成立)"


def test_p151_smoker_on_play_human_search_pick():
    """人間 + デッキ上5枚に海軍複数 → search_top_n の pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST06-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    me.don_remaining_in_deck = 5
    navy = repo.get("P-151")
    # デッキ上5枚のうち複数を海軍に
    me.deck = [navy, navy, repo.get("OP01-013"), navy, repo.get("OP01-013")] \
        + [repo.get("OP01-013")] * 15

    on_play_eff = next(e for e in overlay.get("P-151").effects
                       if e["when"] == "on_play")
    execute_effect(on_play_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-151"), sickness=True))

    # 人間は 任意コスト を 払うか 選べる → まず optional_cost_confirm。 承諾すると
    # discard(自動) → conditional(ドン) → search_top_n の順で 海軍サーチ modal が立つ。
    saw_confirm = False
    saw_search = False
    guard = 0
    while st.pending_choice is not None and guard < 10:
        kind = st.pending_choice.get("kind", "")
        if kind == "optional_cost_confirm":
            saw_confirm = True
            resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
        elif "search_top_n" in kind:
            saw_search = True
            resolve_pending_choice(st, [0])  # 先頭 (海軍) を選択
        else:
            resolve_pending_choice(st, [0])
        guard += 1
    assert saw_confirm, "人間の任意コスト確認 modal が立たなかった"
    assert saw_search, "P-151 の海軍サーチで search_top_n modal が立たなかった"
    assert any(c.card_id == "P-151" for c in me.hand), \
        "人間が選んだ海軍カードが手札に入っていない"
