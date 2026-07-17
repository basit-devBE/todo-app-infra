#!/bin/bash
# One-time setup: point git at the repo's tracked hooks directory so the
# pre-push template sync actually runs.
set -euo pipefail

git config core.hooksPath .githooks
echo "Git hooks path set to .githooks - the pre-push template sync is now active."
