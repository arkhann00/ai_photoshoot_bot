from .start import router as start_router
from .photoshoot import router as photoshoot_router
from .support import router as support_router
from .balance import router as balance_router
from .admin import router as admin_router
from .payments_stars import router as payments_stars_router
from .cabinet import router as cabinet_router
__all__ = [
    "start_router",
    "photoshoot_router",
    "support_router",
    "balance_router",
    "admin_router",
    "payments_stars_router",
    "cabinet_router"
]
