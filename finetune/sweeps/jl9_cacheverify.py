# jevlike OptionCache vs the uncached forward: same checkpoint, dev_test + test_old rows, batch 1 (the phone's case) and 64.
import sys, json, torch
sys.path.insert(0, '/home/khoa/VOX/finetune/students/jevlike')
import suite_jl
from suite_jl import suite, JLModel, FT
ck = sys.argv[1]
rows = suite.jl(FT / 'data/real-targets-v2/b4a/test_real.jsonl') + suite.jl(FT / 'data/real-targets-v2/b4a/test_real_old.jsonl')
res = {}
for dev, bf16, n in (("cuda", True, len(rows)), ("cuda", False, len(rows)), ("cpu", False, 120)):
    torch.set_num_threads(8)
    m = JLModel(ck, dev)
    R = rows[:n]
    for bs in (1, 64):
        def run(cache):
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=bf16):
                if cache:
                    m.cache = __import__('train').OptionCache(m.model, m.collate)
                    return m.logits(R, bs=bs, cache_options=True)
                # uncached path; logits() autocasts on cuda itself, so for fp32 call the model directly
                if dev == "cuda" and not bf16:
                    out = []
                    with torch.no_grad(), torch.autocast("cuda", enabled=False):
                        for i in range(0, len(R), bs):
                            ch = R[i:i + bs]
                            b = {k: v.to(m.device) for k, v in m.collate([suite_jl.jl.validate(r) for r in ch]).items()}
                            z = m.model(b).float()
                            out += [z[j, :len(r["options"])].cpu() for j, r in enumerate(ch)]
                    return out
                return m.logits(R, bs=bs)
        if dev == "cuda" and not bf16:   # the cached path autocasts inside JLModel.logits too: disable for fp32
            import contextlib
            orig = torch.autocast
            torch.autocast = lambda *a, **k: contextlib.nullcontext()
            try:
                za, zb = run(False), run(True)
            finally:
                torch.autocast = orig
        else:
            za, zb = run(False), run(True)
        md = max(float((a - b).abs().max()) for a, b in zip(za, zb))
        ag = sum(int(a.argmax() == b.argmax()) for a, b in zip(za, zb))
        pd = max(float((a.softmax(-1) - b.softmax(-1)).abs().max()) for a, b in zip(za, zb))
        res[f"{dev}{'_bf16' if bf16 else '_fp32'}_bs{bs}"] = {"rows": len(R), "max_abs_logit_diff": md, "max_abs_prob_diff": pd, "argmax_agree": f"{ag}/{len(R)}"}
        print(json.dumps({f"{dev}{'_bf16' if bf16 else '_fp32'}_bs{bs}": res[f"{dev}{'_bf16' if bf16 else '_fp32'}_bs{bs}"]}), flush=True)
    del m
(FT / 'sweeps/logs/jl9-cache-verify.json').write_text(json.dumps({"checkpoint": ck, **res}, indent=1))
