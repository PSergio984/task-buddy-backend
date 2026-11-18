"""
Pydantic schemas for desktop accountability friction barriers and diversion penalties.
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

SERVER_ID_PREFIX = "server:"
FIXED_DIVERSION_BASE_DAMAGE = 15.0


class DiversionPenaltyIn(BaseModel):
    """Payload sent when a user force-bypasses a desktop digital barrier."""

    session_id: Optional[int] = None
    client_event_id: Optional[str] = Field(default=None, max_length=128)
    reason: str = Field(default="barrier_force_bypass", max_length=128)
    base_damage: float = Field(default=FIXED_DIVERSION_BASE_DAMAGE, allow_inf_nan=False)

    @field_validator("client_event_id")
    @classmethod
    def no_server_namespace(cls, v: Optional[str]) -> Optional[str]:
        if v and v.lower().startswith(SERVER_ID_PREFIX):
            raise ValueError("client_event_id prefix 'server:' is reserved")
        return v

    @field_validator("base_damage")
    @classmethod
    def enforce_fixed_damage(cls, v: float) -> float:
        # Enforce server-side authoritative fixed 15.0 damage
        return FIXED_DIVERSION_BASE_DAMAGE


class DiversionPenaltyOut(BaseModel):
    """Result of applying a diversion penalty, including gear mitigation."""

    applied: bool
    base_damage: float
    hp_lost: float
    damage_mitigated: float
    current_hp: float
    died: bool
    gear_stat_bonus: dict[str, int]
