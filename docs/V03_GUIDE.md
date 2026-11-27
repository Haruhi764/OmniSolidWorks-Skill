# V0.3 能力与交付

运行 `python -B scripts/v03_jobs.py` 查看实际 COM 修订版。交互主机应有一个空白 SolidWorks 实例。用 `python -B scripts/v03_jobs.py path/to/job.json` 执行；MCP 客户端可用本机 Python 启动 `scripts/v03_mcp.py`，通过 `solidworks_environment`、`run_cad_job` 调用。安装目录和修订号可由 `SOLIDWORKS_INSTALL_DIR` 和 `SOLIDWORKS_REVISION_MAJOR` 移植配置；其他版本需重新验证。

| 任务 | SolidWorks 2014 实机能力 | 限制 |
| --- | --- | --- |
| 零件 | 凸台拉伸、旋转、端面贯穿切除、可编辑的矩形与圆轮廓、尺寸修改与恢复、原生 SLDPRT 和 STEP | 使用支持的特征与轮廓；复杂自由曲面、螺纹特征和通用图像直接建模仍待验证或实现 |
| 装配与爆炸 | 2 至 5 个实例的任务输入、同心／重合／距离配合、受支持的轴向爆炸步骤、保存重开及展收回读 | 验收样本为两件和四件；任意方向、多级子装配和爆炸线暂未支持 |
| 零件图 | A4/A3 横式 GB 图框、第一角法、主视、俯视、左视、等轴测、常规模型尺寸、关联厚度及孔径 | 标注编排与尺寸完备性以具体图样复核；一般公差和螺纹引注暂不自动生成 |
| 剖视和详图 | 已在轴承座验证关联剖视、详图和孔中心标记，剖面线和比例可回读与目检 | 目前限零件，使用中心截面和固定倍率策略；独立轴线、指定路径剖切和复杂详图排版未验收 |
| 装配图 | 关联装配正投影视图、爆炸等轴测、零件级 BOM、编号与原生引出线 | 已验证轴和法兰案例；多级 BOM、任意客户模板和多页未验收 |
| 交付格式 | SLDDRW 实机保存、关闭并只读重开核对；同一作业导出 DWG、DXF 和 PDF | DWG/DXF 已核验文件格式和哈希，独立 CAD 回读编辑尚未验证；PDF 用于出图审查 |

## 接单与接口

图片需注明来源、可读尺寸和无标注区域。工程文件先按可安全读取的类型和修订版分类，确认基准、材质、公差、螺纹规格、标题栏和签署要求。缺项集中列在单独的待确认文档。已知数据进入任务，交付物仅引用确认的工程内容。

作业公共字段为 `schema_version`、`job_id`、`document_type`、`units: mm`、`features`、`parameters`、`dependencies`、`outputs` 与 `validation`。`scripts/v03_schema.py` 是运行校验入口。工程图使用单项 `drawing_sheet`，纸型是 `auto`、`a4` 或 `a3`；可配置 `section`、`detail`、`center_marks`，装配可配置 `exploded` 和 `bom`。可提供确认的 `title`、`drawing_number`。第一项依赖是源模型，装配图后续依赖为其 `references/` 中的原始零件。所有依赖带 SHA‑256，使用 `outputs/v0.3` 下的相对路径。

`outputs/v0.3/jobs/<job_id>/<run>/` 内有正式文件、副本引用、原始 `native.json` 和摘要 `result.json`。交付时保持 `references/` 相对位置。新的参数版本使用新的 `job_id`；原 ID 和参数相同且文件哈希有效时可重用。未来 AutoCAD 集成可用作业类型、单位、交付件哈希与证据字段作为边界。
