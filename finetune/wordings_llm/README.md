# wordings_llm: LLM-written wording bank

- `bank.json`: extra ways to phrase each action, gesture, rule template and spoken phrase, written by an LLM **blind** to the held-out test lists.
- `AMBIGUITY.md`: wordings that could be read as a different option; `vox/bank.py` drops them.
- `validate.py`: checks the bank against the schema vocabulary and the shipped training wordings.

The bank is never used as-is. `python -m vox.generate --bank wordings_llm/bank.json` merges it through `vox/bank.py`, which removes anything close to a held-out wording (the first blind bank leaked 13 exact test wordings) and writes `bank_dropped.json` next to the data.
