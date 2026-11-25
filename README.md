# global-subagent-rules

Hermes 插件：为所有子 Agent 提供共享的回报规则，并提供一个手动的委派模型选择器（`hermes subagent-model`）。

Hermes plugin for shared subagent reporting rules and manual subagent model selection.

插件版本 0.6.0。功能：

1. **子 Agent 回报规则** — 由 `delegate_task` 派生的子 Agent（会话 platform 为 `subagent`）在新会话启动时，系统提示中会附加插件目录内 `SUBAGENT.md` 的内容。主 Agent 的提示词不受影响。
2. **委派模型选择器** — `hermes subagent-model show / pick / set`，查看、交互选择或一次性设置子 Agent 使用的 provider、模型与推理档位，结果写入 `config.yaml` 的 `delegation` 段。

## 环境要求

- Hermes Agent（`hermes` CLI）。全部命令与行为基于 Hermes 0.23.4 核对；其他版本未经验证。
- 插件为纯 Python，无外部依赖（`plugin.yaml` 未声明 Python/Node 依赖）。

## 安装

```bash
hermes plugins install Everwalker/hermes-global-subagent-rules
```

安装完成后会询问 `Enable 'global-subagent-rules' now? [y/N]`，**默认不启用**。也可以：

```bash
hermes plugins install Everwalker/hermes-global-subagent-rules --enable     # 安装并请求启用
hermes plugins install Everwalker/hermes-global-subagent-rules --no-enable  # 只安装，不询问
```

需要可复现的安装时，用完整 40 位 commit SHA 钉版本（不接受 tag、分支或缩写 SHA）：

```bash
hermes plugins install Everwalker/hermes-global-subagent-rules --ref <40位完整SHA>
```

钉版本的插件不会被 `hermes plugins update` 移动；换版本需显式 `hermes plugins install <source> --force --ref <新SHA>`。

手动安装（不用 Hermes 安装器）也支持：把本仓库克隆为 `~/.hermes/plugins/global-subagent-rules/`，再执行 `hermes plugins enable global-subagent-rules`。Hermes 的用户插件按 `plugins.enabled` 白名单启用，手动放入后仍需 enable 一步。

## 启用、禁用与 profile

插件的启用状态是**每个 profile 各自独立**的。每个 profile 是独立的 Hermes home（各自的 `config.yaml`、`.env`、`plugins/`），安装与启用互不继承：

```bash
hermes plugins                        # 交互式勾选启用/禁用
hermes plugins enable global-subagent-rules
hermes plugins disable global-subagent-rules
```

- 给某个 profile 安装：`hermes --profile coder plugins install ...`，或用 profile 别名命令 `coder plugins install ...`。
- `hermes profile create work --clone` 会把当前 profile 的 `plugins/`（含安装记录）一并复制到新 profile，之后仍需在该 profile 里启用。
- 非默认 profile 若在自己的 `plugins/` 下有同名插件，profile 自身的副本优先。
- 若该 profile 设置了 `plugins.isolation: host`，`hermes subagent-model` CLI 命令不会注册（此模式下 Hermes 跳过 `register_cli_command`），回报规则注入仍然有效。

## 功能 1：子 Agent 回报规则

注入的规则文本就是插件目录里的 `SUBAGENT.md`，**修改这个文件即自定义规则**——这是唯一的规则路径，没有单独的配置键。文件随插件安装到 `~/.hermes/plugins/global-subagent-rules/SUBAGENT.md`（profile 安装时位于该 profile home 下）。

默认内容为两条回报要求：在任务范围内完成工作和必要验证、简洁报告结论与证据位置；如实保留失败与 UNKNOWN 状态、默认不粘贴完整日志。

规则生效的边界（来自 Hermes 系统提示区块机制）：

- 区块只在**新会话创建时**渲染一次；已存在的会话（包括上下文压缩后、进程重启续用的会话）保留旧的文本。改完 `SUBAGENT.md` 后从下一个新子 Agent 会话开始生效。
- 单个区块最多 4 000 字符；所有插件区块合计上限 8 000 字符、最多 32 个。超限或读取失败的区块会被跳过，并在会话启动时给出警告。
- 区块插入位置固定在 memory/profile 上下文之后，插件无法影响其他提示词内容的顺序。
- `hermes plugins update` 会先自动 stash 本地改动，更新后尝试重新套用；若发生冲突，改动保留在 git stash 中，但不会自动生效。`--force` 重装时，被跟踪文件的改动会先备份到 `~/.hermes/plugins-backup/<插件名>-<旧SHA8>/`。

## 功能 2：hermes subagent-model

```bash
hermes subagent-model show   # 只读：显示当前委派后端、模型 pin、fallback 链数量、主模型
hermes subagent-model pick   # 交互选择 provider → model → reasoning effort，确认后写入
hermes subagent-model set <provider> <model> [--effort <level>]   # 直接写入一次
```

也可在 Hermes 桌面端的 **Settings → Model → Subagents** 使用 Hermes 自带的模型选择界面。选择适用的 profile 后，设置对之后启动的子 Agent 生效。

`--effort` 取值：`minimal | low | medium | high | xhigh | max | ultra | none`；省略表示保持当前档位，`none` 表示显式关闭子 Agent 推理。

写入行为（与 Hermes 0.23.4 源码核对）：

- 只写 `delegation.provider` / `delegation.model` / `delegation.reasoning_effort` 三个键，以 Hermes 的配置写入方式合并；`delegation` 段的其他键（`fallback_providers`、`base_url` 等）保持原值。这不是跨进程写入锁，同时修改同一配置文件时仍可能发生覆盖。
- 两种情况会**拒绝写入**并给出解决命令：`delegation.backend` 不是 `default`（非默认路由策略不读这几个键）；`delegation.base_url` 固定了端点（改 provider/model 会造成端点与模型不匹配）。分别用 `hermes config set delegation.backend default`、`hermes config unset delegation.base_url` 自行处理后重试。
- 不改动主模型；不显示、不新增任何凭据；已有的 `delegation.fallback_providers` 链保持生效，命令只会提示其条目数。
- `pick` 沿用 Hermes 自身的模型选择守卫（成本/数据策略警告）；取消或跳过均为 No change。

不用插件也可以直接通过 Hermes 原生配置达到同样效果：

```bash
hermes config set delegation.model <模型id>
hermes config set delegation.provider <provider id>
hermes config set delegation.reasoning_effort <档位>
hermes config unset delegation.model          # 移除 pin，恢复继承主模型
```

Hermes 对子 Agent 的路由规则（供理解 pin 的实际效果）：`delegation.base_url`（直连端点）优先，其次 `delegation.provider`（按运行时 provider 系统解析完整凭据束），两者都未设置时子 Agent 继承父级 provider；`delegation.model` 在任何分支都生效，为空时继承父级模型。推理档位优先级为：委派后端的任务级档位 > `delegation.reasoning_effort` > 父级档位。

注意 pin 是全局的：默认委派策略下 `delegate_task` 没有按任务指定模型的参数，同一 profile 的所有子 Agent 使用同一个 pin。需要按任务路由时请使用委派策略插件（`delegation.backend`）或 kanban 的按任务模型覆盖。

## 更新与卸载

```bash
hermes plugins update global-subagent-rules
hermes plugins remove global-subagent-rules   # 同时从 plugins.enabled/disabled 中移除
```

## 常见问题

- **装完没效果**：安装后默认不启用。用 `hermes plugins list` 查看状态（`not enabled` 即未启用），执行 `hermes plugins enable global-subagent-rules`。
- **`hermes subagent-model` 不在帮助里或不存在**：插件未启用，或该 profile 配置了 `plugins.isolation: host`（此模式不提供插件 CLI）。
- **子 Agent 没有带上规则**：确认规则注入后开的是新会话（老会话不会重新渲染）；确认 `SUBAGENT.md` 未超过 4 000 字符；确认子 Agent 确实由 `delegate_task` 派生（规则只注入 platform 为 `subagent` 的会话）。
- **怀疑插件加载失败**：`hermes plugins doctor global-subagent-rules` 会在隔离环境里重跑发现、manifest 解析与注册流程。

## 兼容性说明

- 安装、启用与两个功能的全部命令基于 Hermes 0.23.4 的官方文档与源码逐条核对；其中 `hermes subagent-model show` 已在本机 0.23.4 上实际运行验证。未在其他 Hermes 版本上验证，跨版本行为不在此文档承诺范围。
- 模型候选列表全部来自本地已有数据（`config.yaml` 声明与 profile 的 provider 模型缓存），本插件自身不联网拉取模型列表；缓存里没有的模型需要手动输入模型 id。
