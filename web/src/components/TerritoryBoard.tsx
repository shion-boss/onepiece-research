"use client";

import { memo, useCallback, useMemo, useState } from "react";
import { CardImage } from "./CardImage";

// 陣取り盤: 1024 マス (32×32)。 各マスは占領者(人間)の推しリーダーの色。 空きマスは中立。
// ホバーでリーダーが分かる / クリックで対象マス選択 → そのマスに挑戦 (占領マス=占領者デッキの AI、
// 空きマス=ランダム AI)。 勝てば占領、 負けても何も起きない。
export type BoardLeader = { id: string; name: string; color: string };

const N = 1024;
const COLS = 32;
const COLOR_HEX: Record<string, string> = {
  赤: "#f14c4c", 青: "#3794ff", 緑: "#4ec9b0", 紫: "#c586c0", 黒: "#6a6a72", 黄: "#cca700",
};
const EMPTY = "#26262b";

// block: n×n 正方形ブロックの一部で、 このセルはブロック内 (r,c)。 n>=2 の時だけ画像を分割表示。
type Cell = { owner: BoardLeader | null; ownerName: string | null; color: string; block: { n: number; r: number; c: number } | null };

function hash(n: number): number {
  let h = (n ^ 0x9e3779b9) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
  return (h ^ (h >>> 16)) >>> 0;
}

// 盤を正方形ブロックで敷き詰める (1×1 / 2×2 / 3×3 / 4×4)。 占領ブロック(n>=2)はカード上部を
// n×n に分割して 1 枚の画像として表示。 1×1 と空きは色のみ。
function seedCells(leaders: BoardLeader[]): Cell[] {
  const cells: (Cell | null)[] = new Array(N).fill(null);
  if (leaders.length === 0) return cells.map(() => ({ owner: null, ownerName: null, color: EMPTY, block: null }));

  const free = (x: number, y: number, n: number): boolean => {
    if (x + n > COLS || y + n > COLS) return false;
    for (let dy = 0; dy < n; dy++) for (let dx = 0; dx < n; dx++) if (cells[(y + dy) * COLS + (x + dx)] !== null) return false;
    return true;
  };
  const pickN = (h: number): number => {
    const r = h % 100;
    return r < 50 ? 1 : r < 78 ? 2 : r < 93 ? 3 : 4;
  };

  for (let y = 0; y < COLS; y++) {
    for (let x = 0; x < COLS; x++) {
      const idx = y * COLS + x;
      if (cells[idx] !== null) continue;
      const h = hash(idx);
      let n = pickN(h);
      while (n > 1 && !free(x, y, n)) n--;
      const owned = hash(idx * 2 + 7) % 100 < 55;
      const ld = owned ? leaders[hash(idx * 3 + 13) % leaders.length] : null;
      const ownerName = owned ? `プレイヤー${(hash(idx * 5 + 1) % 9000) + 1000}` : null;
      const color = ld ? COLOR_HEX[ld.color] ?? "#888" : EMPTY;
      const useImg = !!ld && n >= 2;
      for (let dy = 0; dy < n; dy++) {
        for (let dx = 0; dx < n; dx++) {
          cells[(y + dy) * COLS + (x + dx)] = {
            owner: ld,
            ownerName,
            color,
            block: useImg ? { n, r: dy, c: dx } : null,
          };
        }
      }
    }
  }
  return cells.map((c) => c ?? { owner: null, ownerName: null, color: EMPTY, block: null });
}

export function TerritoryBoard({ leaders }: { leaders: BoardLeader[] }) {
  const cells = useMemo(() => seedCells(leaders), [leaders]);
  const [hovered, setHovered] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  const onEnter = useCallback((i: number) => setHovered(i), []);
  const onClick = useCallback((i: number) => setSelected(i), []);
  const onLeave = useCallback(() => setHovered(null), []);

  const activeIdx = hovered ?? selected;
  const active = activeIdx != null ? cells[activeIdx] : null;
  const occupied = useMemo(() => cells.filter((c) => c.owner).length, [cells]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-6">
      <header className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-6" style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}>
        <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">推しリーダー陣取り</h1>
        <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">
          1024 マスを推しリーダーで奪い合う。AI に勝てば 1 マス占領。占領マスに挑むと、その占領者のデッキを操る AI が防衛する。
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-[color:var(--text-muted)]">占領 <span className="font-bold text-[color:var(--text-strong)]">{occupied}</span> / 空き <span className="font-bold text-[color:var(--text-strong)]">{N - occupied}</span></span>
        <span className="ml-auto text-xs text-[color:var(--text-muted)]">マスにホバーでリーダー表示 ・ クリックで挑戦対象を選択（※対戦連携は次段）</span>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1 rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
          <Grid cells={cells} selected={selected} onEnter={onEnter} onClick={onClick} onLeave={onLeave} />
        </div>
        <PreviewPanel cell={active} idx={activeIdx} selected={selected} />
      </div>
    </div>
  );
}

const Grid = memo(function Grid({
  cells,
  selected,
  onEnter,
  onClick,
  onLeave,
}: {
  cells: Cell[];
  selected: number | null;
  onEnter: (i: number) => void;
  onClick: (i: number) => void;
  onLeave: () => void;
}) {
  return (
    <div
      onMouseLeave={onLeave}
      style={{ display: "grid", gridTemplateColumns: `repeat(${COLS}, 1fr)`, gap: 2 }}
    >
      {cells.map((c, i) => (
        <button
          key={i}
          type="button"
          onMouseEnter={() => onEnter(i)}
          onClick={() => onClick(i)}
          title={c.owner ? `${c.owner.name}（${c.ownerName}）` : "空きマス"}
          className="relative aspect-square overflow-hidden rounded-[1px] transition-[filter] hover:brightness-125"
          style={{ background: c.color, outline: selected === i ? "2px solid #fff" : undefined, outlineOffset: selected === i ? -1 : undefined, zIndex: selected === i ? 10 : undefined }}
        >
          {c.owner && c.block && (
            // ブロック (n×n) でカード上部を分割し、 このセルは (r,c) の画像片を表示。
            <img
              src={`/cards/${c.owner.id}.png`}
              alt=""
              loading="lazy"
              decoding="async"
              draggable={false}
              style={{
                position: "absolute",
                width: `${c.block.n * 100}%`,
                height: "auto",
                maxWidth: "none",
                left: `${-c.block.c * 100}%`,
                top: `${-c.block.r * 100}%`,
              }}
            />
          )}
        </button>
      ))}
    </div>
  );
});

function PreviewPanel({ cell, idx, selected }: { cell: Cell | null; idx: number | null; selected: number | null }) {
  return (
    <div className="w-full shrink-0 self-start rounded-[var(--radius)] border p-4 lg:w-64" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
      {idx == null ? (
        <div className="py-8 text-center text-sm text-[color:var(--text-muted)]">マスにホバー / クリックで詳細</div>
      ) : cell?.owner ? (
        <div className="flex flex-col items-center gap-2">
          <div className="text-[11px] uppercase tracking-wider text-[color:var(--text-muted)]">占領マス #{idx + 1}</div>
          <CardImage cardId={cell.owner.id} alt={cell.owner.name} className="h-40 w-auto rounded-[var(--radius)] border border-[color:var(--border-1)] object-cover" />
          <div className="text-center">
            <div className="text-sm font-semibold text-[color:var(--text-strong)]">{cell.owner.name}</div>
            <div className="text-xs text-[color:var(--text-muted)]">占領者: {cell.ownerName}</div>
          </div>
          <button type="button" disabled={selected !== idx} className="mt-1 w-full rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" title="対戦連携は次段で実装">
            {selected === idx ? "このマスに挑戦（防衛戦）" : "クリックで選択"}
          </button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <div className="text-[11px] uppercase tracking-wider text-[color:var(--text-muted)]">空きマス #{idx + 1}</div>
          <div className="flex h-40 w-[110px] items-center justify-center rounded-[var(--radius)] border border-dashed text-xs text-[color:var(--text-muted)]" style={{ borderColor: "var(--border-2)" }}>
            未占領
          </div>
          <button type="button" disabled={selected !== idx} className="mt-1 w-full rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" title="対戦連携は次段で実装">
            {selected === idx ? "このマスに挑戦（ランダムAI）" : "クリックで選択"}
          </button>
        </div>
      )}
    </div>
  );
}
