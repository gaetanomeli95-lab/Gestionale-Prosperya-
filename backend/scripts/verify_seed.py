"""Quick sanity check of the seeded preview dataset (dev use).

Run from backend/:  python scripts/verify_seed.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

import app.models_all  # noqa: F401 — register every mapper before querying
from app.db import SessionLocal
from app.modules.companies.models import Company
from app.modules.controlling.models import ControllingAlert, DebtFacility
from app.modules.fiscal.models import VatSettlement
from app.modules.treasury.models import BankAccount, OpenItem
from app.modules.users.models import User

db = SessionLocal()
print("users:", db.scalar(select(func.count(User.id))))
for c in db.scalars(select(Company).order_by(Company.legal_name)):
    print(" -", c.legal_name, "|", c.vat_number)
print("accounts:", db.scalar(select(func.count(BankAccount.id))))
print("open_items:", db.scalar(select(func.count(OpenItem.id))))
print("settlements:", db.scalar(select(func.count(VatSettlement.id))))
print("facilities:", db.scalar(select(func.count(DebtFacility.id))))
print("alerts:", db.scalar(select(func.count(ControllingAlert.id))))
