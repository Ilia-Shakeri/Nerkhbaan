#!/bin/sh
# Read-only checks. Run only on the purchased host after verifying its SSH fingerprint.
set -eu
failed=0
check() { if "$@"; then :; else failed=1; fi; }
printf 'architecture=%s\n' "$(uname -m)"
check test "$(uname -m)" = x86_64
cpus=$(getconf _NPROCESSORS_ONLN)
printf 'cpus=%s\n' "$cpus"
check test "$cpus" -ge 2
memory=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
printf 'memory_kib=%s\n' "$memory"
check test "$memory" -ge 3700000
free=$(df -Pk / | awk 'NR==2 {print $4}')
printf 'root_free_kib=%s\n' "$free"
check test "$free" -ge 25165824
printf 'os='; . /etc/os-release; printf '%s %s\n' "$ID" "$VERSION_ID"
check test "$ID" = ubuntu
check test "$VERSION_ID" = 24.04
printf 'clock='; date -u +%FT%TZ
if command -v timedatectl >/dev/null 2>&1; then timedatectl show -p NTPSynchronized; fi
if command -v ss >/dev/null 2>&1; then ss -lnt; fi
if command -v docker >/dev/null 2>&1; then
    docker --version
    docker compose version
    docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
else
    printf 'docker=not-installed; install remains pending\n'
fi
printf 'hardware_checks_passed=%s\n' "$((1-failed))"
printf 'network_tls_dns_and_application_acceptance=pending\n'
exit "$failed"
