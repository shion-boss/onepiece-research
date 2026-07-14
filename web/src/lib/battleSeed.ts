// 陣取りダッシュボードの seed 統計 (見た目プロト用、 決定的)。
// 実データ (人間 vs AI のリーダー別勝敗) 配線までのプレースホルダ。
export type LeaderRef = { id: string; name: string };
export type Period = "all" | "month";

function hash(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

// 決定的な seed 対戦数 + 人間勝率。 key は "all" / "month" / "2026-06" 等 (月別履歴用)。
// 対戦数は long-tail (少数の人気 + 多数の過疎)。 人間勝率は高めに歪める (= 現状 AI が弱い設定)。
export function seedStat(id: string, key: string): { matches: number; win: number } {
  const h = hash(id + ":" + key);
  const r = (h % 10000) / 10000; // 0..1
  const cap = key === "all" ? 900 : 140;
  const matches = Math.floor(Math.pow(r, 3.2) * cap); // 立方で long-tail
  const r2 = (Math.floor(h / 7) % 10000) / 10000;
  const win = 0.42 + r2 * 0.53; // 0.42..0.95、 人間優位寄り
  return { matches, win };
}

export function totals(leaders: LeaderRef[], key: string): { games: number; winRate: number } {
  let g = 0;
  let hw = 0;
  for (const l of leaders) {
    const s = seedStat(l.id, key);
    g += s.matches;
    hw += s.matches * s.win;
  }
  return { games: g, winRate: g > 0 ? hw / g : 0 };
}
