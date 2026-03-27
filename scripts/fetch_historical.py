"""
YRFI/NRFI Historical Data Backfill
Fetches game-level first-inning data from MLB Stats API (2023-present).
Builds pitcher first-inning profiles from game-by-game linescores.

Usage:
    python3 fetch_historical.py [--season 2025] [--start-date 2025-03-27] [--end-date 2025-09-29]

This script outputs SQL INSERT statements to stdout.
Pipe to a file or run via MCP execute_sql.
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

# Add script directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    mlb_get, get_schedule, get_linescore, get_venue_info,
    team_abbrev, safe_float, safe_int, calculate_era, calculate_whip,
    extract_first_inning_runs,
)


def fetch_season_games(season: int, start_date: str = None, end_date: str = None):
    """
    Fetch all regular season games for a season.
    Yields game dicts with first-inning data.
    """
    if not start_date:
        start_date = f"{season}-03-20"
    if not end_date:
        end_date = f"{season}-09-30"

    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        games = get_schedule(date_str, hydrate="probablePitcher")

        if games:
            print(f"-- Processing {date_str}: {len(games)} games", file=sys.stderr)

        for game in games:
            game_pk = game.get("gamePk")
            status = game.get("status", {}).get("abstractGameState", "")

            # Only process completed games
            if status != "Final":
                continue

            # Get first-inning data from linescore
            linescore = get_linescore(game_pk)
            away_runs, home_runs = extract_first_inning_runs(linescore)

            if away_runs is None or home_runs is None:
                continue

            # Extract game info
            teams = game.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            venue = game.get("venue", {})

            home_team = team_abbrev(home.get("team", {}).get("name", ""))
            away_team = team_abbrev(away.get("team", {}).get("name", ""))
            venue_name = venue.get("name", "Unknown")
            venue_info = get_venue_info(venue_name)

            # Probable pitchers
            home_pitcher = home.get("probablePitcher", {})
            away_pitcher = away.get("probablePitcher", {})

            # Final score from linescore
            ls_teams = linescore.get("teams", {}) if linescore else {}
            final_home = ls_teams.get("home", {}).get("runs")
            final_away = ls_teams.get("away", {}).get("runs")

            # Game time
            game_date = game.get("gameDate", "")

            yield {
                "game_id": game_pk,
                "date": date_str,
                "home_team": home_team,
                "away_team": away_team,
                "venue": venue_name,
                "game_time_et": game_date,
                "home_pitcher_id": home_pitcher.get("id"),
                "away_pitcher_id": away_pitcher.get("id"),
                "home_pitcher_name": home_pitcher.get("fullName"),
                "away_pitcher_name": away_pitcher.get("fullName"),
                "first_inning_runs_home": home_runs,
                "first_inning_runs_away": away_runs,
                "final_score_home": final_home,
                "final_score_away": final_away,
                "is_dome": venue_info.get("is_dome", False),
                "game_status": "Final",
            }

        current += timedelta(days=1)


def build_pitcher_profiles(games: list, season: int) -> dict:
    """
    Build pitcher first-inning profiles from game data.
    Returns dict of pitcher_id -> profile.
    """
    pitcher_data = defaultdict(lambda: {
        "games": 0, "scoreless": 0,
        "runs": 0, "hits": 0, "walks": 0, "ks": 0, "hrs": 0,
        "name": "", "team": "",
    })

    for game in games:
        for side in ["home", "away"]:
            pid = game.get(f"{side}_pitcher_id")
            if not pid:
                continue
            pname = game.get(f"{side}_pitcher_name", "Unknown")
            pteam = game.get(f"{side}_team", "")

            # First-inning runs for the pitcher's side
            if side == "home":
                runs_allowed = game.get("first_inning_runs_away", 0)
            else:
                runs_allowed = game.get("first_inning_runs_home", 0)

            pd = pitcher_data[pid]
            pd["name"] = pname
            pd["team"] = pteam
            pd["games"] += 1
            pd["runs"] += safe_int(runs_allowed)
            if safe_int(runs_allowed) == 0:
                pd["scoreless"] += 1

    profiles = {}
    for pid, pd in pitcher_data.items():
        if pd["games"] == 0:
            continue
        innings = pd["games"]  # 1 inning per game in 1st-inning context
        first_inn_era = calculate_era(pd["runs"], innings)
        scoreless_pct = (pd["scoreless"] / pd["games"]) * 100 if pd["games"] > 0 else 0

        profiles[pid] = {
            "pitcher_id": pid,
            "season": season,
            "name": pd["name"],
            "team": pd["team"],
            "first_inning_era": round(first_inn_era, 2),
            "first_inning_runs_allowed_total": pd["runs"],
            "first_inning_games": pd["games"],
            "first_inning_scoreless_pct": round(scoreless_pct, 1),
        }

    return profiles


def build_team_stats(games: list, season: int) -> dict:
    """Build team-level first-inning aggregates."""
    team_data = defaultdict(lambda: {
        "home_games": 0, "away_games": 0,
        "home_yrfi": 0, "away_yrfi": 0,
        "runs_scored_1st": 0, "runs_allowed_1st": 0,
    })

    for game in games:
        home = game["home_team"]
        away = game["away_team"]
        hr = safe_int(game.get("first_inning_runs_home", 0))
        ar = safe_int(game.get("first_inning_runs_away", 0))
        yrfi = (hr + ar) > 0

        # Home team
        td_home = team_data[home]
        td_home["home_games"] += 1
        td_home["runs_scored_1st"] += hr
        td_home["runs_allowed_1st"] += ar
        if yrfi:
            td_home["home_yrfi"] += 1

        # Away team
        td_away = team_data[away]
        td_away["away_games"] += 1
        td_away["runs_scored_1st"] += ar
        td_away["runs_allowed_1st"] += hr
        if yrfi:
            td_away["away_yrfi"] += 1

    stats = {}
    for team, td in team_data.items():
        total = td["home_games"] + td["away_games"]
        total_yrfi = td["home_yrfi"] + td["away_yrfi"]
        stats[team] = {
            "team": team,
            "season": season,
            "games_played": total,
            "runs_scored_first_inning_total": td["runs_scored_1st"],
            "runs_allowed_first_inning_total": td["runs_allowed_1st"],
            "yrfi_pct_home": round(td["home_yrfi"] / td["home_games"] * 100, 1) if td["home_games"] > 0 else 0,
            "yrfi_pct_away": round(td["away_yrfi"] / td["away_games"] * 100, 1) if td["away_games"] > 0 else 0,
            "yrfi_pct_overall": round(total_yrfi / total * 100, 1) if total > 0 else 0,
            "avg_runs_first_inning": round((td["runs_scored_1st"]) / total, 3) if total > 0 else 0,
        }

    return stats


def build_park_factors(games: list, season: int) -> dict:
    """Build venue-specific first-inning data."""
    venue_data = defaultdict(lambda: {"games": 0, "total_runs": 0, "yrfi": 0})

    for game in games:
        venue = game.get("venue", "Unknown")
        hr = safe_int(game.get("first_inning_runs_home", 0))
        ar = safe_int(game.get("first_inning_runs_away", 0))
        vd = venue_data[venue]
        vd["games"] += 1
        vd["total_runs"] += hr + ar
        if (hr + ar) > 0:
            vd["yrfi"] += 1

    factors = {}
    for venue, vd in venue_data.items():
        venue_info = get_venue_info(venue)
        factors[venue] = {
            "venue": venue,
            "season": season,
            "total_games": vd["games"],
            "avg_first_inning_runs": round(vd["total_runs"] / vd["games"], 3) if vd["games"] > 0 else 0,
            "yrfi_pct_at_venue": round(vd["yrfi"] / vd["games"] * 100, 1) if vd["games"] > 0 else 0,
            "elevation": venue_info.get("elevation", 0),
            "is_dome": venue_info.get("is_dome", False),
        }

    return factors


def generate_sql(games: list, pitchers: dict, team_stats: dict, park_factors: dict) -> str:
    """Generate SQL INSERT/UPSERT statements for all data."""
    sql_parts = []

    # Games
    for g in games:
        sql_parts.append(f"""
INSERT INTO mlb_games (game_id, date, home_team, away_team, venue, game_time_et,
    home_pitcher_id, away_pitcher_id, home_pitcher_name, away_pitcher_name,
    first_inning_runs_home, first_inning_runs_away,
    final_score_home, final_score_away, is_dome, game_status)
VALUES ({g['game_id']}, '{g['date']}', '{g['home_team']}', '{g['away_team']}',
    '{g['venue'].replace("'", "''")}', '{g.get('game_time_et', '')}',
    {g['home_pitcher_id'] or 'NULL'}, {g['away_pitcher_id'] or 'NULL'},
    {_sql_str(g.get('home_pitcher_name'))}, {_sql_str(g.get('away_pitcher_name'))},
    {g['first_inning_runs_home']}, {g['first_inning_runs_away']},
    {g.get('final_score_home') or 'NULL'}, {g.get('final_score_away') or 'NULL'},
    {g['is_dome']}, '{g['game_status']}')
ON CONFLICT (game_id) DO UPDATE SET
    first_inning_runs_home = EXCLUDED.first_inning_runs_home,
    first_inning_runs_away = EXCLUDED.first_inning_runs_away,
    final_score_home = EXCLUDED.final_score_home,
    final_score_away = EXCLUDED.final_score_away,
    game_status = EXCLUDED.game_status;""")

    # Pitchers
    for p in pitchers.values():
        sql_parts.append(f"""
INSERT INTO mlb_pitchers (pitcher_id, season, name, team,
    first_inning_era, first_inning_runs_allowed_total,
    first_inning_games, first_inning_scoreless_pct)
VALUES ({p['pitcher_id']}, {p['season']}, {_sql_str(p['name'])}, '{p['team']}',
    {p['first_inning_era']}, {p['first_inning_runs_allowed_total']},
    {p['first_inning_games']}, {p['first_inning_scoreless_pct']})
ON CONFLICT (pitcher_id, season) DO UPDATE SET
    first_inning_era = EXCLUDED.first_inning_era,
    first_inning_runs_allowed_total = EXCLUDED.first_inning_runs_allowed_total,
    first_inning_games = EXCLUDED.first_inning_games,
    first_inning_scoreless_pct = EXCLUDED.first_inning_scoreless_pct,
    last_updated = NOW();""")

    # Team stats
    for ts in team_stats.values():
        sql_parts.append(f"""
INSERT INTO mlb_team_stats (team, season, games_played,
    runs_scored_first_inning_total, runs_allowed_first_inning_total,
    yrfi_pct_home, yrfi_pct_away, yrfi_pct_overall, avg_runs_first_inning)
VALUES ('{ts['team']}', {ts['season']}, {ts['games_played']},
    {ts['runs_scored_first_inning_total']}, {ts['runs_allowed_first_inning_total']},
    {ts['yrfi_pct_home']}, {ts['yrfi_pct_away']}, {ts['yrfi_pct_overall']},
    {ts['avg_runs_first_inning']})
ON CONFLICT (team, season) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    runs_scored_first_inning_total = EXCLUDED.runs_scored_first_inning_total,
    runs_allowed_first_inning_total = EXCLUDED.runs_allowed_first_inning_total,
    yrfi_pct_home = EXCLUDED.yrfi_pct_home,
    yrfi_pct_away = EXCLUDED.yrfi_pct_away,
    yrfi_pct_overall = EXCLUDED.yrfi_pct_overall,
    avg_runs_first_inning = EXCLUDED.avg_runs_first_inning,
    last_updated = NOW();""")

    # Park factors
    for pf in park_factors.values():
        sql_parts.append(f"""
INSERT INTO mlb_park_factors (venue, season, total_games,
    avg_first_inning_runs, yrfi_pct_at_venue, elevation, is_dome)
VALUES ('{pf['venue'].replace("'", "''")}', {pf['season']}, {pf['total_games']},
    {pf['avg_first_inning_runs']}, {pf['yrfi_pct_at_venue']},
    {pf['elevation']}, {pf['is_dome']})
ON CONFLICT (venue, season) DO UPDATE SET
    total_games = EXCLUDED.total_games,
    avg_first_inning_runs = EXCLUDED.avg_first_inning_runs,
    yrfi_pct_at_venue = EXCLUDED.yrfi_pct_at_venue;""")

    return "\n".join(sql_parts)


def _sql_str(val) -> str:
    """Format a value as a SQL string or NULL."""
    if val is None:
        return "NULL"
    return f"'{str(val).replace(chr(39), chr(39)+chr(39))}'"


def main():
    parser = argparse.ArgumentParser(description="Backfill historical YRFI/NRFI data")
    parser.add_argument("--season", type=int, default=2025, help="Season to fetch")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="sql", choices=["sql", "json"],
                        help="Output format")
    args = parser.parse_args()

    print(f"-- Fetching {args.season} season data...", file=sys.stderr)

    games = list(fetch_season_games(args.season, args.start_date, args.end_date))
    print(f"-- Fetched {len(games)} completed games", file=sys.stderr)

    if not games:
        print("-- No games found for this period", file=sys.stderr)
        return

    pitchers = build_pitcher_profiles(games, args.season)
    print(f"-- Built {len(pitchers)} pitcher profiles", file=sys.stderr)

    team_stats = build_team_stats(games, args.season)
    print(f"-- Built {len(team_stats)} team profiles", file=sys.stderr)

    park_factors = build_park_factors(games, args.season)
    print(f"-- Built {len(park_factors)} park factor profiles", file=sys.stderr)

    if args.output == "json":
        output = {
            "season": args.season,
            "games_count": len(games),
            "games": games,
            "pitchers": list(pitchers.values()),
            "team_stats": list(team_stats.values()),
            "park_factors": list(park_factors.values()),
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(generate_sql(games, pitchers, team_stats, park_factors))

    print(f"-- Done! {len(games)} games, {len(pitchers)} pitchers, "
          f"{len(team_stats)} teams, {len(park_factors)} venues", file=sys.stderr)


if __name__ == "__main__":
    main()
