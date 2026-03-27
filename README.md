# YRFI/NRFI Claude Code Skill

A Claude Code skill that generates daily MLB YRFI (Yes Run First Inning) and NRFI (No Run First Inning) betting picks using a 15-factor weighted analysis model with circuit breaker overrides.

## What It Does

- Pulls today's MLB schedule, probable pitchers, and stats from the MLB Stats API
- Enriches with historical first-inning data stored in Supabase
- Runs a multi-factor weighted analysis scoring each game's YRFI/NRFI probability
- Applies hard circuit breaker overrides (Coors Field, ace lockdowns, etc.)
- Outputs picks with confidence ratings and detailed reasoning
- Tracks results and model performance over time

## The Model

### 15-Factor Weighted Scoring

| Tier | Factors | Weight |
|------|---------|--------|
| **Tier 1** (60%) | Pitcher first-inning ERA, WHIP, K rate, career stats | 60% |
| **Tier 2** (25%) | Team YRFI rates, lineup OPS vs handedness, park factors | 25% |
| **Tier 3** (10%) | Weather, umpire tendencies, recent form, season context | 10% |
| **Tier 4** (5%) | Travel/schedule fatigue, opener detection, late scratches | 5% |

### 5 Circuit Breaker Overrides

These override the model regardless of score:

1. **Coors Field** — Auto YRFI (85%+ historical first-inning scoring rate)
2. **Ace Lockdown** — Force NRFI when both starters have sub-1.50 first-inning ERA with 100+ innings
3. **Weather Extreme** — Boost YRFI in extreme heat (95°F+) or heavy wind-out (15+ mph)
4. **Opener/Bullpen Game** — Boost YRFI when a team uses an opener instead of a traditional starter
5. **Confirmed Lineup Shift** — Re-score if a key bat (top 4) is scratched within 2 hours of game time

## Project Structure

```
├── SKILL.md                          # Claude Code skill definition
├── scripts/
│   ├── utils.py                      # Shared config and helpers
│   ├── setup_supabase.py             # Supabase table creation SQL
│   ├── fetch_historical.py           # Backfill historical game data
│   ├── daily_fetch.py                # Fetch today's games and stats
│   ├── analyze.py                    # 15-factor analysis engine
│   └── track_results.py              # Score picks against actual results
├── references/
│   ├── factors.md                    # Deep dive on all 15 factors
│   └── data_sources.md               # API reference and data schemas
└── assets/
    └── pick_template.md              # Output formatting template
```

## Supabase Tables

| Table | Purpose |
|-------|---------|
| `mlb_games` | Game results with first-inning outcomes |
| `mlb_pitchers` | Pitcher stats and first-inning profiles |
| `mlb_team_stats` | Team-level YRFI/NRFI rates |
| `mlb_park_factors` | Venue-specific run environment data |
| `mlb_umpire_data` | Umpire zone tendencies |
| `mlb_weather_log` | Game-day weather conditions |
| `mlb_yrfi_picks` | Daily picks with confidence ratings |
| `mlb_model_performance` | Rolling accuracy and performance metrics |

## Usage

### As a Claude Code Skill

Drop the skill into your project's `.claude/skills/` directory. Then just ask:

- "Get today's YRFI picks"
- "What's the NRFI play for the Yankees game?"
- "How's the YRFI model doing this week?"
- "Backfill historical data for April"

### Standalone Scripts

```bash
# Fetch today's games
python3 scripts/daily_fetch.py --output json > /tmp/today.json

# Run analysis
python3 scripts/analyze.py --input /tmp/today.json --output text

# Track results after games finish
python3 scripts/track_results.py --date 2026-03-27

# Backfill historical data
python3 scripts/fetch_historical.py --start 2025-03-27 --end 2025-09-29
```

## Setup

1. A Supabase project with the tables created (run `setup_supabase.py` SQL)
2. Python 3.10+
3. Optional: `OPENWEATHER_API_KEY` env var for weather data

## Built With

Built by [Sir Claudius Codius](https://github.com/callensw/vibey-boyz) via Claude Code's Telegram channel integration. Powered by vibes and AI.
