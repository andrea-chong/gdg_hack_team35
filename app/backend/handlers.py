# backend/app/handlers.py
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import Dict, List

import pandas as pd
from fastapi import HTTPException

from .data import (
    CustomerAmbiguousError,
    CustomerNotFoundError,
    DataStore,
)
from .schemas import (
    AppointmentCreateRequest,
    AppointmentCreateResponse,
    BalanceAccount,
    BalanceRequest,
    BalanceResponse,
    CardUpdateRequest,
    CardUpdateResponse,
    ContactUpdateRequest,
    ContactUpdateResponse,
    CustomerLookupRequest,
    CustomerLookupResponse,
    CustomerProduct,
    SavingsOpenRequest,
    SavingsOpenResponse,
    SavingsOpenSummary,
    TransactionItem,
    TransactionsFilterRequest,
    TransactionsResponse,
)


def handle_balances(request: BalanceRequest, store: DataStore) -> BalanceResponse:
    accounts_df = store.list_active_accounts(
        customer_id=request.customer_id, account_type=request.account_type
    )
    if accounts_df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No active accounts found for customer {request.customer_id}",
        )
    accounts: List[BalanceAccount] = []
    for _, row in accounts_df.iterrows():
        payload = store.format_account_payload(row)
        accounts.append(BalanceAccount(**payload))
    return BalanceResponse(customer_id=request.customer_id, accounts=accounts)


def handle_customer_lookup(
    request: CustomerLookupRequest, store: DataStore
) -> CustomerLookupResponse:
    birthdate_ts = pd.to_datetime(request.birthdate)
    try:
        customer_id = store.find_customer_by_identity(
            name=request.name, birthdate=birthdate_ts
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerAmbiguousError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    products_df = store.list_all_products(customer_id)
    products: List[CustomerProduct] = [
        CustomerProduct(
            product_id=row["product_id"],
            product_type=row["product_type"],
            product_name=row["product_name"],
            status=row['status'],
        )
        for _, row in products_df.iterrows()
    ]
    return CustomerLookupResponse(customer_id=customer_id, products=products)


def handle_transactions(request: TransactionsFilterRequest, store: DataStore) -> TransactionsResponse:
    date_from = pd.to_datetime(request.date_from) if request.date_from else None
    date_to = pd.to_datetime(request.date_to) if request.date_to else None
    df = store.filter_transactions(
        customer_id=request.customer_id,
        merchant=request.merchant,
        n=request.n,
        date_from=date_from,
        date_to=date_to,
        min_amount=request.min_amount,
    )
    if df.empty:
        return TransactionsResponse(
            customer_id=request.customer_id, total=0.0, currency="EUR", items=[]
        )
    items: List[TransactionItem] = []
    for _, row in df.iterrows():
        items.append(
            TransactionItem(
                transaction_id=row["transaction_id"],
                product_id=row["product_id"],
                date=row["date"],
                description=row["description"],
                merchant=row["description"],
                transaction_type=row["transaction_type"],
                amount=round(row["amount_signed"], 2),
                currency=row["currency"] or "EUR",
                balance_after=round(row["balance_after"], 2),
            )
        )
    total_value = round(df["amount_signed"].sum(), 2)
    return TransactionsResponse(
        customer_id=request.customer_id, total=total_value, currency="EUR", items=items
    )


def handle_card_update(request: CardUpdateRequest, store: DataStore) -> CardUpdateResponse:
    cards_df = store.list_card_products(customer_id=request.customer_id)
    if cards_df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No card products found for customer {request.customer_id}",
        )
    # For demo purposes we operate on the first matching card.
    card_row = cards_df.iloc[0]
    action = request.action.value
    new_status = "Blocked by Customer" if action == "block" else "Active"
    request_id = f"CARD-{uuid.uuid4().hex[:8].upper()}"
    card_payload: Dict[str, str] = {
        "product_id": card_row["product_id"],
        "product_name": card_row["product_name"],
        "status_before": card_row["status"],
    }
    return CardUpdateResponse(
        status="ok",
        request_id=request_id,
        new_status=new_status,
        card_product=card_payload,
    )


def handle_contact_update(request: ContactUpdateRequest, store: DataStore) -> ContactUpdateResponse:
    changes = {
        key: value
        for key, value in {
            "email": request.email,
            "phone": request.phone,
            "address": request.address,
        }.items()
        if value
    }
    if not changes:
        raise HTTPException(
            status_code=400,
            detail="At least one of email, phone, or address must be provided",
        )
    snapshot = store.get_customer_snapshot(request.customer_id)
    ticket_id = f"TICKET-{uuid.uuid4().hex[:8].upper()}"
    updated_fields = {field: changes[field] for field in changes if field in snapshot}
    return ContactUpdateResponse(
        status="ok",
        ticket_id=ticket_id,
        customer_id=request.customer_id,
        changed=updated_fields,
    )


def handle_savings_open(request: SavingsOpenRequest, store: DataStore) -> SavingsOpenResponse:
    store.ensure_customer_exists(request.customer_id)
    new_product_id = f"SAV-{uuid.uuid4().hex[:8].upper()}"
    summary = SavingsOpenSummary(
        new_product_id=new_product_id,
        product_name="ING Orange Savings",
        interest_rate="2.15% AER",
        starting_balance="0.00 EUR",
        next_steps=[
            "Review and accept the terms and conditions in the ING app.",
            "Sign the digital contract with your itsme® or ING card reader.",
            "First deposit can be scheduled immediately after confirmation.",
        ],
    )
    return SavingsOpenResponse(status="ok", summary=summary)


def handle_appointment_create(
    request: AppointmentCreateRequest, store: DataStore
) -> AppointmentCreateResponse:
    store.ensure_customer_exists(request.customer_id)
    today = datetime.now().date()
    base_slots = []
    for delta_days in range(1, 4):
        appointment_date = today + timedelta(days=delta_days)
        for hour in (10, 14):
            slot_dt = datetime.combine(appointment_date, time(hour=hour, minute=0))
            base_slots.append(slot_dt.isoformat())

    if request.slot is None:
        return AppointmentCreateResponse(status="pending_confirmation", slots=base_slots)

    if request.slot not in base_slots:
        raise HTTPException(
            status_code=400,
            detail="Requested slot is no longer available. Please choose one of the proposed times.",
        )

    return AppointmentCreateResponse(status="confirmed", slots=base_slots, confirmed=request.slot)