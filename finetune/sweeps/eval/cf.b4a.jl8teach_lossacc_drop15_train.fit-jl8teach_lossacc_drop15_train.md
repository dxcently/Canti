### Leave-apps-out cross-fit (data/real-targets-v2/b4a; app-cluster 95% CIs, B=1000)

| recipe | seeds | rows / apps | NLL | none AUROC | target acc | novel acc | acc | none recall |
|---|---|---|---|---|---|---|---|---|
| jl8teach_lossacc_drop15_train | 2 | 4252 / 63 | 0.807 [0.729, 0.899] | 0.919 [0.906, 0.931] | 0.775 [0.747, 0.800] | 0.733 [0.704, 0.758] (n=3341) | 0.754 [0.728, 0.778] | 0.616 [0.574, 0.652] |

Seed SD (noise floor of one run): jl8teach_lossacc_drop15_train: nll 0.0016, none_auroc 0.0017, target_acc 0.0025, novel_acc 0.0038, acc 0.0043, none_recall 0.0169, false_none 0.0006

Operating point fitted on jl8teach_lossacc_drop15_train out-of-app preds (2 seeds pooled): T=1.972

| | none bias | t_tap | t_none | tap rate | wrong taps / taps (CP95 UB, deff) | none rate (precision) | defer rate | resolved correct |
|---|---|---|---|---|---|---|---|---|
| fitted | +0.50 | 0.82 | 0.55 | 0.484 | 0.038 (0.050, 2.23) | 0.094 (0.752) | 0.422 | 0.537 |
| argmax, no thresholds | 0 | 0 | 0 | 0.889 | 0.225 (0.257, 6.98) | 0.111 (0.712) | 0.000 | 0.768 |

Per seed at the fitted point: tap 0.486, wrong/tap 0.039, defer 0.422; tap 0.482, wrong/tap 0.036, defer 0.421
