# Final evaluation results

Frozen evidence behind the numbers in the top-level README. The product was evaluated at commit `ea4d1e2`. Each
suite was run once. `../reports/` holds scratch output that is overwritten by every run and is not committed.

| File | What it is |
|---|---|
| `final_scenarios_claude.json` / `.md` | 20 scenarios, Claude-simulated users, with the provider-perspective judge (transcripts, leads, judge items) |
| `final_scenarios_claude_rescored.json` | One evaluator assertion corrected and re-applied to the saved transcripts; no model calls (19/20 → 20/20) |
| `generalization_claude_before_refactor.json` | Frozen 112 openings, before contextual clarification and utility checks |
| `generalization_claude_after_refactor.json` | Same set, right after that refactor |
| `generalization_claude_final.json` | Same set, final code |
| `generalization_rules_baseline.json` | Same set, offline rule-based backend |
| `intent_probes_claude_final.json` | 54 intent probes, final code |
| `intent_probes_rules_baseline.json` | Earlier 44-probe version on the rule-based backend |
| `scenarios_rules_baseline.json` / `.md` | 20 scenarios, offline rule-based backend, structured simulator |
