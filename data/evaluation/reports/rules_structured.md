# Eval report — rules backend, structured simulator

| Metric | Value |
|---|---|
| cases | 18 |
| outcome_accuracy | 94.4 |
| service_category_accuracy | 93.8 |
| dispatchable_lead_rate | 92.9 |
| useful_resolution_rate | 93.3 |
| median_user_turns_to_lead | 6 |
| mean_user_turns_to_lead | 5.77 |
| provider_grounding | 100.0 |
| coverage_truthfulness | 100.0 |
| provider_eligibility | 100.0 |
| consent_correctness | 100.0 |
| avg_lead_quality | 91.8 |
| cases_passed | 17 |

## water_damage_basement_storm — ready_to_dispatch (6 user turns) — PASS

- **User**: Water started coming into my basement last night after the storm. I don't know who to call.
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 1450 Lafayette St, Santa Clara 95050
- **Agent** _(ask_qualification)_: Is water still actively coming in right now?
- **User**: no
- **Agent** _(ask_timing)_: I found 911 Restoration of San Jose, which handles water damage restoration and lists Santa Clara in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: today if possible
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you?
- **User**: Test User, 408-555-0142
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with 911 Restoration of San Jose so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Test User. Your service request is ready to send to 911 Restoration of San Jose. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (408) 449-4904.

```
NEW SERVICE LEAD

Customer: Test User
Contact: (408) 555-0142 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: 1450 Lafayette St, Santa Clara, CA 95050

Service: Water Damage Restoration
Problem: Water started coming into my basement last night after the storm. I don't know who to call.
  Water still entering: No
  Likely source: Exterior / storm water

Timing: Same-day service preferred (availability not confirmed)

Matched provider: 911 Restoration of San Jose
  (408) 449-4904 · https://www.911restorationsanjose.com
  Coverage: Verified — Santa Clara listed on provider's official site
  Source: https://www.911restorationsanjose.com/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## plumbing_burst_pipe — ready_to_dispatch (5 user turns) — PASS

- **User**: A pipe under my kitchen sink burst and it's spraying everywhere
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95051
- **Agent** _(ask_timing)_: I found EJ Home Services, which handles plumbing and lists Santa Clara in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: right now, asap
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Jordan Kim, 408-555-0101
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with EJ Home Services so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Jordan Kim. Your service request is ready to send to EJ Home Services. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (650) 434-4432.

```
NEW SERVICE LEAD

Customer: Jordan Kim
Contact: (408) 555-0101 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 95051; exact address to be confirmed by provider.

Service: Plumbing
Problem: A pipe under my kitchen sink burst and it's spraying everywhere

Timing: As soon as possible (customer reports urgent need) (availability not confirmed)

Matched provider: EJ Home Services
  (650) 434-4432 · https://www.ejplumbing.com
  Coverage: Verified — Santa Clara listed on provider's official site
  Source: https://www.ejplumbing.com/areas-we-serve/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## plumbing_toilet_overflow — ready_to_dispatch (5 user turns) — PASS

- **User**: My toilet keeps overflowing every time we flush
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 820 E El Camino Real, Sunnyvale, CA 94087
- **Agent** _(ask_timing)_: I found EJ Home Services, which handles plumbing and lists Sunnyvale in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: tomorrow works
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Alex Rivera, 650-555-0123
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with EJ Home Services so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Alex Rivera. Your service request is ready to send to EJ Home Services. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (650) 434-4432.

```
NEW SERVICE LEAD

Customer: Alex Rivera
Contact: (650) 555-0123 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 94087; exact address to be confirmed by provider.

Service: Plumbing
Problem: My toilet keeps overflowing every time we flush

Timing: Within the next few days (availability not confirmed)

Matched provider: EJ Home Services
  (650) 434-4432 · https://www.ejplumbing.com
  Coverage: Verified — Sunnyvale listed on provider's official site
  Source: https://www.ejplumbing.com/areas-we-serve/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## hvac_ac_warm_air — ready_to_dispatch (5 user turns) — PASS

- **User**: My AC is running but only blowing warm air
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95134
- **Agent** _(ask_timing)_: I found DG Heating & Air Conditioning, which handles hvac (heating & cooling) and lists North San Jose in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: this week is fine
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Morgan Lee, 408-555-0177
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with DG Heating & Air Conditioning so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Morgan Lee. Your service request is ready to send to DG Heating & Air Conditioning. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (408) 201-9411.

```
NEW SERVICE LEAD

Customer: Morgan Lee
Contact: (408) 555-0177 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 95134; exact address to be confirmed by provider.

Service: HVAC (Heating & Cooling)
Problem: My AC is running but only blowing warm air

Timing: Within the next few days (availability not confirmed)

Matched provider: DG Heating & Air Conditioning
  (408) 201-9411 · https://www.dgheatingandair.com
  Coverage: Verified — North San Jose listed on provider's official site
  Source: https://www.dgheatingandair.com/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## hvac_furnace_dead — ready_to_dispatch (5 user turns) — PASS

- **User**: The furnace won't turn on at all and the house is freezing
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 94086
- **Agent** _(ask_timing)_: I found Supreme Comfort HVAC, Inc., which handles hvac (heating & cooling) and lists Sunnyvale in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: today if possible
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Chris Patel, 408-555-0190
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with Supreme Comfort HVAC, Inc. so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Chris Patel. Your service request is ready to send to Supreme Comfort HVAC, Inc.. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (408) 222-6463.

```
NEW SERVICE LEAD

Customer: Chris Patel
Contact: (408) 555-0190 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 94086; exact address to be confirmed by provider.

Service: HVAC (Heating & Cooling)
Problem: The furnace won't turn on at all and the house is freezing

Timing: Same-day service preferred (availability not confirmed)

Matched provider: Supreme Comfort HVAC, Inc.
  (408) 222-6463 · https://www.supremecomfortca.com
  Coverage: Verified — Sunnyvale listed on provider's official site
  Source: https://www.supremecomfortca.com/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## electrical_sparking_outlet — ready_to_dispatch (4 user turns) — PASS

- **User**: One of my outlets sparked when I plugged in the vacuum
- **Agent** _(ask_location)_: For safety: if it's safe to reach, switch off the breaker for that circuit and don't touch the outlet or panel. If you see smoke or flames, leave and call 911. What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95054
- **Agent** _(ask_contact)_: I found WCI Electric, which handles electrical and lists Santa Clara in its service area. What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Taylor Nguyen, 408-555-0133
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with WCI Electric so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Taylor Nguyen. Your service request is ready to send to WCI Electric. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (408) 242-2069.

```
NEW SERVICE LEAD

Customer: Taylor Nguyen
Contact: (408) 555-0133 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 95054; exact address to be confirmed by provider.

Service: Electrical
Problem: One of my outlets sparked when I plugged in the vacuum
  Sparks / burning smell / hot fixtures: Yes — safety guidance given
Safety flags: electrical_sparking

Timing: As soon as possible (customer reports urgent need) (availability not confirmed)

Matched provider: WCI Electric
  (408) 242-2069 · https://www.wcielectric.com
  Coverage: Verified — Santa Clara listed on provider's official site
  Source: https://www.wcielectric.com/about-us-electricians/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## roofing_leak_after_rain — ready_to_dispatch (6 user turns) — PASS

- **User**: Our roof started leaking into the upstairs bedroom during the rain
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95131
- **Agent** _(ask_qualification)_: Is it actively leaking right now?
- **User**: yes
- **Agent** _(ask_timing)_: I found First Tier Exterior, which handles roofing and lists North San Jose in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: asap
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Dana Brooks, 669-555-0144
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with First Tier Exterior so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Dana Brooks. Your service request is ready to send to First Tier Exterior. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (669) 249-1684.

```
NEW SERVICE LEAD

Customer: Dana Brooks
Contact: (669) 555-0144 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 95131; exact address to be confirmed by provider.

Service: Roofing
Problem: Our roof started leaking into the upstairs bedroom during the rain
  Actively leaking: Yes

Timing: As soon as possible (customer reports urgent need) (availability not confirmed)

Matched provider: First Tier Exterior
  (669) 249-1684 · https://www.firsttierexterior.com
  Coverage: Verified — North San Jose listed on provider's official site
  Source: https://www.firsttierexterior.com/services/roofing/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## ceiling_stain_ambiguous — ready_to_dispatch (7 user turns) — PASS

- **User**: There's a brown stain on my ceiling that keeps getting bigger
- **Agent** _(clarify_category)_: Does it mainly show up when it rains, or is there a bathroom or plumbing directly above that spot?
- **User**: It seems to get worse when it rains
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 94085
- **Agent** _(ask_qualification)_: Is it actively leaking right now?
- **User**: no
- **Agent** _(ask_timing)_: I found Conrad Roofing Service, which handles roofing and lists Sunnyvale in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: no rush
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Riley Chen, 408-555-0155
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with Conrad Roofing Service so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Riley Chen. Your service request is ready to send to Conrad Roofing Service. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (408) 294-7615.

```
NEW SERVICE LEAD

Customer: Riley Chen
Contact: (408) 555-0155 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 94085; exact address to be confirmed by provider.

Service: Roofing
Problem: There's a brown stain on my ceiling that keeps getting bigger
  Actively leaking: No

Timing: Flexible timing (availability not confirmed)

Matched provider: Conrad Roofing Service
  (408) 294-7615 · https://conradroofingservice.com
  Coverage: Verified — Sunnyvale listed on provider's official site
  Source: https://conradroofingservice.com/contact/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## vague_request — ready_to_dispatch (7 user turns) — PASS

- **User**: Something is wrong in my house and I need help
- **Agent** _(ask_category)_: I can help with that. Can you tell me a bit about what's going on — for example a leak, a heating or cooling problem, an electrical issue, or something with the roof?
- **User**: The lights in the kitchen keep flickering and the breaker trips
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95050
- **Agent** _(ask_qualification)_: Are you seeing any sparks, a burning smell, or outlets or switches that feel hot?
- **User**: no
- **Agent** _(ask_timing)_: I found California Power & Light, which handles electrical and lists Santa Clara in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: this week
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Sam Ortiz, 408-555-0166
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with California Power & Light so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Sam Ortiz. Your service request is ready to send to California Power & Light. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (408) 406-5832.

```
NEW SERVICE LEAD

Customer: Sam Ortiz
Contact: (408) 555-0166 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: homeowner

Property: Pending — customer provided ZIP 95050; exact address to be confirmed by provider.

Service: Electrical
Problem: The lights in the kitchen keep flickering and the breaker trips
  Sparks / burning smell / hot fixtures: No

Timing: Within the next few days (availability not confirmed)

Matched provider: California Power & Light
  (408) 406-5832 · https://www.cplelectric.com
  Coverage: Verified — Santa Clara listed on provider's official site
  Source: https://www.cplelectric.com/about-us/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## unsupported_pest_control — unsupported_category (1 user turns) — PASS

- **User**: We have termites in the garage, can you send someone?
- **Agent** _(unsupported_category)_: Sorry — this assistant currently covers plumbing, water damage, roofing, heating/cooling, and electrical only, so I can't match a provider for termites. If you also have one of those issues, I'm happy to help with it.

## user_changes_zip — ready_to_dispatch (6 user turns) — PASS

- **User**: My water heater is leaking all over the garage floor
- **Agent** _(ask_location)_: I'll note the other issue too, but let's get the plumbing problem handled first. What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95050
- **Agent** _(ask_timing)_: I found EJ Home Services, which handles plumbing and lists Santa Clara in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: Sorry, actually the ZIP is 95134, not 95050
- **Agent** _(ask_timing)_: I found EJ Home Services, which handles plumbing and lists North San Jose in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: today if possible
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Jamie Fox, 408-555-0188
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with EJ Home Services so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Jamie Fox. Your service request is ready to send to EJ Home Services. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (650) 434-4432.

```
NEW SERVICE LEAD

Customer: Jamie Fox
Contact: (408) 555-0188 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 95134; exact address to be confirmed by provider.

Service: Plumbing
Problem: My water heater is leaking all over the garage floor
Also mentioned (not part of this lead): possible heating/cooling issue also mentioned

Timing: Same-day service preferred (availability not confirmed)

Matched provider: EJ Home Services
  (650) 434-4432 · https://www.ejplumbing.com
  Coverage: Verified — North San Jose listed on provider's official site
  Source: https://www.ejplumbing.com/areas-we-serve/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## user_changes_category — ready_to_dispatch (7 user turns) — PASS

- **User**: I think a pipe is leaking, there's water dripping in the hallway
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 94086
- **Agent** _(ask_timing)_: I found EJ Home Services, which handles plumbing and lists Sunnyvale in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: Actually I just checked the attic, it's the roof leaking, not a pipe
- **Agent** _(ask_qualification)_: Is it actively leaking right now?
- **User**: yes
- **Agent** _(ask_timing)_: I found First Tier Exterior, which handles roofing and lists Sunnyvale in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: asap
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Casey Wu, 408-555-0199
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with First Tier Exterior so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Casey Wu. Your service request is ready to send to First Tier Exterior. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (669) 249-1684.

```
NEW SERVICE LEAD

Customer: Casey Wu
Contact: (408) 555-0199 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 94086; exact address to be confirmed by provider.

Service: Roofing
Problem: Actually I just checked the attic, it's the roof leaking, not a pipe
  Actively leaking: Yes

Timing: As soon as possible (customer reports urgent need) (availability not confirmed)

Matched provider: First Tier Exterior
  (669) 249-1684 · https://www.firsttierexterior.com
  Coverage: Verified — Sunnyvale listed on provider's official site
  Source: https://www.firsttierexterior.com/services/roofing/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## refuses_contact_sharing — self_serve (5 user turns) — PASS

- **User**: The AC in my condo stopped working
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95051
- **Agent** _(ask_timing)_: I found DG Heating & Air Conditioning, which handles hvac (heating & cooling) and lists Santa Clara in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: whenever
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Pat Doe, 408-555-0111
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with DG Heating & Air Conditioning so they can call or text you about this service request?
- **User**: no, I'd rather call them myself
- **Agent** _(self_serve)_: No problem — I won't share your details. You can contact DG Heating & Air Conditioning directly at (408) 201-9411 (https://www.dgheatingandair.com).

## safety_gas_leak — safety_redirect (1 user turns) — PASS

- **User**: I smell gas in the kitchen, what should I do?
- **Agent** _(safety_redirect)_: If you smell gas, please leave the home now, avoid using light switches, flames, or your phone indoors, and once you're outside call 911 and PG&E's gas emergency line at 1-800-743-5000. Once everyone is safe and the emergency is handled, come back and I can help you find a pro for repairs.

## out_of_pilot_area — no_match (2 user turns) — PASS

- **User**: Our AC is blowing warm air
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 94301
- **Agent** _(out_of_area)_: Thanks. Right now I only have verified providers in Santa Clara, Sunnyvale, and North San Jose (95131, 95134), so I can't confidently match a provider for 94301. If the property is in one of those areas, send me the ZIP and I'll keep going.

## multiple_issues — ready_to_dispatch (6 user turns) — PASS

- **User**: My roof is leaking after the rain and also my AC stopped working
- **Agent** _(ask_location)_: I'll note the other issue too, but let's get the roofing problem handled first. What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 95054
- **Agent** _(ask_qualification)_: Is it actively leaking right now?
- **User**: yes
- **Agent** _(ask_timing)_: I found First Tier Exterior, which handles roofing and lists Santa Clara in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: today if possible
- **Agent** _(ask_contact)_: What's your name and the best phone number to reach you? If you'd like, include the street address too so they can plan the visit.
- **User**: Avery Park, 408-555-0122
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with First Tier Exterior so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Avery Park. Your service request is ready to send to First Tier Exterior. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (669) 249-1684.

```
NEW SERVICE LEAD

Customer: Avery Park
Contact: (408) 555-0122 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 95054; exact address to be confirmed by provider.

Service: Roofing
Problem: My roof is leaking after the rain and also my AC stopped working
  Water still entering: No
  Actively leaking: Yes
Also mentioned (not part of this lead): possible heating/cooling issue also mentioned

Timing: Same-day service preferred (availability not confirmed)

Matched provider: First Tier Exterior
  (669) 249-1684 · https://www.firsttierexterior.com
  Coverage: Verified — Santa Clara listed on provider's official site
  Source: https://www.firsttierexterior.com/services/roofing/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```

## typo_heavy — unsupported_category (4 user turns) — FAIL: outcome unsupported_category != expected ready_to_dispatch; category None != expected water_damage_restoration

- **User**: wter coming in my basment aftr the big strom last nite
- **Agent** _(ask_category)_: I can help with that. Can you tell me a bit about what's going on — for example a leak, a heating or cooling problem, an electrical issue, or something with the roof?
- **User**: I'm not sure
- **Agent** _(ask_category)_: I can help with that. Can you tell me a bit about what's going on — for example a leak, a heating or cooling problem, an electrical issue, or something with the roof?
- **User**: I'm not sure
- **Agent** _(ask_category)_: I can help with that. Can you tell me a bit about what's going on — for example a leak, a heating or cooling problem, an electrical issue, or something with the roof?
- **User**: I'm not sure
- **Agent** _(unsupported_category)_: Sorry — this assistant currently covers plumbing, water damage, roofing, heating/cooling, and electrical only, so I can't match a provider for this request. If you also have one of those issues, I'm happy to help with it.

## unknown_qualification_fact — ready_to_dispatch (6 user turns) — PASS

- **User**: My neighbor says water is pooling in my basement after the storm
- **Agent** _(ask_location)_: What's the property address? Just the ZIP code is fine if that's easier.
- **User**: 94089
- **Agent** _(ask_qualification)_: Is water still actively coming in right now?
- **User**: I'm not sure
- **Agent** _(ask_timing)_: I found 911 Restoration of San Jose, which handles water damage restoration and lists Sunnyvale in its service area. Would you prefer help today if someone is available, or is later this week okay?
- **User**: today if possible
- **Agent** _(ask_contact)_: What's the best phone number for the provider to reach you?
- **User**: Robin Hale, 408-555-0109
- **Agent** _(ask_consent)_: Is it okay to share your name and phone number with 911 Restoration of San Jose so they can call or text you about this service request?
- **User**: yes
- **Agent** _(lead_ready)_: Thanks, Not Sure. Your service request is ready to send to 911 Restoration of San Jose. This demo prepares the lead but does not contact the provider automatically. If you want to reach them sooner, their number is (408) 449-4904.

```
NEW SERVICE LEAD

Customer: Not Sure
Contact: (408) 555-0109 (phone)
Contact permission: Yes — explicit consent to share with this provider
Relationship: Not stated

Property: Pending — customer provided ZIP 94089; exact address to be confirmed by provider.

Service: Water Damage Restoration
Problem: My neighbor says water is pooling in my basement after the storm
  Likely source: Exterior / storm water

Timing: Same-day service preferred (availability not confirmed)

Matched provider: 911 Restoration of San Jose
  (408) 449-4904 · https://www.911restorationsanjose.com
  Coverage: Verified — Sunnyvale listed on provider's official site
  Source: https://www.911restorationsanjose.com/ (verified 2026-10-07)

Lead prepared for dispatch. No provider has been contacted automatically.
```
