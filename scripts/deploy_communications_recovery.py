"""Resume only the recorded communications cutover after one stopped old API.

No migration is rerun. Original receipts, restore proof, private inputs, exact
container identities, semantic configuration and hosted guard CI stay bound.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import json
from pathlib import Path
from datetime import datetime
from deploy_application import COMMUNICATIONS_BASELINE, COMMUNICATIONS_MIGRATION, COMMUNICATIONS_CHECKSUM, COMMUNICATIONS_RESUME_KIND, DeployStopped, NORMAL_RESUME_CI_JOBS, RESUME_FILES, fingerprint, project, service, healthy
RECOVERY_FILES = RESUME_FILES | {'original_preflight',
     'original_dispatch',
     'original_job',
     'original_guard',
     'stage_proof',
     'key_backup'}

def require(value: bool, message: str) -> None:
    if not value:
        raise DeployStopped('Communications recovery: ' + message)
import re
from decimal import Decimal
SEMANTIC_NAMES = {'environment',
     'command',
     'entrypoint',
     'user',
     'working_dir',
     'stop_signal',
     'custom_labels',
     'exposed_ports',
     'healthcheck',
     'cap_drop',
     'security_options',
     'read_only_rootfs',
     'restart_policy',
     'published_ports',
     'mounts',
     'networks'}

def unescape(value):
    if isinstance(value, str):
        return value.replace('$$', '$')
    if isinstance(value, list):
        return [unescape(v) for v in value]
    if isinstance(value, dict):
        return {k: unescape(v) for k, v in value.items()}
    return value

def nanos(value):
    if type(value) is int:
        return value
    if value in (None, ''):
        return 0
    assert isinstance(value, str), 'Unsupported health duration type'
    parts = re.findall('([0-9]+(?:\\.[0-9]+)?)(ns|us|µs|ms|s|m|h)', value)
    assert ''.join((n + u for n, u in parts)) == value, 'Unsupported health duration'
    factors = {'ns': 1, 'us': 1000, 'µs': 1000, 'ms': 1000000, 's': 1000000000, 'm': 60000000000, 'h': 3600000000000}
    return int(sum((Decimal(n) * factors[u] for n, u in parts)))

def semantic_checks(config, item, image, baseline_items):
    spec = unescape(config['services']['backend'])
    runtime = item['Config']
    host = item['HostConfig']
    result = {}
    expected_env = dict((v.split('=', 1) for v in image.get('Env', []) if '=' in v))
    expected_env.update({key: str(value) for key, value in spec.get('environment', {}).items() if value is not None})
    for key, value in spec.get('environment', {}).items():
        if value is None:
            expected_env.pop(key, None)
    actual_env = dict((v.split('=', 1) for v in runtime.get('Env', []) if '=' in v))
    result['environment'] = expected_env == actual_env
    for name, key, src, default in [('command',
         'Cmd',
         'command',
         image.get('Cmd')),
         ('entrypoint',
         'Entrypoint',
         'entrypoint',
         image.get('Entrypoint')),
         ('user',
         'User',
         'user',
         image.get('User',
         '')),
         ('working_dir',
         'WorkingDir',
         'working_dir',
         image.get('WorkingDir',
         '')),
         ('stop_signal',
         'StopSignal',
         'stop_signal',
         image.get('StopSignal',
         ''))]:
        expected = spec.get(src, default)
        expected = default if expected is None else expected
        result[name] = expected == runtime.get(key, '' if isinstance(default, str) else None)
    expected_labels = {**(image.get('Labels') or {}), **(spec.get('labels') or {})}
    actual_labels = {key: value for key,
         value in (runtime.get('Labels')
        or {}).items() if not key.startswith('com.docker.compose.')}
    result['custom_labels'] = expected_labels == actual_labels
    expected_ports = {key: {} for key in image.get('ExposedPorts', {})}
    for port in spec.get('expose', []):
        expected_ports[str(port) if '/' in str(port) else str(port) + '/tcp'] = {}
    result['exposed_ports'] = expected_ports == (runtime.get('ExposedPorts') or {})
    expected_health = dict(image.get('Healthcheck') or {})
    health = spec.get('healthcheck', {})
    if health.get('disable'):
        expected_health = {'Test': ['NONE']}
    else:
        for key, target in [('test',
             'Test'),
             ('interval',
             'Interval'),
             ('timeout',
             'Timeout'),
             ('start_period',
             'StartPeriod'),
             ('start_interval',
             'StartInterval'),
             ('retries',
             'Retries')]:
            if key in health:
                expected_health[target] = nanos(health[key]) if key not in ('test', 'retries') else health[key]
    actual_health = runtime.get('Healthcheck') or {}
    result['healthcheck'] = expected_health.get('Test') == actual_health.get('Test') and all((expected_health.get(key,
         0) == actual_health.get(key,
         0) for key in ['Interval',
         'Timeout',
         'StartPeriod',
         'StartInterval',
         'Retries'])) and (set(actual_health) <= set(expected_health) | {'Interval',
         'Timeout',
         'StartPeriod',
         'StartInterval',
         'Retries'})
    result['cap_drop'] = sorted(spec.get('cap_drop', [])) == sorted(host.get('CapDrop') or [])
    result['security_options'] = sorted(spec.get('security_opt', [])) == sorted(host.get('SecurityOpt') or [])
    result['read_only_rootfs'] = bool(spec.get('read_only', False)) == host.get('ReadonlyRootfs')
    restart = spec.get('restart', 'no')
    parts = restart.split(':', 1)
    result['restart_policy'] = parts[0] == host.get('RestartPolicy',
         {}).get('Name') and (int(parts[1]) if len(parts) == 2 else 0) == host.get('RestartPolicy',
         {}).get('MaximumRetryCount',
         0)
    result['published_ports'] = not spec.get('ports') and (not host.get('PortBindings')) and all((not v for v in item.get('NetworkSettings',
         {}).get('Ports',
         {}).values()))
    expected_mounts = spec.get('volumes', [])
    actual_mounts = item.get('Mounts', [])

    def mount_match(value, mount):
        if mount.get('Destination') != value.get('target') or mount.get('Type') != value.get('type') or mount.get('RW') != (not bool(value.get('read_only',
             False))):
            return False
        if value.get('type') == 'bind':
            return mount.get('Source') == value.get('source')
        if value.get('type') == 'volume':
            return mount.get('Name') == config.get('volumes', {}).get(value.get('source'), {}).get('name')
        return False
    result['mounts'] = len(expected_mounts) == len(actual_mounts) and all((sum((mount_match(v,
         m) for m in actual_mounts)) == 1 for v in expected_mounts))
    expected_networks = {config['networks'][key]['name'] for key in spec.get('networks', {})}
    actual_networks = {name: value['NetworkID'] for name, value in item['NetworkSettings']['Networks'].items()}
    result['networks'] = bool(expected_networks) and set(actual_networks) == expected_networks and all(({name: value['NetworkID'] for name,
         value in old['NetworkSettings']['Networks'].items()} == actual_networks for old in baseline_items))
    assert set(result) == SEMANTIC_NAMES and all((type(value) is bool for value in result.values()))
    return result

def load_recovery(app, current: list[dict], plan: dict, raw: bytes) -> None:
    binding_keys = {'application_commit',
         'guard_commit',
         'application_version',
         'project',
         'readiness_url',
         'images',
         'baseline_backends',
         'added_backend',
         'stopped_backend',
         'target_migrations'}
    target = COMMUNICATIONS_BASELINE | {COMMUNICATIONS_MIGRATION: COMMUNICATIONS_CHECKSUM}
    require(set(plan) == binding_keys | {'schema_version',
         'kind',
         'files'}
        and type(plan['schema_version']) is int
        and (plan['schema_version'] == 1)
        and (plan['kind'] == COMMUNICATIONS_RESUME_KIND)
        and isinstance(plan['guard_commit'],
         str)
        and re.fullmatch('[a-f0-9]{40}',
         plan['guard_commit'])
        and (plan['application_commit'] == app.commit)
        and (plan['application_version'] == '2.8.13')
        and (plan['project'] == app.project_name)
        and (plan['readiness_url'] == app.readiness_url)
        and (plan['images'] == {k: v[1] for k,
         v in app.images.items()})
        and (plan['target_migrations'] == target)
        and (app.replicas == 2)
        and isinstance(plan['files'],
         dict)
        and (set(plan['files']) == RECOVERY_FILES),
         'unsupported exact recovery binding')
    app.resume_plan = plan
    app.plan_files[app.resume_path] = hashlib.sha256(raw).hexdigest()
    inputs = {name: app.read_bound_file(ref) for name, ref in plan['files'].items()}
    app.check_guard_source()
    require(not app.run(['git',
         '-C',
         str(app.guard_root),
         'diff',
         '--name-only',
         app.commit,
         plan['guard_commit'],
         '--',
         'apps',
         'packages',
         'VERSION',
         'package.json',
         'package-lock.json',
         'docker-compose.prod.yaml',
         '.npmrc']),
         'guard recovery changed packaged application inputs')
    selected = {'migration_plan': app.plan_path,
         'image_manifest': app.manifest,
         'operator_evidence': app.evidence,
         'compose_override': app.override,
         'private_environment': app.env_file}
    require(all((path is not None
        and Path(plan['files'][name]['path']).resolve() == path.resolve() for name,
         path in selected.items())),
         'selected runtime or original guard path changed')
    decoded = {name: json.loads(inputs[name]) for name in ('failed_attempt',
         'failed_proof',
         'fresh_observation',
         'guard_ci',
         'original_preflight',
         'original_dispatch',
         'stage_proof',
         'key_backup',
         'migration_plan')}
    attempt, failed, pre = [decoded[n] for n in ('failed_attempt', 'failed_proof', 'original_preflight')]
    require(pre.get('passed') is True
        and pre.get('commit') == app.commit
        and (attempt.get('app') == app.commit)
        and (failed.get('app') == app.commit)
        and (failed.get('passed') is False)
        and (type(failed.get('exit_code')) is int)
        and (failed['exit_code'] != 0)
        and (failed.get('automatic_retry') is False)
        and (attempt.get('preflight_sha256') == plan['files']['original_preflight']['sha256'])
        and (attempt.get('guard_sha256') == plan['files']['original_guard']['sha256'])
        and (failed.get('log_sha256') == plan['files']['failed_log']['sha256'])
        and (decoded['original_dispatch'].get('job_sha256') == plan['files']['original_job']['sha256']),
         'original failed execution chain differs')
    artifact = Path(plan['files']['failed_attempt']['path']).parent
    require(Path(plan['files']['original_guard']['path']) == artifact / 'original-application-guard.py'
        and hashlib.sha256((app.root / 'scripts/deploy_application.py').read_bytes()).hexdigest() == plan['files']['original_guard']['sha256'],
         'original source guard differs from its protected evidence copy')
    expected_names = {'failed_attempt': 'deployment-attempt.json',
         'failed_proof': 'deployment-result.json',
         'failed_log': 'deployment.private.log',
         'original_preflight': 'guard-preflight-proof.json',
         'original_dispatch': 'deployment-dispatch.json',
         'original_job': 'official-deployment-job.py',
         'stage_proof': 'stage-proof.json',
         'key_backup': 'offhost-key-proof.json'}
    require(all((Path(plan['files'][key]['path']) == artifact / name for key,
         name in expected_names.items())),
         'original artifact names changed')
    log = inputs['failed_log'].decode('utf8')
    require('Migration service completed; verifying pinned addition ' + COMMUNICATIONS_MIGRATION in log
        and 'Application deployment passed.' not in log
        and ('Recorded old backend ' not in log)
        and ('stage=retirement type=command_timeout operation=pair_after_public command=backend_probe' in log),
         'failure is outside the reviewed stopped-old retirement boundary')
    tree = ast.parse(inputs['original_job'].decode('utf8'))
    params = ast.literal_eval(tree.body[0].value) if isinstance(tree.body[0],
         ast.Assign) and (len(tree.body[0].targets) == 1
        and isinstance(tree.body[0].targets[0],
         ast.Name)
        and (tree.body[0].targets[0].id == 'PARAMS')) else None
    require(isinstance(params, dict) and params.get('app') == app.commit, 'original job identity differs')
    baseline = params['baseline']['container_fingerprints']
    require(isinstance(baseline, dict) and len(baseline) == 22, 'original inventory is incomplete')
    stage, key = (decoded['stage_proof'], decoded['key_backup'])
    require(stage.get('passed') is True
        and stage.get('commit') == app.commit
        and (stage.get('candidate_env_sha256') == plan['files']['private_environment']['sha256'])
        and (key.get('passed') is True)
        and (key.get('candidate_env_sha256') == stage['candidate_env_sha256'])
        and (pre.get('images') == plan['images'])
        and (pre.get('plan_sha256') == plan['files']['migration_plan']['sha256'])
        and (pre.get('operator_sha256') == plan['files']['operator_evidence']['sha256']),
         'original stage, environment backup or reviewed plan binding changed')
    require(hashlib.sha256((app.root.parent.parent / '.env').read_bytes()).hexdigest() == params['baseline']['root_environment_sha256'],
         'original environment changed')
    ci = decoded['guard_ci']
    jobs = ci.get('jobs')
    require(type(ci.get('schema_version')) is int and ci.get('schema_version') == 1
        and type(ci.get('run_id')) is int
        and (ci['run_id'] > 0)
        and (type(ci.get('run_attempt')) is int)
        and (ci['run_attempt'] > 0)
        and (ci.get('guard_commit') == plan['guard_commit'])
        and (ci.get('status') == 'completed')
        and (ci.get('conclusion') == 'success')
        and (ci.get('run_url') == 'https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/' + str(ci['run_id']))
        and isinstance(jobs,
         list)
        and (len(jobs) == 15)
        and all((isinstance(row,
         dict) for row in jobs))
        and ({row.get('name') for row in jobs} == NORMAL_RESUME_CI_JOBS)
        and (len({row.get('id') for row in jobs}) == 15)
        and all((type(row.get('id')) is int
        and row['id'] > 0
        and (type(row.get('run_id')) is int and row.get('run_id') == ci['run_id'])
        and (type(row.get('run_attempt')) is int and row.get('run_attempt') == ci['run_attempt'])
        and (row.get('head_sha') == plan['guard_commit'])
        and (row.get('status') == 'completed')
        and (row.get('conclusion') == 'success') for row in jobs)),
         'fifteen successful exact-guard hosted jobs required')
    by_id = {item['Id']: item for item in current}
    actual = {key: fingerprint(item) for key, item in by_id.items()}
    old, added, stopped = (plan['baseline_backends'], plan['added_backend'], plan['stopped_backend'])
    require(isinstance(old,
         list)
        and len(old) == 2
        and all((isinstance(row,
         dict) for row in old))
        and (old == decoded['migration_plan'].get('baseline_backends'))
        and all((set(row) == {'id',
         'image',
         'release_version'}
        and row['release_version'] == '2.8.12' for row in old))
        and (len({row['id'] for row in old}) == 2)
        and isinstance(added,
         dict)
        and (set(added) == {'id',
         'image',
         'config_hash'})
        and isinstance(added.get('id'),
         str)
        and re.fullmatch('[a-f0-9]{64}',
         added['id'])
        and ('Verified new backend IDs: ' + added['id'] + '\n' in log)
        and isinstance(stopped,
         dict)
        and (set(stopped) == {'id',
         'exit_code',
         'oom_killed'})
        and (type(stopped['exit_code']) is int)
        and (stopped['exit_code'] in {0,
         137,
         143})
        and (stopped['oom_killed'] is False)
        and (stopped['id'] in {row['id'] for row in old})
        and (set(actual) == set(baseline) | {added['id']})
        and (added['id'] not in baseline),
         'exact old pair, stopped API and one recorded candidate required')
    stopped_item = by_id[stopped['id']]
    restored = copy.deepcopy(stopped_item)
    restored['State']['Running'] = True
    require(stopped_item['State']['Running'] is False
        and stopped_item['State']['ExitCode'] == stopped['exit_code']
        and (stopped_item['State'].get('OOMKilled') is False)
        and (fingerprint(restored) == baseline[stopped['id']])
        and all((actual[key] == value for key,
         value in baseline.items() if key != stopped['id'])),
         'only recorded old running bit may differ')
    protected = set(pre.get('protected_ids', []))
    require(len(protected) == 17
        and protected <= set(baseline)
        and all((key not in protected
        and by_id[key]['Image'] == row['image']
        and (project(by_id[key]) == app.project_name)
        and (service(by_id[key]) == 'backend') for row in old for key in [row['id']])),
         'original protected set or old image changed')
    app.baseline_backends = {row['id']: by_id[row['id']] for row in old}
    candidate = by_id[added['id']]
    require(added['image'] == app.images['backend'][1]
        and added['config_hash'] == app.backend_hash
        and app.desired_backend(candidate)
        and healthy(candidate,
         require_probe=True),
         'candidate not exact and healthy')
    image = json.loads(app.run(['docker', 'image', 'inspect', candidate['Image']]))[0]['Config']
    try:
        semantics = semantic_checks(app.config, candidate, image, list(app.baseline_backends.values()))
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise DeployStopped('Communications recovery semantic model is incomplete') from error
    require(all((value is True for value in semantics.values())), 'candidate semantic configuration differs')
    observation = decoded['fresh_observation']
    app.check_resume_time(observation.get('checked_at'))
    require(type(observation.get('schema_version')) is int and observation.get('schema_version') == 1
        and observation.get('kind') == COMMUNICATIONS_RESUME_KIND
        and (observation.get('source') == 'actual_target_read_only')
        and (observation.get('binding') == {key: plan[key] for key in binding_keys})
        and (observation.get('current_container_fingerprints') == actual)
        and (observation.get('semantic_checks') == semantics)
        and (observation.get('service_hashes') == app.service_hashes)
        and (observation.get('resolved_config_sha256') == hashlib.sha256(json.dumps(app.config,
         sort_keys=True,
         separators=(',',
         ':')).encode()).hexdigest()),
         'fresh observation differs')
    try:
        clocks = [datetime.fromisoformat(value.replace('Z',
             '+00:00')) for value in (pre['checked_at'],
             attempt['started_at'],
             failed['checked_at'],
             observation['checked_at'])]
        require(all((value.tzinfo is not None
            and value.utcoffset().total_seconds() == 0 for value in clocks))
            and clocks == sorted(clocks),
             'original chronology differs')
    except (KeyError, TypeError, ValueError) as error:
        raise DeployStopped('Communications recovery UTC chronology invalid') from error
    require(plan['files']['restore_report'] == decoded['migration_plan']['evidence']
        and plan['files']['restore_transcript'] == json.loads(inputs['restore_report'])['transcript'],
         'original restore or transcript differs')
    app.normal_stopped = stopped_item
    app.normal_resume_observation = observation
    app.resume_observation = observation
    app.resume_attempt = {'baseline_container_roles': {key: {'project': project(by_id[key]),
         'service': service(by_id[key])} for key in baseline}}

def validate_running_pair(app) -> None:
    running = [item for item in app.backends() if item['State'].get('Running')]
    require(len(running) == 2
        and sum((app.desired_backend(item) for item in running)) == 1,
         'one running old and one healthy candidate required')
    require(app.normal_pair_healthy(running), 'strict running pair probe failed')
    app.readiness(allow_old=True)
