# VOX

A hands-free phone controller driven by non-speech vocal sounds: hums that rise, fall, arch or dip, lip pops, tongue clicks, hisses and whistles, plus your own custom sounds.

```
mic ─► Pico 2 W ─(BLE)─► Android app ─► decision model ─► AccessibilityService
       sound → text line      sequencing, screen       Jev /v1/systemone       swipe, tap, back…
       + fingerprint          context, personalization or the local VOX student
```

1. **Hear.** A Pico 2 W with an I2S mic turns each sound into one categorical text line, e.g. `hum that rises from low to high; pitch change large; duration short; …`, plus a small fingerprint.
2. **Understand.** The Android companion app groups sounds into sequences using the device timestamps. It matches the fingerprint against your enrolled examples, adds the screen context from the accessibility tree, and asks a decision model which action applies.
3. **Decide.** The model is a Jev-style typed-choice model: TypeSafe's Jev API, or our fine-tuned VOX student served locally with the same `/v1/systemone` wire format.
4. **Act.** The app performs the action through Android's AccessibilityService and confirms that it worked.

## Folders

| Folder | What it is | Start here |
|---|---|---|
| [`android/`](android/README.md) | The Android companion app (Kotlin, no AndroidX), the emulator test suite on open-source stand-in apps, and the nix flake for the SDK/emulator | `android/README.md`, `android/PROTOCOL.md` (the message format between device and phone) |
| [`ui/`](ui/README.md) | Flutter screens (status screen so far), built into `android/app` from source; `ui/desktop` runs them as a Linux window on a fake backend | `ui/README.md` |
| [`extractor/`](extractor/README.md) | Reference sound extractor in Python: audio → feature lines. It is the spec and test oracle for the Pico firmware. Also holds the recording tool, synthetic audio, real-audio evaluation and C test vectors | `extractor/README.md`, `record.py` |
| [`finetune/`](finetune/README.md) | Everything model-side: the synthetic data generator, the students (jevlike, Kev, Verdict), local teacher models, training sweeps, and the local `/v1/systemone` server | `finetune/README.md` |
| [`wiki/`](wiki/index.md) | Design docs and decisions: hardware, signal processing, gestures, personalization, decision models, phone control, latency, roadmap | `wiki/index.md` |
| [`reports/`](reports/README.md) | Finished research reports | |
| [`research_notes/`](research_notes/README.md) | Raw research notes behind the reports | |
| `datasets/` | Public audio datasets for the real-audio evaluation. Untracked (~45 GB); see [`datasets/README.md`](datasets/README.md) | |
| [`firmware/`](firmware/README.md) | The Pico 2 W firmware (Arduino toolchain, arduino-pico core). Bring-up sketches so far; it will port `extractor/vox_extract` and check itself against `extractor/vectors/` | `firmware/README.md` |
| [`hardware/`](hardware/case/README.md) | The 3D-printed necklace case (parametric OpenSCAD), and a 1:1 layout template for the protoboard | `hardware/case/README.md` |
| [`brand/`](brand/README.md) | Canti logo (wordmark and app icon, SVG), colour palette and UI shape rules | `brand/README.md` |

## What is not in git

The repo holds code and docs only. These stay on disk, untracked (see `.gitignore`):
- datasets;
- model checkpoints;
- generated training data (regenerate it with `python -m vox.generate`, see `finetune/data/README.md`);
- predictions and logs;
- emulator state and APKs;
- upstream clones in `finetune/third_party/`;
- **your voice recordings** (`extractor/recordings/`, private).

## Environments

- This is a NixOS machine. Each workspace brings its own environment: `finetune/env.sh` plus `.venv` (ROCm torch), `extractor/run`, and `android/nix/` (flake).
- Commands in each README assume you run them from that workspace's folder.
- The GPU is an AMD Strix Halo (gfx1151) running ROCm.
