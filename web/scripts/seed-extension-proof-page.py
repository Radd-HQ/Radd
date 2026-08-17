#!/usr/bin/env python3
"""Create (or refresh) a dev page that exercises every extension, for the CDP proof."""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
SESSION = {"cookie": ""}


def api(method, path, body=None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
    )
    req.add_header("Content-Type", "application/json")
    if SESSION["cookie"]:
        req.add_header("Cookie", SESSION["cookie"])
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            set_cookie = resp.headers.get("Set-Cookie")
            if set_cookie:
                SESSION["cookie"] = set_cookie.split(";")[0]
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        print(f"! {method} {path} {exc.code}: {exc.read().decode()[:300]}", file=sys.stderr)
        raise


api("POST", "/auth/login", {"email": os.environ.get("RADD_PROOF_EMAIL", "admin@example.com"), "password": os.environ.get("RADD_PROOF_PASSWORD", "change-me")})

SPACE_SLUG = "ext-proof"
spaces = api("GET", "/page-spaces")
space = next((s for s in spaces if s["slug"] == SPACE_SLUG), None)
if space is None:
    space = api("POST", "/page-spaces", {
        "name": "Extension proof",
        "slug": SPACE_SLUG,
        "description": "Scratch space for verifying the RADD-709 render path.",
    })

BODY = """\
# First heading

Prose before anything. This paragraph must render as prose, through Crepe.

```radd:toc
{"depth": 3}
```

## Second heading

Text between two extensions.

```radd:callout
{"kind": "warning", "title": "Careful", "text": "This is *rendered* markdown inside a callout."}
```

### Third heading

An ordinary code block, which must NOT become an extension:

```python
print("still code")
```

And documentation ABOUT an extension, which must also stay code:

````markdown
```radd:toc
{"subpages": true}
```
````

```radd:children
{}
```

```radd:nonesuch
{}
```

```radd:callout
{"kind": "info", "title": "Broken params below"}
```

```radd:callout
{not json at all
```

```radd:toc
{"subpages": true, "depth": 3}
```
"""

pages = api("GET", f"/page-spaces/{space['id']}/pages")
page = next((p for p in pages if p["slug"] == "render-proof"), None)
if page is None:
    page = api("POST", "/pages", {
        "space_id": space["id"],
        "title": "Render proof",
        "body": BODY,
    })
else:
    page = api("PATCH", f"/pages/{page['id']}", {"body": BODY})

# A child, so radd:children has something to list.
kids = api("GET", f"/page-spaces/{space['id']}/pages")
if not any(k["parent_id"] == page["id"] for k in kids):
    api("POST", "/pages", {
        "space_id": space["id"],
        "parent_id": page["id"],
        "title": "A child page",
        "body": "Just here so the children extension has something to show.",
    })

print(json.dumps({"space": space["slug"], "page": page["slug"], "url": f"/pages/{space['slug']}/{page['slug']}"}))
