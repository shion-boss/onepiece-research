"use client";

import { memo, useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CardImage } from "./CardImage";
import { CellPanel } from "./CellHistoryPanel";
import { useResizable } from "@/lib/useResizable";
import { ResizeHandle } from "./ResizeHandle";
import { useTerritoryBoard } from "@/lib/useTerritory";
import type { TerritoryBoard as TerritoryBoardData } from "@/lib/api";

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
// imageId: 表示するカード絵の full card_id (= ブロックで最後に戦闘した人の variant)。 未指定なら owner.id。
export type Cell = { owner: BoardLeader | null; ownerName: string | null; color: string; block: { w: number; h: number; r: number; c: number } | null; imageId?: string | null };

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

// 実 territory データ (占領済みマスのみ) → 1024 マスの Cell[] を組む。
// - 隣接する同じリーダーのマスは占領者(プレイヤー)が別人でも 1 枚のカード絵に繋げる (矩形ブロック化)。
// - ブロックの絵は「最後に戦闘した人が使った柄」= ブロック内で updated_at が最新の variant_id。
function buildCellsFromBoard(
  board: TerritoryBoardData | undefined,
  leaderById: Map<string, BoardLeader>,
): Cell[] {
  const cells: Cell[] = Array.from({ length: N }, () => ({
    owner: null, ownerName: null, color: EMPTY, block: null, imageId: null,
  }));
  if (!board) return cells;

  // 占領マス cell_id → { leaderId(集計キー=base), variantId(表示柄), user, updatedAt }。
  type Owned = { leaderId: string; variantId: string; user: string | null; updatedAt: string };
  const owned = new Map<number, Owned>();
  for (const c of board.cells) {
    if (c.cell_id < 0 || c.cell_id >= N || !c.leader_id) continue;
    owned.set(c.cell_id, {
      leaderId: c.leader_id,
      variantId: c.variant_id ?? c.leader_id,
      user: c.user,
      updatedAt: c.updated_at ?? "",
    });
  }

  // まず各占領マスに owner(=リーダー)・色・占領者名を入れる (block/imageId はブロック確定後に上書き)。
  for (const [cellId, o] of owned) {
    const ld = leaderById.get(o.leaderId) ?? { id: o.leaderId, name: o.leaderId, color: "黒" };
    cells[cellId] = { owner: ld, ownerName: o.user, color: COLOR_HEX[ld.color] ?? "#888", block: null, imageId: o.variantId };
  }

  // 同一リーダーの隣接マスを貪欲に矩形ブロックへ (占領者違いは無視 = leader が同じなら繋ぐ)。
  const leaderAt = (idx: number): string | null => owned.get(idx)?.leaderId ?? null;
  const blocked = new Uint8Array(N);
  for (let y = 0; y < COLS; y++) {
    for (let x = 0; x < COLS; x++) {
      const idx = y * COLS + x;
      const ld = leaderAt(idx);
      if (!ld || blocked[idx]) continue;
      // 幅: 右へ同一リーダー & 未ブロックの間だけ伸ばす。
      let w = 1;
      while (x + w < COLS && leaderAt(idx + w) === ld && !blocked[idx + w]) w++;
      // 高さ: 下の行の w マスが全て同一リーダー & 未ブロックなら伸ばす。
      let h = 1;
      let extend = true;
      while (extend && y + h < COLS) {
        for (let dx = 0; dx < w; dx++) {
          const b = (y + h) * COLS + (x + dx);
          if (leaderAt(b) !== ld || blocked[b]) { extend = false; break; }
        }
        if (extend) h++;
      }
      // ブロック内で updated_at 最新 = 最後に戦闘した人の variant を採用。
      let bestVariant = owned.get(idx)!.variantId;
      let bestAt = owned.get(idx)!.updatedAt;
      for (let dy = 0; dy < h; dy++) {
        for (let dx = 0; dx < w; dx++) {
          const o = owned.get((y + dy) * COLS + (x + dx))!;
          if (o.updatedAt > bestAt) { bestAt = o.updatedAt; bestVariant = o.variantId; }
        }
      }
      // ブロック全マスに block 座標 + 共通の imageId を割当 (owner/ownerName は各マス固有のまま)。
      for (let dy = 0; dy < h; dy++) {
        for (let dx = 0; dx < w; dx++) {
          const b = (y + dy) * COLS + (x + dx);
          blocked[b] = 1;
          cells[b].block = { w, h, r: dy, c: dx };
          cells[b].imageId = bestVariant;
        }
      }
    }
  }
  return cells;
}

export function TerritoryBoard({
  leaders,
  initialBoard,
}: {
  leaders: BoardLeader[];
  initialBoard?: TerritoryBoardData;
}) {
  const router = useRouter();
  // 盤全体をポーリング (= 再読み込み不要で常時最新)。 初期値は SSR で取得済み。
  const { board } = useTerritoryBoard(initialBoard);
  const leaderById = useMemo(() => {
    const m = new Map<string, BoardLeader>();
    for (const l of leaders) m.set(l.id, l);
    return m;
  }, [leaders]);
  const cells = useMemo(() => buildCellsFromBoard(board, leaderById), [board, leaderById]);
  const [hovered, setHovered] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  const onEnter = useCallback((i: number) => setHovered(i), []);
  // クリックで固定 (再クリックで解除)。 固定中はホバーで切り替わらない → 観戦ボタンまで到達できる。
  const onClick = useCallback((i: number) => setSelected((p) => (p === i ? null : i)), []);
  const onLeave = useCallback(() => setHovered(null), []);

  const [hoverEnabled, setHoverEnabled] = useState(false); // 既定=ホバー切替なし
  // 固定中は selected を優先。 未固定時は toggle ON のときだけホバー追従。
  const activeIdx = selected != null ? selected : hoverEnabled ? hovered : null;
  const active = activeIdx != null ? cells[activeIdx] : null;
  const right = useResizable(288, 240, 560, true); // 右パネル幅ドラッグ
  const occupied = board?.cells.length ?? 0;

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* 中央: ヘッダー + 盤 (スクロール) */}
      <main className="log-scroll min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
          <header className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-5" style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}>
            <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">推しリーダー陣取りボード</h1>
            <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">
              1024 マスを推しリーダーで奪い合う。AI に勝てば 1 マス占領。占領マスに挑むと、その占領者のデッキを操る AI が防衛する。
            </p>
          </header>

          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-[color:var(--text-muted)]">占領 <span className="font-bold text-[color:var(--text-strong)]">{occupied}</span> / 空き <span className="font-bold text-[color:var(--text-strong)]">{N - occupied}</span></span>
            <span className="ml-auto text-xs text-[color:var(--text-muted)]">クリックでマスの詳細を表示（再クリックで解除）・ 右パネルのトグルでホバー切替も可</span>
          </div>

          <div className="rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
            <BoardGrid cells={cells} selected={selected} onEnter={onEnter} onClick={onClick} onLeave={onLeave} />
          </div>
        </div>
      </main>

      {/* 右: マスの情報 (固定サイドメニュー、 左端ハンドルでリサイズ) */}
      <ResizeHandle onMouseDown={right.onMouseDown} />
      <div className="log-scroll shrink-0 overflow-y-auto border-l" style={{ width: right.width, borderColor: "var(--border-1)" }}>
        <CellPanel
          cell={active}
          idx={activeIdx}
          leaders={leaders}
          hoverEnabled={hoverEnabled}
          onToggleHover={() => setHoverEnabled((v) => !v)}
          realBattles
          actionSlot={
            // マス表示中 (ホバー / 選択) は常にボタン領域を確保。
            //   選択時       = 実ボタン (ブランド色)
            //   非選択(ホバー) = 同じサイズ・同じ文字量の黒系プレースホルダー div (文字は透明)
            // → ホバー表示→クリック(選択) で下の詳細がボタン分だけ上下に動かない (ちらつき防止)。
            // 未表示 (プレースホルダー本文) 時は出さない = 余分な空きを作らない。
            active != null ? (
              selected != null ? (
                <button
                  type="button"
                  onClick={() => router.push(`/play?cell=${selected}`)}
                  title={active.owner ? "占領者のデッキを操る AI と防衛戦" : "ランダム AI と対戦"}
                  className="mb-3 w-full rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-2.5 text-sm font-semibold text-white transition-[filter] hover:brightness-110"
                >
                  {active.owner ? "このマスに挑戦（防衛戦）" : "このマスに挑戦（ランダムAI）"}
                </button>
              ) : (
                <div
                  aria-hidden
                  className="mb-3 w-full select-none rounded-[var(--radius)] px-3 py-2.5 text-sm font-semibold text-transparent"
                  style={{ background: "#1a1a1d" }}
                >
                  {active.owner ? "このマスに挑戦（防衛戦）" : "このマスに挑戦（ランダムAI）"}
                </div>
              )
            ) : null
          }
        />
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
                // CardImage = ローカル /cards/<id>.png → 404 なら公式 CDN proxy に fallback
                // (本番はローカル画像未デプロイなので proxy 経由で表示される)。
                <CardImage
                  cardId={c.imageId ?? c.owner.id}
                  alt=""
                  loading="eager"
                  remoteFirst
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

