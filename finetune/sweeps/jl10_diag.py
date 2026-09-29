"""jl10 step 1: why is J5c's none recall on dev_test (0.63) far below test_old (0.81)?
Reads suite.py's cached J5c predictions (3 seeds, stored T) and the b4a rows. Prints the gold-none breakdown by
set / app / screen tag / phrase kind / phrase source / extract, what J5c picks instead and at what confidence,
and gold-none rows that look like label noise (a listed option plausibly matches the phrase). Aggregates + public
emulator rows only (dev_test/test_old are emulator apps)."""
import json, glob, math, collections, re, sys
FT = "/home/khoa/VOX/finetune"
B = f"{FT}/data/real-targets-v2/b4a"
SEEDS = [7, 8, 9]
def jl(p): return [json.loads(l) for l in open(p)]
def sm(z, T):
    m = max(z); e = [math.exp((x - m) / T) for x in z]; s = sum(e); return [x / s for x in e]
Ts = {s: json.load(open(f"{FT}/sweeps/eval/seedpool.jl9-J5c-vs-J5b.json"))["T"][f"runs/jl9-J5b-e3-s{s}.pt"] for s in SEEDS}
out = {}
def words(s): return set(re.findall(r"[a-z0-9]+", s.lower())) - {"the","a","an","to","on","of","tap","open","go","button","my","me","and","for","in","it","that","this","one","thing","please","i","want","show","click","press","select"}
for sname, f in (("dev_test", "test_real"), ("test_old", "test_real_old")):
    rows = jl(f"{B}/{f}.jsonl")
    P = {}
    for s in SEEDS:
        (pp,) = glob.glob(f"{FT}/preds/real-targets-v2/suite/{sname}.jl9-J5b-e3-s{s}.pt.none.*.jsonl")
        for r in jl(pp):
            P.setdefault(r["id"], []).append(sm(r["logits"], Ts[s]))
    recs = []
    for r in rows:
        ps = P[r["id"]]; n = len(r["options"])
        p = [sum(q[i] for q in ps) / len(ps) for i in range(n)]
        ni = n - 1
        assert r["options"][ni].startswith("none of these")
        top = max(range(n), key=lambda i: p[i])
        # per-seed none hit, as the suite counts it (argmax per seed), averaged
        hit_seed = sum(max(range(n), key=lambda i: q[i]) == ni for q in ps) / len(ps)
        recs.append(dict(r=r, p=p, top=top, gn=r["label"] == ni, pnone=p[ni], ptop=p[top], hit=hit_seed, nopt=n - 1))
    gn = [x for x in recs if x["gn"]]
    print(f"\n=== {sname}: {len(rows)} rows, gold none {len(gn)}, none recall (seed-mean argmax) {sum(x['hit'] for x in gn)/len(gn):.3f}")
    def br(key, name):
        g = collections.defaultdict(list)
        for x in gn: g[key(x)].append(x["hit"])
        allg = collections.Counter(key(x) for x in recs)
        print(f"  by {name}: " + "; ".join(f"{k}: {sum(v)/len(v):.2f} ({len(v)} of {allg[k]})" for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))))
    br(lambda x: x["r"]["app"], "app")
    br(lambda x: x["r"]["tag"].split("/")[-1], "screen tag")
    br(lambda x: x["r"]["phrase_kind"], "phrase kind")
    br(lambda x: x["r"].get("confidence"), "label confidence")
    br(lambda x: "n<=5" if x["nopt"] <= 5 else "6-15" if x["nopt"] <= 15 else ">15", "option count")
    br(lambda x: x["r"]["screen_id"], "screen")
    miss = [x for x in gn if x["hit"] < 0.5]
    print(f"  missed (>=2 of 3 seeds pick a target): {len(miss)}; their top-target prob: median {sorted(x['ptop'] for x in miss)[len(miss)//2]:.2f}, "
          f">=0.8: {sum(x['ptop']>=0.8 for x in miss)}, p_none median {sorted(x['pnone'] for x in miss)[len(miss)//2]:.2f}")
    # label-noise check: phrase words overlapping the picked option's label
    print("  missed rows (id | phrase | picked option | p_top | p_none | word overlap | label note):")
    for x in sorted(miss, key=lambda x: -x["ptop"]):
        r = x["r"]; o = r["options"][x["top"]]
        ov = words(r["phrase"]) & words(o.split(" (")[0])
        print(f"   {r['id']} | {r['phrase']!r} | {o!r} | {x['ptop']:.2f} | {x['pnone']:.2f} | {sorted(ov)} | {r.get('label_note','')!r} | {r['screen_id']} | amb={r.get('ambiguous')} conf={r.get('confidence')}")
    # non-none rows: false none
    ng = [x for x in recs if not x["gn"]]
    print(f"  false none rate on target rows {sum(x['top']==len(x['p'])-1 for x in ng)/len(ng):.3f}; none share of rows {len(gn)/len(recs):.3f}")

# ---- part 2: composition of gold-none rows in every set, and val_all recall by group (private preds, aggregates only)
print("\n=== gold-none composition (phrase_kind!='none' = 'near-miss': the phrase was written for a target the labeller judged absent)")
for f in ("zflip/train_real_all", "zflip/val_real_all", "test_real", "test_real_old", "test_exact"):
    rows = jl(f"{B}/{f}.jsonl"); gn = [r for r in rows if r["label"] == len(r["options"]) - 1]
    nm = [r for r in gn if r["phrase_kind"] != "none"]
    amb = [r for r in gn if r.get("ambiguous") or r.get("confidence") in ("med", "low")]
    acc_t = [r for r in gn if len(r["acceptable"]) > 1]
    print(f"  {f}: rows {len(rows)}, gold none {len(gn)} ({len(gn)/len(rows):.3f}); near-miss {len(nm)} ({len(nm)/len(gn):.2f}); "
          f"ambiguous or med/low conf {len(amb)} ({len(amb)/len(gn):.2f}); acceptable also has a target {len(acc_t)}; "
          f"extract {dict(collections.Counter(r.get('extract') for r in gn))}")
rows = jl(f"{B}/zflip/val_real_all.jsonl")
P = {}
for s in SEEDS:
    (pp,) = glob.glob(f"{FT}/data/real-targets-v2/zflip/preds/suite/val_all.jl9-J5b-e3-s{s}.pt.none.*.jsonl")
    for r in jl(pp): P.setdefault(r["id"], []).append(sm(r["logits"], Ts[s]))
gn = [r for r in rows if r["label"] == len(r["options"]) - 1]
def hit(r): return sum(max(range(len(q)), key=lambda i: q[i]) == len(q) - 1 for q in P[r["id"]]) / 3
for name, key in (("extract", lambda r: r.get("extract")), ("conf", lambda r: r.get("confidence")), ("near-miss", lambda r: r["phrase_kind"] != "none"),
                  ("ambiguous", lambda r: bool(r.get("ambiguous")))):
    g = collections.defaultdict(list)
    for r in gn: g[key(r)].append(hit(r))
    print(f"  val_all none recall by {name}: " + "; ".join(f"{k}: {sum(v)/len(v):.2f} (n {len(v)})" for k, v in g.items()))
# dev_test / test_old: recall on 'clean' none rows (high conf, not ambiguous, phrase_kind none)
print("\n=== recall on clean gold-none rows (high confidence, not ambiguous, phrase_kind 'none')")
for sname, f in (("dev_test", "test_real"), ("test_old", "test_real_old")):
    rows = jl(f"{B}/{f}.jsonl"); P = {}
    for s in SEEDS:
        (pp,) = glob.glob(f"{FT}/preds/real-targets-v2/suite/{sname}.jl9-J5b-e3-s{s}.pt.none.*.jsonl")
        for r in jl(pp): P.setdefault(r["id"], []).append(sm(r["logits"], Ts[s]))
    gn = [r for r in rows if r["label"] == len(r["options"]) - 1]
    clean = [r for r in gn if r.get("confidence") == "high" and not r.get("ambiguous") and r["phrase_kind"] == "none"]
    rest = [r for r in gn if r not in clean]
    print(f"  {sname}: clean {sum(map(hit, clean))/len(clean):.3f} (n {len(clean)}), rest {sum(map(hit, rest))/len(rest):.3f} (n {len(rest)})")
