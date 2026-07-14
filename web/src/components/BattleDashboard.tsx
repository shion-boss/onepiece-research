"use client";

import { useMemo, useState } from "react";
import { TerritoryTreemap, type TerritoryItem } from "./TerritoryTreemap";
import { seedStat, totals, type LeaderRef, type Period } from "@/lib/battleSeed";

const NEUTRAL_THRESHOLD = 5; // 対戦 <5 は未開拓 (グレー)

// みんなで育てる OPTCG AI: 数字 + リーダー陣取り treemap。 現状は seed データ。
export function BattleDashboard({ leaders }: { leaders: LeaderRef[] }) {
  const [period, setPeriod] = useState<Period>("all");

  const { items, games, winRate, humanLeaders, aiLeaders } = useMemo(() => {
    const its: TerritoryItem[] = leaders.map((l) => {
      const s = seedStat(l.id, period);
      return {
        id: l.id,
        name: l.name,
        matches: s.matches,
        win: s.win,
        neutral: s.matches < NEUTRAL_THRESHOLD,
      };
    });
    const t = totals(leaders, period);
    const contested = its.filter((i) => !i.neutral && i.matches > 0);
    return {
      items: its,
      games: t.games,
      winRate: t.winRate,
      humanLeaders: contested.filter((i) => i.win >= 0.5).length,
      aiLeaders: contested.filter((i) => i.win < 0.5).length,
    };
  }, [leaders, period]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-6">
      <header className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-6" style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}>
        <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">みんなで育てる OPTCG AI</h1>
        <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">
          みんなの対戦で AI が育つ。各リーダーで人間と AI のどちらが勝ち越しているかの陣取り。あなたの一戦がマスを塗り替える。
        </p>
      </header>

      {/* 数字 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label={period === "all" ? "総対戦数" : "今月の対戦数"} value={games.toLocaleString()} />
        <Stat label={period === "all" ? "人間の勝率" : "今月の人間勝率"} value={`${Math.round(winRate * 100)}%`} tone="human" />
        <Stat label="人間の陣地" value={`${humanLeaders} 体`} tone="human" />
        <Stat label="AI の陣地" value={`${aiLeaders} 体`} tone="ai" />
      </div>

      {/* 期間トグル + 凡例 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded-[var(--radius)] border" style={{ borderColor: "var(--border-2)" }}>
          {(["all", "month"] as Period[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className="px-4 py-1.5 text-sm font-medium transition-colors"
              style={period === p ? { background: "var(--brand)", color: "#fff" } : { color: "var(--text-default)" }}
            >
              {p === "all" ? "全期間" : "今月"}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[color:var(--text-muted)]">
          <Legend color="#4ec9b0" label="人間 勝ち越し" />
          <Legend color="#f14c4c" label="AI 勝ち越し" />
          <Legend color="#6a6a72" label="未開拓" />
        </div>
      </div>

      {/* 陣取り treemap */}
      <div className="rounded-[var(--radius)] border p-2" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
        <TerritoryTreemap items={items} />
      </div>
      <p className="text-center text-[11px] text-[color:var(--text-muted)]">
        マスの大きさ = 対戦数 / 色 = 人間 vs AI の勝率 / 画像 = そのリーダーで最後に戦った人の柄（※現在はサンプルデータ）
      </p>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "human" | "ai" }) {
  const color = tone === "human" ? "var(--accent)" : tone === "ai" ? "var(--danger)" : "var(--text-strong)";
  return (
    <div className="rounded-[var(--radius)] border p-4" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
      <div className="text-[11px] uppercase tracking-wider text-[color:var(--text-muted)]">{label}</div>
      <div className="mt-1 text-2xl font-bold" style={{ color }}>{value}</div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}
