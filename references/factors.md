# YRFI/NRFI Analysis Factors — Deep Dive

## Why First-Inning Analysis Is Different

The first inning is fundamentally different from other innings:
- **Fixed batting order:** You always face the top of the lineup (best hitters)
- **Pitcher cold start:** Starting pitchers haven't settled in yet
- **No bullpen variable:** It's always the starter (unless opener)
- **Predictable sample:** Same hitters, same pitcher, same sequence every game

This predictability is what makes YRFI/NRFI one of the most modelable props in baseball.

---

## Tier 1 Factors (50% of model)

### 1. Starting Pitcher First-Inning Stats (25%)

**Why it matters:** The single most predictive factor. A pitcher who routinely allows runs in the 1st inning will continue to do so — it's a skill/tendency, not random variance.

**Key metrics:**
- **1st-Inning ERA:** Runs allowed per 9 first-inning appearances. Under 2.00 = elite closer. Over 5.00 = alarm bells.
- **1st-Inning WHIP:** Baserunners per inning in the 1st. Under 1.00 = lockdown. Over 1.40 = traffic.
- **1st-Inning Scoreless %:** What percentage of starts have a clean first. Over 75% = NRFI machine. Under 55% = YRFI lean.
- **1st-Inning K Rate:** High K% in the first = pitcher attacks early. Correlates with fewer runs.
- **1st-Inning BB Rate:** High BB% = free baserunners = YRFI fuel.

**Weighting across seasons:**
- Current season: 60%
- Previous season: 25%
- Two seasons ago: 15%

**Early season exception:** When current season has < 5 starts, flip to 15/60/25.

### 2. Slow Starter Delta (10%)

**The key insight:** A pitcher with a 3.20 overall ERA but a 5.10 first-inning ERA is telling you something — they take time to find their rhythm. This delta is more predictive than raw first-inning ERA alone.

**Calculation:** `first_inning_era - overall_season_era`

**Interpretation:**
- Delta > 1.5 → **Major Slow Starter** — massive YRFI signal
- Delta > 1.0 → **Slow Starter** — significant YRFI lean
- Delta -0.5 to 1.0 → Normal range
- Delta < -0.5 → **First-Inning Specialist** — actively better in the 1st

**Why this works:** Some pitchers genuinely need 10-15 pitches to lock in their mechanics. The first inning exposes this tendency in a way that overall stats mask.

### 3. Top 4 Gauntlet (10%)

**Why top 4 specifically:** The 1st inning only sees batters 1-4 (occasionally 5 in big innings). Team-wide batting averages include the 7-8-9 hitters and are diluted. The top of the order is where the damage happens.

**What to analyze for each of the top 4:**

1. **Platoon Advantage (Matchup Geometry)**
   - LHB vs RHP who struggles against lefties = advantage
   - Switch hitters always get the favorable side
   - Track OBP/SLG/wOBA by pitcher handedness faced

2. **Contact vs Power Profile**
   - High-K top of order = NRFI lean (likely to swing and miss early)
   - High-contact with power (SLG > .480 + K% < 20%) = YRFI lean
   - Speedsters at 1-2 with power at 3-4 = classic run-producing combo

3. **First-Pitch/Early-Count Aggression**
   - Hitters who swing early put the ball in play more in the 1st
   - Patient hitters who work counts tend to draw walks (also YRFI fuel)

### 4. Recent Form — Last 10 Games (5%)

**Why 10 games:** Short enough to capture hot/cold streaks, long enough to be non-random. First-inning streaks are sticky in the short term.

**What to track:**
- Team's YRFI rate over last 10 games
- Pitcher's last 3 first-inning performances
- Lineup consistency (same top 4 or shuffled?)

---

## Tier 2 Factors (30% of model)

### 5. Park Factor (10%)

Not all parks are created equal. First-inning park factors differ from overall park factors because:
- Wind patterns change throughout the day
- Shadows affect hitter visibility early
- Altitude always affects ball flight

**Key venues:**
- **Coors Field:** YRFI paradise. Elevation (5,280 ft) means the ball flies. Automatic +15 override.
- **Great American Ball Park:** Small dimensions, hitter-friendly. High YRFI%.
- **Petco Park:** Pitcher's park, especially at night. NRFI lean.
- **Oracle Park:** Cold, wind blowing in off the bay. Suppresses scoring.

### 6. Weather (8%)

- **Temperature > 85°F:** Ball carries further. +6 YRFI lean.
- **Temperature < 50°F:** Ball dies off the bat. -6 NRFI lean.
- **Wind > 15 mph blowing out:** HR risk elevated. +4 YRFI lean.
- **Wind blowing in:** HR risk suppressed. Slight NRFI lean.
- **Humidity > 80%:** Marginal NRFI effect (ball doesn't carry as well in thick air).
- **Dome games:** Weather factor = 0 (climate controlled at ~72°F).

### 7. Pitcher Rest & Workload (6%)

- **Short rest (< 4 days):** Pitcher likely not fully recovered. YRFI lean.
- **Extra rest (6+ days):** Can go either way — some pitchers lose rhythm.
- **High recent workload:** Pitcher who threw 110+ pitches last start may be fatigued.
- **Opener/bullpen game previous start:** May indicate the team is managing the pitcher.

### 8. Home/Away Splits (6%)

Some pitchers have dramatic home/away splits in the first inning:
- **Home advantage:** Familiar mound, crowd energy, pre-game routine
- **Away disadvantage:** New mound, travel, unfamiliar surroundings
- Check if the pitcher has a 1+ ERA difference between home and away 1st-inning performance

---

## Tier 3 Factors (15% of model)

### 9. Umpire Tendencies (5%)

The home plate umpire's zone directly affects walk rates and scoring:
- **Tight zone:** More balls → more walks → more baserunners → YRFI lean
- **Wide zone:** More strikes → more Ks → fewer baserunners → NRFI lean
- Track each ump's historical YRFI%, BB/game, K/game

### 10. Day/Night Split (3%)

Minor but real: some pitchers perform differently in day games. Visibility, routine disruption, and scheduling factors can all play a role.

### 11. Head-to-Head History (3%)

Limited sample size, but directionally useful:
- If a lineup has historically crushed a pitcher, the familiarity factor matters
- Particularly relevant for division rivals who face each other often

### 12. Seasonal Timing & Data Confidence (4%)

- **March/April:** Pitchers are wilder, lineups aren't set, small samples. Boost YRFI probability slightly and flag low-confidence picks.
- **May-August:** Full data, stable rosters. Highest confidence period.
- **September:** Expanded rosters, fatigue, playoff implications change effort levels.

---

## Tier 4 Factors (5% of model)

### 13. Travel & Schedule (2%)
- Day game after night game = fatigued hitters
- Long road trips = cumulative fatigue
- Cross-timezone travel (West Coast team playing early ET game)

### 14. Opener/Bullpen Game Detection (2%)
If a team is using an opener instead of a traditional starter, the entire analysis changes:
- Openers are usually relievers with different pitch mixes
- The "starter" may only go 1-2 innings
- Treat as a completely different pitcher profile

### 15. Injury/Lineup Changes (1%)
- Late scratches of key bats from the top 4 = reduced YRFI threat
- Backup catcher in the lineup = typically weaker bat
- Check injury reports close to game time
