"""Export a Verdict student run to ONNX (fp32 + dynamic int8), self-contained per arch:

  bi     <run>/onnx/encoder.onnx         (input_ids, attention_mask) -> embedding [B, 384], mean-pooled + L2-normalised.
         Score = 20 * embedding(query) . embedding(option) / T; option embeddings can be precomputed once.
  cross  <run>/onnx/cross.onnx           (input_ids, attention_mask) of "query: ctx </s></s> passage: opt" pairs
         -> logit [B]. Softmax over one row's K pairs / T.
  cross_cos <run>/onnx/cross_cos.onnx (input_ids, attention_mask, opt_mask) of the same pairs -> logit [B]
         (20 * cos of the context-span and option-span mean pools; opt_mask = tokenizer sequence_ids == 1).

Both come with *_int8.onnx (onnxruntime quantize_dynamic, QInt8 weights). Needs onnx + onnxruntime only (no optimum).

    python students/verdict/export_onnx.py students/verdict/runs/verdict-bi-smoke
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch
import vlib


class BiWrap(torch.nn.Module):
    def __init__(self, enc):
        super().__init__(); self.enc = enc

    def forward(self, input_ids, attention_mask):
        h = self.enc(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        return torch.nn.functional.normalize(vlib.mean_pool(h, attention_mask), dim=-1)


class CrossWrap(torch.nn.Module):
    def __init__(self, enc, head):
        super().__init__(); self.enc = enc; self.head = head

    def forward(self, input_ids, attention_mask):
        h = self.enc(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        return self.head(vlib.mean_pool(h, attention_mask)).squeeze(-1)


class CrossCosWrap(torch.nn.Module):
    def __init__(self, enc):
        super().__init__(); self.enc = enc

    def forward(self, input_ids, attention_mask, opt_mask):
        h = self.enc(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        return vlib.span_cos(h, attention_mask, opt_mask)


def export(run: str):
    import json
    meta = json.loads((Path(run) / "student.json").read_text())
    arch = meta["arch"]
    m = vlib.Student(run, arch, device="cpu").eval()
    m.enc.config._attn_implementation = "eager"   # plain matmul attention exports cleanly
    # eval: export restores the wrapper's mode (train would enable dropout)
    wrap = {"bi": lambda: BiWrap(m.enc), "cross": lambda: CrossWrap(m.enc, m.head), "cross_cos": lambda: CrossCosWrap(m.enc)}[arch]().eval()
    name = {"bi": "encoder", "cross": "cross", "cross_cos": "cross_cos"}[arch]
    out = Path(run) / "onnx"; out.mkdir(exist_ok=True)
    pair = arch != "bi"
    b = m.tok(["query: hello world"], ["passage: tap the screen"] if pair else None, return_tensors="pt")
    names = ["input_ids", "attention_mask"]
    args = [b["input_ids"], b["attention_mask"]]
    if arch == "cross_cos":
        names.append("opt_mask"); args.append(torch.tensor([[int(s == 1) for s in b.sequence_ids(0)]]))
    f32 = out / f"{name}.onnx"
    dyn = {n: {0: "b", 1: "t"} for n in names}; dyn["out"] = {0: "b"}
    torch.onnx.export(wrap, tuple(args), str(f32), input_names=names, output_names=["out"], dynamic_axes=dyn, opset_version=17, dynamo=False)
    from onnxruntime.quantization import QuantType, quantize_dynamic
    q8 = out / f"{name}_int8.onnx"
    # per-channel: mean cosine to fp32 0.967 vs 0.918 per-tensor on VOX contexts (min is poor for both, see README)
    quantize_dynamic(str(f32), str(q8), weight_type=QuantType.QInt8, per_channel=True)
    # model metadata the app keys on (OptionFormat.kt): the option text format it was trained on; absent = v1
    import onnx
    fmt = meta.get("option_format", "v1")
    info = {"option_format": fmt, "arch": arch, "temperature": meta.get("temperature"), "scale": meta.get("scale"),
            "q_prefix": meta.get("q_prefix"), "p_prefix": meta.get("p_prefix"), "vocab_kept": meta.get("vocab_kept")}
    for p in (f32, q8):
        mp = onnx.load(str(p))
        del mp.metadata_props[:]
        for k, v in info.items():
            if v is not None:
                mp.metadata_props.add(key=k, value=str(v))
        onnx.save(mp, str(p))
    (out / "model_meta.json").write_text(json.dumps(info, indent=2))
    print(f"option_format {fmt}{'' if 'option_format' in meta else ' (not declared in student.json: v1 assumed)'}")
    # parity check against torch
    import onnxruntime as ort
    feeds = {n: x.numpy() for n, x in zip(names, args)}
    with torch.no_grad():
        ref = wrap.eval()(*args).numpy()
    for p in (f32, q8):
        got = ort.InferenceSession(str(p), providers=["CPUExecutionProvider"]).run(None, feeds)[0]
        print(f"{p.name}: {p.stat().st_size/1e6:.1f} MB, max |diff| vs torch {abs(got - ref).max():.4f}")


if __name__ == "__main__":
    export(sys.argv[1])
