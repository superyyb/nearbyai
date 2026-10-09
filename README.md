# NearbyAI — Home Service Lead Agent

A conversational intake agent that turns a homeowner's problem ("Water started coming into my basement after the
storm…") into a **provider-ready lead** for a **real, verified local business**. It aims for the fewest necessary
questions and never invents provider facts.

> **LLM** for language understanding, intent, and wording. **Deterministic code** for orchestration, eligibility,
> safety policy, consent, and dispatchability. The LLM proposes; code decides.

**Status:** the product and evaluation are complete. Final results are from one run on frozen commit `ea4d1e2`
(2026-10-08). Deployment is not done yet.

## Run locally

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY (optional)
cd backend
uv sync
uv run uvicorn app.main:app --port 8000    # http://localhost:8000
uv run pytest -q                           # 188 deterministic tests, no API calls
uv run python ../scripts/run_eval.py       # offline scenario eval (rule-based backend)
```

Evaluation commands (Claude; costs are measured, list prices):

```bash
uv run python ../scripts/run_eval.py --backend anthropic --simulator claude --judge   # 20 scenarios + provider judge, ~$1.00
uv run python ../scripts/run_generalization.py --judge                                # 112 first-turn openings, ~$1.31
uv run python ../scripts/run_intent_probes.py                                         # 54 intent probes, ~$0.28
```

With a key, the app uses Claude (`claude-sonnet-5-5`) for extraction, wording, and reranking. Without one, it runs on
an offline rule-based backend. That backend is also the baseline in every comparison below.

## What it does

| Area | Behavior |
|---|---|
| Pilot geography | Santa Clara (95050/51/53/54), Sunnyvale (94085/86/87/89), North San Jose (95131, 95134). Elsewhere → honest `no_match`. |
| Trades | Plumbing, water-damage restoration, roofing, HVAC, electrical. Other services → `unsupported_category`. Borderline policy: a leak from an appliance's water line is plumbing; an appliance that won't run is appliance repair (out of scope). |
| Provider coverage | `verified` (the official site names the area) / `provisional` (nearby, area not named) / `unknown`. Verified-first; unknown is never matched. A provisional provider is used only after the user accepts an offer that says coverage is unconfirmed. |
| Outcomes | `ready_to_dispatch`, `self_serve` (user declines sharing; gets the provider's number), `no_match`, `unsupported_category`, `safety_redirect`, `utility_redirect`, `abandoned`. Outcomes **reopen** if the user later changes something material. |
| Blocking fields | Trade, issue summary, pilot location, one category-critical fact (asked once), timing, name, valid contact, **explicit consent**, eligible provider. A missing street address → `address_pending` (still dispatchable). |
| Safety | Regex first line, unioned with the extractor's choice from 4 fixed hazard families. Gas/CO/fire → `safety_redirect`. Electrical + water, overheating, and sparking/buzzing → fixed warning first, then the lead continues. Safety copy is fixed in code and never rewritten by the LLM. |
| Utility outages | Whole-home no water/no power → first ask "only your home, or nearby homes too?" Neighbors affected → `utility_redirect`. Only this home → plumber/electrician. |
| User control | Reject a provider, ask for another, list options, choose or restore one by name. Questions about price, reviews, licensing, availability, privacy, and sponsorship get **code-built answers** from the provider record ("I don't have verified pricing…"). Requests to call, book, or guarantee are declined honestly. Consent can be revoked after a lead is prepared, which withdraws the lead. |
| Damage tips | A two-row fixed table (overflowing toilet, active pipe leak), shown at most once, kept verbatim. No diagnosis or DIY advice. |
| Wording | Acknowledges the user's concrete situation. Never says "booked", "dispatched", or "will arrive". A provisional provider is "located near you", never "serves your area". |

## Architecture

```
user message
  → regex safety screen (works even if the LLM fails)
  → ONE structured extraction call (Pydantic-validated, ≤3 attempts; failure keeps prior state):
      job facts · corrections · provider feedback · question topics · impossible requests ·
      consent changes · hazard families · utility signal · a proposed clarifying question
  → merge into LeadState (corrections invalidate stale facts, match, and consent)
  → safety policy (regex ∪ LLM hazard families → fixed copy; redirect or warn-and-continue)
  → explicit user intent first: provider feedback, then questions and impossible requests (answered from the
    record), then the funnel resumes the pending question. The funnel is the default path, not a script.
  → funnel (next_action.decide): utility check → trade → clarification → location → qualification
      → match → timing → contact (+ optional address) → consent
      clarification = validated LLM question → curated rule question → generic menu (last resort)
  → provider search: hard filter (trade ∧ coverage tier ∧ has phone) → 0: no_match · 1: select ·
      2+: LLM ranks the eligible IDs once; later "someone else" uses that ranking with no new call
  → lead validator (only code sets ready_to_dispatch) + 0–100 completeness score (fields present; lead
      quality itself is measured by the provider-perspective judge)
  → wording: template → Claude rephrase → guardrails (ungrounded phone/URL, booking or availability claims,
      invented price/rating/license, internal details, provisional-as-verified, dropped damage tip,
      targeted question turned into a menu) → template on any violation
```

Key files: [`agent.py`](backend/app/services/agent.py) (per-turn orchestration),
[`next_action.py`](backend/app/services/next_action.py) (funnel),
[`llm.py`](backend/app/services/llm.py) (extraction schema, writer, guardrails),
[`safety.py`](backend/app/services/safety.py), [`clarification.py`](backend/app/services/clarification.py),
[`provider_intents.py`](backend/app/services/provider_intents.py), [`answers.py`](backend/app/services/answers.py),
[`lead_validator.py`](backend/app/services/lead_validator.py), [`domain.py`](backend/app/domain.py).
Every behavior and its tests are listed in [docs/conversation_behaviors.md](docs/conversation_behaviors.md).

### A design correction worth calling out

Two manual tests failed the same way: "I don't like DG, any other options?" was ignored, and "There is no water in my
home" got the five-trade menu. The stored state showed **Claude had understood both** (the user rejected DG; no water
pointed to plumbing). The code had no field for the first, and replaced the second with a fixed template. Code was
doing the language work.

The fix moved that work back to the LLM without giving it the business decisions. Extraction now also reports
conversation intent and proposes the clarifying question. Code decides whether to act and validates what the LLM
proposed.

## Provider data

25 real businesses in [`data/providers.json`](data/providers.json), generated from the hand-verified matrix in
`data/source/` by `scripts/import_providers.py`. The script normalizes the matrix but never adds facts. Every record
has `source_url`, `coverage_evidence`, and `verified_at`. `emergency_service` is set only when the cited evidence says
24/7. Every trade × area cell has ≥ 2 verified providers in the current data; a test enforces ≥ 2 eligible
(verified or provisional) providers per cell.

## Evaluation

The suites are kept separate, so that a cheap check doesn't get mistaken for a broad one, and a small result doesn't
get reported as if it were general.

| Suite | What it proves | Judged by | Cost / run |
|---|---|---|---|
| Deterministic tests (188) | Invariants, state transitions (orchestration via a scripted extractor), and the eval harness's own checks | code | free |
| Intent probes (54, incl. 5 negative controls) | Varied wording maps to the right event; plain answers don't trigger events | code | ~$0.28 |
| Simulated-user scenarios (20) | End-to-end conversations; structured (offline) or Claude persona simulator | code | ~$0.87 for 20 |
| First-turn generalization (112, frozen) | Behavior on inputs the code's author didn't write | code + optional Opus judge | ~$1.3 with judge |
| Provider-perspective lead judge | Would a local business act on the lead? Paired degraded copies check that the judge discriminates | Opus | ~$0.13, runs with the scenarios |

**Testing cadence:** pytest on every change. For a fix, only the related Claude cases. For a shared component, a
small smoke set. Full runs only at milestones. Real failures become regression tests; the generalization set stays
frozen so versions stay comparable.

### Final results (one run each on frozen commit `ea4d1e2`; total cost $2.59)

Reports are in [`data/evaluation/results/`](data/evaluation/results/) (see its README for each file;
scratch output from runs goes to the git-ignored `reports/`).

**End-to-end conversations** — 20 scenarios, Claude-simulated users
([`final_scenarios_claude.md`](data/evaluation/results/final_scenarios_claude.md)):

| Metric | Result |
|---|---|
| Scenarios reaching the expected outcome | **20/20** |
| Contractor-eligible scenarios that produced a dispatchable lead | **16/16** |
| The other 4 (pest control, declined sharing, gas leak, out of area) | correct non-lead outcome (`unsupported_category`, `self_serve`, `safety_redirect`, `no_match`) |
| Scenario behavior checks passed | 20/20 after correcting one evaluator assertion (below) |
| Median / mean user turns to a lead | 5.5 / 5.44 |
| Provider grounding · coverage truthfulness · eligibility · consent correctness | 100% · 100% · 100% · 100% |
| Extraction failures · rerank fallbacks · writer fallbacks to template | 0/95 · 0/19 · 1/94 |

One case originally failed an exact-phrase check: the reply answered "are they any good? how much?" in one sentence
("I don't have verified reviews, ratings, or pricing…"). The check now judges behavior (both questions recognized,
both topics addressed, "unavailable" stated, no invented claim), with tests. It was re-applied to the saved
transcripts **without rerunning any model**; the original 19/20 report is kept next to the rescored file.

The one writer fallback was a guardrail false positive: a reply about a roof leak *and* a broken AC named three
trades, which the "don't turn a targeted question into a menu" check flagged. The safe template was used instead.
It is left as a known limitation so that the evaluated product version stays the submitted one.

**Lead quality from the provider's side** — Opus judge, 16 generated leads plus 6 paired degraded copies, each judged
blind and alone, on a provider-view rendering (no consent, coverage, or provenance fields):

| Leads | n | Actionability (1–5) |
|---|---|---|
| Generated by the agent | 16 | **4.19** (thirteen 4s, three 5s) |
| Paired degraded copies, all | 6 | 2.50 |
| — vague issue description | 2 | 1.5 |
| — vague issue + no timing | 2 | 2.0 |
| — timing removed only | 2 | 4.0 (no change from the originals) |

In this evaluation set the judge strongly separated **issue-detail** degradation (all 4 such pairs dropped, by 2–3
points). Removing timing alone had no effect. `would_act` was 100% for generated leads and 83% for degraded ones:
with a phone number present, the judge nearly always "would call", so the 1–5 score is the useful signal. The sample
is small, and every generated lead scored 4–5, so this shows that actionable leads are distinguished from vague ones.
It doesn't show fine-grained quality ranking. Manual calibration of the judge was not done.

**First-turn generalization** — the frozen 112 openings, Claude:

| Metric | Before the refactor | After the refactor | **Final** |
|---|---|---|---|
| Generic fallback rate (reply recites the trade menu) | 17.3% | 0% | **0%** |
| Contextual clarification rate | 10% | 100% | **100%** |
| Labeled accuracy (45 hand labels) | 71.1% | 84.4% | **97.8%** |
| Opus judge mean (1–5, soft quality only) | 2.86 | 3.40 | **3.94** |
| Replies judged ≤ 2 | 52 | 32 | **8** |
| Hard violations / premature provider | 0 / 0 | 0 / 0 | 0 / 0 |

The openings were generated once by **a different model than the agent** (Opus; the agent runs on Sonnet), with
instructions not to target the supported trades. Two openings came from manual tests. Every pass/fail metric is
decided by code. Offline rule-based baseline on the same set: 28.8% generic fallback, 80.0% labeled accuracy.

**Safety detection** — pools reported separately:

| Pool | Regex only | Regex + LLM |
|---|---|---|
| Labeled safety openings (14; several **were used to extend the regex**, so this is regression coverage) | 14/14 | 14/14 |
| Held-out phrasings the regex cannot match (6) | 0/6 | **6/6** |
| Negative controls with scary words that shouldn't trigger (9): false alarms | 2 | 2 (both from regex) |

Known gap: the regex can't tell resolved or hypothetical statements ("the buzzing was fixed", "it might get hot
someday") from current hazards. The LLM gets these right, but the union inherits the regex's two false alarms.

**Intent probes:** 54/54 on the final code, including 5/5 negative controls (rule-based baseline: 29/44 on the
earlier 44-probe version). **Offline scenario baseline:** 19/20 (fails a typo-heavy opening).

**Cost and latency** (measured): about **$0.04 per conversation** for the agent itself (extraction, wording,
rerank). Caching the fixed system prompts halved extraction cost. A turn takes about **5.4 s** on average
(extraction 3.5 s + wording 1.9 s; p95 5.4 s and 4.7 s).

### Changes after the final run

The metrics above are for `ea4d1e2`. Two wording fixes came later from manual testing. Each was checked with
deterministic tests and a three-conversation Claude smoke run (the manual conversation replayed, a burst pipe, and
a provider rejection, all passing), not a full re-run:

- **Acknowledge new facts once.** Replies had restated the situation every turn ("Since the water started…",
  "Since your basement floor is still wet…"). The writer now gets the situation only on the first reply or when a
  turn adds a structured new fact (trade, impact, qualification fact, secondary issue). It also may not repeat the
  previous reply's opening.
- **Inferred source labeled as suspected.** The lead now says "Suspected source: storm-related water intrusion
  (exact source not confirmed)" instead of "Likely source: exterior / storm water".

### What the evaluation taught, and what I did not change

The provider judge valued **specific issue context much more than preferred timing**. Exact street address was the
most frequently requested missing item (14 of 16 leads). I kept both timing and address decisions unchanged, so as
not to optimize the product toward the evaluator after seeing results. Both are future experiments: making timing
optional to cut a turn, and collecting the address later in the funnel or after the provider accepts. The address
signal is partly a simulation artifact: most scenario personas were written to withhold their street address.

### Bugs the evaluation found

Each became a regression test: a negation-blind safety screen ("no sparks" triggered a warning and marked the lead
urgent); guessed qualification facts ("my neighbor says water is pooling" → "water still entering: yes"); a crash
when the reranker returned every candidate; a second question in one message going unanswered; consequences
mislabeled as separate issues; 6 missed hazards; an unprompted "I don't know what's wrong" read as "I don't know if
the neighbors have power", which skipped the utility check; a lead score labeled "quality" that only measured
completeness. Three failures came from manual testing, including the two architecture-level ones above. The
evaluation harness had bugs too (an over-strict assertion, a metric that counted out-of-scope replies as menus), so
its checks now have their own tests.

### Continuous evaluation

Conversations are logged (SQLite: `conversations`, `messages`, `leads`, `eval_candidates`). Conversations with
corrections, provider rejections, no match, unsupported or utility outcomes, extraction failures, guardrail
rejections, or too many turns are flagged as **eval candidates** for manual promotion. Nothing is added to the
benchmarks automatically. (An export script is still to do.)

## Privacy note

Demo: please use test contact information and don't enter sensitive personal information. Conversation data is stored
in a local SQLite file for evaluation and debugging. Contact details reach a provider only through a lead the user
explicitly approves, and this demo never sends leads. An optional `DEMO_ACCESS_CODE` gates the API, and there is a
per-IP rate limit.

## Known limits and next steps

- **To do:** deployment; eval-candidate export script; masking phone numbers in conversation logs.
- **Evaluation limits:** 20 scenarios (1 scenario = 5%); a small judge sample with no manual calibration; the
  simulator is more cooperative than real users; the 112-opening set tests only the first turn, so mid-conversation
  long tail is covered by deterministic tests and probes, not at scale.
- **Safety:** regex false alarms on resolved or hypothetical statements (above). A proposed fix is on hold: let an
  explicit LLM "not present" judgment veto regex-only warnings, but never gas/CO/fire.
- **Wording:** about 1% of replies fall back to the template when the menu guardrail misfires on multi-issue replies.
- **Latency:** about 5 s per turn (two sequential model calls); streaming the reply or a faster extraction model
  would be the first steps.
- **Scope:** one provider per lead (no shared leads). Up to 3 options are listed. No provider comparisons, because the
  dataset has no quality signals. Consent covers name and contact for one provider, and the address can be withheld.
- **Not built, by design:** RAG/pgvector (after hard filtering there are 2–5 candidates; at 1,000+ providers I'd add
  embedding retrieval before the rerank, keeping the hard filter), ReAct, multi-agent orchestration, auth, real
  SMS/dispatch, booking, maps, troubleshooting advice.
