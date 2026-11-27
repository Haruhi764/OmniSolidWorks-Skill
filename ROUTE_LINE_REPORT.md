# V1.0 RC3 原生爆炸路线线 / Native explode route line

**G06 未通过 / Failed.** 实机宿主为 SolidWorks 2014 x64 SP0，COM `22.0.0`。诊断使用独立暂存 RC1 演示零件和装配，保留原始结果。Local COM tests used independent copies of the RC1 demonstration geometry.

经所选本机 PIA 核对，接口具备 `InsertExplodeLineSketch`、`InsertRouteLine`、`GetCorrespondingEntity`、`SelectByID2`、`GetSelectedObject6` 和 `GetActiveSketch2`。旧版官方示例传入强类型边和布尔数组，新版示例使用变体数组。Older and newer official examples show different array representations. 可查所安装版本的 API 帮助及样例。

| 取实体方式 / Entity acquisition | 两圆柱面 / Cylindrical faces | 两圆边 / Circular edges | 面与边 / Mixed |
| --- | --- | --- | --- |
| A · ComponentCylinder / GetBodies3 | True, 1 | True, 1 | False, 0 |
| B · GetCorrespondingEntity 到顶层 / top-level context | True, 1 | True, 1 | False, 0 |
| C · 装配选择及 SelMgr / selection manager | True, 1 | True, 1 | False, 0 |

数值为退出编辑前活动原生爆炸线草图内的线段数量。C 组以组件归属验证选择，坐标选择不足时用 `Select4` 后从 SelMgr 取回。原始记录保存实体 ID/类型和组件、转换或选择路径、展开/活动草图状态、参数数组类型及布尔位、返回值和 HRESULT。一次不同数组表示返回 True 但没有线段，判为失败。Counts are active native sketch segments. Each selection's component ownership was checked. API True with zero segments was treated as failure.

| 流程 / Workflow | 保存与重开 / Save and reopen |
| --- | --- |
| 强类型插入，结束原生草图，折合后 SaveAs / typed insertion and SaveAs while folded | 保存前按特征名、原生 FeatureManager 和段数找到了 `3D爆炸1:ExplodeLineProfileFeature:1`。SaveAs 和 OpenDoc6 无错误/警告。重开后轮廓为空，段的持久引用状态为 1。Native profile found before save and absent on reopen, despite clean save and open codes. |
| 结束原生草图后保持展开并原位 Save3 / in-place save while exploded | 保存和打开同样无错误/警告。重开并展开后，在首次强制重建前特征已缺失，重建后仍然缺失；持久引用未恢复。Profile absent before and after rebuild. |
| 对照官方 AutoExplode 流程 / AutoExplode control | 在尝试插线前报告 `0x80010105`（`RPC_E_SERVERFAULT`）。Previous manual-step controls therefore remain the direct evidence for insertion. The vendor tutorial assembly was outside this RC1 probe. |

这一阶段的证据隔离了数组及选择因素，并定位到本次宿主、文件和流程组合的保存重开边界。证据尚不能判定内部根因，也未完成可编辑性及两次独立冷启动通过。未将普通 3D 草图或工程图装饰线作为原生验证结果。


后续原厂球阀副本也复现持久化失败。RC2 最终对照将原生特征重命名再保存，磁盘字节发生变化，特征和持久引用仍在重开后丢失。RC3 继承该实验结论。采用原生爆炸步骤、BOM 气泡及[拆装步骤表](case-review/DisassemblySteps.csv)交付拆装信息。[当前验收](FINAL_ASSESSMENT.md)
