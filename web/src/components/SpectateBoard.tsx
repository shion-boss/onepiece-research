"use client";

// AI vs AI 観戦の盤面。 人間vsAI (HumanMatchPlay) と **同じ盤面部品** (PlayerMat / HandRow /
// StatBadge / OpponentInfoPanel / LogSidebar) を read-only で composeし、 全画面・3カラムで
// 見た目を揃える (= 2026-06-06、 ohtsuki 要望)。 各カラム幅も人間vsAI と一致
// (左 min-w-280 flex-1 / 中央 w-780 / 右 w-480)。 右パネルは人間vsAI の RightPanel と同じ並び:
// [ヘッダ] → [PREVIEW (大)] → [ACTION 位置 = 観戦コントロール + 盤面データ]。
import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { StateSnapshot } from "@/lib/types";
import {
  PlayerMat,
  HandRow,
  StatBadge,
  OpponentInfoPanel,
  LogSidebar,
  type HoverInfo,
} from "./HumanMatchPlay";
import { CardImage } from "./CardImage";
// 人間vsAI と同じアニメーション部品を再利用 (= 攻撃ビーム/矢印・ライフflash・KO ghost・効果トースト・
// カウンター・カードプレイ/ドロー)。 観戦は idx を進めるたび snap が変わり useFrameDiff が発火する
// ので、 これらが自然に再生される (= 2026-06-07、 ohtsuki「AIvsAIのUI改善」)。
import {
  useFrameDiff,
  LifeFlashOverlay,
  LeftCharaGhostList,
  EffectToastOverlay,
  AttackBeamOverlay,
  AttackTargetArrowOverlay,
  PlayedCardOverlay,
  DrawCardOverlay,
  CounterPlayOverlay,
  fireCounterPlay,
  // 攻撃解決の演出 (= 防御成功で矢印へし折り / 攻撃成立で矢印突き刺さり / 防御成功バナー)
  ArrowBreakOverlay,
  fireArrowBreak,
  ArrowStrikeOverlay,
  fireArrowStrike,
  DefenseSuccessOverlay,
  fireDefenseSuccess,
} from "./_matchAnimHelpers";

const NOOP = () => {};
const EMPTY_ACTIONS = new Map<number, never[]>();

// compute_breakdown (engine/eval.py) の指標キー → 日本語ラベル (全 78 指標)。 AI が手を判断する
// ときに使う盤面指標 = この内訳。 未掲載キーは生キーをそのまま表示 (= フォールバック)。
const METRIC_LABELS: Record<string, string> = {
  // 基本指標 (重み > 0、 判断を駆動)
  life: "ライフ",
  field_count: "場のキャラ数",
  field_power: "場の総パワー",
  hand: "手札枚数",
  don: "DON数",
  blocker: "ブロッカー",
  attached_don: "付与DON",
  active_chara: "アクティブキャラ",
  lethal: "リーサル(自→相)",
  next_turn_lethal: "次ターンリーサル脅威",
  deck_finisher: "山のフィニッシャー数",
  life_trigger: "ライフトリガー価値",
  chara_quality: "場のキャラ質",
  hand_quality: "手札の質",
  opp_hand_threat: "相手手札の脅威",
  // 拡張指標 (Step2-pre)
  is_first_player: "先攻",
  stage_count: "ステージ数",
  stage_value: "ステージ価値",
  trash_count: "トラッシュ枚数",
  trash_archetype_match: "トラッシュのアーキ適合",
  rush_count: "ラッシュ数",
  double_attack_count: "ダブルアタック数",
  static_cost_reduction_total: "常時コスト軽減合計",
  playable_cost_match: "出せるコスト適合",
  synergy_count: "シナジー数",
  is_my_turn: "自分のターン",
  turn_number_normalized: "ターン数(正規化)",
  dead_card_in_hand: "手札の腐りカード",
  active_blocker_count: "アクティブブロッカー数",
  removal_threat_count: "除去脅威数",
  self_counter_in_hand_total: "手札カウンター合計",
  finisher_in_hand_count: "手札フィニッシャー数",
  keyword_taunt_count: "挑発キャラ数",
  ko_immune_count: "KO耐性キャラ数",
  cards_drawn_total: "累計ドロー",
  cards_played_total: "累計プレイ",
  dons_used_total: "累計DON使用",
  tempo_lost_total: "テンポ損失合計",
  known_finisher_count_in_hand: "既知フィニッシャー(手札)",
  don_reserve: "DON温存",
  field_exposure: "場の被弾リスク",
  hand_log: "手札枚数(対数)",
  lethal_risk_diff: "リーサルリスク差",
  // 相互作用指標 (interaction)
  int_low_life_low_hand: "低ライフ×低手札",
  int_low_life_no_blocker: "低ライフ×ブロッカー無",
  int_opp_lethal_no_counter: "被リーサル×カウンター無",
  int_defensive_collapse: "守備崩壊",
  int_opp_da_pressure: "相手ダブルアタック圧",
  int_lethal_setup_ready: "リーサル準備完了",
  int_aggressive_window_open: "攻めどき",
  int_burst_threshold: "バースト閾値",
  int_removal_window: "除去好機",
  int_don_advantage_open: "DON優位",
  int_on_curve: "カーブ通り",
  int_tempo_lost_critical: "致命的テンポ損失",
  int_ramp_paying_off: "ランプ奏功",
  int_mana_starved: "マナ不足",
  int_synergy_threshold_3: "シナジー3閾値",
  int_trash_archetype_5: "トラッシュ5閾値",
  int_stage_with_synergy: "ステージ×シナジー",
  int_ramp_finisher_combo: "ランプ×フィニッシャー",
  int_opp_hidden_threat_high: "相手隠匿脅威 高",
  int_self_hand_quality_high: "自手札の質 高",
  int_opp_low_resource: "相手リソース枯渇",
  int_early_game_strong: "序盤の強さ",
  int_mid_game_pressure: "中盤の圧",
  int_late_game_solver: "終盤の解決力",
  int_ko_immune_finisher: "KO耐性フィニッシャー",
  int_blocker_with_taunt: "挑発持ちブロッカー",
};

const fmt = (n: number) =>
  Number.isInteger(n) ? `${n}` : `${Math.round(n * 10) / 10}`;

// ドン付与 pulse: attached_dons が増えた card (= leader/chara) の上に「+DON」 を浮かせる。
// 専用 overlay が _matchAnimHelpers に無い (= ドン付与は tempo action) ため観戦用に自作。
// iids は前フレーム比較で attached_dons が増えた instance_id。 boardRef + data-iid で位置解決。
function DonAttachPulseOverlay({
  iids,
  boardRef,
  tickId,
}: {
  iids: number[];
  boardRef: React.RefObject<HTMLDivElement | null>;
  tickId: number;
}) {
  const [items, setItems] = useState<{ id: number; x: number; y: number }[]>([]);
  const lastTickRef = useRef(-1);
  useEffect(() => {
    if (tickId === lastTickRef.current) return;
    lastTickRef.current = tickId;
    const board = boardRef.current;
    if (!iids.length || !board) {
      return;
    }
    const br = board.getBoundingClientRect();
    const next: { id: number; x: number; y: number }[] = [];
    let n = 0;
    for (const iid of iids) {
      const el = board.querySelector(`[data-iid="${iid}"]`);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      next.push({
        id: tickId * 100 + n++,
        x: r.left - br.left + r.width / 2,
        y: r.top - br.top + 4,
      });
    }
    if (!next.length) return;
    setItems(next);
    const t = setTimeout(() => setItems([]), 1100);
    return () => clearTimeout(t);
  }, [tickId, iids, boardRef]);
  if (!items.length) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-40">
      <AnimatePresence>
        {items.map((it) => (
          <motion.div
            key={it.id}
            initial={{ opacity: 0, y: 0, scale: 0.6 }}
            animate={{ opacity: 1, y: -30, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.9 }}
            className="absolute -translate-x-1/2 rounded-full border border-amber-300 bg-amber-500/90 px-2 py-0.5 text-[11px] font-bold text-white shadow-lg"
            style={{ left: it.x, top: it.y }}
          >
            +DON
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export function SpectateBoard({
  snapshots,
  deckTopName,
  deckBottomName,
  winner,
  onClose,
  replayKey,
  autoPlay,
}: {
  snapshots: StateSnapshot[];
  deckTopName?: string;
  deckBottomName?: string;
  /** winner_idx (= players index)。 表示用。 */
  winner?: number | null;
  /** 全画面を閉じて selector へ戻る。 */
  onClose?: () => void;
  /** コメントを紐づける replay 識別子 (= LogSidebar の sessionId)。 非null でコメント有効。 */
  replayKey?: string;
  /** マウント時に自動再生を開始する (= AI vs AI 観戦で開始後すぐ再生)。 */
  autoPlay?: boolean;
}) {
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 2 | 4>(1);
  const [hovered, setHovered] = useState<HoverInfo>(null);
  const [showData, setShowData] = useState(false); // 初期値は非表示 (= ボタンで表示)
  const [panelPos, setPanelPos] = useState({ x: 360, y: 92 });
  const [dragging, setDragging] = useState(false);
  const dragOffset = useRef({ dx: 0, dy: 0 });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // アニメーション用: 盤面コンテナ ref (= beam/arrow/pulse の data-iid 位置解決基準)。
  const boardRef = useRef<HTMLDivElement>(null);

  const total = snapshots.length;
  const clampedIdx = Math.min(idx, Math.max(0, total - 1));
  const snap = snapshots[clampedIdx];

  useEffect(() => {
    if (!playing) return;
    if (clampedIdx >= total - 1) {
      setPlaying(false);
      return;
    }
    // 基準 1800ms/手 (= 1x)。 攻撃ビーム/矢印 (~1.3s) が収まる速度。 2x=900 / 4x=450。
    timerRef.current = setTimeout(() => setIdx((i) => i + 1), 1800 / speed);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [playing, clampedIdx, total, speed]);

  // マウント時に自動再生 (= 観戦開始後、 初期盤面で止まらず頭から再生する)。
  useEffect(() => {
    if (autoPlay && total > 1) setPlaying(true);
  }, [autoPlay, total]);

  // 盤面データパネルのドラッグ移動 (= window mousemove/up を dragging 中のみ購読)。
  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const x = e.clientX - dragOffset.current.dx;
      const y = e.clientY - dragOffset.current.dy;
      setPanelPos({
        x: Math.max(-360, Math.min(x, window.innerWidth - 80)),
        y: Math.max(0, Math.min(y, window.innerHeight - 40)),
      });
    };
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  // フレーム差分 (= life/don/entered/left/eventTick)。 idx 進行で snap が変わるたび発火。
  const frameDiff = useFrameDiff(snapshots[clampedIdx] ?? null);

  // カウンター検出 (= 両側)。 「P{attacker}: ... counter +N → ...」 を current frame log から拾い、
  // 防御側 (= 1-attacker) の trash 末尾 card で CounterPlayOverlay を発火 (= 人間vsAI の AI counter
  // 検出を両側に一般化)。
  const lastCounterTickRef = useRef(-1);
  useEffect(() => {
    const s = snapshots[clampedIdx];
    if (!s) return;
    const tick = frameDiff.eventTickId;
    if (tick === lastCounterTickRef.current) return;
    lastCounterTickRef.current = tick;
    const lines = (typeof s.log === "string" ? s.log : "").split("\n");
    for (const ln of lines) {
      const m = ln.match(/counter\s*\+(\d+)\s*→/);
      if (!m) continue;
      const pm = ln.match(/\bP([01])\b/);
      if (!pm) continue;
      // attacker = P{pm}、 defender (= counter を切った側) = 1 - attacker
      const defender = (1 - Number(pm[1])) as 0 | 1;
      const trash = s.players?.[defender]?.trash ?? [];
      const cardId = trash[trash.length - 1] ?? "";
      if (!cardId) break;
      fireCounterPlay(cardId, Number(m[1]), defender === 0 ? "me" : "opp");
      break;
    }
  }, [frameDiff.eventTickId, clampedIdx, snapshots]);

  // 攻撃解決の演出 (= 人間vsAI と同じ): 直近攻撃の attacker→target を lastAttackRef に保持し、
  //   防御成功 (= 「P{tpi}: blocked|survived|blocker survived」) → fireDefenseSuccess + fireArrowBreak (矢印へし折り)
  //   攻撃成立 (= 「hit:|KO|life->hand|ライフ受け取り」) → fireArrowStrike (矢印突き刺さり)
  // coords は boardRef + data-iid から解決 (= AttackBeam と同方式)。
  const lastAttackRef = useRef<{ attackerIid: number; targetIid: number } | null>(
    null,
  );
  const lastResolveTickRef = useRef(-1);
  // 攻撃ターゲット矢印を「宣言→解決演出まで」 持続表示するための state (= ohtsuki 2026-06-07:
  // 矢印は解決アニメ表示中に裏で消す方が臨場感が出る → 解決後に遅延クリアで重ねる)。
  const [arrowTarget, setArrowTarget] = useState<
    { attackerIid: number; targetIid: number } | null
  >(null);
  const arrowClearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const s = snapshots[clampedIdx];
    if (!s) return;
    const tick = frameDiff.eventTickId;
    if (tick === lastResolveTickRef.current) return;
    lastResolveTickRef.current = tick;
    // 現フレームが攻撃宣言なら lastAttackRef を更新 (= 解決フレームで coords に使う)
    const ev = s.event;
    if (
      ev &&
      typeof ev.attacker_iid === "number" &&
      typeof ev.target_iid === "number"
    ) {
      lastAttackRef.current = {
        attackerIid: ev.attacker_iid,
        targetIid: ev.target_iid,
      };
      // 攻撃宣言フレーム → 矢印を持続表示開始 (= 解決まで残す)。 保留中の clear はキャンセル。
      setArrowTarget({ attackerIid: ev.attacker_iid, targetIid: ev.target_iid });
      if (arrowClearTimer.current) {
        clearTimeout(arrowClearTimer.current);
        arrowClearTimer.current = null;
      }
    }
    const ln = typeof s.log === "string" ? s.log : "";
    // 解決演出 (break/strike) を fire したら、 矢印は演出に重ねてから裏で消す (= 遅延クリア)。
    const scheduleArrowClear = () => {
      if (arrowClearTimer.current) clearTimeout(arrowClearTimer.current);
      arrowClearTimer.current = setTimeout(() => setArrowTarget(null), 550);
    };
    const coords = () => {
      const board = boardRef.current;
      const last = lastAttackRef.current;
      if (!board || !last) return null;
      const r = board.getBoundingClientRect();
      const at = board.querySelector(`[data-iid="${last.attackerIid}"]`);
      const tg = board.querySelector(`[data-iid="${last.targetIid}"]`);
      if (!at || !tg) return null;
      const ar = at.getBoundingClientRect();
      const tr = tg.getBoundingClientRect();
      return {
        x1: ar.left + ar.width / 2 - r.left,
        y1: ar.top + ar.height / 2 - r.top,
        x2: tr.left + tr.width / 2 - r.left,
        y2: tr.top + tr.height / 2 - r.top,
      };
    };
    // 防御成功 (= カウンター/ブロッカーで凌いだ) → へし折り + バナー
    const sm = ln.match(/\bP(\d+):\s+(blocker\s+survived|blocked|survived)\s*$/m);
    if (sm) {
      const defenderIdx = 1 - Number(sm[1]);
      fireDefenseSuccess(defenderIdx === 0 ? "me" : "opp", sm[2] === "blocker survived");
      const c = coords();
      if (c) fireArrowBreak(c);
      // へし折り演出は自前で矢印を割って描くので、 持続(intact)矢印は即時消す
      // (= 折れる矢印と無傷の矢印が二重に重なるのを防ぐ、 ohtsuki 2026-06-16)。
      if (arrowClearTimer.current) {
        clearTimeout(arrowClearTimer.current);
        arrowClearTimer.current = null;
      }
      setArrowTarget(null);
      return;
    }
    // 攻撃成立 (= 防御失敗、 ライフ/KO) → 突き刺さり
    if (/\bhit:|^\s*KO\s|^\s*KO:\s|life->hand|ライフ受け取り/m.test(ln)) {
      const c = coords();
      if (c) fireArrowStrike(c);
      scheduleArrowClear();
    }
  }, [frameDiff.eventTickId, clampedIdx, snapshots]);

  if (!snap) {
    return (
      <div className="p-6 text-sm text-zinc-400">観戦データがありません。</div>
    );
  }

  // perspective: players[1] = 上 (相手枠)、 players[0] = 下 (自分枠)。 観戦なので両方 reveal。
  const top = snap.players[1];
  const bottom = snap.players[0];
  // 各ログ行に「どの snapshot(frame) の行か」を付与 (= クリックでその盤面へ移動)。
  const logEntries = snapshots
    .slice(0, clampedIdx + 1)
    .flatMap((s, si) =>
      ((s.log as unknown as string) || "")
        .split("\n")
        .filter((l) => l && l.trim().length > 0)
        .map((text) => ({ text, frame: si })),
    );
  const log = logEntries.map((e) => e.text);
  const lineFrames = logEntries.map((e) => e.frame);
  const atEnd = clampedIdx >= total - 1;
  const onHover = (h: HoverInfo) => setHovered(h);
  const fieldPower = (p: typeof top) =>
    p.characters.reduce((s, c) => s + (c.power || 0), 0);

  // ドン付与検出: 前フレームより attached_dons が増えた card (= leader + chara、 両 player) の iid。
  const prevSnap = clampedIdx > 0 ? snapshots[clampedIdx - 1] : null;
  const donAttachedIids: number[] = [];
  if (prevSnap) {
    for (let pi = 0; pi < 2; pi++) {
      const pp = prevSnap.players[pi];
      const cp = snap.players[pi];
      if (!pp || !cp) continue;
      const prevDon = new Map<number, number>();
      prevDon.set(pp.leader.instance_id, pp.leader.attached_dons ?? 0);
      for (const c of pp.characters)
        prevDon.set(c.instance_id, c.attached_dons ?? 0);
      const check = (iid: number, dons: number) => {
        const pv = prevDon.get(iid);
        if (pv !== undefined && dons > pv) donAttachedIids.push(iid);
      };
      check(cp.leader.instance_id, cp.leader.attached_dons ?? 0);
      for (const c of cp.characters) check(c.instance_id, c.attached_dons ?? 0);
    }
  }

  // カウンター frame は CounterPlayOverlay がカード演出を出すので、 その frame の防御側
  // trashAdded を同期的に空にして PlayedCardOverlay との二重演出を防ぐ (= human-play と同手法。
  // useState exclude では PlayedCardOverlay の useEffect に間に合わない)。
  const counterDefenderIdx: 0 | 1 | -1 = (() => {
    const ln = typeof snap.log === "string" ? snap.log : "";
    const m = ln.match(/\bP(\d+):\s+counter\s*\+/);
    return m ? ((1 - Number(m[1])) as 0 | 1) : -1;
  })();
  const trashAddedBottom =
    counterDefenderIdx === 0 ? [] : frameDiff.trashAdded[0];
  const trashAddedTop =
    counterDefenderIdx === 1 ? [] : frameDiff.trashAdded[1];

  // 盤面データ内訳 (= P0 / 手前 視点固定)。 全件表示。 寄与 (contribution) の大きい順、
  // 同寄与は差の大きい順に並べる (= 判断を駆動する指標を上に、 重み0の参考値を下に)。
  const detail = snap.board_eval_detail ?? null;
  const detailRows = detail
    ? Object.entries(detail)
        .map(([k, v]) => ({ key: k, ...v }))
        .sort(
          (a, b) =>
            Math.abs(b.contribution) - Math.abs(a.contribution) ||
            Math.abs(b.diff) - Math.abs(a.diff),
        )
    : [];
  const p0Eval = detail
    ? Object.values(detail).reduce((s, m) => s + m.contribution, 0)
    : null;

  const startDrag = (e: React.MouseEvent) => {
    dragOffset.current = { dx: e.clientX - panelPos.x, dy: e.clientY - panelPos.y };
    setDragging(true);
  };

  const ctrlBtn =
    "rounded px-2 py-1 text-xs font-bold text-amber-200 hover:bg-amber-900/60";

  return (
    <div
      className="fixed inset-0 z-50 flex h-[100dvh] w-full gap-2 overflow-hidden p-2"
      style={{
        backgroundImage:
          "radial-gradient(ellipse at center, #6b4423 0%, #3d2817 100%)",
      }}
    >
      {/* 左 (= 人間vsAI と同じ min-w-280 flex-1): 相手info + log(コメント可) + 自分stat + 自手札 */}
      <div className="flex min-w-[280px] flex-1 min-h-0 flex-col gap-2">
        <OpponentInfoPanel opp={top} reveal onHover={onHover} />
        <LogSidebar
          log={log}
          aiIdx={1}
          sessionId={replayKey ?? null}
          lineFrames={lineFrames}
          onJump={(f) => {
            // 再生状態は維持 (= 再生中ならその盤面から続けて再生)。
            setIdx(f);
          }}
        />
        <div className="shrink-0 rounded border border-emerald-400/50 bg-emerald-950/40 p-2">
          <StatBadge
            player={bottom}
            label={deckBottomName ?? "P0"}
            color="bg-emerald-700 text-white"
          />
          <div className="mt-2">
            <HandRow
              hand={bottom.hand}
              actionsByHand={EMPTY_ACTIONS}
              canAct={false}
              selectedIdx={null}
              draggingHandIdx={null}
              onClick={NOOP}
              onHover={onHover}
              onDragStart={NOOP}
              onDragEnd={NOOP}
            />
          </div>
        </div>
      </div>

      {/* 中央 (= 人間vsAI と同じ w-780): 相手/自分マット + アニメーション overlay */}
      <div
        ref={boardRef}
        data-board-area="center"
        className="relative flex min-h-0 w-[780px] shrink-0 flex-col gap-2"
      >
        <PlayerMat
          player={top}
          isMe={false}
          attackerIid={null}
          canSelectAsTarget={false}
          onLeaderClick={NOOP}
          onCharaClick={NOOP}
          onSelfLeaderClick={NOOP}
          onSelfCharaClick={NOOP}
          actionsByIid={EMPTY_ACTIONS}
          canAct={false}
          drag={null}
          onDropTarget={NOOP}
          onHover={onHover}
          onTrashClick={NOOP}
        />
        <div className="h-px shrink-0 bg-amber-100/30" />
        <PlayerMat
          player={bottom}
          isMe={true}
          attackerIid={null}
          canSelectAsTarget={false}
          onLeaderClick={NOOP}
          onCharaClick={NOOP}
          onSelfLeaderClick={NOOP}
          onSelfCharaClick={NOOP}
          actionsByIid={EMPTY_ACTIONS}
          canAct={false}
          drag={null}
          onDropTarget={NOOP}
          onHover={onHover}
          onTrashClick={NOOP}
        />

        {/* === アニメーション overlay (= 人間vsAI と同じ部品、 snap/frameDiff 駆動) === */}
        {/* ライフ変化 flash (上=相手=players[1] / 下=自分=players[0]) */}
        <LifeFlashOverlay
          delta={frameDiff.lifeDelta[1]}
          side="opp"
          tickId={frameDiff.eventTickId * 2}
        />
        <LifeFlashOverlay
          delta={frameDiff.lifeDelta[0]}
          side="me"
          tickId={frameDiff.eventTickId * 2 + 1}
        />
        {/* 場を離れた chara の ghost (KO/退場) */}
        <LeftCharaGhostList
          leftCharas={frameDiff.leftCharas[1]}
          side="opp"
          tickId={frameDiff.eventTickId * 2}
        />
        <LeftCharaGhostList
          leftCharas={frameDiff.leftCharas[0]}
          side="me"
          tickId={frameDiff.eventTickId * 2 + 1}
        />
        {/* 攻撃ビーム + 矢印 (= snap.event 駆動、 AI/AI 共通) */}
        <AttackBeamOverlay
          attackerIid={snap.event?.attacker_iid ?? null}
          targetIid={snap.event?.target_iid ?? null}
          boardRef={boardRef}
          tickId={frameDiff.eventTickId}
        />
        {/* 攻撃ターゲット矢印 = 宣言で表示し、 解決演出 (へし折り/突き刺さり) の後に裏で消す
            (= persistent + 遅延クリア)。 アニメ前のハードカットを避けて重ねる (ohtsuki 2026-06-07)。 */}
        <AttackTargetArrowOverlay
          attackerIid={arrowTarget?.attackerIid ?? null}
          targetIid={arrowTarget?.targetIid ?? null}
          boardRef={boardRef}
          tickId={frameDiff.eventTickId}
          persistent
        />
        {/* 対戦終了時の勝者表示 (= 盤面中央に大きく明示、 ohtsuki 2026-06-16)。
            ヘッダの小バッジに加え、 終了が一目で分かる overlay。 */}
        <AnimatePresence>
          {atEnd && winner != null && winner >= 0 && (
            <motion.div
              key="winner-banner"
              className="pointer-events-none absolute inset-0 z-[70] flex items-center justify-center"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              <motion.div
                className="rounded-2xl border-2 border-amber-300 bg-black/80 px-12 py-7 text-center shadow-2xl ring-4 ring-amber-400/40 backdrop-blur-sm"
                initial={{ scale: 0.85, y: 8 }}
                animate={{ scale: 1, y: 0 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
              >
                <div className="text-xs font-bold tracking-[0.35em] text-amber-200">
                  WINNER
                </div>
                <div className="mt-2 text-3xl font-extrabold text-white">
                  {winner === 0 ? deckBottomName ?? "P0" : deckTopName ?? "P1"}
                </div>
                <div className="mt-1 text-xs text-amber-100/70">P{winner} の勝利</div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
        {/* ドン付与 pulse (= attached_dons 増加 card に「+DON」) */}
        <DonAttachPulseOverlay
          iids={donAttachedIids}
          boardRef={boardRef}
          tickId={frameDiff.eventTickId}
        />
        {/* 効果トースト (= 「効果:」 ログ行を分類表示: 登場/サーチ/KO/ドン+/パワー等) */}
        <EffectToastOverlay log={log} />
        {/* カードプレイ → trash slide (= イベント使用/KO)。 counter card は除外 */}
        <PlayedCardOverlay
          trashAddedMe={trashAddedBottom}
          trashAddedOpp={trashAddedTop}
          leftCharasMe={frameDiff.leftCharas[0]}
          leftCharasOpp={frameDiff.leftCharas[1]}
          excludeMeCardIds={[]}
          excludeOppCardIds={[]}
          tickId={frameDiff.eventTickId}
        />
        {/* ドロー演出 (= デッキ → 手札 slide) */}
        <DrawCardOverlay
          handDeltaMe={frameDiff.handDelta[0]}
          handDeltaOpp={frameDiff.handDelta[1]}
          lifeDeltaMe={frameDiff.lifeDelta[0]}
          lifeDeltaOpp={frameDiff.lifeDelta[1]}
          tickId={frameDiff.eventTickId}
          boardRef={boardRef}
        />
        {/* カウンター 「+N」 popup + trash slide (= 上の useEffect が fireCounterPlay) */}
        <CounterPlayOverlay />
        {/* 防御成功で矢印へし折り / 攻撃成立で矢印突き刺さり / 防御成功バナー (= 上の useEffect が fire) */}
        <ArrowBreakOverlay />
        <ArrowStrikeOverlay />
        <DefenseSuccessOverlay />
      </div>

      {/* 右 (= 人間vsAI と同じ w-480): [ヘッダ] → [PREVIEW 大] → [ACTION位置 = コントロール + 盤面データ] */}
      <div className="flex w-[480px] shrink-0 flex-col gap-2">
        {/* ヘッダ: turn / phase / 勝者 / 閉じる */}
        <div className="flex shrink-0 items-center gap-2 rounded bg-black/50 px-2 py-1.5 text-xs text-zinc-100">
          <span className="font-semibold">
            T{snap.turn} {snap.phase}
          </span>
          <span className="rounded bg-rose-500 px-2 py-0.5 text-xs font-bold text-white">
            観戦
          </span>
          {atEnd && winner != null && winner >= 0 && (
            <span className="rounded bg-amber-500 px-2 py-0.5 text-xs font-bold text-white">
              勝者 {winner === 0 ? deckBottomName ?? "P0" : deckTopName ?? "P1"}
            </span>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="ml-auto rounded border border-rose-400 bg-rose-700/80 px-2 py-0.5 text-xs font-bold text-white hover:bg-rose-600"
            >
              閉じる
            </button>
          )}
        </div>

        {/* PREVIEW (= 人間vsAI と同じ flex-1 大表示) */}
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden rounded bg-black/40 p-2">
          <div className="shrink-0 text-xs font-bold text-zinc-200">PREVIEW</div>
          {hovered ? (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-1">
              <CardImage
                cardId={hovered.cardId}
                alt={hovered.cardId}
                className="max-h-full max-w-full rounded object-contain shadow-2xl"
              />
              {hovered.kind === "chara" && (
                <div className="shrink-0 text-center text-xs text-zinc-200">
                  <span className="font-bold">{hovered.name}</span>{" "}
                  <span>
                    P {hovered.power}
                    {hovered.attached_dons > 0
                      ? ` (DON+${hovered.attached_dons})`
                      : ""}
                    {hovered.rested ? " / レスト" : ""}
                  </span>
                  {hovered.keywords.length > 0 && (
                    <span className="ml-1 text-amber-200">
                      {hovered.keywords.join(" ")}
                    </span>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center text-xs text-zinc-400">
              カードに hover で 拡大表示
            </div>
          )}
        </div>

        {/* ACTION 位置 (= 人間vsAI のアクション枠): 観戦コントロール + 盤面データ */}
        <div className="shrink-0 rounded border border-amber-400/40 bg-zinc-900/85 p-2">
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx(0);
              }}
              className={ctrlBtn}
            >
              最初
            </button>
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx((i) => Math.max(0, i - 1));
              }}
              className={ctrlBtn}
            >
              前
            </button>
            <button
              type="button"
              onClick={() => {
                if (atEnd) {
                  setIdx(0);
                  setPlaying(true);
                } else setPlaying((p) => !p);
              }}
              className="rounded bg-amber-500 px-3 py-1 text-xs font-bold text-white hover:bg-amber-400"
            >
              {playing ? "停止" : atEnd ? "再生(最初から)" : "再生"}
            </button>
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx((i) => Math.min(total - 1, i + 1));
              }}
              className={ctrlBtn}
            >
              次
            </button>
            <span className="ml-1 text-xs text-amber-200/80">速度</span>
            {([1, 2, 4] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                className={
                  "rounded px-1.5 py-0.5 text-xs font-bold transition " +
                  (speed === s
                    ? "bg-amber-500 text-white"
                    : "text-amber-200 hover:bg-amber-900/60")
                }
              >
                {s}x
              </button>
            ))}
            <span className="ml-auto text-xs text-zinc-300">
              {clampedIdx + 1}/{total}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(0, total - 1)}
            value={clampedIdx}
            onChange={(e) => {
              setPlaying(false);
              setIdx(parseInt(e.target.value, 10));
            }}
            className="mt-1 w-full accent-amber-500"
          />
          {/* 盤面データ (= クイック表示。 手前 = P0 を左列。 詳細は下のボタンでモーダル) */}
          <div className="mt-2 grid grid-cols-[auto_1fr_1fr] gap-x-2 gap-y-0.5 text-xs text-zinc-200">
            <span className="font-bold text-amber-200">盤面</span>
            <span className="font-semibold text-emerald-300">
              {deckBottomName ?? "P0"}
            </span>
            <span className="font-semibold text-rose-300">
              {deckTopName ?? "P1"}
            </span>
            <span className="text-zinc-500">ライフ</span>
            <span>{bottom.life_count}</span>
            <span>{top.life_count}</span>
            <span className="text-zinc-500">手札</span>
            <span>{bottom.hand_count}</span>
            <span>{top.hand_count}</span>
            <span className="text-zinc-500">DON</span>
            <span>
              {bottom.don_active}/{bottom.don_total}
            </span>
            <span>
              {top.don_active}/{top.don_total}
            </span>
            <span className="text-zinc-500">場/power</span>
            <span>
              {bottom.characters.length} / {fieldPower(bottom)}
            </span>
            <span>
              {top.characters.length} / {fieldPower(top)}
            </span>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2">
            {p0Eval !== null ? (
              <span className="text-xs text-zinc-300">
                eval(手前視点):{" "}
                <span
                  className={
                    "font-bold " +
                    (p0Eval >= 0 ? "text-emerald-300" : "text-rose-300")
                  }
                >
                  {p0Eval > 0 ? "+" : ""}
                  {p0Eval}
                </span>
              </span>
            ) : (
              <span />
            )}
            {detailRows.length > 0 && (
              <button
                type="button"
                onClick={() => setShowData((v) => !v)}
                className="rounded border border-amber-400/60 bg-amber-900/40 px-2 py-0.5 text-xs font-bold text-amber-100 hover:bg-amber-800/60"
              >
                {showData ? "盤面データを隠す" : "盤面データを表示"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 盤面データパネル (= ドラッグ移動可・暗転なし・全件表示。 AI が手を判断する全指標、 手前 P0 視点) */}
      {showData && detail && (
        <div
          className="fixed z-[60] flex max-h-[82vh] w-[460px] flex-col overflow-hidden rounded-lg border border-amber-400/60 bg-zinc-900/95 shadow-2xl"
          style={{ left: panelPos.x, top: panelPos.y }}
        >
          {/* ドラッグハンドル (= ヘッダを掴んで移動) */}
          <div
            onMouseDown={startDrag}
            className={
              "flex shrink-0 select-none items-center justify-between gap-2 border-b border-zinc-700 bg-zinc-800/90 px-3 py-2 " +
              (dragging ? "cursor-grabbing" : "cursor-grab")
            }
          >
            <span className="text-sm font-bold text-amber-200">
              盤面データ (手前 = {deckBottomName ?? "P0"} 視点)
            </span>
            <button
              type="button"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => setShowData(false)}
              className="rounded border border-zinc-500 px-2 py-0.5 text-xs font-bold text-zinc-200 hover:bg-zinc-700"
            >
              閉じる
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <p className="mb-2 text-xs text-zinc-400">
              AI が手を判断するときに使う盤面指標 (= engine/eval.py compute_breakdown)。
              寄与 = 差 × 重み、 正 = 手前有利。 寄与の大きい順。 寄与0 (淡色) = 重み0で判断に未使用の参考値。
            </p>
            <div className="mb-2 rounded bg-black/40 px-2 py-1 text-xs text-zinc-200">
              T{snap.turn} {snap.phase}・線形eval(手前):{" "}
              <span
                className={
                  "font-bold " +
                  ((p0Eval ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300")
                }
              >
                {(p0Eval ?? 0) > 0 ? "+" : ""}
                {p0Eval}
              </span>
            </div>
            <table className="w-full text-xs text-zinc-200">
              <thead>
                <tr className="border-b border-zinc-700 text-zinc-400">
                  <th className="py-1 text-left">指標</th>
                  <th className="py-1 text-right">手前</th>
                  <th className="py-1 text-right">相手</th>
                  <th className="py-1 text-right">差</th>
                  <th className="py-1 text-right">寄与</th>
                </tr>
              </thead>
              <tbody>
                {detailRows.map((r) => (
                  <tr
                    key={r.key}
                    className={
                      "border-b border-zinc-800/60 " +
                      (r.contribution === 0 ? "opacity-50" : "")
                    }
                  >
                    <td className="py-1">{METRIC_LABELS[r.key] ?? r.key}</td>
                    <td className="py-1 text-right">{fmt(r.self)}</td>
                    <td className="py-1 text-right">{fmt(r.opp)}</td>
                    <td className="py-1 text-right">{fmt(r.diff)}</td>
                    <td
                      className={
                        "py-1 text-right font-semibold " +
                        (r.contribution > 0
                          ? "text-emerald-300"
                          : r.contribution < 0
                            ? "text-rose-300"
                            : "text-zinc-500")
                      }
                    >
                      {r.contribution > 0 ? "+" : ""}
                      {fmt(r.contribution)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
