"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listResearchSessions } from "@/lib/api";
import type { ResearchSessionSummary } from "@/lib/types";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";
import { Button } from "@/components/ui/Button";

export default function ResearchListPage() {
  const [sessions, setSessions] = useState<ResearchSessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchData = () => {
      listResearchSessions({ limit: 50 })
        .then((data) => {
          if (!cancelled) {
            setSessions(data);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };
    fetchData();
    // 5 秒ごとに polling (= running セッションの進捗反映)
    const id = setInterval(fetchData, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <PageShell>
      <PageHeader
        title="研究セッション"
        description="対策デッキを 世代交代 で 進化させる 長時間研究 の 管理"
        actions={
          <Link href="/research/new">
            <Button variant="primary">+ 新規セッション</Button>
          </Link>
        }
      />

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          エラー: {error}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-zinc-500 dark:text-zinc-400">読み込み中…</div>
      ) : sessions.length === 0 ? (
        <div className="rounded-lg border border-zinc-200 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          まだ セッションが ありません。 「新規セッション」 から 開始してください。
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-xs text-zinc-500 dark:bg-zinc-900">
              <tr>
                <th className="p-2">対象</th>
                <th className="p-2">ステータス</th>
                <th className="p-2">世代</th>
                <th className="p-2">ベスト勝率</th>
                <th className="p-2">作成日時</th>
                <th className="p-2">アクション</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="p-2 font-mono text-xs">{s.target_slug}</td>
                  <td className="p-2">
                    <StatusBadge status={s.status} />
                    {s.completion_reason && (
                      <span className="ml-2 text-xs text-zinc-500">
                        ({s.completion_reason})
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-xs">Gen {s.current_generation}</td>
                  <td className="p-2 font-mono">
                    {s.best_winrate != null
                      ? `${(s.best_winrate * 100).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="p-2 text-xs text-zinc-500">
                    {new Date(s.created_at).toLocaleString()}
                  </td>
                  <td className="p-2">
                    <Link
                      href={`/research/${encodeURIComponent(s.id)}`}
                      className="text-blue-600 hover:underline"
                    >
                      詳細 →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "running"
      ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
      : status === "paused"
        ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300"
        : status === "completed"
          ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300"
          : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  const label =
    status === "running" ? "実行中"
      : status === "paused" ? "一時停止"
        : status === "completed" ? "完了"
          : "停止";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}
