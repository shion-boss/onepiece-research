# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 098):
OP09-087 / OP09-088 / OP09-089 / OP09-090 / OP09-092 /
OP09-095 / OP09-096 / OP09-097 / OP09-098 / OP09-100 の 10 枚
(黒 黒ひげ海賊団 手札破壊/ドロー/除去/サーチ/効果無効 系 + 黄 革命軍 ブロッカー)。

目的 (= test_backfill_auto_001〜097.py と同一方針):
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
    eval_all_conditions,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_KUROHIGE = "OP09-081"  # マーシャル・D・ティーチ (leader、 四皇/黒ひげ海賊団)
_LEADER_REVO = "OP07-001"      # モンキー・D・ドラゴン (leader、 革命軍)
_LEADER_MUGIWARA = "OP01-001"  # ロロノア・ゾロ (leader、 超新星/麦わらの一味)
_FILLER = "ST01-004"           # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SMALL = "OP01-016"            # ナミ cost1 power2000 (バニラ)
_SMALL_B = "OP01-077"          # ペローナ cost1 (バニラ、 相手キャラ 2 体目)
_KUROHIGE_CARD = "OP09-089"    # ストロンガー (特徴《黒ひげ海賊団》、 サーチ対象)


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


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


def _am_opts(st, me, overlay, cid):
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op09_wave098_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-087", "OP09-088", "OP09-089", "OP09-090", "OP09-092",
           "OP09-095", "OP09-096", "OP09-097", "OP09-098", "OP09-100"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-087 シャーロット・プリン (CHARACTER): 【登場時】相手の手札が5枚以上ある場合、
#          相手は自身の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op09_087_on_play_opp_discard_ai():
    """【登場時】相手手札5枚以上 → 相手手札1枚をランダムに捨てさせる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 5

    trash_before = len(opp.trash)
    for prim in _eff(overlay, "OP09-087", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-087"), sickness=True))
    assert len(opp.hand) == 4, f"相手手札が1枚捨てられていない: {len(opp.hand)}"
    assert len(opp.trash) == trash_before + 1, \
        "捨てた相手手札がトラッシュに置かれていない"


def test_op09_087_condition_requires_opp_hand_5():
    """条件 opp_hand_count_ge:5。 相手手札4枚では発火条件を満たさない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "OP09-087", "on_play")
    assert eff.get("if", {}).get("opp_hand_count_ge") == 5, \
        "overlay の 条件 opp_hand_count_ge=5 が無い"

    opp.hand = [repo.get(_FILLER)] * 4
    assert eval_all_conditions(eff, st, me, None) is False, \
        "相手手札4枚で条件が成立してはいけない"
    opp.hand = [repo.get(_FILLER)] * 5
    assert eval_all_conditions(eff, st, me, None) is True, \
        "相手手札5枚で条件が成立するべき"


# --------------------------------------------------------------------------- #
#  OP09-088 シリュウ (CHARACTER): 【ドン!!×1】【アタック時】自分の手札2枚を捨てる
#          ことができる：カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_088_attack_optional_discard_draw_ai():
    """【アタック時】(任意: 手札2捨て → 2ドロー)。 AI: 手札3枚 → -2捨て +2引き = 3 (net 0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    att = InPlay.of(repo.get("OP09-088"), sickness=False)
    att.attached_dons = 1  # 【ドン!!×1】ゲート
    me.characters = [att]
    me.hand = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 5

    eff = _eff(overlay, "OP09-088", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    trash_before = len(me.trash)
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, att)
    _drain(st, [0])
    assert len(me.trash) == trash_before + 2, "手札2枚が捨てられていない (任意コスト)"
    assert len(me.deck) == deck_before - 2, "カード2枚が引かれていない"
    assert len(me.hand) == 3, f"手札 net (-2 捨て +2 引き) が合わない: {len(me.hand)}"


def test_op09_088_attack_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal → 承諾で 2捨て2引き。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    att = InPlay.of(repo.get("OP09-088"), sickness=False)
    att.attached_dons = 1
    me.characters = [att]
    me.hand = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 5

    execute_effect(_eff(overlay, "OP09-088", "on_attack")["do"][0],
                   st, me, opp, att)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    deck_before = len(me.deck)
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, "承諾後 カード2枚が引かれていない"


# --------------------------------------------------------------------------- #
#  OP09-089 ストロンガー (CHARACTER): 【起動メイン】自分の手札1枚を捨て、このキャラを
#          トラッシュに置くことができる：自リーダーが《黒ひげ海賊団》なら、カード1枚を引く。
#          その後、相手のキャラ1枚までを、このターン中、コスト-2。
# --------------------------------------------------------------------------- #
def test_op09_089_activate_main_draw_cost_minus_ai():
    """【起動メイン】(自トラッシュ + 手札1捨てコスト): 黒ひげ leader で 1ドロー +
    相手キャラ1枚 コスト-2 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    strn = InPlay.of(repo.get("OP09-089"), sickness=False)
    me.characters = [strn]
    me.hand = [repo.get(_FILLER)]  # 捨てコスト用
    me.deck = [repo.get(_FILLER)] * 5
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    opts = _am_opts(st, me, overlay, "OP09-089")
    assert len(opts) == 1, f"OP09-089 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    # コスト: 自身がトラッシュへ + 手札1捨て、 その後 1 ドロー (net hand = 1)
    assert strn not in me.characters, "コストで ストロンガー がトラッシュに置かれるべき"
    assert len(me.hand) == 1, f"手札 net (-1 捨て +1 引き) が合わない: {len(me.hand)}"
    assert victim.cost_minus_until_turn_end == 2, \
        f"相手キャラの コスト-2 が反映されていない: {victim.cost_minus_until_turn_end}"


def test_op09_089_activate_main_gated_by_leader():
    """自リーダーが《黒ひげ海賊団》でない場合、 起動メインは legal に出ない (リーダー条件)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)  # 麦わら = 黒ひげでない
    me, opp = st.players[0], st.players[1]
    strn = InPlay.of(repo.get("OP09-089"), sickness=False)
    me.characters = [strn]
    me.hand = [repo.get(_FILLER)]

    eff = _eff(overlay, "OP09-089", "activate_main")
    assert eff.get("if", {}).get("leader_feature") == "黒ひげ海賊団", \
        "overlay の リーダー条件 (黒ひげ海賊団) が無い"
    assert len(_am_opts(st, me, overlay, "OP09-089")) == 0, \
        "黒ひげでない leader で 起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP09-090 ドクQ (CHARACTER): 【起動メイン】このキャラをレストにできる：自リーダーが
#          《黒ひげ海賊団》なら、相手のコスト1以下のキャラ1枚までを、KOする。
#          【KO時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_090_activate_main_ko_cost1_ai():
    """【起動メイン】(自レストコスト): 黒ひげ leader で 相手コスト1以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    docq = InPlay.of(repo.get("OP09-090"), sickness=False)
    me.characters = [docq]
    victim = InPlay.of(repo.get(_SMALL), sickness=False)  # ナミ cost1 (≤1)
    opp.characters = [victim]

    opts = _am_opts(st, me, overlay, "OP09-090")
    assert len(opts) == 1, f"OP09-090 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"
    assert docq.rested is True, "起動メインコストで ドクQ がレストされるべき"


def test_op09_090_activate_main_ko_human_pick():
    """人間 + 相手コスト1キャラ複数 → target_pick modal で選んだ1枚だけ KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    docq = InPlay.of(repo.get("OP09-090"), sickness=False)
    me.characters = [docq]
    a = InPlay.of(repo.get(_SMALL), sickness=False)     # cost1
    b = InPlay.of(repo.get(_SMALL_B), sickness=False)   # cost1
    opp.characters = [a, b]

    fire_activate_main(st, me, opp, *_am_opts(st, me, overlay, "OP09-090")[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op09_090_on_ko_draw_ai():
    """【KO時】カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 5
    me.hand = []

    for prim in _eff(overlay, "OP09-090", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-090"), sickness=False))
    assert len(me.hand) == 1, f"KO時の1枚ドローが起きていない: hand={len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP09-092 マーシャル・D・ティーチ (CHARACTER): 【起動メイン】このキャラをレストにできる：
#          自分の手札が相手の手札より3枚以上少ない場合、カード2枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op09_092_activate_main_draw_discard_ai():
    """【起動メイン】(自レストコスト): 自手札が相手より3枚以上少ない → 2引き1捨て (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("OP09-092"), sickness=False)
    me.characters = [teach]
    me.hand = [repo.get(_FILLER)] * 1      # 自手札 1
    opp.hand = [repo.get(_FILLER)] * 5     # 相手手札 5 → diff -4 (≤ -3)
    me.deck = [repo.get(_FILLER)] * 5

    opts = _am_opts(st, me, overlay, "OP09-092")
    assert len(opts) == 1, f"OP09-092 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    # 手札: start 1 + 2 引き - 1 捨て = 2
    assert len(me.hand) == 2, f"手札 net (+2 引き -1 捨て) が合わない: {len(me.hand)}"
    assert teach.rested is True, "起動メインコストで ティーチ がレストされるべき"


def test_op09_092_activate_main_gated_by_hand_diff():
    """手札差が -3 未満 (= 3枚以上少なくない) なら 起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("OP09-092"), sickness=False)
    me.characters = [teach]
    me.hand = [repo.get(_FILLER)] * 4
    opp.hand = [repo.get(_FILLER)] * 4  # diff 0

    eff = _eff(overlay, "OP09-092", "activate_main")
    assert eff.get("if", {}).get("self_hand_diff_le") == -3, \
        "overlay の 条件 self_hand_diff_le=-3 が無い"
    assert len(_am_opts(st, me, overlay, "OP09-092")) == 0, \
        "手札差が条件を満たさないのに 起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP09-095 ラフィット (CHARACTER): 【起動メイン】自分のドン!!1枚とこのキャラをレストに
#          できる：自分のデッキの上から5枚を見て、特徴《黒ひげ海賊団》を持つカード1枚までを
#          公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op09_095_activate_main_search_kurohige_ai():
    """【起動メイン】(ドン1レスト + 自レスト): 上5枚から 黒ひげ海賊団 カードを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    laf = InPlay.of(repo.get("OP09-095"), sickness=False)
    me.characters = [laf]
    me.don_active = 2  # ドン1枚をレストするコスト用
    me.deck = [repo.get(_KUROHIGE_CARD)] + [repo.get(_FILLER)] * 20
    me.hand = []

    opts = _am_opts(st, me, overlay, "OP09-095")
    assert len(opts) == 1, f"OP09-095 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert any(c.card_id == _KUROHIGE_CARD for c in me.hand), \
        "上5枚から 黒ひげ海賊団 カードが手札に加わっていない"
    assert laf.rested is True, "起動メインコストで ラフィット がレストされるべき"


def test_op09_095_activate_main_search_human_pick():
    """人間 + 上5枚に 黒ひげ海賊団 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    laf = InPlay.of(repo.get("OP09-095"), sickness=False)
    me.characters = [laf]
    me.don_active = 2
    me.deck = [repo.get(_KUROHIGE_CARD), repo.get(_FILLER),
               repo.get(_KUROHIGE_CARD)] + [repo.get(_FILLER)] * 15
    me.hand = []

    fire_activate_main(st, me, opp, *_am_opts(st, me, overlay, "OP09-095")[0])
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (黒ひげ) を選択
    _drain(st, [])
    assert any(c.card_id == _KUROHIGE_CARD for c in me.hand), \
        "人間が選んだ 黒ひげ海賊団 カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-096 おれの時代だァ!!!! (EVENT): 【メイン】自分のデッキの上から3枚を見て、
#          「おれの時代だァ!!!!」以外の特徴《黒ひげ海賊団》を持つカード1枚までを公開し、
#          手札に加える。その後、残りをトラッシュに置く。 【トリガー】この【メイン】効果。
# --------------------------------------------------------------------------- #
def test_op09_096_main_search_kurohige_ai():
    """【メイン】上3枚から 黒ひげ海賊団 カードを手札へ、 残りをトラッシュへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_KUROHIGE_CARD)] + [repo.get(_FILLER)] * 20
    me.hand = []

    trash_before = len(me.trash)
    for prim in _eff(overlay, "OP09-096", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == _KUROHIGE_CARD for c in me.hand), \
        "上3枚から 黒ひげ海賊団 カードが手札に加わっていない"
    # 手札に加えた 1 枚以外の 2 枚がトラッシュへ
    assert len(me.trash) == trash_before + 2, \
        f"残り2枚がトラッシュに置かれていない: trash+{len(me.trash) - trash_before}"


def test_op09_096_main_search_human_pick():
    """人間 + 上3枚に 黒ひげ海賊団 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_KUROHIGE_CARD), repo.get(_FILLER),
               repo.get(_KUROHIGE_CARD)] + [repo.get(_FILLER)] * 15
    me.hand = []

    execute_effect(_eff(overlay, "OP09-096", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id == _KUROHIGE_CARD for c in me.hand), \
        "人間が選んだ 黒ひげ海賊団 カードが手札に加わっていない"


def test_op09_096_trigger_copies_main_ai():
    """【トリガー】この【メイン】効果を発動する (= main のコピー) → サーチが走る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_KUROHIGE_CARD)] + [repo.get(_FILLER)] * 20
    me.hand = []
    st.current_source_card_id = "OP09-096"

    for prim in _eff(overlay, "OP09-096", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == _KUROHIGE_CARD for c in me.hand), \
        "トリガー (メイン効果コピー) で 黒ひげ海賊団 カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-097 闇水 (EVENT): 【カウンター】相手のリーダーかキャラ1枚までを、このターン中、
#          効果を無効にし、パワー-4000。 【トリガー】相手のリーダーかキャラ1枚まで 効果無効。
# --------------------------------------------------------------------------- #
def test_op09_097_counter_negate_and_debuff_ai():
    """【カウンター】相手キャラ1枚を 効果無効 + パワー-4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP09-097", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.power == power_before - 4000, \
        f"相手キャラの パワー-4000 が反映されていない: {victim.power} (before {power_before})"
    assert "効果無効" in victim.granted_keywords, \
        "相手キャラに 効果無効 が付与されていない"


def test_op09_097_counter_human_pick():
    """人間 + 相手リーダー/キャラ (one_opponent_inplay_any) → 効果無効の target_pick modal が
    立ち、 選んだキャラに 効果無効 が付与される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]  # リーダー + キャラ = 2 候補

    # do[0] = 効果無効 (target one_opponent_inplay_any) → 人間で target_pick modal
    execute_effect(_eff(overlay, "OP09-097", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    vi = next(i for i, c in enumerate(cands) if c["iid"] == victim.instance_id)
    resolve_pending_choice(st, [vi])
    _drain(st, [vi])
    assert "効果無効" in victim.granted_keywords, \
        "人間が選んだ相手キャラに 効果無効 が付与されていない"


# --------------------------------------------------------------------------- #
#  OP09-098 闇穴道 (EVENT): 【メイン】自リーダーが《黒ひげ海賊団》なら、相手のキャラ1枚
#          までを、このターン中、効果を無効にする。その後、そのキャラのコストが4以下の場合、
#          KOする。 【トリガー】相手リーダーかキャラ1枚 効果無効。
# --------------------------------------------------------------------------- #
def test_op09_098_main_negate_then_ko_ai():
    """【メイン】黒ひげ leader: 相手キャラを 効果無効 → コスト4以下なら KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤4)
    opp.characters = [victim]

    trash_before = len(opp.trash)
    for prim in _eff(overlay, "OP09-098", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "コスト4以下の相手キャラが KO されていない"
    assert len(opp.trash) == trash_before + 1, "KO キャラがトラッシュに置かれていない"


def test_op09_098_main_gated_by_leader():
    """自リーダーが《黒ひげ海賊団》でない場合、 【メイン】効果は発火条件を満たさない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)  # 麦わら = 黒ひげでない
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "OP09-098", "main")
    assert eff.get("if", {}).get("leader_feature") == "黒ひげ海賊団", \
        "overlay の リーダー条件 (黒ひげ海賊団) が無い"
    assert eval_all_conditions(eff, st, me, None) is False, \
        "黒ひげでない leader で 条件が成立してはいけない"


def test_op09_098_main_negate_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal で選んだ1枚を無効 → (コスト4以下) KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2
    b = InPlay.of(repo.get(_SMALL), sickness=False)    # cost1
    opp.characters = [a, b]

    do = _eff(overlay, "OP09-098", "main")["do"]
    # do[0] = 効果無効 (相手キャラ選択) → 人間で target_pick modal
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])  # b を効果無効に (= 直近 negate 対象)
    _drain(st, [bi])
    assert "効果無効" in b.granted_keywords, "人間が選んだ相手キャラが 効果無効 になっていない"
    # do[1] = 「その後、そのキャラのコストが4以下なら KO」 (opp_just_negated_cost_le_4)
    execute_effect(do[1], st, me, opp, None)
    _drain(st, [0])
    assert b not in opp.characters, "効果無効にした コスト4以下の相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかった相手キャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP09-100 カラス (CHARACTER): 【ブロッカー】。 【トリガー】自リーダーが《革命軍》で
#          総ライフ5以下なら、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op09_100_trigger_self_play_ai():
    """【トリガー】革命軍 leader + 総ライフ5以下 → このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4  # 総ライフ 4 (≤5)
    me.characters = []
    me.trash = [repo.get("OP09-100")]  # トリガー処理で trash から登場
    st.current_source_card_id = "OP09-100"

    for prim in _eff(overlay, "OP09-100", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card.card_id == "OP09-100" for c in me.characters), \
        "トリガーで カラス が登場していない"


def test_op09_100_trigger_conditions():
    """トリガー条件 leader_feature《革命軍》 + total_life_le:5 の成立/不成立を検証。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-100", "trigger")
    assert eff.get("if", {}).get("leader_feature") == "革命軍", \
        "overlay の リーダー条件 (革命軍) が無い"
    assert eff.get("if", {}).get("total_life_le") == 5, \
        "overlay の 条件 total_life_le=5 が無い"

    # 革命軍 + ライフ4 → 成立
    st = _state(repo, _LEADER_REVO, overlay)
    st.players[0].life = [repo.get(_FILLER)] * 4
    assert eval_all_conditions(eff, st, st.players[0], None) is True, \
        "革命軍 + ライフ4 で 条件が成立するべき"
    # 革命軍でない leader → 不成立
    st2 = _state(repo, _LEADER_MUGIWARA, overlay)
    st2.players[0].life = [repo.get(_FILLER)] * 4
    assert eval_all_conditions(eff, st2, st2.players[0], None) is False, \
        "革命軍でない leader で 条件が成立してはいけない"
    # 革命軍 + ライフ6 (> 5) → 不成立
    st3 = _state(repo, _LEADER_REVO, overlay)
    st3.players[0].life = [repo.get(_FILLER)] * 6
    assert eval_all_conditions(eff, st3, st3.players[0], None) is False, \
        "総ライフ6で 条件が成立してはいけない"
