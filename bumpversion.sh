#!/bin/sh
set -e
cd "${0%/*}"
OLD="$( python setup.py --version )"
NEW="$( git rev-parse --abbrev-ref HEAD | cut -d / -f 2 )"
echo "Bumping version ${OLD} -> ${NEW}...\n"
sed -e "s/^    version='${OLD}'/    version='${NEW}'/" setup.py > .setup.py
mv .setup.py setup.py
sed -e "s/^__version__ = '${OLD}'$/__version__ = '${NEW}'/" dddp/__init__.py > .__init__.py
mv .__init__.py dddp/__init__.py
sed -e "s/^version = '${OLD%.*}'/version = '${NEW%.*}'/" -e "s/^release = '${OLD}'/release = '${NEW}'/" docs/conf.py > docs/.conf.py
mv docs/.conf.py docs/conf.py
git diff setup.py dddp/__init__.py docs/conf.py
