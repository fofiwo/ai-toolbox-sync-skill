# 本机记录：兼容字段与安全更新

记录保持 schemaVersion=1，增加可选 state，不改旧 id、不删除历史/未知字段。没有数据库、守护进程或自动事件队列。实际记录应放本机绑定所在目录，不能进入同步仓库。以当前机器已核实的路径为准。

## 五个独立状态轴

| state 字段 | 值 |
|---|---|
| decision 用户决定 | pending / approved / declined / deferred / unknown |
| collection 收藏结果 | not-collected / collected / failed / unknown |
| installation 本机安装 | source-only / configured / installed / failed / uninstalled / unknown |
| sync 同步结果 | not-requested / pending / synced / failed / unknown |
| catalog 目录刷新 | pending / current / failed / unknown |

示例在 [decisions.example.json](../assets/decisions.example.json)：源码已收藏、安装失败、同步失败可以同时为真。验证状态仍是独立事实，installed 不等于调用验证。

新状态优先；没有新字段时保守读取旧 decision/management/outcome：managed 仅说明 collected（及在缺决定时推断旧批准），approved 仅说明决定，不能推断收藏成功；created 映射 source-only，configured/installed/failed 映射安装结果，不能从失败推断收藏失败。未知旧值保持 unknown。旧字段保留作历史兼容，不能继续作为权威写入；更新只写 state。目录 management 是由 state 派生的兼容筛选字段，collected 优先于同步/目录失败。未触及记录原样保留。

## 实际调用流程

标准库脚本 [record_decision.py](../scripts/record_decision.py) 不执行收藏、安装、同步，只保存已经核实的结果。不要把命令成功当成资源已收藏的证据。

先 inspect（只返回摘要与条目数，不输出记录正文）：

```powershell
python "<Skill目录>/scripts/record_decision.py" inspect --store "<本机记录目录>/decisions.json"
```

读取获准的具体条目并核对真实用户答复，把 [请求示例](../assets/decision-update.example.json) 复制到工作目录，替换 id、来源身份、显示名、实际状态与 decisionEvidence（包含用户答复所在会话依据、明确保存内容及目标本地/库和同步范围）。示例中的用户答复不是授权，禁止直接应用到真实记录。请求只能有 id 与 patch；禁止凭证、机器路径、配置正文。所有值须来自真实已核实结果。

```powershell
python "<Skill目录>/scripts/record_decision.py" update --store "<本机记录目录>/decisions.json" --expected-sha256 "<inspect返回的sha256>" --request "<工作目录>/decision-request.json"
```

退出 0 且 saved=true 才能说决定已持久化；退出非零时先读取当前哈希和对应条目检查，不盲重试。冲突时基于最新记录重新构造最小 patch，保留其它聊天变更；不要把旧整份文件写回。已经给出的决定继续有效，不为记录冲突重复询问同一用户决定。

例如明确加入后请求 patch.state={"decision":"approved"} 并提供真实 decisionEvidence；收藏操作实际完成后另一次请求 patch.state={"collection":"collected"}。上传失败另一次请求 patch.state={"sync":"failed"}，不能带 collection=failed。安装失败、卸载、刷新失败同理。每一步重新 inspect；未答复不能写 approved。

已有记录更新不必重复传 name/kind/sourceIdentity。新记录必须有这三项及稳定 id；sourceIdentity/kind/parentId 一经确定不得通过本辅助变更，重命名只改 name，移动不改变身份。已确认同一来源的 id 应复用；工具拒绝同 kind/sourceIdentity 的第二个条目。未知身份暂停写入，不能用统一 unknown 身份去重。

本辅助拒绝把已 collected 改为 failed/not-collected；删除/取消收藏是独立范围，本次没有实现。decision 变为 approved/declined/deferred 必须在本次请求提供 decisionEvidence；这只是可追溯字段校验，不能证明文本真由用户授权，AI 必须核对会话。每次状态变化追加 history，保留旧历史；未知历史结构拒绝写入。

## 并发与失败保证

- 同目录 `<文件>.lock` 使用独占创建；所有写入者遵循本脚本时只有一个写者。
- expected SHA 不一致立即失败；不是最后写入覆盖。临时文件在同目录 fsync 后 os.replace，替换失败保留原文件；不会回报 saved=true。
- 进程崩溃可能留下 lock；不自动超时抢锁、不自动删除他人锁。核对持有者和文件状态后由明确授权的维护处理。
- 不遵循协议的外部编辑不受锁约束；替换前再比较只能缩小风险窗口，不能承诺无竞态。使用本脚本的前提是暂停其它手工/异构写入者。
- 不提供跨机器锁、跨聊天提示恰好一次、文件和真实资源操作的事务、断电全链路恢复。保存与资源操作失败都需要读取实际状态后继续。

当前机器 records 为空时保留空文件，不为升级格式预建候选、不制造管理器自纳管决定。只有用户授权的实际事件决定才写入；本轮测试使用隔离记录文件。


## Agent 文档

整份全局文档使用 `kind=agent-document`，按 [Agent 文档流程](agent-documents.md) 发布、导入及同步。复制导入提示只表达意图，执行时仍须确认目标与覆盖/整理/追加/插入方式。新派生文档登记独立身份，来源固定到提交；本机整份绑定不能随 Git 分享。目录新增 Agent 文档分类，支持复制导入或同步指令；同步指令必须匹配本机自己的绑定，无绑定时停止。五轴状态沿用，不将本地快照写成功或目录复制成功当成 GitHub 同步成功。
