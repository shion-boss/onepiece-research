"use client";

import { useEffect, useState } from "react";
import { fetchDeckHumanHistory, type HumanMatchEntry } from "@/lib/api";

// 人間 vs AI の直近対戦履歴 (= このデッキ視点の勝敗)。
// メタデッキは全ユーザー横断で貯まる (= 誰が使っても / AI が使っても このデッキの履歴)。
// user デッキは所有者本人の履歴のみ。 この履歴は AI 操縦・対戦AI改善にも使われる。
export function MatchHistorySection({ deckSlug }: { deckSlug: string }) {
  const [rows, setRows] = useState<HumanMatchEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchDeckHumanHistory(deckSlug, 15)
      .then((r) => {
        setRows(r);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [deckSlug]);

  if (loading) {
    return (
      <div className="text-sm text-[color:var(--text-muted)]">履歴読み込み中…</div>
    );
  }
  if (error) {
    return (
      <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-3 text-sm text-[color:var(--danger)]">
        {error}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-3 text-sm text-[color:var(--text-muted)]">
        まだ対戦履歴がありません（このデッキで人間 vs AI 対戦をすると蓄積されます）。
      </div>
    );
  }

  const wins = rows.filter((r) => r.result === "win").length;
  const losses = rows.filter((r) => r.result === "loss").length;

  return (
    <div className="space-y-2">
      <div className="text-xs text-[color:var(--text-muted)]">
        直近 {rows.length} 戦 ： {wins} 勝 {losses} 敗
        {rows.length - wins - losses > 0 && ` ${rows.length - wins - losses} 分`}
        <span className="ml-2">（人間 vs AI・メタデッキは全ユーザー共通で蓄積）</span>
      </div>
      <div className="overflow-x-auto rounded-[var(--radius-lg)] border border-[color:var(--border-1)]">
        <table className="w-full text-sm">
          <thead className="bg-[color:var(--surface-2)]">
            <tr className="text-left">
              <th className="p-2 font-medium">日時</th>
              <th className="p-2 font-medium">操作</th>
              <th className="p-2 font-medium">対戦相手</th>
              <th className="p-2 text-center font-medium">結果</th>
              <th className="p-2 text-center font-medium">先/後</th>
              <th className="p-2 text-right font-medium">ターン</th>
              <th className="p-2 font-medium">種別</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-[color:var(--border-1)]">
                <td className="p-2 font-mono text-xs text-[color:var(--text-muted)]">
                  {r.created_at.replace("T", " ").replace("Z", "")}
                </td>
                <td className="p-2 text-xs">
                  {r.side === "human" ? "あなた" : "AI"}
                </td>
                <td className="p-2">{r.opponent_leader ?? "-"}</td>
                <td className="p-2 text-center">
                  <ResultBadge result={r.result} />
                </td>
                <td className="p-2 text-center text-xs text-[color:var(--text-muted)]">
                  {r.went_first ? "先攻" : "後攻"}
                </td>
                <td className="p-2 text-right font-mono text-xs">
                  {r.turns ?? "-"}
                </td>
                <td className="p-2 text-xs text-[color:var(--text-muted)]">
                  {r.source === "territory" ? "陣取り" : "対戦"}
                  {r.non_stakes && r.source === "territory" ? "(練習)" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ResultBadge({ result }: { result: "win" | "loss" | "draw" }) {
  const style =
    result === "win"
      ? { bg: "var(--accent)", label: "勝ち" }
      : result === "loss"
        ? { bg: "var(--danger)", label: "負け" }
        : { bg: "var(--border-2)", label: "分け" };
  return (
    <span
      className="inline-block rounded px-2 py-0.5 text-[11px] font-semibold text-white"
      style={{ background: style.bg }}
    >
      {style.label}
    </span>
  );
}
