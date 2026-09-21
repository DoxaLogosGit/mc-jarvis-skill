#!/usr/bin/env bash
# Assemble the self-contained skill folder a release attaches.
#
# The skill folder holds the tool: SKILL.md beside the package that runs
# it, so the folder can be dropped into a skills directory and used, the
# way skills that ship scripts normally are. Config goes to `_bundled`,
# which is where `paths.py` looks first - the same place a wheel puts it,
# so nothing has to special-case the bundle.
#
# Lives here rather than inline in the workflow so a test can build one
# and look inside it. A release is a bad place to find out what a shell
# step actually produced.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:?usage: build-skill-bundle.sh <output-dir>}"

mkdir -p "$out"
bundle="$out/mc-jarvis"
rm -rf "$bundle"

# `cp -L` resolves the symlinks a checkout uses for SKILL.md, so the
# bundle carries the file rather than a link into a repository that is
# not there.
cp -RL "$root/skill/mc-jarvis" "$bundle"
cp -RL "$root/src/mc_jarvis" "$bundle/scripts/mc_jarvis"
mkdir -p "$bundle/scripts/mc_jarvis/_bundled"
cp -L "$root"/config/*.yaml "$bundle/scripts/mc_jarvis/_bundled/"
cp -L "$root/LICENSE" "$bundle/LICENSE"

# Build artefacts of whoever ran this, not part of the deliverable.
find "$bundle" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$bundle" -name '*.pyc' -delete

echo "$bundle"
