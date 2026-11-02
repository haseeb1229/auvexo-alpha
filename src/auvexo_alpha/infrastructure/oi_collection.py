"""One bounded hourly OI job. No activation issuer, task registration or catch-up."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Literal

from auvexo_alpha.application.oi_research import (
    OIStudyWindow,
    compute_oi_features,
    create_forecast,
    score_forecast,
)
from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority
from auvexo_alpha.domain.oi_schedule import (
    OIClockProof,
    OICollectionConfig,
    OIStartEnvelope,
    require_scheduled_start,
    slot_allowed,
    symbol_due,
)
from auvexo_alpha.domain.open_interest import OIManifest, OISymbol
from auvexo_alpha.domain.research import DataUseClass
from auvexo_alpha.infrastructure.oi_http import OIHTTP
from auvexo_alpha.infrastructure.oi_parser import parse_oi
from auvexo_alpha.infrastructure.oi_store import OIStore
from auvexo_alpha.infrastructure.public_http import SourceError


@dataclass(frozen=True)
class OIJobStatus:
    code: Literal["COMPLETE", "BLOCKED", "BUSY", "STOPPED", "SOURCE_UNAVAILABLE"]
    reason: str
    manifests: tuple[str, ...] = ()
    forward_days: Literal[0] = 0

    @property
    def exit_code(self) -> int:
        return {"COMPLETE": 0, "BLOCKED": 2, "BUSY": 3, "STOPPED": 4, "SOURCE_UNAVAILABLE": 5}[
            self.code
        ]


class OICollectionJob:
    def __init__(
        self,
        config: OICollectionConfig,
        store: OIStore,
        http: OIHTTP,
        *,
        cancel: Event,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        wait: Callable[[float], bool] | None = None,
        resources_ready: Callable[[], bool],
        review_authority: OIReviewAuthority | None = None,
    ) -> None:
        self.config = OICollectionConfig.model_validate(config.model_dump(mode="python"))
        self.store, self.http, self.cancel = store, http, cancel
        self.now, self.monotonic = now, monotonic
        self.wait = wait or cancel.wait
        self.resources_ready = resources_ready
        self.review_authority = review_authority

    def run(
        self,
        *,
        envelope: OIStartEnvelope | None,
        accepted_start_digest: str | None,
        clock: OIClockProof | None,
    ) -> OIJobStatus:
        config = self.config
        try:
            at = utc_time(self.now())
            slot = require_scheduled_start(config, at, self.review_authority)
            if envelope is None or accepted_start_digest is None:
                raise ValueError("OI_OWNER_START_REQUIRED")
            envelope.require_start(config, accepted_start_digest, at, self.review_authority)
            if clock is None:
                raise ValueError("OI_CLOCK_UNTRUSTED")
            clock.require_trusted(config, at)
            if not self.resources_ready():
                raise ValueError("OI_RESOURCE_YIELD")
        except ValueError as error:
            reason = str(error)
            if not reason.startswith("OI_") or len(reason) > 80:
                reason = "OI_CONFIG_INVALID"
            return OIJobStatus("BLOCKED", reason)
        if self.cancel.is_set():
            return OIJobStatus("STOPPED", "OI_STOPPED")
        deadline = self.monotonic() + min(60, (slot + timedelta(seconds=60) - at).total_seconds())
        study = OIStudyWindow(
            study_id=config.study_id,
            owner_start_at=envelope.owner_start_at,
            preregistration_hash=config.preregistration_hash,
            code_hash=config.code_hash,
            rights_snapshot_hash=config.rights.content_hash(),
        )
        if at < study.t0:
            return OIJobStatus("BLOCKED", "OI_STUDY_NOT_DUE")
        if at >= study.evaluation_end:
            return OIJobStatus("BLOCKED", "OI_STUDY_WINDOW_COMPLETE")
        results: list[str] = []
        with self.store.collection_lease() as acquired:
            if not acquired:
                return OIJobStatus("BUSY", "OI_SINGLE_INSTANCE")
            # A lease/config document is not a START record. No qualification issuer exists.
            self.store.append_study(study)
            for symbol in ("BTCUSDT", "ETHUSDT"):
                if self.cancel.is_set():
                    return OIJobStatus("STOPPED", "OI_STOPPED", tuple(results))
                if not self.resources_ready():
                    return OIJobStatus("BLOCKED", "OI_RESOURCE_YIELD", tuple(results))
                at = utc_time(self.now())
                try:
                    envelope.require_start(config, accepted_start_digest, at, self.review_authority)
                    clock.require_trusted(config, at)
                except ValueError:
                    return OIJobStatus(
                        "BLOCKED", "OI_RUNTIME_AUTHORITY_OR_CLOCK_INVALID", tuple(results)
                    )
                delay = max(0.0, (symbol_due(slot, symbol) - at).total_seconds())
                if self.monotonic() + delay >= deadline:
                    return OIJobStatus("STOPPED", "OI_SLOT_DEADLINE", tuple(results))
                if self.wait(delay):
                    return OIJobStatus("STOPPED", "OI_STOPPED", tuple(results))
                # Revalidate after staggering: the wait can cross an authority/clock
                # boundary, receive cancellation or consume the shared slot deadline.
                at = utc_time(self.now())
                if self.cancel.is_set():
                    return OIJobStatus("STOPPED", "OI_STOPPED", tuple(results))
                if self.monotonic() >= deadline or at >= slot + timedelta(seconds=60):
                    return OIJobStatus("STOPPED", "OI_SLOT_DEADLINE", tuple(results))
                try:
                    envelope.require_start(config, accepted_start_digest, at, self.review_authority)
                    clock.require_trusted(config, at)
                except ValueError:
                    return OIJobStatus(
                        "BLOCKED", "OI_RUNTIME_AUTHORITY_OR_CLOCK_INVALID", tuple(results)
                    )
                if not self.resources_ready():
                    return OIJobStatus("BLOCKED", "OI_RESOURCE_YIELD", tuple(results))
                previous = self.store.checkpoint(symbol)
                if previous is not None and previous.observation.slot_at > slot:
                    return OIJobStatus("BLOCKED", "OI_CLOCK_REGRESSION", tuple(results))
                if previous is not None and previous.observation.slot_at == slot:
                    results.append(previous.content_hash())
                    continue
                try:
                    receipt = self.http.fetch(symbol, slot_deadline=deadline)
                except SourceError as error:
                    return OIJobStatus("SOURCE_UNAVAILABLE", error.code, tuple(results))
                processed_at = utc_time(self.now())
                try:
                    envelope.require_start(
                        config, accepted_start_digest, processed_at, self.review_authority
                    )
                    clock.require_trusted(config, processed_at)
                except ValueError:
                    self.store.quarantine(receipt.body, processed_at, "RIGHTS_REJECTED")
                    return OIJobStatus("BLOCKED", "OI_RECEIPT_ADMISSION_EXPIRED", tuple(results))
                try:
                    observation = parse_oi(
                        receipt.body,
                        symbol=symbol,
                        slot_at=slot,
                        request_sent_at=receipt.request_sent_at,
                        first_seen_at=receipt.first_seen_at,
                        received_at=receipt.received_at,
                        processed_at=processed_at,
                        code_revision=config.git_revision,
                        code_hash=config.code_hash,
                        review_receipt_hash=(
                            self.review_authority.receipt_hash_at(receipt.received_at)
                            if self.review_authority is not None
                            else None
                        ),
                    )
                except ValueError:
                    self.store.quarantine(receipt.body, processed_at, "PARSER_REJECTED")
                    return OIJobStatus("SOURCE_UNAVAILABLE", "OI_SCHEMA_OR_QUALITY", tuple(results))
                manifest = self.store.publish(
                    observation,
                    receipt.body,
                    rights=config.rights,
                    classification=DataUseClass.PERSONAL_RESEARCH,
                    now=processed_at,
                )
                if manifest.observation.quality != "VALID":
                    return OIJobStatus("BLOCKED", "OI_CONFLICT_REVIEW_REQUIRED", tuple(results))
                results.append(manifest.content_hash())
                self._research(study, manifest, previous, symbol)
        return OIJobStatus("COMPLETE", "OI_RECORDED_NO_QUALIFICATION_CREDIT", tuple(results))

    def _research(
        self,
        study: OIStudyWindow,
        current: OIManifest,
        previous: OIManifest | None,
        symbol: OISymbol,
    ) -> None:
        now = utc_time(self.now())
        # Persist outcomes only after original forecasts already exist in the ledger.
        scored = {s.forecast_hash for s in self.store.scores(study.content_hash())}
        for forecast in self.store.forecasts(study.content_hash()):
            if forecast.symbol != symbol or forecast.content_hash() in scored:
                continue
            target_slot = forecast.slot_at + timedelta(hours=1)
            if target_slot > current.observation.slot_at:
                continue
            source = self.store.manifest_by_hash(forecast.current_manifest_hash)
            target = current if target_slot == current.observation.slot_at else None
            score = score_forecast(
                study,
                forecast,
                source,
                target,
                scored_at=now,
                review_authority=self.review_authority,
            )
            self.store.append_score(score)
        feature = compute_oi_features(
            current, previous, at=now, review_authority=self.review_authority
        )
        self.store.append_feature(feature)
        if (
            study.evaluation_start <= feature.slot_at < study.evaluation_end
            and feature.fractional_change is not None
            and all(slot_allowed(feature.slot_at + timedelta(hours=d)) for d in (-1, 0, 1))
            and now < feature.slot_at + timedelta(seconds=60)
        ):
            forecast = create_forecast(study, feature, created_at=now)
            self.store.append_prediction(forecast)
