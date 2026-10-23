"""The project's own packages.

Decision 132: importing core guards every billable request, so no
one-off script can spend money or voice credits (core.paid)."""

from core import paid as _paid

_paid.install()
