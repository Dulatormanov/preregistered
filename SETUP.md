Independent project, not affiliated with Supabase.

# Setup

How to run this from nothing. Every secret, its scope and its rotation are in `credentials.toml`.

1. **Postgres.** A free Supabase project. As `postgres`, run `db/001_ledger.sql` to `db/014_contacts.sql` in order, and `db/check_roles.sql` after each: every row must be true. For each job role, run `python3 scripts/role_password.py <role>`: it saves the password in the macOS keychain and copies an `ALTER ROLE ... PASSWORD '<SCRAM verifier>'` line, so the SQL never holds a usable password. Jobs log in through the session pooler (port 5432, user `<role>.<project-ref>`).
2. **GitHub.** Save each `*_DB_URL` as an Actions secret, `PREREG_READ_TOKEN` (a fine-grained token that can read public repositories) and `ANTHROPIC_API_KEY`. Two environments hold the rest, and only `main` may use them:
   - `adopt`: `ADOPTER_DB_URL` and `REDRIVER_DB_URL`;
   - `sandbox-write`: `PREREG_SANDBOX_WRITE` (a fine-grained token for the sandbox repo only, Issues write, 90 days) and `GATEWAY_DB_URL`, with the owner as required reviewer, prevent self-review on and no admin bypass.
3. **The ruleset on main:** a pull request is required, the checks `test` and `eval-gate` must pass, and nobody can bypass it. Turn on "Allow GitHub Actions to create and approve pull requests", for the verdict and result pull requests.
4. **The sandbox repo** (`Dulatormanov/prereg-sandbox`): the six area labels, `probe-label`, `probe-side-door` and `side_door_demo.yml`; `python sandbox/create_fixtures.py` opens the 20 injection fixtures, and `sandbox/targets.toml` lists the synthetic promotion targets.
5. **Healthchecks.io:** a check "tick" (period 15 minutes) whose URL is `HC_TICK_URL`, and a check "watchdog" (period 30, grace 30) whose URL is `HC_WATCHDOG_URL`.
6. **The kill switch** starts off. To let the gateway write, run `select prereg.set_switch(true, 'why')` as `prereg_owner`.
7. **The backup clock.** On a server of your own, put `ops/backup_clock.py` in `~/prereg/`, and next to it, in `~/prereg/token` (mode 600), a fine-grained token with Actions read and write on this repo only. Then add the cron line from the script's first lines. It starts `tick.yml`, `watchdog.yml` and `watch.yml` whenever GitHub's schedule misses a slot (ADR-001).

## Tests

CI runs every test on Supabase's own Postgres image (`ci.yml`). Locally: start `supabase/postgres:17.11.0.018` in Docker, set `PREREG_TEST_ADMIN_URL` to it, run `python tests/setup_test_db.py`, then each file in `tests/`. The database tests refuse to run against anything but localhost.
