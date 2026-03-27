"""
YRFI/NRFI Supabase Table Setup
Run this once to create all required tables.

Usage via Claude MCP:
    Copy the SQL below and run via mcp__claude_ai_Supabase__execute_sql
    with project_id: kakjbyoxqjvwnsdbqcnb

Usage standalone:
    python3 setup_supabase.py
    (requires SUPABASE_URL and SUPABASE_KEY env vars with service role key)
"""

SETUP_SQL = """
-- ═══════════════════════════════════════════════════════════════════════════
-- YRFI/NRFI Analysis Tables
-- ═══════════════════════════════════════════════════════════════════════════

-- Games: core game-level data with first-inning results
CREATE TABLE IF NOT EXISTS mlb_games (
    game_id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    venue TEXT,
    game_time_et TEXT,
    home_pitcher_id INTEGER,
    away_pitcher_id INTEGER,
    home_pitcher_name TEXT,
    away_pitcher_name TEXT,
    first_inning_runs_home INTEGER,
    first_inning_runs_away INTEGER,
    total_first_inning_runs INTEGER GENERATED ALWAYS AS (
        COALESCE(first_inning_runs_home, 0) + COALESCE(first_inning_runs_away, 0)
    ) STORED,
    yrfi_result BOOLEAN GENERATED ALWAYS AS (
        COALESCE(first_inning_runs_home, 0) + COALESCE(first_inning_runs_away, 0) > 0
    ) STORED,
    final_score_home INTEGER,
    final_score_away INTEGER,
    weather_temp REAL,
    weather_wind_speed REAL,
    weather_wind_dir INTEGER,
    weather_humidity REAL,
    vegas_over_under REAL,
    vegas_yrfi_odds INTEGER,
    vegas_nrfi_odds INTEGER,
    is_dome BOOLEAN DEFAULT FALSE,
    game_status TEXT DEFAULT 'scheduled',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mlb_games_date ON mlb_games(date);
CREATE INDEX IF NOT EXISTS idx_mlb_games_teams ON mlb_games(home_team, away_team);
CREATE INDEX IF NOT EXISTS idx_mlb_games_pitchers ON mlb_games(home_pitcher_id, away_pitcher_id);

-- Pitchers: profiles with rolling stats and first-inning splits
CREATE TABLE IF NOT EXISTS mlb_pitchers (
    pitcher_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    name TEXT NOT NULL,
    team TEXT,
    throws TEXT,  -- L or R
    era REAL,
    whip REAL,
    k_per_9 REAL,
    bb_per_9 REAL,
    hr_per_9 REAL,
    innings_pitched REAL,
    games_started INTEGER,
    first_inning_era REAL,
    first_inning_whip REAL,
    first_inning_avg_against REAL,
    first_inning_runs_allowed_total INTEGER DEFAULT 0,
    first_inning_games INTEGER DEFAULT 0,
    first_inning_scoreless_pct REAL DEFAULT 0,
    first_inning_k_total INTEGER DEFAULT 0,
    first_inning_bb_total INTEGER DEFAULT 0,
    first_inning_hr_total INTEGER DEFAULT 0,
    first_inning_hits_total INTEGER DEFAULT 0,
    first_inning_era_delta REAL DEFAULT 0,  -- 1st-inn ERA minus overall ERA
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (pitcher_id, season)
);

CREATE INDEX IF NOT EXISTS idx_mlb_pitchers_team ON mlb_pitchers(team, season);

-- Lineups: daily lineup snapshots
CREATE TABLE IF NOT EXISTS mlb_lineups (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id INTEGER REFERENCES mlb_games(game_id),
    team TEXT NOT NULL,
    date DATE NOT NULL,
    lineup_json JSONB,  -- full order with splits
    top_4_json JSONB,   -- top 4 hitters isolated
    confirmed BOOLEAN DEFAULT FALSE,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(game_id, team)
);

-- Picks: daily generated predictions
CREATE TABLE IF NOT EXISTS mlb_yrfi_picks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id INTEGER REFERENCES mlb_games(game_id),
    date DATE NOT NULL,
    pick TEXT NOT NULL CHECK (pick IN ('YRFI', 'NRFI', 'SKIP')),
    yrfi_probability REAL,
    confidence INTEGER CHECK (confidence BETWEEN 0 AND 100),
    edge_rating TEXT CHECK (edge_rating IN ('strong', 'moderate', 'lean', 'skip')),
    reasoning_json JSONB,
    overrides_fired JSONB,  -- which circuit breakers triggered
    lineup_confirmed BOOLEAN DEFAULT FALSE,
    odds_at_pick INTEGER,
    result TEXT CHECK (result IN ('W', 'L', 'P', NULL)),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(game_id, date)
);

CREATE INDEX IF NOT EXISTS idx_picks_date ON mlb_yrfi_picks(date);
CREATE INDEX IF NOT EXISTS idx_picks_result ON mlb_yrfi_picks(result);

-- Model Performance: daily accuracy tracking
CREATE TABLE IF NOT EXISTS mlb_model_performance (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    total_picks INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    pushes INTEGER DEFAULT 0,
    skips INTEGER DEFAULT 0,
    win_pct REAL,
    roi_pct REAL,
    strong_picks_total INTEGER DEFAULT 0,
    strong_picks_wins INTEGER DEFAULT 0,
    lean_picks_total INTEGER DEFAULT 0,
    lean_picks_wins INTEGER DEFAULT 0,
    confidence_tier_breakdown JSONB,
    rolling_7d_pct REAL,
    rolling_30d_pct REAL,
    season_pct REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Team Stats: team-level first-inning aggregates
CREATE TABLE IF NOT EXISTS mlb_team_stats (
    team TEXT NOT NULL,
    season INTEGER NOT NULL,
    games_played INTEGER DEFAULT 0,
    runs_scored_first_inning_total INTEGER DEFAULT 0,
    runs_allowed_first_inning_total INTEGER DEFAULT 0,
    yrfi_pct_home REAL DEFAULT 0,
    yrfi_pct_away REAL DEFAULT 0,
    yrfi_pct_overall REAL DEFAULT 0,
    avg_runs_first_inning REAL DEFAULT 0,
    first_inning_ops REAL,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (team, season)
);

-- Park Factors: venue-specific run environments
CREATE TABLE IF NOT EXISTS mlb_park_factors (
    venue TEXT NOT NULL,
    season INTEGER NOT NULL,
    park_factor_runs REAL DEFAULT 1.0,
    park_factor_hr REAL DEFAULT 1.0,
    avg_first_inning_runs REAL,
    yrfi_pct_at_venue REAL,
    total_games INTEGER DEFAULT 0,
    elevation INTEGER DEFAULT 0,
    is_dome BOOLEAN DEFAULT FALSE,
    dimensions_json JSONB,
    PRIMARY KEY (venue, season)
);

-- Umpire Data: home plate umpire tendencies
CREATE TABLE IF NOT EXISTS mlb_umpire_data (
    umpire_name TEXT NOT NULL,
    season INTEGER NOT NULL,
    games_called INTEGER DEFAULT 0,
    avg_runs_per_game REAL,
    first_inning_yrfi_pct REAL,
    k_per_game REAL,
    bb_per_game REAL,
    strike_zone_size_rating TEXT,  -- tight, average, wide
    PRIMARY KEY (umpire_name, season)
);

-- Disable RLS on all tables (personal project, MCP access)
ALTER TABLE mlb_games ENABLE ROW LEVEL SECURITY;
ALTER TABLE mlb_pitchers ENABLE ROW LEVEL SECURITY;
ALTER TABLE mlb_lineups ENABLE ROW LEVEL SECURITY;
ALTER TABLE mlb_yrfi_picks ENABLE ROW LEVEL SECURITY;
ALTER TABLE mlb_model_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE mlb_team_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE mlb_park_factors ENABLE ROW LEVEL SECURITY;
ALTER TABLE mlb_umpire_data ENABLE ROW LEVEL SECURITY;

-- Create permissive policies for anon access
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY[
        'mlb_games', 'mlb_pitchers', 'mlb_lineups', 'mlb_yrfi_picks',
        'mlb_model_performance', 'mlb_team_stats', 'mlb_park_factors', 'mlb_umpire_data'
    ])
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS allow_all_select ON %I', tbl);
        EXECUTE format('CREATE POLICY allow_all_select ON %I FOR SELECT USING (true)', tbl);
        EXECUTE format('DROP POLICY IF EXISTS allow_all_insert ON %I', tbl);
        EXECUTE format('CREATE POLICY allow_all_insert ON %I FOR INSERT WITH CHECK (true)', tbl);
        EXECUTE format('DROP POLICY IF EXISTS allow_all_update ON %I', tbl);
        EXECUTE format('CREATE POLICY allow_all_update ON %I FOR UPDATE USING (true) WITH CHECK (true)', tbl);
        EXECUTE format('DROP POLICY IF EXISTS allow_all_delete ON %I', tbl);
        EXECUTE format('CREATE POLICY allow_all_delete ON %I FOR DELETE USING (true)', tbl);
    END LOOP;
END $$;
"""

def main():
    """Run setup SQL via supabase-py (needs service role key)."""
    import sys
    try:
        from supabase import create_client
    except ImportError:
        print("supabase-py not installed. Run: pip install supabase")
        sys.exit(1)

    from utils import SUPABASE_URL, SUPABASE_KEY
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # supabase-py doesn't support raw SQL execution directly
    # Print the SQL for manual execution via MCP or psql
    print("=" * 70)
    print("YRFI/NRFI TABLE SETUP SQL")
    print("=" * 70)
    print()
    print("Run this SQL via one of:")
    print("  1. MCP: mcp__claude_ai_Supabase__execute_sql (project_id: kakjbyoxqjvwnsdbqcnb)")
    print("  2. Supabase Dashboard SQL Editor")
    print("  3. psql connection to your Supabase database")
    print()
    print(SETUP_SQL)


if __name__ == "__main__":
    main()
