# Brief: v6 gesture data + retrain (popclick bindings)

You are one worker. Do everything below in order, inside /home/khoa/VOX/finetune. Report at the end with the
exact numbers read from files (not from memory).

## Why
The Android app changed its default gesture bindings (commit "popclick"): a "pop" is folded into "click" at intake
(android/app/src/main/java/ai/vox/companion/SoundFold.kt), so the model never sees "pop" any more. The finetune
schema/generator still carry the old bindings, and the served model (runs/sweep-v5-e5-small-e3.pt) answers a lone
"click" with "do nothing" instead of "tap". Source of truth = android/app/src/main/java/ai/vox/companion/Vocab.kt
(DEFAULT_BINDINGS, FREED_SEQUENCES, APP_ONLY_ACTIONS, APP_ONLY_BINDINGS, DISCRETE, ACTIONS) and
ui/lib/src/backend.dart VoxBindings.defaults. Read Vocab.kt first.

New defaults (Vocab.kt): rise=swipe_up, fall=swipe_down, arch=swipe_right, dip=swipe_left, click=tap, hiss=back,
flat=long_press, click click click=listen_for_phrase, click click=home, hiss click=back.
App-only (never a model option, unchanged): click hiss = forward. FREED_SEQUENCES in Kotlin = [["click","pop"]].

## HARD RULES
- No git commands at all. No sudo, no system installs, no pip/uv install (never touch torch). No adb, no phone,
  no emulator. Never open any zflip/ directory. Never print or read ~/.config/vox/ollama_key.
  Never use pgrep -f / pkill -f (exact PIDs only). Never touch ~/jevlike or ~/torch-rocm.
- Write only under /home/khoa/VOX/finetune (vox/, tests/, data/v6/, runs/sweep-v6-*, preds/sweep-*,
  sweeps/logs, sweeps/eval, sweeps/scratch, sweeps/runs.jsonl via sweeps/record.py). android/ and ui/ are READ ONLY.
- NEVER modify or delete anything in data/v5 (or any other data/ version) or any existing runs/*.pt.
- Keep >= 30 GB free on / (df -h /). Run one training job at a time.
- Every python command runs inside the pinned env:
  cd /home/khoa/VOX/finetune && nix shell nixpkgs#python313 nixpkgs#uv -c bash -c 'source ./env.sh; source .venv/bin/activate; <command>'
  (that torch sees the ROCm GPU: train.py prints "device": "cuda"; if it prints cpu, stop and report.)

## Step 1: schema + generator (small, exact edits)
vox/schema.py:
- DEFAULT_BINDINGS -> exactly Vocab.kt's table, same order:
  ("rise",):"swipe_up", ("fall",):"swipe_down", ("arch",):"swipe_right", ("dip",):"swipe_left", ("click",):"tap",
  ("hiss",):"back", ("flat",):"long_press", ("click","click","click"):"listen_for_phrase", ("click","click"):"home",
  ("hiss","click"):"back". Update the comment (2026-09-28: a pop counts as a click; "pop"/"pop pop" removed).
- FREED_SEQUENCES = [("click", "pop")]  (mirror Kotlin; note it can no longer occur after the fold).
- Keep DISCRETE["pop"] (Kotlin's SoundFold uses that exact text to rewrite pop lines; parity), but add a comment that
  the generator never emits it. APP_ONLY_* unchanged.
vox/generate.py:
- DEFAULTS_TEXT = "defaults: rise=swipe up, fall=swipe down, arch=swipe right, dip=swipe left, click=tap, hiss=go back, long flat hum=long-press, click click click=listen for a phrase, click click=go home, hiss click=go back"
- POLICY: "a pop clicks" -> "a click clicks".
- Remove the "pop" entry from GESTURE_WORDS (and from wordings.py GESTURE_WORDS_TRAIN if it has one; keep
  check_disjoint happy).
- random_seq(): pool = list(CONTOURS) + [g for g in DISCRETE if g != "pop"].
- "unbound" kind: only draw from FREED_SEQUENCES entries that contain no "pop" (with the current table that means the
  30% FREED branch is skipped: use a plain random_seq loop that rejects seqs in DEFAULT_BINDINGS/APP_ONLY_BINDINGS).
- make_cursor(): the "pop" branch becomes "click": g choice list ["click", "click_click", "hiss"] + contours,
  sc.sequence=("click",), heard=deliberate_sound("click", loud), answer="click".
- grep -n '"pop"\|pop' vox/*.py tests/*.py and fix any other place that would emit a pop SOUND into data (the
  DISCRETE entry and comments may stay). Do not touch targets*.py / real_targets*.py / whatgen.py logic beyond that.
Then write tests/test_schema_parity.py (unittest, like tests/test_whatgen.py; no model imports): parse
android/app/src/main/java/ai/vox/companion/Vocab.kt with regexes and assert schema.DEFAULT_BINDINGS,
FREED_SEQUENCES, APP_ONLY_ACTIONS, APP_ONLY_BINDINGS, DISCRETE and ACTIONS equal the Kotlin tables (keys, values,
order). Add a SEPARATE test asserting generate.DEFAULTS_TEXT == Vocab.kt's DEFAULTS_TEXT: this one is EXPECTED
TO FAIL right now (Kotlin still has the old line; the user will update it), report its failure, do not "fix" it by
changing DEFAULTS_TEXT back and do not edit Vocab.kt. Add a third test: generate 300 rows from a fresh
Generator with each kind and assert no row's context contains "lip pop" or "sequence: ... pop".
Run: python -m unittest tests.test_schema_parity tests.test_whatgen -v (inside the pinned env). Fix real failures.

## Step 2: data/v6
python -m vox.generate --output data/v6 --bank wordings_llm/bank.json   (same seed/sizes as v5: defaults
20260926 / 40000 / 2000 / 2000). Then: wc -l data/v6/*.jsonl; grep -c '"click"' etc.; confirm
grep -c "lip pop" data/v6/train.jsonl is 0 and that "click=tap" appears in every row's context. Print the kind
histogram of train.jsonl for v5 and v6 side by side. Add a v6 row to data/README.md's table
("v6 | v5 + popclick bindings: click=tap, click click click=listen, pop never emitted | new").

## Step 3: train + evaluate (write sweeps/scratch/v6_queue.sh modelled on sweeps/sweep.sh's train_one/predict_all/
record, DATA=data/v6, WITHOUT the pgrep wait; run it with nohup in the background and poll its log every 60 s)
a) train: python students/jevlike/train.py data/v6/train.jsonl --validation data/v6/validation.jsonl --output
   runs/sweep-v6-e5-small-e3.pt   (name v6-e5-small-e3; same settings as the v5 row: e5-small-v2, 3 epochs).
   Log to sweeps/logs/v6-e5-small-e3.train.log. Record wall time.
b) predict + evaluate runs/sweep-v6-e5-small-e3.pt on data/v6 test_iid, test_unseen_phrasing, test_unseen_apps
   (preds/sweep-v6-e5-small-e3.<split>.jsonl, sweeps/eval/v6-e5-small-e3.<split>.json) and record the ledger row
   with sweeps/record.py --data-version data/v6 exactly as sweep.sh does.
c) predict + evaluate the OLD checkpoint runs/sweep-v5-e5-small-e3.pt on the same three data/v6 tests
   (name v5-e5-small-e3-on-v6; record a ledger row with --data-version data/v6 --note "old bindings ckpt scored on v6").
d) predict + evaluate the NEW checkpoint on data/v5's three tests (name v6-e5-small-e3-on-v5, --data-version data/v5,
   --note "new bindings ckpt scored on v5 (old bindings; expected default-kind drop)").

## Step 4: 9-scene check (sweeps/scratch/scene_check_v6.py)
Load a checkpoint the way servers/systemone.py loads a jevlike checkpoint (read that file and students/jevlike/train.py;
CPU is fine) and score these 9 gesture-mode scenes, built with vox.generate.Scene(...).text() so the context is
byte-identical to what the app sends (Scene.text() must include the NEW DEFAULTS_TEXT), options = every entry of
schema.ACTIONS in table order (that is what the phone sends), app = "com.android.chrome" (Chrome), screen = None,
rules none, recent none:
  rise  : ["hum that rises from low to high; pitch change large (over 4 semitones); duration medium (400-1000 ms); tone clear tone; loudness normal; sounds like hum"], seq ("rise",)  -> swipe_up
  fall  : same with "falls from high to low", seq ("fall",) -> swipe_down
  dip   : "falls then rises", ("dip",) -> swipe_left
  arch  : "rises then falls", ("arch",) -> swipe_right
  click : ["a tongue click; instant sound; loudness normal; sounds like mouth sound"], ("click",) -> tap
  flat  : ["hum that stays level; pitch change small (under 2 semitones); duration long (over 1 s); tone clear tone; loudness normal; sounds like hum"], ("flat",) -> long_press
  talking: the rise line but "sounds like talking", ("rise",) -> none
  click rise: [click line, rise line], ("click","rise") -> none
  hiss  : ["a hiss; duration short (150-400 ms); loudness normal; sounds like mouth sound"], ("hiss",) -> back
Print a table (scene, expected, v5 ckpt answer + prob, v6 ckpt answer + prob) for BOTH checkpoints and save it to
sweeps/scratch/scene_check_v6.md.

## Report (last message; numbers copied from the files)
1. Diff summary of vox/schema.py, vox/generate.py, vox/wordings.py, tests/test_schema_parity.py, data/README.md.
2. unittest results (which passed; the DEFAULTS_TEXT-vs-Kotlin test failing is expected).
3. data/v6 line counts vs v5; kind histograms; "lip pop" count in v6 train.
4. Train wall time and the per-epoch val lines from the train log.
5. Table: accuracy / nll / ece / false_trigger_rate / by_kind for v6 ckpt on v6 tests, v5 ckpt on v6 tests, v6 ckpt
   on v5 tests, and the v5 ckpt on v5 tests (from the existing sweeps/eval/v5-e5-small-e3.*.json).
6. The 9-scene table for both checkpoints.
7. Any file you changed, listed with absolute paths. Do NOT edit android/suite/run.sh.
