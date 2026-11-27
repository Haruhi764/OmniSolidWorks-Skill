# V1.0.0 环境与兼容性 / Environment and compatibility

**发布验收基线 / Release baseline**　SolidWorks 2014 x64 SP0（COM 22.0.0）。新增 SolidWorks 2026 SP0.0（COM 34.0.0）的兼容回归，范围见下文。可识别其他已注册主版本；版本发现不等于该版本全部工作流通过验收。Discovery of another registered release is independent of compatibility.

在解压根目录运行 `python -B scripts/v03_jobs.py --preflight`。预检读取注册信息、实际 COM 修订号、PID、文档数量，校验可执行文件、PIA、Windows PowerShell 和模板。默认优先选择可用的已验收主版本 22；如果它不可用且只有一个可用注册版本，自动选择该版本。候选有多个时设定主版本。未覆盖的版本和工作流需另做实机验收。

| 检查 / Check | 处理 / Remedy |
| --- | --- |
| Python 或 Windows PowerShell | Windows x64 Python 3.12+；可用安装器 `-Python` 指明完整路径。原生桥要求系统自带 64 位 Windows PowerShell 5.1，以 STA 运行。 |
| COM 版本与安装目录 / Major and install directory | 用 `SOLIDWORKS_REVISION_MAJOR` 选择注册主版本。使用 `SOLIDWORKS_INSTALL_DIR` 手动指定含 `SLDWORKS.exe` 和 `SolidWorks.Interop.sldworks.dll` 的绝对目录时，同时指定主版本。EXE 主版本及 COM 回读必须匹配。 |
| 会话 / COM session | 在当前 Windows 会话中启动目标版本。若有多个实例，用 `SOLIDWORKS_TARGET_PID` 指定空白会话。先由使用者保存并关闭其他文档。`scripts/Start-SolidWorksSkillHost.ps1` 默认只探测，显式使用 `-StartIfMissing` 才启动。 |
| 模板 / Templates | 默认在所选主版本的 Windows ProgramData 模板目录查找 `gb_part.prtdot`、`gb_assembly.asmdot`、`gb_a4.drwdot`。可用绝对路径覆盖 `SOLIDWORKS_PART_TEMPLATE`、`SOLIDWORKS_ASSEMBLY_TEMPLATE`、`SOLIDWORKS_DRAWING_TEMPLATE`。A0–A3 的 GB 图纸模板应位于绘图模板同目录；预检按纸幅报告是否存在。带 BOM 的工程图使用本机安装提供的中文 BOM 表模板。 |
| 安装路径 / Destination | 选择可写本地驱动器上的新目录，并放在解压目录外。如果权限不足，改用自己的文档目录。 |
| 宿主异常 / Host fault | 若出现 `sldapiu.dll` 访问违规或 COM 断开，保留现有日志及已校验输出，等待或重新打开空白宿主，再按检查点继续。 |

## SolidWorks 2026 SP0.0 兼容回归

2026-11-28，Windows x64、Python 3.14、Windows PowerShell 5.1，实测 COM `34.0.0`。

- **原生容器**：本次 2026 实机生成的非 OLE 文件前四字节会变化，不能沿用仅识别 OLE 的检查。保留旧 OLE 路径；本次观察到的容器还必须匹配版本标记、成功的 2026 原生报告，以及同一路径的 `nativeOpen` 或 `sourceOpen:*` 记录。没有对应原生打开证据的文件仍拒收。
- **STEP 回读**：2017 及以上版本临时关闭 3D Interconnect，使用经典转换器保持解析圆柱面。关闭本作业拥有的导入文档后，恢复模板设置与原有 3D Interconnect 开关；导入或几何检查失败也走相同清理路径。
- **支撑面**：`IFace2.GetBox` 是近似包围盒，实测水平面在 Z 方向出现约 ±0.001175 mm 厚度。改用 `ISurface.PlaneParams` 的精确法向和高度，保留原有唯一面及最近点判断。
- **草图坐标**：程序化多边形创建期间使用 `AddToDB`，防止交互吸附移动端点，结束后恢复原值。原有 0.02 mm³ 体积校验精度不变。

实机通过七个初始零件作业的原生保存重开、STEP 回读体积与包络检查。下游六轴装配集成另通过七个组件的几何与引用重开、十二项配合、六轴各转动 3° 后恢复，以及交付姿态零实体干涉检查。该装配集成使用本地 COM 扩展，未扩展现有 JSON 装配 schema；2026 的工程图、爆炸图和全行程碰撞检查仍需各自验收。

### 重现零件回归

先选择空白会话并通过预检，再从 Skill 根目录运行：

```powershell
python -B scripts/v03_jobs.py examples/v09_install_smoke.json --force
python -B scripts/v03_jobs.py tests/fixtures/sw2026_tapered_link.json --force
```

第二个用例的目标体积为 `2210063.9753196533 mm³`，包络为 `[-55,-55,0]` 至 `[360,55,120] mm`。修复前曾测得 `2210089.8665720886 mm³`；关闭交互吸附后恢复目标值。重开及 STEP 证据记录在各作业的 `native.json`，其中 `stepPreferencesRestored` 应为 `true`。

[GetBox 的近似精度说明](https://help.solidworks.com/2023/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFace2~GetBox.html) · [PlaneParams 参数定义](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISurface~PlaneParams.html)

[中文安装](README.md) · [English installation](README.en.md) · [运行与恢复](docs/INCREMENTAL_GUIDE.md)
