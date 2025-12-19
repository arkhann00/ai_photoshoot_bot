# src/db/enums.py
from __future__ import annotations

import enum


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    success = "success"
    failed = "failed"


class StyleGender(str, enum.Enum):
    male = "male"
    female = "female"


class PhotoshootStatus(str, enum.Enum):
    success = "success"
    failed = "failed"