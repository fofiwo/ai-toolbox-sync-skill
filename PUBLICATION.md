# Public release boundary

Maintain generic code in this public checkout. Private collections, local bindings, journals and installed runtime data stay outside it. Do not migrate private Git history or repoint private remotes. Do not install this public checkout as a writable runtime catalog.

## Release

1. Review changed content, including allowed Markdown, examples and tests, for private information. The scanner only recognizes selected credential patterns; it cannot infer whether arbitrary prose is private.
2. Run `python -B release.py version`. For a new publication, run `python -B release.py bump patch`, `minor`, or `major` according to the reviewed changes; retain an already prepared higher version. `VERSION` inside the Skill is authoritative; bump updates Skill metadata, README, footer, and the manifest together. Use `prerelease` to advance a draft identifier and `final` to remove it after stable-release validation. Development commits do not each require a new version. Run `python -B -m unittest test_release -v` and tests relevant to the Skill changes.
3. Run `python -B release.py manifest`. This checks exact allowed paths, required files, empty active catalog and null discovery template, and selected credential patterns before regenerating hashes. Unknown paths fail before contents are read. New legitimate files must be individually added to `EXTRA` in release.py after review; never whitelist a whole runtime directory.
4. Review and stage only the approved files. Run `finish` (or the explicitly limited offline `stage-check`) to validate the actual index, make the authorized local commit, then run `verify-commit`. Each new commit must contain a valid manifest. If a local unpushed commit contains private content, stop and arrange an explicitly authorized history repair; deleting the file in a later commit will not pass.
5. Run `python -B release.py check`. It checks every commit after the audited baseline, including merged histories, not only the final tree. Working changes/untracked nonignored files, missing files, links, submodules, unexpected paths and nonempty catalog fail closed.
6. Run `python -B release.py push` with process-scoped proxy/authentication settings required by the host. It verifies the exact origin push URL, main branch, remote ancestry, increasing version and existing version tags. It creates a lightweight `v<VERSION>` tag at the checked SHA and pushes only that SHA to main and that exact tag with `--atomic`; no force, wildcard tags or mirror. Unsupported atomic pushes fail. Tag conflicts, reused versions with changed content and downgrades stop for review. A remote change requires comparison; do not bypass the gate.
7. The command rechecks the remote branch and exact version tag after push. Verify the anonymously downloaded archive manifest and installed `VERSION`/file hashes separately. After verification, record the same version, commit and tag in the machine-local installation receipt. A failed push can leave a local tag; retry the same verified commit, never move or delete an existing tag automatically. A previously confirmed version/commit is idempotent and does not create a new version.

## Boundaries

The audited baseline is d30213adaf3280a563fa8518a683ccc9c7beb135. Historical commits before it were reviewed separately; the initial historical manifest predates the byte-preservation fix. New commits must pass current checks. Python 3.12+ and Git are required for the release tool, not for merely reading the Skill.

This is a cooperative publishing gate, not a server-side confidentiality guarantee. A user or tool can bypass it with direct Git, alter the gate, or place private prose in an allowed file. Human/AI diff review remains required. GitHub CI after push cannot prevent disclosure and is not used as a substitute. No automatic background publishing or collection is installed.

## 修改前与请求同步时的版本核对

准备修改本公开仓库前，以及用户提出同步/发布时，必须先运行 `python -B release.py inspect`（按宿主规则设置进程级网络代理）。仅使用 Skill 不触发。该命令获取远端对象但不合并、不覆盖工作区；网络失败、祖先不明或检查期间版本变化时停止依赖该结果的操作。

向用户简述：版本是否一致、本地新增/修改/删除、远端新增/修改/删除、暂存/未暂存/未跟踪改动，以及建议理由。提交时间仅供参考，不用于判定新旧。文件列表是证据入口，AI 还需审阅获准文件的实际差异，用一两句话说明功能变化；不要直接倾倒完整 diff。aligned 只表示提交一致，有未提交改动时必须说明工作区并未对齐。

开始修改前有未知本地改动或分叉，先让用户选择保留本地继续、采用远端、审查合并或暂不处理；已对同一差异明确选择不重复问。只有干净可信的源码且仅远端领先时，可以在本次更新授权内说明变化后安全快进。请求发布时，本次已授权且审查过的本地改动可继续；云端新增或分叉则说明差异并等待选择，不自动覆盖或合并。发布入口会再次实时比较并阻止云端领先/分叉；执行前版本变化必须重新解释。独立聊天使用独立分支/工作目录，不接管其他聊天的未完成修改。

### 开始、保存与发布入口

完整的跨机状态与安装流程以 [管理器维护与升级](skills/ai-toolbox-sync/references/self-maintenance.md) 为准。开发允许独立分支，发布目标为 main；所有远端操作使用宿主要求的临时代理。

- `start --installed <Skill目录> --receipt <库外installation.json> --paths <精确路径...>`：联网检查并保存本 worktree 的基线。仅源码维护显式用 `--source-only`。已审阅的本地工作可 `--accept-local`；保留安装定制另用 `--accept-installed`。未知变化先解释，不整包回拷安装目录。
- `start --align` 连同上述模式参数：仅干净可信源码安全快进，不丢弃本地提交、不自动 stash、不合并分叉。应用前后复核状态，保护 ignored 文件。安装目录独立更新后，重新比较并用 `--restart` 建立新基线，旧记录保留；同条件续接沿用原基线。
- `review-update SHA` / `approve-update SHA EXACT_PATH ...`：新公开路径的逐项审查与固定提交批准。AI 审阅后才批准，不能放开目录或执行远端校验器；远端或本地起点改变后批准失效。策略/格式不兼容则在独立目录审阅新校验器后迁移，不绕过检查。
- 完成修改并测试、重建 manifest 后，只暂存获准精确路径，再运行 `finish`，检查实际 index、开始基线和安装状态，刷新远端状态。远端领先、分叉、联网失败或暂未升版不会阻止保存本地进度，均不能视为通过发布检查。开发保存不要求每次升版。
- 缺少完整基线或离线需先保存时，`stage-check` 只检查 index，明确不核实安装/远端。获得本地提交授权后，使用原生 Git 提交并运行 `verify-commit`，验证实际 tree、父提交及分支。临时 index 与工作区不一致时先解释并重新暂存获准内容；不自动覆盖任意一边。
- 发布按 Release 流程处理远端、版本、测试、暂存与核验，再运行 `check` / `push`。有准备收据而实际提交未经核验时禁止发布。所有检查均不自动暂存、提交、上传、安装或添加后台 hook；实际 diff 审阅与测试仍由 AI 执行。

## Manager and collection independence

The manager itself is maintained only here, never collected into a private toolbox. Review generic improvements from private copies file by file; keep private collections and Git history separate. Publish and verify the clean public version before an explicitly authorized removal of a legacy manager collection. Upgrade instructions and compatibility boundaries are in skills/ai-toolbox-sync/references/self-maintenance.md.
