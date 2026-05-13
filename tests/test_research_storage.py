# -*- coding: utf-8 -*-
"""engine/research_storage.py のテスト。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine import research_storage


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "test_research.sqlite"
    research_storage.init_db(db)
    return db


def test_create_and_get_session(tmp_db):
    sid = research_storage.create_session(
        target_slug="cardrush_1424",
        config={"target_winrate": 0.7, "max_generations": 50},
        path=tmp_db,
    )
    assert isinstance(sid, str)
    s = research_storage.get_session(sid, path=tmp_db)
    assert s is not None
    assert s["target_slug"] == "cardrush_1424"
    assert s["status"] == "running"
    assert s["config"]["target_winrate"] == 0.7


def test_update_status(tmp_db):
    sid = research_storage.create_session("test", {}, path=tmp_db)
    research_storage.update_session_status(sid, "paused", path=tmp_db)
    s = research_storage.get_session(sid, path=tmp_db)
    assert s["status"] == "paused"
    research_storage.update_session_status(
        sid, "completed", completion_reason="target_reached", path=tmp_db,
    )
    s = research_storage.get_session(sid, path=tmp_db)
    assert s["status"] == "completed"
    assert s["completion_reason"] == "target_reached"


def test_update_progress(tmp_db):
    sid = research_storage.create_session("test", {}, path=tmp_db)
    research_storage.update_session_progress(
        sid, generation=3, best_winrate=0.55,
        best_deck={"leader": "OP01-001", "main": []},
        path=tmp_db,
    )
    s = research_storage.get_session(sid, path=tmp_db)
    assert s["current_generation"] == 3
    assert s["best_winrate"] == 0.55
    assert s["best_deck"]["leader"] == "OP01-001"


def test_insert_and_get_candidates(tmp_db):
    sid = research_storage.create_session("test", {}, path=tmp_db)
    cid1 = research_storage.insert_candidate(
        sid, generation=0, candidate_idx=0,
        deck_dict={"leader": "OP01-001", "main": []},
        winrate=0.6, n_games=20, path=tmp_db,
    )
    cid2 = research_storage.insert_candidate(
        sid, generation=0, candidate_idx=1,
        deck_dict={"leader": "OP01-002", "main": []},
        winrate=0.4, n_games=20, parent_id=cid1, mutation_type="swap_card",
        path=tmp_db,
    )
    cands = research_storage.get_candidates(sid, path=tmp_db)
    assert len(cands) == 2
    # winrate 降順
    assert cands[0]["winrate"] == 0.6
    assert cands[1]["winrate"] == 0.4
    assert cands[1]["mutation_type"] == "swap_card"


def test_update_evaluation(tmp_db):
    sid = research_storage.create_session("test", {}, path=tmp_db)
    cid = research_storage.insert_candidate(
        sid, generation=0, candidate_idx=0,
        deck_dict={"leader": "OP01-001", "main": []},
        path=tmp_db,
    )
    research_storage.update_candidate_evaluation(cid, 0.7, 50, path=tmp_db)
    cands = research_storage.get_candidates(sid, path=tmp_db)
    assert cands[0]["winrate"] == 0.7
    assert cands[0]["n_games"] == 50


def test_best_candidate(tmp_db):
    sid = research_storage.create_session("test", {}, path=tmp_db)
    research_storage.insert_candidate(
        sid, 0, 0, {"leader": "A"}, winrate=0.3, n_games=10, path=tmp_db,
    )
    research_storage.insert_candidate(
        sid, 1, 0, {"leader": "B"}, winrate=0.8, n_games=10, path=tmp_db,
    )
    research_storage.insert_candidate(
        sid, 2, 0, {"leader": "C"}, winrate=0.5, n_games=10, path=tmp_db,
    )
    best = research_storage.get_best_candidate(sid, path=tmp_db)
    assert best is not None
    assert best["winrate"] == 0.8
    assert best["deck"]["leader"] == "B"


def test_generation_history(tmp_db):
    sid = research_storage.create_session("test", {}, path=tmp_db)
    research_storage.insert_candidate(sid, 0, 0, {"leader": "A"}, winrate=0.3, n_games=10, path=tmp_db)
    research_storage.insert_candidate(sid, 0, 1, {"leader": "B"}, winrate=0.5, n_games=10, path=tmp_db)
    research_storage.insert_candidate(sid, 1, 0, {"leader": "C"}, winrate=0.7, n_games=10, path=tmp_db)
    history = research_storage.get_generation_history(sid, path=tmp_db)
    assert len(history) == 2
    assert history[0]["generation"] == 0
    assert history[0]["n_candidates"] == 2
    assert history[0]["best_winrate"] == 0.5
    assert history[0]["avg_winrate"] == 0.4
    assert history[1]["best_winrate"] == 0.7


def test_list_sessions(tmp_db):
    s1 = research_storage.create_session("deck1", {}, path=tmp_db)
    s2 = research_storage.create_session("deck2", {}, path=tmp_db)
    research_storage.update_session_status(s1, "completed", path=tmp_db)
    sessions = research_storage.list_sessions(path=tmp_db)
    assert len(sessions) == 2
    completed = research_storage.list_sessions(status="completed", path=tmp_db)
    assert len(completed) == 1
    assert completed[0]["id"] == s1


def test_delete_session(tmp_db):
    sid = research_storage.create_session("test", {}, path=tmp_db)
    research_storage.insert_candidate(sid, 0, 0, {"leader": "A"}, winrate=0.5, n_games=10, path=tmp_db)
    research_storage.delete_session(sid, path=tmp_db)
    assert research_storage.get_session(sid, path=tmp_db) is None
    assert research_storage.get_candidates(sid, path=tmp_db) == []
