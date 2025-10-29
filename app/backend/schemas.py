# backend/app/schemas.py
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationInfo


class AccountType(str, Enum):
    current = "current"
    savings = "savings"


class BalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(..., description="Customer identifier as found in customers.csv")
    account_type: Optional[AccountType] = Field(
        None,
        description="Optional account type filter. Without it, all eligible accounts are returned.",
    )


class BalanceAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    name: str
    account_type: AccountType
    iban: str
    currency: str
    balance: float


class BalanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    accounts: List[BalanceAccount]


class CustomerLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        min_length=1,
        description="Full name of the customer as stored in customers.csv.",
    )
    birthdate: date = Field(
        ...,
        description="Birthdate of the customer (YYYY-MM-DD).",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


class CustomerProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_type: str
    product_name: str
    status: Optional[str] = None


class CustomerLookupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    products: List[CustomerProduct]


class TransactionsFilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    merchant: Optional[str] = Field(
        None,
        description="Case-insensitive substring match applied to transaction description.",
    )
    n: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Optional limit on number of records to return.",
    )
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    min_amount: Optional[float] = Field(
        None, ge=0, description="Filter transactions whose absolute amount is at least this value."
    )

    @field_validator("date_to", mode="after")
    def validate_date_range(cls, value: Optional[date], info: ValidationInfo) -> Optional[date]:
        # 获取已经解析为目标类型的字段值
        date_from = info.data.get("date_from")

        if value and date_from and value < date_from:
            raise ValueError("date_to cannot be earlier than date_from")
        return value

class TransactionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    product_id: str
    date: datetime
    description: str
    merchant: str
    transaction_type: str
    amount: float
    currency: str
    balance_after: float


class TransactionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    total: float
    currency: str
    items: List[TransactionItem]


class CardUpdateAction(str, Enum):
    block = "block"
    unblock = "unblock"


class CardUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    action: CardUpdateAction


class CardUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    request_id: str
    card_product: Dict[str, str]
    new_status: str


class ContactUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

    @field_validator("email")
    @classmethod
    def ensure_email(cls, value: Optional[str]) -> Optional[str]:
        if value and "@" not in value:
            raise ValueError("email must contain '@'")
        return value


class ContactUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    ticket_id: str
    customer_id: str
    changed: Dict[str, str]


class SavingsOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str


class SavingsOpenSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_product_id: str
    product_name: str
    interest_rate: str
    starting_balance: str
    next_steps: List[str]


class SavingsOpenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    summary: SavingsOpenSummary


class AppointmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    slot: Optional[str] = Field(
        None,
        description="ISO 8601 timestamp. If omitted, available slots are returned for confirmation.",
    )


class AppointmentCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    slots: List[str]
    confirmed: Optional[str] = None