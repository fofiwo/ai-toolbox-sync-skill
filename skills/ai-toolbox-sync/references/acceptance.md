# 接收端验收

公开包是干净安装版，默认收藏数为零；assets 中的 example 文件和 catalog/demo-data.js 只用于明确标记的演示，不导入用户清单。

依次核验：固定公开提交和 SHA256SUMS.json；完整安装目录；当前宿主实际发现；新对话明确调用；用户选定的仓库认证；选定资源差异及恢复。每项分别报告，文件存在不代表宿主已加载。

回归命令（Skill 目录内）：`python -B -m unittest discover -s scripts -p "test_*.py"`，以及 `node scripts/test_agent_catalog.cjs`、`node scripts/test_inventory.cjs`、`node scripts/test_inventory_dom.cjs`。隔离测试不代表真实第二台机器、其他账号邀请或所有宿主联调通过。

只使用不检查；修改已纳管资源先比较并处理差异；结束只提醒；用户主动同步才上传。没有后台监听，既有聊天不保证重载新规则。合作式锁无法阻止外部编辑器或 Git 写入。不同账号授权、断电、磁盘满和接收端宿主加载须单独验证。
