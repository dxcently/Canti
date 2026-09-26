# vectors: reference test vectors for the C port

A C port of `vox_extract` should reproduce these files. The audio is **SYNTHETIC** (synth.py). The vectors show that a port computes the same thing as the Python reference. They say nothing about accuracy on real voices.

To regenerate after any change to `vox_extract/` or `Config` (`tests/test_vectors.py` fails until you do), run this from the extractor folder:

```bash
./run python export_vectors.py            # --wav also writes a .wav per case, for listening
```

| File | Contents |
|---|---|
| `manifest.json` | The full `Config`, the vocabulary and its digest, the input high-pass biquad, the 48k→16k decimator taps, the frame-time formula, the comparison tolerances, and each case with its expected `(label, text)` list. |
| `<case>.pcm` | Input: signed 16-bit little-endian mono, at the case's rate (16 kHz, or 48 kHz for `*_48k`). |
| `<case>.frames.csv` | Per-frame reference features at 16 kHz: `FRAME_FIELDS` plus the noise floor after the frame. The fp1 per-frame sums (mel8 etc.) are not in here. |
| `<case>.events.json` | Expected events: timing, label, exact text and the raw measurements. Each event also has its protocol `message`, with the optional `features` entry (`fp`, `fp_version`, `pitch16`). |
| `decimator.in48k.f32`, `decimator.out16k.f32` | The FIR alone: a 48 kHz sweep plus noise in, and the reference 16 kHz output out (float32 LE). |

There are 19 cases:
- the five hum contours;
- a whistled rise;
- pop, click, hiss and click+pop;
- a rise in cafe babble at 10 dB;
- talk, laugh, cough, music, fan motor and silence;
- two 48 kHz cases.

Tolerances are in `manifest.json`: event count, label and text must match exactly, and times must be within 10 ms.
