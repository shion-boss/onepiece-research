"""宣言的 feature spec = 「指標が自動で増える」ための土台 — 2026-07-23。

これまで特徴列は gbm_value.py にベタ書きだった (v16/v18/v19/v20)。 = 列を増やすには人間が
コードを書く必要があり、 そこが律速だった。 ここでは列を **データ (JSON)** にする:

  db/eiv1/feature_spec.json  = 現在採用中の追加列 (v20(94) の後ろに append される)
  <model>.spec.json          = その model が学習された時の spec (= 推論で使う、 model と対で保存)

⭐ 評価器は 1 本だけ (evaluate)。 学習は corpus の snapshot、 推論は live state を
gbm_value._mini_snap で同じ形にして渡す → **学習と推論のズレが構造的に起きない**。

列の種類:
  agg  : {zone × label カテゴリ × 統計}  … 例 「相手の残りデッキの除去の期待枚数」
  x    : agg × 文脈スカラー (turn / ライフ差 …) … この repo の実績上、 効くのは盤面と
         相互作用する形 (静的な記述子は value に冗長で null になる)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
EIV1_DIR = ROOT / "db" / "eiv1"
ACTIVE_SPEC_PATH = EIV1_DIR / "feature_spec.json"

# --- 語彙 ------------------------------------------------------------------
ZONES = ("my_hand", "my_board", "opp_board", "my_trash", "opp_trash",
         "opp_seen_hand", "opp_belief")
# card_labels の effect ラベル (頻度上位) + 構造ラベル
CATS = ("removal", "removal_ko", "removal_bounce", "draw", "search", "buff_power",
        "blocker", "ramp_don", "play_accel", "keyword_grant", "tempo_rest", "attach_don",
        "untap", "life_recovery", "cost_reduce", "recursion", "protect", "disruption",
        "life_manip", "hand_disrupt", "self_discard", "negate", "power_set", "don_disrupt",
        "board_wipe", "finisher_swing", "counter_card", "high_power")
# 大きさ (矢印の長さ) を持つカテゴリ → card_magnitudes のどの量を使うか
MAG_FIELD = {"removal": "_rm_reach", "removal_ko": "_rm_reach", "removal_bounce": "_rm_reach",
             "draw": "draw", "ramp_don": "don", "buff_power": "pump", "search": "search",
             "life_recovery": "recover", "counter_card": "_counter", "high_power": "_power"}
STATS = ("count", "mag_sum", "mag_max")
CONTEXTS = ("turn", "life_diff", "opp_life", "my_life", "board_pw_diff", "my_don", "opp_hand_n")

_CARD_INFO: Optional[dict] = None
_BELIEF_TABLE: dict = {}


def _card_info() -> dict:
    """card_id → {cats: frozenset, mags: {field: value}}。 overlay/labels から 1 度だけ構築。"""
    global _CARD_INFO
    if _CARD_INFO is not None:
        return _CARD_INFO
    from . import card_labels, card_magnitudes
    info = {}
    try:
        labels = card_labels.build_all()
    except Exception:
        labels = {}
    mags = card_magnitudes.magnitudes_db()
    for cid, meta in labels.items():
        cats = set(meta.get("labels") or [])
        if meta.get("is_blocker"):
            cats.add("blocker")
        counter = float(meta.get("counter") or 0)
        power = float(meta.get("power") or 0)
        if counter > 0:
            cats.add("counter_card")
        if power >= 5000:
            cats.add("high_power")
        m = dict(mags.get(cid) or {})
        m["_rm_reach"] = max(m.get("rm_play_cost", 0.0), m.get("rm_active_cost", 0.0))
        m["_counter"] = counter / 1000.0
        m["_power"] = power / 1000.0
        m["pump"] = m.get("pump", 0.0) / 1000.0
        info[cid] = {"cats": frozenset(cats), "mags": m, "counter_value": counter,
                     # カウンターイベント = 手札から相手のアタック時に撃つ (ドンが要る)
                     "counter_event": ("t_counter" in (meta.get("timings") or ())
                                       and str(meta.get("category", "")).upper() == "EVENT")}
    _CARD_INFO = info
    return info


def _belief_cards(leader_id: str) -> list:
    """leader prior → [(card_id, E[枚数])] (leader 単位 cache)。 seen 減算は呼び出し側。"""
    tbl = _BELIEF_TABLE.get(leader_id)
    if tbl is None:
        try:
            from .opponent_deck_model import get_default_model
            bel = get_default_model().belief_for_leader(leader_id, None) or {}
            tbl = [(cid, float(v.get("exp_count", 0.0))) for cid, v in bel.items()]
        except Exception:
            tbl = []
        _BELIEF_TABLE[leader_id] = tbl
    return tbl


# --- 生成器 ----------------------------------------------------------------


def col_name(col: dict) -> str:
    if col.get("k") == "x":
        return f"x_{col_name(col['a'])}__{col['b']}"
    if col.get("k") == "card":
        return f"{col['z']}_card_{col['c']}"
    if col.get("k") == "don":
        return f"don_{col['c']}"
    if col.get("k") == "der":
        return f"der_{col['c']}"
    if col.get("k") == "eye":
        return f"eye_{col['c']}"
    return f"{col['z']}_{col['c']}_{col['s']}"


DON_KEYS = (
    # 生の枚数 (v2 は d_don = 差 しか持たず、 active/rested を区別できない)
    "my_don_active", "opp_don_active", "my_don_rested", "opp_don_rested",
    "my_don_total", "opp_don_total",
    # ⭐ 自分側: アクティブドンは「手札の何が今出せるか」を決める (盤面の集計では代替不可)
    "my_playable_n", "my_playable_max_cost", "my_playable_ratio", "my_tapout",
    # ⭐ 相手側: アクティブドンは「カウンターイベントを払えるか」を決める。 アクティブ 0 なら
    # 手札に持っていても物理的に撃てない = v18 の belief 残りカウンターに掛けるべきゲート
    "opp_tapout", "opp_counter_payable", "opp_belief_counter_payable", "opp_don_active_ge2",
)


def _don_features(snap: dict) -> dict:
    """ドン状態から派生する 14 スカラー。 snapshot にも live state にも同じ形で存在する。"""
    hi = snap["hero_idx"]
    me, opp = snap["players"][hi], snap["players"][1 - hi]
    ma = float(me.get("don_active") or 0)
    oa = float(opp.get("don_active") or 0)
    mr = float(me.get("don_rested") or 0)
    orr = float(opp.get("don_rested") or 0)
    # 手札で今払えるカード (= アクティブドンが実際に何を可能にしているか)
    playable, max_cost, n_hand = 0, 0.0, 0
    try:
        from .deck import CardRepository
        repo = _repo()
        for cid in (me.get("hand_card_ids") or []):
            n_hand += 1
            try:
                cost = float(getattr(repo.get(cid), "cost", 0) or 0)
            except Exception:
                continue
            if cost <= ma:
                playable += 1
                max_cost = max(max_cost, cost)
    except Exception:
        pass
    # 相手の belief 残りカウンター × 払えるか (持っていても払えなければ脅威でない)
    bel_ctr = 0.0
    try:
        from . import gbm_value as G
        from collections import Counter
        ids = [c.get("card_id") for c in (opp.get("field") or [])] \
            + list(opp.get("trash_card_ids") or []) + list(opp.get("known_hand_card_ids") or [])
        seen = dict(Counter([i for i in ids if i]))
        ec, _ = G._belief_deck_totals(opp["leader"]["card_id"], seen)
        bel_ctr = float(ec)
    except Exception:
        pass
    return {
        "my_don_active": ma, "opp_don_active": oa, "my_don_rested": mr, "opp_don_rested": orr,
        "my_don_total": ma + mr, "opp_don_total": oa + orr,
        "my_playable_n": float(playable), "my_playable_max_cost": max_cost,
        "my_playable_ratio": float(playable) / float(n_hand) if n_hand else 0.0,
        "my_tapout": 1.0 if ma <= 0 else 0.0,
        "opp_tapout": 1.0 if oa <= 0 else 0.0,
        "opp_counter_payable": 1.0 if oa >= 1 else 0.0,
        "opp_belief_counter_payable": bel_ctr if oa >= 1 else 0.0,
        "opp_don_active_ge2": 1.0 if oa >= 2 else 0.0,
    }


def generate_don_candidates() -> list:
    return [{"k": "don", "c": k} for k in DON_KEYS]


# 「人間が区別しているのに現行 94 列が潰しているもの」の細分化 (2026-07-23 の監査より)。
# 実測: 手札カウンター値は平均 2.41 種を 1 列 (合計) に潰していた / 相手ブロッカーは合計パワー
# しか無く最大値 (= 壁の厚さ) が無い / 攻撃が通るかの比較列そのものが存在しなかった。
DERIVED_KEYS = (
    # ④ 攻防マッチアップ (= 人間が最初に見る「この攻撃は通るか」。 現行に比較列が無い)
    "atk_best_breaks", "atk_unblockable_n", "atk_power_over_blocker",
    "def_opp_breaks", "def_opp_unblockable_n", "blocker_wall_gap",
    # ① 手札カウンターの内訳 (= 合計 4000 が 2000×2 か 1000×4 かで守れる回数が違う)
    "my_ctr2000_n", "my_ctr1000_n", "my_ctr_none_n", "my_ctr_max",
    "my_counter_event_n", "my_counter_card_n",
    # ② ブロッカーの質 (= 壁の厚さは合計でなく最大値で決まる)
    "my_blocker_max_pw", "opp_blocker_max_pw", "my_blocker_n", "opp_blocker_n",
    # ③ アクティブキャラの質 (= 「殴れる駒 3 枚」が 1000×3 か 7000+2000×2 かで別物)
    "my_active_max_pw", "my_active_sum_pw", "opp_active_max_pw", "my_active_ge5000_n",
    # ⑤ 付与ドンの所在 (= 合計でなくどこに寄っているか)
    "my_attached_max", "my_attached_holders", "opp_attached_max",
    # ⑧ 人間の定石をそのままスカラー化 (2026-07-24、 docs/optcg/ の一次情報)。
    # 現行 94 列は「手札枚数」「ライフ枚数」を別々に持つだけで、 人間が全てを翻訳して使う
    # 合成量 (NNA / 要求値 / クロック) を持っていない。 木は理論上これらを学べるが、
    # 「hand + life×2 + 1」 のような特定の重み付き和を偶然見つけるには大量のデータが要る。
    "my_nna", "opp_nna", "nna_diff", "my_nna_le3", "opp_nna_le3",
    "my_attacks_per_turn", "opp_attacks_per_turn",
    "my_clock", "opp_clock", "clock_diff",
    "my_demand_max", "my_demand_sum", "opp_demand_max",
    "my_counter_vs_demand", "my_life_absorb",
    "my_pw_ge7000_n", "my_pw_5000_6999_n", "my_pw_lt3000_n",
    "opp_pw_ge7000_n", "opp_pw_5000_6999_n", "opp_pw_lt3000_n",
    "my_attack_ladder",
    # ⑦ 情報の非対称性 (2026-07-24)。 公開サーチ/バウンスで手札が割れている枚数。
    # ⚠ 両方とも公開情報 (自分の割れ札は自分も見ている / 相手の割れ札はこちらが見た)。
    # ブラフ・温存・「バレ札から切る」判断の土台になる量。
    "my_hand_known_n", "my_hand_known_ratio",
    "opp_hand_known_n", "opp_hand_known_ratio", "info_edge",
)


def _derived_features(snap: dict) -> dict:
    """現行列が潰している区別を明示的な列にする 23 スカラー。 snapshot / live 共通。

    ⚠ ライフの中身 (トリガー密度) は入れない: 自分のライフは本来非公開で、 snapshot の
    life_card_ids は oracle。 推論時に使えない情報を学習に入れると train/serve がズレる。"""
    hi = snap["hero_idx"]
    me, opp = snap["players"][hi], snap["players"][1 - hi]
    info = _card_info()

    def _chars(p):
        return [c for c in (p.get("field") or []) if isinstance(c, dict)]

    def _pw(c):
        return float(c.get("power") or 0)

    def _blockers(p):
        out = []
        for c in _chars(p):
            blk = c.get("is_blocker_now")
            if blk is None:
                blk = "blocker" in (info.get(c.get("card_id"), {}).get("cats") or ())
            if blk:
                out.append(_pw(c))
        return out

    def _actives(p):
        return [_pw(c) for c in _chars(p)
                if not c.get("rested") and not c.get("summoning_sickness")]

    my_act, opp_act = _actives(me), _actives(opp)
    my_blk, opp_blk = _blockers(me), _blockers(opp)
    my_atk_max = max(my_act, default=0.0)
    opp_atk_max = max([_pw(c) for c in _chars(opp)], default=0.0)
    opp_blk_max = max(opp_blk, default=0.0)
    my_blk_max = max(my_blk, default=0.0)

    # 手札のカウンター内訳
    c2 = c1 = c0 = ce = 0
    cmax = 0.0
    for cid in (me.get("hand_card_ids") or []):
        meta = info.get(cid)
        if not meta:
            continue
        cv = float(meta.get("counter_value") or 0.0)
        if cv >= 2000:
            c2 += 1
        elif cv > 0:
            c1 += 1
        else:
            c0 += 1
        cmax = max(cmax, cv)
        if meta.get("counter_event"):
            ce += 1

    att = [(float(c.get("attached_dons") or 0)) for c in _chars(me)]
    att_o = [(float(c.get("attached_dons") or 0)) for c in _chars(opp)]
    # 情報の非対称性: 手札のうち相手に割れている枚数 (公開サーチ / バウンスで判明した分)
    mk = float(len(me.get("known_hand_card_ids") or []))
    ok = float(len(opp.get("known_hand_card_ids") or []))
    mh = float(me.get("hand_count") or len(me.get("hand_card_ids") or []) or 0)
    oh = float(opp.get("hand_count") or 0)
    return {
        "atk_best_breaks": 1.0 if (my_act and (not opp_blk or my_atk_max > opp_blk_max)) else 0.0,
        "atk_unblockable_n": float(sum(1 for p in my_act if not opp_blk or p > opp_blk_max)),
        "atk_power_over_blocker": (my_atk_max - opp_blk_max) / 1000.0,
        "def_opp_breaks": 1.0 if (opp_atk_max > my_blk_max) else 0.0,
        "def_opp_unblockable_n": float(sum(1 for c in _chars(opp)
                                           if not my_blk or _pw(c) > my_blk_max)),
        "blocker_wall_gap": (my_blk_max - opp_atk_max) / 1000.0,
        "my_ctr2000_n": float(c2), "my_ctr1000_n": float(c1), "my_ctr_none_n": float(c0),
        "my_ctr_max": cmax / 1000.0, "my_counter_event_n": float(ce),
        "my_counter_card_n": float(c2 + c1),
        "my_blocker_max_pw": my_blk_max / 1000.0, "opp_blocker_max_pw": opp_blk_max / 1000.0,
        "my_blocker_n": float(len(my_blk)), "opp_blocker_n": float(len(opp_blk)),
        "my_active_max_pw": my_atk_max / 1000.0,
        "my_active_sum_pw": sum(my_act) / 1000.0,
        "opp_active_max_pw": max(opp_act, default=0.0) / 1000.0,
        "my_active_ge5000_n": float(sum(1 for p in my_act if p >= 5000)),
        "my_attached_max": max(att, default=0.0),
        "my_attached_holders": float(sum(1 for a in att if a > 0)),
        "opp_attached_max": max(att_o, default=0.0),
        **_race_scalars(me, opp, my_act, opp_act, _chars, _pw, mh, oh),
        "my_hand_known_n": mk, "my_hand_known_ratio": (mk / mh) if mh else 0.0,
        "opp_hand_known_n": ok, "opp_hand_known_ratio": (ok / oh) if oh else 0.0,
        # 正 = こちらの方が相手の手札を多く知っている (情報で優位)
        "info_edge": ok - mk,
    }


def _race_scalars(me: dict, opp: dict, my_act: list, opp_act: list,
                  _chars, _pw, mh: float, oh: float) -> dict:
    """人間の定石量 (docs/optcg/)。 NNA・要求値・クロック・パワー帯。

    NNA (必要攻撃回数) = 手札 + ライフ×2 + 1 = 「相手を倒すのに要る 5000 攻撃の最大回数」。
    上達論の中核で、 攻撃も防御もこれ 1 本に翻訳して考える。 現行特徴は手札とライフを
    別々に持つだけなので、 この特定の重み付き和は木が偶然見つけない限り使えない。
    要求値 = 攻撃側パワー − 守備側パワー + 1000 = 相手に強いるカウンター値。"""
    ml = float(me.get("life_count") or 0)
    ol = float(opp.get("life_count") or 0)
    my_nna = mh + ml * 2.0 + 1.0
    opp_nna = oh + ol * 2.0 + 1.0
    # 攻撃回数 = アクティブキャラ + リーダー (レストしていなければ)
    my_atk_n = float(len(my_act)) + (0.0 if me.get("leader_rested") else 1.0)
    # ⚠ 相手は次の自分のターンに全キャラがアクティブに戻る (召喚酔いも解ける) ので、
    # 相手の攻撃回数/要求値は「今アクティブな駒」でなく **全キャラ** で数える。
    # ここを今アクティブだけで数えると、 攻撃直後の相手を丸腰と誤認して脅威を過小評価する。
    opp_all = [_pw(c) for c in _chars(opp)]
    opp_atk_n = float(len(opp_all)) + 1.0
    my_clock = (opp_nna / my_atk_n) if my_atk_n > 0 else 99.0
    opp_clock = (my_nna / opp_atk_n) if opp_atk_n > 0 else 99.0
    # 要求値 (対リーダー): 攻撃側パワー − 相手リーダーパワー + 1000
    olp = float((opp.get("leader") or {}).get("power") or 5000)
    mlp = float((me.get("leader") or {}).get("power") or 5000)
    dem = [max(0.0, p - olp + 1000.0) / 1000.0 for p in my_act]
    odem = [max(0.0, p - mlp + 1000.0) / 1000.0 for p in opp_all]
    ctr = 0.0
    try:
        info = _card_info()
        ctr = sum(float((info.get(c) or {}).get("counter_value") or 0.0)
                  for c in (me.get("hand_card_ids") or [])) / 1000.0
    except Exception:
        pass
    opp_demand_total = sum(odem)
    my_pw = opp_all
    return {
        "my_nna": my_nna, "opp_nna": opp_nna, "nna_diff": opp_nna - my_nna,
        "my_nna_le3": 1.0 if my_nna <= 3 else 0.0,
        "opp_nna_le3": 1.0 if opp_nna <= 3 else 0.0,
        "my_attacks_per_turn": my_atk_n, "opp_attacks_per_turn": opp_atk_n,
        "my_clock": min(my_clock, 20.0), "opp_clock": min(opp_clock, 20.0),
        "clock_diff": min(opp_clock, 20.0) - min(my_clock, 20.0),
        "my_demand_max": max(dem, default=0.0), "my_demand_sum": sum(dem),
        "opp_demand_max": max(odem, default=0.0),
        # 次の相手ターンの要求値合計を、 手札のカウンター総量で払えるか (>1 なら守り切れる)
        "my_counter_vs_demand": (ctr / opp_demand_total) if opp_demand_total > 0 else 2.0,
        "my_life_absorb": ml,
        "my_pw_ge7000_n": float(sum(1 for p in my_act if p >= 7000)),
        "my_pw_5000_6999_n": float(sum(1 for p in my_act if 5000 <= p < 7000)),
        "my_pw_lt3000_n": float(sum(1 for p in my_act if p < 3000)),
        "opp_pw_ge7000_n": float(sum(1 for p in my_pw if p >= 7000)),
        "opp_pw_5000_6999_n": float(sum(1 for p in my_pw if 5000 <= p < 7000)),
        "opp_pw_lt3000_n": float(sum(1 for p in my_pw if p < 3000)),
        # 攻撃順の階段 (低→高で要求値を積む) が作れるか = アタッカーのパワー幅
        "my_attack_ladder": (max(my_act) - min(my_act)) / 1000.0 if len(my_act) > 1 else 0.0,
    }

def generate_derived_candidates() -> list:
    return [{"k": "der", "c": k} for k in DERIVED_KEYS]


_REPO_CACHE = None


def _repo():
    global _REPO_CACHE
    if _REPO_CACHE is None:
        from .deck import CardRepository
        _REPO_CACHE = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    return _REPO_CACHE


CARD_ZONES = ("my_board", "opp_board", "my_hand", "my_trash", "opp_trash", "opp_seen_hand")
_CARD_FREQ_PATH = EIV1_DIR / "card_freq.json"


def card_frequency(corpus_path: Any = None, sample: int = 60000) -> list:
    """corpus に実際に現れるカードを頻度順で返す ([(card_id, 出現数), ...])。 結果は cache。

    ⭐ カード ID 列を「全 4,731 枚」で作ると疎すぎて木が使えない。 実際に盤面/手札に出る
    カードだけに絞る (= 233 デッキプールで使われている札 = 実質数百枚)。"""
    if _CARD_FREQ_PATH.exists():
        try:
            return [(c, n) for c, n in json.loads(_CARD_FREQ_PATH.read_text(encoding="utf-8"))]
        except Exception:
            pass
    from collections import Counter
    cnt: Counter = Counter()
    path = Path(corpus_path) if corpus_path else (EIV1_DIR / "corpus.jsonl")
    lines: list = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if len(lines) > sample:
                lines.pop(0)
    for line in lines:
        try:
            snap = json.loads(line).get("state") or {}
            for p in snap.get("players", []):
                for c in (p.get("field") or []):
                    if c.get("card_id"):
                        cnt[c["card_id"]] += 1
                for cid in (p.get("hand_card_ids") or []):
                    cnt[cid] += 1
        except Exception:
            continue
    out = cnt.most_common()
    try:
        _CARD_FREQ_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CARD_FREQ_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out


def generate_card_candidates(top_n: int = 200, zones: tuple = ("my_board", "opp_board")) -> list:
    """頻出カード上位 N × zone のカード ID 列を生成 (= 「どのカードが居るか」を value に見せる)。"""
    freq = card_frequency()[:top_n]
    return [{"k": "card", "z": z, "c": cid} for z in zones for cid, _ in freq]


def generate_candidates() -> list:
    """zone × カテゴリ × 統計 の直積で候補列を機械生成 (人手ゼロ)。"""
    out = []
    for z in ZONES:
        for c in CATS:
            for s in STATS:
                if s != "count" and c not in MAG_FIELD:
                    continue   # 大きさを持たないカテゴリは count と重複するので出さない
                out.append({"k": "agg", "z": z, "c": c, "s": s})
    return out


def generate_interactions(base_cols: list) -> list:
    """効いた列 × 文脈スカラー。 この repo の実績上、 効くのは盤面と相互作用する形。"""
    return [{"k": "x", "a": c, "b": ctx} for c in base_cols for ctx in CONTEXTS]


# --- 評価器 ----------------------------------------------------------------


def _zone_cards(snap: dict, zone: str) -> list:
    """zone → [(card_id, weight)]。 weight は belief のみ期待枚数、 他は 1。
    ⚠ 必要な zone だけ作る (belief は 60-100 枚を触るので、 使わない時は組まない = 推論速度)。

    ⚠ 公平性: 推論時に知り得ない情報は使わない (自分のライフ中身 / 相手の生手札は zone に無い)。
    相手手札は公開履歴 (known_hand_card_ids) のみ、 相手デッキは belief。"""
    hi = snap["hero_idx"]
    me, opp = snap["players"][hi], snap["players"][1 - hi]

    def ids(p, key):
        return [(c, 1.0) for c in (p.get(key) or []) if c]

    def field_ids(p):
        return [(c.get("card_id"), 1.0) for c in (p.get("field") or []) if c.get("card_id")]

    if zone == "my_hand":
        return ids(me, "hand_card_ids")
    if zone == "my_board":
        return field_ids(me)
    if zone == "opp_board":
        return field_ids(opp)
    if zone == "my_trash":
        return ids(me, "trash_card_ids")
    if zone == "opp_trash":
        return ids(opp, "trash_card_ids")
    if zone == "opp_seen_hand":
        return ids(opp, "known_hand_card_ids")
    if zone == "opp_belief":
        return _belief_rest(snap)
    return []


def _seen_key(snap: dict) -> tuple:
    """相手の見た札 (場+トラッシュ+バレ手札) の署名。 belief 集計の cache key。"""
    opp = snap["players"][1 - snap["hero_idx"]]
    seen: dict = {}
    for cid in [c.get("card_id") for c in (opp.get("field") or [])] \
            + list(opp.get("trash_card_ids") or []) + list(opp.get("known_hand_card_ids") or []):
        if cid:
            seen[cid] = seen.get(cid, 0) + 1
    return opp["leader"]["card_id"], tuple(sorted(seen.items()))


def _belief_rest(snap: dict) -> list:
    lid, seen_t = _seen_key(snap)
    seen = dict(seen_t)
    return [(cid, e - seen.get(cid, 0)) for cid, e in _belief_cards(lid)
            if e - seen.get(cid, 0) > 0]


_BELIEF_AGG_CACHE: dict = {}


def _belief_aggregates(snap: dict) -> dict:
    """belief zone の集計は 60-100 枚を触るので (leader, 見た札) で cache する。
    beam は同じ局面から多数の枝を評価するので hit 率が高い。"""
    key = _seen_key(snap)
    agg = _BELIEF_AGG_CACHE.get(key)
    if agg is None:
        agg = _zone_aggregates(_belief_rest(snap))
        if len(_BELIEF_AGG_CACHE) < 100000:
            _BELIEF_AGG_CACHE[key] = agg
    return agg


def _zone_aggregates(cards: list) -> dict:
    """[(cid, w)] → {(cat, stat): value}。 zone ごとに 1 回だけ回す。"""
    info = _card_info()
    agg: dict = {}
    for cid, w in cards:
        meta = info.get(cid)
        if not meta:
            continue
        mags = meta["mags"]
        for cat in meta["cats"]:
            agg[(cat, "count")] = agg.get((cat, "count"), 0.0) + w
            f = MAG_FIELD.get(cat)
            if f:
                v = float(mags.get(f, 0.0) or 0.0)
                if v:
                    agg[(cat, "mag_sum")] = agg.get((cat, "mag_sum"), 0.0) + w * v
                    agg[(cat, "mag_max")] = max(agg.get((cat, "mag_max"), 0.0), v)
    return agg


def _contexts(snap: dict) -> dict:
    hi = snap["hero_idx"]
    me, opp = snap["players"][hi], snap["players"][1 - hi]

    def pw(p):
        v = p.get("field_total_power")
        if v is None:
            v = sum(float(c.get("power") or 0) for c in (p.get("field") or []))
        return float(v) / 1000.0
    ml, ol = float(me.get("life_count") or 0), float(opp.get("life_count") or 0)
    return {"turn": float(snap.get("turn_number") or 0), "life_diff": ml - ol,
            "opp_life": ol, "my_life": ml, "board_pw_diff": pw(me) - pw(opp),
            "my_don": float(me.get("don_active") or 0),
            "opp_hand_n": float(opp.get("hand_count") or 0)}


def evaluate(snap: dict, spec: list) -> list:
    """snapshot (または _mini_snap した live state) + spec → 列の値。"""
    if not spec:
        return []
    try:
        need, need_card, need_don, need_der, need_eye = set(), set(), False, False, False
        for col in spec:
            base = col["a"] if col.get("k") == "x" else col
            if base.get("k") == "don":
                need_don = True
            elif base.get("k") == "der":
                need_der = True
            elif base.get("k") == "eye":
                need_eye = True
            elif base.get("k") == "card":
                need_card.add(base["z"])
            else:
                need.add(base["z"])
        dons = _don_features(snap) if need_don else {}
        ders = _derived_features(snap) if need_der else {}
        eyes = _eyes_features(snap) if need_eye else {}
        aggs = {z: (_belief_aggregates(snap) if z == "opp_belief"
                    else _zone_aggregates(_zone_cards(snap, z))) for z in need}
        # カード ID 列: zone ごとに card_id → 枚数 を 1 回だけ作る
        counts = {}
        for z in need_card:
            d: dict = {}
            for cid, w in _zone_cards(snap, z):
                d[cid] = d.get(cid, 0.0) + w
            counts[z] = d
        ctx = _contexts(snap) if any(c.get("k") == "x" for c in spec) else {}
        out = []
        for col in spec:
            base = col["a"] if col.get("k") == "x" else col
            if base.get("k") == "don":
                v = dons.get(base["c"], 0.0)
            elif base.get("k") == "der":
                v = ders.get(base["c"], 0.0)
            elif base.get("k") == "eye":
                v = eyes.get(base["c"], 0.0)
            elif base.get("k") == "card":
                v = counts[base["z"]].get(base["c"], 0.0)
            else:
                v = aggs[base["z"]].get((base["c"], base["s"]), 0.0)
            if col.get("k") == "x":
                v *= ctx.get(col["b"], 0.0)
            out.append(float(v))
        return out
    except Exception:
        return [0.0] * len(spec)


# --- spec の入出力 ----------------------------------------------------------


def load_spec(path: Any) -> list:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return list(d.get("columns") or [])
    except Exception:
        return []


def active_spec() -> list:
    """学習が今使う spec (無ければ空 = v20(94) のまま)。"""
    return load_spec(ACTIVE_SPEC_PATH)


def spec_path_for_model(model_path: Any) -> Path:
    p = Path(model_path)
    return p.with_suffix("").with_suffix(".spec.json") if p.suffix == ".pkl" \
        else Path(str(p) + ".spec.json")


def save_spec(path: Any, columns: list, provenance: Optional[dict] = None) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(
        {"n_columns": len(columns), "columns": columns, "provenance": provenance or {}},
        ensure_ascii=False, indent=1), encoding="utf-8")


# === 「EIV1 に目を」 — 盤面の個体を 1 体ずつ見る + 未使用ゾーンを全部使う (2026-07-24) =======
# ohtsuki:「ワンピースカードは複雑なはずで、 スカラーがこれで足りているとは到底思えない」。
# 監査したら snapshot にあるのに特徴が 1 つも使っていないものが多数あった:
#   リーダーの状態 (パワー/レスト/付与ドン) / ステージ / デッキ残枚数 / トラッシュ枚数 /
#   レストドン / ドンデッキ残 / キーワード付与 / マリガン有無 / 効果発動の累計回数
# さらに盤面は top1/top2 しか見ていなかった → **上位 5 体を 1 体ずつ**見る。

_SLOT_N = 5
_SLOT_ATTRS = ("power", "cost", "don", "rested", "blocker", "removal", "engine")
EYES_KEYS = tuple(
    [f"{side}_c{i}_{at}" for side in ("my", "opp") for i in range(_SLOT_N) for at in _SLOT_ATTRS]
    + ["my_leader_power", "opp_leader_power", "my_leader_rested", "opp_leader_rested",
       "my_leader_don", "opp_leader_don",
       "my_stage_n", "opp_stage_n", "my_deck_left", "opp_deck_left",
       "my_trash_n", "opp_trash_n", "my_don_deck_left", "opp_don_deck_left",
       "my_mulliganed", "opp_mulliganed", "effect_events_total",
       "my_kw_rush_n", "opp_kw_rush_n", "my_kw_granted_n", "opp_kw_granted_n",
       "my_sick_n", "opp_sick_n", "my_rested_n", "opp_rested_n"]
    + [f"my_hand_cost{c}_n" for c in range(1, 8)]
    + ["my_hand_cost8plus_n", "my_hand_chara_n", "my_hand_event_n", "my_hand_stage_n",
       "my_hand_best_playable_pw", "my_hand_avg_cost"]
    # 効果発動の履歴 (2026-07-24 に engine が常時記録するようになった。 それ以前は audit
    # モード専用で corpus は常に空だった)。 「相手はこの試合で何回効果を使ったか」
    # 「直近に除去/ドローを撃たれたか」 は人間が当然使う情報。
    + ["my_effects_used", "opp_effects_used", "effects_used_diff",
       "opp_recent_removal", "opp_recent_draw", "opp_recent_search",
       "recent_effects_n", "my_effects_per_turn"]
)


def _eyes_features(snap: dict) -> dict:
    """盤面を 1 体ずつ見る + 未使用ゾーンを全部使う。 全て snapshot / _mini_snap 共通の key。"""
    info = _card_info()
    hi = snap["hero_idx"]
    me, opp = snap["players"][hi], snap["players"][1 - hi]
    out: dict = {}

    def _slots(p, side):
        chars = sorted([c for c in (p.get("field") or []) if isinstance(c, dict)],
                       key=lambda c: -float(c.get("power") or 0))
        for i in range(_SLOT_N):
            c = chars[i] if i < len(chars) else None
            meta = info.get((c or {}).get("card_id")) or {}
            cats = meta.get("cats") or frozenset()
            out[f"{side}_c{i}_power"] = float(c.get("power") or 0) / 1000.0 if c else 0.0
            out[f"{side}_c{i}_cost"] = float(c.get("cost") or 0) if c else 0.0
            out[f"{side}_c{i}_don"] = float(c.get("attached_dons") or 0) if c else 0.0
            out[f"{side}_c{i}_rested"] = 1.0 if (c and c.get("rested")) else 0.0
            out[f"{side}_c{i}_blocker"] = 1.0 if (c and c.get("is_blocker_now")) else 0.0
            out[f"{side}_c{i}_removal"] = 1.0 if (cats & {"removal", "removal_ko"}) else 0.0
            out[f"{side}_c{i}_engine"] = 1.0 if (cats & {"draw", "search", "ramp_don"}) else 0.0
        return chars

    mc, oc = _slots(me, "my"), _slots(opp, "opp")
    for side, p in (("my", me), ("opp", opp)):
        ld = p.get("leader") or {}
        out[f"{side}_leader_power"] = float(ld.get("power") or 5000) / 1000.0
        out[f"{side}_leader_rested"] = 1.0 if ld.get("rested") else 0.0
        out[f"{side}_leader_don"] = float(ld.get("attached_dons") or 0)
        out[f"{side}_stage_n"] = float(len(p.get("stages") or []))
        out[f"{side}_deck_left"] = float(p.get("deck_count") or 0)
        out[f"{side}_trash_n"] = float(p.get("trash_count") or len(p.get("trash_card_ids") or []))
        out[f"{side}_don_deck_left"] = float(p.get("don_remaining_in_deck") or 0)
        out[f"{side}_mulliganed"] = 1.0 if p.get("did_mulligan") else 0.0
    out["effect_events_total"] = float(snap.get("total_effect_events_count") or 0)
    for side, chars in (("my", mc), ("opp", oc)):
        out[f"{side}_kw_rush_n"] = float(sum(1 for c in chars if c.get("is_rush_now")))
        out[f"{side}_kw_granted_n"] = float(sum(len(c.get("granted_keywords") or []) for c in chars))
        out[f"{side}_sick_n"] = float(sum(1 for c in chars if c.get("summoning_sickness")))
        out[f"{side}_rested_n"] = float(sum(1 for c in chars if c.get("rested")))
    # 手札のコストカーブ (= 「何が出せるか」の形。 現行は枚数 1 列のみ)
    costs, chara, event, stage, best_pw = [], 0, 0, 0, 0.0
    don = float(me.get("don_active") or 0)
    try:
        repo = _repo()
        for cid in (me.get("hand_card_ids") or []):
            try:
                card = repo.get(cid)
            except Exception:
                continue
            cost = float(getattr(card, "cost", 0) or 0)
            costs.append(cost)
            cat = str(getattr(card, "category", "")).upper()
            if "EVENT" in cat:
                event += 1
            elif "STAGE" in cat:
                stage += 1
            else:
                chara += 1
            if cost <= don:
                best_pw = max(best_pw, float(getattr(card, "power", 0) or 0))
    except Exception:
        pass
    for c in range(1, 8):
        out[f"my_hand_cost{c}_n"] = float(sum(1 for x in costs if int(x) == c))
    out["my_hand_cost8plus_n"] = float(sum(1 for x in costs if x >= 8))
    out["my_hand_chara_n"] = float(chara)
    out["my_hand_event_n"] = float(event)
    out["my_hand_stage_n"] = float(stage)
    out["my_hand_best_playable_pw"] = best_pw / 1000.0
    out["my_hand_avg_cost"] = (sum(costs) / len(costs)) if costs else 0.0

    # --- 効果発動の履歴 ---
    by = list(snap.get("effect_events_by_player") or [0, 0])
    mine = float(by[hi]) if len(by) > hi else 0.0
    theirs = float(by[1 - hi]) if len(by) > (1 - hi) else 0.0
    rec = list(snap.get("recent_effect_events") or [])
    opp_rec = [e for e in rec if len(e) > 2 and e[1] == (1 - hi)]
    turn = float(snap.get("turn_number") or 1)
    out["my_effects_used"] = mine
    out["opp_effects_used"] = theirs
    out["effects_used_diff"] = mine - theirs
    out["opp_recent_removal"] = float(sum(1 for e in opp_rec if "ko" in str(e[2])
                                          or "return_to_hand" in str(e[2])))
    out["opp_recent_draw"] = float(sum(1 for e in opp_rec if "draw" in str(e[2])))
    out["opp_recent_search"] = float(sum(1 for e in opp_rec if "search" in str(e[2])))
    out["recent_effects_n"] = float(len(rec))
    out["my_effects_per_turn"] = mine / max(turn, 1.0)
    return out


def generate_eyes_candidates() -> list:
    return [{"k": "eye", "c": k} for k in EYES_KEYS]
