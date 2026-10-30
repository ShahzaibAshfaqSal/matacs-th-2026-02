# Write-up

The [diagram](diagram/process-flow.png) shows the flow. In short: **AI reads, rules do the maths, people decide.**

## Assumptions

- $260,000 and 16 weeks are hard limits. Over the limit means not eligible. If a proposal doesn't say, it goes on hold and we ask the bidder.
- The licence must belong to the bidder, not a subcontractor.
- "Last 5 years" counts back from 2026. C's "since 2020" may include older jobs, so the reviewer checks it.
- Prices are compared as written, before tax.
- For hidden instructions, the admin's policy decides: disqualify, or score with a warning. I assume "score with a warning".
- Handling a very large number of proposals at once (speed, servers, cost limits) is out of scope. The design works one batch at a time. For big volumes, proposals could be processed in parallel, and saved answers keep repeat work low.

## 1. AI vs. rules

**AI, for understanding text:**
- **Safety check:** finds text that tries to give orders to a reviewer or an AI (like C). A word list is only a backup.
- **Reading:** answers the admin's questions, with the exact sentence for each answer, or "not stated".
- **Double-check:** confirms each sentence really supports its yes/no answer. For example, "a licensed subcontractor" does not mean the bidder holds a licence.

**Rules, for exact and repeatable results:** the hidden-text finder, the sentence-in-PDF check, number matching, must-have checks, limits, points and ranking.

**Why:** AI reads text that each bidder writes differently, but it doesn't give the same score twice. Rules do, and they are easy to explain.

The admin sets how each criterion is measured (lower or higher is better, checklist, or level scale), writes the AI's questions, and chooses "zero" or "hold" when a proposal doesn't mention it. So the rules never have to interpret criteria text.

## 2. Consistency and explainability

- AI answers are saved and reused, so ranking twice gives the same result.
- Points compare each bid with the best bid that passed the must-have checks:
  - Experience (30): installs ÷ most installs
  - Price (25): lowest price ÷ this price
  - Timeline (15): fastest ÷ this
  - Warranty (15): half panel, half workmanship, each ÷ best
  - Team (15): 3.75 each for lead, crew, safety plan and monitoring
- Held bids are included in the comparison, so clearing a hold doesn't change the other scores.
- The reviewer sees the points for each criterion and each sentence highlighted in the PDF. The reason is built from the points.

## 3. Human in the loop

- **Admin:** sets the criteria and tests new questions on old proposals first.
- **Hidden text:** a person sees it at normal size and decides. If it's real, it is removed before reading.
- **Reviewer:** confirms "not eligible", clears holds, checks doubted answers, and corrects or overrides with a reason. Changes are recalculated.
- **Bidder replies** are uploaded and go through every step again.
- **No answer:** a reminder after 2 working days, then a backup reviewer. Holds are never cleared automatically.
- **Final award:** always a person.

**Audit record (never edited):** who did what and when, the criteria version, the file, the AI model and prompt version, the AI answers with their sentences, the checks, the points, and every human change with its reason.

## 4. Changing criteria

- Each edit creates a new version. Old results stay linked to their version and are marked. A ranking never mixes versions.
- **Weights or formulas changed:** recalculate from the saved answers, with no AI.
- **New or changed question:** test it, then AI re-reads all proposals for that question only.
- Overrides must be confirmed again. A new kind of formula needs a developer.

## 5. Risks and safeguards

| Risk | Safeguard |
|---|---|
| Wrong reading | Sentence must be in the PDF, numbers must match, AI double-check, reviewer sees the sentence |
| Made-up facts | No sentence, no fact. "Not stated" goes on hold (D) |
| Manipulation (C) | AI safety check, word list and hidden-text finder; a person decides; the text is removed. The reading AI always treats proposals as information, not orders, and can't rank |
| Bias | One proposal per AI call; no view of other bids; the same formulas for all; sales claims ignored |
| Cost | Few small AI calls; answers saved and reused |

## Sample result

- **A** is 1st (98.0) and **E** 2nd (84.8).
- **B** is not eligible: the licence belongs to a subcontractor, even though B is the cheapest and fastest.
- **C** is on hold for its hidden instruction. If cleared, it would be 3rd (77.1).
- **D** is on hold because it gives no timeline. At 13–16 weeks it would be 3rd; at 12 weeks or less it would pass E for 2nd. So D is held, not dropped.
