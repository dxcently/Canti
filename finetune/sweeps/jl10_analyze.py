import json
from collections import Counter
from vox import real_targets_v2 as r2

FILES = ["train_real.jsonl", "val_real.jsonl", "test_real.jsonl", "test_real_old.jsonl", "test_exact.jsonl",
         "zflip/train_real_all.jsonl", "zflip/val_real_all.jsonl", "zflip/train_real_zflip.jsonl",
         "zflip/val_real_zflip.jsonl", "zflip/diag_x_opus.jsonl"]
B = "data/real-targets-v2/b4a-v2i"

# collect rows and the screen_ids they reference
rows_by_file = {}
sids = set()
for f in FILES:
    rows = [json.loads(l) for l in open(f"{B}/{f}")]
    rows_by_file[f] = rows
    sids |= {r["screen_id"] for r in rows}

# load the screens
screens = {}
for src in ["data/real-targets-v2/emulator/screens.jsonl", "data/real-targets-v2/zflip/screens.jsonl"]:
    try:
        for line in open(src):
            d = json.loads(line)
            if d["screen_id"] in sids:
                screens[d["screen_id"]] = d
    except FileNotFoundError:
        pass
print("screens loaded:", len(screens), "of", len(sids))

# v2i and plain-v2 options per screen
def fmt_all(fmt):
    r2.OPTION_FORMAT = fmt
    r2._FMT_CACHE.clear()
    out = {}
    for sid, s in screens.items():
        out[sid] = r2.formatted(s)["options"]
    return out

v2i_opt = fmt_all("v2i")
v2_opt = fmt_all("v2")

def has_ctx(opts):
    return any(" · " in o for o in opts[:-1])

def indent_added(v2i, v2):
    n = 0
    for a, b in zip(v2i, v2):
        if " · " in a and " · " not in b:
            n += 1
    return n

def indent_ctxs(v2i, v2):
    out = []
    for a, b in zip(v2i, v2):
        if " · " in a and " · " not in b:
            out.append(a.split(" · ", 1)[1].rsplit(" (", 1)[0])
    return out

print("\nper split file:")
for f in FILES:
    rows = rows_by_file[f]
    gained = 0
    any_ctx = 0
    screens_indent = set()
    for r in rows:
        sid = r["screen_id"]
        v2i, v2 = v2i_opt[sid], v2_opt[sid]
        if indent_added(v2i, v2) > 0:
            gained += 1
            screens_indent.add(sid)
        if has_ctx(r["options"]):
            any_ctx += 1
    print(f"  {f}: rows={len(rows)} gained_indent={gained} any_context={any_ctx} distinct_screens_with_indent={len(screens_indent)}")

# top 10 indent context labels (across all distinct screens, counted once per option)
ctx_count = Counter()
for sid in screens:
    for c in indent_ctxs(v2i_opt[sid], v2_opt[sid]):
        ctx_count[c] += 1
print("\ntop 10 indent context labels (distinct screens):")
for c, n in ctx_count.most_common(10):
    print(f"  {n:4d}  {c!r}")

# test_exact: how many options differ from the app's own options_v2 text
print("\ntest_exact vs app options_v2:")
te_rows = rows_by_file["test_exact.jsonl"]
te_screens = {r["screen_id"] for r in te_rows}
n_diff_screens = 0
n_diff_options = 0
for sid in te_screens:
    s = screens[sid]
    app = s.get("options_v2")
    if app is None:
        continue
    v2i = v2i_opt[sid]
    d = sum(1 for a, b in zip(v2i, app) if a != b)
    if d:
        n_diff_screens += 1
        n_diff_options += d
print(f"  test_exact screens={len(te_screens)} screens_with_diff={n_diff_screens} total_options_diff={n_diff_options}")
