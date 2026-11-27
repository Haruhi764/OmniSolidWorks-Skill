# V1.0.0 验收范围 / Acceptance scope

适用宿主为 SolidWorks 2014 x64 SP0，COM `22.0.0`。项目所有者已确认原创内容的 MIT 许可。以下实机能力继承自 RC2。见 [RC2 全量评分](V1_ACCEPTANCE.json) 和 [RC3 增量验收](FINAL_ASSESSMENT.md)。

- 三工位合成夹爪含八种独立参数化零件、三个独立子装配和 18 个零件实例。站位 X 为 -90、0、+90 mm。顶层 5 个距离配合，各子装配 4 个距离配合；它们约束指定的轴向距离，仍存在平面内自由度。
- 顶层有 5 步原生爆炸，每个子装配有 4 步。保存重开后核对展开位移与折合恢复。顶层原生静态实体干涉验收为零。连续运动扫掠仍只做 AABB 粗筛。
- A2 原生总装图含主视、俯视、侧视、等轴爆炸、剖视、两条关联尺寸、零件明细表和气泡。BOM 由递归零件统计交叉验证，故意输入错误数量会被拒收。
- G06 为实验性功能且未获分。RC2 最终试验成功重命名原生特征；保存、关闭、重开后特征和持久引用均缺失。稳定输出包含原生可编辑爆炸步骤、图纸气泡及独立步骤表。步骤表的距离是从经过原生位置核验的步骤合同读回的目标值。
- 项目所有者已授权发布有权授权的内容。归档仅以已验证的 RC2 为基线，不包含原厂样件、外部机器人资料、私有 COM 日志、PIA 和原生 CAD 文件。使用包含的脚本可以在安装后重建自有案例。

This candidate was verified on SolidWorks 2014 x64 SP0 (COM 22.0.0). The synthetic blind case has eight distinct part files, three independently generated assemblies, 18 leaf instances and five top-level native distance mates. Each module has four native distance mates. In-plane degrees of freedom remain. Five native top-level and four native per-module explode steps survive reopen. Native static interference is zero in the folded top-level assembly. The A2 drawing contains a section, two associated dimensions and an eight-row, 18-instance BOM linked to item balloons.

G06 is experimental and failed persistence. The stable documentation workflow uses native explode steps and item balloons alongside a separate verified disassembly table. The owner approved MIT for authorized original project content and authorized public release.

历史宿主故障复现为 `sldapiu.dll` 访问违规 `0xc0000005`。RC2 已验证的检查点保持完整，通过新的空白 2014 会话继续回归。该宿主故障仍可能发生。
The host reproduced the historical `sldapiu.dll` access violation. Verified checkpoints were preserved and regression proceeded on a fresh empty 2014 session. The vendor-side fault remains a known limitation.
