# 同步前检查：人工执行的门槛，不是已经实现的自动保护

适用于 sync、pull、push --pull、安装后的 sync、更新、启用/禁用及恢复后的 sync。先检查再调用；dry-run 不能代替本地修改检测。本草稿不提供无人值守模式。

修改前先实时比较三层及可信基线；有差异先简述双方变更、建议理由并取得用户本次选择，才可执行相应入站更新，不默认云端较新；collect/commit/push 须由用户本次明确请求触发，不能因任务结束或已有持续权限自动执行。仅收集不上传。

任务路由与合作式锁见 [任务触发流程](task-sync.md)。本页全部 scope 检查继续适用；缓存命中不能替代推送前实时检查，流程辅助不代替人工审查。

## 必须先确认

1. 读取本次受管清单和本机明确绑定的配置路径；确认 CLI v0.26.1、实际 Git 根、远端、分支、上次应用状态。不要扫描完整宿主配置找凭证。配置/目标/缓存路径不得靠 HOME 推测。
2. 按下表展开实际命令 scope，检查其全部配置目标及副作用，不能只检查用户这次选中的一个资源或 Codex 目录。文件资源只允许已经核实指向受管源的 merge 链接，或经过逐项审查的新建空目标。目标不是预期链接、存在同名本地目录、来源不明时停止。**copy 模式一律停止应用**（含 Windows 文件链接降级成 copy）：本草稿尚无经过验证的副本漂移保护。MCP/插件按其原生预览和 ownership 检查，不把文件链接规则错误套到原生配置。不要建议 force、模式切换或删除目录绕过。
3. 核对 git status、tracked/untracked 路径以及待上传提交中的文件；也核对 fetch 后远端将引入的资源、清单与路径，不能只审上传。只允许已授权范围内的清单资源与已审核管理文件，未知新增资源先暂停应用。拒绝 .env*、凭证、安装缓存、机器状态、逃逸链接、嵌套 Git 指针。发现未知文件先停止，不读敏感内容、不用忽略规则掩盖已进入历史的内容。Skillshare push/commit 会 git add -A，不能只审核当前暂存区。还要将资源目录中的全部应保存文件与实际提交树逐项对账，不能只依赖 git status 或 git add -A：它们会遗漏被忽略的新文件。由 sync_session 的提交完整性校验阻断缺项；不得临时扩大 runtimeExclusions 使检查通过。
4. 将拟删除/重命名、过滤变更导致的移除、插件取消目标、MCP 删除全部单列。无对应删除授权就停止，不让隐式 sync 先执行。检查本地未提交变化，也检查相对共同祖先的本地和远端差异；无共同祖先或未知初始状态停止。
5. 在允许的联网范围内 fetch，记录检查的 remote tip。比较 merge-base 到本地（含待提交变化）和远端的文件列表。**任一 .metadata.json 两侧均有修改/删除就停止**，先人工核对条目；Skillshare 会按 installed_at 自动择一，不能未经审阅交给它解决。清单等普通文件冲突也停止。仅靠描述不能消除并发竞态；若远端在检查后变动，重新审查。不能宣称这个人工流程是有原子保护的一键执行器。

隔离调用时同时设置进程级 XDG_CONFIG_HOME、XDG_DATA_HOME、XDG_STATE_HOME、XDG_CACHE_HOME 和 SKILLSHARE_CONFIG。v0.26.1 的 git_root: root 使用 BaseDir，即 XDG_CONFIG_HOME/skillshare；**仅改 SKILLSHARE_CONFIG 不会改变这个 Git 根**。不要改 HOME 或 CODEX_HOME，也不要假定 config 文件所在目录就是 Git 根。测试目标路径必须显式指定。

## 命令范围必须与检查范围一致

| 实际命令（显式 -g） | 应用范围，必须全部检查 |
|---|---|
| sync | 当前配置全部启用的 Skill 目标及各自过滤后资源；不是“当前一个 Skill” |
| pull / push --pull，git_root 为空或 skills | 与普通 sync 相同的全部 Skill 目标 |
| pull / push --pull，git_root 为 agents | 全部 agent 目标；不只 Skill 目录 |
| pull / push --pull，git_root 为 extras | 全部已配置 extras 目标 |
| pull / push --pull，git_root 为 root | 依次全部 Skill、agent、extras 目标；extras 未配置时跳过；不含 MCP/hooks/plugins |
| sync --all | Skill、agent、extras、MCP、hooks 全部相关目标；不含 plugins；本草稿首期不使用这个扩大范围的快捷方式 |
| sync mcp / sync plugins | 按对应命令支持的实际目标选择核对；没有显式限制时不能假定只操作 Codex |
| push / commit（没有 --pull） | 不分发目标，但仍会 git add -A，审核整个 Git 根的新增、修改与待发送历史 |

依据 v0.26.1 [pulledScopeSyncArgs](https://github.com/runkids/skillshare/blob/v0.26.1/cmd/skillshare/pull.go#L169) 和 [sync](https://github.com/runkids/skillshare/blob/v0.26.1/cmd/skillshare/sync.go)。使用独立管理配置，不直接复用含额外 targets、agents、extras、hooks 的现有配置。root scope 下需确认有效 agent 来源/目标和 extras，即使本次只编辑 skills；未知或不在授权范围就停止，不能临时删掉真实配置来缩小范围。

同步还可能备份 Skill/agent 目标（含推导出的 agent 路径）、按保留策略清理旧备份，非 JSON 路径还可能清理过期 trash。将本机 data/state 内这些副作用也纳入检查；隔离测试使用新建目录，不代表已有备份可以删除。存在未授权读取/删除候选或不能确定时，暂停命令并列出具体范围，不靠 sync --dry-run 假定覆盖了全部清理。不要复用真实用户配置的备份/垃圾箱作为本草稿状态目录。

若预览或执行前配置/目标/远端发生变化，原检查失效，重新核对；人工流程仍无原子性或并发锁保证。CLI 不支持所需的细粒度限制时停止，不臆造 --target 参数。

## 正常同步

唯一执行顺序见 [任务触发流程](task-sync.md)：审核全部 scope → 显式 commit → 核对具体提交的文件完整性 → 实时探测 → 登记 intent → 不带 --pull 的 push → 再次探测、核验并 resolve。持续授权有效时不重复询问。不要把 push --pull 当作本流程捷径；pull/merge 及宿主应用是独立阶段，必须分别满足在用资源延期和全部目标检查。显式使用 -g 及已核实配置；上游文档只说明 CLI 能力，不替代本流程顺序。

执行后核对退出码、Git 状态、源内容及各目标结果。冲突停止后检查 merge 是否确实撤销；不以提示文字替代实际状态。保留本地提交，使用原生 Git 的正常冲突解决流程，不自动选择 ours/theirs、不 hard reset、不 force push。

pull 不应用 MCP/插件；sync --all 包含 MCP，但不含插件，且本草稿不使用这个扩大范围的快捷方式。MCP 与插件分别按对应命令预览和应用。处理真实 MCP 配置需要明确的字段级范围；不为导入而读取完整含凭证配置。未能安全取得非敏感定义时，请用户提供脱敏定义，其他资源可继续。

## 新电脑及恢复

在新的独立目录连接仓库，比较本机已有同名资源；禁止 init --remote 接管旧内容。建立本机宿主/路径绑定后再逐项应用。登录和信任由宿主完成，不迁移凭证。

恢复前保存当前变化；源码采用正常历史恢复并形成新提交。MCP 备份恢复不改变源定义，下一次 sync 前需核对二者。插件按已记录版本重建，不承诺原生缓存全部可回滚。删除仍需明确范围授权。

## 已知上游边界（v0.26.1）

- internal/sync/copy.go：受管副本源变更时会重复制，源移除时会清理，未核对副本编辑；collect 又跳过受管副本。
- internal/install/metadata_merge.go：同条目双边更改时取较晚 installed_at，平局取远端。
- cmd/skillshare/collect_shared.go：CLI collect 按 target 收集，不是逐 Skill 白名单。
- config.yaml 不进入默认 Git 同步；root scope 也排除它。推送前仍要检查历史，不只 .gitignore。
- 上游 run.sh 有隐式下载/升级；本草稿不调用。

## 第三方资源边界

源码同步仅允许权威清单 ownership=self 的已授权资源。开始/收尾均核对 taskSync.resourceIds、实际 source 内容、CLI 全部目标及待提交路径；第三方或归属未知资源混入时停止相关同步，不靠网页过滤代替执行检查。第三方 Skill/MCP/插件只登记安装来源与提示词，实际版本/安装状态留在库外；不 collect 或复制其目录。第三方最新版检查与更新独立走 [更新流程](third-party-updates.md)。授权只来自当前用户对具体仓库、分支、资源和操作的明确选择；不继承发布者的授权。


## 整份 Agent 文档资源

`kind=agent-document` 的身份、来源与精确目标规则见 [Agent 文档](agent-documents.md)。它不使用 Skill 的目录指纹、collect 或 agent 批量分发；使用专用全文摘要、独立文档绑定和 `agent_documents.py`。共享快照置于 `agent-documents/<documentId>.json`，不得放入 Skillshare 的 agents 来源目录或 targets。现有“仅自建源码同步”限制针对 Skill/MCP/插件，不禁止已获准的文档派生版本；派生来源仍须保留。

复用本页的仓库锁、远端检查、任务触发、提交/推送和 pending 流程。文档 `inspect` 返回的 installedDigest/sourceDigest 用于原 sync_session observation，bundleDigest 另作完整快照前置条件。全文已加载时可 collect 已授权本地修改，但入站 apply 延后；不能宣称当前会话重新加载了文档。导入新电脑默认派生新 documentId 与 installationId，不能复制旧机器的绑定。
