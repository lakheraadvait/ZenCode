#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════╗
# ║         ZENCODE v10 — One-Shot Installer              ║
# ║         Linux / macOS                                ║
# ╚══════════════════════════════════════════════════════╝
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'
BOLD='\033[1m'

print_logo() {
    echo -e "${CYAN}"
    echo "  ███████╗███████╗███╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗"
    echo "  ╚══███╔╝██╔════╝████╗  ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝"
    echo "    ███╔╝ █████╗  ██╔██╗ ██║██║     ██║   ██║██║  ██║█████╗  "
    echo "   ███╔╝  ██╔══╝  ██║╚██╗██║██║     ██║   ██║██║  ██║██╔══╝  "
    echo "  ███████╗███████╗██║ ╚████║╚██████╗╚██████╔╝██████╔╝███████╗"
    echo "  ╚══════╝╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝"
    echo -e "${NC}"
    echo -e "  ${BOLD}${CYAN}ZENCODE v10 — Autonomous AI Code Shell${NC}"
    echo -e "  ${DIM}Installing system-wide...${NC}"
    echo ""
}

step() { echo -e "  ${CYAN}▸${NC}  $1"; }
ok()   { echo -e "  ${GREEN}✔${NC}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
fail() { echo -e "  ${RED}✖${NC}  $1"; exit 1; }

print_logo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.zencode"
BIN_LINK=""

# ── 1. Check Python ──────────────────────────────────────────────────────────
step "Checking Python..."
if command -v python3 &>/dev/null; then
    PY=$(python3 --version 2>&1)
    ok "Found $PY"
    PYTHON=python3
elif command -v python &>/dev/null; then
    PY=$(python --version 2>&1)
    ok "Found $PY"
    PYTHON=python
else
    fail "Python 3.9+ required. Install from python.org"
fi

# Check version
PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    fail "Python 3.9+ required (found $PY_VER)"
fi

# ── 2. Install Python deps ───────────────────────────────────────────────────
step "Installing Python dependencies..."
$PYTHON -m pip install --quiet --upgrade \
    mistralai rich click prompt_toolkit \
    --break-system-packages 2>/dev/null || \
$PYTHON -m pip install --quiet --upgrade \
    mistralai rich click prompt_toolkit 2>/dev/null || \
warn "pip install had issues — trying with --user flag..." && \
$PYTHON -m pip install --quiet --upgrade --user \
    mistralai rich click prompt_toolkit 2>/dev/null
ok "Python dependencies installed"

# ── 3. Install zencode package ───────────────────────────────────────────────
step "Installing zencode package..."
cd "$SCRIPT_DIR"
$PYTHON -m pip install --quiet -e . --break-system-packages 2>/dev/null || \
$PYTHON -m pip install --quiet -e . 2>/dev/null || \
$PYTHON -m pip install --quiet --user -e . 2>/dev/null
ok "Package installed"

# ── 4. Verify zencode command ────────────────────────────────────────────────
step "Verifying installation..."
if command -v zencode &>/dev/null; then
    ok "zencode command available at $(which zencode)"
    BIN_LINK=$(which zencode)
else
    # Try common pip bin paths
    POSSIBLE_BINS=(
        "$HOME/.local/bin/zencode"
        "/usr/local/bin/zencode"
        "$HOME/Library/Python/3.${PY_MINOR}/bin/zencode"
        "$($PYTHON -c 'import sys; print(sys.prefix)')/bin/zencode"
    )
    for bin in "${POSSIBLE_BINS[@]}"; do
        if [ -f "$bin" ]; then
            BIN_LINK="$bin"
            ok "Found at $bin"
            break
        fi
    done

    if [ -z "$BIN_LINK" ]; then
        # Create a manual wrapper
        WRAPPER="$HOME/.local/bin/zencode"
        mkdir -p "$HOME/.local/bin"
        cat > "$WRAPPER" << EOF
#!/usr/bin/env bash
exec $PYTHON -m zencode "\$@"
EOF
        chmod +x "$WRAPPER"
        BIN_LINK="$WRAPPER"
        ok "Created wrapper at $WRAPPER"
    fi
fi

# ── 5. Add to PATH if needed ─────────────────────────────────────────────────
BIN_DIR=$(dirname "$BIN_LINK")
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR not in PATH — adding to shell profile..."

    SHELL_PROFILES=("$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.profile")
    ADDED=false
    for profile in "${SHELL_PROFILES[@]}"; do
        if [ -f "$profile" ]; then
            echo "" >> "$profile"
            echo "# ZenCode" >> "$profile"
            echo "export PATH=\"\$PATH:$BIN_DIR\"" >> "$profile"
            ok "Added to $profile"
            ADDED=true
            break
        fi
    done

    if [ "$ADDED" = false ]; then
        echo "export PATH=\"\$PATH:$BIN_DIR\"" >> "$HOME/.profile"
        ok "Added to $HOME/.profile"
    fi

    export PATH="$PATH:$BIN_DIR"
fi

# ── 6. Create config dir ─────────────────────────────────────────────────────
mkdir -p "$HOME/.zencode"
ok "Config dir: $HOME/.zencode"

# ── 7. API key setup ─────────────────────────────────────────────────────────
echo ""
echo -e "  ${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${BOLD}Setup your Mistral API key${NC}"
echo -e "  ${DIM}Get one free at: console.mistral.ai${NC}"
echo -e "  ${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if key already set
EXISTING_KEY=$($PYTHON -c "
import json, pathlib
cfg = pathlib.Path.home() / '.zencode' / 'config.json'
try:
    data = json.loads(cfg.read_text())
    k = data.get('api_key','')
    print(k[:8] + '...' if len(k) > 8 else '')
except: print('')
" 2>/dev/null)

if [ -n "$EXISTING_KEY" ]; then
    ok "API key already set ($EXISTING_KEY)"
else
    read -p "  Enter Mistral API key (or press Enter to skip): " API_KEY
    if [ -n "$API_KEY" ]; then
        $PYTHON -m zencode --setkey "$API_KEY" 2>/dev/null || \
            zencode --setkey "$API_KEY" 2>/dev/null
        ok "API key saved"
    else
        warn "Skipped — run 'zencode --setkey YOUR_KEY' later"
    fi
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}${BOLD}✔  ZENCODE v10 INSTALLED${NC}"
echo -e "  ${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Quick start:${NC}"
echo -e "  ${CYAN}  cd ~/myproject${NC}"
echo -e "  ${CYAN}  zencode${NC}"
echo ""
echo -e "  ${DIM}Or restart your terminal first if 'zencode' isn't found${NC}"
echo ""
