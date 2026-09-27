"""Real-screen test set for intent cursor mode: data/real-targets-v1 (see its README.md).

Stages (run from finetune/):
  screens   raw emulator captures (android/suite/harvest_real.py) -> the kept screen list + set-of-marks images
  prompts   one DeepSeek prompt per kept emulator screen (text only: app, screen line, visible texts, options)
  phrases   run the prompts through `eidolon run -m ollama:deepseek-v4-pro` (never Z Flip content)
  build     screens + phrases + labels (+ heldout/user_phrasings.md rows) -> test_emulator.jsonl (targets-v2 schema)
  review    review.html: a random 15% of rows with marks, phrase, gold, acceptable set, note, agree/disagree
  score     accuracy vs gold and vs the acceptable set, none-recall, by kind/app/source, failures

`screens` and `review` draw images and need Pillow, which the training venv does not have:
  nix shell --impure --expr 'with import <nixpkgs> {}; python313.withPackages (p: [p.pillow])' -c python3 -m vox.real_targets screens
The other stages are stdlib only.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import json
import random
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

NONE_OPTION = "none of these (the thing I named is not on screen)"
DATA = Path(__file__).resolve().parents[1] / "data" / "real-targets-v1"
HELDOUT = Path(__file__).resolve().parents[1] / "heldout" / "user_phrasings.md"
PHRASE_MODEL = "ollama:deepseek-v4-pro"   # DeepSeek V4 Pro; the deepseek: route has no key on this box (README)
KINDS = ["name", "position", "function", "appearance", "casual", "none"]

# Which packages a walk's screen may legitimately be in (anything else means the walk lost its app: dropped).
ALLOWED = {"launcher": {"com.android.launcher3", "com.android.systemui"}, "files": {"com.android.documentsui", "android"},
           "fixture": {"ai.vox.fixture"}, "newpipe": {"org.schabi.newpipe"}, "vlc": {"org.videolan.vlc"},
           "organicmaps": {"app.organicmaps"}, "gallery": {"org.fossify.gallery"}, "fennec": {"org.mozilla.fennec_fdroid"},
           "settings": {"com.android.settings", "com.android.settings.intelligence", "com.android.permissioncontroller"}, "clock": {"com.android.deskclock"}, "contacts": {"com.android.contacts"},
           "dialer": {"com.android.dialer"}, "messages": {"com.android.messaging"}, "calendar": {"com.android.calendar"},
           "gallery3d": {"com.android.gallery3d"}, "browser": {"org.chromium.webview_shell"}, "camera": {"com.android.camera2"},
           "vox": {"ai.vox.companion"}}
# Hand exclusions after looking at the screenshots: reason per screen.
EXCLUDE = {"emu-calendar-11": "tree changed during capture (stable=false) and the new-event screen did not open"}


def jl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def wjl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# --- screens + marks ------------------------------------------------------------------------------------------------------

def keep_screens(raw: list[dict]) -> tuple[list[dict], dict[str, str]]:
    kept, dropped, seen = [], {}, {}
    for r in raw:
        sid = r["screen_id"]
        sig = (r["package"], tuple(r["options"]), r["screen_text"] if len(r["options"]) > 1 else "")
        if sid in EXCLUDE:
            dropped[sid] = EXCLUDE[sid]
        elif r["package"] not in ALLOWED.get(r["app"], {r["package"]}):
            dropped[sid] = f"walk left the app (package {r['package']})"
        elif r.get("duplicate_of") or sig in seen:
            dropped[sid] = f"same options and screen line as {r.get('duplicate_of') or seen[sig]}"
        else:
            seen[sig] = sid
            kept.append(r)
    return kept, dropped


PALETTE = [(230, 25, 75), (0, 130, 200), (60, 180, 75), (245, 130, 48), (145, 30, 180), (0, 128, 128),
           (240, 50, 230), (128, 0, 0), (0, 0, 128), (128, 128, 0)]


def draw_marks(png: Path, bounds: list, out: Path, screen_w: int = 1080) -> None:
    """Numbered boxes (option index) on a copy of the screenshot. Bounds are in screen pixels; the PNG may be scaled."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(png).convert("RGB")
    scale = im.width / screen_w
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font = ImageFont.load_default(size=max(22, int(34 * im.width / 1080)))
    boxes = [(i, [int(v * scale) for v in b]) for i, b in enumerate(bounds) if b]
    for i, (x1, y1, x2, y2) in boxes:
        c = PALETTE[i % len(PALETTE)]
        k = 2 if x2 - x1 > 6 and y2 - y1 > 6 else 0
        d.rectangle([x1 + k, y1 + k, max(x2 - k, x1 + k), max(y2 - k, y1 + k)], outline=c + (255,), width=5)
    for i, (x1, y1, x2, y2) in boxes:   # tags last, so no box is drawn over a number
        c = PALETTE[i % len(PALETTE)]
        t = str(i)
        tw, th = d.textbbox((0, 0), t, font=font)[2:]
        tx, ty = x1 + 4, y1 + 4
        d.rectangle([tx, ty, tx + tw + 10, ty + th + 8], fill=c + (235,))
        d.text((tx + 5, ty + 2), t, fill=(255, 255, 255, 255), font=font)
    Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB").save(out, optimize=True)


def cmd_screens(a) -> None:
    raw_dir = DATA / "emulator" / "raw"
    kept, dropped = keep_screens(jl(raw_dir / "screens.jsonl"))
    (DATA / "emulator" / "marks").mkdir(parents=True, exist_ok=True)
    out = []
    for r in kept:
        m = DATA / "emulator" / "marks" / f"{r['screen_id']}.png"
        if not m.exists() or a.redraw:
            draw_marks(raw_dir / r["screenshot"], r["bounds"], m)
        out.append({k: r[k] for k in ("screen_id", "tag", "app", "package", "app_name", "state_template", "screen_text",
                                      "options", "bounds", "stable", "step")}
                   | {"screenshot": f"emulator/raw/{r['screenshot']}", "marks": f"emulator/marks/{r['screen_id']}.png",
                      "texts": (r.get("summary") or {}).get("texts", [])})
    wjl(DATA / "emulator" / "screens.jsonl", out)
    (DATA / "emulator" / "dropped_screens.json").write_text(json.dumps(dropped, indent=1))
    print(f"kept {len(out)} screens over {len({r['app'] for r in out})} apps; dropped {len(dropped)}")
    print(Counter(r["app"] for r in out))


# --- phrases (DeepSeek, text only) ------------------------------------------------------------------------------------------

PROMPT = """You are helping build a test set for a hands-free phone controller. The user looks at their phone screen and
SAYS OUT LOUD which on-screen element they want to tap. A model then has to pick that element from a list.

Below is one real Android screen: the app, a one-line summary, some text visible on it, and the list of tappable
elements the model will choose from, written as "label (kind, position)". Position is a 3x3 grid of the screen.
Labels are raw accessibility labels, so some are odd (ids, "unlabeled", a letter). You cannot see the screen.

App: {app}
Screen summary: {screen}
Visible text (partial): {texts}
Elements:
{options}

Write {n} different things a real person might naturally SAY to pick an element on this screen. Spread them over
these kinds (use each kind at most twice, and include at least one "none"):
- "name": the element by its name or a synonym ("hit settings", "the wifi one")
- "position": only where it is, no name ("the thing in the top right corner", "second row")
- "function": what it does, without its name ("the one that makes a new alarm", "go back")
- "appearance": what it probably looks like: an icon shape, a toggle, a plus sign, a big round button
- "casual": indirect or chatty, how people actually talk ("uh can you open the bluetooth stuff", "that one, the menu")
- "none": something plausible for this app that is NOT in the element list (the right answer is "none of these")
Speech only: short, spoken, lower case is fine, no quotes inside, no element numbers. Do not copy the labels
verbatim every time; real people paraphrase. Vary sentence shape.

Answer with only a JSON array, no prose, like:
[{{"phrase": "...", "kind": "name", "intended": 3}}, {{"phrase": "...", "kind": "none", "intended": "none"}}]
where "intended" is the element number you meant (0-based, as listed) or "none"."""


def prompt_for(s: dict, n: int = 5) -> str:
    opts = "\n".join(f"{i}. {o}" for i, o in enumerate(s["options"][:-1])) or "(no tappable elements)"
    texts = "; ".join(t for t in s.get("texts", [])[:20]) or "(none)"
    return PROMPT.format(app=f"{s['app_name']} ({s['package']})", screen=s["screen_text"].removeprefix("screen: "),
                         texts=texts, options=opts, n=n)


def cmd_prompts(a) -> None:
    screens = jl(DATA / "emulator" / "screens.jsonl")
    pdir = DATA / "emulator" / "prompts"
    pdir.mkdir(exist_ok=True)
    for s in screens:
        (pdir / f"{s['screen_id']}.txt").write_text(prompt_for(s, a.n))
    print(f"{len(screens)} prompts -> {pdir}")


def run_eidolon(prompt: str, cwd: Path) -> tuple[str, str]:
    """-> (stdout answer, session path). Runs in an empty dir; the prompt forbids tools. Verifies the session's model."""
    r = subprocess.run(["eidolon", "run", "-m", PHRASE_MODEL, "--cwd", str(cwd), prompt], capture_output=True, text=True,
                       timeout=600, stdin=subprocess.DEVNULL)
    m = re.search(r"session: (\S+\.eid)", r.stderr)
    sess = m.group(1) if m else ""
    if sess:
        log = subprocess.run(["eidolon", "log", "--json", sess], capture_output=True, text=True).stdout
        models = set(re.findall(r'"SessionStart":\{"model":"([^"]+)"', log)) | set(re.findall(r'"model":"([^"]+)"', log))
        # a fallback shows up as an event key (e.g. "ModelFallback": ...); screen text in the prompt may contain the word
        if any(m_ != PHRASE_MODEL for m_ in models) or re.search(r'"[A-Za-z_]*[Ff]allback[A-Za-z_]*":', log):
            raise RuntimeError(f"session {sess} did not stay on {PHRASE_MODEL}: {models}")
    return r.stdout.strip(), sess


def parse_phrases(txt: str) -> list[dict]:
    t = txt[txt.find("["): txt.rfind("]") + 1]
    arr = json.loads(t)
    return [x for x in arr if isinstance(x, dict) and x.get("phrase")]


def cmd_phrases(a) -> None:
    screens = jl(DATA / "emulator" / "screens.jsonl")
    out_p = DATA / "emulator" / "phrases.jsonl"
    done = {r["screen_id"] for r in jl(out_p)}
    todo = [s for s in screens if s["screen_id"] not in done][: a.limit or None]
    cwd = DATA / "emulator" / ".eidolon-cwd"
    cwd.mkdir(exist_ok=True)

    def one(s):
        p = (DATA / "emulator" / "prompts" / f"{s['screen_id']}.txt").read_text()
        for attempt in range(3):
            try:
                txt, sess = run_eidolon(p, cwd)
                return s, parse_phrases(txt), sess, txt
            except (json.JSONDecodeError, ValueError, subprocess.TimeoutExpired) as e:
                err = e
        return s, None, "", f"failed: {err}"

    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for s, ph, sess, txt in ex.map(one, todo):
            if ph is None:
                print(f"  {s['screen_id']}: {txt}")
                continue
            with out_p.open("a") as f:
                f.write(json.dumps({"screen_id": s["screen_id"], "model": PHRASE_MODEL, "session": sess, "phrases": ph,
                                    "raw": txt}, ensure_ascii=False) + "\n")
            print(f"  {s['screen_id']}: {len(ph)} phrases")


# --- user phrasings ------------------------------------------------------------------------------------------------------

def user_rows() -> list[dict]:
    """`screen_id | phrase` lines in the "E." section of heldout/user_phrasings.md (template lines ignored)."""
    if not HELDOUT.exists():
        return []
    txt = HELDOUT.read_text()
    i = txt.find("## E.")
    if i < 0:
        return []
    out = []
    for line in txt[i:].splitlines():
        m = re.match(r"^\s*[-*]?\s*((?:emu|zf)[\w-]+)\s*\|\s*(.+?)\s*$", line)
        if m and not m.group(2).startswith("<"):
            out.append({"screen_id": m.group(1), "phrase": m.group(2).strip().strip('"')})
    return out


def pid(screen_id: str, source: str, phrase: str) -> str:
    """Stable phrase id (labels are keyed on it)."""
    import hashlib
    return f"{screen_id}:{source[:2]}:{hashlib.sha1(phrase.lower().encode()).hexdigest()[:8]}"


def cmd_tolabel(a) -> None:
    """The phrase list to label: one line per phrase with its stable id (DeepSeek + user)."""
    screens = {s["screen_id"]: s for s in jl(DATA / "emulator" / "screens.jsonl")}
    labels = {r["pid"] for r in jl(DATA / "emulator" / "labels.jsonl")}
    rows = []
    for r in jl(DATA / "emulator" / "phrases.jsonl"):
        for p in r["phrases"]:
            rows.append({"pid": pid(r["screen_id"], "deepseek-v4-pro", p["phrase"]), "screen_id": r["screen_id"],
                         "phrase": p["phrase"], "phrase_kind": p.get("kind"), "intended": p.get("intended"),
                         "phrase_source": "deepseek-v4-pro"})
    for u in user_rows():
        if u["screen_id"] in screens:
            rows.append({"pid": pid(u["screen_id"], "user", u["phrase"]), **u, "phrase_kind": "user", "intended": None,
                         "phrase_source": "user"})
    todo = [r for r in rows if r["pid"] not in labels]
    wjl(DATA / "emulator" / "to_label.jsonl", rows)
    print(f"{len(rows)} phrases, {len(todo)} unlabelled")


# --- build ---------------------------------------------------------------------------------------------------------------

def cmd_build(a) -> None:
    screens = {s["screen_id"]: s for s in jl(DATA / "emulator" / "screens.jsonl")}
    labels = {r["pid"]: r for r in jl(DATA / "emulator" / "labels.jsonl")}
    rows, dropped, unlabelled = [], [], 0
    for p in jl(DATA / "emulator" / "to_label.jsonl"):
        lab = labels.get(p["pid"])
        if lab is None:
            unlabelled += 1
            continue
        if lab.get("drop"):
            dropped.append({**p, "drop_reason": lab.get("reason", "")})
            continue
        s = screens[p["screen_id"]]
        keys = [f"t{i}" for i in range(len(s["options"]) - 1)] + ["none"]
        gold = len(keys) - 1 if lab["gold"] == "none" else int(lab["gold"])
        acc = sorted({len(keys) - 1 if x == "none" else int(x) for x in (lab.get("acceptable") or [lab["gold"]])} | {gold})
        rows.append({
            "context": s["state_template"].replace("{UTTERANCE}", p["phrase"]),
            "options": s["options"], "label": gold, "option_keys": keys,
            # kind: "none" iff gold is none; a phrase written as "none" whose gold is an element is "near_none"
            "kind": "none" if keys[gold] == "none" else
                    ("near_none" if p["phrase_kind"] == "none" else (p["phrase_kind"] or "user")),
            "meta": {"target": keys[gold], "pid": p["pid"]},
            "id": f"real-emu-{len(rows)}", "split": "test_emulator",
            "screen_id": s["screen_id"], "app": s["app"], "package": s["package"], "tag": s["tag"],
            "screenshot": s["screenshot"], "marks": s["marks"], "bounds": s["bounds"],
            "phrase": p["phrase"], "phrase_source": p["phrase_source"], "phrase_kind": p["phrase_kind"],
            "phrase_intended": p.get("intended"), "gold": lab["gold"], "acceptable": acc,
            "ambiguous": bool(lab.get("ambiguous")), "confidence": lab.get("confidence", "high"),
            "label_note": lab.get("note", ""), "options_source": "tree",
        })
    wjl(DATA / "test_emulator.jsonl", rows)
    wjl(DATA / "emulator" / "dropped_rows.jsonl", dropped)
    print(f"{len(rows)} rows -> test_emulator.jsonl; {len(dropped)} dropped; {unlabelled} unlabelled")


# --- review sheet --------------------------------------------------------------------------------------------------------

def cmd_review(a) -> None:
    from io import BytesIO
    from PIL import Image
    rows = jl(DATA / a.split)
    rng = random.Random(a.seed)
    sample = rng.sample(rows, max(1, round(len(rows) * a.frac)))
    cache: dict[str, str] = {}

    def img(rel: str) -> str:
        if rel not in cache:
            im = Image.open(DATA / rel).convert("RGB")
            im.thumbnail((430, 960))
            b = BytesIO()
            im.save(b, "JPEG", quality=72)
            cache[rel] = base64.b64encode(b.getvalue()).decode()
        return cache[rel]

    items = []
    for r in sample:
        items.append({"id": r["meta"]["pid"], "screen": r["screen_id"], "app": r["app"], "phrase": r["phrase"],
                      "source": r["phrase_source"], "kind": r["phrase_kind"], "img": r["marks"],
                      "options": r["options"], "gold": r["label"], "acceptable": r["acceptable"],
                      "ambiguous": r["ambiguous"], "confidence": r["confidence"], "note": r["label_note"]})
    imgs = {it["img"]: img(it["img"]) for it in items}
    html = REVIEW_HTML.replace("__ITEMS__", json.dumps(items, ensure_ascii=False)).replace("__IMGS__", json.dumps(imgs)) \
        .replace("__TITLE__", f"{a.split} spot check ({len(items)} of {len(rows)} rows)")
    out = DATA / a.out
    out.write_text(html)
    print(f"{len(items)} rows -> {out}")


REVIEW_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Real targets review</title>
<style>
:root{--bg:#f6f6f4;--card:#fff;--ink:#1b1b1b;--mut:#666;--line:#ddd;--gold:#0b7a3b;--acc:#8a6d00;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161616;--card:#222;--ink:#eee;--mut:#aaa;--line:#3a3a3a;--gold:#5fd08e;--acc:#e5c55a;--bad:#ff8a80}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;z-index:2}
h1{font-size:17px;margin:0 0 4px}.mut{color:var(--mut);font-size:13px}
main{max-width:1100px;margin:0 auto;padding:12px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0;display:grid;grid-template-columns:minmax(0,430px) 1fr;gap:16px}
@media (max-width:760px){.card{grid-template-columns:1fr}}
img{width:100%;height:auto;border-radius:6px;border:1px solid var(--line)}
.phrase{font-size:19px;font-weight:600;margin:4px 0 8px}
ol{padding-left:0;list-style:none;margin:6px 0;font-size:13.5px}
li{padding:2px 6px;border-radius:4px}li.g{background:color-mix(in srgb,var(--gold) 18%,transparent);font-weight:600}
li.a{background:color-mix(in srgb,var(--acc) 16%,transparent)}
.btns button{font:inherit;padding:6px 14px;margin-right:6px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.btns button.on.ok{background:var(--gold);color:#fff}.btns button.on.no{background:var(--bad);color:#fff}
textarea{width:100%;box-sizing:border-box;margin-top:6px;font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px}
</style></head><body>
<header><h1>__TITLE__</h1><div class="mut">Green = my gold, amber = also acceptable. Numbers on the image are option indices. Your marks are saved in this browser (localStorage). <span id="tally"></span> <button id="exp">Copy results as JSON</button></div></header>
<main id="m"></main>
<script>
const ITEMS=__ITEMS__, IMGS=__IMGS__, KEY="vox-real-targets-review";
let st={};try{st=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}tally()}
function tally(){const v=Object.values(st);document.getElementById("tally").textContent=`agree ${v.filter(x=>x.v==="ok").length} · disagree ${v.filter(x=>x.v==="no").length} · of ${ITEMS.length}`}
const m=document.getElementById("m");
ITEMS.forEach(it=>{const c=document.createElement("div");c.className="card";
const opts=it.options.map((o,i)=>`<li class="${i===it.gold?"g":it.acceptable.includes(i)?"a":""}">${i===it.options.length-1?"none":i}. ${o.replace(/</g,"&lt;")}</li>`).join("");
c.innerHTML=`<div><img loading="lazy" src="data:image/jpeg;base64,${IMGS[it.img]}" alt="${it.screen}"></div><div>
<div class="mut">${it.screen} · ${it.app} · ${it.source} / ${it.kind} · conf ${it.confidence}${it.ambiguous?" · ambiguous":""}</div>
<div class="phrase">“${it.phrase.replace(/</g,"&lt;")}”</div>
<div><b>Gold:</b> ${it.gold===it.options.length-1?"none":it.gold} &nbsp; <b>Acceptable:</b> ${it.acceptable.map(i=>i===it.options.length-1?"none":i).join(", ")}</div>
<div class="mut">${(it.note||"").replace(/</g,"&lt;")}</div><ol>${opts}</ol>
<div class="btns"><button class="ok">Agree</button><button class="no">Disagree</button></div>
<textarea rows="2" placeholder="What should it be?"></textarea></div>`;
const [ok,no]=c.querySelectorAll("button"),ta=c.querySelector("textarea");
const paint=()=>{const s=st[it.id]||{};ok.classList.toggle("on",s.v==="ok");no.classList.toggle("on",s.v==="no");ok.classList.add("ok");no.classList.add("no");ta.value=s.n||""};
ok.onclick=()=>{st[it.id]={...(st[it.id]||{}),v:"ok"};save();paint()};no.onclick=()=>{st[it.id]={...(st[it.id]||{}),v:"no"};save();paint()};
ta.oninput=()=>{st[it.id]={...(st[it.id]||{}),n:ta.value};save()};paint();m.appendChild(c)});
document.getElementById("exp").onclick=()=>{const t=JSON.stringify(st,null,1);navigator.clipboard?.writeText(t).then(()=>alert("Copied"),()=>prompt("Copy:",t))};
tally();
</script></body></html>"""


# --- Z Flip (private: everything stays under zflip/, which is gitignored; no external model ever sees it) --------------

ZF = DATA / "zflip"
POSITIONS = ["top left", "top", "top right", "left", "center", "right", "bottom left", "bottom", "bottom right"]


def _clean(s: str) -> str:
    t = re.sub(r"\s+", " ", s).strip()
    return t if len(t) <= 60 else t[:57].rstrip() + "..."   # Targets.kt MAX_LABEL_CHARS


def vision_options(items: list[tuple[str, str, list[int]]], w: int = 1080, h: int = 2640) -> tuple[list[str], list]:
    """(label, role, bounds) -> (options, bounds) exactly as Targets.kt orders them: 3x3 cell, then top, then left;
    duplicate option strings dropped; capped at 39 + none."""
    found = []
    for lab, role, b in items:
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        cell = min(max(cy * 3 // h, 0), 2) * 3 + min(max(cx * 3 // w, 0), 2)
        found.append((cell, b, f"{_clean(lab)} ({role}, {POSITIONS[cell]})"))
    found.sort(key=lambda t: (t[0] // 3, t[0] % 3, t[1][1], t[1][0]))
    seen, opts, bounds = set(), [], []
    for _, b, o in found:
        if o not in seen:
            seen.add(o)
            opts.append(o)
            bounds.append(b)
    return opts[:39] + [NONE_OPTION], bounds[:39] + [None]


def parse_spec(path: Path) -> list[dict]:
    screens, cur = [], None
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("= "):
            sid, app_name, pkg, screen, desc = [x.strip() for x in line[2:].split("|")]
            cur = {"screen_id": sid, "app_name": app_name, "package": pkg, "screen_text": f"screen: {screen}",
                   "description": desc, "items": []}
            screens.append(cur)
        else:
            lab, role, b = [x.strip() for x in line.rsplit("|", 2)]
            cur["items"].append((lab, role, [int(v) for v in b.split()]))
    return screens


def cmd_zflip_vision(a) -> None:
    """zflip/vision/spec.txt (my option lists from the user's screenshots) -> screens.jsonl, marks, phrases_pending.json."""
    vdir = ZF / "vision"
    (vdir / "marks").mkdir(parents=True, exist_ok=True)
    out = []
    for s in parse_spec(vdir / "spec.txt"):
        opts, bounds = vision_options(s["items"])
        sid = s["screen_id"]
        draw_marks(ZF / "user_screens" / f"{sid}.png", bounds, vdir / "marks" / f"{sid}.png", screen_w=1080)
        app = {"YouTube Music": "ytmusic", "YouTube": "youtube"}.get(s["app_name"], s["app_name"].lower())
        out.append({"screen_id": sid, "app": app, "app_name": s["app_name"], "package": s["package"],
                    "screen_text": s["screen_text"], "description": s["description"],
                    "state_template": f"mode: cursor\napp: {s['app_name']} ({s['package']})\n{s['screen_text']}\n"
                                      "spoken target: \"{UTTERANCE}\"",
                    "options": opts, "bounds": bounds, "options_source": "vision", "screen_size": [1080, 2640],
                    "screenshot": f"zflip/user_screens/{sid}.png", "marks": f"zflip/vision/marks/{sid}.png"})
    wjl(vdir / "screens.jsonl", out)
    pending = [{"screen_id": s["screen_id"], "description": s["description"], "options": s["options"]}
               for s in out if not any(u["screen_id"] == s["screen_id"] for u in user_rows())]
    (ZF / "phrases_pending.json").write_text(json.dumps(pending, indent=1, ensure_ascii=False))
    print(f"{len(out)} vision screens; {sum(len(s['options']) - 1 for s in out)} options; {len(pending)} awaiting phrases")


def cmd_zflip_build(a) -> None:
    """User phrases (heldout/user_phrasings.md, section E) + my labels -> test_zflip_vision.jsonl / test_zflip.jsonl.
    Labels: zflip/labels.jsonl, one {"pid", "gold", "acceptable", "ambiguous", "confidence", "note"} (or "drop") per phrase.
    Phrases to label are listed in zflip/to_label.jsonl."""
    vis = {s["screen_id"]: s for s in jl(ZF / "vision" / "screens.jsonl")}
    tree = {s["screen_id"]: s | {"marks": f"zflip/raw/marks/{s['screen_id']}.png",
                                 "screenshot": f"zflip/raw/{s['screenshot']}"} for s in jl(ZF / "raw" / "screens.jsonl")}
    labels = {r["pid"]: r for r in jl(ZF / "labels.jsonl")}
    todo, sets = [], {"test_zflip_vision": [], "test_zflip": []}
    for u in user_rows():
        s = vis.get(u["screen_id"]) or tree.get(u["screen_id"])
        if s is None:
            continue
        p = pid(u["screen_id"], "user", u["phrase"])
        lab = labels.get(p)
        todo.append({"pid": p, **u, "labelled": lab is not None})
        if lab is None or lab.get("drop"):
            continue
        split = "test_zflip_vision" if u["screen_id"] in vis else "test_zflip"
        keys = [f"t{i}" for i in range(len(s["options"]) - 1)] + ["none"]
        gold = len(keys) - 1 if lab["gold"] == "none" else int(lab["gold"])
        acc = sorted({len(keys) - 1 if x == "none" else int(x) for x in (lab.get("acceptable") or [lab["gold"]])} | {gold})
        rows = sets[split]
        rows.append({"context": s["state_template"].replace("{UTTERANCE}", u["phrase"]), "options": s["options"],
                     "label": gold, "option_keys": keys, "kind": "none" if keys[gold] == "none" else "user",
                     "meta": {"target": keys[gold], "pid": p}, "id": f"real-{split[5:]}-{len(rows)}", "split": split,
                     "screen_id": s["screen_id"], "app": s["app"], "package": s["package"],
                     "screenshot": s["screenshot"], "marks": s["marks"], "bounds": s["bounds"], "phrase": u["phrase"],
                     "phrase_source": "user", "phrase_kind": "user", "gold": lab["gold"], "acceptable": acc,
                     "ambiguous": bool(lab.get("ambiguous")), "confidence": lab.get("confidence", "high"),
                     "label_note": lab.get("note", ""), "options_source": s.get("options_source", "tree")})
    wjl(ZF / "to_label.jsonl", todo)
    for split, rows in sets.items():
        wjl(ZF / f"{split}.jsonl", rows)
        print(f"{split}: {len(rows)} rows")
    print(f"{len(todo)} user phrases on Z Flip screens, {sum(not t['labelled'] for t in todo)} unlabelled")


def cmd_zflip_marks(a) -> None:
    """Marks for the phone tree captures (zflip/raw/marks/<id>.png)."""
    raw = ZF / "raw"
    (raw / "marks").mkdir(exist_ok=True)
    n = 0
    for s in jl(raw / "screens.jsonl"):
        m = raw / "marks" / f"{s['screen_id']}.png"
        if not m.exists() or a.redraw:
            draw_marks(raw / s["screenshot"], s["bounds"], m, screen_w=s["screen_size"][0])
            n += 1
    print(f"{n} marks drawn")


# --- score ---------------------------------------------------------------------------------------------------------------

def cmd_score(a) -> None:
    gold = {r["id"]: r for r in jl(Path(a.gold))}
    out = {}
    for pf in a.preds:
        preds = {r["id"]: r for r in jl(Path(pf))}
        rows = [(g, preds[i]) for i, g in gold.items() if i in preds]
        res = defaultdict(lambda: [0, 0, 0])   # key -> [n, hit_gold, hit_acceptable]
        fails = []
        none_n = none_hit = false_none = act_n = 0
        for g, p in rows:
            top = max(range(len(p["probs"])), key=p["probs"].__getitem__)
            hg, ha = top == g["label"], top in g["acceptable"]
            none_idx = len(g["options"]) - 1
            for k in ("all", f"kind:{g['phrase_kind']}", f"app:{g['app']}", f"source:{g['phrase_source']}",
                      f"conf:{g['confidence']}", "ambiguous" if g["ambiguous"] else "unambiguous"):
                res[k][0] += 1
                res[k][1] += hg
                res[k][2] += ha
            if g["label"] == none_idx:
                none_n += 1
                none_hit += top == none_idx
            else:
                act_n += 1
                false_none += top == none_idx
            if not ha:
                fails.append({"id": g["id"], "screen": g["screen_id"], "phrase": g["phrase"], "kind": g["phrase_kind"],
                              "gold": g["options"][g["label"]], "pred": g["options"][top], "conf": round(p["probs"][top], 3)})
        name = Path(pf).name
        out[name] = {"n": len(rows), "groups": {k: {"n": v[0], "acc_gold": round(v[1] / v[0], 3),
                                                    "acc_acceptable": round(v[2] / v[0], 3)} for k, v in sorted(res.items())},
                     "none_recall": round(none_hit / none_n, 3) if none_n else None, "none_n": none_n,
                     "false_none_rate": round(false_none / act_n, 3) if act_n else None, "failures": fails}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    for name, r in out.items():
        g = r["groups"]["all"]
        print(f"{name}: n={r['n']} acc_gold={g['acc_gold']} acc_acceptable={g['acc_acceptable']} "
              f"none_recall={r['none_recall']} false_none={r['false_none_rate']}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("screens"); s.add_argument("--redraw", action="store_true")
    s = sub.add_parser("prompts"); s.add_argument("--n", type=int, default=6)
    s = sub.add_parser("phrases"); s.add_argument("--jobs", type=int, default=6); s.add_argument("--limit", type=int, default=0)
    sub.add_parser("tolabel")
    sub.add_parser("build")
    s = sub.add_parser("review"); s.add_argument("--split", default="test_emulator.jsonl"); s.add_argument("--out", default="review.html")
    s.add_argument("--frac", type=float, default=0.15); s.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("score"); s.add_argument("gold"); s.add_argument("preds", nargs="+"); s.add_argument("--out", required=True)
    sub.add_parser("zflip-vision")
    sub.add_parser("zflip-build")
    s = sub.add_parser("zflip-marks"); s.add_argument("--redraw", action="store_true")
    a = p.parse_args()
    {"screens": cmd_screens, "prompts": cmd_prompts, "phrases": cmd_phrases, "tolabel": cmd_tolabel, "build": cmd_build,
     "review": cmd_review, "score": cmd_score, "zflip-vision": cmd_zflip_vision, "zflip-build": cmd_zflip_build,
     "zflip-marks": cmd_zflip_marks}[a.cmd](a)


if __name__ == "__main__":
    main()
