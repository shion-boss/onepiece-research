"use client";

import { useEffect, useState } from "react";
import { fetchFaqSourceLinks, fetchFaqMeta, type FaqSourceLink, type FaqMeta } from "@/lib/api";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";

export default function FaqSourcesPage() {
  const [sources, setSources] = useState<FaqSourceLink[] | null>(null);
  const [meta, setMeta] = useState<FaqMeta | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchFaqSourceLinks()
      .then(setSources)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    fetchFaqMeta().then(setMeta).catch(() => {});
  }, []);

  const total = sources?.reduce((n, s) => n + s.count, 0) ?? meta?.count ?? 0;

  return (
    <PageShell>
      <PageHeader
        title="Q&A 参照先"
        description="公式サイトの Q&A / ルールのうち、 このツールが取り込み対象にしているページの一覧です。"
        meta={
          sources ? (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {sources.length} ソース ／ {total.toLocaleString()} 件
            </span>
          ) : null
        }
      />

      {error && (
        <div
          className="mt-4 rounded-[var(--radius)] border p-3 text-sm"
          style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
        >
          読み込みに失敗しました: {error}
        </div>
      )}

      {sources === null && !error && (
        <div className="mt-4 text-sm" style={{ color: "var(--text-muted)" }}>
          読み込み中…
        </div>
      )}

      {sources && sources.length === 0 && !error && (
        <div className="mt-4 text-sm" style={{ color: "var(--text-muted)" }}>
          参照先がまだ登録されていません。
        </div>
      )}

      {sources && sources.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {sources.map((s) => (
            <li
              key={s.source}
              className="rounded-[var(--radius)] border p-3"
              style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}
            >
              <div className="flex items-center justify-between gap-3">
                <span
                  className="min-w-0 truncate text-sm font-medium"
                  style={{ color: "var(--text-strong)" }}
                >
                  {s.label}
                </span>
                <span className="shrink-0 text-xs" style={{ color: "var(--text-muted)" }}>
                  {s.count.toLocaleString()} 件
                </span>
              </div>
              {s.source_url ? (
                <a
                  href={s.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 block truncate text-xs hover:underline"
                  style={{ color: "var(--brand)" }}
                >
                  {s.source_url}
                </a>
              ) : (
                <span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>
                  （URL 情報なし）
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}
