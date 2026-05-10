import type { StateSnapshot, PlayerSnapshot } from "./types";

/**
 * 盤面評価ユーティリティ。
 * engine/ai.py の LookaheadAI._evaluate と同じ重みで盤面スコアを算出する。
 *
 * 出力:
 *   - selfScore / oppScore: 各プレイヤーの加重スコア
 *   - diff: selfScore - oppScore (>0 で self 有利)
 *   - breakdown: 内訳 (life / field_count / field_power / hand / don)
 */

// LookaheadAI と一致させる重み (engine/ai.py) + UI 拡張指標。
// 拡張 4 指標は UI のみで使用 (Python AI の評価は変えない)。
export const BOARD_EVAL_WEIGHTS = {
  W_LIFE: 1500,
  W_FIELD_COUNT: 1200,
  W_FIELD_POWER: 1,
  W_HAND: 250,
  W_DON: 200,
  // 拡張指標
  W_BLOCKER: 800, // ブロッカー 1 体 ≒ 1 ライフ相当の防御力
  W_ATTACHED_DON: 400, // 付与済 DON は攻撃打点に直結 (戻すまでテンポ拘束)
  W_ACTIVE_CHARA: 600, // 次ターンの攻撃手数
  W_LETHAL: 5000, // リーサル兆候は決定的
};

export type BoardMetric = {
  self: number;
  opp: number;
  diff: number; // self - opp
  contribution: number; // 重み * diff (= 最終スコアへの寄与)
};

export type BoardEval = {
  selfScore: number;
  oppScore: number;
  diff: number; // selfScore - oppScore
  // 有利度 (-1.0 〜 +1.0): 視覚化ゲージ用に正規化。
  // 大きい絶対値で「圧倒的有利/劣勢」、 0 付近で互角。
  // tanh(diff / 5000) でスケール。 ±5000 程度で約 ±0.76、 ±10000 で ±0.96。
  normalized: number;
  breakdown: {
    life: BoardMetric;
    fieldCount: BoardMetric;
    fieldPower: BoardMetric;
    hand: BoardMetric;
    don: BoardMetric;
    // 拡張指標 (UI のみ)
    blocker: BoardMetric;
    attachedDon: BoardMetric;
    activeChara: BoardMetric;
    lethal: BoardMetric;
  };
};

function rawScore(p: PlayerSnapshot): {
  life: number;
  fieldCount: number;
  fieldPower: number;
  hand: number;
  don: number;
  blocker: number;
  attachedDon: number;
  activeChara: number;
} {
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
 * リーサル可能性を 0.0〜1.0 で見積。
 * self の「次ターン総打点」(leader + active chars) と opp の「総防御力」
 * (life × 5000 + hand × 1500) を比較し、 sigmoid でスケール。
 *
 * 簡略: power 合計 - opp.leader.power × ヒット数 (= 攻撃回数)。
 * 攻撃回数 = 自リーダー (rested でない) + active chars。
 */
function lethalEstimate(
  self: PlayerSnapshot,
  opp: PlayerSnapshot,
): number {
  const attackers: number[] = [];
  if (!self.leader.rested) attackers.push(self.leader.power);
  for (const c of self.characters) {
    if (!c.rested && !c.summoning_sickness) attackers.push(c.power);
  }
  if (attackers.length === 0) return 0;
  const oppLeaderP = opp.leader.power;
  // 各 attacker の超過打点 (= leader.power 超過分)
  const excesses = attackers.map((p) => Math.max(0, p - oppLeaderP));
  const totalExcess = excesses.reduce((s, x) => s + x, 0);
  // 相手の防御リソース推定: ライフ × 5000 (= 1 ライフ削るのにそれだけのパワー要)
  // + 手札 × 1500 (= 平均カウンター)
  const oppDefense = opp.life_count * 5000 + opp.hand_count * 1500;
  if (oppDefense === 0) return 1.0; // 防御力ゼロ = 確実勝利
  // 比率 (= 攻撃力 / 防御力) を sigmoid で 0-1 へ
  const ratio = totalExcess / oppDefense;
  // ratio=0.5 → 0.27、 ratio=1.0 → 0.5、 ratio=2.0 → 0.73
  return 1 / (1 + Math.exp(-2 * (ratio - 1)));
}

function metric(self: number, opp: number, weight: number): BoardMetric {
  const diff = self - opp;
  return { self, opp, diff, contribution: diff * weight };
}

export function computeBoardEval(
  snap: StateSnapshot,
  selfIdx: 0 | 1,
  oppIdx: 0 | 1,
): BoardEval {
  const me = snap.players[selfIdx];
  const op = snap.players[oppIdx];
  const sm = rawScore(me);
  const om = rawScore(op);
  const W = BOARD_EVAL_WEIGHTS;

  // リーサル兆候 (双方 0.0-1.0)。 self が高いほど勝利接近、 opp が高いほど自分が負ける接近。
  const selfLethal = lethalEstimate(me, op);
  const oppLethal = lethalEstimate(op, me);

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
  };

  const sumOf = (b: typeof breakdown, side: "self" | "opp") =>
    Object.values(b).reduce(
      (s, m) => s + (side === "self" ? m.self : m.opp) * 0,
      0,
    );
  // 上記 sumOf は型のための dummy。 実際は重み付け合計を直接計算:
  void sumOf;
  const selfScore =
    sm.life * W.W_LIFE +
    sm.fieldCount * W.W_FIELD_COUNT +
    sm.fieldPower * W.W_FIELD_POWER +
    sm.hand * W.W_HAND +
    sm.don * W.W_DON +
    sm.blocker * W.W_BLOCKER +
    sm.attachedDon * W.W_ATTACHED_DON +
    sm.activeChara * W.W_ACTIVE_CHARA +
    selfLethal * W.W_LETHAL;
  const oppScore =
    om.life * W.W_LIFE +
    om.fieldCount * W.W_FIELD_COUNT +
    om.fieldPower * W.W_FIELD_POWER +
    om.hand * W.W_HAND +
    om.don * W.W_DON +
    om.blocker * W.W_BLOCKER +
    om.attachedDon * W.W_ATTACHED_DON +
    om.activeChara * W.W_ACTIVE_CHARA +
    oppLethal * W.W_LETHAL;
  const diff = selfScore - oppScore;
  const normalized = Math.tanh(diff / 5000);

  return { selfScore, oppScore, diff, normalized, breakdown };
}

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
