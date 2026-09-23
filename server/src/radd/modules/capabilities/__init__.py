"""The /capabilities aggregator — a thin core plugin over the kernel capability
registry (docs/plugin-platform.md §3.2/§8a). Owns the two cross-cutting *infra*
capabilities (background workers + outbound SMTP) that belong to no single feature;
every feature/connector plugin registers its own CapabilitySpec in its manifest.
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
    # The default TaskBackend socket provider (spec 93 / A8, §6). A `celery` plugin
    # registers another `task_backend` provider to swap the runner.
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
        CapabilitySpec(
            key="smtp",
            label="Outbound email (SMTP)",
            category="infra",
            check=lambda: {"enabled": bool(settings.smtp_host)},
        ),
        CapabilitySpec(
            key="mfa",
            label="Multi-factor auth (TOTP)",
            category="auth",
            check=lambda: {"enabled": True},
        ),
    ),
)
