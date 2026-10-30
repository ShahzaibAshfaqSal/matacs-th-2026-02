"""AI steps: safety check, reading, and double-check. Runs the prompts in prompt_templates.py.

Proposal text is NOT stored in this repository (the brief asks us not to copy it).
To run this, create prototype/samples/A.txt ... E.txt yourself from the brief
(that folder is git-ignored), put your key in .env, then:

    pip install -r requirements.txt
    python extract.py --dry-run          # print the exact prompts and schemas, no API call
    python extract.py                    # run every samples/*.txt
    python score.py --facts out/extracted_facts.json

Proposals with suspicious text are held and listed in out/review_queue.json. After a
person has looked at them, record the decision in a JSON file and run again with
--decisions that_file.json:

    {"C": {"decision": "confirmed", "remove": ["<the exact suspicious passage>"]},
     "X": {"decision": "false_alarm"}}

Confirmed passages are cut out of the text before the reading step sees it.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from prompt_templates import (
    PROMPT_VERSION, SCREEN_SCHEMA, SCREEN_SYSTEM_PROMPT, SCREEN_USER_TEMPLATE, SYSTEM_PROMPT,
    USER_TEMPLATE, VERIFY_SCHEMA, VERIFY_SYSTEM_PROMPT, VERIFY_USER_TEMPLATE, build_schema,
    render_field_list,
)

HERE = Path(__file__).parent
MODEL = "claude-opus-5-5"

# Backup only: the AI safety check is the main detector. This list catches the
# obvious wording even if the AI step fails or is skipped.
BACKUP_PATTERNS = [
    r"automated (review|system|reviewer)",
    r"\b(AI|LLM|language model|assistant)\b.{0,40}\b(should|must|rank|score)",
    r"\brank (it|this|us)\b.{0,20}\bfirst\b",
    r"full marks",
    r"ignore (all|any|previous|the) ",
    r"pre-?approved",
]

WORD_NUMBERS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}

# Fields whose answer is a judgement, so a second AI call checks the quote supports it.
JUDGEMENT_TYPES = {"yes_no_unclear", "boolean", "level"}


def normalise(text):
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"-\s*\n\s*", "", text)  # words split across lines by the PDF
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_found(quote, source):
    """True if the quote is in the text, allowing small PDF-extraction differences."""
    q, s = normalise(quote), normalise(source)
    if not q:
        return False
    if q in s:
        return True
    match = difflib.SequenceMatcher(None, s, q, autojunk=False).find_longest_match(0, len(s), 0, len(q))
    return match.size / len(q) >= 0.9


def numbers_in(quote):
    found = set()
    for m in re.finditer(r"\$?(\d[\d,]*(?:\.\d+)?)\s*(m|million|k|thousand)?\b", quote, re.IGNORECASE):
        n = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        found.add(n)
        if unit in ("m", "million"):
            found.add(n * 1_000_000)
        elif unit in ("k", "thousand"):
            found.add(n * 1_000)
    for word in re.findall(r"[a-z]+", quote.lower()):
        if word in WORD_NUMBERS:
            found.add(float(WORD_NUMBERS[word]))
    return found


def backup_scan(text):
    return [p for p in BACKUP_PATTERNS if re.search(p, text, re.IGNORECASE)]


def load_env():
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


class Caller:
    """Sends one prompt and returns the parsed JSON. Keeps token counts for the audit log."""

    def __init__(self):
        import anthropic
        load_env()
        self.client = anthropic.Anthropic()
        self.input_tokens = 0
        self.output_tokens = 0
        self.model_used = None

    def __call__(self, system, user, schema, effort="medium"):
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        self.model_used = response.model
        if response.stop_reason == "refusal":
            return None
        return json.loads(next(b.text for b in response.content if b.type == "text"))


def check_answers(facts, fields, text, ask_ai):
    """Code checks every quote and number; a second AI call checks judgement answers."""
    problems = []
    for f in fields:
        entry = facts.get(f["name"])
        if not entry or entry["status"] != "stated":
            continue
        if not quote_found(entry["quote"], text):
            entry["status"] = "unclear"
            problems.append(f"{f['name']}: the quoted sentence could not be found in the proposal")
            continue
        if f["type"] in ("integer", "number") and entry["value"] is not None:
            if float(entry["value"]) not in numbers_in(entry["quote"]):
                entry["status"] = "unclear"
                problems.append(f"{f['name']}: the number {entry['value']} does not appear in its quote")
        elif f["type"] in JUDGEMENT_TYPES:
            result = ask_ai(VERIFY_SYSTEM_PROMPT,
                            VERIFY_USER_TEMPLATE.format(question=f["ask"], answer=json.dumps(entry["value"]),
                                                        quote=entry["quote"]),
                            VERIFY_SCHEMA, effort="low")
            if result is None or result["verdict"] != "supports":
                entry["status"] = "unclear"
                reason = result["reason"] if result else "double-check could not run"
                problems.append(f"{f['name']}: double-check disagreed ({reason})")
    return problems


def blank_facts(fields, concern):
    facts = {f["name"]: {"value": None, "status": "unclear", "quote": ""} for f in fields}
    facts.update({"injection_attempts": [], "concerns": [concern]})
    return facts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--criteria", default=HERE / "criteria" / "commercial_solar_v1.json")
    parser.add_argument("--samples", default=HERE / "samples")
    parser.add_argument("--out", default=HERE / "out")
    parser.add_argument("--decisions", help="reviewer decisions on held proposals (JSON)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = json.loads(Path(args.criteria).read_text(encoding="utf-8"))
    fields = cfg["fields"]
    schema = build_schema(fields)
    common = {
        "category": cfg["category"],
        "criteria_version": cfg["version"],
        "project_description": cfg["project"]["description"],
        "evaluation_date": date.today().isoformat(),
        "field_list": render_field_list(fields),
    }

    if args.dry_run:
        print("=== 1. SAFETY CHECK: SYSTEM ===\n" + SCREEN_SYSTEM_PROMPT)
        print("\n=== 1. SAFETY CHECK: USER ===\n" + SCREEN_USER_TEMPLATE.format(proposal_id="X", proposal_text="<PDF text>"))
        print("\n=== 2. READING: SYSTEM ===\n" + SYSTEM_PROMPT)
        print("\n=== 2. READING: USER ===\n" + USER_TEMPLATE.format(**common, proposal_id="X", proposal_text="<PDF text>"))
        print("\n=== 2. READING: OUTPUT SCHEMA ===\n" + json.dumps(schema, indent=2))
        print("\n=== 3. DOUBLE-CHECK: SYSTEM ===\n" + VERIFY_SYSTEM_PROMPT)
        print("\n=== 3. DOUBLE-CHECK: USER ===\n" + VERIFY_USER_TEMPLATE.format(
            question="<field question>", answer="<recorded answer>", quote="<quote>"))
        return

    files = sorted(Path(args.samples).glob("*.txt"))
    if not files:
        raise SystemExit(f"No .txt files in {args.samples}. See the notes at the top of this file.")
    decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8")) if args.decisions else {}

    ask_ai = Caller()
    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    all_facts, review_queue, audit = {}, {}, []

    for path in files:
        pid = path.stem
        original = path.read_text(encoding="utf-8")
        text = original

        # Steps 4a and 4b: AI safety check plus the backup word list (code).
        screen = ask_ai(SCREEN_SYSTEM_PROMPT, SCREEN_USER_TEMPLATE.format(proposal_id=pid, proposal_text=text),
                        SCREEN_SCHEMA, effort="low")
        passages = screen["suspicious_passages"] if screen else []
        backup_hits = backup_scan(text)
        suspected = bool(passages or backup_hits or screen is None)
        decision = decisions.get(pid, {}).get("decision")

        injection = {"status": "none", "passages": [{"location": p["location"], "reason": p["reason"]} for p in passages]}
        if suspected and decision is None:
            injection["status"] = "suspected"
            review_queue[pid] = {"passages": passages, "backup_hits": backup_hits}
            facts = blank_facts(fields, "Held: suspicious text waiting for a reviewer's decision.")
            facts["injection"] = injection
            all_facts[pid] = facts
            print(f"{pid}: HELD for reviewer ({len(passages)} passages, {len(backup_hits)} backup hits)")
            continue
        if decision == "confirmed":
            injection["status"] = "confirmed"
            for passage in decisions[pid].get("remove", []):
                text = text.replace(passage, "[removed by reviewer: instruction aimed at reviewers]")
        elif decision == "false_alarm":
            injection["status"] = "false_alarm"

        # Step 7: AI reads the proposal.
        user = USER_TEMPLATE.format(**common, proposal_id=pid, proposal_text=text)
        facts = ask_ai(SYSTEM_PROMPT, user, schema)
        if facts is None:
            facts = blank_facts(fields, "Model declined to read this proposal; manual review required.")

        # Steps 8a and 8b: rules check the answers, AI double-checks yes/no answers.
        problems = check_answers(facts, fields, text, ask_ai)
        facts["concerns"].extend(problems)
        facts["injection"] = injection
        all_facts[pid] = facts

        audit.append({
            "proposal": pid,
            "file_fingerprint_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "criteria_version": cfg["version"],
            "prompt_version": PROMPT_VERSION,
            "model": ask_ai.model_used,
            "injection": injection["status"],
            "backup_hits": backup_hits,
            "check_problems": problems,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        print(f"{pid}: done ({len(problems)} check problems)")

    (out_dir / "extracted_facts.json").write_text(json.dumps(all_facts, indent=2), encoding="utf-8")
    (out_dir / "review_queue.json").write_text(json.dumps(review_queue, indent=2), encoding="utf-8")
    with open(out_dir / "audit_log.jsonl", "a", encoding="utf-8") as log:
        for row in audit:
            log.write(json.dumps(row) + "\n")
    print(f"Wrote extracted_facts.json, review_queue.json; tokens in/out: {ask_ai.input_tokens}/{ask_ai.output_tokens}")


if __name__ == "__main__":
    main()
