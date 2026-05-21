"""
Database models.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Enum
from app.database import Base
import enum


class PlanTier(str, enum.Enum):
    free = "free"
    payg = "payg"          # pay-as-you-go
    pro = "pro"            # $19/mo
    business = "business"  # $79/mo


class User(Base):
    __tablename__ = "users"

    id                  = Column(Integer, primary_key=True, index=True)
    email               = Column(String, unique=True, index=True, nullable=False)
    password_hash       = Column(String, nullable=False)
    is_verified         = Column(Boolean, default=False)
    is_admin            = Column(Boolean, default=False)

    # Stripe
    stripe_customer_id  = Column(String, nullable=True)
    stripe_sub_id       = Column(String, nullable=True)  # active subscription ID
    plan                = Column(Enum(PlanTier), default=PlanTier.free)

    # Usage (rolling calendar month)
    pages_used          = Column(Integer, default=0)
    usage_month         = Column(String, default="")  # "2026-05" format

    reset_token         = Column(String, nullable=True, index=True)
    reset_token_exp     = Column(DateTime, nullable=True)

    created_at          = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login          = Column(DateTime, nullable=True)
