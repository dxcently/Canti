# Brief: act on the v6 seed advice (E1-E3 code + scripts; the coordinator runs the GPU training)

Read sweeps/scratch/v6s2-ADVICE.md first (the advisor's findings, verified by the coordinator: 21/28 seed-11 errors on
test_unseen_phrasing are the one wording "push the screen upward" -> volume_up; selection ties go to the earliest
epoch). HARD RULES: same as sweeps/scratch/v6-brief.md HARD RULES (no git, no installs, never touch torch/jevlike/
torch-rocm, no adb/phone, never open zflip/, never read the ollama key, exact PIDs only, one simple command per bash
call, pinned env for python). You cannot launch background jobs; do NOT start any training yourself.

E1 (code, 0 GPU): students/jevlike/train.py: add `--save-every-epoch` (writes <output stem>.e<N>.pt for each epoch, same
format as the final checkpoint) and `--tie later` (default stays `earliest` so old runs reproduce; `later` keeps the
later epoch on an exact tie). Unit-test the tie logic if the file has a testable seam; otherwise a tiny tests/ test on
a factored-out helper. Do not change any default behaviour.
E2 (0 GPU): sweeps/cluster_eval.py: from a data split + one or more preds files, report accuracy per wording cluster
(held-out action wording / phrase text, and app x screen kind for test_unseen_apps), how many clusters pass (>= 95%),
and seed-mean + range when several preds for the same split are given. Write its output for v6 s7 + s11 on the three
splits to sweeps/scratch/v6_clusters.txt.
E3 (short, run it in the foreground only if it takes < 2 min on GPU, else write the script and stop): prob-average
ensemble of preds/sweep-v6-e5-small-e3{,-s2}.<split>.jsonl (no model needed: average the probs) -> evaluate with
vox.evaluate -> sweeps/scratch/v6_ens.txt. Weight soup only if trivial; say which you did.
E4 prep: write sweeps/scratch/v6s3_queue.sh (from v6s2_queue.sh) that retrains seed 11 as v6-e5-small-e3-s11b with
--save-every-epoch --tie later, then predicts+evaluates the final AND each per-epoch checkpoint on the 3 v6 splits
(names v6-e5-small-e3-s11b, -s11b-e1/-e2/-e3), recording ledger rows. Do not run it.
Report: sweeps/scratch/v6s3-REPORT.md (what changed, test results, E2/E3 numbers).
