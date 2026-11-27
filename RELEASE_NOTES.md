# OmniSolidWorks Skill V1.0.0

OmniSolidWorks 通过本机 SolidWorks COM/API 生成可编辑参数化零件、多级配合装配、原生爆炸步骤及关联工程图。V1.0.0 以 RC3 为技术基线，整合品牌、文档、许可及分发文件。

- **Model / Assemble / Verify / Deliver**　核对原生几何与参数修改、层级引用与配合、折合实体静态干涉、负面测试、重开读回、工程图与 BOM，以及检查点和文件哈希。
- **实机案例**　三工位平行夹爪包含 8 种参数化零件、3 个子装配、18 个零件实例及 5 个顶层原生爆炸步骤。A2 工程图含剖视、关联尺寸、BOM 和气泡。RC2 全量验收 90/100 与 RC3 的 24 项单测、独立安装和原生重开是既有验收证据。
- **安装**　使用 Windows x64、Python 3.12+、Windows PowerShell 5.1 和已许可 SolidWorks。在解压目录运行 `python -B scripts/v03_jobs.py --preflight`，随后调用 `scripts/Install-SolidWorksSkill.ps1`，提供本地新目录并使用 `-Smoke`。核对随附的 `SHA256SUMS.txt`。
- **已知限制**　实机范围为 SolidWorks 2014 x64 SP0（COM 22.0.0）。其他版本或跨机器没有完成同等实机验收。G06 原生爆炸路线线重开持久化未通过，仍为实验性功能。稳定拆装资料包含原生步骤、气泡和步骤表。部分配合保留平面内自由度。连续运动仅做 AABB 粗筛。SolidWorks 2014 的 `sldapiu.dll` 访问违规为已知宿主风险。
- 项目有权授权的原创内容采用 MIT。第三方来源、标准和 SolidWorks 的权利按各自条款处理。官方技术交流群 QQ **313181842**。

## English

OmniSolidWorks uses local SolidWorks COM/API to build editable parametric parts, nested mated assemblies, native explode steps, and linked drawings. V1.0.0 integrates the approved brand, documentation, licensing, and distribution files with the RC3 technical baseline.

- **Model / Assemble / Verify / Deliver.** Read back native geometry and parametric edits, assembly references and mates, static solid interference, negative checks, drawings, BOMs, and reopened files. Checkpoints and file hashes preserve traceability.
- **Verified example.** The three-station gripper has eight distinct parts, three subassemblies, 18 part occurrences, and five top-level native explode steps. Its A2 drawing contains a section view, linked dimensions, BOM, and balloons. The RC2 score of 90/100 and RC3’s 24 unit tests, independent installation, and native reopen are inherited acceptance records.
- **Installation.** Use Windows x64, Python 3.12+, Windows PowerShell 5.1, and licensed SolidWorks. Run `python -B scripts/v03_jobs.py --preflight` from the extracted folder. Run `scripts/Install-SolidWorksSkill.ps1` with a new local destination and `-Smoke`. Compare the archive with the accompanying `SHA256SUMS.txt`.
- **Known limits.** Live verification covers SolidWorks 2014 x64 SP0 (COM 22.0.0). Other releases and machines lack equivalent verification. G06 native route line persistence remains experimental and failed reopen. The stable workflow uses native explode steps, balloons, and a disassembly table. Some mates retain in-plane freedom. Continuous motion is screened with AABBs. SolidWorks 2014 has a known `sldapiu.dll` host fault.
- MIT applies to original project material the owner can license. Third-party material and SolidWorks retain their respective terms. Official technical QQ group **313181842**.
