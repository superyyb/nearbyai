# Eval report — anthropic backend, structured simulator

| Metric | Value |
|---|---|
| cases | 1 |
| outcome_accuracy | 100.0 |
| service_category_accuracy | 100.0 |
| dispatchable_lead_rate | 100.0 |
| useful_resolution_rate | 100.0 |
| median_user_turns_to_lead | 5 |
| mean_user_turns_to_lead | 5 |
| provider_grounding | 100.0 |
| coverage_truthfulness | 100.0 |
| provider_eligibility | 100.0 |
| consent_correctness | 100.0 |
| avg_lead_quality | 92.0 |
| cases_passed | 1 |

## multiple_issues — ready_to_dispatch (5 user turns) — PASS

- **User**: My roof is leaking after the rain and also my AC stopped working
- **Agent** _(ask_location)_: I'm sorry you're dealing with this. I've noted the AC issue so it won't be lost, but let's get the roofing problem handled first. What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95054
- **Agent** _(ask_timing)_: I found First Tier Exterior, which handles roofing and lists Santa Clara in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: today if possible
- **Agent** _(ask_contact)_: Thanks for letting me know. What's your name and the best phone number to reach you? If you'd like, you can also include the street address so they can plan the visit.
- **User**: Avery Park, 408-555-0122
- **Agent** _(ask_consent)_: First Tier Exterior handles roofing and serves your area. Is it okay if I share your name and phone number with them so they can call or text you about this request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Avery Park. Your request is all set to send to First Tier Exterior. This demo only prepares the lead and doesn't contact the provider automatically, so if you'd like to reach them sooner, their number is (669) 249-1684.

```
NEW SERVICE LEAD

Customer: Avery Park
Contact: (408) 555-0122 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 95054; exact address to be confirmed by provider.

Service: Roofing
Problem: Roof is leaking after rain. Customer also reports their AC has stopped working. Customer would like service today if possible.
  Actively leaking: Yes
  Likely source: Exterior / storm water
Also mentioned (not part of this lead): AC stopped working

Timing: Same-day service preferred (availability not confirmed)

Matched provider: First Tier Exterior
  (669) 249-1684 · https://www.firsttierexterior.com
  Coverage: Verified — Santa Clara listed on provider's official site
  Source: https://www.firsttierexterior.com/services/roofing/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```
