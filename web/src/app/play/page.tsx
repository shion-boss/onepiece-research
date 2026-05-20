import { fetchDecks } from "@/lib/api";
import { HumanMatchPlay } from "@/components/HumanMatchPlay";

export default async function PlayPage() {
  let decks: { slug: string; name: string }[] = [];
  let error: string | null = null;
  try {
    const raw = await fetchDecks();
    decks = raw.map((d) => ({ slug: d.slug, name: d.name ?? d.slug }));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          人間 vs AI 対戦 (大会練習)
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          GoalDirectedAI と 実際に 対戦 します。 自分の手番 で action を 選び、
          相手 攻撃 中は ブロッカー / カウンター を 選択。 試合 ログ は
          後続 imitation learning の 学習データ に なります。
        </p>
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">API への接続に失敗しました</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      ) : decks.length === 0 ? (
        <div className="rounded border border-zinc-200 p-6 text-sm dark:border-zinc-800">
          まだデッキが登録されていません。
        </div>
      ) : (
        <HumanMatchPlay decks={decks} />
      )}
    </main>
  );
}
