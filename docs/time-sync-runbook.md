# Production clock synchronization

Correct UTC time is a hard dependency for login tokens, provider freshness,
cache expiry, scheduled work, and TLS. The production host was found about 84
minutes behind while Chrony had no reachable source. Do not weaken timestamp
validation to hide this failure.

## Safe source test

Query candidate servers without changing the system clock:

```bash
sudo chronyd -Q 'server ntp.time.ir iburst'
sudo chronyd -Q 'server ntp.day.ir iburst'
sudo chronyd -Q 'server ntp.cloud.ir iburst'
```

Continue only when at least two queries return a consistent offset. The three
servers above agreed within milliseconds during the 2026-09-12 incident.

## Persist reachable sources

Run as an operator with sudo access:

```bash
sudo install -d -m 755 /etc/chrony/sources.d
printf '%s\n' \
  'server ntp.time.ir iburst' \
  'server ntp.day.ir iburst' \
  'server ntp.cloud.ir iburst' \
  | sudo tee /etc/chrony/sources.d/nerkhbaan-iran.sources >/dev/null
sudo chmod 644 /etc/chrony/sources.d/nerkhbaan-iran.sources
sudo chronyc reload sources
sudo chronyc burst 4/4
sleep 10
chronyc sources -v
chronyc tracking
```

Require a selected reachable source (`^*`) before correction. Keep the existing
foreign sources as fallback; unreachable sources do not invalidate the selected
Iranian source.

## Correct a large offset

First inspect `chronyc tracking` after the source reload. If it already reports
`Leap status: Normal` and a small system-time offset, do not run `makestep`.
Chrony may already have corrected the clock under its configured startup-step
policy. Continue directly to application verification.

A large forward jump can expire existing sessions and timers. Announce a short
maintenance window, stop new traffic if the service has active users, then run:

```bash
sudo chronyc makestep
chronyc waitsync 30 0.5
chronyc tracking
date -u
```

Require `Leap status: Normal`, a non-zero reference, and a small system-time
offset. Then restart the application processes, verify login, readiness, price
freshness, and scheduled jobs. Never move the clock manually with `date`.

During the 2026-09-12 incident, Chrony selected `185.192.112.101`, corrected
the clock automatically after the source reload, and reported a normal leap
status with a sub-millisecond offset. No manual step was required.

## Rollback

If every Iranian source fails later, remove only the dedicated source file and
reload sources. Do not change application freshness limits.

```bash
sudo rm /etc/chrony/sources.d/nerkhbaan-iran.sources
sudo chronyc reload sources
chronyc sources -v
```
