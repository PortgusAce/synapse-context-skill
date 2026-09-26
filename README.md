# Synapse Context Skill

面向分支对话的文件用途与变更证据记录 Skill。

**状态：实验性、指令型 Skill 初稿。未完成 DeepSeek Harness / Synapse 运行时端到端兼容性测试。**

在一个对话分支处理文件任务时，记录任务开始时可观察的文件版本、实际变化与用途说明，使后续分支能够判断哪些资料仍有效。它适用于有文件读写能力、能够加载 SKILL.md 的 Agent。

参考上游：[liangmianya/dsh-synapse](https://github.com/liangmianya/dsh-synapse)。本项目是独立的工作流 Skill，未获上游背书，不是对 Synapse 插件的 fork 或已完成的 UI 扩展。

## 使用

Skill 位于 [skills/synapse-context](skills/synapse-context/SKILL.md)。将整个目录交给支持 Agent Skills 的宿主，按该宿主的文档安装或显式加载。目录内部使用相对链接，可以整体复制。

也可以在具备本地文件工具的 Agent 中请求：

> 阅读并使用 skills/synapse-context/SKILL.md，记录这次 CSV 导入修复的文件用途和变化。只纳入当前任务的源代码、测试和复现脚本。

此处没有未经验证的 `dsh plugin add` 命令。Skill 包不等于 DSH 插件，DSH 的安装/自动发现方式应按实际版本单独验证。

## 能做什么

- 为任务建立独立记录，并尽可能关联原生 session / turn / fork 信息。
- 对明确范围建立开始快照，收尾时核对文件变化。
- 为实验、产物和重要资源记录用途、状态、关联及证据。
- 在分支切换后提醒核实当前文件版本，发现记录过期。

## 边界

- 对话 fork 不会自动复制或隔离工作目录。共享目录中的变化可能来自其他分支或人工操作。
- 文件哈希与时间不证明变更作者，也不能恢复旧内容。
- 只有实际可见的会话 ID 才作为原生标识；无法取得时留空，使用本地 run_id 追踪。
- Skill 不保证每次自动执行，不常驻监控，不修改 Synapse 画布或内部存储，不自动删除临时文件。
- 自动版本关联与画布显示仍需后续运行时集成；当前不宣称与任何名为“Synapse 2.0”的版本兼容。

## 记录与验证

[记录约定与虚构示例](skills/synapse-context/references/record-format.md)说明观测事实与归属判断的区别。记录默认留在项目本地 `.contextos/`，使用前将它排除出项目公开提交；当前仓库已经忽略该目录。

公开演示使用虚构资料。真实文件内容、会话记录、绝对路径和任务日志不会因使用此 Skill 自动发布。

里程碑：先审阅流程与记录字段，再在已固定版本的 DSH/Synapse 上进行串行、fork、共享目录并发和中断恢复验证。当前没有 token 节省或准确率实验结果。

## License

MIT，见 [LICENSE](LICENSE)。
