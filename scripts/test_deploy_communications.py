"""Exercise the pinned communications migration with owned files and fake CLIs."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone

from deploy_application import (
    COMMUNICATIONS_BASELINE, COMMUNICATIONS_CHECKSUM,
    COMMUNICATIONS_COLUMNS, COMMUNICATIONS_MIGRATION, COMMUNICATIONS_PLAN_KIND,
    COMMUNICATIONS_STATUS_KEY, DeployStopped, communications_added_objects,
    communications_schema_snapshot, validate_communications_schema,
)
import test_deploy_application as fixtures
from test_deploy_application import forward_fixture, ready_payload


def status_constraint(*, after=False):
    values = "pending processing sending delivered retrying failed dead cancelled".split()
    if after:
        values = values[:3] + ["accepted"] + values[3:] + ["unknown"]
    return {"kind": "c", "definition": "CHECK (status::text = ANY (ARRAY[" + ", ".join(
        "'" + value + "'::character varying" for value in values) + "]::text[]))",
        "deferrable": False, "initially_deferred": False, "validated": True, "no_inherit": False}


def schema_pair():
    rows = {"namespace:public": {"nspname": "public"}, COMMUNICATIONS_STATUS_KEY: status_constraint()}
    for name in ("alerts", "alert_delivery_jobs", "users", "schema_migrations"):
        rows["relation:public." + name] = {"relname": name, "relkind": "r"}
        rows["column:public." + name + ".id"] = {"type": "integer"}
    before = communications_schema_snapshot(rows.items())
    rows[COMMUNICATIONS_STATUS_KEY] = status_constraint(after=True)
    for key in communications_added_objects():
        rows[key] = {"fixture": key}
        if key.startswith("relation:"):
            name = key.removeprefix("relation:public.")
            rows[key] = {"relname": name, "relkind": "r" if name in COMMUNICATIONS_COLUMNS else
                         "S" if name.endswith("_id_seq") else "i"}
    for name, kind, default in (("notify_voip", "boolean", "false"),
                               ("priority", "character varying(16)", "'normal'::character varying")):
        rows["column:public.alerts." + name] = {
            "type": kind, "nullable": False, "default": default, "identity": "", "generated": ""}
    return before, communications_schema_snapshot(rows.items())


def communications_fixture():
    return forward_fixture() | {"communications": True, "direct_entrypoint": True,
        "current_migrations": copy.deepcopy(COMMUNICATIONS_BASELINE),
        "applied_migrations": copy.deepcopy(COMMUNICATIONS_BASELINE),
        "desired_migrations": COMMUNICATIONS_BASELINE | {COMMUNICATIONS_MIGRATION: COMMUNICATIONS_CHECKSUM}}


def communications_plan_proof(state):
    before, after = schema_pair()
    plan = {"schema_version": 1, "kind": COMMUNICATIONS_PLAN_KIND, "application_version": "2.8.13",
            "commit": state["commit"], "project": "nerkhbaan",
            "readiness_url": "https://fixture.invalid/api/health/ready", "images": state["manifest"]["images"],
            "baseline_backends": [{"id": item["Id"], "image": item["Image"], "release_version": "2.8.12"}
                                  for item in state["containers"] if "nerkhbaan-backend-" in item["Id"]],
            "baseline_migrations": copy.deepcopy(state["current_migrations"]),
            "target_migrations": copy.deepcopy(state["desired_migrations"])}
    proof = {"schema_version": 1, "kind": COMMUNICATIONS_PLAN_KIND,
             "checked_at": datetime.now(timezone.utc).isoformat(),
             "release": {key: copy.deepcopy(value) for key, value in plan.items()
                         if key not in {"schema_version", "kind"}},
             "restore": {"isolated": True, "source_database_container_id": "nerkhbaan-postgres-1",
                         "restore_database": "nerkhbaan_restore_communications",
                         "migration_command": ["python", "-m", "app.migrations.runner"],
                         "migration_image": state["manifest"]["images"]["migrate"],
                         "baseline_migrations": copy.deepcopy(state["current_migrations"]),
                         "target_migrations": copy.deepcopy(state["desired_migrations"]),
                         "existing_data_sha256_before": "1" * 64, "existing_data_sha256_after": "1" * 64,
                         "existing_data_columns": before["data_columns"],
                         "data_fingerprint_scope": "all-public-tables-baseline-columns-except-schema-migrations-v1",
                         "schema_before": before, "schema_after": after,
                         "new_table_rows": {"public." + name: 0 for name in COMMUNICATIONS_COLUMNS},
                         "added_column_nondefault_rows": {"public.alerts.notify_voip": 0, "public.alerts.priority": 0}},
             "compatibility": {"old_image": plan["baseline_backends"][0]["image"],
                               "new_image": state["manifest"]["images"]["backend"],
                               "old_release_version": "2.8.12", "old_ready_status": 503,
                               "old_ready_payload": ready_payload(old=True, communications=True),
                               "old_migration_state": {"current": False, "version": COMMUNICATIONS_MIGRATION,
                                                       "applied_count": 10, "expected_count": 9,
                                                       "missing": [], "changed": [], "unknown": [COMMUNICATIONS_MIGRATION]},
                               "business_probes": [{"path": path, "status": 200, "body_sha256": "2" * 64}
                                                   for path in ("/api/prices", "/api/instruments")],
                               "new_ready_status": 200, "new_ready_payload": ready_payload(communications=True)}}
    fault = state.get("communications_fault")
    if fault == "old_version":
        plan["baseline_backends"][0]["release_version"] = "2.8.11"
    elif fault == "legacy_kind":
        plan["kind"] = "iranian-reference-addition-v1"
    elif fault == "extra_migration":
        plan["target_migrations"]["future.sql"] = "f" * 64
    elif fault == "unrelated_schema":
        proof["restore"]["schema_after"]["objects"]["function:public.unreviewed()"] = "f" * 64
    elif fault == "old_schema_changed":
        proof["restore"]["schema_after"]["objects"]["column:public.users.id"] = "f" * 64
    elif fault == "projection_omitted":
        proof["restore"]["existing_data_columns"] = {}
    elif fault == "new_table_nonempty":
        proof["restore"]["new_table_rows"]["public.communication_events"] = 1
    elif fault == "unsafe_default_rows":
        proof["restore"]["added_column_nondefault_rows"]["public.alerts.notify_voip"] = 1
    elif fault == "restore_name":
        proof["restore"]["restore_database"] = "nerkhbaan"
    elif fault == "scope":
        proof["restore"]["data_fingerprint_scope"] = "only-selected-tables"
    elif fault == "boolean_zero":
        proof["restore"]["new_table_rows"]["public.admin_secrets"] = False
    elif fault == "consistent_wrong_old_version":
        for row in plan["baseline_backends"]: row["release_version"] = "2.8.11"
        proof["release"]["baseline_backends"] = copy.deepcopy(plan["baseline_backends"])
        proof["compatibility"]["old_release_version"] = "2.8.11"
        proof["compatibility"]["old_ready_payload"]["release_version"] = "2.8.11"
    return plan, proof


class CommunicationsSchemaTests(unittest.TestCase):
    def test_canonical_schema_accepts_only_exact_pinned_additions(self):
        before, after = schema_pair()
        self.assertEqual(validate_communications_schema(before, after), before["data_columns"])
        self.assertEqual(len(COMMUNICATIONS_BASELINE), 9)
        self.assertEqual(len(communications_added_objects()), 73)

    def test_unrelated_addition_removal_or_change_is_refused(self):
        for fault in ("addition", "removal", "change", "preexisting_new_table", "missing_added_column"):
            with self.subTest(fault=fault):
                before, after = schema_pair()
                if fault == "addition": after["objects"]["function:public.bad()"] = "a" * 64
                elif fault == "removal": after["objects"].pop("column:public.users.id")
                elif fault == "change": after["objects"]["column:public.users.id"] = "a" * 64
                elif fault == "preexisting_new_table":
                    before["objects"]["type:public.admin_secrets"] = after["objects"]["type:public.admin_secrets"]
                else:
                    after["objects"].pop("column:public.admin_secrets.id")
                with self.assertRaises(DeployStopped): validate_communications_schema(before, after)

    def test_default_constraint_and_hash_tampering_are_refused(self):
        for key, field, value in (("column:public.alerts.notify_voip", "default", "true"),
                                  ("column:public.alerts.priority", "nullable", True),
                                  (COMMUNICATIONS_STATUS_KEY, "definition", "CHECK (true)"),
                                  (COMMUNICATIONS_STATUS_KEY, "validated", False)):
            with self.subTest(key=key, field=field):
                before, after = schema_pair()
                after["details"][key][field] = value
                for rehash in (False, True):
                    if rehash: after["objects"][key] = hashlib.sha256(json.dumps(
                        after["details"][key], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
                    with self.assertRaises(DeployStopped): validate_communications_schema(before, after)

    def test_snapshot_rejects_duplicate_malformed_objects_and_projection_omission(self):
        for rows in ([('same', {}), ('same', {})], [(None, {})], [('object', None)]):
            with self.subTest(rows=rows), self.assertRaises(DeployStopped): communications_schema_snapshot(rows)
        before, after = schema_pair()
        before["data_columns"].pop("public.users")
        with self.assertRaises(DeployStopped): validate_communications_schema(before, after)


class CommunicationsDeployTests(unittest.TestCase):
    run_deploy = fixtures.ApplicationDeployTests.run_deploy
    assert_no_mutation = fixtures.ApplicationDeployTests.assert_no_mutation
    assert_protected_unchanged = fixtures.ApplicationDeployTests.assert_protected_unchanged

    @classmethod
    def setUpClass(cls):
        fixtures.ApplicationDeployTests.setUpClass()
        cls.bash = fixtures.ApplicationDeployTests.bash

    def test_nine_to_ten_wrapper_rolls_replicas_with_exact_ledger_and_protection(self):
        result, final, initial = self.run_deploy(communications_fixture() | {"direct_entrypoint": False})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(COMMUNICATIONS_MIGRATION, result.stdout)
        self.assertEqual(final["applied_migrations"], COMMUNICATIONS_BASELINE | {
            COMMUNICATIONS_MIGRATION: COMMUNICATIONS_CHECKSUM})
        self.assertEqual(final["scale_runs"], 2)
        self.assert_protected_unchanged(initial, final)

    def test_plan_source_schema_data_and_version_faults_fail_before_mutation(self):
        for fault in ("old_version", "legacy_kind", "extra_migration", "unrelated_schema", "old_schema_changed",
                      "projection_omitted", "new_table_nonempty", "unsafe_default_rows", "restore_name", "scope",
                      "boolean_zero", "consistent_wrong_old_version"):
            with self.subTest(fault=fault):
                result, final, initial = self.run_deploy(communications_fixture() | {"communications_fault": fault})
                self.assertNotEqual(result.returncode, 0, fault)
                self.assert_no_mutation(final)
                self.assert_protected_unchanged(initial, final)

    def test_common_proof_and_binding_gates_remain_required_for_tenth_migration(self):
        for fault in ("commit", "images", "baseline", "baseline_checksum", "target_checksum", "proof_target",
                      "past", "future", "no_timezone", "restore_changed", "not_isolated", "source_database",
                      "business_probe", "proof_old_state", "proof_new_ready", "transcript_hash", "proof_hash",
                      "missing_proof", "missing_new_image", "wrong_new_image", "config_migration_command",
                      "config_migration_entrypoint", "proof_migration_command", "proof_migration_image"):
            with self.subTest(fault=fault):
                result, final, initial = self.run_deploy(communications_fixture() | {"plan_fault": fault})
                self.assertNotEqual(result.returncode, 0, fault)
                self.assert_no_mutation(final)
                self.assert_protected_unchanged(initial, final)
        for extra in ({"no_migration_plan": True}, {"source_version": "2.8.12"}, {"plan_fault": "sql_changed"}):
            with self.subTest(extra=extra):
                result, final, _ = self.run_deploy(communications_fixture() | extra)
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_mutation(final)

    def test_live_drift_or_failure_keeps_old_apis_and_never_retries(self):
        for fault in ("post_migration_unknown", "post_migration_checksum_change", "old_other_migration_failure",
                      "old_ready_failure", "new_ready_failure", "wrong_new_hash", "protected_drift",
                      "proof_drift_after_migrate", "proof_drift_after_scale"):
            with self.subTest(fault=fault):
                result, final, _ = self.run_deploy(communications_fixture() | {fault: True})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:2] in (["docker", "stop"], ["docker", "rm"]) for call in final["commands"]))
                self.assertEqual(sum(call[:2] == ["docker", "compose"] and "run" in call
                                     for call in final["commands"]), 1)


if __name__ == "__main__":
    unittest.main()
