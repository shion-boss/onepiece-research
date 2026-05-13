import type { StateSnapshot, PlayerSnapshot } from "./types";

/**
 * 盤面評価ユーティリティ。 engine/eval.py compute_breakdown と同一の 14 指標を計算。
 *
 * 14 指標 = 基本 9 (life / field_count / field_power / hand / don / blocker /
 * attached_don / active_chara / lethal) + Phase 1 (next_turn_lethal /
 * deck_finisher / life_trigger) + Phase 2 (chara_quality / hand_quality)。
 *
 * snapshot から計算可能な範囲:
 *  - 10 指標: 基本 9 + nextTurnLethal (= snapshot から完全に計算可能)
 *  - chara_quality / hand_quality: card role db (Map<card_id, role>) が必要。
 *    `useCardRoleDb()` から取得して props で渡す。 db 未取得時は 0 で degrade。
 *  - life_trigger / deck_finisher: snapshot に life/deck の card_id が無いため
 *    計算不可。 snap.board_eval (= server 計算の真値) から逆算する形で contribution
 *    のみ表示、 self/opp の生値は表示不可。
 *
 * 出力:
 *   - selfScore / oppScore: 各プレイヤーの加重スコア (= breakdown の sum)
 *   - diff: snap.board_eval があれば server 値、 無ければ selfScore - oppScore
 *   - breakdown: 14 指標の内訳
 */

import { getCardRoleSync } from "./cardRoleDb";

// engine/eval.py BoardEvalWeights と同期。
export const BOARD_EVAL_WEIGHTS = {
  W_LIFE: 1500,
  W_FIELD_COUNT: 1200,
  W_FIELD_POWER: 1,
  W_HAND: 250,
  W_DON: 200,
  W_BLOCKER: 800,
  W_ATTACHED_DON: 400,
  W_ACTIVE_CHARA: 600,
  W_LETHAL: 5000,
  // Phase 1 (R68): 被リーサル / デッキ残 / トリガー期待
  W_OPP_NEXT_LETHAL: 4000,
  W_DECK_FINISHER: 150,
  W_LIFE_TRIGGER: 200,
  // Phase 2 (R69): role 別 個別価値
  W_CHARA_QUALITY: 400,
  W_HAND_QUALITY: 150,
};

// role 別 base 価値 (engine/eval.py _ROLE_VALUES と同期)
const ROLE_VALUES: Record<string, number> = {
  finisher: 3.0,
  removal: 2.5,
  negation: 2.5,
  blocker: 2.0,
  disruption: 2.0,
  recovery: 1.5,
  ramp: 1.5,
  draw: 1.5,
  search: 1.5,
  synergy: 1.0,
};

function roleValueOf(cardId: string, roleDb: Map<string, string> | null): number {
  if (!roleDb) return 0.5;
  const role = roleDb.get(cardId) ?? "";
  return ROLE_VALUES[role] ?? 0.5;
}

export type BoardMetric = {
  self: number;
  opp: number;
  diff: number; // self - opp
  contribution: number; // 重み * diff (= 最終スコアへの寄与)
};

export type BoardEval = {
  selfScore: number;
  oppScore: number;
  diff: number; // server snap.board_eval を優先、 無ければ self - opp
  // 有利度 (-1.0 〜 +1.0): tanh(diff / 5000) で正規化。
  normalized: number;
  // 14 指標の内訳。 lifeTrigger / deckFinisher は self/opp が unknown のため
  // 0 placeholder (= snapshot に life/deck card_id が無い限界)。
  breakdown: {
    life: BoardMetric;
    fieldCount: BoardMetric;
    fieldPower: BoardMetric;
    hand: BoardMetric;
    don: BoardMetric;
    blocker: BoardMetric;
    attachedDon: BoardMetric;
    activeChara: BoardMetric;
    lethal: BoardMetric;
    // Phase 1
    nextTurnLethal: BoardMetric;
    deckFinisher: BoardMetric; // server-only
    lifeTrigger: BoardMetric;  // server-only
    // Phase 2
    charaQuality: BoardMetric;
    handQuality: BoardMetric;
  };
};

function rawScore(p: PlayerSnapshot) {
  const blocker = p.characters.filter((c) =>
    c.keywords.includes("ブロッカー"),
  ).length;
  const attachedDon =
    p.leader.attached_dons +
    p.characters.reduce((s, c) => s + c.attached_dons, 0) +
    p.stages.reduce((s, c) => s + c.attached_dons, 0);
  const activeChara = p.characters.filter(
    (c) => !c.rested && !c.summoning_sickness,
  ).length;
  return {
    life: p.life_count,
    fieldCount: p.characters.length,
    fieldPower: p.characters.reduce((s, c) => s + c.power, 0),
    hand: p.hand_count,
    don: p.don_total,
    blocker,
    attachedDon,
    activeChara,
  };
}

/**
 * リーサル可能性 (現ターン視点)。 active chars + leader の総打点 vs opp 防御。
 * engine/eval.py lethal_estimate と同一公式。
 */
function lethalEstimate(self: PlayerSnapshot, opp: PlayerSnapshot): number {
  const attackers: number[] = [];
  if (!self.leader.rested) attackers.push(self.leader.power);
  for (const c of self.characters) {
    if (!c.rested && !c.summoning_sickness) attackers.push(c.power);
  }
  if (attackers.length === 0) return 0;
  const oppLeaderP = opp.leader.power;
  const excesses = attackers.map((p) => Math.max(0, p - oppLeaderP));
  const totalExcess = excesses.reduce((s, x) => s + x, 0);
  const oppDefense = opp.life_count * 5000 + opp.hand_count * 1500;
  if (oppDefense === 0) return 1.0;
  const ratio = totalExcess / oppDefense;
  return 1 / (1 + Math.exp(-2 * (ratio - 1)));
}

/**
 * 次ターン REFRESH 後の lethal 見積。 全 chara が active な状態を仮定。
 * engine/eval.py project_opp_next_turn_lethal と同等。
 *
 * self が「次ターン全 chara で攻撃すると opp を仕留めるか」 を返す。
 * cannot_attack_static などのキーワード判定は snapshot に flag が無いため省略 (= 簡略)。
 */
function projectForwardLethal(self: PlayerSnapshot, opp: PlayerSnapshot): number {
  const attackers: number[] = [self.leader.power];
  for (const c of self.characters) {
    attackers.push(c.power);
  }
  const oppLeaderP = opp.leader.power;
  const excesses = attackers.map((p) => Math.max(0, p - oppLeaderP));
  const totalExcess = excesses.reduce((s, x) => s + x, 0);
  const oppDefense = opp.life_count * 5000 + opp.hand_count * 1500;
  if (oppDefense === 0) return 1.0;
  const ratio = totalExcess / oppDefense;
  return 1 / (1 + Math.exp(-2 * (ratio - 1)));
}

/**
 * 場のキャラの role 別合計価値。 engine/eval.py chara_quality_score と同等。
 * roleDb が null の場合は 0 (= graceful degradation、 メトリックは 0 になる)。
 */
function charaQualityScore(
  p: PlayerSnapshot,
  roleDb: Map<string, string> | null,
): number {
  if (!roleDb) return 0;
  let total = 0;
  for (const ip of p.characters) {
    total += roleValueOf(ip.card_id, roleDb);
  }
  return total;
}

/**
 * 手札の role 別合計価値。 engine/eval.py hand_quality_score と同等。
 * snapshot.hand は card_id 配列 (= player.hand が public な計算用に保存されている)。
 */
function handQualityScore(
  p: PlayerSnapshot,
  roleDb: Map<string, string> | null,
): number {
  if (!roleDb) return 0;
  let total = 0;
  for (const cid of p.hand) {
    total += roleValueOf(cid, roleDb);
  }
  return total;
}

function metric(self: number, opp: number, weight: number): BoardMetric {
  const diff = self - opp;
  return { self, opp, diff, contribution: diff * weight };
}

export function computeBoardEval(
  snap: StateSnapshot,
  selfIdx: 0 | 1,
  oppIdx: 0 | 1,
  roleDb: Map<string, string> | null = null,
): BoardEval {
  const me = snap.players[selfIdx];
  const op = snap.players[oppIdx];
  const sm = rawScore(me);
  const om = rawScore(op);
  const W = BOARD_EVAL_WEIGHTS;

  const selfLethal = lethalEstimate(me, op);
  const oppLethal = lethalEstimate(op, me);
  const meForwardLethal = projectForwardLethal(me, op);
  const oppForwardLethal = projectForwardLethal(op, me);
  const meCharaQ = charaQualityScore(me, roleDb);
  const opCharaQ = charaQualityScore(op, roleDb);
  const meHandQ = handQualityScore(me, roleDb);
  const opHandQ = handQualityScore(op, roleDb);

  // server-only metrics は snapshot から復元不可能。 0 で placeholder。
  const placeholderMetric: BoardMetric = {
    self: 0,
    opp: 0,
    diff: 0,
    contribution: 0,
  };

  const breakdown = {
    life: metric(sm.life, om.life, W.W_LIFE),
    fieldCount: metric(sm.fieldCount, om.fieldCount, W.W_FIELD_COUNT),
    fieldPower: metric(sm.fieldPower, om.fieldPower, W.W_FIELD_POWER),
    hand: metric(sm.hand, om.hand, W.W_HAND),
    don: metric(sm.don, om.don, W.W_DON),
    blocker: metric(sm.blocker, om.blocker, W.W_BLOCKER),
    attachedDon: metric(sm.attachedDon, om.attachedDon, W.W_ATTACHED_DON),
    activeChara: metric(sm.activeChara, om.activeChara, W.W_ACTIVE_CHARA),
    lethal: metric(selfLethal, oppLethal, W.W_LETHAL),
    nextTurnLethal: metric(meForwardLethal, oppForwardLethal, W.W_OPP_NEXT_LETHAL),
    deckFinisher: placeholderMetric,
    lifeTrigger: placeholderMetric,
    charaQuality: metric(meCharaQ, opCharaQ, W.W_CHARA_QUALITY),
    handQuality: metric(meHandQ, opHandQ, W.W_HAND_QUALITY),
  };

  // breakdown の sum (= 12 計算可能 metric の contribution、 placeholder 2 は 0)
  const computedSum = Object.values(breakdown).reduce(
    (s, m) => s + m.contribution,
    0,
  );

  // server 真値 (= snap.board_eval) を優先採用。 ただし turn_player_idx 視点
  // なので self 視点なら sign 反転が必要。
  // self_score = me 視点の合計、 opp_score は対称で生成。 diff のみ server 値を採用。
  const selfScore = Object.values(breakdown).reduce((s, m) => s + m.self * 0, 0);
  void selfScore;
  // 個別 score は breakdown から再計算 (= sum)
  const selfSum =
    sm.life * W.W_LIFE +
    sm.fieldCount * W.W_FIELD_COUNT +
    sm.fieldPower * W.W_FIELD_POWER +
    sm.hand * W.W_HAND +
    sm.don * W.W_DON +
    sm.blocker * W.W_BLOCKER +
    sm.attachedDon * W.W_ATTACHED_DON +
    sm.activeChara * W.W_ACTIVE_CHARA +
    selfLethal * W.W_LETHAL +
    meForwardLethal * W.W_OPP_NEXT_LETHAL +
    meCharaQ * W.W_CHARA_QUALITY +
    meHandQ * W.W_HAND_QUALITY;
  const oppSum =
    om.life * W.W_LIFE +
    om.fieldCount * W.W_FIELD_COUNT +
    om.fieldPower * W.W_FIELD_POWER +
    om.hand * W.W_HAND +
    om.don * W.W_DON +
    om.blocker * W.W_BLOCKER +
    om.attachedDon * W.W_ATTACHED_DON +
    om.activeChara * W.W_ACTIVE_CHARA +
    oppLethal * W.W_LETHAL +
    oppForwardLethal * W.W_OPP_NEXT_LETHAL +
    opCharaQ * W.W_CHARA_QUALITY +
    opHandQ * W.W_HAND_QUALITY;

  // diff: server の board_eval (= 14 指標真値) があれば優先。 turn_player 視点なので符号調整。
  let diff: number;
  if (typeof snap.board_eval === "number") {
    diff =
      snap.turn_player_idx === selfIdx ? snap.board_eval : -snap.board_eval;
  } else {
    diff = computedSum;
  }
  const normalized = Math.tanh(diff / 5000);

  return {
    selfScore: selfSum,
    oppScore: oppSum,
    diff,
    normalized,
    breakdown,
  };
}

// boardEval を直接使わなくても利用できる helper を再 export
export { useCardRoleDb, getCardRoleSync } from "./cardRoleDb";

/** 有利度ラベル (日本語)。 normalized -1.0 〜 +1.0 を 5 段階に区分。 */
export function evalLabel(normalized: number): string {
  if (normalized >= 0.6) return "圧倒的有利";
  if (normalized >= 0.25) return "有利";
  if (normalized >= -0.25) return "互角";
  if (normalized >= -0.6) return "劣勢";
  return "圧倒的劣勢";
}

/** 有利度に対応する色 (Tailwind クラス)。 */
export function evalColorClass(normalized: number): string {
  if (normalized >= 0.6) return "text-emerald-600 dark:text-emerald-400";
  if (normalized >= 0.25) return "text-lime-600 dark:text-lime-400";
  if (normalized >= -0.25) return "text-zinc-600 dark:text-zinc-400";
  if (normalized >= -0.6) return "text-orange-600 dark:text-orange-400";
  return "text-rose-600 dark:text-rose-400";
}
