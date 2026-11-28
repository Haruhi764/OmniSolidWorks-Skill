# V1.0.1-RC1 · Issue #2 SolidWorks 2026 专项复测

SolidWorks 2014 x64 SP0 已完成实机测试。SolidWorks 2024 尚未完成实机验证。SolidWorks 2026 的圆柱拆分和未知原生容器已完成模拟测试，以下步骤用于外部实机复测。

请在已许可的 SolidWorks 2026 x64 和 Windows x64 Python 3.12+ 环境运行。使用新的解压目录和安装目录。保留 V1.0.0 及已有工程作为回滚。解压前用 `Get-FileHash -Algorithm SHA256` 核对外测目录中的 ZIP 摘要。预检前保存工作并打开空白 SolidWorks 会话。

```powershell
python -B scripts/v03_jobs.py --preflight
```

确认输出的 `status` 为 `PASS`，`revision` 的主版本为 `34`，且 `documents` 为 `0`。若同机还有其他版本，先设定 `$env:SOLIDWORKS_REVISION_MAJOR = '34'`。有多个进程时，用 `$env:SOLIDWORKS_TARGET_PID` 指定空白的 SW2026 进程。安装目录和 GB 模板覆盖方法见 [环境说明](../ENVIRONMENT_COMPATIBILITY.md)。

```powershell
python -B scripts/v03_jobs.py --force examples/v03/D-BearingBlock.json examples/issue2/Cylinder40x30.json
python -B scripts/sw_rc_smoke.py install
python -B scripts/sw_rc_smoke.py bearing-drawing
```

| 用例 | 核对项 |
| --- | --- |
| [轴承座原始案例](../examples/v03/D-BearingBlock.json) | 原生及 STEP 单实体，体积约 63,852.2138 mm³。Ø30、两个 Ø8，厚度 20→21→20 mm。 |
| [Ø40×30 圆柱](../examples/issue2/Cylinder40x30.json) | 原生及 STEP 单实体，体积约 37,699.1118 mm³。深度 30→31→30 mm。 |
| 装配及工程图 | 原生 SLDASM 重开，2 个组件、2 项配合及原生爆炸步。SLDDRW 重开后检查视图、BOM 与气泡。轴承座工程图重开后检查剖视与关联尺寸。每个阶段应报告 `verified`。 |

两个零件的 `result.json` 应显示 `PASS/complete`、`cache_hit: false`。在同目录 `native.json` 核对 `nativeSave`、`nativeOpen`、`nativeFile`、`reopenedGeometry`、`stepGeometry` 和尺寸探针。`stepGeometry.cylinders[*].faceCount` 记录匹配的原生面数。若 SW2026 导入器确实拆分，`faceCount` 会大于 1，`coverageRadians` 应约为 6.2831853。若全部仍为 1，请记录实际 STEP 设置和面数。拆分路径需要另做实机复现。

若宿主使用未知原生容器，各文档类型应分别为 SLDPRT=1、SLDASM=2、SLDDRW=3，比较重开前的 `nativeOpen.fileBeforeReopen` 和最终 `nativeFile`，文档类型、文件大小及 SHA-256 应一致。请标明宿主产出的 SLDPRT 是 OLE 复合文件还是未知容器。保持默认验收规则。若失败，保留原始输出，并记录首次失败的 `stage`、`error`、`hresult`。

请仅回传实际 COM 修订号、Python 版本、上述字段及必要的匿名化错误片段。分享日志前请移除私有路径、用户名、序列号、许可证信息或未授权的图纸和模型。 [原始反馈](https://github.com/Haruhi764/OmniSolidWorks-Skill/issues/2)
