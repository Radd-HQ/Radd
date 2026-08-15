import os

# One source of truth for the running version (RADD-1066): the image build
# stamps RADD_VERSION from the git tag (Containerfile ARG -> publish.yaml
# --build-arg), so /health, the OpenAPI page and the MCP handshake report the
# version that is actually deployed. Everything else — dev checkouts, tests,
# hand-built images — honestly reads "dev". The pyproject version is
# deliberately NOT consulted: nothing bumped it across 33 releases, and a
# stale number is worse than none.
__version__ = os.environ.get("RADD_VERSION") or "dev"
