# V1.0.1-RC1 环境与兼容性 / Environment and compatibility

| 环境 / Host | 验证状态 / Evidence |
| --- | --- |
| SolidWorks 2014 x64 SP0 (COM 22.0.0) | 已完成实机测试。 Live testing completed. |
| SolidWorks 2024 | 尚未完成实机验证。 Live validation pending. |
| SolidWorks 2026 | 特殊兼容性已完成模拟测试，等待外部实机复测。 Compatibility cases passed simulation and await external live testing. |

COM 34 及以上的未知容器必须通过原生保存、关闭重开及读回验证。发现已注册宿主只说明该版本可以被预检识别。

在解压根目录运行 `python -B scripts/v03_jobs.py --preflight`。预检读取注册信息、实际 COM 修订号、PID、文档数量，校验可执行文件、PIA、Windows PowerShell 和模板。默认优先选择可用的已验收主版本 22；如果它不可用且只有一个可用注册版本，自动选择该版本。候选有多个时设定主版本。任何其他版本均需另做实机验收。

| 检查 / Check | 处理 / Remedy |
| --- | --- |
| Python 或 Windows PowerShell | Windows x64 Python 3.12+。旧版 Python 在预检入口以 `python_version` 阻止运行。可用安装器 `-Python` 指明完整路径。原生桥要求系统自带 64 位 Windows PowerShell 5.1，以 STA 运行。 |
| COM 版本与安装目录 / Major and install directory | 用 `SOLIDWORKS_REVISION_MAJOR` 选择注册主版本。使用 `SOLIDWORKS_INSTALL_DIR` 手动指定含 `SLDWORKS.exe` 和 `SolidWorks.Interop.sldworks.dll` 的绝对目录时，同时指定主版本。EXE 主版本及 COM 回读必须匹配。 |
| 会话 / COM session | 在当前 Windows 会话中启动目标版本。若有多个实例，用 `SOLIDWORKS_TARGET_PID` 指定空白会话。先由使用者保存并关闭其他文档。`scripts/Start-SolidWorksSkillHost.ps1` 默认只探测，显式使用 `-StartIfMissing` 才启动。 |
| 模板 / Templates | 默认在所选主版本的 Windows ProgramData 模板目录查找 `gb_part.prtdot`、`gb_assembly.asmdot`、`gb_a4.drwdot`。可用绝对路径覆盖 `SOLIDWORKS_PART_TEMPLATE`、`SOLIDWORKS_ASSEMBLY_TEMPLATE`、`SOLIDWORKS_DRAWING_TEMPLATE`。A0–A3 的 GB 图纸模板应位于绘图模板同目录；预检按纸幅报告是否存在。带 BOM 的工程图使用本机安装提供的中文 BOM 表模板。 |
| 安装路径 / Destination | 选择可写本地驱动器上的新目录，并放在解压目录外。如果权限不足，改用自己的文档目录。 |
| 宿主异常 / Host fault | 若出现 `sldapiu.dll` 访问违规或 COM 断开，保留现有日志及已校验输出，等待或重新打开空白宿主，再按检查点继续。 |

[中文安装](README.md) · [English installation](README.en.md) · [运行与恢复](docs/INCREMENTAL_GUIDE.md)
