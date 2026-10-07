# NearbyAI — Home Service Lead Agent

A conversational intake agent that turns a homeowner's problem ("Water started coming into my basement after the storm…") into a **provider-ready lead** for a **real, verified local business** — with the fewest necessary questions and no invented provider facts.

> LLM for language understanding and wording. Deterministic Python for orchestration, eligibility, validation, consent, and dispatchability.

## Run locally

```bash
cd backend
uv sync
uv run uvicorn app.main:app --port 8000      # open http://localhost:8000
uv run pytest -q                             # 31 deterministic tests
uv run python ../scripts/run_eval.py         # offline eval (no API key needed)
```

With `ANTHROPIC_API_KEY` set, the app uses Claude for extraction, wording, and reranking (`LLM_BACKEND=auto`, model `claude-sonnet-5-5`, override with `LLM_MODEL`). Without a key it runs on an offline rule-based backend, which is also the baseline for eval comparisons.

## Product rules (frozen)

| Area | Rule |
|---|---|
| Pilot geography | Santa Clara (95050/51/53/54), Sunnyvale (94085/86/87/89), North San Jose (95131, 95134). Other areas → honest `no_match`. |
| Categories | water damage restoration, plumbing, roofing, HVAC, electrical. Anything else → `unsupported_category`. |
| Coverage | `verified` (official site names the area) / `provisional` (nearby, area not named) / `unknown` / `out_of_area`. Verified-first: if any verified provider exists, only verified are eligible. Unknown is never auto-matched. |
| Wording | Verified → "lists Sunnyvale in its service area". Provisional → "located near you; coverage still needs to be confirmed". Never "booked / dispatched / will arrive". |
| Outcomes | `ready_to_dispatch`, `self_serve`, `no_match`, `unsupported_category`, `safety_redirect`, `abandoned`. |
| Blocking fields | category, issue summary, pilot ZIP, category-critical fact (asked once), timing, name, valid contact, **explicit consent**, eligible provider. |
| Street address | Asked once, alongside the contact question; missing → `address_pending` (lead still dispatchable, quality score lower). |
| Safety | Gas / fire / CO → `safety_redirect` (911 / PG&E guidance, no lead). Sparking / water near electrical → safety guidance first, then continue as urgent. Safety text is deterministic and never rewritten by the LLM. |
| UI | One primary provider; at most one alternative, only when coverage is provisional or the user self-serves. |
| Turn metric | A turn = one user message. Target: median successful user turns ≤ 6. |

## Architecture

```
user message
  → safety screen (regex, deterministic)
  → LLM extraction → Pydantic-validated ExtractionResult (≤3 attempts with error feedback;
                     failure keeps prior state)
  → merge into LeadState (corrections overwrite; category/location change clears stale facts + match + consent)
  → ambiguity rules (ceiling stain → roof vs plumbing, …) + deterministic funnel (next_action.decide)
  → provider search when category + pilot area + critical facts are known
       hard filter: category ∧ coverage tier   →  0: no_match · 1: select · 2+: LLM rerank among IDs
  → lead validator (only code can set ready_to_dispatch) + 0–100 quality score
  → wording: template → optional Claude rephrase → guardrails (ungrounded phone/URL, booking claims,
             provisional-as-verified, >1 question) → fall back to template on any violation
```

Key files: [`domain.py`](backend/app/domain.py) (LeadState, scope), [`next_action.py`](backend/app/services/next_action.py) (funnel), [`provider_search.py`](backend/app/services/provider_search.py), [`lead_validator.py`](backend/app/services/lead_validator.py), [`agent.py`](backend/app/services/agent.py) (per-turn orchestration), [`llm.py`](backend/app/services/llm.py) (Claude + guardrails).

## Provider data

25 real businesses in [`data/providers.json`](data/providers.json), generated from the hand-verified matrix in `data/source/` by `scripts/import_providers.py` (which normalizes but never adds facts). Every record has `source_url`, `coverage_evidence`, and `verified_at`. `emergency_service` is set only when the cited evidence says 24/7; otherwise it stays unknown. Every category × area cell has ≥ 2 verified providers (enforced by a test).

## Evaluation

`scripts/run_eval.py` runs 18 simulated-user scenarios ([`core_cases.json`](data/evaluation/core_cases.json)): each case has a persona, an opening, and **hidden facts** the simulated user answers from (it never invents). Scenarios cover the happy path, ambiguity, vague requests, corrections (ZIP, category), multiple issues, typos, unknown facts, refusal to share contact (→ self-serve), safety redirect, unsupported category, and out-of-area requests.

- `--simulator structured` (default, offline): answers the field the agent asked for. Deterministic regression.
- `--simulator claude`: Claude plays the persona from the agent's text only.
- `--judge`: provider-perspective Claude judge on finished lead packets, plus 4 **negative-control** packets (no location/contact, vague problem, no consent, category mismatch) to check that the judge actually discriminates.
- `--repeat 3 --repeat-tags ambiguous,correction`: stability check on high-risk cases.

Reports (metrics, failures, full transcripts, lead packets) are written to `data/evaluation/reports/`.

**Baseline — offline rule-based backend, structured simulator:**

| Metric | Value |
|---|---|
| Cases passing all checks | 17 / 18 |
| Service category accuracy | 93.8% |
| Dispatchable lead rate | 92.9% |
| Useful resolution rate (lead + self-serve) | 93.3% |
| Median / mean user turns to lead | 6 / 5.77 |
| Provider grounding | 100% |
| Coverage truthfulness | 100% |
| Provider eligibility | 100% |
| Consent correctness | 100% |
| Avg lead quality | 91.8 / 100 |

Known baseline failure: `typo_heavy` ("wter in my basment aftr the strom"). The regex extractor can't parse it; this is the main gap the Claude extractor is expected to close. *Claude backend results: pending an API key.*

Real conversations are logged (SQLite: `conversations`, `messages`, `leads`, `eval_candidates`). Conversations with corrections, category changes, no match, unsupported requests, too many turns, extraction failures, or writer-guardrail rejections are flagged as **eval candidates** for manual promotion into the core set. The core set is never modified automatically.

## Privacy note

Demo: please use test contact information. Conversation data is stored in a local SQLite file for evaluation and debugging. Optional `DEMO_ACCESS_CODE` gates the API; there is a basic per-IP rate limit.

## Not built (by design)

RAG / pgvector (after hard filtering there are 2–5 candidates; at 1,000+ providers I'd add embedding retrieval *before* the rerank, keeping the same hard filter), ReAct, auth, real SMS/dispatch, booking, maps.
