### Operating point fitted on `val_all` (seeds pooled, cf_eval.fit_operating_point, CP95 UB (app design effect) of wrong/tap <= 0.05), frozen and applied to dev_test, test_old

| recipe | set | none bias | t_tap | t_none | tap rate | wrong/tap (bound used) | none rate (prec) | defer | resolved correct | utility |
|---|---|---|---|---|---|---|---|---|---|---|
| J5c | val_all (fit) | +0.50 | 0.92 | 0.85 | 0.317 | 0.019 (0.049) | 0.099 (0.797) | 0.584 | 0.390 | 0.370 |
| J7a | val_all (fit) | +1.50 | 0.90 | 0.90 | 0.400 | 0.020 (0.049) | 0.093 (0.855) | 0.507 | 0.471 | 0.458 |
| J7b | val_all (fit) | +0.00 | 0.96 | 0.60 | 0.343 | 0.016 (0.048) | 0.112 (0.814) | 0.545 | 0.429 | 0.408 |
| J5c | dev_test | | | | 0.321 | 0.039 (0.085) | 0.078 (0.815) | 0.601 | 0.372 | 0.358 |
| J7a | dev_test | | | | 0.391 | 0.040 (0.080) | 0.084 (0.782) | 0.524 | 0.442 | 0.423 |
| J7b | dev_test | | | | 0.360 | 0.032 (0.076) | 0.102 (0.762) | 0.538 | 0.426 | 0.402 |
| J5c | test_old | | | | 0.363 | 0.060 (0.361) | 0.081 (0.867) | 0.556 | 0.411 | 0.400 |
| J7a | test_old | | | | 0.433 | 0.045 (0.210) | 0.080 (0.878) | 0.487 | 0.484 | 0.474 |
| J7b | test_old | | | | 0.359 | 0.039 (0.204) | 0.096 (0.854) | 0.544 | 0.427 | 0.413 |

Paired against J5c at each recipe's own frozen point (screen-cluster bootstrap B=2000): Δutility/row, Δwrong taps/row, Δtap rate, Δresolved correct [95% CI] p

| recipe | set | Δutility | Δwrong taps / row | Δtap rate | Δresolved correct |
|---|---|---|---|---|---|
| J7a | dev_test | +0.066 [+0.032, +0.102] p=0.001 | +0.003 [-0.005, +0.012] p=0.546 | +0.071 [+0.039, +0.107] p=0.000 | +0.070 [+0.038, +0.104] p=0.000 |
| J7b | dev_test | +0.045 [+0.015, +0.076] p=0.001 | -0.001 [-0.009, +0.005] p=0.849 | +0.040 [+0.015, +0.068] p=0.003 | +0.054 [+0.028, +0.081] p=0.000 |
| J7a | test_old | +0.074 [+0.038, +0.107] p=0.000 | -0.002 [-0.012, +0.005] p=0.743 | +0.070 [+0.036, +0.104] p=0.000 | +0.073 [+0.037, +0.106] p=0.000 |
| J7b | test_old | +0.013 [-0.018, +0.045] p=0.392 | -0.008 [-0.018, +0.002] p=0.166 | -0.003 [-0.031, +0.025] p=0.851 | +0.016 [-0.014, +0.047] p=0.277 |
