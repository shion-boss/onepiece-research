"use client";

import { CardImage } from "./CardImage";
import type { Cell, BoardLeader } from "./TerritoryBoard";

// マスで行われた戦いの履歴 (現状は seed)。 ホバー中のマスの右側パネルに表示。
export type Battle = {
  id: number;
  daysAgo: number;
  challenger: string;
  leaderId: string;
  leaderName: string;
  conquered: boolean; // true=奪取(挑戦者の勝ち) / false=防衛成功(占領者の勝ち)
  turns: number;
};

function h32(n: number): number {
  let h = (n ^ 0x9e3779b9) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
  return (h ^ (h >>> 16)) >>> 0;
}

function seedBattles(idx: number, cell: Cell, leaders: BoardLeader[]): Battle[] {
  if (leaders.length === 0) return [];
  const n = h32(idx * 11 + 5) % 7; // 0..6 件
  const out: Battle[] = [];
  for (let k = 0; k < n; k++) {
    const s = h32(idx * 131 + k * 17 + 3);
    // 先頭(最新)が占領者本人の奪取。 以降は防衛成功が多め。
    const conquered = k === 0 ? !!cell.owner : s % 100 < 30;
    const ld = conquered && k === 0 && cell.owner ? cell.owner : leaders[s % leaders.length];
    out.push({
      id: k,
      daysAgo: (h32(idx * 7 + k * 13) % 26) + k * 3 + 1,
      challenger: k === 0 && cell.owner ? cell.ownerName ?? "—" : `プレイヤー${(h32(idx * 5 + k) % 9000) + 1000}`,
      leaderId: ld.id,
      leaderName: ld.name,
      conquered,
      turns: (h32(idx * 3 + k * 29) % 14) + 6,
    });
  }
  return out.sort((a, b) => a.daysAgo - b.daysAgo);
}

export function CellHistoryPanel({
  cell,
  idx,
  leaders,
}: {
  cell: Cell | null;
  idx: number | null;
  leaders: BoardLeader[];
}) {
  return (
    <div className="w-full rounded-[var(--radius)] border p-3" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
      {idx == null ? (
        <div className="py-10 text-center text-sm text-[color:var(--text-muted)]">マスにホバーで<br />そのマスの戦いの履歴</div>
      ) : (
        <CellDetail cell={cell!} idx={idx} leaders={leaders} />
      )}
    </div>
  );
}

function CellDetail({ cell, idx, leaders }: { cell: Cell; idx: number; leaders: BoardLeader[] }) {
  const battles = seedBattles(idx, cell, leaders);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        {cell.owner ? (
          <>
            <CardImage cardId={cell.owner.id} alt={cell.owner.name} className="h-12 w-auto rounded border border-[color:var(--border-1)] object-cover" />
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">マス #{idx + 1} の占領者</div>
              <div className="truncate text-sm font-semibold text-[color:var(--text-strong)]">{cell.owner.name}</div>
              <div className="truncate text-xs text-[color:var(--text-muted)]">{cell.ownerName}</div>
            </div>
          </>
        ) : (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">マス #{idx + 1}</div>
            <div className="text-sm font-semibold text-[color:var(--text-strong)]">空きマス（未占領）</div>
          </div>
        )}
      </div>

      <div>
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">このマスの戦い（新しい順）</div>
        {battles.length === 0 ? (
          <div className="rounded border border-dashed px-2 py-4 text-center text-xs text-[color:var(--text-muted)]" style={{ borderColor: "var(--border-2)" }}>
            まだ戦いはありません
          </div>
        ) : (
          <ul className="flex flex-col gap-1">
            {battles.map((b) => (
              <li key={b.id} className="flex items-center gap-2 rounded border px-2 py-1.5 text-xs" style={{ borderColor: "var(--border-1)", background: "var(--surface-2)" }}>
                <CardImage cardId={b.leaderId} alt={b.leaderName} className="h-8 w-auto rounded object-cover" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-[color:var(--text-strong)]">{b.challenger}</div>
                  <div className="flex items-center gap-1.5 text-[10px] text-[color:var(--text-muted)]">
                    <span className="rounded px-1 font-bold text-white" style={{ background: b.conquered ? "var(--accent)" : "var(--danger)" }}>
                      {b.conquered ? "奪取" : "防衛"}
                    </span>
                    <span>{b.turns}T</span>
                    <span>{b.daysAgo}日前</span>
                  </div>
                </div>
                <button
                  type="button"
                  disabled
                  title="対戦連携の実装後に、この試合を再生できます"
                  className="rounded border px-1.5 py-0.5 text-[10px] text-[color:var(--text-muted)] opacity-50"
                  style={{ borderColor: "var(--border-2)" }}
                >
                  観戦
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
