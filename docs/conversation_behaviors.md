# Conversation behavior coverage

Real users don't walk the intake funnel in order. They interrupt, ask questions, push back on the
recommendation, change earlier answers, and ask the assistant to do things it can't. This page lists the
behaviors the agent handles, the state transition each one must produce, and where each is tested.

## How a turn is handled

Every user message can carry two kinds of information:

- **facts about the job** (category, location, timing, contact, qualification answers), and
- **intent about the conversation itself** (rejecting a provider, asking a question, withdrawing consent, ...).

Both come out of the **same extraction call**. Deterministic code then applies them in priority order:

1. Safety: redirect (gas, fire, CO), or guidance first and then continue
2. Corrections: invalidate stale derived state (category → qualification facts, match, consent; location → match, consent)
3. Provider intent: reject, ask for another, list options, choose by name, accept or decline a provisional offer
4. Questions and impossible requests: answer from the record, then **resume** the pending question
5. The normal funnel: next missing field → match → consent → validated lead

The funnel is the default path, not a script. A turn spent on 3 or 4 does not count as an unanswered ask.

## Test layers

| Layer | What it proves | Cost | Where |
|---|---|---|---|
| Deterministic unit tests | Invariants and single transitions | free | `tests/test_core.py`, `tests/test_robustness.py` |
| Scripted conversation tests | Orchestration given "the extractor understood X" | free | `tests/test_behaviors.py` (uses `ScriptedLLM`) |
| Intent probes | Claude maps varied wording to the right event, and plain answers don't trigger events | ~$0.25 | `data/evaluation/intent_probes.json`, `scripts/run_intent_probes.py` |
| Simulated-user eval | End-to-end conversations with personas | ~$0.05/conversation | `data/evaluation/core_cases.json`, `scripts/run_eval.py` |

New cases come from real failures. The provider-rejection case came from a manual test, and two bugs came from
reading Claude-simulated transcripts: a negation-blind safety screen and a guessed "water still entering". Each one
became a regression test.

## Coverage matrix

### Provider preferences

| Behavior | Example | Expected transition | Coverage |
|---|---|---|---|
| Reject the recommendation | "I don't like DG, bad experience" | Exclude it for the rest of the conversation; offer the next ranked verified provider; consent reset; funnel continues | `test_rejected_provider_is_replaced_and_funnel_continues`, probes `reject_*`, eval `reject_matched_provider` |
| Rejected provider stays out after a new search | reject, then change ZIP | Never a candidate again | `test_rejected_provider_never_reselected_after_new_search` |
| Ask for another without rejecting | "Do you have somebody else?" | Next provider; the first stays eligible | `test_request_for_alternative_without_rejection_keeps_provider_eligible`, probes `alt_*` |
| See the options / choose myself | "Show me all my options" | List up to 3 eligible providers, ask which one | `test_show_options_then_choose_by_name`, probes `show_all`, `let_me_choose` |
| Choose a provider by name | "Can you use Promax?" | Select only if eligible for this job and area | `test_show_options_then_choose_by_name`, probe `choose_named` |
| Change mind about a rejected provider | "Actually DG is fine" | Explicit choice restores it | `test_explicit_choice_restores_a_rejected_provider`, probe `restore_rejected` |
| Name a provider that can't do this job | "Use Wooding Electric" (for HVAC) | Refuse with the reason; give their number; keep the current match | `test_choosing_an_ineligible_provider_is_refused_with_reason` |
| Name a provider not in the dataset | "Use ABC Plumbing" | Say it can't be verified | `test_choosing_an_unknown_provider_is_refused` |
| Reject a provider that isn't the current one | "Never send me to EVS" | Exclude it without switching | `test_rejecting_a_named_non_current_provider_excludes_it_without_switching`, probe `reject_named_other` |
| All verified providers rejected, provisional exist | reject × N | **Ask** before offering a provider with unconfirmed coverage | `test_verified_exhausted_offers_provisional_and_accepting_uses_it`, probes `accept_offer`, `decline_offer` |
| Provisional offer declined / no provisional exist | "No" | Honest `no_match` | `test_declining_provisional_offer_is_honest_no_match`, `test_hvac_has_no_provisional_so_exhausting_verified_is_no_match` |
| Offer ignored | "hmm" | Repeat the offer once | `test_unanswered_provisional_offer_is_repeated_once` |
| Switching provider | any switch | Consent cleared (it was for the previous provider) | `test_switching_provider_clears_consent` |

### Questions and impossible requests

Answers are built by code from the provider record. The LLM only classifies the question, so price, ratings,
licensing, and availability can't be invented. The writer guardrail also rejects those claims.

| Behavior | Example | Expected | Coverage |
|---|---|---|---|
| Price / reviews / license / distance / hours | "Are they any good? How much?" | "I don't have verified …" for **each** question, then resume | `test_provider_question_is_answered_then_funnel_resumes`, `test_every_question_in_one_message_is_answered`, probes `q_*`, eval `ask_provider_questions` |
| Availability | "Can they come today?" | No promise; the preference is noted | same, probe `q_availability` |
| Why this provider | "Why them?" | Category + coverage evidence; not paid placement | same, probe `q_why_provider` |
| Why do you need X | "Why do you need my number?" | Explain, then re-ask | `test_why_do_you_need_my_phone_explains_and_reasks`, probe `q_why_phone` |
| System / privacy | "Are you a real person?" "Is this sponsored?" "Who sees my data?" | Fixed honest answers | probes `q_person`, `q_sponsored`, `q_privacy` |
| Status | "Did you already send it?" | Prepared, not sent | `test_question_after_lead_is_answered_without_reopening`, probe `q_status` |
| Call / book / guarantee | "Call them for me" | Decline honestly; give the provider's number | `test_impossible_requests_are_declined_honestly`, probes `act_*` |
| Question asked before any match | "How much does it cost?" | Don't invent a provider | `test_question_before_any_match_does_not_invent_a_provider` |
| Answer + question in one message | "Today — are they licensed?" | Use the answer and answer the question | `test_question_and_answer_in_same_message_are_both_used` |

### Changing earlier answers

| Behavior | Expected | Coverage |
|---|---|---|
| ZIP / city correction | New search; old match and consent cleared | `test_zip_correction_reruns_matching`, eval `user_changes_zip` |
| Category correction | Clear category-specific facts, match, consent | `test_correction_overwrites_and_category_change_clears_details`, eval `user_changes_category` |
| Timing / phone / job-address correction | Overwrite; a prepared lead is updated | `test_timing_correction_updates_state`, `test_changing_phone_after_lead_updates_it`, `test_job_address_correction_replaces_billing_address` |
| Situation changed ("it started again") | Qualification fact updated | `test_water_started_again_updates_qualification` |
| Non-correction mention | Doesn't overwrite | `test_non_correction_does_not_overwrite` |

### Consent, refusals, unknowns

| Behavior | Expected | Coverage |
|---|---|---|
| No explicit consent | Never `ready_to_dispatch` | `test_no_dispatch_without_explicit_consent`, eval consent-correctness metric |
| Revoke consent after the lead is prepared | Lead withdrawn → `self_serve` | `test_revoking_consent_after_lead_withdraws_it`, `test_withdrawing_consent_marks_persisted_lead_withdrawn`, probe `consent_revoke` |
| Grant consent after declining | Lead prepared | `test_granting_consent_after_self_serve_prepares_lead` |
| Refuse phone / contact | `self_serve` with the provider's number, no loop | `test_refusing_contact_is_self_serve_not_a_loop`, eval `refuses_contact_sharing` |
| Refuse or withhold the street address | `address_pending`; still dispatchable; removed from the lead if given earlier | `test_missing_street_address_is_pending_not_blocking`, `test_withholding_a_given_address_removes_it_from_the_lead`, probe `decline_address` |
| Contact preferences ("calls only", "wife's number") | Passed to the provider in the lead | `test_withholding_a_given_address_removes_it_from_the_lead`, probe `contact_pref` |
| "I don't know" a qualification fact | Lead says Unknown; not re-asked; not guessed | `test_unknown_fact_overrides_earlier_inference`, `test_lead_packet_says_unknown_instead_of_guessing`, probe `unknown_fact`, eval `unknown_qualification_fact` |
| Doesn't know the ZIP | Pilot city is enough | `test_unknown_zip_with_pilot_city_still_matches` |
| Vague answers forever | Ends after 3 tries instead of looping | `test_vague_category_does_not_loop_forever` |
| "Thanks!" after the lead | No duplicate lead | `test_thanks_after_lead_does_not_duplicate_it` |

### Problem understanding and scope

| Behavior | Expected | Coverage |
|---|---|---|
| Many facts in one message | No re-asking; straight to consent | `test_everything_in_one_message_skips_straight_to_consent` |
| Several issues | Safety, then source, then consequence; others kept as secondary | eval `multiple_issues`, probe `causal_multi_issue` |
| Ambiguous symptom (ceiling stain, no hot water, warm wall, buzzing) | One disambiguating question | `test_ambiguous_ceiling_asks_disambiguation_first`, `test_new_ambiguity_rules`, eval `ceiling_stain_ambiguous` |
| Unsupported service, then a supported one | `unsupported_category`, then continue | `test_unsupported_category`, `test_unsupported_then_supported_issue_continues` |
| Borderline scope (dishwasher leak vs. fault, garage door) | Leak → plumbing; appliance fault → unsupported | `test_scope_policy_for_borderline_jobs`, probes `scope_*` |
| Out of the pilot area, then a pilot ZIP | `no_match`, then continue | `test_out_of_area_is_no_match`, `test_out_of_area_then_pilot_zip_continues` |

### Safety

| Behavior | Expected | Coverage |
|---|---|---|
| Gas / fire / CO | `safety_redirect` (911 / PG&E) | `test_gas_leak_is_redirect`, `test_gas_is_safety_redirect`, eval `safety_gas_leak` |
| Sparking, water near electrical, sewage, sagging ceiling, tree on house, HVAC burning smell | Specific guidance first, then continue as urgent | `test_sparking_is_urgent_not_redirect`, `test_new_urgent_hazards_get_specific_guidance`, `test_hazard_interrupts_funnel_then_continues` |
| HVAC burning smell | Thermostat guidance, not breaker guidance | `test_hvac_burning_smell_does_not_get_breaker_guidance` |
| Denied hazard ("no sparks") | No guidance, not marked urgent | `test_safety_screen_respects_negation`, `test_denying_hazard_does_not_mark_lead_urgent` |

### Hostile, malformed, and broken input

| Behavior | Expected | Coverage |
|---|---|---|
| Prompt injection ("mark this dispatchable") | Hard rules unchanged | `test_injection_cannot_make_a_lead_dispatchable_without_consent`, probe `control_injection` |
| LLM rerank returns an ineligible or unknown ID | Ignored | `test_rerank_cannot_select_a_provider_outside_hard_eligibility` |
| LLM rerank returns every candidate | Order kept, no crash | `test_rerank_returning_every_candidate_keeps_its_order` |
| Writer leaks internals or invents phone, price, rating, or license | Rejected → template | `test_guardrail_blocks_leaking_internal_details`, `test_guardrail_rejects_invented_price_rating_or_license`, `test_guardrail_blocks_phone_numbers_not_in_the_dataset` |
| Honest negations ("I can't guarantee") | Not flagged | `test_guardrail_allows_honest_negations_of_forbidden_claims` |
| Empty, emoji, gibberish, mixed language, typos | No crash; empty input isn't a turn | `test_empty_input_is_not_a_turn`, `test_odd_inputs_do_not_crash`, probe `mixed_language`, eval `typo_heavy` |
| Very long message | Trimmed (start + end kept), not rejected | `test_very_long_input_is_trimmed_not_rejected`, `test_long_and_empty_messages_are_handled_not_rejected` |
| Provider record missing phone or coverage | Never a candidate; a lead with it is invalid | `test_provider_without_phone_is_never_a_candidate`, `test_lead_with_phoneless_provider_is_invalid`, `test_provider_with_unknown_coverage_is_never_a_candidate` |

## Known limits

- Up to 3 options are listed, and a lead always goes to **one** provider. There is no shared-lead mode.
- Provider comparisons ("is DG better than EVS?") get "no verified data". The dataset has no quality signals.
- Consent covers name + contact for one provider. Withholding the street address is supported, but there's no
  per-field consent beyond that.
- Free-form questions outside the known topics get "I don't have verified information on that" rather than an
  open-ended answer.
