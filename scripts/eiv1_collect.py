"""EIV1 self-play データ収集 → 永続 append-only corpus (2026-07-23, 2026-07-24 プール回転)。

hero = ExploitBeam(EIV1 value or agnostic fallback) + ε探索、 opp = EBV2(agnostic)。
各 hero MAIN 局面で ①v15 集計特徴 ②局面まるごと oracle スナップショット を記録、 終局 outcome でラベル
→ db/eiv1/corpus.jsonl に APPEND。 各行 = {f: v15, y: 勝敗, hero: slug, opp: slug, state: full oracle snapshot}。

= EIV1 の②永続 corpus + ⑤フライホイールの"データ生成"側 (自分側=beam+学習value+探索、 相手=EBV2)。
「回せば貯まる」器。 rollout target(④)は現状 outcome ラベル (拡張点=--rollout-n で後日)。

⭐ **hero/opp 両プール回転 (= デッキ在庫フル活用)**: --heroes / --opps に comma-list か @file
(例 @db/eiv1/pool_all.txt = eiv1_build_pools.py 生成の 233 デッキ) を渡すと game 毎に両側を回転。
card-aware value は cell を暗記せず card で汎化するので広プールが転移に効く (= 汎用 value = ユーザーデッキ対応)。

⭐ **盲目化しない保証**: state = snapshot_state (両者の隠匿手札/ライフ中身/デッキtop5 込み oracle)。
将来どんな value 指標を思いついても「保存済み state の関数」で過去 corpus 全件に遡って再計算でき無意味化しない。

  .venv/bin/python scripts/eiv1_collect.py --games 40 --workers 12
    [--heroes @db/eiv1/pool_all.txt] [--opps @db/eiv1/pool_all.txt] [--epsilon 0.15]
"""
from __future__ import annotations
import os
# ⚠ BLAS/OpenMP スレッドを 1 に固定 (numpy/sklearn import 前に必須)。 multiprocessing の
# worker × ライブラリ内部スレッドで過剰subscription (12worker×~8スレッド=load 96) → thrashing に
# なるのを防ぐ。 fork した worker が単一スレッド numpy を継承 → 12worker=12コアでクリーンに回る。
for _tv in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_tv, "1")
import argparse
import json
import random
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions
from engine.ai import play_one_action
from engine.core import Phase
from engine.exploit_beam_ai import ExploitBeamAI
from engine.eiv1_features import eiv1_features
from engine.game_corpus import snapshot_state

_REPO = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
_OVERLAY = load_effect_overlay(str(ROOT / "db" / "card_effects.json"))
EIV1_DIR = ROOT / "db" / "eiv1"
CORPUS = EIV1_DIR / "corpus.jsonl"
AGNOSTIC = str(ROOT / "db" / "value_gbm_agnostic.pkl")
EIV1_VALUE = ROOT / "db" / "eiv1" / "value.pkl"

# module-global (worker が fork で継承)
HEROES = ["cardrush_1454"]
OPPS = ["cardrush_1385", "tcgportal_calgara", "tcgportal_bonney", "cardrush_1399"]
EPSILON = 0.15
BEAM_W, BEAM_D = 8, 6
RECORD_BOTH = True   # 両席の局面を記録 (自己対戦なら同じ計算量でサンプル 2 倍)
SNAP_DIR = EIV1_DIR / "snapshots"


def _resolve_opp_mix(spec: str) -> list:
    """"eiv1:0.7,snapshot:0.3" → [(value_path, weight)]。 存在しない選択肢は自動で落とす。

    ⭐ 自己対戦の相手プール。 純ミラー (最新 EIV1 100%) だと双方が同じ弱点を持つため、
    その弱点を突く打ち方が data から消える (忘却・狭窄)。 過去 snapshot を混ぜて防ぐ。
    ⚠ EBV2(agnostic) は **強さ計測の物差し** として arena 側で使うので、 学習の相手には既定で入れない。"""
    out = []
    for part in (spec or "").split(","):
        if not part.strip():
            continue
        name, _, w = part.partition(":")
        try:
            weight = float(w) if w else 1.0
        except ValueError:
            weight = 1.0
        name = name.strip()
        if name == "eiv1":
            if EIV1_VALUE.exists():
                out.append((str(EIV1_VALUE), weight))
        elif name == "snapshot":
            snaps = sorted(SNAP_DIR.glob("value_iter*.pkl"))
            if snaps:
                out.append(([str(p) for p in snaps], weight))
        elif name == "agnostic":
            out.append((AGNOSTIC, weight))
        elif Path(name).exists():
            out.append((name, weight))
    return out or [(AGNOSTIC, 1.0)]


def _pick_opp_value(mix: list, rng: random.Random) -> str:
    total = sum(w for _, w in mix)
    r = rng.random() * total
    for val, w in mix:
        r -= w
        if r <= 0:
            return rng.choice(val) if isinstance(val, list) else val
    val = mix[-1][0]
    return rng.choice(val) if isinstance(val, list) else val


def _ref_path(ref: str) -> str:
    """ref = slug (→ decks/<slug>.json) か repo 相対パス (→ decks/_train_pool/x.json)。"""
    if "/" in ref or ref.endswith(".json"):
        return str(ROOT / ref)
    return str(ROOT / "decks" / f"{ref}.json")


def _slug(ref: str) -> str:
    return Path(ref).stem


def _dl(ref: str) -> DeckList:
    return DeckList.from_json(_ref_path(ref), _REPO)


def _ana(ref: str) -> dict:
    p = ROOT / "decks" / f"{_slug(ref)}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _parse_pool(arg: str) -> list:
    """comma-list か @file (1 行 1 ref) を ref 列に。"""
    if arg.startswith("@"):
        return [l.strip() for l in open(arg[1:], encoding="utf-8") if l.strip() and not l.startswith("#")]
    return [s for s in arg.split(",") if s]


class _ExploreBeam(ExploitBeamAI):
    """ExploitBeam + ε探索 (= 探索ノイズ)。 hero(学習側)用。"""

    def __init__(self, *a, epsilon=0.0, **k):
        super().__init__(*a, **k)
        self._epsilon = epsilon

    def choose_action(self, state):
        rng = self.rng or random
        if self._epsilon > 0 and rng.random() < self._epsilon:
            acts = legal_actions(state)
            if acts:
                return rng.choice(acts)
        return super().choose_action(state)


def _hero_value_path() -> str:
    """EIV1 value があればそれ (= 全 hero 共通の汎用 value)、 無ければ agnostic に degrade (iter0)。"""
    return str(EIV1_VALUE) if EIV1_VALUE.exists() else AGNOSTIC


def _collect_game(task):
    seed, hero, opp, opp_value = task
    hero_first = (seed % 2 == 0)
    try:
        if hero_first:
            st = setup_game(_dl(hero), _dl(opp), rng=random.Random(seed), first_player=0,
                            effects_overlay=_OVERLAY, deck1_analysis=_ana(hero), deck2_analysis=_ana(opp))
            hero_idx = 0
        else:
            st = setup_game(_dl(opp), _dl(hero), rng=random.Random(seed), first_player=0,
                            effects_overlay=_OVERLAY, deck1_analysis=_ana(opp), deck2_analysis=_ana(hero))
            hero_idx = 1
    except Exception:
        return []
    play_until_main(st)
    ais = [None, None]
    # hero = EIV1 value (or agnostic) + ε探索
    ais[hero_idx] = _ExploreBeam(rng=random.Random(seed * 3 + 1),
                                 deck_analysis={**_ana(hero), "deck_slug": _slug(hero)},
                                 gbm_path=_hero_value_path(), beam_width=BEAM_W, max_depth=BEAM_D,
                                 epsilon=EPSILON)
    # opp = 抽選された value (自己対戦: 最新 EIV1 / 過去 snapshot / agnostic)。
    # EIV1 系の相手には hero と同じ ε を与える (= 両席が対称。 片側だけ探索付きだと、
    # 両席記録した時に席によってラベルのノイズ量が変わってしまう)。
    if opp_value == AGNOSTIC:
        ais[1 - hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 2),
                                          deck_analysis={**_ana(opp), "deck_slug": _slug(opp)},
                                          gbm_path=opp_value, beam_width=BEAM_W, max_depth=BEAM_D)
    else:
        ais[1 - hero_idx] = _ExploreBeam(rng=random.Random(seed * 5 + 2),
                                         deck_analysis={**_ana(opp), "deck_slug": _slug(opp)},
                                         gbm_path=opp_value, beam_width=BEAM_W, max_depth=BEAM_D,
                                         epsilon=EPSILON)
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    rows, seen = [], set()  # rows = (v15_features, full_oracle_snapshot, 視点 seat)
    n = 0
    while not st.game_over and st.turn_number < 60 and n < 800:
        cur = st.turn_player_idx
        key = (cur, st.turn_number)
        if st.phase == Phase.MAIN and key not in seen and (RECORD_BOTH or cur == hero_idx):
            seen.add(key)
            try:
                fv = eiv1_features(st, cur)   # v15 集計 (今の GBM が使う、 高速用に併記)
                # 局面まるごと oracle スナップショット (= 両者の隠匿手札/ライフ中身/デッキtop5 込み)。
                # 将来どんな指標を足しても「保存済み state の関数」で再計算でき盲目化しない。
                # 手番側の視点で記録 (両席記録なら 1 game から 2 倍のサンプルが取れる)。
                snap = snapshot_state(st)
                snap["hero_idx"] = cur
                rows.append((fv, snap, cur))
            except Exception:
                pass
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return []
    winner = getattr(st, "winner", -1)
    decks = [None, None]
    decks[hero_idx], decks[1 - hero_idx] = _slug(hero), _slug(opp)
    return [(fv, 1 if winner == seat else 0, decks[seat], decks[1 - seat], snap)
            for fv, snap, seat in rows]


def main():
    global HEROES, OPPS, EPSILON, BEAM_W, BEAM_D, RECORD_BOTH
    ap = argparse.ArgumentParser()
    ap.add_argument("--heroes", default=None, help="hero プール (comma-list か @file)。 未指定は --hero")
    ap.add_argument("--hero", default="cardrush_1454", help="単一 hero (back-compat、 --heroes 未指定時)")
    ap.add_argument("--opps", default=",".join(OPPS), help="opp プール (comma-list か @file)")
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--epsilon", type=float, default=EPSILON)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed-base", type=int, default=None)
    ap.add_argument("--beam-width", type=int, default=BEAM_W)
    ap.add_argument("--max-depth", type=int, default=BEAM_D)
    ap.add_argument("--opp-mix", default="eiv1:0.7,snapshot:0.3",
                    help="相手 value の抽選 (eiv1 / snapshot / agnostic / パス:重み)。 "
                         "既定 = 自己対戦 (最新 7 : 過去 snapshot 3)")
    ap.add_argument("--record-both", type=int, default=1,
                    help="1 = 両席の局面を記録 (自己対戦なら同計算量でサンプル 2 倍)")
    a = ap.parse_args()
    HEROES = _parse_pool(a.heroes) if a.heroes else [a.hero]
    OPPS = _parse_pool(a.opps)
    EPSILON = a.epsilon
    BEAM_W, BEAM_D = a.beam_width, a.max_depth
    RECORD_BOTH = bool(a.record_both)
    EIV1_DIR.mkdir(parents=True, exist_ok=True)
    # seed-base: 既存 corpus サイズからずらして重複を避ける (毎日足しても別ゲーム)
    base = a.seed_base
    if base is None:
        base = 700000 + (CORPUS.stat().st_size if CORPUS.exists() else 0) % 500000
    # game 毎に hero/opp を seed 決定的にランダム選択 (広プールを均等に散らす)
    mix = _resolve_opp_mix(a.opp_mix)
    tasks = []
    for i in range(a.games):
        seed = base + i
        r = random.Random(seed * 9176 + 12345)
        tasks.append((seed, r.choice(HEROES), r.choice(OPPS), _pick_opp_value(mix, r)))
    mix_desc = ",".join(f"{'snapshot' if isinstance(v, list) else Path(v).stem}:{w:g}"
                        for v, w in mix)
    print(f"EIV1 collect: heroes={len(HEROES)} × opps={len(OPPS)} | games={a.games} eps={EPSILON} "
          f"beam={BEAM_W}/{BEAM_D} | value={'EIV1' if EIV1_VALUE.exists() else 'agnostic(iter0)'} "
          f"| 相手={mix_desc} 両席記録={'on' if RECORD_BOTH else 'off'}", flush=True)
    t0 = time.time()
    # 1 round の上限秒 (circuit breaker): 病的に長いゲームが pool を無限ブロックし lock を握り続ける
    # のを防ぐ。 超えたら pool を terminate してこの round を打ち切り (lock 解放 → 次 cron が回れる)。
    timeout_s = int(os.environ.get("EIV1_COLLECT_TIMEOUT", "900"))
    with mp.Pool(a.workers) as pool:
        try:
            results = pool.map_async(_collect_game, tasks).get(timeout=timeout_s)
        except mp.TimeoutError:
            pool.terminate()
            print(f"!! collect timeout ({timeout_s}s) → この round を打ち切り (次へ)", flush=True)
            results = []
    # game_id を付ける: 1 game = 5〜6 行を吐くので、 学習の held-out split を game 単位で
    # 切らないと同一 game の行が train/test に跨り AUC がリークで上振れする。
    run_tag = int(t0)   # この run の識別子 (round/日を跨いでも game_id が衝突しない)
    rows, n_games = [], 0
    for gi, r in enumerate(results):
        if r:
            n_games += 1
            rows.extend((f"{run_tag}-{gi}", *row) for row in r)
    with open(CORPUS, "a", encoding="utf-8") as f:
        for gid, fv, y, hero, opp, snap in rows:
            # f = v15 集計特徴 (今の GBM 学習が使う) / state = 局面まるごと oracle 生スナップショット
            # (= 将来どんな指標も後から再計算でき盲目化しない = 「データが無意味にならない」保証)
            # g = game_id (= 同一 game の行を train/test で分けないための group key)
            f.write(json.dumps({"f": fv, "y": y, "hero": hero, "opp": opp, "state": snap,
                                "g": gid}) + "\n")
    total = sum(1 for _ in open(CORPUS)) if CORPUS.exists() else 0
    # ⚠ win率は出さない: 自己対戦では構造的に ~0.5 になるだけで強さを測れない。
    # 強さの推移は ε=0 arena (vs EBV2 agnostic) が唯一の物差し。
    print(f"appended {len(rows)} samples from {n_games}/{a.games} games "
          f"({time.time()-t0:.0f}s) → corpus 総計 {total} samples", flush=True)


if __name__ == "__main__":
    main()
