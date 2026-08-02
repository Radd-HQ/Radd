from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="settings",
    description="Scalar settings that cascade project → instance → env default (specs 50/67).",
    depends_on=("projects", "auth"),
    routers=(router,),
)
