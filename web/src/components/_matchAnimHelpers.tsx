"use client";

/**
 * HumanMatchPlay 用 animation helpers。
 *
 * 提供:
 * - useFrameDiff: 前回 snapshot を 保持 し 現 snapshot との 差分 (life delta / chara
 *   登場退場 / don delta / attack event) を 返す
 * - LifeFlashOverlay: ライフ 減/増 を フィールド 全体 に flash overlay で 表示
 * - DamageNumber: 攻撃 命中 時 に 数値 を ポップアップ
 * - useNumberCountUp: 数値 が 変わる 時 に カウントアップ animation
 *
 * 設計:
 * - framer-motion AnimatePresence + layoutId は 呼び出し側 (= HumanMatchPlay) で
 *   character の outer div に 適用。 ここでは 補助 utility のみ 提供。
 */

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { StateSnapshot, CharSnapshot } from "@/lib/types";
import { CardImage } from "./CardImage";

// --------------------------------------------------------------------------
// snapshot diff hook
// --------------------------------------------------------------------------

export type FrameDiff = {
  // 各 player の life 変化 (= 正 = 減、 負 = 増)。
  // life は 個別 card 識別 不能 なので count delta のみ。
  lifeDelta: [number, number];
  // 各 player の hand_count 変化
  handDelta: [number, number];
  // 各 player の don 変化 (= active+rested-deck合算)
  donDelta: [number, number];
  // 場に新規登場した chara の iid (= player 別)
  enteredIids: [Set<number>, Set<number>];
  // 場から消えた chara の iid + 該当 snapshot (= player 別)
  leftCharas: [CharSnapshot[], CharSnapshot[]];
  // trash 末尾 に 新規追加された card_id (= event / counter / 効果 で 捨てられた)
  // 場のキャラが KO で trash に行った場合は leftCharas で扱う想定なので 重複もあり得る
  trashAdded: [string[], string[]];
  // event (= AttackEvent) の identity 更新 (= 同 event の 再 trigger 検知)
  eventTickId: number;
  // フィールド全体 を flash させる ヒント (= life 減 or 重大 event)
  shouldFieldFlash: boolean;
};

const EMPTY_DIFF: FrameDiff = {
  lifeDelta: [0, 0],
  handDelta: [0, 0],
  donDelta: [0, 0],
  enteredIids: [new Set(), new Set()],
  leftCharas: [[], []],
  trashAdded: [[], []],
  eventTickId: 0,
  shouldFieldFlash: false,
};

export function useFrameDiff(snap: StateSnapshot | null): FrameDiff {
  const prevRef = useRef<StateSnapshot | null>(null);
  const tickRef = useRef(0);
  const [diff, setDiff] = useState<FrameDiff>(EMPTY_DIFF);

  useEffect(() => {
    if (!snap) {
      prevRef.current = null;
      setDiff(EMPTY_DIFF);
      return;
    }
    const prev = prevRef.current;
    if (!prev) {
      prevRef.current = snap;
      setDiff(EMPTY_DIFF);
      return;
    }
    // 同 snapshot (= 参照 同一) なら 差分 0
    if (prev === snap) return;

    const lifeDelta: [number, number] = [
      (prev.players[0]?.life_count ?? 0) - (snap.players[0]?.life_count ?? 0),
      (prev.players[1]?.life_count ?? 0) - (snap.players[1]?.life_count ?? 0),
    ];
    const handDelta: [number, number] = [
      (snap.players[0]?.hand_count ?? 0) - (prev.players[0]?.hand_count ?? 0),
      (snap.players[1]?.hand_count ?? 0) - (prev.players[1]?.hand_count ?? 0),
    ];
    const donTotal = (p: typeof snap.players[0]) =>
      (p?.don_active ?? 0) + (p?.don_rested ?? 0);
    const donDelta: [number, number] = [
      donTotal(snap.players[0]) - donTotal(prev.players[0]),
      donTotal(snap.players[1]) - donTotal(prev.players[1]),
    ];

    const enteredIids: [Set<number>, Set<number>] = [new Set(), new Set()];
    const leftCharas: [CharSnapshot[], CharSnapshot[]] = [[], []];
    const trashAdded: [string[], string[]] = [[], []];
    for (let p = 0; p < 2; p++) {
      const prevChars = prev.players[p]?.characters ?? [];
      const curChars = snap.players[p]?.characters ?? [];
      const prevIids = new Set(prevChars.map((c) => c.instance_id));
      const curIids = new Set(curChars.map((c) => c.instance_id));
      for (const c of curChars) {
        if (!prevIids.has(c.instance_id)) enteredIids[p].add(c.instance_id);
      }
      for (const c of prevChars) {
        if (!curIids.has(c.instance_id)) leftCharas[p].push(c);
      }
      // trash 末尾 に 追加された card_id (= count 差分 を 末尾 から 取得)
      const prevTrash = prev.players[p]?.trash ?? [];
      const curTrash = snap.players[p]?.trash ?? [];
      const addedN = curTrash.length - prevTrash.length;
      if (addedN > 0) {
        trashAdded[p] = curTrash.slice(prevTrash.length);
      }
    }

    const shouldFieldFlash =
      lifeDelta[0] > 0 ||
      lifeDelta[1] > 0 ||
      leftCharas[0].length > 0 ||
      leftCharas[1].length > 0;

    tickRef.current += 1;
    prevRef.current = snap;
    setDiff({
      lifeDelta,
      handDelta,
      donDelta,
      enteredIids,
      leftCharas,
      trashAdded,
      eventTickId: tickRef.current,
      shouldFieldFlash,
    });
  }, [snap]);

  return diff;
}

// --------------------------------------------------------------------------
// ManualLifeFlashOverlay: 明示的 に 発火 する LIFE -N flash (= ライフ取得 確認 modal
// 前 に 「LIFE -1 演出」 を 先 に 見せる 用)。 fireLifeFlash(side, delta) で 発火、
// auto fade。
// --------------------------------------------------------------------------

type LifeFlashItem = {
  id: number;
  side: "me" | "opp";
  delta: number;
};

let _lifeFlashFire:
  | ((side: "me" | "opp", delta: number) => void)
  | null = null;

export function fireLifeFlash(side: "me" | "opp", delta: number = 1): void {
  if (_lifeFlashFire) _lifeFlashFire(side, delta);
}

export function ManualLifeFlashOverlay(): React.JSX.Element | null {
  const [items, setItems] = useState<LifeFlashItem[]>([]);
  const idRef = useRef(0);
  useEffect(() => {
    _lifeFlashFire = (side, delta) => {
      const id = idRef.current++;
      setItems((prev) => [...prev, { id, side, delta }]);
      setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== id));
      }, 900);
    };
    return () => {
      _lifeFlashFire = null;
    };
  }, []);
  if (items.length === 0) return null;
  return (
    <AnimatePresence>
      {items.map((it) => {
        const color = it.delta > 0 ? "bg-rose-600/40" : "bg-emerald-500/25";
        const label = it.delta > 0 ? `−${it.delta}` : `+${-it.delta}`;
        const labelColor =
          it.delta > 0
            ? "text-red-400 drop-shadow-[0_0_18px_rgba(239,68,68,0.95)]"
            : "text-emerald-200";
        const sideClass =
          it.side === "me" ? "top-1/2 bottom-0" : "top-0 bottom-1/2";
        return (
          <motion.div
            key={it.id}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 1, 0.4, 0] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.85, times: [0, 0.18, 0.55, 1] }}
            className={
              "pointer-events-none absolute left-0 right-0 z-30 flex items-center justify-center " +
              sideClass +
              " " +
              color
            }
          >
            <motion.div
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: [0.5, 1.4, 1.2], opacity: [0, 1, 1] }}
              exit={{ opacity: 0, scale: 1.5 }}
              transition={{ duration: 0.7 }}
              className={
                "rounded-full bg-black/60 px-8 py-3 text-5xl font-extrabold drop-shadow-2xl " +
                labelColor
              }
            >
              LIFE {label}
            </motion.div>
          </motion.div>
        );
      })}
    </AnimatePresence>
  );
}

// --------------------------------------------------------------------------
// LifeFlashOverlay: ライフ 減 / 増 の flash overlay
// --------------------------------------------------------------------------

/** owner: "me"|"opp" の どちら側 の life が 変わったか の flash overlay。
 *  delta 正 = 減 (= red flash)、 delta 負 = 増 (= green flash)。 */
export function LifeFlashOverlay({
  delta,
  side,
  tickId,
}: {
  delta: number;
  side: "me" | "opp";
  tickId: number;
}) {
  if (delta === 0) return null;
  const color = delta > 0 ? "bg-rose-600/40" : "bg-emerald-500/25";
  const label = delta > 0 ? `−${delta}` : `+${-delta}`;
  const labelColor =
    delta > 0
      ? "text-red-400 drop-shadow-[0_0_18px_rgba(239,68,68,0.95)]"
      : "text-emerald-200";
  // side で 上 or 下 を 占有 (= field 全体 ではなく 該当 player 側)
  const sideClass =
    side === "me"
      ? "top-1/2 bottom-0"
      : "top-0 bottom-1/2";
  return (
    <AnimatePresence>
      <motion.div
        key={tickId}
        initial={{ opacity: 0 }}
        animate={{ opacity: [0, 1, 0.4, 0] }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.8, times: [0, 0.15, 0.5, 1] }}
        className={
          "pointer-events-none absolute left-0 right-0 z-30 flex items-center justify-center " +
          sideClass +
          " " +
          color
        }
      >
        <motion.div
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: [0.5, 1.4, 1.2], opacity: [0, 1, 1] }}
          exit={{ opacity: 0, scale: 1.5 }}
          transition={{ duration: 0.7 }}
          className={
            "rounded-full bg-black/60 px-8 py-3 text-5xl font-extrabold drop-shadow-2xl " +
            labelColor
          }
        >
          LIFE {label}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

// --------------------------------------------------------------------------
// LeftCharaGhost: 場 から 消えた chara の 一瞬 fade-out ghost overlay
// --------------------------------------------------------------------------

/** 消えた chara を 短時間 表示 → fade out。 layoutId は 元 chara と 共有 しない
 *  (= 別 表現)。 KO / return_to_hand / chara_to_*_life 等 共通 で 使う 演出。 */
export function LeftCharaGhostList({
  leftCharas,
  side,
  tickId,
}: {
  leftCharas: CharSnapshot[];
  side: "me" | "opp";
  tickId: number;
}) {
  if (leftCharas.length === 0) return null;
  const sideClass = side === "me" ? "bottom-4" : "top-4";
  return (
    <div
      className={
        "pointer-events-none absolute left-1/2 z-40 -translate-x-1/2 " + sideClass
      }
    >
      <AnimatePresence>
        {leftCharas.map((c) => (
          <motion.div
            key={`${tickId}-${c.instance_id}`}
            initial={{ opacity: 1, y: 0, scale: 1, rotate: 0 }}
            animate={{
              opacity: [1, 1, 0],
              y: [0, -8, 40],
              scale: [1, 1.05, 0.8],
              rotate: [0, -3, 12],
            }}
            transition={{ duration: 1.0, times: [0, 0.2, 1] }}
            className="mr-3 inline-block rounded bg-rose-900/70 px-3 py-1 text-sm font-bold text-rose-100 shadow-lg ring-2 ring-rose-300"
          >
            退場: {c.name}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

// --------------------------------------------------------------------------
// PlayedCardOverlay: 手札 から 使用 された カード (= event / counter / 効果 discard) を
// 中央 で 大型表示 → trash 方向 に slide-fade
// --------------------------------------------------------------------------

type PlayedCardItem = {
  id: number;
  cardId: string;
  side: "me" | "opp";
};

/** trashAdded を 拾い、 leftCharas (= 場 KO 経由) を 除外、 残りを 中央 で 演出。
 *
 * side="me" は 下半分 中央 (= 自分側)、 side="opp" は 上半分 中央 (= 相手側)。
 * 1.2 秒 で fade-out + 右端 (= trash 方向) へ slide。
 */
export function PlayedCardOverlay({
  trashAddedMe,
  trashAddedOpp,
  leftCharasMe,
  leftCharasOpp,
  excludeMeCardIds,
  excludeOppCardIds,
  tickId,
}: {
  trashAddedMe: string[];
  trashAddedOpp: string[];
  leftCharasMe: CharSnapshot[];
  leftCharasOpp: CharSnapshot[];
  /** 自分側 trash 移動 で 別 演出 (= CounterPlayOverlay 等) 済 の card_id list を 除外 */
  excludeMeCardIds?: string[];
  /** opp 側 trash 移動 で 別 演出 (= AI counter の CounterPlayOverlay 等) 済 を 除外 */
  excludeOppCardIds?: string[];
  tickId: number;
}) {
  const [items, setItems] = useState<PlayedCardItem[]>([]);
  const nextIdRef = useRef(0);
  const lastTickRef = useRef(-1);
  // 最新 props を ref に 持って useEffect dep から 外す (= tickId 単独 で 1 回 fire 保証)
  const trashAddedMeRef = useRef(trashAddedMe);
  const trashAddedOppRef = useRef(trashAddedOpp);
  const leftCharasMeRef = useRef(leftCharasMe);
  const leftCharasOppRef = useRef(leftCharasOpp);
  const excludeMeRef = useRef(excludeMeCardIds ?? []);
  const excludeOppRef = useRef(excludeOppCardIds ?? []);
  trashAddedMeRef.current = trashAddedMe;
  trashAddedOppRef.current = trashAddedOpp;
  leftCharasMeRef.current = leftCharasMe;
  leftCharasOppRef.current = leftCharasOpp;
  excludeMeRef.current = excludeMeCardIds ?? [];
  excludeOppRef.current = excludeOppCardIds ?? [];

  useEffect(() => {
    if (tickId === lastTickRef.current) return; // 重複 fire 防止
    lastTickRef.current = tickId;
    // 場 から KO で trash に行った card_id を 除外 → 残り が 「手札からの使用」
    function diff(added: string[], chars: CharSnapshot[]): string[] {
      const charPool = chars.map((c) => c.card_id);
      const result: string[] = [];
      const used: number[] = [];
      for (const cid of added) {
        const idx = charPool.findIndex(
          (x, i) => x === cid && !used.includes(i),
        );
        if (idx >= 0) {
          used.push(idx);
          continue;
        }
        result.push(cid);
      }
      return result;
    }
    let meHandPlays = diff(trashAddedMeRef.current, leftCharasMeRef.current);
    let oppHandPlays = diff(
      trashAddedOppRef.current,
      leftCharasOppRef.current,
    );
    // CounterPlayOverlay 等 別 演出 済 card は 除外 (= 自/相手 共通)
    function applyExclude(plays: string[], excludes: string[]): string[] {
      if (excludes.length === 0) return plays;
      const counts: Record<string, number> = {};
      for (const cid of excludes) {
        counts[cid] = (counts[cid] ?? 0) + 1;
      }
      return plays.filter((cid) => {
        if ((counts[cid] ?? 0) > 0) {
          counts[cid] -= 1;
          return false;
        }
        return true;
      });
    }
    meHandPlays = applyExclude(meHandPlays, excludeMeRef.current);
    oppHandPlays = applyExclude(oppHandPlays, excludeOppRef.current);
    if (meHandPlays.length === 0 && oppHandPlays.length === 0) return;
    const additions: PlayedCardItem[] = [
      ...meHandPlays.map((cid) => ({
        id: nextIdRef.current++,
        cardId: cid,
        side: "me" as const,
      })),
      ...oppHandPlays.map((cid) => ({
        id: nextIdRef.current++,
        cardId: cid,
        side: "opp" as const,
      })),
    ];
    setItems((prev) => [...prev, ...additions].slice(-6));
    additions.forEach((it) => {
      setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== it.id));
      }, 1700);
    });
  }, [tickId]);

  if (items.length === 0) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-40">
      <AnimatePresence>
        {items.map((it, idx) => {
          // 開始位置: 手札 方向 から 出現
          //   me (自分): 画面 下 から 上 へ
          //   opp (AI): 画面 上 から 下 へ
          const startY = it.side === "me" ? "85vh" : "-85vh";
          // 横並び 配置 (= 複数 同時 でも 重ならない)
          const xOffset = (idx - items.length / 2) * 130;
          return (
            <motion.div
              key={it.id}
              initial={{
                opacity: 0,
                scale: 0.55,
                x: xOffset,
                y: startY,
                rotate: 0,
              }}
              animate={{
                // 単純 path: 手札位置 → 中央 (= 0.4s で 到達) → 中央 hold (= 0.9s) → fade out
                opacity: [0, 1, 1, 0],
                scale: [0.55, 1.0, 1.0, 0.92],
                x: [xOffset, xOffset, xOffset, xOffset],
                y: [startY, "0%", "0%", "0%"],
                rotate: 0,
              }}
              exit={{ opacity: 0, scale: 0.5 }}
              transition={{
                duration: 1.7,
                times: [0, 0.3, 0.85, 1],
                ease: "easeOut",
              }}
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
            >
              <div
                className={
                  "rounded-lg shadow-2xl ring-4 " +
                  (it.side === "me"
                    ? "ring-emerald-400"
                    : "ring-rose-400")
                }
              >
                <CardImage
                  cardId={it.cardId}
                  alt={it.cardId}
                  className="h-72 w-auto rounded-lg"
                />
              </div>
              <div
                className={
                  "absolute -bottom-2 left-1/2 -translate-x-1/2 rounded-full px-3 py-1 text-xs font-bold text-white shadow " +
                  (it.side === "me"
                    ? "bg-emerald-600"
                    : "bg-rose-600")
                }
              >
                {it.side === "me" ? "YOU 使用" : "AI 使用"}
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// --------------------------------------------------------------------------
// DrawCardOverlay: ドロー 演出 (= デッキ位置 → 手札方向 へ 裏面 カード slide)
// --------------------------------------------------------------------------

type DrawItem = {
  id: number;
  side: "me" | "opp";
  source: "deck" | "life";
  delayIdx: number;
};

export function DrawCardOverlay({
  handDeltaMe,
  handDeltaOpp,
  lifeDeltaMe,
  lifeDeltaOpp,
  tickId,
  boardRef,
}: {
  handDeltaMe: number;
  handDeltaOpp: number;
  /** 同 frame で life-1 起きた → handDelta は 「ライフ→手札」 由来 で DrawOverlay 不適切。 */
  lifeDeltaMe: number;
  lifeDeltaOpp: number;
  tickId: number;
  /** DOM 位置 取得 用 (= deck/life DOM の data-* 属性 を 検索) */
  boardRef: React.RefObject<HTMLDivElement | null>;
}) {
  const [items, setItems] = useState<DrawItem[]>([]);
  const lastTickRef = useRef(-1);
  const nextIdRef = useRef(0);
  const lastFireAtRef = useRef(0);
  const meDeltaRef = useRef(handDeltaMe);
  const oppDeltaRef = useRef(handDeltaOpp);
  const lifeMeRef = useRef(lifeDeltaMe);
  const lifeOppRef = useRef(lifeDeltaOpp);
  meDeltaRef.current = handDeltaMe;
  oppDeltaRef.current = handDeltaOpp;
  lifeMeRef.current = lifeDeltaMe;
  lifeOppRef.current = lifeDeltaOpp;

  useEffect(() => {
    if (tickId === lastTickRef.current) return;
    lastTickRef.current = tickId;
    // 同 frame で lifeDelta>0 と handDelta>0 が 同時 (= life trigger draw):
    //   1 枚 は source=life (= ライフ位置 から)
    //   余剰 hand+N は source=deck (= デッキ位置 から、 別 経路)
    // life trigger ない frame の handDelta は 全 source=deck。
    const meLifeHit = lifeMeRef.current > 0;
    const oppLifeHit = lifeOppRef.current > 0;
    const meN = Math.max(0, Math.min(meDeltaRef.current, 6));
    const oppN = Math.max(0, Math.min(oppDeltaRef.current, 6));
    if (meN === 0 && oppN === 0) return;
    // cooldown 撤回 (= 同 frame 内 で 複数 item OK、 必要 なら delayIdx で 順次)
    lastFireAtRef.current = Date.now();
    const additions: DrawItem[] = [];
    if (meLifeHit && meN > 0) {
      additions.push({
        id: nextIdRef.current++,
        side: "me",
        source: "life",
        delayIdx: 0,
      });
      for (let i = 1; i < meN; i++) {
        additions.push({
          id: nextIdRef.current++,
          side: "me",
          source: "deck",
          delayIdx: i + 2, // 大幅 遅延 (= life trigger 完了後)
        });
      }
    } else {
      for (let i = 0; i < meN; i++) {
        additions.push({
          id: nextIdRef.current++,
          side: "me",
          source: "deck",
          delayIdx: i,
        });
      }
    }
    if (oppLifeHit && oppN > 0) {
      additions.push({
        id: nextIdRef.current++,
        side: "opp",
        source: "life",
        delayIdx: 0,
      });
      for (let i = 1; i < oppN; i++) {
        additions.push({
          id: nextIdRef.current++,
          side: "opp",
          source: "deck",
          delayIdx: i + 2,
        });
      }
    } else {
      for (let i = 0; i < oppN; i++) {
        additions.push({
          id: nextIdRef.current++,
          side: "opp",
          source: "deck",
          delayIdx: i,
        });
      }
    }
    setItems((prev) => [...prev, ...additions].slice(-12));
    additions.forEach((it) => {
      // life trigger 後 の deck draw は 1.2 秒 遅延 + 850ms 表示
      // 通常 は 650 + idx * 80ms
      const isLifeChained = it.source === "deck" && it.delayIdx >= 2;
      const dismiss = isLifeChained
        ? 1200 + 850
        : 650 + it.delayIdx * 80;
      setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== it.id));
      }, dismiss);
    });
  }, [tickId]);

  if (items.length === 0) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-30">
      <AnimatePresence>
        {items.map((it) => {
          const isMe = it.side === "me";
          const isLife = it.source === "life";
          // DOM 位置 を 取得 (= boardRef 内 で data-deck-side / data-life-side 検索)
          const board = boardRef.current;
          let startX = 0;
          let startY = 0;
          let endX = 0;
          let endY = 0;
          if (board) {
            const br = board.getBoundingClientRect();
            const sel = isLife
              ? `[data-life-side="${it.side}"]`
              : `[data-deck-side="${it.side}"]`;
            const el = board.querySelector(sel) as HTMLElement | null;
            if (el) {
              const er = el.getBoundingClientRect();
              startX = er.left + er.width / 2 - br.left - br.width / 2;
              startY = er.top + er.height / 2 - br.top - br.height / 2;
            }
            // 手札 DOM 位置 取得 (= data-hand-side で 識別)
            const handSel = isMe
              ? '[data-hand-side="me"]'
              : '[data-hand-side="opp"]';
            const hand = document.querySelector(handSel) as HTMLElement | null;
            if (hand) {
              const hr = hand.getBoundingClientRect();
              endX = hr.left + hr.width / 2 - br.left - br.width / 2;
              endY = hr.top + hr.height / 2 - br.top - br.height / 2;
            } else {
              endX = 0;
              endY = isMe ? br.height / 2 - 60 : -(br.height / 2 - 60);
            }
          }
          const ringColor = isLife
            ? "ring-orange-300"
            : isMe
              ? "ring-emerald-300"
              : "ring-rose-300";
          // life trigger 後 の deck draw (= 同 frame 内 で 連鎖) は 大幅 遅延
          const isLifeChained = !isLife && it.delayIdx >= 2;
          const delay = isLifeChained ? 1.2 : it.delayIdx * 0.08;
          return (
            <motion.div
              key={it.id}
              initial={{
                opacity: 0,
                scale: 0.7,
                x: startX,
                y: startY,
              }}
              animate={{
                opacity: [0, 1, 1, 0],
                scale: [0.7, 1.0, 1.0, 0.9],
                x: [startX, startX, endX, endX],
                y: [startY, startY, endY, endY],
              }}
              exit={{ opacity: 0 }}
              transition={{
                duration: isLife ? 0.8 : 0.6,
                delay,
                times: [0, 0.15, 0.85, 1],
                ease: "easeInOut",
              }}
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
            >
              <img
                src="/assets/ura.png"
                alt={isLife ? "life trigger draw" : "draw"}
                className={
                  "h-32 w-24 rounded shadow-2xl ring-2 " + ringColor
                }
              />
              {isLife && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-orange-500 px-2 py-0.5 text-[10px] font-bold text-white shadow">
                  LIFE!
                </div>
              )}
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// --------------------------------------------------------------------------
// OppActionBanner: 自ターン中 に AI 効果 (= 「相手ターン開始時」 trigger 等) で
// AI が play / 効果発動 した時 に 「[AI 効果] play」 banner を 表示
// --------------------------------------------------------------------------

export function OppActionBanner({
  isHumanTurn,
  oppEnteredCount,
  tickId,
}: {
  isHumanTurn: boolean;
  oppEnteredCount: number;
  tickId: number;
}) {
  const [showItem, setShowItem] = useState<{ id: number; n: number } | null>(
    null,
  );
  const idRef = useRef(0);
  const lastTickRef = useRef(-1);
  useEffect(() => {
    if (tickId === lastTickRef.current) return;
    lastTickRef.current = tickId;
    if (!isHumanTurn || oppEnteredCount <= 0) return;
    const id = idRef.current++;
    setShowItem({ id, n: oppEnteredCount });
    const t = setTimeout(() => {
      setShowItem((cur) => (cur?.id === id ? null : cur));
    }, 1800);
    return () => clearTimeout(t);
  }, [tickId, isHumanTurn, oppEnteredCount]);

  if (!showItem) return null;
  return (
    <div className="pointer-events-none absolute top-24 left-1/2 z-[57] -translate-x-1/2">
      <motion.div
        key={showItem.id}
        initial={{ opacity: 0, y: -20, scale: 0.7 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.4 }}
        className="rounded-lg border-2 border-rose-300 bg-rose-900/85 px-5 py-2 text-base font-bold text-rose-100 shadow-lg backdrop-blur"
      >
        [AI 効果] キャラ {showItem.n} 枚 を 場 に 出した
      </motion.div>
    </div>
  );
}

// --------------------------------------------------------------------------
// TurnBannerOverlay: ターン 切替 時 「YOUR TURN」 / 「OPPONENT TURN」 大型 banner
// --------------------------------------------------------------------------

export function TurnBannerOverlay({
  turnPlayerIdx,
  humanIdx,
  hasMulliganPending,
  pendingKind,
}: {
  turnPlayerIdx: number;
  humanIdx: number;
  /** マリガン modal 中 は ○○のターン banner は 出さない (= ターン 概念前)。
   *  ただし 「先攻/後攻」 banner は mulligan 前 に 必ず 表示する。 */
  hasMulliganPending?: boolean;
  /** "action" (= 自分 操作可能) で fire 確定。 中間 frame で 早期 fire 防止。 */
  pendingKind?: string | null;
}) {
  type TurnBanner = {
    id: number;
    kind: "turn";
    label: string;
    color: "self" | "opp";
  };
  type FirstOrderBanner = {
    id: number;
    kind: "first_order";
    /** humanIsFirst=true → 左 (先攻) が 緑、 右 (後攻) が 赤。 false で 逆。 */
    humanIsFirst: boolean;
  };
  type BannerItem = TurnBanner | FirstOrderBanner;
  const [queue, setQueue] = useState<BannerItem[]>([]);
  const [showItem, setShowItem] = useState<BannerItem | null>(null);
  const prevTurnRef = useRef<number>(-1);
  const firstOrderEnqueuedRef = useRef(false);
  const idRef = useRef(0);

  useEffect(() => {
    const isMe = turnPlayerIdx === humanIdx;
    const additions: BannerItem[] = [];

    // 初回 (= 試合 start) は 「先攻/後攻」 banner を 先 enqueue。
    // mulligan 中 でも 表示 (= 順序: 先攻後攻 → mulligan modal → ○○のターン)。
    if (!firstOrderEnqueuedRef.current) {
      firstOrderEnqueuedRef.current = true;
      additions.push({
        id: idRef.current++,
        kind: "first_order",
        humanIsFirst: isMe,
      });
    }

    // ○○のターン banner: mulligan 中 は 出さない。 mulligan 解消 後 の
    // turn 確定 で fire。 turn 切替 (= playFrames 中 の 中間 frame で
    // turn_player_idx が 変わる 時) で も fire。
    if (!hasMulliganPending) {
      const prev = prevTurnRef.current;
      if (prev !== turnPlayerIdx) {
        prevTurnRef.current = turnPlayerIdx;
        additions.push({
          id: idRef.current++,
          kind: "turn",
          label: isMe ? "人間 の ターン" : "AI の ターン",
          color: isMe ? "self" : "opp",
        });
      }
    }

    if (additions.length > 0) {
      setQueue((q) => [...q, ...additions]);
    }
    void pendingKind;
  }, [turnPlayerIdx, humanIdx, hasMulliganPending, pendingKind]);

  // queue を 順次 1.5 秒 ずつ 表示 (= 連続 fire を 上書き せず 全 表示)。
  // cleanup で clearTimeout しない (= queue 変化 で 旧 timeout cancel され dismiss
  // 不能 になる 問題 解消)。 旧 timeout も そのまま fire で showItem null に。
  useEffect(() => {
    if (showItem !== null) return;
    if (queue.length === 0) return;
    const next = queue[0];
    setShowItem(next);
    setQueue((q) => q.slice(1));
    setTimeout(() => setShowItem(null), 1500);
  }, [showItem, queue]);

  return (
    <div className="pointer-events-none fixed inset-0 z-[58] flex items-center justify-center">
      <AnimatePresence>
        {showItem && showItem.kind === "turn" && (
          <motion.div
            key={showItem.id}
            initial={{ opacity: 0, x: -300 }}
            animate={{
              opacity: [0, 1, 1, 0],
              x: [-300, 0, 0, 300],
            }}
            transition={{
              duration: 1.5,
              times: [0, 0.18, 0.7, 1],
              ease: "easeOut",
            }}
            exit={{ opacity: 0 }}
            className={
              "rounded-2xl border-4 px-20 py-8 text-center shadow-2xl backdrop-blur " +
              (showItem.color === "self"
                ? "border-emerald-300 bg-emerald-900/80"
                : "border-rose-300 bg-rose-900/80")
            }
          >
            <div
              className={
                "text-6xl font-extrabold drop-shadow-[0_0_30px_rgba(255,255,255,0.6)] " +
                (showItem.color === "self"
                  ? "text-emerald-200"
                  : "text-rose-200")
              }
            >
              {showItem.label}
            </div>
          </motion.div>
        )}
        {showItem && showItem.kind === "first_order" && (
          <motion.div
            key={showItem.id}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{
              opacity: [0, 1, 1, 0],
              scale: [0.6, 1, 1, 1.05],
            }}
            transition={{
              duration: 1.5,
              times: [0, 0.18, 0.7, 1],
              ease: "easeOut",
            }}
            exit={{ opacity: 0 }}
            className="flex w-[640px] items-stretch gap-0 shadow-2xl backdrop-blur"
          >
            {/* 左: 先攻 — basis-1/2 で 左右 等幅 (= AI vs 人間 の対比 を 強調) */}
            <div
              className={
                "flex basis-1/2 flex-col items-center justify-center rounded-l-2xl border-4 border-r-0 px-8 py-8 " +
                (showItem.humanIsFirst
                  ? "border-emerald-300 bg-emerald-900/80"
                  : "border-rose-300 bg-rose-900/80")
              }
            >
              <div
                className={
                  "text-2xl font-bold tracking-widest " +
                  (showItem.humanIsFirst
                    ? "text-emerald-300"
                    : "text-rose-300")
                }
              >
                先攻
              </div>
              <div
                className={
                  "mt-1 text-5xl font-extrabold drop-shadow-[0_0_30px_rgba(255,255,255,0.6)] " +
                  (showItem.humanIsFirst
                    ? "text-emerald-200"
                    : "text-rose-200")
                }
              >
                {showItem.humanIsFirst ? "人間" : "AI"}
              </div>
            </div>
            {/* 右: 後攻 — basis-1/2 で 左右 等幅 */}
            <div
              className={
                "flex basis-1/2 flex-col items-center justify-center rounded-r-2xl border-4 px-8 py-8 " +
                (showItem.humanIsFirst
                  ? "border-rose-300 bg-rose-900/80"
                  : "border-emerald-300 bg-emerald-900/80")
              }
            >
              <div
                className={
                  "text-2xl font-bold tracking-widest " +
                  (showItem.humanIsFirst
                    ? "text-rose-300"
                    : "text-emerald-300")
                }
              >
                後攻
              </div>
              <div
                className={
                  "mt-1 text-5xl font-extrabold drop-shadow-[0_0_30px_rgba(255,255,255,0.6)] " +
                  (showItem.humanIsFirst
                    ? "text-rose-200"
                    : "text-emerald-200")
                }
              >
                {showItem.humanIsFirst ? "AI" : "人間"}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** 自分側 hand で 直近 ドロー カード を ハイライト 表示 する 用 hook。
 *
 * 返値 = ハイライト 対象 の hand idx Set。 hand 末尾 N 枚 (= handDelta 分) を
 * 一定 時間 (= 2 秒) ハイライト、 経過後 自動 clear。 別 ドロー で 更新。 */
export function useRecentDrawnIdxs(
  handDelta: number,
  handLength: number,
  tickId: number,
): Set<number> {
  const [recent, setRecent] = useState<Set<number>>(new Set());
  const lastTickRef = useRef(-1);
  const handDeltaRef = useRef(handDelta);
  const handLengthRef = useRef(handLength);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  handDeltaRef.current = handDelta;
  handLengthRef.current = handLength;

  useEffect(() => {
    if (tickId === lastTickRef.current) return;
    lastTickRef.current = tickId;
    const delta = handDeltaRef.current;
    const len = handLengthRef.current;
    if (delta <= 0) return;
    const startIdx = Math.max(0, len - delta);
    const idxs = new Set<number>();
    for (let i = startIdx; i < len; i++) idxs.add(i);
    setRecent(idxs);
    // setTimeout を ref で 保持。 cleanup で clear しない (= 旧 timer も
    // そのまま fire で recent 自動 clear)。 「いつまで も NEW 残る」 防止。
    const t = setTimeout(() => setRecent(new Set()), 1500);
    timersRef.current.push(t);
  }, [tickId]);

  useEffect(() => {
    // unmount 時 のみ 全 timer cleanup (= memory leak 防止)
    return () => {
      timersRef.current.forEach((t) => clearTimeout(t));
      timersRef.current = [];
    };
  }, []);

  return recent;
}

// --------------------------------------------------------------------------
// AnimatedNumber: 数値 が 変わる 時 に 軽く scale + flash
// --------------------------------------------------------------------------

export function AnimatedNumber({
  value,
  className = "",
  flashColorClass = "text-amber-300",
}: {
  value: number;
  className?: string;
  flashColorClass?: string;
}) {
  const [shown, setShown] = useState(value);
  const [flashing, setFlashing] = useState(false);
  useEffect(() => {
    if (value === shown) return;
    setFlashing(true);
    setShown(value);
    const t = setTimeout(() => setFlashing(false), 450);
    return () => clearTimeout(t);
  }, [value, shown]);
  return (
    <motion.span
      animate={
        flashing
          ? { scale: [1, 1.4, 1.0] }
          : { scale: 1 }
      }
      transition={{ duration: 0.45 }}
      className={
        className +
        " inline-block " +
        (flashing ? flashColorClass : "")
      }
    >
      {shown}
    </motion.span>
  );
}

// --------------------------------------------------------------------------
// EffectToast: log の 「効果:」 行 を 中央上部 で 1.6 秒 toast 表示
// --------------------------------------------------------------------------

type ToastItem = { id: number; text: string; category: string };

/** log 文字列 から 「効果:」 行 を 抽出 し、 効果 種別 を 色 分け。 */
function categorizeEffectLog(text: string): { category: string; clean: string } | null {
  const m = text.match(/効果:\s*(.+)/);
  if (!m) return null;
  const body = m[1].trim();
  let category = "default";
  if (/KO|ＫＯ/.test(body)) category = "ko";
  else if (/ライフ/.test(body)) category = "life";
  else if (/ドン/.test(body) && /\+|アクティブ/.test(body)) category = "don";
  else if (/サーチ|登場|手札に加える/.test(body)) category = "search";
  else if (/パワー[+\-＋−]/.test(body)) category = "power";
  else if (/ブロッカー|速攻|ダブルアタック|バニッシュ|【.*】/.test(body)) category = "keyword";
  else if (/レスト|アクティブ|起こす/.test(body)) category = "rest";
  else if (/手札.*戻す|手札に戻す|捨て/.test(body)) category = "hand";
  return { category, clean: body };
}

const TOAST_COLORS: Record<string, string> = {
  ko: "border-rose-400 bg-rose-900/85 text-rose-100",
  life: "border-orange-400 bg-orange-900/85 text-orange-100",
  don: "border-amber-400 bg-amber-900/85 text-amber-100",
  search: "border-cyan-400 bg-cyan-900/85 text-cyan-100",
  power: "border-fuchsia-400 bg-fuchsia-900/85 text-fuchsia-100",
  keyword: "border-emerald-400 bg-emerald-900/85 text-emerald-100",
  rest: "border-violet-400 bg-violet-900/85 text-violet-100",
  hand: "border-yellow-400 bg-yellow-900/85 text-yellow-100",
  default: "border-zinc-300 bg-zinc-800/85 text-zinc-100",
};

export function EffectToastOverlay({ log }: { log: string[] }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const lastSeenLenRef = useRef(0);
  const nextIdRef = useRef(0);

  useEffect(() => {
    const prevLen = lastSeenLenRef.current;
    if (log.length <= prevLen) {
      lastSeenLenRef.current = log.length;
      return;
    }
    const newLines = log.slice(prevLen);
    lastSeenLenRef.current = log.length;
    const additions: ToastItem[] = [];
    for (const line of newLines) {
      const cat = categorizeEffectLog(line);
      if (cat) {
        additions.push({
          id: nextIdRef.current++,
          text: cat.clean,
          category: cat.category,
        });
      }
    }
    if (additions.length === 0) return;
    // 直近 4 件 だけ 保持
    setToasts((prev) => [...prev, ...additions].slice(-4));
    // 各 toast を 1.6 秒 後 に dismiss (= id 別)
    additions.forEach((t) => {
      setTimeout(() => {
        setToasts((cur) => cur.filter((x) => x.id !== t.id));
      }, 1600);
    });
  }, [log]);

  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none absolute top-20 left-1/2 z-40 flex -translate-x-1/2 flex-col items-center gap-2">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: -16, scale: 0.85 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.7 }}
            transition={{ duration: 0.25 }}
            className={
              "rounded-lg border-2 px-4 py-2 text-sm font-bold shadow-xl backdrop-blur " +
              (TOAST_COLORS[t.category] ?? TOAST_COLORS.default)
            }
          >
            {t.text}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

// --------------------------------------------------------------------------
// CounterPlayOverlay: 手札 counter ドロップ 時 「+N」 popup + カード trash slide
// --------------------------------------------------------------------------

type CounterFireItem = {
  id: number;
  cardId: string;
  value: number;
  side: "me" | "opp";
};

let _counterFireExternal:
  | ((cardId: string, value: number, side: "me" | "opp") => void)
  | null = null;

export function fireCounterPlay(
  cardId: string,
  value: number,
  side: "me" | "opp" = "me",
): void {
  if (_counterFireExternal) _counterFireExternal(cardId, value, side);
}

export function CounterPlayOverlay(): React.JSX.Element | null {
  const [items, setItems] = useState<CounterFireItem[]>([]);
  const idRef = useRef(0);
  useEffect(() => {
    _counterFireExternal = (cardId, value, side) => {
      const id = idRef.current++;
      setItems((prev) => [...prev, { id, cardId, value, side }].slice(-4));
      setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== id));
      }, 1800);
    };
    return () => {
      _counterFireExternal = null;
    };
  }, []);
  if (items.length === 0) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-[60]">
      <AnimatePresence>
        {items.map((it, idx) => {
          const xOffset = (idx - items.length / 2) * 160;
          const isMe = it.side === "me";
          const startY = isMe ? "60vh" : "-60vh";
          const endY = isMe ? "30vh" : "-30vh";
          const midY = isMe ? "10vh" : "-10vh";
          return (
            <motion.div
              key={it.id}
              initial={{ opacity: 0, scale: 0.4, x: xOffset, y: startY }}
              animate={{
                opacity: [0, 1, 1, 0.85, 0],
                scale: [0.4, 1.15, 1.05, 0.95, 0.8],
                x: [xOffset, xOffset, xOffset, xOffset + 160, xOffset + 380],
                y: [startY, "0vh", "0vh", midY, endY],
              }}
              transition={{
                duration: 1.8,
                times: [0, 0.22, 0.55, 0.85, 1],
                ease: "easeOut",
              }}
              exit={{ opacity: 0 }}
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
            >
              <div className="relative">
                <CardImage
                  cardId={it.cardId}
                  alt={it.cardId}
                  className={
                    "h-72 w-auto rounded shadow-2xl ring-4 " +
                    (isMe
                      ? "ring-amber-300 drop-shadow-[0_0_30px_rgba(251,191,36,0.85)]"
                      : "ring-rose-300 drop-shadow-[0_0_30px_rgba(244,114,182,0.85)]")
                  }
                />
                <div
                  className={
                    "absolute -top-8 left-1/2 -translate-x-1/2 rounded-full px-6 py-2 text-4xl font-extrabold text-white shadow-2xl " +
                    (isMe
                      ? "bg-amber-500 drop-shadow-[0_0_18px_rgba(251,191,36,0.95)]"
                      : "bg-rose-500 drop-shadow-[0_0_18px_rgba(244,114,182,0.95)]")
                  }
                >
                  +{it.value}
                </div>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// --------------------------------------------------------------------------
// ArrowBreakOverlay: 防御 成功 時 に 攻撃 矢印 を 真ん中 で 割って 飛び散らせる 演出。
// fireArrowBreak({x1, y1, x2, y2}) で 発火 (= 0.8 秒 で 自動 dismiss)。
// 左右 半 を 回転 + flying outward + 中央 衝撃波 + spark particle。
// --------------------------------------------------------------------------

type ArrowBreakItem = {
  id: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

let _arrowBreakFire:
  | ((coords: { x1: number; y1: number; x2: number; y2: number }) => void)
  | null = null;

export function fireArrowBreak(coords: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}): void {
  if (_arrowBreakFire) _arrowBreakFire(coords);
}

// --------------------------------------------------------------------------
// ArrowStrikeOverlay: 防御 失敗 (= 攻撃 成立) 時 に 矢印 が target に 突き刺さる 演出。
// 持続矢印 が 消える 瞬間 に fireArrowStrike(coords) で 発火。
// 矢印 が 一旦 縮んで 突き出る + target 位置 で 衝撃 flash + shake。
// --------------------------------------------------------------------------

type ArrowStrikeItem = {
  id: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

let _arrowStrikeFire:
  | ((coords: { x1: number; y1: number; x2: number; y2: number }) => void)
  | null = null;

export function fireArrowStrike(coords: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}): void {
  if (_arrowStrikeFire) _arrowStrikeFire(coords);
}

export function ArrowStrikeOverlay(): React.JSX.Element | null {
  const [items, setItems] = useState<ArrowStrikeItem[]>([]);
  const idRef = useRef(0);
  useEffect(() => {
    _arrowStrikeFire = (coords) => {
      const id = idRef.current++;
      setItems((prev) => [...prev, { id, ...coords }].slice(-3));
      setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== id));
      }, 1600);
    };
    return () => {
      _arrowStrikeFire = null;
    };
  }, []);
  if (items.length === 0) return null;
  return (
    <>
      {/* 画面全体 赤フラッシュ (= 攻撃 命中 の 強調) */}
      <AnimatePresence>
        {items.map((it) => (
          <motion.div
            key={`flash-${it.id}`}
            className="pointer-events-none fixed inset-0 z-[55] bg-rose-600"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.35, 0.15, 0] }}
            exit={{ opacity: 0 }}
            transition={{
              duration: 0.85,
              times: [0, 0.45, 0.6, 1],
              ease: "easeOut",
              delay: 0.35,
            }}
          />
        ))}
      </AnimatePresence>

      <svg className="pointer-events-none absolute inset-0 z-[56] h-full w-full">
        <defs>
          <filter id="strikeGlow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <radialGradient id="impactGrad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#fef08a" stopOpacity="1" />
            <stop offset="40%" stopColor="#f97316" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#dc2626" stopOpacity="0" />
          </radialGradient>
        </defs>
        {items.map((it) => {
          const dx = it.x2 - it.x1;
          const dy = it.y2 - it.y1;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const ang = Math.atan2(dy, dx);
          const overshoot = 50;
          const x2e = it.x2 + Math.cos(ang) * overshoot;
          const y2e = it.y2 + Math.sin(ang) * overshoot;
          const angDeg = (ang * 180) / Math.PI;
          // 矢の 通り過ぎ 軌跡 用 control point (= 曲線 でなく 直線 で 高速 通過)
          return (
            <g key={it.id}>
              {/* === 攻撃 軌跡: 高速 凱旋 風 太線 (= 二重 で 立体感) === */}
              <motion.line
                x1={it.x1}
                y1={it.y1}
                x2={it.x2}
                y2={it.y2}
                stroke="#fde047"
                strokeWidth={22}
                strokeLinecap="round"
                opacity={0.6}
                filter="url(#strikeGlow)"
                initial={{ opacity: 0, pathLength: 0 }}
                animate={{
                  opacity: [0, 0.85, 0.85, 0],
                  pathLength: [0, 1, 1, 1],
                }}
                transition={{ duration: 1.0, times: [0, 0.25, 0.5, 0.8], ease: "easeOut" }}
              />
              <motion.line
                x1={it.x1}
                y1={it.y1}
                x2={it.x2}
                y2={it.y2}
                stroke="#ef4444"
                strokeWidth={14}
                strokeLinecap="round"
                filter="url(#strikeGlow)"
                initial={{ opacity: 1, pathLength: 0 }}
                animate={{
                  opacity: [1, 1, 0.7, 0],
                  pathLength: [0, 1, 1.1, 1.1],
                }}
                transition={{ duration: 1.0, times: [0, 0.25, 0.6, 0.85], ease: "easeOut" }}
              />
              {/* === 矢印 head (= 三角) === 線 が 伸びきった 後 (= t=0.25) に target で 出現
                  → overshoot へ 突き抜け。 polygon (0,0) が 矢印 tip。
                  transform-origin "0px 0px" で rotate も (0,0) を pivot に
                  (= 旧 default bbox center で 位置 ずれ 発生 した 修正)。
                  rotate を SVG attribute (= transform="rotate(deg, cx, cy)") として 直接 設定
                  するため <g> で wrap し、 内側 polygon は 静的 に point 計算。
              */}
              <motion.g
                initial={{ opacity: 0, x: it.x2, y: it.y2, scale: 1.4 }}
                animate={{
                  opacity: [0, 0, 1, 1, 0],
                  x: [it.x2, it.x2, it.x2, x2e, x2e],
                  y: [it.y2, it.y2, it.y2, y2e, y2e],
                  scale: [1.4, 1.4, 1.6, 1.8, 1.8],
                }}
                transition={{
                  duration: 1.0,
                  times: [0, 0.25, 0.3, 0.5, 0.85],
                  ease: "easeOut",
                }}
                style={{ transformOrigin: "0px 0px" }}
              >
                {/* tip を (0,0) に 置き、 angDeg 方向 に 向く 三角 (= 静的 計算) */}
                {(() => {
                  const c = Math.cos(ang);
                  const s = Math.sin(ang);
                  // 基本: 0,0 / -32,12 / -32,-12 (= 右向き矢印)
                  // angDeg 回転 後 の 点
                  const p1x = -32 * c - 12 * s;
                  const p1y = -32 * s + 12 * c;
                  const p2x = -32 * c + 12 * s;
                  const p2y = -32 * s - 12 * c;
                  return (
                    <polygon
                      points={`0,0 ${p1x},${p1y} ${p2x},${p2y}`}
                      fill="#ef4444"
                      stroke="#fef08a"
                      strokeWidth={2}
                      filter="url(#strikeGlow)"
                    />
                  );
                })()}
              </motion.g>
              {/* === 巨大 衝撃 グラデ ヒット === */}
              <motion.circle
                cx={it.x2}
                cy={it.y2}
                fill="url(#impactGrad)"
                initial={{ r: 0, opacity: 0 }}
                animate={{ r: [0, 90, 130, 100], opacity: [0, 1, 0.7, 0] }}
                transition={{ duration: 0.8, times: [0, 0.25, 0.55, 1], delay: 0.4, ease: "easeOut" }}
                filter="url(#strikeGlow)"
              />
              {/* === 中央 白 コア (= 爆発 中心) === */}
              <motion.circle
                cx={it.x2}
                cy={it.y2}
                fill="#ffffff"
                initial={{ r: 0, opacity: 0 }}
                animate={{ r: [0, 50, 30, 0], opacity: [0, 1, 0.7, 0] }}
                transition={{ duration: 0.5, times: [0, 0.3, 0.6, 1], delay: 0.4 }}
                filter="url(#strikeGlow)"
              />
              {/* === 衝撃 波 リング 3 段 (= 拡散) === */}
              {[0, 0.15, 0.3].map((offset, i) => (
                <motion.circle
                  key={`shock-${i}`}
                  cx={it.x2}
                  cy={it.y2}
                  fill="none"
                  stroke={i === 0 ? "#fef08a" : i === 1 ? "#f97316" : "#dc2626"}
                  strokeWidth={6 - i * 1.5}
                  filter="url(#strikeGlow)"
                  initial={{ r: 20, opacity: 0 }}
                  animate={{ r: [20, 120 + i * 60, 200 + i * 80], opacity: [0, 0.9, 0] }}
                  transition={{ duration: 0.9, times: [0, 0.4, 1], delay: 0.4 + offset }}
                />
              ))}
              {/* === 火花 12 方向 (= 内→外 散る) === */}
              {Array.from({ length: 12 }).map((_, i) => {
                const deg = i * 30;
                const rad = (deg * Math.PI) / 180;
                const dd = 100 + (i % 3) * 30;
                return (
                  <motion.circle
                    key={`spark-${deg}`}
                    cx={it.x2}
                    cy={it.y2}
                    r={4 + (i % 3) * 2}
                    fill={i % 2 === 0 ? "#fde047" : "#fca5a5"}
                    filter="url(#strikeGlow)"
                    initial={{ x: 0, y: 0, opacity: 0, scale: 1.4 }}
                    animate={{
                      x: Math.cos(rad) * dd,
                      y: Math.sin(rad) * dd,
                      opacity: [0, 1, 0],
                      scale: [1.4, 1.0, 0.4],
                    }}
                    transition={{ duration: 0.85, times: [0, 0.4, 1], delay: 0.4 }}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>
    </>
  );
}

export function ArrowBreakOverlay(): React.JSX.Element | null {
  const [items, setItems] = useState<ArrowBreakItem[]>([]);
  const idRef = useRef(0);
  useEffect(() => {
    _arrowBreakFire = (coords) => {
      const id = idRef.current++;
      setItems((prev) => [...prev, { id, ...coords }].slice(-3));
      setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== id));
      }, 900);
    };
    return () => {
      _arrowBreakFire = null;
    };
  }, []);
  if (items.length === 0) return null;
  return (
    <svg className="pointer-events-none absolute inset-0 z-[56] h-full w-full">
      <defs>
        <filter id="breakGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {items.map((it) => {
        const midX = (it.x1 + it.x2) / 2;
        const midY = (it.y1 + it.y2) / 2;
        return (
          <g key={it.id}>
            {/* 左半 (= attacker → mid) を 上 へ 跳ね飛ばす + 回転 */}
            <motion.line
              x1={it.x1}
              y1={it.y1}
              x2={midX}
              y2={midY}
              stroke="#fde047"
              strokeWidth={9}
              strokeLinecap="round"
              filter="url(#breakGlow)"
              initial={{ opacity: 1, rotate: 0, x: 0, y: 0 }}
              animate={{
                opacity: [1, 1, 0],
                rotate: [0, 45],
                x: [0, -55],
                y: [0, -40],
              }}
              transition={{ duration: 0.85, ease: "easeOut" }}
              style={{ transformOrigin: `${midX}px ${midY}px` }}
            />
            {/* 右半 (= mid → target) も 反対 方向 へ */}
            <motion.line
              x1={midX}
              y1={midY}
              x2={it.x2}
              y2={it.y2}
              stroke="#fde047"
              strokeWidth={9}
              strokeLinecap="round"
              filter="url(#breakGlow)"
              initial={{ opacity: 1, rotate: 0, x: 0, y: 0 }}
              animate={{
                opacity: [1, 1, 0],
                rotate: [0, -45],
                x: [0, 55],
                y: [0, -40],
              }}
              transition={{ duration: 0.85, ease: "easeOut" }}
              style={{ transformOrigin: `${midX}px ${midY}px` }}
            />
            {/* 中央 衝撃波 (= 拡大 + フェード) */}
            <motion.circle
              cx={midX}
              cy={midY}
              fill="none"
              stroke="#fde047"
              strokeWidth={5}
              filter="url(#breakGlow)"
              initial={{ r: 8, opacity: 1 }}
              animate={{ r: [8, 70, 140], opacity: [1, 0.5, 0] }}
              transition={{ duration: 0.85, ease: "easeOut" }}
            />
            <motion.circle
              cx={midX}
              cy={midY}
              fill="#fef08a"
              initial={{ r: 0, opacity: 1 }}
              animate={{ r: [0, 26, 16], opacity: [1, 0.9, 0] }}
              transition={{ duration: 0.55, ease: "easeOut" }}
              filter="url(#breakGlow)"
            />
            {/* 火花 8 方向 */}
            {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => {
              const rad = (deg * Math.PI) / 180;
              const dx = Math.cos(rad) * 75;
              const dy = Math.sin(rad) * 75;
              return (
                <motion.circle
                  key={deg}
                  cx={midX}
                  cy={midY}
                  r={5}
                  fill="#fde047"
                  filter="url(#breakGlow)"
                  initial={{ x: 0, y: 0, opacity: 1, scale: 1 }}
                  animate={{
                    x: dx,
                    y: dy,
                    opacity: [1, 1, 0],
                    scale: [1, 0.6, 0.3],
                  }}
                  transition={{ duration: 0.8, ease: "easeOut" }}
                />
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}

// --------------------------------------------------------------------------
// DefenseSuccessOverlay: 攻撃 不発 (= "  survived" / "  blocker survived" log)
// を 検出 → 「防御 成功!」 / 「攻撃 阻止!」 banner を 一瞬 表示。
// fireDefenseSuccess(side, blocked) を 呼び出して 発火。
//   side: "me" (= 自分 が 守った)、 "opp" (= 自分 の 攻撃 が AI に 防がれた)
//   blocked: true (= blocker が 受けて 生存)、 false (= attack power 不足 で 不発)
// --------------------------------------------------------------------------

type DefenseFireItem = {
  id: number;
  side: "me" | "opp";
  blocked: boolean;
};

let _defenseFireExternal:
  | ((side: "me" | "opp", blocked: boolean) => void)
  | null = null;

export function fireDefenseSuccess(
  side: "me" | "opp",
  blocked: boolean = false,
): void {
  if (_defenseFireExternal) _defenseFireExternal(side, blocked);
}

export function DefenseSuccessOverlay(): React.JSX.Element | null {
  const [items, setItems] = useState<DefenseFireItem[]>([]);
  const idRef = useRef(0);
  useEffect(() => {
    _defenseFireExternal = (side, blocked) => {
      const id = idRef.current++;
      setItems((prev) => [...prev, { id, side, blocked }].slice(-3));
      setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== id));
      }, 1500);
    };
    return () => {
      _defenseFireExternal = null;
    };
  }, []);
  if (items.length === 0) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-[57] flex items-center justify-center">
      <AnimatePresence>
        {items.map((it, idx) => {
          const isMe = it.side === "me";
          const yOffset = (idx - (items.length - 1) / 2) * 90;
          const label = isMe
            ? it.blocked
              ? "ブロッカー で 防御!"
              : "防御 成功!"
            : it.blocked
              ? "AI ブロック で 耐えた"
              : "攻撃 が 通らない";
          return (
            <motion.div
              key={it.id}
              initial={{ opacity: 0, scale: 0.4, rotate: -8, y: yOffset }}
              animate={{
                opacity: [0, 1, 1, 0],
                scale: [0.4, 1.2, 1.0, 1.0],
                rotate: [-8, 0, 0, 4],
                y: [yOffset, yOffset, yOffset, yOffset - 20],
              }}
              transition={{
                duration: 1.5,
                times: [0, 0.18, 0.75, 1],
                ease: "easeOut",
              }}
              exit={{ opacity: 0 }}
              className="absolute"
            >
              <div
                className={
                  "relative rounded-2xl border-4 px-12 py-5 shadow-2xl backdrop-blur " +
                  (isMe
                    ? "border-cyan-300 bg-cyan-900/85"
                    : "border-amber-300 bg-amber-900/85")
                }
              >
                {/* shield 形 装飾 (= SVG) */}
                <svg
                  viewBox="0 0 24 24"
                  className={
                    "absolute -left-2 -top-2 h-12 w-12 drop-shadow-[0_0_15px_rgba(255,255,255,0.7)] " +
                    (isMe ? "text-cyan-200" : "text-amber-200")
                  }
                  fill="currentColor"
                >
                  <path d="M12 2 4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5l-8-3z" />
                </svg>
                <div
                  className={
                    "text-center text-4xl font-extrabold drop-shadow-[0_0_25px_rgba(255,255,255,0.7)] " +
                    (isMe ? "text-cyan-100" : "text-amber-100")
                  }
                >
                  {label}
                </div>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// --------------------------------------------------------------------------
// AttackTargetArrowOverlay: 相手 攻撃 中 に attacker → target の 矢印 (三角ヘッド) を
// 一定時間 表示 する。 AttackBeam とは別、 「何 を 狙ってるか」 を 明示的 に 示す ための
// 静的 な 矢印 (= 1.2 秒)。
// --------------------------------------------------------------------------

export function AttackTargetArrowOverlay({
  attackerIid,
  targetIid,
  boardRef,
  tickId,
  persistent = false,
}: {
  attackerIid: number | null;
  targetIid: number | null;
  boardRef: React.RefObject<HTMLDivElement | null>;
  tickId: number;
  /** true なら 自動 fade out しない (= defense pending 中 ずっと表示) */
  persistent?: boolean;
}) {
  const [coords, setCoords] = useState<{
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  } | null>(null);
  // 同 attacker→target に 対する 連続 fire (= atk frame の 直後 に counter frame で
  // pending_event が 再 set される ケース) を 重複表示 しない 用 dedupe key。
  const lastFiredKeyRef = useRef<string>("");

  useEffect(() => {
    if (attackerIid === null || targetIid === null || !boardRef.current) {
      setCoords(null);
      // event 無し に なったら dedupe key を 解除 (= 次 の 同 attacker 攻撃 で 再 fire)
      lastFiredKeyRef.current = "";
      return;
    }
    // non-persistent 矢印: 同 (attacker, target) で 連続 fire したら skip (= 既 表示済)
    // event が 一旦 null に なった 後 の 再 fire は OK (= 別 攻撃 と 判定)。
    if (!persistent) {
      const key = `${attackerIid}:${targetIid}`;
      if (key === lastFiredKeyRef.current) return;
      lastFiredKeyRef.current = key;
    }
    const board = boardRef.current;
    // DOM レイアウト が 確定するのを 待って 座標 取得 (= playFrames で 直後 だと 未配置)
    function update() {
      if (!board) return;
      const r = board.getBoundingClientRect();
      const findEl = (iid: number): HTMLElement | null =>
        board.querySelector(`[data-iid="${iid}"]`);
      const at = findEl(attackerIid!);
      const tg = findEl(targetIid!);
      if (!at || !tg) {
        setCoords(null);
        return;
      }
      const ar = at.getBoundingClientRect();
      const tr = tg.getBoundingClientRect();
      setCoords({
        x1: ar.left + ar.width / 2 - r.left,
        y1: ar.top + ar.height / 2 - r.top,
        x2: tr.left + tr.width / 2 - r.left,
        y2: tr.top + tr.height / 2 - r.top,
      });
    }
    update();
    if (persistent) {
      // defense 中 は user が 手札 hover 等 で 場 が 動かない 想定、 1 回 算出 で十分
      return;
    }
    const timer = setTimeout(() => setCoords(null), 1300);
    return () => clearTimeout(timer);
  }, [attackerIid, targetIid, tickId, boardRef, persistent]);

  if (!coords) return null;
  // arrow head 角度 計算
  const angle = Math.atan2(
    coords.y2 - coords.y1,
    coords.x2 - coords.x1,
  );
  // 三角ヘッド を target 手前 で 描画 (= 中心 を target 寄り に 配置)
  const headLen = 26;
  const baseX = coords.x2 - Math.cos(angle) * headLen;
  const baseY = coords.y2 - Math.sin(angle) * headLen;
  const leftX = baseX - Math.sin(angle) * 14;
  const leftY = baseY + Math.cos(angle) * 14;
  const rightX = baseX + Math.sin(angle) * 14;
  const rightY = baseY - Math.cos(angle) * 14;

  return (
    <svg className="pointer-events-none absolute inset-0 z-30 h-full w-full">
      <defs>
        <filter id="arrowGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <motion.line
        x1={coords.x1}
        y1={coords.y1}
        x2={coords.x2}
        y2={coords.y2}
        stroke="#fb7185"
        strokeWidth={persistent ? 7 : 6}
        strokeLinecap="round"
        strokeDasharray={persistent ? "16 10" : "14 8"}
        filter="url(#arrowGlow)"
        initial={{ opacity: 0, pathLength: 0 }}
        animate={
          persistent
            ? { opacity: 1, pathLength: 1 }
            : { opacity: [0, 1, 1, 1, 0], pathLength: [0, 1, 1, 1, 1] }
        }
        transition={
          persistent
            ? { duration: 0.5, ease: "easeOut" }
            : { duration: 1.3, times: [0, 0.2, 0.5, 0.9, 1] }
        }
      />
      <motion.polygon
        points={`${coords.x2},${coords.y2} ${leftX},${leftY} ${rightX},${rightY}`}
        fill="#fb7185"
        filter="url(#arrowGlow)"
        initial={{ opacity: 0, scale: 0 }}
        animate={
          persistent
            ? { opacity: 1, scale: 1 }
            : { opacity: [0, 1, 1, 1, 0], scale: [0, 1, 1.1, 1, 0.9] }
        }
        transition={
          persistent
            ? { duration: 0.4, ease: "easeOut" }
            : { duration: 1.3, times: [0, 0.25, 0.5, 0.9, 1] }
        }
        style={{ transformOrigin: `${coords.x2}px ${coords.y2}px` }}
      />
    </svg>
  );
}

// --------------------------------------------------------------------------
// AttackBeamOverlay: snapshot.event (= AttackEvent) を 拾って 攻撃ビーム を 流す
// --------------------------------------------------------------------------

/** event tick 毎 に 短時間 beam line を 表示。
 *  attacker / target の DOM 位置 は data-iid 属性 で 取得 (= boardRef 内 を 探す)。 */
export function AttackBeamOverlay({
  attackerIid,
  targetIid,
  boardRef,
  tickId,
}: {
  attackerIid: number | null;
  targetIid: number | null;
  boardRef: React.RefObject<HTMLDivElement | null>;
  tickId: number;
}) {
  const [coords, setCoords] = useState<{
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  } | null>(null);
  // 同 attacker→target に 対する 連続 fire (= atk → counter で pending_event 再 set)
  // を 重複表示 しない 用 dedupe key。
  const lastFiredKeyRef = useRef<string>("");

  useEffect(() => {
    if (attackerIid === null || targetIid === null || !boardRef.current) {
      setCoords(null);
      lastFiredKeyRef.current = "";
      return;
    }
    const key = `${attackerIid}:${targetIid}`;
    if (key === lastFiredKeyRef.current) return;
    lastFiredKeyRef.current = key;
    const board = boardRef.current;
    const r = board.getBoundingClientRect();
    const findEl = (iid: number): HTMLElement | null =>
      board.querySelector(`[data-iid="${iid}"]`);
    const at = findEl(attackerIid);
    const tg = findEl(targetIid);
    if (!at || !tg) {
      setCoords(null);
      return;
    }
    const ar = at.getBoundingClientRect();
    const tr = tg.getBoundingClientRect();
    setCoords({
      x1: ar.left + ar.width / 2 - r.left,
      y1: ar.top + ar.height / 2 - r.top,
      x2: tr.left + tr.width / 2 - r.left,
      y2: tr.top + tr.height / 2 - r.top,
    });
    const timer = setTimeout(() => setCoords(null), 750);
    return () => clearTimeout(timer);
  }, [attackerIid, targetIid, tickId, boardRef]);

  if (!coords) return null;
  return (
    <svg className="pointer-events-none absolute inset-0 z-30 h-full w-full">
      <defs>
        <linearGradient id="atkBeam" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#fbbf24" stopOpacity="0" />
          <stop offset="50%" stopColor="#f59e0b" stopOpacity="1" />
          <stop offset="100%" stopColor="#ef4444" stopOpacity="1" />
        </linearGradient>
        <filter id="atkGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <motion.line
        x1={coords.x1}
        y1={coords.y1}
        x2={coords.x1}
        y2={coords.y1}
        stroke="url(#atkBeam)"
        strokeWidth={10}
        strokeLinecap="round"
        filter="url(#atkGlow)"
        initial={{ x2: coords.x1, y2: coords.y1, opacity: 0 }}
        animate={{
          x2: [coords.x1, coords.x2],
          y2: [coords.y1, coords.y2],
          opacity: [0.2, 1, 1, 0],
        }}
        transition={{ duration: 0.7, times: [0, 0.4, 0.7, 1] }}
      />
      <motion.circle
        cx={coords.x2}
        cy={coords.y2}
        r={0}
        fill="#fde047"
        filter="url(#atkGlow)"
        initial={{ r: 0, opacity: 0 }}
        animate={{ r: [0, 22, 40], opacity: [0, 1, 0] }}
        transition={{ duration: 0.5, delay: 0.35 }}
      />
    </svg>
  );
}
