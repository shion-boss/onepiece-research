import { fetchCards, fetchTerritoryBoard, type TerritoryBoard as TerritoryBoardData } from "@/lib/api";
import { TerritoryBoard, type BoardLeader } from "@/components/TerritoryBoard";
import { PageShell } from "@/components/ui/PageShell";

// 推しリーダー陣取り (表: 陣取りゲーム / 裏: みんなで育てる AI)。
// リーダーは card DB から動的導出 (新弾で自動追加)。 パラレルは base card_id に統合。
export default async function GrowPage() {
  const leaders: BoardLeader[] = [];
  let error: string | null = null;
  try {
    const cards = await fetchCards({ category: "LEADER", limit: 10000 });
    const seen = new Set<string>();
    for (const c of cards) {
      const base = c.card_id.split("_")[0];
      if (seen.has(base)) continue;
      seen.add(base);
      leaders.push({ id: base, name: c.name, color: c.color?.[0] ?? "黒" });
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  // 占領状態は SSR で 1 度取得 (= 初回描画から実データ)。 以降はクライアントがポーリングで更新。
  // 取得失敗しても盤は出す (クライアント SWR が retry)。
  let initialBoard: TerritoryBoardData | undefined;
  try {
    initialBoard = await fetchTerritoryBoard();
  } catch {
    initialBoard = undefined;
  }

  if (error) {
    return (
      <PageShell>
        <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-4 text-sm text-[color:var(--danger)]">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      </PageShell>
    );
  }

  return (
    <div className="h-full w-full">
      <TerritoryBoard leaders={leaders} initialBoard={initialBoard} />
    </div>
  );
}
