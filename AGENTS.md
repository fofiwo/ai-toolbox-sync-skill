# Public Skill maintenance

This repository is the public maintenance source for ai-toolbox-sync. Private collections and machine bindings belong elsewhere. Never change a private toolbox remote to this repository, import its Git history, or copy an installed Skill directory wholesale.

Read PUBLICATION.md before editing or releasing. Changes to the generic Skill may be published under the owner's existing authorization after validation. This authorization never includes private user data. Publish the manager only through release.py; private resource collection is a separate workflow. This is an independent project using native Git and its own Python helpers.

Preserve the root release tooling, source attribution, and empty active catalog. New paths require explicit allowlist review, not merely regenerating hashes. Review the actual diff for private content even in approved file names. Do not bypass a failing gate.

Run `python -B -m unittest test_release -v`, applicable Skill tests, and the publication gate. Publish only using `python -B release.py push` with the required process-scoped network settings. Report exact commit and unverified boundaries. Direct Git pushes bypass the gate and are not the supported workflow.

## 修改前与请求同步时的版本核对

准备修改本公开仓库前，以及用户提出同步/发布时，必须先运行 `python -B release.py inspect`（按宿主规则设置进程级网络代理）。仅使用 Skill 不触发。该命令获取远端对象但不合并、不覆盖工作区；网络失败、祖先不明或检查期间版本变化时停止依赖该结果的操作。

向用户简述：版本是否一致、本地新增/修改/删除、远端新增/修改/删除、暂存/未暂存/未跟踪改动，以及建议理由。提交时间仅供参考，不用于判定新旧。文件列表是证据入口，AI 还需审阅获准文件的实际差异，用一两句话说明功能变化；不要直接倾倒完整 diff。aligned 只表示提交一致，有未提交改动时必须说明工作区并未对齐。

开始修改前有差异，先让用户选择保留本地继续、采用远端、审查合并或暂不处理；已对同一差异明确选择不重复问。请求发布时，本次已授权且审查过的本地改动可继续；有未知本地改动、云端新增或分叉则说明差异并等待选择，不自动覆盖或合并。发布入口会再次实时比较并阻止云端领先/分叉；执行前版本变化必须重新解释。独立聊天使用独立分支/工作目录，不接管其他聊天的未完成修改。
