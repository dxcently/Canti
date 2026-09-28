### Seed-pooled: `jl8-C-vs-v1d`

A = jl8-C-s7.pt, jl8-C-s8.pt, jl8-C-s9.pt; B = verdict-bi-real-v1d. Mean over seeds; paired A - B, screen-cluster bootstrap B=2000 shared across seeds. T per checkpoint (stored).

| set | n | A mean (seed SD) acc | B mean acc | Δacc [95% CI] p | ΔNLL [95% CI] | Δwrong-tap@0.8 [95% CI] | A NLL / B NLL | A wt@0.8 / B wt@0.8 |
|---|---|---|---|---|---|---|---|---|
| dev_test | 344 | 0.729 (0.015) | 0.750 | -0.021 [-0.065, +0.019] p=0.306 | +0.026 [-0.052, +0.107] | +0.004 [-0.010, +0.018] | 0.906 / 0.880 | 0.030 / 0.026 |
| test_old | 308 | 0.788 (0.010) | 0.838 | -0.050 [-0.084, -0.017] p=0.002 | +0.136 [+0.042, +0.226] | -0.001 [-0.015, +0.013] | 0.714 / 0.578 | 0.025 / 0.026 |
| diag_x | 40 | 0.375 (0.050) | 0.450 | -0.075 [-0.233, +0.083] p=0.395 | +0.266 [-0.012, +0.564] | -0.025 [-0.075, +0.017] | 1.960 / 1.694 | 0.025 / 0.050 |
