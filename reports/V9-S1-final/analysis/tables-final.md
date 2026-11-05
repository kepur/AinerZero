| 指标 | 方向 | arm2 均值 [min, max] | arm3 均值 [min, max] | arm4 均值 [min, max] | final 按均值排序 | 范围不重叠的对 | dev 排序 | 与 dev 同序 |
|---|---|---|---|---|---|---|---|---|
| translation error, mean (m) | lower_is_better | 0.3493 [0.3342, 0.3622] | 0.3563 [0.3483, 0.3657] | 0.3510 [0.3468, 0.3584] | arm2 > arm4 > arm3 | 无 | arm2 > arm4 > arm3 | 是 |
| translation error, median (m) | lower_is_better | 0.1337 [0.1183, 0.1414] | 0.1408 [0.1397, 0.1414] | 0.1402 [0.1385, 0.1414] | arm2 > arm4 > arm3 | 无 | arm2 > arm4 > arm3 | 是 |
| yaw error, mean (deg) | lower_is_better | 3.6029 [2.9499, 3.9575] | 3.4050 [3.1276, 3.9104] | 3.3940 [3.2820, 3.5910] | arm4 > arm3 > arm2 | 无 | arm4 > arm3 > arm2 | 是 |
| next-observation NLL, mean (nats) | lower_is_better | 0.0075 [0.0008316, 0.0171] | 0.000765 [0.0003698, 0.0012] | 0.0004102 [0.0002828, 0.0005807] | arm4 > arm3 > arm2 | arm4_vs_arm2 | arm4 > arm3 > arm2 | 是 |
| next-observation NLL, median (nats) | lower_is_better | 0.0080 [0.0009137, 0.0181] | 0.0008403 [0.0003904, 0.0013] | 0.0004456 [0.0002994, 0.0006397] | arm4 > arm3 > arm2 | arm4_vs_arm2 | arm4 > arm3 > arm2 | 是 |
| unseen-map translation error, mean (m) | lower_is_better | 0.3493 [0.3342, 0.3622] | 0.3563 [0.3483, 0.3657] | 0.3510 [0.3468, 0.3584] | arm2 > arm4 > arm3 | 无 | arm2 > arm4 > arm3 | 是 |
| edge F1 (degenerate, see notes)（全格相同） | higher_is_better | 0.7500 [0.7500, 0.7500] | 0.7500 [0.7500, 0.7500] | 0.7500 [0.7500, 0.7500] | tie (identical in every cell; no ranking) | 无 | tie (identical in every cell; no ranking) | 是 |
| NLL curve, normalised area | lower_is_better | 0.1060 [0.1002, 0.1109] | 0.0954 [0.0933, 0.0979] | 0.0924 [0.0915, 0.0931] | arm4 > arm3 > arm2 | arm4_vs_arm3, arm4_vs_arm2, arm3_vs_arm2 | arm4 > arm3 > arm2 | 是 |
| NLL at the final checkpoint | lower_is_better | 0.0075 [0.0008316, 0.0171] | 0.000765 [0.0003698, 0.0012] | 0.0004102 [0.0002828, 0.0005807] | arm4 > arm3 > arm2 | arm4_vs_arm2 | arm4 > arm3 > arm2 | 是 |
| localization curve, normalised area | lower_is_better | 0.3426 [0.3277, 0.3546] | 0.3488 [0.3420, 0.3585] | 0.3449 [0.3392, 0.3503] | arm2 > arm4 > arm3 | 无 | arm2 > arm4 > arm3 | 是 |
| worst retention delta | lower_is_better | 0.1274 [0.0149, 0.2593] | 0.0031 [-1.577e-05, 0.0094] | 0.0014 [-9.459e-06, 0.0041] | arm4 > arm3 > arm2 | arm4_vs_arm2, arm3_vs_arm2 | arm3 > arm2 > arm4 | 否 |

| 族 | NLL arm2 | NLL arm3 | NLL arm4 | 平移 arm2 (m) | 平移 arm3 | 平移 arm4 |
|---|---|---|---|---|---|---|
| e3_identity | 0.0097 | 0.0009482 | 0.000498 | 0.1311 | 0.1261 | 0.1052 |
| navigation | 0.0058 | 0.0006452 | 0.0003575 | 1.0077 | 1.0177 | 1.0198 |
| relation | 0.0081 | 0.0008001 | 0.000427 | 0.1357 | 0.1401 | 0.1410 |
| time | 0.0065 | 0.0006665 | 0.0003583 | 0.1228 | 0.1414 | 0.1381 |

| k | worlds (arm2 s0) | arm2 acc / bal | arm3 acc / bal | arm4 acc / bal |
|---|---|---|---|---|
| 0 | 200 | 0.6000 / 0.5000 | 0.6000 / 0.5000 | 0.6000 / 0.5000 |
| 1 | 200 | 0.4988 / 0.4572 | 0.5455 / 0.5000 | 0.5455 / 0.5000 |
| 2 | 150 | 0.3810 / 0.4444 | 0.4286 / 0.5000 | 0.4286 / 0.5000 |
| 4 | 50 | 0.0000 / 0.0000 | 0.0000 / 0.0000 | 0.0000 / 0.0000 |
| 8 | 0 | insufficient_data | insufficient_data | insufficient_data |
