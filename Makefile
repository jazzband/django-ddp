NAME := $(shell python setup.py --name)
VERSION := $(shell python setup.py --version)

SDIST := dist/${NAME}-${VERSION}.tar.gz
WHEEL_PY2 := dist/$(subst -,_,${NAME})-${VERSION}-py2-none-any.whl
WHEEL_PY3 := dist/$(subst -,_,${NAME})-${VERSION}-py3-none-any.whl
WHEEL_PYPY := dist/$(subst -,_,${NAME})-${VERSION}-pypy-none-any.whl

.PHONY: all test clean clean-docs clean-dist upload-docs upload-pypi dist

.INTERMEDIATE: dist.intermediate docs

all: docs dist

test:
	tox -vvv

clean: clean-docs clean-dist

clean-docs:
	$(MAKE) -C docs/ clean

clean-dist:
	rm -f "${SDIST}" "${WHEEL_PY2}" "${WHEEL_PY3}"

docs: $(shell find docs/ -type f -name \*.rst) docs/conf.py docs/Makefile $(shell find docs/_static/ -type f) $(shell find docs/_templates/ -type f) README.rst CHANGES.rst
	$(MAKE) -C docs/ clean html
	touch "$@"

dist: ${SDIST} ${WHEEL_PY2} ${WHEEL_PY3}

${SDIST}: dist.intermediate

${WHEEL_PY2}: dist.intermediate

${WHEEL_PY3}: dist.intermediate

${WHEEL_PYPY}:
	tox -e pypy-test-dist

dist.intermediate: $(shell find dddp -type f)
	tox -e py27-test-dist,py34-test-dist

upload: upload-pypi upload-docs

upload-pypi: ${SDIST} ${WHEEL_PY2} ${WHEEL_PY3}
	twine upload "${WHEEL_PY2}" "${WHEEL_PY3}" "${SDIST}"

upload-docs: docs/_build/
	python setup.py upload_sphinx --upload-dir="$<html"
