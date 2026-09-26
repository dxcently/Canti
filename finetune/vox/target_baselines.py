"""No-training baselines for intent-cursor target selection (data/targets-*): is a trained model even needed?

  fuzzy  word overlap between the utterance and each option's label, plus a bonus when the utterance's position
         words (top/bottom/left/right/middle, simple keywords, not the generator's lists) match the option's cell;
         "none" wins when no option scores above a threshold fitted on validation.
  e5     zero-shot intfloat/e5-small-v2 cosine("query: utterance", "passage: label role position"); "none" is a fixed
         score fitted on validation.

Writes preds/<data name>/<split>.<baseline>.jsonl in the usual {"id", "probs"} format; score with vox.evaluate.
Usage: python -m vox.target_baselines data/targets-v1 [--device cpu]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

STOP = set("a an the to of my it this that on in at up please i want me go tap press hit select one thing icon button "
           "let could you can whatever is sitting along side corner screen".split())
POS_KEYS = {"top": ("top", "upper", "up"), "bottom": ("bottom", "lower", "down", "low"), "left": ("left",), "right": ("right",),
            "center": ("middle", "center", "centre")}


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def parse_option(opt: str) -> tuple[str, str, str]:
    m = re.match(r"(.*) \((.*), (.*)\)$", opt)
    return (m.group(1), m.group(2), m.group(3)) if m else (opt, "", "")


def utter(row: dict) -> str:
    return re.search(r'spoken target: "(.*)"', row["context"]).group(1)


def pos_match(utt: str, pos: str) -> float:
    said = {k for k, ws in POS_KEYS.items() if any(w in words(utt) for w in ws)}
    if not said:
        return 0.0
    cell = set(pos.split()) if pos != "center" else {"center"}
    return 1.0 if said == cell else 0.5 if said & cell else -0.5


def fuzzy_scores(row: dict) -> list[float]:
    u = set(words(utter(row))) - STOP
    out = []
    for o in row["options"][:-1]:
        label, role, pos = parse_option(o)
        lw = set(words(label)) - STOP
        overlap = len(u & lw) / max(1, len(lw)) if lw else 0.0
        out.append(overlap + 0.6 * pos_match(utter(row), pos) + (0.2 if role and role in utter(row) else 0.0))
    return out


def softmax(z: list[float], t: float) -> list[float]:
    m = max(z)
    e = [math.exp((v - m) / t) for v in z]
    s = sum(e)
    return [v / s for v in e]


def fit_none(rows: list[dict], scores: list[list[float]]) -> float:
    """The constant 'none' score that maximises validation accuracy."""
    grid = sorted({round(x, 3) for sc in scores for x in sc} | {0.0, 1.0})
    def acc(t):
        ok = 0
        for r, sc in zip(rows, scores):
            z = sc + [t]
            ok += max(range(len(z)), key=z.__getitem__) == r["label"]
        return ok
    return max(grid, key=acc)


class E5:
    def __init__(self, device: str) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch, self.device = torch, device
        self.tok = AutoTokenizer.from_pretrained("intfloat/e5-small-v2")
        self.model = AutoModel.from_pretrained("intfloat/e5-small-v2").to(device).eval()

    def embed(self, texts: list[str]):
        torch = self.torch
        with torch.inference_mode():
            b = self.tok(texts, padding=True, truncation=True, max_length=64, return_tensors="pt").to(self.device)
            h = self.model(**b).last_hidden_state
            m = b["attention_mask"].unsqueeze(-1)
            v = (h * m).sum(1) / m.sum(1)
            return torch.nn.functional.normalize(v, dim=-1)

    def scores(self, row: dict) -> list[float]:
        opts = [" ".join(parse_option(o)) for o in row["options"][:-1]]
        v = self.embed([f"query: {utter(row)}"] + [f"passage: {o}" for o in opts])
        return (v[1:] @ v[0]).tolist()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data", type=Path)
    p.add_argument("--device", default="cpu")
    p.add_argument("--baselines", default="fuzzy,e5")
    a = p.parse_args()
    load = lambda s: [json.loads(line) for line in (a.data / f"{s}.jsonl").open()]  # noqa: E731
    val = load("validation")
    out_dir = Path("preds") / a.data.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in a.baselines.split(","):
        fn = fuzzy_scores if name == "fuzzy" else E5(a.device).scores
        temp = 0.15 if name == "fuzzy" else 0.02
        none = fit_none(val, [fn(r) for r in val])
        for split in ("test_iid", "test_unseen_phrasing", "test_unseen_apps"):
            with (out_dir / f"{split}.{name}.jsonl").open("w") as f:
                for r in load(split):
                    f.write(json.dumps({"id": r["id"], "probs": [round(x, 6) for x in softmax(fn(r) + [none], temp)]}) + "\n")
        print(json.dumps({"baseline": name, "none_score": none}))


if __name__ == "__main__":
    main()
