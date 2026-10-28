"""Build and verify one fixed application release on an ephemeral runner."""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import urllib.request
import zipfile


APPLICATION_COMMIT = '228ca5868d90686bb0a476f93179afead83d474a'
BASE_COMMIT = 'fcdac9fc75e974f06162efd9d59dd68cf9257c68'
NODE_BASE_COMMIT = '9a8947b51cb924e3eaf62553193e104db8361834'
VERSION = '2.8.15'
APPLICATION_CI_RUN = 40661404431
REPOSITORY = "Ilia-Shakeri/Nerkhbaan"
PUBLIC_ASSET = 'https://nerkhbaan.ir/assets/index-CgtClNOA.js'
PUBLIC_ASSET_SHA256 = '6230de7ea0e342b2e43a13f9b96eb61d0cca81512fa244783d0b6bfc8ae94663'
PUBLIC_KEY_SHA256 = "0dc48003fa42c7f39424bb09461a9f872943fcc51a48fff61ae4e48ca417a2eb"
EXISTING_PUBLIC_KEY = 'BNg6GMpk04N2Oqp_GRI2DsFRrtJA4M_svcEiNEeJiJuAvQU0U_E6ivDd7C8Z6rHpv5yBYMnXca5vC7BU5ye-vos'
PUBLIC_KEY_OBSERVED_AT = '2026-10-28T08:07:34.964452+00:00'
OPS_PATHS = {".github/workflows/release-runtime-artifacts.yml", "scripts/build_runtime_artifacts.py"}
PATCH_PATHS = {
    '.env.example',
    '.github/workflows/ci.yml',
    '.github/workflows/release-runtime-artifacts.yml',
    '.gitignore',
    'API_DOCUMENTATION.md',
    'CHANGELOG.md',
    'FUTURE_TASKS.md',
    'LICENSE',
    'PROJECT_STATUS.md',
    'README.md',
    'VERSION',
    'apps/admin-web/Dockerfile',
    'apps/admin-web/communications-preview.html',
    'apps/admin-web/package.json',
    'apps/admin-web/public/fonts/Vazir/OFL.txt',
    'apps/admin-web/src/App.tsx',
    'apps/admin-web/src/CommunicationsPage.tsx',
    'apps/admin-web/src/SecurityPage.tsx',
    'apps/admin-web/src/api.ts',
    'apps/admin-web/src/assets/Vazir-Bold.woff2',
    'apps/admin-web/src/assets/Vazir-NOTICE.md',
    'apps/admin-web/src/assets/Vazir-Regular.woff2',
    'apps/admin-web/src/communications-preview-client.ts',
    'apps/admin-web/src/communications-preview.css',
    'apps/admin-web/src/communications-preview.tsx',
    'apps/admin-web/src/communications.css',
    'apps/admin-web/src/pages.tsx',
    'apps/admin-web/src/styles.css',
    'apps/admin-web/src/ui.tsx',
    'apps/api/app/admin/communication_schemas.py',
    'apps/api/app/admin/communication_storage.py',
    'apps/api/app/admin/models.py',
    'apps/api/app/admin/routers/alerts.py',
    'apps/api/app/admin/routers/communications.py',
    'apps/api/app/admin/routers/operations.py',
    'apps/api/app/admin/routers/pricing.py',
    'apps/api/app/config.py',
    'apps/api/app/models.py',
    'apps/api/app/pricing/history.py',
    'apps/api/app/pricing/models.py',
    'apps/api/app/pricing/persistence.py',
    'apps/api/app/pricing/providers.py',
    'apps/api/app/pricing/registry.py',
    'apps/api/app/pricing/rights.py',
    'apps/api/app/pricing/service.py',
    'apps/api/app/release.py',
    'apps/api/app/routers/alerts.py',
    'apps/api/app/routers/notifications.py',
    'apps/api/app/schemas.py',
    'apps/api/app/security.py',
    'apps/api/app/services/alert_delivery_state.py',
    'apps/api/app/services/alert_engine.py',
    'apps/api/app/services/background.py',
    'apps/api/app/services/communication_delivery.py',
    'apps/api/app/services/communication_transport.py',
    'apps/api/app/services/dlq_worker.py',
    'apps/api/db/migrations/20261021_001_communications.sql',
    'apps/api/requirements-dev.lock',
    'apps/api/requirements.lock',
    'apps/api/tests/test_admin_communications.py',
    'apps/api/tests/test_communication_transports.py',
    'apps/api/tests/test_communication_worker.py',
    'apps/api/tests/test_communications_migration.py',
    'apps/api/tests/test_nerkhsanj_markets.py',
    'apps/api/tests/test_nobitex_source_contracts.py',
    'apps/api/tests/test_pricing_refresh_health.py',
    'apps/api/tests/test_pricing_refresh_isolation.py',
    'apps/api/tests/test_pricing_rights_boundaries.py',
    'apps/api/tests/test_pricing_rights_postgres.py',
    'apps/api/tests/test_provider_contracts.py',
    'apps/api/tests/test_smtp_delivery.py',
    'apps/api/tests/test_source_rights_decision_storage.py',
    'apps/api/tests/test_source_rights_policy.py',
    'apps/api/tests/test_step1_transport_worker_insights.py',
    'apps/desktop/package.json',
    'apps/desktop/vite.config.ts',
    'apps/price-feed-pull/Dockerfile',
    'apps/web/Dockerfile',
    'apps/web/package.json',
    'apps/web/public/fonts/Vazir/OFL.txt',
    'apps/web/public/fonts/Vazir/provenance.json',
    'apps/web/src/app/components/SplashScreen.tsx',
    'apps/web/src/app/services/api.ts',
    'apps/web/src/app/views/AlertsView.tsx',
    'apps/web/src/app/views/SettingsView.tsx',
    'apps/web/src/pwa/push-readiness.ts',
    'apps/web/src/pwa/sw.ts',
    'docs/admin-guide.md',
    'docs/admin-release-2.8.13-fa.md',
    'docs/api-contracts.json',
    'docs/api-route-index.md',
    'docs/brand-license-record-2026-10-24.json',
    'docs/client-delivery-roadmap-fa.md',
    'docs/code-signing-policy.md',
    'docs/delivery-readiness.md',
    'docs/desktop-pre-sign-review-2026-10-24.md',
    'docs/free-windows-signing-2026-10-24.md',
    'docs/license-scope.md',
    'docs/live-auth-readiness-2026-10-24.md',
    'docs/notification-delivery-probe.md',
    'docs/operator-workspace-fa.md',
    'docs/pricing-repair-2026-10-28.md',
    'docs/production-readiness-roadmap.md',
    'docs/release-operations.md',
    'docs/signpath-application-draft.md',
    'docs/signpath-submission-2026-10-24.md',
    'docs/source-quality-validation-2026-10-28.md',
    'docs/step4-delivery-acceptance-2026-10-19.md',
    'docs/step5-acceptance-2026-10-24.md',
    'docs/step5-access-fa.md',
    'docs/web-initial-delivery-fa.md',
    'docs/web-push-dns-repair-2026-10-25.md',
    'docs/windows-signing-readiness-fa.md',
    'infra/compose.backend-dns.yaml',
    'infra/relay/Dockerfile',
    'nginx/Dockerfile',
    'package-lock.json',
    'package.json',
    'packages/ui/package.json',
    'playwright.config.ts',
    'scripts/admin-runtime.test.mjs',
    'scripts/build_runtime_artifacts.py',
    'scripts/check-release-version.mjs',
    'scripts/deploy_application.py',
    'scripts/deploy_communications_recovery.py',
    'scripts/desktop-licenses.mjs',
    'scripts/desktop-licenses.test.mjs',
    'scripts/desktop-package-negative.mjs',
    'scripts/desktop-smoke.mjs',
    'scripts/live-web-auth-smoke.mjs',
    'scripts/notification_delivery_probe.py',
    'scripts/operator_access.py',
    'scripts/playwright-admin-panel.config.ts',
    'scripts/playwright-alert-communications.config.ts',
    'scripts/playwright-communications.config.ts',
    'scripts/playwright-web-push.config.ts',
    'scripts/test_deploy_application.py',
    'scripts/test_deploy_communications.py',
    'scripts/test_deploy_communications_recovery.py',
    'scripts/test_deploy_normal_resume.py',
    'scripts/test_notification_delivery_probe.py',
    'scripts/test_operator_access.py',
    'scripts/vendor-licenses/fancy-canvas-2.1.0-LICENSE.txt',
    'scripts/vendor-licenses/manifest.json',
    'scripts/vendor-licenses/radix-ui-primitive-1.1.1-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-arrow-1.1.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-collection-1.1.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-compose-refs-1.1.1-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-context-1.1.1-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-dialog-1.1.6-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-direction-1.1.0-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-dismissable-layer-1.1.5-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-dropdown-menu-2.1.6-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-focus-guards-1.1.1-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-focus-scope-1.1.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-id-1.1.0-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-menu-2.1.6-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-popover-1.1.6-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-popper-1.2.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-portal-1.1.4-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-presence-1.1.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-primitive-2.0.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-roving-focus-1.1.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-slot-1.1.2-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-use-callback-ref-1.1.0-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-use-controllable-state-1.1.0-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-use-escape-keydown-1.1.0-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-use-layout-effect-1.1.0-LICENSE.txt',
    'scripts/vendor-licenses/radix-ui-react-use-size-1.1.0-LICENSE.txt',
    'scripts/vendor-licenses/react-remove-scroll-bar-2.3.8-LICENSE.txt',
    'scripts/vendor-licenses/victory-vendor-36.9.2-LICENSE.txt',
    'scripts/verify-windows-signature.ps1',
    'scripts/web-push-runtime.test.mjs',
    'scripts/windows-installer-preflight.ps1',
    'scripts/windows-installer-preflight.test.mjs',
    'scripts/windows-signature.test.mjs',
    'tests/e2e/admin-communications.spec.ts',
    'tests/e2e/admin-console.spec.ts',
    'tests/e2e/admin-fixture-url.ts',
    'tests/e2e/admin-panel.spec.ts',
    'tests/e2e/alert-communications.spec.ts',
    'tests/e2e/web-push-setup.spec.ts',
}

RECIPES = [
    ("api", "apps/api/Dockerfile", "apps/api"),
    ("web", "apps/web/Dockerfile", "."),
    ("admin-web", "apps/admin-web/Dockerfile", "."),
    ("price-feed-pull", "apps/price-feed-pull/Dockerfile", "apps/price-feed-pull"),
]


def utc_now():
    return datetime.now(timezone.utc)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value, indent=2).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def run(args, *, cwd=None, timeout=120):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Local command failed: " + Path(args[0]).name)
    return result.stdout


def git(source, *args):
    return run(["git", "-C", str(source), *args])



SECURITY_LOCK_OLD = b'certifi==2026.7.22 \\\n    --hash=sha256:62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775 \\\n    --hash=sha256:741e2c3b351ddf169a738da9f2c048608ff7f2c5cc02f1ebc6b118bb090d5d55'
SECURITY_LOCK_NEW = b'certifi==2026.10.23 \\\n    --hash=sha256:a9895e6e2758b371e0545e321a3a8fd1fcfd9829ada8824a936dfb16aaaf36cd \\\n    --hash=sha256:e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1'
GO_BASE_OLD = b"golang:1.26.9-alpine3.24"
GO_BASE_NEW = b"golang:1.26.10-alpine3.24"
NGINX_BASE_OLD = b"nginx:1.30.4-alpine3.24"
NGINX_BASE_NEW = b"nginx:1.30.6-alpine3.24"
VITE_INTEGRITY_OLD = "sha512-NTKlcQjlAK7MlQoyb6LgaqHc8sso/pVyUJYWMws3jg21uTJw/LddqIFPcPqP6PzpgbIcZyKI85sFE4HBrQDA8A=="
VITE_INTEGRITY_NEW = "sha512-xGjU/SyjeNyb0E4KxXBvYz/1C+3JXuujvf2hXNOtnlcE+58o5ajd9N2/n2VhkiJvpCP2qQasnUpx5PXNeI+p1Q=="


def reviewed_runtime_input(path, baseline):
    if path in {"apps/web/Dockerfile", "apps/admin-web/Dockerfile", "nginx/Dockerfile", "infra/relay/Dockerfile"}:
        assert baseline.count(NGINX_BASE_OLD) == 1, "Unreviewed baseline Nginx recipe"
        return baseline.replace(NGINX_BASE_OLD, NGINX_BASE_NEW, 1)
    if path == "apps/price-feed-pull/Dockerfile":
        assert baseline.count(GO_BASE_OLD) == 1, "Unreviewed baseline Go recipe"
        return baseline.replace(GO_BASE_OLD, GO_BASE_NEW, 1)
    if path in {"apps/api/requirements.lock", "apps/api/requirements-dev.lock"}:
        assert baseline.count(SECURITY_LOCK_OLD) == 1, "Unreviewed baseline trust bundle"
        return baseline.replace(SECURITY_LOCK_OLD, SECURITY_LOCK_NEW, 1)
    return baseline



def reviewed_node_manifest(value):
    result = json.loads(json.dumps(value))
    dev = result.get("devDependencies", {})
    if "vite" in dev:
        assert dev["vite"] == "6.4.3", "Unreviewed baseline Vite pin"
        dev["vite"] = "6.4.4"
    return result


def reviewed_node_lock(value):
    result = json.loads(json.dumps(value))
    for path in ["", "apps/web", "apps/admin-web", "apps/desktop", "packages/ui"]:
        result["packages"][path] = reviewed_node_manifest(result["packages"][path])
    vite = result["packages"].get("node_modules/vite")
    if vite is not None:
        assert vite["version"] == "6.4.3" and vite["integrity"] == VITE_INTEGRITY_OLD, "Unreviewed baseline Vite package"
        vite["version"], vite["integrity"] = "6.4.4", VITE_INTEGRITY_NEW
    return result


def validate_source(source, ops, workflow_sha):
    assert re.fullmatch(r"[a-f0-9]{40}", workflow_sha), "Invalid workflow commit"
    for checkout, commit in [(source, APPLICATION_COMMIT), (ops, workflow_sha)]:
        assert git(checkout, "rev-parse", "HEAD").decode().strip() == commit
        assert not git(checkout, "status", "--porcelain", "--untracked-files=all").strip()
    git(source, "merge-base", "--is-ancestor", BASE_COMMIT, APPLICATION_COMMIT)
    git(source, "merge-base", "--is-ancestor", NODE_BASE_COMMIT, APPLICATION_COMMIT)
    changed = set(git(source, "diff", "--name-only", BASE_COMMIT, APPLICATION_COMMIT).decode().splitlines())
    assert changed == PATCH_PATHS, "Application patch differs from reviewed release paths"
    ops_changed = set(git(ops, "diff", "--name-only", APPLICATION_COMMIT, workflow_sha).decode().splitlines())
    assert ops_changed == OPS_PATHS, "Workflow commit includes unrelated application changes"
    assert git(source, "show", APPLICATION_COMMIT + ":VERSION").decode().strip() == VERSION
    for _, recipe, _ in RECIPES:
        assert reviewed_runtime_input(recipe, git(source, "show", BASE_COMMIT + ":" + recipe)) == (source / recipe).read_bytes()
    for path in ["apps/api/requirements.lock", "apps/api/requirements-dev.lock", "apps/price-feed-pull/go.mod", ".npmrc", "scripts/install-dependencies.sh", "nginx/Dockerfile", "infra/relay/Dockerfile"]:
        assert reviewed_runtime_input(path, git(source, "show", BASE_COMMIT + ":" + path)) == (source / path).read_bytes()
    for path in ["package.json", "apps/web/package.json", "apps/admin-web/package.json", "apps/desktop/package.json", "packages/ui/package.json"]:
        old = json.loads(git(source, "show", NODE_BASE_COMMIT + ":" + path))
        current = json.loads((source / path).read_bytes())
        assert current.pop("version") == VERSION
        old.pop("version")
        assert current["license"] == "MIT", "Owner-authorized license required"
        assert old == current, "Unreviewed manifest change"
    old = json.loads(git(source, "show", NODE_BASE_COMMIT + ":package-lock.json"))
    current = json.loads((source / "package-lock.json").read_bytes())
    for manifest in [old, current]:
        manifest.pop("version")
        for path in ["", "apps/web", "apps/admin-web", "apps/desktop", "packages/ui"]:
            manifest["packages"][path].pop("version")
            assert manifest["packages"][path]["license"] == "MIT"
    assert old == current, "Unreviewed lock change"
    return sorted(changed)


def archive_source(checkout, destination):
    raw = git(checkout, "archive", "--format=zip", APPLICATION_COMMIT)
    destination.mkdir()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            assert not entry.filename.startswith("/") and ".." not in Path(entry.filename).parts
        archive.extractall(destination)
    blobs = {}
    for entry in git(checkout, "ls-tree", "-rz", APPLICATION_COMMIT).split(b"\0"):
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        mode, kind, expected = meta.split()
        assert kind == b"blob" and mode in [b"100644", b"100755"]
        filename = os.fsdecode(name)
        content = (destination / filename).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        assert actual == expected.decode(), "Archived source blob differs"
        blobs[filename] = hashlib.sha256(content).hexdigest()
    return {"archive_sha256": hashlib.sha256(raw).hexdigest(), "git_blob_files_verified": len(blobs), "source_sha256": blobs}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError("HTTP redirect refused")


def read_https(url, *, token=None, limit=20 * 1024 * 1024):
    assert url.startswith("https://")
    headers = {"User-Agent": "release-runtime-verifier", "Accept": "application/json" if token else "*/*"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=45) as response:
        assert response.status == 200 and response.geturl() == url
        raw = response.read(limit + 1)
    assert len(raw) <= limit, "Response exceeds reviewed size bound"
    return raw


def recover_public_key(raw):
    assert hashlib.sha256(raw).hexdigest() == PUBLIC_ASSET_SHA256, "Public asset hash differs"
    matches = {value for value in re.findall(rb"[A-Za-z0-9_-]{87}", raw) if hashlib.sha256(value).hexdigest() == PUBLIC_KEY_SHA256}
    assert len(matches) == 1, "Existing public key missing or ambiguous"
    return matches.pop().decode()


def validated_public_key(value=EXISTING_PUBLIC_KEY):
    assert isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{87}", value)
    assert hashlib.sha256(value.encode()).hexdigest() == PUBLIC_KEY_SHA256, "Reviewed public key hash differs"
    decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    assert len(decoded) == 65 and decoded[0] == 4, "Uncompressed public point required"
    return value


def verify_application_ci(repository, token):
    assert repository == REPOSITORY, "Repository differs from reviewed source"
    base = "https://api.github.com/repos/" + repository + "/actions/runs/" + str(APPLICATION_CI_RUN)
    result = json.loads(read_https(base, token=token))
    assert result["id"] == APPLICATION_CI_RUN and result["head_sha"] == APPLICATION_COMMIT
    assert result["status"] == "completed" and result["conclusion"] == "success"
    assert type(result["run_attempt"]) is int and result["run_attempt"] > 0
    jobs = json.loads(read_https(base + "/jobs?per_page=100", token=token))
    assert jobs["total_count"] == 15 and len(jobs["jobs"]) == 15
    for job in jobs["jobs"]:
        assert job["run_id"] == result["id"] and job["head_sha"] == APPLICATION_COMMIT
        assert job["run_attempt"] == result["run_attempt"]
        assert job["status"] == "completed" and job["conclusion"] == "success"
    return {"id": result["id"], "head_sha": result["head_sha"], "status": "completed", "conclusion": "success", "run_attempt": result["run_attempt"], "jobs": [{"name": item["name"], "status": "completed", "conclusion": "success"} for item in jobs["jobs"]]}


def verify_database_clocks(metadata):
    assert type(metadata["Version"]) is int and metadata["Version"] == 2
    clocks = {}
    for key in ["UpdatedAt", "DownloadedAt", "NextUpdate"]:
        value = metadata[key]
        assert isinstance(value, str)
        clocks[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert clocks[key].utcoffset() == timedelta(0), "Scanner clock must use UTC"
    now = utc_now()
    assert now - timedelta(hours=48) <= clocks["UpdatedAt"] <= now + timedelta(minutes=5)
    assert now - timedelta(hours=1) <= clocks["DownloadedAt"] <= now + timedelta(minutes=5)
    assert now < clocks["NextUpdate"] <= now + timedelta(hours=48), "Scanner database expired or date unbounded"
    assert clocks["UpdatedAt"] < clocks["NextUpdate"]


def verify_database(cache, archive_path):
    metadata_bytes = (cache / "db/metadata.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    verify_database_clocks(metadata)
    database_sha = sha256(cache / "db/trivy.db")
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(cache / "db/trivy.db", arcname="db/trivy.db", recursive=False)
        archive.add(cache / "db/metadata.json", arcname="db/metadata.json", recursive=False)
    with tarfile.open(archive_path, "r:gz") as archive:
        assert {item.name for item in archive.getmembers()} == {"db/trivy.db", "db/metadata.json"}
        assert hashlib.file_digest(archive.extractfile("db/trivy.db"), "sha256").hexdigest() == database_sha
        assert archive.extractfile("db/metadata.json").read() == metadata_bytes
    assert (cache / "db/metadata.json").read_bytes() == metadata_bytes
    assert sha256(cache / "db/trivy.db") == database_sha
    return {"verified": True, "metadata": metadata, "archive_sha256": sha256(archive_path), "archive_bytes": archive_path.stat().st_size, "database_sha256": database_sha, "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest()}


def verified_scan_findings(scan, item):
    assert type(scan.get("SchemaVersion")) is int and scan["SchemaVersion"] == 2
    assert scan.get("Metadata", {}).get("ImageID") == item["image_id"], "Scan image binding differs"
    system = scan["Metadata"].get("OS", {})
    assert system.get("Family") == "alpine" and re.fullmatch(r"3\.24(?:\.\d+)?", system.get("Name", ""))
    results = scan.get("Results")
    assert isinstance(results, list) and results, "Scanner returned no package inventory"
    os_results = [row for row in results if isinstance(row, dict) and row.get("Class") == "os-pkgs" and row.get("Type") == "alpine"]
    assert len(os_results) == 1 and os_results[0].get("Target") == item["image_id"] + " (alpine " + system["Name"] + ")"
    packages = os_results[0].get("Packages")
    assert isinstance(packages, list) and packages and all(isinstance(package, dict) and isinstance(package.get("Name"), str) and package["Name"] for package in packages), "Installed OS packages missing"
    kind = item["tag"].split(":")[0].removeprefix("nerkhbaan-")
    if kind in ["api", "price-feed-pull"]:
        language = "python-pkg" if kind == "api" else "gobinary"
        language_rows = [row for row in results if isinstance(row, dict) and row.get("Class") == "lang-pkgs" and row.get("Type") == language]
        expected_target = "Python" if kind == "api" else "usr/local/bin/price-feed-pull"
        assert language_rows and any(row.get("Target", "").lstrip("/") == expected_target and isinstance(row.get("Packages"), list) and row["Packages"] and all(isinstance(package, dict) and isinstance(package.get("Name"), str) and package["Name"] for package in row["Packages"]) for row in language_rows), "Language dependency inventory missing"
    findings = []
    for row in results:
        assert isinstance(row, dict) and isinstance(row.get("Target"), str) and row["Target"]
        vulnerabilities = row.get("Vulnerabilities", [])
        assert isinstance(vulnerabilities, list)
        assert all(isinstance(value, dict) and value.get("Severity") in ["HIGH", "CRITICAL"] for value in vulnerabilities)
        findings.extend(vulnerabilities)
    return findings


def nginx_probe_command(common, image_id):
    return common + ["--cap-add", "CHOWN", "--tmpfs", "/var/cache/nginx:rw,nosuid,nodev,size=16m", "--tmpfs", "/var/run:rw,nosuid,nodev,size=1m", "--entrypoint", "nginx", image_id, "-t"]


class RuntimeBuild:
    def __init__(self, args):
        self.args = args
        self.checkout = args.source.resolve()
        self.ops = args.ops_source.resolve()
        self.out = args.output.resolve()
        self.work = args.work.resolve()
        assert not self.out.exists() and not self.work.exists(), "Output already exists; automatic retry refused"
        self.out.mkdir(parents=True)
        self.work.mkdir(parents=True)
        self.source = self.work / "source"
        self.public_key = ""
        self.provenance = {
            "commit": APPLICATION_COMMIT, "application_commit": APPLICATION_COMMIT,
            "workflow_commit": args.workflow_sha, "version": VERSION,
            "dependency_manifest_baseline": NODE_BASE_COMMIT,
            "workflow_run_id": args.run_id, "workflow_run_attempt": args.run_attempt,
            "repository": args.repository,
        }
        self.before = self.snapshot()

    def proof(self, **values):
        return self.provenance | values

    def logged(self, name, args, *, timeout=2400):
        print("phase: " + name, flush=True)
        try:
            result = subprocess.run(args, cwd=self.work, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raw = b"\n".join(part for part in [error.stdout, error.stderr] if part)
            text = raw.decode(errors="replace").replace(self.public_key, "<public-key>") if self.public_key else raw.decode(errors="replace")
            write_new(self.out / name, ("Operation timed out\n" + text).encode())
            raise RuntimeError("Operation timed out; log " + name) from None
        raw = (result.stdout + b"\n" + result.stderr).decode(errors="replace")
        if self.public_key:
            raw = raw.replace(self.public_key, "<public-key-sha256:" + PUBLIC_KEY_SHA256 + ">")
        write_new(self.out / name, raw.encode())
        if result.returncode:
            raise RuntimeError("Operation failed; log " + name)
        return result.stdout

    def snapshot(self):
        ids = run(["docker", "ps", "-aq", "--no-trunc"]).decode().split()
        objects = json.loads(run(["docker", "inspect", *ids])) if ids else []
        return {item["Id"]: hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest() for item in objects}

    def unchanged(self):
        current = self.snapshot()
        assert all(current.get(key) == value for key, value in self.before.items()), "Preexisting runner container changed"

    def docker(self, *args):
        return run(["docker", *args])

    def prepare(self):
        assert shutil.disk_usage(self.work).free >= 8 * 1024**3, "Runner has less than 8 GiB free"
        assert len(self.args.run_id) <= 30 and self.args.run_id.isdecimal()
        assert type(self.args.run_attempt) is int and self.args.run_attempt > 0
        changed = validate_source(self.checkout, self.ops, self.args.workflow_sha)
        assert self.ops / "scripts/build_runtime_artifacts.py" == Path(__file__).resolve()
        ci = verify_application_ci(self.args.repository, os.environ["GH_TOKEN"])
        source_proof = archive_source(self.checkout, self.source)
        write_new(self.out / "source-build-proof.json", self.proof(**source_proof, allowed_changed_paths=changed, source_archive_only=True, released_notice_code_included=True, application_ci=ci, canonical_recipes=[{"kind": kind, "dockerfile": recipe, "context": context} for kind, recipe, context in RECIPES]))
        self.public_key = validated_public_key()
        write_new(self.out / "build-inputs.json", self.proof(vapid_public_key_sha256=PUBLIC_KEY_SHA256, public_asset_sha256=PUBLIC_ASSET_SHA256, admin_base_path="/admin/", platform="linux/amd64", public_key_source={"kind": "existing_published_web_client_key", "url": PUBLIC_ASSET, "asset_sha256": PUBLIC_ASSET_SHA256, "asset_bytes": 224424, "observed_at": PUBLIC_KEY_OBSERVED_AT, "runner_fetched_public_asset": False, "private_inputs_used": False}))

    def build(self):
        images = []
        for kind, recipe, context in RECIPES:
            tag = "nerkhbaan-" + kind + ":" + VERSION + "-" + APPLICATION_COMMIT[:7]
            assert not self.docker("image", "ls", "-q", tag).strip(), "Release image tag already exists"
            args = ["docker", "buildx", "build", "--load", "--provenance=false", "--pull", "--platform", "linux/amd64", "--progress=plain", "--file", str(self.source / recipe), "--tag", tag]
            if kind == "web":
                args += ["--build-arg", "VITE_VAPID_PUBLIC_KEY=" + self.public_key]
            if kind == "admin-web":
                args += ["--build-arg", "VITE_ADMIN_BASE_PATH=/admin/"]
            self.logged("build-" + kind + ".log", args + [str(self.source / context)])
            image = json.loads(self.docker("image", "inspect", tag))[0]
            assert image["Architecture"] == "amd64" and image["Os"] == "linux"
            images.append({"tag": tag, "image_id": image["Id"], "commit": APPLICATION_COMMIT, "architecture": "amd64", "os": "linux"})
            self.unchanged()
        write_new(self.out / "built-images.json", self.proof(images=images, vapid_public_key_sha256=PUBLIC_KEY_SHA256, admin_base_path="/admin/"))
        return images

    def runtime_checks(self, images):
        checks = {}
        for item in images:
            kind = item["tag"].split(":")[0].removeprefix("nerkhbaan-")
            common = ["docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--label", "org.nerkhbaan.owner=hosted-" + self.args.run_id]
            if kind == "api":
                expected = {"/app/" + str(path.relative_to(self.source / "apps/api")): sha256(path) for path in (self.source / "apps/api/app").rglob("*") if path.is_file()}
                app_count = len(expected)
                migrations = {"/app/" + str(path.relative_to(self.source / "apps/api")): sha256(path) for path in (self.source / "apps/api/db").rglob("*") if path.is_file()}
                migration_count = len(list((self.source / "apps/api/db/migrations").glob("*.sql")))
                assert len(migrations) == 11 and migration_count == 10, "Reviewed DB source count differs"
                expected.update(migrations)
                expected["/app/requirements.lock"] = sha256(self.source / "apps/api/requirements.lock")
                script = (
                    "import hashlib,json,pathlib,os,pwd,subprocess\nfrom app.release import VERSION\nexpected=" + repr(expected)
                    + "\nassert VERSION==" + repr(VERSION) + "\nassert os.getuid()!=0\n"
                    + "for path,wanted in expected.items():assert hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()==wanted,path\n"
                    + "assert subprocess.run(['python','-m','pip','check'],capture_output=True).returncode==0\n"
                    + "print(json.dumps({'git_source_files_matched':" + str(app_count) + ",'migration_source_files_matched':" + str(migration_count) + ",'db_source_files_matched':" + str(len(migrations)) + ",'requirements_lock_matched':True,'runtime_user':pwd.getpwuid(os.getuid()).pw_name,'pip_check_passed':True,'release_version':VERSION,'history_sha256':expected['/app/app/pricing/history.py']}))"
                )
                checks[kind] = json.loads(self.logged("runtime-api-check.log", common + ["--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m", "--entrypoint", "python", item["image_id"], "-c", script], timeout=120))
            elif kind in ["web", "admin-web"]:
                self.logged("runtime-" + kind + "-nginx.log", nginx_probe_command(common, item["image_id"]), timeout=60)
                for name, target in [("nginx.conf", "/etc/nginx/conf.d/default.conf"), ("security-headers.conf", "/etc/nginx/security-headers.inc")]:
                    assert run(common + ["--entrypoint", "cat", item["image_id"], target]) == (self.source / "apps" / kind / name).read_bytes()
                raw = run(common + ["--entrypoint", "sh", item["image_id"], "-c", "tar -C /usr/share/nginx/html -cf - ."])
                with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                    files = {}
                    for member in archive.getmembers():
                        assert member.isfile() or member.isdir()
                        if member.isfile():
                            files[member.name.removeprefix("./")] = archive.extractfile(member).read()
                assert files.get("index.html")
                record = {"image_id": item["image_id"], "static_files": len(files), "nginx_source_config_matched": True, "security_headers_source_matched": True, "nginx_config_passed": True, "probe_cap_add": ["CHOWN"], "static_sha256": {"./" + name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}}
                scripts = {name: raw for name, raw in files.items() if name.endswith(".js")}
                assert scripts
                if kind == "web":
                    joined = b"\n".join(scripts.values())
                    assert ("v" + VERSION).encode() in joined
                    assert all(marker in joined for marker in [b"Windows notices for this session", b"desktop-open-inbox", b"Native notice deadline"])
                    public_assets = [name for name, raw in scripts.items() if any(hashlib.sha256(value).hexdigest() == PUBLIC_KEY_SHA256 for value in re.findall(rb"[A-Za-z0-9_-]{87}", raw))]
                    assert public_assets
                    record.update(production_public_vapid_key_embedded=True, vapid_public_key_sha256=PUBLIC_KEY_SHA256, public_key_asset_files=["./" + name for name in public_assets], release_version=VERSION, native_notice_code_present=True)
                else:
                    assets = re.findall(r"(?:src|href)=[\"']([^\"']+\.(?:js|css))[\"']", files["index.html"].decode())
                    assert assets and all(path.startswith("/admin/assets/") for path in assets)
                    record["admin_asset_base_path"] = "/admin/"
                checks[kind] = record
            else:
                raw = run(common + ["--entrypoint", "cat", item["image_id"], "/usr/local/bin/price-feed-pull"])
                assert raw[:4] == b"\x7fELF" and raw[4:6] == b"\x02\x01" and int.from_bytes(raw[18:20], "little") == 62
                checks[kind] = {"linux_elf": True, "binary_sha256": hashlib.sha256(raw).hexdigest(), "architecture": "amd64", "image_id": item["image_id"]}
            self.unchanged()
        assert set(checks) == {kind for kind, _, _ in RECIPES}
        write_new(self.out / "runtime-build-checks.json", self.proof(all_passed=True, checks=checks, source_archive_only=True, released_notice_code_included=True))

    def scan(self, images):
        version = run(["trivy", "--version"]).decode()
        assert re.search(r"^Version:\s*0\.70\.0\s*$", version, re.MULTILINE), "Scanner version differs"
        cache = self.work / "scan-cache"
        assert not cache.exists(), "Fresh scanner cache required"
        download_started_at = utc_now().isoformat()
        self.logged("runtime-trivy-db-download.log", ["trivy", "image", "--download-db-only", "--cache-dir", str(cache)], timeout=600)
        database = verify_database(cache, self.work / "verified-trivy-db.tar.gz")
        database.update(download_started_at=download_started_at, download_completed_at=utc_now().isoformat())
        results = []
        for item in images:
            kind = item["tag"].split(":")[0].removeprefix("nerkhbaan-")
            report = self.out / ("runtime-trivy-" + kind + ".json")
            args = ["trivy", "image", "--cache-dir", str(cache), "--skip-db-update", "--skip-java-db-update", "--offline-scan", "--list-all-pkgs", "--scanners", "vuln", "--severity", "HIGH,CRITICAL", "--ignore-unfixed=false", "--ignorefile", "/dev/null", "--exit-code", "1", "--format", "json", "--output", str(report), "--no-progress", item["image_id"]]
            result = subprocess.run(args, cwd=self.work, capture_output=True, timeout=600)
            write_new(self.out / ("runtime-trivy-" + kind + ".log"), result.stdout + b"\n" + result.stderr)
            assert result.returncode in [0, 1] and report.is_file(), "Scanner did not produce a valid report"
            os.chmod(report, 0o600)
            scan = json.loads(report.read_bytes())
            findings = verified_scan_findings(scan, item)
            results.append({"tag": item["tag"], "image_id": item["image_id"], "returncode": result.returncode, "high_critical_count": len(findings)})
            self.unchanged()
            if result.returncode or findings:
                write_new(self.out / "runtime-trivy-summary.json", self.proof(all_passed=False, images=results, severity="HIGH,CRITICAL", ignore_unfixed=False, database=database))
                raise RuntimeError("Strict scan failed; image export refused")
        verify_database_clocks(database["metadata"])
        assert sha256(cache / "db/trivy.db") == database["database_sha256"]
        assert sha256(cache / "db/metadata.json") == database["metadata_sha256"]
        write_new(self.out / "runtime-trivy-summary.json", self.proof(all_passed=True, images=results, severity="HIGH,CRITICAL", ignore_unfixed=False, database=database, scanner_version="0.70.0"))

    def export(self, images):
        for item in images:
            assert json.loads(self.docker("image", "inspect", item["tag"]))[0]["Id"] == item["image_id"]
        archive = self.work / "application-images.tar"
        self.logged("image-export.log", ["docker", "image", "save", "--output", str(archive), *[item["tag"] for item in images]], timeout=900)
        compressed = self.out / ("application-images-" + APPLICATION_COMMIT + ".tar.gz")
        with archive.open("rb") as source, compressed.open("xb") as target, gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as destination:
            shutil.copyfileobj(source, destination, 1024 * 1024)
        os.chmod(compressed, 0o600)
        bundle = self.out / ("source-" + APPLICATION_COMMIT + ".bundle")
        assert git(self.checkout, "rev-parse", "HEAD").decode().strip() == APPLICATION_COMMIT
        git(self.checkout, "bundle", "create", str(bundle), "HEAD")
        assert git(self.checkout, "bundle", "list-heads", str(bundle)).decode().splitlines() == [APPLICATION_COMMIT + " HEAD"]
        git(self.checkout, "bundle", "verify", str(bundle))
        os.chmod(bundle, 0o600)
        rows = [{key: item[key] for key in ["tag", "image_id", "commit"]} for item in images]
        pack = self.proof(schema_version=1, images=rows, source={"path": bundle.name, "sha256": sha256(bundle), "bytes": bundle.stat().st_size}, archive={"path": compressed.name, "sha256": sha256(compressed), "bytes": compressed.stat().st_size})
        self.unchanged()
        write_new(self.out / "hosted-transfer-pack.json", pack)
        write_new(self.out / "image-export-proof.json", self.proof(all_scans_passed=True, runtime_source_validation_passed=True, transfer_pack="hosted-transfer-pack.json", unowned_containers_preserved=len(self.before), target_actions=0, artifact_sha256={path.name: sha256(path) for path in self.out.iterdir() if path.is_file()}))

    def execute(self):
        write_new(self.out / "build-attempt.json", self.proof(started_at=utc_now().isoformat(), automatic_retry=False, preexisting_container_fingerprints=self.before))
        try:
            self.prepare()
            images = self.build()
            self.runtime_checks(images)
            self.scan(images)
            self.export(images)
        except Exception as error:
            write_new(self.out / "build-failure.json", self.proof(passed=False, error_type=type(error).__name__, export_ready=False))
            raise


class OfflineContracts(unittest.TestCase):
    def test_workflow_artifact_name_binds_application_version_and_short_commit(self):
        workflow = Path(__file__).resolve().parents[1] / '.github/workflows/release-runtime-artifacts.yml'
        expected = 'name: release-runtime-' + VERSION + '-' + APPLICATION_COMMIT[:7] + '-${{ github.run_id }}-${{ github.run_attempt }}'
        self.assertIn(expected, workflow.read_text(encoding='utf8'))

    def test_node_patch_changes_only_exact_vite_pin_and_integrity(self):
        old = {"devDependencies": {"vite": "6.4.3", "typescript": "5.9.3"}, "custom": True}
        self.assertEqual(reviewed_node_manifest(old), {"devDependencies": {"vite": "6.4.4", "typescript": "5.9.3"}, "custom": True})
        self.assertEqual(old["devDependencies"]["vite"], "6.4.3")
        lock = {"packages": {key: {} for key in ["", "apps/web", "apps/admin-web", "apps/desktop", "packages/ui"]}}
        lock["packages"]["node_modules/vite"] = {"version": "6.4.3", "integrity": VITE_INTEGRITY_OLD, "other": "keep"}
        result = reviewed_node_lock(lock)
        self.assertEqual(result["packages"]["node_modules/vite"], {"version": "6.4.4", "integrity": VITE_INTEGRITY_NEW, "other": "keep"})
        for field, value in [("version", "6.4.2"), ("integrity", "unreviewed")]:
            changed = json.loads(json.dumps(lock))
            changed["packages"]["node_modules/vite"][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                reviewed_node_lock(changed)

    def test_security_input_patch_allows_only_pinned_trust_bundle_and_go_tag(self):
        for path, old, new in [
            ("apps/api/requirements.lock", SECURITY_LOCK_OLD, SECURITY_LOCK_NEW),
            ("apps/api/requirements-dev.lock", SECURITY_LOCK_OLD, SECURITY_LOCK_NEW),
            ("apps/price-feed-pull/Dockerfile", GO_BASE_OLD, GO_BASE_NEW),
            ("apps/admin-web/Dockerfile", NGINX_BASE_OLD, NGINX_BASE_NEW),
        ]:
            self.assertEqual(reviewed_runtime_input(path, b"prefix\n" + old + b"\nsuffix"),
                             b"prefix\n" + new + b"\nsuffix")
            for invalid in (b"unreviewed", old + old, new):
                with self.subTest(path=path), self.assertRaises(AssertionError):
                    reviewed_runtime_input(path, invalid)
        self.assertEqual(reviewed_runtime_input("apps/api/Dockerfile", b"keep"), b"keep")

    def test_nginx_probe_adds_only_chown_with_network_readonly_and_other_caps_dropped(self):
        common = ["docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--label", "org.nerkhbaan.owner=fixture"]
        command = nginx_probe_command(common, "sha256:" + "a" * 64)
        self.assertEqual(command[:len(common)], common)
        self.assertEqual([command[index + 1] for index, value in enumerate(command) if value == "--cap-add"], ["CHOWN"])
        self.assertEqual(command[-3:], ["nginx", "sha256:" + "a" * 64, "-t"])
        self.assertNotIn("--privileged", command)
        self.assertNotIn("--network=host", command)
        self.assertNotIn("--cap-add=ALL", command)
        self.assertNotIn("SYS_ADMIN", command)

    def test_published_client_key_requires_exact_hash_alphabet_and_public_point(self):
        self.assertEqual(validated_public_key(), EXISTING_PUBLIC_KEY)
        for value in [EXISTING_PUBLIC_KEY + "x", EXISTING_PUBLIC_KEY[:-1] + "!", "A" + EXISTING_PUBLIC_KEY[1:]]:
            with self.subTest(length=len(value)), self.assertRaises(AssertionError):
                validated_public_key(value)
        compressed = base64.urlsafe_b64encode(b"\x02" + b"\0" * 64).decode().rstrip("=")
        with patch(__name__ + ".PUBLIC_KEY_SHA256", hashlib.sha256(compressed.encode()).hexdigest()), self.assertRaises(AssertionError):
            validated_public_key(compressed)

    def test_authenticated_redirect_is_refused_before_any_followup_request(self):
        request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY, headers={"Authorization": "Bearer test-only"})
        for destination in ["https://other.example/blob", "https://api.github.com/redirect", "http://api.github.com/plain"]:
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                NoRedirect().redirect_request(request, None, 302, "redirect", {}, destination)

    def test_source_and_ops_scope_reject_dirty_foreign_and_dependency_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, ops = root / "source", root / "ops"
            source.mkdir()
            ops.mkdir()
            workflow_sha = "b" * 40
            previous = {}
            for _, recipe, _ in RECIPES:
                previous[recipe] = b"original recipe"
            for path in ["apps/api/requirements.lock", "apps/api/requirements-dev.lock", "apps/price-feed-pull/go.mod", ".npmrc", "scripts/install-dependencies.sh", "nginx/Dockerfile", "infra/relay/Dockerfile"]:
                previous[path] = b"locked original input"
            for recipe in ["apps/web/Dockerfile", "apps/admin-web/Dockerfile", "nginx/Dockerfile", "infra/relay/Dockerfile"]:
                previous[recipe] = b"FROM " + NGINX_BASE_OLD + b" AS runtime\n"
            previous["apps/price-feed-pull/Dockerfile"] = b"FROM " + GO_BASE_OLD + b" AS builder\n"
            previous["apps/api/requirements.lock"] = previous["apps/api/requirements-dev.lock"] = SECURITY_LOCK_OLD + b"\n"
            manifests = ["package.json", "apps/web/package.json", "apps/admin-web/package.json", "apps/desktop/package.json", "packages/ui/package.json"]
            for path in manifests:
                previous[path] = json.dumps({"version": "2.8.8", "license": "MIT", "scripts": {"build": "original"}}).encode()
            lock = {"version": "2.8.8", "packages": {key: {"version": "2.8.8", "license": "MIT"} for key in ["", "apps/web", "apps/admin-web", "apps/desktop", "packages/ui"]}}
            previous["package-lock.json"] = json.dumps(lock).encode()
            for path, raw in previous.items():
                target = source / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw.replace(b"2.8.8", VERSION.encode()) if path.endswith("package.json") or path == "package-lock.json" else reviewed_runtime_input(path, raw))
            state = {"dirty": False, "foreign": False, "head": APPLICATION_COMMIT}

            def read(checkout, *args):
                if args[0] == "rev-parse":
                    return (state["head"] if checkout == source else workflow_sha).encode()
                if args[0] == "status":
                    return b"?? unreleased.txt" if state["dirty"] and checkout == source else b""
                if args[0] == "merge-base":
                    return b""
                if args[0] == "diff":
                    paths = PATCH_PATHS if checkout == source else (OPS_PATHS | {"apps/web/src/app/App.tsx"} if state["foreign"] else OPS_PATHS)
                    return "\n".join(sorted(paths)).encode()
                if args[0] == "show":
                    path = args[1].split(":", 1)[1]
                    return VERSION.encode() if path == "VERSION" else previous[path]
                raise AssertionError(args)

            with patch(__name__ + ".git", side_effect=read):
                self.assertEqual(validate_source(source, ops, workflow_sha), sorted(PATCH_PATHS))
                for key, value in [("dirty", True), ("foreign", True), ("head", "c" * 40)]:
                    original = state[key]
                    state[key] = value
                    with self.subTest(key=key), self.assertRaises(AssertionError):
                        validate_source(source, ops, workflow_sha)
                    state[key] = original
                (source / "apps/api/requirements.lock").write_bytes(b"changed dependency")
                with self.assertRaises(AssertionError):
                    validate_source(source, ops, workflow_sha)

    def test_ci_proof_needs_all_fifteen_jobs_from_same_successful_attempt(self):
        run_info = {"id": APPLICATION_CI_RUN, "head_sha": APPLICATION_COMMIT, "status": "completed", "conclusion": "success", "run_attempt": 1}
        job = {"run_id": APPLICATION_CI_RUN, "head_sha": APPLICATION_COMMIT, "run_attempt": 1, "status": "completed", "conclusion": "success", "name": "check"}
        jobs = {"total_count": 15, "jobs": [dict(job) for _ in range(15)]}
        with patch(__name__ + ".read_https", side_effect=lambda url, **_: json.dumps(jobs if "/jobs?" in url else run_info).encode()):
            self.assertEqual(len(verify_application_ci(REPOSITORY, "unused")["jobs"]), 15)
            with self.assertRaises(AssertionError):
                verify_application_ci("foreign/repo", "unused")
            for target, key, value in [(run_info, "conclusion", "failure"), (run_info, "run_attempt", True), (jobs["jobs"][0], "head_sha", "c" * 40), (jobs["jobs"][0], "run_attempt", 2), (jobs["jobs"][0], "status", "in_progress")]:
                original = target[key]
                target[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                    verify_application_ci(REPOSITORY, "unused")
                target[key] = original

    def test_strict_scan_failure_or_wrong_image_cannot_write_green_summary(self):
        for returncode, findings, wrong_image, empty, missing_packages in [(0, [{"Severity": "HIGH"}], False, False, False), (1, [], False, False, False), (0, [], True, False, False), (0, [], False, True, False), (0, [], False, False, True), (0, [], False, False, False)]:
            with self.subTest(returncode=returncode, wrong_image=wrong_image, findings=bool(findings), empty=empty, missing_packages=missing_packages), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                build = object.__new__(RuntimeBuild)
                build.work, build.out = root / "work", root / "out"
                build.work.mkdir()
                build.out.mkdir()
                build.provenance = {"commit": APPLICATION_COMMIT}
                build.logged = lambda *_args, **_kwargs: b""
                build.unchanged = lambda: None
                images = [{"tag": "nerkhbaan-" + kind + ":" + VERSION, "image_id": "sha256:" + str(index) * 64} for index, (kind, _, _) in enumerate(RECIPES, 1)]
                now = utc_now()
                metadata = {"Version": 2, "NextUpdate": (now + timedelta(hours=24)).isoformat(), "UpdatedAt": now.isoformat(), "DownloadedAt": now.isoformat()}
                proof = {"verified": True, "metadata": metadata, "database_sha256": "a" * 64, "metadata_sha256": "a" * 64}

                def scanner(args, **_kwargs):
                    report = Path(args[args.index("--output") + 1])
                    rows = [
                        {"Target": args[-1] + " (alpine 3.24.2)", "Class": "os-pkgs", "Type": "alpine", "Packages": [] if missing_packages else [{"Name": "alpine-baselayout", "Version": "3.7.1-r0"}], "Vulnerabilities": findings},
                        {"Target": "Python", "Class": "lang-pkgs", "Type": "python-pkg", "Packages": [{"Name": "pip", "Version": "25.2"}]},
                        {"Target": "usr/local/bin/price-feed-pull", "Class": "lang-pkgs", "Type": "gobinary", "Packages": [{"Name": "stdlib", "Version": "v1.26.10"}]},
                    ]
                    report.write_text(json.dumps({"SchemaVersion": 2, "Metadata": {"ImageID": "foreign" if wrong_image else args[-1], "OS": {"Family": "alpine", "Name": "3.24.2"}}, "Results": [] if empty else rows}))
                    return subprocess.CompletedProcess(args, returncode, b"", b"")

                with patch(__name__ + ".run", return_value=b"Version: 0.70.0\n"), patch(__name__ + ".verify_database", return_value=proof), patch(__name__ + ".sha256", return_value="a" * 64), patch(__name__ + ".subprocess.run", side_effect=scanner):
                    if returncode or findings or wrong_image or empty or missing_packages:
                        with self.assertRaises((AssertionError, RuntimeError)):
                            build.scan(images)
                        summary = build.out / "runtime-trivy-summary.json"
                        self.assertFalse(summary.exists() and json.loads(summary.read_text())["all_passed"])
                    else:
                        build.scan(images)
                        result = json.loads((build.out / "runtime-trivy-summary.json").read_text())
                        self.assertTrue(result["all_passed"])
                        self.assertEqual(len(result["images"]), 4)
                        self.assertFalse(result["ignore_unfixed"])
                        self.assertEqual(result["severity"], "HIGH,CRITICAL")
                self.assertFalse((build.out / "hosted-transfer-pack.json").exists())

    def test_public_key_requires_both_exact_asset_and_key_hash(self):
        key = b"K" * 87
        raw = b"public=" + key
        with patch(__name__ + ".PUBLIC_ASSET_SHA256", hashlib.sha256(raw).hexdigest()), patch(__name__ + ".PUBLIC_KEY_SHA256", hashlib.sha256(key).hexdigest()):
            self.assertEqual(recover_public_key(raw), key.decode())
            with self.assertRaises(AssertionError):
                recover_public_key(raw + b"changed")
        with patch(__name__ + ".PUBLIC_ASSET_SHA256", hashlib.sha256(raw).hexdigest()), self.assertRaises(AssertionError):
            recover_public_key(raw)

    def test_database_archive_roundtrip_and_expiry_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "db").mkdir()
            (root / "db/trivy.db").write_bytes(b"owned database")
            now = utc_now()
            metadata = {"Version": 2, "NextUpdate": (now + timedelta(hours=24)).isoformat(), "UpdatedAt": now.isoformat(), "DownloadedAt": now.isoformat()}
            (root / "db/metadata.json").write_text(json.dumps(metadata))
            proof = verify_database(root, root / "verified.tar.gz")
            self.assertIs(proof["verified"], True)
            self.assertEqual(proof["database_sha256"], sha256(root / "db/trivy.db"))
            for key, value in [
                ("NextUpdate", (now - timedelta(seconds=1)).isoformat()),
                ("NextUpdate", (now + timedelta(hours=49)).isoformat()),
                ("UpdatedAt", (now - timedelta(hours=49)).isoformat()),
                ("DownloadedAt", (now - timedelta(hours=2)).isoformat()),
                ("DownloadedAt", (now + timedelta(minutes=6)).isoformat()),
                ("DownloadedAt", "0001-01-01T00:00:00Z"),
            ]:
                changed = metadata | {key: value}
                (root / "db/metadata.json").write_text(json.dumps(changed))
                with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                    verify_database(root, root / "expired.tar.gz")
                self.assertFalse((root / "expired.tar.gz").exists())

    def test_exclusive_proof_keeps_first_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "proof.json"
            write_new(path, {"first": True})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_new(path, {"first": False})
            self.assertEqual(path.read_bytes(), original)

    def test_archived_build_context_excludes_dirty_and_untracked_files(self):
        with tempfile.TemporaryDirectory(prefix="runtime-source-contract-") as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            checkout.mkdir()
            git(checkout, "init", "-q")
            (checkout / "tracked.txt").write_bytes(b"committed source")
            git(checkout, "add", "tracked.txt")
            git(checkout, "-c", "user.name=Local Check", "-c", "user.email=local@invalid", "commit", "-qm", "Source fixture")
            commit = git(checkout, "rev-parse", "HEAD").decode().strip()
            (checkout / "tracked.txt").write_bytes(b"unreleased dirty source")
            (checkout / "native-notifications.cjs").write_bytes(b"unreleased untracked source")
            with patch(__name__ + ".APPLICATION_COMMIT", commit):
                proof = archive_source(checkout, root / "archive")
            self.assertEqual((root / "archive/tracked.txt").read_bytes(), b"committed source")
            self.assertFalse((root / "archive/native-notifications.cjs").exists())
            self.assertEqual(proof["git_blob_files_verified"], 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--ops-source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--workflow-sha")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--repository")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OfflineContracts))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    for field in ["source", "ops_source", "output", "work", "workflow_sha", "run_id", "run_attempt", "repository"]:
        assert getattr(args, field), "Missing runner argument: " + field
    assert os.name == "posix" and os.environ.get("GITHUB_ACTIONS") == "true", "Hosted runner required"
    RuntimeBuild(args).execute()


if __name__ == "__main__":
    main()
