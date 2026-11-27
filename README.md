<p align="center"><img src="assets/brand/omnisw-hero.png" width="100%" alt="OmniSolidWorks — Model. Assemble. Verify."></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-B87948?style=flat-square" alt="MIT"></a>
  <a href="SKILL.md"><img src="https://img.shields.io/badge/Agent-Codex-B87948?style=flat-square" alt="Codex"></a>
  <a href="ENVIRONMENT_COMPATIBILITY.md"><img src="https://img.shields.io/badge/Host-Windows%20x64-B87948?style=flat-square" alt="Windows x64"></a>
  <a href="https://github.com/Haruhi764/OmniSolidWorks-Skill/stargazers"><img src="https://img.shields.io/github/stars/Haruhi764/OmniSolidWorks-Skill?style=flat-square" alt="Stars"></a>
  <a href="https://github.com/Haruhi764/OmniSolidWorks-Skill/forks"><img src="https://img.shields.io/github/forks/Haruhi764/OmniSolidWorks-Skill?style=flat-square" alt="Forks"></a>
</p>

<h1 align="center">OmniSolidWorks-Skill — AI 机械建模与 SolidWorks 自动化</h1>

<p align="center"><strong>不止于建模，更让每一次装配与交付有据可查。</strong></p>

<p align="center"><a href="README.en.md">English</a> · <a href="SKILL.md">Agent Skill</a> · <a href="FINAL_ASSESSMENT.md">验收记录</a> · <a href="ENVIRONMENT_COMPATIBILITY.md">兼容性</a> · <a href="RELEASE_NOTES.md">发布说明</a></p>

面向 Codex 的 SolidWorks 原生机械建模与装配 Skill，通过本地 COM/API 构建参数化零件、多级装配、爆炸视图和工程图，并以实际几何、配合、BOM 与重开结果作为验收依据。

> V1.0.0 · 以 RC3 为技术基线。实测宿主为 SolidWorks 2014 x64 SP0（COM 22.0.0）。原生路线线持久化为实验性能力。

[下载正式版](https://github.com/Haruhi764/OmniSolidWorks-Skill/releases/tag/v1.0.0) · [快速安装](#安装与使用) · [工程案例](#工程案例--mechanical-portfolio) · [证据驱动](#证据驱动--evidence-driven)

## 核心能力 · Core Capabilities

| 01 / MODEL · 建模 | 02 / ASSEMBLE · 装配 | 03 / VERIFY · 验证 |
| --- | --- | --- |
| 原生特征、尺寸修改与重建 | 多级子装配、配合、爆炸步骤 | 几何回读、静态干涉、工程图与重开 |

**先看案例，再看验收。** 下方展示真实 SolidWorks 输出，而非概念渲染。

## 工程案例 · Mechanical Portfolio

### 01 / 三工位平行夹爪

正式独立盲测从 8 种参数化零件生成 3 个子装配和 18 个零件实例。顶层 5 步原生爆炸。第一角投影 A2 工程图含剖视、关联尺寸、8 行 BOM 和气泡。折合状态的原生实体干涉为零。

| 原生爆炸视图 | A2 原生工程图 |
| :---: | :---: |
| [![三工位夹爪真实爆炸视图](case-review/GripperExploded.png)](case-review/GripperExploded.png) | [![三工位夹爪 A2 工程图](case-review/GripperDrawing.png)](case-review/GripperDrawing.png) |
| [拆装步骤表](case-review/DisassemblySteps.csv) | [RC3 案例验收](V1_SCOPE.md) |

### 02 / 六工位装配与历史案例

<img src="assets/brand/omnisw-assembly.png" width="100%" alt="历史六工位装配的折合与爆炸预览">

[六工位折合](case-review/MultiStationCollapsed.png) · [六工位爆炸](case-review/MultiStationExploded.png) · [导向夹具 A3 图纸](case-review/GuideFixtureDrawing.png) · [导向夹具 BOM](case-review/BOM.csv) · [轴承座剖视](case-review/BearingBlockA2.png)

首页铜橙横幅中的六工位图与上述归档图为早期实机案例。三工位夹爪是后续正式盲测案例，实机工程文件和原始 COM 日志保留在本地验收环境。

## 证据驱动 · Evidence-Driven

<img src="assets/brand/omnisw-evidence.png" width="100%" alt="原生建模、实测、验收、重开">

| 环节 | 原生与自动验收证据 |
| --- | --- |
| **MODEL** | 参数化特征、体积、质心和几何尺寸。 |
| **ASSEMBLE** | 多级结构、组件引用、配合、变换及折合状态静态实体干涉。 |
| **VERIFY** | 参数修改与重建、错误输入拒收和 SolidWorks 原生读回。 |
| **DELIVER** | 保存关闭重开、工程图、关联尺寸、BOM 与气泡、检查点和文件 SHA-256。 |

| 状态 | 实测边界 |
| --- | --- |
| **PASS** | SolidWorks 2014 x64 SP0 上的已验收零件、装配、原生爆炸步骤和工程图工作流。 |
| **EXPERIMENTAL** | G06 原生路线线重开持久化未通过。拆装资料采用原生步骤、气泡和步骤表。 |
| **NOT VERIFIED** | 其他主版本或跨机器兼容性。 |
| **NOT SUPPORTED** | 连续实体扫掠碰撞与自动运动仿真。连续运动仅做 AABB 粗筛。 |

RC2 全量验收 90/100，RC3 的 24 项单测、113 项清单校验和独立安装是历史证据。部分夹爪配合保留平面内自由度；2014 的 `sldapiu.dll` 访问违规是已知宿主风险。 [最终验收](FINAL_ASSESSMENT.md) · [兼容性](ENVIRONMENT_COMPATIBILITY.md) · [已知限制](OPEN_ITEMS.md)

#### V1.0.0 · 实际验证记录

| **90/100** | **24** 项单测 | **SolidWorks 2014** |
| :---: | :---: | :---: |
| RC2 全量验收 | RC3 历史记录 | x64 SP0 原生实测 |

## OmniGB Core

对图纸尺寸链、重复跨度、纸面边界、BOM 和气泡一致性进行检查，并提供公开标准题录索引。公差、粗糙度及其他制造语义覆盖见[国标规则范围](GB_RULE_COVERAGE.md)。

## 安装与使用

从 [V1.0.0 Release](https://github.com/Haruhi764/OmniSolidWorks-Skill/releases/tag/v1.0.0) 下载正式 ZIP 并解压。

需要 Windows x64、Python 3.12+、Windows PowerShell 5.1 和已许可的 SolidWorks。打开空白 SolidWorks 会话，在解压目录运行。安装目标须为本地新目录。

```powershell
python -B scripts/v03_jobs.py --preflight
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\Install-SolidWorksSkill.ps1 -Destination 'D:\OmniSolidWorks' -Smoke
```

Python 未加入 PATH 时，可将完整路径传给 `-Python`。多会话可用 `SOLIDWORKS_TARGET_PID` 选择空白会话。卸载前备份需保留的 `outputs`，再删除独立安装目录。 [Skill](SKILL.md) · [操作指南](docs/V03_GUIDE.md) · [爆炸图指南](docs/EXPLODED_VIEW_GUIDE.md) · [安全审计](SECURITY_AUDIT.md) · [发布说明](RELEASE_NOTES.md)

## 官方技术交流群

<p align="center"><img src="assets/brand/omnisw-community.png" width="520" alt="OmniSolidWorks 官方 QQ 群 313181842"></p>

QQ **313181842**。建议附 CAD 版本、复现步骤和脱敏样例。项目有权授权的原创内容采用 [MIT](LICENSE)，第三方范围见[授权说明](THIRD_PARTY_LICENSES.md)。

---
<p align="center"><img src="assets/brand/omnisw-logo.svg" width="96" alt="OmniSolidWorks"></p>
<p align="center"><strong>OMNI · Model / Assemble / Verify</strong></p>
<p align="center"><a href="https://github.com/Haruhi764/OmniSolidWorks-Skill/issues">问题反馈</a> · <a href="https://github.com/Haruhi764/OmniSolidWorks-Skill/releases">版本下载</a></p>

## Omni 系列 · Two dimensions, one philosophy

| <a href="https://github.com/Haruhi764/OmniCAD-Skill"><img src="https://raw.githubusercontent.com/Haruhi764/OmniCAD-Skill/main/assets/omnicad-precision-crystal.svg" width="88" alt="OmniCAD"></a> | <img src="assets/brand/omnisw-logo.svg" width="88" alt="OmniSolidWorks"> |
| :---: | :---: |
| **[OmniCAD](https://github.com/Haruhi764/OmniCAD-Skill)** | **OmniSolidWorks** |
| 二维工程制图 · Draft / Verify / Deliver | 三维机械建模 · Model / Assemble / Verify |

