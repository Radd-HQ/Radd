# Shared by scripts/dev.sh and scripts/dev-clean.sh.
#
# The two stacks differ in exactly three things — which database, which Garage
# volumes, and whether the database is wiped first. Everything else is identical,
# so it lives here rather than being written twice and drifting.

say() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
step() { printf '  \033[2m->\033[0m %s\n' "$1"; }

pg_url() { echo "postgresql+psycopg://radd:radd@localhost:$1/radd"; }

# Postgres accepts connections a moment after the container is "up"; migrating
# too early fails with a connection refused that reads like a broken setup.
wait_for_pg() {
    port="$1"
    tries=0
    until podman exec "$(pg_container "$port")" pg_isready -U radd -d radd >/dev/null 2>&1; do
        tries=$((tries + 1))
        [ "$tries" -gt 60 ] && { echo "postgres on :$port never became ready"; exit 1; }
        sleep 1
    done
}

pg_container() {
    case "$1" in
        5457) echo "radd-clean_db_1" ;;
        *) echo "tracker_db_1" ;;
    esac
}

# Shared between both stacks: it is stateless, holds no instance data, and one
# GPU cannot serve two copies anyway.
start_embeddings() {
    if podman ps --format '{{.Names}}' | grep -q 'embeddings-gpu'; then
        step "embeddings already up"
        return
    fi
    # NAME the service. `up -d` with no service starts everything in the file
    # that is not behind another profile — including compose.dev.yaml's own `app`,
    # which publishes :8000 and then fights the server this script is about to
    # start. Two servers on one port is the "old server answering" trap: the port
    # responds, so it looks like the code under test, not like a stray container.
    podman compose -f compose.dev.yaml --profile embeddings-gpu up -d embeddings-gpu >/dev/null 2>&1 || {
        printf '     \033[2m(embeddings-gpu did not start — semantic search will be dark)\033[0m\n'
    }
}

build_web() {
    if [ ! -x web/node_modules/.bin/vite ]; then
        printf '     \033[2m(no vite binary — skipping the bundle)\033[0m\n'
        return
    fi
    (cd web && ./node_modules/.bin/vite build >/dev/null 2>&1) || {
        printf '     \033[2m(bundle failed — the API still runs, the SPA may be stale)\033[0m\n'
    }
}

# compose.dev.yaml carries a containerised `app` on :8000 for the all-in-container
# workflow. These scripts run the server on the HOST, so the two compete for the
# port — and the container wins on restart, quietly serving its own build of the
# code against whichever database IT was configured for. Stop it.
stop_container_app() {
    if podman ps --format '{{.Names}}' | grep -q '^radd-dev_app_1$'; then
        step "stopping the containerised app on :8000 (it competes with this one)"
        podman stop radd-dev_app_1 >/dev/null 2>&1 || true
    fi
}

# Free the port before binding it. A failed bind leaves the OLD server answering,
# which looks exactly like a bug in the code under test rather than like the new
# process never having started.
free_port() {
    pid=$(ss -lptnH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true)
    [ -n "$pid" ] && { step "stopping the server already on :$1 (pid $pid)"; kill "$pid"; sleep 2; }
    return 0
}

serve() {
    url="$1"
    port="$2"
    stop_container_app
    free_port "$port"
    say "server on :$port"
    printf '  open \033[4mhttp://localhost:%s\033[0m\n\n' "$port"
    # From `server/`, deliberately: Settings reads env_file=".env" relative to
    # the CWD, and server/.env carries RADD_LDAP_* — a root-CWD start silently
    # loses LDAP sign-in and the bind account.
    # RADD_BACKUP_TOOLS_OPTIONAL because the host has no pg_dump; the app refuses
    # to start without it otherwise.
    cd server
    exec env \
        RADD_DATABASE_URL="$url" \
        RADD_BACKUP_TOOLS_OPTIONAL=true \
        uv run uvicorn --factory radd.app:create_app --host 0.0.0.0 --port "$port"
}
