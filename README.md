# ai-toolbox-sync

独立维护的个人 AI 工具箱项目。公开分发版本：0.5.0-draft；首期支持范围为 Windows + Codex。

## 交给 AI 安装

复制 [完整安装与授权提示词](INSTALL.md) 给 AI，或说：

> 请阅读此仓库的 INSTALL.md，安装干净的 ai-toolbox-sync，再引导我选择创建空私人工具箱或授权接入已有私人库。

Skill 路径：[skills/ai-toolbox-sync](skills/ai-toolbox-sync/SKILL.md)。安装整个目录，不是只复制 SKILL.md。固定实际下载提交并核对 [SHA256SUMS.json](SHA256SUMS.json)。摘要验证完整性，不代替来源信任。

## 两条独立流程

- **公开安装**：无需私人仓库权限；默认零收藏、无绑定、无授权记录。示例文件标为 example，只在主动打开演示时使用，不自动导入。
- **私人工具箱**：用户另行选择自己的空库或获得授权的已有库。登录、主人邀请、接受邀请和 Git 权限核验须在读取私人资源前完成。此项目不授予任何私人仓库权限。

只使用不检查；修改已纳管资源前比较差异；修改结束只提醒；用户主动同步才上传。不运行后台服务、不默认扫描全机、不自动改写全局 Agent 规则。

收藏同步提供可执行入口：`python -B <Skill>/scripts/sync_session.py status|sync --binding <本机绑定.json>`。`status` 只读本机，`sync --dry-run` 实时取得差异并生成计划，`sync` 在本次授权范围内精确提交、三方合并兼容变化、验证和上传。收藏清单按稳定 id 合并；真实冲突、身份变化和未授权删除才交给用户。失败保留 Git 提交和库外恢复收据；没有变化不造版本。Git 同步、独立安装应用和宿主加载分别报告，详见 [执行流程](skills/ai-toolbox-sync/references/task-sync.md#收藏同步执行入口)。

管理器源码只在本公开库维护；私人工具箱保存用户选定的其他工具，不收藏管理器自身。收藏清单、本机绑定和生成页面位于安装目录之外，升级步骤见 [管理器维护与升级](skills/ai-toolbox-sync/references/self-maintenance.md)。本版包含离线收藏/待收藏统一工作台，活动目录与发现模板保持空白。接收者按第三方来源记录此 Skill，不继承发布者的自建身份或权限。依赖为 Python 3.12+、原生 Git；GitHub 接入复用 gh。Git 传输、选择性文件应用和宿主注册分别执行，不安装其他工具箱管理器。

## 验证与边界

见 [接收端验收](skills/ai-toolbox-sync/references/acceptance.md)。文件安装、宿主发现、实际触发、仓库认证、Git 读写及资源恢复分别验收。现有聊天不保证重载规则；已授权目标邀请由 AI 检查并接受；敏感输入、宿主强制本人操作及实际新会话加载分别验证。

## 维护与发布

通用优化在此公开仓库维护，私人收藏与机器状态不进入此仓库。发布必须按 [PUBLICATION.md](PUBLICATION.md) 使用本地发布门禁；摘要清单不等于隐私审查。现有私人同步绑定不因公开发布而改变。

“同步 toolbox”先区分更新管理器本身、发布管理器本地修改与同步已收藏工具；上下文无法确定时先询问，再访问相应仓库。已有私人绑定或待上传工具不代表本次要上传收藏。其他电脑缺少公开来源、仍显示“尚无公开发布 URL”或使用旧 Skill 时，从本库读取 README.md、INSTALL.md，并按 [旧电脑升级](skills/ai-toolbox-sync/references/self-maintenance.md#旧电脑缺少来源或仍加载旧指令) 核对实际副本和差异，保留本地定制；公开发布不代表其他电脑的安装或已打开会话自动更新。

版本以 Skill 内的 `VERSION` 为唯一来源。AI 根据变化选择 `python -B release.py bump patch|minor|major`，统一更新元数据、README、页面和摘要；`prerelease` 递增草稿序号，`final` 去掉预发布标识。开发提交可以共用草稿版本，每次有新内容的对外发布必须升版。`release.py push` 原子发布 main 与精确 `v<VERSION>` 标签，拒绝复用版本、倒退和标签覆盖；没有变化时不制造新版本。`release.py version` 只读检查当前版本，发布仍需用户本次同步授权。

## 来源

本项目独立维护代码、协议、版本和发布。早期第三方材料的 [历史来源档案](skills/ai-toolbox-sync/UPSTREAM.json) 与 [历史许可](skills/ai-toolbox-sync/LICENSE.skillshare) 仅用于来源追溯；原运行依赖、安装校验资产和操作手册已退出当前分发。
