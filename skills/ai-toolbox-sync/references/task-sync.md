# 任务触发同步（完整性加固协议）

## 收藏同步执行入口

已明确同步收藏时，优先使用下列入口；不再让 AI 逐个拼接 observe/intent/Git/resolve。下文低层 API 保留给历史事务恢复、编辑登记与独立安装应用，不能覆盖本节已授权兼容合并的规则。

```powershell
python -B <Skill>/scripts/sync_session.py status --binding <本机绑定.json>
python -B <Skill>/scripts/sync_session.py sync --dry-run --binding <本机绑定.json>
python -B <Skill>/scripts/sync_session.py sync --binding <本机绑定.json>
```

省略 binding 时复用本机定位指针。`status` 只读本机，明确返回 remoteVerification=not-queried，不将本地 origin 引用或旧记录冒充实时云端。`sync --dry-run` 实时核对远端并取得比较对象，用临时索引和 Git merge-tree 生成计划；不修改实际 HEAD/暂存区/安装、不创建提交、不上传，会保留检查日志与 Git 对象。`sync` 只在本次同步授权内执行；仅收集、仅检查和普通编辑任务不能调用写入模式。

执行器复用仓库锁和原绑定，依次检查范围、安装/受管源、暂存区、历史与敏感路径，生成三方合并结果；通过检查后精确提交本机变化、快进或普通合并、核对提交覆盖、实时重查远端、推送固定 SHA 并核实结果。没有变化不造提交。自建安装修改只有在可信基线证明受管源未变时才逐文件收集，复用文件执行器和库外备份；无可信基线保留两边。第三方只同步安装来源索引，不复制其源码。

清单按稳定 id 做三方合并；不同资源的新增、不同字段的兼容修改可继续，同一字段冲突、修改与删除冲突、kind/sourceIdentity/ownership/contentPath/parentId 变化停止。源文件由 Git 合并，不以“同文件双边变化”直接判冲突。检查 Git 合并后的清单、身份、路径、文件摘要和提交树；相关功能测试仍由 AI 按影响执行，不声称 Git 无文本冲突等于功能正确。

默认范围为已绑定资源源码、toolbox.json 和 README.md。确有本次授权的额外管理文件，通过 `--paths <精确文件...>` 指定；每一文件删除用 `--allow-delete <精确文件...>`，每一资源取消收藏用 `--allow-remove <稳定id...>` 单列批准。不使用目录、通配符或 force 绕过范围检查。已有非空暂存区、旧未完 Git 意图、未知安装漂移、链接、敏感文件或自定义过滤器/合并驱动停止并保留。执行器不执行仓库 hook、自动 stash 或强推。

远端检查前配置当前操作所需的授权凭证助手；已有 gh 登录可使用进程级 Git credential helper，不能读取/输出 token、重设全局 Git 配置或自动登录。网络失败只按宿主规则切换一次连接，认证/权限失败不当作网络错误重试。

库外 journal 旁的 sync-runs 保留本次计划、具体提交及阶段。提交后远端前进，返回 remote-advanced 并保留本机提交；重新执行同一入口再次比较，不要求用户为可兼容变化重新授权。push-pending 可能表示远端已经收到，重入先读真实远端，内容一致时不重复提交/推送。失败和真实冲突保留现场，不自动回滚或重置。上传核验与本机状态写回之间仍存在外部写者竞态。

Git 同步成功不自动覆盖独立安装目录。报告 installations 中 equal/source-only 等真实结果；需要安装时仍按本页“独立宿主目录的审核应用”执行并保留在用保护。执行器只建立已核实一致资源的基线，不清空其他 owner 的 workItems、旧管理器记录或用户决定。核对相关任务已结束且具体内容确已上传后才完成对应待办，再用原清单和本机记录重建库外收藏页。网页、安装收据与宿主加载分别验收。

管理器自身先走 [管理器维护与升级](self-maintenance.md)：ai-toolbox-sync 不加入私人收藏或 taskSync 资源绑定；其干净源码只发布到公开源码库。普通资源规则不改变这个分流。

## 先确定“同步”的目标与完成标准

先按 [Skill 首页](../SKILL.md#同步前先分流) 区分管理器自身与收藏工具；未明确时先询问，再进入本流程。即使只有一个私人绑定、存在待上传内容，也不能据此把“同步 toolbox”解释为上传收藏。管理器更新不要求先配置私人绑定或登录私人库。

已确定为收藏工具同步时，优先复用当前已确认的资源、仓库、分支、方向与操作范围。区分本机分发、工具箱 Git 上传/拉取、第三方官方更新和向项目源码库提交修改；这些不是同一操作。只有一个已确认绑定且范围明确时直接执行；没有绑定或多个候选时，先只读核实非敏感本机定位信息，再就缺失目标给具体选择；选定并获准后才读取相应私人清单与远端差异，不把公开安装源自动当作上传目标。

第三方安装包的本地修改仍保留原来源。用户可明确选择将改动贡献到该项目源码库，或将其他工具作为已确认的定制身份同步到指定私人库（本管理器除外）；需要核对该库中的资源身份及本机映射，不能仅凭同名就改 ownership=self 或上传第三方整包。已登记的定制版本保留其原功能和历史，先提出合并建议，有冲突按下文让用户选择。项目源码维护使用该项目既有 Git/发布检查，不为此伪造工具箱绑定或初始化其他管理配置；工具箱资源同步继续遵循本文绑定、锁与完整性检查。

用户本次明确要求上传已选资源，可更新此前仅恢复的操作范围，但不扩大到其他资源、仓库、公开发布或凭证。绑定定位失败须报告“未建立/未能读取绑定”及实际原因，不能把错误当作没有变化或同步成功；可继续准备可审阅差异，不静默另建绑定绕过。

依次区分检查完成、本机纳入/提交、远端上传、目标安装与宿主实际加载。上传成功须实时查询授权分支，核实远端包含本次具体提交及选定文件内容；远端若前进，核实提交祖先关系和内容，不简单判失败或重推。命令退出成功、网页可见、邀请接受、文件保存或本地 HEAD 改变均不足以单独证明同步成功。凭证、机器路径和宿主配置继续留在库外。

## 触发策略（手动上传）

本节是任务路由的统一规则，覆盖旧授权中“任务结束自动上传”的触发方式；已有库/分支/资源权限继续有效，但不代表本次要求上传。没有后台监控、轮询或自动收尾。

| 用户行为 | 执行 |
|---|---|
| 仅使用 Skill/MCP/插件或读取文档 | 直接使用，不调用同步检查，不联网，不扫描待办 |
| 准备修改资源 | 先以本机绑定/同步清单判断是否纳管；未纳管不联网。已纳管的自建资源/自己绑定的文档，按下文实时比较；有差异先简述双方变化及建议理由，由用户选择后再编辑 |
| 已纳管资源修改任务本轮结束（包括阶段性结束） | 有实际改动且未同步时，仅在最终回复末尾提醒一次“本轮改动尚未同步，是否现在同步？”；不主动 collect、commit、push，不因回复结束标记完成。用户已说稍后/不同步则本轮不再问 |
| 安装外部 Skill 等资源完成 | 对尚未纳管且没有拒绝/待定决定的资源，按 after-change.md 集中询问是否纳管；加入只表示收藏，不自动上传 |
| 新建 Skill（包括为验证新建 Skill 而顺带安装） | 不主动收集、不询问纳管或同步、不监控；等待用户主动要求收集/同步 |
| 用户主动要求收集、同步、检查更新或换机恢复 | 只执行所请求动作与范围；仅收集不上传，仅检查不安装，恢复先选资源；同步请求范围清楚时直接执行，不重复询问已有权限 |

“先同步到最新”必须先按下节比较与选择，不能把云端当权威新版本；不是安装第三方 latest。编辑前 probe 必须 strict=true，不能用 24 小时缓存证明最新。已存在本地未同步改动时保留并比较，不覆盖；需合并、删除或其他聊天仍在编辑时暂停相关入站更新，说明原因。网络失败也不能宣称最新；可继续不依赖远端的本地工作并注明未更新。正在加载的资源不热替换（包括本管理器自身）；有入站更新时延后应用，不能假称当前会话已刷新。

新会话接手编辑时重新检查现场；workItems 只表示尚未核实同步的改动，不代表原聊天仍在运行，也不是自动上传指令。核对负责方避免并发修改，已结束任务的待办保留至用户主动同步后核验完成。只有未完成 Git 意图需要先核实真实结果；未经本次同步请求不得借“恢复”重试 push。



## 比较与选择（先比较，不默认云端更新）

比较实际安装目录、受管源（含暂存、未暂存、未跟踪文件）与已核实远端提交，以最后可信同步基线及 Git 共同祖先判断变更方向。版本号、文件时间、提交时间或云端位置都不能单独证明谁较新。Git HEAD 相同也不能忽略安装目录尚未收集的改动。必要 fetch 只取得比较对象，不 pull、merge 或应用文件。

| 比较结果 | 建议与处理 |
|---|---|
| 内容一致 | 无需选择，直接继续修改，不造同步 |
| 只有本地变化（含忘记上传） | 说明本地新增/修改/删除，建议保留本地继续；不得用云端旧内容覆盖 |
| 只有远端变化 | 说明云端新增/修改/删除，建议采用云端；用户选择后才安全应用 |
| 双方都有变化 | 分别说明各自改动与重叠处，不能称某一方整体较新；建议保留双方并审查合并 |
| 无可信基线、历史不相关或无法读取 | 明确无法判定新旧；列出可证实的内容区别，建议保留现场暂不应用 |

尚无本次同步请求时，有差异先给出本地、云端和建议的摘要并等待选择。用户已明确同步时，由本页执行入口先合并和校验兼容变化；只对真实冲突、身份/范围不明、未授权删除及安装覆盖风险提供适用选项。不能从文件名猜功能，也不把已有选择重复交回用户。执行前文件或远端变化重新比较；锁、备份与在用资源保护继续适用。

提示示例（仅示例，实际内容必须来自 diff）：
> 本地：新增手动同步，取消结束自动上传；云端：仍为旧自动上传规则。建议保留本地，采用云端会撤销这次修改。选择：保留本地继续 / 采用云端 / 暂不处理。

## 本机绑定与实际目标

本机 binding.taskSync 保存 enabled、授权证据、唯一 repository/branch/resourceIds、journalPath、默认 remoteCacheSeconds=86400 及 resources 映射。每个资源明确 installedPath（实际宿主目录）、sourcePath（受管源码）、runtimeExclusions（已审定精确路径）、applicationMode。binding 的 resources 映射是唯一文件应用范围；测试目标不能冒充宿主目录。仅安装 Skill 不自动开全局入口；每机核实授权与实际加载规则。继承已有用户授权须记录依据，缺失时只询问一次开启范围。

实际安装可能是独立目录或链接，须现场核实；CLI 测试目标不等于宿主安装目录。reviewed-files 表示在既有明确授权内逐文件审核更新，不自动覆盖独立副本。发现远端变化时，先展示差异并取得本次选择，未使用且scope安全才拉取受管源；实际安装仍等于可信基线时可按下节步骤应用。若资源正在使用，连受管源拉取也延后。不要自行转换用户目录为链接或降级 copy。

## 整个流程的锁与证据

[sync_session.py](../scripts/sync_session.py) 维护合作式工作流锁、摘要、日志和提交完整性检查；Git 操作只读，不执行 Git 写入、安装或权限授权。每个开始同步事务先取得 repository 级锁，覆盖观察→意图→CLI→验证→记录，完成或延后即释放；业务任务执行期间不持锁。用户主动要求同步时重新取锁并核对全部基线，再覆盖同步和状态写回，最后释放。普通任务结束仅提醒，不重新启动同步事务。每个仓库串行，单资源观察按 id 逐个处理，任一未完操作先恢复再换资源。

首次先 `python <Skill>/scripts/sync_session.py --locate` 读取本机定位指针；指针不存在时由已核实绑定路径显式传入 `--binding <库外binding.json>`，不扫描宿主凭证。调用：`python <Skill>/scripts/sync_session.py --binding <库外binding.json> --request <库外request.json>`。兼容显式 --state；升级后第一次 begin 必须在 request 中提供 binding 路径，后续可复用 journal.bindingPath。request 包含 operation 与 owner（本任务唯一标识）；begin 同时独占创建 Git common-dir 下 ai-toolbox-sync.flow.lock 与 journal 旁 .flow.lock，release 仅允许同 owner/session。即使误用两个 journal，同一 Git 仓库也不能同时加锁。锁跨调用持续，不随单次脚本退出释放。死锁不自动按超时抢占；确认旧任务已结束后按原 owner 显式 release，保留 pending 日志。不得以生成新 owner 绕过已有锁；相同 owner 的调用由任务串行执行。外部 Git/编辑器不遵守锁时不受保护，检查与命令间仍存在竞态。

observe.observation 必须包含：resourceId、sourceDigest、installedDigest、remoteTip、head、localPaths、remotePaths、remoteAvailable、scopeReviewed、inUse。摘要与提交必须为真实 SHA；断网 remoteTip=unknown、remoteAvailable=false，不能用缓存伪称 live。localPaths 比较 merge-base 到当前 HEAD 并含已暂存/未暂存/未跟踪改动；remotePaths 比较同一祖先到已取回远端。scopeReviewed 只能在 safe-sync 全部目标/删除/metadata/备份等检查后置 true，不是程序自动审查结果。

用 fingerprint(installedPath, runtimeExclusions) 和 fingerprint(sourcePath, runtimeExclusions) 比较三层中的本地两层。顶层链接须提供已批准 expected_root，嵌套链接和 .env（不区分大小写）在读内容前拒绝。runtimeExclusions 只取预先核实绑定，历史管理器绑定曾使用 catalog/data.js、scripts/__pycache__；这仅用于识别旧记录，当前管理器已分流到 self-maintenance.md，不再进入私人源码绑定。其他资源的排除项须逐项审定；不临时排除业务文件来取得一致。跨任务无可靠内容变化证据则重新计算摘要；同任务可靠已核实基线且确认无写入时可复用，不以 mtime 或 TTL 替代内容证明。

## 远端观察缓存

probe 请求包含 repo、remote（每次先核对 origin 解析的实际 URL，不传 origin 别名）、branch、knownTip（本地远端引用 SHA）、strict/force/dirty/endPush 标志。按仓库绝对路径、远端、分支保存 remote_head_cached、checkedAt、cache_expire_at，默认 86400 秒（滚动 24 小时）。快速命中返回 cached-not-live，不联网，也不延长 TTL；必须仍检查本地漂移/改动、未完操作和绑定。strict、force、dirty、pending 或 endPush 绕过缓存，使用 20 秒超时的 `git ls-remote <remote> refs/heads/<branch>`。不是查询远端默认 HEAD，以免分支错配。

live head 与 knownTip 相同则不需 fetch；不同时 fetch 后核对真正远端 tip、共同祖先和路径差异，若 fetch tip 又变化重新审查。缓存命中但本地没有对应引用/对象时不能假设已取回，需 fetch 或延后。绑定变化、时钟回拨、过期超过写入时刻 86400 秒（滚动 24 小时）等缓存失效。失败保留旧缓存但不延长，返回 network-pending；严格模式暂停同步，快速模式只继续独立本地工作，不写 synced。推送前总要 endPush=true 实时检查，缓存不提供跨电脑失效广播。

## 开始决策

| 观察 | 执行 |
|---|---|
| 本机安装与受管源不同 | 有上次确认基线且 source 未变时为 installed-only；普通收尾只提醒并保留待办。用户本次明确要求收集或同步后，才审核差异、登记 collect 意图并逐文件纳入 source、验证后 resolve；仅收集不 commit/push；无基线或两边均变为 installed-drift，保留两边核对/合并，不自动覆盖 |
| 没有改动 | 不造提交；live 且 HEAD=remoteTip 可 confirm；缓存只表示本次按旧观察继续，不宣布实时同步 |
| 仅本地变化 | 简述本地变化，建议保留本地继续并等待选择，不自动上传；已提交未推送也算本地变化 |
| 仅远端变化 | 简述新增/修改/删除和建议理由，用户选择采用云端后，未使用资源且全部scope安全时 intent(pull) 后按 git-workflow.md 执行原生 Git 快进，再逐项审核应用并验证后 resolve |
| 双方不同文件 | 修改前保留本地改动并报告需合并；不自动 commit 或 push。用户明确要求同步/合并后，审核并显式 commit，再重新观察、intent(merge) 和经批准的原生 Git 合并；验证后仅在本次同步请求内 push |
| 双方同一文件/metadata/删除风险 | 保守停相关操作，保留两边；不自动 ours/theirs，不为了合并清除本地改动 |
| 正在使用且远端有变化 | application-deferred，不热替换；结束后仍已加载旧 Skill 的会话不能声称刷新 |
| 网络失败 | pending，独立本地任务可继续；不自动直连、不谎报同步成功 |

## 用户主动同步时的提交、上传与恢复

以下写操作只在用户明确提出本次同步时执行；持续权限、工作项 pending 或聊天结束均不能单独触发。用户指定阶段保存时同步当前获准内容，不把业务需求标记完成。

1. 重新核对三层、整个 Git 根的 tracked/untracked、命令真实scope及授权。仅选定资源和获准管理文件可上传；新资源未加入指定库不进入；没有变化不 commit。
2. **先精确暂存获准文件并用原生 git commit 提交，再重读 HEAD**。暂存区不能包含其他变化；Git push 不会隐式 commit。登记 intent 前确认工作区干净并固定真正待推 SHA，不把后续新文件混入本次事务。任务期间新增变化使检查失效。
3. endPush=true 实时探测/必要 fetch，重新核对双方差异。仅本地变化时 observe → intent(action=push, head=真实HEAD) → 按 git-workflow.md 将固定 SHA 原生 Git push（不强推）；前后核对工作区与远端。Git push 不隐式分发，不顺便安装第三方新版本。
4. CLI 失败或输出不确定时保留 pending，不能按“失败”盲重发。下次先确认原命令已结束、实际 HEAD/工作区及真实远端：远端恰为 intent.head 且三层已核实可 resolve；远端仍是原 tip、本地仍是待推 HEAD 且无入站变化，可传 previousCommandFinished=true resolve，恢复 local-only 后重新检查再登记新 intent。远端前进到其它提交时保守保留 pending，人工核对 ancestry/差异，不将远端不同当作未推送。merge/pull 后本地尚需 push 时保持日志待处理，不能假报完成。
5. resolve 只在实际同步结果核实后确认；独立轴更新使用 record_decision.py。同步失败不撤销收藏/安装成功；目录刷新失败独立记录。confirmedKey 按稳定身份+内容摘要+远端观察去重；拉取后的相同 HEAD/内容不再制造上传提交。释放流程锁不删除未完日志。

本辅助不会执行或保证 scopeReviewed 的真实性，不提供外部写者排他、远端事务或跨机器锁。拉取/合并的本地提交领先远端须如实保留待同步状态，等待用户主动同步；无法安全自动处理时保留 pending 并报告，不伪称已完成。

首次只在安装/受管源实际内容一致、提交覆盖核验通过且真实远端核对通过后 confirm 建立 baseline，不能虚构历史。installed-only 纳入前备份、复核原 source 摘要未变；只处理用户授权的具体文件，删除仍需单独范围许可，运行产物不纳入。此授权纳入仅限所选文件，不是目录镜像。collect/merge 完成转 local-only 须 previousCommandFinished=true、applicationVerified=true：实查工作区无冲突/MERGE_HEAD、原远端 tip 已为本地祖先（merge-base --is-ancestor）、源/目标内容符合预期，再重新观察登记 push，不把 merge 本身当已推送。

跨聊天无法证明资源无人使用时保守延后应用，不新增租约/监听服务。快速缓存不能生成新的 confirmed/synced；observe 不接受缓存或失败 probe 冒充 live。

成功基线 baselines 与去重 confirmedKeys 按 resourceId 保存，同一仓库多个资源交替处理不会覆盖彼此。旧单资源基线只在身份吻合时兼容使用。

## 独立宿主目录的审核应用

source-only 仅在安装摘要仍等于该资源上次可信基线、而受管源改变时产生；正在使用则 application-deferred。applicationMode=reviewed-files 且已有本机目标授权、用户已选择本次差异处理方案时：核对远端来源/提交，按 [本项目文件执行器](git-workflow.md#本项目文件执行器) 生成源到安装目录的只读计划，审查新增/修改/删除、敏感文件、身份与链接。再次核对 installedDigest 与基线一致，再 intent(apply,head=当前HEAD)，应用批准计划；执行器只备份将被替换或删除的原文件，保留审定排除项及本机运行产物。来源或安装内容再次变化、操作失败则停止后续替换，保留备份、回执及 pending，不把部分应用当成功。

完成后核对全资源摘要、预期逐文件结果及当前宿主使用状态，previousCommandFinished=true/applicationVerified=true resolve 才更新基线。这是有备份和逐项核对的 AI 执行流程，不是目录级事务，也不能防住不合作外部写者；不悄悄改目录为 junction，不执行目录镜像覆盖。无可信基线先报告并核实建立，不能用当前远端内容伪造过去基线。与源同时发生本地编辑时停止自动应用并保留两边。

已有 pull 意图覆盖受管源拉取与获准的独立宿主应用，不另开 apply 意图。Git 快进或合并完成后真实核对 HEAD=远端原检查 tip、无工作区/入站差异、宿主仍等于基线且非在用，调用 application（含 observation、previousCommandFinished=true）转 application-ready；按上述逐文件备份审核流程应用，再 resolve。失败/在用/漂移保留原 pull pending，不以删除日志绕过；无现有 pull 意图的独立 source-only 更新才登记 apply 意图。

缓存按成功观察时刻起滚动 24 小时，不是每天零点刷新；旧缓存沿用原 checkedAt/cache_expire_at，不追溯延长，下一次真实查询成功才写入新的 86400 秒 TTL。

## 第三方资源边界

源码同步仅允许权威清单 ownership=self 的已授权资源。开始/收尾均核对 taskSync.resourceIds、实际 source 内容、本次全部明确目标及待提交路径；第三方或归属未知资源混入时停止相关同步，不靠网页过滤代替执行检查。第三方 Skill/MCP/插件只登记安装来源与提示词，实际版本/安装状态留在库外；不 collect 或复制其目录。第三方最新版检查与更新独立走 [更新流程](third-party-updates.md)。授权只来自当前用户对具体仓库、分支、资源和操作的明确选择；不继承发布者的授权。


## 必须执行的完整性与新鲜度校验

- 新 begin 保留历史 baseline、pending 和 workItems，但清除旧 live/完整性证据，状态变为 inspection-required 或 reconcile-required。绑定的真实 Git 根、origin、分支、资源及 journal 必须匹配；流程中绑定变化即停，release 仍可由原 owner 执行。
- fingerprint 的目录遍历错误、读取错误、链接或敏感文件均失败，不把未扫描内容当不存在。内容摘要格式兼容原基线。
- confirm、push intent 和最终 resolve 会重新扫描实际安装/源，并把全部应保存文件与具体 HEAD 的 Git tree 比对。遗漏的 ignored 文件、提交多出/缺少文件、内容不同或检查期间变动都会失败。可先用 operation=verify（含 observation）取得文件数；该次结果不免除后续自动复核。
- 支持 Git 内置换行规范化；拒绝需要自定义 clean filter 或 working-tree-encoding 的自动完整性确认，不调用仓库提供的过滤程序。需要这些机制的资源须另行设计真实恢复验证，不能静默跳过。
- 实时证据必须来自本事务的 probe，绑定仓库/远端/分支/session，最长有效 300 秒。push intent 还要求该次 probe 的 endPush=true。超过时限重查，不能扩大缓存 TTL 或沿用历史 live。24 小时缓存仍只用于快速只读观察；缓存命中时不能填 remoteAvailable=true，也不能 confirm。
- scopeReviewed 仍是人工审核结果；上述校验不替代授权、秘密检查、Git 全仓历史审查或外部写者隔离。直接调用 transition 是内部状态机接口，正式流程必须调用 operate/CLI，不能绕过实际文件校验。

## 编辑前登记与中断恢复

1. 在已获准资源开始编辑前 begin，调用 `mark-dirty`（owner 为当前任务稳定 ID，resourceId 为绑定 ID），成功后 release；业务编辑阶段不持同步锁。只读任务不登记 dirty。
2. workItems 保存在库外 journal；begin 总会返回该仓库全部历史工作项。下次进入流程先核对 pending 项及负责聊天，不能将无 pending Git 意图误认为没有未完成业务工作。操作失败或任务中断不会自动删除工作项。
3. 普通收尾只提醒，保留 pending 工作项。用户主动同步时重新 begin，按完整流程上传/核验至 confirmed 后，调用 `complete-work`、`previousCommandFinished=true`。默认只完成当前 owner 的当前资源；恢复已结束的旧任务可明确传 workOwner，必须先确认该旧任务已结束，不代其他正在工作的聊天清账。
4. 旧 journal 没有 workItems 时不推断之前任务已完成；先比较真实三层，再登记需要恢复的工作。confirmed 是某次验证结果，不代表后续编辑仍已同步。
5. 仍无后台、hook 或定时任务。中断后仅在下次修改前检查或显式调用时核实；重新上传必须等待用户本次同步请求。任务路由未加载、绑定未定位时需报告，不宣称自动收尾。

## 本机绑定定位

固定定位文件为用户目录下 `.agents/ai-toolbox-sync/binding-pointer.json`，仅保存 `schemaVersion: 1` 与 `bindingPath`，不保存凭证，不进入同步仓库。它只定位库外绑定；实际 Git/宿主路径始终以已批准 binding 为准。安装或迁移时在授权内建立指针；已有不同指针先核对，不覆盖。也可每次显式 --binding，不能为了定位扫描账号配置。`--locate` 只读验证并返回绑定/journal 路径，不产生同步。


## 整份 Agent 文档资源

`kind=agent-document` 的身份、来源与精确目标规则见 [Agent 文档](agent-documents.md)。它不使用 Skill 的目录指纹、collect 或 agent 批量分发；使用专用全文摘要、独立文档绑定和 `agent_documents.py`。共享快照置于 `agent-documents/<documentId>.json`，不作为 Skill/MCP 批量分发，也不广播到其他宿主。现有“仅自建源码同步”限制针对 Skill/MCP/插件，不禁止已获准的文档派生版本；派生来源仍须保留。

复用本页的仓库锁、远端检查、任务触发、提交/推送和 pending 流程。文档 `inspect` 返回的 installedDigest/sourceDigest 用于原 sync_session observation，bundleDigest 另作完整快照前置条件。全文已加载时可 collect 已授权本地修改，但入站 apply 延后；不能宣称当前会话重新加载了文档。导入新电脑默认派生新 documentId 与 installationId，不能复制旧机器的绑定。


Agent 文档在 taskSync.resources 使用 kind=agent-document，明确 sourcePath（快照 JSON）、installedPath（全文文件）及 documentBindingPath（库外专用绑定）；id 必须为 agent-document:<documentId> 并已纳入授权 resourceIds。完整性检查只核对该快照，不扫描其他文档；sourceDigest 仍为正文摘要，Git 完整性使用完整 JSON 内容单独验证。register 之前先以已授权仓库绑定加锁（资源列表可为空），注册获准后更新资源列表并 release/re-begin，不能在旧事务中悄悄改变绑定。


## 中断释放与校验收尾

release 按原 owner 核对锁身份，不解析或改写损坏的业务日志；两把锁释放中途失败可由原任务重试。若 begin 中断只留下仓库锁，确认原任务已结束后，用原 owner 并显式提供 binding 执行 release，核对 journal 归属后释放；不会自动按超时抢占。锁文件本身损坏或绑定失效时仍保留现场，人工核对恢复，不推断锁已失效。

存在 pending 的 workItems 时 probe 自动绕过缓存，不依赖调用者补传 dirty。complete-work 在完整性扫描后再次检查实时证据时限；Git 超时由 CLI 返回结构化失败，保留工作项与锁供原任务检查后释放。

完整性核验先比对原始 Git blob；原始字节已一致时不因当前 core.autocrlf 与提交时不同而误拒绝。原始字节不同时仍只接受 Git 内置换行规范化后的匹配；自定义 filter/working-tree-encoding 继续拒绝，真实内容变化仍阻断。

Git 只读查询共享有界执行入口：远端查询限时 20 秒，其他证据查询限时 30 秒，超时后另留有限进程清理时间。Windows 使用当前任务启动的 PID 清理其 Git 进程树；输出不使用会被后代进程持有的管道。失败仍保留 journal/pending，不自动重试业务写入。
