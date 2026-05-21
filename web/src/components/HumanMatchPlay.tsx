"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { CardImage } from "./CardImage";
import {
  applyHumanAction,
  applyHumanChoice,
  applyHumanDefense,
  endHumanMatch,
  startHumanMatch,
  type HumanLegalAction,
  type HumanMatchState,
} from "@/lib/api";
import type { CharSnapshot, PlayerSnapshot, StateSnapshot } from "@/lib/types";
import {
  useFrameDiff,
  LifeFlashOverlay,
  LeftCharaGhostList,
  AnimatedNumber,
  EffectToastOverlay,
  AttackBeamOverlay,
  AttackTargetArrowOverlay,
  PlayedCardOverlay,
  DrawCardOverlay,
  CounterPlayOverlay,
  fireCounterPlay,
  TurnBannerOverlay,
  useRecentDrawnIdxs,
} from "./_matchAnimHelpers";

/**
 * 人間 vs AI 対戦 component (= OPTCGSim 風 + 重ね 手札 + D&D 対応)。
 */

type DeckOption = { slug: string; name: string };

type Selection =
  | null
  | { kind: "hand"; handIdx: number }
  | { kind: "self_chara"; iid: number }
  | { kind: "self_leader" }
  | { kind: "attack_pending"; attackerIid: number };

type HoverInfo =
  | { kind: "hand"; cardId: string }
  | {
      kind: "chara";
      cardId: string;
      name: string;
      power: number;
      attached_dons: number;
      rested: boolean;
      keywords: string[];
      isLeader: boolean;
    }
  | null;

type DragPayload =
  | {
      kind: "hand";
      handIdx: number;
      handKind: "CHARACTER" | "EVENT" | "STAGE";
    }
  | { kind: "chara"; iid: number }
  | { kind: "don"; count: number }
  | { kind: "counter"; handIdx: number };

type DropTarget =
  | { kind: "self_field" }
  | { kind: "self_leader" }
  | { kind: "self_chara"; iid: number }
  | { kind: "opp_leader" }
  | { kind: "opp_chara"; iid: number }
  | { kind: "self_counter"; handIdx: number };

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
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [counterIdxs, setCounterIdxs] = useState<number[]>([]);
  const [blockerIid, setBlockerIid] = useState<number | null>(null);
  const [defenseClosing, setDefenseClosing] = useState(false);
  // counter で 使った card_id を 記録 (= PlayedCardOverlay で 「再演出」 除外 用)
  const [usedCounterCardIds, setUsedCounterCardIds] = useState<string[]>([]);
  const [hovered, setHovered] = useState<HoverInfo>(null);
  const [drag, setDrag] = useState<DragPayload | null>(null);
  const [trashViewer, setTrashViewer] = useState<"me" | "opp" | null>(null);

  const sessionId = state?.session_id;
  const boardRef = useRef<HTMLDivElement | null>(null);
  const router = useRouter();
  // applyAction 重複 防止 (= 連打 / 連 drop で 同時 fetch を 防ぐ)
  const applyInFlightRef = useRef(false);

  // frame 再生 ヘルパ (= AI ターン を ログ通り 順次 表示)
  // delay の デフォルト は 700ms。 最後の frame は 通常 setState に 任せる ので 含めない。
  async function playFrames(
    final: HumanMatchState,
    frames: Record<string, unknown>[],
    perFrameMs: number = 2200,
  ) {
    if (frames.length === 0) {
      setState(final);
      return;
    }
    // 各 frame で snapshot (= board) は 中間状態 を 表示 する が、
    // log は 累積 で 表示 する (= 「相手ターン中 log が 1 行 しか 出ない」 修正)。
    // frame.log は その時点 の 1 行 のみ なので、 final.log (= 全行) を 使う。
    // ライフ→手札 / KO / draw / turn切替 等 重い演出 frame は wait 延長。
    let prevTurn = -1;
    for (let i = 0; i < frames.length - 1; i++) {
      const f = frames[i];
      setState({
        ...final,
        snapshot: f,
        legal_actions: [],
        pending_kind: null,
        log: final.log,
      });
      const logLine = typeof f.log === "string" ? f.log : "";
      const curTurn =
        typeof f.turn === "number" ? f.turn : prevTurn;
      const turnChanged = prevTurn >= 0 && curTurn !== prevTurn;
      const turnPlayerIdx =
        typeof f.turn_player_idx === "number" ? f.turn_player_idx : -1;
      const isHumanFrame = turnPlayerIdx === final.human_idx;
      // 人間 ターン frame は wait 不要 (= user 操作 で 既に 1 つ ずつ 進行)。
      // 但し ライフ被弾 / KO 等 重要 visual は 確認時間 のため 短時間 wait は 残す。
      if (isHumanFrame) {
        const isLifeHit = /life->hand|hit:|ライフ/.test(logLine);
        const isMediumHeavy = /KO|登場/.test(logLine);
        let wait = 150;
        if (isLifeHit) wait = 1500;
        if (isMediumHeavy) wait = 800;
        prevTurn = curTurn;
        await new Promise((resolve) => setTimeout(resolve, wait));
        continue;
      }
      // 優先順 で wait 決定 (= 高い ほう を 採用、 AI ターン frame)
      const isLifeHit = /life->hand|hit:|ライフ/.test(logLine);
      const isDraw = /draw:|ドロー/.test(logLine);
      const isMediumHeavy = /KO|登場|refresh:/.test(logLine);
      const isEndPhase = /end_phase|ターン終了|GAME OVER/.test(logLine);
      let wait = perFrameMs;
      if (isLifeHit) wait = Math.max(wait, 3500);
      if (isDraw) wait = Math.max(wait, 2000);
      if (isMediumHeavy) wait = Math.max(wait, 1800);
      if (isEndPhase) wait = Math.max(wait, 3000);
      if (turnChanged) wait = Math.max(wait, 4000);
      prevTurn = curTurn;
      await new Promise((resolve) => setTimeout(resolve, wait));
    }
    setState(final);
  }

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
      // 相手先行 等 で 初期 frame が 複数 ある場合 は 順次 再生
      const frames = next.frames ?? [];
      if (frames.length > 1) {
        setState(next); // 初期 board state を 一旦 表示
        await playFrames(next, frames, 2200);
      } else {
        setState(next);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function applyAction(
    action: HumanLegalAction,
    opts?: { keepSelection?: boolean },
  ) {
    if (!sessionId) return;
    if (applyInFlightRef.current) return; // 連打 / 連 drop 防止
    applyInFlightRef.current = true;
    setError(null);
    setBusy(true);
    if (!opts?.keepSelection) setSelection(null);
    setDrag(null);
    try {
      const next = await applyHumanAction(sessionId, action.idx);
      // AI ターン 等 で frame が 複数 あれば 順次 再生
      const frames = next.frames ?? [];
      if (frames.length > 1) {
        await playFrames(next, frames, 2200);
      } else {
        setState(next);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      applyInFlightRef.current = false;
      setBusy(false);
    }
  }

  async function handleChoiceSubmit(picks: number[]) {
    if (!sessionId) return;
    if (applyInFlightRef.current) return;
    applyInFlightRef.current = true;
    setError(null);
    setBusy(true);
    try {
      const next = await applyHumanChoice(sessionId, picks);
      const frames = next.frames ?? [];
      if (frames.length > 1) {
        await playFrames(next, frames, 2200);
      } else {
        setState(next);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      applyInFlightRef.current = false;
      setBusy(false);
    }
  }

  async function handleDefenseSubmit() {
    if (!sessionId) return;
    setError(null);
    setBusy(true);
    setDefenseClosing(true); // 確定 押下 で 即時 modal 視覚的 close
    try {
      const next = await applyHumanDefense(sessionId, blockerIid, counterIdxs);
      setState(next);
      setCounterIdxs([]);
      setBlockerIid(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setDefenseClosing(false); // 次 pending=defense なら modal 再 open される
      // 防御確定 完了 後、 used counter は 1 秒後 に 記録 clear (= 以降 通常 動作)
      setTimeout(() => setUsedCounterCardIds([]), 1500);
    }
  }

  async function handleEnd() {
    if (sessionId) {
      try {
        await endHumanMatch(sessionId);
      } catch {
        /* ignore */
      }
    }
    setState(null);
    router.push("/");
  }

  useEffect(() => {
    return () => {
      if (sessionId) {
        endHumanMatch(sessionId).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // ESC で 選択 / drag をキャンセル
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setSelection(null);
        setDrag(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // snapshot 差分 (= life delta / chara 退場 等) を hook で 追跡 し animation 用
  const snapForDiff = (state?.snapshot ?? null) as StateSnapshot | null;
  const frameDiff = useFrameDiff(snapForDiff);
  // 自分側 hand で 直近 ドロー idx を ハイライト
  const meHandLen =
    (snapForDiff?.players?.[state?.human_idx ?? 0]?.hand?.length) ?? 0;
  const recentDrawnIdxs = useRecentDrawnIdxs(
    frameDiff.handDelta[state?.human_idx ?? 0] ?? 0,
    meHandLen,
    frameDiff.eventTickId,
  );

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
      <div className="m-6 rounded border border-zinc-300 p-4 text-sm">
        snapshot 取得失敗
      </div>
    );
  }

  const isHumanTurn = state.turn_player_idx === state.human_idx;
  const isDefensePending = state.pending_kind === "defense";
  const isActionPending = state.pending_kind === "action";
  const isChoicePending = state.pending_kind === "choice";
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
    // AttachDonToCharacter は target_iid (= self chara) で index
    if (a.kind === "AttachDonToCharacter" && a.target_iid !== undefined) {
      const arr = actionsByIid.get(a.target_iid) ?? [];
      arr.push(a);
      actionsByIid.set(a.target_iid, arr);
    }
    // AttachDonToLeader は leader 自身に iid が無いので自リーダー iid で index
    if (a.kind === "AttachDonToLeader") {
      const leaderIid = me.leader.instance_id;
      const arr = actionsByIid.get(leaderIid) ?? [];
      arr.push(a);
      actionsByIid.set(leaderIid, arr);
    }
    // ActivateMain は source_iid (= 起動元 self chara) で index
    if (a.source_iid !== undefined) {
      const arr = actionsByIid.get(a.source_iid) ?? [];
      arr.push(a);
      actionsByIid.set(a.source_iid, arr);
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

  // === drop handler === //
  function handleDrop(target: DropTarget) {
    if (!drag) {
      setDrag(null);
      return;
    }
    // canAct false (= busy / AI turn 等) でも legal_actions に action が
    // あれば 試みる (= サーバ側 が validate)。 busy 中の applyAction は
    // applyInFlightRef で hard guard 済。
    let action: HumanLegalAction | undefined;
    if (drag.kind === "hand") {
      const acts = actionsByHand.get(drag.handIdx) ?? [];
      if (
        target.kind === "self_field" ||
        target.kind === "self_leader" ||
        target.kind === "self_chara"
      ) {
        action =
          acts.find((a) => a.kind === "PlayCharacter") ??
          acts.find((a) => a.kind === "PlayStage") ??
          acts.find((a) => a.kind === "PlayEvent");
      } else {
        action = acts.find((a) => a.kind === "PlayEvent");
      }
    } else if (drag.kind === "chara") {
      if (target.kind === "opp_leader") {
        action = state!.legal_actions.find(
          (a) => a.kind === "AttackLeader" && a.attacker_iid === drag.iid,
        );
      } else if (target.kind === "opp_chara") {
        action = state!.legal_actions.find(
          (a) =>
            a.kind === "AttackCharacter" &&
            a.attacker_iid === drag.iid &&
            a.target_iid === target.iid,
        );
      }
    } else if (drag.kind === "don") {
      const count = Math.max(1, drag.count);
      if (count > 1 && sessionId) {
        // 複数 DON: applyHumanAction を 直接 sequential 呼び、 各回 next の
        // legal_actions から 再 find (= 旧 state.legal_actions idx は 別 action
        // を 指す リスクある ため、 都度 最新 を 取得)。
        setDrag(null);
        if (applyInFlightRef.current) return;
        applyInFlightRef.current = true;
        setBusy(true);
        (async () => {
          try {
            let curLegal = state!.legal_actions;
            for (let k = 0; k < count; k++) {
              const a = curLegal.find((x) => {
                if (target.kind === "self_leader")
                  return x.kind === "AttachDonToLeader";
                if (target.kind === "self_chara")
                  return (
                    x.kind === "AttachDonToCharacter" &&
                    x.target_iid === target.iid
                  );
                return false;
              });
              if (!a) break;
              const next = await applyHumanAction(sessionId, a.idx);
              const fr = next.frames ?? [];
              if (fr.length > 1) {
                await playFrames(next, fr, 2200);
              } else {
                setState(next);
              }
              curLegal = next.legal_actions;
            }
          } catch (e) {
            setError(String(e));
          } finally {
            applyInFlightRef.current = false;
            setBusy(false);
          }
        })();
        return;
      }
      // 単発 (= count=1) 既存挙動
      if (target.kind === "self_leader") {
        action = state!.legal_actions.find(
          (a) => a.kind === "AttachDonToLeader",
        );
      } else if (target.kind === "self_chara") {
        action = state!.legal_actions.find(
          (a) =>
            a.kind === "AttachDonToCharacter" && a.target_iid === target.iid,
        );
      }
    } else if (drag.kind === "counter") {
      // 防御 中: 手札 counter idx を toggle で counterIdxs に追加 + 視覚 演出
      if (!counterIdxs.includes(drag.handIdx)) {
        const cardId = me.hand[drag.handIdx];
        const counterValues = (state?.pending_payload?.counter_values as
          | Record<string, number>
          | undefined) ?? null;
        const value = counterValues?.[String(drag.handIdx)] ?? 1000;
        setCounterIdxs([...counterIdxs, drag.handIdx]);
        if (cardId) {
          fireCounterPlay(cardId, value);
          // 防御確定 後 engine が trash に追加するが、 PlayedCardOverlay で
          // 「再演出」 されないよう に 使用 card_id を 記録
          setUsedCounterCardIds((prev) => [...prev, cardId]);
        }
      }
      setDrag(null);
      return;
    }
    setDrag(null);
    if (action) applyAction(action);
  }

  type SelectionAction = {
    action: HumanLegalAction;
    label: string;
    mode: "attack" | "apply";
  };

  function actionShortLabel(kind: string): string {
    switch (kind) {
      case "PlayCharacter":
        return "Deploy";
      case "PlayEvent":
        return "Use Event";
      case "PlayStage":
        return "Place Stage";
      case "AttachDonToLeader":
        return "ドン付与";
      case "AttachDonToCharacter":
        return "ドン付与";
      case "AttackLeader":
      case "AttackCharacter":
        return "Attack";
      case "ActivateMain":
        return "起動メイン";
      default:
        return kind;
    }
  }

  function getSelectionActions(): SelectionAction[] {
    if (!selection) return [];
    let acts: HumanLegalAction[] = [];
    if (selection.kind === "hand") {
      acts = actionsByHand.get(selection.handIdx) ?? [];
    } else if (selection.kind === "self_leader") {
      acts = actionsByIid.get(me.leader.instance_id) ?? [];
    } else if (selection.kind === "self_chara") {
      acts = actionsByIid.get(selection.iid) ?? [];
    }
    const result: SelectionAction[] = [];
    const seenKinds = new Set<string>();
    // Attack 系 は target 別 に 大量 に 存在 する ので 1 つ に 集約
    const attack = acts.find(
      (a) => a.kind === "AttackLeader" || a.kind === "AttackCharacter",
    );
    if (attack) {
      result.push({ action: attack, label: "Attack", mode: "attack" });
      seenKinds.add("Attack");
    }
    for (const a of acts) {
      if (a.kind === "AttackLeader" || a.kind === "AttackCharacter") continue;
      if (seenKinds.has(a.kind)) continue;
      seenKinds.add(a.kind);
      result.push({
        action: a,
        label: actionShortLabel(a.kind),
        mode: "apply",
      });
    }
    return result;
  }

  function handleSelectionActionClick(sa: SelectionAction) {
    if (sa.mode === "attack" && sa.action.attacker_iid !== undefined) {
      setSelection({
        kind: "attack_pending",
        attackerIid: sa.action.attacker_iid,
      });
      return;
    }
    // DON 付与 系 は 連続 付与 し やすい よう selection を 維持
    const keepSelection =
      sa.action.kind === "AttachDonToLeader" ||
      sa.action.kind === "AttachDonToCharacter";
    applyAction(sa.action, { keepSelection });
  }

  function cancelSelection() {
    setSelection(null);
  }

  const attackerIid =
    selection?.kind === "attack_pending" ? selection.attackerIid : null;

  // preview priority:
  //   trash modal hover > selection (= ロック) > hover > nothing
  // 選択中 は hover で 表示 を 変えない (= ただし トラッシュ閲覧中 は hover 優先)
  let previewCardId: string | null = null;
  let previewMeta:
    | {
        kind: "chara";
        cardId: string;
        name: string;
        power: number;
        attached_dons: number;
        rested: boolean;
        keywords: string[];
        isLeader: boolean;
      }
    | null = null;

  if (trashViewer && hovered?.kind === "hand") {
    previewCardId = hovered.cardId;
  } else if (trashViewer && hovered?.kind === "chara") {
    previewCardId = hovered.cardId;
    previewMeta = hovered;
  } else if (selection) {
    if (selection.kind === "hand") {
      previewCardId = me.hand[selection.handIdx] ?? null;
    } else if (selection.kind === "self_leader") {
      const ch = me.leader;
      previewCardId = ch.card_id;
      previewMeta = {
        kind: "chara",
        cardId: ch.card_id,
        name: ch.name,
        power: ch.power,
        attached_dons: ch.attached_dons,
        rested: ch.rested,
        keywords: ch.keywords,
        isLeader: true,
      };
    } else if (selection.kind === "self_chara") {
      const ch = me.characters.find((c) => c.instance_id === selection.iid);
      if (ch) {
        previewCardId = ch.card_id;
        previewMeta = {
          kind: "chara",
          cardId: ch.card_id,
          name: ch.name,
          power: ch.power,
          attached_dons: ch.attached_dons,
          rested: ch.rested,
          keywords: ch.keywords,
          isLeader: false,
        };
      }
    } else if (selection.kind === "attack_pending") {
      const isLeaderAttacker =
        me.leader.instance_id === selection.attackerIid;
      const attacker = isLeaderAttacker
        ? me.leader
        : me.characters.find((c) => c.instance_id === selection.attackerIid);
      if (attacker) {
        previewCardId = attacker.card_id;
        previewMeta = {
          kind: "chara",
          cardId: attacker.card_id,
          name: attacker.name,
          power: attacker.power,
          attached_dons: attacker.attached_dons,
          rested: attacker.rested,
          keywords: attacker.keywords,
          isLeader: isLeaderAttacker,
        };
      }
    }
  } else if (hovered?.kind === "hand") {
    previewCardId = hovered.cardId;
  } else if (hovered?.kind === "chara") {
    previewCardId = hovered.cardId;
    previewMeta = hovered;
  }

  return (
    <div
      ref={boardRef}
      onMouseMove={(e) => {
        if (attackerIid !== null && boardRef.current) {
          const r = boardRef.current.getBoundingClientRect();
          setMousePos({ x: e.clientX - r.left, y: e.clientY - r.top });
        }
      }}
      onClick={() => {
        // 背景 (= ボタン以外) クリックで 選択 を 解除
        // ボタン clicks は 各 ハンドラ で stopPropagation 済
        if (selection) setSelection(null);
      }}
      className="relative flex h-[100dvh] w-full flex-col gap-2 overflow-hidden p-2"
      style={{
        backgroundImage:
          "radial-gradient(ellipse at center, #6b4423 0%, #3d2817 100%)",
      }}
    >
      {/* 右上 対戦終了 ボタン (= 常時表示、 押下で home へ) */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          handleEnd();
        }}
        className="absolute top-2 right-2 z-40 rounded-lg border border-rose-400 bg-rose-700/90 px-4 py-2 text-sm font-bold text-white shadow-lg backdrop-blur hover:bg-rose-600"
      >
        対戦終了
      </button>

      {error && (
        <div className="shrink-0 rounded border border-red-500 bg-red-950/80 p-2 text-sm text-red-100">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 gap-2 overflow-hidden">
        {/* 左 サイド: opp info → log → self stats → 自手札 */}
        <div className="flex min-w-[280px] flex-1 min-h-0 flex-col gap-2">
          <OpponentInfoPanel
            opp={opp}
            reveal={state.game_over}
            onHover={setHovered}
          />
          <LogSidebar log={state.log} aiIdx={state.ai_idx} />
          {/* 自分側 (= 数字 + 手札) を 1 つの emerald エリア に まとめる */}
          <div className="shrink-0 rounded border border-emerald-400/50 bg-emerald-950/40 p-2">
            <StatBadge player={me} label="YOU" color="bg-emerald-700 text-white" />
            <div className="mt-2">
              <HandRow
                hand={me.hand}
                actionsByHand={actionsByHand}
                canAct={canAct}
                selectedIdx={
                  selection?.kind === "hand" ? selection.handIdx : null
                }
                draggingHandIdx={
                  drag?.kind === "hand" || drag?.kind === "counter"
                    ? drag.handIdx
                    : null
                }
                recentDrawnIdxs={recentDrawnIdxs}
                counterIdxsAvail={
                  isDefensePending && state.pending_payload
                    ? (state.pending_payload.legal_counter_card_idxs as
                        | number[]
                        | undefined)
                    : undefined
                }
                counterSelectedIdxs={isDefensePending ? counterIdxs : undefined}
                onCounterDragStart={(handIdx) =>
                  setDrag({ kind: "counter", handIdx })
                }
                onClick={clickHandCard}
                onHover={setHovered}
                onDragStart={(handIdx) => {
                  const acts = actionsByHand.get(handIdx) ?? [];
                  let handKind: "CHARACTER" | "EVENT" | "STAGE" = "CHARACTER";
                  for (const a of acts) {
                    if (a.kind === "PlayCharacter") handKind = "CHARACTER";
                    else if (a.kind === "PlayEvent") handKind = "EVENT";
                    else if (a.kind === "PlayStage") handKind = "STAGE";
                  }
                  setDrag({ kind: "hand", handIdx, handKind });
                }}
                onDragEnd={() => setDrag(null)}
              />
            </div>
          </div>
        </div>

        {/* 中央: マット (= 5 横向き chara が 収まる固定幅) */}
        <div className="relative flex min-h-0 w-[780px] shrink-0 flex-col gap-2">
          {/* ライフ 変化 flash overlay (= 自/相手 別 side) */}
          <LifeFlashOverlay
            delta={frameDiff.lifeDelta[state.ai_idx]}
            side="opp"
            tickId={frameDiff.eventTickId * 2}
          />
          <LifeFlashOverlay
            delta={frameDiff.lifeDelta[state.human_idx]}
            side="me"
            tickId={frameDiff.eventTickId * 2 + 1}
          />
          {/* 場を離れた chara の ghost 表示 */}
          <LeftCharaGhostList
            leftCharas={frameDiff.leftCharas[state.ai_idx]}
            side="opp"
            tickId={frameDiff.eventTickId * 2}
          />
          <LeftCharaGhostList
            leftCharas={frameDiff.leftCharas[state.human_idx]}
            side="me"
            tickId={frameDiff.eventTickId * 2 + 1}
          />

          {/* 相手 マット */}
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
            drag={drag}
            onDropTarget={handleDrop}
            onHover={setHovered}
            onTrashClick={() => setTrashViewer("opp")}
            lifeDamageTickId={
              frameDiff.lifeDelta[state.ai_idx] > 0
                ? frameDiff.eventTickId
                : undefined
            }
          />

          <div className="h-px shrink-0 bg-amber-100/30" />

          {/* 自分 マット */}
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
            drag={drag}
            onDropTarget={handleDrop}
            onHover={setHovered}
            onDragStart={(p) => setDrag(p)}
            onDragEnd={() => setDrag(null)}
            onTrashClick={() => setTrashViewer("me")}
            lifeDamageTickId={
              frameDiff.lifeDelta[state.human_idx] > 0
                ? frameDiff.eventTickId
                : undefined
            }
          />
        </div>

        {/* 右 サイド: hover preview + action panel (+ 防御 mode) */}
        <RightPanel
          previewCardId={previewCardId}
          previewMeta={previewMeta}
          canAct={canAct}
          selection={selection}
          availableActions={getSelectionActions()}
          onActionClick={handleSelectionActionClick}
          onCancel={cancelSelection}
          endPhaseAction={endPhaseAction}
          onEndPhase={() => endPhaseAction && applyAction(endPhaseAction)}
          isHumanTurn={isHumanTurn}
          isDefensePending={isDefensePending && !defenseClosing}
          gameOver={state.game_over}
          winner={state.winner}
          humanIdx={state.human_idx}
          aiIdx={state.ai_idx}
          turn={state.turn}
          phase={state.phase}
          defensePayload={state.pending_payload}
          defenseMe={me}
          defenseBlockerIid={blockerIid}
          defenseSetBlockerIid={setBlockerIid}
          defenseCounterIdxs={counterIdxs}
          defenseSetCounterIdxs={setCounterIdxs}
          defenseOnSubmit={handleDefenseSubmit}
          defenseOnHover={setHovered}
          defenseBusy={busy}
        />
      </div>

      {/* 防御 panel は 右 サイド に embed したので overlay は 廃止 */}

      {/* 攻撃 矢印 SVG (= ユーザ操作 中) */}
      {attackerIid !== null && mousePos && (
        <AttackArrow attackerIid={attackerIid} mousePos={mousePos} />
      )}

      {/* 攻撃 ビーム (= snapshot.event 拾って 一瞬 流す、 AI/自分 共通) */}
      {snap.event && (
        <AttackBeamOverlay
          attackerIid={snap.event.attacker_iid}
          targetIid={snap.event.target_iid}
          boardRef={boardRef}
          tickId={frameDiff.eventTickId}
        />
      )}

      {/* 攻撃 矢印 (= 1.3 秒、 「何を狙ってるか」 を 明示) */}
      {snap.event && (
        <AttackTargetArrowOverlay
          attackerIid={snap.event.attacker_iid}
          targetIid={snap.event.target_iid}
          boardRef={boardRef}
          tickId={frameDiff.eventTickId}
        />
      )}

      {/* 防御 pending 中 の attacker→target 矢印 (= 持続表示、 カウンター 判断 用) */}
      {isDefensePending && state.pending_payload && (
        <AttackTargetArrowOverlay
          attackerIid={
            typeof state.pending_payload.attacker_iid === "number"
              ? state.pending_payload.attacker_iid
              : null
          }
          targetIid={
            state.pending_payload.is_leader_attack
              ? me.leader.instance_id
              : typeof state.pending_payload.target_iid === "number"
                ? state.pending_payload.target_iid
                : null
          }
          boardRef={boardRef}
          tickId={frameDiff.eventTickId}
          persistent={true}
        />
      )}

      {/* 効果 log toast (= 「効果:」 行 を 中央上部 で 1.6秒 表示) */}
      <EffectToastOverlay log={state.log} />

      {/* 手札から使用 された カード を 中央 で 大型表示 → trash 方向 slide-fade */}
      <PlayedCardOverlay
        trashAddedMe={frameDiff.trashAdded[state.human_idx]}
        trashAddedOpp={frameDiff.trashAdded[state.ai_idx]}
        leftCharasMe={frameDiff.leftCharas[state.human_idx]}
        leftCharasOpp={frameDiff.leftCharas[state.ai_idx]}
        excludeMeCardIds={usedCounterCardIds}
        tickId={frameDiff.eventTickId}
      />

      {/* ドロー 演出 (= デッキ位置 → 手札方向 へ 裏面カード slide)。
          ライフ削り frame では DrawCardOverlay 抑制 (= ライフ→手札 と デッキ→手札 が
          別 意味、 LifeFlash で 代替) */}
      <DrawCardOverlay
        handDeltaMe={frameDiff.handDelta[state.human_idx]}
        handDeltaOpp={frameDiff.handDelta[state.ai_idx]}
        lifeDeltaMe={frameDiff.lifeDelta[state.human_idx]}
        lifeDeltaOpp={frameDiff.lifeDelta[state.ai_idx]}
        tickId={frameDiff.eventTickId}
        boardRef={boardRef}
      />

      {/* counter ドロップ 時 「+N」 popup + カード trash slide 演出 */}
      <CounterPlayOverlay />

      {/* ターン 切替 banner (= YOUR TURN / OPPONENT TURN 大型) */}
      <TurnBannerOverlay
        turnPlayerIdx={state.turn_player_idx}
        humanIdx={state.human_idx}
        hasMulliganPending={
          isChoicePending &&
          state.pending_payload?.kind === "mulligan_confirm"
        }
        pendingKind={state.pending_kind}
      />

      {/* ゲーム終了 大型 WIN/LOSE/DRAW 表示 */}
      {state.game_over && (
        <div className="pointer-events-none absolute inset-0 z-[55] flex items-center justify-center">
          <motion.div
            initial={{ opacity: 0, scale: 0.3, y: -50 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
            className={
              "rounded-2xl border-4 px-16 py-10 text-center shadow-2xl backdrop-blur " +
              (state.winner === state.human_idx
                ? "border-emerald-300 bg-emerald-900/80"
                : state.winner === state.ai_idx
                  ? "border-rose-300 bg-rose-900/80"
                  : "border-amber-300 bg-amber-900/80")
            }
          >
            <div
              className={
                "text-7xl font-extrabold drop-shadow-[0_0_30px_rgba(255,255,255,0.6)] " +
                (state.winner === state.human_idx
                  ? "text-emerald-200"
                  : state.winner === state.ai_idx
                    ? "text-rose-200"
                    : "text-amber-200")
              }
            >
              {state.winner === state.human_idx
                ? "YOU WIN"
                : state.winner === state.ai_idx
                  ? "YOU LOSE"
                  : "DRAW"}
            </div>
            <div className="mt-3 text-base text-zinc-200">
              T{state.turn} で 試合 終了
            </div>
          </motion.div>
        </div>
      )}

      {/* interactive 選択 modal (= kind 別に dispatch) */}
      {isChoicePending && state.pending_payload && (
        state.pending_payload.kind === "target_pick" ? (
          <TargetPickModal
            payload={state.pending_payload}
            onSubmit={handleChoiceSubmit}
            onHover={setHovered}
            busy={busy}
          />
        ) : state.pending_payload.kind === "scry_life_reorder" ? (
          <ScryLifeReorderModal
            payload={state.pending_payload}
            onSubmit={handleChoiceSubmit}
            onHover={setHovered}
            busy={busy}
          />
        ) : state.pending_payload.kind === "reveal_top_play_confirm" ? (
          <RevealTopPlayConfirmModal
            payload={state.pending_payload}
            onSubmit={handleChoiceSubmit}
            onHover={setHovered}
            busy={busy}
          />
        ) : state.pending_payload.kind === "option_pick" ? (
          <OptionPickModal
            payload={state.pending_payload}
            onSubmit={handleChoiceSubmit}
            busy={busy}
          />
        ) : state.pending_payload.kind === "mulligan_confirm" ? (
          <MulliganConfirmModal
            payload={state.pending_payload}
            onSubmit={handleChoiceSubmit}
            onHover={setHovered}
            busy={busy}
          />
        ) : state.pending_payload.kind === "life_taken_choice" ? (
          <LifeTakenChoiceModal
            payload={state.pending_payload}
            onSubmit={handleChoiceSubmit}
            busy={busy}
          />
        ) : (
          <SearchChoiceModal
            payload={state.pending_payload}
            onSubmit={handleChoiceSubmit}
            onHover={setHovered}
            busy={busy}
          />
        )
      )}

      {/* トラッシュ閲覧 modal (= 右パネル除いて 中央+左 をカバー、 hover は右パネル preview へ) */}
      {trashViewer && (
        <TrashViewer
          side={trashViewer}
          cards={trashViewer === "me" ? me.trash : opp.trash}
          onClose={() => setTrashViewer(null)}
          onHover={setHovered}
        />
      )}
    </div>
  );
}

// ========================================================================== //
// StartPanel (= heading 内蔵)
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
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-6">
      <div className="flex items-center gap-3">
        <Link
          href="/"
          className="rounded border border-zinc-300 px-3 py-1 text-sm text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          ← ホームへ
        </Link>
      </div>
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          人間 vs AI 対戦 (大会練習)
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          GoalDirectedAI と 実際に 対戦 します。 手札 を 自フィールド に
          ドラッグ で deploy、 自キャラ を 相手 に ドラッグ で attack、
          DON を 自リーダー/キャラ に ドラッグ で attach。
        </p>
      </header>
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
            {busy ? "開始中..." : "対戦開始"}
          </button>
        </div>
        {error && (
          <div className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

// ========================================================================== //
// PlayerMat
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
  drag,
  onDropTarget,
  onHover,
  onDragStart,
  onDragEnd,
  onTrashClick,
  lifeDamageTickId,
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
  drag: DragPayload | null;
  onDropTarget: (t: DropTarget) => void;
  onHover: (h: HoverInfo) => void;
  onDragStart?: (p: DragPayload) => void;
  onDragEnd?: () => void;
  onTrashClick: () => void;
  lifeDamageTickId?: number;
}) {
  // どの drag を 受け入れる か
  const acceptHandDrop = isMe && drag?.kind === "hand";
  const acceptDonDrop = isMe && drag?.kind === "don";
  const acceptAttackDrop = !isMe && drag?.kind === "chara";
  const acceptCounterDrop = isMe && drag?.kind === "counter";

  function matDragOver(e: React.DragEvent) {
    if (acceptHandDrop || acceptCounterDrop) e.preventDefault();
  }
  function matDrop(e: React.DragEvent) {
    if (acceptHandDrop) {
      e.preventDefault();
      onDropTarget({ kind: "self_field" });
    } else if (acceptCounterDrop && drag?.kind === "counter") {
      e.preventDefault();
      onDropTarget({ kind: "self_counter", handIdx: drag.handIdx });
    }
  }

  return (
    <div
      onDragOver={matDragOver}
      onDrop={matDrop}
      className={
        "relative flex min-h-0 flex-1 rounded-lg border-2 p-2 transition " +
        // 公式 鏡像 レイアウト: 自分 mat は Life/DON 左、 相手 mat は Life/DON 右
        (isMe ? "" : "flex-row-reverse ") +
        (isMe
          ? "border-emerald-400/60 bg-emerald-950/40"
          : "border-rose-400/60 bg-rose-950/40") +
        (acceptHandDrop || acceptDonDrop || acceptAttackDrop || acceptCounterDrop
          ? " ring-4 ring-yellow-400/60"
          : "")
      }
    >
      {/* ライフ + DON デッキ: 自分=左、 相手=右 (= flex-row-reverse 効果)。
          縦並び は 相手 mat で flex-col-reverse (= DON Deck が opp の 奥側) */}
      <div
        className={
          "flex shrink-0 items-center justify-between gap-2 " +
          (isMe ? "flex-col pr-3" : "flex-col-reverse pl-3")
        }
      >
        <div className="text-xs font-bold text-zinc-100">
          LIFE × {player.life_count}
        </div>
        <div data-life-side={isMe ? "me" : "opp"}>
          <LifeStack
            count={player.life_count}
            damageTickId={lifeDamageTickId}
          />
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <div className="text-xs text-zinc-300">DON Deck</div>
          <div className="relative">
            <img
              src="/assets/don.png"
              alt="DON"
              className="h-14 w-10 rounded shadow"
            />
            <span className="absolute -bottom-1 -right-1 rounded bg-amber-600 px-1.5 text-[11px] font-bold text-white">
              {player.don_remaining_in_deck}
            </span>
          </div>
        </div>
      </div>

      {/* 中央: フィールド */}
      <div className="flex min-h-0 flex-1 flex-col justify-between gap-1">
        {/* 上段: 自分ならキャラ、 相手なら DON 表示 */}
        {!isMe ? (
          <DonRow
            donActive={player.don_active}
            donRested={player.don_rested}
            donTotal={player.don_total}
            isMe={false}
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
            isMe={true}
            drag={drag}
            onDropTarget={onDropTarget}
            onHover={onHover}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
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
          drag={drag}
          onDropTarget={onDropTarget}
          onHover={onHover}
          onTrashClick={onTrashClick}
        />

        {/* 下段: 相手ならキャラ (= 仕切り接触)、 自分なら DON (= 手前) */}
        {!isMe ? (
          <CharacterRow
            chars={player.characters}
            attackerIid={attackerIid}
            canSelectAsTarget={canSelectAsTarget}
            canAct={false}
            actionsByIid={actionsByIid}
            onChara={onCharaClick}
            selection={selection}
            isMe={false}
            drag={drag}
            onDropTarget={onDropTarget}
            onHover={onHover}
          />
        ) : (
          <DonRow
            donActive={player.don_active}
            donRested={player.don_rested}
            donTotal={player.don_total}
            isMe={true}
            onDragStart={(count) =>
              onDragStart?.({ kind: "don", count })
            }
            onDragEnd={onDragEnd}
          />
        )}
      </div>

    </div>
  );
}

function LifeStack({
  count,
  damageTickId,
}: {
  count: number;
  damageTickId?: number;
}) {
  // 横向き レイアウト 中で 縦横比 5:7 を 保持 する ため、
  // 縦長 image を rotate-90 で 横倒し に する (= wrapper は landscape、 中身 は portrait)。
  // 高さ 固定 (= h-40) で count 変動 で 全体 layout が 動かない。
  // damageTickId が 変わる たび に shake animation を 発火 (= ダメージ食らった 演出)。
  return (
    <motion.div
      key={damageTickId ?? 0}
      animate={
        damageTickId !== undefined && damageTickId > 0
          ? {
              x: [0, -10, 8, -6, 4, -2, 0],
              rotate: [0, -2, 2, -1, 1, 0],
            }
          : { x: 0, rotate: 0 }
      }
      transition={{ duration: 0.45 }}
      className="relative flex h-40 w-20 flex-col items-center justify-end"
    >
      {count === 0 ? (
        <div className="my-auto rounded border border-red-500 px-3 py-1 text-xs text-red-300">
          0
        </div>
      ) : (
        Array.from({ length: count }).map((_, i) => (
          <div
            key={i}
            style={{ marginTop: i === 0 ? 0 : -28 }}
            className="relative h-14 w-20"
          >
            <img
              src="/assets/ura.png"
              alt="life"
              className="absolute left-1/2 top-1/2 h-20 w-14 -translate-x-1/2 -translate-y-1/2 rotate-90 rounded shadow ring-1 ring-amber-100/20"
            />
          </div>
        ))
      )}
    </motion.div>
  );
}

function DonRow({
  donActive,
  donRested,
  donTotal,
  isMe,
  onDragStart,
  onDragEnd,
}: {
  donActive: number;
  donRested: number;
  donTotal: number;
  isMe: boolean;
  onDragStart?: (count: number) => void;
  onDragEnd?: () => void;
}) {
  const totalShown = Math.min(donTotal, 12);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const lastClickedRef = useRef<number | null>(null);

  function handleDonClick(i: number, e: React.MouseEvent) {
    e.stopPropagation();
    if (!isMe) return;
    if (e.shiftKey && lastClickedRef.current !== null) {
      // 範囲選択
      const a = lastClickedRef.current;
      const b = i;
      const lo = Math.min(a, b);
      const hi = Math.max(a, b);
      const next = new Set<number>();
      for (let k = lo; k <= hi; k++) next.add(k);
      setSelected(next);
    } else if (e.ctrlKey || e.metaKey) {
      // 個別 toggle
      const next = new Set(selected);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      setSelected(next);
      lastClickedRef.current = i;
    } else {
      // 通常 click: 単一 選択
      setSelected(new Set([i]));
      lastClickedRef.current = i;
    }
  }
  return (
    <div className="flex h-16 shrink-0 items-center gap-1 rounded bg-black/30 px-3">
      <span className="text-xs font-bold text-zinc-200">DON</span>
      <div className="flex items-center gap-1 overflow-hidden">
        {Array.from({ length: donActive }).map((_, i) => {
          const isSel = selected.has(i);
          return (
            <button
              key={`a-${i}`}
              type="button"
              draggable={isMe && donActive > 0}
              onClick={(e) => handleDonClick(i, e)}
              onDragStart={() => {
                // 選択中 なら 選択数、 そうでなければ 1 枚 で drag
                const count = isSel && selected.size > 0 ? selected.size : 1;
                onDragStart?.(count);
              }}
              onDragEnd={() => {
                onDragEnd?.();
                setSelected(new Set());
                lastClickedRef.current = null;
              }}
              className={
                "h-10 w-7 rounded transition " +
                (isSel
                  ? "ring-4 ring-cyan-300 -translate-y-1 drop-shadow-[0_0_10px_rgba(103,232,249,0.85)]"
                  : "ring-1 ring-amber-400 ") +
                (isMe ? "cursor-grab active:cursor-grabbing" : "cursor-default")
              }
              title={
                isMe
                  ? "クリック=選択 / Shift+クリック=範囲選択 / Ctrl+クリック=個別 追加。 ドラッグで attach"
                  : "DON"
              }
            >
              <img
                src="/assets/don.png"
                alt="DON"
                className="h-full w-full rounded shadow"
                draggable={false}
              />
            </button>
          );
        })}
        {donRested > 0 && (
          <div className="flex">
            {Array.from({ length: donRested }).map((_, i) => (
              <div
                key={`r-${i}`}
                style={{ marginLeft: i === 0 ? 0 : -20 }}
                className="relative h-7 w-10"
              >
                <img
                  src="/assets/don.png"
                  alt="DON rested"
                  className="absolute left-1/2 top-1/2 h-10 w-7 -translate-x-1/2 -translate-y-1/2 rotate-90 rounded opacity-70 shadow"
                />
              </div>
            ))}
          </div>
        )}
        {Array.from({ length: Math.max(0, totalShown - donActive - donRested) }).map(
          (_, i) => (
            <div key={`p-${i}`} className="h-10 w-7 rounded bg-zinc-700/40" />
          ),
        )}
      </div>
      <span className="ml-auto text-xs font-semibold text-amber-200">
        {selected.size > 1 && (
          <span className="mr-2 rounded bg-cyan-600 px-1.5 py-0.5 text-[11px] text-white">
            {selected.size}枚 選択
          </span>
        )}
        <AnimatedNumber value={donActive} flashColorClass="text-emerald-300" />A
        {" / "}
        <AnimatedNumber value={donRested} flashColorClass="text-zinc-400" />R
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
  drag,
  onDropTarget,
  onHover,
  onTrashClick,
}: {
  player: PlayerSnapshot;
  isMe: boolean;
  isLeaderTarget: boolean;
  isLeaderActable: boolean;
  isLeaderSelected: boolean;
  isLeaderAttacker: boolean;
  onLeaderClick: () => void;
  drag: DragPayload | null;
  onDropTarget: (t: DropTarget) => void;
  onHover: (h: HoverInfo) => void;
  onTrashClick: () => void;
}) {
  // Leader drop 受け入れ:
  //  自リーダー: DON drag / hand drag (= PlayStage 等)
  //  相手リーダー: chara drag (= AttackLeader)
  const acceptOnLeader = isMe
    ? drag?.kind === "don" || drag?.kind === "hand"
    : drag?.kind === "chara";

  function leaderDragOver(e: React.DragEvent) {
    if (acceptOnLeader) e.preventDefault();
  }
  function leaderDrop(e: React.DragEvent) {
    if (!acceptOnLeader) return;
    e.preventDefault();
    onDropTarget(isMe ? { kind: "self_leader" } : { kind: "opp_leader" });
  }
  return (
    <div className="flex shrink-0 items-center justify-center gap-3 py-1">
      <div
        data-iid={player.leader.instance_id}
        onDragOver={leaderDragOver}
        onDrop={leaderDrop}
      >
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
          onHover={onHover}
          draggable={false}
          dropHint={acceptOnLeader}
        />
      </div>
      <div className="flex flex-col items-center gap-0.5">
        <div className="text-[10px] font-semibold text-zinc-300">STAGE</div>
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
            onHover={onHover}
            draggable={false}
          />
        ) : (
          <div className="flex h-32 w-24 items-center justify-center rounded border border-dashed border-zinc-600 text-xs text-zinc-500">
            empty
          </div>
        )}
      </div>
      <div className="flex flex-col items-center gap-0.5">
        <div className="text-xs font-semibold text-zinc-300">DECK</div>
        <div className="relative" data-deck-side={isMe ? "me" : "opp"}>
          <img
            src="/assets/ura.png"
            alt="deck"
            className="h-32 w-24 rounded shadow"
          />
          <span className="absolute -bottom-1 -right-1 rounded bg-zinc-900 px-1.5 text-xs font-bold text-white">
            {player.deck_count}
          </span>
        </div>
      </div>
      <div className="flex flex-col items-center gap-0.5">
        <div className="text-xs font-semibold text-zinc-300">TRASH</div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            if (player.trash_count > 0) onTrashClick();
          }}
          disabled={player.trash_count === 0}
          className={
            "relative h-32 w-24 rounded border border-dashed border-zinc-600 transition " +
            (player.trash_count > 0
              ? "cursor-pointer bg-zinc-700/40 hover:border-emerald-400 hover:bg-zinc-700/60"
              : "cursor-default")
          }
          title={
            player.trash_count > 0
              ? `${player.trash_count} 枚 - clickで閲覧`
              : "空"
          }
        >
          {player.trash.length > 0 && (
            <img
              src={`/cards/${player.trash[player.trash.length - 1]}.png`}
              alt="top trash"
              className="absolute inset-0 h-full w-full rounded object-cover opacity-80"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          )}
          <span className="absolute bottom-0 right-0 rounded bg-zinc-900 px-1.5 text-xs font-bold text-white">
            {player.trash_count}
          </span>
        </button>
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
  isMe,
  drag,
  onDropTarget,
  onHover,
  onDragStart,
  onDragEnd,
}: {
  chars: CharSnapshot[];
  attackerIid: number | null;
  canSelectAsTarget: boolean;
  canAct: boolean;
  actionsByIid: Map<number, HumanLegalAction[]>;
  onChara: (iid: number) => void;
  selection?: Selection;
  isMe: boolean;
  drag: DragPayload | null;
  onDropTarget: (t: DropTarget) => void;
  onHover: (h: HoverInfo) => void;
  onDragStart?: (p: DragPayload) => void;
  onDragEnd?: () => void;
}) {
  const slots: (CharSnapshot | null)[] = [...chars];
  while (slots.length < 5) slots.push(null);
  return (
    <div className="flex shrink-0 items-center justify-center gap-x-10 py-1">
      <AnimatePresence mode="popLayout" initial={false}>
        {slots.map((c, i) => {
          if (!c) {
            return (
              <div
                key={`slot-${i}`}
                className={
                  "h-32 w-24 rounded border border-dashed " +
                  // キャラ slot の 黄色 hint は CHARACTER drag の時のみ。
                  // EVENT / STAGE は 場 ではなく leader へ drop なので 通常表示。
                  (isMe &&
                  drag?.kind === "hand" &&
                  drag.handKind === "CHARACTER"
                    ? "border-yellow-400 bg-yellow-900/30"
                    : "border-zinc-600/50")
                }
                data-iid="empty"
                onDragOver={(e) => {
                  if (
                    isMe &&
                    drag?.kind === "hand" &&
                    drag.handKind === "CHARACTER"
                  )
                    e.preventDefault();
                }}
                onDrop={(e) => {
                  if (
                    !isMe ||
                    drag?.kind !== "hand" ||
                    drag.handKind !== "CHARACTER"
                  )
                    return;
                  e.preventDefault();
                  onDropTarget({ kind: "self_field" });
                }}
              />
            );
          }
          const isAttacker = attackerIid === c.instance_id;
          const isActable =
            canAct && (actionsByIid.get(c.instance_id)?.length ?? 0) > 0;
          const isSelected =
            selection?.kind === "self_chara" && selection.iid === c.instance_id;

          // Drop target:
          //  自キャラ: DON drag (= AttachDonToCharacter)
          //  相手キャラ: chara drag (= AttackCharacter)
          const acceptOnThis = isMe
            ? drag?.kind === "don"
            : drag?.kind === "chara";

          // Draggable:
          //  自キャラ で attack action あれば draggable
          const isAttackSrc =
            isMe &&
            canAct &&
            (actionsByIid.get(c.instance_id) ?? []).some(
              (a) =>
                a.kind === "AttackLeader" || a.kind === "AttackCharacter",
            );

          return (
            <motion.div
              key={c.instance_id}
              data-iid={c.instance_id}
              layoutId={`chara-${c.instance_id}`}
              initial={{ opacity: 0, scale: 0.6, y: isMe ? 40 : -40 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.4, y: isMe ? 60 : -60, rotate: 8 }}
              transition={{
                type: "spring",
                stiffness: 320,
                damping: 26,
                opacity: { duration: 0.25 },
              }}
              onDragOver={(e) => {
                if (acceptOnThis) e.preventDefault();
              }}
              onDrop={(e) => {
                if (!acceptOnThis) return;
                e.preventDefault();
                onDropTarget(
                  isMe
                    ? { kind: "self_chara", iid: c.instance_id }
                    : { kind: "opp_chara", iid: c.instance_id },
                );
              }}
            >
              <CharCard
                ch={c}
                isLeader={false}
                isMine={isMe}
                isAttacker={isAttacker}
                isTarget={canSelectAsTarget}
                isActable={isActable}
                isSelected={isSelected}
                onClick={() => onChara(c.instance_id)}
                size="small"
                onHover={onHover}
                draggable={isAttackSrc}
                onDragStart={
                  isAttackSrc
                    ? () => onDragStart?.({ kind: "chara", iid: c.instance_id })
                    : undefined
                }
                onDragEnd={onDragEnd}
                dropHint={acceptOnThis}
              />
            </motion.div>
          );
        })}
      </AnimatePresence>
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
  onHover,
  draggable,
  onDragStart,
  onDragEnd,
  dropHint,
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
  onHover: (h: HoverInfo) => void;
  draggable?: boolean;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  dropHint?: boolean;
}) {
  const dim = size === "leader" ? "h-40 w-28" : "h-32 w-24";
  const ringClass = isSelected
    ? "ring-4 ring-yellow-400 ring-offset-2 ring-offset-amber-950"
    : isAttacker
      ? "ring-4 ring-orange-500 ring-offset-2 ring-offset-amber-950 animate-pulse"
      : isTarget
        ? "ring-2 ring-rose-500 hover:ring-rose-400 hover:ring-4"
        : isActable
          ? "ring-2 ring-emerald-400 hover:ring-emerald-300"
          : dropHint
            ? "ring-2 ring-yellow-400"
            : "ring-1 ring-zinc-700";
  const cursor =
    draggable
      ? "cursor-grab active:cursor-grabbing"
      : isActable || isTarget
        ? "cursor-pointer"
        : "cursor-default";
  return (
    <button
      type="button"
      data-iid={ch.instance_id}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      draggable={draggable}
      onDragStart={() => onDragStart?.()}
      onDragEnd={() => onDragEnd?.()}
      onMouseEnter={() =>
        onHover({
          kind: "chara",
          cardId: ch.card_id,
          name: ch.name,
          power: ch.power,
          attached_dons: ch.attached_dons,
          rested: ch.rested,
          keywords: ch.keywords,
          isLeader,
        })
      }
      onMouseLeave={() => onHover(null)}
      className={`group relative inline-block ${cursor} transition`}
      title={ch.name}
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
      <span className="absolute top-0 left-0 rounded-br bg-black/80 px-1 text-xs font-bold text-white">
        {ch.power}
      </span>
      {ch.attached_dons > 0 && (
        <span className="absolute bottom-0 right-0 rounded-tl bg-amber-600 px-1 text-[11px] font-bold text-white">
          +{ch.attached_dons}d
        </span>
      )}
      {ch.summoning_sickness && !isLeader && (
        <span className="absolute top-0 right-0 rounded-bl bg-blue-600 px-1 text-[10px] text-white">
          zZ
        </span>
      )}
      {ch.keywords.length > 0 && (
        <div className="absolute bottom-0 left-0 flex gap-0.5">
          {ch.keywords.map((k) => (
            <span
              key={k}
              className="rounded-tr bg-zinc-900/90 px-1 text-[10px] font-bold text-white"
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
// 手札 row (= overlapping fan、 hover で 持ち上げ)
// ========================================================================== //

function HandRow({
  hand,
  actionsByHand,
  canAct,
  selectedIdx,
  draggingHandIdx,
  recentDrawnIdxs,
  counterIdxsAvail,
  counterSelectedIdxs,
  onCounterDragStart,
  onClick,
  onHover,
  onDragStart,
  onDragEnd,
}: {
  hand: string[];
  actionsByHand: Map<number, HumanLegalAction[]>;
  canAct: boolean;
  selectedIdx: number | null;
  draggingHandIdx: number | null;
  recentDrawnIdxs?: Set<number>;
  counterIdxsAvail?: number[];
  counterSelectedIdxs?: number[];
  onCounterDragStart?: (handIdx: number) => void;
  onClick: (idx: number) => void;
  onHover: (h: HoverInfo) => void;
  onDragStart: (handIdx: number) => void;
  onDragEnd: () => void;
}) {
  // overlap 量 は 枚数 と 横幅 に 応じて 自動調整 (= card 幅 ~ 137px @ h-48)
  const overlap = hand.length <= 6 ? 76 : hand.length <= 9 ? 96 : 112;
  return (
    <div
      data-hand-side="me"
      className="relative flex h-24 shrink-0 items-start justify-center overflow-visible"
    >
      <div className="flex shrink-0 items-start">
        {hand.map((cardId, i) => {
          const playable = canAct && (actionsByHand.get(i)?.length ?? 0) > 0;
          const isCounterAvail = !!counterIdxsAvail?.includes(i);
          const isCounterSelected = !!counterSelectedIdxs?.includes(i);
          const selected = selectedIdx === i;
          const dragging = draggingHandIdx === i;
          const isRecentDrawn = !!recentDrawnIdxs?.has(i);
          const ring = isCounterSelected
            ? "ring-4 ring-amber-400 drop-shadow-[0_0_14px_rgba(251,191,36,0.85)]"
            : isCounterAvail
              ? "ring-2 ring-amber-500 hover:ring-amber-300"
              : isRecentDrawn
                ? "ring-4 ring-cyan-300 drop-shadow-[0_0_18px_rgba(103,232,249,0.85)]"
                : selected
                  ? "ring-4 ring-yellow-400"
                  : playable
                    ? "ring-2 ring-emerald-400 hover:ring-emerald-300"
                    : "ring-1 ring-zinc-700 opacity-90";
          const dragMode = isCounterAvail
            ? "counter"
            : playable
              ? "play"
              : null;
          return (
            <motion.button
              key={i}
              type="button"
              draggable={dragMode !== null}
              onDragStart={() => {
                if (dragMode === "counter" && onCounterDragStart) {
                  onCounterDragStart(i);
                } else if (dragMode === "play") {
                  onDragStart(i);
                }
              }}
              onDragEnd={onDragEnd}
              onClick={(e) => {
                e.stopPropagation();
                if (playable) onClick(i);
              }}
              onMouseEnter={() => onHover({ kind: "hand", cardId })}
              onMouseLeave={() => onHover(null)}
              style={{
                marginLeft: i === 0 ? 0 : -overlap,
                zIndex: selected ? 50 : isRecentDrawn ? 40 : i,
                // counter として使用済 (= 視覚的 トラッシュ移動完了) は 即時 非表示
                opacity: dragging || isCounterSelected ? 0 : undefined,
                pointerEvents: isCounterSelected ? "none" : undefined,
              }}
              animate={
                isRecentDrawn
                  ? {
                      y: [0, -10, 0],
                      scale: [1, 1.06, 1],
                    }
                  : undefined
              }
              transition={
                isRecentDrawn
                  ? { duration: 0.5, ease: "easeOut" }
                  : undefined
              }
              className={`relative inline-block rounded transition duration-150 ease-out ${ring} ${
                playable
                  ? "cursor-grab active:cursor-grabbing hover:-translate-y-4 hover:z-50"
                  : "cursor-default hover:-translate-y-2 hover:z-50"
              } ${selected ? "-translate-y-6" : ""}`}
              title={cardId}
            >
              <CardImage
                cardId={cardId}
                alt={cardId}
                className="h-48 w-auto rounded object-cover shadow-lg"
              />
              {isRecentDrawn && (
                <span className="pointer-events-none absolute top-1 right-1 rounded-full bg-cyan-500 px-2 py-0.5 text-[10px] font-bold text-white shadow">
                  NEW
                </span>
              )}
            </motion.button>
          );
        })}
        {hand.length === 0 && (
          <div className="px-6 py-4 text-sm text-zinc-400">手札なし</div>
        )}
      </div>
    </div>
  );
}

// ========================================================================== //
// 左 サイド: opp info (= hand 裏面 + DON 視覚化)
// ========================================================================== //

function StatBadge({
  player,
  label,
  color,
}: {
  player: PlayerSnapshot;
  label: string;
  color: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs font-bold text-zinc-100">
      <span className={`rounded px-2 py-0.5 text-sm ${color}`}>{label}</span>
      <span className="rounded bg-black/40 px-2 py-0.5">
        Hand{" "}
        <AnimatedNumber
          value={player.hand_count}
          className="text-base text-yellow-200"
          flashColorClass="text-yellow-100"
        />
      </span>
      <span className="rounded bg-black/40 px-2 py-0.5">
        DON{" "}
        <AnimatedNumber
          value={player.don_total}
          className="text-base text-amber-200"
          flashColorClass="text-amber-100"
        />
      </span>
      <span className="rounded bg-black/40 px-2 py-0.5">
        Life{" "}
        <AnimatedNumber
          value={player.life_count}
          className="text-base text-orange-200"
          flashColorClass="text-rose-300"
        />
      </span>
      <span className="opacity-70">
        Deck {player.deck_count} · Trash {player.trash_count}
      </span>
    </div>
  );
}

function SelfInfoPanel({ me }: { me: PlayerSnapshot }) {
  return (
    <div className="shrink-0 rounded border border-emerald-400/50 bg-emerald-950/40 p-2">
      <StatBadge player={me} label="YOU" color="bg-emerald-700 text-white" />
    </div>
  );
}

function OpponentInfoPanel({
  opp,
  reveal,
  onHover,
}: {
  opp: PlayerSnapshot;
  reveal?: boolean;
  onHover?: (h: HoverInfo) => void;
}) {
  return (
    <div className="shrink-0 rounded border border-rose-400/50 bg-rose-950/40 p-3">
      <div className="mb-2">
        <StatBadge player={opp} label="AI" color="bg-rose-700 text-white" />
      </div>
      <div data-hand-side="opp" className="flex flex-wrap gap-0.5">
        {reveal
          ? opp.hand.map((cardId, i) => (
              <button
                key={i}
                type="button"
                onMouseEnter={() =>
                  onHover?.({ kind: "hand", cardId })
                }
                onMouseLeave={() => onHover?.(null)}
                className="rounded ring-1 ring-rose-300/50 transition hover:-translate-y-1 hover:ring-rose-200"
                title={cardId}
              >
                <CardImage
                  cardId={cardId}
                  alt={cardId}
                  className="h-16 w-auto rounded shadow"
                />
              </button>
            ))
          : Array.from({ length: opp.hand_count }).map((_, i) => (
              <img
                key={i}
                src="/assets/ura.png"
                alt="opp hand"
                className="h-12 w-9 rounded shadow ring-1 ring-rose-300/30"
              />
            ))}
        {opp.hand_count === 0 && (
          <span className="text-xs text-rose-300">手札なし</span>
        )}
      </div>
    </div>
  );
}

// ========================================================================== //
// 左 サイド 下部: log
// ========================================================================== //

/** AI 側 (= ai_idx) の log 行 で 非公開カード名 を 「???」 に 置換。
 *
 * 隠す情報:
 *  - 「効果: ドロー N → ['カード名', ...]」  → ドロー カード 中身
 *  - 「効果: search_top_n → 手札 カード名」  → サーチ で 手札 に 加えた カード
 *  - 「効果: 手札に加える カード名」        → 同上 (= 別表記)
 *  - 「マリガン: 手札 [...]」             → 引き直し 後 の 手札 (= 通常 P0 ライン)
 * 公開情報 (= 隠さない):
 *  - play / event / atk / counter (= 場 に 出した カード は 公開)
 *  - hit: life→hand (= 自分視点 で 引いた カード = 自分の場合 公開、 AI 側の場合は 公開
 *    トリガー の 性質上 ライフ から 表 で 開く 演出 が 公式 で 公開なので 公開扱い)
 */
function sanitizeLogLine(line: string, aiIdx: number): string {
  const aiPrefix = `P${aiIdx}`;
  // 「T# P{aiIdx}: ...」 形式 を 拾う
  if (!new RegExp(`\\bP${aiIdx}\\b`).test(line)) return line;

  // 「ドロー N → ['カード1', 'カード2', ...]」
  let out = line.replace(
    /(ドロー\s+\d+\s*→\s*)\[[^\]]*\]/,
    "$1[???]",
  );
  // 「search_top_n → 手札 カード名」 (= 末尾 → 改行 or 行末 まで を 隠す)
  out = out.replace(
    /(search_top_n\s*→\s*手札\s+)([^\s].*)$/,
    "$1???",
  );
  // 「手札に加える カード名」 (= P{aiIdx} 行 限定)
  out = out.replace(
    /(手札に加える\s+)([^\s].+)$/,
    "$1???",
  );
  // 「公開 カード名 → 手札」
  out = out.replace(
    /(公開\s+)([^\s→]+)(\s*→)/,
    "$1???$3",
  );
  // マリガン後の手札開示 (= 通常 出ない が 念のため)
  out = out.replace(
    /(マリガン.*手札\s*)\[[^\]]*\]/,
    "$1[???]",
  );
  // prefix 比較 (= 不要 だが 名前比較 用に keep)
  void aiPrefix;
  return out;
}

function LogSidebar({ log, aiIdx }: { log: string[]; aiIdx: number }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded bg-black/50 p-2 text-xs text-zinc-200">
      <div className="mb-1 shrink-0 text-sm font-bold">LOG</div>
      <div className="flex-1 overflow-y-auto font-mono">
        {log.map((line, i) => {
          const shown = sanitizeLogLine(line, aiIdx);
          const isMasked = shown !== line;
          return (
            <div
              key={i}
              className={
                "border-b border-zinc-700/50 py-0.5 " +
                (isMasked ? "text-zinc-400 italic" : "")
              }
              title={shown}
            >
              {shown}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ========================================================================== //
// 右 サイド: hover preview + action panel + turn/end
// ========================================================================== //

function RightPanel({
  previewCardId,
  previewMeta,
  canAct,
  selection,
  availableActions,
  onActionClick,
  onCancel,
  endPhaseAction,
  onEndPhase,
  isHumanTurn,
  isDefensePending,
  gameOver,
  winner,
  humanIdx,
  aiIdx,
  turn,
  phase,
  defensePayload,
  defenseMe,
  defenseBlockerIid,
  defenseSetBlockerIid,
  defenseCounterIdxs,
  defenseSetCounterIdxs,
  defenseOnSubmit,
  defenseOnHover,
  defenseBusy,
}: {
  previewCardId: string | null;
  previewMeta:
    | {
        kind: "chara";
        name: string;
        power: number;
        attached_dons: number;
        rested: boolean;
        keywords: string[];
        isLeader: boolean;
        cardId: string;
      }
    | null;
  canAct: boolean;
  selection: Selection;
  availableActions: {
    action: HumanLegalAction;
    label: string;
    mode: "attack" | "apply";
  }[];
  onActionClick: (sa: {
    action: HumanLegalAction;
    label: string;
    mode: "attack" | "apply";
  }) => void;
  onCancel: () => void;
  endPhaseAction?: HumanLegalAction;
  onEndPhase: () => void;
  isHumanTurn: boolean;
  isDefensePending: boolean;
  gameOver: boolean;
  winner: number | null;
  humanIdx: number;
  aiIdx: number;
  turn: number;
  phase: string;
  defensePayload: Record<string, unknown> | null;
  defenseMe: PlayerSnapshot;
  defenseBlockerIid: number | null;
  defenseSetBlockerIid: (v: number | null) => void;
  defenseCounterIdxs: number[];
  defenseSetCounterIdxs: (v: number[]) => void;
  defenseOnSubmit: () => void;
  defenseOnHover: (h: HoverInfo) => void;
  defenseBusy: boolean;
}) {
  const turnLabel = gameOver
    ? winner === humanIdx
      ? "WIN"
      : winner === aiIdx
        ? "LOSE"
        : "DRAW"
    : isHumanTurn
      ? "YOUR TURN"
      : "AI TURN";
  const turnColor = gameOver
    ? "bg-amber-500"
    : isHumanTurn
      ? "bg-emerald-500"
      : "bg-rose-500";

  return (
    <div className="flex w-[480px] shrink-0 flex-col gap-2">
      {/* turn / phase */}
      <div className="flex shrink-0 items-center gap-2 rounded bg-black/50 px-2 py-1.5 pr-28 text-xs text-zinc-100">
        <span className="font-semibold">
          T{turn} {phase}
        </span>
        <span
          className={`rounded px-2 py-0.5 text-xs font-bold text-white ${turnColor}`}
        >
          {turnLabel}
        </span>
      </div>

      {/* preview */}
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden rounded bg-black/40 p-2">
        <div className="text-xs font-bold text-zinc-200">PREVIEW</div>
        {previewCardId ? (
          <div className="flex justify-center">
            <CardImage
              cardId={previewCardId}
              alt={previewCardId}
              className="max-h-[calc(100vh-260px)] w-full max-w-[440px] rounded object-contain shadow-2xl"
            />
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center text-xs text-zinc-400">
            カードに hover で 拡大表示
          </div>
        )}
      </div>

      {/* action */}
      <div className="flex shrink-0 flex-col gap-2 rounded bg-black/40 p-2">
        <div className="text-xs font-bold text-zinc-200">ACTION</div>
        {gameOver && (
          <div
            className={
              "rounded p-3 text-center text-base font-bold text-white " +
              (winner === humanIdx
                ? "bg-emerald-600"
                : winner === aiIdx
                  ? "bg-rose-600"
                  : "bg-amber-700")
            }
          >
            {winner === humanIdx
              ? "WIN"
              : winner === aiIdx
                ? "LOSE"
                : "DRAW"}
          </div>
        )}
        {!gameOver && !isHumanTurn && (
          <div className="rounded bg-rose-900/60 p-3 text-center text-sm text-rose-100">
            AI 思考中...
          </div>
        )}
        {!gameOver && isDefensePending && defensePayload && (
          <DefensePanel
            payload={defensePayload}
            me={defenseMe}
            counterIdxs={defenseCounterIdxs}
            setCounterIdxs={defenseSetCounterIdxs}
            onSubmit={defenseOnSubmit}
            busy={defenseBusy}
          />
        )}
        {canAct && !selection && (
          <div className="rounded bg-emerald-900/60 p-3 text-center text-sm text-emerald-100">
            操作: ドラッグ&ドロップ
            <div className="mt-1 text-xs text-emerald-200">
              手札→フィールド / 自キャラ→相手 / DON→自リーダー&キャラ
            </div>
          </div>
        )}
        {canAct && selection?.kind === "attack_pending" && (
          <div className="rounded bg-orange-700 p-3 text-center text-sm text-white">
            攻撃中
            <div className="mt-1 text-xs">対象 click / Esc キャンセル</div>
          </div>
        )}
        {canAct &&
          selection &&
          selection.kind !== "attack_pending" && (
            <ActionButtonGrid
              selection={selection}
              availableActions={availableActions}
              onActionClick={onActionClick}
            />
          )}
        {canAct && selection && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onCancel();
            }}
            className="rounded bg-zinc-700 p-2 text-sm text-white hover:bg-zinc-600"
          >
            Cancel (Esc)
          </button>
        )}
        {canAct && endPhaseAction && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onEndPhase();
            }}
            className="rounded bg-rose-600 p-2 text-sm font-bold text-white hover:bg-rose-500"
          >
            ターン終了
          </button>
        )}
      </div>
    </div>
  );
}

// ========================================================================== //
// ActionButtonGrid: selection 種別 別 に 期待ボタン を 全表示 (= 不可なら disabled)
// ========================================================================== //

type ActionButtonGroup = { kinds: string[]; label: string };

type ActionButtonItem = {
  action: HumanLegalAction;
  label: string;
  mode: "attack" | "apply";
};

function ActionButtonGrid({
  selection,
  availableActions,
  onActionClick,
}: {
  selection: Exclude<Selection, null | { kind: "attack_pending"; attackerIid: number }>;
  availableActions: ActionButtonItem[];
  onActionClick: (sa: ActionButtonItem) => void;
}) {
  // selection 種別 別 「期待 ボタン グループ」 (= 該当 kind あれば active、 なければ disabled)
  let groups: ActionButtonGroup[];
  if (selection.kind === "hand") {
    groups = [
      { kinds: ["PlayCharacter"], label: "登場" },
      { kinds: ["PlayEvent"], label: "イベント" },
      { kinds: ["PlayStage"], label: "ステージ" },
    ];
  } else if (selection.kind === "self_leader") {
    groups = [
      { kinds: ["AttachDonToLeader"], label: "ドン付与" },
      { kinds: ["AttackLeader", "AttackCharacter"], label: "Attack" },
    ];
  } else if (selection.kind === "self_chara") {
    groups = [
      { kinds: ["AttachDonToCharacter"], label: "ドン付与" },
      { kinds: ["AttackLeader", "AttackCharacter"], label: "Attack" },
      { kinds: ["ActivateMain"], label: "起動メイン" },
    ];
  } else {
    groups = [];
  }

  // hand 選択 時 は 該当 group しか 候補 が 通常 ない (= 1 種 のカード = 1 種 の play)。
  // 利用可能 group のみ filter (= 「ステージ なのに 登場」 は disable 表示 する 意味薄い)。
  if (selection.kind === "hand") {
    groups = groups.filter((g) =>
      availableActions.some((sa) => g.kinds.includes(sa.action.kind)),
    );
  }

  return (
    <div
      className={
        "grid gap-2 " + (groups.length >= 2 ? "grid-cols-2" : "grid-cols-1")
      }
    >
      {groups.map((g, i) => {
        const sa = availableActions.find((x) =>
          g.kinds.includes(x.action.kind),
        );
        const active = !!sa;
        return (
          <button
            key={i}
            type="button"
            onClick={(e) => {
              if (!active || !sa) return;
              e.stopPropagation();
              onActionClick(sa);
            }}
            disabled={!active}
            className={
              "rounded p-3 text-sm font-bold shadow transition " +
              (active
                ? "bg-emerald-600 text-white hover:bg-emerald-500"
                : "cursor-not-allowed bg-zinc-700/50 text-zinc-500 line-through")
            }
            title={active ? g.label : `${g.label} (= 現状 不可)`}
          >
            {g.label}
          </button>
        );
      })}
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
// 人間 interactive 選択 modal (= search_top_n 等)
// ========================================================================== //

function SearchChoiceModal({
  payload,
  onSubmit,
  onHover,
  busy,
}: {
  payload: Record<string, unknown>;
  onSubmit: (picks: number[]) => void;
  onHover: (h: HoverInfo) => void;
  busy: boolean;
}) {
  const cards =
    (payload.cards as
      | { idx: number; card_id: string; name: string; matches_filter: boolean }[]
      | undefined) ?? [];
  const limit = Number(payload.limit ?? 1);
  const destination = String(payload.destination ?? "hand");
  const restRemain = String(payload.rest_remain ?? "bottom");
  const depth = Number(payload.depth ?? cards.length);
  const [picked, setPicked] = useState<number[]>([]);

  function togglePick(idx: number, allowed: boolean) {
    if (!allowed) return;
    if (picked.includes(idx)) {
      setPicked(picked.filter((x) => x !== idx));
      return;
    }
    if (picked.length < limit) {
      setPicked([...picked, idx]);
      return;
    }
    // 上限到達 + 未選択 idx をクリック: limit=1 なら 切り替え、 limit>1 なら 最古を退けて 追加
    if (limit === 1) {
      setPicked([idx]);
    } else {
      setPicked([...picked.slice(1), idx]);
    }
  }

  const destLabel = destination === "play" ? "場に登場" : "手札に加える";
  const restLabel =
    restRemain === "trash"
      ? "トラッシュ"
      : restRemain === "top"
        ? "デッキの上"
        : "デッキの下";

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/85 p-6"
      style={{ right: "488px" }}
    >
      <div className="flex max-h-[95vh] w-full max-w-full flex-col rounded-lg border-2 border-amber-400 bg-zinc-900 p-4 shadow-2xl">
        <div className="mb-3 flex items-baseline gap-3">
          <h3 className="text-lg font-bold text-amber-200">
            デッキ 上 {depth} 枚 公開
          </h3>
          <span className="text-sm text-zinc-300">
            最大 {limit} 枚 を {destLabel} (= 残りは {restLabel})
          </span>
          <span className="ml-auto text-sm font-bold text-emerald-300">
            選択 {picked.length} / {limit}
          </span>
        </div>
        <div className="flex min-h-0 flex-1 flex-wrap content-start gap-3 overflow-y-auto px-1 py-3">
          {cards.map((c) => {
            const allowed = c.matches_filter;
            const isSelected = picked.includes(c.idx);
            return (
              <button
                key={c.idx}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  togglePick(c.idx, allowed);
                }}
                onMouseEnter={() =>
                  onHover({ kind: "hand", cardId: c.card_id })
                }
                onMouseLeave={() => onHover(null)}
                disabled={!allowed}
                className={
                  "relative rounded transition " +
                  (isSelected
                    ? "ring-4 ring-amber-400 -translate-y-2"
                    : allowed
                      ? "ring-2 ring-emerald-400 hover:ring-emerald-300"
                      : "ring-1 ring-zinc-700 opacity-50 cursor-not-allowed")
                }
                title={
                  allowed ? c.name : `${c.name} (条件 非該当 → 選択不可)`
                }
              >
                <CardImage
                  cardId={c.card_id}
                  alt={c.name}
                  className="h-72 w-auto rounded shadow-xl"
                />
              </button>
            );
          })}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <span className="text-xs text-zinc-400">
            条件 非該当 のカード は 選択 不可 (= グレー)。 緑枠 = 選択可。
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit(picked);
            }}
            disabled={busy || picked.length === 0}
            className="ml-auto rounded bg-amber-500 px-6 py-2 text-base font-bold text-white shadow hover:bg-amber-400 disabled:opacity-50"
          >
            確定 ({picked.length}枚)
          </button>
        </div>
      </div>
    </div>
  );
}

// ========================================================================== //
// 人間 interactive 対象選択 modal (= ko / return_to_hand / power_pump 等)
// ========================================================================== //

function TargetPickModal({
  payload,
  onSubmit,
  onHover,
  busy,
}: {
  payload: Record<string, unknown>;
  onSubmit: (picks: number[]) => void;
  onHover: (h: HoverInfo) => void;
  busy: boolean;
}) {
  const candidates =
    (payload.candidates as
      | {
          iid: number;
          card_id: string;
          name: string;
          power: number;
          rested: boolean;
          attached_dons: number;
          owner: "self" | "opp";
          is_leader: boolean;
        }[]
      | undefined) ?? [];
  const limit = Number(payload.limit ?? 1);
  const description = String(payload.description ?? "対象 を 選択");
  const primitiveKind = String(payload.primitive_kind ?? "");
  const [picked, setPicked] = useState<number[]>([]);

  function togglePick(idx: number) {
    if (picked.includes(idx)) {
      setPicked(picked.filter((x) => x !== idx));
      return;
    }
    if (picked.length < limit) {
      setPicked([...picked, idx]);
      return;
    }
    // 上限到達 + 未選択 idx クリック: limit=1 → 切替、 limit>1 → 最古退けて追加
    if (limit === 1) {
      setPicked([idx]);
    } else {
      setPicked([...picked.slice(1), idx]);
    }
  }

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/85 p-6"
      style={{ right: "488px" }}
    >
      <div className="flex max-h-[95vh] w-full max-w-full flex-col rounded-lg border-2 border-amber-400 bg-zinc-900 p-4 shadow-2xl">
        <div className="mb-3 flex items-baseline gap-3">
          <h3 className="text-lg font-bold text-amber-200">{description}</h3>
          <span className="text-sm text-zinc-300">({primitiveKind})</span>
          <span className="ml-auto text-sm font-bold text-emerald-300">
            選択 {picked.length} / {limit}
          </span>
        </div>
        <div className="flex min-h-0 flex-1 flex-wrap content-start gap-3 overflow-y-auto px-1 py-3">
          {candidates.map((c, idx) => {
            const isSelected = picked.includes(idx);
            const ownerColor = c.owner === "opp" ? "rose" : "emerald";
            return (
              <button
                key={`${c.iid}-${idx}`}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  togglePick(idx);
                }}
                onMouseEnter={() =>
                  onHover({ kind: "hand", cardId: c.card_id })
                }
                onMouseLeave={() => onHover(null)}
                className={
                  "relative rounded transition " +
                  (isSelected
                    ? "ring-4 ring-amber-400 -translate-y-2"
                    : `ring-2 ring-${ownerColor}-400 hover:ring-emerald-300`)
                }
                title={`${c.name} (P=${c.power}, ${c.rested ? "rested" : "active"}${c.attached_dons > 0 ? `, +${c.attached_dons}d` : ""})`}
              >
                <CardImage
                  cardId={c.card_id}
                  alt={c.name}
                  className={`h-56 w-auto rounded shadow-xl ${c.rested ? "rotate-90" : ""}`}
                />
                <span
                  className={
                    "absolute top-0 left-0 rounded-br px-1.5 text-xs font-bold text-white " +
                    (c.owner === "opp" ? "bg-rose-600" : "bg-emerald-600")
                  }
                >
                  {c.owner === "opp" ? "AI" : "YOU"}
                  {c.is_leader ? " · L" : ""}
                </span>
                <span className="absolute bottom-0 right-0 rounded-tl bg-black/80 px-1.5 text-xs font-bold text-white">
                  P{c.power}
                </span>
              </button>
            );
          })}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <span className="text-xs text-zinc-400">
            候補をクリックして 選択 (最大 {limit} 枚)。
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit(picked);
            }}
            disabled={busy || picked.length === 0}
            className="ml-auto rounded bg-amber-500 px-6 py-2 text-base font-bold text-white shadow hover:bg-amber-400 disabled:opacity-50"
          >
            確定 ({picked.length}枚)
          </button>
        </div>
      </div>
    </div>
  );
}

// ========================================================================== //
// LifeTakenChoiceModal: ライフ受け取り 確認 (= trigger 使う/使わない or OK)
// ========================================================================== //

function LifeTakenChoiceModal({
  payload,
  onSubmit,
  busy,
}: {
  payload: Record<string, unknown>;
  onSubmit: (picks: number[]) => void;
  busy: boolean;
}) {
  const cardId = String(payload.card_id ?? "");
  const name = String(payload.name ?? cardId);
  const hasTrigger = !!payload.has_trigger;
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/85 p-6"
      style={{ right: "488px" }}
    >
      <div className="flex max-h-[95vh] w-full max-w-md flex-col rounded-lg border-2 border-orange-400 bg-zinc-900 p-5 shadow-2xl">
        <h3 className="mb-3 text-lg font-bold text-orange-200">
          ライフ 受け取り: {name}
        </h3>
        <div className="flex justify-center">
          <CardImage
            cardId={cardId}
            alt={name}
            className="h-96 w-auto rounded shadow-2xl ring-4 ring-orange-300"
          />
        </div>
        <div className="mt-4 flex items-center gap-3">
          {hasTrigger ? (
            <>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onSubmit([0]);
                }}
                disabled={busy}
                className="flex-1 rounded bg-zinc-700 px-4 py-3 text-sm font-bold text-white hover:bg-zinc-600 disabled:opacity-50"
              >
                使わない (= 手札 へ)
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onSubmit([1]);
                }}
                disabled={busy}
                className="flex-1 rounded bg-orange-500 px-4 py-3 text-base font-bold text-white shadow hover:bg-orange-400 disabled:opacity-50"
              >
                トリガー 使う
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onSubmit([0]);
              }}
              disabled={busy}
              className="ml-auto rounded bg-orange-500 px-6 py-3 text-base font-bold text-white shadow hover:bg-orange-400 disabled:opacity-50"
            >
              OK (= 手札 に 加える)
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ========================================================================== //
// MulliganConfirmModal: 試合開始時 初期手札 5 枚 を keep / 引き直し
// ========================================================================== //

function MulliganConfirmModal({
  payload,
  onSubmit,
  onHover,
  busy,
}: {
  payload: Record<string, unknown>;
  onSubmit: (picks: number[]) => void;
  onHover: (h: HoverInfo) => void;
  busy: boolean;
}) {
  const cards =
    (payload.cards as { card_id: string; name: string }[] | undefined) ?? [];
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/85 p-6"
      style={{ right: "488px" }}
    >
      <div className="flex max-h-[95vh] w-full max-w-6xl flex-col rounded-lg border-2 border-amber-400 bg-zinc-900 p-5 shadow-2xl">
        <h3 className="mb-1 text-xl font-bold text-amber-200">
          マリガン: 初期手札 を 確認
        </h3>
        <p className="mb-4 text-sm text-zinc-300">
          手札 5 枚 を 確認 (= 右パネル に hover 拡大表示)、 「キープ」 か
          「引き直し」 を 1 度 だけ 選択 できます。
        </p>
        <div className="flex flex-nowrap items-center justify-center gap-3 overflow-x-auto px-1 py-3">
          {cards.map((c, i) => (
            <button
              key={i}
              type="button"
              onMouseEnter={() =>
                onHover({ kind: "hand", cardId: c.card_id })
              }
              onMouseLeave={() => onHover(null)}
              className="shrink-0 rounded ring-2 ring-amber-400 transition hover:-translate-y-2 hover:ring-amber-200"
            >
              <CardImage
                cardId={c.card_id}
                alt={c.name}
                className="h-64 w-auto rounded shadow-2xl"
              />
            </button>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit([0]);
            }}
            disabled={busy}
            className="rounded bg-emerald-600 px-6 py-2.5 text-base font-bold text-white shadow hover:bg-emerald-500 disabled:opacity-50"
          >
            キープ (= この 手札 で 始める)
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit([1]);
            }}
            disabled={busy}
            className="ml-auto rounded bg-rose-600 px-6 py-2.5 text-base font-bold text-white shadow hover:bg-rose-500 disabled:opacity-50"
          >
            引き直し (= デッキ戻し + 新 5 枚)
          </button>
        </div>
      </div>
    </div>
  );
}

// ========================================================================== //
// OptionPickModal: 「効果 発動 する? / どの 効果?」 段階選択 (= choice_effect)
// ========================================================================== //

function OptionPickModal({
  payload,
  onSubmit,
  busy,
}: {
  payload: Record<string, unknown>;
  onSubmit: (picks: number[]) => void;
  busy: boolean;
}) {
  const options =
    (payload.options as { idx: number; label: string }[] | undefined) ?? [];
  const optional = !!payload.optional;

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/85 p-6"
      style={{ right: "488px" }}
    >
      <div className="flex max-h-[95vh] w-full max-w-2xl flex-col rounded-lg border-2 border-fuchsia-400 bg-zinc-900 p-5 shadow-2xl">
        <h3 className="mb-1 text-lg font-bold text-fuchsia-200">
          効果 を 選んで ください
        </h3>
        <p className="mb-4 text-xs text-zinc-400">
          {optional
            ? "発動するか、 どの 効果 を 選ぶか を 指定。 スキップ も 可。"
            : "以下から 1 つ を 選んで ください。"}
        </p>
        <div className="flex flex-col gap-3">
          {options.map((o) => (
            <button
              key={o.idx}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onSubmit([o.idx]);
              }}
              disabled={busy}
              className="rounded-lg border-2 border-fuchsia-500 bg-fuchsia-900/40 px-4 py-3 text-left text-sm font-bold text-fuchsia-100 shadow hover:border-fuchsia-300 hover:bg-fuchsia-800/60 disabled:opacity-50"
            >
              {o.label}
            </button>
          ))}
        </div>
        {optional && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit([-1]);
            }}
            disabled={busy}
            className="mt-4 rounded bg-zinc-700 px-4 py-2 text-sm text-white hover:bg-zinc-600 disabled:opacity-50"
          >
            効果 を 発動 しない (skip)
          </button>
        )}
      </div>
    </div>
  );
}

// ========================================================================== //
// scry_life: 自分のライフ上 N 枚 を 並び替え modal
// ========================================================================== //

function ScryLifeReorderModal({
  payload,
  onSubmit,
  onHover,
  busy,
}: {
  payload: Record<string, unknown>;
  onSubmit: (picks: number[]) => void;
  onHover: (h: HoverInfo) => void;
  busy: boolean;
}) {
  const cards =
    (payload.cards as
      | {
          card_id: string;
          name: string;
          trigger: boolean;
          counter: number;
          power: number;
        }[]
      | undefined) ?? [];
  const depth = Number(payload.depth ?? cards.length);
  const description = String(payload.description ?? "ライフ 並び替え");
  const [order, setOrder] = useState<number[]>([]);

  function appendPick(idx: number) {
    if (order.includes(idx)) return;
    if (order.length >= depth) return;
    setOrder([...order, idx]);
  }

  function reset() {
    setOrder([]);
  }

  const orderRank: Record<number, number> = {};
  order.forEach((idx, rank) => {
    orderRank[idx] = rank + 1;
  });
  const ready = order.length === cards.length;

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/85 p-6"
      style={{ right: "488px" }}
    >
      <div className="flex max-h-[95vh] w-full max-w-full flex-col rounded-lg border-2 border-cyan-400 bg-zinc-900 p-4 shadow-2xl">
        <div className="mb-3 flex items-baseline gap-3">
          <h3 className="text-lg font-bold text-cyan-200">{description}</h3>
          <span className="text-sm text-zinc-300">
            上 → 下 の 順 で クリック (= 1 番目 が ライフ 1 番上)
          </span>
          <span className="ml-auto text-sm font-bold text-emerald-300">
            選択 {order.length} / {cards.length}
          </span>
        </div>
        <div className="flex min-h-0 flex-1 flex-wrap content-start gap-3 overflow-y-auto px-1 py-3">
          {cards.map((c, idx) => {
            const rank = orderRank[idx];
            const isPicked = rank !== undefined;
            return (
              <button
                key={`${c.card_id}-${idx}`}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  appendPick(idx);
                }}
                onMouseEnter={() =>
                  onHover({ kind: "hand", cardId: c.card_id })
                }
                onMouseLeave={() => onHover(null)}
                disabled={isPicked}
                className={
                  "relative rounded transition " +
                  (isPicked
                    ? "ring-4 ring-cyan-400 -translate-y-2 opacity-90"
                    : "ring-2 ring-emerald-400 hover:ring-emerald-300")
                }
                title={`${c.name} (P=${c.power}, C=${c.counter}${c.trigger ? ", trigger" : ""})`}
              >
                <CardImage
                  cardId={c.card_id}
                  alt={c.name}
                  className="h-72 w-auto rounded shadow-xl"
                />
                {isPicked && (
                  <span className="absolute top-0 left-0 rounded-br bg-cyan-500 px-2 text-base font-bold text-white">
                    #{rank}
                  </span>
                )}
                {c.trigger && (
                  <span className="absolute top-0 right-0 rounded-bl bg-rose-600 px-1 text-[10px] font-bold text-white">
                    TRG
                  </span>
                )}
                <span className="absolute bottom-0 right-0 rounded-tl bg-black/80 px-1.5 text-xs font-bold text-white">
                  P{c.power}/C{c.counter}
                </span>
              </button>
            );
          })}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <span className="text-xs text-zinc-400">
            #1 = 一番 上 (= 次 受ける ダメージ で 引く) / 下 ほど 後 で 引く
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              reset();
            }}
            className="rounded bg-zinc-700 px-3 py-2 text-sm text-white hover:bg-zinc-600"
          >
            やり直し
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit(order);
            }}
            disabled={busy || !ready}
            className="ml-auto rounded bg-cyan-500 px-6 py-2 text-base font-bold text-white shadow hover:bg-cyan-400 disabled:opacity-50"
          >
            確定 (順 {order.map((i) => i + 1).join("→")})
          </button>
        </div>
      </div>
    </div>
  );
}

// ========================================================================== //
// reveal_top_play: デッキ上 1 枚 公開 → 登場 / skip confirm modal
// ========================================================================== //

function RevealTopPlayConfirmModal({
  payload,
  onSubmit,
  onHover,
  busy,
}: {
  payload: Record<string, unknown>;
  onSubmit: (picks: number[]) => void;
  onHover: (h: HoverInfo) => void;
  busy: boolean;
}) {
  const card =
    (payload.card as
      | { card_id: string; name: string; cost: number; power: number }
      | undefined) ?? { card_id: "", name: "?", cost: 0, power: 0 };
  const restRemain = String(payload.rest_remain ?? "bottom");
  const description = String(payload.description ?? `${card.name} を 登場?`);
  const restLabel = restRemain === "top" ? "デッキの上" : "デッキの下";

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/85 p-6"
      style={{ right: "488px" }}
    >
      <div className="flex max-h-[95vh] w-full max-w-md flex-col rounded-lg border-2 border-fuchsia-400 bg-zinc-900 p-4 shadow-2xl">
        <h3 className="mb-3 text-lg font-bold text-fuchsia-200">
          {description}
        </h3>
        <div className="flex justify-center">
          <button
            type="button"
            onMouseEnter={() => onHover({ kind: "hand", cardId: card.card_id })}
            onMouseLeave={() => onHover(null)}
            className="relative cursor-default"
          >
            <CardImage
              cardId={card.card_id}
              alt={card.name}
              className="h-96 w-auto rounded shadow-xl ring-2 ring-fuchsia-400"
            />
            <span className="absolute bottom-0 right-0 rounded-tl bg-black/80 px-2 text-sm font-bold text-white">
              C{card.cost} / P{card.power}
            </span>
          </button>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <span className="text-xs text-zinc-400">
            skip 時 → {restLabel} へ 戻る
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit([0]);
            }}
            disabled={busy}
            className="ml-auto rounded bg-zinc-700 px-4 py-2 text-sm text-white hover:bg-zinc-600 disabled:opacity-50"
          >
            skip
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSubmit([1]);
            }}
            disabled={busy}
            className="rounded bg-fuchsia-500 px-6 py-2 text-base font-bold text-white shadow hover:bg-fuchsia-400 disabled:opacity-50"
          >
            登場 させる
          </button>
        </div>
      </div>
    </div>
  );
}

// ========================================================================== //
// トラッシュ閲覧 modal
// ========================================================================== //

function TrashViewer({
  side,
  cards,
  onClose,
  onHover,
}: {
  side: "me" | "opp";
  cards: string[];
  onClose: () => void;
  onHover: (h: HoverInfo) => void;
}) {
  return (
    <div
      onClick={onClose}
      // 右パネル (= w-[480px]) を 除いて 左+中央 のみ カバー
      // 480 + gap-2(8) + p-2(8) ≈ 488px を 右側 から 開ける
      className="absolute top-0 bottom-0 left-0 z-50 flex items-center justify-center bg-black/80 p-6"
      style={{ right: "488px" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[95vh] w-full max-w-full flex-col rounded-lg border border-zinc-600 bg-zinc-900 p-4 shadow-2xl"
      >
        <div className="mb-3 flex items-center gap-3">
          <h3 className="text-lg font-bold text-zinc-100">
            {side === "me" ? "YOUR TRASH" : "OPP TRASH"} ({cards.length})
          </h3>
          <span className="text-xs text-zinc-400">
            新しい順 (= 上が最新)
          </span>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto rounded border border-zinc-500 px-3 py-1 text-sm text-white hover:bg-zinc-700"
          >
            閉じる
          </button>
        </div>
        {cards.length === 0 ? (
          <div className="py-12 text-center text-sm text-zinc-400">
            トラッシュは空です
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-wrap content-start gap-3 overflow-y-auto px-1 py-3">
            {/* 新しい順 (= 最新が先頭) */}
            {[...cards].reverse().map((cardId, i) => (
              <div
                key={`${cardId}-${i}`}
                onMouseEnter={() => onHover({ kind: "hand", cardId })}
                onMouseLeave={() => onHover(null)}
                className="relative rounded hover:ring-2 hover:ring-emerald-400"
                title={cardId}
              >
                <CardImage
                  cardId={cardId}
                  alt={cardId}
                  className="h-72 w-auto rounded shadow-xl ring-1 ring-zinc-700"
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ========================================================================== //
// 防御 overlay
// ========================================================================== //

function DefensePanel({
  payload,
  me,
  counterIdxs,
  setCounterIdxs,
  onSubmit,
  busy,
}: {
  payload: Record<string, unknown>;
  me: PlayerSnapshot;
  counterIdxs: number[];
  setCounterIdxs: (v: number[]) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  const isLeaderAttack = !!payload.is_leader_attack;
  const atkPower = Number(payload.attacker_power ?? 0);
  // defender base power: leader or 該当 chara
  let defBase = 0;
  if (isLeaderAttack) {
    defBase = me.leader.power;
  } else {
    const targetIid = payload.target_iid as number | undefined;
    const ch = me.characters.find((c) => c.instance_id === targetIid);
    defBase = ch?.power ?? me.leader.power;
  }
  // counter 加算 = 各 counter idx の card.counter (= hand string id だけなので 推定不可、
  //   payload に counter_values 含む場合 そこから、 無ければ 1000/枚 を 仮定)
  const counterValues =
    (payload.counter_values as Record<number, number> | undefined) ?? null;
  let counterTotal = 0;
  for (const idx of counterIdxs) {
    counterTotal += counterValues?.[idx] ?? 1000;
  }
  const defTotal = defBase + counterTotal;
  const blocked = defTotal >= atkPower;
  return (
    <div className="flex flex-col gap-2 rounded border-2 border-amber-400 bg-amber-950/70 p-3">
      <div className="text-sm font-bold text-amber-200">
        {isLeaderAttack ? "リーダー" : "キャラ"} 防御
      </div>
      <div className="flex items-center justify-between text-sm text-amber-100">
        <span>相手 攻撃 P</span>
        <span className="text-2xl font-bold text-rose-300">
          {atkPower || "?"}
        </span>
      </div>
      <div className="flex items-center justify-between text-sm text-amber-100">
        <span>
          自防御 P{counterTotal > 0 ? ` (+${counterTotal})` : ""}
        </span>
        <span
          className={
            "text-2xl font-bold " +
            (blocked ? "text-emerald-300" : "text-rose-300")
          }
        >
          {defTotal}
        </span>
      </div>
      <div className="text-center text-xs text-zinc-300">
        手札 の カウンター を マット へ ドラッグ で 加算
      </div>
      {counterIdxs.length > 0 && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setCounterIdxs([]);
          }}
          className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600"
        >
          counter リセット ({counterIdxs.length})
        </button>
      )}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onSubmit();
        }}
        disabled={busy}
        className="rounded bg-amber-500 px-3 py-2 text-base font-bold text-white shadow hover:bg-amber-400 disabled:opacity-50"
      >
        防御 確定
      </button>
    </div>
  );
}

function DefenseOverlay({
  payload,
  me,
  blockerIid,
  setBlockerIid,
  counterIdxs,
  setCounterIdxs,
  onSubmit,
  busy,
  onHover,
}: {
  payload: Record<string, unknown> | null;
  me: PlayerSnapshot;
  blockerIid: number | null;
  setBlockerIid: (v: number | null) => void;
  counterIdxs: number[];
  setCounterIdxs: (v: number[]) => void;
  onSubmit: () => void;
  busy: boolean;
  onHover: (h: HoverInfo) => void;
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
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute inset-x-4 bottom-4 z-50 rounded-lg border-2 border-amber-400 bg-amber-950/95 p-3 shadow-xl backdrop-blur"
    >
      <div className="mb-2 text-base font-bold text-amber-200">
        相手が {isLeaderAttack ? "リーダー" : "キャラ"} を攻撃中 — 防御
      </div>
      <div className="flex gap-4">
        <div>
          <div className="text-sm font-semibold text-amber-200">Blocker</div>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => setBlockerIid(null)}
              className={
                "rounded px-2 py-1 text-sm " +
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
                onMouseEnter={() =>
                  onHover({
                    kind: "chara",
                    cardId: c.card_id,
                    name: c.name,
                    power: c.power,
                    attached_dons: c.attached_dons,
                    rested: c.rested,
                    keywords: c.keywords,
                    isLeader: false,
                  })
                }
                onMouseLeave={() => onHover(null)}
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
                  className="h-28 w-auto rounded"
                />
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1">
          <div className="text-sm font-semibold text-amber-200">
            Counter ({counterIdxs.length})
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {counterIdxsAvail.length === 0 && (
              <span className="text-sm text-amber-300">
                手札に counter 無し
              </span>
            )}
            {counterIdxsAvail.map((idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => toggleCounter(idx)}
                onMouseEnter={() =>
                  onHover({ kind: "hand", cardId: me.hand[idx] })
                }
                onMouseLeave={() => onHover(null)}
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
                  className="h-28 w-auto rounded"
                />
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy}
          className="self-end rounded bg-amber-500 px-4 py-2 text-base font-bold text-white hover:bg-amber-400 disabled:opacity-50"
        >
          防御確定
        </button>
      </div>
    </div>
  );
}
