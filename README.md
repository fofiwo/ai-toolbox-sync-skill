# ai-toolbox-sync

干净的个人 AI 工具箱 Skill，基于 Skillshare v0.26.1。公开分发版本：0.2.4-draft；首期支持范围为 Windows + Codex。

## 交给 AI 安装

复制 [完整安装与授权提示词](INSTALL.md) 给 AI，或说：

> 请阅读此仓库的 INSTALL.md，安装干净的 ai-toolbox-sync，再引导我选择创建空私人工具箱或授权接入已有私人库。

Skill 路径：[skills/ai-toolbox-sync](skills/ai-toolbox-sync/SKILL.md)。安装整个目录，不是只复制 SKILL.md。固定实际下载提交并核对 [SHA256SUMS.json](SHA256SUMS.json)。摘要验证完整性，不代替来源信任。

## 两条独立流程

- **公开安装**：无需私人仓库权限；默认零收藏、无绑定、无授权记录。示例文件标为 example，只在主动打开演示时使用，不自动导入。
- **私人工具箱**：用户另行选择自己的空库或获得授权的已有库。登录、主人邀请、接受邀请和 Git 权限核验须在读取私人资源前完成。此项目不授予任何私人仓库权限。

只使用不检查；修改已纳管资源前比较差异；修改结束只提醒；用户主动同步才上传。不运行后台服务、不默认扫描全机、不自动改写全局 Agent 规则。

管理器源码只在本公开库维护；私人工具箱保存用户选定的其他工具，不收藏管理器自身。收藏清单、本机绑定和生成页面位于安装目录之外，升级步骤见 [管理器维护与升级](skills/ai-toolbox-sync/references/self-maintenance.md)。本版包含离线收藏/待收藏统一工作台，活动目录与发现模板保持空白。接收者按第三方来源记录此 Skill，不继承发布者的自建身份或权限。CLI 二进制不随包提供，按引导单独核验安装。不要运行上游 run.sh。

## 验证与边界

见 [接收端验收](skills/ai-toolbox-sync/references/acceptance.md)。文件安装、宿主发现、实际触发、仓库认证、Git 读写及资源恢复分别验收。现有聊天不保证重载规则；已授权目标邀请由 AI 检查并接受；敏感输入、宿主强制本人操作及实际新会话加载分别验证。

## 维护与发布

通用优化在此公开仓库维护，私人收藏与机器状态不进入此仓库。发布必须按 [PUBLICATION.md](PUBLICATION.md) 使用本地发布门禁；摘要清单不等于隐私审查。现有私人同步绑定不因公开发布而改变。

## 来源

保留 [上游来源与摘要](skills/ai-toolbox-sync/UPSTREAM.json) 和 [Skillshare MIT 许可证](skills/ai-toolbox-sync/LICENSE.skillshare)。原样上游文档位于 references/upstream；本项目是适配版，不是上游官方发行。
