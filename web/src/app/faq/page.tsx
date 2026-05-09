"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
import { fetchFaqSources, searchFaq } from "@/lib/api";
import type { FaqHit, FaqSource } from "@/lib/types";

const TABS: { key: string; label: string; prefix: string | null }[] = [
  { key: "all", label: "all", prefix: null },
  { key: "base", label: "基本ルール", prefix: "base" },
  { key: "keyword_effect", label: "キーワード効果", prefix: "keyword_effect" },
  { key: "keyword", label: "キーワード", prefix: "keyword.json" }, // 完全一致回避
  { key: "detail", label: "詳細ルール", prefix: "detail" },
  { key: "cardqa", label: "カードQ&A", prefix: "cardqa_" },
];

export default function FaqPage() {
  const [sources, setSources] = useState<FaqSource[]>([]);
  const [q, setQ] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [hitsAll, setHitsAll] = useState<FaqHit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    fetchFaqSources()
      .then(setSources)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const tokens = useMemo(
    () => q.trim().split(/\s+/).filter(Boolean),
    [q],
  );

  const runSearch = () => {
    setError(null);
    startTransition(async () => {
      try {
        // タブに依らず全件取得 → クライアントでカテゴリ別に分類
        const r = await searchFaq(q, undefined, 500);
        setHitsAll(r);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });
  };

  useEffect(() => {
    const t = setTimeout(runSearch, 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const totalQa = sources.reduce((s, x) => s + x.count, 0);

  // タブ別の件数集計
  const byTab = useMemo(() => {
    const counts = new Map<string, number>();
    for (const tab of TABS) counts.set(tab.key, 0);
    for (const h of hitsAll) {
      counts.set("all", (counts.get("all") ?? 0) + 1);
      for (const tab of TABS) {
        if (tab.key === "all" || !tab.prefix) continue;
        if (h.source.startsWith(tab.prefix)) {
          counts.set(tab.key, (counts.get(tab.key) ?? 0) + 1);
        }
      }
    }
    return counts;
  }, [hitsAll]);

  const filteredHits = useMemo(() => {
    if (activeTab === "all") return hitsAll;
    const tab = TABS.find((t) => t.key === activeTab);
    if (!tab || !tab.prefix) return hitsAll;
    return hitsAll.filter((h) => h.source.startsWith(tab.prefix!));
  }, [hitsAll, activeTab]);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-6">
      <header className="space-y-1">
        <Link
          href="/"
          className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
        >
          ← back
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">/faq</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          公式 Q&A 横断検索 ({totalQa.toLocaleString()} 件 / {sources.length} ソース)。
          複数キーワードはスペース区切りで AND 検索。
        </p>
      </header>

      <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder='例: "トリガー 発動" / "ダブルアタック ライフ" / "OP07-115"'
          className="w-full rounded border border-zinc-300 bg-transparent px-3 py-1.5 text-sm dark:border-zinc-700"
          aria-label="検索クエリ"
        />
        {pending && (
          <span className="mt-1 inline-block text-xs text-zinc-500 dark:text-zinc-400">
            検索中…
          </span>
        )}
      </div>

      {/* カテゴリタブ */}
      <nav
        className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800"
        role="tablist"
      >
        {TABS.map((tab) => {
          const count = byTab.get(tab.key) ?? 0;
          const active = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveTab(tab.key)}
              className={`rounded-t border-b-2 px-3 py-1.5 text-sm transition ${
                active
                  ? "border-zinc-900 font-medium text-zinc-900 dark:border-zinc-100 dark:text-zinc-100"
                  : "border-transparent text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              }`}
            >
              {tab.label}{" "}
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                ({count})
              </span>
            </button>
          );
        })}
      </nav>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">エラー</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      )}

      {filteredHits.length === 0 && !pending && q && (
        <div className="rounded border border-zinc-200 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          該当する Q&A がありません
        </div>
      )}

      <ul className="space-y-2">
        {filteredHits.map((h, i) => (
          <li
            key={`${h.source}-${i}`}
            className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
          >
            <div className="mb-1 flex flex-wrap items-baseline gap-2">
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-mono text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                {h.source}
              </span>
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                {h.category}
              </span>
            </div>
            <Highlighted tokens={tokens} className="font-medium">
              Q. {h.q}
            </Highlighted>
            <Highlighted
              tokens={tokens}
              className="mt-1 whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300"
            >
              A. {h.a}
            </Highlighted>
          </li>
        ))}
      </ul>
    </main>
  );
}

function Highlighted({
  tokens,
  className,
  children,
}: {
  tokens: string[];
  className?: string;
  children: string | React.ReactNode;
}) {
  if (tokens.length === 0 || typeof children !== "string") {
    return <div className={className}>{children}</div>;
  }
  // 全トークンをハイライト (重複しないよう左から順)
  const parts: React.ReactNode[] = [];
  let rest = children;
  let id = 0;
  while (rest.length > 0) {
    let earliest: { idx: number; token: string } | null = null;
    for (const tok of tokens) {
      const i = rest.indexOf(tok);
      if (i < 0) continue;
      if (earliest === null || i < earliest.idx) {
        earliest = { idx: i, token: tok };
      }
    }
    if (earliest === null) {
      parts.push(rest);
      break;
    }
    parts.push(rest.slice(0, earliest.idx));
    parts.push(
      <mark
        key={id++}
        className="bg-yellow-200 px-0.5 dark:bg-yellow-700/60 dark:text-yellow-100"
      >
        {earliest.token}
      </mark>,
    );
    rest = rest.slice(earliest.idx + earliest.token.length);
  }
  return <div className={className}>{parts}</div>;
}
