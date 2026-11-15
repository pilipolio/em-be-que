#!/bin/sh
# Build the standalone page and publish dist/ to the gh-pages branch (GitHub Pages source).
# Usage: scripts/deploy_pages.sh
set -eu
cd "$(dirname "$0")/.."
python3 scripts/build.py --standalone
remote=$(git remote get-url origin)
revision=$(git rev-parse --short HEAD)
email=$(git config user.email)
name=$(git config user.name)
staging=$(mktemp -d)
cp -R dist/. "$staging"
touch "$staging/.nojekyll"
cd "$staging"
git init -q -b gh-pages
git add -A
git -c user.email="$email" -c user.name="$name" commit -q -m "Deploy $revision"
git -c credential.helper='!gh auth git-credential' push -q -f "$remote" gh-pages
rm -rf "$staging"
echo "deployed $revision to gh-pages"
