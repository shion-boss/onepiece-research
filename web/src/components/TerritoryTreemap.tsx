"use client";

import { CardImage } from "./CardImage";

// 陣取りグリッド: カードは対戦数降順に並べ、 対戦数でサイズを変える (人気=大)。
// カード全体を表示 (5:7 のまま切り抜かない)。 色 = 人間 vs AI 勝率。
export type TerritoryItem = {
  id: string; // 表示画像の card_id (= 最後に戦った人の柄。 seed では base id)
  name: string;
  matches: number;
  win: number; // 人間勝率 0..1
  neutral: boolean; // 低データ (未開拓)
};

const HUMAN = "#4ec9b0";
const AI = "#f14c4c";
const NEUTRAL = "#6a6a72";
const MIN_W = 66;
const MAX_W = 208;

export function TerritoryTreemap({ items }: { items: TerritoryItem[] }) {
  const shown = items.filter((it) => it.matches > 0).sort((a, b) => b.matches - a.matches);
  if (shown.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-[color:var(--text-muted)]">
        まだ対戦データがありません
      </div>
    );
  }
  const maxMatches = shown[0].matches;
  return (
    <div className="flex flex-wrap items-end justify-center gap-2 p-1">
      {shown.map((it) => {
        const w = Math.round(MIN_W + (MAX_W - MIN_W) * Math.sqrt(it.matches / maxMatches));
        const lead = it.win >= 0.5;
        const territory = it.neutral ? NEUTRAL : lead ? HUMAN : AI;
        const showText = w >= 96;
        return (
          <div key={it.id} style={{ width: w }} className="flex flex-col gap-0.5" title={`${it.name} ・ ${it.matches}戦 ・ 人間 ${Math.round(it.win * 100)}%`}>
            <div className="relative overflow-hidden rounded" style={{ boxShadow: `0 0 0 2px ${territory}` }}>
              <CardImage cardId={it.id} alt={it.name} className="block w-full rounded object-cover" style={{ aspectRatio: "5 / 7" }} />
              {/* territory tint (勝ってる側の色、 差が大きいほど濃い) */}
              <div className="pointer-events-none absolute inset-0" style={{ background: territory, opacity: it.neutral ? 0.4 : 0.14 + Math.abs(it.win - 0.5) * 0.5 }} />
              {/* 勝率バー (下端: 人間色の割合 = 人間勝率) */}
              {!it.neutral && (
                <div className="absolute inset-x-0 bottom-0 flex h-1.5">
                  <div style={{ width: `${it.win * 100}%`, background: HUMAN }} />
                  <div style={{ flex: 1, background: AI }} />
                </div>
              )}
              {showText && (
                <div className="absolute left-1 top-1 rounded px-1 text-[10px] font-bold text-white" style={{ background: "rgba(0,0,0,0.55)" }}>
                  {it.neutral ? "未開拓" : `人間 ${Math.round(it.win * 100)}%`}
                </div>
              )}
            </div>
            {showText && (
              <div className="truncate text-center text-[10px] leading-tight text-[color:var(--text-muted)]">
                {it.name}・{it.matches}戦
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
