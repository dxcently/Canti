# third_party (untracked)

Upstream repositories cloned for the students. They're not vendored into git; clone them at the pinned commit:

| Folder | Upstream | Commit |
|---|---|---|
| `kev/` | https://github.com/jaredpalmer/kev | `58d9438` |
| `verdict/` | https://github.com/Manavarya09/verdict | `76bc1fe` |

```bash
git clone https://github.com/jaredpalmer/kev third_party/kev && git -C third_party/kev checkout 58d9438
git clone https://github.com/Manavarya09/verdict third_party/verdict && git -C third_party/verdict checkout 76bc1fe
```
The teacher models (Decider 4B, JevK5) come from Hugging Face at the revisions pinned in `teachers/scorer.py`.
