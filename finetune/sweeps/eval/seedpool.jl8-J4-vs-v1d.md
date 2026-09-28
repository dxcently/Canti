### Seed-pooled: `jl8-J4-vs-v1d`

A = jl8-J4-s7.pt, jl8-J4-s8.pt, jl8-J4-s9.pt; B = verdict-bi-real-v1d. Mean over seeds; paired A - B, screen-cluster bootstrap B=2000 shared across seeds. T per checkpoint (stored).

| set | n | A mean (seed SD) acc | B mean acc | Δacc [95% CI] p | ΔNLL [95% CI] | Δwrong-tap@0.8 [95% CI] | A NLL / B NLL | A wt@0.8 / B wt@0.8 |
|---|---|---|---|---|---|---|---|---|
| dev_test | 344 | 0.744 (0.013) | 0.750 | -0.006 [-0.043, +0.029] p=0.772 | -0.016 [-0.095, +0.061] | +0.008 [-0.009, +0.023] | 0.864 / 0.880 | 0.034 / 0.026 |
| test_old | 308 | 0.819 (0.005) | 0.838 | -0.018 [-0.047, +0.012] p=0.236 | +0.066 [-0.017, +0.149] | +0.005 [-0.007, +0.018] | 0.644 / 0.578 | 0.031 / 0.026 |
| diag_x | 40 | 0.408 (0.029) | 0.450 | -0.042 [-0.142, +0.108] p=0.528 | +0.119 [-0.129, +0.354] | -0.050 [-0.100, +0.000] | 1.813 / 1.694 | 0.000 / 0.050 |
