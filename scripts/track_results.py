"""
YRFI/NRFI Results Tracker
Score yesterday's picks against actual results and update model performance.

Usage:
    python3 track_results.py [--date 2026-04-15]

Outputs:
  - Pick results (W/L for each pick)
  - Updated model performance stats
  - SQL to update Supabase
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    get_schedule, get_linescore, extract_first_inning_runs,
    team_abbrev, safe_float, safe_int, today_str,
)


def fetch_actual_results(date: str) -> dict:
    """
    Fetch actual first-inning results for all games on a date.
    Returns dict of game_id -> result.
    """
    games = get_schedule(date)
    results = {}

    for game in games:
        game_pk = game.get("gamePk")
        status = game.get("status", {}).get("abstractGameState", "")

        if status != "Final":
            continue

        linescore = get_linescore(game_pk)
        away_runs, home_runs = extract_first_inning_runs(linescore)

        if away_runs is None or home_runs is None:
            continue

        total_fi_runs = safe_int(away_runs) + safe_int(home_runs)
        yrfi_result = total_fi_runs > 0

        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        # Final score
        ls_teams = linescore.get("teams", {}) if linescore else {}

        results[game_pk] = {
            "game_id": game_pk,
            "date": date,
            "home_team": team_abbrev(home.get("team", {}).get("name", "")),
            "away_team": team_abbrev(away.get("team", {}).get("name", "")),
            "first_inning_runs_home": safe_int(home_runs),
            "first_inning_runs_away": safe_int(away_runs),
            "total_first_inning_runs": total_fi_runs,
            "yrfi_result": yrfi_result,
            "final_score_home": ls_teams.get("home", {}).get("runs"),
            "final_score_away": ls_teams.get("away", {}).get("runs"),
        }

    return results


def score_picks(picks: list, results: dict) -> list:
    """
    Score picks against actual results.
    Returns list of scored picks.
    """
    scored = []
    for pick in picks:
        game_id = pick.get("game_id")
        result = results.get(game_id)

        if not result:
            scored.append({**pick, "result": None, "status": "no_result"})
            continue

        actual_yrfi = result["yrfi_result"]
        predicted = pick.get("pick", "SKIP")

        if predicted == "SKIP":
            scored.append({
                **pick,
                "result": "SKIP",
                "status": "skipped",
                "actual_yrfi": actual_yrfi,
                "actual_runs": result["total_first_inning_runs"],
            })
            continue

        if predicted == "YRFI":
            won = actual_yrfi
        elif predicted == "NRFI":
            won = not actual_yrfi
        else:
            won = None

        scored.append({
            **pick,
            "result": "W" if won else "L",
            "status": "scored",
            "actual_yrfi": actual_yrfi,
            "actual_runs": result["total_first_inning_runs"],
            "first_inning_detail": (
                f"{result['away_team']} {result['first_inning_runs_away']}, "
                f"{result['home_team']} {result['first_inning_runs_home']}"
            ),
        })

    return scored


def calculate_performance(scored_picks: list) -> dict:
    """Calculate performance stats from scored picks."""
    wins = sum(1 for p in scored_picks if p.get("result") == "W")
    losses = sum(1 for p in scored_picks if p.get("result") == "L")
    skips = sum(1 for p in scored_picks if p.get("result") == "SKIP")
    total = wins + losses

    # By edge rating
    strong = [p for p in scored_picks if p.get("edge_rating") == "strong"]
    strong_w = sum(1 for p in strong if p.get("result") == "W")
    strong_total = sum(1 for p in strong if p.get("result") in ("W", "L"))

    lean = [p for p in scored_picks if p.get("edge_rating") == "moderate"]
    lean_w = sum(1 for p in lean if p.get("result") == "W")
    lean_total = sum(1 for p in lean if p.get("result") in ("W", "L"))

    # Confidence tier breakdown
    tiers = defaultdict(lambda: {"wins": 0, "total": 0})
    for p in scored_picks:
        if p.get("result") not in ("W", "L"):
            continue
        conf = p.get("confidence", 50)
        if conf >= 75:
            tier = "75-100"
        elif conf >= 60:
            tier = "60-74"
        else:
            tier = "50-59"
        tiers[tier]["total"] += 1
        if p["result"] == "W":
            tiers[tier]["wins"] += 1

    tier_breakdown = {}
    for tier, data in tiers.items():
        tier_breakdown[tier] = {
            "wins": data["wins"],
            "total": data["total"],
            "pct": round(data["wins"] / data["total"] * 100, 1) if data["total"] > 0 else 0,
        }

    return {
        "total_picks": total,
        "wins": wins,
        "losses": losses,
        "skips": skips,
        "win_pct": round(wins / total * 100, 1) if total > 0 else 0,
        "strong_picks_total": strong_total,
        "strong_picks_wins": strong_w,
        "strong_pct": round(strong_w / strong_total * 100, 1) if strong_total > 0 else 0,
        "lean_picks_total": lean_total,
        "lean_picks_wins": lean_w,
        "lean_pct": round(lean_w / lean_total * 100, 1) if lean_total > 0 else 0,
        "confidence_tier_breakdown": tier_breakdown,
    }


def format_results_report(date: str, scored_picks: list, performance: dict) -> str:
    """Format a results report for Telegram."""
    lines = [
        f"📊 YRFI/NRFI RESULTS — {date}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # Individual results
    for pick in scored_picks:
        if pick.get("status") == "no_result":
            continue

        if pick.get("result") == "SKIP":
            emoji = "⏭️"
        elif pick.get("result") == "W":
            emoji = "✅"
        else:
            emoji = "❌"

        matchup = pick.get("matchup", "???")
        pred = pick.get("pick", "SKIP")
        actual = "YRFI" if pick.get("actual_yrfi") else "NRFI"
        conf = pick.get("confidence", 0)
        detail = pick.get("first_inning_detail", "")

        line = f"{emoji} {matchup}: {pred} (conf {conf}) → {actual}"
        if detail:
            line += f" [{detail}]"
        lines.append(line)

    # Summary
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    w = performance["wins"]
    l = performance["losses"]
    pct = performance["win_pct"]
    lines.append(f"📈 Day: {w}-{l} ({pct}%)")

    if performance["strong_picks_total"] > 0:
        sw = performance["strong_picks_wins"]
        st = performance["strong_picks_total"]
        sp = performance["strong_pct"]
        lines.append(f"🔒 Strong picks: {sw}-{st-sw} ({sp}%)")

    if performance["lean_picks_total"] > 0:
        lw = performance["lean_picks_wins"]
        lt = performance["lean_picks_total"]
        lp = performance["lean_pct"]
        lines.append(f"📊 Lean picks: {lw}-{lt-lw} ({lp}%)")

    return "\n".join(lines)


def generate_result_sql(date: str, scored_picks: list, performance: dict) -> str:
    """Generate SQL to update picks and performance in Supabase."""
    sql_parts = []

    # Update individual pick results
    for pick in scored_picks:
        if pick.get("result") in ("W", "L"):
            sql_parts.append(f"""
UPDATE mlb_yrfi_picks
SET result = '{pick['result']}'
WHERE game_id = {pick['game_id']} AND date = '{date}';""")

    # Update game results
    for pick in scored_picks:
        if pick.get("actual_runs") is not None:
            sql_parts.append(f"""
UPDATE mlb_games
SET first_inning_runs_home = COALESCE(first_inning_runs_home, 0),
    first_inning_runs_away = COALESCE(first_inning_runs_away, 0),
    game_status = 'Final'
WHERE game_id = {pick['game_id']};""")

    # Upsert model performance
    p = performance
    tier_json = json.dumps(p["confidence_tier_breakdown"]).replace("'", "''")
    sql_parts.append(f"""
INSERT INTO mlb_model_performance (date, total_picks, wins, losses, skips,
    win_pct, strong_picks_total, strong_picks_wins,
    lean_picks_total, lean_picks_wins, confidence_tier_breakdown)
VALUES ('{date}', {p['total_picks']}, {p['wins']}, {p['losses']}, {p['skips']},
    {p['win_pct']}, {p['strong_picks_total']}, {p['strong_picks_wins']},
    {p['lean_picks_total']}, {p['lean_picks_wins']}, '{tier_json}')
ON CONFLICT (date) DO UPDATE SET
    total_picks = EXCLUDED.total_picks,
    wins = EXCLUDED.wins,
    losses = EXCLUDED.losses,
    win_pct = EXCLUDED.win_pct,
    strong_picks_total = EXCLUDED.strong_picks_total,
    strong_picks_wins = EXCLUDED.strong_picks_wins,
    lean_picks_total = EXCLUDED.lean_picks_total,
    lean_picks_wins = EXCLUDED.lean_picks_wins,
    confidence_tier_breakdown = EXCLUDED.confidence_tier_breakdown;""")

    return "\n".join(sql_parts)


def main():
    parser = argparse.ArgumentParser(description="Track YRFI/NRFI pick results")
    parser.add_argument("--date", type=str, help="Date to score (YYYY-MM-DD, default: yesterday)")
    parser.add_argument("--picks", type=str, help="JSON file with picks to score")
    parser.add_argument("--output", type=str, default="text",
                        choices=["text", "json", "sql"],
                        help="Output format")
    args = parser.parse_args()

    # Default to yesterday
    if args.date:
        date = args.date
    else:
        yesterday = datetime.now() - timedelta(days=1)
        date = yesterday.strftime("%Y-%m-%d")

    print(f"Scoring results for {date}...", file=sys.stderr)

    # Get actual results
    results = fetch_actual_results(date)
    print(f"Found {len(results)} completed games", file=sys.stderr)

    if not results:
        print(f"No completed games found for {date}", file=sys.stderr)
        return

    # Load picks (from file or generate placeholder)
    if args.picks:
        with open(args.picks) as f:
            picks_data = json.load(f)
        picks = picks_data.get("all_picks", picks_data.get("picks", []))
    else:
        # Without pick data, just output the actual results
        print(f"\n📊 ACTUAL FIRST-INNING RESULTS — {date}", file=sys.stderr)
        yrfi_count = 0
        nrfi_count = 0
        for gid, result in results.items():
            yrfi = "YRFI" if result["yrfi_result"] else "NRFI"
            if result["yrfi_result"]:
                yrfi_count += 1
            else:
                nrfi_count += 1
            print(
                f"  {result['away_team']} @ {result['home_team']}: "
                f"{result['first_inning_runs_away']}-{result['first_inning_runs_home']} "
                f"({yrfi})",
                file=sys.stderr
            )
        print(f"\nYRFI: {yrfi_count} | NRFI: {nrfi_count} | "
              f"YRFI%: {yrfi_count/(yrfi_count+nrfi_count)*100:.1f}%",
              file=sys.stderr)

        if args.output == "json":
            print(json.dumps({
                "date": date,
                "results": list(results.values()),
                "yrfi_count": yrfi_count,
                "nrfi_count": nrfi_count,
            }, indent=2, default=str))
        return

    # Score picks
    scored = score_picks(picks, results)
    performance = calculate_performance(scored)

    # Output
    if args.output == "json":
        print(json.dumps({
            "date": date,
            "scored_picks": scored,
            "performance": performance,
        }, indent=2, default=str))
    elif args.output == "sql":
        print(generate_result_sql(date, scored, performance))
    else:
        print(format_results_report(date, scored, performance))


if __name__ == "__main__":
    main()
