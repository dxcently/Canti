import json, sys
from transformers import AutoConfig, AutoModel, AutoTokenizer

out = {}
for name in ["intfloat/e5-base-v2", "answerdotai/ModernBERT-base"]:
    try:
        tok = AutoTokenizer.from_pretrained(name)
        model = AutoModel.from_pretrained(name)
        m = model
        cand = []
        obj = m
        for part in ("encoder", "layers", "transformer"):
            getattr(obj, part, None) and cand.append(part)
        layers = None
        for path in ("encoder.layer", "layers", "transformer.layer"):
            o = m
            try:
                for p in path.split("."):
                    o = getattr(o, p)
                layers = path
                break
            except AttributeError:
                continue
        out[name] = {
            "model_class": type(m).__name__,
            "config_class": type(m.config).__name__,
            "hidden_size": m.config.hidden_size,
            "layers_attr_path": layers,
            "n_layers": len(list(getattr(m, "layers", [])) or []) if layers else None,
            "params_m": round(sum(p.numel() for p in m.parameters()) / 1e6, 1),
            "tokenizer": type(tok).__name__,
            "pad_token_id": tok.pad_token_id,
        }
    except Exception as e:
        out[name] = {"error": f"{type(e).__name__}: {e}"}
print(json.dumps(out, indent=2))
