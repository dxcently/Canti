# Dataset sources

These are the public audio sets used by the real-audio evaluation of the extractor (`extractor/eval_real/`).

- **Fetched:** 2026-09-26, from `/home/khoa/VOX/datasets`.
- **Not committed:** nothing here is in git (the repo `.gitignore` has `/datasets/*`).
- **Not redistributed:** the audio stays on this machine. The licences below allow use in a class project, but several are non-commercial or no-derivatives.
- **Rates:** every set is 44.1 kHz or lower. Each one is resampled offline to 16 kHz with `scipy.signal.resample_poly` (`vox_extract.resample.to_16k`). The extractor's 48 kHz decimator is exercised only by the user's own recordings.
- **Splits:** 30 % tune / 70 % test, by speaker, via `sha1("<dataset>:<speaker>") % 100 < 30`. Where a set has no speaker ID, the source recording stands in for it.

| Folder | On disk | Licence | Used |
|---|---|---|---|
| `nonverbal/` | 44 MB tgz, 71 MB unpacked | CC BY-NC-ND 4.0 | all 16 classes |
| `mir-qbsh/` | 112 MB rar, 296 MB unpacked | research corpus, no explicit licence | all 4431 recordings |
| `musan/` | 10.3 GB tar.gz, 12 GB unpacked | CC licences or US public domain, per file | speech, music, noise |
| `mlend_hums_whistles/` | 16 GB | none stated in the repository | 6598 of 6610 files |
| `nonspeech7k/` | 2.5 GB zips, 2.7 GB unpacked | ambiguous: CC BY 4.0 or CC BY-NC-SA 4.0 | 7014 "original" clips |
| `esc50/` | 616 MB zip, 846 MB unpacked | CC BY-NC 3.0 | all 2000 clips |
| `vocalset/` | 2.1 GB zip, 2.5 GB unpacked | CC BY 4.0 | a/i/u files (voice cursor only) |
| `hillenbrand/` | 22 MB zip (+ men/women/kids zips), 72 MB unpacked | repository MIT; data hosted with the author's permission | iy/ah/uw (voice cursor only) |

The archives are still on disk next to the unpacked folders (about 13 GB in total). You can delete them.

## VocalSet (Wilkins et al., ISMIR 2018): `vocalset/`

- **Fetched:** 2026-09-27, for the voice-cursor multi-voice check (`wiki/voice-cursor.md`), not the gesture evaluation.
- **URL:** https://zenodo.org/api/records/1193957/files/VocalSet.zip/content (record https://zenodo.org/records/1193957)
- **Licence:** CC BY 4.0 (Zenodo record). Cite Wilkins, Seetharaman, Wahl, Pardo, "VocalSet: A Singing Voice Dataset", ISMIR 2018.
- **Archive:** `VocalSet.zip`, 2,077,087,366 bytes, md5 `c44f60d34b8724b9a6f6d15e0a3158a9` (matches Zenodo), sha256 `2bf96b80abe57a23323fd8c78be8cb70503e35995e6bae94a6067197c88a61ae`.
- **Content:** 3615 wavs (44.1 kHz) under `FULL/<female1-9|male1-11>/<exercise>/<technique>/`: arpeggios, scales and long tones on a/e/i/o/u, sung straight, with vibrato, belted, breathy, fry, trill and so on. The files carry no per-singer voice-type labels.
- **Subset used:** files ending `_a/_i/_u.wav`, minus lip trill, vocal fry, inhaled and trill. `__MACOSX/` and `.DS_Store` were deleted after unpacking.

```bash
mkdir -p vocalset && cd vocalset
curl -fL --retry 5 -C - -o VocalSet.zip https://zenodo.org/api/records/1193957/files/VocalSet.zip/content
md5sum VocalSet.zip   # c44f60d34b8724b9a6f6d15e0a3158a9
unzip -q VocalSet.zip && rm -rf __MACOSX && find . -name .DS_Store -delete
```

## Hillenbrand, Getty, Clark & Wheeler 1995 vowels: `hillenbrand/`

- **Fetched:** 2026-09-27, for the voice-cursor formant-tracker check.
- **URL:** the original https://homepages.wmich.edu/~hillenbr/voweldata.html now redirects to a university login. The copy used is the mirror https://github.com/santiagobarreda/hillenbrand_et_al_1995 (cloned to `repo/`), which says it is hosted with Jim Hillenbrand's permission.
- **Licence:** the repository is MIT. The recordings are the authors' research data; cite Hillenbrand et al. (1995), JASA 97(5), 3099–3111.
- **Archive:** `repo/h95-alldata.zip`, sha256 `2560548591e3a726c88549b6dc9d226995616c26874d601c69fee8b9eee9d730`.
- **Content:** unpacked to `data/`:
  - `men/`, `women/`, `kids/`: 1668 wavs at 16 kHz of /hVd/ words;
  - file names: char 1 is m/w/b/g, chars 2–3 the talker, chars 4–5 the vowel (iy = heed, ah = hod, uw = who'd, …);
  - `data/vowdata.dat`: hand-measured duration, steady-state F0 and F1–F4, and F1–F3 at 20/50/80 % (0 = not measurable).
- **Subset used:** iy/ah/uw (ee/ah/oo), with `vowdata.dat` as ground truth.

```bash
mkdir -p hillenbrand && cd hillenbrand
git clone https://github.com/santiagobarreda/hillenbrand_et_al_1995 repo
unzip -q repo/h95-alldata.zip -d data
```

## Deeply Nonverbal Vocalization Dataset (OpenSLR 99): `nonverbal/`

- **URL:** https://openslr.elda.org/resources/99/NonverbalVocalization.tgz (listed on https://www.openslr.org/99/)
- **Licence:** CC BY-NC-ND 4.0, per `NonverbalVocalization/README.md`. The set is a ~5 % subset of Deeply Inc.'s commercial corpus.
- **Content:**
  - 16 kHz mono;
  - 16 classes, one speaker performing one class per file, often several times;
  - no per-event timestamps.
- **Subset used:** every class.
  - Positives: tongue-clicking → click, lip-popping → pop.
  - Borderline: lip-smacking.
  - Negatives: every other class.

```bash
mkdir -p nonverbal && cd nonverbal
curl -fL --retry 5 -C - -o NonverbalVocalization.tgz https://openslr.elda.org/resources/99/NonverbalVocalization.tgz
tar xzf NonverbalVocalization.tgz            # -> NonverbalVocalization/<class>/*.wav
```

## MIR-QBSH (Roger Jang, MIR Lab): `mir-qbsh/`

- **URL:** the original http://mirlab.org/dataSet/public/MIR-QBSH-corpus.rar timed out on 2026-09-26. The copy used is the Internet Archive capture of 2015-04-29:
  `https://web.archive.org/web/20150429171614id_/http://mirlab.org/dataSet/public/mir-qbsh-corpus.rar`
- **Licence:** none stated. It is distributed publicly for research, and the MIREX QBSH task has used it since 2005. Cite Jang, "MIR-QBSH corpus", MIR Lab, National Taiwan University.
- **Content:**
  - 4431 sung or hummed queries (8 kHz, 8 s each);
  - a manual pitch file (`.pv`, semitones per 32 ms frame) for each query.
- **Subset used:**
  - all recordings, for the pitch-tracker comparison;
  - contour clips cut from them by the rules in `extractor/eval_real/qbsh.py`.
- **Speakers:** taken from the `personDirInfo.txt` name bytes, which merges a person across years. That gives 184 speakers.

```bash
mkdir -p mir-qbsh && cd mir-qbsh
curl -fL --retry 5 -o MIR-QBSH-corpus.rar "https://web.archive.org/web/20150429171614id_/http://mirlab.org/dataSet/public/mir-qbsh-corpus.rar"
# 7-Zip from nixpkgs cannot unpack this RAR method; unrar is unfree, so it needs --impure:
NIXPKGS_ALLOW_UNFREE=1 nix shell --impure nixpkgs#unrar -c unrar x -o+ -idq MIR-QBSH-corpus.rar
```

## MUSAN (Snyder, Chen & Povey 2015; OpenSLR 17): `musan/`

- **URL:** https://openslr.elda.org/resources/17/musan.tar.gz
- **Licence:** every file is under a Creative Commons licence or in the US public domain. The authors left out anything that forbids commercial use. Per-file licences are in `musan/<part>/*/LICENSE`.
- **Subset used:** one excerpt of at most 60 s per file, starting at 20 s (or at the end part of a shorter file). The three parts are used as follows:

  | Part | Used as | Split by |
  |---|---|---|
  | speech/ (librivox, us-gov) | negatives | file |
  | music/ | negatives | artist |
  | noise/ | noise mixed into positives at 20 / 10 / 5 dB SNR, and negatives in its own right | file |

  - For noise mixing, the tune split draws noise only from tune files and the test split only from test files.
  - One file is scored as a cat meow in the ESC-50 report instead: `noise/sound-bible/noise-sound-bible-0013.wav` ("Cat Meow 2").

```bash
mkdir -p musan && cd musan
curl -fL --retry 10 --retry-delay 5 -C - -o musan.tar.gz https://openslr.elda.org/resources/17/musan.tar.gz
tar xzf musan.tar.gz                          # -> musan/{speech,music,noise}
```

## MLEnd Hums and Whistles (Queen Mary University of London): `mlend_hums_whistles/`

- **URL:** https://github.com/MLEndDatasets/HumsAndWhistles. The raw files come from `raw/main/...`; the `mlend` PyPI package fetches from the same place.
- **Licence:** the repository states none. The data is published for teaching (QMUL "MLEnd" datasets). Treat it as all-rights-reserved and use it for evaluation only.
- **Content:**
  - 226 interpreters;
  - 8 songs, each hummed and whistled, about 15–20 s per file;
  - recorded on the interpreters' own devices, 44.1 kHz.
- **Subset used:** all files that downloaded (6598 of 6610). Speaker = `Interpreter`.
- **Unreachable:** 10 files failed on both passes, 5 retries each (GitHub raw returned errors):
  0727, 1411, 1439, 2118, 2130, 4541, 4569, 5677, 5887, 6356.

```bash
mkdir -p mlend_hums_whistles && cd mlend_hums_whistles
for f in MLEndHWD_audio_attributes_benchmark.csv MLEndHWD_interpreter_demographics_benchmark.csv; do
  curl -sfL -o $f https://github.com/MLEndDatasets/HumsAndWhistles/raw/main/$f; done
mkdir -p MLEndHWD_audiofiles
tail -n +2 MLEndHWD_audio_attributes_benchmark.csv | cut -d, -f1 | xargs -P 6 -I{} sh -c \
  'test -s MLEndHWD_audiofiles/{} || curl -sfL --retry 5 -o MLEndHWD_audiofiles/{} https://github.com/MLEndDatasets/HumsAndWhistles/raw/main/MLEndHWD_audiofiles/{} || echo FAIL {}' > dl.log 2>&1
```

## Nonspeech7k (Rashid et al., IET Signal Processing 2023; Zenodo): `nonspeech7k/`

- **URL:** https://zenodo.org/records/6967442 (DOI 10.5281/zenodo.6967442). The files come from `https://zenodo.org/api/records/6967442/files/<name>/content`, with spaces in the name encoded as `%20`.
- **Licence:** this is inconsistent. The record's metadata says CC BY 4.0, but the description text says CC BY-NC-SA 4.0. Assume the stricter one: non-commercial, share-alike.
- **Content:**
  - 7 classes: breath, cough, crying, laugh, screaming, sneeze, yawn;
  - clips of 0.5–4 s, 32 kHz mono.
- **Subset used:** the rows marked "Original" (not augmented) in both metadata CSVs. That is 7014 clips; the train/test folders are pooled and re-split by `File ID`.
- **Metadata quirks:** the two CSVs spell their headers differently, and the train CSV says "Orignal" and "yawm". The loader normalises all of these.

```bash
mkdir -p nonspeech7k && cd nonspeech7k
for f in test.zip train.zip "metadata of train set .csv" "metadata of test set.csv" "youtube ID vs link .TXT"; do
  curl -fL --retry 5 -o "$f" "https://zenodo.org/api/records/6967442/files/$(printf %s "$f" | sed 's/ /%20/g')/content"; done
unzip -q -o test.zip && unzip -q -o train.zip   # -> test/, train/
```

## ESC-50 (Piczak 2015): `esc50/`

- **URL:** https://github.com/karoldvl/ESC-50/archive/master.zip
- **Licence:** CC BY-NC 3.0, per the repository README. The clips come from freesound.org.
- **Content:** 2000 clips of 5 s each, 44.1 kHz mono, in 50 classes.
- **Subset used:** all 50 classes, as negatives. "cat" (40 clips) is the class of interest, plus the MUSAN meow. Split by `src_file`.

```bash
mkdir -p esc50 && cd esc50
curl -fL --retry 5 -o ESC-50-master.zip https://github.com/karoldvl/ESC-50/archive/master.zip
unzip -q ESC-50-master.zip                    # -> ESC-50-master/{audio,meta}
```

## Tools installed

- Only one package was installed for this work: `praat-parselmouth` 0.4.7, into the extractor's own venv. It is used as the reference pitch tracker for MLEnd.

  ```bash
  nix shell nixpkgs#uv -c uv pip install --python .venv/bin/python praat-parselmouth
  ```

- Nothing was installed system-wide.

## `_eval_cache/`

This folder is evaluation output, not a dataset. It is regenerable.

- `runs/<tag>/<dataset>_<split>.jsonl`: per-clip records from `extractor/eval_real/run_all.py`.
- `frozen_src/`: a snapshot of `vox_extract/` as it was before the real-audio fixes, used by `VOX_CODE=frozen`. Its md5s are in `frozen_code.md5`.
- `*.log`: run logs.
