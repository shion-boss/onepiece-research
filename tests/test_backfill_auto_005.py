# -*- coding: utf-8 -*-
"""EB01 / EB02 弾 効果 回帰テスト バックフィル (自動生成 wave 005):
EB01-058 / EB01-059 / EB01-060 / EB02-002 / EB02-003 / EB02-006 /
EB02-008 / EB02-009 / EB02-011 / EB02-012 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import Category, GameState, InPlay, Phase, Player
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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave5_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB01-058", "EB01-059", "EB01-060", "EB02-002", "EB02-003",
           "EB02-006", "EB02-008", "EB02-009", "EB02-011", "EB02-012"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB01-058 モンブラン・クリケット:
#    【ドン!!×1】【自分のターン中】自分のライフが2枚以下の場合、このキャラ +2000
# --------------------------------------------------------------------------- #
def test_eb01_058_cricket_self_pump_when_life_le2():
    """自ライフ2以下 → このキャラ(自身)は パワー+2000。 対象 self の単純 pump。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2  # ライフ 2 (= 条件成立)
    cricket = InPlay.of(repo.get("EB01-058"), sickness=False)  # power 3000
    me.characters = [cricket]

    eff = overlay.get("EB01-058").effects[0]
    assert eff.get("if", {}).get("self_life_le") == 2, \
        "overlay の 条件 self_life_le=2 が無い"
    power_before = cricket.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, cricket)

    assert cricket.power == power_before + 2000, \
        f"自ライフ2以下で 自己 +2000 が反映されていない: {cricket.power}"


# --------------------------------------------------------------------------- #
#  EB01-059 雷迎 (EVENT):
#    【メイン】相手のキャラ1枚までをKO → 自ライフが1枚になるようトラッシュ
# --------------------------------------------------------------------------- #
def test_eb01_059_raigo_main_ko_then_mill_life_ai():
    """AI: 相手キャラ1体を KO し、 自ライフを 1 枚まで削ってトラッシュへ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 4
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    eff = next(e for e in overlay.get("EB01-059").effects if e["when"] == "main")
    trash_before = len(me.trash)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-059"), sickness=False))

    assert victim not in opp.characters, "相手キャラが KO されていない"
    assert len(me.life) == 1, f"自ライフが1枚になっていない: {len(me.life)}"
    assert len(me.trash) == trash_before + 3, "削られたライフ3枚がトラッシュに置かれていない"


def test_eb01_059_raigo_ko_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち、 選んだ1体だけ KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    eff = next(e for e in overlay.get("EB01-059").effects if e["when"] == "main")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("EB01-059"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選んでいない相手キャラまで KO されている"


# --------------------------------------------------------------------------- #
#  EB01-060 我が神なり (EVENT):
#    【メイン】手札/トラッシュから コスト7以下「エネル」1枚を登場 → 自ライフ1枚に
# --------------------------------------------------------------------------- #
def test_eb01_060_waga_kami_play_enel_then_mill_ai():
    """AI: 手札の エネル (cost5) を登場させ、 自ライフを 1 枚まで削る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 4
    enel = repo.get("OP10-025")  # エネル CHARACTER cost5
    assert enel.name == "エネル", "テスト前提: OP10-025 は エネル"
    me.hand = [enel]

    eff = next(e for e in overlay.get("EB01-060").effects if e["when"] == "main")
    chars_before = len(me.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-060"), sickness=False))

    assert len(me.characters) == chars_before + 1, "エネルが登場していない"
    assert any(c.card.name == "エネル" for c in me.characters), \
        "登場したキャラが エネル でない"
    assert len(me.life) == 1, f"自ライフが1枚になっていない: {len(me.life)}"


# --------------------------------------------------------------------------- #
#  EB02-002 サボ:
#    【起動メイン】このキャラをレスト → 自「サボ」以外の《革命軍》1枚 +2000 (このターン)
# --------------------------------------------------------------------------- #
def test_eb02_002_sabo_activate_main_pump_ai():
    """AI: 自身をレストして 革命軍キャラ1体に +2000 (turn)。 サボ自身は対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("EB02-002"), sickness=False)
    rev = InPlay.of(repo.get("EB04-045"), sickness=False)  # ジニー 革命軍
    assert "革命軍" in (repo.get("EB04-045").features or ()), \
        "テスト前提: EB04-045 は 革命軍"
    me.characters = [sabo, rev]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "EB02-002"]
    assert len(opts) == 1, f"EB02-002 の起動メインが legal に出ない: {len(opts)}"
    power_before = rev.power
    fire_activate_main(st, me, opp, *opts[0])

    assert rev.power == power_before + 2000, \
        f"革命軍キャラに +2000 が反映されていない: {rev.power}"
    assert sabo.rested is True, "コストで サボ自身がレストされるべき"


def test_eb02_002_sabo_activate_main_human_pick():
    """人間 + 革命軍キャラ複数 → target_pick modal が立ち、 選んだ1体に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("EB02-002"), sickness=False)
    r1 = InPlay.of(repo.get("EB04-045"), sickness=False)  # ジニー
    r2 = InPlay.of(repo.get("EB03-042"), sickness=False)  # コアラ 革命軍
    me.characters = [sabo, r1, r2]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "EB02-002"]
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # 候補は サボ以外の 革命軍 2 体 (サボ自身は exclude_name で除外)
    assert len(cands) == 2, f"候補 (革命軍2体) でない: {len(cands)}"

    r2_idx = next(i for i, c in enumerate(cands) if c["iid"] == r2.instance_id)
    r2_before = r2.power
    resolve_pending_choice(st, [r2_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert r2.power == r2_before + 2000, "人間が選んだ革命軍キャラに +2000 が反映されていない"


def test_eb02_002_sabo_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("EB02-002"), sickness=False)
    rev = InPlay.of(repo.get("EB04-045"), sickness=False)
    me.characters = [sabo, rev]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "EB02-002"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "EB02-002"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB02-003 トニートニー・チョッパー:
#    【登場時】自リーダーが《麦わらの一味》→ 自リーダー/キャラにレストドン1まで付与
# --------------------------------------------------------------------------- #
def test_eb02_003_chopper_on_play_attach_rested_don_ai():
    """AI: 麦わらの一味 leader で 登場時 自リーダー(既定)にレストドン1を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB02-005", overlay)  # ルフィ 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    chopper = InPlay.of(repo.get("EB02-003"), sickness=True)

    eff = next(e for e in overlay.get("EB02-003").effects if e["when"] == "on_play")
    assert eff.get("if", {}).get("leader_feature") == "麦わらの一味", \
        "overlay の 条件 leader_feature=麦わらの一味 が無い"
    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, chopper)

    assert me.leader.attached_dons == don_before + 1, \
        "登場時に自リーダーへレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_eb02_003_chopper_on_play_human_pick():
    """人間 + 自リーダー/キャラ 複数候補 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB02-005", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    chopper = InPlay.of(repo.get("EB02-003"), sickness=True)
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [chopper, friend]

    eff = next(e for e in overlay.get("EB02-003").effects if e["when"] == "on_play")
    execute_effect(eff["do"][0], st, me, opp, chopper)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) >= 2, f"候補 (リーダー+キャラ) が 2 件以上でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  EB02-006 ヤマト:
#    【起動メイン】【ターン1回】ワノ国/エース leader → 自リーダーにレストドン1 +
#                  このキャラ このターン【速攻】
# --------------------------------------------------------------------------- #
def test_eb02_006_yamato_activate_main_attach_and_rush_ai():
    """AI: ワノ国 leader で 自リーダーにレストドン1を付与し、 自身が 速攻 を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん ワノ国 leader
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    yamato = InPlay.of(repo.get("EB02-006"), sickness=False)
    me.characters = [yamato]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "EB02-006"]
    assert len(opts) == 1, f"EB02-006 の起動メインが legal に出ない: {len(opts)}"
    don_before = me.leader.attached_dons
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert "速攻" in getattr(yamato, "granted_keywords", set()), \
        f"ヤマトが 速攻 を得ていない: {getattr(yamato, 'granted_keywords', None)}"


def test_eb02_006_yamato_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    yamato = InPlay.of(repo.get("EB02-006"), sickness=False)
    me.characters = [yamato]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "EB02-006"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "EB02-006"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB02-008 最高到達点 (EVENT):
#    【メイン】デッキ上4枚を見て コスト4以上1枚を手札 → 残りをデッキ下
# --------------------------------------------------------------------------- #
def test_eb02_008_saikou_search_cost_ge4_to_hand_ai():
    """AI: デッキ上4枚から コスト4以上のカードを1枚 手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # デッキトップに コスト4以上のカードを配置 (PRB02-001 = コスト4)
    big = repo.get("PRB02-001")
    def _cost_int(c):
        try:
            return int(c.cost)
        except (TypeError, ValueError):
            return 0
    assert _cost_int(big) >= 4, "テスト前提: PRB02-001 は コスト4以上"
    me.deck = [big] + [repo.get("OP01-013")] * 10  # OP01-013 = コスト2
    me.hand = []

    eff = next(e for e in overlay.get("EB02-008").effects if e["when"] == "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-008"), sickness=False))

    assert len(me.hand) == 1, f"コスト4以上カードが手札に加わっていない: {len(me.hand)}"
    assert _cost_int(me.hand[0]) >= 4, \
        f"手札に加えたカードが コスト4以上でない: {me.hand[0].cost}"


# --------------------------------------------------------------------------- #
#  EB02-009 サウザンド・サニー号 (STAGE):
#    【起動メイン】このステージをレスト → 自付与ドン1を《麦わらの一味》キャラに移す
# --------------------------------------------------------------------------- #
def test_eb02_009_sunny_activate_main_transfer_don_ai():
    """AI: ステージをレストにし、 自リーダーの付与ドン1を 麦わらの一味キャラに移す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("EB02-009"), sickness=False)
    me.stages = [stage]
    nami = InPlay.of(repo.get("PRB02-012"), sickness=False)  # ナミ 麦わらの一味
    assert "麦わらの一味" in (repo.get("PRB02-012").features or ()), \
        "テスト前提: PRB02-012 は 麦わらの一味"
    me.characters = [nami]
    me.leader.attached_dons = 1  # 移動元の付与ドン

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "EB02-009"]
    assert len(opts) == 1, f"EB02-009 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert nami.attached_dons == 1, \
        f"麦わらの一味キャラに付与ドンが移されていない: {nami.attached_dons}"
    assert me.leader.attached_dons == 0, "移動元 (リーダー) の付与ドンが減っていない"
    assert stage.rested is True, "コストでステージがレストされるべき"


# --------------------------------------------------------------------------- #
#  EB02-011 アーロン:
#    【登場時】魚人族/東の海 leader → 自リーダーにレストドン1 +
#             相手コスト5以下1枚は 次の相手ターン終了まで レストにできない
# --------------------------------------------------------------------------- #
def test_eb02_011_arlong_on_play_attach_and_set_cannot_rest_ai():
    """AI: 魚人族 leader で 自リーダーにレストドン1を付与し、 相手コスト5以下1体を
    レスト不可にする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)  # ジンベエ 魚人族 leader
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    arlong = InPlay.of(repo.get("EB02-011"), sickness=True)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 opp
    opp.characters = [victim]

    eff = next(e for e in overlay.get("EB02-011").effects if e["when"] == "on_play")
    don_before = me.leader.attached_dons
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, arlong)

    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert victim.cannot_be_rested_buff is True, \
        "相手コスト5以下キャラが レスト不可にされていない"


def test_eb02_011_arlong_set_cannot_rest_human_pick():
    """人間 + 相手コスト5以下 複数 → target_pick modal が立ち、 選んだ1体だけ レスト不可。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost? (<=5)
    opp.characters = [a, b]

    eff = next(e for e in overlay.get("EB02-011").effects if e["when"] == "on_play")
    execute_effect(eff["do"][1], st, me, opp,
                   InPlay.of(repo.get("EB02-011"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (コスト5以下2体) でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.cannot_be_rested_buff is True, "人間が選んだキャラが レスト不可にされていない"
    assert a.cannot_be_rested_buff is False, "選んでいないキャラまで レスト不可にされている"


# --------------------------------------------------------------------------- #
#  EB02-012 ガイモン:
#    自「サーファンクル」がいる場合、 このキャラは【ブロッカー】を得る (静的効果)
# --------------------------------------------------------------------------- #
def test_eb02_012_gaimon_gains_blocker_with_surfunkel():
    """静的: 場に サーファンクル がいれば ガイモンは ブロッカー を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    gaimon = InPlay.of(repo.get("EB02-012"), sickness=False)
    surf = InPlay.of(repo.get("EB02-014"), sickness=False)  # サーファンクル
    assert repo.get("EB02-014").name == "サーファンクル", \
        "テスト前提: EB02-014 は サーファンクル"
    assert repo.get("EB02-012").is_blocker is False, \
        "テスト前提: ガイモンは innate ブロッカーではない"
    me.characters = [gaimon, surf]

    evaluate_static_effects(st, overlay)
    assert gaimon.is_blocker_now is True, \
        "サーファンクル在場時 ガイモンが ブロッカー を得ていない"


def test_eb02_012_gaimon_no_blocker_without_surfunkel():
    """静的: サーファンクル が いなければ ガイモンは ブロッカー を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    gaimon = InPlay.of(repo.get("EB02-012"), sickness=False)
    me.characters = [gaimon]

    evaluate_static_effects(st, overlay)
    assert gaimon.is_blocker_now is False, \
        "サーファンクル不在時に ガイモンが ブロッカー を得ている"
