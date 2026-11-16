CPU 工具已就绪；复核未完成，未建议通过。

独立实现位于 recompute.py。仅导入标准库和 NumPy，审计钩子拒绝导入 mlx / ainerzero。preliminary-01、preliminary-02 是训练进行中的只读快照，均未读 eval 报告。tool-validation.json 保存手算八门、零世界方差区间、自由运动负对照和逐字段篡改检测。

等待一级在 P260 信箱明确通知 EVAL-probe.json 完整可读后，才执行最终逐字段比较。
