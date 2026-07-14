"use client";

import { CardImage } from "./CardImage";
import type { Cell, BoardLeader } from "./TerritoryBoard";

// マスで行われた戦いの履歴 (現状は seed)。 各戦い = 挑戦者(人間)リーダー vs 防衛側リーダー。
export type Battle = {
  id: number;
  daysAgo: number;
  challenger: string;
  attackerId: string; // 挑戦者(人間)が使ったリーダー
  attackerName: string;
  defenderId: string; // 防衛側リーダー
  defenderName: string;
  conquered: boolean; // true=奪取(挑戦者の勝ち) / false=防衛成功
  turns: number;
};

function h32(n: number): number {
  let h = (n ^ 0x9e3779b9) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
  return (h ^ (h >>> 16)) >>> 0;
}

// 現占領者から時間を遡って攻防チェーンを組む (占領者=最後に奪取した側)。
function seedBattles(idx: number, cell: Cell, leaders: BoardLeader[]): Battle[] {
  if (leaders.length === 0) return [];
  const n = h32(idx * 11 + 5) % 7; // 0..6 件
  const out: Battle[] = [];
  let owner = cell.owner; // 現(この時点)の占領者。 null=空き
  for (let k = 0; k < n; k++) {
    const s = h32(idx * 131 + k * 17 + 3);
    const rnd = (salt: number) => leaders[h32(idx * 100 + k * 7 + salt) % leaders.length];
    let attacker: BoardLeader;
    let defender: BoardLeader;
    let conquered: boolean;
    if (owner) {
      conquered = s % 100 < 33; // 1/3 で奪取 (所有権移動)
      if (conquered) {
        attacker = owner; // この時点の所有者が奪取した
        defender = rnd(1); // 前の所有者
        owner = defender; // 遡ると前の所有者
      } else {
        defender = owner; // 所有者が防衛
        attacker = rnd(2);
      }
    } else {
      // 空きマス: ランダム AI が防衛、 挑戦は失敗 (成功なら占領されている)
      conquered = false;
      defender = rnd(1);
      attacker = rnd(2);
    }
    out.push({
      id: k,
      daysAgo: (h32(idx * 7 + k * 13) % 26) + k * 3 + 1,
      challenger: k === 0 && conquered && cell.ownerName ? cell.ownerName : `プレイヤー${(h32(idx * 5 + k) % 9000) + 1000}`,
      attackerId: attacker.id,
      attackerName: attacker.name,
      defenderId: defender.id,
      defenderName: defender.name,
      conquered,
      turns: (h32(idx * 3 + k * 29) % 14) + 6,
    });
  }
  return out;
}

export function CellHistoryPanel({ cell, idx, leaders }: { cell: Cell | null; idx: number | null; leaders: BoardLeader[] }) {
  if (idx == null) return null;
  return (
    <div className="w-full rounded-[var(--radius)] border p-3" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
      <CellDetail cell={cell!} idx={idx} leaders={leaders} />
    </div>
  );
}

// 対戦ログ内のリーダー画像 (パネル幅に応じて大きく = 各辺 flex-1)。
function LeaderThumb({ id, name, label, ring }: { id: string; name: string; label: string; ring: string }) {
  return (
    <div className="min-w-0 flex-1" title={`${label}: ${name}`}>
      <CardImage cardId={id} alt={name} className="w-full rounded object-cover" style={{ aspectRatio: "5 / 7", boxShadow: `0 0 0 2px ${ring}` }} />
      <div className="mt-0.5 flex items-center justify-center gap-1">
        <span className="rounded px-1 text-[9px] font-bold text-white" style={{ background: ring }}>{label}</span>
        <span className="min-w-0 truncate text-[10px] text-[color:var(--text-default)]">{name}</span>
      </div>
    </div>
  );
}

function CellDetail({ cell, idx, leaders }: { cell: Cell; idx: number; leaders: BoardLeader[] }) {
  const battles = seedBattles(idx, cell, leaders);
  return (
    <div className="flex flex-col gap-3">
      {cell.owner ? (
        <div className="flex flex-col items-center gap-2">
          <div className="self-start text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">マス #{idx + 1} の占領リーダー</div>
          <CardImage
            cardId={cell.owner.id}
            alt={cell.owner.name}
            className="w-full max-w-[240px] rounded-[var(--radius)] object-cover"
            style={{ aspectRatio: "5 / 7", boxShadow: "0 0 0 3px var(--brand)" }}
          />
          <div className="text-center">
            <div className="text-lg font-bold text-[color:var(--text-strong)]">{cell.owner.name}</div>
            <div className="text-xs text-[color:var(--text-muted)]">占領者: {cell.ownerName}</div>
          </div>
        </div>
      ) : (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">マス #{idx + 1}</div>
          <div className="text-base font-semibold text-[color:var(--text-strong)]">空きマス（未占領）</div>
        </div>
      )}

      <div>
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">このマスの戦い（挑戦者 vs 防衛、新しい順）</div>
        {battles.length === 0 ? (
          <div className="rounded border border-dashed px-2 py-4 text-center text-xs text-[color:var(--text-muted)]" style={{ borderColor: "var(--border-2)" }}>
            まだ戦いはありません
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {battles.map((b) => (
              <li key={b.id} className="rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-2)" }}>
                {/* 挑戦者(人間) vs 防衛側 を大きく */}
                <div className="flex items-stretch gap-2">
                  <LeaderThumb id={b.attackerId} name={b.attackerName} label="挑戦" ring="var(--accent)" />
                  <div className="flex flex-col items-center justify-center gap-1">
                    <span className="text-sm font-black text-[color:var(--text-muted)]">VS</span>
                    <span className="rounded px-1.5 py-0.5 text-[10px] font-bold text-white" style={{ background: b.conquered ? "var(--accent)" : "var(--danger)" }}>
                      {b.conquered ? "奪取" : "防衛"}
                    </span>
                  </div>
                  <LeaderThumb id={b.defenderId} name={b.defenderName} label="防衛" ring="var(--danger)" />
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-[11px] text-[color:var(--text-muted)]">
                  <span className="min-w-0 flex-1 truncate">{b.challenger}</span>
                  <span>{b.turns}ターン</span>
                  <span>{b.daysAgo}日前</span>
                  <button
                    type="button"
                    disabled
                    title="対戦連携の実装後に、この試合を再生できます"
                    className="rounded border px-2 py-0.5 text-[11px] opacity-50"
                    style={{ borderColor: "var(--border-2)" }}
                  >
                    観戦
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
