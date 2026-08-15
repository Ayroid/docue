#!/usr/bin/env bash
#
# Docue — local development launcher.
#
#   ./dev.sh              bring up services, API and interface
#   ./dev.sh backend      services and API only
#   ./dev.sh frontend     interface only (expects the API already running)
#   ./dev.sh stop         stop the containers, keep the data
#   ./dev.sh reset        destroy the database and rebuild it from scratch
#
# Safe to re-run. Migrations are applied every time, dependencies are synced
# only when their manifests have changed, and the admin is seeded only if no
# user exists yet.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

API_PORT=8000
WEB_PORT=5173

# ── output ────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  BLUE=$'\033[34m'; MAGENTA=$'\033[35m'; RESET=$'\033[0m'
else
  DIM=; RED=; GREEN=; YELLOW=; BLUE=; MAGENTA=; RESET=
fi

say()  { printf '%s==>%s %s\n' "$BLUE" "$RESET" "$*"; }
ok()   { printf '%s  ok%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s  !!%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%s error:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 \
    || die "$1 is not installed. $2"
}

# ── preflight ─────────────────────────────────────────────────────────────
check_tools() {
  need docker "Install Docker and make sure the daemon is running."
  docker info >/dev/null 2>&1 \
    || die "The Docker daemon is not reachable. Start it and try again."
  need uv "Install it: https://docs.astral.sh/uv/getting-started/installation/"
  need node "Install Node 18 or newer."
}

# A port already in use is almost always a previous run of this script that was
# not shut down. Saying so beats a stack trace from uvicorn or vite.
check_port() {
  local port=$1 what=$2
  if command -v ss >/dev/null 2>&1 && ss -lnt "sport = :$port" 2>/dev/null | grep -q LISTEN; then
    die "Port $port is already in use, so $what cannot start. Stop whatever holds it, or run './dev.sh stop'."
  fi
}

check_env() {
  if [ ! -f "$BACKEND/.env" ]; then
    warn "backend/.env is missing — creating it from .env.example."
    cp "$BACKEND/.env.example" "$BACKEND/.env"
    warn "Fill in DATABASE_URL, LLM_API_KEY and JWT_SECRET before this will work."
    warn "Generate a secret with:"
    warn "  python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    exit 1
  fi
}

# ── services ──────────────────────────────────────────────────────────────
wait_healthy() {
  local name=$1 tries=${2:-60}
  printf '     waiting for %s' "$name"
  for _ in $(seq 1 "$tries"); do
    case "$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null)" in
      healthy) printf '\n'; ok "$name is healthy"; return 0 ;;
      unhealthy) printf '\n'; die "$name reported unhealthy. Check: docker logs $name" ;;
    esac
    printf '.'
    sleep 1
  done
  printf '\n'
  die "$name did not become healthy in time. Check: docker logs $name"
}

start_services() {
  say "Starting Postgres and MinIO"
  ( cd "$BACKEND" && docker compose up -d )
  wait_healthy postgres
  wait_healthy minio
}

# ── backend ───────────────────────────────────────────────────────────────
prepare_backend() {
  say "Preparing the API"
  ( cd "$BACKEND" && uv sync --quiet )

  # The venv records absolute paths, so moving or renaming the checkout leaves
  # every console script pointing at a directory that no longer exists. uv sync
  # does not repair this, so detect it and rebuild rather than failing later
  # with a bare "No such file or directory".
  if [ -f "$BACKEND/.venv/bin/alembic" ]; then
    local shebang
    shebang="$(head -1 "$BACKEND/.venv/bin/alembic")"
    if [[ "$shebang" != *"$BACKEND"* ]]; then
      warn "The virtualenv points at an old path — rebuilding it."
      rm -rf "$BACKEND/.venv"
      ( cd "$BACKEND" && uv sync --quiet )
    fi
  fi
  ok "dependencies synced"

  ( cd "$BACKEND" && uv run alembic upgrade head >/dev/null )
  ok "migrations applied"

  # Only on a genuinely empty database — never overwrite an existing admin.
  local users
  users="$(docker exec postgres psql -U docue -d docue -tAc \
    'select count(*) from users' 2>/dev/null || echo 0)"
  if [ "${users//[[:space:]]/}" = "0" ]; then
    say "No users yet — seeding the first administrator"
    ( cd "$BACKEND" && uv run python scripts/seed_admin.py ) \
      || warn "Seeding failed. Set SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD in backend/.env."
  fi
}

prepare_frontend() {
  say "Preparing the interface"
  if [ ! -d "$FRONTEND/node_modules" ] \
     || [ "$FRONTEND/package-lock.json" -nt "$FRONTEND/node_modules" ]; then
    ( cd "$FRONTEND" && npm install --no-fund --no-audit )
  fi
  ok "packages installed"
}

# ── run ───────────────────────────────────────────────────────────────────
PIDS=()
SHUTTING_DOWN=0

# Each service runs as a subshell wrapping a pipeline, so $! is the wrapper --
# killing it would orphan the uvicorn and vite processes inside and leave the
# ports held. Walk the tree and signal every descendant, deepest first.
kill_tree() {
  local pid=$1 sig=$2 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child" "$sig"
  done
  kill "-$sig" "$pid" 2>/dev/null || true
}

shutdown() {
  # The trap fires on INT and again on EXIT; only the first should do the work.
  [ "$SHUTTING_DOWN" = "1" ] && return
  SHUTTING_DOWN=1
  trap - INT TERM EXIT

  printf '\n'
  say "Shutting down"
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill_tree "$pid" TERM
  done

  # Give them a moment to exit cleanly, then insist.
  local waited=0
  while [ "$waited" -lt 10 ]; do
    local alive=0
    for pid in "${PIDS[@]:-}"; do
      [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && alive=1
    done
    [ "$alive" = "0" ] && break
    sleep 0.5
    waited=$((waited + 1))
  done
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill_tree "$pid" KILL
  done

  wait 2>/dev/null || true
  ok "processes stopped (containers left running — './dev.sh stop' to stop those too)"
}

run_api() {
  ( cd "$BACKEND" && uv run uvicorn app.main:app --reload --port "$API_PORT" 2>&1 \
    | sed -u "s/^/${MAGENTA}api ${RESET}/" ) &
  PIDS+=($!)
}

run_web() {
  ( cd "$FRONTEND" && npm run dev -- --port "$WEB_PORT" 2>&1 \
    | sed -u "s/^/${BLUE}web ${RESET}/" ) &
  PIDS+=($!)
}

banner() {
  printf '\n'
  printf '  %sDocue is running%s\n' "$GREEN" "$RESET"
  [ "$1" = "both" ] || [ "$1" = "frontend" ] && \
    printf '    interface   http://localhost:%s\n' "$WEB_PORT"
  [ "$1" = "both" ] || [ "$1" = "backend" ] && {
    printf '    api         http://localhost:%s\n' "$API_PORT"
    printf '    api docs    http://localhost:%s/docs\n' "$API_PORT"
    printf '    minio       http://localhost:9001  %s(minio / minioadm)%s\n' "$DIM" "$RESET"
  }
  printf '\n  %sCtrl-C to stop%s\n\n' "$DIM" "$RESET"
}

# ── subcommands ───────────────────────────────────────────────────────────
cmd_stop() {
  say "Stopping containers"
  ( cd "$BACKEND" && docker compose down )
  ok "stopped — data volumes kept"
}

cmd_reset() {
  printf '%sThis destroys the Docue database and every uploaded file.%s\n' "$YELLOW" "$RESET"
  read -r -p "Type 'reset' to confirm: " reply
  [ "$reply" = "reset" ] || { echo "Cancelled."; exit 0; }
  ( cd "$BACKEND" && docker compose down -v )
  ok "volumes destroyed"
  start_services
  prepare_backend
  ok "rebuilt — run './dev.sh' to start"
}

main() {
  local mode="${1:-both}"

  case "$mode" in
    stop)  check_tools; cmd_stop; exit 0 ;;
    reset) check_tools; check_env; cmd_reset; exit 0 ;;
    both|backend|frontend) ;;
    -h|--help|help)
      # The header comment block, up to the first line that is not a comment.
      awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) die "Unknown command '$mode'. Try: ./dev.sh --help" ;;
  esac

  check_tools

  trap shutdown INT TERM EXIT

  if [ "$mode" != "frontend" ]; then
    check_env
    check_port "$API_PORT" "the API"
    start_services
    prepare_backend
    run_api
  fi

  if [ "$mode" != "backend" ]; then
    check_port "$WEB_PORT" "the interface"
    prepare_frontend
    run_web
  fi

  banner "$mode"
  wait
}

main "$@"
