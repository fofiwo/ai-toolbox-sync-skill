# Public release boundary

Maintain generic code in this public checkout. Private collections, local bindings, journals and installed runtime data stay outside it. Do not migrate private Git history or repoint private remotes. Do not install this public checkout as a writable runtime catalog.

## Release

1. Review changed content, including allowed Markdown, examples and tests, for private information. The scanner only recognizes selected credential patterns; it cannot infer whether arbitrary prose is private.
2. Run `python -B -m unittest test_release -v` and tests relevant to the Skill changes.
3. Run `python -B release.py manifest`. This checks exact allowed paths, required files, empty active catalog, and selected credential patterns before regenerating hashes. Unknown paths fail before contents are read. New legitimate files must be individually added to `EXTRA` in release.py after review; never whitelist a whole runtime directory.
4. Review and commit only the approved files. Each new commit must contain a valid manifest. If a local unpushed commit contains private content, stop and arrange an explicitly authorized history repair; deleting the file in a later commit will not pass.
5. Run `python -B release.py check`. It checks every commit after the audited baseline, including merged histories, not only the final tree. Working changes/untracked nonignored files, missing files, links, submodules, unexpected paths and nonempty catalog fail closed.
6. Run `python -B release.py push` with process-scoped proxy/authentication settings required by the host. It verifies the exact origin push URL, main branch and remote ancestry, then pushes only the checked SHA to main, without force, tags or mirror. A remote change requires comparison; do not bypass the gate.
7. Verify the remote SHA and anonymously downloaded archive manifest after publishing.

## Boundaries

The audited baseline is d30213adaf3280a563fa8518a683ccc9c7beb135. Historical commits before it were reviewed separately; the initial historical manifest predates the byte-preservation fix. New commits must pass current checks. Python 3.12+ and Git are required for the release tool, not for merely reading the Skill.

This is a cooperative publishing gate, not a server-side confidentiality guarantee. A user or tool can bypass it with direct Git, alter the gate, or place private prose in an allowed file. Human/AI diff review remains required. GitHub CI after push cannot prevent disclosure and is not used as a substitute. No automatic background publishing or collection is installed.
