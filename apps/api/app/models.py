"""Import every model module so Base.metadata is complete (Alembic, tests)."""

from app.crm import models as crm_models  # noqa: F401
from app.learning import models as learning_models  # noqa: F401
