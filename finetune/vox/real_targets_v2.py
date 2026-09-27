"""Real-screen TRAINING data for intent cursor mode: data/real-targets-v2 (split rules: data/real-targets-v2/SPLIT.md).

Reuses real_targets.py (v1: prompt text, DeepSeek call, marks drawing, phrase ids, scorer). v1's emulator screens,
phrases and labels are carried over unchanged; new emulator screens come from android/suite/harvest_explore.py.

Stages (run from finetune/):
  screens   v1 kept screens + v2 raw captures -> emulator/screens.jsonl (+ marks for new screens; needs Pillow, see v1)
  prompts   DeepSeek prompts for the NEW screens (same PROMPT as v1; --n phrases per screen)
  phrases   `eidolon run -m ollama:deepseek-v4-pro` over the prompts (emulator screens only, never Z Flip content)
  tolabel   phrase list with stable ids + labelling batches (emulator/label_batches/*.json) for the Opus labellers
  build     rows for every labelled phrase -> train_real / val_real / test_real (+ zflip/*_zflip.jsonl, gitignored)
  mix       a training file: real rows (oversampled, + drop-gold negatives) + a synthetic targets-v2 sample
  user      heldout/user_phrasings.md section C/E lines -> test_user.jsonl (once the user has written them and they are labelled)

Z Flip rows (phrases written by Claude, never sent to any external model) are built from zflip/phrases.jsonl and
zflip/labels.jsonl; every file derived from them stays under zflip/ (gitignored).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import random
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from vox import real_targets as v1

FT = Path(__file__).resolve().parents[1]
V1 = FT / "data" / "real-targets-v1"
D = FT / "data" / "real-targets-v2"
SYN = FT / "data" / "targets-v2"
NONE_OPTION = v1.NONE_OPTION
HELDOUT_PKGS = {"com.twitter.android", "org.wikipedia", "de.danoeh.antennapod", "org.tasks"}
# Locked test (SPLIT.md amendment 2026-09-27): never trained on, never used for selection; scored only by
# students/verdict/suite.py --final <run>, once per release. The sha256 of the sorted, newline-joined list is sealed in SPLIT.md.
LOCKED_PKGS = frozenset({
    "com.foobnix.pro.pdf.reader",
    "com.looker.droidify",
    "com.jiaqifeng.hacki",
    "com.kylecorry.trail_sense",
    "de.grobox.liberario",
    "dev.dimension.flare",
    "dev.octoshrimpy.quik.fdroid",
    "me.ash.reader",
    "net.osmand.plus",
    "net.programmierecke.radiodroid2",
    "nl.viter.glider",
    "nodomain.freeyourgadget.gadgetbridge",
    "openfoodfacts.github.scrachx.openfood",
    "org.briarproject.briar.android",
    "org.framasoft.peertube",
})
LOCKED_SHA256 = "c95aa250dd3719c53fc9aea895abf8945116db1a44e24499f5d1bf8158ba0a7a"
assert hashlib.sha256("\n".join(sorted(LOCKED_PKGS)).encode()).hexdigest() == LOCKED_SHA256, "LOCKED_PKGS changed after sealing"
VAL_FRAC = 0.12
DIALOG_PKGS = {"com.android.permissioncontroller", "android", "com.android.intentresolver"}
APP_ALIAS = {"settings2": "settings"}
jl, wjl = v1.jl, v1.wjl


def rel(p: Path) -> str:
    return str(p.relative_to(FT))


def val_screen(screen_id: str) -> bool:
    return int(hashlib.sha1(screen_id.encode()).hexdigest()[:8], 16) % 1000 < VAL_FRAC * 1000


# Val assignment mode (build --val-mode). "screen" = v1a-v1e (hash of screen_id; near-duplicate screens could land on
# both sides). "optset" (SPLIT.md amendment 2026-09-27) = hash of package + option-set cluster: screens of one package
# whose option-label sets have Jaccard >= 0.8 are linked, and a linked cluster goes to one side as a whole.
VAL_MODE = "screen"
_VAL_KEY: dict[str, str] = {}
# Option text format of a build (OptionFormat.kt; vox/option_format.py). "v1" rows are the stored text unchanged (no
# option_format field: missing = v1). "v2" rows are re-serialised: exact from a capture's own options_v2 when it has one,
# else approximated from the stored screen (v2_approx: True / "no_tree"; never used to score v2).
OPTION_FORMAT = "v1"
_FMT_CACHE: dict[str, dict] = {}


def formatted(s: dict) -> dict:
    """The screen with its options in OPTION_FORMAT (cached per screen)."""
    if OPTION_FORMAT == "v1":
        return s
    if s["screen_id"] in _FMT_CACHE:
        return _FMT_CACHE[s["screen_id"]]
    from vox import option_format as of
    if s.get("options_v2"):                        # exact capture (the app's own v2 text) or its port re-serialisation
        out = {**s, "options": s["options_v2"], "option_format": "v2",
               "v2_approx": False if s.get("options_exact", "app") == "app" else "port"}
    else:
        nodes, size, root = None, s.get("screen_size"), None
        if s.get("source") == "v2" and s.get("raw_id"):
            r = _raw_index(D / "emulator" / "raw" / "screens.jsonl").get(s["raw_id"], {})
            nodes, size = r.get("nodes"), r.get("screen_size", size)
        elif s.get("source") == "v1":
            r = _raw_index(V1 / "emulator" / "raw" / "screens.jsonl").get(s["screen_id"], {})
            nodes, size = r.get("nodes"), r.get("screen_size", size)
        elif s.get("source") == "zflip-raw":
            r = _raw_index(V1 / "zflip" / "raw" / "screens.jsonl").get(s["screen_id"], {})
            size = r.get("screen_size") or (1080, 2640)
            if r.get("xml"):
                root = of.tree_from_xml((V1 / "zflip" / "raw" / r["xml"]).read_text())
        elif str(s.get("source", "")).startswith("zflip"):
            size = size or (1080, 2640)
        opts, info = of.reserialize(s["options"], s["bounds"], size, nodes, "v2", root=root)
        out = {**s, "options": opts, "option_format": "v2", "v2_approx": info["v2_approx"]}
    _FMT_CACHE[s["screen_id"]] = out
    return out


_RAW_CACHE: dict[str, dict] = {}


def _raw_index(p: Path) -> dict:
    k = str(p)
    if k not in _RAW_CACHE:
        _RAW_CACHE[k] = {r["screen_id"]: r for r in jl(p)} if p.exists() else {}
    return _RAW_CACHE[k]


def label_set(options: list[str]) -> frozenset:
    return frozenset(re.sub(r" \([^()]*\)$", "", o).strip().lower() for o in options[:-1])


def optset_val_keys(screens: list[dict], jac: float = 0.8) -> dict[str, str]:
    """screen_id -> 'package|cluster signature' (connected components of option-label Jaccard >= jac within a package)."""
    by = defaultdict(list)
    for s in screens:
        by[s.get("app_pkg", s["package"])].append(s)
    out = {}
    for pkg, ss in by.items():
        ls = [label_set(s["options"]) for s in ss]
        parent = list(range(len(ss)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                u = len(ls[i] | ls[j])
                if u and len(ls[i] & ls[j]) / u >= jac:
                    parent[find(i)] = find(j)
        comp = defaultdict(list)
        for i in range(len(ss)):
            comp[find(i)].append(i)
        for members in comp.values():
            sig = min("\x1f".join(sorted(ls[i])) for i in members)
            for i in members:
                out[ss[i]["screen_id"]] = f"{pkg}|{sig}"
    return out


# Forks / clients of one service: always in the same cross-fit fold, so "out-of-app" is not a sibling of a training app.
APP_FAMILIES = {"clock": ["clock", "fclock", "bestclock"], "contacts": ["contacts", "fcontacts"], "calendar": ["calendar", "fcalendar"],
                "files": ["files", "ffiles", "mfiles"], "gallery": ["gallery", "gallery3d"], "phone": ["dialer", "fphone"],
                "youtube": ["youtube", "ytmusic", "newpipe", "libretube"], "mastodon": ["tusky", "mastodon"]}


def split_of(pkg: str, screen_id: str) -> str:
    if pkg in LOCKED_PKGS:
        return "locked"
    if pkg in HELDOUT_PKGS:
        return "test"
    if VAL_MODE == "optset":
        return "val" if val_screen(_VAL_KEY[screen_id]) else "train"
    return "val" if val_screen(screen_id) else "train"


# --- screens -------------------------------------------------------------------------------------------------------------

def cmd_screens(a) -> None:
    out, dropped, seen = [], {}, {}
    for s in jl(V1 / "emulator" / "screens.jsonl"):
        sig = (s["package"], tuple(s["options"]), s["screen_text"], "pre-occlusion")
        seen[sig] = s["screen_id"]
        out.append({**s, "source": "v1", "app_pkg": s["package"] if s["app"] != "settings" else "com.android.settings",
                    "screenshot": rel(V1 / s["screenshot"]), "marks": rel(V1 / s["marks"])})
    raw = jl(D / "emulator" / "raw" / "screens.jsonl")
    # the walk's own package = the most common package among its captures
    main_pkg = {app: Counter(r["package"] for r in raw if r["app"] == app).most_common(1)[0][0] for app in {r["app"] for r in raw}}
    (D / "emulator" / "marks").mkdir(parents=True, exist_ok=True)
    for r in raw:
        sid, app = r["screen_id"].replace("emu-", "emu2-", 1), APP_ALIAS.get(r["app"], r["app"])   # v1 uses emu-<app>-NN too
        app_pkg = "com.android.settings" if app == "settings" else main_pkg[r["app"]]
        ok_pkgs = {app_pkg} | DIALOG_PKGS | ({"com.android.settings.intelligence"} if app == "settings" else set())
        sig = (r["package"], tuple(r["options"]), r["screen_text"], extract_of(r))
        if r["package"] not in ok_pkgs:
            dropped[sid] = f"outside the app ({r['package']})"
        elif len(r["options"]) < 3:
            dropped[sid] = "fewer than 2 elements"
        elif sig in seen:
            dropped[sid] = f"same options and screen line as {seen[sig]}"
        elif sum(o.startswith("unlabeled") for o in r["options"][:-1]) > 0.6 * (len(r["options"]) - 1):
            dropped[sid] = "mostly unlabeled elements"
        else:
            seen[sig] = sid
            m = D / "emulator" / "marks" / f"{sid}.png"
            if not m.exists() or a.redraw:
                v1.draw_marks(D / "emulator" / "raw" / r["screenshot"], r["bounds"], m)
            out.append({k: r[k] for k in ("tag", "package", "app_name", "state_template", "screen_text",
                                          "options", "bounds", "stable", "step", "captured_at")}
                       | {"screen_id": sid, "raw_id": r["screen_id"], "app": app, "app_pkg": app_pkg, "source": "v2",
                          "screenshot": rel(D / "emulator" / "raw" / r["screenshot"]), "marks": rel(m),
                          "texts": (r.get("summary") or {}).get("texts", [])})
    out += exact_screens(out, seen, dropped, a.redraw)
    wjl(D / "emulator" / "screens.jsonl", out)
    (D / "emulator" / "dropped_screens.json").write_text(json.dumps(dropped, indent=1))
    print(f"kept {len(out)} screens ({sum(s['source'] == 'v2' for s in out)} new) over {len({s['app_pkg'] for s in out})} apps; "
          f"dropped {len(dropped)}: {Counter(v.split(' (')[0] for v in dropped.values())}")
    print(Counter(s["app"] for s in out).most_common())


# Exact captures (Canti builds that send options_v1 AND options_v2 with per-target bounds, plus a full raw_tree).
# raw_devtest3 = dev-test-exact (held-out apps: dev-test only, never trained); raw_train3 = training; raw_locked3 = the
# re-captured locked screens (split by LOCKED_PKGS as always). Screens from a build that sent a single format are
# re-serialised from their raw_tree by the app's Python port (tree_targets, byte-parity with Targets.kt): options_exact
# = "port" (never used to score v2); screens with the app's own lists: options_exact = "app".
EXACT_DIRS = ("raw_devtest3", "raw_train3", "raw_locked3")


def exact_screens(prev: list[dict], seen: dict, dropped: dict, redraw: bool = False) -> list[dict]:
    from vox import option_format as of
    app_pkg_of = {s["app"]: s["app_pkg"] for s in prev}
    out, seen_x = [], {}   # exact sets are de-duplicated among themselves only (a dev-test-exact screen may repeat an old one)
    for d in EXACT_DIRS:
        zr = D / "emulator" / d
        if not (zr / "screens.jsonl").exists():
            continue
        (zr / "marks").mkdir(exist_ok=True)
        raws = jl(zr / "screens.jsonl")
        main_pkg = {a: Counter(r["package"] for r in raws if r["app"] == a and r["package"] not in DIALOG_PKGS).most_common(1)
                    for a in {r["app"] for r in raws}}
        for r in raws:
            sid, app = r["screen_id"], APP_ALIAS.get(r["app"], r["app"])
            assert sid.startswith("emu") and "zf" not in sid, sid
            size = of.json_list(r.get("screen_size") or [1080, 2400])
            if r.get("options_v1") and r.get("options_v2"):
                o1, o2, bounds, exact = r["options_v1"], r["options_v2"], [t["bounds"] for t in r["targets_v1"]], "app"
            elif not any("focusable" in x for x in (r.get("raw_tree") or [])[:1]):
                dropped[sid] = f"single-format capture without a full raw_tree (build {r.get('build')}): not exact"
                continue
            else:
                root = of.tree_from_raw(r.get("raw_tree") or [])
                t1 = of.tt.build(root, size[0], size[1], of.EMU_BARS, fmt="v1")
                o1, o2, bounds, exact = (of.tt.options(t1), of.tt.options(of.tt.build(root, size[0], size[1], of.EMU_BARS, fmt="v2")),
                                         [t["bounds"] for t in t1], "port")
            bounds = [list(of._box(b)) for b in bounds]
            assert o1[-1] == NONE_OPTION and o2[-1] == NONE_OPTION and len(o1) == len(o2) == len(bounds) + 1, sid
            app_pkg = r["package"] if r["package"] not in DIALOG_PKGS else \
                app_pkg_of.get(app) or (main_pkg[r["app"]][0][0] if main_pkg[r["app"]] else r["package"])
            sig = (r["package"], tuple(o1), r["screen_text"], "occlusion")
            if len(o1) < 3:
                dropped[sid] = "fewer than 2 elements"
                continue
            if sig in seen_x:
                dropped[sid] = f"same options and screen line as {seen_x[sig]}"
                continue
            seen_x[sig] = sid
            m = zr / "marks" / f"{sid}.png"
            if not m.exists() or redraw:
                v1.draw_marks(zr / r["screenshot"], bounds, m, screen_w=size[0])
            out.append({k: r[k] for k in ("tag", "package", "app_name", "state_template", "screen_text", "stable", "step", "captured_at", "build")}
                       | {"screen_id": sid, "app": app, "app_pkg": app_pkg, "source": "v3", "exact_set": d, "options_exact": exact,
                          "options": o1, "options_v1": o1, "options_v2": o2, "bounds": bounds, "screen_size": list(size),
                          "extract": "occlusion", "screenshot": rel(zr / r["screenshot"]), "marks": rel(m),
                          "texts": (r.get("summary") or {}).get("texts", [])})
    return out


# --- prompts / phrases (DeepSeek, emulator only) -------------------------------------------------------------------------

def cmd_prompts(a) -> None:
    pdir = D / "emulator" / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for s in jl(D / "emulator" / "screens.jsonl"):
        if s["source"] == "v2":
            (pdir / f"{s['screen_id']}.txt").write_text(v1.prompt_for(s, a.n))
            n += 1
        elif s["source"] == "v3":   # exact captures: at least 3 none phrases per screen (plan STEP 2.7 / exact captures)
            p = v1.prompt_for(s, a.n + 1)
            old = 'use each kind at most twice, and include at least one "none"'
            assert old in p
            (pdir / f"{s['screen_id']}.txt").write_text(p.replace(old, 'use each other kind at most twice, and include at least three "none" phrases'))
            n += 1
    print(f"{n} prompts -> {pdir}")


def cmd_phrases(a) -> None:
    screens = [s for s in jl(D / "emulator" / "screens.jsonl") if s["source"] in ("v2", "v3")]
    # Hard boundary: DeepSeek sees emulator screens only. Z Flip captures (zflip/raw, real-targets-v1/zflip) live in a
    # separate manifest (zflip/screens.jsonl) that this stage never reads; these asserts catch any accidental mixing.
    assert all(not s["package"].startswith("com.twitter") and "zflip" not in s["screenshot"]
               and s["screenshot"].startswith(("data/real-targets-v2/emulator/", "data/real-targets-v1/emulator/"))
               and not s["screen_id"].startswith("zf") and "serial" not in s for s in screens), "non-emulator screen in the DeepSeek job"
    out_p = D / "emulator" / "phrases.jsonl"
    done = {r["screen_id"] for r in jl(out_p)}
    todo = [s for s in screens if s["screen_id"] not in done][: a.limit or None]
    cwd = D / "emulator" / ".eidolon-cwd"
    cwd.mkdir(exist_ok=True)

    def one(s):
        p = (D / "emulator" / "prompts" / f"{s['screen_id']}.txt").read_text()
        err = None
        for _ in range(3):
            try:
                txt, sess = v1.run_eidolon(p, cwd)
                return s, v1.parse_phrases(txt), sess, txt
            except (json.JSONDecodeError, ValueError, subprocess.TimeoutExpired) as e:
                err = e
        return s, None, "", f"failed: {err}"

    ok = 0
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for s, ph, sess, txt in ex.map(one, todo):
            if ph is None:
                print(f"  {s['screen_id']}: {txt}", flush=True)
                continue
            with out_p.open("a") as f:
                f.write(json.dumps({"screen_id": s["screen_id"], "model": v1.PHRASE_MODEL, "session": sess, "phrases": ph,
                                    "raw": txt}, ensure_ascii=False) + "\n")
            ok += 1
            if ok % 20 == 0:
                print(f"  {ok}/{len(todo)} screens phrased", flush=True)
    print(f"{ok}/{len(todo)} screens phrased")


# --- labelling batches ---------------------------------------------------------------------------------------------------

def cmd_tolabel(a) -> None:
    screens = {s["screen_id"]: s for s in jl(D / "emulator" / "screens.jsonl")}
    labelled = {r["pid"] for f in sorted((D / "emulator" / "labels").glob("*.jsonl")) for r in jl(f)}
    rows = []
    for r in jl(D / "emulator" / "phrases.jsonl"):
        for p in r["phrases"]:
            rows.append({"pid": v1.pid(r["screen_id"], "deepseek-v4-pro", p["phrase"]), "screen_id": r["screen_id"],
                         "phrase": p["phrase"], "phrase_kind": p.get("kind"), "intended": p.get("intended"),
                         "phrase_source": "deepseek-v4-pro"})
    wjl(D / "emulator" / "to_label.jsonl", rows)
    todo = defaultdict(list)
    for r in rows:
        if r["pid"] not in labelled:
            todo[r["screen_id"]].append(r)
    bdir = D / "emulator" / "label_batches"
    bdir.mkdir(exist_ok=True)
    # batches are append-only (labellers may be working on earlier ones): skip screens already in a batch file
    batched = {x["screen_id"] for f in bdir.glob("batch_*.json") for x in json.loads(f.read_text())}
    start = 1 + max([int(f.stem.split("_")[1]) for f in bdir.glob("batch_*.json")] or [-1])
    sids = sorted(s for s in todo if s not in batched)
    for b in range(0, len(sids), a.per_batch):
        batch = []
        for sid in sids[b:b + a.per_batch]:
            s = screens[sid]
            batch.append({"screen_id": sid, "app": s["app_name"], "screen": s["screen_text"], "marks": str(FT / s["marks"]),
                          "options": {("none" if i == len(s["options"]) - 1 else str(i)): o for i, o in enumerate(s["options"])},
                          "phrases": [{"pid": r["pid"], "phrase": r["phrase"], "writer_kind": r["phrase_kind"],
                                       "writer_intended": r["intended"]} for r in todo[sid]]})
        (bdir / f"batch_{start + b // a.per_batch:03d}.json").write_text(json.dumps(batch, indent=1, ensure_ascii=False))
    print(f"{len(rows)} phrases; {sum(map(len, todo.values()))} unlabelled on {len(todo)} screens; "
          f"{len(sids)} screens newly batched -> {-(-len(sids) // a.per_batch)} new batches from batch_{start:03d} in {bdir}")


# --- Z Flip (personal; Claude writes the phrases; nothing leaves the machine) ---------------------------------------------

# Z Flip social captures left out of Verdict data (user decision, STEP 3.12): unusable captures, and the Instagram
# screens whose target list is empty (the app's bottom-sheet occlusion bug) are the APP's occlusion regression case.
ZF_EXCLUDE = {"zf-facebook-01", "zf-telegram-01", "zf-linkedin-04"}
ZF_OCCLUSION_CASE = {f"zf-instagram-{i:02d}" for i in range(6, 11)}


def cmd_zscreens(a) -> None:
    """Z Flip tree captures (real-targets-v1/zflip/raw) -> zflip/screens.jsonl + writer batches for new screens.
    The vision-built zfNN screens are left out: they are the screens the user phrases for the gold test."""
    zd = D / "zflip"
    out = []
    from vox.real_targets import draw_marks
    # tree captures, the vision-built option lists of the user's screenshots (zfNN), and (v2) the social-app tree captures
    for src, zr in (("raw", V1 / "zflip" / "raw"), ("vision", V1 / "zflip" / "vision"), ("raw2", zd / "raw")):
        if not (zr / "screens.jsonl").exists():
            continue
        # marks for every capture that has a screenshot and none yet (was: raw2 only, so the v1 raw social captures had none)
        (zr / "marks").mkdir(exist_ok=True)
        for r in jl(zr / "screens.jsonl"):
            m = zr / "marks" / f"{r['screen_id']}.png"
            if not m.exists() and len(r["options"]) >= 3 and r.get("screenshot") and (zr / r["screenshot"]).exists():
                draw_marks(zr / r["screenshot"], r["bounds"], m, screen_w=(r.get("screen_size") or [1080])[0])
        for r in jl(zr / "screens.jsonl"):
            if len(r["options"]) < 3 or r["screen_id"] in ZF_EXCLUDE | ZF_OCCLUSION_CASE:
                continue
            m = zr / "marks" / f"{r['screen_id']}.png"
            out.append({k: r.get(k, "") for k in ("screen_id", "tag", "app", "package", "app_name", "state_template",
                                                  "screen_text", "options", "bounds", "captured_at")}
                       | ({"extract": r["extract"]} if r.get("extract") else {})
                       | {"app_pkg": r["package"], "source": "zflip-" + src,
                          "options_source": r.get("options_source", "tree" if src == "raw" else "vision"),
                          "marks": rel(m) if m.exists() else ""})
    wjl(zd / "screens.jsonl", out)
    done = {p["screen_id"] for p in jl(zd / "phrases.jsonl")}
    bdir = zd / "write_batches"
    bdir.mkdir(exist_ok=True)
    batched = {x["screen_id"] for f in bdir.glob("zbatch_*.json") for x in json.loads(f.read_text())}
    start = 1 + max([int(f.stem.split("_")[1]) for f in bdir.glob("zbatch_*.json")] or [-1])
    todo = [s for s in out if s["screen_id"] not in done and s["screen_id"] not in batched and s["marks"]]
    for b in range(0, len(todo), a.per_batch):
        batch = [{"screen_id": s["screen_id"], "app": s["app_name"], "screen": s["screen_text"], "marks": str(FT / s["marks"]),
                  "options": {("none" if i == len(s["options"]) - 1 else str(i)): o for i, o in enumerate(s["options"])}}
                 for s in todo[b:b + a.per_batch]]
        (bdir / f"zbatch_{start + b // a.per_batch:03d}.json").write_text(json.dumps(batch, indent=1, ensure_ascii=False))
    print(f"{len(out)} zflip screens ({Counter(s['app'] for s in out)}); {len(todo)} newly batched; "
          f"{sum(not s['marks'] for s in out)} without marks")


def cmd_zcollect(a) -> None:
    """zflip/written/*.jsonl (one line per phrase: screen_id, phrase, kind, gold, acceptable, ...) -> phrases + labels."""
    zd = D / "zflip"
    ph, lab = [], []
    for f in sorted((zd / "written").glob("*.jsonl")):
        for r in jl(f):
            p = v1.pid(r["screen_id"], "claude-opus", r["phrase"])
            ph.append({"pid": p, "screen_id": r["screen_id"], "phrase": r["phrase"], "phrase_kind": r["kind"],
                       "intended": r["gold"], "phrase_source": "claude-opus"})
            lab.append({"pid": p, **{k: r[k] for k in ("gold", "acceptable", "ambiguous", "confidence", "note") if k in r}})
    wjl(zd / "phrases.jsonl", ph)
    wjl(zd / "labels.jsonl", lab)
    print(f"{len(ph)} zflip phrases on {len({p['screen_id'] for p in ph})} screens")


# --- build ---------------------------------------------------------------------------------------------------------------

# Canti builds installed on emulator-5580 with the occlusion-aware target list (Targets.kt 19:06 on 2026-09-26): screens
# captured at or after this time use it. None = not installed yet (every emulator row is pre-occlusion).
OCCLUSION_BUILD_AT: str | None = "2026-09-26T19:14:17"   # canti-combined-20260926-1918.apk, install -r by the user
# Labels that say a visible element is missing from the option list (usually a FAB) and therefore chose "none": correct
# for the old list, wrong for the app's new one, so they are left out of every split.
UNBOXED_NOTE = re.compile(r"not (among|in) the options|not an option|no box|isn't an option|unboxed|not one of the options", re.I)


def extract_of(s: dict) -> str:
    if s.get("extract"):   # set at capture time (Z Flip social harvest: from the phone's Canti build)
        return s["extract"]
    if s.get("options_source", "tree") != "tree":
        return "vision"
    at = s.get("captured_at") or ""
    return "occlusion" if OCCLUSION_BUILD_AT and at >= OCCLUSION_BUILD_AT else "pre-occlusion"


def make_row(s: dict, p: dict, lab: dict, split: str, idx: int, source_tag: str) -> dict:
    s = formatted(s)
    keys = [f"t{i}" for i in range(len(s["options"]) - 1)] + ["none"]
    g = lab["gold"]
    gold = len(keys) - 1 if g == "none" else int(g)
    acc = sorted({len(keys) - 1 if x == "none" else int(x) for x in (lab.get("acceptable") or [g])} | {gold})
    pk = p.get("phrase_kind") or "user"
    kind = "none" if keys[gold] == "none" else ("near_none" if pk == "none" else pk)
    return {"context": s["state_template"].replace("{UTTERANCE}", p["phrase"]), "options": s["options"], "label": gold,
            "option_keys": keys, "kind": kind, "meta": {"target": keys[gold], "pid": p["pid"]},
            "id": f"rt2-{source_tag}-{idx}", "split": split, "screen_id": s["screen_id"], "app": s["app"],
            "package": s.get("app_pkg", s["package"]), "tag": s.get("tag", ""), "marks": s.get("marks", ""),
            "phrase": p["phrase"], "phrase_source": p["phrase_source"], "phrase_kind": pk,
            "phrase_intended": p.get("intended"), "gold": g, "acceptable": acc, "ambiguous": bool(lab.get("ambiguous")),
            "confidence": lab.get("confidence", "high"), "label_note": lab.get("note", ""),
            "options_source": s.get("options_source", "tree"), "extract": extract_of(s),
            **({"option_format": s["option_format"], "v2_approx": s["v2_approx"]} if s.get("option_format") else {}),
            **({"exact_set": s["exact_set"], "options_exact": s["options_exact"]} if s.get("exact_set") else {})}


def build_emulator() -> list[dict]:
    screens = {s["screen_id"]: s for s in jl(D / "emulator" / "screens.jsonl")}
    labels = {r["pid"]: r for r in jl(V1 / "emulator" / "labels.jsonl")}
    for f in sorted((D / "emulator" / "labels").glob("*.jsonl")):
        labels.update({r["pid"]: r for r in jl(f)})
    phrases = [p for p in jl(V1 / "emulator" / "to_label.jsonl") if p["phrase_source"] != "user"] + jl(D / "emulator" / "to_label.jsonl")
    rows, stats = [], Counter()
    for p in phrases:
        s, lab = screens.get(p["screen_id"]), labels.get(p["pid"])
        if s is None:
            stats["screen dropped"] += 1
        elif lab is None:
            stats["unlabelled"] += 1
        elif lab.get("drop"):
            stats["label drop"] += 1
        elif lab["gold"] == "none" and extract_of(s) == "pre-occlusion" and UNBOXED_NOTE.search(lab.get("note", "")):
            stats["none only because a visible element is unboxed (old extraction)"] += 1
        else:
            rows.append(make_row(s, p, lab, split_of(s["app_pkg"], s["screen_id"]), len(rows), "emu"))
    print("emulator:", dict(stats), len(rows), "rows")
    return rows


def build_zflip() -> list[dict]:
    """Z Flip rows with Claude-written phrases. X (held-out app) rows go to split "diag" ONLY: they are never trained on
    and never written to any test_zflip* file (the Z Flip test uses the user's own phrases, test_user)."""
    zd = D / "zflip"
    screens = {s["screen_id"]: s for s in jl(zd / "screens.jsonl")}
    labels = {r["pid"]: r for r in jl(zd / "labels.jsonl")}
    # label-pass adjudications (students/verdict/label_pass.py apply) override, in name order like emulator/labels/zz_*
    for f in sorted(zd.glob("labels_adjudicated*.jsonl")):
        labels.update({r["pid"]: r for r in jl(f)})
    rows = []
    for p in jl(zd / "phrases.jsonl"):
        s, lab = screens.get(p["screen_id"]), labels.get(p["pid"])
        if s is None or lab is None or lab.get("drop"):
            continue
        split = "diag" if s["package"] in HELDOUT_PKGS else split_of(s["package"], s["screen_id"])
        rows.append(make_row(s, p, lab, split, len(rows), "zf"))
    return rows


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def code_hashes() -> dict:
    files = sorted((FT / "vox").glob("*.py"))
    per = {f.name: file_sha(f) for f in files}
    return {"vox_py_combined": hashlib.sha256("".join(f"{k}:{v}\n" for k, v in per.items()).encode()).hexdigest(), "vox_py": per}


def split_counts(rows: list[dict]) -> dict:
    return {"rows": len(rows), "screens": len({r["screen_id"] for r in rows}), "packages": len({r["package"] for r in rows}),
            "kinds": dict(sorted(Counter(r["kind"] for r in rows).items()))}


def input_files() -> list[Path]:
    """Every file the build reads: screens, phrase lists, label files (emulator v1 + v2, Z Flip)."""
    fs = [D / "emulator" / "screens.jsonl", D / "emulator" / "to_label.jsonl", V1 / "emulator" / "to_label.jsonl",
          V1 / "emulator" / "labels.jsonl", D / "zflip" / "screens.jsonl", D / "zflip" / "phrases.jsonl", D / "zflip" / "labels.jsonl"]
    fs += sorted((D / "emulator" / "labels").glob("*.jsonl"))
    fs += sorted((D / "zflip").glob("labels_adjudicated*.jsonl"))
    return [f for f in fs if f.exists()]


def write_manifest(out: Path, outputs: dict[str, list[dict]], argv: list[str], note: str = "") -> dict:
    """MANIFEST.json: sha256 + counts of every split file written, sha256 of every input/label file, hash of vox/*.py."""
    import datetime
    import sys
    man = {"built_at": datetime.datetime.now().isoformat(timespec="seconds"), "argv": argv or sys.argv, "note": note,
           "option_format": OPTION_FORMAT, "val_mode": VAL_MODE,
           "out_dir": rel(out) if out.is_relative_to(FT) else str(out),
           "splits": {k: {"sha256": file_sha(out / k), **split_counts(v)} for k, v in sorted(outputs.items())},
           "inputs": {rel(f): file_sha(f) for f in input_files()}, **code_hashes(),
           **({"folds_sha256": file_sha(out / "folds.json")} if (out / "folds.json").exists() else {})}
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    return man


def build_outputs(emu: list[dict], zf: list[dict]) -> dict[str, list[dict]]:
    """{relative file name: rows}. Z Flip-derived files stay under zflip/."""
    # exact captures: dev-test-exact (raw_devtest3) and the re-captured locked screens (raw_locked3) get their own files
    assert all(r["split"] == "test" for r in emu if r.get("exact_set") == "raw_devtest3"), "a dev-test-exact row outside the test split"
    ex_test = [r for r in emu if r.get("exact_set") == "raw_devtest3"]
    ex_locked = [r for r in emu if r.get("exact_set") == "raw_locked3"]
    emu = [r for r in emu if r.get("exact_set") not in ("raw_devtest3", "raw_locked3")]
    out = {"test_real_old.jsonl": [r for r in emu if r["split"] == "test" and r["extract"] == "pre-occlusion"]}
    if ex_test:
        out["test_exact.jsonl"] = ex_test
    for split in ("train", "val", "test"):
        e = [r for r in emu if r["split"] == split and (split != "test" or r["extract"] == "occlusion")]
        out[f"{split}_real.jsonl"] = e
        if split != "test":
            z = [r for r in zf if r["split"] == split]
            out[f"zflip/{split}_real_zflip.jsonl"] = z
            out[f"zflip/{split}_real_all.jsonl"] = e + z
    out["zflip/diag_x_opus.jsonl"] = [r for r in zf if r["split"] == "diag"]
    locked = [r for r in emu if r["split"] == "locked"]
    if locked:
        out["locked_test.jsonl"] = locked
    if ex_locked:
        assert all(r["split"] == "locked" for r in ex_locked), "a raw_locked3 screen outside LOCKED_PKGS"
        out["locked_test_exact.jsonl"] = ex_locked
    assert not any(r["split"] == "locked" for r in zf), "a Z Flip row in the locked test"
    for k, v in out.items():   # the seal: no locked-package row outside locked_test.jsonl
        if k not in ("locked_test.jsonl", "locked_test_exact.jsonl"):
            assert not any(r["package"] in LOCKED_PKGS for r in v), f"locked package in {k}"
    return out


def dumps_rows(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def cmd_build(a) -> None:
    """Build the splits into --out (default: the dataset root). Never silently overwrites: if any split file already
    exists with different content, the build refuses unless --overwrite, which first archives the old files (and the
    old MANIFEST.json) to <out>/archive/<timestamp>/."""
    import datetime
    import shutil
    import sys
    global VAL_MODE, OPTION_FORMAT
    out = Path(a.out) if a.out else D
    VAL_MODE = a.val_mode
    OPTION_FORMAT = a.option_format
    if OPTION_FORMAT != "v1" and out.resolve() == D.resolve():
        raise SystemExit("--option-format v2 builds go to a new --out dir")
    if VAL_MODE == "optset":
        scr = jl(D / "emulator" / "screens.jsonl") + (jl(D / "zflip" / "screens.jsonl") if (D / "zflip" / "screens.jsonl").exists() else [])
        _VAL_KEY.update(optset_val_keys(scr))
    emu = build_emulator()
    zf = build_zflip() if (D / "zflip" / "phrases.jsonl").exists() else []
    assert not any(r["split"] == "test" for r in zf)
    outputs = build_outputs(emu, zf)
    changed = [k for k, v in outputs.items() if (out / k).exists() and (out / k).read_text() != dumps_rows(v)]
    if VAL_MODE != "screen" and out.resolve() == D.resolve():
        raise SystemExit("--val-mode optset builds go to a new --out dir (the root keeps the v1a-v1e splits)")
    if changed and not a.overwrite:
        raise SystemExit(f"refusing to overwrite {len(changed)} split file(s) in {out} whose content would change "
                         f"({', '.join(changed)}). Build into a new --out dir, or pass --overwrite (archives the old files).")
    if changed:
        arc = out / "archive" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        for k in list(outputs) + ["MANIFEST.json"]:
            if (out / k).exists():
                (arc / k).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(out / k, arc / k)
        print(f"archived the previous split files to {arc}")
    if a.folds:
        outputs["folds.json"] = None
    for k, v in outputs.items():
        (out / k).parent.mkdir(parents=True, exist_ok=True)
        if k == "folds.json":
            continue
        wjl(out / k, v)
    if a.folds:   # leave-apps-out folds over every held-in app (train + val rows), balanced by rows, deterministic
        rows = [r for r in emu + zf if r["split"] in ("train", "val")]
        fam = {app: f for f, apps in APP_FAMILIES.items() for app in apps}
        n_fam = Counter(fam.get(r["app"], r["app"]) for r in rows)
        order = sorted(n_fam, key=lambda x: (-n_fam[x], hashlib.sha1(x.encode()).hexdigest()))
        load, ffold = [0] * a.folds, {}
        if a.folds_from:   # keep an earlier build's app -> fold map (so its cross-fits stay comparable); place new families only
            prev = json.loads(Path(a.folds_from).read_text())
            assert prev["k"] == a.folds, "--folds-from has a different k"
            for app, k in prev["fold"].items():
                ffold[fam.get(app, app)] = k
            for f in order:
                if f in ffold:
                    load[ffold[f]] += n_fam[f]
            order = [f for f in order if f not in ffold]
        for f in order:
            k = min(range(a.folds), key=lambda i: (load[i], i))
            ffold[f] = k
            load[k] += n_fam[f]
        fold = {app: ffold[fam.get(app, app)] for app in sorted({r["app"] for r in rows})}
        (out / "folds.json").write_text(json.dumps({"key": "app", "k": a.folds, "families": APP_FAMILIES, "rows_per_fold": load,
                                                    "fold": fold}, indent=1))
        del outputs["folds.json"]
    for k, v in outputs.items():
        print(f"{k}: {len(v)} rows; screens {len({r['screen_id'] for r in v})}; apps {len({r['package'] for r in v})}; "
              f"kinds {dict(Counter(r['kind'] for r in v))}")
    if not changed and (out / "MANIFEST.json").exists():
        old = json.loads((out / "MANIFEST.json").read_text())
        if {k: v["sha256"] for k, v in old["splits"].items()} == {k: file_sha(out / k) for k in outputs}:
            print("splits unchanged; MANIFEST.json kept")
            return
    man = write_manifest(out, outputs, sys.argv)
    print(f"MANIFEST.json written: {len(man['splits'])} split files, {len(man['inputs'])} input files, vox code {man['vox_py_combined'][:12]}")


def cmd_manifest(a) -> None:
    """(Re)write MANIFEST.json for split files already on disk (no rebuild): hashes and counts of what is there."""
    import sys
    out = Path(a.out) if a.out else D
    names = ["test_real_old.jsonl", "train_real.jsonl", "val_real.jsonl", "test_real.jsonl"] + \
            [f"zflip/{s}_real_{k}.jsonl" for s in ("train", "val") for k in ("zflip", "all")] + ["zflip/diag_x_opus.jsonl"]
    outputs = {n: jl(out / n) for n in names if (out / n).exists()}
    man = write_manifest(out, outputs, sys.argv, note=a.note)
    print(json.dumps({k: {"rows": v["rows"], "sha256": v["sha256"][:12]} for k, v in man["splits"].items()}, indent=1))


# --- training mix --------------------------------------------------------------------------------------------------------

def drop_gold(r: dict, rng: random.Random) -> dict | None:
    """A hard 'none' row: the phrase names an element that is removed from the list (with every acceptable one)."""
    none_i = len(r["options"]) - 1
    if r["label"] == none_i:
        return None
    rm = set(r["acceptable"]) - {none_i}
    keep = [i for i in range(none_i) if i not in rm]
    if len(keep) < 2:
        return None
    opts = [r["options"][i] for i in keep] + [NONE_OPTION]
    return {**r, "options": opts, "option_keys": [f"t{i}" for i in range(len(keep))] + ["none"], "label": len(keep),
            "acceptable": [len(keep)], "kind": "none_dropgold", "id": r["id"] + "-dg", "meta": {**r["meta"], "target": "none"}}


def cmd_mix(a) -> None:
    rng = random.Random(a.seed)
    real = jl(Path(a.real))
    out = []
    for r in real:
        out += [{**r, "id": f"{r['id']}-r{k}"} for k in range(a.real_rep)]
    if a.dropgold > 0:
        dg = [x for x in (drop_gold(r, rng) for r in real if rng.random() < a.dropgold) if x]
        out += dg
        print(f"drop-gold none rows: {len(dg)}")
    syn_f = Path(a.syn_file) if a.syn_file else SYN / "train.jsonl"
    syn = jl(syn_f)
    fmts = {r.get("option_format", "v1") for r in real} | {r.get("option_format", "v1") for r in syn[:1000]}
    if len(fmts) != 1:
        raise SystemExit(f"real and synthetic option formats differ ({sorted(fmts)}): pass a --syn-file of the same format")
    rng.shuffle(syn)
    none_syn = [r for r in syn if r["kind"] == "none"]
    act_syn = [r for r in syn if r["kind"] != "none"]
    n_none = int(a.syn * a.syn_none)
    pick = act_syn[: a.syn - n_none] + none_syn[:n_none]
    out += pick
    rng.shuffle(out)
    for r in out:
        if a.norm_caps:
            r["options"] = [norm_opt(o) for o in r["options"]]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    wjl(Path(a.out), out)
    side = {"args": {k: v for k, v in vars(a).items() if k != "func"}, "real_sha256": file_sha(Path(a.real)),
            "synthetic_file": rel(syn_f) if syn_f.resolve().is_relative_to(FT) else str(syn_f), "synthetic_sha256": file_sha(syn_f), "out_sha256": file_sha(Path(a.out)), "rows": len(out)}
    Path(a.out + ".mix.json").write_text(json.dumps(side, indent=1))
    k = Counter("none" if r["label"] == len(r["options"]) - 1 else "target" for r in out)
    print(f"{len(out)} rows -> {a.out}: real {len(real)} x{a.real_rep}, synthetic {len(pick)}; none share {k['none'] / len(out):.3f}")


def norm_opt(o: str) -> str:
    import re
    if o == NONE_OPTION:
        return o
    i = o.rfind(" (")
    lab, rest = (o[:i], o[i:]) if i > 0 else (o, "")
    lab = re.sub(r"\s+", " ", lab).strip()
    return re.sub(r"\b[A-Z][A-Z0-9&'-]{3,}\b", lambda m: m.group(0).capitalize(), lab) + rest


# --- score ---------------------------------------------------------------------------------------------------------------

THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]


def ece(conf: list[float], ok: list[bool], bins: int = 15) -> float:
    tot = 0.0
    for b in range(bins):
        idx = [i for i, c in enumerate(conf) if b / bins < c <= (b + 1) / bins or (b == 0 and c == 0)]
        if idx:
            tot += len(idx) / len(conf) * abs(sum(ok[i] for i in idx) / len(idx) - sum(conf[i] for i in idx) / len(idx))
    return round(tot, 4)


def score_preds(gold: list[dict], preds: dict[str, list[float]]) -> dict:
    rows = [(g, preds[g["id"]]) for g in gold if g["id"] in preds]
    groups = defaultdict(lambda: [0, 0, 0])
    conf, ok_g, ok_a, is_pn, is_gn = [], [], [], [], []
    none_n = none_hit = act_n = false_none = pred_none = 0
    for g, p in rows:
        top = max(range(len(p)), key=p.__getitem__)
        ni = len(g["options"]) - 1
        hg, ha = top == g["label"], top in g["acceptable"]
        conf.append(p[top]); ok_g.append(hg); ok_a.append(ha); pred_none += top == ni
        is_pn.append(top == ni); is_gn.append(g["label"] == ni)
        for k in ("all", f"kind:{g['kind']}", f"app:{g['app']}", f"source:{g['phrase_source']}"):
            groups[k][0] += 1; groups[k][1] += hg; groups[k][2] += ha
        if g["label"] == ni:
            none_n += 1; none_hit += top == ni
        else:
            act_n += 1; false_none += top == ni
    thr = {}
    for t in THRESHOLDS:
        cov = [i for i, c in enumerate(conf) if c >= t]
        thr[str(t)] = {"coverage": round(len(cov) / len(conf), 3),
                       "acc_covered": round(sum(ok_a[i] for i in cov) / len(cov), 3) if cov else None,
                       "acc_deferred": round(sum(ok_a[i] for i in range(len(conf)) if conf[i] < t) / max(1, len(conf) - len(cov)), 3),
                       "tap": {"n": sum(1 for i in cov if not is_pn[i]),
                               "acc": round(sum(ok_a[i] for i in cov if not is_pn[i]) / max(1, sum(1 for i in cov if not is_pn[i])), 3)},
                       "none": {"n": sum(1 for i in cov if is_pn[i]),
                                "acc": round(sum(ok_a[i] for i in cov if is_pn[i]) / max(1, sum(1 for i in cov if is_pn[i])), 3)},
                       "gold_none_tapped": round(sum(1 for i in cov if is_gn[i] and not is_pn[i]) / max(1, sum(is_gn)), 3)}
    return {"n": len(rows),
            "groups": {k: {"n": v[0], "acc_gold": round(v[1] / v[0], 3), "acc_acceptable": round(v[2] / v[0], 3)}
                       for k, v in sorted(groups.items())},
            "none_recall": round(none_hit / none_n, 3) if none_n else None, "false_none_rate": round(false_none / act_n, 3) if act_n else None,
            "pred_none_share": round(pred_none / max(1, len(rows)), 3), "ece_gold": ece(conf, ok_g), "ece_acceptable": ece(conf, ok_a), "thresholds": thr}


def none_bias(p: list[float], b: float) -> list[float]:
    """Add b to the none (last) logit: multiply its probability by e^b and renormalise (the app can do the same)."""
    q = p[:-1] + [p[-1] * math.exp(b)]
    s = sum(q)
    return [x / s for x in q]


def cmd_nonebias(a) -> None:
    """Fit the none-logit bias on a validation split: highest accuracy with none-recall >= floor."""
    gold = jl(Path(a.gold))
    raw = {r["id"]: r["probs"] for r in jl(Path(a.preds))}
    best = None
    for i in range(-60, 121):
        b = i / 20
        r = score_preds(gold, {k: none_bias(p, b) for k, p in raw.items()})
        acc, nr = r["groups"]["all"]["acc_gold"], r["none_recall"] or 0
        cand = (nr >= a.floor, acc, -abs(b))
        if best is None or cand > best[0]:
            best = (cand, b, acc, nr, r["false_none_rate"])
    print(json.dumps({"bias": best[1], "acc": best[2], "none_recall": best[3], "false_none": best[4], "meets_floor": best[0][0]}))


def cmd_score(a) -> None:
    gold = jl(Path(a.gold))
    out = {}
    for pf in a.preds:
        preds = {r["id"]: r["probs"] for r in jl(Path(pf))}
        if a.none_bias:
            preds = {k: none_bias(p, a.none_bias) for k, p in preds.items()}
        out[Path(pf).name] = score_preds(gold, preds)
        r = out[Path(pf).name]; g = r["groups"]["all"]
        print(f"{Path(pf).name}: n={r['n']} acc={g['acc_gold']} acc_acc={g['acc_acceptable']} ece={r['ece_gold']} "
              f"none_recall={r['none_recall']} false_none={r['false_none_rate']} "
              + " ".join(f"@{t}:{v['coverage']}/{v['acc_covered']}" for t, v in r["thresholds"].items()))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1))


def main() -> None:
    p = argparse.ArgumentParser()
    s = None
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("screens"); s.add_argument("--redraw", action="store_true")
    s = sub.add_parser("prompts"); s.add_argument("--n", type=int, default=8)
    s = sub.add_parser("phrases"); s.add_argument("--jobs", type=int, default=6); s.add_argument("--limit", type=int, default=0)
    s = sub.add_parser("tolabel"); s.add_argument("--per-batch", type=int, default=20)
    s = sub.add_parser("build"); s.add_argument("--out", default=""); s.add_argument("--overwrite", action="store_true")
    s.add_argument("--val-mode", choices=["screen", "optset"], default="screen"); s.add_argument("--folds", type=int, default=0)
    s.add_argument("--folds-from", default="", help="folds.json of an earlier build: keep its app -> fold map, place only new apps")
    s.add_argument("--option-format", choices=["v1", "v2"], required=True,
                   help="option text format of every row (OptionFormat.kt); explicit so no build mixes formats")
    s = sub.add_parser("manifest"); s.add_argument("--out", default=""); s.add_argument("--note", default="")
    s = sub.add_parser("mix"); s.add_argument("--real", required=True); s.add_argument("--out", required=True)
    s.add_argument("--real-rep", type=int, default=3); s.add_argument("--syn", type=int, default=12000)
    s.add_argument("--syn-none", type=float, default=0.12); s.add_argument("--dropgold", type=float, default=0.0)
    s.add_argument("--norm-caps", action="store_true"); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--syn-file", default="", help="synthetic rows (default data/targets-v2/train.jsonl, v1 text)")
    s = sub.add_parser("zscreens"); s.add_argument("--per-batch", type=int, default=6)
    sub.add_parser("zcollect")
    s = sub.add_parser("score"); s.add_argument("gold"); s.add_argument("preds", nargs="+"); s.add_argument("--out", default=""); s.add_argument("--none-bias", type=float, default=0.0)
    s = sub.add_parser("nonebias"); s.add_argument("gold"); s.add_argument("preds"); s.add_argument("--floor", type=float, default=0.8)
    a = p.parse_args()
    {"screens": cmd_screens, "prompts": cmd_prompts, "phrases": cmd_phrases, "tolabel": cmd_tolabel, "build": cmd_build, "manifest": cmd_manifest,
     "mix": cmd_mix, "score": cmd_score, "nonebias": cmd_nonebias, "zscreens": cmd_zscreens, "zcollect": cmd_zcollect}[a.cmd](a)


if __name__ == "__main__":
    main()
