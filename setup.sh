#!/usr/bin/env bash
# ───────────────────────────────────────────────────────
# Momir Vig Web App — Setup & Run Script
# ───────────────────────────────────────────────────────
# Run this after cloning:
#   git clone https://github.com/PlazmaEssence/momir-basic.git
#   cd momir-basic
#   chmod +x setup.sh && ./setup.sh
#
# It's idempotent — safe to run again on an existing install.
# ───────────────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()   { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC}  $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. System dependencies ──────────────────────────
log "Checking system dependencies..."

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python not found. Install python3 and pip."
    exit 1
fi

ok "Using $($PYTHON --version)"

# ── 2. Virtual environment ──────────────────────────
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
    ok "Virtual environment created at $VENV_DIR"
else
    ok "Virtual environment already exists"
fi

# Use the venv's python and pip from here on
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ── 3. Python packages ──────────────────────────────
log "Installing Python packages from requirements.txt..."

$VENV_PIP install --upgrade pip -q

if [ -f requirements.txt ]; then
    $VENV_PIP install -r requirements.txt -q
    ok "Python packages installed"
else
    warn "No requirements.txt found — installing core deps directly..."
    $VENV_PIP install flask -q
    ok "Flask installed"
fi

# ── 4. AtomicCards data file ────────────────────────
ATOMIC_FILE="AtomicCards.json.gz"
ATOMIC_URL="https://mtgjson.com/api/v5/AtomicCards.json.gz"

log "Checking data file: $ATOMIC_FILE"

if [ -f "$ATOMIC_FILE" ]; then
    # Quick sanity check — is it a valid gzip?
    if gzip -t "$ATOMIC_FILE" 2>/dev/null; then
        ok "$ATOMIC_FILE exists and is valid"
    else
        warn "$ATOMIC_FILE is corrupt — re-downloading..."
        rm -f "$ATOMIC_FILE"
    fi
fi

if [ ! -f "$ATOMIC_FILE" ]; then
    log "Downloading $ATOMIC_FILE from MTGJSON..."
    echo ""
    if command -v wget &>/dev/null; then
        wget -O "$ATOMIC_FILE" "$ATOMIC_URL" --show-progress
    elif command -v curl &>/dev/null; then
        curl -L -o "$ATOMIC_FILE" "$ATOMIC_URL" --progress-bar
    else
        err "Neither wget nor curl found. Install one of them."
        exit 1
    fi
    echo ""

    # Validate
    if [ -f "$ATOMIC_FILE" ] && gzip -t "$ATOMIC_FILE" 2>/dev/null; then
        ok "Downloaded and verified $ATOMIC_FILE"
    else
        err "Download failed or file is corrupt"
        exit 1
    fi
fi

# ── 5. Build database if needed ─────────────────────
DB_FILE="momir.db"

log "Checking database: $DB_FILE"

# Decide if we need to rebuild:
# - DB doesn't exist, OR
# - DB is older than AtomicCards.json.gz, OR
# - build script has changed since DB was created
NEED_BUILD=false

if [ ! -f "$DB_FILE" ]; then
    NEED_BUILD=true
    log "Database not found — will build"
elif [ "$ATOMIC_FILE" -nt "$DB_FILE" ]; then
    NEED_BUILD=true
    log "Data file is newer than database — will rebuild"
elif [ -f "build_momir_db.py" ] && [ "build_momir_db.py" -nt "$DB_FILE" ]; then
    NEED_BUILD=true
    log "Build script updated since last DB build — will rebuild"
fi

if [ "$NEED_BUILD" = true ]; then
    if [ ! -f "build_momir_db.py" ]; then
        err "build_momir_db.py not found! Cannot build database."
        exit 1
    fi

    log "Running build_momir_db.py..."
    $VENV_PYTHON build_momir_db.py
    echo ""

    if [ -f "$DB_FILE" ]; then
        ok "Database built successfully ($(du -h "$DB_FILE" | cut -f1))"
    else
        err "Database build failed — $DB_FILE not created"
        exit 1
    fi
else
    ok "Database is up to date ($(du -h "$DB_FILE" | cut -f1))"
fi

# ── 6. Launch web server ────────────────────────────
echo ""
log "Starting Momir Vig web server..."
echo "───────────────────────────────────────────────"
echo -e "  Open in your browser: ${CYAN}http://localhost:5000${NC}"
echo -e "  Or from another machine: ${CYAN}http://<raspberry-pi-ip>:5000${NC}"
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop"
echo "───────────────────────────────────────────────"
echo ""

exec $VENV_PYTHON momir_app.py