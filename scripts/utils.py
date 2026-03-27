"""
YRFI/NRFI Analysis Utilities
Shared helpers for MLB data fetching, Supabase client, and formatting.
"""

import os
import json
import time
import httpx
from datetime import datetime, timedelta, timezone

# ── Supabase Config ──────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://kakjbyoxqjvwnsdbqcnb.supabase.co"
)
SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtha2pieW94cWp2d25zZGJxY25iIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk0NzQxMjgsImV4cCI6MjA4NTA1MDEyOH0.6kkaabg_8D2qKcIsuEUVuZWja3LIdx8-a2wwoTmu30k",
)

# ── MLB Stats API ────────────────────────────────────────────────────────────
MLB_BASE = "https://statsapi.mlb.com/api/v1"
REQUEST_TIMEOUT = 30
RATE_LIMIT_DELAY = 0.25  # seconds between API calls

_last_request_time = 0


def _rate_limit():
    """Simple rate limiter for MLB API."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    _last_request_time = time.time()


def mlb_get(endpoint: str, params: dict = None) -> dict | None:
    """GET from MLB Stats API with rate limiting and error handling."""
    _rate_limit()
    url = f"{MLB_BASE}{endpoint}"
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[MLB API Error] {url}: {e}")
        return None


# ── Schedule & Games ─────────────────────────────────────────────────────────

def get_schedule(date: str, hydrate: str = None) -> list:
    """
    Get MLB schedule for a date (YYYY-MM-DD).
    Returns list of game dicts.
    hydrate options: "probablePitcher", "lineup", "probablePitcher,lineup"
    """
    params = {"date": date, "sportId": 1}
    if hydrate:
        params["hydrate"] = hydrate
    data = mlb_get("/schedule", params)
    if not data or not data.get("dates"):
        return []
    games = []
    for d in data["dates"]:
        games.extend(d.get("games", []))
    return games


def get_linescore(game_pk: int) -> dict | None:
    """Get linescore for a game (inning-by-inning breakdown)."""
    return mlb_get(f"/game/{game_pk}/linescore")


def get_boxscore(game_pk: int) -> dict | None:
    """Get full boxscore for a game."""
    return mlb_get(f"/game/{game_pk}/boxscore")


def get_game_feed(game_pk: int) -> dict | None:
    """Get live game feed (comprehensive game data)."""
    return mlb_get(f"/game/{game_pk}/feed/live")


def extract_first_inning_runs(linescore: dict) -> tuple:
    """
    Extract first-inning runs from a linescore.
    Returns (away_runs, home_runs) or (None, None) if unavailable.
    """
    if not linescore:
        return None, None
    innings = linescore.get("innings", [])
    if not innings:
        return None, None
    first = innings[0]
    away = first.get("away", {}).get("runs")
    home = first.get("home", {}).get("runs")
    return away, home


# ── Pitcher Stats ────────────────────────────────────────────────────────────

def get_pitcher_season_stats(pitcher_id: int, season: int) -> dict | None:
    """Get a pitcher's season pitching stats."""
    data = mlb_get(
        f"/people/{pitcher_id}/stats",
        {"stats": "season", "group": "pitching", "season": season},
    )
    if not data:
        return None
    stats = data.get("stats", [])
    if not stats or not stats[0].get("splits"):
        return None
    return stats[0]["splits"][0].get("stat", {})


def get_pitcher_game_log(pitcher_id: int, season: int) -> list:
    """Get a pitcher's game-by-game log for a season."""
    data = mlb_get(
        f"/people/{pitcher_id}/stats",
        {"stats": "gameLog", "group": "pitching", "season": season},
    )
    if not data:
        return []
    stats = data.get("stats", [])
    if not stats or not stats[0].get("splits"):
        return []
    return stats[0]["splits"]


def get_pitcher_splits(pitcher_id: int, season: int, sit_codes: str = None) -> list:
    """
    Get pitcher splits (vs LHB, vs RHB, home/away, etc.)
    sit_codes: e.g., "vl" (vs left), "vr" (vs right), "h" (home), "a" (away)
    """
    params = {"stats": "statSplits", "group": "pitching", "season": season}
    if sit_codes:
        params["sitCodes"] = sit_codes
    data = mlb_get(f"/people/{pitcher_id}/stats", params)
    if not data:
        return []
    stats = data.get("stats", [])
    if not stats or not stats[0].get("splits"):
        return []
    return stats[0]["splits"]


def get_pitcher_info(pitcher_id: int) -> dict | None:
    """Get basic pitcher info (name, team, handedness)."""
    data = mlb_get(f"/people/{pitcher_id}")
    if not data or not data.get("people"):
        return None
    return data["people"][0]


# ── Batter Stats ─────────────────────────────────────────────────────────────

def get_batter_season_stats(batter_id: int, season: int) -> dict | None:
    """Get a batter's season hitting stats."""
    data = mlb_get(
        f"/people/{batter_id}/stats",
        {"stats": "season", "group": "hitting", "season": season},
    )
    if not data:
        return None
    stats = data.get("stats", [])
    if not stats or not stats[0].get("splits"):
        return None
    return stats[0]["splits"][0].get("stat", {})


def get_batter_splits(batter_id: int, season: int, sit_codes: str = None) -> list:
    """Get batter splits (vs LHP, vs RHP, etc.)"""
    params = {"stats": "statSplits", "group": "hitting", "season": season}
    if sit_codes:
        params["sitCodes"] = sit_codes
    data = mlb_get(f"/people/{batter_id}/stats", params)
    if not data:
        return []
    stats = data.get("stats", [])
    if not stats or not stats[0].get("splits"):
        return []
    return stats[0]["splits"]


# ── Lineups ──────────────────────────────────────────────────────────────────

def extract_lineup_from_boxscore(boxscore: dict, team_type: str) -> list:
    """
    Extract batting order from boxscore.
    team_type: "home" or "away"
    Returns list of player dicts with battingOrder, id, name.
    """
    if not boxscore:
        return []
    teams = boxscore.get("teams", {})
    team = teams.get(team_type, {})
    players = team.get("players", {})
    lineup = []
    for pid, pdata in players.items():
        order = pdata.get("battingOrder")
        if order:
            person = pdata.get("person", {})
            lineup.append({
                "batting_order": int(str(order)[0]),  # 100 -> 1, 200 -> 2, etc.
                "player_id": person.get("id"),
                "name": person.get("fullName", "Unknown"),
                "position": pdata.get("position", {}).get("abbreviation", ""),
                "stats": pdata.get("stats", {}),
            })
    lineup.sort(key=lambda x: x["batting_order"])
    return lineup


# ── Weather ──────────────────────────────────────────────────────────────────

OPENWEATHER_KEY = os.environ.get("OPENWEATHER_API_KEY", "")


def get_weather(lat: float, lon: float) -> dict | None:
    """Get current weather for coordinates. Requires OPENWEATHER_API_KEY env var."""
    if not OPENWEATHER_KEY:
        return None
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": OPENWEATHER_KEY,
                    "units": "imperial",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            wind = data.get("wind", {})
            main = data.get("main", {})
            return {
                "temp": main.get("temp"),
                "humidity": main.get("humidity"),
                "wind_speed": wind.get("speed"),
                "wind_deg": wind.get("deg"),
                "description": data.get("weather", [{}])[0].get("description", ""),
            }
    except Exception as e:
        print(f"[Weather API Error]: {e}")
        return None


# ── Venue Data ───────────────────────────────────────────────────────────────

VENUES = {
    "Coors Field": {"lat": 39.756, "lon": -104.994, "is_dome": False, "elevation": 5280},
    "Chase Field": {"lat": 33.445, "lon": -112.067, "is_dome": True, "elevation": 1082},
    "Tropicana Field": {"lat": 27.768, "lon": -82.653, "is_dome": True, "elevation": 44},
    "Minute Maid Park": {"lat": 29.757, "lon": -95.356, "is_dome": True, "elevation": 42},
    "T-Mobile Park": {"lat": 47.591, "lon": -122.333, "is_dome": True, "elevation": 20},
    "Rogers Centre": {"lat": 43.641, "lon": -79.389, "is_dome": True, "elevation": 269},
    "loanDepot park": {"lat": 25.778, "lon": -80.220, "is_dome": True, "elevation": 6},
    "Globe Life Field": {"lat": 32.747, "lon": -97.084, "is_dome": True, "elevation": 541},
    "American Family Field": {"lat": 43.028, "lon": -87.971, "is_dome": True, "elevation": 601},
    "Yankee Stadium": {"lat": 40.829, "lon": -73.926, "is_dome": False, "elevation": 20},
    "Dodger Stadium": {"lat": 34.074, "lon": -118.240, "is_dome": False, "elevation": 515},
    "Fenway Park": {"lat": 42.346, "lon": -71.097, "is_dome": False, "elevation": 20},
    "Wrigley Field": {"lat": 41.948, "lon": -87.656, "is_dome": False, "elevation": 600},
    "Oracle Park": {"lat": 37.778, "lon": -122.389, "is_dome": False, "elevation": 5},
    "Petco Park": {"lat": 32.707, "lon": -117.157, "is_dome": False, "elevation": 15},
    "Busch Stadium": {"lat": 38.623, "lon": -90.193, "is_dome": False, "elevation": 455},
    "Citizens Bank Park": {"lat": 39.906, "lon": -75.167, "is_dome": False, "elevation": 20},
    "Great American Ball Park": {"lat": 39.097, "lon": -84.507, "is_dome": False, "elevation": 490},
    "Target Field": {"lat": 44.982, "lon": -93.278, "is_dome": False, "elevation": 830},
    "Guaranteed Rate Field": {"lat": 41.830, "lon": -87.634, "is_dome": False, "elevation": 595},
    "Kauffman Stadium": {"lat": 39.051, "lon": -94.481, "is_dome": False, "elevation": 820},
    "Angel Stadium": {"lat": 33.800, "lon": -117.883, "is_dome": False, "elevation": 157},
    "Oakland Coliseum": {"lat": 37.751, "lon": -122.201, "is_dome": False, "elevation": 5},
    "Nationals Park": {"lat": 38.873, "lon": -77.007, "is_dome": False, "elevation": 25},
    "Truist Park": {"lat": 33.891, "lon": -84.468, "is_dome": False, "elevation": 1050},
    "Comerica Park": {"lat": 42.339, "lon": -83.049, "is_dome": False, "elevation": 600},
    "PNC Park": {"lat": 40.447, "lon": -80.006, "is_dome": False, "elevation": 730},
    "Citi Field": {"lat": 40.757, "lon": -73.846, "is_dome": False, "elevation": 15},
    "Camden Yards": {"lat": 39.284, "lon": -76.622, "is_dome": False, "elevation": 30},
    "Progressive Field": {"lat": 41.496, "lon": -81.685, "is_dome": False, "elevation": 650},
}


def get_venue_info(venue_name: str) -> dict:
    """Get venue metadata. Falls back to defaults for unknown venues."""
    for name, info in VENUES.items():
        if name.lower() in venue_name.lower() or venue_name.lower() in name.lower():
            return {**info, "name": name}
    return {"lat": 0, "lon": 0, "is_dome": False, "elevation": 0, "name": venue_name}


# ── Team Abbreviations ──────────────────────────────────────────────────────

TEAM_ABBREVS = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}


def team_abbrev(full_name: str) -> str:
    """Convert full team name to abbreviation."""
    return TEAM_ABBREVS.get(full_name, full_name[:3].upper())


# ── Helpers ──────────────────────────────────────────────────────────────────

def safe_float(val, default: float = 0.0) -> float:
    """Safely convert to float."""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def safe_int(val, default: int = 0) -> int:
    """Safely convert to int."""
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def today_str() -> str:
    """Today's date as YYYY-MM-DD in US Eastern."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def format_game_time(game_datetime_str: str) -> str:
    """Convert MLB API datetime string to ET display time."""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(game_datetime_str.replace("Z", "+00:00"))
        et = dt.astimezone(ZoneInfo("America/New_York"))
        return et.strftime("%-I:%M ET")
    except Exception:
        return game_datetime_str


def calculate_era(earned_runs: float, innings: float) -> float:
    """Calculate ERA from earned runs and innings pitched."""
    if innings <= 0:
        return 0.0
    return (earned_runs / innings) * 9.0


def calculate_whip(walks: int, hits: int, innings: float) -> float:
    """Calculate WHIP."""
    if innings <= 0:
        return 0.0
    return (walks + hits) / innings


def print_json(data):
    """Pretty print JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))
