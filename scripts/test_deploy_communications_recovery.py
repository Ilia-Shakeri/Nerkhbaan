"""Owned-file recovery contracts; no real Docker, Git, network or credentials."""
from __future__ import annotations
import copy
import hashlib
import json
import tempfile
import unittest
import threading
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timezone
import deploy_application as guard
import deploy_communications_recovery as recovery
from test_deploy_communications import communications_fixture, communications_plan_proof
from test_deploy_application import container, NEW_HASH

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

class OwnedRecovery:

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='communications-recovery-')
        self.base = Path(self.temp.name)
        self.root = self.base / '.releases' / ('a' * 40)
        self.root.mkdir(parents=True)
        self.artifact = self.base / 'private'
        self.artifact.mkdir()
        self.paths = {}
        self.calls = []
        self.stamp = datetime.now(timezone.utc).isoformat()
        self.state = communications_fixture()
        self.old = copy.deepcopy(self.state['containers'][:2])
        for i in range(6):
            self.state['containers'].append(container('extra', str(i), owner='other'))
        self.original = copy.deepcopy(self.state['containers'])
        self.baseline = {r['Id']: guard.fingerprint(r) for r in self.original}
        self.current = copy.deepcopy(self.original)
        self.current[0]['State'].update(Running=False, ExitCode=137, OOMKilled=False)
        self.candidate = container('backend', 'recorded', image=self.state['manifest']['images']['backend'], config_hash=NEW_HASH)
        self.candidate['Id'] = 'e' * 64
        self.candidate['Mounts'] = []
        self.candidate['Config'].update(Env=[],
             User='',
             WorkingDir='',
             StopSignal='',
             Cmd=None,
             Entrypoint=None,
             Healthcheck={'Test': ['CMD',
             'true']})
        self.candidate['HostConfig'].update(ReadonlyRootfs=False,
             RestartPolicy={'Name': 'unless-stopped',
             'MaximumRetryCount': 0})
        self.current.append(self.candidate)
        self.config = copy.deepcopy(self.state['config'])
        self.config['services']['backend'].update(restart='unless-stopped')
        self.image = {'Env': []}
        self.write('private_environment', b'OWNED=fixture', raw=True, name='runtime.private.env')
        rootenv = self.base / '.env'
        rootenv.write_bytes(b'ORIGINAL=fixture')
        (self.root / 'VERSION').write_text('2.8.13')
        original_guard = self.root / 'scripts/deploy_application.py'
        original_guard.parent.mkdir()
        original_guard.write_bytes(b'# immutable original guard fixture')
        original_guard.chmod(384)
        self.write('original_guard', original_guard.read_bytes(), raw=True, name='original-application-guard.py')
        plan, proof = communications_plan_proof(self.state)
        self.write('restore_transcript', {'owned': True}, name='transcript.json')
        proof['transcript'] = self.ref('restore_transcript')
        self.write('restore_report', proof, name='migration-restore-proof.json')
        plan['evidence'] = self.ref('restore_report')
        self.write('migration_plan', plan, name='migration-plan.json')
        self.write('image_manifest', self.state['manifest'], name='prepared-images.json')
        self.write('operator_evidence', {'owned': True}, name='operator-gates.json')
        self.write('compose_override', {}, name='runtime.override.json')
        selected_sha = self.ref('private_environment')['sha256']
        self.write('stage_proof',
             {'passed': True,
             'commit': 'a' * 40,
             'candidate_env_sha256': selected_sha},
             name='stage-proof.json')
        self.write('key_backup', {'passed': True, 'candidate_env_sha256': selected_sha}, name='offhost-key-proof.json')
        self.protected = [r['Id'] for r in self.original if not (guard.project(r) == 'nerkhbaan'
            and guard.service(r) in {'backend',
             'frontend',
             'admin-frontend',
             'price-feed-pull'})]
        self.write('original_preflight',
             {'passed': True,
             'commit': 'a' * 40,
             'checked_at': self.stamp,
             'images': plan['images'],
             'protected_ids': self.protected,
             'plan_sha256': self.ref('migration_plan')['sha256'],
             'operator_sha256': self.ref('operator_evidence')['sha256']},
             name='guard-preflight-proof.json')
        self.write('failed_attempt',
             {'app': 'a' * 40,
             'started_at': self.stamp,
             'preflight_sha256': self.ref('original_preflight')['sha256'],
             'guard_sha256': self.ref('original_guard')['sha256']},
             name='deployment-attempt.json')
        params = {'app': 'a' * 40,
             'baseline': {'container_fingerprints': self.baseline,
             'root_environment_sha256': digest(rootenv.read_bytes())}}
        self.write('original_job', ('PARAMS=' + repr(params) + '\n').encode(), raw=True, name='official-deployment-job.py')
        self.write('original_dispatch', {'job_sha256': self.ref('original_job')['sha256']}, name='deployment-dispatch.json')
        log = ('Migration service completed; verifying pinned addition ' + guard.COMMUNICATIONS_MIGRATION + '\nVerified new backend IDs: ' + self.candidate['Id'] + '\nDeploy stopped: stage=retirement type=command_timeout operation=pair_after_public command=backend_probe\n').encode()
        self.write('failed_log', log, raw=True, name='deployment.private.log')
        self.write('failed_proof',
             {'app': 'a' * 40,
             'passed': False,
             'exit_code': 1,
             'automatic_retry': False,
             'checked_at': self.stamp,
             'log_sha256': digest(log)},
             name='deployment-result.json')
        jobs = [{'id': i + 1,
             'name': n,
             'run_id': 123,
             'run_attempt': 1,
             'head_sha': 'd' * 40,
             'status': 'completed',
             'conclusion': 'success'} for i,
             n in enumerate(sorted(guard.NORMAL_RESUME_CI_JOBS))]
        self.write('guard_ci',
             {'schema_version': 1,
             'guard_commit': 'd' * 40,
             'run_id': 123,
             'run_attempt': 1,
             'run_url': 'https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/123',
             'status': 'completed',
             'conclusion': 'success',
             'jobs': jobs})
        self.binding = {'application_commit': 'a' * 40,
             'guard_commit': 'd' * 40,
             'application_version': '2.8.13',
             'project': 'nerkhbaan',
             'readiness_url': 'https://fixture.invalid/api/health/ready',
             'images': plan['images'],
             'baseline_backends': plan['baseline_backends'],
             'added_backend': {'id': self.candidate['Id'],
             'image': self.candidate['Image'],
             'config_hash': NEW_HASH},
             'stopped_backend': {'id': self.current[0]['Id'],
             'exit_code': 137,
             'oom_killed': False},
             'target_migrations': plan['target_migrations']}
        self.service_hashes = {n: NEW_HASH for n in ['backend', 'frontend', 'admin-frontend', 'price-feed-pull']}
        semantics = recovery.semantic_checks(self.config, self.candidate, self.image, self.current[:2])
        if not all(semantics.values()):
            raise AssertionError(semantics)
        self.write('fresh_observation',
             {'schema_version': 1,
             'kind': guard.COMMUNICATIONS_RESUME_KIND,
             'source': 'actual_target_read_only',
             'checked_at': self.stamp,
             'binding': self.binding,
             'current_container_fingerprints': {r['Id']: guard.fingerprint(r) for r in self.current},
             'semantic_checks': semantics,
             'service_hashes': self.service_hashes,
             'resolved_config_sha256': digest(json.dumps(self.config,
             sort_keys=True,
             separators=(',',
             ':')).encode())})
        app = object.__new__(guard.ApplicationDeploy)
        app.root = self.root
        app.guard_root = self.base / 'guard'
        app.commit = 'a' * 40
        app.project_name = 'nerkhbaan'
        app.readiness_url = self.binding['readiness_url']
        app.replicas = 2
        app.images = {n: ('image:' + n, v) for n, v in plan['images'].items()}
        app.backend_hash = NEW_HASH
        app.config = self.config
        app.service_hashes = self.service_hashes
        app.manifest = self.paths['image_manifest']
        app.evidence = self.paths['operator_evidence']
        app.override = self.paths['compose_override']
        app.env_file = self.paths['private_environment']
        app.plan_path = self.paths['migration_plan']
        app.resume_path = self.artifact / 'resume.json'
        app.resume_plan = None
        app.normal_resume_path = None
        app.normal_resume_plan = None
        app.plan_files = {}
        app.database_id = 'nerkhbaan-postgres-1'
        app.proof = None
        app.migrated = False
        app.run = self.run
        app.check_plan_files = self.check_files
        self.app = app
        return self

    def __exit__(self, *args):
        self.temp.cleanup()

    def write(self, key, value, *, raw=False, name=None):
        path = self.artifact / (name or key + '.json')
        path.write_bytes(value if raw else json.dumps(value).encode())
        path.chmod(384)
        self.paths[key] = path
        return path

    def ref(self, key):
        path = self.paths[key]
        return {'path': str(path), 'sha256': digest(path.read_bytes())}

    def plan(self):
        return {'schema_version': 1,
             'kind': guard.COMMUNICATIONS_RESUME_KIND,
             **self.binding,
             'files': {k: self.ref(k) for k in recovery.RECOVERY_FILES}}

    def run(self, args, **kwargs):
        self.calls.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([{'Config': self.image}])
        if args[0] == 'git':
            if args[-2:] == ['rev-parse', 'HEAD']:
                return 'd' * 40
            if 'status' in args or 'diff' in args:
                return ''
        raise AssertionError('Recovery validation attempted non-read-only command')

    def check_files(self):
        for path, expected in self.app.plan_files.items():
            if path == self.app.resume_path:
                continue
            if digest(path.read_bytes()) != expected:
                raise guard.DeployStopped('Bound file changed')

    def load(self):
        plan = self.plan()
        raw = json.dumps(plan).encode()
        recovery.load_recovery(self.app, self.current, plan, raw)
        migration = json.loads(self.paths['migration_plan'].read_text())
        self.app.load_communications_plan(migration,
             self.paths['migration_plan'].read_bytes(),
             self.binding['target_migrations'],
             {'expected': guard.COMMUNICATIONS_BASELINE,
             'applied': self.binding['target_migrations']})
        return self.app

class RecoveryTests(unittest.TestCase):

    def test_communications_retirement_probes_overlap_and_keep_strict_ledgers(self):
        for mismatch in (False, True):
            with self.subTest(mismatch=mismatch), OwnedRecovery() as fixture:
                app = fixture.load()
                app.migrated = True
                app.startup_deadline = None
                barrier = threading.Barrier(2)
                completed = []

                def probe(item):
                    barrier.wait(timeout=3)
                    old = item['Id'] in app.baseline_backends
                    payload = copy.deepcopy(app.proof['compatibility'][
                        'old_ready_payload' if old else 'new_ready_payload'])
                    if mismatch and not old:
                        payload['redis'] = 'disconnected'
                    completed.append(item['Id'])
                    return {'status': 503 if old else 200, 'payload': payload,
                            'expected': guard.COMMUNICATIONS_BASELINE if old else fixture.binding['target_migrations'],
                            'applied': fixture.binding['target_migrations'],
                            'migration_state': app.old_migration_state() if old else {'current': True}}

                running = [row for row in fixture.current if guard.service(row) == 'backend'
                           and row['State']['Running']]
                with patch.object(app, 'backend_probe', side_effect=probe), patch.object(app, 'guard_old'):
                    if mismatch:
                        with self.assertRaises(guard.DeployStopped):
                            app.strict_pair_healthy(running)
                    else:
                        self.assertTrue(app.strict_pair_healthy(running))
                self.assertCountEqual(completed, [row['Id'] for row in running])

    def test_exact_recorded_stopped_old_and_pinned_tenth_migration_are_accepted(self):
        with OwnedRecovery() as f:
            app = f.load()
            self.assertTrue(app.communications_recovery())
            self.assertEqual(app.normal_stopped['Id'], f.current[0]['Id'])
            self.assertEqual(set(app.proof['restore']['existing_data_columns']),
                 {'public.users',
                 'public.alerts',
                 'public.alert_delivery_jobs'})
            self.assertFalse(any(('stop' in call or 'rm' in call or 'up' in call for call in f.calls)))

    def test_current_identity_health_and_image_drift_are_rejected(self):
        for fault in ['protected', 'running_bit', 'oom', 'extra', 'candidate_image', 'candidate_health', 'old_image']:
            with self.subTest(fault=fault), OwnedRecovery() as f:
                if fault == 'protected':
                    f.current[3]['Config']['unreviewed'] = True
                elif fault == 'running_bit':
                    f.current[0]['State']['Running'] = True
                elif fault == 'oom':
                    f.current[0]['State']['OOMKilled'] = True
                elif fault == 'extra':
                    f.current.append(container('unexpected'))
                elif fault == 'candidate_image':
                    f.candidate['Image'] = 'sha256:wrong'
                elif fault == 'candidate_health':
                    f.candidate['State']['Health']['Status'] = 'unhealthy'
                else:
                    f.current[1]['Image'] = 'sha256:wrong'
                with self.assertRaises(guard.DeployStopped):
                    f.load()

    def test_ci_and_failure_chain_must_be_genuine_complete_and_exact(self):
        faults = [('guard_ci',
             'conclusion',
             'failure'),
             ('guard_ci',
             'guard_commit',
             'f' * 40),
             ('guard_ci',
             'jobs',
             []),
             ('failed_proof',
             'passed',
             True),
             ('failed_attempt',
             'guard_sha256',
             'f' * 64),
             ('original_dispatch',
             'job_sha256',
             'f' * 64),
             ('original_preflight',
             'plan_sha256',
             'f' * 64),
             ('stage_proof',
             'candidate_env_sha256',
             'f' * 64),
             ('key_backup',
             'passed',
             False)]
        for file, key, value in faults:
            with self.subTest(file=file, key=key), OwnedRecovery() as f:
                data = json.loads(f.paths[file].read_text())
                data[key] = value
                f.paths[file].write_text(json.dumps(data))
                with self.assertRaises(guard.DeployStopped):
                    f.load()

    def test_semantic_drift_in_candidate_is_rejected_even_with_rehashed_observation(self):
        for field in ['Env', 'Cmd', 'Entrypoint', 'User', 'WorkingDir', 'StopSignal', 'Healthcheck']:
            with self.subTest(field=field), OwnedRecovery() as f:
                f.candidate['Config'][field] = ['unreviewed'] if field in ['Env',
                     'Cmd',
                     'Entrypoint'] else {'Test': ['NONE']} if field == 'Healthcheck' else 'unreviewed'
                with self.assertRaises(guard.DeployStopped):
                    f.load()

    def test_stale_observation_and_unrelated_ledger_are_refused(self):
        with OwnedRecovery() as f:
            data = json.loads(f.paths['fresh_observation'].read_text())
            data['checked_at'] = '2000-01-01T00:00:00+00:00'
            f.paths['fresh_observation'].write_text(json.dumps(data))
            with self.assertRaises(guard.DeployStopped):
                f.load()
        with OwnedRecovery() as f:
            f.binding['target_migrations']['unreviewed.sql'] = 'f' * 64
            with self.assertRaises(guard.DeployStopped):
                f.load()

    def test_different_original_failure_cannot_select_recovery(self):
        with OwnedRecovery() as f:
            f.paths['failed_log'].write_bytes(b'Unrelated failure')
            with self.assertRaises(guard.DeployStopped):
                f.load()
if __name__ == '__main__':
    unittest.main()
