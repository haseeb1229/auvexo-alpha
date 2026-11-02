"""Read-only DS-03 port; no execution, secret, process or provider imports."""

from typing import Protocol

from auvexo_alpha.domain.ds03 import Ds03Attestation, Ds03Reply, Ds03Request


class Ds03ReadPort(Protocol):
    def attest(self) -> Ds03Attestation: ...
    def execute(self, request: Ds03Request) -> Ds03Reply: ...
    def disconnect(self) -> None: ...
