# 原生 Git 与资源应用

用户明确同步目录类自建资源与第三方来源索引时，首选 [sync_session.py 的收藏执行入口](task-sync.md#收藏同步执行入口)，由程序完成计划、精确提交、兼容合并与固定 SHA 推送。清单或绑定包含 Agent 文档时，使用既有 agent_documents.py 全文事务。本页 Git 命令保留用于审查和恢复，不要求每轮同步由 AI 手工重复编排；真实冲突仍保留双方。公开管理器维护继续使用独立 release.py。

ai-toolbox-sync 是独立项目。AI 直接调用 Git、本项目的 Python 脚本及资源官方安装器；同步不依赖其他工具箱管理器。Python 3.12+ 与 Git 是运行依赖；GitHub 接入使用 gh 或用户授权的官方网页登录。Node.js 仅用于本项目 JavaScript 测试，资源自己的依赖另行安装。

以下是参数形式，所有占位符必须替换为已核实值，以参数数组调用，不拼接不可信 shell 文本。先执行 [同步前检查](safe-sync.md) 与 [任务事务](task-sync.md)；命令说明不构成授权。Git hooks、外部 diff/filter、子模块和仓库脚本也是待审查代码，不因文件来自已授权仓库而自动执行。

## 新建与取得源码

- 新建：仅对本次获准的新空目录调用 `git init --initial-branch=<branch> <new-directory>`；由 AI 创建空 `toolbox.json`，没有自动发现、导入或宿主分发。
- 接入：仅在全新目录 `git clone --no-checkout --no-tags -- <verified-url> <new-directory>`。先读取固定提交的清单与路径，拒绝敏感/逃逸/链接/子模块路径；再检出审核通过的提交。已有目录不得用 clone、reset 或 checkout 接管。仓库源码检出与向宿主安装是两步。
- 已有仓库比较：`git -C <repo> fetch --no-tags --no-write-fetch-head -- <verified-url> refs/heads/<branch>`；随后 `ls-remote` 取得该分支 SHA，确认对象已取得且检查前后未改变。fetch 不合并、不更新安装目录。
- 原生 Git 说明：[clone](https://git-scm.com/docs/git-clone)、[fetch](https://git-scm.com/docs/git-fetch)。实际安装版本不支持所需参数时先核对本机帮助，不静默换成范围更大的命令。

## 提交、接收入站与上传

1. 核对实际 Git 根、branch、origin 的读取/推送 URL 和全部待发送历史。用 `status --porcelain=v1 --untracked-files=all`、`diff --no-ext-diff`、`diff --cached --no-ext-diff` 及具体提交树审查变化。暂存区有无关内容时暂停提交，不替用户取消暂存。
2. 只对已审查文件使用 `git --literal-pathspecs -C <repo> add -- <exact-file> ...`。删除单列获准后同样精确暂存。不使用 `add .`、`add -A`、`commit -a`，不通过宽泛目录夹带文件。被忽略但应保存的文件先核实原因与授权，不能省略或临时扩大排除项。
3. 核对暂存树只含获准变化，再 `git -C <repo> commit -m <message>`；没有变化不提交。作者信息缺失只确认必要署名，不猜邮箱、不写全局 Git 配置。保存真实 HEAD，执行本项目 `sync_session.py` 的 verify 完整性检查。
4. 用户已选择接收入站且工作区/暂存区干净、检查仍有效时，单边远端变化用 `git -C <repo> merge --ff-only <reviewed-sha>`。分叉时该命令拒绝；双边合并先由用户选择，按已审查差异执行普通 Git 合并，保留冲突现场，不自动 ours/theirs、rebase、reset 或强推。合并后重新核对实际文件及日志。
5. 用户本次已要求上传，实时检查远端、固定 HEAD 并登记 push intent 后，用 `git -c push.followTags=false -c remote.origin.mirror=false -C <repo> push -- <verified-url> <checked-head>:refs/heads/<branch>`。不加 `+` 或 force。Git push 本身不暂存、不提交、不安装资源；远端前进则重新比较。
6. 上传返回后重新 `ls-remote` 核验具体提交与文件；结果不确定先查实，不盲重推。GitHub 可读不等于 Git 可读；读取成功也不等于写入已验证。空库首次上传按 first-use.md 单独处理。

官方语义：[add](https://git-scm.com/docs/git-add)、[merge](https://git-scm.com/docs/git-merge)、[push](https://git-scm.com/docs/git-push)。公开管理器源码发布另受根目录 release.py 门禁约束，不能用本节命令绕过。

## 自建资源的收集与恢复

AI 只逐文件处理选定资源。清单与 `taskSync.resources` 明确 sourcePath、installedPath、稳定 id、可信基线及审定的排除项；不发现其他宿主目标，不修改现有链接形态。

- 收集：取得锁并比较安装、源与基线；登记 collect 意图后，把已批准的本机文件写入所选受管源。复核原源摘要未变、保存仅存在于本机的修改及必要依赖锁文件。仅收集不 commit/push。
- 恢复：Git 取得源码后，比较实际宿主目录。新目标也先核实路径、归属和链接；存在同名内容时说明双方新增/修改/删除，等待选择。按 `applicationMode=reviewed-files` 逐文件应用批准的内容，前后核对摘要。删除独立获准，不用目录镜像或整目录覆盖。没有可靠旧基线时不宣称可安全覆盖。
- 自建 Skill 保存完整目录；自建 MCP/插件保存完整源码和锁文件，按已审查项目说明安装必要依赖。凭证、机器路径与宿主注册在本机单独配置；MCP/插件加载使用对应宿主的官方接口，不提供虚构的统一命令，也不复制完整宿主配置。
- 第三方资源仅按已保存的官方来源及用户版本要求安装，核对实际版本；不从私人库分发第三方源码。Git 成功、文件恢复、依赖安装和宿主实际可用分别验收。

## 本项目文件执行器

资源复制使用本项目 [resource_files.py](../scripts/resource_files.py)，不需要其他工具箱 CLI。它只执行一个明确资源的获准文件计划，不读取整个清单、不决定授权、不自动提交/上传；本页及 task-sync.md 的锁、身份、基线和差异选择继续适用。

1. 先 `python <Skill>/scripts/resource_files.py plan --source <approved-source> --target <approved-target>`，把只读 JSON 计划保存在库外。恢复时 source 为固定提交的受管源，target 为宿主安装目录；收集时明确反向设置。已审定的排除项通过重复的 `--exclude` 传入，不能为通过检查临时扩大范围。
2. 向用户说明 changes 中的新增/修改/删除与覆盖损失，按其本次选择处理；计划生成不等于批准。取得事务锁并登记 collect/apply 意图后，用 `python <Skill>/scripts/resource_files.py apply --plan <reviewed-plan.json> --receipt <new-local-receipt.json> --backup <new-local-backup-directory>` 执行。仅计划中具体删除已获准才添加 `--allow-delete`。
3. 回执与备份必须在源码、安装目录及所有 Git 仓库之外，已有位置不覆盖。执行器重新核对完整计划与源/目标摘要，先保存将被替换或删除的原文件，逐文件复核并原子替换；任何漂移都停止。中断保留 incomplete 回执、completed 列表和旧文件，不自动回滚覆盖其他写者、不盲重试。AI 核实现场后再生成新的计划。
4. applied 仅表示审核文件计划已完成；再次核对源/目标摘要并执行 sync_session.py 的 verify/resolve，Git 与宿主实际加载另行核验。它不是目录级原子事务，不能阻止不遵守锁的外部写者。Agent 文档使用 agent_documents.py，不通过该目录执行器。

文件执行器的验证范围为 Windows，不将字节复制冒称跨平台可执行位、权限或宿主信任迁移已验证；MCP/插件的依赖与宿主注册仍按对应官方接口在本机完成。

## 旧绑定继续使用

保留原 Git 根、remote、branch、清单、稳定身份、基线、journal、workItems、binding-pointer 与 decisions。`paths.gitRoot`、authorization、taskSync 是现有脚本的有效契约。旧绑定的 cli、XDG 或旧管理配置字段只作为历史保留，本项目不调用、不删除、不重新初始化；新绑定只记录本机 Python/Git/gh 路径与实际 Git 根。身份或路径冲突时停止相关步骤，不能另建空库替代原收藏。
