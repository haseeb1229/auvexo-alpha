"""Coverage and actual calendar-day qualification; absent observations remain absent."""

from datetime import UTC, date, datetime, timedelta

from auvexo_alpha.domain.market_data import DatasetManifest, IngestionEvent


def coverage_matrix(manifests: list[DatasetManifest]) -> list[dict[str, object]]:
    superseded = {m.supersedes for m in manifests if m.supersedes}
    rows: list[dict[str, object]] = []
    for m in manifests:
        if m.dataset_version in superseded:
            continue
        c = m.coverage
        rows.append(
            dict(
                instrument=c.instrument_id,
                venue="BINANCE",
                product="SPOT",
                symbol=c.instrument_id.rsplit(".", 1)[-1],
                timeframe=c.interval,
                source=m.source.source_id,
                earliest=c.earliest.isoformat() if c.earliest else None,
                latest_end=c.latest_end.isoformat() if c.latest_end else None,
                observed_rows=c.observed_rows,
                expected_rows=c.expected_rows,
                quality=c.status,
                findings=[f.model_dump(mode="json") for f in c.findings],
                dataset_version=m.dataset_version,
                source_url=m.source_url,
                source_hash=m.source_hash,
                rights=m.rights.version,
                permitted_use=m.rights.permitted_use,
                bytes=m.parquet_bytes,
                availability="Actual receipt only; historical publication UNKNOWN",
                limitation="Spot research only; not executable CFD quotes; "
                "unselected history UNKNOWN",
            )
        )
    for asset in ("BTC", "ETH", "XAU"):
        rows.append(
            dict(
                instrument="exness.cfd." + asset,
                venue="EXNESS",
                product="CFD",
                symbol=None,
                timeframe=None,
                source="DS-03",
                earliest=None,
                latest_end=None,
                observed_rows=0,
                expected_rows=None,
                quality="BLOCKED",
                bytes=0,
                limitation="Owner demo access/isolation/attestation absent; no substitute",
            )
        )
    return rows


def qualification(events: list[IngestionEvent], start: date, now: datetime) -> dict[str, object]:
    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
        # Scheduled public-data window: 00:00 through 00:12 UTC. At least ten minutes
        # of genuine per-symbol observations, no >120-second heartbeat gaps.
        selected = [
            e
            for e in events
            if midnight <= e.observed_at < midnight + timedelta(minutes=12)
            and e.observed_at <= now
            and e.feed_key.startswith("DS-02.")
        ]
        good = True
        for symbol in ("BTCUSDT", "ETHUSDT"):
            feed = sorted(
                (e for e in selected if e.feed_key == f"DS-02.{symbol}.1m"),
                key=lambda e: e.observed_at,
            )
            good = (
                good
                and len(feed) >= 11
                and all(e.state == "FRESH" and e.dataset_version for e in feed)
            )
            if feed:
                good = good and (feed[-1].observed_at - feed[0].observed_at).total_seconds() >= 600
                good = good and all(
                    (b.observed_at - a.observed_at).total_seconds() <= 120
                    for a, b in zip(feed, feed[1:], strict=False)
                )
        closed = now >= midnight + timedelta(minutes=12)
        days.append(
            dict(
                day=day.isoformat(),
                events=len(selected),
                status="PASS" if good and closed else "OPEN" if not closed else "INCOMPLETE",
                first=selected[0].observed_at.isoformat() if selected else None,
                last=selected[-1].observed_at.isoformat() if selected else None,
            )
        )
    return dict(
        status="PASS" if all(d["status"] == "PASS" for d in days) else "OPEN",
        days=days,
        scope="Public scheduled 12-minute UTC windows only; "
        "not continuous uptime or Exness qualification",
    )
