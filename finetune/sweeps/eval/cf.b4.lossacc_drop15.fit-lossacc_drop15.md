### Leave-apps-out cross-fit (data/real-targets-v2/b4; app-cluster 95% CIs, B=1000)

| recipe | seeds | rows / apps | NLL | none AUROC | target acc | novel acc | acc | none recall |
|---|---|---|---|---|---|---|---|---|
| lossacc_drop15 | 3 | 4751 / 63 | 0.808 [0.735, 0.896] | 0.921 [0.910, 0.932] | 0.780 [0.754, 0.802] | 0.736 [0.708, 0.760] (n=3718) | 0.759 [0.735, 0.781] | 0.620 [0.580, 0.658] |

Seed SD (noise floor of one run): lossacc_drop15: nll 0.0063, none_auroc 0.0031, target_acc 0.0002, novel_acc 0.0003, acc 0.0022, none_recall 0.0164, false_none 0.0004

Operating point fitted on lossacc_drop15 out-of-app preds (3 seeds pooled): T=1.985

| | none bias | t_tap | t_none | tap rate | wrong taps / taps (CP95 UB, deff) | none rate (precision) | defer rate | resolved correct |
|---|---|---|---|---|---|---|---|---|
| fitted | +0.75 | 0.82 | 0.60 | 0.481 | 0.036 (0.050, 3.22) | 0.090 (0.774) | 0.429 | 0.533 |
| argmax, no thresholds | 0 | 0 | 0 | 0.892 | 0.222 (0.259, 10.63) | 0.108 (0.740) | 0.000 | 0.774 |

Per seed at the fitted point: tap 0.481, wrong/tap 0.033, defer 0.429; tap 0.481, wrong/tap 0.040, defer 0.429; tap 0.480, wrong/tap 0.035, defer 0.430
