| 指标 | 方向 | arm2 均值 [min, max] | arm3 均值 [min, max] | arm4 均值 [min, max] | 按均值排序 | 范围不重叠的对 |
|---|---|---|---|---|---|---|
| development translation error, mean (m) | lower_is_better | 0.3484 [0.3315, 0.3621] | 0.3562 [0.3481, 0.3656] | 0.3505 [0.3462, 0.3578] | arm2 > arm4 > arm3 | 无 |
| development translation error, median (m) | lower_is_better | 0.1328 [0.1156, 0.1414] | 0.1407 [0.1394, 0.1414] | 0.1398 [0.1375, 0.1413] | arm2 > arm4 > arm3 | 无 |
| development yaw error, mean (deg) | lower_is_better | 3.5918 [2.9264, 3.9558] | 3.3929 [3.1031, 3.9075] | 3.3814 [3.2777, 3.5888] | arm4 > arm3 > arm2 | 无 |
| next-observation NLL, mean (nats) | lower_is_better | 0.0074 [0.0008267, 0.0166] | 0.0007862 [0.0003753, 0.0013] | 0.000423 [0.0002891, 0.0006018] | arm4 > arm3 > arm2 | arm4_vs_arm2 |
| next-observation NLL, median (nats) | lower_is_better | 0.0054 [0.0007469, 0.0120] | 0.0006604 [0.0003578, 0.0010] | 0.0003686 [0.0002742, 0.0004939] | arm4 > arm3 > arm2 | arm4_vs_arm2 |
| unseen-map translation error, mean (m) | lower_is_better | 0.3484 [0.3315, 0.3621] | 0.3562 [0.3481, 0.3656] | 0.3505 [0.3462, 0.3578] | arm2 > arm4 > arm3 | 无 |
| edge F1 (degenerate, see notes)（全格相同） | higher_is_better | 0.7500 [0.7500, 0.7500] | 0.7500 [0.7500, 0.7500] | 0.7500 [0.7500, 0.7500] | tie (identical in every cell; no ranking) | 无 |
| NLL curve, normalised area | lower_is_better | 0.1033 [0.0976, 0.1080] | 0.0929 [0.0908, 0.0953] | 0.0900 [0.0891, 0.0907] | arm4 > arm3 > arm2 | arm4_vs_arm3, arm4_vs_arm2, arm3_vs_arm2 |
| NLL at the final checkpoint | lower_is_better | 0.0074 [0.0008267, 0.0166] | 0.0007862 [0.0003753, 0.0013] | 0.000423 [0.0002891, 0.0006018] | arm4 > arm3 > arm2 | arm4_vs_arm2 |
| localization curve, normalised area | lower_is_better | 0.3418 [0.3254, 0.3545] | 0.3487 [0.3418, 0.3585] | 0.3444 [0.3386, 0.3499] | arm2 > arm4 > arm3 | 无 |
| worst retention delta | lower_is_better | 0.0051 [-0.0005336, 0.0141] | 2.149e-05 [-0.0045, 0.0046] | 0.0062 [-0.0001862, 0.0177] | arm3 > arm2 > arm4 | 无 |

| 族 | NLL arm2 | NLL arm3 | NLL arm4 | 平移 arm2 (m) | 平移 arm3 | 平移 arm4 |
|---|---|---|---|---|---|---|
| e3_identity | 0.0101 | 0.0010 | 0.0005333 | 0.1302 | 0.1260 | 0.1040 |
| navigation | 0.0063 | 0.0006977 | 0.0003823 | 1.0077 | 1.0177 | 1.0198 |
| relation | 0.0068 | 0.0007359 | 0.0004005 | 0.1344 | 0.1399 | 0.1409 |
| time | 0.0063 | 0.0006916 | 0.000376 | 0.1213 | 0.1413 | 0.1373 |

| k | worlds (arm2 s0) | arm2 acc / bal | arm3 acc / bal | arm4 acc / bal |
|---|---|---|---|---|
| 0 | 200 | 0.6000 / 0.5000 | 0.6000 / 0.5000 | 0.6000 / 0.5000 |
| 1 | 200 | 0.5115 / 0.4689 | 0.5455 / 0.5000 | 0.5455 / 0.5000 |
| 2 | 150 | 0.3705 / 0.4322 | 0.4286 / 0.5000 | 0.4286 / 0.5000 |
| 4 | 50 | 0.0000 / 0.0000 | 0.0000 / 0.0000 | 0.0000 / 0.0000 |
| 8 | 0 | insufficient_data | insufficient_data | insufficient_data |
