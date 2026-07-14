"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Card } from "@/lib/types";
import { banInfoFor, type BanInfo } from "@/lib/banlist";
import { CardTile } from "./CardTile";
import { CardDetailModal } from "./CardDetailModal";

const BATCH = 48;
const ATTRIBUTES = ["斬", "打", "射", "特", "知"] as const;

type Sort =
  | "default"
  | "cost_asc"
  | "cost_desc"
  | "power_asc"
  | "power_desc"
  | "name";

// 規制フィルタ: "" = 不問 / "any" = 何らか規制 / それ以外は BanKind 一致
type BanFilter = "" | "any" | "forbidden" | "restricted" | "pair";

const SORT_LABELS: Record<Sort, string> = {
  default: "既定 (DB順)",
  cost_asc: "コスト昇順",
  cost_desc: "コスト降順",
  power_asc: "パワー昇順",
  power_desc: "パワー降順",
  name: "名前順",
};

const selectClass =
  "rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-sm text-[color:var(--text-default)] outline-none focus:border-[color:var(--brand)]";
const numClass =
  "w-20 rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]";

/**
 * クライアント側の二次絞り込み (パワー / 属性 / カウンター / トリガー) + 並び替え +
 * スクロール ページネーション (= IntersectionObserver で BATCH 件ずつ追加表示)。
 * サーバ側フィルタ (色 / カテゴリ / 特徴 / コスト / 名前 / レギュレーション) で
 * 取得済みの cards を受け取り、 即時に絞り込む (= 再 fetch なし)。
 */
export function CardBrowser({
  cards,
  banStatus = {},
}: {
  cards: Card[];
  banStatus?: Record<string, BanInfo>;
}) {
  const [selected, setSelected] = useState<Card | null>(null);
  const [powerMin, setPowerMin] = useState("");
  const [powerMax, setPowerMax] = useState("");
  const [attribute, setAttribute] = useState("");
  const [counterMin, setCounterMin] = useState("");
  const [triggerOnly, setTriggerOnly] = useState(false);
  const [banFilter, setBanFilter] = useState<BanFilter>("");
  const [sort, setSort] = useState<Sort>("default");
  const [visible, setVisible] = useState(BATCH);

  const filtered = useMemo(() => {
    const pmin = powerMin === "" ? null : Number(powerMin);
    const pmax = powerMax === "" ? null : Number(powerMax);
    const cmin = counterMin === "" ? null : Number(counterMin);
    let out = cards.filter((c) => {
      if (pmin != null && c.power < pmin) return false;
      if (pmax != null && c.power > pmax) return false;
      if (attribute && !(c.attribute || "").includes(attribute)) return false;
      if (cmin != null && c.counter < cmin) return false;
      if (triggerOnly && !c.trigger) return false;
      if (banFilter) {
        const ban = banInfoFor(banStatus, c.card_id);
        if (banFilter === "any" && !ban) return false;
        if (banFilter !== "any" && ban?.kind !== banFilter) return false;
      }
      return true;
    });
    const cmp: Record<Sort, ((a: Card, b: Card) => number) | null> = {
      default: null,
      cost_asc: (a, b) => a.cost - b.cost,
      cost_desc: (a, b) => b.cost - a.cost,
      power_asc: (a, b) => a.power - b.power,
      power_desc: (a, b) => b.power - a.power,
      name: (a, b) => a.name.localeCompare(b.name, "ja"),
    };
    const fn = cmp[sort];
    if (fn) out = [...out].sort(fn);
    return out;
  }, [cards, powerMin, powerMax, attribute, counterMin, triggerOnly, banFilter, banStatus, sort]);

  // 絞り込み結果が変わったら表示件数をリセット
  useEffect(() => {
    setVisible(BATCH);
  }, [filtered]);

  // スクロール ページネーション: sentinel が見えたら BATCH 件追加
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setVisible((v) => Math.min(v + BATCH, filtered.length));
        }
      },
      { rootMargin: "600px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [filtered.length]);

  const refined =
    filtered.length !== cards.length ? `絞り込み後 ${filtered.length} 件 / ` : "";
  const shown = Math.min(visible, filtered.length);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3 text-xs">
        <span className="font-medium text-[color:var(--text-muted)]">絞り込み</span>

        <label className="flex items-center gap-1 text-[color:var(--text-muted)]">
          パワー
          <input
            type="number"
            step={1000}
            min={0}
            value={powerMin}
            onChange={(e) => setPowerMin(e.target.value)}
            placeholder="最小"
            className={numClass}
            aria-label="パワー最小"
          />
          〜
          <input
            type="number"
            step={1000}
            min={0}
            value={powerMax}
            onChange={(e) => setPowerMax(e.target.value)}
            placeholder="最大"
            className={numClass}
            aria-label="パワー最大"
          />
        </label>

        <select
          value={attribute}
          onChange={(e) => setAttribute(e.target.value)}
          className={selectClass}
          aria-label="属性"
        >
          <option value="">全属性</option>
          {ATTRIBUTES.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        <select
          value={counterMin}
          onChange={(e) => setCounterMin(e.target.value)}
          className={selectClass}
          aria-label="カウンター"
        >
          <option value="">カウンター不問</option>
          <option value="1000">カウンター 1000+</option>
          <option value="2000">カウンター 2000+</option>
        </select>

        <button
          type="button"
          onClick={() => setTriggerOnly((v) => !v)}
          aria-pressed={triggerOnly}
          className={`rounded-[var(--radius-sm)] px-2 py-1 font-medium ${
            triggerOnly
              ? "bg-[color:var(--brand)] text-white"
              : "bg-[color:var(--surface-2)] text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
          }`}
        >
          トリガー有り
        </button>

        <select
          value={banFilter}
          onChange={(e) => setBanFilter(e.target.value as BanFilter)}
          className={selectClass}
          aria-label="規制"
        >
          <option value="">規制不問</option>
          <option value="any">規制カードのみ</option>
          <option value="forbidden">禁止のみ</option>
          <option value="restricted">制限のみ</option>
          <option value="pair">ペア禁止のみ</option>
        </select>

        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          className={`${selectClass} ml-auto`}
          aria-label="並び替え"
        >
          {(Object.keys(SORT_LABELS) as Sort[]).map((s) => (
            <option key={s} value={s}>
              {SORT_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      <div className="text-xs text-[color:var(--text-muted)]">
        {refined}
        {filtered.length > 0 ? `${shown} 件 表示中` : ""}
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-6 text-center text-sm text-[color:var(--text-muted)]">
          該当するカードがありません
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {filtered.slice(0, visible).map((c) => (
              <CardTile
                key={c.card_id}
                card={c}
                onClick={setSelected}
                ban={banInfoFor(banStatus, c.card_id)}
              />
            ))}
          </div>
          {/* スクロール ページネーション用 sentinel */}
          <div ref={sentinelRef} className="h-1" aria-hidden />
          {shown < filtered.length && (
            <div className="py-4 text-center text-xs text-[color:var(--text-muted)]">
              スクロールで さらに 読み込み… ({shown} / {filtered.length})
            </div>
          )}
        </>
      )}

      <CardDetailModal
        card={selected}
        onClose={() => setSelected(null)}
        ban={selected ? banInfoFor(banStatus, selected.card_id) : undefined}
      />
    </div>
  );
}
