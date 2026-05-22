# -*- coding: utf-8 -*-
"""/api/human_match の Vercel serverless 向け reconstruct 経路 smoke test。

別 sid で 同じ session_spec + prior_actions を 投げて、 元 session と 同じ state
(= turn / phase / human_idx / log 末尾) が 復元される ことを 確認。

これは _HUMAN_SESSIONS in-memory dict が function instance 横断で 共有されない
Vercel 環境 を 模擬する: 新規 sid で start せずに、 別 sid + spec + prior_actions で
直接 action 経路を叩いて reconstruct する。
"""
from __future__ import annotations

import os

import pytest

# default GoalDirectedAI v1 は torch / heavy。 軽量化のため GreedyAI に置換
import api.main as api_main
from engine.ai import GreedyAI
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    def _greedy_factory(rng, deck_analysis=None):
        return GreedyAI(rng=rng, deck_analysis=deck_analysis)

    # _build_default_ai_factory を GreedyAI に差し替え (= test 高速化)
    monkeypatch.setattr(
        api_main, "_build_default_ai_factory", lambda slug: _greedy_factory
    )
    # session dict を clean
    api_main._HUMAN_SESSIONS.clear()
    return TestClient(api_main.app)


def _start(client):
    res = client.post(
        "/api/human_match",
        json={
            "deck_a_slug": "cardrush_1456",
            "deck_b_slug": "cardrush_1456",
            "seed": 123,
            "human_first": True,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _state_signature(payload: dict) -> tuple:
    """state を 比較可能 な signature に。 snapshot 全比較 は デバッグ困難 なので
    主要 field の tuple で 一致 確認。"""
    return (
        payload["turn"],
        payload["turn_player_idx"],
        payload["phase"],
        payload["human_idx"],
        payload["ai_idx"],
        payload["pending_kind"],
        payload["game_over"],
        payload["snapshots_count"],
    )


def test_reconstruct_after_mulligan_keep(client):
    """マリガン keep だけの 単純 ケース で reconstruct が 元 session と 一致 する。"""
    start = _start(client)
    sid_a = start["session_id"]
    spec = start["session_spec"]
    assert spec["human_first"] is True
    assert spec["seed"] == 123
    assert start["pending_kind"] == "choice"  # mulligan_confirm

    # session A: choice 適用 (= keep)
    res = client.post(
        f"/api/human_match/{sid_a}/choice",
        json={"picks": [0], "session_spec": spec, "prior_actions": []},
    )
    assert res.status_code == 200, res.text
    state_a = res.json()
    sig_a = _state_signature(state_a)
    actions_after = state_a["actions"]
    assert len(actions_after) == 1
    assert actions_after[0]["kind"] == "choice"

    # 別 sid で reconstruct (= cache miss 模擬)
    api_main._HUMAN_SESSIONS.clear()  # in-memory cache を 完全 flush
    sid_b = "deadbeef" + sid_a[:8]
    # まず 1 個目 の choice を replay するため、 prior_actions=[] + 今回 choice=[0]
    res2 = client.post(
        f"/api/human_match/{sid_b}/choice",
        json={"picks": [0], "session_spec": spec, "prior_actions": []},
    )
    assert res2.status_code == 200, res2.text
    state_b = res2.json()
    sig_b = _state_signature(state_b)
    assert sig_a == sig_b, f"signatures differ: a={sig_a} b={sig_b}"


def test_reconstruct_with_multi_step_history(client):
    """choice + action 数手 を 1 セッション で 進めた 後、 別 sid で 全 history を
    replay → 元 session と signature 一致。"""
    start = _start(client)
    sid_a = start["session_id"]
    spec = start["session_spec"]

    # 1) mulligan keep
    res = client.post(
        f"/api/human_match/{sid_a}/choice",
        json={"picks": [0], "session_spec": spec, "prior_actions": []},
    )
    assert res.status_code == 200
    state = res.json()

    # 数 action 進める (= EndPhase あれば優先、 なければ 0)
    actions_log = list(state["actions"])
    max_steps = 6
    for _ in range(max_steps):
        if state["game_over"]:
            break
        pk = state["pending_kind"]
        if pk == "action":
            legal = state["legal_actions"]
            if not legal:
                break
            end_idx = next(
                (a["idx"] for a in legal if a["kind"] == "EndPhase"), None
            )
            chosen = end_idx if end_idx is not None else legal[0]["idx"]
            res = client.post(
                f"/api/human_match/{sid_a}/action",
                json={
                    "action_idx": chosen,
                    "session_spec": spec,
                    "prior_actions": actions_log,
                },
            )
        elif pk == "defense":
            res = client.post(
                f"/api/human_match/{sid_a}/defense",
                json={
                    "blocker_iid": None,
                    "counter_card_idxs": [],
                    "session_spec": spec,
                    "prior_actions": actions_log,
                },
            )
        elif pk == "choice":
            res = client.post(
                f"/api/human_match/{sid_a}/choice",
                json={
                    "picks": [0],
                    "session_spec": spec,
                    "prior_actions": actions_log,
                },
            )
        else:
            break
        assert res.status_code == 200, res.text
        state = res.json()
        actions_log = list(state["actions"])

    sig_a = _state_signature(state)

    # cache を flush して、 同 history を 別 sid で 完全 replay
    api_main._HUMAN_SESSIONS.clear()

    # 最後 の action を 「今回 action」 として 切り出して、 残り を prior_actions に
    if not actions_log:
        pytest.skip("no actions applied")
    last = actions_log[-1]
    prior = actions_log[:-1]

    last_kind = last["kind"]
    sid_b = "cafef00d" + sid_a[:8]
    if last_kind == "action":
        body = {
            "action_idx": last["action_idx"],
            "session_spec": spec,
            "prior_actions": prior,
        }
        res_r = client.post(f"/api/human_match/{sid_b}/action", json=body)
    elif last_kind == "defense":
        body = {
            "blocker_iid": last.get("blocker_iid"),
            "counter_card_idxs": last.get("counter_card_idxs") or [],
            "session_spec": spec,
            "prior_actions": prior,
        }
        res_r = client.post(f"/api/human_match/{sid_b}/defense", json=body)
    elif last_kind == "choice":
        body = {
            "picks": last.get("picks") or [],
            "session_spec": spec,
            "prior_actions": prior,
        }
        res_r = client.post(f"/api/human_match/{sid_b}/choice", json=body)
    else:
        pytest.skip(f"unsupported last kind: {last_kind}")
    assert res_r.status_code == 200, res_r.text
    state_b = res_r.json()
    sig_b = _state_signature(state_b)
    assert sig_a == sig_b, (
        f"reconstruct signature mismatch: a={sig_a} b={sig_b}\n"
        f"history={actions_log}"
    )


def test_missing_spec_returns_404(client):
    """spec / prior_actions なし の リクエスト が cache miss だと 404 を 返す
    (= 旧 client への 後方互換: 古い frontend は spec を 送らない、 cache hit なら動く)。"""
    api_main._HUMAN_SESSIONS.clear()
    res = client.post(
        "/api/human_match/no_such_sid/action",
        json={"action_idx": 0},
    )
    assert res.status_code == 404
