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
      eventTickId: tickRef.current,
      shouldFieldFlash,
    });
  }, [snap]);

  return diff;
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
  const color = delta > 0 ? "bg-rose-500/30" : "bg-emerald-500/25";
  const label = delta > 0 ? `−${delta}` : `+${-delta}`;
  const labelColor = delta > 0 ? "text-rose-200" : "text-emerald-200";
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
