# OmniSolidWorks V1.0.1-RC1 发布就绪

**状态**　可交付外部测试。正式发布需要 SW2026 实机复测和维护者确认。

| 测试环境 | 证据 |
| --- | --- |
| SolidWorks 2014 x64 SP0（COM `22.0.0`） | 原始 RC1 已完成实机回归与独立安装。D-BearingBlock、Ø40×30 圆柱、装配、原生爆炸步、工程图和 BOM 均通过。 |
| SolidWorks 2024 | 尚未完成实机验证。 |
| SolidWorks 2026 | 圆柱拆分和未知原生容器完成模拟测试，等待外部实机复测。 |

外测包基于原始 RC1，运行程序、测试和回归样例经逐文件 SHA-256 对比一致。随包文件通过完整性核验。面向用户的版本名统一为 `V1.0.1-RC1`，安装器与清单使用 SemVer `1.0.1-rc.1`。

正式发布前需在 SW2026 确认 STEP 拆分圆柱面仍能识别为完整圆柱、未知原生容器能通过原生重开与完整性检查，并请维护者确认。 [补丁验收](ACCEPTANCE_REPORT.md) · [安全审计](FINAL_SECURITY_AUDIT.md) · [环境与安装](ENVIRONMENT_COMPATIBILITY.md) · [SW2026 复测](docs/ISSUE_2_SW2026_RETEST.md)

## 历史记录 · V1.0.0

V1.0.0 的验收和发布依据保留在历史记录中。RC2 的 90/100、RC3 的 24 项单测及 113 项清单校验均属于原版本。 [原版最终验收](FINAL_ASSESSMENT.md) · [原版安全审计](SECURITY_AUDIT.md) · [原版发布与许可记录](LICENSE-PROPOSAL.md)
