"""
Pydantic schemas for desktop accountability friction barriers and diversion penalties.
"""

from typing import Optional

from pydantic import BaseModel, Field


class DiversionPenaltyIn(BaseModel):
    """Payload sent when a user force-bypasses a desktop digital barrier."""

    session_id: Optional[int] = None
    reason: str = Field(default="barrier_force_bypass", max_length=128)
    base_damage: float = Field(default=15.0, ge=1.0, le=100.0)


class DiversionPenaltyOut(BaseModel):
    """Result of applying a diversion penalty, including gear mitigation."""

    applied: bool
    base_damage: float
    hp_lost: float
    damage_mitigated: float
    current_hp: float
    died: bool
    gear_stat_bonus: dict[str, int]
