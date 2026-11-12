# Clock trust

Evidence carries timestamps. An untrusted clock makes time-quality evidence worthless and
makes some gates refuse.

## What depends on the clock

- Open-interest collection refuses to start unless Windows Time reports a synchronised
  external source with a bound of at most one second and a sync no older than one hour.
- PAPER observation requires each bar to be fetched within the provider's own minute
  after bar end, and the risk kernel denies when the measured offset exceeds 250 ms.
- Public-data qualification places events in the 18:00-18:12 UTC window by local time.
- DS-03 evidence is labelled `STRUCTURAL_ONLY_CLOCK_BLOCKED` regardless.

The clock does not block source engineering, tests, documentation or the terminal.

## Check, read-only

```text
w32tm /query /status
```

Trusted means: `Leap Indicator: 0`, a stratum from 1 to 15, a `Source` that is not
`Local CMOS Clock`, and a recent `Last Successful Sync Time`.

To measure the actual offset against a provider without changing anything, compare the
local time with the `serverTime` returned by `https://data-api.binance.vision/api/v3/time`.
On 2026-11-12 the laptop was about 33 seconds slow by that measure.

## Restore, owner only

A resync needs an elevated prompt:

```text
w32tm /resync
w32tm /query /status
```

If it still reports the local CMOS clock, NTP (UDP 123) is probably blocked on the
network path. That is a router or network decision for the owner.

Do not set the time by hand, do not backdate, do not disable the firewall, do not lower a
trust threshold in code, and do not rotate through NTP providers. One attempt, then
record the result. While the clock is untrusted, record `CLOCK_EXTERNAL_BLOCKED` and keep
the open-interest forward clock at zero.
