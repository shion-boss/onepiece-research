import Link from "next/link";
import { fetchCards } from "@/lib/api";
import type { CardCategory, CardFilters } from "@/lib/types";
import { CardFilterBar } from "@/components/CardFilterBar";
import { CardGrid } from "@/components/CardGrid";

const VALID_CATEGORIES = new Set<CardCategory>([
  "LEADER",
  "CHARACTER",
  "EVENT",
  "STAGE",
]);

function parseInt0(v: string | undefined): number | undefined {
  if (!v) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export default async function CardsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const get = (k: string): string | undefined => {
    const v = sp[k];
    return Array.isArray(v) ? v[0] : v;
  };

  const categoryRaw = get("category");
  const regulationRaw = get("regulation");
  const filters: CardFilters = {
    color: get("color"),
    category:
      categoryRaw && VALID_CATEGORIES.has(categoryRaw as CardCategory)
        ? (categoryRaw as CardCategory)
        : undefined,
    cost_le: parseInt0(get("cost_le")),
    cost_ge: parseInt0(get("cost_ge")),
    name_contains: get("name_contains"),
    // "standard" = block_icon >= 2、未指定 = 全件
    block_icon_ge: regulationRaw === "standard" ? 2 : undefined,
    limit: 200,
  };

  let cards: Awaited<ReturnType<typeof fetchCards>> = [];
  let error: string | null = null;
  try {
    cards = await fetchCards(filters);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">カード</h1>
        <div className="text-sm text-zinc-600 dark:text-zinc-400">
          {error ? "—" : `${cards.length} 件 (上限 200)`}
        </div>
      </header>

      <CardFilterBar />

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">API への接続に失敗しました</div>
          <div className="mt-1 font-mono">{error}</div>
          <div className="mt-2 text-red-800 dark:text-red-300">
            <code>uvicorn api.main:app --reload --port 8000</code> を起動してください。
          </div>
        </div>
      ) : (
        <CardGrid cards={cards} />
      )}
    </main>
  );
}
