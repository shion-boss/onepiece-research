"use client";

import { useEffect, useState } from "react";
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
 * 人間 vs AI 対戦 component (= リッチ UI 版)。
 *
 * 自分のターン中:
 *  - 手札 カード click → 対応 PlayCharacter / PlayEvent action 適用
 *  - 自リーダー click → AttachDonToLeader or AttackLeader (= 攻撃中の場合 確定)
 *  - 自キャラ click → AttachDonToCharacter / 攻撃 mode 開始 / ActivateMain
 *  - 攻撃中 (= attacker 選択済): 相手 リーダー or キャラ click で 対象確定
 *  - 「ターン終了」 ボタン
 *
 * 防御 phase (= 相手 攻撃中): blocker / counter 選択 panel。
 */

type DeckOption = { slug: string; name: string };

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
  // 攻撃中 attacker (= iid) を 保持。 null なら 通常 mode、 値あり なら 「次 の click で 対象確定」
  const [attackingIid, setAttackingIid] = useState<number | null>(null);
  // defense panel state
  const [counterIdxs, setCounterIdxs] = useState<number[]>([]);
  const [blockerIid, setBlockerIid] = useState<number | null>(null);

  const sessionId = state?.session_id;

  async function handleStart() {
    setError(null);
    setBusy(true);
    setAttackingIid(null);
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
    setAttackingIid(null);
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

  // 開始前 セレクタ
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
        snapshot を 取得できません
      </div>
    );
  }
  const isHumanTurn = state.turn_player_idx === state.human_idx;
  const isDefensePending = state.pending_kind === "defense";
  const isActionPending = state.pending_kind === "action";

  // 自分 / 相手 player snapshot
  const me = snap.players[state.human_idx];
  const opp = snap.players[state.ai_idx];

  // legal_actions を card_id / iid 別に index 化
  const actionsByHand = new Map<number, HumanLegalAction[]>();
  const actionsByIid = new Map<number, HumanLegalAction[]>();
  let endPhaseAction: HumanLegalAction | undefined;
  let attackLeaderActions: HumanLegalAction[] = [];
  const attackCharacterByAttackerIid = new Map<number, HumanLegalAction[]>();
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
    if (a.kind === "EndPhase") endPhaseAction = a;
    if (a.kind === "AttackLeader" && a.attacker_iid !== undefined) {
      attackLeaderActions.push(a);
    }
    if (a.kind === "AttackCharacter" && a.attacker_iid !== undefined) {
      const arr = attackCharacterByAttackerIid.get(a.attacker_iid) ?? [];
      arr.push(a);
      attackCharacterByAttackerIid.set(a.attacker_iid, arr);
    }
  }

  // 各 char (=リーダー or 自キャラ) の 利用可能 action
  function availableActionsForCharacter(iid: number): HumanLegalAction[] {
    // AttachDon, ActivateMain, AttackLeader, AttackCharacter
    return state!.legal_actions.filter((a) => {
      if (a.attacker_iid === iid && (a.kind === "AttackLeader" || a.kind === "AttackCharacter")) return true;
      if (a.iid === iid && (a.kind === "AttachDonToCharacter" || a.kind === "ActivateMain")) return true;
      return false;
    });
  }

  function availableLeaderActions(): HumanLegalAction[] {
    return state!.legal_actions.filter((a) => {
      if (a.kind === "AttachDonToLeader") return true;
      // 自リーダー が attacker (= attacker_iid が leader.instance_id)
      if (a.kind === "AttackLeader" || a.kind === "AttackCharacter") {
        if (a.attacker_iid === me.leader.instance_id) return true;
      }
      return false;
    });
  }

  function clickHandCard(handIdx: number) {
    if (!isHumanTurn || !isActionPending || busy) return;
    const actions = actionsByHand.get(handIdx) ?? [];
    if (actions.length === 0) return;
    if (actions.length === 1) {
      applyAction(actions[0]);
    } else {
      // 複数 (= rare、 とりあえず 最初 を)
      applyAction(actions[0]);
    }
  }

  function clickSelfCharacter(iid: number) {
    if (!isHumanTurn || !isActionPending || busy) return;
    const available = availableActionsForCharacter(iid);
    if (available.length === 0) return;
    // attack 系 が ある なら attacker として 選択 (= 次 の click で 対象確定)
    const attackable = available.find(
      (a) => a.kind === "AttackLeader" || a.kind === "AttackCharacter",
    );
    if (attackable) {
      setAttackingIid(iid);
      return;
    }
    // attack 不可 → AttachDon or ActivateMain (= 最初 の を 適用)
    applyAction(available[0]);
  }

  function clickSelfLeader() {
    if (!isHumanTurn || !isActionPending || busy) return;
    const actions = availableLeaderActions();
    if (actions.length === 0) return;
    // AttackLeader が ある (= 自リーダー が attacker、 まれ) → attacker mode
    const attackable = actions.find(
      (a) => a.kind === "AttackLeader" || a.kind === "AttackCharacter",
    );
    if (attackable) {
      setAttackingIid(me.leader.instance_id);
      return;
    }
    // AttachDonToLeader 等
    applyAction(actions[0]);
  }

  function clickOpponentLeader() {
    if (!isHumanTurn || !isActionPending || busy) return;
    if (attackingIid === null) return;
    const action = state!.legal_actions.find(
      (a) =>
        a.kind === "AttackLeader" && a.attacker_iid === attackingIid,
    );
    if (action) applyAction(action);
  }

  function clickOpponentCharacter(iid: number) {
    if (!isHumanTurn || !isActionPending || busy) return;
    if (attackingIid === null) return;
    const action = state!.legal_actions.find(
      (a) =>
        a.kind === "AttackCharacter" &&
        a.attacker_iid === attackingIid &&
        a.target_iid === iid,
    );
    if (action) applyAction(action);
  }

  // 攻撃モード 解除 (= 何もない 領域 click 用)
  function cancelAttack() {
    setAttackingIid(null);
  }

  return (
    <div className="flex flex-col gap-3">
      {/* ヘッダ */}
      <div className="flex flex-wrap items-center gap-3 rounded bg-zinc-100 px-3 py-2 text-sm dark:bg-zinc-900">
        <span className="font-semibold">
          ターン {state.turn} ({state.phase})
        </span>
        <span
          className={
            isHumanTurn
              ? "rounded bg-emerald-600 px-2 py-0.5 text-xs text-white"
              : "rounded bg-zinc-500 px-2 py-0.5 text-xs text-white"
          }
        >
          {isHumanTurn ? "あなたのターン" : "AI のターン (進行中)"}
        </span>
        {state.game_over && (
          <span className="rounded bg-amber-600 px-2 py-0.5 text-xs font-semibold text-white">
            ゲーム終了:{" "}
            {state.winner === state.human_idx
              ? "勝利 🎉"
              : state.winner === state.ai_idx
                ? "敗北"
                : "引き分け"}
          </span>
        )}
        <span className="ml-auto text-xs text-zinc-500">
          sid={sessionId?.slice(0, 8)}
        </span>
        <button
          type="button"
          onClick={handleEnd}
          className="rounded border border-zinc-400 px-2 py-0.5 text-xs hover:bg-zinc-200 dark:border-zinc-600 dark:hover:bg-zinc-800"
        >
          終了
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      )}

      {/* 相手 (上) */}
      <PlayerBoard
        player={opp}
        isMe={false}
        attackingIid={attackingIid}
        onLeaderClick={clickOpponentLeader}
        onCharacterClick={clickOpponentCharacter}
      />

      {/* 中央 操作 行 */}
      <div className="flex items-center gap-2">
        {isActionPending && isHumanTurn && (
          <>
            {attackingIid !== null && (
              <div className="flex items-center gap-2 rounded border border-amber-400 bg-amber-50 px-2 py-1 text-xs dark:border-amber-700 dark:bg-amber-950">
                <span>⚔ 攻撃中 (attacker iid={attackingIid})</span>
                <button
                  type="button"
                  onClick={cancelAttack}
                  className="rounded border border-amber-400 px-2 py-0.5"
                >
                  キャンセル
                </button>
              </div>
            )}
            {endPhaseAction && (
              <button
                type="button"
                onClick={() => applyAction(endPhaseAction!)}
                disabled={busy}
                className="rounded bg-rose-600 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                ターン終了
              </button>
            )}
            <span className="text-xs text-zinc-500">
              手札 click = 出す / 自キャラ click = DON 付与 or 攻撃 / 起動メイン あれば 自動
            </span>
          </>
        )}
        {isDefensePending && (
          <span className="text-xs font-semibold text-amber-700 dark:text-amber-300">
            ⚠ 防御 中 — 下 パネル で ブロッカー / カウンター 選択
          </span>
        )}
        {!isHumanTurn && !isDefensePending && !state.game_over && (
          <span className="text-xs text-zinc-500">AI 思考中...</span>
        )}
      </div>

      {/* 自分 (下) */}
      <PlayerBoard
        player={me}
        isMe={true}
        attackingIid={attackingIid}
        onLeaderClick={clickSelfLeader}
        onCharacterClick={clickSelfCharacter}
        legalActionsByIid={actionsByIid}
        canAct={isHumanTurn && isActionPending && !busy}
      />

      {/* 手札 */}
      <HandPanel
        hand={me.hand}
        actionsByHand={actionsByHand}
        canAct={isHumanTurn && isActionPending && !busy}
        onPick={clickHandCard}
      />

      {/* 防御 panel */}
      {isDefensePending && (
        <DefensePanel
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

      {/* ログ */}
      <details className="rounded bg-zinc-50 dark:bg-zinc-950">
        <summary className="cursor-pointer p-2 text-xs font-semibold">
          ログ ({state.log.length} 行)
        </summary>
        <div className="max-h-48 overflow-y-auto p-2 text-xs font-mono">
          {state.log.map((line, i) => (
            <div key={i} className="text-zinc-700 dark:text-zinc-300">
              {line}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

// ============================================================================ //
// 開始前 セレクタ
// ============================================================================ //

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

// ============================================================================ //
// PlayerBoard (= リーダー + キャラ + 状態表示)
// ============================================================================ //

function PlayerBoard({
  player,
  isMe,
  attackingIid,
  onLeaderClick,
  onCharacterClick,
  legalActionsByIid,
  canAct,
}: {
  player: PlayerSnapshot;
  isMe: boolean;
  attackingIid: number | null;
  onLeaderClick: () => void;
  onCharacterClick: (iid: number) => void;
  legalActionsByIid?: Map<number, HumanLegalAction[]>;
  canAct?: boolean;
}) {
  const leader = player.leader;
  const isLeaderActable =
    isMe &&
    canAct &&
    legalActionsByIid &&
    (legalActionsByIid.get(leader.instance_id)?.length ?? 0) > 0;
  // 相手 leader = 攻撃中 で attack 可能なら highlight
  const leaderTarget = !isMe && attackingIid !== null;

  return (
    <div
      className={
        "rounded border p-2 " +
        (isMe
          ? "border-emerald-300 bg-emerald-50/30 dark:border-emerald-800 dark:bg-emerald-950/30"
          : "border-rose-300 bg-rose-50/30 dark:border-rose-800 dark:bg-rose-950/30")
      }
    >
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold">
          {isMe ? "あなた" : "AI"} ({player.name})
        </span>
        <span className="text-zinc-500">
          ライフ {player.life_count} / 手札 {player.hand_count} / デッキ{" "}
          {player.deck_count} / トラッシュ {player.trash_count}
        </span>
        <span className="rounded bg-amber-200 px-1.5 text-[10px] text-amber-900 dark:bg-amber-800 dark:text-amber-100">
          DON {player.don_active}A / {player.don_rested}R /{" "}
          {player.don_total} 累計
        </span>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {/* リーダー */}
        <CharCard
          ch={leader}
          isLeader={true}
          isMine={isMe}
          isAttacker={attackingIid === leader.instance_id}
          isTarget={leaderTarget}
          isActable={isLeaderActable}
          onClick={onLeaderClick}
        />
        {/* 自キャラ群 */}
        {player.characters.map((c) => {
          const isAttacker = attackingIid === c.instance_id;
          const isCharTarget = !isMe && attackingIid !== null; // 攻撃対象候補
          const isCharActable =
            isMe &&
            canAct &&
            legalActionsByIid &&
            (legalActionsByIid.get(c.instance_id)?.length ?? 0) > 0;
          return (
            <CharCard
              key={c.instance_id}
              ch={c}
              isLeader={false}
              isMine={isMe}
              isAttacker={isAttacker}
              isTarget={isCharTarget}
              isActable={isCharActable}
              onClick={() => onCharacterClick(c.instance_id)}
            />
          );
        })}
      </div>
    </div>
  );
}

function CharCard({
  ch,
  isLeader,
  isMine,
  isAttacker,
  isTarget,
  isActable,
  onClick,
}: {
  ch: CharSnapshot;
  isLeader: boolean;
  isMine: boolean;
  isAttacker: boolean;
  isTarget: boolean;
  isActable?: boolean;
  onClick: () => void;
}) {
  const ringClass = isAttacker
    ? "ring-2 ring-amber-500"
    : isTarget
      ? "ring-2 ring-rose-500 hover:ring-rose-400"
      : isActable
        ? "ring-2 ring-emerald-400 hover:ring-emerald-300"
        : "ring-1 ring-zinc-300 dark:ring-zinc-700";
  const cursor = isActable || isTarget ? "cursor-pointer" : "cursor-default";
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "group relative inline-block " +
        cursor +
        " transition " +
        (ch.rested ? "rotate-90 " : "")
      }
      title={`${ch.name} (P=${ch.power}, iid=${ch.instance_id}${ch.rested ? ", R" : ""}${ch.attached_dons > 0 ? `, +${ch.attached_dons}d` : ""})`}
    >
      <div className={"overflow-hidden rounded " + ringClass}>
        <CardImage
          cardId={ch.card_id}
          alt={ch.name}
          className="h-24 w-auto object-cover"
        />
      </div>
      {/* 状態 オーバーレイ */}
      <div className="absolute -top-1 -right-1 flex flex-col items-end gap-0.5">
        {isLeader && (
          <span className="rounded bg-yellow-500 px-1 text-[8px] font-bold text-white">
            L
          </span>
        )}
        <span className="rounded bg-zinc-900/80 px-1 text-[9px] font-bold text-white">
          {ch.power}
        </span>
        {ch.attached_dons > 0 && (
          <span className="rounded bg-amber-600 px-1 text-[8px] font-bold text-white">
            +{ch.attached_dons}d
          </span>
        )}
        {ch.summoning_sickness && !isLeader && (
          <span className="rounded bg-blue-500 px-1 text-[8px] text-white">
            zZ
          </span>
        )}
      </div>
      {/* キーワード */}
      {ch.keywords.length > 0 && (
        <div className="absolute -bottom-1 left-0 flex gap-0.5">
          {ch.keywords.map((k) => (
            <span
              key={k}
              className="rounded bg-zinc-800/90 px-1 text-[8px] text-white"
            >
              {k[0]}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

// ============================================================================ //
// 手札 panel
// ============================================================================ //

function HandPanel({
  hand,
  actionsByHand,
  canAct,
  onPick,
}: {
  hand: string[];
  actionsByHand: Map<number, HumanLegalAction[]>;
  canAct: boolean;
  onPick: (handIdx: number) => void;
}) {
  return (
    <div className="rounded border border-zinc-300 bg-white p-2 dark:border-zinc-700 dark:bg-zinc-900">
      <div className="mb-1 text-xs font-semibold">手札 ({hand.length})</div>
      <div className="flex flex-wrap gap-2">
        {hand.map((cardId, i) => {
          const actions = actionsByHand.get(i) ?? [];
          const playable = canAct && actions.length > 0;
          return (
            <button
              key={i}
              type="button"
              onClick={() => onPick(i)}
              disabled={!playable}
              className={
                "group relative inline-block transition " +
                (playable
                  ? "cursor-pointer ring-2 ring-emerald-400 hover:ring-emerald-300"
                  : "cursor-default opacity-70 ring-1 ring-zinc-300 dark:ring-zinc-700")
              }
              title={
                playable
                  ? `クリックで ${actions[0].label}`
                  : `${cardId} (現在 出せません)`
              }
            >
              <div className="overflow-hidden rounded">
                <CardImage
                  cardId={cardId}
                  alt={cardId}
                  className="h-28 w-auto object-cover"
                />
              </div>
              {playable && (
                <span className="absolute bottom-0 left-0 right-0 rounded-b bg-emerald-600/90 px-1 text-[9px] font-bold text-white">
                  {actions[0].label}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================================ //
// 防御 panel
// ============================================================================ //

function DefensePanel({
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
    <div className="rounded border border-amber-400 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950">
      <div className="mb-2 text-sm font-semibold text-amber-900 dark:text-amber-200">
        ⚠ 相手が {isLeaderAttack ? "リーダー" : "キャラ"} を 攻撃しています — 防御 選択
      </div>
      <div className="mb-2">
        <div className="text-xs font-semibold">ブロッカー</div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setBlockerIid(null)}
            className={
              "rounded px-2 py-1 text-xs " +
              (blockerIid === null
                ? "bg-amber-600 text-white"
                : "border border-amber-500 bg-white dark:bg-zinc-900")
            }
          >
            使わない
          </button>
          {blockerOptions.map((c) => (
            <button
              key={c.instance_id}
              type="button"
              onClick={() => setBlockerIid(c.instance_id)}
              className={
                "rounded px-1 py-0.5 transition " +
                (blockerIid === c.instance_id
                  ? "ring-2 ring-amber-600"
                  : "ring-1 ring-amber-300 hover:ring-amber-400")
              }
              title={c.name}
            >
              <CardImage cardId={c.card_id} alt={c.name} className="h-20 w-auto" />
              <div className="text-[9px]">{c.name}</div>
            </button>
          ))}
        </div>
      </div>
      <div className="mb-2">
        <div className="text-xs font-semibold">
          カウンター ({counterIdxs.length} 枚 選択)
        </div>
        <div className="mt-1 flex flex-wrap gap-2">
          {counterIdxsAvail.length === 0 && (
            <span className="text-xs text-zinc-500">
              手札に counter 持ち 無し
            </span>
          )}
          {counterIdxsAvail.map((idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => toggleCounter(idx)}
              className={
                "rounded px-1 py-0.5 transition " +
                (counterIdxs.includes(idx)
                  ? "ring-2 ring-amber-600"
                  : "ring-1 ring-amber-300 hover:ring-amber-400")
              }
            >
              <CardImage cardId={me.hand[idx]} alt={me.hand[idx]} className="h-20 w-auto" />
              <div className="text-[9px]">hand[{idx}]</div>
            </button>
          ))}
        </div>
      </div>
      <button
        type="button"
        onClick={onSubmit}
        disabled={busy}
        className="rounded bg-amber-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
      >
        防御 確定
      </button>
    </div>
  );
}
