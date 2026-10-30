# AI Proposal Triage: Design

**Name:** Shahzaib Ashfaq
**Reference:** MATACS-TH-2026-02
**Time spent:** About 4.5 hours

The core design took about the expected time. The extra time went into:
- building and testing the optional prototype;
- checking every fact and score against the brief;
- a critical review of my own design, looking for edge cases such as D's missing timeline.

## Files

- [WRITEUP.md](WRITEUP.md): answers to the five questions
- [diagram/process-flow.png](diagram/process-flow.png): the flow from upload to ranked list
- [PROMPTS.md](PROMPTS.md): the three AI prompts, exactly as sent
- [ranking.json](ranking.json): ranking of proposals A–E
- [prototype/](prototype/): optional scripts

## Result

| Proposal | Result |
|---|---|
| A | 1st, 98.0 |
| E | 2nd, 84.8 |
| C | On hold: hidden instruction telling the AI to rank it first |
| D | On hold: no completion time |
| B | Not eligible: the licence belongs to a subcontractor |

## How I used AI tools

I designed the overall flow myself: the steps, where AI is used, where rules are used, and where a person decides. I used AI (Claude) as an assistant to suggest options, write the code, draw the diagram and speed up the writing. I reviewed every suggestion and made the final decisions.

**Where I corrected the AI:**

- **Catching hidden instructions.**
  - *The AI's plan:* catch them by searching for set words, like "rank this first".
  - *The problem:* the same trick can be written in other words.
  - *My fix:* an AI reads each proposal looking for tricks, with the word search kept only as a backup. A person confirms, and the trick is removed before scoring.
- **Checking the AI's answers.**
  - *The AI's plan:* if the quoted sentence is found in the PDF, the answer is correct.
  - *The problem:* the sentence can be real but the answer wrong. For example, the sentence says 12 weeks but the answer says 14.
  - *My fix:* numbers must match the sentence, and a second AI checks that each yes/no answer fits its sentence.
- **Criteria written in words.**
  - *The AI's plan:* code applies every criterion.
  - *The problem:* code can't understand something like "quality of the safety plan".
  - *My fix:* the admin picks how each criterion is measured, and word-based criteria get a simple level scale (0 none, 1 mentioned, 2 detailed).
- **Missing cases.**
  - *The problem:* the AI's plan didn't say what happens if the reviewer never replies, and treated adding a criterion as a small change.
  - *My fix:* a reminder, then a backup reviewer, and held items are never cleared on their own. New questions are tested before use.
- **Proposal D's missing timeline.**
  - *The AI's plan:* it noted that even at the full 16 weeks, D would still score below E, so holding D seemed safe.
  - *The problem:* that only checks the slowest case.
  - *My fix:* I tested faster timelines. If D says 12 weeks or less, it beats E for 2nd place. So D must stay on hold until a person gets its timeline.

## Prototype (optional)

- `python prototype/score.py --write ranking.json` recreates the ranking. It needs no AI and no key.
- `python prototype/extract.py --dry-run` prints the three prompts. **This script has not been run with a real API key yet.**
- The criteria are stored as data in `prototype/criteria/commercial_solar_v1.json`, so nothing is hard-coded.
- To run the AI part:
  1. Put each proposal's text in `prototype/samples/A.txt` to `E.txt` (this folder is not uploaded).
  2. Copy `.env.example` to `.env` and add your key.
  3. Run `pip install -r prototype/requirements.txt`, then `python prototype/extract.py`.
