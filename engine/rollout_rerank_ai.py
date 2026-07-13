# -*- coding: utf-8 -*-
"""推論時 rollout-rerank AI (2026-07-10、 ohtsuki 機構の配備形)。

配備 ExploitBeam の各 MAIN 決定で、候補手を「**強い下流プレイ(ExploitBeam)での rollout 勝率**」で
再ランク → argmax を選ぶ。= TD-Gammon 式 root rollout policy improvement。悪い value を強い探索で
補償する(エネル vs Ace で +43pt 実証、 [[project_experience_pruning_result]])。

⚠⚠ **検証結果 = 公平版は改善無し(2026-07-11、 [[project_experience_pruning_result]])**。 見かけの
+43pt は full-info rollout(下記 determinize=False 相当)が相手の隠匿手札を覗く**情報アドバンテージ
の artifact**。 同一 config(CAND4 RO5 N40)で determinize ON=+0pt / OFF=+35pt = 覗くか否かが全て。
公平プレイ(determinize=True)では配備 value を超えない。 = 研究用に残置、 配備はしない。

⚠ 遅い(1手 ~数〜十数秒、 CAND×RO の ExploitBeam rollout)。matrix/practice の既定は高速 value のまま。

公平性(human-play): rollout は相手の**隠匿手札を覗かない** — determinize=True で相手の hand を
(hand+deck)プールから再配布し、自分の deck も再シャッフルしてから playout する(既知の decklist は
使うが、 現在どのカードが手札かは推定=paired rollout の variance 低減も兼ねる)。

下流 policy の強さが効果を決める(greedy=+0 / goal=+7 / beam4=+10 / ExploitBeam=+43pt)ので、
下流は既定 ExploitBeam。相手 deck 既知なら ro_opp_slug で config を渡すと playout が忠実になる。
"""
from __future__ import annotations
import math
import os
import pickle
import random
from collections import Counter
from typing import Optional

from engine.exploit_beam_ai import ExploitBeamAI
from engine.game import (legal_actions, apply_action, AttackLeader, AttackCharacter,
                         ActivateMain, PlayCharacter)
from engine.ai import play_one_action
from engine.plan_search import fast_clone


class RolloutRerankAI(ExploitBeamAI):
    def __init__(self, *args, ro_cand: int = 4, ro_n: int = 3,
                 ro_opp_slug: Optional[str] = None, ro_turn_cap: int = 40,
                 ro_determinize: bool = True, ro_reveal_p: float = 0.0,
                 ro_hand_predict: bool = False, ro_feature_reveal: bool = False,
                 ro_feature_predict: bool = False, ro_crn: bool = False,
                 ro_feature_map: bool = False, ro_map_thresh: float = 0.5,
                 ro_log_shifts: bool = False, ro_risk_aware: bool = False,
                 ro_risk_k: float = 2.0, ro_adv_thresh: float = 0.35, **kwargs):
        super().__init__(*args, **kwargs)
        self._ro_cand = ro_cand
        self._ro_n = ro_n
        self._ro_opp_slug = ro_opp_slug
        self._ro_turn_cap = ro_turn_cap
        self._ro_determinize = ro_determinize
        # 手札予測器の accuracy 代理: 各相手カードを確率 p で真の位置(hand/deck)に固定、
        # 残りを一様 redeal。 p=0=一様(予測無し)、 p=1=full-info(完全予測)。 天井曲線の測定用。
        self._ro_reveal_p = ro_reveal_p
        # ⭐ ④⑤ ceiling (2026-07-11): 相手手札の「特徴カウント」(rush/counter2000/blocker/removal)
        # だけを真値として固定し、 exact card は隠して redeal。 = 「特徴を確実に知る」公平プレイ。
        # 予測器 (③ AUC0.63) が到達しうる上限を測る。 これが +0 なら ④⑤ Q-pipeline は無意味。
        self._ro_feature_reveal = ro_feature_reveal
        # ⑤ 配備形 (2026-07-11): feature-reveal の「真値」を ③ 予測器の belief に置換 (覗かない公平)。
        self._ro_feature_predict = ro_feature_predict
        # CRN(common random numbers): 候補評価を同一 world で paired 化(predict-mode の分散低減)。
        self._ro_crn = ro_crn
        # ⭐ MAP-commit (ohtsuki 人間モデル): 最尤な手札特徴に決め打ち (hedge でなく commit)。
        self._ro_feature_map = ro_feature_map
        self._ro_map_thresh = ro_map_thresh
        # 診断: 各決定で belief が base の手を変えたか (must-react vs gameplan の分解)。 peek=ログ専用。
        self._ro_log_shifts = ro_log_shifts
        self.shift_log = []
        # ⭐ risk-aware「踏まない」(ohtsuki): 予測で plausible な脅威を特定 → 有利時はその脅威で崩れる手を
        # 減点(平均でなく最悪plausibleを回避)。 予測(不確定情報)を hedge でなく回避に使う。
        self._ro_risk_aware = ro_risk_aware
        self._ro_risk_k = ro_risk_k          # risk 回避の強さ (lead に比例)
        self._ro_adv_thresh = ro_adv_thresh  # P(feature) >= これ なら plausible な脅威として固定
        # 診断: risk-aware が発火(lam>0)した回数 / 実際に argmax を変えた回数 / 全 rerank 決定数
        self.risk_fires = 0
        self.risk_changes = 0
        self.rerank_decisions = 0
        # ⭐ ohtsuki 案: 学習した「盤面→手札」予測器で相手手札を weighted-sample (一様でなく)。
        # db/hand_predictor_<ro_opp_slug>.pkl があれば load。 覗かない公平のまま予測で補填。
        self._ro_hand_predict = ro_hand_predict
        self._hp = None
        self._hp_loaded = False
        self._ro_seq = 0
        # behavioral: 相手が受けた攻撃数 = 自分(hero)がこの game で相手にした攻撃数 (2人対戦)。
        # 予測器の attacks_faced 特徴に使う (= カウンターを切る機会。 未使用→手札に無い推定)。
        self._attacks_made = 0

    @staticmethod
    def _cid(c):
        return getattr(c, "card_id", None) or getattr(getattr(c, "card", None), "card_id", None)

    def _load_hand_predictor(self):
        if self._hp_loaded:
            return self._hp
        self._hp_loaded = True
        self._hp = None
        if self._ro_opp_slug:
            p = f"db/hand_predictor_{self._ro_opp_slug}.pkl"
            if os.path.exists(p):
                try:
                    self._hp = pickle.load(open(p, "rb"))
                except Exception:
                    self._hp = None
        return self._hp

    def _predict_hand_weights(self, state, opp_idx):
        """{card_id: E[手札枚数]} を予測 (train_hand_predictor._row と特徴を一致させる)。"""
        hp = self._load_hand_predictor()
        if hp is None:
            return None
        opp = state.players[opp_idx]
        board = Counter(self._cid(c) for c in getattr(opp, "characters", []))
        trash = Counter(self._cid(c) for c in getattr(opp, "trash", []))
        turn = state.turn_number
        hs = len(getattr(opp, "hand", []))
        da = int(getattr(opp, "don_active", 0) or 0)
        dr = int(getattr(opp, "don_rested", 0) or 0)
        life = len(getattr(opp, "life", []) or [])
        nb = sum(board.values())
        nt = sum(trash.values())
        cm = hp["card_meta"]

        def _cm(cid):
            v = cm.get(cid, (0, "", 0))
            return (v[0], v[1], v[2] if len(v) > 2 else 0)
        # behavioral (train_hand_predictor._row と一致): 使ったカウンター数 / 受けた攻撃数
        n_ctr = sum(n for cid, n in trash.items() if _cm(cid)[2] >= 1000)
        af = self._attacks_made
        v2 = hp.get("feat_version") == "v2_behavioral"
        rows = []
        cards = hp["cards"]
        for cid in cards:
            cost, cat, counter = _cm(cid)
            row = [turn, board.get(cid, 0), trash.get(cid, 0), hp["deck_counts"].get(cid, 0),
                   hs, nb, nt, da, dr, life, cost,
                   1 if cat == "EVENT" else 0, 1 if cat == "CHARACTER" else 0,
                   1 if cat == "STAGE" else 0]
            if v2:
                row += [af, counter, n_ctr, max(0, af - n_ctr)]
            rows.append(row)
        import numpy as np
        pred = hp["model"].predict(np.array(rows, dtype=float))
        return {cid: max(0.0, float(p)) for cid, p in zip(cards, pred)}

    # --- 下流 playout policy (強さが効果を決める → 既定 ExploitBeam) ---
    def _mk_down(self, is_me: bool, seed: int):
        slug = (self.deck_analysis or {}).get("deck_slug") if is_me else self._ro_opp_slug
        da = {"deck_slug": slug} if slug else None
        return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)

    # --- 相手隠匿手札の determinize (覗かない) + 自 deck 再シャッフル ---
    def _determinize(self, state, me_idx: int, seed: int):
        r = random.Random(seed)
        p = self._ro_reveal_p
        if p >= 1.0:
            return  # full-info (覗く): 天井測定用
        opp_idx = 1 - me_idx
        opp = state.players[opp_idx]
        hand = list(getattr(opp, "hand", []))
        deck = list(getattr(opp, "deck", []))
        if self._ro_feature_reveal:
            self._determinize_feature_reveal(state, me_idx, opp, hand, deck, r)
            return
        if self._ro_feature_predict:
            self._determinize_feature_predict(state, me_idx, opp, hand, deck, r)
            return
        weights = self._predict_hand_weights(state, opp_idx) if self._ro_hand_predict else None
        # reveal-p: 各カードを確率 p で真の位置に固定、 残りを redeal (index-safe)
        fixed_hand, pool = [], []
        for c in hand:
            (fixed_hand if r.random() < p else pool).append(c)
        fixed_deck = []
        for c in deck:
            (fixed_deck if r.random() < p else pool).append(c)
        need = len(hand) - len(fixed_hand)
        if weights and need > 0 and pool:
            # 予測器で weighted-sample without replacement (Efraimidis-Spirakis)
            keyed = []
            for c in pool:
                w = max(1e-4, weights.get(self._cid(c), 1e-4))
                u = r.random() or 1e-12
                keyed.append((math.log(u) / w, c))  # w 大 → key 大 → 選ばれやすい
            keyed.sort(key=lambda t: t[0], reverse=True)
            opp.hand = fixed_hand + [c for _, c in keyed[:need]]
            opp.deck = fixed_deck + [c for _, c in keyed[need:]]
        else:
            r.shuffle(pool)
            opp.hand = fixed_hand + pool[:need]
            opp.deck = fixed_deck + pool[need:]
        r.shuffle(opp.deck)
        me = state.players[me_idx]
        d = list(getattr(me, "deck", []))
        r.shuffle(d)
        me.deck = d

    def _determinize_feature_reveal(self, state, me_idx, opp, hand, deck, r):
        """相手手札の feature カウント (rush/counter2000/blocker/removal) だけを真値として固定し、
        exact card 同一性は隠して redeal。 = ④⑤ の ceiling (特徴を確実に知る公平プレイ)。"""
        from engine.hand_feature_predictor import _card_features, FEATURES
        target = {f: 0 for f in FEATURES}
        for c in hand:
            fe = _card_features(c)
            for f in FEATURES:
                if fe.get(f):
                    target[f] += 1
        self._redeal_to_targets(state, me_idx, opp, hand, deck, r, target)

    def _determinize_feature_predict(self, state, me_idx, opp, hand, deck, r):
        """⑤ 配備形: ③ HandFeaturePredictor で P(相手手札に特徴F)を推定 → 各 rollout で
        Bernoulli(P_F) をサンプル → その指標に手札を合わせて redeal。 = 「予測した特徴belief」を
        rollout に注入(覗かない公平)。 予測器の確信度が gain を決める(曖昧なら hedge で +0)。"""
        from engine.hand_feature_predictor import get_default, FEATURES
        opp_idx = 1 - me_idx
        lid = self._opp_leader_id(state, opp_idx)
        probs = get_default().predict(lid, state, opp_idx) if lid else {}
        if self._ro_feature_map:
            # ⭐ MAP-commit (ohtsuki 人間モデル): 最尤な手札状態に決め打ちで賭ける (hedge しない)。
            # P>=閾 → 特徴「有り」として確実に扱う。 各 choose_action で board 込み再予測 =
            # 「状況が変わるたび仮説を組み立てなおす」。 曖昧でも一番ありそうな方に commit。
            target = {f: (1 if float(probs.get(f, 0.0)) >= self._ro_map_thresh else 0) for f in FEATURES}
        else:
            # Bernoulli(P) sample = belief を marginalize (hedge)。 曖昧だと base と同手 → +0。
            target = {f: (1 if r.random() < float(probs.get(f, 0.0)) else 0) for f in FEATURES}
        self._redeal_to_targets(state, me_idx, opp, hand, deck, r, target)

    @staticmethod
    def _opp_leader_id(state, opp_idx):
        opp = state.players[opp_idx]
        ld = getattr(opp, "leader", None)
        if ld is None:
            return None
        return getattr(ld, "card_id", None) or getattr(getattr(ld, "card", None), "card_id", None)

    def _redeal_to_targets(self, state, me_idx, opp, hand, deck, r, target):
        """(hand+deck) プールから手札を target[feature] カウントに合わせて redeal。 exact card は隠す。
        target=0 の feature は手札から極力排除(=「確実に持っていない」信号)。 multiset/手札枚数を保存。"""
        from engine.hand_feature_predictor import _card_features, FEATURES
        pool = hand + deck
        r.shuffle(pool)
        feats = [_card_features(c) for c in pool]  # CardDef 直接 (hand/deck 要素)
        n_hand = len(hand)
        taken = [False] * len(pool)
        taken_order = []
        cur = {f: 0 for f in FEATURES}
        # 稀少 feature 優先で満たす。 各充足で「他 feature の target 超過」を最小化するカードを選び、
        # 相関 feature の漏れ(removal+blocker 等)を抑える。
        for f in FEATURES:
            while cur[f] < target.get(f, 0):
                best_i, best_cost = -1, 999
                for i in range(len(pool)):
                    if taken[i] or not feats[i].get(f):
                        continue
                    cost = sum(1 for g in FEATURES
                               if g != f and feats[i].get(g) and cur[g] >= target.get(g, 0))
                    if cost < best_cost:
                        best_cost, best_i = cost, i
                        if cost == 0:
                            break
                if best_i < 0:
                    break  # pool に f-card が尽きた
                taken[best_i] = True
                taken_order.append(best_i)
                for g in FEATURES:
                    if feats[best_i].get(g):
                        cur[g] += 1
        need = n_hand - len(taken_order)
        rem_idx = [i for i in range(len(pool)) if not taken[i]]
        if need > 0:
            # target=0 の feature を持つカードを避け(強制ゼロ尊重)、 次に feature 無しを優先
            zero_f = [f for f in FEATURES if target.get(f, 0) == 0]

            def _fill_key(i):
                violates_zero = any(feats[i].get(f) for f in zero_f)
                has_any = any(feats[i].get(f) for f in FEATURES)
                return (1 if violates_zero else 0, 1 if has_any else 0)
            rem_idx.sort(key=_fill_key)
            taken_order += rem_idx[:need]
            rem_idx = rem_idx[need:]
        elif need < 0:
            # dual-feature hand を単一 feature の pool card で満たすと n_hand 超過 (稀): 余りを deck へ
            rem_idx = taken_order[n_hand:] + rem_idx
            taken_order = taken_order[:n_hand]
        new_hand = [pool[i] for i in taken_order]
        remaining = [pool[i] for i in rem_idx]
        r.shuffle(remaining)
        opp.hand = new_hand
        opp.deck = remaining
        me = state.players[me_idx]
        d = list(getattr(me, "deck", [])); r.shuffle(d); me.deck = d

    def _determinize_adversarial(self, state, me_idx, seed):
        """予測で plausible(P>=閾)な脅威を手札に present で固定 = 「相手が持ってたら痛い最悪plausible手」。
        脅威以外は自然に pool から埋める(強制排除しない)。 risk-aware「踏まない」の下振れ評価用。"""
        from engine.hand_feature_predictor import _card_features, get_default, FEATURES
        r = random.Random(seed)
        opp_idx = 1 - me_idx
        opp = state.players[opp_idx]
        hand = list(getattr(opp, "hand", []))
        deck = list(getattr(opp, "deck", []))
        lid = self._opp_leader_id(state, opp_idx)
        probs = get_default().predict(lid, state, opp_idx) if lid else {}
        threats = [f for f in FEATURES if float(probs.get(f, 0.0)) >= self._ro_adv_thresh]
        pool = hand + deck
        r.shuffle(pool)
        feats = [_card_features(c) for c in pool]
        n_hand = len(hand)
        taken = [False] * len(pool)
        taken_order = []
        for f in threats:  # 各 plausible 脅威を最低1枚 hand に固定
            for i in range(len(pool)):
                if not taken[i] and feats[i].get(f):
                    taken[i] = True
                    taken_order.append(i)
                    break
        rem = [i for i in range(len(pool)) if not taken[i]]
        need = n_hand - len(taken_order)
        if need > 0:
            taken_order += rem[:need]
            rem = rem[need:]
        elif need < 0:
            rem = taken_order[n_hand:] + rem
            taken_order = taken_order[:n_hand]
        opp.hand = [pool[i] for i in taken_order]
        remaining = [pool[i] for i in rem]
        r.shuffle(remaining)
        opp.deck = remaining
        me = state.players[me_idx]
        d = list(getattr(me, "deck", [])); r.shuffle(d); me.deck = d

    def _rollout_winrate(self, base, cand_idx: int, me_idx: int, seed: int,
                         adversarial: bool = False) -> float:
        b = fast_clone(base)
        if self._ro_determinize:
            if adversarial:
                self._determinize_adversarial(b, me_idx, seed)
            else:
                self._determinize(b, me_idx, seed)
        acts = legal_actions(b)
        if cand_idx >= len(acts):
            return 0.5
        try:
            apply_action(b, acts[cand_idx])
        except Exception:
            return 0.5
        dr = [None, None]
        dr[me_idx] = self._mk_down(True, seed * 3 + 1)
        dr[1 - me_idx] = self._mk_down(False, seed * 5 + 2)
        steps = 0
        while not b.game_over and b.turn_number < self._ro_turn_cap and steps < 400:
            cur = b.turn_player_idx
            try:
                play_one_action(b, dr[cur], dr[1 - cur])
            except Exception:
                break
            steps += 1
        if not b.game_over:
            return 0.5
        w = getattr(b, "winner", -1)
        return 1.0 if w == me_idx else (0.0 if w == (1 - me_idx) else 0.5)

    def _candidate_idxs(self, acts, dep_idx: Optional[int]):
        cand = set()
        if dep_idx is not None:
            cand.add(dep_idx)
        for i, a in enumerate(acts):
            if isinstance(a, (AttackLeader, AttackCharacter, ActivateMain, PlayCharacter)):
                cand.add(i)
        return sorted(cand)[:self._ro_cand]

    def _track(self, action):
        """behavioral: hero の攻撃をカウント (= 相手が受けた攻撃数 attacks_faced)。"""
        if isinstance(action, (AttackLeader, AttackCharacter)):
            self._attacks_made += 1
        return action

    def choose_action(self, state):
        if getattr(state.phase, "name", "") != "MAIN":
            return self._track(super().choose_action(state))
        me_idx = state.turn_player_idx
        acts = legal_actions(state)
        # 配備 ExploitBeam の手を候補に含める(base policy の argmax)
        dep = super().choose_action(state)
        dep_idx = None
        for i, a in enumerate(acts):
            if a == dep:
                dep_idx = i
                break
        cands = self._candidate_idxs(acts, dep_idx)
        if len(cands) <= 1:
            return self._track(dep)
        self._ro_seq += 1
        # 各候補の belief 勝率 (通常 determinize) を計算
        wr = {}
        for ci in cands:
            w = 0.0
            for si in range(self._ro_n):
                # CRN(common random numbers): seed を ci 非依存にし、 全候補を同一 determinize world +
                # 同一 downstream RNG で評価 → paired 比較 → predict-mode の Bernoulli feature sampling
                # 分散を除去(候補は「打つ手」だけが違う)。 ci 依存(既定)は独立 world = 高分散。
                if self._ro_crn:
                    seed = self._ro_seq * 100003 + si * 17
                else:
                    seed = self._ro_seq * 100003 + ci * 131 + si * 17
                w += self._rollout_winrate(state, ci, me_idx, seed)
            wr[ci] = w / self._ro_n
        score = dict(wr)
        self.rerank_decisions += 1
        if self._ro_risk_aware:
            # ⭐「踏まない」: lead(=最善候補の belief 勝率)が高い時ほど、 plausible 脅威で崩れる手を減点。
            # 有利=リード保持で下振れ回避、 不利=λ≈0 で通常 belief 評価(勝ち筋に賭ける)。
            lead = max(wr.values()) if wr else 0.5
            lam = self._ro_risk_k * max(0.0, lead - 0.55)
            if lam > 0:
                self.risk_fires += 1
                wr_argmax = max(wr, key=lambda c: wr[c])
                for ci in cands:
                    adv = 0.0
                    for si in range(self._ro_n):
                        seed = self._ro_seq * 100003 + 777 + ci * 131 + si * 17
                        adv += self._rollout_winrate(state, ci, me_idx, seed, adversarial=True)
                    adv /= self._ro_n
                    # 脅威世界で belief より大きく落ちる手ほど減点 (= 相手の out を踏む手)
                    score[ci] = wr[ci] - lam * max(0.0, wr[ci] - adv)
                if max(score, key=lambda c: score[c]) != wr_argmax:
                    self.risk_changes += 1
        best_idx, best_w = (dep_idx if dep_idx is not None else cands[0]), -1.0
        for ci in cands:
            if score[ci] > best_w:
                best_w, best_idx = score[ci], ci
        # 再計算した legal_actions は同順(MAIN は自 hand/board 依存)なので index で返す
        cur_acts = legal_actions(state)
        chosen = cur_acts[best_idx] if best_idx < len(cur_acts) else dep
        if self._ro_log_shifts:
            self._log_shift(state, me_idx, acts, dep_idx, best_idx, chosen, dep, len(cands))
        return self._track(chosen)

    @staticmethod
    def _action_kind(a):
        if isinstance(a, AttackLeader):
            return "atk_leader"
        if isinstance(a, AttackCharacter):
            return "atk_char"
        if isinstance(a, ActivateMain):
            return "activate"
        if isinstance(a, PlayCharacter):
            return "play"
        return type(a).__name__

    @staticmethod
    def _cname(c):
        return getattr(c, "name", None) or getattr(c, "card_id", "?")

    def _describe_action(self, state, action, me_idx):
        """行動を可読文字列に(手札から出す札名 / 攻撃者・対象 を含める)。"""
        t = type(action).__name__
        v = dict(vars(action)) if hasattr(action, "__dict__") else {}
        p = state.players[me_idx]
        hand = getattr(p, "hand", [])
        chars = getattr(p, "characters", [])
        if "hand_idx" in v and isinstance(v["hand_idx"], int) and 0 <= v["hand_idx"] < len(hand):
            return f"{t}({self._cname(hand[v['hand_idx']])})"
        if t in ("AttackLeader", "AttackCharacter"):
            ai = v.get("attacker_idx", v.get("attacker"))
            atk = "leader"
            if isinstance(ai, int) and 0 <= ai < len(chars):
                atk = self._cname(chars[ai])
            tgt = "→leader" if t == "AttackLeader" else f"→char{v.get('target_idx', v.get('target',''))}"
            return f"Atk({atk}{tgt})"
        return f"{t}({v})" if v else t

    def _log_shift(self, state, me_idx, acts, dep_idx, best_idx, chosen, dep, n_cands):
        """診断: この決定で belief が base の手を変えたか + 相手の真手札/盤面/ライフ の具体 snapshot。"""
        from engine.hand_feature_predictor import _card_features, FEATURES, get_default
        opp_idx = 1 - me_idx
        opp = state.players[opp_idx]
        me = state.players[me_idx]
        true_ind = {f: (1 if any(_card_features(c).get(f) for c in getattr(opp, "hand", [])) else 0)
                    for f in FEATURES}
        lid = self._opp_leader_id(state, opp_idx)
        belief = get_default().predict(lid, state, opp_idx) if lid else {}
        shifted = (best_idx != dep_idx)
        self.shift_log.append({
            "turn": state.turn_number,
            "shifted": shifted,
            "base_kind": self._action_kind(dep),
            "chosen_kind": self._action_kind(chosen),
            "n_cands": n_cands,
            "true": true_ind,
            "belief": {f: round(float(belief.get(f, 0.0)), 3) for f in FEATURES},
            # 具体 snapshot (case study 用)
            "me_life": len(getattr(me, "life", []) or []),
            "opp_life": len(getattr(opp, "life", []) or []),
            "me_don": (int(getattr(me, "don_active", 0) or 0), int(getattr(me, "don_rested", 0) or 0)),
            "me_hand": [self._cname(c) for c in getattr(me, "hand", [])],
            "me_board": [self._cname(getattr(c, "card", c)) for c in getattr(me, "characters", [])],
            "opp_board": [self._cname(getattr(c, "card", c)) for c in getattr(opp, "characters", [])],
            "opp_TRUE_hand": [self._cname(c) for c in getattr(opp, "hand", [])],
            "base_move": self._describe_action(state, dep, me_idx),
            "chosen_move": self._describe_action(state, chosen, me_idx),
        })
