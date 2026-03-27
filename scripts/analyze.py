"""
YRFI/NRFI Core Analysis Engine
Weighted multi-factor model with circuit breaker overrides.

Usage:
    python3 analyze.py [--date 2026-04-15] [--game-id 12345] [--input games.json]

Can read game data from:
  1. A JSON file (output of daily_fetch.py)
  2. Stdin (piped from daily_fetch.py)
  3. A specific game ID (fetches from MLB API)

Outputs formatted pick cards to stdout.
"""

import sys
import os
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import safe_float, safe_int, today_str

# ── XGBoost Model Integration ────────────────────────────────────────────────
_XGB_MODEL = None
_XGB_CONFIG = None


def _load_xgb_model():
    """Lazy-load the XGBoost model and config."""
    global _XGB_MODEL, _XGB_CONFIG
    if _XGB_MODEL is not None:
        return _XGB_MODEL, _XGB_CONFIG
    try:
        import joblib
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models")
        model_path = os.path.join(models_dir, "yrfi_xgboost.joblib")
        config_path = os.path.join(models_dir, "model_config.json")
        if os.path.exists(model_path) and os.path.exists(config_path):
            _XGB_MODEL = joblib.load(model_path)
            with open(config_path) as f:
                _XGB_CONFIG = json.load(f)
            return _XGB_MODEL, _XGB_CONFIG
    except Exception as e:
        print(f"[XGBoost] Could not load model: {e}", file=sys.stderr)
    return None, None


def xgb_predict(game: dict) -> dict | None:
    """
    Run XGBoost prediction on a game dict.
    Extracts features from the game data and returns probability + tier.
    """
    model, config = _load_xgb_model()
    if model is None or config is None:
        return None

    try:
        import numpy as np

        feature_map = config["feature_map"]
        feature_names = config["feature_names"]
        tiers = config["confidence_tiers"]

        # Extract features from game dict, mapping to model's expected inputs
        features = {}
        for friendly, db_col in feature_map.items():
            val = _extract_game_feature(game, friendly, db_col)
            features[friendly] = val

        # Build feature array in correct order
        X = np.array([[features.get(f, 0.0) for f in feature_names]])
        proba = float(model.predict_proba(X)[0][1])

        # Classify into tier
        tier = "Skip"
        for tier_name, (low, high) in tiers.items():
            if low <= proba < high:
                tier = tier_name
                break

        # Determine pick direction
        if "YRFI" in tier:
            pick = "YRFI"
        elif "NRFI" in tier:
            pick = "NRFI"
        else:
            pick = "SKIP"

        return {
            "probability": round(proba, 4),
            "tier": tier,
            "pick": pick,
            "model_version": config.get("model_version", "unknown"),
        }
    except Exception as e:
        print(f"[XGBoost] Prediction error: {e}", file=sys.stderr)
        return None


def _extract_game_feature(game: dict, friendly: str, db_col: str) -> float:
    """Extract a single feature value from the game dict for XGBoost."""
    # Map friendly names to where the data lives in the game dict
    fi_home = game.get("home_pitcher_fi", {})
    fi_away = game.get("away_pitcher_fi", {})
    prof_home = game.get("home_pitcher_profile", {})
    prof_away = game.get("away_pitcher_profile", {})
    park = game.get("park_factor", {})
    weather = game.get("weather", {})

    mapping = {
        "combined_scoreless_pct": lambda: (
            safe_float(fi_home.get("first_inning_scoreless_pct", 50)) +
            safe_float(fi_away.get("first_inning_scoreless_pct", 50))
        ) / 2.0,
        "combined_fi_era": lambda: (
            safe_float(fi_home.get("first_inning_era", 4.5)) +
            safe_float(fi_away.get("first_inning_era", 4.5))
        ) / 2.0,
        "home_p_era_delta": lambda: safe_float(fi_home.get("first_inning_era_delta", 0)),
        "away_p_era_delta": lambda: safe_float(fi_away.get("first_inning_era_delta", 0)),
        "home_p_scoreless_pct": lambda: safe_float(fi_home.get("first_inning_scoreless_pct", 50)),
        "away_p_scoreless_pct": lambda: safe_float(fi_away.get("first_inning_scoreless_pct", 50)),
        "home_p_k9": lambda: safe_float(prof_home.get("k_per_9", 8.0)),
        "away_p_k9": lambda: safe_float(prof_away.get("k_per_9", 8.0)),
        "home_p_bb9": lambda: safe_float(prof_home.get("bb_per_9", 3.0)),
        "away_p_bb9": lambda: safe_float(prof_away.get("bb_per_9", 3.0)),
        "home_p_fi_era": lambda: safe_float(fi_home.get("first_inning_era", 4.5)),
        "away_p_fi_era": lambda: safe_float(fi_away.get("first_inning_era", 4.5)),
        "home_team_yrfi_pct": lambda: safe_float(game.get("home_team_stats", {}).get("yrfi_pct_home", 50)),
        "away_team_yrfi_pct": lambda: safe_float(game.get("away_team_stats", {}).get("yrfi_pct_away", 50)),
        "park_yrfi_pct": lambda: safe_float(park.get("yrfi_pct_at_venue", 50)),
        "is_dome": lambda: 1.0 if weather.get("is_dome") else 0.0,
        "vegas_over_under": lambda: safe_float(game.get("vegas_over_under", 8.5)),
        "era_delta_x_park": lambda: (
            safe_float(fi_home.get("first_inning_era_delta", 0)) *
            safe_float(park.get("park_factor_runs", 1.0))
        ),
        "pitcher_era_gap": lambda: abs(
            safe_float(fi_home.get("first_inning_era", 4.5)) -
            safe_float(fi_away.get("first_inning_era", 4.5))
        ),
    }

    extractor = mapping.get(friendly)
    if extractor:
        try:
            return float(extractor())
        except (TypeError, ValueError):
            return 0.0
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# FACTOR WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

WEIGHTS = {
    # Tier 1 — ~50%
    "pitcher_first_inning":   0.25,  # Both pitchers' 1st-inning ERA, WHIP, scoreless%
    "slow_starter_delta":     0.10,  # ERA delta (1st-inn ERA - overall ERA)
    "top_4_gauntlet":         0.10,  # Top 4 hitters matchup analysis
    "recent_form":            0.05,  # Last 10 games 1st-inning scoring rate

    # Tier 2 — ~30%
    "park_factor":            0.10,  # Venue run environment
    "weather":                0.08,  # Temp, wind, humidity
    "pitcher_rest":           0.06,  # Days rest, workload
    "home_away_splits":       0.06,  # Pitcher/team home vs away 1st-inning splits

    # Tier 3 — ~15%
    "umpire":                 0.05,  # HP umpire tendencies
    "day_night":              0.03,  # Day vs night split
    "h2h_history":            0.03,  # Head-to-head familiarity
    "seasonal_timing":        0.04,  # Early season uncertainty, sample size

    # Tier 4 — ~5%
    "travel_schedule":        0.02,  # Travel fatigue, day-after-night
    "opener_detection":       0.02,  # Bullpen/opener game detection
    "injury_lineup_changes":  0.01,  # Late scratches, key bat missing
}


# ═══════════════════════════════════════════════════════════════════════════════
# FACTOR SCORING FUNCTIONS
# Each returns a score from 0-100 where:
#   0 = strongest NRFI signal
#   50 = neutral
#   100 = strongest YRFI signal
# ═══════════════════════════════════════════════════════════════════════════════

def score_pitcher_first_inning(game: dict) -> tuple:
    """
    Score both pitchers' first-inning quality.
    Lower ERA/WHIP/runs = lower score (NRFI lean).
    """
    reasons = []
    score = 50  # neutral baseline

    for side in ["home", "away"]:
        profile = game.get(f"{side}_pitcher_profile", {})
        fi = game.get(f"{side}_pitcher_fi", {})
        name = profile.get("name", "TBD")

        if not profile.get("available"):
            reasons.append(f"{name}: no data available")
            continue

        fi_era = safe_float(fi.get("first_inning_era"))
        fi_scoreless = safe_float(fi.get("first_inning_scoreless_pct"))
        fi_games = safe_int(fi.get("first_inning_games"))
        era = safe_float(profile.get("era"))
        whip = safe_float(profile.get("whip"))

        # Use overall stats if no first-inning-specific data
        if fi_games < 3:
            if era < 3.00:
                score -= 8
                reasons.append(f"{name}: elite ERA ({era:.2f}), limited 1st-inn data")
            elif era > 4.50:
                score += 8
                reasons.append(f"{name}: high ERA ({era:.2f}), limited 1st-inn data")
            continue

        # First-inning ERA scoring
        if fi_era < 2.00:
            score -= 12
            reasons.append(f"{name}: elite 1st-inn ERA ({fi_era:.2f})")
        elif fi_era < 3.00:
            score -= 6
            reasons.append(f"{name}: strong 1st-inn ERA ({fi_era:.2f})")
        elif fi_era > 5.00:
            score += 12
            reasons.append(f"{name}: poor 1st-inn ERA ({fi_era:.2f})")
        elif fi_era > 4.00:
            score += 6
            reasons.append(f"{name}: shaky 1st-inn ERA ({fi_era:.2f})")

        # Scoreless percentage
        if fi_scoreless > 80:
            score -= 5
        elif fi_scoreless < 55:
            score += 5

        # WHIP impact
        if whip > 1.40:
            score += 3
        elif whip < 1.05:
            score -= 3

    return max(0, min(100, score)), reasons


def score_slow_starter_delta(game: dict) -> tuple:
    """
    The 'Slow Starter' metric: gap between 1st-inning ERA and overall ERA.
    Delta > 1.0 = flagged as slow starter.
    """
    reasons = []
    score = 50
    slow_starters = []

    for side in ["home", "away"]:
        profile = game.get(f"{side}_pitcher_profile", {})
        fi = game.get(f"{side}_pitcher_fi", {})
        name = profile.get("name", "TBD")

        fi_era = safe_float(fi.get("first_inning_era"))
        overall_era = safe_float(profile.get("era"))
        fi_games = safe_int(fi.get("first_inning_games"))

        if fi_games < 5 or overall_era == 0:
            continue

        delta = fi_era - overall_era
        fi["first_inning_era_delta"] = round(delta, 2)

        if delta > 1.5:
            score += 15
            slow_starters.append(name)
            reasons.append(
                f"SLOW STARTER: {name} (1st-inn ERA {fi_era:.2f} vs {overall_era:.2f} overall, "
                f"delta {delta:+.2f})"
            )
        elif delta > 1.0:
            score += 10
            slow_starters.append(name)
            reasons.append(
                f"Slow Starter: {name} (delta {delta:+.2f})"
            )
        elif delta < -0.5:
            score -= 5
            reasons.append(f"{name}: strong 1st-inning specialist (delta {delta:+.2f})")

    game["_slow_starters"] = slow_starters
    return max(0, min(100, score)), reasons


def score_top_4_gauntlet(game: dict) -> tuple:
    """
    Analyze the top 4 hitters each team sends up in the 1st inning.
    High OBP/SLG top of order = YRFI lean.
    """
    reasons = []
    score = 50

    for side in ["home", "away"]:
        lineup_data = game.get(f"{side}_lineup", {})
        top_4 = lineup_data.get("top_4", [])
        pitcher_profile = game.get(
            f"{'away' if side == 'home' else 'home'}_pitcher_profile", {}
        )
        pitcher_throws = pitcher_profile.get("throws", "R")
        team = game.get(f"{side}_team", "???")

        if not top_4:
            reasons.append(f"{team}: lineup not available")
            continue

        confirmed = lineup_data.get("confirmed", False)
        if not confirmed:
            reasons.append(f"{team}: projected lineup (confidence reduced)")

        # Analyze top 4 hitters
        high_obp_count = 0
        high_power_count = 0
        high_k_count = 0

        for hitter in top_4:
            stats = hitter.get("stats", {})
            batting = stats.get("batting", {})
            obp = safe_float(batting.get("obp"))
            slg = safe_float(batting.get("slg"))
            avg = safe_float(batting.get("avg"))

            if obp > .360:
                high_obp_count += 1
            if slg > .480:
                high_power_count += 1

        if high_obp_count >= 3:
            score += 6
            reasons.append(f"{team}: {high_obp_count}/4 top hitters with .360+ OBP")
        elif high_obp_count == 0:
            score -= 4

        if high_power_count >= 2:
            score += 4
            reasons.append(f"{team}: {high_power_count} power bats in top 4")

    return max(0, min(100, score)), reasons


def score_recent_form(game: dict) -> tuple:
    """Score based on last 10 games 1st-inning scoring rate."""
    reasons = []
    score = 50

    for side in ["home", "away"]:
        team = game.get(f"{side}_team", "???")
        recent = game.get(f"{side}_recent_form", {})
        yrfi_rate = safe_float(recent.get("yrfi_rate_last_10"))
        games = safe_int(recent.get("games_last_10"))

        if games < 5:
            continue

        if yrfi_rate > 0.65:
            score += 5
            reasons.append(f"{team}: hot 1st-inning streak ({yrfi_rate*100:.0f}% YRFI last {games})")
        elif yrfi_rate < 0.35:
            score -= 5
            reasons.append(f"{team}: cold 1st-inning stretch ({yrfi_rate*100:.0f}% YRFI last {games})")

    return max(0, min(100, score)), reasons


def score_park_factor(game: dict) -> tuple:
    """Score venue run environment."""
    reasons = []
    score = 50
    venue = game.get("venue", "Unknown")
    park = game.get("park_factor", {})

    avg_fi_runs = safe_float(park.get("avg_first_inning_runs"))
    yrfi_pct = safe_float(park.get("yrfi_pct_at_venue"))
    elevation = safe_int(park.get("elevation", 0))

    if yrfi_pct > 55:
        score += 8
        reasons.append(f"{venue}: high YRFI venue ({yrfi_pct:.1f}%)")
    elif yrfi_pct > 50:
        score += 3
    elif yrfi_pct < 42:
        score -= 8
        reasons.append(f"{venue}: pitcher-friendly venue ({yrfi_pct:.1f}% YRFI)")
    elif yrfi_pct < 46:
        score -= 3

    if elevation > 4000:
        score += 5
        reasons.append(f"High elevation ({elevation} ft)")

    return max(0, min(100, score)), reasons


def score_weather(game: dict) -> tuple:
    """Score weather impact on scoring."""
    reasons = []
    score = 50
    w = game.get("weather", {})

    if w.get("is_dome"):
        reasons.append("Dome game — weather neutral")
        return 50, reasons

    if not w.get("temp"):
        return 50, ["Weather data unavailable"]

    temp = safe_float(w.get("temp"))
    wind = safe_float(w.get("wind_speed"))
    humidity = safe_float(w.get("humidity"))

    # Temperature: hot = more runs
    if temp > 85:
        score += 6
        reasons.append(f"Hot ({temp:.0f}°F) — ball carries")
    elif temp > 75:
        score += 2
    elif temp < 50:
        score -= 6
        reasons.append(f"Cold ({temp:.0f}°F) — suppresses offense")
    elif temp < 60:
        score -= 3

    # Wind: high wind out = more HR risk
    if wind > 15:
        score += 4
        reasons.append(f"Windy ({wind:.0f} mph)")
    elif wind > 10:
        score += 2

    # Humidity: high = ball doesn't carry as well (slight NRFI lean)
    if humidity > 80:
        score -= 2

    return max(0, min(100, score)), reasons


def score_pitcher_rest(game: dict) -> tuple:
    """Score based on pitcher rest days and workload."""
    reasons = []
    score = 50

    for side in ["home", "away"]:
        profile = game.get(f"{side}_pitcher_profile", {})
        name = profile.get("name", "TBD")
        rest = game.get(f"{side}_pitcher_rest", {})
        days = safe_int(rest.get("days_rest"))

        if days > 0 and days < 4:
            score += 5
            reasons.append(f"{name}: short rest ({days} days)")
        elif days >= 6:
            score -= 2
            reasons.append(f"{name}: extra rest ({days} days)")

    return max(0, min(100, score)), reasons


def score_home_away_splits(game: dict) -> tuple:
    """Score home/away performance splits."""
    return 50, []  # Populated when split data is available


def score_umpire(game: dict) -> tuple:
    """Score based on home plate umpire tendencies."""
    reasons = []
    score = 50
    ump = game.get("umpire", {})

    if not ump.get("umpire_name"):
        return 50, ["Umpire not yet assigned"]

    yrfi_pct = safe_float(ump.get("first_inning_yrfi_pct"))
    zone = ump.get("strike_zone_size_rating", "average")

    if yrfi_pct > 55:
        score += 5
        reasons.append(f"Ump {ump['umpire_name']}: high YRFI rate ({yrfi_pct:.1f}%)")
    elif yrfi_pct < 42:
        score -= 5
        reasons.append(f"Ump {ump['umpire_name']}: low YRFI rate ({yrfi_pct:.1f}%)")

    if zone == "tight":
        score += 3
        reasons.append("Tight zone — more walks likely")
    elif zone == "wide":
        score -= 3

    return max(0, min(100, score)), reasons


def score_day_night(game: dict) -> tuple:
    """Score day vs night game impact."""
    return 50, []  # Minor factor, populated when split data available


def score_h2h_history(game: dict) -> tuple:
    """Score head-to-head lineup familiarity."""
    return 50, []  # Populated when matchup data available


def score_seasonal_timing(game: dict) -> tuple:
    """
    Score based on season timing and data confidence.
    Early April = wilder pitchers, less reliable data.
    """
    reasons = []
    score = 50
    date = game.get("date", "")

    try:
        month = int(date.split("-")[1])
        day = int(date.split("-")[2])
    except (IndexError, ValueError):
        return 50, []

    if month == 3 or (month == 4 and day <= 15):
        score += 5
        reasons.append("Early season — pitchers typically wilder in 1st starts")
        game["_low_sample_flag"] = True
    elif month == 9 and day > 1:
        score += 3
        reasons.append("September — expanded rosters, lineup changes")

    # Check if pitchers have enough 1st-inning data
    for side in ["home", "away"]:
        fi = game.get(f"{side}_pitcher_fi", {})
        fi_games = safe_int(fi.get("first_inning_games"))
        fi_ip = fi_games  # ~1 IP per first inning

        if fi_ip < 30 and fi_games > 0:
            reasons.append(
                f"{game.get(f'{side}_pitcher_profile', {}).get('name', '???')}: "
                f"LOW SAMPLE ({fi_games} 1st-inn appearances)"
            )
            game["_low_sample_flag"] = True

    return max(0, min(100, score)), reasons


def score_travel_schedule(game: dict) -> tuple:
    """Score travel fatigue and schedule factors."""
    return 50, []  # Populated when schedule context available


def score_opener_detection(game: dict) -> tuple:
    """Detect if a team is using an opener/bullpen game."""
    reasons = []
    score = 50

    for side in ["home", "away"]:
        profile = game.get(f"{side}_pitcher_profile", {})
        ip = safe_float(profile.get("innings_pitched"))
        gs = safe_int(profile.get("seasons", {}).get(
            int(game.get("date", "2026")[:4]), {}
        ).get("games_started", 0))

        # Potential opener: pitcher with very few innings per start
        if gs > 3 and ip > 0 and (ip / gs) < 3.5:
            score += 5
            reasons.append(
                f"{profile.get('name', '???')}: possible opener "
                f"({ip:.1f} IP in {gs} starts)"
            )

    return max(0, min(100, score)), reasons


def score_injury_lineup(game: dict) -> tuple:
    """Score impact of injury/lineup changes."""
    return 50, []  # Populated when injury data available


# ═══════════════════════════════════════════════════════════════════════════════
# SCORING FUNCTIONS MAP
# ═══════════════════════════════════════════════════════════════════════════════

FACTOR_FUNCTIONS = {
    "pitcher_first_inning":   score_pitcher_first_inning,
    "slow_starter_delta":     score_slow_starter_delta,
    "top_4_gauntlet":         score_top_4_gauntlet,
    "recent_form":            score_recent_form,
    "park_factor":            score_park_factor,
    "weather":                score_weather,
    "pitcher_rest":           score_pitcher_rest,
    "home_away_splits":       score_home_away_splits,
    "umpire":                 score_umpire,
    "day_night":              score_day_night,
    "h2h_history":            score_h2h_history,
    "seasonal_timing":        score_seasonal_timing,
    "travel_schedule":        score_travel_schedule,
    "opener_detection":       score_opener_detection,
    "injury_lineup_changes":  score_injury_lineup,
}


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER OVERRIDES
# ═══════════════════════════════════════════════════════════════════════════════

def apply_circuit_breakers(game: dict, yrfi_prob: float) -> tuple:
    """
    Apply hard override rules that can force adjustments.
    Returns (adjusted_probability, list of fired overrides).
    """
    overrides = []
    prob = yrfi_prob

    # Override 1: Walk/HR Trap
    for side in ["home", "away"]:
        fi = game.get(f"{side}_pitcher_fi", {})
        fi_games = safe_int(fi.get("first_inning_games"))
        if fi_games < 3:
            continue
        fi_bb_pct = safe_float(fi.get("first_inning_bb_pct"))
        fi_hr9 = safe_float(fi.get("first_inning_hr_per_9"))

        if fi_bb_pct > 9 or fi_hr9 > 1.5:
            name = game.get(f"{side}_pitcher_profile", {}).get("name", "???")
            overrides.append({
                "rule": "Walk/HR Trap",
                "detail": f"{name}: BB%={fi_bb_pct:.1f}%, HR/9={fi_hr9:.1f}",
                "action": "NRFI confidence capped at 55",
            })
            # If model says NRFI (prob < 50), cap confidence
            if prob < 45:
                prob = max(prob, 45)

    # Override 2: Over/Under Correlation
    ou = safe_float(game.get("vegas_over_under"))
    if ou >= 9.5 and prob < 48:
        # NRFI pick on high total — needs justification
        overrides.append({
            "rule": "O/U Correlation Check",
            "detail": f"O/U is {ou} but model leans NRFI (prob={prob:.1f})",
            "action": "Requires explicit justification for NRFI on high-total game",
        })

    # Override 3: Double Slow Starter
    slow_starters = game.get("_slow_starters", [])
    if len(slow_starters) >= 2:
        prob = max(prob, 70)
        overrides.append({
            "rule": "Double Slow Starter",
            "detail": f"Both pitchers flagged: {', '.join(slow_starters)}",
            "action": "Auto-classified Strong YRFI, min confidence 70",
        })

    # Override 4: Ace Lockdown
    ace_count = 0
    for side in ["home", "away"]:
        fi = game.get(f"{side}_pitcher_fi", {})
        scoreless = safe_float(fi.get("first_inning_scoreless_pct"))
        fi_whip = safe_float(fi.get("first_inning_whip"))
        if scoreless > 75 and fi_whip < 1.00:
            ace_count += 1

    if ace_count == 2:
        prob = min(prob, 25)
        overrides.append({
            "rule": "Ace Lockdown",
            "detail": "Both pitchers: 75%+ scoreless 1st inn, sub-1.00 WHIP",
            "action": "Auto-classified Strong NRFI, min confidence 75",
        })
        # Coors exception
        venue = game.get("venue", "")
        if "coors" in venue.lower():
            prob = min(prob + 15, 45)
            overrides.append({
                "rule": "Coors Override on Ace Lockdown",
                "detail": "Ace Lockdown weakened at Coors",
                "action": "+15 to YRFI probability",
            })

    # Override 5: Coors Field Override
    venue = game.get("venue", "")
    if "coors" in venue.lower():
        prob = min(100, prob + 15)
        overrides.append({
            "rule": "Coors Field Override",
            "detail": "+15 YRFI probability at Coors",
            "action": "Applied before pick classification",
        })

    return prob, overrides


# ═══════════════════════════════════════════════════════════════════════════════
# PICK CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

def classify_pick(yrfi_prob: float) -> tuple:
    """
    Convert YRFI probability to a pick and edge rating.
    Returns (pick, edge_rating, confidence).
    """
    if yrfi_prob >= 66:
        return "YRFI", "strong", int(yrfi_prob)
    elif yrfi_prob >= 58:
        return "YRFI", "moderate", int(yrfi_prob)
    elif yrfi_prob >= 48:
        return "SKIP", "skip", int(50 - abs(yrfi_prob - 50))
    elif yrfi_prob >= 43:
        return "SKIP", "skip", int(50 - abs(yrfi_prob - 50))
    elif yrfi_prob >= 36:
        return "NRFI", "moderate", int(100 - yrfi_prob)
    else:
        return "NRFI", "strong", int(100 - yrfi_prob)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_game(game: dict) -> dict:
    """
    Run full analysis on a single game.
    Returns pick dict with all factor scores and reasoning.
    """
    factor_scores = {}
    all_reasons = []

    # Run each factor
    for factor_name, func in FACTOR_FUNCTIONS.items():
        score, reasons = func(game)
        weight = WEIGHTS[factor_name]
        factor_scores[factor_name] = {
            "score": score,
            "weight": weight,
            "weighted_contribution": round(score * weight, 2),
            "reasons": reasons,
        }
        all_reasons.extend(reasons)

    # Calculate weighted YRFI probability
    yrfi_prob = sum(
        fs["score"] * fs["weight"]
        for fs in factor_scores.values()
    )

    # Apply low sample confidence reduction
    if game.get("_low_sample_flag"):
        original = yrfi_prob
        # Push toward 50 (reduce confidence) by 10 points
        if yrfi_prob > 50:
            yrfi_prob = max(50, yrfi_prob - 10)
        else:
            yrfi_prob = min(50, yrfi_prob + 10)
        all_reasons.append(
            f"Low sample size adjustment: {original:.1f} → {yrfi_prob:.1f}"
        )

    # Apply circuit breakers
    yrfi_prob, overrides = apply_circuit_breakers(game, yrfi_prob)

    # Classify the pick
    pick, edge_rating, confidence = classify_pick(yrfi_prob)

    # Lineup confirmation affects confidence
    home_confirmed = game.get("home_lineup", {}).get("confirmed", False)
    away_confirmed = game.get("away_lineup", {}).get("confirmed", False)
    lineup_status = "confirmed" if (home_confirmed and away_confirmed) else "projected"
    if lineup_status == "projected" and pick != "SKIP":
        confidence = max(0, confidence - 5)

    # ── XGBoost Scoring ─────────────────────────────────────────
    xgb_result = xgb_predict(game)
    consensus = False
    if xgb_result:
        # Check for consensus: both models agree on direction AND non-skip
        if pick != "SKIP" and xgb_result["pick"] != "SKIP":
            if pick == xgb_result["pick"]:
                consensus = True

    result = {
        "game_id": game.get("game_id"),
        "date": game.get("date"),
        "matchup": f"{game.get('away_team', '???')} @ {game.get('home_team', '???')}",
        "game_time": game.get("game_time_et", ""),
        "venue": game.get("venue", ""),
        "pick": pick,
        "yrfi_probability": round(yrfi_prob, 1),
        "confidence": confidence,
        "edge_rating": edge_rating,
        "lineup_status": lineup_status,
        "home_pitcher": game.get("home_pitcher_profile", {}).get("name", "TBD"),
        "away_pitcher": game.get("away_pitcher_profile", {}).get("name", "TBD"),
        "overrides_fired": overrides,
        "factor_scores": factor_scores,
        "key_reasons": all_reasons[:10],  # Top 10 most relevant reasons
        "weather": game.get("weather", {}),
        "vegas_ou": game.get("vegas_over_under"),
        "xgb": xgb_result,
        "consensus_pick": consensus,
        "model_version": xgb_result["model_version"] if xgb_result else None,
    }

    return result


def analyze_slate(games: list) -> dict:
    """Analyze a full day's slate of games."""
    picks = []
    for game in games:
        pick = analyze_game(game)
        picks.append(pick)

    # Sort: strong picks first, then by confidence
    picks.sort(key=lambda p: (
        0 if p["edge_rating"] == "strong" else 1 if p["edge_rating"] == "moderate" else 2,
        -p["confidence"],
    ))

    strong = [p for p in picks if p["edge_rating"] == "strong"]
    moderate = [p for p in picks if p["edge_rating"] == "moderate"]
    skips = [p for p in picks if p["edge_rating"] == "skip"]

    return {
        "date": games[0]["date"] if games else today_str(),
        "total_games": len(games),
        "strong_picks": strong,
        "lean_picks": moderate,
        "skips": skips,
        "all_picks": picks,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def format_pick_card(pick: dict) -> str:
    """Format a single pick as a text card."""
    emoji = "🟢" if pick["pick"] == "YRFI" else "🔴" if pick["pick"] == "NRFI" else "⚪"
    consensus_flag = "🔒 CONSENSUS " if pick.get("consensus_pick") else ""
    lines = [
        f"{consensus_flag}{emoji} {pick['pick']}: {pick['matchup']} ({pick['game_time']})",
        f"Confidence: {pick['confidence']}/100 | "
        f"{'O/U: ' + str(pick['vegas_ou']) if pick.get('vegas_ou') else 'No O/U data'}",
        f"Pitchers: {pick['away_pitcher']} vs {pick['home_pitcher']}",
    ]

    # Dual model scores
    xgb = pick.get("xgb")
    if xgb:
        rb_dir = pick["pick"]
        xgb_dir = xgb["pick"]
        lines.append(
            f"Rule-based: {pick['yrfi_probability']:.0f}/100 {rb_dir} | "
            f"XGBoost: {xgb['probability']:.2f} P(YRFI) → {xgb['tier']}"
        )

    # Add override flags
    for override in pick.get("overrides_fired", []):
        lines.append(f"⚠️ {override['rule']}: {override['detail']}")

    # Key reasons (top 3)
    for reason in pick.get("key_reasons", [])[:3]:
        if "SLOW STARTER" in reason or "Slow Starter" in reason:
            lines.append(f"⚠️ {reason}")
        elif "Ace Lockdown" in reason.lower():
            lines.append(f"✅ {reason}")
        else:
            lines.append(f"  {reason}")

    # Weather
    w = pick.get("weather", {})
    if w and not w.get("is_dome") and w.get("temp"):
        wind_str = f"Wind: {w.get('wind_speed', 0):.0f}mph" if w.get("wind_speed") else ""
        temp_str = f"Temp: {w.get('temp', 0):.0f}°F" if w.get("temp") else ""
        weather_parts = [p for p in [wind_str, temp_str] if p]
        if weather_parts:
            lines.append(" | ".join(weather_parts))
    elif w and w.get("is_dome"):
        lines.append("Dome game")

    # Lineup status
    if pick.get("lineup_status") == "projected":
        lines.append("📋 Projected lineups (re-run closer to game time)")

    return "\n".join(lines)


def format_full_slate(analysis: dict) -> str:
    """Format the full slate output for Telegram."""
    lines = [
        f"⚾ YRFI/NRFI PICKS — {analysis['date']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if analysis["strong_picks"]:
        lines.append("")
        lines.append("🔒 STRONG PICKS")
        lines.append("")
        for pick in analysis["strong_picks"]:
            lines.append(format_pick_card(pick))
            lines.append("")

    if analysis["lean_picks"]:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📊 LEAN PICKS")
        lines.append("")
        for pick in analysis["lean_picks"]:
            lines.append(format_pick_card(pick))
            lines.append("")

    if analysis["skips"]:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⏭️ SKIPPED: {len(analysis['skips'])} games too close to call")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="YRFI/NRFI Analysis Engine")
    parser.add_argument("--input", type=str, help="JSON file from daily_fetch.py")
    parser.add_argument("--date", type=str, help="Date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="text",
                        choices=["text", "json", "sql"],
                        help="Output format")
    args = parser.parse_args()

    # Load game data
    if args.input:
        with open(args.input) as f:
            data = json.load(f)
    elif not sys.stdin.isatty():
        data = json.load(sys.stdin)
    else:
        print("Provide game data via --input file or stdin pipe", file=sys.stderr)
        print("Example: python3 daily_fetch.py | python3 analyze.py", file=sys.stderr)
        sys.exit(1)

    games = data.get("games", [])
    if not games:
        print("No games to analyze", file=sys.stderr)
        sys.exit(0)

    # Run analysis
    analysis = analyze_slate(games)

    # Output
    if args.output == "json":
        print(json.dumps(analysis, indent=2, default=str))
    elif args.output == "sql":
        for pick in analysis["all_picks"]:
            if pick["pick"] == "SKIP":
                continue
            xgb = pick.get("xgb", {})
            xgb_prob = xgb.get("probability", "NULL") if xgb else "NULL"
            xgb_tier = f"'{xgb['tier']}'" if xgb and xgb.get("tier") else "NULL"
            model_ver = f"'{pick['model_version']}'" if pick.get("model_version") else "NULL"
            consensus = pick.get("consensus_pick", False)
            print(f"""
INSERT INTO mlb_yrfi_picks (game_id, date, pick, yrfi_probability, confidence,
    edge_rating, reasoning_json, overrides_fired, lineup_confirmed,
    xgb_probability, xgb_tier, model_version, consensus_pick)
VALUES ({pick['game_id']}, '{pick['date']}', '{pick['pick']}',
    {pick['yrfi_probability']}, {pick['confidence']}, '{pick['edge_rating']}',
    '{json.dumps(pick["factor_scores"]).replace(chr(39), chr(39)+chr(39))}',
    '{json.dumps(pick["overrides_fired"]).replace(chr(39), chr(39)+chr(39))}',
    {pick['lineup_status'] == 'confirmed'},
    {xgb_prob}, {xgb_tier}, {model_ver}, {consensus})
ON CONFLICT (game_id, date) DO UPDATE SET
    pick = EXCLUDED.pick,
    yrfi_probability = EXCLUDED.yrfi_probability,
    confidence = EXCLUDED.confidence,
    edge_rating = EXCLUDED.edge_rating,
    reasoning_json = EXCLUDED.reasoning_json,
    overrides_fired = EXCLUDED.overrides_fired,
    lineup_confirmed = EXCLUDED.lineup_confirmed,
    xgb_probability = EXCLUDED.xgb_probability,
    xgb_tier = EXCLUDED.xgb_tier,
    model_version = EXCLUDED.model_version,
    consensus_pick = EXCLUDED.consensus_pick;""")
    else:
        print(format_full_slate(analysis))


if __name__ == "__main__":
    main()
