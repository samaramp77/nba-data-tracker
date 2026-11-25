# NBA Data Tracker

[![Tests](https://github.com/samaramp77/nba-data-tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/samaramp77/nba-data-tracker/actions/workflows/tests.yml)

An automatically refreshed NBA data archive and browser report. GitHub Actions runs the collector daily at 06:17 UTC. The collector saves compressed raw responses, rebuilds the history from those raw files, writes the latest status, opens that day’s GitHub Issue, closes the previous day’s issue, and commits the data.

## Sources

| Source | Format | What it supplies |
| --- | --- | --- |
| ESPN NBA scoreboard endpoint | JSON | Games for the UTC run date, home/away teams, scores, margin, and status. |
| ESPN NBA standings endpoint | JSON | The current team standings snapshot, wins, losses, win percentage, and games behind. |

The source URLs are defined in `pipeline.py`. They are public endpoints and do not require an API key. The pipeline treats each source independently: a failed source has no raw file for that day, is recorded as `ok: false`, and does not prevent the other source, history build, Issue step, or commit from completing.

## Data files

Raw responses are stored at `data/raw/YYYY-MM-DD/<source>.<format>.gz`. Raw bytes are preserved inside gzip; the conversion step reads those files and never calls the network. Running `python pipeline.py --build-history` therefore reproduces `data/history.csv` from the raw archive alone.

`data/history.csv` has one row per item per collected day. Rows are sorted by date, item ID, and source. A source with no raw file contributes no rows for that day.

| Column | Meaning | Unit |
| --- | --- | --- |
| `date` | UTC collection date | `YYYY-MM-DD` |
| `item_id` | Stable source-scoped identifier such as `team:1` or `game:401...` | text |
| `item` | Human-readable team or game name | text |
| `source` | Converter/source name | text |
| `value_1` | Primary numeric value: wins for standings, home points for games | wins or points |
| `value_2` | Secondary numeric value: losses for standings, away points for games | losses or points |
| `value_3` | Win percentage for standings, home-minus-away margin for games | ratio or points |
| `value_4` | Games behind for standings; currently empty for games | games or empty |
| `unit` | Semicolon-separated description of the value columns | text |
| `category` | `standings` or `game` | text |
| `team_abbreviation` | Main/home team abbreviation | text |
| `opponent` | Away opponent abbreviation for a game | text |
| `game_id` | ESPN game identifier when the row represents a game | text |
| `game_status` | ESPN status for a game or `current` for standings | text |

`data/status.json` contains `run_time` (UTC timestamp), `first_run_date`, `days_with_success`, `items`, `new_today`, `gone_today`, and one `sources` entry per source with `name`, `ok`, and `count`. The dashboard displays that UTC timestamp in America/Chicago Central Time while retaining UTC in the data file as required.

## Move rule

The pipeline and Today page compare each source/item pair with the previous collected day. For every numeric value column available in both rows, the score is `abs(new - old) / max(abs(old), 1)`. An item’s move is its largest score across `value_1` through `value_4`. New and disappeared items receive an infinite score and rank first. The daily Issue lists the ten highest-ranked moves. An Issue is opened even when the list is empty.

## Site

The `site/` folder is a static, installable web app. `index.html` is Today, `browse.html` is Browse, and `trends.html` is Trends. `app.js` loads `data/history.csv` and `data/status.json` in the browser and performs the filtering, movement calculations, shortlist behavior, and trend calculations there. `styles.css` supplies the shared visual system. `manifest.webmanifest` enables installation and `sw.js` caches the app shell while using network-first loading for the data files so the last loaded data remains available offline.

## File map

- `pipeline.py` — source registry, fetcher, raw archive writer, converters, reproducible history builder, status writer, move rule, and GitHub Issue updater.
- `data/history.csv` — fixed-path history output.
- `data/status.json` — fixed-path latest-run metadata.
- `data/raw/` — date-partitioned compressed source responses.
- `site/index.html` — Today page.
- `site/browse.html` — Browse page with filters, numeric sorting, search, and browser-persisted stars.
- `site/trends.html` — Trends report with an item picker, a value-over-time chart, and four calculated findings.
- `site/app.js` — browser-side data loading and calculations shared by all pages.
- `site/styles.css` — shared fonts, colors, layout, tables, cards, and responsive behavior.
- `site/creative.css` — custom court-side details: NBA-style badge, basketball mark, and reduced-motion-safe dribbling animation.
- `site/girly.css` — pink/plum theme and jeweled hoop styling.
- `site/manifest.webmanifest` — installable web app manifest.
- `site/sw.js` — service worker for online refresh and offline fallback.
- `site/icon.svg` — app icon.
- `.github/workflows/tests.yml` — runs pytest on every push and pull request.
- `.github/workflows/daily.yml` — daily scheduled collector and data commit.
- `.github/workflows/pages.yml` — packages the static site and publishes it with GitHub Pages.
- `tests/test_pipeline.py` — source conversion, move rule, sorting/missing-source, and same-day replacement tests.
- `requirements.txt` — test dependency.
- `.gitignore` — local Python/test cache exclusions.

## Commands

```bash
python pipeline.py --run                 # fetch, build, status, and Issue update
python pipeline.py --run --skip-github   # local run without the GitHub API
python pipeline.py --build-history       # rebuild only from data/raw
pytest -q                                # run the test suite
```

For GitHub Pages, enable the `GitHub Actions` source under repository Settings → Pages. The Pages workflow publishes the contents of `site/` plus the two fixed-path data files. The repository must be public for the assignment’s public-site requirement.
