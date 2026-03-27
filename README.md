# YRFI/NRFI Claude Code Skill

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that generates daily MLB YRFI (Yes Run First Inning) and NRFI (No Run First Inning) betting picks using a 15-factor weighted analysis model with circuit breaker overrides.

Built to run as an always-on skill inside a Telegram group chat — ask it for picks and it fetches live MLB data, runs the model, and delivers formatted pick cards in seconds.

## What It Does

- Pulls today's MLB schedule, probable pitchers, and multi-season stats from the MLB Stats API
- Enriches with historical first-inning data stored in Supabase
- Scrapes Vegas odds (O/U totals, YRFI/NRFI lines) via web search
- Runs a multi-factor weighted analysis scoring each game's YRFI/NRFI probability (0-100)
- Applies hard circuit breaker overrides that trump the model when triggered
- Classifies picks as Strong, Lean, or Skip based on confidence thresholds
- Outputs picks with confidence ratings, reasoning, and flags
- Tracks results and model performance over time

## The Model

### 15-Factor Weighted Scoring

Each game is scored from 0 (strongest NRFI) to 100 (strongest YRFI) across 15 factors organized into four tiers:

| Tier | Weight | Factors |
|------|--------|---------|
| **Tier 1** (~50%) | 50% | Pitcher 1st-inning ERA/WHIP/scoreless%/K rate (25%), Slow Starter Delta (10%), Top-4 Lineup Gauntlet with platoon splits (10%), Recent Form last 10 games (5%) |
| **Tier 2** (~30%) | 30% | Park Factor (10%), Weather — temp/wind/humidity (8%), Pitcher Rest & Workload (6%), Home/Away Splits (6%) |
| **Tier 3** (~15%) | 15% | Umpire Tendencies (5%), Seasonal Timing & Data Confidence (4%), Day/Night Split (3%), Head-to-Head History (3%) |
| **Tier 4** (~5%) | 5% | Travel/Schedule Fatigue (2%), Opener/Bullpen Detection (2%), Injury/Lineup Changes (1%) |

### Pick Classification

| YRFI Probability | Pick | Edge Rating |
|-------------------|------|-------------|
| 66-100 | YRFI | Strong |
| 58-65 | YRFI | Lean |
| 43-57 | SKIP | No edge |
| 36-42 | NRFI | Lean |
| 0-35 | NRFI | Strong |

### 5 Circuit Breaker Overrides

These hard rules override the weighted model when triggered:

| # | Name | Trigger | Effect |
|---|------|---------|--------|
| 1 | **Walk/HR Trap** | Either pitcher: 1st-inn BB% > 9% or HR/9 > 1.5 | NRFI confidence capped at 55 |
| 2 | **O/U Correlation** | NRFI pick on game with 9.5+ O/U total | Must explicitly justify or pick is invalidated |
| 3 | **Double Slow Starter** | Both pitchers: 1st-inn ERA - overall ERA > 1.0 | Auto Strong YRFI, min confidence 70 |
| 4 | **Ace Lockdown** | Both pitchers: 75%+ scoreless 1st innings, sub-1.00 WHIP | Auto Strong NRFI, min confidence 75 |
| 5 | **Coors Field** | Game at Coors Field | +15 added to YRFI probability before classification |

### Early Season Rule

In March/April when a pitcher has fewer than 5 current-season starts:

- Season weighting shifts from 60/25/15 (current/prev/2yr ago) to 15/60/25
- Picks relying on < 30 IP of 1st-inning data flagged as "Low Sample"
- Confidence reduced by 10 points on low-sample picks

### Vegas Odds Integration

The model doesn't scrape odds automatically. During analysis, it web-searches for current YRFI/NRFI odds and game O/U totals from DraftKings, FanDuel, and ESPN. The O/U Correlation circuit breaker uses this data to validate NRFI picks against high-total games.

## How It Works

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│  daily_fetch │───▶│   Supabase   │───▶│  analyze.py │───▶│  Pick Cards  │
│  .py         │    │  enrichment  │    │  15 factors │    │  (Telegram)  │
│              │    │              │    │  + breakers │    │              │
│ MLB Stats API│    │ Historical   │    │             │    │ Strong/Lean/ │
│ Weather API  │    │ 1st-inn data │    │ 0-100 score │    │ Skip + flags │
│ Lineups      │    │ Park factors │    │             │    │              │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
                                              │
                                              ▼
                                       ┌─────────────┐
                                       │track_results│
                                       │   .py       │
                                       │             │
                                       │ Score picks │
                                       │ vs actuals  │
                                       └─────────────┘
```

## Project Structure

```
├── SKILL.md                          # Claude Code skill definition (frontmatter + instructions)
├── scripts/
│   ├── utils.py                      # Shared config, MLB API client, rate limiter, helpers
│   ├── setup_supabase.py             # Supabase table creation SQL
│   ├── fetch_historical.py           # Backfill historical game data by season
│   ├── daily_fetch.py                # Fetch today's games, pitchers, weather, lineups
│   ├── analyze.py                    # 15-factor scoring engine + circuit breakers
│   └── track_results.py              # Score picks against actual 1st-inning results
├── references/
│   ├── factors.md                    # Deep dive on all 15 analysis factors
│   └── data_sources.md               # API endpoints, schemas, and data dictionary
└── assets/
    └── pick_template.md              # Telegram output formatting template
```

## Supabase Tables

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `mlb_games` | `game_id` | Game results with first-inning outcomes (YRFI true/false) |
| `mlb_pitchers` | `(pitcher_id, season)` | Pitcher profiles with first-inning splits |
| `mlb_team_stats` | `(team, season)` | Team-level YRFI/NRFI rates and 1st-inning aggregates |
| `mlb_park_factors` | `(venue, season)` | Venue-specific run environment data |
| `mlb_umpire_data` | `(umpire_name, season)` | Home plate umpire zone tendencies |
| `mlb_lineups` | `(game_id, team)` | Daily lineup snapshots |
| `mlb_yrfi_picks` | `(game_id, date)` | Generated picks with confidence ratings |
| `mlb_model_performance` | `date` | Daily win/loss tracking and rolling accuracy |

## Usage

### As a Claude Code Skill

Drop the entire directory into your project's `.claude/skills/` folder. Claude Code will auto-detect the `SKILL.md` and make it available. Then just ask in natural language:

- "Get today's YRFI picks"
- "What's the NRFI play for the Yankees game?"
- "Analyze the Dodgers vs Padres first inning"
- "How's the YRFI model doing this week?"
- "Backfill historical data for 2025"
- "Update yesterday's results"

The skill handles the full pipeline — fetching data, querying Supabase, running analysis, and formatting output.

### Standalone Scripts

```bash
# Fetch today's games and pitcher data
python3 scripts/daily_fetch.py --output json > /tmp/today.json

# Run analysis on fetched data
python3 scripts/analyze.py --input /tmp/today.json --output text

# Pipe directly (fetch → analyze)
python3 scripts/daily_fetch.py | python3 scripts/analyze.py

# Generate SQL to store picks in Supabase
python3 scripts/analyze.py --input /tmp/today.json --output sql

# Track results after games complete (next morning is fine)
python3 scripts/track_results.py --date 2026-03-27 --output text

# Backfill a full season of historical data
python3 scripts/fetch_historical.py --season 2025 --output sql > /tmp/yrfi_2025.sql
```

### Output Format

Picks are delivered as formatted cards:

```
⚾ YRFI/NRFI PICKS — 2026-03-27
━━━━━━━━━━━━━━━━━━━━━━━━

🔒 STRONG PICKS

🔴 NRFI: KC @ ATL (7:15 ET)
Confidence: 72/100 | O/U: 7.5
Pitchers: Cole Ragans (KC) vs Chris Sale (ATL)
Two elite lefties, weak lineups, low total.

━━━━━━━━━━━━━━━━━━━━━━━━
📊 LEAN PICKS
...

━━━━━━━━━━━━━━━━━━━━━━━━
📈 MODEL PERFORMANCE
Season: 12-8 (60.0%) | Last 7: 5-2 (71.4%)
Strong picks: 8-3 (72.7%) | ROI: +14.2%
```

## Setup

### Requirements

- **Python 3.10+**
- **[httpx](https://www.python-httpx.org/)** — async-capable HTTP client (used for MLB API and weather calls)
- **Supabase project** — free tier works fine ([supabase.com](https://supabase.com))
- **Optional:** `OPENWEATHER_API_KEY` env var for weather data (without it, weather scores as neutral)

### Installation

```bash
# Install Python dependency
pip install httpx

# Clone the repo
git clone https://github.com/callensw/yrfi-nrfi-claude-skill.git

# Set up Supabase tables (run the SQL from setup_supabase.py in your Supabase SQL editor)
# Or if using Claude Code with Supabase MCP, it runs the SQL automatically on first use

# Optional: backfill historical data for better predictions
cd yrfi-nrfi-claude-skill
python3 scripts/fetch_historical.py --season 2025 --output sql > /tmp/backfill.sql
# Then run the SQL in your Supabase project
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | No | Supabase project URL (defaults to built-in project) |
| `SUPABASE_KEY` | No | Supabase anon key (defaults to built-in key) |
| `OPENWEATHER_API_KEY` | No | OpenWeatherMap API key for game-day weather data |

## Data Sources

| Source | Auth | Used For |
|--------|------|----------|
| [MLB Stats API](https://statsapi.mlb.com) | None (free) | Schedule, pitchers, lineups, box scores, linescore |
| [OpenWeatherMap](https://openweathermap.org/api) | API key (free tier) | Temperature, wind, humidity at game venues |
| Web search (DraftKings, FanDuel, ESPN) | None | Vegas O/U totals, YRFI/NRFI odds |
| [Supabase](https://supabase.com) | Anon key | Historical data, picks, performance tracking |

See [`references/data_sources.md`](references/data_sources.md) for full API endpoint documentation and [`references/factors.md`](references/factors.md) for a deep dive on all 15 analysis factors.

## Built With

Built by **Sir Claudius Codius** via [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with the Telegram channel integration. Part of the [vibey-boyz](https://github.com/callensw/vibey-boyz) project — a group of friends who build stuff with AI for fun.
