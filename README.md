# Synapse Context Skill

为分支对话记录文件用途、生命周期和可核对的变化，让下一次任务知道哪些上下文仍然有效。

**v0.2 本地原型：Skill + Python 辅助脚本。无需安装 Harness、Synapse、Git 或第三方 Python 包，也不需要 API Key。** 真实 DSH/Synapse 会话集成与画布展示尚未完成兼容性验证。

参考上游：[liangmianya/dsh-synapse](https://github.com/liangmianya/dsh-synapse)。本项目独立维护，未获上游背书；它不是 DSH 运行时插件或 Synapse 的 fork。

## 给 Agent 使用

将整个 [skills/synapse-context](skills/synapse-context/SKILL.md) 目录按宿主支持的方式加载，或者直接请求：

> 阅读并使用 skills/synapse-context/SKILL.md，记录这次 CSV 导入修复的文件用途和变化。范围包括 src、tests 和 experiments。

辅助脚本随 Skill 携带。只需 Python 3.10+ 和宿主正常的文件访问权限；无需先安装到全局目录。宿主能否自动发现 Skill 属于另一层接入验证，不能从脚本运行成功直接推断。

## 手动运行

在本仓库根目录执行下面的 PowerShell 示例，将项目路径替换成实际目录。返回的 run_id 用于后续命令。

```powershell
$helper = Join-Path (Get-Location) 'skills/synapse-context/scripts/context_ledger.py'
$project = 'D:\Projects\demo'
$run = python $helper start --root $project --include src --include tests --include experiments --label 'CSV 导入修复' | ConvertFrom-Json

# 正常完成实际开发任务；文件存在后再记录用途。
python $helper note --root $project --run $run.run_id --path experiments/reproduce.py --purpose '复现 CSV 编码错误' --lifecycle temporary
python $helper finish --root $project --run $run.run_id
python $helper report --root $project --run $run.run_id --limit 30
```

其他 shell 调用同一 Python 脚本即可；`python ... --help` 查看入口。`--include` 是相对文件/目录路径，可以重复，不使用通配符；`--exclude` 是附加通配规则。计划新增的目录可在开始时纳入。已经修改后才启用记录时，加 `--late` 明示早期变化缺失。

| 命令 | 行为 |
| --- | --- |
| start | 保存任务范围和开始快照，返回唯一 run_id |
| note | 给范围内已有文件追加用途与状态，绑定实际内容哈希 |
| finish | 核对新增/修改/删除/未知变化；首次结果固定，重复调用幂等 |
| report | 生成有限大小的 JSON 交接信息，检查最新漂移与过期备注 |

原生标识由 `--session-id`、`--turn-id`、`--parent-session-id`、`--fork-anchor` 传入，仅在宿主真实提供时填写。默认空值；本地 run_id 不冒充原生分支 ID。

## 能力与边界

- 支持普通目录和未提交文件，不依赖 git log。记录 SHA-256、路径、用途及观测缺口，不保存正文副本。
- 只写本地 `.contextos/` 记录，创建其内部忽略规则；不改源码、不执行测试、不自动提交或发布。
- 默认排除自身记录、常见依赖/生成目录及常见凭证文件名。规则不等于完整秘密检测，也不是权限沙箱。
- 文件无法读取时保留 unknown 和错误信息，不把读取失败静默当作删除。两次快照之间的短暂变化不可恢复。
- 对话 fork 不隔离文件。两个运行可观测同一次修改；自动变更均标为 observed_only，不声称作者身份。
- 移动按新增/删除呈现；临时状态只提示复核。目录备注继承、工具因果归属、watcher 和 Synapse 画布附件暂未实现。
- 详见 [记录与恢复约定](skills/synapse-context/references/record-format.md)。

## 测试

```text
python -m unittest discover -s tests -v
```

测试使用临时虚构项目，覆盖中文路径、非 Git 文件变化、幂等结束、备注失效、范围与默认排除、读取错误、重叠运行及中断恢复。可通过 `SYNAPSE_TEST_TMP` 指向已存在、可写的测试目录。

本地验证环境为 Windows / Python 3.14。不能创建符号链接的系统会跳过真实链接测试；不会把跳过项报告为通过。当前没有模型效果、token 节省或 DSH/Synapse 端到端测试结果。

下一阶段再安装并固定 Harness / Synapse 版本，核实 Skill 加载和会话标识。Synapse 原生画布需要 Harness，参见其[安装要求](https://github.com/liangmianya/dsh-synapse#快速安装)；这不是本地脚本的前置依赖。

## License

MIT，见 [LICENSE](LICENSE)。
