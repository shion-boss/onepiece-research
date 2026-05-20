"use client";

import { useEffect, useRef, useState } from "react";
import { CardImage } from "./CardImage";
import {
  applyHumanAction,
  applyHumanDefense,
  endHumanMatch,
  startHumanMatch,
  type HumanLegalAction,
  type HumanMatchState,
} from "@/lib/api";
import type { CharSnapshot, PlayerSnapshot, StateSnapshot } from "@/lib/types";

/**
 * 人間 vs AI 対戦 component (= OPTCGSim 風 UI)。
 *
 * Layout:
 *  ┌────────────────────────────────────────────────┐
 *  │ ┌─ log ─┐  ┌── 相手 マット (上向き) ─────────┐ │
 *  │ │       │  │ ライフ縦  キャラ5  デッキ     │ │
 *  │ │       │  │           リーダー ステージ TRH │ │
 *  │ │       │  │  DON横                          │ │
 *  │ │       │  ╞══════════════════════════════════╡
 *  │ │       │  │  DON横                          │ │
 *  │ │       │  │  リーダー ステージ TRH          │ │
 *  │ │       │  │ ライフ縦  キャラ5  デッキ     │ │
 *  │ └───────┘  └──────────────────────────────────┘ │
 *  │           ┌── 手札 横並び ──────────────────┐  │
 *  │           │  🃏 🃏 🃏 🃏 🃏 🃏 🃏          │  │
 *  │           └──────────────────────────────────┘  │
 *  │                              [Deploy] [Cancel] │
 *  └────────────────────────────────────────────────┘
 */

type DeckOption = { slug: string; name: string };

type Selection =
  | null
  | { kind: "hand"; handIdx: number }
  | { kind: "self_chara"; iid: number }
  | { kind: "self_leader" }
  | { kind: "attack_pending"; attackerIid: number };

export function HumanMatchPlay({ decks }: { decks: DeckOption[] }) {
  const [deckA, setDeckA] = useState<string>(decks[0]?.slug ?? "");
  const [deckB, setDeckB] = useState<string>(decks[0]?.slug ?? "");
  const [seed, setSeed] = useState<number>(42);
  const [humanFirst, setHumanFirst] = useState<"random" | "first" | "second">(
    "random",
  );
  const [state, setState] = useState<HumanMatchState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<Selection>(null);
  // 攻撃中: target 候補 を 表示 + マウス 位置 追従 矢印
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);
  // 防御 panel state
  const [counterIdxs, setCounterIdxs] = useState<number[]>([]);
  const [blockerIid, setBlockerIid] = useState<number | null>(null);

  const sessionId = state?.session_id;
  const boardRef = useRef<HTMLDivElement | null>(null);

  async function handleStart() {
    setError(null);
    setBusy(true);
    setSelection(null);
    setCounterIdxs([]);
    setBlockerIid(null);
    try {
      const hf = humanFirst === "random" ? null : humanFirst === "first";
      const next = await startHumanMatch(deckA, deckB, {
        seed,
        human_first: hf,
      });
      setState(next);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function applyAction(action: HumanLegalAction) {
    if (!sessionId) return;
    setError(null);
    setBusy(true);
    setSelection(null);
    try {
      const next = await applyHumanAction(sessionId, action.idx);
      setState(next);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleDefenseSubmit() {
    if (!sessionId) return;
    setError(null);
    setBusy(true);
    try {
      const next = await applyHumanDefense(sessionId, blockerIid, counterIdxs);
      setState(next);
      setCounterIdxs([]);
      setBlockerIid(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleEnd() {
    if (!sessionId) return;
    await endHumanMatch(sessionId);
    setState(null);
  }

  useEffect(() => {
    return () => {
      if (sessionId) {
        endHumanMatch(sessionId).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  if (!state) {
    return (
      <StartPanel
        decks={decks}
        deckA={deckA}
        deckB={deckB}
        seed={seed}
        humanFirst={humanFirst}
        setDeckA={setDeckA}
        setDeckB={setDeckB}
        setSeed={setSeed}
        setHumanFirst={setHumanFirst}
        onStart={handleStart}
        busy={busy}
        error={error}
      />
    );
  }

  const snap = state.snapshot as StateSnapshot | null;
  if (!snap) {
    return (
      <div className="rounded border border-zinc-300 p-4 text-sm">
        snapshot 取得失敗
      </div>
    );
  }

  const isHumanTurn = state.turn_player_idx === state.human_idx;
  const isDefensePending = state.pending_kind === "defense";
  const isActionPending = state.pending_kind === "action";
  const me = snap.players[state.human_idx];
  const opp = snap.players[state.ai_idx];
  const canAct = isHumanTurn && isActionPending && !busy;

  // legal actions index
  const actionsByHand = new Map<number, HumanLegalAction[]>();
  const actionsByIid = new Map<number, HumanLegalAction[]>();
  let endPhaseAction: HumanLegalAction | undefined;
  for (const a of state.legal_actions) {
    if (a.hand_idx !== undefined) {
      const arr = actionsByHand.get(a.hand_idx) ?? [];
      arr.push(a);
      actionsByHand.set(a.hand_idx, arr);
    }
    if (a.iid !== undefined) {
      const arr = actionsByIid.get(a.iid) ?? [];
      arr.push(a);
      actionsByIid.set(a.iid, arr);
    }
    if (a.attacker_iid !== undefined) {
      const arr = actionsByIid.get(a.attacker_iid) ?? [];
      arr.push(a);
      actionsByIid.set(a.attacker_iid, arr);
    }
    if (a.kind === "EndPhase") endPhaseAction = a;
  }

  // === click handlers === //
  function clickHandCard(handIdx: number) {
    if (!canAct) return;
    const actions = actionsByHand.get(handIdx) ?? [];
    if (actions.length === 0) return;
    setSelection({ kind: "hand", handIdx });
  }

  function clickSelfLeader() {
    if (!canAct) return;
    const leaderIid = me.leader.instance_id;
    const actions = actionsByIid.get(leaderIid) ?? [];
    if (actions.length === 0) return;
    setSelection({ kind: "self_leader" });
  }

  function clickSelfChara(iid: number) {
    if (!canAct) return;
    const actions = actionsByIid.get(iid) ?? [];
    if (actions.length === 0) return;
    setSelection({ kind: "self_chara", iid });
  }

  function clickOppLeader() {
    if (!canAct) return;
    if (selection?.kind !== "attack_pending") return;
    const action = state!.legal_actions.find(
      (a) =>
        a.kind === "AttackLeader" && a.attacker_iid === selection.attackerIid,
    );
    if (action) applyAction(action);
  }

  function clickOppChara(iid: number) {
    if (!canAct) return;
    if (selection?.kind !== "attack_pending") return;
    const action = state!.legal_actions.find(
      (a) =>
        a.kind === "AttackCharacter" &&
        a.attacker_iid === selection.attackerIid &&
        a.target_iid === iid,
    );
    if (action) applyAction(action);
  }

  // 右下 confirm ボタン の primary action を 決定
  function primaryActionForSelection(): HumanLegalAction | undefined {
    if (!selection) return undefined;
    if (selection.kind === "hand") {
      return (actionsByHand.get(selection.handIdx) ?? [])[0];
    }
    if (selection.kind === "self_leader") {
      // AttachDonToLeader 優先
      return (actionsByIid.get(me.leader.instance_id) ?? [])[0];
    }
    if (selection.kind === "self_chara") {
      const acts = actionsByIid.get(selection.iid) ?? [];
      // attack あれば まず attacker mode に
      const attack = acts.find(
        (a) => a.kind === "AttackLeader" || a.kind === "AttackCharacter",
      );
      if (attack) return attack;
      return acts[0];
    }
    return undefined;
  }

  function confirmSelection() {
    if (!selection) return;
    const primary = primaryActionForSelection();
    if (!primary) return;
    // 攻撃系: attacker mode 切替
    if (
      (primary.kind === "AttackLeader" || primary.kind === "AttackCharacter") &&
      primary.attacker_iid !== undefined
    ) {
      setSelection({ kind: "attack_pending", attackerIid: primary.attacker_iid });
      return;
    }
    applyAction(primary);
  }

  function cancelSelection() {
    setSelection(null);
  }

  // 右下 ボタン の ラベル
  function primaryButtonLabel(): string {
    if (selection?.kind === "attack_pending") return "対象を選択";
    const primary = primaryActionForSelection();
    if (!primary) return "";
    switch (primary.kind) {
      case "PlayCharacter":
        return "Deploy";
      case "PlayEvent":
        return "Use Event";
      case "PlayStage":
        return "Place Stage";
      case "AttachDonToLeader":
        return "Attach DON → Leader";
      case "AttachDonToCharacter":
        return "Attach DON → Character";
      case "AttackLeader":
      case "AttackCharacter":
        return "⚔ Attack";
      case "ActivateMain":
        return "Activate Main";
      default:
        return primary.label || primary.kind;
    }
  }

  // attacker iid の field 位置 (= attack 矢印 の 起点)
  const attackerIid =
    selection?.kind === "attack_pending" ? selection.attackerIid : null;

  return (
    <div
      ref={boardRef}
      onMouseMove={(e) => {
        if (attackerIid !== null && boardRef.current) {
          const r = boardRef.current.getBoundingClientRect();
          setMousePos({ x: e.clientX - r.left, y: e.clientY - r.top });
        }
      }}
      className="relative flex h-[calc(100vh-7rem)] flex-col gap-2 overflow-hidden rounded-xl border border-amber-900/40 p-3"
      style={{
        backgroundImage:
          "radial-gradient(ellipse at center, #6b4423 0%, #3d2817 100%)",
      }}
    >
      {/* ヘッダ */}
      <div className="flex shrink-0 items-center gap-2 rounded bg-black/40 px-3 py-1.5 text-xs text-zinc-100 backdrop-blur">
        <span className="font-semibold">
          Turn {state.turn} ({state.phase})
        </span>
        <span
          className={
            isHumanTurn
              ? "rounded bg-emerald-500 px-2 py-0.5 text-xs font-bold text-white"
              : "rounded bg-rose-500 px-2 py-0.5 text-xs font-bold text-white"
          }
        >
          {isHumanTurn ? "YOUR TURN" : "AI TURN"}
        </span>
        {state.game_over && (
          <span className="rounded bg-amber-500 px-2 py-0.5 text-xs font-bold text-white">
            GAME OVER:{" "}
            {state.winner === state.human_idx
              ? "🎉 WIN"
              : state.winner === state.ai_idx
                ? "LOSE"
                : "DRAW"}
          </span>
        )}
        <span className="ml-auto text-zinc-300">
          sid={sessionId?.slice(0, 8)}
        </span>
        <button
          type="button"
          onClick={handleEnd}
          className="rounded border border-zinc-500 px-2 py-0.5 text-xs hover:bg-zinc-700"
        >
          End
        </button>
      </div>

      {error && (
        <div className="shrink-0 rounded border border-red-500 bg-red-950/80 p-2 text-sm text-red-100">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 gap-3">
        {/* 左 サイド: log */}
        <LogSidebar log={state.log} />

        {/* 中央: マット (上下対峙) + 手札 */}
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          {/* 相手 マット (= 上、 反転表示) */}
          <PlayerMat
            player={opp}
            isMe={false}
            attackerIid={attackerIid}
            canSelectAsTarget={attackerIid !== null}
            onLeaderClick={clickOppLeader}
            onCharaClick={clickOppChara}
            onSelfCharaClick={() => {}}
            onSelfLeaderClick={() => {}}
            actionsByIid={actionsByIid}
            canAct={false}
          />

          {/* 仕切り */}
          <div className="shrink-0 h-px bg-amber-100/30" />

          {/* 自分 マット (= 下) */}
          <PlayerMat
            player={me}
            isMe={true}
            attackerIid={attackerIid}
            canSelectAsTarget={false}
            onLeaderClick={() => {}}
            onCharaClick={() => {}}
            onSelfCharaClick={clickSelfChara}
            onSelfLeaderClick={clickSelfLeader}
            actionsByIid={actionsByIid}
            canAct={canAct}
            selection={selection}
          />

          {/* 手札 */}
          <HandRow
            hand={me.hand}
            actionsByHand={actionsByHand}
            canAct={canAct}
            selectedIdx={selection?.kind === "hand" ? selection.handIdx : null}
            onClick={clickHandCard}
          />
        </div>

        {/* 右 サイド: 確定ボタン + フェーズ */}
        <RightActionPanel
          canAct={canAct}
          selection={selection}
          primaryLabel={primaryButtonLabel()}
          onConfirm={confirmSelection}
          onCancel={cancelSelection}
          endPhaseAction={endPhaseAction}
          onEndPhase={() => endPhaseAction && applyAction(endPhaseAction)}
          isHumanTurn={isHumanTurn}
          isDefensePending={isDefensePending}
          gameOver={state.game_over}
        />
      </div>

      {/* 防御 panel overlay */}
      {isDefensePending && (
        <DefenseOverlay
          payload={state.pending_payload}
          me={me}
          blockerIid={blockerIid}
          setBlockerIid={setBlockerIid}
          counterIdxs={counterIdxs}
          setCounterIdxs={setCounterIdxs}
          onSubmit={handleDefenseSubmit}
          busy={busy}
        />
      )}

      {/* 攻撃 矢印 SVG (= attacker → マウス) */}
      {attackerIid !== null && mousePos && (
        <AttackArrow attackerIid={attackerIid} mousePos={mousePos} />
      )}
    </div>
  );
}

// ========================================================================== //
// 開始 panel
// ========================================================================== //

function StartPanel({
  decks,
  deckA,
  deckB,
  seed,
  humanFirst,
  setDeckA,
  setDeckB,
  setSeed,
  setHumanFirst,
  onStart,
  busy,
  error,
}: {
  decks: DeckOption[];
  deckA: string;
  deckB: string;
  seed: number;
  humanFirst: "random" | "first" | "second";
  setDeckA: (v: string) => void;
  setDeckB: (v: string) => void;
  setSeed: (v: number) => void;
  setHumanFirst: (v: "random" | "first" | "second") => void;
  onStart: () => void;
  busy: boolean;
  error: string | null;
}) {
  return (
    <div className="flex flex-col gap-3 rounded border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-lg font-semibold">対戦設定</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_120px_140px_auto]">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-zinc-500">自分のデッキ</span>
          <select
            value={deckA}
            onChange={(e) => setDeckA(e.target.value)}
            className="rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            disabled={busy}
          >
            {decks.map((d) => (
              <option key={d.slug} value={d.slug}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-zinc-500">AI のデッキ</span>
          <select
            value={deckB}
            onChange={(e) => setDeckB(e.target.value)}
            className="rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            disabled={busy}
          >
            {decks.map((d) => (
              <option key={d.slug} value={d.slug}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-zinc-500">seed</span>
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(parseInt(e.target.value || "0", 10))}
            className="rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            disabled={busy}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-zinc-500">先攻</span>
          <select
            value={humanFirst}
            onChange={(e) =>
              setHumanFirst(e.target.value as "random" | "first" | "second")
            }
            className="rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            disabled={busy}
          >
            <option value="random">ランダム</option>
            <option value="first">自分が先攻</option>
            <option value="second">AI が先攻</option>
          </select>
        </label>
        <button
          type="button"
          onClick={onStart}
          disabled={busy || !deckA || !deckB}
          className="self-end rounded bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {busy ? "開始中..." : "▶ 対戦開始"}
        </button>
      </div>
      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      )}
    </div>
  );
}

// ========================================================================== //
// PlayerMat (= 公式 マット 配置)
// ========================================================================== //

function PlayerMat({
  player,
  isMe,
  attackerIid,
  canSelectAsTarget,
  onLeaderClick,
  onCharaClick,
  onSelfLeaderClick,
  onSelfCharaClick,
  actionsByIid,
  canAct,
  selection,
}: {
  player: PlayerSnapshot;
  isMe: boolean;
  attackerIid: number | null;
  canSelectAsTarget: boolean;
  onLeaderClick: () => void;
  onCharaClick: (iid: number) => void;
  onSelfLeaderClick: () => void;
  onSelfCharaClick: (iid: number) => void;
  actionsByIid: Map<number, HumanLegalAction[]>;
  canAct: boolean;
  selection?: Selection;
}) {
  return (
    <div
      className={
        "relative flex min-h-0 flex-1 rounded-lg border-2 p-2 " +
        (isMe
          ? "border-emerald-400/60 bg-emerald-950/40"
          : "border-rose-400/60 bg-rose-950/40")
      }
    >
      {/* 左端: ライフ 縦 + DON デッキ */}
      <div className="flex shrink-0 flex-col items-center justify-between gap-1 pr-2">
        <div className="text-[10px] font-bold text-zinc-200">
          LIFE × {player.life_count}
        </div>
        <LifeStack count={player.life_count} />
        <div className="flex flex-col items-center gap-0.5">
          <div className="text-[10px] text-zinc-300">DON Deck</div>
          <div className="relative">
            <img src="/assets/don.png" alt="DON" className="h-10 w-7 rounded shadow" />
            <span className="absolute -bottom-1 -right-1 rounded bg-amber-600 px-1 text-[8px] font-bold text-white">
              {player.don_remaining_in_deck}
            </span>
          </div>
        </div>
      </div>

      {/* 中央: フィールド (= キャラ 5 + リーダー / ステージ / デッキ + DON コスト)
        公式マット 配置: キャラ は 仕切り 側 (= 相手 と 対峙)、 DON は 自分側 手前。
        - 相手 マット (上): 上から DON → リーダー段 → キャラ (= キャラ が 仕切り 接触)
        - 自分 マット (下): 上から キャラ → リーダー段 → DON (= キャラ が 仕切り 接触)
      */}
      <div className="flex min-h-0 flex-1 flex-col justify-between gap-1">
        {/* 上段: 相手 マットなら DON (= 相手 手前)、 自分 マットなら キャラ (= 自分 奥) */}
        {!isMe ? (
          <DonRow
            donActive={player.don_active}
            donRested={player.don_rested}
            donTotal={player.don_total}
          />
        ) : (
          <CharacterRow
            chars={player.characters}
            attackerIid={attackerIid}
            canSelectAsTarget={false}
            canAct={canAct}
            actionsByIid={actionsByIid}
            onChara={onSelfCharaClick}
            selection={selection}
          />
        )}

        {/* 中段: リーダー / ステージ / デッキ / トラッシュ */}
        <CenterRow
          player={player}
          isMe={isMe}
          isLeaderTarget={canSelectAsTarget}
          isLeaderActable={
            canAct &&
            (actionsByIid.get(player.leader.instance_id)?.length ?? 0) > 0
          }
          isLeaderSelected={isMe && selection?.kind === "self_leader"}
          isLeaderAttacker={attackerIid === player.leader.instance_id}
          onLeaderClick={isMe ? onSelfLeaderClick : onLeaderClick}
        />

        {/* 下段: 相手 マットなら キャラ (= 相手 奥、 仕切り 接触)、 自分 マットなら DON (= 自分 手前) */}
        {!isMe ? (
          <CharacterRow
            chars={player.characters}
            attackerIid={attackerIid}
            canSelectAsTarget={canSelectAsTarget}
            canAct={false}
            actionsByIid={actionsByIid}
            onChara={onCharaClick}
            selection={selection}
          />
        ) : (
          <DonRow
            donActive={player.don_active}
            donRested={player.don_rested}
            donTotal={player.don_total}
          />
        )}
      </div>

      {/* ヘッダ ラベル */}
      <div
        className={
          "absolute top-1 left-1/2 -translate-x-1/2 rounded px-2 py-0.5 text-[10px] font-bold " +
          (isMe ? "bg-emerald-700 text-white" : "bg-rose-700 text-white")
        }
      >
        {isMe ? "YOU" : "AI"} | Hand {player.hand_count} | Deck {player.deck_count} | Trash {player.trash_count}
      </div>
    </div>
  );
}

function LifeStack({ count }: { count: number }) {
  return (
    <div className="flex flex-col gap-0.5">
      {Array.from({ length: count }).map((_, i) => (
        <img
          key={i}
          src="/assets/ura.png"
          alt="life"
          className="h-6 w-9 rounded shadow"
        />
      ))}
      {count === 0 && (
        <div className="rounded border border-red-500 px-2 py-1 text-[10px] text-red-300">
          0
        </div>
      )}
    </div>
  );
}

function DonRow({
  donActive,
  donRested,
  donTotal,
}: {
  donActive: number;
  donRested: number;
  donTotal: number;
}) {
  const totalShown = Math.min(donTotal, 12);
  return (
    <div className="flex shrink-0 items-center gap-1 rounded bg-black/30 px-2 py-1">
      <span className="text-[10px] text-zinc-300">DON</span>
      <div className="flex flex-wrap gap-0.5">
        {Array.from({ length: donActive }).map((_, i) => (
          <img
            key={`a-${i}`}
            src="/assets/don.png"
            alt="DON"
            className="h-7 w-5 rounded shadow ring-1 ring-amber-400"
          />
        ))}
        {Array.from({ length: donRested }).map((_, i) => (
          <img
            key={`r-${i}`}
            src="/assets/don.png"
            alt="DON rested"
            className="h-5 w-7 rotate-90 rounded opacity-60 shadow"
          />
        ))}
        {Array.from({ length: Math.max(0, totalShown - donActive - donRested) }).map(
          (_, i) => (
            <div
              key={`p-${i}`}
              className="h-7 w-5 rounded bg-zinc-700/40"
            />
          ),
        )}
      </div>
      <span className="ml-auto text-[10px] text-zinc-300">
        {donActive}A / {donRested}R
      </span>
    </div>
  );
}

function CenterRow({
  player,
  isMe,
  isLeaderTarget,
  isLeaderActable,
  isLeaderSelected,
  isLeaderAttacker,
  onLeaderClick,
}: {
  player: PlayerSnapshot;
  isMe: boolean;
  isLeaderTarget: boolean;
  isLeaderActable: boolean;
  isLeaderSelected: boolean;
  isLeaderAttacker: boolean;
  onLeaderClick: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center justify-center gap-2 py-1">
      <CharCard
        ch={player.leader}
        isLeader={true}
        isMine={isMe}
        isAttacker={isLeaderAttacker}
        isTarget={isLeaderTarget}
        isActable={isLeaderActable}
        isSelected={isLeaderSelected}
        onClick={onLeaderClick}
        size="leader"
      />
      <div className="flex flex-col items-center gap-0.5">
        <div className="text-[9px] text-zinc-300">STAGE</div>
        {player.stages[0] ? (
          <CharCard
            ch={player.stages[0]}
            isLeader={false}
            isMine={isMe}
            isAttacker={false}
            isTarget={false}
            isActable={false}
            isSelected={false}
            onClick={() => {}}
            size="small"
          />
        ) : (
          <div className="flex h-16 w-12 items-center justify-center rounded border border-dashed border-zinc-600 text-[8px] text-zinc-500">
            empty
          </div>
        )}
      </div>
      <div className="flex flex-col items-center gap-0.5">
        <div className="text-[9px] text-zinc-300">DECK</div>
        <div className="relative">
          <img
            src="/assets/ura.png"
            alt="deck"
            className="h-16 w-12 rounded shadow"
          />
          <span className="absolute -bottom-1 -right-1 rounded bg-zinc-900 px-1 text-[9px] font-bold text-white">
            {player.deck_count}
          </span>
        </div>
      </div>
      <div className="flex flex-col items-center gap-0.5">
        <div className="text-[9px] text-zinc-300">TRASH</div>
        <div
          className={
            "relative h-16 w-12 rounded border border-dashed border-zinc-600 " +
            (player.trash_count > 0 ? "bg-zinc-700/40" : "")
          }
        >
          <span className="absolute bottom-0 right-0 rounded bg-zinc-900 px-1 text-[9px] font-bold text-white">
            {player.trash_count}
          </span>
        </div>
      </div>
    </div>
  );
}

function CharacterRow({
  chars,
  attackerIid,
  canSelectAsTarget,
  canAct,
  actionsByIid,
  onChara,
  selection,
}: {
  chars: CharSnapshot[];
  attackerIid: number | null;
  canSelectAsTarget: boolean;
  canAct: boolean;
  actionsByIid: Map<number, HumanLegalAction[]>;
  onChara: (iid: number) => void;
  selection?: Selection;
}) {
  // 5 枠 表示 (= 空 枠 placeholder 含む)
  const slots: (CharSnapshot | null)[] = [...chars];
  while (slots.length < 5) slots.push(null);
  return (
    <div className="flex shrink-0 items-center justify-center gap-1 py-1">
      {slots.map((c, i) => {
        if (!c) {
          return (
            <div
              key={`slot-${i}`}
              className="h-20 w-14 rounded border border-dashed border-zinc-600/50"
              data-iid="empty"
            />
          );
        }
        const isAttacker = attackerIid === c.instance_id;
        const isActable =
          canAct && (actionsByIid.get(c.instance_id)?.length ?? 0) > 0;
        const isSelected =
          selection?.kind === "self_chara" && selection.iid === c.instance_id;
        return (
          <CharCard
            key={c.instance_id}
            ch={c}
            isLeader={false}
            isMine={true}
            isAttacker={isAttacker}
            isTarget={canSelectAsTarget}
            isActable={isActable}
            isSelected={isSelected}
            onClick={() => onChara(c.instance_id)}
            size="small"
          />
        );
      })}
    </div>
  );
}

function CharCard({
  ch,
  isLeader,
  isAttacker,
  isTarget,
  isActable,
  isSelected,
  onClick,
  size,
}: {
  ch: CharSnapshot;
  isLeader: boolean;
  isMine: boolean;
  isAttacker: boolean;
  isTarget: boolean;
  isActable: boolean;
  isSelected: boolean;
  onClick: () => void;
  size: "leader" | "small";
}) {
  const dim = size === "leader" ? "h-24 w-18" : "h-20 w-14";
  const ringClass = isSelected
    ? "ring-4 ring-yellow-400 ring-offset-2 ring-offset-amber-950"
    : isAttacker
      ? "ring-4 ring-orange-500 ring-offset-2 ring-offset-amber-950 animate-pulse"
      : isTarget
        ? "ring-2 ring-rose-500 hover:ring-rose-400 hover:ring-4"
        : isActable
          ? "ring-2 ring-emerald-400 hover:ring-emerald-300"
          : "ring-1 ring-zinc-700";
  const cursor = isActable || isTarget ? "cursor-pointer" : "cursor-default";
  return (
    <button
      type="button"
      data-iid={ch.instance_id}
      onClick={onClick}
      className={`group relative inline-block ${cursor} transition`}
      title={`${ch.name} (P=${ch.power}, iid=${ch.instance_id}${ch.rested ? ", R" : ""}${ch.attached_dons > 0 ? `, +${ch.attached_dons}d` : ""})`}
    >
      <div
        className={`overflow-hidden rounded ${ringClass} ${ch.rested ? "rotate-90" : ""}`}
      >
        <CardImage
          cardId={ch.card_id}
          alt={ch.name}
          className={`${dim} object-cover`}
        />
      </div>
      <span className="absolute top-0 left-0 rounded-br bg-black/80 px-1 text-[10px] font-bold text-white">
        {ch.power}
      </span>
      {ch.attached_dons > 0 && (
        <span className="absolute bottom-0 right-0 rounded-tl bg-amber-600 px-1 text-[9px] font-bold text-white">
          +{ch.attached_dons}d
        </span>
      )}
      {ch.summoning_sickness && !isLeader && (
        <span className="absolute top-0 right-0 rounded-bl bg-blue-600 px-1 text-[8px] text-white">
          zZ
        </span>
      )}
      {ch.keywords.length > 0 && (
        <div className="absolute bottom-0 left-0 flex gap-0.5">
          {ch.keywords.map((k) => (
            <span
              key={k}
              className="rounded-tr bg-zinc-900/90 px-0.5 text-[8px] text-white"
              title={k}
            >
              {k[0]}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

// ========================================================================== //
// 手札 row
// ========================================================================== //

function HandRow({
  hand,
  actionsByHand,
  canAct,
  selectedIdx,
  onClick,
}: {
  hand: string[];
  actionsByHand: Map<number, HumanLegalAction[]>;
  canAct: boolean;
  selectedIdx: number | null;
  onClick: (idx: number) => void;
}) {
  return (
    <div className="flex shrink-0 items-center justify-center gap-1 rounded bg-black/40 p-2">
      <span className="shrink-0 text-[10px] font-bold text-zinc-200">
        HAND ({hand.length})
      </span>
      <div className="flex flex-wrap gap-1">
        {hand.map((cardId, i) => {
          const playable = canAct && (actionsByHand.get(i)?.length ?? 0) > 0;
          const selected = selectedIdx === i;
          const ring = selected
            ? "ring-4 ring-yellow-400 -translate-y-2"
            : playable
              ? "ring-2 ring-emerald-400 hover:-translate-y-1 hover:ring-emerald-300"
              : "ring-1 ring-zinc-700 opacity-80";
          return (
            <button
              key={i}
              type="button"
              onClick={() => onClick(i)}
              disabled={!playable}
              className={`relative inline-block transition ${ring} rounded overflow-hidden ${playable ? "cursor-pointer" : "cursor-default"}`}
              title={cardId}
            >
              <CardImage
                cardId={cardId}
                alt={cardId}
                className="h-24 w-auto object-cover"
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ========================================================================== //
// 左 サイド: log
// ========================================================================== //

function LogSidebar({ log }: { log: string[] }) {
  return (
    <div className="flex w-48 shrink-0 flex-col overflow-hidden rounded bg-black/50 p-2 text-[10px] text-zinc-200">
      <div className="mb-1 shrink-0 font-bold">LOG</div>
      <div className="flex-1 overflow-y-auto font-mono">
        {log.map((line, i) => (
          <div
            key={i}
            className="border-b border-zinc-700/50 py-0.5"
            title={line}
          >
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}

// ========================================================================== //
// 右 サイド: action panel
// ========================================================================== //

function RightActionPanel({
  canAct,
  selection,
  primaryLabel,
  onConfirm,
  onCancel,
  endPhaseAction,
  onEndPhase,
  isHumanTurn,
  isDefensePending,
  gameOver,
}: {
  canAct: boolean;
  selection: Selection;
  primaryLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  endPhaseAction?: HumanLegalAction;
  onEndPhase: () => void;
  isHumanTurn: boolean;
  isDefensePending: boolean;
  gameOver: boolean;
}) {
  return (
    <div className="flex w-44 shrink-0 flex-col gap-2 rounded bg-black/40 p-2">
      <div className="text-[10px] font-bold text-zinc-200">ACTION</div>
      <div className="flex flex-1 flex-col gap-2">
        {gameOver && (
          <div className="rounded bg-amber-700 p-3 text-center text-sm font-bold text-white">
            GAME OVER
          </div>
        )}
        {!gameOver && !isHumanTurn && (
          <div className="rounded bg-rose-900/60 p-3 text-center text-xs text-rose-100">
            AI 思考中...
          </div>
        )}
        {!gameOver && isDefensePending && (
          <div className="rounded bg-amber-700 p-3 text-center text-xs text-white">
            ⚠ 防御 中
            <br />
            下 のパネルで 選択
          </div>
        )}
        {canAct && !selection && (
          <div className="rounded bg-emerald-900/60 p-3 text-center text-xs text-emerald-100">
            カード を 選択 してください
            <div className="mt-1 text-[9px] text-emerald-200">
              手札 / 自リーダー / 自キャラ click
            </div>
          </div>
        )}
        {canAct && selection?.kind === "attack_pending" && (
          <div className="rounded bg-orange-700 p-3 text-center text-xs text-white">
            ⚔ 攻撃中
            <div className="mt-1 text-[9px]">対象 (リーダー or キャラ) click</div>
          </div>
        )}
        {canAct && selection && selection.kind !== "attack_pending" && (
          <button
            type="button"
            onClick={onConfirm}
            className="rounded bg-emerald-600 p-3 text-base font-bold text-white shadow-lg hover:bg-emerald-500"
          >
            {primaryLabel}
          </button>
        )}
        {canAct && selection && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded bg-zinc-700 p-2 text-xs text-white hover:bg-zinc-600"
          >
            Cancel
          </button>
        )}
      </div>
      {canAct && endPhaseAction && (
        <button
          type="button"
          onClick={onEndPhase}
          className="rounded bg-rose-600 p-2 text-xs font-bold text-white hover:bg-rose-500"
        >
          ターン終了
        </button>
      )}
    </div>
  );
}

// ========================================================================== //
// 攻撃 矢印
// ========================================================================== //

function AttackArrow({
  attackerIid,
  mousePos,
}: {
  attackerIid: number;
  mousePos: { x: number; y: number };
}) {
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const elem = document.querySelector(
      `button[data-iid="${attackerIid}"]`,
    ) as HTMLButtonElement | null;
    if (!elem) {
      setOrigin(null);
      return;
    }
    const board = elem.closest('[class*="relative flex h-["]') as HTMLElement | null;
    if (!board) {
      setOrigin(null);
      return;
    }
    const r = elem.getBoundingClientRect();
    const br = board.getBoundingClientRect();
    setOrigin({
      x: r.left + r.width / 2 - br.left,
      y: r.top + r.height / 2 - br.top,
    });
  }, [attackerIid, mousePos]);

  if (!origin) return null;
  return (
    <svg className="pointer-events-none absolute inset-0 z-50 h-full w-full">
      <defs>
        <marker
          id="arrowhead"
          markerWidth="12"
          markerHeight="12"
          refX="6"
          refY="6"
          orient="auto"
        >
          <polygon points="0 0, 12 6, 0 12" fill="#ef4444" />
        </marker>
      </defs>
      <line
        x1={origin.x}
        y1={origin.y}
        x2={mousePos.x}
        y2={mousePos.y}
        stroke="#ef4444"
        strokeWidth="5"
        strokeLinecap="round"
        markerEnd="url(#arrowhead)"
        opacity="0.85"
      />
    </svg>
  );
}

// ========================================================================== //
// 防御 overlay
// ========================================================================== //

function DefenseOverlay({
  payload,
  me,
  blockerIid,
  setBlockerIid,
  counterIdxs,
  setCounterIdxs,
  onSubmit,
  busy,
}: {
  payload: Record<string, unknown> | null;
  me: PlayerSnapshot;
  blockerIid: number | null;
  setBlockerIid: (v: number | null) => void;
  counterIdxs: number[];
  setCounterIdxs: (v: number[]) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  const blockerIids =
    (payload?.legal_blocker_iids as number[] | undefined) ?? [];
  const counterIdxsAvail =
    (payload?.legal_counter_card_idxs as number[] | undefined) ?? [];
  const isLeaderAttack = !!payload?.is_leader_attack;

  function toggleCounter(idx: number) {
    if (counterIdxs.includes(idx)) {
      setCounterIdxs(counterIdxs.filter((x) => x !== idx));
    } else {
      setCounterIdxs([...counterIdxs, idx]);
    }
  }

  const blockerOptions = me.characters.filter((c) =>
    blockerIids.includes(c.instance_id),
  );

  return (
    <div className="absolute inset-x-4 bottom-4 z-50 rounded-lg border-2 border-amber-400 bg-amber-950/95 p-3 shadow-xl backdrop-blur">
      <div className="mb-2 text-sm font-bold text-amber-200">
        ⚠ 相手が {isLeaderAttack ? "リーダー" : "キャラ"} を攻撃中 — 防御
      </div>
      <div className="flex gap-4">
        <div>
          <div className="text-xs font-semibold text-amber-200">Blocker</div>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => setBlockerIid(null)}
              className={
                "rounded px-2 py-1 text-xs " +
                (blockerIid === null
                  ? "bg-amber-500 text-white"
                  : "border border-amber-400 bg-amber-900/40 text-amber-100")
              }
            >
              No Blocker
            </button>
            {blockerOptions.map((c) => (
              <button
                key={c.instance_id}
                type="button"
                onClick={() => setBlockerIid(c.instance_id)}
                className={
                  "rounded transition " +
                  (blockerIid === c.instance_id
                    ? "ring-4 ring-amber-400"
                    : "ring-1 ring-amber-600 hover:ring-amber-400")
                }
                title={c.name}
              >
                <CardImage
                  cardId={c.card_id}
                  alt={c.name}
                  className="h-20 w-auto rounded"
                />
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1">
          <div className="text-xs font-semibold text-amber-200">
            Counter ({counterIdxs.length})
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {counterIdxsAvail.length === 0 && (
              <span className="text-xs text-amber-300">
                手札に counter 無し
              </span>
            )}
            {counterIdxsAvail.map((idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => toggleCounter(idx)}
                className={
                  "rounded transition " +
                  (counterIdxs.includes(idx)
                    ? "ring-4 ring-amber-400"
                    : "ring-1 ring-amber-600 hover:ring-amber-400")
                }
              >
                <CardImage
                  cardId={me.hand[idx]}
                  alt={me.hand[idx]}
                  className="h-20 w-auto rounded"
                />
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy}
          className="self-end rounded bg-amber-500 px-4 py-2 text-sm font-bold text-white hover:bg-amber-400 disabled:opacity-50"
        >
          防御確定
        </button>
      </div>
    </div>
  );
}
