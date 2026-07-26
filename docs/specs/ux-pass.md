# UX pass — proposal (2026-07-26)

Driven by the four concept mockups in `Assets/Concept/` (esp. image 4, literally
titled "POE Community Companion") + the explicit ask: **each achievement board should
show only players with submissions** (small pool → less filler, more categories
visible). Status: **proposed, awaiting greenlight** (propose-first).

## Guardrails / what we adapt vs skip
The concepts are gorgeous but built on assets/features we don't do:
- **No PoE artwork (standing rule).** The concepts use character portraits + item
  sprites throughout. We keep the rule: adopt the *layout, density, hierarchy and
  medal iconography* rendered as our **own CSS** (gold medallions, class-coloured
  pills), plus the existing user `avatar` upload + `banner_hue` accent. No game art.
- **Single private guild.** Skip multi-guild "Guild Standings", guild-rank "Top 18%".
- **Data we actually have.** PoB paste gives class/ascendancy/level (+ a few defence
  numbers). No live passive-tree render or full gear grid → the deep character sheet
  (concept 3) is out of reach now.
- **Out of this pass (bigger features):** global search / Cmd+K, notifications bell,
  online-presence dots, left-sidebar nav redesign, guild-progression charts.

## Tier 1 — the leaderboard/density asks (your requirement) + quick wins
1. **Achievement cards: drop the "Not submitted" list from the card face.** Only
   players *with* submissions show. (Optionally keep a tiny "N not yet submitted"
   count, expandable, on the achievement *detail* page only — concept 4 shows it as a
   small corner aside.) → your explicit requirement.
2. **New "Medals" matrix leaderboard** (concept 3 & 4): a compact grid, players ×
   achievements, each cell a medal icon (First / Best / efficiency / none) + a Total
   Points column. One screen shows *every* category at once — directly serves "see
   more categories." Add as a tab alongside the existing points leaderboard.
3. **First-place "trophy card" treatment** for the winner on each achievement (icon +
   winner name + level/time + View Proof), matching concepts 1/2/4 — denser and more
   celebratory than the current banner.

## Tier 2 — visual hierarchy & consistency (full visual review)
4. **Dashboard reorg** to the concept-4 hierarchy: League Champion card · "First
   Achievements" trophy row · Recent Activity · Leaderboard standings. All data exists;
   it's layout + CSS.
5. **Consistent medal iconography** as reusable CSS (gold medallions for First/Best/
   Lowest-played/Fewest-kills/Lowest-level) used everywhere medals appear.
6. **Roster cards** (concept 2): class/level badge + a stat line (Life/ES/Armour *if*
   we can parse them from the PoB code) + prominent "Paste your PoB code" CTA; add
   grid/list toggle + class/player filters.

## Tier 3 — copy & clarity + mobile
7. **Copy pass:** headings, labels, empty states, onboarding hints — tighten tone
   ("Prove your strength. Be the first." style), make CTAs obvious.
8. **Mobile density** (concept 6): make the denser cards + the medals matrix collapse
   cleanly on phones (horizontal-scroll the matrix, stack cards).
9. **Light-theme polish:** the earlier hardcoded dark colours in proofs/firsts/social
   css need light-mode overrides (already flagged in ROADMAP).

## Open decisions (need your call)
- **Art policy:** keep no-game-art (recommended — badges + user avatars), or revisit?
- **"Not submitted":** remove entirely from cards, or keep a small expandable count on
  the detail page?
- **Scope to apply now:** all three tiers, or Tier 1 first then reassess?
- **Roster stat line:** worth parsing Life/ES/Armour out of PoB codes, or keep
  class/level only for now?
