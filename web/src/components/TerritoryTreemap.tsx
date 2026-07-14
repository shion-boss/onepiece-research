"use client";

import { useEffect, useRef, useState } from "react";
import { CardImage } from "./CardImage";

// 陣取りグリッド: カードは対戦数降順、 対戦数でサイズ可変 (人気=大)。 カード全体表示 (5:7 切抜なし)。
// justified レイアウト = 各行を横幅いっぱいに詰める (敷き詰め感)。 色 = 人間 vs AI 勝率。
export type TerritoryItem = {
  id: string;
  name: string;
  matches: number;
  win: number; // 人間勝率 0..1
  neutral: boolean;
};

const HUMAN = "#4ec9b0";
const AI = "#f14c4c";
const NEUTRAL = "#6a6a72";
const RATIO = 5 / 7; // カードの幅/高さ
const MIN_H = 78;
const MAX_H = 214;
const GAP = 4;

type Placed = TerritoryItem & { w: number; h: number };

function buildRows(items: TerritoryItem[], containerW: number): Placed[][] {
  if (containerW <= 0) return [];
  const sorted = [...items].sort((a, b) => b.matches - a.matches);
  const maxM = sorted[0]?.matches || 1;
  const desiredH = (m: number) => MIN_H + (MAX_H - MIN_H) * Math.sqrt(Math.max(0, m) / maxM);
  const rows: Placed[][] = [];
  let row: TerritoryItem[] = [];
  let rowH = 0;
  const flush = (fill: boolean) => {
    if (!row.length) return;
    const scale = fill ? (containerW - (row.length - 1) * GAP) / (row.length * rowH * RATIO) : 1;
    const h = rowH * scale;
    rows.push(row.map((it) => ({ ...it, h, w: h * RATIO })));
    row = [];
    rowH = 0;
  };
  for (const it of sorted) {
    if (!row.length) rowH = desiredH(it.matches); // 行高 = その行の先頭(=最大)カード
    row.push(it);
    const natW = row.length * rowH * RATIO + (row.length - 1) * GAP;
    if (natW >= containerW) flush(true); // 横幅を満たしたら justify して確定
  }
  flush(false); // 最終行は upscale しない
  return rows;
}

export function TerritoryTreemap({ items }: { items: TerritoryItem[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const shown = items.filter((it) => it.matches > 0);
  const rows = buildRows(shown, width);

  return (
    <div ref={ref} className="w-full">
      {shown.length === 0 ? (
        <div className="flex h-40 items-center justify-center text-sm text-[color:var(--text-muted)]">
          まだ対戦データがありません
        </div>
      ) : (
        <div className="flex flex-col" style={{ gap: GAP }}>
          {rows.map((row, ri) => (
            <div key={ri} className="flex" style={{ gap: GAP }}>
              {row.map((it) => (
                <Tile key={it.id} it={it} />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Tile({ it }: { it: Placed }) {
  const lead = it.win >= 0.5;
  const territory = it.neutral ? NEUTRAL : lead ? HUMAN : AI;
  const showText = it.w >= 92;
  return (
    <div
      style={{ width: it.w, height: it.h }}
      className="relative shrink-0 overflow-hidden rounded"
      title={`${it.name} ・ ${it.matches}戦 ・ 人間 ${Math.round(it.win * 100)}%`}
    >
      <CardImage cardId={it.id} alt={it.name} className="block h-full w-full object-cover" />
      <div className="pointer-events-none absolute inset-0" style={{ boxShadow: `inset 0 0 0 2px ${territory}` }} />
      <div className="pointer-events-none absolute inset-0" style={{ background: territory, opacity: it.neutral ? 0.4 : 0.12 + Math.abs(it.win - 0.5) * 0.5 }} />
      {!it.neutral && (
        <div className="absolute inset-x-0 bottom-0 flex h-1.5">
          <div style={{ width: `${it.win * 100}%`, background: HUMAN }} />
          <div style={{ flex: 1, background: AI }} />
        </div>
      )}
      {showText && (
        <>
          <div className="absolute left-1 top-1 rounded px-1 text-[10px] font-bold text-white" style={{ background: "rgba(0,0,0,0.55)" }}>
            {it.neutral ? "未開拓" : `人間 ${Math.round(it.win * 100)}%`}
          </div>
          <div className="absolute inset-x-0 bottom-1.5 truncate bg-black/45 px-1 text-center text-[10px] font-medium text-white">
            {it.name}・{it.matches}戦
          </div>
        </>
      )}
    </div>
  );
}
