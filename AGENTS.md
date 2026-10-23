# Public Skill maintenance

This repository is the public maintenance source for ai-toolbox-sync. Private collections and machine bindings belong elsewhere. Never change a private toolbox remote to this repository, import its Git history, or copy an installed Skill directory wholesale.

Read PUBLICATION.md before editing or releasing. Changes to the generic Skill may be published under the owner's existing authorization after validation. This authorization never includes private user data. Do not use Skillshare collect/push to publish this repository.

Preserve the root release tooling, source attribution, and empty active catalog. New paths require explicit allowlist review, not merely regenerating hashes. Review the actual diff for private content even in approved file names. Do not bypass a failing gate.

Run `python -B -m unittest test_release -v`, applicable Skill tests, and the publication gate. Publish only using `python -B release.py push` with the required process-scoped network settings. Report exact commit and unverified boundaries. Direct Git pushes bypass the gate and are not the supported workflow.
