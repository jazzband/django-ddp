#!/bin/sh
cd "${0%/*}"
cat setup.py | sed -e "s/version='[0123456789]\{1,\}\.[0123456789]\{1,\}\.[01234567989]\{1,\}'/version='$( git rev-parse --abbrev-ref HEAD | cut -d / -f 2 )'/" > setup.py
