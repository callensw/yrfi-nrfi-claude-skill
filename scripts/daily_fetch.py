"""
YRFI/NRFI Daily Data Fetch
Pull today's matchups, probable pitchers, lineups, and weather.
Safe to run multiple times per day (upserts, not duplicates).

Usage:
    python3 daily_fetch.py [--date 2026-04-15]

Outputs JSON with all fetched data for today's slate.
"""

import sys
import os
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    mlb_get, get_schedule, get_linescore, get_boxscore,
    get_pitcher_season_stats, get_pitcher_game_log, get_pitcher_info,
    get_batter_season_stats, get_batter_splits,
    extract_lineup_from_boxscore, get_weather, get_venue_info,
    team_abbrev, safe_float, safe_int, today_str, format_game_time,
    calculate_era, calculate_whip,
)


def fetch_todays_games(date: str) -> list:
    """Fetch today's schedule with probable pitchers."""
    games = get_schedule(date, hydrate="probablePitcher,linescore")
    if not games:
        print(f"No games found for {date}", file=sys.stderr)
        return []

    results = []
    for game in games:
        game_pk = game.get("gamePk")
        status = game.get("status", {}).get("abstractGameState", "Preview")
        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        venue = game.get("venue", {})

        home_pitcher = home.get("probablePitcher", {})
        away_pitcher = away.get("probablePitcher", {})
        venue_name = venue.get("name", "Unknown")
        venue_info = get_venue_info(venue_name)

        result = {
            "game_id": game_pk,
            "date": date,
            "status": status,
            "home_team": team_abbrev(home.get("team", {}).get("name", "")),
            "away_team": team_abbrev(away.get("team", {}).get("name", "")),
            "home_team_full": home.get("team", {}).get("name", ""),
            "away_team_full": away.get("team", {}).get("name", ""),
            "venue": venue_name,
            "venue_info": venue_info,
            "game_time": game.get("gameDate", ""),
            "game_time_et": format_game_time(game.get("gameDate", "")),
            "home_pitcher": {
                "id": home_pitcher.get("id"),
                "name": home_pitcher.get("fullName", "TBD"),
            },
            "away_pitcher": {
                "id": away_pitcher.get("id"),
                "name": away_pitcher.get("fullName", "TBD"),
            },
            "is_dome": venue_info.get("is_dome", False),
        }

        results.append(result)

    return results


def fetch_pitcher_profile(pitcher_id: int, current_season: int) -> dict:
    """
    Build a comprehensive pitcher profile with first-inning data.
    Uses current season + last 2 seasons weighted (60/25/15).
    """
    if not pitcher_id:
        return {"id": None, "name": "TBD", "available": False}

    # Get basic info
    info = get_pitcher_info(pitcher_id)
    if not info:
        return {"id": pitcher_id, "name": "Unknown", "available": False}

    profile = {
        "id": pitcher_id,
        "name": info.get("fullName", "Unknown"),
        "team": info.get("currentTeam", {}).get("name", ""),
        "throws": info.get("pitchHand", {}).get("code", "R"),
        "available": True,
        "seasons": {},
    }

    # Fetch stats for current + 2 prior seasons
    weights = {current_season: 0.60, current_season - 1: 0.25, current_season - 2: 0.15}

    for season, weight in weights.items():
        stats = get_pitcher_season_stats(pitcher_id, season)
        if not stats:
            continue

        era = safe_float(stats.get("era"))
        whip = safe_float(stats.get("whip"))
        ip = safe_float(stats.get("inningsPitched"))
        k9 = safe_float(stats.get("strikeoutsPer9Inn"))
        bb9 = safe_float(stats.get("walksPer9Inn"))
        hr9 = safe_float(stats.get("homeRunsPer9"))
        gs = safe_int(stats.get("gamesStarted"))

        profile["seasons"][season] = {
            "season": season,
            "weight": weight,
            "era": era,
            "whip": whip,
            "innings_pitched": ip,
            "k_per_9": k9,
            "bb_per_9": bb9,
            "hr_per_9": hr9,
            "games_started": gs,
        }

    # Get current season stats as primary
    current = profile["seasons"].get(current_season, {})
    profile["era"] = current.get("era", 0)
    profile["whip"] = current.get("whip", 0)
    profile["k_per_9"] = current.get("k_per_9", 0)
    profile["bb_per_9"] = current.get("bb_per_9", 0)
    profile["hr_per_9"] = current.get("hr_per_9", 0)
    profile["innings_pitched"] = current.get("innings_pitched", 0)

    return profile


def fetch_first_inning_stats_from_games(pitcher_id: int, season: int, game_results: list = None) -> dict:
    """
    Calculate first-inning-specific stats from game-by-game data.
    If game_results are provided (from Supabase), use those.
    Otherwise, attempts to derive from game log (less reliable).
    """
    if not pitcher_id:
        return {}

    # This would ideally query Supabase for historical game data
    # where this pitcher started, and aggregate first-inning runs allowed.
    # For now, return a placeholder that the SKILL.md instructs Claude to
    # populate via Supabase queries.
    return {
        "pitcher_id": pitcher_id,
        "season": season,
        "note": "Query Supabase mlb_games + mlb_pitchers for first-inning splits",
    }


def fetch_lineup(game_pk: int, team_type: str, date: str) -> dict:
    """
    Attempt to get the lineup for a team in a game.
    Returns lineup data if available, or a flag indicating it's not confirmed.
    """
    boxscore = get_boxscore(game_pk)
    if not boxscore:
        return {"confirmed": False, "lineup": [], "source": "unavailable"}

    lineup = extract_lineup_from_boxscore(boxscore, team_type)

    if not lineup:
        return {"confirmed": False, "lineup": [], "source": "not_posted"}

    return {
        "confirmed": True,
        "lineup": lineup,
        "top_4": lineup[:4] if len(lineup) >= 4 else lineup,
        "source": "mlb_boxscore",
    }


def fetch_weather_for_game(venue_info: dict) -> dict:
    """Get weather for a venue if it's an outdoor park."""
    if venue_info.get("is_dome"):
        return {
            "temp": 72,
            "humidity": 50,
            "wind_speed": 0,
            "wind_deg": 0,
            "description": "dome (climate controlled)",
            "is_dome": True,
        }

    lat = venue_info.get("lat", 0)
    lon = venue_info.get("lon", 0)
    if lat == 0 and lon == 0:
        return {"available": False}

    weather = get_weather(lat, lon)
    if weather:
        weather["is_dome"] = False
        return weather

    return {"available": False, "is_dome": False}


def build_game_sql(game: dict) -> str:
    """Generate upsert SQL for a game."""
    hp = game.get("home_pitcher", {})
    ap = game.get("away_pitcher", {})
    w = game.get("weather", {})

    return f"""
INSERT INTO mlb_games (game_id, date, home_team, away_team, venue, game_time_et,
    home_pitcher_id, away_pitcher_id, home_pitcher_name, away_pitcher_name,
    weather_temp, weather_wind_speed, weather_wind_dir, weather_humidity,
    is_dome, game_status)
VALUES ({game['game_id']}, '{game['date']}',
    '{game['home_team']}', '{game['away_team']}',
    '{game['venue'].replace("'", "''")}', '{game.get('game_time_et', '')}',
    {hp.get('id') or 'NULL'}, {ap.get('id') or 'NULL'},
    {_sql_str(hp.get('name'))}, {_sql_str(ap.get('name'))},
    {w.get('temp') or 'NULL'}, {w.get('wind_speed') or 'NULL'},
    {w.get('wind_deg') or 'NULL'}, {w.get('humidity') or 'NULL'},
    {game.get('is_dome', False)}, '{game.get('status', 'Preview')}')
ON CONFLICT (game_id) DO UPDATE SET
    home_pitcher_id = EXCLUDED.home_pitcher_id,
    away_pitcher_id = EXCLUDED.away_pitcher_id,
    home_pitcher_name = EXCLUDED.home_pitcher_name,
    away_pitcher_name = EXCLUDED.away_pitcher_name,
    weather_temp = EXCLUDED.weather_temp,
    weather_wind_speed = EXCLUDED.weather_wind_speed,
    weather_wind_dir = EXCLUDED.weather_wind_dir,
    weather_humidity = EXCLUDED.weather_humidity,
    game_status = EXCLUDED.game_status;"""


def _sql_str(val) -> str:
    if val is None:
        return "NULL"
    return f"'{str(val).replace(chr(39), chr(39)+chr(39))}'"


def main():
    parser = argparse.ArgumentParser(description="Fetch today's MLB data for YRFI/NRFI analysis")
    parser.add_argument("--date", type=str, default=None, help="Date to fetch (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="json", choices=["json", "sql"],
                        help="Output format")
    parser.add_argument("--skip-weather", action="store_true", help="Skip weather fetching")
    parser.add_argument("--skip-lineups", action="store_true", help="Skip lineup fetching")
    args = parser.parse_args()

    date = args.date or today_str()
    current_season = int(date[:4])

    print(f"Fetching data for {date}...", file=sys.stderr)

    # Step 1: Get today's games
    games = fetch_todays_games(date)
    print(f"Found {len(games)} games", file=sys.stderr)

    if not games:
        if args.output == "json":
            print(json.dumps({"date": date, "games": [], "message": "No games today"}))
        return

    # Step 2: Enrich each game
    for i, game in enumerate(games):
        print(f"  [{i+1}/{len(games)}] {game['away_team']} @ {game['home_team']}...",
              file=sys.stderr)

        # Pitcher profiles
        game["home_pitcher_profile"] = fetch_pitcher_profile(
            game["home_pitcher"]["id"], current_season
        )
        game["away_pitcher_profile"] = fetch_pitcher_profile(
            game["away_pitcher"]["id"], current_season
        )

        # Weather
        if not args.skip_weather:
            game["weather"] = fetch_weather_for_game(game["venue_info"])
        else:
            game["weather"] = {"available": False}

        # Lineups (usually not available until ~2hrs before game)
        if not args.skip_lineups:
            game["home_lineup"] = fetch_lineup(game["game_id"], "home", date)
            game["away_lineup"] = fetch_lineup(game["game_id"], "away", date)
        else:
            game["home_lineup"] = {"confirmed": False, "lineup": []}
            game["away_lineup"] = {"confirmed": False, "lineup": []}

    # Output
    if args.output == "json":
        output = {
            "date": date,
            "season": current_season,
            "games_count": len(games),
            "games": games,
            "fetch_time": datetime.utcnow().isoformat() + "Z",
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        # SQL output
        for game in games:
            print(build_game_sql(game))

    print(f"Done! Enriched {len(games)} games", file=sys.stderr)


if __name__ == "__main__":
    main()
