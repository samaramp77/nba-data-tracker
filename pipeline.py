#!/usr/bin/env python3
"""Fetch NBA data, build the reproducible history, and publish run metadata.

The history builder only reads data/raw.  This makes a historical rebuild
independent of the network and means that changing a conversion rule can be
applied to every day already collected.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
HISTORY_PATH = DATA_DIR / "history.csv"
STATUS_PATH = DATA_DIR / "status.json"

HISTORY_COLUMNS = [
    "date",
    "item_id",
    "item",
    "source",
    "value_1",
    "value_2",
    "value_3",
    "value_4",
    "unit",
    "category",
    "team_abbreviation",
    "opponent",
    "game_id",
    "game_status",
]
NUMERIC_COLUMNS = ["value_1", "value_2", "value_3", "value_4"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def scoreboard_url(run_date: str) -> str:
    compact = run_date.replace("-", "")
    return (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
        f"scoreboard?dates={compact}&limit=1000"
    )


def standings_url(_: str) -> str:
    return (
        "https://site.api.espn.com/apis/v2/sports/basketball/nba/"
        "standings?region=us&lang=en&contentorigin=espn"
    )


SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "nba_scoreboard": {"format": "json", "url": scoreboard_url},
    "nba_standings": {"format": "json", "url": standings_url},
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_date() -> str:
    return utc_now().date().isoformat()


def json_number(value: Any) -> float | int | str:
    """Return a number when possible while preserving an empty value."""
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return int(number) if number.is_integer() else number


def fetch_bytes(url: str, timeout: int = 45) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "data-tracker/1.0 (GitHub Actions; educational project)",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def write_gzip(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the compressed wrapper reproducible when the response is
    # unchanged; the raw payload itself is never altered.
    with gzip.GzipFile(filename=str(path), mode="wb", mtime=0) as output:
        output.write(payload)


def read_raw_json(path: Path) -> Any:
    with gzip.open(path, "rb") as source:
        return json.loads(source.read().decode("utf-8"))


def blank_row(run_date: str, item_id: str, item: str, source: str) -> dict[str, Any]:
    return {
        "date": run_date,
        "item_id": item_id,
        "item": item,
        "source": source,
        "value_1": "",
        "value_2": "",
        "value_3": "",
        "value_4": "",
        "unit": "",
        "category": "",
        "team_abbreviation": "",
        "opponent": "",
        "game_id": "",
        "game_status": "",
    }


def convert_scoreboard(payload: dict[str, Any], run_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in payload.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        competition = competitions[0]
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home_team = home.get("team") or {}
        away_team = away.get("team") or {}
        home_name = home_team.get("displayName", "Home")
        away_name = away_team.get("displayName", "Away")
        home_score = json_number(home.get("score"))
        away_score = json_number(away.get("score"))
        margin: float | int | str = ""
        if isinstance(home_score, (int, float)) and isinstance(away_score, (int, float)):
            margin = home_score - away_score
        status = ((event.get("status") or {}).get("type") or {}).get("shortDetail", "")
        row = blank_row(
            run_date,
            f"game:{event.get('id', competition.get('id', 'unknown'))}",
            f"{away_name} at {home_name}",
            "nba_scoreboard",
        )
        row.update(
            {
                "value_1": home_score,
                "value_2": away_score,
                "value_3": margin,
                "unit": "home points; away points; home margin",
                "category": "game",
                "team_abbreviation": home_team.get("abbreviation", ""),
                "opponent": away_team.get("abbreviation", ""),
                "game_id": event.get("id", competition.get("id", "")),
                "game_status": status,
            }
        )
        rows.append(row)
    return rows


def find_standing_entries(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        standings = value.get("standings")
        if isinstance(standings, dict) and isinstance(standings.get("entries"), list):
            yield from (entry for entry in standings["entries"] if isinstance(entry, dict))
        for child in value.values():
            yield from find_standing_entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from find_standing_entries(child)


def stat_value(stats: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in stats:
            return stats[name]
    return ""


def convert_standings(payload: dict[str, Any], run_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in find_standing_entries(payload):
        team = entry.get("team") or {}
        team_id = str(team.get("id", ""))
        if not team_id or team_id in seen:
            continue
        seen.add(team_id)
        stats: dict[str, Any] = {}
        for stat in entry.get("stats", []):
            if isinstance(stat, dict) and stat.get("name"):
                stats[str(stat["name"])] = stat.get("value", stat.get("displayValue", ""))
        name = team.get("displayName", team.get("abbreviation", team_id))
        row = blank_row(run_date, f"team:{team_id}", name, "nba_standings")
        row.update(
            {
                "value_1": json_number(stat_value(stats, "wins")),
                "value_2": json_number(stat_value(stats, "losses")),
                "value_3": json_number(stat_value(stats, "winPercent", "winPercentage")),
                "value_4": json_number(stat_value(stats, "gamesBehind", "gamesBack")),
                "unit": "wins; losses; win percentage; games behind",
                "category": "standings",
                "team_abbreviation": team.get("abbreviation", ""),
                "game_status": "current",
            }
        )
        rows.append(row)
    return rows


CONVERTERS: dict[str, Callable[[dict[str, Any], str], list[dict[str, Any]]]] = {
    "nba_scoreboard": convert_scoreboard,
    "nba_standings": convert_standings,
}


def source_from_raw_path(path: Path) -> tuple[str, str]:
    source, file_format, compression = path.name.rsplit(".", 2)
    if compression != "gz":
        raise ValueError(f"Raw file is not gzip compressed: {path}")
    return source, file_format


def convert_raw_file(path: Path, run_date: str | None = None) -> list[dict[str, Any]]:
    source, file_format = source_from_raw_path(path)
    if file_format != "json":
        raise ValueError(f"Unsupported raw format: {file_format}")
    if source not in CONVERTERS:
        raise ValueError(f"No converter registered for source: {source}")
    day = run_date or path.parent.name
    return CONVERTERS[source](read_raw_json(path), day)


def iter_raw_days(raw_root: Path | None = None) -> list[str]:
    raw_root = raw_root or RAW_DIR
    if not raw_root.exists():
        return []
    return sorted(
        child.name
        for child in raw_root.iterdir()
        if child.is_dir() and DATE_RE.fullmatch(child.name)
    )


def build_history(raw_root: Path | None = None, output_path: Path | None = None) -> list[dict[str, Any]]:
    raw_root = raw_root or RAW_DIR
    output_path = output_path or HISTORY_PATH
    rows: list[dict[str, Any]] = []
    for day in iter_raw_days(raw_root):
        day_path = raw_root / day
        for raw_path in sorted(day_path.glob("*.gz")):
            rows.extend(convert_raw_file(raw_path, day))
    rows.sort(key=lambda row: (row["date"], row["item_id"], row["source"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=HISTORY_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in HISTORY_COLUMNS} for row in rows)
    return rows


def load_history(path: Path | None = None) -> list[dict[str, str]]:
    path = path or HISTORY_PATH
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def row_key(row: dict[str, Any]) -> str:
    return f"{row.get('source', '')}:{row.get('item_id', '')}"


def numeric_value(row: dict[str, Any], column: str) -> float | None:
    value = row.get(column, "")
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def move_score(old: dict[str, Any] | None, new: dict[str, Any] | None) -> float:
    if old is None or new is None:
        return math.inf
    scores: list[float] = []
    for column in NUMERIC_COLUMNS:
        before = numeric_value(old, column)
        after = numeric_value(new, column)
        if before is not None and after is not None and before != after:
            scores.append(abs(after - before) / max(abs(before), 1.0))
    return max(scores, default=0.0)


def calculate_moves(
    previous_rows: Iterable[dict[str, Any]],
    current_rows: Iterable[dict[str, Any]],
    limit: int | None = 10,
) -> list[dict[str, Any]]:
    previous = {row_key(row): row for row in previous_rows}
    current = {row_key(row): row for row in current_rows}
    moves: list[dict[str, Any]] = []
    for key in sorted(set(previous) | set(current)):
        old = previous.get(key)
        new = current.get(key)
        score = move_score(old, new)
        if score == 0:
            continue
        kind = "new" if old is None else "gone" if new is None else "changed"
        moves.append({"key": key, "kind": kind, "old": old, "new": new, "score": score})
    moves.sort(key=lambda move: (-move["score"], move["key"]))
    return moves if limit is None else moves[:limit]


def latest_day_rows(rows: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("date") == day]


def previous_day_rows(rows: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    days = sorted({row.get("date", "") for row in rows if row.get("date", "") < day})
    return [row for row in rows if days and row.get("date") == days[-1]]


def make_status(rows: list[dict[str, Any]], run_date: str, run_time: str, source_results: list[dict[str, Any]]) -> dict[str, Any]:
    current = latest_day_rows(rows, run_date)
    previous = previous_day_rows(rows, run_date)
    current_keys = {row_key(row) for row in current}
    previous_keys = {row_key(row) for row in previous}
    raw_days = iter_raw_days()
    return {
        "run_time": run_time,
        "first_run_date": raw_days[0] if raw_days else None,
        "days_with_success": sum(1 for day in raw_days if list((RAW_DIR / day).glob("*.gz"))),
        "items": len(current),
        "new_today": len(current_keys - previous_keys),
        "gone_today": len(previous_keys - current_keys),
        "sources": source_results,
    }


def write_status(status: dict[str, Any], path: Path | None = None) -> None:
    path = path or STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def display_row(row: dict[str, Any] | None) -> str:
    if row is None:
        return "—"
    if row.get("category") == "standings":
        labels = {"value_1": "Wins", "value_2": "Losses", "value_3": "Win %", "value_4": "Games behind"}
    elif row.get("category") == "game":
        labels = {"value_1": "Home points", "value_2": "Away points", "value_3": "Margin", "value_4": "Attendance"}
    else:
        labels = {column: column for column in NUMERIC_COLUMNS}
    values = [f"{labels[column]}={row.get(column, '')}" for column in NUMERIC_COLUMNS if row.get(column, "") != ""]
    return ", ".join(values) or "no numeric values"


def make_issue_body(status: dict[str, Any], moves: list[dict[str, Any]], run_date: str) -> str:
    lines = [
        f"## NBA data report for {run_date}",
        "",
        f"Run time (UTC): `{status['run_time']}`  ",
        f"Items in latest run: **{status['items']}**  ",
        f"New items: **{status['new_today']}** · Gone items: **{status['gone_today']}**",
        "",
        "The move score is the largest `abs(new - old) / max(abs(old), 1)` across the four numeric value columns. New and gone items are ranked first.",
        "",
        "### Biggest moves",
    ]
    if not moves:
        lines.append("No item changed relative to the previous collected day.")
    else:
        for move in moves:
            old = move["old"]
            new = move["new"]
            row = new or old
            lines.append(
                f"- **{row.get('item', move['key'])}** (`{move['kind']}`, `{row.get('source', '')}`): "
                f"{display_row(old)} → {display_row(new)}"
            )
    lines.extend(["", "### Source status"])
    for source in status["sources"]:
        state = "ok" if source["ok"] else "failed"
        lines.append(f"- `{source['name']}`: **{state}**, {source['count']} rows")
    return "\n".join(lines) + "\n"


def github_request(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "nba-data-tracker",
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else None


def update_github_issue(status: dict[str, Any], moves: list[dict[str, Any]], run_date: str) -> None:
    repository = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repository or not token:
        print("GitHub issue update skipped: GITHUB_REPOSITORY or GITHUB_TOKEN is missing")
        return
    api_root = f"https://api.github.com/repos/{repository}"
    try:
        issues = github_request("GET", f"{api_root}/issues?state=open&per_page=100", token) or []
        yesterday = (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()
        for issue in issues:
            if issue.get("pull_request"):
                continue
            if issue.get("title") in {run_date, yesterday}:
                github_request("PATCH", f"{api_root}/issues/{issue['number']}", token, {"state": "closed"})
        github_request(
            "POST",
            f"{api_root}/issues",
            token,
            {"title": run_date, "body": make_issue_body(status, moves, run_date), "labels": ["data-tracker"]},
        )
        print(f"GitHub issue opened for {run_date}")
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        # A transient GitHub outage should not prevent the data commit.
        print(f"GitHub issue update failed: {error}", file=sys.stderr)


def clear_day(raw_root: Path, run_date: str) -> None:
    day_path = raw_root / run_date
    day_path.mkdir(parents=True, exist_ok=True)
    for child in day_path.iterdir():
        if child.is_file():
            child.unlink()


def run_pipeline(run_date: str | None = None, skip_github: bool = False) -> dict[str, Any]:
    run_date = run_date or utc_date()
    run_time = utc_now().isoformat().replace("+00:00", "Z")
    clear_day(RAW_DIR, run_date)
    source_results: list[dict[str, Any]] = []
    for source_name, config in SOURCE_REGISTRY.items():
        try:
            payload = fetch_bytes(config["url"](run_date))
            raw_path = RAW_DIR / run_date / f"{source_name}.{config['format']}.gz"
            write_gzip(raw_path, payload)
            rows = convert_raw_file(raw_path, run_date)
            source_results.append({"name": source_name, "ok": True, "count": len(rows)})
            print(f"{source_name}: ok ({len(rows)} rows)")
        except Exception as error:  # one source must never stop the run
            source_results.append({"name": source_name, "ok": False, "count": 0})
            print(f"{source_name}: failed ({error})", file=sys.stderr)
    rows = build_history()
    current = latest_day_rows(rows, run_date)
    previous = previous_day_rows(rows, run_date)
    moves = calculate_moves(previous, current, limit=10)
    status = make_status(rows, run_date, run_time, source_results)
    write_status(status)
    if not skip_github:
        update_github_issue(status, moves, run_date)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="fetch sources, build files, and update the issue")
    parser.add_argument("--build-history", action="store_true", help="rebuild data/history.csv from data/raw")
    parser.add_argument("--date", help="UTC date to use for a run (primarily for tests/replays)")
    parser.add_argument("--skip-github", action="store_true", help="do not call the GitHub Issues API")
    args = parser.parse_args()
    if args.build_history and not args.run:
        build_history()
        return 0
    if args.run:
        run_pipeline(args.date, skip_github=args.skip_github)
        return 0
    return 0 if args.run or not args.build_history else 1


if __name__ == "__main__":
    raise SystemExit(main())
