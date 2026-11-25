import json
from pathlib import Path

import pipeline


def scoreboard_payload(home_score="110", away_score="100"):
    return {
        "events": [
            {
                "id": "401999001",
                "status": {"type": {"shortDetail": "Final"}},
                "competitions": [
                    {
                        "id": "401999001",
                        "competitors": [
                            {"homeAway": "home", "score": home_score, "team": {"id": "1", "displayName": "Chicago Bulls", "abbreviation": "CHI"}},
                            {"homeAway": "away", "score": away_score, "team": {"id": "2", "displayName": "New York Knicks", "abbreviation": "NY"}},
                        ],
                    }
                ],
            }
        ]
    }


def standings_payload(wins="10", losses="5"):
    return {
        "children": [
            {
                "standings": {
                    "entries": [
                        {
                            "team": {"id": "1", "displayName": "Chicago Bulls", "abbreviation": "CHI"},
                            "stats": [
                                {"name": "wins", "value": wins},
                                {"name": "losses", "value": losses},
                                {"name": "winPercent", "value": "0.667"},
                                {"name": "gamesBehind", "value": "2.5"},
                            ],
                        }
                    ]
                }
            }
        ]
    }


def write_raw(path: Path, payload: dict) -> None:
    pipeline.write_gzip(path, json.dumps(payload).encode())


def test_each_nba_source_converts_to_common_columns():
    scoreboard = pipeline.convert_scoreboard(scoreboard_payload(), "2026-11-20")[0]
    standings = pipeline.convert_standings(standings_payload(), "2026-11-20")[0]
    assert scoreboard["source"] == "nba_scoreboard"
    assert scoreboard["item_id"] == "game:401999001"
    assert scoreboard["value_1"] == 110
    assert scoreboard["value_2"] == 100
    assert scoreboard["value_3"] == 10
    assert standings["source"] == "nba_standings"
    assert standings["item_id"] == "team:1"
    assert standings["value_1"] == 10
    assert standings["value_2"] == 5
    assert standings["value_3"] == 0.667
    assert set(scoreboard) == set(standings) == set(pipeline.HISTORY_COLUMNS)


def test_move_rule_ranks_relative_numeric_change_and_new_items():
    old = [{"source": "nba_standings", "item_id": "team:1", "item": "Bulls", "value_1": "10", "value_2": "5", "value_3": "0.667", "value_4": "2"}]
    new = [
        {"source": "nba_standings", "item_id": "team:1", "item": "Bulls", "value_1": "12", "value_2": "5", "value_3": "0.706", "value_4": "1"},
        {"source": "nba_standings", "item_id": "team:2", "item": "New team", "value_1": "1", "value_2": "0", "value_3": "1", "value_4": "0"},
    ]
    moves = pipeline.calculate_moves(old, new, limit=None)
    assert moves[0]["kind"] == "new"
    assert moves[1]["kind"] == "changed"
    assert moves[1]["score"] == 0.5


def test_history_is_sorted_and_omits_a_missing_source(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw / "2026-11-21" / "nba_standings.json.gz", standings_payload("11", "5"))
    write_raw(raw / "2026-11-20" / "nba_scoreboard.json.gz", scoreboard_payload())
    output = tmp_path / "history.csv"
    rows = pipeline.build_history(raw, output)
    assert [(row["date"], row["item_id"]) for row in rows] == [
        ("2026-11-20", "game:401999001"),
        ("2026-11-21", "team:1"),
    ]
    assert output.read_text().splitlines()[0].split(",")[:4] == ["date", "item_id", "item", "source"]


def test_second_run_on_same_day_replaces_raw_and_history(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    history = tmp_path / "history.csv"
    status = tmp_path / "status.json"
    monkeypatch.setattr(pipeline, "RAW_DIR", raw)
    monkeypatch.setattr(pipeline, "HISTORY_PATH", history)
    monkeypatch.setattr(pipeline, "STATUS_PATH", status)
    state = {"score": "100", "wins": "10"}

    def fake_fetch(url):
        return json.dumps(
            scoreboard_payload(state["score"], "90") if "scoreboard" in url else standings_payload(state["wins"], "5")
        ).encode()

    monkeypatch.setattr(pipeline, "fetch_bytes", fake_fetch)
    pipeline.run_pipeline("2026-11-22", skip_github=True)
    state.update(score="120", wins="12")
    pipeline.run_pipeline("2026-11-22", skip_github=True)

    rows = pipeline.load_history(history)
    assert len(list((raw / "2026-11-22").glob("*.gz"))) == 2
    assert len(rows) == 2
    assert {row["value_1"] for row in rows} == {"120", "12"}
    assert json.loads(status.read_text())["items"] == 2
