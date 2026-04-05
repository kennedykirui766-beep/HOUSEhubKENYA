#!/bin/sh
# Install repository hooks by setting git's core.hooksPath to .githooks
set -e
git config core.hooksPath .githooks
echo "git hooks path set to .githooks"
if [ -d ".githooks" ]; then
  echo "Making hooks executable..."
  chmod +x .githooks/* 2>/dev/null || true
fi
echo "Done. To enable hooks for other clones, run: git config core.hooksPath .githooks"
