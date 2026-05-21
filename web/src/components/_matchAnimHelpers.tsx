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
  tickId,
}: {
  trashAddedMe: string[];
  trashAddedOpp: string[];
  leftCharasMe: CharSnapshot[];
  leftCharasOpp: CharSnapshot[];
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
  trashAddedMeRef.current = trashAddedMe;
  trashAddedOppRef.current = trashAddedOpp;
  leftCharasMeRef.current = leftCharasMe;
  leftCharasOppRef.current = leftCharasOpp;

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
    const meHandPlays = diff(trashAddedMeRef.current, leftCharasMeRef.current);
    const oppHandPlays = diff(
      trashAddedOppRef.current,
      leftCharasOppRef.current,
    );
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

type DrawItem = { id: number; side: "me" | "opp"; delayIdx: number };

export function DrawCardOverlay({
  handDeltaMe,
  handDeltaOpp,
  lifeDeltaMe,
  lifeDeltaOpp,
  tickId,
}: {
  handDeltaMe: number;
  handDeltaOpp: number;
  /** 同 frame で life-1 起きた → handDelta は 「ライフ→手札」 由来 で DrawOverlay 不適切。 */
  lifeDeltaMe: number;
  lifeDeltaOpp: number;
  tickId: number;
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
    // ライフ削り frame では handDelta は 「ライフ→手札」 由来 → DrawCardOverlay 不発
    // (= デッキ → 手札 演出 は 公式 「ライフ trigger」 と 別物、 LifeFlash で 代替)。
    const meLifeHit = lifeMeRef.current > 0;
    const oppLifeHit = lifeOppRef.current > 0;
    const meN = meLifeHit ? 0 : Math.max(0, Math.min(meDeltaRef.current, 6));
    const oppN = oppLifeHit ? 0 : Math.max(0, Math.min(oppDeltaRef.current, 6));
    if (meN === 0 && oppN === 0) return;
    // 連続 fire 阻止 cooldown (= visual overlap 防止)。
    const now = Date.now();
    if (now - lastFireAtRef.current < 1500) {
      return;
    }
    lastFireAtRef.current = now;
    const additions: DrawItem[] = [];
    for (let i = 0; i < meN; i++) {
      additions.push({
        id: nextIdRef.current++,
        side: "me",
        delayIdx: i,
      });
    }
    for (let i = 0; i < oppN; i++) {
      additions.push({
        id: nextIdRef.current++,
        side: "opp",
        delayIdx: i,
      });
    }
    setItems((prev) => [...prev, ...additions].slice(-12));
    additions.forEach((it) => {
      setTimeout(
        () => {
          setItems((cur) => cur.filter((x) => x.id !== it.id));
        },
        650 + it.delayIdx * 80,
      );
    });
  }, [tickId]);

  if (items.length === 0) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-30">
      <AnimatePresence>
        {items.map((it) => {
          // デッキ位置 → 手札方向 へ 縦方向 直線 で 飛ばす (= 横にズレない)。
          // 自分 mat の deck は 中央付近、 自分 手札 は 画面 下端 HandRow。
          // AI mat の deck は 中央付近、 AI 手札 は 画面 上端 OpponentInfoPanel 内。
          const isMe = it.side === "me";
          const startY = isMe ? "-10vh" : "10vh"; // mat 内 deck 概略位置
          const endY = isMe ? "55vh" : "-55vh"; // 手札位置 (= 画面端)
          const midY1 = isMe ? "15vh" : "-15vh";
          const midY2 = isMe ? "35vh" : "-35vh";
          const delay = it.delayIdx * 0.1;
          return (
            <motion.div
              key={it.id}
              initial={{
                opacity: 0,
                scale: 0.7,
                x: 0,
                y: startY,
                rotate: 0,
              }}
              animate={{
                // x は 中央維持 (= デッキ→手札 直線)、 終端 で fade-out
                opacity: [0, 1, 1, 1, 0],
                scale: [0.7, 0.95, 1.0, 0.95, 0.85],
                x: [0, 0, 0, 0, 0],
                y: [startY, "0%", midY1, midY2, endY],
                rotate: [0, isMe ? 3 : -3, isMe ? 5 : -5, isMe ? 7 : -7, 0],
              }}
              exit={{ opacity: 0 }}
              transition={{
                duration: 0.55,
                delay,
                times: [0, 0.25, 0.55, 0.8, 1],
                ease: "easeIn",
              }}
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
            >
              <img
                src="/assets/ura.png"
                alt="draw"
                className={
                  "h-32 w-24 rounded shadow-2xl ring-2 " +
                  (isMe ? "ring-emerald-300" : "ring-rose-300")
                }
              />
            </motion.div>
          );
        })}
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
    const t = setTimeout(() => setRecent(new Set()), 1100);
    return () => clearTimeout(t);
  }, [tickId]);

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

  useEffect(() => {
    if (attackerIid === null || targetIid === null || !boardRef.current) {
      setCoords(null);
      return;
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

  useEffect(() => {
    if (attackerIid === null || targetIid === null || !boardRef.current) {
      setCoords(null);
      return;
    }
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
