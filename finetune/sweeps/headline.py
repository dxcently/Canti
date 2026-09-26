"""One-line summary of a vox.evaluate JSON file: sweeps/headline.py <eval.json> <key>."""

import json
import sys

m = json.load(open(sys.argv[1]))[sys.argv[2]]
print(f"acc {m['accuracy']:.3f} ece {m['ece']:.3f} ftr {m['false_trigger_rate']:.3f} "
      f"missed {m['missed_command_rate']:.3f} {m['by_kind']}")
