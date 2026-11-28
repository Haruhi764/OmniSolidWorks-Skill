# V1.0.1-RC1 已知限制

- Issue #2 的 SW2026（COM 34.x）特殊兼容性已完成模拟测试，等待外部实机复测。需要核实真实 STEP 半圆柱面的共享边和角度参数，以及宿主生成的未知原生容器。使用 [外部复测说明](docs/ISSUE_2_SW2026_RETEST.md) 回传必要结果。
- SolidWorks 2024 尚未完成实机验证。

- G06 原生路线线仍为实验性功能。保存关闭重开持久化未通过。拆装资料使用原生可编辑爆炸步骤、工程图气泡及独立步骤表。
- 部分夹爪配合保留平面内自由度。连续运动检查为 AABB 粗筛。折合状态静态干涉另由原生实体查询验证。
- SolidWorks 2014 可能发生 `sldapiu.dll` 访问违规。保留经验证的检查点，在空白会话恢复。
- SolidWorks 2014 x64 SP0（COM 22.0.0）为经实机验收的宿主。其他版本与跨机器环境尚未完成同等验证。

[补丁验收](ACCEPTANCE_REPORT.md) · [V1.0.0 历史验收](FINAL_ASSESSMENT.md) · [环境与兼容性](ENVIRONMENT_COMPATIBILITY.md)
