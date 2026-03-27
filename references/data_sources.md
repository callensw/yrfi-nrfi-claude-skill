# YRFI/NRFI Data Sources & API Reference

## Primary: MLB Stats API

**Base URL:** `https://statsapi.mlb.com/api/v1`
**Auth:** None (free, public API)
**Rate Limits:** Unofficial ~10 req/sec. The scripts use 0.25s delay between calls.

### Key Endpoints

#### Schedule
```
GET /schedule?date=2026-04-15&sportId=1&hydrate=probablePitcher,linescore
```
Returns all games for a date with probable pitchers and linescore data.

#### Linescore (Inning-by-Inning)
```
GET /game/{gamePk}/linescore
```
Returns inning-by-inning run totals. **This is how we get first-inning runs.**

Response structure:
```json
{
  "innings": [
    {
      "num": 1,
      "home": {"runs": 0, "hits": 1, "errors": 0},
      "away": {"runs": 2, "hits": 3, "errors": 0}
    }
  ]
}
```

#### Boxscore
```
GET /game/{gamePk}/boxscore
```
Full game boxscore including batting orders, player stats, and positions.

#### Player Stats
```
GET /people/{playerId}/stats?stats=season&group=pitching&season=2026
```
Season pitching stats for a player. Groups: `pitching`, `hitting`, `fielding`.

#### Player Game Log
```
GET /people/{playerId}/stats?stats=gameLog&group=pitching&season=2026
```
Game-by-game log for the season.

#### Stat Splits
```
GET /people/{playerId}/stats?stats=statSplits&group=pitching&season=2026&sitCodes=vl
```
Split stats. sitCodes:
- `vl` — vs left-handed batters
- `vr` — vs right-handed batters
- `h` — home games
- `a` — away games
- `d` — day games
- `n` — night games

#### Player Info
```
GET /people/{playerId}
```
Basic info: name, team, handedness, position, etc.

#### Teams
```
GET /teams?sportId=1&season=2026
```
All MLB teams with IDs, abbreviations, venue info.

#### Venues
```
GET /venues/{venueId}
```
Venue details including location coordinates.

---

## Weather: OpenWeatherMap

**Base URL:** `https://api.openweathermap.org/data/2.5`
**Auth:** API key required (`OPENWEATHER_API_KEY` env var)
**Free Tier:** 1,000 calls/day (more than enough for 15 games)

### Current Weather
```
GET /weather?lat={lat}&lon={lon}&appid={key}&units=imperial
```

Returns temperature (°F), humidity, wind speed/direction.

**If no API key is set:** Weather factor scores as neutral (50). The analysis still works; you just lose the weather edge.

---

## Vegas Odds (Manual/WebSearch)

No free API provides reliable YRFI/NRFI odds. Use WebSearch to find:
- "MLB YRFI odds today" → DraftKings, FanDuel, BetMGM
- "MLB game over under today" → ESPN, Action Network

Key data points to capture:
- Game Over/Under (total runs line)
- YRFI odds (e.g., -130)
- NRFI odds (e.g., +110)

---

## Supplementary Sources

### Baseball Savant (Statcast)
**URL:** `https://baseballsavant.mlb.com`
- Advanced metrics: exit velocity, launch angle, barrel rate
- Pitch-level data: pitch type mix, velocity trends
- CSV exports available for bulk data

### FanGraphs
**URL:** `https://www.fangraphs.com`
- Park factors by season
- Pitcher game logs with detailed splits
- wOBA, FIP, xFIP for advanced pitcher evaluation

### Rotowire / Baseball Press
- Probable pitcher schedules
- Projected lineups (before official confirmation)
- Injury updates

---

## Supabase Tables Reference

**Project ID:** `kakjbyoxqjvwnsdbqcnb`
**URL:** `https://kakjbyoxqjvwnsdbqcnb.supabase.co`

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `mlb_games` | `game_id` | Game-level data with 1st-inning results |
| `mlb_pitchers` | `(pitcher_id, season)` | Pitcher profiles with 1st-inning splits |
| `mlb_lineups` | `id` (auto), unique `(game_id, team)` | Daily lineup snapshots |
| `mlb_yrfi_picks` | `id` (auto), unique `(game_id, date)` | Generated picks |
| `mlb_model_performance` | `id` (auto), unique `date` | Daily accuracy tracking |
| `mlb_team_stats` | `(team, season)` | Team 1st-inning aggregates |
| `mlb_park_factors` | `(venue, season)` | Venue-specific run environments |
| `mlb_umpire_data` | `(umpire_name, season)` | HP umpire tendencies |

All tables have permissive RLS policies for anon key access.
