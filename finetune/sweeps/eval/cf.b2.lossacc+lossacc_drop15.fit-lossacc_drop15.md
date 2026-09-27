### Leave-apps-out cross-fit (data/real-targets-v2/b2; app-cluster 95% CIs, B=1000)

| recipe | seeds | rows / apps | NLL | none AUROC | target acc | novel acc | acc | none recall |
|---|---|---|---|---|---|---|---|---|
| lossacc | 3 | 4156 / 55 | 0.735 [0.677, 0.800] | 0.912 [0.897, 0.927] | 0.804 [0.781, 0.824] | 0.755 [0.734, 0.775] (n=3210) | 0.776 [0.756, 0.794] | 0.582 [0.530, 0.635] |
| lossacc_drop15 | 3 | 4141 / 55 | 0.719 [0.659, 0.779] | 0.921 [0.910, 0.932] | 0.802 [0.779, 0.822] | 0.757 [0.736, 0.777] (n=3197) | 0.777 [0.756, 0.796] | 0.606 [0.560, 0.654] |

Seed SD (noise floor of one run): lossacc: nll 0.0037, none_auroc 0.0005, target_acc 0.0031, novel_acc 0.0040, acc 0.0034, none_recall 0.0054, false_none 0.0010; lossacc_drop15: nll 0.0060, none_auroc 0.0022, target_acc 0.0017, novel_acc 0.0008, acc 0.0017, none_recall 0.0109, false_none 0.0022

Paired against lossacc (difference of seed means, same rows, app resampling):

| recipe | nll | none_auroc | target_acc | novel_acc | acc | none_recall | false_none |
|---|---|---|---|---|---|---|---|
| lossacc_drop15 | -0.0027 [-0.0091, +0.0039] | -0.0002 [-0.0037, +0.0028] | -0.0030 [-0.0084, +0.0027] | +0.0001 [-0.0051, +0.0055] | -0.0010 [-0.0054, +0.0041] | +0.0134 [-0.0089, +0.0344] | +0.0002 [-0.0023, +0.0026] |

Operating point fitted on lossacc_drop15 out-of-app preds (3 seeds pooled): T=1.958

| | none bias | t_tap | t_none | tap rate | wrong taps / taps (CP95 UB, deff) | none rate (precision) | defer rate | resolved correct |
|---|---|---|---|---|---|---|---|---|
| fitted | +0.25 | 0.84 | 0.50 | 0.514 | 0.036 (0.049, 2.55) | 0.088 (0.756) | 0.398 | 0.562 |
| argmax, no thresholds | 0 | 0 | 0 | 0.895 | 0.203 (0.234, 7.19) | 0.105 (0.723) | 0.000 | 0.790 |

Per seed at the fitted point: tap 0.513, wrong/tap 0.036, defer 0.401; tap 0.511, wrong/tap 0.036, defer 0.396; tap 0.519, wrong/tap 0.037, defer 0.397
