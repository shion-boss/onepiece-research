"""黄カタクリ(OP03-099) scry_life 修正の回帰テスト。

修正前バグ: owner="self_or_opp" を常に自ライフに固定し、 かつ depth=1 では並び替えが no-op
だったため、 「相手ライフの上にあるトリガーを下に埋める(妨害)」 も 「上/下 の選択」 も
一度も行われず、 リーダー効果が +1000 パワーだけに縮退していた。

修正後: AI は相手の上ライフが有用札(トリガー/高カウンター)なら相手を見て【下に埋める】(妨害)、
さもなくば自ライフを最適化する。 ライフ枚数は不変(公式: 見て上下に置くだけ)。
"""
import json
import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import load_effect_overlay, execute_effect

_ROOT = str(Path(__file__).resolve().parent.parent)
_repo = CardRepository.from_json(f"{_ROOT}/db/cards.json")
_overlay = load_effect_overlay(f"{_ROOT}/db/card_effects.json")
_raw = json.load(open(f"{_ROOT}/db/card_effects.json"))

_TRIG = "EB01-038"          # トリガー持ち
_JUNK1, _JUNK2 = "EB01-012_r1", "EB01-015_p2"   # トリガー無し


def _run_katakuri_scry(opp_life_ids):
    me = Player(name="ME", leader=InPlay.of(_repo.get("OP03-099")))   # 黄カタクリ
    opp = Player(name="OPP", leader=InPlay.of(_repo.get("OP01-001")))
    me.life = [_repo.get("ST01-004")] * 3
    opp.life = [_repo.get(c) for c in opp_life_ids]
    me.deck = [_repo.get("ST01-004")] * 20
    opp.deck = [_repo.get("ST01-004")] * 20
    st = GameState(players=[me, opp], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=_overlay)
    st.turn_player_idx = 0
    st.turn_number = 5
    src = InPlay.of(_repo.get("OP03-099"))
    src.attached_dons = 1
    for prim in _raw["OP03-099"][0]["do"]:
        execute_effect(prim, st, me, opp, src)
    return [c.card_id for c in opp.life]


def test_katakuri_buries_opp_top_trigger():
    """相手ライフの上がトリガー → AI が下に埋める(妨害)。 枚数は不変。"""
    before = [_TRIG, _JUNK1, _JUNK2]
    after = _run_katakuri_scry(before)
    assert len(after) == len(before), "scry_life でライフ枚数が変わってはいけない"
    assert after[-1] == _TRIG, "相手ライフ上のトリガーを下に埋めていない(妨害できていない)"
    assert after[0] != _TRIG, "トリガーが上に残っている"


def test_katakuri_ignores_opp_when_top_is_junk():
    """相手ライフ上が雑魚 → 妨害不要、 相手ライフは(順序を悪化させ)ない。 枚数不変。"""
    before = [_JUNK1, _JUNK2, _TRIG]   # 上2枚は雑魚、 トリガーは最下
    after = _run_katakuri_scry(before)
    assert len(after) == len(before)
    # 相手の有用札(最下のトリガー)を上に繰り上げてしまっていないこと
    assert after[0] != _TRIG, "妨害不要なのに相手トリガーを上に繰り上げた"


def test_katakuri_trigger_has_trigger_flag():
    """テスト前提: _TRIG は実際にトリガーを持つ。"""
    assert bool(getattr(_repo.get(_TRIG), "trigger", None))
