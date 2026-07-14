"use client";

import { useMemo, useState } from "react";
import { TerritoryTreemap, type TerritoryItem } from "./TerritoryTreemap";
import { seedStat, totals, type LeaderRef } from "@/lib/battleSeed";

const NEUTRAL_THRESHOLD = 5;

// seed の月リスト (プロト用)。 実装では完了月の凍結スナップショットを並べる。
const MONTHS: { key: string; label: string; current?: boolean }[] = [
  { key: "2026-07", label: "2026年7月", current: true },
  { key: "2026-06", label: "2026年6月" },
  { key: "2026-05", label: "2026年5月" },
  { key: "2026-04", label: "2026年4月" },
  { key: "2026-03", label: "2026年3月" },
  { key: "2026-02", label: "2026年2月" },
];

export function BattleHistory({ leaders }: { leaders: LeaderRef[] }) {
  const [sel, setSel] = useState(MONTHS[1].key); // 既定 = 直近の完了月

  const monthSummaries = useMemo(
    () =>
      MONTHS.map((m) => {
        const t = totals(leaders, m.key);
        return { ...m, games: t.games, winRate: t.winRate };
      }),
    [leaders],
  );

  const items: TerritoryItem[] = useMemo(
    () =>
      leaders.map((l) => {
        const s = seedStat(l.id, sel);
        return { id: l.id, name: l.name, matches: s.matches, win: s.win, neutral: s.matches < NEUTRAL_THRESHOLD };
      }),
    [leaders, sel],
  );

  const selInfo = monthSummaries.find((m) => m.key === sel)!;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-6">
      <header className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-6" style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}>
        <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">戦いの歴史</h1>
        <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">
          毎月末に陣取りの状態を記録。人類 vs AI の歩みを月ごとに振り返る。AI が月を追うごとにリーダーを取り返していれば、みんなの対戦で AI が育っている証。
        </p>
      </header>

      {/* 月タイムライン */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {monthSummaries.map((m) => {
          const active = m.key === sel;
          return (
            <button
              key={m.key}
              type="button"
              onClick={() => setSel(m.key)}
              className="flex flex-col gap-1 rounded-[var(--radius)] border p-3 text-left transition-colors"
              style={{
                borderColor: active ? "var(--brand)" : "var(--border-1)",
                background: active ? "var(--list-hover)" : "var(--surface-1)",
              }}
            >
              <span className="flex items-center gap-1 text-xs font-medium text-[color:var(--text-strong)]">
                {m.label}
                {m.current && <span className="rounded bg-[color:var(--brand)] px-1 text-[9px] text-white">進行中</span>}
              </span>
              <span className="text-lg font-bold" style={{ color: "var(--accent)" }}>{Math.round(m.winRate * 100)}%</span>
              <span className="text-[10px] text-[color:var(--text-muted)]">{m.games.toLocaleString()} 戦</span>
            </button>
          );
        })}
      </div>

      {/* 選択月の陣取り */}
      <div className="flex items-baseline gap-2">
        <h2 className="text-lg font-medium text-[color:var(--text-strong)]">{selInfo.label} の陣取り</h2>
        <span className="text-sm text-[color:var(--text-muted)]">人間勝率 {Math.round(selInfo.winRate * 100)}% ・ {selInfo.games.toLocaleString()} 戦</span>
      </div>
      <div className="rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
        <TerritoryTreemap items={items} />
      </div>
      <p className="text-center text-[11px] text-[color:var(--text-muted)]">
        マスの大きさ = その月の対戦数 / 色 = 人間 vs AI の勝率（※現在はサンプルデータ）
      </p>
    </div>
  );
}
