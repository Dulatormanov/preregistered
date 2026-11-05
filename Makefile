# make show-bundle: the newest promotion bundle, before you approve it (tools/show_bundle.py).
# make tables: the sensitivity table (tools/tables.py). It needs OBSERVER_DB_URL; the dev-set column also needs
# the git-ignored golden/private/issues.jsonl and a results file from suite.yml on main (RESULTS=path).
PY ?= python3
RESULTS ?=

tables:
	$(PY) tools/tables.py $(RESULTS)

show-bundle:
	$(PY) tools/show_bundle.py

.PHONY: tables show-bundle
