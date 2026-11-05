# make readme: regenerate the README's numbers (tools/readme_numbers.py).
# make verify: recompute every anchor from public data only (notary/verify.py).
# make show-bundle: the newest promotion bundle, before you approve it (tools/show_bundle.py).
# make tables: the sensitivity table (tools/tables.py). It needs OBSERVER_DB_URL; the dev-set column also needs
# the git-ignored golden/private/issues.jsonl and a results file from suite.yml on main (RESULTS=path).
PY ?= python3
RESULTS ?=

tables:
	$(PY) tools/tables.py $(RESULTS)

show-bundle:
	$(PY) tools/show_bundle.py

verify:  # from a clean clone: the public data branch, the Notary log and git, with a read-only GH_TOKEN
	rm -rf .data && git fetch -q origin data && git worktree add -q -f .data origin/data
	$(PY) -m notary.verify .data

tables-public: verify  # the live score from public data only: the data branch and GitHub's public label events
	$(PY) tools/public_tables.py .data

readme:  # the numbers on the README's first screen, from the ledger
	$(PY) tools/readme_numbers.py

.PHONY: tables show-bundle verify tables-public readme
