from __future__ import annotations

from typing import Any, Mapping


SENSITIVE_FIELDS = frozenset({"name", "phone", "id_number", "address"})
CLOUD_ALLOWED_FIELDS = frozenset(
    {
        "session_id",
        "age_group",
        "sex",
        "symptoms",
        "duration",
        "severity",
        "visual_findings",
        "verification_results",
        "safety",
    }
)


def sanitize_patient_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Construct a new cloud payload from an explicit field whitelist."""

    sanitized = {key: payload[key] for key in CLOUD_ALLOWED_FIELDS if key in payload}
    leaked = SENSITIVE_FIELDS.intersection(sanitized)
    if leaked:  # Defensive invariant; unreachable while whitelist remains correct.
        raise RuntimeError(f"privacy whitelist leaked sensitive fields: {sorted(leaked)}")
    return sanitized
