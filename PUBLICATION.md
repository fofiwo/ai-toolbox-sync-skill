# Public release boundary

Maintain generic code in this public checkout. Private collections, local bindings, journals and installed runtime data stay outside it. Do not migrate private Git history or repoint private remotes. Do not install this public checkout as a writable runtime catalog.

## Release

1. Review changed content, including allowed Markdown, examples and tests, for private information. The scanner only recognizes selected credential patterns; it cannot infer whether arbitrary prose is private.
2. Run `python -B -m unittest test_release -v` and tests relevant to the Skill changes.
3. Run `python -B release.py manifest`. This checks exact allowed paths, required files, empty active catalog and null discovery template, and selected credential patterns before regenerating hashes. Unknown paths fail before contents are read. New legitimate files must be individually added to `EXTRA` in release.py after review; never whitelist a whole runtime directory.
4. Review and commit only the approved files. Each new commit must contain a valid manifest. If a local unpushed commit contains private content, stop and arrange an explicitly authorized history repair; deleting the file in a later commit will not pass.
5. Run `python -B release.py check`. It checks every commit after the audited baseline, including merged histories, not only the final tree. Working changes/untracked nonignored files, missing files, links, submodules, unexpected paths and nonempty catalog fail closed.
6. Run `python -B release.py push` with process-scoped proxy/authentication settings required by the host. It verifies the exact origin push URL, main branch and remote ancestry, then pushes only the checked SHA to main, without force, tags or mirror. A remote change requires comparison; do not bypass the gate.
7. Verify the remote SHA and anonymously downloaded archive manifest after publishing.

## Boundaries

The audited baseline is d30213adaf3280a563fa8518a683ccc9c7beb135. Historical commits before it were reviewed separately; the initial historical manifest predates the byte-preservation fix. New commits must pass current checks. Python 3.12+ and Git are required for the release tool, not for merely reading the Skill.

This is a cooperative publishing gate, not a server-side confidentiality guarantee. A user or tool can bypass it with direct Git, alter the gate, or place private prose in an allowed file. Human/AI diff review remains required. GitHub CI after push cannot prevent disclosure and is not used as a substitute. No automatic background publishing or collection is installed.

## 修改前与请求同步时的版本核对

准备修改本公开仓库前，以及用户提出同步/发布时，必须先运行 `python -B release.py inspect`（按宿主规则设置进程级网络代理）。仅使用 Skill 不触发。该命令获取远端对象但不合并、不覆盖工作区；网络失败、祖先不明或检查期间版本变化时停止依赖该结果的操作。

向用户简述：版本是否一致、本地新增/修改/删除、远端新增/修改/删除、暂存/未暂存/未跟踪改动，以及建议理由。提交时间仅供参考，不用于判定新旧。文件列表是证据入口，AI 还需审阅获准文件的实际差异，用一两句话说明功能变化；不要直接倾倒完整 diff。aligned 只表示提交一致，有未提交改动时必须说明工作区并未对齐。

开始修改前有差异，先让用户选择保留本地继续、采用远端、审查合并或暂不处理；已对同一差异明确选择不重复问。请求发布时，本次已授权且审查过的本地改动可继续；有未知本地改动、云端新增或分叉则说明差异并等待选择，不自动覆盖或合并。发布入口会再次实时比较并阻止云端领先/分叉；执行前版本变化必须重新解释。独立聊天使用独立分支/工作目录，不接管其他聊天的未完成修改。

## Manager and collection independence

The manager itself is maintained only here, never collected into a private toolbox. Review generic improvements from private copies file by file; keep private collections and Git history separate. Publish and verify the clean public version before an explicitly authorized removal of a legacy manager collection. Upgrade instructions and compatibility boundaries are in skills/ai-toolbox-sync/references/self-maintenance.md.
