NAME := $(shell python setup.py --name)
VERSION := $(shell python setup.py --version)

SDIST := dist/${NAME}-${VERSION}.tar.gz
WHEEL := dist/${NAME}-${VERSION}-py2.py3-none-any.whl

.PHONY: all test clean clean-docs upload-docs upload-pypi dist docs

all: docs dist

test:
	tox

clean: clean-docs clean-sdist clean-wheel

clean-docs:
	$(MAKE) -C docs/ clean

clean-sdist:
	rm -f "${SDIST}"

clean-wheel:
	rm -f "${WHEEL}"

docs:
	$(MAKE) -C docs/ clean html

${SDIST}:
	python setup.py sdist

${WHEEL}:
	python setup.py bdist_wheel

dist: test ${SDIST} ${WHEEL}

upload: upload-pypi upload-docs

upload-pypi: ${SDIST} ${WHEEL}
	twine upload "${WHEEL}" "${SDIST}"

upload-docs: docs/_build/
	python setup.py upload_sphinx --upload-dir="$<html"
