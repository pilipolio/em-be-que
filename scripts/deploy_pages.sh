#!/bin/sh
# Build the standalone page from the last commit and publish it to the gh-pages branch.
# Uncommitted changes are not deployed.
# Usage: scripts/deploy_pages.sh
set -eu
cd "$(dirname "$0")/.."
remote=$(git remote get-url origin)
revision=$(git rev-parse --short HEAD)
email=$(git config user.email)
name=$(git config user.name)
checkout=$(mktemp -d)
git archive HEAD | tar -x -C "$checkout"
python3 "$checkout/scripts/build.py" --standalone
cd "$checkout/dist"
touch .nojekyll
git init -q -b gh-pages
git add -A
git -c user.email="$email" -c user.name="$name" commit -q -m "Deploy $revision"
git -c credential.helper='!gh auth git-credential' push -q -f "$remote" gh-pages
rm -rf "$checkout"
echo "deployed $revision to gh-pages"
