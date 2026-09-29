import json
from collections import Counter


def hist(path):
    c = Counter()
    for line in open(path):
        c[json.loads(line)["kind"]] += 1
    return c


v5 = hist("data/v5/train.jsonl")
v6 = hist("data/v6/train.jsonl")
keys = sorted(set(v5) | set(v6))
print(f"{'kind':20s} {'v5':>7s} {'v6':>7s}")
for k in keys:
    print(f"{k:20s} {v5.get(k, 0):7d} {v6.get(k, 0):7d}")
print(f"{'TOTAL':20s} {sum(v5.values()):7d} {sum(v6.values()):7d}")
