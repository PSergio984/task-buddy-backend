# Habitica Economy Formulas — Fact Base

Research for game-economy design ticket. All code citations are from
[HabitRPG/habitica](https://github.com/HabitRPG/habitica), `develop` branch,
paths under `website/common/script/` (shared client/server logic) and
`website/server/` (server-only). Wiki citations are habitica.fandom.com pages.

Notation used below: `V` = `task.value` (per-task hidden stat), `P` =
`task.priority` (difficulty multiplier), `crit` = critical-hit multiplier,
`delta` = the signed change in task value produced by a score event.

---

## 1. XP-to-level curve

`toNextLevel(lvl)` in `website/common/script/statHelpers.js`:

```js
if (lvl < 5)  return 25 * lvl;
if (lvl == 5) return 150;
return Math.round((lvl**2 * 0.25 + 10*lvl + 139.75) / 10) * 10;
```

- Levels 1→4: `25 × level` (25 / 50 / 75 / 100 XP).
- Level 5→6: hard-coded 150 XP.
- Level ≥6: `0.25·lvl² + 10·lvl + 139.75`, rounded to the nearest 10.
  - e.g. L10→11 = 260, L50→51 ≈ 1,780, L100→101 = 3,640.
- Level-up is a while-loop: excess XP carries into the next level;
  each level-up **refills HP to max (50)** and grants **1 stat point**
  (capped at 100 total allocated points; `MAX_STAT_POINTS = MAX_LEVEL = 100`).
  Sources: `fns/updateStats.js` (`user.stats.hp = MAX_HEALTH`,
  `user.stats.points = user.stats.lvl - allocatedStatPoints`),
  `constants.js` (`MAX_HEALTH=50`, `MAX_LEVEL=100`, `MAX_LEVEL_HARD_CAP=9999`).
- Soft cap: stat bonuses from level stop growing at level 100
  (`capByLevel`, `statHelpers.js`); absolute level hard cap = 9,999.

Cross-check: wiki "Experience Level Chart" documents the identical formulas and
links to the same `statHelpers.js` lines:
<https://habitica.fandom.com/wiki/Experience_Level_Chart>

---

## 2. XP / gold / HP awards per action type

All scoring goes through `scoreTask()` in
`website/common/script/ops/scoreTask.js`.

### 2a. Task value (V) — the hidden driver

- Every task carries `task.value`, starting at 0 (yellow), bounded for reward
  purposes to `[-47.27, +21.27]` (`MAX_TASK_VALUE`, `MIN_TASK_VALUE`).
- Each score event moves V by `delta = ±0.9747^V` (positive for up, negative
  for down). Because `0.9747^V` shrinks as V rises, a task you do often yields
  less reward; a task you keep failing goes red (V → −47) and each failure
  hurts/pays progressively more (max |delta| ≈ 3.36 at V=−47.27; min ≈ 0.58
  at V=+21.27). Source: `_calculateDelta()` in `scoreTask.js`;
  wiki <https://habitica.fandom.com/wiki/Task_Value> documents the same
  `0.9747^x` curve and the same effective bounds.
- Unchecking a completed daily/to-do recomputes a reverse delta so the
  reward is almost exactly clawed back (`_calculateReverseDelta`).

### 2b. Difficulty → priority (P)

`website/client/src/components/tasks/modal-controls/selectDifficulty.vue`:

| Difficulty | P   | Stars |
|------------|-----|-------|
| Trivial    | 0.1 | 1     |
| Easy       | 1.0 | 2     |
| Medium     | 1.5 | 3     |
| Hard       | 2.0 | 4     |

`taskDefaults.js` sets `priority: 1` (Easy) as the default.

### 2c. Rewards per action

`_addPoints()` in `scoreTask.js`:

- **XP** = `round(delta × (1 + 0.025·INT) × P × crit × 6)`
  - Baseline (V=0, Easy, INT 0, no crit): **6 XP**; Medium 9, Hard 12,
    Trivial ≈ 0.6 → 1.
- **GP** = `delta × P × crit × (1 + 0.02·PER)`, `Math.ceil` on gain /
  `Math.floor` on uncheck.
  - Baseline: **~1 GP** per Easy task at V=0.
- **Streak bonus** (dailies only, `task.streak` ≥ 1):
  `gp × (1 + streak/100)`; if the increment < 1 it is forced to ±1.
- **Habit + click**: same XP+GP formulas above (only if delta > 0).
- **Habit − click**: **no XP/GP loss** — only HP damage (see §4).
  Negative habits can *never* drain gold or XP.
- **Daily checked**: XP+GP as above, `streak += 1`, and a streak achievement
  every 21 streaks. Unchecking reverses the delta and removes a streak point.
- **To-do completed**: XP+GP as above; a to-do's V *decays every cron* while
  uncompleted (server `cron.js` scores it `direction:'down'`, which only moves
  V — older to-dos go red and are worth more when finally done).
- **Checklists**:
  - To-do: delta × `(1 + #completed items)` → each checked sub-item is a full
    extra reward multiplier.
  - Daily missed at cron: damage × `(1 − fraction of checklist completed)`
    (partial credit only against *damage*, not rewards).
- **Custom Reward purchase**: `gp -= task.value` (default reward price 10 GP).
  Source: `scoreTask.js` reward branch; `taskDefaults.js` (`value: 10`).

### 2d. Mana (in the same loop)

`_gainMP()` in `scoreTask.js`; `maxMP = 2·INT + 30` (`libs/statsComputed.js`):

- Habit click: `max(0.25, 0.0025·maxMP)` MP (lost on − click).
- Daily/To-do: `max(1, 0.01·maxMP)` MP; ×(checklist items) for to-dos.
- Cron regen: `max(10, 0.1·maxMP) × (completed fraction of due dailies)`
  — see `website/server/libs/cron.js` end. Confirmed by wiki
  <https://habitica.fandom.com/wiki/Mana_Points>.

---

## 3. Stats (STR / INT / CON / PER) and equipment modifiers

Effective stat (`statsComputed`, `website/common/script/libs/statsComputed.js`):

```
total(stat) = gearBonus + classBonus + allocatedPoints + buff + floor(level/2)
```

- `floor(level/2)` uses `capByLevel(lvl)` → max +50 at level 100.
- `classBonus` = gear stat counted **a second time** when
  `item.klass === user.stats.class || item.specialClass === user.stats.class`
  → i.e., in current code wearing your class's gear **doubles** its stat
  contribution. (⚠ Discrepancy: wiki "Character Stats" claims class gear gets
  only a **+50%** bonus, i.e., 1.5× — wiki is likely stale vs. `develop`.
  Verify against production before relying on either number.)
- Stat point allocation: 1 point per level-up (from level 10, all points from
  earlier levels become available), manual or `autoAllocate`
  (flat / classbased / taskbased), capped at 100 total.

Per-stat effects, all verified in code:

| Stat | Effect (code location) |
|------|------------------------|
| INT  | `+2.5%` XP per point: `1 + 0.025·INT` in `_addPoints`; `maxMP = 2·INT + 30` |
| PER  | `+2%` GP per point: `1 + 0.02·PER`; `+1%` drop chance per point; daily drop cap `5 + floor(PER/25)` |
| CON  | Damage taken × `(1 − CON/250)`, floored at `0.1` → up to 90% reduction (`_subtractPoints`) |
| STR  | Crit: chance `0.03 × (1 + STR/100)`, multiplier `1.5 + 4·STR/(STR+200)` (`fns/crit.js`); boss/quest damage `1 + STR/200` (daily/todo) or `0.5 + STR/400` (habit) in `_changeTaskValue` |

Critical hits only roll on positive scores (`direction === 'up'`):
`crit = 1.5 + 4s/(s+200)` asymptotically → 5.5× at very high STR.

Also: `training[task.attribute] += delta` when `allocationMode==='taskbased'`
— each task is tagged with one attribute and feeds that stat's pool.

Source: `scoreTask.js`, `fns/crit.js`, `fns/updateStats.js`,
`fns/autoAllocate.js`; wiki <https://habitica.fandom.com/wiki/Character_Stats>.

---

## 4. HP loss / damage

`_subtractPoints()` in `scoreTask.js`:

```
hpMod = delta × (1 − CON/250, min 0.1) × P × 2
if (hpMod > -1) hp -= 1 else hp += ceil(hpMod)
```

- **Minimum 1 HP loss** per negative event (the `hpMod > -1` floor).
- At V=0, CON=0: Trivial −0.2→**1 HP** (floor), Easy −**2**, Medium −**3**,
  Hard −**4**. Wiki "Health Points" states the same base numbers:
  <https://habitica.fandom.com/wiki/Health_Points>.
- Negative habit click: same formula, applied immediately.
- **Missed daily at cron** (`website/server/libs/cron.js`): each due-but-not-
  completed daily is scored `direction:'down', cron:true` → same HP formula.
  `multiDaysCountAsOneDay = true` means several missed days are treated as one
  day of damage. Resting in the Inn (`preferences.sleep`) skips damage
  entirely; Rogue Stealth buff evades one missed daily per charge.
- Checklist partial credit reduces the daily's effective delta.
- Team-board dailies (`task.group.id`) do **not** damage their assignee.
- **Party/boss damage**: missed daily adds
  `progress.down += delta × min(P, 1)` — then `Group._processBossQuest`
  applies `down × quest.boss.str` as HP loss **to every quest participant**
  (`website/server/models/group.js`). Note Medium/Hard do not multiply party
  damage (intentional, see code comment).
- HP is clamped `0–50` (`updateStats.js`, `constants.js MAX_HEALTH`).
  Potion: +15 HP for 25 GP (`ops/buy/buyHealthPotion.js`, `content/index.js`).
- One-sided habits (only + or only −): `task.value` halves each cron toward 0
  (`processHabits` in `server/libs/cron.js`).

---

## 5. Death penalty at 0 HP

Trigger: `updateStats.js` clamps `hp` to 0; the penalty is applied by
`revive()` in `website/common/script/ops/revive.js` (runs when the user clicks
"Refill Health & Try Again" — death is a state, revival applies the cost):

- `hp → 50`, `exp → 0`, `gp → 0` (all gold, all level-progress XP).
- `lvl − 1`, floor at 1.
- **−1 allocated stat point**, chosen uniformly at random among
  `str/con/per/int` stats that currently have >0 points.
- **−1 random gear item** from `losableItems`: owned items where
  `value > 0` (free/special items exempt — Mystery gear can't be lost) AND
  (`klass === user.class` OR `klass === 'special'` matching `specialClass`
  OR `klass === 'armoire'`). Off-class gear is never lost. If it was
  equipped/costumed, the slot resets to `type_base_0`; the lost item is
  pinned back to the Market for repurchase with gold.
- Wiki confirms the same list (level + XP-to-date, all gold, 1 stat point,
  1 random repurchasable equipment piece):
  <https://habitica.fandom.com/wiki/Death_Mechanics>.
- Revive op: `ops/revive.js`; the "can't revive while alive" guard is
  `if (user.stats.hp > 0) throw NotAuthorized`.

---

## 6. Gear pricing & stat-bonus model

Gear content lives in `website/common/script/content/gear/`
(`armor.js`, `weapon.js`, `head.js`, `shield.js`, `back.js`, `body.js`,
`eyewear.js`, `head-accessory.js`, `sets/`). `content/gear/index.js` flattens
the tree into keys like `weapon_warrior_3` and defaults missing
`str/int/per/con` to 0, `klass`, `set = <klass>-<index>`, `type`, `value`.

Model per item: flat additive stat fields (`str`, `int`, `per`, `con`),
`value` = gold price, `klass` = owning class (`warrior|rogue|healer|wizard|
special|armoire|mystery|base`), `last` flag = final tier.

Warrior set (from `gear/sets/warrior.js`) — linear price/stat ladders per slot:

| Slot   | Stat | Tiers (stat @ price GP)                        |
|--------|------|------------------------------------------------|
| armor  | CON  | 3@30 → 5@45 → 7@65 → 9@90 → 11@120             |
| head   | STR  | 2@15 → 4@25 → 6@40 → 9@60 → 12@80              |
| shield | CON  | 2@20 → 3@35 → 5@50 → 7@70 → 9@90               |
| weapon | STR  | 0@1 (free) → 3@20 → 6@30 → 9@45 → 12@65 → 15@90 → 18@120 |

- Purchases are sequential per class (each tier gated by owning the previous;
  enforced in `ops/buy/buyMarketGear.js` + pinned-gear logic).
- Sell-back exists via `ops/sell.js` (items like eggs/food/mounts; gear is
  repurchased after loss rather than resold).
- Other classes mirror the shape with different primary stats
  (Rogue→PER, Wizard→INT, Healer→CON/INT mixed).
- Enchanted Armoire = gacha gold sink: **100 GP/pull**
  (`content/index.js` `armoire.value = 100`); yield = 60% equipment
  (from the `armoire` klass pool, while items remain), next 20% food,
  else XP = `floor(rand×40 + 10)` → 10–49 XP
  (`ops/buy/buyArmoire.js` thresholds 0.6 / 0.8).
- Health potion: 25 GP → +15 HP (`content/index.js` `potion.value = 25`).

---

## 7. Anti-inflation / pacing mechanics

- **Task-value bounds** `[-47.27, +21.27]` cap both reward and damage deltas
  per action (`scoreTask.js`).
- **Diminishing-returns hyperbola** `max·b/(b+h)`, `h = max/2`
  (`statHelpers.js#diminishingReturns`) — used to cap drop chance at 75%.
- **Drop system** (`fns/randomDrop.js`): base chance
  `min(|V − 21.27|, 37.5)/150 + 0.02` (≈16% at V=0), multiplied by `P`,
  `(1 + streak/100)`, `(1 + PER/100)`, new-user bonus `(1 + max(0,80−5·lvl)/100)`,
  checklist bonus `1 + 0.5·items`, `crit`; then `diminishingReturns(chance, 0.75)`.
  Daily drop cap `5 + floor(PER/25) + contributor.level` (×2 for subscribers);
  drop types split ~40% food / 30% egg / 30% potion (rarity rolls in file).
- **Cron collapse**: multiple missed days count as one day
  (`multiDaysCountAsOneDay` in `server/libs/cron.js`).
- **Streak multiplier is small** (1%/day on gold only) and habits decay toward
  0 if one-sided → natural sinks against farming.
- **Perfect Day buff**: completing all due dailies grants `ceil(level/2)` to
  ALL stats until next cron (`server/libs/cron.js`) — a daily-reset buff, not
  compounding wealth.
- **Stat point cap** 100 total; level bonus to stats caps at +50 (level 100);
  crit multiplier asymptotes at ~5.5×; CON damage reduction floored at 0.1×.
- **Gold→gems**: subscribers only, 20 GP per gem, monthly cap 24 + loyalty
  bonus (`libs/planGemLimits.js` `convRate:20, convCap:24`;
  `ops/buy/buyGem.js`). Wiki confirms 20 GP/gem:
  <https://habitica.fandom.com/wiki/Gold_Points>.
- **Mana gating**: skills are the "spend MP for burst reward/safety" valve;
  `maxMP = 2·INT + 30`; regen is proportional to daily completion, so mana
  income is tied to engagement, not task spam.
- Login incentives (`loginIncentives`) and level-gated unlocks (quests at
  15/30/40/60; rebirth at 50; classes at 10) pace content drip.

---

## Implications for Task Buddy (Pomodoro-driven economy)

- **Borrow the XP curve wholesale**: `25·lvl` early, then
  `0.25·lvl² + 10·lvl + ~140` rounded — it's battle-tested, trivial to
  implement, and produces satisfying early-game velocity.
- **Borrow difficulty multipliers** `{0.1, 1, 1.5, 2}` — maps cleanly onto
  task-estimation UI users already understand.
- **Borrow the hidden task-value decay** `0.9747^V` — for recurring
  tasks/habits it self-balances rewards and is the single most elegant
  anti-farming mechanic. But consider applying it per *focus session* rather
  than per click.
- **Simplify rewards**: keep XP = `delta × P × statBonus × K` with one or two
  multipliers; a ×6 XP / ×~1 GP split only makes sense with a gold economy —
  if Task Buddy has one currency, fold them together.
- **Keep stat effects linear & small** (2–2.5%/point) with hard caps;
  Habitica's caps (100 points, floor-0.1 CON, 75% drop cap) are what keep a
  10-year-old economy sane.
- **HP analog**: for a focus app, "damage" = broken pomodoros / missed
  commitments. Keep the **1-point minimum loss** and CON-style mitigation if
  you offer defensive stats; keep `hp ≤ 0` consequences forgiving
  (Habitica takes a level + all gold + gear — brutal; for retention, a
  lighter "lose today's bonus + streak" may fit better).
- **Cron evaluation is the right architectural pattern**: one end-of-day
  pass that settles all due-but-unmet commitments (with partial-credit for
  checklists/subtasks) — mirrors "missed daily" damage and "Perfect Day"
  rewards without per-event bookkeeping.
- **Partial credit everywhere**: checklist fraction reducing damage and
  increasing to-do reward is cheap to implement and removes "all-or-nothing"
  rage-quits.
- **Streaks**: +1%/day capped multiplier is enough to feel meaningful
  without inflation; pair with the 21-day streak achievement cadence.
- **Skip for v1**: classes/gear/stat allocation, mana, party/boss damage,
  pets/drops, gem conversion. If you later want a "focus gear" shop, copy the
  flat-stat + per-class ladder model (it's just data rows, no engine).
- **Watch the classBonus discrepancy** (code 2× vs wiki 1.5×) — a reminder
  that docs drift; whichever side you copy, test the actual deployed number.

### Unverified / caveats

- Class-gear bonus factor: `develop` code doubles the stat; wiki says +50%.
- Exact drop-split percentages after the food branch were truncated during
  extraction (~40/30/30 from partial read of `randomDrop.js`).
- Quest `boss.str` typical values were not sampled (defined per-quest in
  `content/quests/`).
- Mobile apps may run the same `common` scoring code; server cron is the
  authoritative daily settlement path.
