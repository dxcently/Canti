# datasets (untracked, ~52 GB including the downloaded archives and ~2 GB of evaluation cache)

Public audio used by the real-audio extractor evaluation (`extractor/eval_real/`). Nothing here is committed. Each folder has a loader in `extractor/eval_real/` that maps its files to VOX gesture classes or to "should be none".

| Folder | Used as | Loader |
|---|---|---|
| `mir-qbsh/` | Hummed melodies: pitch-contour ground truth | `qbsh.py` |
| `mlend_hums_whistles/` | Many speakers humming and whistling | `mlend.py` |
| `nonverbal/` | Deeply Nonverbal: tongue clicks and lip pops (positives), lip smacks (borderline), coughs, sighs, laughs, … (negatives) | `nonverbal.py` |
| `nonspeech7k/` | Non-speech human sounds (coughs, screams, laughs, …): negatives | `nonspeech7k.py` |
| `musan/` | Noise, music and speech: negatives and noise mixing | `musan.py` |
| `esc50/` | Environmental sounds incl. cats: negatives | `esc50.py` |
| `vocalset/` | VocalSet: 20 trained singers, vowels a/e/i/o/u across their range, straight and vibrato: voice-cursor vowel separability vs F0 | none (scratch analysis, `wiki/voice-cursor.md`) |
| `hillenbrand/` | Hillenbrand et al. 1995: 139 men/women/children, 12 vowels in /hVd/, hand-measured F0/F1–F3: voice-cursor formant-tracker check | none (scratch analysis, `wiki/voice-cursor.md`) |
| `_eval_cache/` | Evaluation cache, all regenerable: per-clip run records `runs/<tag>/<dataset>_<split>.jsonl`, the pre-fix code snapshot `frozen_src/` (used by `VOX_CODE=frozen`), derived file lists and run logs | `common.py`, `run_all.py` |

Source URLs, licences, fetch commands and files that could not be fetched: see `SOURCES.md`. Note: the root `.gitignore` ignores everything in `datasets/` except this README, so `SOURCES.md` is untracked unless `!/datasets/SOURCES.md` is added there.
