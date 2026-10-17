"""Exness is externally gated; no terminal library or callable connection exists."""

from typing import Literal

from auvexo_alpha.domain.contracts import Contract


class DemoDataPrerequisites(Contract):
    owner_authorized: bool = False
    encrypted_os_store: bool = False
    isolated_process: bool = False
    dedicated_demo_profile: bool = False
    provider_terms_reviewed: bool = False
    terminal_account_type: Literal["DEMO", "REAL", "UNKNOWN"] = "UNKNOWN"
    attestation_origin: Literal["TERMINAL", "LABEL", "UNKNOWN"] = "UNKNOWN"


def require_demo_data(prerequisites: DemoDataPrerequisites) -> None:
    if (
        prerequisites.terminal_account_type != "DEMO"
        or prerequisites.attestation_origin != "TERMINAL"
    ):
        raise ValueError("REAL_OR_UNVERIFIED_ACCOUNT_REFUSED")
    if not all(
        (
            prerequisites.owner_authorized,
            prerequisites.encrypted_os_store,
            prerequisites.isolated_process,
            prerequisites.dedicated_demo_profile,
            prerequisites.provider_terms_reviewed,
        )
    ):
        raise ValueError("EXNESS_PREREQUISITES_BLOCKED")
    # Supplied booleans are not proof. A future owner-authorized isolated connector must
    # generate and independently verify actual terminal facts before this gate is revised.
    raise ValueError("EXNESS_CONNECTOR_NOT_PROVISIONED")
