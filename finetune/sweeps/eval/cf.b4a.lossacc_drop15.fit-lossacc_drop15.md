### Leave-apps-out cross-fit (data/real-targets-v2/b4a; app-cluster 95% CIs, B=1000)

| recipe | seeds | rows / apps | NLL | none AUROC | target acc | novel acc | acc | none recall |
|---|---|---|---|---|---|---|---|---|
| lossacc_drop15 | 3 | 4749 / 63 | 0.801 [0.727, 0.889] | 0.919 [0.908, 0.930] | 0.780 [0.754, 0.803] | 0.738 [0.711, 0.761] (n=3716) | 0.759 [0.735, 0.781] | 0.620 [0.582, 0.659] |

Seed SD (noise floor of one run): lossacc_drop15: nll 0.0035, none_auroc 0.0020, target_acc 0.0033, novel_acc 0.0032, acc 0.0031, none_recall 0.0059, false_none 0.0009

Operating point fitted on lossacc_drop15 out-of-app preds (3 seeds pooled): T=1.971

| | none bias | t_tap | t_none | tap rate | wrong taps / taps (CP95 UB, deff) | none rate (precision) | defer rate | resolved correct |
|---|---|---|---|---|---|---|---|---|
| fitted | +0.50 | 0.82 | 0.55 | 0.488 | 0.036 (0.050, 3.42) | 0.092 (0.770) | 0.420 | 0.541 |
| argmax, no thresholds | 0 | 0 | 0 | 0.891 | 0.221 (0.257, 10.41) | 0.109 (0.731) | 0.000 | 0.774 |

Per seed at the fitted point: tap 0.486, wrong/tap 0.037, defer 0.422; tap 0.489, wrong/tap 0.035, defer 0.419; tap 0.489, wrong/tap 0.035, defer 0.420
