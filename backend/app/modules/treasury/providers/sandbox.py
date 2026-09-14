"""Built-in banking adapters: `manual` and `sandbox-openbanking/v1`.

**Neither talks to a real bank.** `capabilities.is_real_institution` is False
for both and every sync batch stores `environment="sandbox"`, so the UI can
never present simulated movements as production data. Real PSD2 adapters
(GoCardless/Nordigen, Tink, Yapily, CBI flows…) are added later as separate
versioned modules implementing the same contract — no domain change required.

The sandbox is deterministic on purpose: the same account and window always
produce the same `provider_tx_id` values, which is what makes the idempotent
sync path and the reconciliation engine testable.
"""
import hashlib
from datetime import date, timedelta
from decimal import Decimal

from app.modules.treasury.providers.base import (
    BankCapabilities,
    BankError,
    BankErrorCategory,
    BankingProvider,
    BankResult,
    ConnectionState,
    ProviderAccount,
    ProviderBalance,
    ProviderTransaction,
)
from app.modules.treasury.providers.registry import register
from app.shared.mixins import today

SANDBOX_LABEL = "DATI SANDBOX SIMULATI — non provengono da un istituto reale."


def _stable_int(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


@register
class ManualLedger(BankingProvider):
    """Accounts fed by hand (or by file import): no remote connection at all.

    Kept as an adapter so the domain has exactly one code path; it simply
    declines every remote operation instead of pretending to succeed.
    """

    key = "manual"
    api_version = "v1"

    @property
    def capabilities(self) -> BankCapabilities:
        return BankCapabilities(
            supports_balances=False, supports_transactions=False,
            supports_consent_renewal=False, supports_sandbox=False,
            is_real_institution=False, max_history_days=0,
        )

    def validate_configuration(self) -> list[str]:
        return []

    def _declined(self) -> BankResult:
        return BankResult(
            ok=False,
            error=BankError(
                category=BankErrorCategory.NOT_SUPPORTED,
                message="Conto alimentato manualmente: nessuna connessione bancaria da aggiornare.",
            ),
        )

    def connect_account(self, *, reference: str) -> BankResult:  # noqa: ARG002
        return self._declined()

    def refresh_accounts(self) -> BankResult:
        return self._declined()

    def get_balances(self, provider_account_id: str) -> BankResult:  # noqa: ARG002
        return self._declined()

    def refresh_transactions(self, provider_account_id: str, *,  # noqa: ARG002
                             date_from: date, date_to: date) -> BankResult:
        return self._declined()

    def connection_status(self) -> BankResult:
        return BankResult(
            ok=True,
            connection=ConnectionState(
                status="not_connected",
                detail="Inserimento manuale: nessun consenso PSD2 in essere.",
                environment="local",
            ),
        )


@register
class SandboxOpenBanking(BankingProvider):
    """Deterministic simulator of an account-information (AIS) provider.

    Two modes, both reproducible:

    * **scripted** — `config["script"]` holds an explicit list of movements
      (used by the seed and tests to build coherent demo scenarios);
    * **synthetic** — movements are derived from the account seed, producing a
      plausible but clearly fictional monthly pattern.
    """

    key = "sandbox-openbanking"
    api_version = "v1"
    MAX_WINDOW_DAYS = 365

    @property
    def capabilities(self) -> BankCapabilities:
        return BankCapabilities(
            supports_balances=True, supports_transactions=True,
            supports_consent_renewal=True, supports_sandbox=True,
            is_real_institution=False, max_history_days=self.MAX_WINDOW_DAYS,
        )

    def validate_configuration(self) -> list[str]:
        problems: list[str] = []
        if self.environment == "production":
            problems.append(
                "L'adapter sandbox non può essere usato in ambiente production: "
                "configurare un provider bancario reale."
            )
        if not self.config.get("provider_account_id"):
            problems.append("provider_account_id mancante nella configurazione del conto.")
        script = self.config.get("script")
        if script is not None and not isinstance(script, list):
            problems.append("config.script deve essere una lista di movimenti.")
        return problems

    # --- contract ---------------------------------------------------------
    def connect_account(self, *, reference: str) -> BankResult:
        if problems := self.validate_configuration():
            return BankResult(ok=False, error=BankError(
                category=BankErrorCategory.CONFIGURATION, message=problems[0]))
        return BankResult(
            ok=True,
            accounts=(self._account(),),
            connection=ConnectionState(
                status="active", detail=SANDBOX_LABEL,
                expires_at=(today() + timedelta(days=180)).isoformat(),
                environment=self.environment,
            ),
            raw={"reference": reference, "sandbox": True},
        )

    def refresh_accounts(self) -> BankResult:
        if problems := self.validate_configuration():
            return BankResult(ok=False, error=BankError(
                category=BankErrorCategory.CONFIGURATION, message=problems[0]))
        return BankResult(ok=True, accounts=(self._account(),), raw={"sandbox": True})

    def get_balances(self, provider_account_id: str) -> BankResult:
        if problems := self.validate_configuration():
            return BankResult(ok=False, error=BankError(
                category=BankErrorCategory.CONFIGURATION, message=problems[0]))
        configured = self.config.get("opening_balance")
        base = Decimal(str(configured)) if configured is not None else Decimal(
            _stable_int("balance", provider_account_id) % 90_000
        ) + Decimal("1500.00")
        as_of = self.config.get("balance_date")
        return BankResult(
            ok=True,
            balances=(ProviderBalance(
                provider_account_id=provider_account_id,
                amount=base.quantize(Decimal("0.01")),
                balance_date=date.fromisoformat(as_of) if as_of else today(),
                kind="booked",
            ),),
            raw={"sandbox": True},
        )

    def refresh_transactions(self, provider_account_id: str, *,
                             date_from: date, date_to: date) -> BankResult:
        if problems := self.validate_configuration():
            return BankResult(ok=False, error=BankError(
                category=BankErrorCategory.CONFIGURATION, message=problems[0]))
        if date_to < date_from:
            return BankResult(ok=False, error=BankError(
                category=BankErrorCategory.PERMANENT,
                message="Finestra temporale non valida: data finale precedente alla iniziale."))
        if (date_to - date_from).days > self.MAX_WINDOW_DAYS:
            return BankResult(ok=False, error=BankError(
                category=BankErrorCategory.PERMANENT,
                message=f"Finestra massima supportata: {self.MAX_WINDOW_DAYS} giorni."))
        script = self.config.get("script")
        rows = (self._scripted(script, date_from, date_to) if isinstance(script, list)
                else self._synthetic(provider_account_id, date_from, date_to))
        return BankResult(ok=True, transactions=tuple(rows), raw={"sandbox": True})

    def connection_status(self) -> BankResult:
        ok = not self.validate_configuration()
        return BankResult(
            ok=ok,
            connection=ConnectionState(
                status="active" if ok else "error",
                detail=SANDBOX_LABEL, environment=self.environment,
            ),
        )

    def revoke_connection(self) -> BankResult:
        return BankResult(ok=True, connection=ConnectionState(
            status="revoked", detail=SANDBOX_LABEL, environment=self.environment))

    # --- generators -------------------------------------------------------
    def _account(self) -> ProviderAccount:
        account_id = str(self.config.get("provider_account_id", ""))
        return ProviderAccount(
            provider_account_id=account_id,
            label=str(self.config.get("label") or f"Conto sandbox {account_id[-4:]}"),
            bank_name=str(self.config.get("bank_name") or "Banca Sandbox (simulata)"),
            iban_last4=f"{_stable_int('iban', account_id) % 10000:04d}",
        )

    @staticmethod
    def _scripted(script: list, date_from: date, date_to: date) -> list[ProviderTransaction]:
        rows: list[ProviderTransaction] = []
        for index, raw in enumerate(script):
            if not isinstance(raw, dict):
                continue
            try:
                booking = date.fromisoformat(str(raw["date"]))
                amount = Decimal(str(raw["amount"])).quantize(Decimal("0.01"))
            except (KeyError, ValueError, ArithmeticError):
                continue
            if amount == 0 or not (date_from <= booking <= date_to):
                continue
            rows.append(ProviderTransaction(
                provider_tx_id=str(raw.get("id") or f"SBX-{booking.isoformat()}-{index:03d}"),
                booking_date=booking, value_date=booking, amount=amount,
                description=str(raw.get("description", ""))[:600],
                counterparty_name=(str(raw["counterparty"])[:300]
                                   if raw.get("counterparty") else None),
                raw={"sandbox": True, "scripted": True},
            ))
        return sorted(rows, key=lambda r: (r.booking_date, r.provider_tx_id))

    def _synthetic(self, account_id: str, date_from: date,
                   date_to: date) -> list[ProviderTransaction]:
        """Plausible fictional pattern: a monthly inflow, a supplier payment,
        salaries, an F24 and a bank fee. Amounts are stable per month."""
        rows: list[ProviderTransaction] = []
        cursor = date(date_from.year, date_from.month, 1)
        while cursor <= date_to:
            tag = f"{cursor.year}-{cursor.month:02d}"
            noise = _stable_int(account_id, tag)
            plan = (
                (10, Decimal(noise % 20_000 + 4_000), "INCASSO FATTURA CLIENTE SANDBOX", "Cliente Sandbox S.r.l."),
                (16, -Decimal(noise % 4_000 + 900), "PAGAMENTO F24 SANDBOX", "Agenzia Entrate (simulata)"),
                (20, -Decimal(noise % 9_000 + 2_500), "BONIFICO FORNITORE SANDBOX", "Fornitore Sandbox S.p.A."),
                (27, -Decimal(noise % 12_000 + 5_000), "STIPENDI SANDBOX", None),
                (28, Decimal("-4.50"), "COMMISSIONI CONTO SANDBOX", None),
            )
            for day, amount, description, counterparty in plan:
                try:
                    when = cursor.replace(day=day)
                except ValueError:
                    continue
                if not (date_from <= when <= date_to):
                    continue
                rows.append(ProviderTransaction(
                    provider_tx_id=f"SBX-{account_id[-6:]}-{when.isoformat()}-{day:02d}",
                    booking_date=when, value_date=when,
                    amount=amount.quantize(Decimal("0.01")),
                    description=description, counterparty_name=counterparty,
                    raw={"sandbox": True, "synthetic": True},
                ))
            cursor = (cursor.replace(day=28) + timedelta(days=7)).replace(day=1)
        return sorted(rows, key=lambda r: (r.booking_date, r.provider_tx_id))
