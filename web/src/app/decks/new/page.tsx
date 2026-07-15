"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { useDeckBuilderStore } from "@/stores/deckBuilder";
import { LeaderPicker } from "@/components/builder/LeaderPicker";
import { CardSearchPane } from "@/components/builder/CardSearchPane";
import { BuilderSidebar } from "@/components/builder/BuilderSidebar";
import { CostCurveMini } from "@/components/builder/CostCurveMini";
import { CardImage } from "@/components/CardImage";
import { ResizeHandle } from "@/components/ResizeHandle";
import { useResizable } from "@/lib/useResizable";
import type { Card } from "@/lib/types";
import {
  buildDeckWithCore,
  fetchCard,
  fetchDeck,
  saveDeckToServer,
} from "@/lib/api";

export default function NewDeckPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-[color:var(--text-muted)]">読み込み中…</div>}>
      <NewDeckPageContent />
    </Suspense>
  );
}

function NewDeckPageContent() {
  const params = useSearchParams();
  const router = useRouter();
  const fromSlug = params.get("from");

  const {
    leader,
    entries,
    name,
    regulation,
    setName,
    setLeader,
    setRegulation,
    addCard,
    increment,
    decrement,
    removeCard,
    reset,
    countByBaseId,
  } = useDeckBuilderStore();

  const [flash, setFlash] = useState<string | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [coreInput, setCoreInput] = useState("");
  const [autoBuilding, setAutoBuilding] = useState(false);
  const [saving, setSaving] = useState(false);
  // 非公開 (= 陣取りで使用不可)。 生成時にのみ決定・以後不変なので保存時に一度だけ送る。
  const [isPrivate, setIsPrivate] = useState(false);
  // 右の拡大プレビュー対象 (= カードグリッドをホバー中のカード)。
  const [hoveredCard, setHoveredCard] = useState<Card | null>(null);
  // 列幅ドラッグリサイズ (左=デッキ列 / 右=拡大プレビュー列、 中央=カード検索は flex-1)。
  const left = useResizable(340, 260, 620);
  const preview = useResizable(260, 200, 460, true);
  const hydratedSlugRef = useRef<string | null>(null);

  // ?from=<slug> でデッキ初期化 (1度だけ)
  useEffect(() => {
    if (!fromSlug) return;
    if (hydratedSlugRef.current === fromSlug) return;
    hydratedSlugRef.current = fromSlug;

    let cancelled = false;
    (async () => {
      setHydrating(true);
      try {
        const detail = await fetchDeck(fromSlug);
        const leaderCard = await fetchCard(detail.leader);
        const cardMap = new Map<string, Awaited<ReturnType<typeof fetchCard>>>();
        for (const e of detail.main) {
          if (cardMap.has(e.card_id)) continue;
          try {
            cardMap.set(e.card_id, await fetchCard(e.card_id));
          } catch {
            // 個別失敗はスキップ
          }
        }
        if (cancelled) return;
        // store を初期化
        reset();
        setLeader(leaderCard);
        setName(detail.name ?? `${fromSlug} のコピー`);
        for (const e of detail.main) {
          const card = cardMap.get(e.card_id);
          if (!card) continue;
          for (let i = 0; i < e.count; i++) {
            addCard(card);
          }
        }
        setFlash(`${detail.name ?? fromSlug} をロードしました (${detail.main.reduce((s, x) => s + x.count, 0)} 枚)`);
        setTimeout(() => setFlash(null), 3000);
      } catch (e) {
        setFlash(`ロード失敗: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        if (!cancelled) setHydrating(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromSlug]);

  const total = entries.reduce((s, e) => s + e.count, 0);
  const valid = total === 50 && leader !== null;

  const coreCardIds = new Set(
    coreInput.split(/[\s,、]+/).map((s) => s.trim()).filter(Boolean),
  );

  const onToggleCore = (card: { card_id: string }) => {
    const id = card.card_id;
    setCoreInput((prev) => {
      const ids = prev.split(/[\s,、]+/).map((s) => s.trim()).filter(Boolean);
      if (ids.includes(id)) return ids.filter((x) => x !== id).join(" ");
      return prev.trim() ? `${prev.trim()} ${id}` : id;
    });
  };

  const showFlash = (msg: string, ttlMs = 2000) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), ttlMs);
  };

  const onAutoBuild = async () => {
    if (!leader) {
      showFlash("先にリーダーを選んでください");
      return;
    }
    const cores = coreInput
      .split(/[\s,、]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    setAutoBuilding(true);
    try {
      const result = await buildDeckWithCore({
        leader: leader.card_id,
        core_cards: cores,
        name: name || undefined,
      });
      // 結果を store に流し込む (既存 main をリセット)
      const cardMap = new Map<string, Awaited<ReturnType<typeof fetchCard>>>();
      for (const e of result.main) {
        if (cardMap.has(e.card_id)) continue;
        try {
          cardMap.set(e.card_id, await fetchCard(e.card_id));
        } catch {
          // 失敗はスキップ
        }
      }
      // 全カード削除して再構築。 レギュレーション(STD/EX)は維持する
      // (reset() が standard に戻すため、 現在値を退避して復元)。
      const keepRegulation = regulation;
      reset();
      setRegulation(keepRegulation);
      setLeader(leader);
      setName(result.name);
      for (const e of result.main) {
        const card = cardMap.get(e.card_id);
        if (!card) continue;
        for (let i = 0; i < e.count; i++) addCard(card);
      }
      const wstr = result.warnings.length > 0
        ? ` (warnings: ${result.warnings.length})`
        : "";
      showFlash(
        `自動構築完了: ${result.main.reduce((s, e) => s + e.count, 0)} 枚 / effect ${result.effect_density} / counter ${result.counter_total}${wstr}`,
        4000,
      );
    } catch (e) {
      showFlash(`自動構築失敗: ${e instanceof Error ? e.message : String(e)}`, 4000);
    } finally {
      setAutoBuilding(false);
    }
  };

  // サーバ保存。 draft=true は下書き (未完成でも可、 マイデッキに (下書き) 表示・対戦選択肢外)。
  // draft=false は完成保存 (50枚 validate、 保存後デッキ詳細へ)。 同名は同 slug で上書き
  // (下書き→完成の finalize もこれで成立、 backend が下書きは overwrite 可)。
  const saveToServer = async (draft: boolean) => {
    if (!leader) {
      showFlash("先にリーダーを選んでください", 3000);
      return;
    }
    if (!draft && !valid) {
      showFlash(`完成保存は 合計 ${total}/50 枚にしてください (下書きなら未完成でも保存できます)`, 4000);
      return;
    }
    setSaving(true);
    try {
      const deckName = name && name.trim() ? name.trim() : `${leader.name} 自作`;
      const res = await saveDeckToServer({
        name: deckName,
        leader: leader.card_id,
        main: entries.map((e) => ({ card_id: e.card.card_id, count: e.count })),
        regulation,
        private: isPrivate,
        draft,
        overwrite: draft ? true : undefined,
      });
      if (draft) {
        showFlash(`下書きをマイデッキに保存しました (slug: ${res.slug})`, 3000);
      } else {
        showFlash(`サーバ保存しました (slug: ${res.slug}) → デッキ詳細へ移動`, 3000);
        setTimeout(() => router.push(`/decks/${res.slug}`), 600);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      showFlash(`${draft ? "下書き保存" : "サーバ保存"}失敗: ${msg}`, 5000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="flex h-full w-full flex-col gap-4 overflow-hidden px-6 py-6">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href="/decks"
            className="inline-flex items-center gap-1 text-sm text-[color:var(--text-muted)] hover:underline"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M15 18l-6-6 6-6" />
            </svg>
            マイデッキ
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--text-strong)]">
            デッキを作る
            {hydrating && (
              <span className="ml-2 text-xs text-[color:var(--text-muted)]">ロード中…</span>
            )}
          </h1>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-[var(--radius-sm)] border border-[color:var(--border-2)] text-sm overflow-hidden">
            <button
              type="button"
              onClick={() => setRegulation("standard")}
              className={`px-3 py-1 font-medium transition ${
                regulation === "standard"
                  ? "bg-[color:var(--brand)] text-white"
                  : "bg-transparent text-[color:var(--text-muted)] hover:bg-[var(--list-hover)]"
              }`}
            >
              STD
            </button>
            <button
              type="button"
              onClick={() => setRegulation("extra")}
              className={`px-3 py-1 font-medium transition ${
                regulation === "extra"
                  ? "bg-[color:var(--brand)] text-white"
                  : "bg-transparent text-[color:var(--text-muted)] hover:bg-[var(--list-hover)]"
              }`}
            >
              EX
            </button>
          </div>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="デッキ名"
            className="rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-sm text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
          />
          <span
            className={`rounded-[var(--radius-sm)] px-2 py-1 font-mono text-sm ${
              valid
                ? "bg-[color:var(--accent)]/15 text-[color:var(--accent)]"
                : "bg-[color:var(--surface-2)] text-[color:var(--text-default)]"
            }`}
          >
            {total}/50
          </span>
          <button
            type="button"
            onClick={() => saveToServer(true)}
            disabled={!leader || saving}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-[color:var(--border-2)] px-3 py-1.5 text-sm font-medium text-[color:var(--text-default)] transition hover:bg-[var(--list-hover)] disabled:opacity-50"
            title="未完成でもマイデッキに下書き保存 (対戦の選択肢には出ません)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
              <path d="M17 21v-8H7v8M7 3v5h7" />
            </svg>
            下書き
          </button>
          <button
            type="button"
            onClick={() => setIsPrivate((v) => !v)}
            aria-pressed={isPrivate}
            title={
              isPrivate
                ? "非公開: 陣取りの防衛に使われません（相手に露出しない）。作成後は変更できません。クリックで公開に切替。"
                : "公開: 陣取りで使えます（占領すると相手が対戦）。クリックで非公開に切替。作成後は変更できません。"
            }
            className={`inline-flex items-center gap-1.5 rounded-[var(--radius)] border px-2.5 py-1.5 text-sm font-medium transition ${
              isPrivate
                ? "border-transparent bg-orange-500 text-white hover:bg-orange-600"
                : "border-[color:var(--border-2)] text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
            }`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <rect x="3" y="11" width="18" height="11" rx="2" />
              {/* 非公開=閉じた鍵 / 公開=開いた鍵 */}
              <path d={isPrivate ? "M7 11V7a5 5 0 0 1 10 0v4" : "M7 11V7a5 5 0 0 1 9.9-1"} />
            </svg>
            {/* 公開(2字)/非公開(3字) で幅が変わらないよう固定幅 + 中央寄せ */}
            <span className="min-w-[3em] text-center">{isPrivate ? "非公開" : "公開"}</span>
          </button>
          <button
            type="button"
            onClick={() => saveToServer(false)}
            disabled={!leader || !valid || saving}
            className="rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-1.5 text-sm font-medium text-white transition hover:bg-[color:var(--brand-strong)] disabled:opacity-50"
            title="API 経由で decks/<slug>.json に保存"
          >
            {saving ? "保存中…" : "サーバ保存"}
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm("リセットしますか?")) reset();
            }}
            className="rounded-[var(--radius)] border border-[color:var(--border-2)] px-3 py-1.5 text-sm text-[color:var(--text-default)] transition hover:bg-[var(--list-hover)]"
          >
            リセット
          </button>
        </div>
      </header>

      {flash && (
        <div className="shrink-0 rounded-[var(--radius)] border border-[color:var(--accent)]/40 bg-[color:var(--accent)]/10 px-3 py-2 text-sm text-[color:var(--accent)]">
          {flash}
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-x-auto">
        {/* 左: デッキ列 (ドラッグでリサイズ + 独立スクロール) */}
        <aside
          style={{ width: left.width }}
          className="min-h-0 shrink-0 space-y-4 overflow-y-auto log-scroll pr-1"
        >
          <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
            <h2 className="text-sm font-medium text-[color:var(--text-strong)]">リーダー</h2>
            <LeaderPicker current={leader} onPick={setLeader} />
          </section>

          {leader && (
            <>
              <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
                <h2 className="text-sm font-medium text-[color:var(--text-strong)]">自動構築 (コアカード固定)</h2>
                <p className="text-xs text-[color:var(--text-muted)]">
                  使いたい card_id を改行/スペース/カンマ区切りで入力 (例: <code>OP15-077 OP15-076</code>)。
                  リーダー色合致 + effect 濃度高めの 50 枚を自動生成。
                </p>
                <textarea
                  value={coreInput}
                  onChange={(e) => setCoreInput(e.target.value)}
                  rows={3}
                  placeholder="OP15-077 OP15-076 OP15-075"
                  className="w-full resize-y rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 font-mono text-xs text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
                />
                <button
                  type="button"
                  onClick={onAutoBuild}
                  disabled={autoBuilding}
                  className="inline-flex w-full items-center justify-center gap-1.5 rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-1.5 text-sm font-medium text-white transition hover:bg-[color:var(--brand-strong)] disabled:opacity-50"
                >
                  {autoBuilding ? (
                    "構築中…"
                  ) : (
                    <>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                        <path d="M12 2l1.9 6.4L20 10l-6.1 1.6L12 18l-1.9-6.4L4 10l6.1-1.6z" />
                        <path d="M18.5 13l.9 2.9L22 16.5l-2.6.6L18.5 20l-.9-2.9L15 16.5l2.6-.6z" />
                      </svg>
                      自動構築
                    </>
                  )}
                </button>
              </section>

              <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
                <h2 className="text-sm font-medium text-[color:var(--text-strong)]">コストカーブ</h2>
                <CostCurveMini entries={entries} />
              </section>

              <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
                <h2 className="text-sm font-medium text-[color:var(--text-strong)]">デッキ ({total} 枚)</h2>
                <BuilderSidebar
                  entries={entries}
                  onIncrement={(cid) => {
                    const err = increment(cid);
                    if (err) showFlash(err);
                  }}
                  onDecrement={decrement}
                  onRemove={removeCard}
                />
              </section>
            </>
          )}
        </aside>

        <ResizeHandle onMouseDown={left.onMouseDown} />

        {/* 中: カード検索 (flex-1、 カードをホバーで右に拡大) */}
        <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
          <h2 className="shrink-0 text-sm font-medium text-[color:var(--text-strong)]">カード検索</h2>
          <CardSearchPane
            fillHeight
            onHover={setHoveredCard}
            leaderColors={leader?.color ?? []}
            onAdd={(c) => {
              const err = addCard(c);
              if (err) showFlash(err);
            }}
            countOf={(cid) => countByBaseId(cid)}
            onMarkCore={onToggleCore}
            coreCardIds={coreCardIds}
          />
        </section>

        <ResizeHandle onMouseDown={preview.onMouseDown} />

        {/* 右: 拡大プレビュー (ドラッグでリサイズ、 カードホバーで表示) */}
        <div
          style={{ width: preview.width }}
          className="min-h-0 shrink-0 overflow-y-auto log-scroll rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3"
        >
          <CardPreviewPane card={hoveredCard} />
        </div>
      </div>
    </main>
  );
}

// 右の拡大プレビュー: ホバー中のカードを大きく + 主要情報を表示。 未ホバーは案内文。
function CardPreviewPane({ card }: { card: Card | null }) {
  if (!card) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-2 text-center text-xs text-[color:var(--text-muted)]">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M3 9h18M9 21V9" />
        </svg>
        <span>
          カードにカーソルを合わせると
          <br />
          ここに拡大表示されます
        </span>
      </div>
    );
  }
  const chip =
    "rounded-[var(--radius-sm)] bg-[color:var(--surface-2)] px-1.5 py-0.5 text-[color:var(--text-default)]";
  return (
    <div className="flex flex-col gap-3">
      <CardImage
        cardId={card.card_id}
        alt={card.name}
        className="w-full rounded-[var(--radius)] border border-[color:var(--border-1)]"
      />
      <div className="space-y-1.5">
        <div className="text-sm font-semibold leading-tight text-[color:var(--text-strong)]">{card.name}</div>
        <div className="font-mono text-[11px] text-[color:var(--text-muted)]">{card.card_id}</div>
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          <span className={chip}>{card.category}</span>
          <span className={chip}>コスト {card.cost}</span>
          {card.category !== "EVENT" && <span className={chip}>パワー {card.power}</span>}
          {card.counter > 0 && <span className={chip}>カウンター {card.counter}</span>}
          {card.color.map((col) => (
            <span key={col} className={chip}>{col}</span>
          ))}
        </div>
        {card.features.length > 0 && (
          <div className="text-[11px] text-[color:var(--text-muted)]">特徴: {card.features.join(" / ")}</div>
        )}
      </div>
      {card.text && (
        <div className="whitespace-pre-wrap rounded-[var(--radius)] bg-[color:var(--surface-2)] p-2 text-xs leading-relaxed text-[color:var(--text-default)]">
          {card.text}
        </div>
      )}
      {card.trigger && (
        <div className="whitespace-pre-wrap rounded-[var(--radius)] border border-[color:var(--accent)]/40 bg-[color:var(--accent)]/10 p-2 text-xs leading-relaxed text-[color:var(--accent)]">
          <span className="font-semibold">トリガー:</span> {card.trigger}
        </div>
      )}
    </div>
  );
}
