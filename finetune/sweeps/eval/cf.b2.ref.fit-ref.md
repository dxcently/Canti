### Leave-apps-out cross-fit (data/real-targets-v2/b2; app-cluster 95% CIs, B=1000)

| recipe | seeds | rows / apps | NLL | none AUROC | target acc | novel acc | acc | none recall |
|---|---|---|---|---|---|---|---|---|
| ref | 3 | 4156 / 55 | 0.742 [0.683, 0.809] | 0.909 [0.893, 0.924] | 0.799 [0.776, 0.821] | 0.750 [0.728, 0.772] (n=3210) | 0.772 [0.752, 0.790] | 0.583 [0.534, 0.636] |

Seed SD (noise floor of one run): ref: nll 0.0009, none_auroc 0.0010, target_acc 0.0014, novel_acc 0.0023, acc 0.0024, none_recall 0.0100, false_none 0.0019

Operating point fitted on ref out-of-app preds (3 seeds pooled): T=1.989

| | none bias | t_tap | t_none | tap rate | wrong taps / taps (CP95 UB, deff) | none rate (precision) | defer rate | resolved correct |
|---|---|---|---|---|---|---|---|---|
| fitted | +0.75 | 0.90 | 0.55 | 0.410 | 0.032 (0.050, 4.10) | 0.097 (0.725) | 0.493 | 0.467 |
| argmax, no thresholds | 0 | 0 | 0 | 0.896 | 0.209 (0.240, 6.96) | 0.104 (0.716) | 0.000 | 0.784 |

Per seed at the fitted point: tap 0.413, wrong/tap 0.033, defer 0.487; tap 0.415, wrong/tap 0.032, defer 0.491; tap 0.402, wrong/tap 0.031, defer 0.500
