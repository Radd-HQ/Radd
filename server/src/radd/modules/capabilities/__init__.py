"""The /capabilities aggregator — a thin core plugin over the kernel capability
registry (docs/plugin-platform.md §3.2/§8a). Owns the one cross-cutting *infra*
capability that belongs to no feature (background workers); every feature and
connector plugin registers its own CapabilitySpec in its manifest — outbound
email is mailintake's, since it owns the senders (RADD-1389).
"""

from radd.config import settings
from radd.kernel import CapabilitySpec, IntegrationSpec, RaddPlugin
from radd.kernel.sockets import Socket
from radd.worker import LOCALLOOP

from .router import router

plugin = RaddPlugin(
    name="capabilities",
    description="Reports which features are available and configured on this server.",
    depends_on=("auth",),
    routers=(router,),
    # The TASK_BACKEND socket provider (spec 93, §6).
    integrations=(
        IntegrationSpec(Socket.TASK_BACKEND, "localloop", impl=LOCALLOOP),
    ),
    capabilities=(
        CapabilitySpec(
            key="workers",
            label="Background workers",
            category="infra",
            check=lambda: {"enabled": settings.run_workers},
        ),
    ),
)
