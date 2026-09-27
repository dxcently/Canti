### Leave-apps-out cross-fit (data/real-targets-v2/b2; app-cluster 95% CIs, B=1000)

| recipe | seeds | rows / apps | NLL | none AUROC | target acc | novel acc | acc | none recall |
|---|---|---|---|---|---|---|---|---|
| ref | 3 | 4156 / 55 | 0.742 [0.683, 0.809] | 0.909 [0.893, 0.924] | 0.799 [0.776, 0.821] | 0.750 [0.728, 0.772] (n=3210) | 0.772 [0.752, 0.790] | 0.583 [0.534, 0.636] |
| lossacc | 3 | 4156 / 55 | 0.735 [0.677, 0.800] | 0.912 [0.897, 0.927] | 0.804 [0.781, 0.824] | 0.755 [0.734, 0.775] (n=3210) | 0.776 [0.756, 0.794] | 0.582 [0.530, 0.635] |
| lossacc_drop15 | 1 | 4141 / 55 | 0.713 [0.654, 0.777] | 0.923 [0.913, 0.934] | 0.800 [0.775, 0.821] | 0.757 [0.733, 0.777] (n=3197) | 0.775 [0.753, 0.794] | 0.603 [0.553, 0.655] |

Seed SD (noise floor of one run): ref: nll 0.0009, none_auroc 0.0010, target_acc 0.0014, novel_acc 0.0023, acc 0.0024, none_recall 0.0100, false_none 0.0019; lossacc: nll 0.0037, none_auroc 0.0005, target_acc 0.0031, novel_acc 0.0040, acc 0.0034, none_recall 0.0054, false_none 0.0010; lossacc_drop15: 

Paired against ref (difference of seed means, same rows, app resampling):

| recipe | nll | none_auroc | target_acc | novel_acc | acc | none_recall | false_none |
|---|---|---|---|---|---|---|---|
| lossacc | -0.0078 [-0.0158, +0.0008] | +0.0034 [-0.0001, +0.0075] | +0.0049 [-0.0012, +0.0104] | +0.0049 [-0.0012, +0.0105] | +0.0042 [-0.0013, +0.0095] | -0.0006 [-0.0152, +0.0139] | -0.0006 [-0.0026, +0.0012] |
| lossacc_drop15 | -0.0156 [-0.0266, -0.0061] | +0.0054 [+0.0009, +0.0107] | +0.0002 [-0.0062, +0.0070] | +0.0042 [-0.0036, +0.0121] | +0.0014 [-0.0054, +0.0081] | +0.0096 [-0.0157, +0.0374] | -0.0005 [-0.0042, +0.0036] |

Operating point fitted on lossacc out-of-app preds (3 seeds pooled): T=1.991

| | none bias | t_tap | t_none | tap rate | wrong taps / taps (CP95 UB, deff) | none rate (precision) | defer rate | resolved correct |
|---|---|---|---|---|---|---|---|---|
| fitted | +0.50 | 0.88 | 0.50 | 0.455 | 0.033 (0.050, 3.95) | 0.095 (0.730) | 0.450 | 0.510 |
| argmax, no thresholds | 0 | 0 | 0 | 0.897 | 0.203 (0.233, 6.46) | 0.103 (0.720) | 0.000 | 0.789 |

Per seed at the fitted point: tap 0.459, wrong/tap 0.036, defer 0.445; tap 0.448, wrong/tap 0.031, defer 0.458; tap 0.458, wrong/tap 0.032, defer 0.447
