import { Suspense } from "react";
import { fetchMetaMatrix } from "@/lib/api";
import type { MatchupMatrix } from "@/lib/types";
import { MetaPageClient } from "./client";

/**
 * メタ分析 hub。 2 tab 構成:
 * - matrix (= デフォルト): N×N 勝率 heatmap
 * - spectate (= 旧 /meta/spectate): AI vs AI ライブ観戦 (= 1 試合 シミュ + 盤面再生)
 *
 * `?tab=spectate&a=<slug>&b=<slug>&seed=<n>` で 直接 spectate tab を 開ける。
 */
export default async function MetaPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const get = (k: string): string | undefined => {
    const v = sp[k];
    return Array.isArray(v) ? v[0] : v;
  };
  const initialTab = get("tab") === "spectate" ? "spectate" : "matrix";
  const initialA = get("a");
  const initialB = get("b");
  const seedStr = get("seed");
  const initialSeed = seedStr ? parseInt(seedStr, 10) : undefined;

  let data: MatchupMatrix | null = null;
  let error: string | null = null;
  try {
    data = await fetchMetaMatrix();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <Suspense fallback={<div className="p-6 text-sm text-zinc-500">読み込み中…</div>}>
      <MetaPageClient
        initialData={data}
        initialError={error}
        initialTab={initialTab}
        initialA={initialA}
        initialB={initialB}
        initialSeed={Number.isFinite(initialSeed) ? initialSeed : undefined}
      />
    </Suspense>
  );
}
