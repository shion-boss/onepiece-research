"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import { CardImage } from "./CardImage";
import type {
  CharSnapshot,
  PlayerSnapshot,
  ReplayResponse,
  StateSnapshot,
} from "@/lib/types";

// ホバー中のカード情報をどこからでも共有するための Context
type HoverInfo = {
  cardId: string;
  name?: string;
  power?: number;
  keywords?: string[];
  attachedDons?: number;
  summoningSickness?: boolean;
};

const HoverContext = createContext<(info: HoverInfo | null) => void>(() => {});

function useHoverHandlers(info: HoverInfo | null | undefined) {
  const setHovered = useContext(HoverContext);
  if (!info) return {};
  // mouseLeave で null にしない: スナップショット更新中に DOM が remount すると
  // hover している要素が一瞬 unmount → mouseLeave が走ってプレビューがちらつく。
  // 別カードを hover すると上書きされるのでクリア不要。
  return {
    onMouseEnter: () => setHovered(info),
  };
}

// カード DOM 要素を instance_id で登録する Context (アタック矢印描画用)
type CardRefRegistry = {
  register: (iid: number, el: HTMLElement | null) => void;
  get: (iid: number) => HTMLElement | undefined;
};
const CardRefContext = createContext<CardRefRegistry | null>(null);

// 「ゾーン」(life pile / trash / hand panel など) の DOM 要素を文字列キーで登録
type ZoneRefRegistry = {
  register: (zone: string, el: HTMLElement | null) => void;
  get: (zone: string) => HTMLElement | undefined;
};
const ZoneRefContext = createContext<ZoneRefRegistry | null>(null);

function useZoneRef(zone: string) {
  const reg = useContext(ZoneRefContext);
  return useCallback(
    (el: HTMLElement | null) => {
      reg?.register(zone, el);
    },
    [reg, zone],
  );
}

// ライフダメージ/回復インジケータ (-N 赤 / +N 緑 のフロート)
type DamageIndicator = {
  id: string;
  text: string;
  x: number;
  y: number;
  color: string;
};

// カードの飛行アニメーション
type Flight = {
  id: string;
  cardId: string; // 表示する card_id (face-up 時)
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  // 中継点 (例: イベントは hand → leader 横で一旦表示 → trash)
  midX?: number;
  midY?: number;
  midHoldMs?: number; // mid で停止する時間 (ms)
  startBack: boolean; // 始点で裏向きか
  endBack: boolean; // 終点で裏向きか
  // DON!! トークンの移動アニメ。true のとき CardImage の代わりに DonAsset を表示。
  // サイズも縮小 (44×62) で flight cleanup は短め (500ms)。
  isDon?: boolean;
  // アニメ開始までの遅延 (ms)。複数 DON を捌くとき stagger に使う。
  delayMs?: number;
  // この flight が「上マット (= 相手 = rotate-180)」を起点/終点にしているか。
  // true のとき相手マットと同じ向きで描画する。
  // 注意: snap.players のインデックスではなくマット位置で判定する。deck_a が
  // 後攻のときは players[0] が上マットに居るため、p === oppIdx で算出すること。
  onTopMat?: boolean;
};

// 状態遷移を View Transitions API でラップ。
// 対応ブラウザ (Chromium 系) ではカード移動が自動的にアニメーション。
// 非対応ブラウザでは即時更新 (フォールバック)。
type DocWithVT = Document & { startViewTransition?: (cb: () => void) => unknown };
function withViewTransition(fn: () => void) {
  if (typeof document === "undefined") return fn();
  const d = document as DocWithVT;
  if (typeof d.startViewTransition === "function") {
    d.startViewTransition(() => flushSync(fn));
  } else {
    fn();
  }
}

const SPEEDS: { label: string; ms: number }[] = [
  { label: "0.5x", ms: 1600 },
  { label: "1x", ms: 800 },
  { label: "2x", ms: 400 },
  { label: "4x", ms: 200 },
];

export function MatchReplay({ replay }: { replay: ReplayResponse }) {
  const snapshots = replay.snapshots;
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(1);
  const [followLog, setFollowLog] = useState(true);
  const [hovered, setHovered] = useState<HoverInfo | null>(null);

  // BoardCard 各々の DOM 要素を instance_id で記録 → アタック矢印描画に使う
  const cardRefs = useRef(new Map<number, HTMLElement>());
  const cardRegistry = useMemo<CardRefRegistry>(
    () => ({
      register: (iid, el) => {
        if (el) cardRefs.current.set(iid, el);
        else cardRefs.current.delete(iid);
      },
      get: (iid) => cardRefs.current.get(iid),
    }),
    [],
  );

  // マットコンテナの ref (矢印 SVG の座標基準)
  const matContainerRef = useRef<HTMLDivElement | null>(null);
  const [arrow, setArrow] = useState<{
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  } | null>(null);

  // ゾーン (life/trash/hand パネルなど) の DOM 要素登録
  const zoneRefs = useRef(new Map<string, HTMLElement>());
  const zoneRegistry = useMemo<ZoneRefRegistry>(
    () => ({
      register: (zone, el) => {
        if (el) zoneRefs.current.set(zone, el);
        else zoneRefs.current.delete(zone);
      },
      get: (zone) => zoneRefs.current.get(zone),
    }),
    [],
  );

  // 前回のスナップショット位置キャッシュ (KO/移動アニメ用)
  const cardPosCache = useRef(new Map<number, DOMRect>());
  const prevSnapRef = useRef<StateSnapshot | null>(null);
  const [flights, setFlights] = useState<Flight[]>([]);
  // 飛行アニメ中のキャラ instance_id を保持。BoardCard はこの集合に含まれる間、
  // opacity:0 で「到着前」を表現し flight オーバーレイとの 2 重表示を防ぐ。
  const [incomingIids, setIncomingIids] = useState<Set<number>>(new Set());
  const [damageIndicators, setDamageIndicators] = useState<DamageIndicator[]>(
    [],
  );
  // トラッシュモーダル: { player_idx, cards } を表示
  const [trashModal, setTrashModal] = useState<{
    title: string;
    cards: string[];
  } | null>(null);
  // snap.players[0] は first_player の側 (= deck_a なら first_player=0、deck_b なら 1)
  // playerName は snap.players の順序に揃える。
  const playerName = useMemo<[string, string]>(() => {
    if (replay.first_player === 0) {
      return [replay.deck_a_name, replay.deck_b_name];
    }
    return [replay.deck_b_name, replay.deck_a_name];
  }, [replay.deck_a_name, replay.deck_b_name, replay.first_player]);

  // 「自分デッキ (deck_a) = 下マット」「相手デッキ (deck_b) = 上マット」を
  // 先攻/後攻に関係なく固定する。snap.players は先攻=index 0 で並んでいるので、
  // deck_a が後攻なら selfIdx=1, oppIdx=0。
  // flight 検出ロジックや FlyingCard の rotate 判定でも参照するので render の早い段階で確定させる。
  const selfIdx: 0 | 1 = replay.first_player === 0 ? 0 : 1;
  const oppIdx: 0 | 1 = (1 - selfIdx) as 0 | 1;

  const atEnd = idx >= snapshots.length - 1;
  const playingActive = playing && !atEnd;

  useEffect(() => {
    if (!playingActive) return;
    const t = setTimeout(() => {
      withViewTransition(() =>
        setIdx((i) => Math.min(i + 1, snapshots.length - 1)),
      );
    }, SPEEDS[speedIdx].ms);
    return () => clearTimeout(t);
  }, [playingActive, idx, speedIdx, snapshots.length]);

  // アタックイベントが含まれるスナップショットの時、attacker → target に矢印を引く
  // (early return より前にフックを呼ぶ必要があるため、snapshots[idx] を nullable で参照)
  const snapForArrow = snapshots[idx];
  /* eslint-disable react-hooks/set-state-in-effect */
  useLayoutEffect(() => {
    if (
      !snapForArrow ||
      !snapForArrow.event ||
      snapForArrow.event.type !== "attack"
    ) {
      setArrow(null);
      return;
    }
    const matEl = matContainerRef.current;
    const aEl = cardRegistry.get(snapForArrow.event.attacker_iid);
    const tEl = cardRegistry.get(snapForArrow.event.target_iid);
    if (!matEl || !aEl || !tEl) {
      setArrow(null);
      return;
    }
    const matRect = matEl.getBoundingClientRect();
    const aRect = aEl.getBoundingClientRect();
    const tRect = tEl.getBoundingClientRect();
    setArrow({
      x1: aRect.left + aRect.width / 2 - matRect.left,
      y1: aRect.top + aRect.height / 2 - matRect.top,
      x2: tRect.left + tRect.width / 2 - matRect.left,
      y2: tRect.top + tRect.height / 2 - matRect.top,
    });
  }, [snapForArrow, cardRegistry]);

  // 前回のスナップショットと比較してカード移動を検出 → 飛行オーバーレイをスケジュール
  useLayoutEffect(() => {
    const oldCardCache = new Map(cardPosCache.current);
    // 新しい位置キャッシュを更新
    const newCache = new Map<number, DOMRect>();
    for (const [iid, el] of cardRefs.current.entries()) {
      newCache.set(iid, el.getBoundingClientRect());
    }
    cardPosCache.current = newCache;

    const prev = prevSnapRef.current;
    const cur = snapForArrow;
    prevSnapRef.current = cur ?? null;
    if (!prev || !cur) return;

    const matEl = matContainerRef.current;
    if (!matEl) return;
    const matRect = matEl.getBoundingClientRect();

    const newFlights: Flight[] = [];
    // play flight に対応する到着前キャラ iid (この set に居る間 BoardCard を opacity:0)
    const incomingToAdd: number[] = [];
    const now = Date.now();

    for (let p = 0; p < 2; p++) {
      const pp = prev.players[p];
      const cp = cur.players[p];

      // (1) Char → Trash: instance_id が消滅 + trash 数増加
      const curIds = new Set(cp.characters.map((c) => c.instance_id));
      const lostChars = pp.characters.filter(
        (c) => !curIds.has(c.instance_id),
      );
      const trashGain = cp.trash_count - pp.trash_count;
      const koCount = Math.min(lostChars.length, Math.max(0, trashGain));
      const trashEl = zoneRefs.current.get(`trash-${p}`);
      if (koCount > 0 && trashEl) {
        const trashRect = trashEl.getBoundingClientRect();
        const toX = trashRect.left + trashRect.width / 2 - matRect.left;
        const toY = trashRect.top + trashRect.height / 2 - matRect.top;
        for (let i = 0; i < koCount; i++) {
          const lost = lostChars[i];
          const fromRect = oldCardCache.get(lost.instance_id);
          if (!fromRect) continue;
          newFlights.push({
            id: `ko-${lost.instance_id}-${now}-${i}`,
            cardId: lost.card_id,
            onTopMat: p === oppIdx,
            fromX: fromRect.left + fromRect.width / 2 - matRect.left,
            fromY: fromRect.top + fromRect.height / 2 - matRect.top,
            toX,
            toY,
            startBack: false,
            endBack: false,
          });
        }
      }

      // (1.5) キャラ登場 (手札 → 場): log "play:" + 新規 instance_id + hand-1
      const prevCharIds = new Set(pp.characters.map((c) => c.instance_id));
      const newChars = cp.characters.filter(
        (c) => !prevCharIds.has(c.instance_id),
      );
      const isPlayLog = /(?:^|: )\s*play: /.test(cur.log);
      if (
        isPlayLog &&
        newChars.length > 0 &&
        cp.hand.length < pp.hand.length &&
        cur.turn_player_idx === p
      ) {
        const handEl = zoneRefs.current.get(`hand-${p}`);
        if (handEl) {
          const handRect = handEl.getBoundingClientRect();
          const fromX = handRect.left + handRect.width / 2 - matRect.left;
          const fromY = handRect.top + handRect.height / 2 - matRect.top;
          for (const newChar of newChars) {
            const toRect = newCache.get(newChar.instance_id);
            if (!toRect) continue;
            newFlights.push({
              id: `play-${newChar.instance_id}-${now}`,
              cardId: newChar.card_id,
              onTopMat: p === oppIdx,
              fromX,
              fromY,
              toX: toRect.left + toRect.width / 2 - matRect.left,
              toY: toRect.top + toRect.height / 2 - matRect.top,
              startBack: false,
              endBack: false,
            });
            incomingToAdd.push(newChar.instance_id);
          }
        }
      }

      // (2) Event 再生: log が "event:" で始まる + hand-1 + trash+1
      //     → hand → leader 横で一旦表示 → trash の 2 段モーション
      const isEventLog =
        /(?:^|: )\s*event: /.test(cur.log) &&
        !cur.log.includes("counter event:");
      if (
        isEventLog &&
        cp.hand.length === pp.hand.length - 1 &&
        cp.trash.length === pp.trash.length + 1 &&
        // ログの "T# P{owner}:" でターンプレイヤーが p のとき
        cur.turn_player_idx === p
      ) {
        const newCardId = cp.trash[cp.trash.length - 1];
        const handEl = zoneRefs.current.get(`hand-${p}`);
        const leaderEl = cardRefs.current.get(cp.leader.instance_id);
        const trashEl = zoneRefs.current.get(`trash-${p}`);
        if (handEl && leaderEl && trashEl) {
          const handRect = handEl.getBoundingClientRect();
          const leaderRect = leaderEl.getBoundingClientRect();
          const trashRect = trashEl.getBoundingClientRect();
          // 「各リーダーから見て左側」にイベントを設置・実行する。
          // - 自分マット (selfIdx, 非回転): leader 視点の左 = 画面の左 → -90
          // - 相手マット (oppIdx, rotate-180): leader 視点の左 = 画面の右 → +90
          // (snap idx ではなく selfIdx/oppIdx で判定しないと deck_a 後攻時に逆転する)
          const midOffsetX = p === oppIdx ? 90 : -90;
          newFlights.push({
            id: `event-${p}-${now}`,
            cardId: newCardId ?? "",
            onTopMat: p === oppIdx,
            fromX: handRect.left + handRect.width / 2 - matRect.left,
            fromY: handRect.top + handRect.height / 2 - matRect.top,
            midX:
              leaderRect.left +
              leaderRect.width / 2 -
              matRect.left +
              midOffsetX,
            midY: leaderRect.top + leaderRect.height / 2 - matRect.top,
            midHoldMs: 700,
            toX: trashRect.left + trashRect.width / 2 - matRect.left,
            toY: trashRect.top + trashRect.height / 2 - matRect.top,
            startBack: false,
            endBack: false,
          });
        }
      }

      // (3a) 手札増減インジケータ
      //   増加: 必ず +N 表示 (ドロー / ライフ→手札 / サーチ など)
      //   減少: 「捨て」を含むログのみ -N 表示。play/event/stage/atk(=counter spend) は表示しない。
      const dhand = cp.hand.length - pp.hand.length;
      if (dhand !== 0) {
        const handEl = zoneRefs.current.get(`hand-${p}`);
        let show: { text: string; color: string } | null = null;
        if (dhand > 0) {
          show = { text: `+${dhand}`, color: "#16a34a" }; // green-600
        } else {
          // 減少: 捨て効果のときのみ表示
          if (cur.log.includes("捨て")) {
            show = { text: `${dhand}`, color: "#dc2626" }; // red-600
          }
        }
        if (show && handEl) {
          const handRect = handEl.getBoundingClientRect();
          const id = `hand-dmg-${p}-${now}`;
          setDamageIndicators((d) => [
            ...d,
            {
              id,
              text: show.text,
              x: handRect.left + handRect.width / 2 - matRect.left,
              y: handRect.top + handRect.height / 2 - matRect.top,
              color: show.color,
            },
          ]);
          setTimeout(() => {
            setDamageIndicators((d) => d.filter((x) => x.id !== id));
          }, 1400);
        }
      }

      // (3b) Life ダメージ/回復インジケータ + Life → Hand 飛行
      const dlife = pp.life_count - cp.life_count;
      if (dlife !== 0) {
        const lifeEl = zoneRefs.current.get(`life-${p}`);
        if (lifeEl) {
          const lifeRect = lifeEl.getBoundingClientRect();
          const isDamage = dlife > 0;
          const dmgId = `dmg-${p}-${now}`;
          setDamageIndicators((d) => [
            ...d,
            {
              id: dmgId,
              text: isDamage ? `-${dlife}` : `+${-dlife}`,
              x: lifeRect.left + lifeRect.width / 2 - matRect.left,
              y: lifeRect.top + lifeRect.height / 2 - matRect.top,
              color: isDamage ? "#dc2626" : "#16a34a", // red-600 / green-600
            },
          ]);
          setTimeout(() => {
            setDamageIndicators((d) => d.filter((x) => x.id !== dmgId));
          }, 1400);
        }
      }
      if (dlife > 0 && cp.hand.length > pp.hand.length) {
        const lifeEl = zoneRefs.current.get(`life-${p}`);
        const handEl = zoneRefs.current.get(`hand-${p}`);
        if (lifeEl && handEl) {
          const lifeRect = lifeEl.getBoundingClientRect();
          const handRect = handEl.getBoundingClientRect();
          const fromX = lifeRect.left + lifeRect.width / 2 - matRect.left;
          const fromY = lifeRect.top + lifeRect.height / 2 - matRect.top;
          const toX = handRect.left + handRect.width / 2 - matRect.left;
          const toY = handRect.top + handRect.height / 2 - matRect.top;
          // 新しく増えたカード = cur.hand の末尾分 (ヒューリスティック)
          const newCards = cp.hand.slice(pp.hand.length);
          for (let i = 0; i < Math.min(dlife, newCards.length); i++) {
            newFlights.push({
              id: `lh-${p}-${i}-${now}`,
              cardId: newCards[i] ?? "",
              onTopMat: p === oppIdx,
              fromX,
              fromY,
              toX,
              toY,
              startBack: true,
              endBack: false,
            });
          }
        }
      }

      // === DON!! トークンの移動アニメ === //
      // 各 InPlay の attached_dons をマップにまとめ、prev/cur 差分から (return / attach) を検出
      const collectAttached = (snap: typeof pp) => {
        const m = new Map<number, number>();
        m.set(snap.leader.instance_id, snap.leader.attached_dons);
        for (const c of snap.characters) m.set(c.instance_id, c.attached_dons);
        for (const s of snap.stages) m.set(s.instance_id, s.attached_dons);
        return m;
      };
      const prevAttached = collectAttached(pp);
      const curAttached = collectAttached(cp);
      const costEl = zoneRefs.current.get(`costarea-${p}`);
      const costRect = costEl?.getBoundingClientRect();
      const costCx = costRect
        ? costRect.left + costRect.width / 2 - matRect.left
        : 0;
      const costCy = costRect
        ? costRect.top + costRect.height / 2 - matRect.top
        : 0;

      // (4) DON Deck → Cost Area (DON フェイズの 1〜2 枚分配)
      const ddDelta = pp.don_remaining_in_deck - cp.don_remaining_in_deck;
      if (ddDelta > 0 && costRect) {
        const ddEl = zoneRefs.current.get(`dondeck-${p}`);
        if (ddEl) {
          const ddRect = ddEl.getBoundingClientRect();
          const fromX = ddRect.left + ddRect.width / 2 - matRect.left;
          const fromY = ddRect.top + ddRect.height / 2 - matRect.top;
          for (let i = 0; i < ddDelta; i++) {
            newFlights.push({
              id: `don-draw-${p}-${i}-${now}`,
              cardId: "",
              isDon: true,
              onTopMat: p === oppIdx,
              delayMs: i * 120,
              fromX,
              fromY,
              toX: costCx,
              toY: costCy,
              startBack: false,
              endBack: false,
            });
          }
        }
      }

      // (5) Char/Leader → Cost Area (REFRESH 時の付与 DON 戻り)
      if (costRect) {
        let returnStagger = 0;
        for (const [iid, prevCount] of prevAttached) {
          const curCount = curAttached.get(iid) ?? 0;
          const delta = prevCount - curCount;
          if (delta <= 0) continue;
          // 既に場から消えた (KO 等) キャラは oldCardCache、生存中は newCache
          const fromRect = newCache.get(iid) ?? oldCardCache.get(iid);
          if (!fromRect) continue;
          const fromX = fromRect.left + fromRect.width / 2 - matRect.left;
          const fromY = fromRect.top + fromRect.height / 2 - matRect.top;
          for (let i = 0; i < delta; i++) {
            newFlights.push({
              id: `don-return-${p}-${iid}-${i}-${now}`,
              cardId: "",
              isDon: true,
              onTopMat: p === oppIdx,
              delayMs: returnStagger,
              fromX,
              fromY,
              toX: costCx,
              toY: costCy,
              startBack: false,
              endBack: false,
            });
            returnStagger += 80;
          }
        }
      }

      // (6) Cost Area (active) → Leader/Char (DON 付与)
      if (costRect) {
        let attachStagger = 0;
        for (const [iid, curCount] of curAttached) {
          const prevCount = prevAttached.get(iid) ?? 0;
          const delta = curCount - prevCount;
          if (delta <= 0) continue;
          const toR = newCache.get(iid);
          if (!toR) continue;
          const toX = toR.left + toR.width / 2 - matRect.left;
          const toY = toR.top + toR.height / 2 - matRect.top;
          for (let i = 0; i < delta; i++) {
            newFlights.push({
              id: `don-attach-${p}-${iid}-${i}-${now}`,
              cardId: "",
              isDon: true,
              onTopMat: p === oppIdx,
              delayMs: attachStagger,
              fromX: costCx,
              fromY: costCy,
              toX,
              toY,
              startBack: false,
              endBack: false,
            });
            attachStagger += 80;
          }
        }
      }
    }

    if (newFlights.length === 0) return;
    setFlights((f) => [...f, ...newFlights]);
    if (incomingToAdd.length > 0) {
      setIncomingIids((prev) => {
        const next = new Set(prev);
        for (const iid of incomingToAdd) next.add(iid);
        return next;
      });
    }
    const ids = newFlights.map((f) => f.id);
    // 最長の飛行を計算してクリーンアップ。DON は delayMs (stagger) + 600ms 必要、
    // mid 経由 flight は 1500ms、通常 flight は 800ms。
    const baseDuration = newFlights.some((f) => f.midX !== undefined) ? 1500 : 800;
    const donMaxDelay = newFlights.reduce(
      (m, f) => (f.isDon ? Math.max(m, (f.delayMs ?? 0) + 600) : m),
      0,
    );
    const maxDuration = Math.max(baseDuration, donMaxDelay);
    setTimeout(() => {
      setFlights((f) => f.filter((x) => !ids.includes(x.id)));
      if (incomingToAdd.length > 0) {
        setIncomingIids((prev) => {
          if (prev.size === 0) return prev;
          const next = new Set(prev);
          for (const iid of incomingToAdd) next.delete(iid);
          return next;
        });
      }
    }, maxDuration);
  }, [snapForArrow]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (snapshots.length === 0) {
    return (
      <div className="rounded border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        スナップショットなし
      </div>
    );
  }

  const snap = snapshots[idx];
  const acting = snap.turn_player_idx;

  const onPrev = () => {
    setPlaying(false);
    withViewTransition(() => setIdx((i) => Math.max(0, i - 1)));
  };
  const onNext = () => {
    setPlaying(false);
    withViewTransition(() =>
      setIdx((i) => Math.min(snapshots.length - 1, i + 1)),
    );
  };
  const onJumpTurn = (delta: 1 | -1) => {
    setPlaying(false);
    withViewTransition(() => {
      setIdx((i) => {
        const target = snapshots[i].turn + delta;
        if (delta > 0) {
          for (let j = i + 1; j < snapshots.length; j++) {
            if (snapshots[j].turn >= target) return j;
          }
          return snapshots.length - 1;
        } else {
          for (let j = i - 1; j >= 0; j--) {
            if (
              snapshots[j].turn <= target &&
              snapshots[j].turn !== snapshots[i].turn
            ) {
              return j;
            }
          }
          return 0;
        }
      });
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {/* 上端: フェーズストリップ (画面の上に固定表示) */}
      <PhaseStrip snap={snap} aName={playerName[0]} bName={playerName[1]} />

      {/* 3 列レイアウト
            ┌──────────────┬─────────────┬──────────────┐
            │ HOVER Preview│  Opp Mat    │  OPP HAND    │
            │ (top-L)      │  (180°)     │  (top-R)     │
            │              │  ────────   │              │
            │              │  Self Mat   │              │
            │              │             │              │
            │ Self HAND    │             │ Log+Controls │
            │ (bot-L)      │             │ (bot-R)      │
            └──────────────┴─────────────┴──────────────┘
      */}
      <HoverContext.Provider value={setHovered}>
      <CardRefContext.Provider value={cardRegistry}>
      <ZoneRefContext.Provider value={zoneRegistry}>
      <div className="flex min-h-0 w-full flex-1 gap-2">
        {/* 左サイド: 上=Preview (3) / 下=自分手札 (2) */}
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          {/* 左上: プレビュー + 情報 (flex-3) */}
          <div className="flex min-h-0 flex-[3] flex-col gap-1 rounded bg-amber-950/40 p-2 ring-1 ring-amber-950/60">
            <div className="text-[10px] uppercase tracking-wide text-amber-200/70">
              Card Preview
            </div>
            <div className="flex min-h-0 flex-1 items-start justify-center overflow-hidden">
              {hovered ? (
                <CardImage
                  cardId={hovered.cardId}
                  alt={hovered.name ?? hovered.cardId}
                  loading="eager"
                  className="block h-full w-auto max-w-full rounded object-contain shadow-lg ring-1 ring-amber-900/40"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-[11px] text-amber-200/40">
                  カードにホバーすると拡大表示
                </div>
              )}
            </div>
            {hovered && (
              <div className="space-y-0.5 text-amber-100/90">
                {hovered.name && (
                  <div className="truncate text-[12px] font-medium">
                    {hovered.name}
                  </div>
                )}
                <div className="font-mono text-[10px] text-amber-200/60">
                  {hovered.cardId}
                </div>
                {(hovered.power !== undefined ||
                  (hovered.attachedDons !== undefined &&
                    hovered.attachedDons > 0) ||
                  hovered.summoningSickness) && (
                  <div className="flex flex-wrap items-center gap-2 text-[11px]">
                    {hovered.power !== undefined && (
                      <span className="font-mono text-amber-100">
                        P={hovered.power}
                      </span>
                    )}
                    {hovered.attachedDons !== undefined &&
                      hovered.attachedDons > 0 && (
                        <span className="rounded bg-amber-500/20 px-1 font-mono text-amber-200">
                          DON×{hovered.attachedDons}
                        </span>
                      )}
                    {hovered.summoningSickness && (
                      <span className="rounded bg-zinc-500/20 px-1 text-[10px] text-zinc-200">
                        召喚酔
                      </span>
                    )}
                  </div>
                )}
                {hovered.keywords && hovered.keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {hovered.keywords.map((k) => (
                      <span
                        key={k}
                        className="rounded bg-amber-200/20 px-1 text-[10px] text-amber-100"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 左下: 自分の手札 (flex-2) — selfIdx 固定 */}
          <HandPanel
            className="min-h-0 flex-[2]"
            hand={snap.players[selfIdx].hand}
            count={snap.players[selfIdx].hand_count}
            name={playerName[selfIdx]}
            active={acting === selfIdx}
            zoneId={`hand-${selfIdx}`}
          />
        </div>

        {/* 中央: マット (固定幅 720px、5 レストキャラ並ぶ攻撃シーン基準)
            両マットを grid-rows: 1fr 1fr で完全に同じ高さに。
            ネームプレートは container 側で絶対配置 → 視点的に常に各マット左上に表示。 */}
        <div
          ref={matContainerRef}
          className="relative grid shrink-0 gap-1 overflow-hidden rounded-xl border-4 border-amber-950 bg-gradient-to-b from-amber-900 via-amber-800 to-amber-900 p-2 shadow-2xl"
          style={{
            width: 720,
            gridTemplateRows: "minmax(0, 1fr) minmax(0, 1fr)",
          }}
        >
          {/* 相手マット (180° 反転) — 外側ラッパは非回転 relative にして
              NamePlate を絶対配置で左上にぴったり付ける */}
          <div className="relative flex min-h-0 flex-col">
            <div className="flex min-h-0 flex-1 flex-col rotate-180">
              <PlayerMat
                player={snap.players[oppIdx]}
                active={acting === oppIdx}
                playerIdx={oppIdx}
                incomingIids={incomingIids}
                onOpenTrash={(cards) =>
                  setTrashModal({
                    title: `${playerName[oppIdx]} のトラッシュ (${cards.length})`,
                    cards,
                  })
                }
              />
            </div>
            <NamePlate
              name={playerName[oppIdx]}
              active={acting === oppIdx}
              className="absolute left-0 top-0 z-20"
            />
            {snap.game_over && snap.winner !== null && (
              <ResultBanner won={snap.winner === oppIdx} />
            )}
          </div>
          {/* 自分マット */}
          <div className="relative flex min-h-0 flex-col">
            <PlayerMat
              player={snap.players[selfIdx]}
              active={acting === selfIdx}
              playerIdx={selfIdx}
              incomingIids={incomingIids}
              onOpenTrash={(cards) =>
                setTrashModal({
                  title: `${playerName[selfIdx]} のトラッシュ (${cards.length})`,
                  cards,
                })
              }
            />
            <NamePlate
              name={playerName[selfIdx]}
              active={acting === selfIdx}
              className="absolute left-0 top-0 z-20"
            />
            {snap.game_over && snap.winner !== null && (
              <ResultBanner won={snap.winner === selfIdx} />
            )}
          </div>

          {/* アタック矢印 SVG オーバーレイ (attacker → target) + パワー表示 */}
          {arrow && snap.event && (
            <svg
              className="pointer-events-none absolute inset-0 z-30"
              style={{ width: "100%", height: "100%" }}
            >
              <defs>
                <marker
                  id="arrowhead"
                  markerWidth="40"
                  markerHeight="40"
                  refX="36"
                  refY="20"
                  orient="auto"
                  markerUnits="userSpaceOnUse"
                >
                  {/* 大きめの塗りつぶし三角 + 黒縁取りで視認性 UP */}
                  <path
                    d="M0,2 L40,20 L0,38 Z"
                    fill="#ef4444"
                    stroke="#7f1d1d"
                    strokeWidth="2"
                    strokeLinejoin="round"
                  />
                </marker>
              </defs>
              <line
                x1={arrow.x1}
                y1={arrow.y1}
                x2={arrow.x2}
                y2={arrow.y2}
                stroke="#ef4444"
                strokeWidth="7"
                strokeLinecap="round"
                markerEnd="url(#arrowhead)"
                opacity="0.95"
              />
              {/* attacker の最終パワー (赤文字 + 縁取り白で視認性) */}
              <text
                x={arrow.x1}
                y={arrow.y1}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="22"
                fontWeight="900"
                fill="#dc2626"
                stroke="white"
                strokeWidth="3"
                paintOrder="stroke"
                style={{ fontFamily: "ui-monospace, monospace" }}
              >
                {snap.event.atk_power}
              </text>
              {/* target の最終パワー */}
              <text
                x={arrow.x2}
                y={arrow.y2}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="22"
                fontWeight="900"
                fill="#dc2626"
                stroke="white"
                strokeWidth="3"
                paintOrder="stroke"
                style={{ fontFamily: "ui-monospace, monospace" }}
              >
                {snap.event.defender_power}
              </text>
            </svg>
          )}

          {/* 飛行カードオーバーレイ (KO / life→hand 等の移動アニメ) */}
          {flights.map((f) => (
            <FlyingCard key={f.id} flight={f} />
          ))}

          {/* ライフダメージインジケータ ("-N" 赤字フロート) */}
          {damageIndicators.map((d) => (
            <DamagePop key={d.id} indicator={d} />
          ))}
        </div>

        {/* 右サイド: 上=相手手札 (2) / 下=Log+Controls (3) */}
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          {/* 右上: 相手の手札 (flex-2) — oppIdx 固定 */}
          <HandPanel
            className="min-h-0 flex-[2]"
            hand={snap.players[oppIdx].hand}
            count={snap.players[oppIdx].hand_count}
            name={playerName[oppIdx]}
            active={acting === oppIdx}
            hidden
            zoneId={`hand-${oppIdx}`}
          />

          {/* 右下: ログ + コントロール (flex-3) */}
          <div className="flex min-h-0 flex-[3] flex-col gap-2 rounded bg-amber-950/40 p-2 ring-1 ring-amber-950/60">
            {/* コントロール */}
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-1">
                <Btn onClick={() => onJumpTurn(-1)} title="前のターンへ">⏮</Btn>
                <Btn onClick={onPrev} title="前のステップ" disabled={idx === 0}>◀</Btn>
                <Btn
                  onClick={() => setPlaying((p) => !p)}
                  variant="primary"
                  disabled={idx >= snapshots.length - 1}
                >
                  {playing ? "❚❚" : "▶"}
                </Btn>
                <Btn onClick={onNext} title="次のステップ" disabled={idx >= snapshots.length - 1}>▶</Btn>
                <Btn onClick={() => onJumpTurn(1)} title="次のターンへ">⏭</Btn>
              </div>
              <div className="flex flex-wrap items-center gap-1 text-[11px] text-amber-100/80">
                速度
                {SPEEDS.map((s, i) => (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => setSpeedIdx(i)}
                    className={`rounded px-2 py-0.5 ${
                      speedIdx === i
                        ? "bg-amber-300 text-amber-950"
                        : "border border-amber-200/40"
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
                <label className="ml-2 flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={followLog}
                    onChange={(e) => setFollowLog(e.target.checked)}
                  />
                  📌 追従
                </label>
              </div>
              <input
                type="range"
                min={0}
                max={snapshots.length - 1}
                value={idx}
                onChange={(e) => {
                  setPlaying(false);
                  setIdx(Number(e.target.value));
                }}
                className="w-full"
              />
            </div>

            {/* ログ */}
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-amber-950/60 pt-2">
              <div className="mb-1 text-[10px] uppercase tracking-wide text-amber-200/70">
                Log  step {idx + 1}/{snapshots.length}
              </div>
              <LogTrackCompact
                snapshots={snapshots}
                idx={idx}
                follow={followLog}
                onJump={(i) => {
                  setPlaying(false);
                  setIdx(i);
                }}
              />
            </div>
          </div>
        </div>
      </div>
      </ZoneRefContext.Provider>
      </CardRefContext.Provider>

      {/* トラッシュモーダル (HoverContext 内に置いて、内部のカードホバーでプレビュー連動) */}
      {trashModal && (
        <TrashModal
          title={trashModal.title}
          cards={trashModal.cards}
          onClose={() => setTrashModal(null)}
        />
      )}
      </HoverContext.Provider>
    </div>
  );
}

function PhaseStrip({
  snap,
  aName,
  bName,
}: {
  snap: StateSnapshot;
  aName: string;
  bName: string;
}) {
  const playerName = snap.turn_player_idx === 0 ? aName : bName;
  const phaseColor: Record<string, string> = {
    REFRESH: "bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100",
    DRAW: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100",
    DON: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
    MAIN: "bg-violet-100 text-violet-900 dark:bg-violet-900 dark:text-violet-100",
    END: "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100",
  };
  return (
    <div className="flex items-center justify-center gap-3 border-y border-zinc-200 bg-white py-1.5 text-xs dark:border-zinc-800 dark:bg-zinc-900">
      <span className="font-mono">T{snap.turn}</span>
      <span
        className={`rounded px-2 py-0.5 font-medium ${
          phaseColor[snap.phase] ?? "bg-zinc-100 dark:bg-zinc-800"
        }`}
      >
        {snap.phase}
      </span>
      <span className="text-zinc-600 dark:text-zinc-400">{playerName} のターン</span>
      {snap.game_over && (
        <span className="rounded bg-rose-100 px-2 py-0.5 font-medium text-rose-900 dark:bg-rose-900 dark:text-rose-100">
          GAME OVER
        </span>
      )}
    </div>
  );
}

// ゲーム終了時に各マット中央へオーバーレイ表示する WIN / LOSE バナー。
// 親ラッパは relative なので absolute inset-0 で覆い、rotate-180 を継承しないよう
// 必ず PlayerMat (相手側は rotate-180 ラッパ) の **外側** に置くこと。
function ResultBanner({ won }: { won: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center">
      {won ? (
        <span
          className="select-none text-8xl font-black tracking-[0.25em] text-amber-300"
          style={{
            textShadow:
              "0 0 24px rgba(251,191,36,0.95), 0 0 56px rgba(251,191,36,0.55), 0 4px 8px rgba(0,0,0,0.5)",
            WebkitTextStroke: "2px rgba(120,53,15,0.85)",
          }}
        >
          WIN
        </span>
      ) : (
        <span
          className="select-none text-8xl font-black tracking-[0.25em] text-zinc-400/80"
          style={{
            textShadow: "0 4px 14px rgba(0,0,0,0.65)",
            WebkitTextStroke: "1px rgba(63,63,70,0.65)",
          }}
        >
          LOSE
        </span>
      )}
    </div>
  );
}

function PlayerMat({
  player,
  active,
  playerIdx,
  incomingIids,
  onOpenTrash,
}: {
  player: PlayerSnapshot;
  active: boolean;
  playerIdx: 0 | 1;
  incomingIids?: Set<number>;
  onOpenTrash?: (cards: string[]) => void;
}) {
  const stage = player.stages[0] ?? null;
  return (
    <div
      className={`relative grid min-h-0 flex-1 gap-1 rounded-lg bg-gradient-to-b from-emerald-100/85 via-emerald-50/85 to-emerald-100/85 p-1 ring-1 ring-emerald-900/30 ${
        active
          ? "outline outline-4 outline-amber-400 shadow-[inset_0_0_16px_rgba(251,191,36,0.6)]"
          : ""
      }`}
      style={{ gridTemplateColumns: "auto 1fr" }}
    >

      {/* 左列: LIFE pile (上) + DON DECK pile (下) */}
      <div className="flex flex-col items-center justify-between gap-1 pt-3.5">
        <LifePile count={player.life_count} zoneId={`life-${playerIdx}`} />
        <DonDeckPile
          count={player.don_remaining_in_deck}
          zoneId={`dondeck-${playerIdx}`}
        />
      </div>

      {/* 右列: 3 段 (chars / leader-stage-deck / cost-trash)。空き高は chars 行で吸収。 */}
      <div className="flex min-h-0 flex-col gap-0.5">
        {/* CHARACTER AREA — flex-1 で残余高を吸収 */}
        <div className="relative flex flex-1 items-center justify-center gap-2 rounded bg-emerald-200/40 px-2 py-0.5 ring-1 ring-emerald-700/30">
          <span className="absolute right-2 top-0 text-[9px] font-bold uppercase tracking-widest text-emerald-900/40">
            CHARACTER AREA
          </span>
          {player.characters.length === 0 && (
            <div style={{ height: 123 }} className="opacity-0">.</div>
          )}
          {player.characters.map((c) => (
            <BoardCard
              key={c.instance_id}
              card={c}
              incoming={incomingIids?.has(c.instance_id) ?? false}
            />
          ))}
        </div>

        {/* LEADER + STAGE + DECK
            DECK と STAGE は右端にピン留めし、LEADER が rest して横向きになっても
            それらの位置は動かない。LEADER の左端だけが左へ伸びる (justify-end の効果)。 */}
        <div className="flex shrink-0 items-center justify-end gap-2 rounded bg-emerald-200/30 px-2 py-0.5 ring-1 ring-emerald-700/20">
          <BoardCard card={player.leader} isLeader />
          {stage ? <BoardCard card={stage} /> : <CardSlot label="STAGE" />}
          <DeckPile count={player.deck_count} />
        </div>

        {/* COST AREA + TRASH (高さ固定 + overflow-hidden + items-start:
            DON カードの下 1/4 程度ははみ出して見えなくなる前提で短めに圧縮。
            items-start で「Cost Area …」ラベルを常に行上端に固定 (DON 数の変化で
            CostArea 全体が上下に動かない)。 ) */}
        <div
          className="flex shrink-0 items-start gap-2 overflow-hidden rounded bg-emerald-200/30 px-2 py-0.5 ring-1 ring-emerald-700/20"
          style={{ height: 100 }}
        >
          <CostArea
            active={player.don_active}
            rested={player.don_rested}
            zoneId={`costarea-${playerIdx}`}
          />
          <TrashPile
            count={player.trash_count}
            zoneId={`trash-${playerIdx}`}
            cards={player.trash}
            onClick={onOpenTrash}
          />
        </div>
      </div>
    </div>
  );
}

// === トラッシュ閲覧モーダル (画面下寄せ・横スクロールカルーセル) === //
function TrashModal({
  title,
  cards,
  onClose,
}: {
  title: string;
  cards: string[];
  onClose: () => void;
}) {
  // ESC で閉じる
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="pointer-events-none fixed inset-0 z-[100] flex items-end justify-center"
      onClick={onClose}
    >
      <div
        className="pointer-events-auto flex w-full flex-col gap-3 rounded-t-xl border-t-2 border-amber-900 bg-zinc-900 p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-medium text-amber-100">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded bg-zinc-700 px-3 py-1 text-sm text-zinc-100 hover:bg-zinc-600"
          >
            閉じる (ESC)
          </button>
        </div>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {cards.length === 0 ? (
            <span className="text-sm text-zinc-400">(空)</span>
          ) : (
            cards.map((cid, i) => (
              <TrashModalCard key={`${i}-${cid}`} cardId={cid} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function TrashModalCard({ cardId }: { cardId: string }) {
  const hover = useHoverHandlers({ cardId });
  return (
    <div className="flex shrink-0 flex-col items-center gap-1" {...hover}>
      <CardImage
        cardId={cardId}
        alt={cardId}
        className="block w-40 rounded shadow-lg ring-1 ring-zinc-600"
      />
      <span className="font-mono text-[10px] text-zinc-400">{cardId}</span>
    </div>
  );
}

// === ライフダメージ/回復インジケータ ("-N" 赤 / "+N" 緑、上方向にフェード) === //
function DamagePop({ indicator }: { indicator: DamageIndicator }) {
  return (
    <div
      className="pointer-events-none absolute z-50 font-mono font-black"
      style={{
        left: indicator.x,
        top: indicator.y,
        transform: "translate(-50%, -50%)",
        fontSize: "44px",
        color: indicator.color,
        textShadow:
          "0 0 4px white, 0 0 4px white, 2px 2px 0 white, -2px -2px 0 white, 2px -2px 0 white, -2px 2px 0 white",
        animation: "damage-pop 1.4s cubic-bezier(0.4, 0, 0.2, 1) forwards",
      }}
    >
      {indicator.text}
    </div>
  );
}

// === 飛行カード (KO / life→hand / イベントなどの移動アニメ用) === //
function FlyingCard({ flight }: { flight: Flight }) {
  // 経由点 mid がある場合: from → mid (300ms) → hold (midHoldMs) → to (300ms)
  // それ以外: from → to (700ms / DON は 450ms)
  const hasMid = flight.midX !== undefined && flight.midY !== undefined;
  const [pos, setPos] = useState({ x: flight.fromX, y: flight.fromY });
  const [transitionMs, setTransitionMs] = useState(0);
  const [showBack, setShowBack] = useState(flight.startBack);
  const [visible, setVisible] = useState(!flight.delayMs);

  useEffect(() => {
    const delay = flight.delayMs ?? 0;
    const tDelay = delay > 0 ? setTimeout(() => setVisible(true), delay) : null;
    const raf = requestAnimationFrame(() => {
      const startMove = () => {
        if (hasMid) {
          setTransitionMs(300);
          setPos({ x: flight.midX!, y: flight.midY! });
          const hold = flight.midHoldMs ?? 500;
          const t1 = setTimeout(() => {
            setTransitionMs(300);
            setPos({ x: flight.toX, y: flight.toY });
          }, 300 + hold);
          let t2: ReturnType<typeof setTimeout> | undefined;
          if (flight.startBack !== flight.endBack) {
            t2 = setTimeout(() => setShowBack(flight.endBack), 300 + hold + 150);
          }
          return () => {
            clearTimeout(t1);
            if (t2) clearTimeout(t2);
          };
        }
        // mid なし。DON は移動を少し速める
        setTransitionMs(flight.isDon ? 450 : 700);
        setPos({ x: flight.toX, y: flight.toY });
        if (flight.startBack !== flight.endBack) {
          const t = setTimeout(() => setShowBack(flight.endBack), 350);
          return () => clearTimeout(t);
        }
      };
      if (delay > 0) {
        const t = setTimeout(startMove, delay);
        return () => clearTimeout(t);
      }
      return startMove();
    });
    return () => {
      cancelAnimationFrame(raf);
      if (tDelay) clearTimeout(tDelay);
    };
  }, [flight, hasMid]);

  // 通常カード/DON トークンとも 80×112 (場の DON カード w-20 と同サイズに揃える)
  const W = 80;
  const H = 112;
  // 上マット (= 相手マット、rotate-180 されている) を起点/終点とする flight は
  // マットと同じ向きで描画。親 grid (matContainerRef) は非回転なので、ここで
  // 個別に rotate(180deg) を当てる。先攻/後攻と無関係に「上マット = 相手」固定。
  return (
    <div
      className="pointer-events-none absolute z-40"
      style={{
        left: pos.x - W / 2,
        top: pos.y - H / 2,
        width: W,
        height: H,
        transform: flight.onTopMat ? "rotate(180deg)" : undefined,
        transition: `left ${transitionMs}ms cubic-bezier(0.4, 0, 0.2, 1), top ${transitionMs}ms cubic-bezier(0.4, 0, 0.2, 1)`,
      }}
    >
      {flight.isDon ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src="/assets/don.png"
          alt="DON"
          style={{ opacity: visible ? 1 : 0 }}
          className="block h-full w-full rounded shadow-lg ring-2 ring-amber-400"
        />
      ) : showBack ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src="/assets/ura.png"
          alt=""
          style={{ opacity: visible ? 1 : 0 }}
          className="block h-full w-full rounded shadow-lg ring-2 ring-amber-400"
        />
      ) : (
        <CardImage
          cardId={flight.cardId}
          alt={flight.cardId}
          loading="eager"
          style={{ opacity: visible ? 1 : 0 }}
          className="block h-full w-full rounded shadow-lg ring-2 ring-amber-400"
        />
      )}
    </div>
  );
}

// === ネームプレート === //
function NamePlate({
  name,
  active,
  className = "",
}: {
  name: string;
  active: boolean;
  className?: string;
}) {
  return (
    <div
      className={`rounded-tl-lg rounded-br-md px-2 py-px text-[11px] font-medium ${
        active
          ? "bg-amber-400 text-amber-950 shadow-[0_0_8px_rgba(251,191,36,0.7)]"
          : "bg-emerald-900/70 text-amber-100"
      } ${className}`}
    >
      {active && "▶ "}
      {name}
    </div>
  );
}

// === 手札パネル (盤面の左下/右下、横並び flex-wrap) === //
function HandPanel({
  hand,
  count,
  name,
  active,
  hidden = false,
  className = "",
  zoneId,
}: {
  hand: string[];
  count: number;
  name: string;
  active: boolean;
  hidden?: boolean;
  className?: string;
  zoneId?: string;
}) {
  const zoneRef = useZoneRef(zoneId ?? "_unused");
  return (
    <div
      ref={zoneRef}
      className={`flex flex-col gap-1 overflow-hidden rounded bg-amber-950/40 p-2 ring-1 ring-amber-950/60 ${
        active ? "ring-amber-400" : ""
      } ${className}`}
    >
      <span className="text-[10px] font-medium uppercase tracking-wide text-amber-100/80">
        {name} Hand ×{count}
      </span>
      <div className="flex min-h-0 flex-1 flex-wrap content-start items-start gap-1 overflow-y-auto">
        {hand.length === 0 ? (
          <span className="text-[10px] text-amber-200/40">(なし)</span>
        ) : hidden ? (
          hand.map((cid, i) => (
            <HiddenHandCard key={`${i}-${cid}`} cardId={cid} />
          ))
        ) : (
          hand.map((cid, i) => <HandCard key={`${i}-${cid}`} cardId={cid} />)
        )}
      </div>
    </div>
  );
}

// === コンパクトログトラック (左上パネル内) === //
function LogTrackCompact({
  snapshots,
  idx,
  follow,
  onJump,
}: {
  snapshots: StateSnapshot[];
  idx: number;
  follow: boolean;
  onJump: (i: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!follow) return;
    const el = ref.current?.querySelector<HTMLElement>(`[data-step='${idx}']`);
    el?.scrollIntoView({ block: "nearest" });
  }, [idx, follow]);
  return (
    <div
      ref={ref}
      className="flex-1 overflow-y-auto font-mono text-[11px] leading-5"
    >
      {snapshots.map((s, i) => (
        <div
          key={i}
          data-step={i}
          onClick={() => onJump(i)}
          className={`cursor-pointer rounded px-1 ${
            i === idx
              ? "bg-amber-400/40 text-amber-50"
              : i < idx
                ? "text-amber-200/40 hover:bg-amber-900/40"
                : "text-amber-100/70 hover:bg-amber-900/40"
          }`}
        >
          {s.log}
        </div>
      ))}
    </div>
  );
}

// === Playmat の各置場 === //

function CardSlot({ label }: { label: string }) {
  return (
    <div className="grid h-[100px] w-[72px] place-items-center rounded border border-dashed border-emerald-700/40 text-[10px] text-emerald-900/50">
      {label}
    </div>
  );
}

// === パイル: 画像ベースの山札 === //

function CardBack({
  className = "",
  size = "md",
  style,
}: {
  className?: string;
  size?: "sm" | "md";
  style?: React.CSSProperties;
}) {
  // /assets/ura.png (ONE PIECE CARD GAME 公式裏面)
  const w = size === "sm" ? "w-10" : "w-[72px]";
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src="/assets/ura.png"
      alt=""
      style={style}
      className={`block ${w} rounded shadow ring-1 ring-amber-950/40 ${className}`}
    />
  );
}

function DonAsset({
  className = "",
  size = "md",
  style,
}: {
  className?: string;
  size?: "sm" | "md" | "lg";
  style?: React.CSSProperties;
}) {
  // /assets/don.png (公式 DON!! カード画像)
  // md = 通常カード (char/stage) と同じ w-20 (80px)
  // sm = キャラ裏に重ねる用、ピーク表示なので小さめ
  // lg = DON DECK 山札用
  const w = size === "sm" ? "w-9" : size === "lg" ? "w-20" : "w-20";
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src="/assets/don.png"
      alt="DON"
      style={style}
      className={`block ${w} rounded shadow-sm ring-1 ring-amber-900/30 ${className}`}
    />
  );
}

function LifePile({
  count,
  zoneId,
}: {
  count: number;
  zoneId?: string;
}) {
  const zoneRef = useZoneRef(zoneId ?? "_unused");
  // 公式マットの LIFE は 4-5 枚を横向き (寝かせた向き) でずらして重ねる。
  // CardBack 大 (w-16 ≒ 64px) を 90° 回転 → 視覚的には height=64, width=88 程度。
  const cardW = 64;
  const cardH = 88;
  const offsetY = 8;
  return (
    <div className="flex flex-col items-center gap-0.5" ref={zoneRef}>
      <span className="text-[9px] font-medium uppercase tracking-wide text-emerald-900/60">
        Life
      </span>
      <div
        className="relative"
        style={{
          width: cardH,
          height: Math.max(cardW, cardW + (count - 1) * offsetY) + 4,
        }}
      >
        {count === 0 ? (
          <div className="absolute inset-0 grid place-items-center rounded border border-dashed border-emerald-700/40">
            <span className="text-[10px] text-emerald-900/40">0</span>
          </div>
        ) : (
          Array.from({ length: count }).map((_, i) => (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              key={i}
              alt=""
              src="/assets/ura.png"
              className="absolute block rounded shadow ring-1 ring-amber-950/40"
              style={{
                width: cardW,
                top: `${i * offsetY}px`,
                left: (cardH - cardW) / 2,
                transform: "rotate(90deg)",
                transformOrigin: "center center",
              }}
            />
          ))
        )}
      </div>
      <span className="font-mono text-[11px] text-emerald-950/80">{count}</span>
    </div>
  );
}

function DeckPile({ count }: { count: number }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[9px] font-medium uppercase tracking-wide text-emerald-900/60">
        Deck
      </span>
      <div className="relative h-[100px] w-[72px]">
        {count > 0 ? (
          <>
            <CardBack className="absolute inset-0 translate-x-1 translate-y-1 opacity-80" />
            <CardBack className="absolute inset-0" />
          </>
        ) : (
          <CardSlot label="DECK" />
        )}
      </div>
      <span className="font-mono text-[11px] text-emerald-950/80">{count}</span>
    </div>
  );
}

function TrashPile({
  count,
  zoneId,
  cards,
  onClick,
}: {
  count: number;
  zoneId?: string;
  cards?: string[];
  onClick?: (cards: string[]) => void;
}) {
  const zoneRef = useZoneRef(zoneId ?? "_unused");
  const isClickable = onClick !== undefined && cards !== undefined && cards.length > 0;
  return (
    <div className="flex flex-col items-center gap-0.5" ref={zoneRef}>
      <span className="text-[9px] font-medium uppercase tracking-wide text-emerald-900/60">
        Trash
      </span>
      <button
        type="button"
        disabled={!isClickable}
        onClick={() => onClick?.(cards ?? [])}
        className={`grid h-[100px] w-[72px] place-items-center rounded border border-dashed border-emerald-700/40 bg-emerald-50/40 ${
          isClickable
            ? "cursor-pointer transition hover:bg-emerald-100/70 hover:ring-2 hover:ring-emerald-700/40"
            : "cursor-default"
        }`}
      >
        <span className="font-mono text-sm text-emerald-900/70">×{count}</span>
      </button>
    </div>
  );
}

function DonDeckPile({ count, zoneId }: { count: number; zoneId?: string }) {
  const zoneRef = useZoneRef(zoneId ?? "_unused");
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[9px] font-medium uppercase tracking-wide text-emerald-900/60">
        DON Deck
      </span>
      <div ref={zoneRef} className="relative h-[100px] w-[72px]">
        {count > 0 ? (
          <>
            <DonAsset
              size="lg"
              className="absolute inset-0 translate-x-1 translate-y-1 opacity-80 !w-[72px]"
            />
            <DonAsset size="lg" className="absolute inset-0 !w-[72px]" />
          </>
        ) : (
          <CardSlot label="" />
        )}
      </div>
      <span className="font-mono text-[11px] text-emerald-950/80">×{count}</span>
    </div>
  );
}

// 場の DON コストエリア。active と rested を 2 列に重ねる (overlap)。
// DON カードは通常カードと同じ w-20 (80px)、aspect 5:7 → 高さ ≒ 112px。
function CostArea({
  active,
  rested,
  zoneId,
}: {
  active: number;
  rested: number;
  zoneId?: string;
}) {
  const zoneRef = useZoneRef(zoneId ?? "_unused");
  const donW = 80; // = w-20
  const donH = 112;
  const overlap = 18; // 縦置き同士の重ね幅 (~22% visible)
  const restedOverlap = 14; // 横向きは縦が短いのでもう少し詰める
  return (
    <div className="flex flex-1 flex-col gap-0.5">
      <span className="text-[9px] font-medium uppercase tracking-wide text-emerald-900/60">
        Cost Area  active {active} / rested {rested}
      </span>
      <div
        ref={zoneRef}
        className="flex flex-1 items-center gap-2 rounded border border-dashed border-emerald-700/40 bg-emerald-900/10 px-1 py-1"
      >
        {active === 0 && rested === 0 ? (
          <span className="text-[10px] text-emerald-900/40">(空)</span>
        ) : (
          <>
            {/* active 列: 縦置きで重ねる */}
            {active > 0 && (
              <div
                className="relative shrink-0"
                style={{
                  width: donW + (active - 1) * overlap,
                  height: donH,
                }}
                title={`active DON ×${active}`}
              >
                {Array.from({ length: active }).map((_, i) => (
                  <DonAsset
                    key={`a${i}`}
                    className="absolute top-0"
                    style={{ left: `${i * overlap}px` }}
                  />
                ))}
              </div>
            )}
            {/* rested 列: 横向きで重ねる */}
            {rested > 0 && (
              <div
                className="relative shrink-0"
                style={{
                  width: donH + (rested - 1) * restedOverlap,
                  height: donW + 8,
                }}
                title={`rested DON ×${rested}`}
              >
                {Array.from({ length: rested }).map((_, i) => (
                  <DonAsset
                    key={`r${i}`}
                    className="absolute origin-center -rotate-90"
                    style={{
                      // 視覚的左端 = left - (donH-donW)/2 になるので、コンテナ左端 (0) に揃えるには
                      // left = (donH-donW)/2 から始める。これで DON DECK 列に食い込まない。
                      left: `${(donH - donW) / 2 + i * restedOverlap}px`,
                      top: (donW - donH) / 2 + 4,
                    }}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function HandCard({ cardId }: { cardId: string }) {
  const hover = useHoverHandlers({ cardId });
  return (
    <div className="w-16 shrink-0" {...hover}>
      <CardImage
        cardId={cardId}
        alt={cardId}
        className="block w-full rounded shadow-sm ring-1 ring-zinc-300"
      />
    </div>
  );
}

function HiddenHandCard({ cardId }: { cardId: string }) {
  const hover = useHoverHandlers({ cardId });
  return (
    <div className="group relative w-16 shrink-0" {...hover}>
      <CardImage
        cardId={cardId}
        alt={cardId}
        className="block w-full rounded shadow-sm ring-1 ring-zinc-300"
      />
      {/* /assets/ura.png で覆う。ホバーで透明化して公開 */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/assets/ura.png"
        alt=""
        className="absolute inset-0 block w-full rounded shadow-sm ring-1 ring-amber-950/40 transition-opacity group-hover:opacity-0"
      />
    </div>
  );
}

function BoardCard({
  card,
  isLeader = false,
  incoming = false,
}: {
  card: CharSnapshot;
  isLeader?: boolean;
  // true: 飛行アニメ中で「まだ盤面に到着していない」状態 → opacity:0 で隠す。
  // レイアウト/ref 計測のためマウントは維持する。
  incoming?: boolean;
}) {
  // 通常カードは upright。レスト時のみ 90° 回転 (公式準拠)。
  // 相手側の上下逆さは、PlayerMat 全体に rotate-180 を掛けることで実現する。
  // リーダー / キャラ / ステージ すべて同じサイズ。
  const baseW = 80;
  const baseH = Math.round(baseW * 1.4);
  const rested = card.rested;

  // レスト時は bbox が swap (W↔H)
  const wrapperW = rested ? baseH : baseW;
  const wrapperH = rested ? baseW : baseH;
  const hover = useHoverHandlers({
    cardId: card.card_id,
    name: card.name,
    power: card.power,
    keywords: card.keywords,
    attachedDons: card.attached_dons,
    summoningSickness: card.summoning_sickness && !isLeader,
  });

  // 矢印描画のために instance_id を keyed registry に登録
  const cardRegistry = useContext(CardRefContext);
  const cardInstanceId = card.instance_id;
  const registerRef = useCallback(
    (el: HTMLElement | null) => {
      cardRegistry?.register(cardInstanceId, el);
    },
    [cardRegistry, cardInstanceId],
  );

  // 付与 DON はキャラと同サイズ (80×112)、char の裏に少しずつずらして重ねる。
  // 各 DON は右下に donStep px ずれて配置 → 右辺と下辺の 2 辺だけが char の影から覗く。
  const donCount = Math.min(card.attached_dons, 6);
  const donStep = 5; // 1 枚ごとに右下に 5px ずらす
  const donExtraW = donCount > 0 ? donCount * donStep : 0;
  const donExtraH = donCount > 0 ? donCount * donStep : 0;

  return (
    <div
      className="flex flex-col items-center gap-0.5"
      style={{ opacity: incoming ? 0 : 1 }}
      {...hover}
    >
      <div
        ref={registerRef}
        style={{ width: wrapperW + donExtraW, height: wrapperH + donExtraH }}
        className="relative shrink-0"
      >
        {/* 付与 DON カード: char の裏に同サイズ (80×112) で stair-step 重ね。
            「下 (深く重なるほど) = 外側」になるよう、奥の DON ほど右下にずらす。
            z-index は奥のもの (i=0) が小さく char(=10) より十分低、上のもの (i=N-1) が大きい。
            これで char から外へ向かって 上→下 の DON edge が順に見える stair-step に。 */}
        {donCount > 0 &&
          Array.from({ length: donCount }).map((_, i) => {
            const charLeft = (wrapperW - baseW) / 2;
            const charTop = (wrapperH - baseH) / 2;
            // i=0 が最下層 (奥) → 最も外側 (donCount * step)
            // i=N-1 が最上層 (手前) → 最も内側 (1 * step)
            const offset = (donCount - i) * donStep;
            return (
              <DonAsset
                key={i}
                style={{
                  position: "absolute",
                  left: charLeft + offset,
                  top: charTop + offset,
                  zIndex: i,
                }}
              />
            );
          })}
        {card.attached_dons > 6 && (
          <span
            className="absolute z-[7] rounded bg-amber-500 px-1 py-px font-mono text-[9px] font-bold text-white shadow"
            style={{
              left: (wrapperW - baseW) / 2 + 6 * donStep + 4,
              top: (wrapperH - baseH) / 2 + 6 * donStep + 4,
            }}
          >
            +{card.attached_dons - 6}
          </span>
        )}

        {/* キャラ本体 (DON より上、wrapper 中央に配置)。
            注: per-card view-transition-name は rotate-180 親と互換性が悪く
            相手側カードが微小にジャンプするため使わない。setIdx 全体の
            crossfade (withViewTransition + ::view-transition-old(root) ...) のみ採用。 */}
        <div
          style={{
            width: baseW,
            height: baseH,
            left: (wrapperW - baseW) / 2,
            top: (wrapperH - baseH) / 2,
            transform: rested ? "rotate(-90deg)" : undefined,
            transformOrigin: "center center",
            zIndex: 10,
          }}
          className="absolute"
        >
          <CardImage
            cardId={card.card_id}
            alt={card.name}
            className={`block w-full rounded shadow-md ring-1 ring-zinc-300 dark:ring-zinc-700 ${
              card.summoning_sickness && !isLeader ? "opacity-70" : ""
            }`}
          />
          {/* power chip (カード枠内に収める / フル桁表示) */}
          <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 rounded bg-zinc-900/90 px-1 py-px text-[9px] font-mono leading-none text-white">
            {card.power}
          </span>
          {/* keyword icons */}
          {card.keywords.length > 0 && (
            <div className="absolute top-0 left-0 flex flex-col gap-px p-px">
              {card.keywords.includes("ブロッカー") && (
                <span className="rounded bg-blue-600 px-1 text-[8px] text-white">
                  B
                </span>
              )}
              {card.keywords.includes("速攻") && (
                <span className="rounded bg-red-600 px-1 text-[8px] text-white">
                  速
                </span>
              )}
              {card.keywords.includes("ダブルアタック") && (
                <span className="rounded bg-orange-600 px-1 text-[8px] text-white">
                  W
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Btn({
  children,
  onClick,
  variant = "default",
  disabled = false,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  variant?: "default" | "primary";
  disabled?: boolean;
  title?: string;
}) {
  const cls =
    variant === "primary"
      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:opacity-80"
      : "border border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded px-3 py-1 text-sm transition disabled:opacity-40 disabled:cursor-not-allowed ${cls}`}
    >
      {children}
    </button>
  );
}

