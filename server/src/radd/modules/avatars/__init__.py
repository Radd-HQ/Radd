"""RADD-1295 — people's pictures.

A person's avatar is an uploaded image, else their identity provider's picture,
else the colour/emoji they already had. `auth` owns the columns and the one
`User.avatar_url` rule; this module owns the BYTES: it normalises an upload
(square, 256px, WebP — so no 20px chip ever downloads a photo) and stores it
through the attachments blob API, which is why it sits above `attachments`
rather than inside `auth`.

An avatar is deliberately NOT an attachment: it is not listed on anything,
carries no per-file grants, and never asks which storage host to use.
"""

from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="avatars",
    description="Profile pictures: upload your own, or use your sign-in provider's.",
    depends_on=("auth", "attachments"),
    routers=(router,),
)
