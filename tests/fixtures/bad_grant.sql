-- A grant that must never exist: tests/test_privilege_matrix.py must fail while it is applied.
set role prereg_owner;
grant update on prereg.predictions to triage_agent;
reset role;
