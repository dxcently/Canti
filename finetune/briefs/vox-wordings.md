# Brief: vox-wordings (DeepSeek V4.1 executor)

You are generating TRAINING wordings for VOX, a system that maps vocal gestures (hums, pops, clicks) to phone actions.
A small student model reads user-written rules like "In TikTok, a rising hum means like it" and must pick the right
action option. It currently fails when a rule words the action or gesture differently from what it saw in training.
Your job: produce large, varied, natural wording banks so it learns meaning, not strings.

## Scope and permissions
- Work ONLY inside /home/khoa/VOX/finetune/wordings_llm/. Create files only there. Do not modify anything else.
- READ ONLY these for context: /home/khoa/VOX/finetune/vox/schema.py and /home/khoa/VOX/finetune/vox/wordings.py.
- Do NOT open /home/khoa/VOX/finetune/vox/generate.py or anything under data/ or preds/. They contain held-out
  test wordings; seeing them would contaminate the evaluation.
- No network access beyond your own model. No git operations.

## Deliverable: /home/khoa/VOX/finetune/wordings_llm/bank.json
{
  "actions":  {"<action_key>": ["wording", ...], ...},   // every key in schema.ACTIONS except "none"; 30-40 each
  "gestures": {"<gesture_key>": ["wording", ...], ...},  // rise, fall, arch, dip, flat, pop, click, hiss; 20-30 each
  "app_rule_templates":    ["... {app} ... {g} ... {a} ...", ...],   // 40+, must contain {app} {g} {a}
  "global_rule_templates": ["... {g} ... {a} ...", ...],             // 25+, must contain {g} {a}, no {app}
  "disable_templates":     ["... {app} ... {g} ...", ...],           // 15+, must contain {app} {g}
  "phrase_templates":      ["... '{p}' ... {a} ...", ...]            // 15+, must contain {p} {a}
}
Requirements:
- Action wordings are verb phrases a user would write after "should" or "means", e.g. "go back a screen",
  "heart the post". Cover casual, terse, verbose, British/American spellings, slangy ("nuke the volume"),
  and descriptive ("the gesture you'd do to see the next video"). Keep the meaning unambiguous: a wording must
  not plausibly mean a different action in the list (e.g. do not use "go back" for previous_item).
- Gesture wordings are noun phrases: "a hum that climbs in pitch", "a quick pop of the lips".
  Contours: rise=low to high, fall=high to low, arch=up then down, dip=down then up, flat=level and held.
- Templates: varied sentence shapes (imperative, conditional, arrow/colon notation, "whenever", "if ... then").
- No duplicates. Nothing copied from wordings.py (those already exist); produce new ones.
- Also write /home/khoa/VOX/finetune/wordings_llm/validate.py that loads bank.json and checks: every schema
  action/gesture key present, minimum counts, placeholders exactly as required, no duplicates, no overlap with
  wordings.py. Run it and fix until it passes.
- Then write /home/khoa/VOX/finetune/wordings_llm/AMBIGUITY.md listing any wordings you were unsure map to
  one action only (so a human can review them).

Run python with: nix shell nixpkgs#python313 -c python3 <script>
Finish with a short summary: counts per section, validate.py output, and the ambiguity list size.
