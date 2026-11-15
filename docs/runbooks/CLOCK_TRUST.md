# Clock trust

Evidence carries timestamps. An untrusted clock makes time-quality evidence worthless and
makes some gates refuse.

## What depends on the clock

- Open-interest collection refuses to start unless Windows Time reports a synchronised
  external source with a bound of at most one second and a sync no older than one hour.
- PAPER observation requires each bar to be fetched within the provider's own minute
  after bar end, and the risk kernel denies when the measured offset exceeds 250 ms
  (campaign v2 proposes a 2000 ms minute-bar bound and a per-run sync check, ADR-032).
- Public-data collection refuses a poll while the local clock is more than two seconds
  from the provider's (ADR-031), and qualification places events in the 18:00-18:12 UTC
  window.
- DS-03 evidence is labelled `STRUCTURAL_ONLY_CLOCK_BLOCKED` regardless.

The clock does not block source engineering, tests, documentation or the terminal.

## Check, read-only

```text
w32tm /query /status
```

Trusted means: `Leap Indicator: 0`, a stratum from 1 to 15, a `Source` that is not
`Local CMOS Clock`, and a recent `Last Successful Sync Time`.

To see each input of the open-interest gate, its observed value and which one fails,
without changing anything (no elevation needed):

```text
.venv\Scripts\python.exe tools\oi_clock_status.py --source "time.windows.com,0x9"
```

It runs the same System32 `w32tm /query /status /verbose` the gate uses and applies the
same rules. Exit code 0 means trusted, 2 means not.

To measure the actual offset against a provider without changing anything, compare the
local time with the `serverTime` returned by `https://data-api.binance.vision/api/v3/time`.

Measured history: about 33 seconds slow on 2026-11-12; Windows Time then synchronised
once at 2026-11-13 01:18:59 from `time.windows.com`; by about 20:50 the same day the clock was
about 1.8 seconds fast and Windows Time again reported Leap 3, stratum 0. A stock
non-domain host polls only every 16384 seconds (about 4.5 hours), so the one-hour
sync-age rule fails between polls even when the clock is close.

## Restore, owner only

The one-hour sync age and one-second bound are frozen for open interest and reused by
[ADR-032](../adr/032-paper-evidence-campaign-v2.md); they are not lowered. To keep a
stock Windows host inside them, run once in an elevated prompt:

```text
sc.exe triggerinfo w32time delete
sc.exe config w32time start= auto
w32tm /config /manualpeerlist:"time.windows.com,0x9" /syncfromflags:manual /reliable:no /update
reg add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpClient" /v SpecialPollInterval /t REG_DWORD /d 900 /f
net stop w32time
net start w32time
w32tm /resync /rediscover
```

This makes the service start automatically instead of on a trigger, and polls every 900
seconds, so the sync age stays under an hour even with three missed polls. Then check
with `w32tm /query /status` and the diagnostic above. The open-interest configuration's
clock source must be exactly `time.windows.com,0x9`. After sleep or resume, the first
slot may be refused until the next poll; that slot is recorded as a gap.

If `Last Sync Error` still says no time data was available, NTP (UDP 123) is probably
blocked on the network path. That is a router or network decision for the owner.

One open question for an independent look: on 2026-11-13 the verbose status reported
"time since last good sync" of under an hour while the last successful sync was about
20 hours earlier; the field appears to reset when the service restarts. The gate also
requires leap 0, a real stratum and a bound under one second, which all failed closed,
so this does not let an untrusted clock through.

Do not set the time by hand, do not backdate, do not disable the firewall, do not lower a
trust threshold in code, and do not rotate through NTP providers. One attempt, then
record the result. While the clock is untrusted, record `CLOCK_EXTERNAL_BLOCKED` and keep
the open-interest forward clock at zero.
