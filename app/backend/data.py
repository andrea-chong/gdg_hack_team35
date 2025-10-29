# backend/app/data.py
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from .config import DATA_DIR


ACCOUNT_TYPE_KEYWORDS: Dict[str, Iterable[str]] = {
    "current": ("current", "checking", "zicht", "lion"),
    "savings": ("saving", "spaar", "orange"),
}

CARD_KEYWORDS = ("card", "visa", "mastercard", "credit", "debit")


class CustomerNotFoundError(LookupError):
    """Raised when no customer matches the provided identity information."""


class CustomerAmbiguousError(LookupError):
    """Raised when multiple customers match the provided identity information."""


def _normalize_phone(raw: str) -> str:
    """
    Convert scientific notation or float-like phone numbers into digit strings.
    Keeps raw string if conversion fails.
    """
    if raw is None or str(raw).strip() == "":
        return ""
    candidate = str(raw).strip()
    try:
        decimal_value = Decimal(candidate)
        # Remove decimal part if it is zero.
        if decimal_value == decimal_value.to_integral():
            return str(decimal_value.to_integral())
        return candidate
    except (InvalidOperation, ValueError):
        return candidate


@dataclass
class DataStore:
    customers: pd.DataFrame
    products: pd.DataFrame
    products_closed: pd.DataFrame
    transactions: pd.DataFrame
    product_balances: Dict[str, float]

    @classmethod
    def from_directory(cls, data_dir: Path) -> "DataStore":
        customers = cls._load_customers(data_dir / "customers.csv")
        products = cls._load_products(data_dir / "products.csv")
        products_closed = cls._load_products(
            data_dir / "products_closed.csv", allow_missing=True
        )
        transactions = cls._load_transactions(
            data_dir / "transactions.csv", products, products_closed
        )
        product_balances = (
            transactions.groupby("product_id")["amount_signed"].sum().to_dict()
        )
        return cls(
            customers, products, products_closed, transactions, product_balances
        )

    @staticmethod
    def _load_customers(path: Path) -> pd.DataFrame:
        df = pd.read_csv(
            path,
            dtype={
                "customer_id": str,
                "name": str,
                "email": str,
                "phone": str,
                "address": str,
                "segment_code": str,
            },
            parse_dates=["birthdate"],
            dayfirst=False,
        )
        df["customer_id"] = df["customer_id"].astype(str)
        df["phone"] = df["phone"].apply(_normalize_phone)

        # 保证 birthdate 始终为标准化 datetime，避免对象列导致的 .dt 访问错误
        df["birthdate"] = pd.to_datetime(df["birthdate"], errors="coerce")
        df["birthdate"] = df["birthdate"].dt.tz_localize(None).dt.normalize()

        return df.set_index("customer_id")

    @staticmethod
    def _load_products(path: Path, allow_missing: bool = False) -> pd.DataFrame:
        if allow_missing and not path.exists():
            return pd.DataFrame(
                columns=[
                    "product_id",
                    "customer_id",
                    "product_type",
                    "product_name",
                    "opened_date",
                    "status",
                ]
            )
        df = pd.read_csv(
            path,
            dtype={
                "product_id": str,
                "customer_id": str,
                "product_type": str,
                "product_name": str,
                "status": str,
            },
            parse_dates=["opened_date"],
            dayfirst=False,
        )
        for column in ("product_id", "customer_id"):
            df[column] = df[column].astype(str)
        return df

    @staticmethod
    def _load_transactions(
        path: Path,
        products: pd.DataFrame,
        products_closed: pd.DataFrame,
    ) -> pd.DataFrame:
        df = pd.read_csv(
            path,
            dtype={
                "transaction_id": str,
                "product_id": str,
                "currency": str,
                "description": str,
                "transaction_type": str,
            },
            parse_dates=["date"],
            dayfirst=False,
        )
        df["product_id"] = df["product_id"].astype(str)
        df["transaction_type"] = df["transaction_type"].str.title()
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

        df["amount_signed"] = df.apply(
            lambda row: row["amount"]
            if row["transaction_type"].lower() == "credit"
            else -row["amount"],
            axis=1,
        )

        all_products = pd.concat(
            [
                products.assign(is_closed=False),
                products_closed.assign(is_closed=True),
            ],
            ignore_index=True,
        )
        all_products = all_products[["product_id", "customer_id"]].drop_duplicates()

        df = df.merge(all_products, on="product_id", how="left")
        df["customer_id"] = df["customer_id"].astype(str)

        df["normalized_merchant"] = df["description"].fillna("").str.lower()
        df.sort_values(["product_id", "date", "transaction_id"], inplace=True)
        df["balance_after"] = df.groupby("product_id")["amount_signed"].cumsum()
        return df

    def ensure_customer_exists(self, customer_id: str) -> None:
        if customer_id not in self.customers.index:
            raise ValueError(f"Customer {customer_id} not found")

    def find_customer_by_identity(
        self, name: str, birthdate: pd.Timestamp
    ) -> str:
        normalized_name = name.strip().lower()
        customers_df = self.customers.copy()
        customers_df["normalized_name"] = (
            customers_df["name"].fillna("").str.strip().str.lower()
        )

        # 使用 to_datetime + normalize，确保可安全访问 .dt
        birthdate_series = pd.to_datetime(
            customers_df["birthdate"], errors="coerce"
        ).dt.normalize()
        birthdate_ts = pd.Timestamp(birthdate).normalize()

        matches = customers_df[
            (customers_df["normalized_name"] == normalized_name)
            & (birthdate_series == birthdate_ts)
        ]

        if matches.empty:
            raise CustomerNotFoundError(
                f"No customer matched name '{name}' with birthdate {birthdate_ts.date()}."
            )
        if len(matches) > 1:
            raise CustomerAmbiguousError(
                f"Multiple customers matched name '{name}' with birthdate {birthdate_ts.date()}."
            )
        return matches.index[0]

    def infer_account_type(self, product_type: str) -> Optional[str]:
        product_type_lower = product_type.lower()
        for account_type, keywords in ACCOUNT_TYPE_KEYWORDS.items():
            if any(keyword in product_type_lower for keyword in keywords):
                return account_type
        return None

    def list_active_accounts(
        self, customer_id: str, account_type: Optional[str] = None
    ) -> pd.DataFrame:
        self.ensure_customer_exists(customer_id)
        df = self.products[self.products["customer_id"] == customer_id].copy()
        if df.empty:
            return df
        df["account_type"] = df["product_type"].apply(self.infer_account_type)
        df = df[~df["status"].str.lower().str.contains("closed")]
        if account_type:
            df = df[df["account_type"] == account_type]
        df = df[df["account_type"].notna()]
        return df

    def list_all_products(self, customer_id: str) -> pd.DataFrame:
        self.ensure_customer_exists(customer_id)
        combined = pd.concat(
            [self.products, self.products_closed],
            ignore_index=True,
        )
        columns = ["product_id", "product_type", "product_name", "status"]
        if combined.empty:
            return pd.DataFrame(columns=columns)
        filtered = combined[combined["customer_id"] == customer_id]
        if filtered.empty:
            return pd.DataFrame(columns=columns)
        return (
            filtered[columns]
            .drop_duplicates()
            .sort_values(["product_type", "product_id"])
            .reset_index(drop=True)
        )

    def get_balance(self, product_id: str) -> float:
        return float(self.product_balances.get(product_id, 0.0))

    @staticmethod
    def _fake_iban(product_id: str) -> str:
        # Simple deterministic faker for demo purposes.
        digits = re.sub(r"[^0-9]", "", product_id) or "0000000000"
        padded = digits.zfill(10)[-10:]
        return f"BE71{padded}"

    def format_account_payload(self, row: pd.Series) -> Dict[str, str]:
        return {
            "product_id": row["product_id"],
            "name": row["product_name"],
            "account_type": row["account_type"],
            "iban": self._fake_iban(row["product_id"]),
            "currency": "EUR",
            "balance": round(self.get_balance(row["product_id"]), 2),
        }

    def filter_transactions(
        self,
        customer_id: str,
        merchant: Optional[str],
        n: Optional[int],
        date_from: Optional[pd.Timestamp],
        date_to: Optional[pd.Timestamp],
        min_amount: Optional[float],
    ) -> pd.DataFrame:
        self.ensure_customer_exists(customer_id)
        df = self.transactions[self.transactions["customer_id"] == customer_id].copy()
        if merchant:
            pattern = merchant.lower()
            df = df[df["normalized_merchant"].str.contains(pattern)]
        if date_from is not None:
            df = df[df["date"] >= date_from]
        if date_to is not None:
            df = df[df["date"] <= date_to]
        if min_amount is not None:
            df = df[df["amount"].abs() >= min_amount]
        df.sort_values("date", ascending=False, inplace=True)
        if n is not None:
            df = df.head(n)
        return df

    def list_card_products(self, customer_id: str) -> pd.DataFrame:
        self.ensure_customer_exists(customer_id)
        df = self.products[self.products["customer_id"] == customer_id].copy()
        df["is_card"] = df["product_type"].str.lower().apply(
            lambda value: any(keyword in value for keyword in CARD_KEYWORDS)
        )
        return df[df["is_card"]]

    def get_customer_snapshot(self, customer_id: str) -> Dict[str, str]:
        self.ensure_customer_exists(customer_id)
        record = self.customers.loc[customer_id]
        return {
            "customer_id": customer_id,
            "name": record["name"],
            "email": record["email"],
            "phone": record["phone"],
            "address": record["address"],
            "segment_code": record["segment_code"],
        }


@lru_cache(maxsize=1)
def get_data_store() -> DataStore:
    return DataStore.from_directory(DATA_DIR)