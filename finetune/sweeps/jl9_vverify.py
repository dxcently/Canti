# Verdict bi: plain embed() vs fast_embed (length-sorted chunks) on real pool batches of 16 rows, eval mode (no dropout).
import sys, json, random, torch
sys.path.insert(0, '/home/khoa/VOX/finetune/students/verdict'); sys.path.insert(0, '/home/khoa/VOX/finetune/students')
import vlib
FT = '/home/khoa/VOX/finetune/'
m = vlib.Student(FT + 'students/verdict/runs/verdict-bi-targets-v2', 'bi', device='cuda')
m.eval(); m.enc.get_input_embeddings().weight.requires_grad_(False)
rows = [json.loads(x) for x in open(FT + 'data/real-targets-v2/b4a/zflip/aug/pool_nohidden_train.jsonl')]
random.seed(0); random.shuffle(rows)
def run(ch, fast, bf16):
    m.fast_embed = fast; m.zero_grad(set_to_none=True)
    with torch.autocast('cuda', dtype=torch.bfloat16, enabled=bf16):
        zs = m.logits(ch)
    loss = torch.stack([torch.nn.functional.cross_entropy(z.float()[None], torch.tensor([r['label']], device='cuda')) for z, r in zip(zs, ch)]).mean()
    loss.backward()
    g = torch.cat([p.grad.flatten() for p in m.parameters() if p.grad is not None])
    return [z.detach().float() for z in zs], g
res = {}
for name, cfgs in (("fp32_old_vs_fast", ((False, False), (True, False))), ("bf16_old_vs_fast", ((False, True), (True, True))),
                   ("old_bf16_vs_fp32", ((False, False), (False, True)))):
    md = 0.0; agree = tot = 0; gd = 0.0
    for bi in range(8):
        ch = rows[bi * 16:(bi + 1) * 16]
        (za, ga), (zb, gb) = run(ch, *cfgs[0]), run(ch, *cfgs[1])
        for a, b in zip(za, zb):
            md = max(md, float((a - b).abs().max())); agree += int(a.argmax() == b.argmax()); tot += 1
        gd = max(gd, float((ga - gb).norm() / ga.norm()))
    res[name] = {"max_abs_logit_diff": md, "argmax_agree": f"{agree}/{tot}", "grad_rel_l2_diff": gd}
print(json.dumps(res))
