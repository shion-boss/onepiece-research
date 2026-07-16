"use client";

import { useEffect, useRef, useState } from "react";
import { CardImage } from "./CardImage";
import { fetchDeck } from "@/lib/api";
import { cardImageUrl, cardImageRemoteUrl } from "@/lib/images";

type DeckInfo = {
  slug: string;
  name: string;
  leader: string;
  cardIds: string[];
};

export function CardPreloader({
  deckSlugA,
  deckSlugB,
  deckNameA,
  deckNameB,
  leaderBOverride,
  nameBOverride,
  randomB,
  onComplete,
  title,
}: {
  deckSlugA: string;
  deckSlugB: string;
  deckNameA?: string;
  deckNameB?: string;
  // 陣取り防衛戦: AI 側 (B) の実デッキは server 決定でフロントに無いが、 リーダーは既知。
  // これを渡すと deckSlugB を fetch/表示せず、 このリーダーカードを B 側に出す (= 盤の防衛
  // リーダーと一致)。 randomB=true は空きマス (ランダム AI) で、 相手不定のプレースホルダ表示。
  leaderBOverride?: string | null;
  nameBOverride?: string;
  randomB?: boolean;
  onComplete: () => void;
  title?: string;
}) {
  const [decks, setDecks] = useState<[DeckInfo, DeckInfo] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(0);
  const [total, setTotal] = useState(0);
  // onComplete を ref に持って effect の dep から外す (= 親が inline で渡しても再実行されない)
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const buildInfo = (
          slug: string,
          nameOverride: string | undefined,
          d: { leader: string; name?: string; main: { card_id: string }[] },
        ): DeckInfo => {
          const ids = new Set<string>();
          ids.add(d.leader);
          for (const e of d.main) ids.add(e.card_id);
          return {
            slug,
            name: nameOverride ?? d.name ?? slug,
            leader: d.leader,
            cardIds: [...ids],
          };
        };
        // A (人間) は必ず fetch。 B は override/random ならフロントに実デッキが無いので
        // fetch せず、 既知のリーダー (or 空プレースホルダ) だけを出す。
        const da = await fetchDeck(deckSlugA);
        if (cancelled) return;
        const infoA = buildInfo(deckSlugA, deckNameA, da);
        let infoB: DeckInfo;
        if (randomB) {
          infoB = { slug: "random", name: nameBOverride ?? "ランダム AI", leader: "", cardIds: [] };
        } else if (leaderBOverride) {
          infoB = {
            slug: "defender",
            name: nameBOverride ?? "防衛リーダー",
            leader: leaderBOverride,
            cardIds: [leaderBOverride],
          };
        } else {
          const db = await fetchDeck(deckSlugB);
          if (cancelled) return;
          infoB = buildInfo(deckSlugB, deckNameB, db);
        }
        setDecks([infoA, infoB]);
        const allIds = Array.from(
          new Set([...infoA.cardIds, ...infoB.cardIds]),
        ).filter(Boolean);
        setTotal(allIds.length);
        setLoaded(0);

        let done = 0;
        await Promise.all(
          allIds.map(
            (cardId) =>
              new Promise<void>((resolve) => {
                const finish = () => {
                  done++;
                  if (!cancelled) setLoaded(done);
                  resolve();
                };
                const img = new window.Image();
                img.onload = finish;
                img.onerror = () => {
                  // local 404 → 公式 CDN proxy へ fallback
                  const img2 = new window.Image();
                  img2.onload = finish;
                  img2.onerror = finish;
                  img2.src = cardImageRemoteUrl(cardId);
                };
                img.src = cardImageUrl(cardId);
              }),
          ),
        );
        if (cancelled) return;
        onCompleteRef.current();
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [deckSlugA, deckSlugB, deckNameA, deckNameB, leaderBOverride, nameBOverride, randomB]);

  const pct = total > 0 ? Math.round((loaded / total) * 100) : 0;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 p-8">
      <h2 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
        {title ?? "カード 読み込み中..."}
      </h2>

      {decks && (
        <div className="grid w-full grid-cols-[1fr_auto_1fr] items-center gap-6">
          <div className="flex flex-col items-center gap-2">
            <CardImage
              cardId={decks[0].leader}
              alt={decks[0].name}
              className="w-32 rounded-lg shadow-lg"
              loading="eager"
            />
            <div className="text-center text-xs font-medium text-zinc-700 dark:text-zinc-300">
              {decks[0].name}
            </div>
          </div>
          <div className="text-3xl font-black tracking-widest text-zinc-300 dark:text-zinc-700">
            VS
          </div>
          <div className="flex flex-col items-center gap-2">
            {decks[1].leader ? (
              <CardImage
                cardId={decks[1].leader}
                alt={decks[1].name}
                className="w-32 rounded-lg shadow-lg"
                loading="eager"
              />
            ) : (
              // 空きマス (ランダム AI): 相手不定なのでプレースホルダ (=? マーク) を出す。
              <div className="flex h-[179px] w-32 items-center justify-center rounded-lg border border-dashed text-3xl font-black text-zinc-400 shadow-lg dark:border-zinc-700 dark:text-zinc-600">
                ?
              </div>
            )}
            <div className="text-center text-xs font-medium text-zinc-700 dark:text-zinc-300">
              {decks[1].name}
            </div>
          </div>
        </div>
      )}

      <div className="w-full max-w-md">
        <div className="mb-1 text-xs text-zinc-600 dark:text-zinc-400">
          カード 画像 を 読み込み中
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
          <div
            className="h-full bg-emerald-500 transition-all duration-200"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          読み込み失敗: {error}
        </div>
      )}
    </div>
  );
}
