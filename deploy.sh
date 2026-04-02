#!/usr/bin/env bash
# deploy.sh
# ------------------------------------------------------------
# Deployment script for stake move automation
# Sets up .env file, installs dependencies, and configures systemd
# ------------------------------------------------------------
set -euo pipefail

############################ CONSTANTS ############################
INSTALL_DIR="/opt/stake-move-automation"
ENV_FILE="$INSTALL_DIR/.env"
SERVICE_USER="${SERVICE_USER:-root}"
###################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    log_error "This script must be run as root (use sudo)"
    exit 1
fi

# Check for required commands
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is not installed. Please install it first."
        return 1
    fi
}

log_info "Checking prerequisites..."
check_command "python3" || log_warn "python3 not found, will install"
check_command "pip3" || log_warn "pip3 not found, will install"

# Install dependencies
log_info "Installing system dependencies..."
if command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y python3 python3-pip python3-venv curl git
elif command -v yum &> /dev/null; then
    yum install -y python3 python3-pip curl git
elif command -v dnf &> /dev/null; then
    dnf install -y python3 python3-pip curl git
else
    log_warn "Unknown package manager. Please install 'python3', 'pip3', and 'curl' manually."
fi

# Verify Python installation
if ! command -v python3 &> /dev/null; then
    log_error "python3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# Verify pip installation
if ! command -v pip3 &> /dev/null; then
    log_error "pip3 is not installed. Please install pip3."
    exit 1
fi

# Create installation directory
log_info "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mkdir -p /var/log/stake-move

# Determine the user who will run the service (prefer SUDO_USER, fallback to current user)
SERVICE_USER="${SUDO_USER:-$USER}"
if [ "$SERVICE_USER" = "root" ] || [ -z "$SERVICE_USER" ]; then
    # If running as root without sudo, try to find a non-root user
    SERVICE_USER=$(getent passwd | awk -F: '$3 >= 1000 && $1 != "nobody" {print $1; exit}')
    if [ -z "$SERVICE_USER" ]; then
        SERVICE_USER="root"
    fi
fi

# Set proper permissions for log directory (service user needs write access)
log_info "Setting permissions for log directory (user: $SERVICE_USER)..."
if chown -R "$SERVICE_USER:$SERVICE_USER" /var/log/stake-move 2>/dev/null; then
    chmod 755 /var/log/stake-move
    log_info "Log directory ownership set to $SERVICE_USER"
else
    # If chown fails (e.g., directory owned by root), make it writable by the user
    chmod 775 /var/log/stake-move
    # Try to use ACLs if available, otherwise the user will need sudo to write
    if command -v setfacl &>/dev/null; then
        setfacl -m "u:$SERVICE_USER:rwx" /var/log/stake-move 2>/dev/null && \
        setfacl -d -m "u:$SERVICE_USER:rwx" /var/log/stake-move 2>/dev/null && \
        log_info "Log directory ACLs set for $SERVICE_USER"
    else
        log_warn "Could not set ownership. You may need to manually fix permissions:"
        log_warn "  sudo chown -R $SERVICE_USER:$SERVICE_USER /var/log/stake-move"
    fi
fi

# Copy scripts to installation directory
log_info "Copying scripts to $INSTALL_DIR..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/daily_stake_move.py" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/daily_stake_move.py"

# Copy utils directory
if [ -d "$SCRIPT_DIR/utils" ]; then
    cp -r "$SCRIPT_DIR/utils" "$INSTALL_DIR/"
    log_info "Copied utils directory"
fi

# Copy requirements.txt
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
    log_info "Copied requirements.txt"
fi

# Install Python dependencies
log_info "Installing Python dependencies..."
if [ "$SERVICE_USER" != "root" ]; then
    USER_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6)
    PIP_CMD="pip3 install --user"
    PIP_TARGET="$USER_HOME/.local"
else
    PIP_CMD="pip3 install"
    PIP_TARGET="/usr/local"
fi

# Install requirements
if [ -f "$INSTALL_DIR/requirements.txt" ]; then
    log_info "Installing Python packages from requirements.txt..."
    if sudo -u "$SERVICE_USER" $PIP_CMD -r "$INSTALL_DIR/requirements.txt" 2>&1 | tee /tmp/pip_install.log; then
        log_info "Python dependencies installed successfully"
    else
        log_error "Failed to install Python dependencies. Check /tmp/pip_install.log for details."
        log_warn "You may need to install dependencies manually: $PIP_CMD -r $INSTALL_DIR/requirements.txt"
    fi
else
    log_warn "requirements.txt not found. Installing basic dependencies..."
    sudo -u "$SERVICE_USER" $PIP_CMD bittensor python-dotenv requests 2>&1 | tee /tmp/pip_install.log || log_warn "Some dependencies may have failed to install"
fi

# Copy systemd files
log_info "Installing systemd service and timer..."
cp "$SCRIPT_DIR/stake-move.service" /etc/systemd/system/
cp "$SCRIPT_DIR/stake-move.timer" /etc/systemd/system/

# SERVICE_USER should already be set from above
if [ -z "${SERVICE_USER:-}" ]; then
    SERVICE_USER="${SUDO_USER:-$USER}"
    if [ "$SERVICE_USER" = "root" ] || [ -z "$SERVICE_USER" ]; then
        SERVICE_USER=$(getent passwd | awk -F: '$3 >= 1000 && $1 != "nobody" {print $1; exit}')
        if [ -z "$SERVICE_USER" ]; then
            SERVICE_USER="root"
            log_warn "Could not determine non-root user, service will run as root"
        fi
    fi
fi

log_info "Service will run as user: $SERVICE_USER"

# Update service file with correct paths and user
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|" /etc/systemd/system/stake-move.service

# Determine Python path
if [ "$SERVICE_USER" != "root" ]; then
    USER_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6)
    PYTHON_CMD="$USER_HOME/.local/bin/python3"
    if [ ! -f "$PYTHON_CMD" ]; then
        # Fallback to system python3
        PYTHON_CMD="python3"
    fi
    UPDATED_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$USER_HOME/.local/bin"
else
    PYTHON_CMD="python3"
    UPDATED_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
fi

# Update ExecStart to use Python script
sed -i "s|ExecStart=.*|ExecStart=$PYTHON_CMD $INSTALL_DIR/daily_stake_move.py|" /etc/systemd/system/stake-move.service
sed -i "s|^User=.*|User=$SERVICE_USER|" /etc/systemd/system/stake-move.service

# Update PATH to include Python user install location
if [ -n "$USER_HOME" ] && [ "$SERVICE_USER" != "root" ]; then
    # Check if PATH line exists, if not add it
    if ! grep -q "^Environment=\"PATH=" /etc/systemd/system/stake-move.service; then
        sed -i "/^\[Service\]/a Environment=\"PATH=$UPDATED_PATH\"" /etc/systemd/system/stake-move.service
    else
        sed -i "s|^Environment=\"PATH=.*|Environment=\"PATH=$UPDATED_PATH\"|" /etc/systemd/system/stake-move.service
    fi
    log_info "Updated PATH in service file to include $USER_HOME/.local/bin"
fi

# Mask a secret for display (show first/last chars only)
mask_secret() {
    local secret="$1"
    local len=${#secret}
    if [ "$len" -le 4 ]; then
        echo "****"
    elif [ "$len" -le 16 ]; then
        echo "${secret:0:3}****${secret: -3}"
    else
        echo "${secret:0:5}****${secret: -5}"
    fi
}

# Read a single value from the current .env file (empty string if not found)
_get_env_val() {
    local key="$1"
    [ -f "$ENV_FILE" ] || { echo ""; return; }
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-
}

# Set up .env file
log_info ""
log_info "Setting up .env file..."

# Collect all inputs then write the file once.
# When .env already exists, existing values are shown as defaults so the user
# can press Enter to keep them or type a new value to override.
_collect_and_write_env() {
    local _existing_env=""
    [ -f "$ENV_FILE" ] && _existing_env="yes"

    if [ -n "$_existing_env" ]; then
        echo -e "${YELLOW}Existing values shown in [brackets] — press Enter to keep, or type to override.${NC}"
    fi

    local _cur _def _input

    # ---- Section 1: Wallet & Network (required) ----
    log_info ""
    log_info "=== Section 1: Wallet & Network (required) ==="

    _cur=$(_get_env_val WALLET_NAME)
    _def="${_cur:-}"
    read -p "Wallet name${_def:+ [${_def}]}: " _input
    _WALLET_NAME="${_input:-${_def}}"
    [ -z "$_WALLET_NAME" ] && { log_error "Wallet name is required."; return 1; }

    _cur=$(_get_env_val ORIGIN_NETUID)
    _def="${_cur:-}"
    read -p "Origin subnet UID${_def:+ [${_def}]}: " _input
    _ORIGIN_NETUID="${_input:-${_def}}"
    [ -z "$_ORIGIN_NETUID" ] && { log_error "Origin subnet UID is required."; return 1; }

    _cur=$(_get_env_val DEST_NETUID)
    _def="${_cur:-}"
    read -p "Destination subnet UID${_def:+ [${_def}]}: " _input
    _DEST_NETUID="${_input:-${_def}}"
    [ -z "$_DEST_NETUID" ] && { log_error "Destination subnet UID is required."; return 1; }

    _cur=$(_get_env_val ORIGIN_HOTKEY)
    _def="${_cur:-}"
    read -p "Origin hotkey (SS58)${_def:+ [${_def}]}: " _input
    _ORIGIN_HOTKEY="${_input:-${_def}}"
    [ -z "$_ORIGIN_HOTKEY" ] && { log_error "Origin hotkey is required."; return 1; }

    _cur=$(_get_env_val DEST_HOTKEY)
    _def="${_cur:-}"
    read -p "Destination hotkey (SS58)${_def:+ [${_def}]}: " _input
    _DEST_HOTKEY="${_input:-${_def}}"
    [ -z "$_DEST_HOTKEY" ] && { log_error "Destination hotkey is required."; return 1; }

    _cur=$(_get_env_val WALLET_PASSWORD)
    if [ -n "$_cur" ]; then
        read -sp "Wallet password [current: $(mask_secret "$_cur"), Enter to keep]: " _input; echo
        _WALLET_PASSWORD="${_input:-${_cur}}"
    else
        read -sp "Wallet password: " _WALLET_PASSWORD; echo
    fi
    [ -z "$_WALLET_PASSWORD" ] && { log_error "Wallet password is required."; return 1; }

    _cur=$(_get_env_val MINIMUM_STAKE_THRESHOLD)
    _def="${_cur:-0.001}"
    read -p "Minimum stake threshold α [${_def}]: " _input
    _MIN_STAKE="${_input:-${_def}}"

    # ---- Section 2: Telegram (optional) ----
    log_info ""
    log_info "=== Section 2: Telegram notifications (optional) ==="
    _TELEGRAM_BOT_TOKEN=$(_get_env_val TELEGRAM_BOT_TOKEN)
    _TELEGRAM_CHAT_ID=$(_get_env_val TELEGRAM_CHAT_ID)
    local _tg_hint=""
    [ -n "$_TELEGRAM_BOT_TOKEN" ] && _tg_hint=" (currently configured)"

    read -p "Configure Telegram notifications?${_tg_hint} (y/N): " -n 1 -r; echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        _cur=$(_get_env_val TELEGRAM_BOT_TOKEN)
        if [ -n "$_cur" ]; then
            read -sp "Bot token [current: $(mask_secret "$_cur"), Enter to keep]: " _input; echo
            _TELEGRAM_BOT_TOKEN="${_input:-${_cur}}"
        else
            read -sp "Bot token: " _TELEGRAM_BOT_TOKEN; echo
        fi

        _cur=$(_get_env_val TELEGRAM_CHAT_ID)
        _def="${_cur:-}"
        read -p "Chat ID${_def:+ [${_def}]}: " _input
        _TELEGRAM_CHAT_ID="${_input:-${_def}}"
        log_info "Telegram configured."
    fi

    # ---- Section 3: Google Sheets (optional) ----
    log_info ""
    log_info "=== Section 3: Google Sheets logging (optional) ==="
    _GOOGLE_SA_JSON=$(_get_env_val GOOGLE_SERVICE_ACCOUNT_JSON)
    _GOOGLE_SHEET_ID=$(_get_env_val GOOGLE_SHEET_ID)
    local _sheets_hint=""
    [ -n "$_GOOGLE_SHEET_ID" ] && _sheets_hint=" (currently configured)"

    read -p "Configure Google Sheets logging?${_sheets_hint} (y/N): " -n 1 -r; echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        _cur=$(_get_env_val GOOGLE_SERVICE_ACCOUNT_JSON)
        _def="${_cur:-}"
        read -p "Path to service-account JSON${_def:+ [${_def}]}: " _input
        _GOOGLE_SA_JSON="${_input:-${_def}}"

        _cur=$(_get_env_val GOOGLE_SHEET_ID)
        _def="${_cur:-}"
        read -p "Google Sheet ID${_def:+ [${_def}]}: " _input
        _GOOGLE_SHEET_ID="${_input:-${_def}}"
        log_info "Google Sheets configured."

        # ---- Section 4: Sheet Setup (optional, for setup_sheets.py) ----
        log_info ""
        log_info "=== Section 4: Sheet Setup (for setup_sheets.py — one-time) ==="
        local _setup_hint=""
        [ -n "$(_get_env_val PARTNER_COUNT)" ] && _setup_hint=" (currently configured)"
        read -p "Configure sheet setup variables?${_setup_hint} (y/N): " -n 1 -r; echo

        _SHEET_SETUP_CONFIGURED=""
        _PARTNERS=()
        _OPENING_BALANCE="" _OPENING_DATE="" _PARTNER_COUNT=""
        _FIRST_DIST_DATE="" _CYCLE_DAYS="" _ARCHIVE_TAB_NAMES=""

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            _cur=$(_get_env_val OPENING_BALANCE)
            _def="${_cur:-0.0}"
            read -p "Opening balance [${_def}]: " _input
            _OPENING_BALANCE="${_input:-${_def}}"

            _cur=$(_get_env_val OPENING_DATE)
            _def="${_cur:-$(date +%Y-%m-%d)}"
            read -p "Opening date (YYYY-MM-DD) [${_def}]: " _input
            _OPENING_DATE="${_input:-${_def}}"

            _cur=$(_get_env_val PARTNER_COUNT)
            _def="${_cur:-2}"
            read -p "Number of distribution partners [${_def}]: " _input
            _PARTNER_COUNT="${_input:-${_def}}"

            for i in $(seq 1 "$_PARTNER_COUNT"); do
                log_info "  --- Partner $i ---"
                _cur=$(_get_env_val "PARTNER_${i}_NAME")
                _def="${_cur:-Partner${i}}"
                read -p "    Name [${_def}]: " _input
                _p_name="${_input:-${_def}}"

                _cur=$(_get_env_val "PARTNER_${i}_SHARE")
                _def="${_cur:-}"
                read -p "    Share 0–1${_def:+ [${_def}]}: " _input
                _p_share="${_input:-${_def}}"

                _cur=$(_get_env_val "PARTNER_${i}_WALLET")
                _def="${_cur:-}"
                read -p "    Wallet SS58${_def:+ [${_def}]}: " _input
                _p_wallet="${_input:-${_def}}"

                _PARTNERS+=("${_p_name}|${_p_share}|${_p_wallet}")
            done

            _cur=$(_get_env_val FIRST_DIST_DATE)
            _def="${_cur:-$(date +%Y-%m-%d)}"
            read -p "First distribution date (YYYY-MM-DD) [${_def}]: " _input
            _FIRST_DIST_DATE="${_input:-${_def}}"

            _cur=$(_get_env_val CYCLE_DAYS)
            _def="${_cur:-14}"
            read -p "Distribution cycle days [${_def}]: " _input
            _CYCLE_DAYS="${_input:-${_def}}"

            _cur=$(_get_env_val ARCHIVE_TAB_NAMES)
            _def="${_cur:-}"
            read -p "Archive tab names (comma-separated, blank to skip)${_def:+ [${_def}]}: " _input
            _ARCHIVE_TAB_NAMES="${_input:-${_def}}"

            _SHEET_SETUP_CONFIGURED="yes"
        fi
    fi

    # ---- Write .env ----
    {
        cat <<ENVEOF
# =============================================================
# stake-move-automation — runtime configuration
# Generated by deploy.sh on $(date +%Y-%m-%d)
# =============================================================

# --- Wallet & Network (REQUIRED) ---
WALLET_NAME=$_WALLET_NAME
WALLET_PASSWORD=$_WALLET_PASSWORD
ORIGIN_NETUID=$_ORIGIN_NETUID
DEST_NETUID=$_DEST_NETUID
ORIGIN_HOTKEY=$_ORIGIN_HOTKEY
DEST_HOTKEY=$_DEST_HOTKEY

# Minimum stake (α) to sweep — runs below this are skipped
MINIMUM_STAKE_THRESHOLD=$_MIN_STAKE

# --- Telegram (optional) ---
TELEGRAM_BOT_TOKEN=$_TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$_TELEGRAM_CHAT_ID

# --- Google Sheets (optional) ---
GOOGLE_SERVICE_ACCOUNT_JSON=$_GOOGLE_SA_JSON
GOOGLE_SHEET_ID=$_GOOGLE_SHEET_ID

ENVEOF

        if [ "${_SHEET_SETUP_CONFIGURED:-}" = "yes" ]; then
            printf '# --- Sheet Setup (for setup_sheets.py) ---\n'
            printf 'OPENING_BALANCE=%s\n' "$_OPENING_BALANCE"
            printf 'OPENING_DATE=%s\n'    "$_OPENING_DATE"
            printf 'PARTNER_COUNT=%s\n'   "$_PARTNER_COUNT"
            local _n=1
            for _entry in "${_PARTNERS[@]}"; do
                IFS='|' read -r _pn _ps _pw <<< "$_entry"
                printf 'PARTNER_%s_NAME=%s\n'   "$_n" "$_pn"
                printf 'PARTNER_%s_SHARE=%s\n'  "$_n" "$_ps"
                printf 'PARTNER_%s_WALLET=%s\n' "$_n" "$_pw"
                (( _n++ )) || true
            done
            printf 'FIRST_DIST_DATE=%s\n'    "$_FIRST_DIST_DATE"
            printf 'CYCLE_DAYS=%s\n'         "$_CYCLE_DAYS"
            printf 'ARCHIVE_TAB_NAMES=%s\n'  "$_ARCHIVE_TAB_NAMES"
        else
            cat <<SETUPEOF
# --- Sheet Setup (fill in before running setup_sheets.py) ---
# OPENING_BALANCE=0.0
# OPENING_DATE=$(date +%Y-%m-%d)
# PARTNER_COUNT=2
# PARTNER_1_NAME=Alice
# PARTNER_1_SHARE=0.5
# PARTNER_1_WALLET=5...
# PARTNER_2_NAME=Bob
# PARTNER_2_SHARE=0.5
# PARTNER_2_WALLET=5...
# FIRST_DIST_DATE=$(date +%Y-%m-%d)
# CYCLE_DAYS=14
# ARCHIVE_TAB_NAMES=
SETUPEOF
        fi
    } > "$ENV_FILE"
}

if [ -f "$ENV_FILE" ]; then
    log_info ".env already exists at $ENV_FILE"
    log_info "Re-prompting all values — press Enter on any line to keep the current value."
    cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    _collect_and_write_env || exit 1
    log_info ".env file updated"
else
    log_info "Creating .env file at $ENV_FILE"
    _collect_and_write_env || exit 1
    log_info ".env file created successfully"
fi

# Set proper permissions on .env file (always ensure correct ownership)
if [ -f "$ENV_FILE" ]; then
    log_info "Setting permissions on .env file..."
    chmod 600 "$ENV_FILE"
    chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
    log_info "✓ .env file permissions set to 600 ($SERVICE_USER:$SERVICE_USER)"
else
    log_error ".env file not found at $ENV_FILE"
    exit 1
fi

log_info ""
log_info "To update the .env file later, edit it directly:"
log_info "  sudo nano $ENV_FILE"

# Reload systemd
log_info "Reloading systemd daemon..."
systemctl daemon-reload

# Enable and start timer
log_info "Enabling and starting stake-move timer..."
systemctl enable stake-move.timer
systemctl start stake-move.timer

# Check timer status
log_info "Checking timer status..."
systemctl status stake-move.timer --no-pager || true

# Show next run time
NEXT_RUN=$(systemctl list-timers stake-move.timer --no-pager | grep stake-move.timer | awk '{print $1, $2, $3, $4, $5}' || echo "Unable to determine")
log_info "Next scheduled run: $NEXT_RUN"

# Test run option
log_info ""
log_info "You can test the automation now, or wait for the scheduled run at 8AM PST."
read -p "Do you want to run a test execution now? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_info "Running test execution..."
    log_info "This will perform an actual stake move operation!"
    systemctl start stake-move.service
    
    # Wait a bit for the service to start
    sleep 3
    
    # Show recent logs
    log_info "Recent service logs:"
    journalctl -u stake-move.service -n 50 --no-pager || true
    
    log_info ""
    log_info "To follow the logs in real-time, run:"
    log_info "  journalctl -u stake-move.service -f"
    log_info ""
    log_info "To view the daily log file:"
    log_info "  tail -f /var/log/stake-move/\$(date +%Y-%m-%d).log"
else
    log_info "Skipping test run. The automation will run automatically at 8AM PST daily."
    log_info "To manually trigger a test run later, use:"
    log_info "  sudo systemctl start stake-move.service"
fi

log_info "=========================================="
log_info "Deployment completed successfully!"
log_info "=========================================="
log_info "Installation directory: $INSTALL_DIR"
log_info "Log directory: /var/log/stake-move"
log_info ""
log_info "Useful commands:"
log_info "  Check timer status: systemctl status stake-move.timer"
log_info "  Check service logs: journalctl -u stake-move.service -f"
log_info "  View daily logs: tail -f /var/log/stake-move/\$(date +%Y-%m-%d).log"
log_info "  View summary: tail -f /var/log/stake-move/summary.log"
log_info "  Manual run: systemctl start stake-move.service"
log_info ""

