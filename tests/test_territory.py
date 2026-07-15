"""api/territory.py の occupancy + optimistic-CAS capture のテスト。

race 処理 (対戦中に別の挑戦者が先に奪取) が version の CAS で正しく弾かれることを担保する。
"""

import threading

import pytest

from api import territory


@pytest.fixture
def t(tmp_path, monkeypatch):
    """テスト毎に隔離された SQLite territory DB を用意する。"""
    monkeypatch.setattr(territory, "_USE_POSTGRES", False)
    monkeypatch.setattr(territory, "_PH", "?")
    monkeypatch.setattr(territory, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(territory, "_TERRITORY_DB", tmp_path / "territory.sqlite")
    territory.init_schema()
    return territory


def test_empty_board(t):
    b = t.get_board()
    assert b["cells"] == []
    assert b["board_version"] == 0
    assert b["n_cells"] == territory.N_CELLS
    c = t.get_cell(10)
    assert c["version"] == 0
    assert c["leader_id"] is None


def test_first_capture(t):
    r = t.resolve_capture(
        10, 0, leader_id="OP01-001", variant_id="OP01-001_p1",
        user="alice", deck_slug="alice-luffy",
    )
    assert r["captured"] is True
    assert r["version"] == 1
    assert r["board_version"] == 1
    c = t.get_cell(10)
    assert c["leader_id"] == "OP01-001"
    assert c["variant_id"] == "OP01-001_p1"
    assert c["user"] == "alice"
    assert c["deck_slug"] == "alice-luffy"
    assert c["version"] == 1


def test_variant_defaults_to_leader_id(t):
    t.resolve_capture(3, 0, leader_id="OP01-001")
    assert t.get_cell(3)["variant_id"] == "OP01-001"


def test_race_stale_expected_rejected(t):
    # alice が version 0 の時に占領成立。
    assert t.resolve_capture(10, 0, leader_id="A", user="alice")["captured"] is True
    # bob も version 0 の時に挑戦を始めていたが、 alice に先を越された。
    # bob の expected=0 は stale → 占領は起きない (non_stakes)。
    r = t.resolve_capture(10, 0, leader_id="B", user="bob")
    assert r["captured"] is False
    assert r["current_version"] == 1
    # マスは alice のまま。
    assert t.get_cell(10)["user"] == "alice"
    # board_version は成立した 1 回分だけ進む。
    assert t.get_board()["board_version"] == 1


def test_recapture_with_correct_version(t):
    t.resolve_capture(10, 0, leader_id="A", user="alice")
    # bob は現 owner (alice, version 1) の防衛 AI に勝ち、 expected=1 で正しく奪取。
    r = t.resolve_capture(10, 1, leader_id="B", user="bob")
    assert r["captured"] is True
    assert r["version"] == 2
    assert t.get_cell(10)["user"] == "bob"
    assert t.get_board()["board_version"] == 2


def test_board_lists_only_owned(t):
    t.resolve_capture(5, 0, leader_id="A", user="alice")
    t.resolve_capture(900, 0, leader_id="B", user="bob")
    ids = sorted(c["cell_id"] for c in t.get_board()["cells"])
    assert ids == [5, 900]


def test_out_of_range_rejected(t):
    with pytest.raises(ValueError):
        t.resolve_capture(territory.N_CELLS, 0, leader_id="A")
    with pytest.raises(ValueError):
        t.resolve_capture(-1, 0, leader_id="A")


def test_seed_board(t):
    res = t.seed_board(
        [
            {"cell_id": 1, "leader_id": "A"},
            {"cell_id": 2, "leader_id": "B", "user": "bob", "deck_slug": "bob-deck"},
        ]
    )
    assert res["seeded"] == 2
    assert t.get_cell(2)["user"] == "bob"
    assert t.get_cell(2)["deck_slug"] == "bob-deck"
    assert len(t.get_board()["cells"]) == 2


def test_seed_board_reset(t):
    t.seed_board([{"cell_id": 1, "leader_id": "A"}])
    t.seed_board([{"cell_id": 2, "leader_id": "B"}], reset=True)
    ids = sorted(c["cell_id"] for c in t.get_board()["cells"])
    assert ids == [2]


def test_sequential_race_only_one_wins(t):
    # 2 人が両方 version 0 を snapshot して挑戦 → 先に解決した 1 人だけ奪取。
    r1 = t.resolve_capture(7, 0, leader_id="A", user="alice")
    r2 = t.resolve_capture(7, 0, leader_id="B", user="bob")
    assert r1["captured"] is True
    assert r2["captured"] is False
    assert t.get_cell(7)["user"] == "alice"


def test_concurrent_capture_exactly_one_wins(t):
    # BEGIN IMMEDIATE による直列化を実スレッドで確認: 全員 expected=0 で同時突入しても
    # 占領成立は 1 回だけ、 最終 version は 1。
    results: list[dict] = []
    lock = threading.Lock()

    def attempt(name: str):
        r = t.resolve_capture(42, 0, leader_id=name, user=name)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=attempt, args=(f"p{i}",)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    wins = [r for r in results if r["captured"]]
    assert len(wins) == 1
    assert t.get_cell(42)["version"] == 1
    assert t.get_board()["board_version"] == 1
