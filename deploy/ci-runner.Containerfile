# The CI/CD runner image — every tool both pipelines used to download at job
# time, taken from pinned registry images instead.
#
#   git.radd-hq.com/radd/ci-runner:<version>     (version in ci-runner.version)
#
# WHY THIS EXISTS (RADD-807). Both workflows curled their tools on every run,
# which made third-party HTTPS hosts a hard dependency of every deploy and every
# image build. On 2026-08-04 that cost four red deploys (#51, #52, #55, #56).
#
# Three things turned a flaky download into a blocked pipeline:
#
#   * `get.helm.sh` RESOLVES IPv6-ONLY (2603:1061:14:21::1, Azure Front Door).
#     The k3s node has working IPv6 and fetches it fine, which is why this looked
#     intermittent for days — but the DinD bridge that job containers sit on has
#     no IPv6 at all, so from inside a build it times out every single time. It
#     was never a blip; that host is simply not reachable from where the work
#     happens, and `curl -4` cannot help because there is nothing to fall back
#     to.
#   * The "fallback mirror" was fictional. helm publishes NO binary tarballs on
#     GitHub releases — only .asc/.sha256sum.asc signatures — so the primary URL
#     404s on every run and the unreachable host was the only real source.
#   * One step installed kubectl AND helm and exited before `kubectl apply`, so
#     a helm failure blocked manifest-only deploys that never touch helm.
#
# SO NOTHING IS FETCHED OVER PLAIN HTTPS HERE. Every binary is copied out of an
# official image, pinned by digest. A container build must already reach a
# registry, so this adds no dependency it did not have — and registries are the
# one path proven to work from the DinD bridge, since that is how job containers
# themselves are pulled.
#
# Upgrading a tool means bumping a digest here and ci-runner.version: a
# reviewable commit, not a silent change in what a deploy executes.

# helm 3.16.3 — alpine/helm is a repackage rather than an upstream image,
# because upstream ships only the tarball on the IPv6-only host above.
FROM docker.io/alpine/helm@sha256:8af788e831994fb426290aa30d8a0dbfefd4f32a3bbe851c4129d28db360c9d8 AS helm

# kubectl v1.31.3 — the Kubernetes project's own image.
FROM registry.k8s.io/kubectl@sha256:83e1de860f7ee7a2659eb18cc6ea8c133d7fa66c0c60ff9c9858ba5ce5c7cfc8 AS kubectl

# docker 27.5.1, CLI ONLY. The daemon is the runner pod's DinD sidecar, reached
# over DOCKER_HOST — this image must never ship a docker daemon of its own.
FROM docker.io/library/docker@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c AS dockercli

# BASE IS node:22-bookworm ON PURPOSE. actions/checkout is a JavaScript action:
# an image carrying kubectl and helm but no node cannot check out a repository,
# which is why the workflows started from a node image and added tools rather
# than starting from something like alpine/k8s.
FROM docker.io/library/node:22-bookworm

# git is used by actions/checkout; python3 by publish.yaml's release_notes.py.
# Both happen to be present in node:22-bookworm today via buildpack-deps —
# precisely the kind of inherited accident that disappears on a base bump and
# fails a release at its last step. Ask for them explicitly. (apt reaches the
# Debian mirrors fine; it is get.helm.sh specifically that is unroutable here.)
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates git python3; \
    rm -rf /var/lib/apt/lists/*

COPY --from=helm      /usr/bin/helm         /usr/local/bin/helm
COPY --from=kubectl   /bin/kubectl          /usr/local/bin/kubectl
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

# Prove every tool RUNS, and that the versions are the ones claimed above — a
# COPY from the wrong path in a rebuilt upstream image would otherwise surface
# as a failed deploy weeks later. Each grep fails the BUILD on a mismatch.
RUN set -eux; \
    helm version --short              | grep -q '^v3\.16\.3'; \
    kubectl version --client=true -o yaml | grep -q 'gitVersion: v1\.31\.3'; \
    docker --version                  | grep -q '27\.5\.1'; \
    git --version; \
    node --version; \
    python3 --version
