# NearbyAI — Home Service Lead Agent

A conversational agent that turns a homeowner's problem ("Water started coming into my basement after the storm…")
into a **provider-ready lead** for a **real, verified local business**, with the fewest necessary questions and no
invented provider facts.

> **The LLM proposes; code decides.** Claude handles language: understanding, intent, and wording. Deterministic
> code handles orchestration, provider eligibility, safety policy, consent, and whether a lead is dispatchable.

## Results

| Assignment goal | Result |
|---|---|
| Lead conversion | **16/16** lead-eligible scenarios → dispatchable lead¹ |
| Lead quality / actionability | **4.19 / 5** from an LLM provider-perspective judge, vs **2.50 / 5** for paired degraded controls² |
| Outcome correctness | **20/20** scenarios reached the expected outcome³ (the 4 non-lead cases correctly ended as unsupported service, declined sharing, gas-leak safety redirect, out of area) |
| Conversation efficiency | median **5.5** user turns to a lead |
| Provider grounding | **25** real local businesses with source and coverage evidence; **100%** of applicable provider-grounding, coverage-truthfulness, eligibility, and consent checks passed |
| First-turn generalization | **112** frozen diverse openings: **0%** generic "pick a trade" fallback, **97.8%** labeled accuracy (rule-based baseline: 28.8%, 80.0%)⁴ |

¹ Lead-eligible excludes unsupported service, safety redirect, out of area, and an explicit refusal to share
contact information.
² Claude Opus as judge; 16 generated leads and 6 degraded controls, each judged blind and alone. The gap comes from
issue detail: degrading the issue description dropped scores by 2–3 points, removing timing alone did not.
³ One evaluator assertion was too strict (an exact-phrase check). It was corrected and re-applied to the saved
transcripts without rerunning any model; the original 19/20 report is kept.
⁴ Generated once, mostly by a different model than the agent, and frozen. It was also used to compare versions during
development, so it is a frozen benchmark, not a strictly held-out test.

**Evaluated version:** the headline metrics come from one run of each major suite on frozen commit `ea4d1e2`
(2026-10-08). Later fixes from manual testing were checked with deterministic tests, intent probes, and short Claude
smoke runs, not a full benchmark re-run. Details, baselines, and raw reports:
[docs/evaluation.md](docs/evaluation.md).

## Try it

```bash
cp .env.example .env                                       # add ANTHROPIC_API_KEY; without it, an offline rule-based backend runs
cd backend && uv sync
uv run uvicorn app.main:app --port 8000                    # open http://localhost:8000
```

`uv run pytest -q` runs the 285 deterministic tests (no API calls). Evaluation commands are in
[Running the evaluation](#running-the-evaluation).

## How it works

```
message → regex safety screen → ONE structured extraction call (Claude) → merge into LeadState
        → safety policy → user's explicit intent (edits, provider feedback, questions) → funnel → provider search
        → lead validator → reply: template → Claude rephrase → guardrails (template on any violation)
```

| Claude (`claude-sonnet-5-5`) proposes | Code decides |
|---|---|
| Job facts, corrections, and edits from free text | What to store, what a correction invalidates, whether each value is valid |
| Conversation intent: provider rejection, questions, impossible requests | Which intent to act on first; answers built from the provider record |
| A clarifying question for a vague problem | Whether that question is acceptable; otherwise a curated rule question |
| Which of 4 hazard families applies | Fixed safety copy; redirect or warn-and-continue (unioned with a regex screen) |
| A ranking of 2+ eligible providers | Eligibility: trade, coverage tier, phone present |
| The wording of each reply | Guardrails: no ungrounded phone/URL, booking claims, invented price or rating, or endorsements |
| — | Consent, `ready_to_dispatch`, and every outcome |

## Why this design

- **Conversion and lead quality depend on decisions that must not drift.** Sending a lead to an ineligible provider,
  or without consent, is a real failure, so those decisions are code and are covered by deterministic tests.
- **Homeowners describe problems in unpredictable ways.** Understanding, intent, and wording go to the LLM. When code
  did that language work, it failed on real phrasings (see the [design correction](#a-design-correction-worth-calling-out)).
- **A lead is only useful if the provider facts are true.** Every provider fact comes from a source-cited record, and
  the writer can't add any: guardrails reject invented claims, and the template is used instead.

---

## What it does

| Area | Behavior |
|---|---|
| Pilot geography | Santa Clara (95050/51/53/54), Sunnyvale (94085/86/87/89), North San Jose (95131, 95134). Elsewhere → honest `no_match`. |
| Trades | Plumbing, water-damage restoration, roofing, HVAC, electrical. Other services → `unsupported_category`. Borderline policy: a leak from an appliance's water line is plumbing; an appliance that won't run is appliance repair (out of scope). |
| Provider coverage | `verified` (the official site names the area) / `provisional` (nearby, area not named) / `unknown`. Verified-first; unknown is never matched. A provisional provider is used only after the user accepts an offer that says coverage is unconfirmed. |
| Outcomes | `ready_to_dispatch`, `self_serve` (user declines sharing; gets the provider's number), `no_match`, `unsupported_category`, `safety_redirect`, `utility_redirect`, `abandoned`. Outcomes **reopen** if the user later changes something material. |
| Blocking fields | Trade, issue summary, pilot location, one category-critical fact (asked once), timing (if it's still not given after two asks, the lead says "not stated"), name, valid contact, **explicit consent**, eligible provider. A missing street address → `address_pending` (still dispatchable). A specific visit time is kept next to the urgency and fixed to a date ("Same-day service preferred — Thursday, Oct 8 after 2 PM"). |
| Safety | Regex first line, unioned with the extractor's choice from 4 fixed hazard families. Gas/CO/fire → `safety_redirect`. Electrical + water, overheating, and sparking/buzzing → fixed warning first, then the lead continues. Safety copy is fixed in code and never rewritten by the LLM. The risk goes into the lead as a separate safety priority (and favors 24/7 providers); it is never written as the customer's timing. Observed facts ("sparks: no") are kept separately from the hazard, one fact at a time. |
| Utility outages | Whole-home no water/no power → first ask "only your home, or nearby homes too?" Neighbors affected → `utility_redirect`. Only this home → plumber/electrician. |
| User control | Reject a provider, ask for another, list options, choose or restore one by name. Questions about price, reviews, licensing, availability, privacy, and sponsorship get **code-built answers** from the provider record ("I don't have verified pricing…"). Requests to call, book, or guarantee are declined honestly. Consent can be revoked after a lead is prepared, which withdraws the lead. |
| Changing answers | "Can I change my address?" holds the request and asks for the new value. A value the user calls wrong is cleared, so the lead can't go out with it. An invalid phone, email, or ZIP is asked for again, saying what's wrong; the other fields in the same message are kept. Only a service-area change re-matches the provider. |
| Damage tips | A two-row fixed table (overflowing toilet, active pipe leak), shown at most once, kept verbatim. No diagnosis or DIY advice. |
| Wording | Acknowledges the user's concrete situation once. Never says "booked", "dispatched", or "will arrive". A provisional provider is "located near you", never "serves your area". No endorsements such as "good fit". |

Every behavior and its tests are listed in [docs/conversation_behaviors.md](docs/conversation_behaviors.md).

## Provider data

25 real businesses in [`data/providers.json`](data/providers.json), generated from the hand-verified matrix in
`data/source/` by `scripts/import_providers.py`. The script normalizes the matrix but never adds facts. Every record
has `source_url`, `coverage_evidence`, and `verified_at`. `emergency_service` is set only when the cited evidence says
24/7. Every trade × area cell has ≥ 2 verified providers in the current data; a test enforces ≥ 2 eligible
(verified or provisional) providers per cell.

## Architecture in detail

```
user message
  → regex safety screen (works even if the LLM fails)
  → ONE structured extraction call (Pydantic-validated, ≤3 attempts; failure keeps prior state):
      job facts · corrections · field edits · provider feedback · question topics · impossible requests ·
      consent changes · hazard families · utility signal · a proposed clarifying question
  → merge into LeadState (each value validated on its own; corrections invalidate stale facts, match, and consent)
  → safety policy (regex ∪ LLM hazard families → fixed copy; redirect or warn-and-continue)
  → explicit user intent first: field edits and invalid values, provider feedback, then questions and impossible
    requests (answered from the record), then the funnel resumes the pending question. The funnel is the default
    path, not a script.
  → funnel (next_action.decide): utility check → trade → clarification → location → qualification
      → match → timing → contact (+ optional address) → consent
      clarification = validated LLM question → curated rule question → generic menu (last resort)
  → provider search: hard filter (trade ∧ coverage tier ∧ has phone) → 0: no_match · 1: select ·
      2+: LLM ranks the eligible IDs once; later "someone else" uses that ranking with no new call
  → lead validator (only code sets ready_to_dispatch) + 0–100 completeness score (fields present; lead
      quality itself is measured by the provider-perspective judge)
  → wording: template → Claude rephrase → guardrails (ungrounded phone/URL, booking or availability claims,
      invented price/rating/license, endorsements, internal details, provisional-as-verified, dropped damage tip,
      targeted question turned into a menu) → template on any violation
```

Key files: [`agent.py`](backend/app/services/agent.py) (per-turn orchestration),
[`next_action.py`](backend/app/services/next_action.py) (funnel),
[`llm.py`](backend/app/services/llm.py) (extraction schema, writer, guardrails),
[`state_manager.py`](backend/app/services/state_manager.py) (merge and invalidation),
[`safety.py`](backend/app/services/safety.py), [`clarification.py`](backend/app/services/clarification.py),
[`provider_intents.py`](backend/app/services/provider_intents.py), [`answers.py`](backend/app/services/answers.py),
[`edits.py`](backend/app/services/edits.py), [`validation.py`](backend/app/services/validation.py),
[`lead_validator.py`](backend/app/services/lead_validator.py), [`domain.py`](backend/app/domain.py).

Stack: FastAPI, Pydantic, SQLAlchemy + SQLite, a static single-page frontend, Python 3.13 with uv.

### A design correction worth calling out

Two manual tests failed the same way: "I don't like DG, any other options?" was ignored, and "There is no water in my
home" got the five-trade menu. The stored state showed **Claude had understood both** (the user rejected DG; no water
pointed to plumbing). The code had no field for the first, and replaced the second with a fixed template. Code was
doing the language work.

The fix moved that work back to the LLM without giving it the business decisions. Extraction now also reports
conversation intent and proposes the clarifying question. Code decides whether to act and validates what the LLM
proposed. On the frozen 112-opening benchmark, generic fallbacks fell from **17.3% to 0%**, and labeled accuracy
improved from **71.1% to 97.8%** in the final version.

## Evaluation

Five separate suites: 285 deterministic tests, 81 intent probes (incl. 12 negative controls), 20 simulated-user
scenarios, a frozen set of 112 first-turn openings written by a different model than the agent, and a
provider-perspective lead judge with paired degraded controls. Safety detection is reported in separate pools
(semantic stress cases outside regex coverage: regex alone 0/6, regex + LLM 6/6). A turn takes about **5.4 s**.

Full tables, baselines, the evaluator correction, bugs the evaluation found, and the changes made after the final
run are in [docs/evaluation.md](docs/evaluation.md). Raw reports are in
[`data/evaluation/results/`](data/evaluation/results/).

### Running the evaluation

From `backend/`:

```bash
uv run python ../scripts/run_eval.py                                                 # offline scenario eval (rule-based backend)
uv run python ../scripts/run_eval.py --backend anthropic --simulator claude --judge   # 20 scenarios + provider judge
uv run python ../scripts/run_generalization.py --judge                                # 112 first-turn openings
uv run python ../scripts/run_intent_probes.py                                         # 81 intent probes
```

## Privacy note

Demo: please use test contact information and don't enter sensitive personal information. Conversation data is stored
in a local SQLite file for evaluation and debugging. Contact details reach a provider only through a lead the user
explicitly approves, and this demo never sends leads. An optional `DEMO_ACCESS_CODE` gates the API, and there is a
per-IP rate limit.

## Known limits and next steps

- **Production next steps:** hosted deployment, eval-candidate export, and masking contact information in logs.
- **Evaluation limits:** 20 scenarios (1 scenario = 5%); a small judge sample with no manual calibration; the
  simulator is more cooperative than real users; the 112-opening set tests only the first turn.
- **Safety:** regex false alarms on resolved or hypothetical statements ("the buzzing was fixed"). A proposed fix is
  on hold: let an explicit LLM "not present" judgment veto regex-only warnings, but never gas/CO/fire.
- **Wording:** about 1% of replies fall back to the template when the menu guardrail misfires on multi-issue replies.
- **Latency:** about 5 s per turn (two sequential model calls); streaming the reply or a faster extraction model
  would be the first steps.
- **Untested product ideas:** the judge valued issue detail far more than timing, and street address was its most
  requested missing item. Making timing optional, or collecting the address later, are experiments I didn't run, so
  as not to tune the product to the evaluator after seeing results.
- **Scope:** one provider per lead (no shared leads). Up to 3 options are listed. No provider comparisons, because the
  dataset has no quality signals. Consent covers name and contact for one provider, and the address can be withheld.
- **Not built, by design:** RAG/pgvector (after hard filtering there are 2–5 candidates; at 1,000+ providers I'd add
  embedding retrieval before the rerank, keeping the hard filter), ReAct, multi-agent orchestration, auth, real
  SMS/dispatch, booking, maps, troubleshooting advice.
