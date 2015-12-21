NAME := $(shell python setup.py --name)
VERSION := $(shell python setup.py --version)

SDIST := dist/${NAME}-${VERSION}.tar.gz
WHEEL := dist/$(subst -,_,${NAME})-${VERSION}-py2.py3-none-any.whl

.PHONY: all test clean clean-docs clean-dist upload-docs upload-pypi dist

.INTERMEDIATE: dist.intermediate docs

all: .travis.yml.ok docs dist

test:
	tox --skip-missing-interpreters -vvv

clean: clean-docs clean-dist clean-pyc

clean-docs:
	$(MAKE) -C docs/ clean

clean-dist:
	rm -rf "${SDIST}" "${WHEEL}" dddp/test/build/ dddp/test/meteor_todos/.meteor/local/

clean-pyc:
	find . -type f -name \*.pyc -print0 | xargs -0 rm -f

docs: $(shell find docs/ -type f -name \*.rst) docs/conf.py docs/Makefile $(shell find docs/_static/ -type f) $(shell find docs/_templates/ -type f) README.rst CHANGES.rst
	$(MAKE) -C docs/ clean html
	touch "$@"

dist: ${SDIST} ${WHEEL}
	@echo 'Build successful, `${MAKE} upload` when  ready to release.'

${SDIST}: dist.intermediate
	@echo "Testing ${SDIST}..."
	tox --skip-missing-interpreters --notest --installpkg ${SDIST}

${WHEEL}: dist.intermediate
	@echo "Testing ${WHEEL}..."
	tox --skip-missing-interpreters --notest --installpkg ${WHEEL}

dist.intermediate: $(shell find dddp -type f)
	tox -e dist

upload: upload-pypi upload-docs

upload-pypi: ${SDIST} ${WHEEL}
	twine upload "${WHEEL}" "${SDIST}"

upload-docs: docs/_build/
	python setup.py upload_sphinx --upload-dir="$<html"

.travis.yml.ok: .travis.yml
	@travis --version > "$@" || { echo 'Install travis command line client?'; exit 1; }
	travis lint --exit-code | tee -a "$@"
