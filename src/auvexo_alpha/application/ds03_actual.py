"""Fixed actual-family wrapper around the single shared causal read session."""

from collections.abc import Callable
from datetime import datetime
from time import monotonic

from auvexo_alpha.application.ds03 import _ActualCodec, _ReadSession
from auvexo_alpha.application.ds03_ports import ActualDs03ReadPort
from auvexo_alpha.domain.ds03_actual import (
    ActualAttestation,
    ActualIdentity,
    ActualReply,
    ActualRequest,
    ActualRights,
)


class ActualDs03Reader(
    _ReadSession[ActualRequest, ActualReply, ActualIdentity, ActualAttestation, ActualRights]
):
    def __init__(
        self,
        port: ActualDs03ReadPort,
        expected: ActualIdentity,
        rights: ActualRights,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        super().__init__(
            port, expected, rights, _ActualCodec(), clock=clock, monotonic_clock=monotonic_clock
        )
