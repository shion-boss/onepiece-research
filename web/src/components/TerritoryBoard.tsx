"use client";

import { memo, useCallback, useMemo, useState } from "react";
import { CellHistoryPanel } from "./CellHistoryPanel";
import { useResizable } from "@/lib/useResizable";
import { ResizeHandle } from "./ResizeHandle";

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

// 画像はカード上部の正方形にズーム (説明欄=下部を除外して大きく)。
const CARD_W = 5;
const CARD_H = 7;
const CROP_FRAC = 0.5; // カード高さの上から何割を正方形に使うか (0.5 = 上半分)
const CROP = CROP_FRAC * CARD_H; // 正方形の一辺 (card 単位)
const ZOOM = CARD_W / CROP; // 画像全幅 = L*ZOOM セル (大きく見せるズーム)
const HOFF = (CARD_W - CROP) / 2 / CROP; // 横方向センタリング量 (L 単位)

// block: w×h ブロックの一部で、 このセルはブロック内 (r,c)。 面積>=4 の占領のみ画像を分割表示。
export type Cell = { owner: BoardLeader | null; ownerName: string | null; color: string; block: { w: number; h: number; r: number; c: number } | null };

function hash(n: number): number {
  let h = (n ^ 0x9e3779b9) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
  return (h ^ (h >>> 16)) >>> 0;
}

// 盤を矩形ブロック (1..4 × 1..4) で敷き詰める。 占領で面積>=4 のブロックはカード上部の正方形を
// 「長い方に合わせて」配置し w×h に分割して 1 枚の画像に (縦は上詰め / 横は中央)。 それ以外は色のみ。
export function seedCells(leaders: BoardLeader[], salt = 0): Cell[] {
  const cells: (Cell | null)[] = new Array(N).fill(null);
  if (leaders.length === 0) return cells.map(() => ({ owner: null, ownerName: null, color: EMPTY, block: null }));

  const free = (x: number, y: number, w: number, h: number): boolean => {
    if (x + w > COLS || y + h > COLS) return false;
    for (let dy = 0; dy < h; dy++) for (let dx = 0; dx < w; dx++) if (cells[(y + dy) * COLS + (x + dx)] !== null) return false;
    return true;
  };
  const pickDim = (h: number): number => {
    const r = h % 100;
    return r < 48 ? 1 : r < 76 ? 2 : r < 92 ? 3 : 4;
  };

  for (let y = 0; y < COLS; y++) {
    for (let x = 0; x < COLS; x++) {
      const idx = y * COLS + x;
      if (cells[idx] !== null) continue;
      let w = pickDim(hash(idx + salt));
      let h = pickDim(hash(idx * 7 + 3 + salt));
      // 収まるまで長い方から縮める。
      while ((w > 1 || h > 1) && !free(x, y, w, h)) {
        if (w >= h && w > 1) w--;
        else if (h > 1) h--;
        else w--;
      }
      const owned = hash(idx * 2 + 7 + salt) % 100 < 55;
      const ld = owned ? leaders[hash(idx * 3 + 13 + salt) % leaders.length] : null;
      const ownerName = owned ? `プレイヤー${(hash(idx * 5 + 1 + salt) % 9000) + 1000}` : null;
      const color = ld ? COLOR_HEX[ld.color] ?? "#888" : EMPTY;
      const useImg = !!ld && w * h >= 4;
      for (let dy = 0; dy < h; dy++) {
        for (let dx = 0; dx < w; dx++) {
          cells[(y + dy) * COLS + (x + dx)] = {
            owner: ld,
            ownerName,
            color,
            block: useImg ? { w, h, r: dy, c: dx } : null,
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
  // クリックで固定 (再クリックで解除)。 固定中はホバーで切り替わらない → 観戦ボタンまで到達できる。
  const onClick = useCallback((i: number) => setSelected((p) => (p === i ? null : i)), []);
  const onLeave = useCallback(() => setHovered(null), []);

  const activeIdx = selected ?? hovered; // 固定中は selected を優先 (ホバー無視)
  const active = activeIdx != null ? cells[activeIdx] : null;
  const right = useResizable(288, 240, 560, true); // 右パネル幅ドラッグ
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
        <span className="ml-auto text-xs text-[color:var(--text-muted)]">ホバーで履歴表示 ・ クリックで固定（再クリックで解除）・ 固定中は観戦ボタンまで操作可</span>
      </div>

      <div className="flex flex-col gap-2 lg:flex-row lg:gap-0">
        <div className="min-w-0 flex-1 rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
          <BoardGrid cells={cells} selected={selected} onEnter={onEnter} onClick={onClick} onLeave={onLeave} />
        </div>
        {/* 右パネル (左端ハンドルでドラッグリサイズ) */}
        <ResizeHandle onMouseDown={right.onMouseDown} />
        <div className="flex shrink-0 flex-col gap-3 lg:pl-1" style={{ width: right.width }}>
          {selected != null && (
            <button
              type="button"
              disabled
              title="対戦連携は次段で実装"
              className="rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              {cells[selected]?.owner ? "このマスに挑戦（防衛戦）" : "このマスに挑戦（ランダムAI）"}
            </button>
          )}
          <CellHistoryPanel cell={active} idx={activeIdx} leaders={leaders} />
        </div>
      </div>
    </div>
  );
}

export const BoardGrid = memo(function BoardGrid({
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
      style={{ display: "grid", gridTemplateColumns: `repeat(${COLS}, 1fr)`, gap: 1 }}
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
            // カード上部の正方形を「長い方 L=max(w,h) に合わせて」配置し、 w×h に分割。
            // 縦は上詰め (imgR=r) / 横は中央 (imgC=c+(L-w)/2)。 このセルは (r,c) の画像片。
            (() => {
              const { w, h, r, c: cc } = c.block!;
              const L = Math.max(w, h); // 長い方に合わせる (縦長なら縦=L)
              const imgCol = cc + (L - w) / 2; // 横は中央
              return (
                <img
                  src={`/cards/${c.owner.id}.png`}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  draggable={false}
                  style={{
                    position: "absolute",
                    width: `${L * ZOOM * 100}%`, // 上半分正方形にズーム
                    height: "auto",
                    maxWidth: "none",
                    left: `${-(imgCol + HOFF * L) * 100}%`,
                    top: `${-r * 100}%`, // 縦は上詰め (説明欄=下部は写らない)
                  }}
                />
              );
            })()
          )}
        </button>
      ))}
    </div>
  );
});

