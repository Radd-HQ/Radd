"""People's pictures (RADD-1295): an upload, else the identity provider's picture, else the
colour/emoji. `auth` owns the columns and the `User.avatar_url` rule; this module owns the BYTES —
normalised (square, 256px, WebP: no 20px chip downloads a photo) and stored through the
attachments blob API. Deliberately NOT an attachment: never listed, no per-file grants, no
storage-host question.
"""

from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="avatars",
    description="Profile pictures: upload your own, or use your sign-in provider's.",
    depends_on=("auth", "attachments"),
    routers=(router,),
)
