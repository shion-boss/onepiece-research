"use client";

import { useEffect, useState } from "react";
import {
  applyHumanAction,
  applyHumanDefense,
  endHumanMatch,
  fetchHumanMatch,
  startHumanMatch,
  type HumanLegalAction,
  type HumanMatchState,
} from "@/lib/api";

/**
 * 人間 vs AI 対戦 component。
 *
 * 自分のターン中は legal_actions ボタンをクリックして action を選ぶ。
 * AI ターン中は API 側 で 自動進行、 board snapshot を 表示。
 * 攻撃 を 受けた時 (= pending_kind = "defense") は ブロッカー / カウンター を選ぶ。
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
  const [counterIdxs, setCounterIdxs] = useState<number[]>([]);
  const [blockerIid, setBlockerIid] = useState<number | null>(null);

  const sessionId = state?.session_id;

  async function handleStart() {
    setError(null);
    setBusy(true);
    setCounterIdxs([]);
    setBlockerIid(null);
    try {
      const hf =
        humanFirst === "random" ? null : humanFirst === "first";
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

  async function handleAction(idx: number) {
    if (!sessionId) return;
    setError(null);
    setBusy(true);
    try {
      const next = await applyHumanAction(sessionId, idx);
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
      // unmount 時 session 削除
      if (sessionId) {
        endHumanMatch(sessionId).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // ====================================================================== //
  // 開始 前 セレクタ
  // ====================================================================== //
  if (!state) {
    return (
      <div className="flex flex-col gap-3 rounded border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-lg font-semibold">人間 vs AI 対戦</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_120px_140px_auto]">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-zinc-500">自分のデッキ (P0)</span>
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
            <span className="text-zinc-500">AI のデッキ (P1)</span>
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
            onClick={handleStart}
            disabled={busy || !deckA || !deckB}
            className="self-end rounded bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
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

  // ====================================================================== //
  // 対戦中 (= state あり)
  // ====================================================================== //
  const isHumanTurn = state.turn_player_idx === state.human_idx;
  const isDefensePending = state.pending_kind === "defense";
  const isActionPending = state.pending_kind === "action";

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
          {isHumanTurn ? "あなたのターン" : "AI のターン"}
        </span>
        {state.game_over && (
          <span className="rounded bg-amber-600 px-2 py-0.5 text-xs font-semibold text-white">
            ゲーム終了 {state.winner === state.human_idx ? "(勝利)" : state.winner === state.ai_idx ? "(敗北)" : "(引き分け)"}
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

      {/* 盤面 snapshot */}
      <BoardDisplay state={state} />

      {/* legal actions or defense panel */}
      {isActionPending && isHumanTurn && (
        <ActionPanel
          actions={state.legal_actions}
          busy={busy}
          onPick={handleAction}
        />
      )}
      {isDefensePending && (
        <DefensePanel
          payload={state.pending_payload}
          state={state}
          blockerIid={blockerIid}
          setBlockerIid={setBlockerIid}
          counterIdxs={counterIdxs}
          setCounterIdxs={setCounterIdxs}
          onSubmit={handleDefenseSubmit}
          busy={busy}
        />
      )}
      {!isActionPending && !isDefensePending && !state.game_over && (
        <div className="rounded border border-zinc-200 bg-white p-2 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
          AI 進行中...
        </div>
      )}

      {/* ログ */}
      <div className="max-h-48 overflow-y-auto rounded bg-zinc-50 p-2 text-xs font-mono dark:bg-zinc-950">
        {state.log.map((line, i) => (
          <div key={i} className="text-zinc-700 dark:text-zinc-300">
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- //

function ActionPanel({
  actions,
  busy,
  onPick,
}: {
  actions: HumanLegalAction[];
  busy: boolean;
  onPick: (idx: number) => void;
}) {
  return (
    <div className="rounded border border-emerald-300 bg-emerald-50 p-2 dark:border-emerald-800 dark:bg-emerald-950">
      <div className="mb-2 text-xs font-semibold text-emerald-900 dark:text-emerald-200">
        あなたの手番 — action を 選択 ({actions.length} 件)
      </div>
      <div className="flex flex-wrap gap-2">
        {actions.map((a) => (
          <button
            key={a.idx}
            type="button"
            onClick={() => onPick(a.idx)}
            disabled={busy}
            className="rounded border border-emerald-400 bg-white px-2 py-1 text-xs hover:bg-emerald-100 disabled:opacity-50 dark:bg-zinc-900 dark:hover:bg-zinc-800"
          >
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function DefensePanel({
  payload,
  state,
  blockerIid,
  setBlockerIid,
  counterIdxs,
  setCounterIdxs,
  onSubmit,
  busy,
}: {
  payload: Record<string, unknown> | null;
  state: HumanMatchState;
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

  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-2 dark:border-amber-800 dark:bg-amber-950">
      <div className="mb-2 text-xs font-semibold text-amber-900 dark:text-amber-200">
        防御 — 相手が {isLeaderAttack ? "リーダー" : "キャラ"} を 攻撃中
      </div>
      <div className="flex flex-col gap-2 text-xs">
        <div>
          <span className="font-semibold">ブロッカー: </span>
          <button
            type="button"
            onClick={() => setBlockerIid(null)}
            className={
              blockerIid === null
                ? "rounded bg-amber-600 px-2 py-1 text-white"
                : "rounded border border-amber-400 px-2 py-1"
            }
          >
            使わない
          </button>
          {blockerIids.map((iid) => (
            <button
              key={iid}
              type="button"
              onClick={() => setBlockerIid(iid)}
              className={
                "ml-1 " +
                (blockerIid === iid
                  ? "rounded bg-amber-600 px-2 py-1 text-white"
                  : "rounded border border-amber-400 px-2 py-1")
              }
            >
              iid={iid}
            </button>
          ))}
        </div>
        <div>
          <span className="font-semibold">カウンター: </span>
          {counterIdxsAvail.length === 0 && (
            <span className="text-zinc-500">手札に counter 持ち 無し</span>
          )}
          {counterIdxsAvail.map((idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => toggleCounter(idx)}
              className={
                "ml-1 " +
                (counterIdxs.includes(idx)
                  ? "rounded bg-amber-600 px-2 py-1 text-white"
                  : "rounded border border-amber-400 px-2 py-1")
              }
            >
              hand[{idx}]
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy}
          className="self-start rounded bg-amber-600 px-3 py-1 text-white hover:bg-amber-700 disabled:opacity-50"
        >
          防御確定
        </button>
      </div>
    </div>
  );
}

function BoardDisplay({ state }: { state: HumanMatchState }) {
  type PlayerSnap = {
    name: string;
    leader: { name: string; power: number; rested: boolean };
    characters: { name: string; power: number; rested: boolean; instance_id: number; attached_dons: number }[];
    hand_size: number;
    deck_size: number;
    life_count: number;
    don_active: number;
    don_rested: number;
    trash_count: number;
  };
  const snap = state.snapshot as { players?: PlayerSnap[] } | null;
  const players = snap?.players ?? [];
  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
      {players.map((p, idx) => {
        const isHuman = idx === state.human_idx;
        return (
          <div
            key={idx}
            className={
              "rounded border p-2 " +
              (isHuman
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950"
                : "border-rose-300 bg-rose-50 dark:border-rose-800 dark:bg-rose-950")
            }
          >
            <div className="mb-1 flex items-center gap-2 text-xs font-semibold">
              <span>{p.name}</span>
              <span className="rounded bg-zinc-200 px-1 dark:bg-zinc-800">
                {isHuman ? "あなた" : "AI"}
              </span>
              <span className="text-zinc-500">
                life={p.life_count} hand={p.hand_size} deck={p.deck_size} trash=
                {p.trash_count}
              </span>
              <span className="text-zinc-500">
                don={p.don_active}/{p.don_active + p.don_rested}
              </span>
            </div>
            <div className="text-xs">
              <div className="flex items-center gap-1">
                <span className="rounded bg-zinc-300 px-1 text-[10px] dark:bg-zinc-700">
                  L
                </span>
                <span>
                  {p.leader.name} ({p.leader.power}, {p.leader.rested ? "R" : "A"})
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {p.characters.map((c) => (
                  <span
                    key={c.instance_id}
                    className="rounded bg-white px-1 text-[11px] dark:bg-zinc-800"
                  >
                    {c.name} ({c.power}
                    {c.attached_dons > 0 ? ` +${c.attached_dons}d` : ""},
                    {c.rested ? "R" : "A"}, iid={c.instance_id})
                  </span>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
