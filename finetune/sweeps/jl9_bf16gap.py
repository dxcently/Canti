# Reference for jl9_cacheverify: the UNCACHED jevlike path's own bf16-vs-fp32 gap (batch 1, dev_test + test_old).
import sys, json, contextlib, torch
sys.path.insert(0, '/home/khoa/VOX/finetune/students/jevlike')
from suite_jl import suite, JLModel, FT
import train as jl
rows = suite.jl(FT / 'data/real-targets-v2/b4a/test_real.jsonl') + suite.jl(FT / 'data/real-targets-v2/b4a/test_real_old.jsonl')
m = JLModel(sys.argv[1], "cuda")
out = {}
for cache in (False, True):
    zb = m.logits(rows, bs=1, cache_options=cache)
    orig = torch.autocast
    torch.autocast = lambda *a, **k: contextlib.nullcontext()
    try:
        if cache: m.cache = jl.OptionCache(m.model, m.collate)
        zf = m.logits(rows, bs=1, cache_options=cache)
    finally:
        torch.autocast = orig
    if cache: m.cache = jl.OptionCache(m.model, m.collate)
    out["cached" if cache else "uncached"] = {"max_abs_logit_diff_bf16_vs_fp32": max(float((a - b).abs().max()) for a, b in zip(zb, zf)),
        "argmax_agree": f"{sum(int(a.argmax() == b.argmax()) for a, b in zip(zb, zf))}/{len(rows)}"}
print(json.dumps(out))
