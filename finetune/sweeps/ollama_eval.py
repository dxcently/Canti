"""Score an Ollama-hosted model (default: DeepSeek V4.1 Flash on Ollama cloud) on the typed choice questions the
students answer, and compare it with jevlike and Verdict on the SAME rows.

Request (one per row): POST {endpoint}/api/chat, stream false, think false, temperature 0,
  system = the dataset's policy.txt, user = the row's context + its options as "key: text" lines,
  format = JSON schema {"choice": enum[option keys]}.
The API key is read from ~/.config/vox/ollama_key (never printed, logged or put on a command line). A LAN Ollama
needs no key: --endpoint http://host:11434 --no-key.

Row sets (fixed seed, ~1,550 calls in total):
  tv2-phrasing  targets-v2/test_unseen_phrasing, up to 80 rows per kind (population-weighted accuracy also reported)
  tv2-iid       targets-v2/test_iid, 100 random rows
  tv2-apps      targets-v2/test_unseen_apps, 100 random rows
  real-emu      a snapshot of real-targets-v1/test_emulator (preds/ollama/test_emulator.snapshot.jsonl), all rows
  v5-phrase     v5/test_unseen_phrasing, kinds phrase + screen_phrase, all rows
  real2-test / real2-test-old / real2-val   real-targets-v2 dev-test (new extraction), dev-test (pre-occlusion) and the
                emulator val, all rows (~1,059 calls). These read ONLY data/real-targets-v2/{test_real,test_real_old,val_real}.jsonl
                and pass a hard allowlist guard (real2_guard) before anything is sent.
Nothing under real-targets-v1/zflip/ or real-targets-v2/zflip/ is ever read (private phone data); rows are also checked before sending.

Answers are cached in preds/ollama/<set>.<tag>.jsonl, so a re-run only sends the rows still missing.

Usage:
  python sweeps/ollama_eval.py --dry-run                 # build the sample and print one request body (no network)
  python sweeps/ollama_eval.py --sets tv2-phrasing --limit 5
  python sweeps/ollama_eval.py                           # everything, then score -> sweeps/eval/ollama-<tag>.<set>.json
  python sweeps/ollama_eval.py --score-only
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vox.evaluate import score  # noqa: E402

KEY_FILE = Path.home() / ".config/vox/ollama_key"
DATA = ROOT / "data"
OUT_PREDS = ROOT / "preds/ollama"
OUT_EVAL = ROOT / "sweeps/eval"
SNAPSHOT = OUT_PREDS / "test_emulator.snapshot.jsonl"
SEED = 20260926
# On-phone budgets the app will use: a target pick may wait 2.5 s, anything else 1.5 s.
BUDGET_MS = {"target": 2500, "other": 1500}

# set -> (gold file, policy file, sampler, question kind, student preds {name: file})
SETS = {
    "tv2-phrasing": ("targets-v2/test_unseen_phrasing.jsonl", "targets-v2/policy.txt", ("per_kind", 80), "target", {
        "jevlike": "preds/sweep-targets-v2-e5-small-e3.test_unseen_phrasing.jsonl",
        "verdict": "preds/targets-v2/test_unseen_phrasing.verdict-bi-targets-v2.jsonl"}),
    "tv2-iid": ("targets-v2/test_iid.jsonl", "targets-v2/policy.txt", ("random", 100), "target", {
        "jevlike": "preds/sweep-targets-v2-e5-small-e3.test_iid.jsonl",
        "verdict": "preds/targets-v2/test_iid.verdict-bi-targets-v2.jsonl"}),
    "tv2-apps": ("targets-v2/test_unseen_apps.jsonl", "targets-v2/policy.txt", ("random", 100), "target", {
        "jevlike": "preds/sweep-targets-v2-e5-small-e3.test_unseen_apps.jsonl",
        "verdict": "preds/targets-v2/test_unseen_apps.verdict-bi-targets-v2.jsonl"}),
    "real-emu": (None, "targets-v2/policy.txt", ("all", 0), "target", {
        "jevlike": "preds/real-targets-v1/test_emulator.jevlike-targets-v2-e5-small-e3.jsonl",
        "verdict": "preds/real-targets-v1/test_emulator.verdict-bi-targets-v2.jsonl"}),
    "real2-test": ("real-targets-v2/test_real.jsonl", "targets-v2/policy.txt", ("all", 0), "target", {
        "verdict-v1d": "preds/real-targets-v2/test_real.verdict-bi-real-v1d.jsonl"}),
    "real2-test-old": ("real-targets-v2/test_real_old.jsonl", "targets-v2/policy.txt", ("all", 0), "target", {
        "verdict-v1d": "preds/real-targets-v2/test_real_old.verdict-bi-real-v1d.jsonl"}),
    "real2-val": ("real-targets-v2/val_real.jsonl", "targets-v2/policy.txt", ("all", 0), "target", {
        "verdict-v1d": "preds/real-targets-v2/val_real.verdict-bi-real-v1d.jsonl"}),
    "v5-phrase": ("v5/test_unseen_phrasing.jsonl", "v5/policy.txt", ("kinds", ("phrase", "screen_phrase")), "other", {
        "jevlike": "preds/sweep-v5-e5-small-e3.test_unseen_phrasing.jsonl",
        "verdict": "preds/v5/test_unseen_phrasing.verdict-bi-v5.jsonl"}),
}


def jl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def gold_path(name: str) -> Path:
    f = SETS[name][0]
    return SNAPSHOT if f is None else DATA / f


# Hard allowlist for the real2-* sets: the only files, packages and provenance that may be sent to the cloud.
REAL2_FILES = {"real-targets-v2/test_real.jsonl", "real-targets-v2/test_real_old.jsonl", "real-targets-v2/val_real.jsonl"}
EMULATOR_PKGS = frozenset("""ai.vox.companion ai.vox.fixture android app.organicmaps com.android.calendar com.android.contacts
com.android.deskclock com.android.dialer com.android.documentsui com.android.gallery3d com.android.launcher3 com.android.messaging
com.android.permissioncontroller com.android.settings com.android.systemui com.beemdevelopment.aegis com.best.deskclock
com.darshancomputing.BatteryIndicatorPro com.forrestguice.suntimeswidget com.fsck.k9 com.gh4a com.github.ashutoshgngwr.noice
com.github.libretube com.keylesspalace.tusky com.kunzisoft.keepass.libre com.nononsenseapps.feeder de.danoeh.antennapod
io.github.muntashirakon.AppManager me.hackerchick.catima me.zhanghai.android.files net.gsantner.markor org.breezyweather
org.chromium.webview_shell org.fdroid.fdroid org.fossify.calendar org.fossify.clock org.fossify.contacts org.fossify.filemanager
org.fossify.gallery org.fossify.math org.fossify.musicplayer org.fossify.notes org.fossify.paint org.fossify.phone
org.fossify.voicerecorder org.isoron.uhabits org.jellyfin.mobile org.joinmastodon.android org.kde.kdeconnect_tp
org.mozilla.fennec_fdroid org.oxycblt.auxio org.schabi.newpipe org.secuso.privacyfriendlynotes org.secuso.privacyfriendlytodolist
org.tasks org.videolan.vlc org.wikipedia""".split())
# Emulator screenshot dirs. real-targets-v1/emulator/ is the first emulator harvest (same emulator; DeepSeek phrased those screens).
EMULATOR_MARKS = ("data/real-targets-v2/emulator/", "data/real-targets-v1/emulator/")


def real2_guard(rows: list[dict], path: Path) -> None:
    """Abort (never skip) unless EVERY row is an emulator row with DeepSeek phrases. Z Flip rows can never pass."""
    rel = str(path.relative_to(DATA)) if path.is_relative_to(DATA) else str(path)
    if rel not in REAL2_FILES or "zflip" in str(path):
        raise SystemExit(f"real2 guard: {path} is not an allowlisted file")
    for r in rows:
        bad = []
        if r.get("package") not in EMULATOR_PKGS: bad.append("package")
        if r.get("phrase_source") != "deepseek-v4-pro": bad.append("phrase_source")
        if not str(r.get("marks", "")).startswith(EMULATOR_MARKS) or "zflip" in str(r.get("marks", "")): bad.append("marks")
        if not str(r.get("screen_id", "")).startswith("emu"): bad.append("screen_id")
        if "serial" in r or any(k.startswith("zf") for k in r) or "-zf-" in str(r.get("id", "")) or "zflip" in json.dumps(r): bad.append("zflip/serial")
        if r.get("options_source", "tree") != "tree": bad.append("options_source")
        if bad:
            raise SystemExit(f"real2 guard: row {r.get('id')} fails {bad}; aborting before any request")


def assert_not_private(r: dict, path: Path) -> None:
    blob = " ".join(str(r.get(k, "")) for k in ("split", "screenshot", "marks", "id"))
    if "zflip" in str(path) or "zflip" in blob:
        raise SystemExit(f"refusing to send a private (zflip) row: {r.get('id')}")


def sample(name: str) -> list[dict]:
    path = gold_path(name)
    rows = jl(path)
    how, arg = SETS[name][2]
    rng = random.Random(f"{SEED}:{name}")
    if how == "all":
        out = rows
    elif how == "random":
        out = rng.sample(rows, min(arg, len(rows)))
    elif how == "kinds":
        out = [r for r in rows if r["kind"] in arg]
    else:  # per_kind
        by = defaultdict(list)
        for r in rows:
            by[r["kind"]].append(r)
        out = [r for k in sorted(by) for r in rng.sample(by[k], min(arg, len(by[k])))]
    for r in out:
        assert_not_private(r, path)
    if name.startswith("real2-"):
        real2_guard(rows, path)   # the whole file, not only the sample
    return out


def user_message(r: dict) -> str:
    lines = [f"{k}: {o}" for k, o in zip(r["option_keys"], r["options"])]
    return r["context"] + "\n\noptions (answer with the key before the colon):\n" + "\n".join(lines)


def request_body(r: dict, policy: str, model: str, think) -> dict:
    return {
        "model": model,
        "stream": False,
        "think": think,
        "options": {"temperature": 0},
        "format": {"type": "object", "properties": {"choice": {"type": "string", "enum": list(r["option_keys"])}},
                   "required": ["choice"]},
        "messages": [{"role": "system", "content": policy}, {"role": "user", "content": user_message(r)}],
    }


def read_key() -> str:
    if not KEY_FILE.exists():
        raise SystemExit(f"{KEY_FILE} is missing: create it (one line, mode 600) and re-run")
    mode = stat.S_IMODE(KEY_FILE.stat().st_mode)
    if mode & 0o077:
        print(f"warning: {KEY_FILE} is mode {oct(mode)}, expected 0o600", file=sys.stderr)
    key = KEY_FILE.read_text().strip()
    if not key:
        raise SystemExit(f"{KEY_FILE} is empty")
    return key


class Client:
    def __init__(self, endpoint: str, key: str | None, timeout: float) -> None:
        self.url = endpoint.rstrip("/") + "/api/chat"
        self._headers = {"Content-Type": "application/json"}
        if key:
            self._headers["Authorization"] = "Bearer " + key
        self.timeout = timeout
        self.gate = threading.Lock()
        self.pause_until = 0.0

    def post(self, body: dict) -> tuple[int, dict | str]:
        """-> (status, parsed json | short error text). Never includes request headers in any message."""
        data = json.dumps(body).encode()
        for attempt in range(6):
            with self.gate:
                wait = self.pause_until - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(self.url, data=data, headers=self._headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")[:300]
                if e.code in (429, 502, 503) and attempt < 5:
                    ra = e.headers.get("Retry-After")
                    delay = float(ra) if ra and ra.replace(".", "").isdigit() else 2.0 * 2 ** attempt
                    with self.gate:
                        self.pause_until = max(self.pause_until, time.monotonic() + delay)
                    continue
                return e.code, text
        return 429, "rate limited after retries"


ECHO = re.compile(r'^"?([A-Za-z0-9_]+)"?\s*:\s*(.+?)\.?$')


def parse_choice(content: str, keys: list[str], options: list[str]) -> tuple[str | None, str]:
    """-> (key or None, how). Strict: the answer must name exactly one option.
    json    {"choice": k} (what the schema asks for) or a JSON string "k"
    bare    k. Ollama cloud's deepseek-v4.1-flash (2026-09) ignores `format` and usually answers with the bare key
    echo    "k: <the start of option k's text>", the option line copied back (one line, the text must match option k)
    Anything else (prose, unknown keys, a key with other text) is None. OllamaClient.parseChoice in the app is the same."""
    s = content.strip()
    try:
        v = json.loads(s)
    except Exception:
        v = None
    if isinstance(v, dict):
        v = v.get("choice")
    if isinstance(v, str):
        return (v.strip(), "json") if v.strip() in keys else (None, "invalid")
    if s in keys:
        return s, "bare"
    m = ECHO.match(s) if "\n" not in s else None
    if m and m.group(1) in keys:
        text = options[keys.index(m.group(1))].lower()
        if text.startswith(m.group(2).strip().lower()):
            return m.group(1), "echo"
    return None, "invalid"


def ask(client: Client, r: dict, policy: str, model: str, think) -> dict:
    body = request_body(r, policy, model, think)
    t0 = time.monotonic()
    out = {"id": r["id"], "think": think}
    try:
        code, res = client.post(body)
    except TimeoutError:
        code, res = -1, "timeout"
    except (urllib.error.URLError, OSError) as e:
        code, res = -1, ("timeout" if "timed out" in str(e) else f"{type(e).__name__}: {str(e)[:120]}")
    out["latency_ms"] = round((time.monotonic() - t0) * 1000)
    if code != 200 or not isinstance(res, dict):
        out["error"] = f"http {code}: {res}" if code != -1 else str(res)
        return out
    content = (res.get("message") or {}).get("content", "")
    out["raw"] = content[:200]
    out["tokens"] = {"prompt": res.get("prompt_eval_count"), "eval": res.get("eval_count")}
    out["server_ms"] = round(res["total_duration"] / 1e6) if res.get("total_duration") else None
    choice, how = parse_choice(content, r["option_keys"], r["options"])
    if choice is None:
        out["error"] = "invalid choice"
        return out
    out["parse"] = how
    out["choice"] = choice
    out["probs"] = [1.0 if k == choice else 0.0 for k in r["option_keys"]]
    return out


def pick_think(client: Client, row: dict, policy: str, model: str) -> object:
    """think false if the model accepts it, else the lowest level it takes."""
    for think in (False, "low"):
        res = ask(client, row, policy, model, think)
        if "error" not in res or not res["error"].startswith("http 400"):
            print(f"think={think!r}: {res.get('error') or 'ok'} in {res['latency_ms']} ms")
            return think
        print(f"think={think!r} rejected: {res['error'][:160]}")
    raise SystemExit("the model accepts neither think=false nor think='low'")


def run(names: list[str], a) -> None:
    key = None if a.no_key else read_key()
    client = Client(a.endpoint, key, a.timeout)
    first = sample(names[0])[0]
    think = pick_think(client, first, (DATA / SETS[names[0]][1]).read_text().strip(), a.model)
    for name in names:
        policy = (DATA / SETS[name][1]).read_text().strip()
        rows = sample(name)[: a.limit or None]
        cache = OUT_PREDS / f"{name}.{a.tag}.jsonl"
        done = {r["id"] for r in jl(cache)} if cache.exists() else set()
        todo = [r for r in rows if r["id"] not in done]
        print(f"{name}: {len(rows)} rows, {len(done)} cached, {len(todo)} to send")
        lock = threading.Lock()
        n_err = 0
        with open(cache, "a") as f, ThreadPoolExecutor(max_workers=a.jobs) as ex:
            for i, res in enumerate(ex.map(lambda r: ask(client, r, policy, a.model, think), todo), 1):
                with lock:
                    f.write(json.dumps(res) + "\n")
                    f.flush()
                n_err += "error" in res
                if i % 50 == 0 or i == len(todo):
                    print(f"  {name} {i}/{len(todo)} errors={n_err}", flush=True)


# --- scoring ----------------------------------------------------------------------------------------------------------

def pct(xs: list[float], q: float):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else None


def real_groups(gold: dict[str, dict], preds: dict[str, dict]) -> dict:
    """vox.real_targets cmd_score, restricted to the rows in `preds`: accuracy vs gold and vs the acceptable set."""
    res = defaultdict(lambda: [0, 0, 0])
    none_n = none_hit = false_none = act_n = 0
    for i, g in gold.items():
        if i not in preds:
            continue
        p = preds[i]["probs"]
        top = max(range(len(p)), key=p.__getitem__)
        hg, ha = top == g["label"], top in g["acceptable"]
        none_idx = len(g["options"]) - 1
        for k in ("all", f"kind:{g['phrase_kind']}", f"source:{g['phrase_source']}", f"conf:{g['confidence']}",
                  "ambiguous" if g["ambiguous"] else "unambiguous"):
            res[k][0] += 1
            res[k][1] += hg
            res[k][2] += ha
        if g["label"] == none_idx:
            none_n += 1
            none_hit += top == none_idx
        else:
            act_n += 1
            false_none += top == none_idx
    return {"groups": {k: {"n": v[0], "acc_gold": round(v[1] / v[0], 3), "acc_acceptable": round(v[2] / v[0], 3)}
                       for k, v in sorted(res.items())},
            "none_recall": round(none_hit / none_n, 3) if none_n else None,
            "false_none_rate": round(false_none / act_n, 3) if act_n else None}


def reparse(p: dict, g: dict) -> dict:
    """Apply the current parser to a cached raw answer (the first run only accepted json/bare answers)."""
    if p.get("error") not in ("invalid choice", "unparseable") or "raw" not in p:
        return p
    choice, how = parse_choice(p["raw"], g["option_keys"], g["options"])
    if choice is None:
        return {**p, "error": "invalid choice"}
    q = {k: v for k, v in p.items() if k != "error"}
    return {**q, "choice": choice, "parse": how, "probs": [1.0 if k == choice else 0.0 for k in g["option_keys"]]}


def score_set(name: str, a) -> dict | None:
    cache = OUT_PREDS / f"{name}.{a.tag}.jsonl"
    if not cache.exists():
        return None
    rows = sample(name)
    gold_all = {r["id"]: r for r in jl(gold_path(name))}
    cloud_all = {r["id"]: reparse(r, gold_all[r["id"]]) for r in jl(cache) if r["id"] in gold_all}
    gold = {r["id"]: r for r in rows if r["id"] in cloud_all}
    budget = BUDGET_MS[SETS[name][3]]
    cloud_ok = {i: p for i, p in cloud_all.items() if i in gold and "probs" in p}
    students = {m: {r["id"]: r for r in jl(ROOT / f)} for m, f in SETS[name][4].items()}
    for m, s in students.items():   # same rows, same option order, or the comparison is void
        bad = [i for i in gold if i not in s or len(s[i]["probs"]) != len(gold[i]["options"])]
        if bad:
            raise SystemExit(f"{name}: {m} preds do not cover/align with {len(bad)} rows (e.g. {bad[0]})")
    fbm = "jevlike" if "jevlike" in students else next(iter(students))
    # What the phone would do: the cloud answer if it came back valid within budget, else the local model's answer.
    fb = {i: (cloud_ok[i] if i in cloud_ok and cloud_all[i]["latency_ms"] <= budget else
              {**students[fbm][i], "fallback": True}) for i in gold}
    models = {f"ollama-{a.tag}": cloud_ok, f"ollama-{a.tag}+{fbm}-fallback@{budget}ms": fb, **students}
    out: dict = {"set": name, "gold": str(gold_path(name).relative_to(ROOT)), "rows_in_file": len(gold_all),
                 "rows_scored": len(gold), "sample": SETS[name][2], "model": a.model, "endpoint": a.endpoint,
                 "kinds_in_sample": dict(Counter(g["kind"] for g in gold.values())), "models": {}}
    for m, p in models.items():
        out["models"][m] = score(gold, p)
        if name == "real-emu" or name.startswith("real2-"):
            out["models"][m]["real"] = real_groups(gold, p)
    if SETS[name][2][0] == "per_kind":   # re-weight the per-kind sample to the file's kind mix
        mix = Counter(r["kind"] for r in gold_all.values())
        tot = sum(mix.values())
        for m, r in out["models"].items():
            r["accuracy_population_weighted"] = round(sum(mix[k] / tot * v for k, v in r["by_kind"].items()), 4)
    calls = [cloud_all[i] for i in gold]
    lat = [c["latency_ms"] for c in calls if "error" not in c]
    lat_all = [c["latency_ms"] for c in calls]
    errs = Counter(c["error"].split(":")[0] if c["error"].startswith("http") else c["error"] for c in calls if "error" in c)
    toks_p = [c["tokens"]["prompt"] or 0 for c in calls if c.get("tokens")]
    toks_e = [c["tokens"]["eval"] or 0 for c in calls if c.get("tokens")]
    out["cloud_calls"] = {
        "n": len(calls), "ok": len(lat), "error_rate": round(1 - len(lat) / max(len(calls), 1), 4), "errors": dict(errs),
        "latency_ms_p50": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95), "latency_ms_max": max(lat_all, default=None),
        "server_ms_p50": pct([c["server_ms"] for c in calls if c.get("server_ms")], 0.5),
        "budget_ms": budget, "within_budget_rate": round(sum(c["latency_ms"] <= budget and "error" not in c for c in calls)
                                                         / max(len(calls), 1), 4),
        "fallback_rate": round(sum("fallback" in v for v in fb.values()) / max(len(fb), 1), 4),
        "tokens_prompt_total": sum(toks_p), "tokens_eval_total": sum(toks_e),
        "tokens_prompt_mean": round(sum(toks_p) / max(len(toks_p), 1), 1),
        "tokens_eval_mean": round(sum(toks_e) / max(len(toks_e), 1), 1),
        "think": calls[0].get("think") if calls else None,
        "parse": dict(Counter(c.get("parse", "json/bare (run 1)") for c in calls if "error" not in c)),
    }
    dest = OUT_EVAL / f"ollama-{a.tag}.{name}.json"
    dest.write_text(json.dumps(out, indent=1))
    return out


def summary(results: dict[str, dict], tag: str) -> None:
    print("| set | n | model | acc | acc (pop.) | none-recall/FT | missed | p50 ms | p95 ms | err | in budget |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, r in results.items():
        c = r["cloud_calls"]
        for m, s in r["models"].items():
            cloud = m == f"ollama-{tag}"
            acc = s["real"]["groups"]["all"]["acc_gold"] if "real" in s else round(s["accuracy"], 3)
            if "real" in s:
                acc = f"{acc} / {s['real']['groups']['all']['acc_acceptable']} acc."
            print(f"| {name} | {s['n']} | {m} | {acc} | {s.get('accuracy_population_weighted', '')} | "
                  f"{1 - s['false_trigger_rate']:.3f} | {s['missed_command_rate']:.3f} | "
                  f"{c['latency_ms_p50'] if cloud else ''} | {c['latency_ms_p95'] if cloud else ''} | "
                  f"{c['error_rate'] if cloud else ''} | {c['within_budget_rate'] if cloud else ''} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", nargs="+", default=list(SETS), choices=list(SETS))
    ap.add_argument("--endpoint", default="https://ollama.com")
    ap.add_argument("--model", default="deepseek-v4.1-flash")
    ap.add_argument("--tag", default="dsv41flash")
    ap.add_argument("--no-key", action="store_true", help="LAN Ollama: send no Authorization header")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=20.0, help="per-call client timeout, seconds (eval only)")
    ap.add_argument("--limit", type=int, default=0, help="first N sampled rows per set (smoke test)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--score-only", action="store_true")
    a = ap.parse_args()
    a.jobs = min(a.jobs, 4)
    if a.dry_run:
        total = 0
        for n in a.sets:
            rows = sample(n)
            total += len(rows)
            print(f"{n}: {len(rows)} rows, kinds {dict(Counter(r['kind'] for r in rows))}")
        print(f"total calls: {total}")
        r = sample(a.sets[0])[0]
        print(json.dumps(request_body(r, (DATA / SETS[a.sets[0]][1]).read_text().strip(), a.model, False), indent=1))
        return
    OUT_PREDS.mkdir(parents=True, exist_ok=True)
    if not a.score_only:
        run(a.sets, a)
    results = {n: r for n in a.sets if (r := score_set(n, a))}
    summary(results, a.tag)


if __name__ == "__main__":
    main()
