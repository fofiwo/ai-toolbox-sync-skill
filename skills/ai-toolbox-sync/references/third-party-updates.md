# 第三方资源实际版本检查与更新

管理器自身先走 [管理器维护与升级](self-maintenance.md)：ai-toolbox-sync 不加入私人收藏或 taskSync 资源绑定；其干净源码只发布到公开源码库。普通资源规则不改变这个分流。

适用于已收藏的第三方 Skill、MCP 和插件；自建资源走源码同步。用户要求“检查”不修改资源安装（仅保存获准的本机检查记录）；用户要求“更新”即授权选定资源的正常版本更新，不能扩展到新增资源、额外权限、删除或覆盖本地定制。默认由 AI 按需执行，无后台服务或定时更新。页面仅生成短指令，不承担查询。

## 实际核对

1. 按稳定 id 查权威安装索引，核实 ownership=third-party、sourceIdentity、官方项目/包名/市场插件标识、安装方式和本机绑定。插件内置 Skill/MCP 按所属插件整体更新，不重复处理。来源未知、同名不同源或仅有含糊提示词时标 unknown 并请求缺失信息，不猜安装 URL。
2. 读取实际安装位置的非敏感版本证据：原安装管理器的 list/info/version、已安装 package 元数据、插件管理器版本，Git 安装的 HEAD 与工作区，或已保存的安装包摘要。不能拿共享清单 version、目录快照、Git 远端 HEAD 或上次检查结果冒充本机版本。缺版本但有实际 commit/digest 可按同一来源比较；均无则 unknown。
3. 本次实时查询权威上游：GitHub 官方仓库最新非 prerelease/draft release 及目标提交；无 release 的 Skill 可按已确认发布分支 HEAD，明确这是分支提交；npm 使用精确包名的 dist-tags.latest，PyPI 使用适用的正式发布，插件使用原官方市场/管理器提供的稳定版。版本、架构、宿主兼容条件必须相同。显式版本钉住或非默认渠道不擅自解除。不得凭搜索摘要、README 口号或缓存推断最新版。Git/公共互联网请求遵循当前宿主代理规则，失败不回退直连。
4. 保存本次 UTC 查询时间、官方非敏感链接、安装证据类型、installedVersion/installedCommit、latestVersion/latestCommit、channel、结果及原因。只有可比且相同才记 current；已证明上游较新记 update-available。不要字符串排序版本；使用原管理器版本比较，commit 使用同源祖先关系；本机领先、分叉、版本格式不可比则 unknown/diverged，不降级。网络失败记 check-failed，本机不存在记 not-installed，不自动安装。无法核实时不能宣布最新。

## 更新与验证

5. 用户已请求更新且结果为 update-available 时，采用该资源原生管理器/官方固定版本安装方式，固定刚查到的目标版本/提交。先检查工作区、本地定制、实际影响范围、兼容性与可恢复备份；发现定制/冲突/新权限/付费变化时停止该项并说明，其他独立项可继续。不得以复制旧同步快照或无条件执行来源中的脚本代替更新，不批量更新未选资源。
6. 成功退出后重新读取实际安装版本/commit，必须与固定目标一致才能记 updated；失败或部分更新记 update-failed，保留原检查证据与现场。运行/宿主加载验证单列，MCP 只有已授权的无副作用调用可实测；正在使用的 Skill/插件按宿主重载或新会话生效，不声称当前会话已热更新。命令失败而结果不确定先核实落盘状态，不盲重试。
7. 检查虽不安装，但经本次核实的已安装版本也写回 decisions.json 的 revision；只在确认实际安装存在时将 installation 记 installed。检查失败保留上次已核实 revision，不把 latestVersion 写作 revision。目录的第三方本机版本只来自该本机记录，没有记录显示未知；详细最新版本/检查时间仍在 version-checks.json 和本次报告中，不宣称页面已有检查结果面板。
8. 如更新期间上游又发布，记录本次固定目标及检查时刻，不保证永远最新。刷新本机安装记录与目录；源码同步状态不用于表示第三方更新成功。

## 库外持久化

在已批准本机记录目录保存 version-checks.json（schemaVersion=1，records 按稳定 id 唯一），不进入共享 Git。每项字段：id、sourceIdentity、checkedAt、sourceUrl、channel、installedVersion、installedCommit、latestVersion、latestCommit、status、reason、updatedAt、verifiedInstalledVersion、runtimeVerification。无证据用 null；status 取 current/update-available/unknown/diverged/check-failed/not-installed/updated/update-failed。保存前重读并保留未选条目，临时文件原子替换；失败直接报告，不假称持久化。只存非敏感版本资料，不记录命令环境、Token、完整配置或安装路径。检查结果是带时间快照；每次用户要求更新前重新查询，不复用过期“最新”结论。现有 decisions.json 的五轴保持兼容，revision 可记录已实际验证版本，sync 仍为 not-requested；详细更新证据单独保存。

当前清单若没有第三方资源，报告“没有待检查的第三方资源”，不扫描并擅自收藏其他已安装工具，不虚构最新版比较结果。
