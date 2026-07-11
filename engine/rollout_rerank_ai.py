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
                 ro_hand_predict: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._ro_cand = ro_cand
        self._ro_n = ro_n
        self._ro_opp_slug = ro_opp_slug
        self._ro_turn_cap = ro_turn_cap
        self._ro_determinize = ro_determinize
        # 手札予測器の accuracy 代理: 各相手カードを確率 p で真の位置(hand/deck)に固定、
        # 残りを一様 redeal。 p=0=一様(予測無し)、 p=1=full-info(完全予測)。 天井曲線の測定用。
        self._ro_reveal_p = ro_reveal_p
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

    def _rollout_winrate(self, base, cand_idx: int, me_idx: int, seed: int) -> float:
        b = fast_clone(base)
        if self._ro_determinize:
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
        best_idx, best_w = (dep_idx if dep_idx is not None else cands[0]), -1.0
        for ci in cands:
            w = 0.0
            for si in range(self._ro_n):
                seed = self._ro_seq * 100003 + ci * 131 + si * 17
                w += self._rollout_winrate(state, ci, me_idx, seed)
            w /= self._ro_n
            if w > best_w:
                best_w, best_idx = w, ci
        # 再計算した legal_actions は同順(MAIN は自 hand/board 依存)なので index で返す
        cur_acts = legal_actions(state)
        return self._track(cur_acts[best_idx] if best_idx < len(cur_acts) else dep)
