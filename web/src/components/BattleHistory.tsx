"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BoardGrid, seedCells, type BoardLeader } from "./TerritoryBoard";

// 月キー → seed salt (月ごとに盤が変わる)。
function monthSalt(key: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

// i=0 が最新 (進行中)。 そこから 1 ヶ月ずつ過去へ。 (プロト: 現在=2026/07 固定)
const BASE_IDX = 2026 * 12 + 6; // 2026年7月 (month-1=6)
const MAX_MONTHS = 120; // 無限スクロールの上限 (= 10 年)
function monthAt(i: number): { key: string; label: string; current: boolean } {
  const idx = BASE_IDX - i;
  const year = Math.floor(idx / 12);
  const month = (idx % 12) + 1;
  const mm = String(month).padStart(2, "0");
  return { key: `${year}-${mm}`, label: `${year} / ${mm}`, current: i === 0 };
}

const NOOP = () => {};
const PAGE = 12;

export function BattleHistory({ leaders }: { leaders: BoardLeader[] }) {
  const [count, setCount] = useState(PAGE);
  const [sel, setSel] = useState(monthAt(1).key); // 既定 = 直近の完了月

  const months = useMemo(() => Array.from({ length: Math.min(count, MAX_MONTHS) }, (_, i) => monthAt(i)), [count]);
  const selInfo = useMemo(() => months.find((m) => m.key === sel) ?? monthAt(1), [months, sel]);
  const cells = useMemo(() => seedCells(leaders, monthSalt(sel)), [leaders, sel]);
  const occupied = useMemo(() => cells.filter((c) => c.owner).length, [cells]);

  // 無限スクロール: sentinel が見えたら 12 ヶ月追加。
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) setCount((c) => Math.min(c + PAGE, MAX_MONTHS));
      },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左メニュー: 月を縦に (上=最新) + 無限スクロール */}
      <aside className="log-scroll w-32 shrink-0 overflow-auto border-r py-2" style={{ borderColor: "var(--border-1)" }}>
        <div className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--text-muted)]">戦いの歴史</div>
        {months.map((m) => {
          const on = m.key === sel;
          return (
            <button
              key={m.key}
              type="button"
              onClick={() => setSel(m.key)}
              className="flex w-full items-center gap-1.5 border-l-2 px-3 py-2 text-left text-[13px] transition-colors"
              style={{
                borderLeftColor: on ? "var(--brand)" : "transparent",
                background: on ? "var(--list-hover)" : "transparent",
                color: on ? "var(--text-strong)" : "var(--text-default)",
              }}
            >
              {m.label}
              {m.current && <span className="rounded bg-[color:var(--brand)] px-1 text-[8px] text-white">進行中</span>}
            </button>
          );
        })}
        {count < MAX_MONTHS && <div ref={sentinelRef} className="h-6" aria-hidden />}
      </aside>

      {/* 右: 選択月の最終陣地 */}
      <main className="min-w-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-6">
          <header className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-5" style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}>
            <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">
              {selInfo.label} の最終陣地{selInfo.current && "（進行中）"}
            </h1>
            <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">
              その月末に凍結した陣取りの状態。占領 {occupied} / 空き {1024 - occupied}（※現在はサンプルデータ）
            </p>
          </header>
          <div className="rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
            <BoardGrid cells={cells} selected={null} onEnter={NOOP} onClick={NOOP} onLeave={NOOP} />
          </div>
        </div>
      </main>
    </div>
  );
}
