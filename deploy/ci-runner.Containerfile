# The CI/CD runner image — every tool both pipelines used to download at job
# time, baked in and pinned.
#
#   git.radd-hq.com/radd/ci-runner:<version>     (version in ci-runner.version)
#
# WHY THIS EXISTS (RADD-807). Both workflows curled their tools on every run,
# which made a third-party host a hard dependency of every deploy and every
# image build. On 2026-08-04 that stopped being theoretical: `get.helm.sh` was
# unreachable from the runner's nested job container and CD failed four runs
# (#51, #52, #55, #56).
#
# Two things made it worse than a flaky download:
#
#   * The "fallback mirror" was fictional. helm publishes NO binary tarballs on
#     GitHub releases — only .asc/.sha256sum.asc signatures — so the primary URL
#     404s on EVERY run and the fallback was the only real source. Two sources,
#     one of them imaginary.
#   * One step installed kubectl AND helm, exiting before `kubectl apply` if the
#     helm tarball was empty. kubectl downloads fine from dl.k8s.io, so a helm
#     outage blocked manifest-only deploys that never touch helm.
#
# Downloads now happen HERE, once per version bump, where a failure is a red
# build of this image instead of a failed deployment.
#
# BASE IS node:22-bookworm ON PURPOSE. actions/checkout is a JavaScript action:
# an image carrying kubectl and helm but no node cannot check out a repository,
# which is why the workflows started from a node image and added tools rather
# than starting from something like alpine/k8s.
FROM docker.io/library/node:22-bookworm

# Pinned deliberately, and matched to what the workflows used before this image
# existed so switching to it changes nothing but where the bytes come from. A
# floating version would reintroduce exactly what this image removes: a deploy
# whose tools differ from yesterday's for reasons nobody chose. Upgrading is a
# commit here plus a bump of ci-runner.version.
ARG KUBECTL_VERSION=v1.31.3
ARG HELM_VERSION=v3.16.3
ARG DOCKER_CLI_VERSION=27.5.1

# git is used by actions/checkout; python3 by publish.yaml's release_notes.py.
# Both happen to be present in node:22-bookworm today via buildpack-deps —
# which is precisely the kind of inherited accident that disappears on a base
# bump and fails a release at the last step. Ask for them explicitly.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ca-certificates curl git python3 tar; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    curl -fsSL --connect-timeout 20 --retry 3 --retry-delay 2 \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
      -o /usr/local/bin/kubectl; \
    chmod 0755 /usr/local/bin/kubectl

# get.helm.sh is the ONLY host that serves helm binaries. There is no mirror to
# fall back to — which is the whole argument for fetching it here, once, rather
# than on the critical path of every deploy.
RUN set -eux; \
    curl -fsSL --connect-timeout 20 --retry 3 --retry-delay 2 \
      "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" -o /tmp/helm.tgz; \
    tar xz -C /tmp -f /tmp/helm.tgz linux-amd64/helm; \
    install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm; \
    rm -rf /tmp/helm.tgz /tmp/linux-amd64

# The CLI ONLY. The daemon is the runner pod's DinD sidecar, reached over
# DOCKER_HOST — this image must never ship a docker daemon of its own.
RUN set -eux; \
    curl -fsSL --connect-timeout 20 --retry 3 --retry-delay 2 \
      "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
      | tar xz -C /tmp docker/docker; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker

# Prove every tool RUNS, not merely that a file landed. A truncated download
# produces a file of the right name and the wrong size; this is what turns that
# into a failed image build rather than a failed deploy three weeks later.
RUN set -eux; \
    kubectl version --client=true -o yaml > /dev/null; \
    helm version --short; \
    docker --version; \
    git --version; \
    node --version; \
    python3 --version
