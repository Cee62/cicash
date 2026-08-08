#!/usr/bin/env bash
# The two publishing steps that need YOUR credentials. I could not run these:
# there is no gh CLI and no PyPI token in this environment, and both actions
# publish irreversibly under your identity.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> tests + conformance vectors"
python3 -m unittest discover -s tests -t . -q

echo "==> build"
rm -rf dist build ./*.egg-info
python3 -m build

echo
echo "1) PyPI  (name 'cicash' was unclaimed when this was written)"
echo "     python3 -m pip install --upgrade twine"
echo "     python3 -m twine upload dist/*          # needs your API token"
echo
echo "2) GitHub"
echo "     gh repo create cicash --public --source=. --remote=origin --push"
echo "   or, without the gh CLI:"
echo "     git remote add origin git@github.com:<you>/cicash.git"
echo "     git branch -M main && git push -u origin main"
echo
echo "Before either: edit NOTICE to put your own name on the copyright line."
