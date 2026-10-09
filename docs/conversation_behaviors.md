# Conversation behavior coverage

Real users don't walk the intake funnel in order. They interrupt, ask questions, push back on the
recommendation, change earlier answers, and ask the assistant to do things it can't. This page lists the
behaviors the agent handles, the state transition each one must produce, and where each is tested.

## How a turn is handled

Every user message can carry two kinds of information:

- **facts about the job** (category, location, timing, contact, qualification answers), and
- **intent about the conversation itself** (rejecting a provider, asking a question, withdrawing consent, ...).

Both come out of the **same extraction call**. Deterministic code then applies them in priority order:

1. Safety: regex screen ∪ the extractor's fixed hazard families → redirect (gas, fire, CO), or fixed guidance first
   and then continue
2. Corrections: invalidate stale derived state (category → qualification facts, match, consent; location → match, consent)
3. Provider intent: reject, ask for another, list options, choose by name, accept or decline a provisional offer
4. Questions and impossible requests: answer from the record, then **resume** the pending question
5. The normal funnel: utility-outage check → trade (with a validated LLM clarifying question if needed) → location →
   qualification → match → timing → contact → consent → validated lead

The funnel is the default path, not a script. A turn spent on 3 or 4 does not count as an unanswered ask.

## Test layers

| Layer | What it proves | Cost | Where |
|---|---|---|---|
| Deterministic unit tests | Invariants and single transitions | free | `tests/test_core.py`, `tests/test_robustness.py` |
| Scripted conversation tests | Orchestration given "the extractor understood X" | free | `tests/test_behaviors.py` (uses `ScriptedLLM`) |
| Intent probes | Claude maps varied wording to the right event, and plain answers don't trigger events | ~$0.25 | `data/evaluation/intent_probes.json`, `scripts/run_intent_probes.py` |
| Simulated-user eval | End-to-end conversations with personas | ~$0.05/conversation | `data/evaluation/core_cases.json`, `scripts/run_eval.py` |
| First-turn generalization | 112 frozen openings written by a different model than the agent | ~$1.3 | `data/evaluation/generalization_openings.json`, `scripts/run_generalization.py` |
| Provider-perspective judge | Lead actionability, with paired degraded copies | ~$0.13 | `backend/app/evaluation/provider_judge.py` (`run_eval.py --judge`) |
| Eval-harness tests | The evaluator's own checks and the judge plumbing | free | `tests/test_evaluator.py`, `tests/test_provider_judge.py` |

New cases come from real failures, and each became a regression test:
- **Manual tests:** provider rejection was ignored; "no water in my home" got the trade menu; an unprompted "I don't
  know what's wrong" skipped the utility check.
- **Reading Claude-simulated transcripts:** a negation-blind safety screen; a guessed "water still entering"; a second
  question left unanswered.
- **The frozen generalization set:** missed hazards; consequences mislabeled as separate issues; replies that ignored
  the concrete situation.

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
| "Can I change my address?" (no new value yet) | Hold the request, keep the old value, ask for the new one; the next value overrides | `test_wants_change_holds_the_request_and_asks_for_the_new_value`, `test_new_value_after_wants_change_updates_the_lead`, `test_never_mind_after_wants_change_restores_the_lead`, probes `edit_*` |
| "I gave you the wrong phone number" | Clear the wrong value now (lead not dispatchable), ask for the correct one; consent stands for the same provider | `test_wrong_phone_clears_it_and_makes_the_lead_undispatchable`, `test_correct_phone_after_wrong_rebuilds_lead_without_reasking_consent`, `test_wrong_phone_then_no_number_asks_again_instead_of_giving_up` |
| Wrong ZIP / a different problem | Re-match after the new ZIP; re-qualify for the new trade | `test_wrong_zip_clears_the_match_and_new_zip_rematches`, `test_changing_the_problem_rematches_for_the_new_trade` |
| New street address or same-area ZIP | Provider and consent kept; only a service-area change re-matches | `test_new_street_address_in_the_same_area_keeps_provider_and_consent`, `test_zip_in_the_same_area_keeps_the_match` |
| Invalid phone / email / ZIP in a message with other fields ("yy, 669222192, 1200 Main St") | Valid fields saved; only the invalid one asked for, saying what's wrong; example on the 2nd try, another way forward on the 3rd; never counted as a refusal | `test_nine_digit_number_keeps_name_and_address_and_asks_only_for_the_phone`, `test_repeated_invalid_numbers_escalate_and_never_become_a_refusal`, `test_invalid_attempts_do_not_count_toward_the_contact_ask_limit`, `test_four_digit_zip_is_asked_for_again`, `test_malformed_email_is_asked_for_again`, probe `raw_short_phone` |
| Valid values in any common format (bare 10 digits, +1, ZIP+4) | Normalized and saved; consent still asked | `test_multi_field_message_with_a_valid_bare_number_saves_everything_and_asks_consent`, `test_phone_formats_normalize`, `test_zip_plus4_is_accepted_for_matching`, probe `raw_zip_plus4` |
| Invalid number while editing the phone | The edit stays pending; no "ready" until a valid number | `test_invalid_number_during_a_phone_edit_keeps_the_edit_pending` |
| Self-serve without an explicit refusal | Says what's missing, never "I won't share your details" | `test_giving_up_without_a_refusal_does_not_claim_one`, `test_explicit_refusal_is_the_only_path_to_declined_wording` |
| Unclear request | A clarifying question, never "I can't" (that is only for calls, bookings, guarantees) | `test_unclear_request_after_lead_gets_a_clarifying_question_only`, `test_only_truly_impossible_requests_say_cant`, probe `control_thanks_not_unclear` |

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
| Unclear trade | One clarifying question in the user's terms, proposed by the LLM and validated by code (one question, no provider facts, no known-info asks, not a menu); rule question, then the generic menu as fallbacks | `test_no_water_regression_uses_the_targeted_question`, `test_choice_order_llm_then_rule_then_generic`, `test_validator_rejects_bad_proposals`, `test_ask_category_uses_the_llm_question_too` |
| Writer turns a targeted question back into a menu | Rejected → template | `test_no_water_regression_uses_the_targeted_question` (menu check), generalization generic-fallback metric |
| Several related problems | Source is the trade; damage it caused goes to `observed_impacts` (shown in the lead), not "another issue" | `test_consequence_is_an_observed_impact_not_a_second_issue`, `test_lead_packet_lists_observed_impact`, probes `causal_multi_issue`, `ceiling_drip_consequence` |
| Unrelated problems | Most urgent first; others noted as secondary | `test_unrelated_problem_is_still_noted_as_secondary`, eval `multiple_issues`, probe `unrelated_multi_issue` |
| Active damage with an obvious low-risk step | One fixed tip (toilet supply valve; main shutoff), at most once, verbatim; never for water heaters; no DIY advice | `test_overflowing_toilet_gets_the_fixed_tip_once`, `test_active_pipe_leak_gets_main_shutoff_tip`, `test_no_tip_without_a_clear_low_risk_trigger`, `test_writer_that_alters_the_damage_tip_is_rejected` |
| Ambiguous symptom (ceiling stain, no hot water, warm wall, buzzing) | One disambiguating question | `test_ambiguous_ceiling_asks_disambiguation_first`, `test_new_ambiguity_rules`, eval `ceiling_stain_ambiguous` |
| Unsupported service, then a supported one | `unsupported_category`, then continue | `test_unsupported_category`, `test_unsupported_then_supported_issue_continues` |
| Borderline scope (dishwasher leak vs. fault, garage door) | Leak → plumbing; appliance fault → unsupported | `test_scope_policy_for_borderline_jobs`, probes `scope_*` |
| Out of the pilot area, then a pilot ZIP | `no_match`, then continue | `test_out_of_area_is_no_match`, `test_out_of_area_then_pilot_zip_continues` |

### Utility outages

| Behavior | Expected | Coverage |
|---|---|---|
| Whole home has no water / power | Ask "only your home, or nearby homes too?" before any provider | `test_no_water_asks_home_only_vs_neighbors_first`, `test_scope_is_asked_before_any_provider_and_only_once` |
| Nearby homes affected | `utility_redirect`; no phone numbers invented | `test_neighbors_affected_is_utility_redirect_with_no_invented_numbers`, `test_neighbors_affected_stated_upfront_redirects_immediately` |
| Only this home / unknown after asking | Plumber or electrician; the lead records the answer | `test_only_this_home_continues_to_plumbing_funnel`, `test_unknown_scope_after_asking_continues_and_lead_says_unsure` |
| Unprompted "I don't know what's wrong" | Not treated as an unknown scope; the scope question is still asked | `test_unprompted_unknown_scope_does_not_skip_the_scope_question`, `test_unprompted_unknown_scope_for_water_is_ignored_too` |
| Later "actually it's only my house" | Reopens into the contractor funnel | `test_utility_redirect_reopens_when_user_corrects_scope` |
| Partial outage (half the house) | Not a utility issue | `test_partial_outage_is_not_a_utility_issue_in_rules_backend` |

### Safety

| Behavior | Expected | Coverage |
|---|---|---|
| Gas / fire / CO | `safety_redirect` (911 / PG&E) | `test_gas_leak_is_redirect`, `test_gas_is_safety_redirect`, eval `safety_gas_leak` |
| Sparking, water near electrical, sewage, sagging ceiling, tree on house, HVAC burning smell | Specific guidance first, then continue as urgent | `test_sparking_is_urgent_not_redirect`, `test_new_urgent_hazards_get_specific_guidance`, `test_hazard_interrupts_funnel_then_continues` |
| HVAC burning smell | Thermostat guidance, not breaker guidance | `test_hvac_burning_smell_does_not_get_breaker_guidance` |
| Denied hazard ("no sparks", "the outlet isn't warm") | No guidance, not marked urgent | `test_safety_screen_respects_negation`, `test_denying_hazard_does_not_mark_lead_urgent`, `test_no_false_alarm_on_similar_wording` |
| Hazard phrased in a way no regex covers ("the fuse box is sizzling") | The extractor's fixed hazard family adds the fixed guidance | `test_llm_hazard_flows_through_the_turn_with_fixed_copy`, held-out probes `hazard_*` (regex 0/6, hybrid 6/6) |
| LLM flags gas / CO / fire | Blocking redirect; reopens if the user clarifies | `test_llm_gas_family_is_a_blocking_redirect`, `test_llm_gas_flag_redirects_but_can_reopen` |
| Regex and LLM flag the same family | One guidance, the regex's more specific copy | `test_llm_family_does_not_duplicate_a_regex_family` |
| Previously missed hazards (cords, light fixture, warm outlet, buzzing panel, unexplained burning smell) | Guidance | `test_regex_first_line_now_catches_previously_missed_hazards` (regression coverage) |

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

### Evaluation harness

| Behavior | Expected | Coverage |
|---|---|---|
| Honest combined answer ("no verified reviews or pricing") | Passes; an invented price or a missing topic fails | `test_combined_honest_answer_passes`, `test_invented_price_fails`, `test_answering_only_one_topic_fails` |
| Provider judge input | Provider view only; no consent, coverage, or provenance | `test_judge_view_hides_hard_rules_and_internal_metadata` |
| Judge controls | Paired, same format, one dimension degraded; blind and shuffled; Opus pinned | `test_degraded_copies_keep_the_format_and_change_one_dimension`, `test_items_are_paired_shuffled_and_anonymous`, `test_judge_prompt_is_blind_to_labels_and_uses_the_fixed_model` |

## Known limits

- Up to 3 options are listed, and a lead always goes to **one** provider. There is no shared-lead mode.
- Provider comparisons ("is DG better than EVS?") get "no verified data". The dataset has no quality signals.
- Consent covers name + contact for one provider. Withholding the street address is supported, but there's no
  per-field consent beyond that.
- Free-form questions outside the known topics get "I don't have verified information on that" rather than an
  open-ended answer.
- The regex safety layer still raises false alarms on resolved or hypothetical statements ("the buzzing was fixed").
- The menu guardrail misfires on about 1% of multi-issue replies; the safe template is used instead.
