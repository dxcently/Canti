# Where a Verdict bi training step's time goes (teacher recipe, 16-row batches of the pool, bf16): tokenisation (CPU),
# encoder forward, per-row python loss, backward + optimizer, and the per-row .item() syncs of the logging.
import sys, json, time, random, torch
sys.path.insert(0, '/home/khoa/VOX/finetune/students/verdict'); sys.path.insert(0, '/home/khoa/VOX/finetune/students')
import vlib
FT = '/home/khoa/VOX/finetune/'
m = vlib.Student(FT + 'students/verdict/runs/verdict-bi-targets-v2', 'bi', device='cuda'); m.train()
m.enc.get_input_embeddings().weight.requires_grad_(False)
opt = torch.optim.AdamW([p for p in m.parameters() if p.requires_grad], lr=1e-6)
rows = [json.loads(x) for x in open(FT + 'data/real-targets-v2/b4a/zflip/aug/pool_nohidden_train.jsonl')]
random.seed(0); random.shuffle(rows)
sync = torch.cuda.synchronize
for fast in (False, True):
    m.fast_embed = fast
    T = {"tokenize_cpu": 0.0, "forward": 0.0, "loss_python": 0.0, "backward_step": 0.0, "item_syncs": 0.0}
    n = 60
    for s in range(n + 5):
        ch = rows[s * 16:(s + 1) * 16]
        sync(); t0 = time.perf_counter()
        m.tok([m.q_prefix + r["context"] for r in ch], truncation=True, max_length=512)   # tokenisation cost alone
        uniq = list(dict.fromkeys(o for r in ch for o in r["options"])); m.tok([m.p_prefix + o for o in uniq], truncation=True, max_length=64)
        t1 = time.perf_counter()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            zs = m.logits(ch)
        sync(); t2 = time.perf_counter()
        loss = torch.stack([torch.nn.functional.cross_entropy(z.float()[None], torch.tensor([r["label"]], device="cuda")) for z, r in zip(zs, ch)]).sum() / 16
        sync(); t3 = time.perf_counter()
        opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_([p for p in m.parameters() if p.requires_grad], 1.0); opt.step()
        sync(); t4 = time.perf_counter()
        _ = loss.item(); _ = sum(int(z.argmax().item() == r["label"]) for z, r in zip(zs, ch))
        t5 = time.perf_counter()
        if s >= 5:
            for k, a, b in (("tokenize_cpu", t0, t1), ("forward", t1, t2), ("loss_python", t2, t3), ("backward_step", t3, t4), ("item_syncs", t4, t5)):
                T[k] += (b - a) * 1000 / n
    tot = sum(T.values())
    print(json.dumps({"fast_embed": fast, "ms_per_step": {k: round(v, 2) for k, v in T.items()}, "total_ms": round(tot, 1),
                      "rows_per_s_equiv": round(16000 / tot, 1)}))
