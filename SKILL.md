---
name: yrfi-nrfi
description: Perform detailed MLB YRFI (Yes Run First Inning) and NRFI (No Run First Inning) analysis and generate daily betting picks. Use this skill whenever the user asks about YRFI, NRFI, first inning bets, first inning runs, MLB first inning analysis, today's baseball picks, YRFI model performance, or wants to fetch/update/backfill MLB first-inning data. Also trigger when user mentions specific MLB games and wants first-inning analysis, or asks about pitcher first-inning stats, park factors, or any baseball betting analysis related to the first inning.
user-invocable: false
allowed-tools:
  - mcp__claude_ai_Supabase__execute_sql
  - mcp__claude_ai_Supabase__list_tables
  - Bash(python3 *)
  - Bash(cd * && python3 *)
  - Bash(cat *)
  - Read
  - Write
  - Edit
  - WebSearch
  - WebFetch
---

# YRFI/NRFI Analysis Engine

A rigorous MLB first-inning run analysis system that generates daily YRFI/NRFI picks with confidence ratings, weighted multi-factor scoring, and circuit breaker overrides.

**Supabase Project ID:** `kakjbyoxqjvwnsdbqcnb`
**Scripts Directory:** `/home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts/`

---

## Quick Reference: What To Do

| User Says | What To Do |
|-----------|-----------|
| "get today's YRFI picks" | Run daily analysis pipeline (Steps 1-3 below) |
| "what's the NRFI play tonight" | Run daily analysis, filter to specific game |
| "analyze the Yankees game" | Run analysis for specific game only |
| "how's the YRFI model doing" | Query `mlb_model_performance` table |
| "backfill historical data" | Run fetch_historical.py |
| "update today's results" | Run track_results.py |
| "set up YRFI tables" | Run setup SQL via execute_sql |

---

## First-Time Setup

Run this SQL via `mcp__claude_ai_Supabase__execute_sql` (project_id: `kakjbyoxqjvwnsdbqcnb`):

Copy the SQL from `/home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts/setup_supabase.py` (the `SETUP_SQL` variable).

Run it in chunks if needed — Supabase has SQL length limits.

---

## Daily Analysis Pipeline

### Step 1: Fetch Today's Data

```bash
cd /home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts && python3 daily_fetch.py --output json > /tmp/yrfi_today.json
```

This pulls from MLB Stats API:
- Today's schedule with probable pitchers
- Pitcher season stats (current + 2 prior seasons, weighted 60/25/15)
- Weather at each venue (if OPENWEATHER_API_KEY is set)
- Lineups (if confirmed — usually ~2hrs before game time)

**Re-run this closer to game time** to get confirmed lineups and updated data.

### Step 2: Enrich with Supabase Historical Data

After fetching, query Supabase for historical first-inning data to enrich the analysis:

```sql
-- Get pitcher first-inning profiles
SELECT * FROM mlb_pitchers WHERE pitcher_id IN (...) ORDER BY season DESC;

-- Get team YRFI rates
SELECT * FROM mlb_team_stats WHERE team IN (...) AND season >= 2023;

-- Get park factors
SELECT * FROM mlb_park_factors WHERE venue = '...' ORDER BY season DESC;

-- Get recent form (last 10 games for each team)
SELECT home_team, away_team, yrfi_result
FROM mlb_games
WHERE (home_team = '...' OR away_team = '...')
AND date >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY date DESC LIMIT 10;

-- Get umpire data if assigned
SELECT * FROM mlb_umpire_data WHERE umpire_name = '...';
```

Merge this data into the game objects before running analysis.

### Step 3: Run Analysis

```bash
cd /home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts && python3 analyze.py --input /tmp/yrfi_today.json --output text
```

Or pipe directly:
```bash
cd /home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts && python3 daily_fetch.py | python3 analyze.py
```

For JSON output (to store picks in Supabase):
```bash
cd /home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts && python3 analyze.py --input /tmp/yrfi_today.json --output sql
```

Then run the SQL output via `execute_sql`.

### Step 4: Format & Deliver

Format the output for Telegram using this structure:

```
⚾ YRFI/NRFI PICKS — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━━

🔒 STRONG PICKS

🟢 YRFI: [AWAY] @ [HOME] ([TIME] ET)
Confidence: [XX]/100 | O/U: [X.X]
Pitchers: [Away P] ([TEAM]) vs [Home P] ([TEAM])
⚠️ [Any overrides/flags]
[Key reasons]
[Weather line]

🔴 NRFI: [AWAY] @ [HOME] ([TIME] ET)
...

━━━━━━━━━━━━━━━━━━━━━━━━
📊 LEAN PICKS
...

━━━━━━━━━━━━━━━━━━━━━━━━
📈 MODEL PERFORMANCE
Season: [W]-[L] ([X.X]%) | Last 7: [W]-[L] ([X.X]%)
Strong picks: [W]-[L] ([X.X]%) | ROI: [X.X]%
```

---

## Tracking Results

Run after games complete (next morning is fine):

```bash
cd /home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts && python3 track_results.py --date YYYY-MM-DD --output text
```

To score against stored picks:
```bash
python3 track_results.py --picks /tmp/yrfi_picks_YYYY-MM-DD.json --output sql
```

Run the SQL output via `execute_sql` to update pick results and model performance.

### Model Performance Query
```sql
-- Season performance
SELECT SUM(wins) as total_wins, SUM(losses) as total_losses,
    ROUND(SUM(wins)::numeric / NULLIF(SUM(wins) + SUM(losses), 0) * 100, 1) as win_pct
FROM mlb_model_performance;

-- Last 7 days
SELECT SUM(wins), SUM(losses),
    ROUND(SUM(wins)::numeric / NULLIF(SUM(wins) + SUM(losses), 0) * 100, 1)
FROM mlb_model_performance
WHERE date >= CURRENT_DATE - INTERVAL '7 days';

-- Strong picks accuracy
SELECT SUM(strong_picks_wins) as sw, SUM(strong_picks_total) as st,
    ROUND(SUM(strong_picks_wins)::numeric / NULLIF(SUM(strong_picks_total), 0) * 100, 1) as pct
FROM mlb_model_performance;
```

---

## Historical Backfill

To backfill past seasons (run once per season):

```bash
cd /home/chase/vibey-boyz/.claude/skills/yrfi-nrfi/scripts && python3 fetch_historical.py --season 2025 --output sql > /tmp/yrfi_2025.sql
```

Then run the SQL via `execute_sql` in chunks (the output can be large).

Repeat for 2024 and 2023:
```bash
python3 fetch_historical.py --season 2024 --output sql > /tmp/yrfi_2024.sql
python3 fetch_historical.py --season 2023 --output sql > /tmp/yrfi_2023.sql
```

**Note:** Historical backfill makes many MLB API calls. Run during off-peak hours and expect it to take 10-30 minutes per season.

---

## Analysis Model Details

### Factor Weights (total = 100%)

**Tier 1 — Highest Weight (~50%)**
- Starting Pitcher 1st-Inning Stats (25%) — Both pitchers' 1st-inn ERA, WHIP, scoreless%, K rate
- Slow Starter Delta (10%) — Gap between 1st-inn ERA and overall ERA. Delta > 1.0 = flagged
- Top 4 Gauntlet (10%) — #1-#4 hitters, not team-wide averages. Platoon splits vs pitcher hand
- Recent Form (5%) — Last 10 games 1st-inning scoring rate

**Tier 2 — Moderate Weight (~30%)**
- Park Factor (10%) — Venue-specific 1st-inning run environment
- Weather (8%) — Temp, wind, humidity (dome = neutral)
- Pitcher Rest (6%) — Days rest, workload, short rest = YRFI lean
- Home/Away Splits (6%) — Pitcher/team home vs away 1st-inning performance

**Tier 3 — Lower Weight (~15%)**
- Umpire (5%) — HP ump zone size, YRFI rate, walk rate
- Day/Night (3%) — Some pitchers/teams split significantly
- H2H History (3%) — Lineup familiarity with specific pitcher
- Seasonal Timing (4%) — Early season wildness, sample size confidence

**Tier 4 — Contextual (~5%)**
- Travel/Schedule (2%) — Road trips, day-after-night
- Opener Detection (2%) — Bullpen/opener game changes analysis
- Injury/Lineup Changes (1%) — Late scratches, key bat missing

### Circuit Breaker Overrides

These HARD RULES override the weighted model:

1. **Walk/HR Trap:** Either pitcher with 1st-inn BB% > 9% or HR/9 > 1.5 → NRFI confidence capped at 55
2. **O/U Correlation:** NRFI pick on 9.5+ total → must explicitly justify or pick is invalid
3. **Double Slow Starter:** Both pitchers with ERA delta > 1.0 → auto Strong YRFI, min confidence 70
4. **Ace Lockdown:** Both pitchers 75%+ scoreless, sub-1.00 WHIP → auto Strong NRFI, min confidence 75
5. **Coors Field Override:** Any Coors game → +15 to YRFI probability before classification

### Pick Classification

| YRFI Probability | Pick | Edge Rating |
|-------------------|------|-------------|
| 66-100 | YRFI | Strong |
| 58-65 | YRFI | Moderate/Lean |
| 43-57 | SKIP | Too close to call |
| 36-42 | NRFI | Moderate/Lean |
| 0-35 | NRFI | Strong |

### Early Season Rule

In March/April when current-season sample < 5 starts:
- Prioritize prior full season data (weight shifts to 15/60/25 instead of 60/25/15)
- Flag picks relying on < 30 IP of 1st-inning data as "Low Sample"
- Reduce confidence by 10 points on low-sample picks

---

## Vegas Odds Integration

The model doesn't scrape odds automatically. When generating picks:

1. **WebSearch** for "MLB YRFI odds today" or "DraftKings YRFI"
2. Add Vegas O/U and YRFI/NRFI odds to game data before analysis
3. The O/U Correlation circuit breaker uses this data

If odds aren't available, the analysis still works — just note "No odds data" in the output.

---

## Key Data Sources

- **MLB Stats API** (statsapi.mlb.com) — Free, no key needed. Games, pitchers, lineups, box scores
- **OpenWeatherMap** — Weather at venue coordinates. Needs `OPENWEATHER_API_KEY` env var (optional)
- **WebSearch** — Vegas odds, injury reports, lineup confirmations
- **Supabase** — All historical data, picks, performance tracking

See `references/data_sources.md` for detailed API endpoint documentation.
See `references/factors.md` for deep dive on each analysis factor.
