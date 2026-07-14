import { fetchBanlist, fetchCards, fetchSets } from "@/lib/api";
import type { Banlist, CardCategory, CardFilters, SetInfo } from "@/lib/types";
import { buildBanStatus } from "@/lib/banlist";
import { CardBrowser } from "@/components/CardBrowser";
import { CardCountBadge } from "@/components/CardCountBadge";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";

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
    feature: get("feature"),
    set: get("set"),
    // "standard" = block_icon >= 2、未指定 = 全件
    block_icon_ge: regulationRaw === "standard" ? 2 : undefined,
    // 全カード (現状 4,673 枚) を取得。 表示は無限スクロールなので上限は不要。
    limit: 10000,
  };

  let cards: Awaited<ReturnType<typeof fetchCards>> = [];
  let sets: SetInfo[] = [];
  let banlist: Banlist | null = null;
  let error: string | null = null;
  try {
    [cards, sets] = await Promise.all([fetchCards(filters), fetchSets()]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }
  // banlist の取得失敗はカード表示を妨げない (= 目印が出ないだけ)
  try {
    banlist = await fetchBanlist();
  } catch {
    banlist = null;
  }
  const banStatus = buildBanStatus(banlist);

  return (
    <PageShell>
      <PageHeader
        title="カード"
        description="全 4,673 枚 の 検索 + フィルタ"
        actions={error ? <div className="text-sm text-[color:var(--text-muted)]">—</div> : <CardCountBadge fallback={cards.length} />}
      />

      {error ? (
        <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-4 text-sm text-[color:var(--danger)]">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
          <div className="mt-2 text-[color:var(--text-default)]">
            <code className="rounded-[var(--radius-sm)] bg-[color:var(--surface-2)] px-1">uvicorn api.main:app --reload --port 8000</code> を 起動してください。
          </div>
        </div>
      ) : (
        <CardBrowser cards={cards} banStatus={banStatus} sets={sets} />
      )}
    </PageShell>
  );
}
