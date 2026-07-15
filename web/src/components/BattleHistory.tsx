"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BoardGrid, seedCells, type BoardLeader } from "./TerritoryBoard";
import { CellPanel } from "./CellHistoryPanel";
import { useResizable } from "@/lib/useResizable";
import { ResizeHandle } from "./ResizeHandle";

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
const BASE_IDX = 2026 * 12 + 6;
const MAX_MONTHS = 120;
function monthAt(i: number): { key: string; label: string; current: boolean } {
  const idx = BASE_IDX - i;
  const year = Math.floor(idx / 12);
  const month = (idx % 12) + 1;
  const mm = String(month).padStart(2, "0");
  return { key: `${year}-${mm}`, label: `${year} / ${mm}`, current: i === 0 };
}

const PAGE = 12;

export function BattleHistory({ leaders }: { leaders: BoardLeader[] }) {
  const [count, setCount] = useState(PAGE);
  const [sel, setSel] = useState(monthAt(1).key);
  const [selected, setSelected] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [hoverEnabled, setHoverEnabled] = useState(false); // 既定=ホバー切替なし

  // 今月(進行中)は歴史に含めない → i=1 (先月) から過去へ。
  const months = useMemo(() => Array.from({ length: Math.min(count, MAX_MONTHS) }, (_, i) => monthAt(i + 1)), [count]);
  const selInfo = useMemo(() => months.find((m) => m.key === sel) ?? monthAt(1), [months, sel]);
  const cells = useMemo(() => seedCells(leaders, monthSalt(sel)), [leaders, sel]);
  const occupied = useMemo(() => cells.filter((c) => c.owner).length, [cells]);

  // クリックで固定 (再クリックで解除)。 固定中はホバー無視。 ホバー切替は toggle ON かつ未固定時のみ。
  const onClick = useCallback((i: number) => setSelected((p) => (p === i ? null : i)), []);
  const onEnter = useCallback((i: number) => setHovered(i), []);
  const NOOP = useCallback(() => {}, []);
  const activeIdx = selected != null ? selected : hoverEnabled ? hovered : null;
  const active = activeIdx != null ? cells[activeIdx] : null;

  // 列幅ドラッグリサイズ (左=月メニュー / 右=履歴パネル)。 左は初期幅より狭くできない。
  const left = useResizable(128, 128, 300);
  const right = useResizable(288, 240, 560, true);

  // 月切替で選択/ホバーをクリア (盤が変わるため)。
  useEffect(() => {
    setSelected(null);
    setHovered(null);
  }, [sel]);

  // 無限スクロール: sentinel が見えたら 12 ヶ月追加 (aside 内でスクロール)。
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const asideRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) setCount((c) => Math.min(c + PAGE, MAX_MONTHS));
      },
      { root: asideRef.current, rootMargin: "120px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [count]);

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* 左: 月メニュー (高さ制限 + 内部無限スクロール、 上=最新) */}
      <aside ref={asideRef} className="log-scroll shrink-0 overflow-y-auto py-2" style={{ width: left.width }}>
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
            </button>
          );
        })}
        {count < MAX_MONTHS && <div ref={sentinelRef} className="h-6" aria-hidden />}
      </aside>

      <ResizeHandle onMouseDown={left.onMouseDown} />

      {/* 中央: 選択月の最終陣地 */}
      <main className="log-scroll min-w-0 flex-1 overflow-y-auto border-l" style={{ borderColor: "var(--border-1)" }}>
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
          <header className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-5" style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}>
            <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">
              {selInfo.label} の最終陣地
            </h1>
            <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">
              その月末に凍結した陣取りの状態。占領 {occupied} / 空き {1024 - occupied}。マスをクリックで戦いの履歴を表示（再クリックで解除）
            </p>
          </header>
          <div className="rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
            <BoardGrid cells={cells} selected={selected} onEnter={onEnter} onClick={onClick} onLeave={NOOP} />
          </div>
        </div>
      </main>

      {/* 右: 選択マスの詳細 (固定ヘッダー + トグル、 左端ハンドルでリサイズ) */}
      <ResizeHandle onMouseDown={right.onMouseDown} />
      <div className="log-scroll shrink-0 overflow-y-auto border-l" style={{ width: right.width, borderColor: "var(--border-1)" }}>
        <CellPanel cell={active} idx={activeIdx} leaders={leaders} hoverEnabled={hoverEnabled} onToggleHover={() => setHoverEnabled((v) => !v)} />
      </div>
    </div>
  );
}
