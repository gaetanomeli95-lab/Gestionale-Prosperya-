"""Single import surface for every ORM model.

`Base.metadata` is only complete once every model module has been imported.
Two places need that guarantee — Alembic autogenerate and the dev seed's
`create_all` — so the list lives here instead of being duplicated (and going
stale, which silently breaks cross-module foreign keys).
"""
import app.modules.activities.models  # noqa: F401
import app.modules.audit.models  # noqa: F401
import app.modules.billing.models  # noqa: F401
import app.modules.companies.models  # noqa: F401
import app.modules.contacts.models  # noqa: F401
import app.modules.controlling.models  # noqa: F401
import app.modules.documents.models  # noqa: F401
import app.modules.fiscal.models  # noqa: F401
import app.modules.funding.models  # noqa: F401
import app.modules.leads.models  # noqa: F401
import app.modules.management.models  # noqa: F401
import app.modules.notes.models  # noqa: F401
import app.modules.opportunities.models  # noqa: F401
import app.modules.practices.models  # noqa: F401
import app.modules.service_lines.models  # noqa: F401
import app.modules.tasks.models  # noqa: F401
import app.modules.tenancy.models  # noqa: F401
import app.modules.treasury.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.db import Base

#: Re-exported for convenience: `from app.models_all import metadata`.
metadata = Base.metadata
