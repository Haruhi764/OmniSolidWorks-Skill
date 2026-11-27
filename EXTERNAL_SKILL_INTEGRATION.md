# 外部 Skill 调查与融合

| 来源 | 核查 | 本轮处理 |
| --- | --- | --- |
| SolidCraft 上游 | 真实 Rust CAD 项目。本地与云端共用命令，建模 Skill 位于 `skills/solidcraft-modeling/SKILL.md`，另有编辑 Skill。上游活跃，支持离线比较分析值与实际值、批处理和编辑后检查。代码 MIT 或 Apache-2.0，品牌及部分资源另有条款 | 独立增加同单位几何质心和两种 SolidWorks 体积读回的交叉核对。用上游的先验数值与阶段验收思路验证参数编辑和错误注入 |
| ArtCraft Skills | 独立 Skill 集合。其 SolidCraft 条目记录上游版本和提交指纹，仓库标为 MIT。属于工具使用说明和证据索引 | 仅用于辨认真实 Skill 和理解宿主版本限制。在报告中注明候选宿主和执行来源 |
| 中国机械制图参考包 | 11 项条目，核对主 Skill、README、图样数据库、Python 制图库、演示测试、规范说明及 AutoCAD 导出路径。包内未见独立许可证 | 独立编写 OmniGB Core。迁移了尺寸链无环及完整性检查、估计字宽、分层和原生数据回读比对的思路。参考库、示例和数据库继续隔离 |

既有 V0.9 已有独立体积和包围盒、参数编辑、检查点发布、结构化日志、有限重试和原生状态清理。本轮沿用这些模块。SolidCraft 的事务批处理及小响应机制属于它的 MCP 引擎；SolidWorks 继续通过本机 STA COM 和已校验的作业检查点执行。原生体积、质心和形体证据来自 SolidWorks。依赖图的全量删除影响验证仍开放。

外部技术入口见 [SolidCraft 建模](https://github.com/tangency-labs/solidcraft/blob/main/skills/solidcraft-modeling/SKILL.md)、[SolidCraft 编辑](https://github.com/tangency-labs/solidcraft/blob/main/skills/solidcraft-editing/SKILL.md) 和 [ArtCraft Skills](https://github.com/midasmatterhorn/artcraft-skills)。
