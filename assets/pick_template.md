# YRFI/NRFI Pick Output Template

Use this template when formatting picks for Telegram delivery.

---

## Full Slate Template

```
⚾ YRFI/NRFI PICKS — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━━

🔒 STRONG PICKS

🟢 YRFI: [Away] @ [Home] ([Time] ET)
Confidence: [XX]/100 | O/U: [X.X]
Pitchers: [Away P] ([TEAM]) vs [Home P] ([TEAM])
⚠️ Slow Starter: [Name] (1st-inn ERA [X.XX] vs [X.XX] overall, Δ[X.XX])
⚠️ Overrides: [List any circuit breakers that fired]
Top 4 Threat: [TEAM] — [Key hitter] ([stat vs handedness]), [Key hitter] ([stat])
Wind: [X]mph [direction] | Temp: [X]°F

🔴 NRFI: [Away] @ [Home] ([Time] ET)
Confidence: [XX]/100 | O/U: [X.X]
Pitchers: [Away P] ([TEAM]) vs [Home P] ([TEAM])
✅ Ace Lockdown: Both [XX]%+ scoreless 1st inn, sub-[X.XX] WHIP
Top 4 Threat: LOW — [Reason]
Ump: [Name] ([tendency note])

━━━━━━━━━━━━━━━━━━━━━━━━
📊 LEAN PICKS

🟡 YRFI: [Away] @ [Home] ([Time] ET)
Confidence: [XX]/100
[Brief reasoning — 1-2 lines max]

🟡 NRFI: [Away] @ [Home] ([Time] ET)
Confidence: [XX]/100
[Brief reasoning]

━━━━━━━━━━━━━━━━━━━━━━━━
⏭️ SKIPPED: [X] games too close to call
[List matchups briefly]

━━━━━━━━━━━━━━━━━━━━━━━━
📈 MODEL PERFORMANCE
Season: [W]-[L] ([X.X]%) | Last 7: [W]-[L] ([X.X]%)
Strong picks: [W]-[L] ([X.X]%) | ROI: [+X.X]%
```

---

## Single Game Template

```
⚾ [Away] @ [Home] — 1ST INNING ANALYSIS

Pick: [🟢 YRFI / 🔴 NRFI] (Confidence: [XX]/100)
Pitchers: [Away P] vs [Home P]

📊 KEY FACTORS:
• [Factor 1 — most important reason]
• [Factor 2]
• [Factor 3]

⚠️ FLAGS:
• [Any overrides or warnings]

📋 TOP 4 GAUNTLET:
Away: [#1 Name .OBP], [#2], [#3], [#4]
Home: [#1 Name .OBP], [#2], [#3], [#4]

🌡️ Conditions: [Temp]°F, Wind [X]mph [dir] | [Venue]
```

---

## Results Report Template

```
📊 YRFI/NRFI RESULTS — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━━

✅ [Away] @ [Home]: [PICK] (conf [XX]) → [ACTUAL] [1st-inn score detail]
❌ [Away] @ [Home]: [PICK] (conf [XX]) → [ACTUAL] [detail]
✅ [Away] @ [Home]: [PICK] (conf [XX]) → [ACTUAL] [detail]

━━━━━━━━━━━━━━━━━━━━━━━━
📈 Day: [W]-[L] ([X.X]%)
🔒 Strong picks: [W]-[L] ([X.X]%)
📊 Lean picks: [W]-[L] ([X.X]%)

Season: [W]-[L] ([X.X]%) | Last 7: [W]-[L] ([X.X]%)
```

---

## Formatting Rules

1. **Telegram uses plain text** — no markdown rendering in group chats. Use Unicode symbols (━, ⚾, 🔒, etc.) for visual structure.
2. **Keep picks scannable** — most important info (pick, confidence, pitchers) on the first 2 lines.
3. **Flag overrides prominently** — ⚠️ emoji makes circuit breaker flags stand out.
4. **Include game times** — always in ET since the group is in CST (1 hour behind).
5. **Confidence colors:**
   - 🟢 Green = YRFI
   - 🔴 Red = NRFI
   - 🟡 Yellow = Lean pick (lower confidence)
   - ⚪ White = Skip
6. **Projected lineup warning** — always note when lineups aren't confirmed: "📋 Projected lineups (re-run closer to game time)"
