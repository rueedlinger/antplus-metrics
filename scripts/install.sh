#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

LOG_FILE="$(eval echo "~$SUDO_USER")/amwa_install.log"

# Truncate log at start
> "$LOG_FILE"

# -----------------------
# HELPERS
# -----------------------
run_as_user() {
    log ">>> Running as $CURRENT_USER: $*"
    sudo -u "$CURRENT_USER" bash -c "$*" 2>&1 | tee -a "$LOG_FILE"
}

run_in_repo() {
    run_as_user "cd \"$REPO_PATH\" && $*"
}

log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

log_cmd() {
    log ">>> $*"
    "$@" 2>&1 | tee -a "$LOG_FILE"
}

# -----------------------
# DISCLAIMER
# -----------------------
log "======================================"
log " AMWA Installer"
log "======================================"
log ""
log "DISCLAIMER:"
log "This script will install and configure the AMWA service"
log "on your system. It will modify systemd services and"
log "write system files."
log ""
log "NO WARRANTY is provided. Use at your own risk."
log ""

# -----------------------
# CHECK SUDO
# -----------------------
if [[ $EUID -ne 0 ]]; then
    log "Error: This script must be run with sudo."
    log "Example: sudo ./install.sh"
    exit 1
fi

read -r -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    log "Aborted."
    exit 1
fi

CURRENT_USER=${SUDO_USER:-$(whoami)}
log "Running commands as user: $CURRENT_USER"



# -----------------------
# CONFIGURATION
# -----------------------
USER_HOME=$(eval echo "~$CURRENT_USER")
SETUP_VENV_DIR="${USER_HOME}/.setup"

REPO_DIR="amwa"
REPO_URL="https://github.com/rueedlinger/${REPO_DIR}"

FRONTEND_DIR="frontend"
SERVICE_FILE="/etc/systemd/system/amwa.service"
REPO_PATH="${USER_HOME}/${REPO_DIR}"

TEMPLATE_DIR="${REPO_PATH}/templates"
ANTUSB_TEMPLATE="${TEMPLATE_DIR}/99-antusb.rules.template"
SERVICE_TEMPLATE="${TEMPLATE_DIR}/amwa.service.template"
NGINX_TEMPLATE="${TEMPLATE_DIR}/nginx.conf.template"

# -----------------------
# STEP 1: Optional system update and install dependencies
# -----------------------
log ""
log "=== STEP 1: Update system and install required software ==="

read -r -p "Do you want to update the system and install required software (nodejs, npm, git, python3, python3-pip, python3-venv, vim, nginx)? [yes/no]: " INSTALL_SOFTWARE

if [[ "$INSTALL_SOFTWARE" == "yes" ]]; then
    log "Updating package lists..."
    log_cmd apt-get update -y

    log "Installing required software..."
    log_cmd apt-get install -y nodejs npm git python3 python3-pip python3-venv vim nginx

    log "System update and software installation complete."
else
    log "Skipping system update and software installation."
fi

# -----------------------
# STEP 2: Clone repository
# -----------------------
log ""
log "=== STEP 2: Cloning repository ==="

if [ ! -d "$REPO_PATH" ]; then
    run_as_user "git clone \"$REPO_URL\" \"$REPO_PATH\""
else
    run_as_user "git -C \"$REPO_PATH\" pull"
fi

chown -R "$CURRENT_USER":"$CURRENT_USER" "$REPO_PATH"

# -----------------------
# STEP 3: Check dependencies
# -----------------------
log ""
log "=== STEP 3: Checking dependencies ==="

dependencies=(python3 node npm git)

for cmd in "${dependencies[@]}"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log "Error: $cmd is not installed."
        exit 1
    fi
done

if ! python3 -m venv --help >/dev/null 2>&1; then
    log "Error: python3-venv package is not installed."
    log "Install it with: sudo apt install python3-venv"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d. -f1)
NPM_VERSION=$(npm -v | cut -d. -f1)

if (( NODE_VERSION < 16 )); then
    log "Warning: Node.js version >=16 recommended."
fi
if (( NPM_VERSION < 8 )); then
    log "Warning: npm version >=8 recommended."
fi

log "Python version: $(python3 --version)"
log "Node version: $(node -v)"
log "npm version: $(npm -v)"
log "Git version: $(git --version)"

# -----------------------
# STEP 4: Setup Python environment
# -----------------------
log ""
log "=== STEP 4: Setting up Python virtual environment ==="

run_in_repo <<'EOF'
if [ ! -d "$SETUP_VENV_DIR" ]; then
    python3 -m venv "$SETUP_VENV_DIR"
fi
source "$SETUP_VENV_DIR/bin/activate"
pip install --upgrade pip
pip install uv
EOF

# -----------------------
# STEP 5: Build backend
# -----------------------
log ""
log "=== STEP 5: Building backend ==="

run_in_repo <<'EOF'
source "$SETUP_VENV_DIR/bin/activate"
uv sync --all-groups --active
EOF

# -----------------------
# STEP 6: Build frontend
# -----------------------
log ""
log "=== STEP 6: Building frontend ==="

if run_as_user "[ -d '$REPO_PATH/$FRONTEND_DIR' ]"; then
    run_in_repo <<EOF
npm ci --include=dev --prefix "$FRONTEND_DIR"
npm run build --prefix "$FRONTEND_DIR"
EOF
else
    log "Warning: Frontend directory '$FRONTEND_DIR' does not exist."
    exit 1
fi

# -----------------------
# STEP 7: Deploy frontend to web root
# -----------------------
log ""
log "=== STEP 7: Deploy frontend to /var/www/html ==="

FRONTEND_BUILD_DIR="${REPO_PATH}/${FRONTEND_DIR}/dist"
WEB_ROOT="/var/www/html"

if [ -d "$FRONTEND_BUILD_DIR" ]; then
    log "Cleaning existing files in $WEB_ROOT..."
    rm -rf "${WEB_ROOT:?}/"*

    log "Copying new frontend build to $WEB_ROOT..."
    cp -r "$FRONTEND_BUILD_DIR"/* "$WEB_ROOT"/

    chown -R www-data:www-data "$WEB_ROOT"
    log "Frontend deployed successfully."
else
    log "Error: Frontend build directory '$FRONTEND_BUILD_DIR' not found."
    exit 1
fi

# -----------------------
# STEP 8: Optional Nginx configuration
# -----------------------
log ""
log "=== STEP 8: Optional Nginx configuration ==="

read -r -p "Configure Nginx for AMWA frontend? [yes/no]: " CONFIGURE_NGINX
if [[ "$CONFIGURE_NGINX" == "yes" ]]; then
    if ! command -v nginx >/dev/null 2>&1; then
        log "Error: nginx not installed."
        exit 1
    fi

    NGINX_DEST="/etc/nginx/sites-available/default"

    if [ ! -f "$NGINX_TEMPLATE" ]; then
        log "Error: Nginx template not found: $NGINX_TEMPLATE"
        exit 1
    fi

    if [ ! -f "${NGINX_DEST}.bak" ]; then
        log "Backing up existing Nginx config..."
        cp "$NGINX_DEST" "${NGINX_DEST}.bak"
    fi

    sed "s|WWW_ROOT|$WEB_ROOT|g" "$NGINX_TEMPLATE" > "$NGINX_DEST"

    log "Testing nginx configuration..."
    if nginx -t 2>&1 | tee -a "$LOG_FILE"; then
        log "Reloading nginx..."
        systemctl reload nginx | tee -a "$LOG_FILE"
        log "Nginx configured successfully."
    else
        log "Error: nginx config test failed."
        exit 1
    fi
else
    log "Skipping Nginx configuration."
fi

# -----------------------
# STEP 9: Optional ANT+ USB setup
# -----------------------
log ""
log "=== STEP 9: Optional ANT+ USB adapter setup ==="

read -r -p "Configure ANT+ USB adapter? [yes/no]: " ANTUSB_CHOICE
if [[ "$ANTUSB_CHOICE" == "yes" ]]; then
    if [ ! -f "$ANTUSB_TEMPLATE" ]; then
        log "Error: ANT+ udev template not found: $ANTUSB_TEMPLATE"
        exit 1
    fi

    log "Adding $CURRENT_USER to plugdev group..."
    usermod -aG plugdev "$CURRENT_USER"

    log "Listing USB devices..."
    lsusb | tee -a "$LOG_FILE"

    read -r -p "Enter idVendor (e.g., 0fcf): " ID_VENDOR
    read -r -p "Enter idProduct (e.g., 1008): " ID_PRODUCT

    log "Creating udev rule..."
    UDEV_RULE_DEST="/etc/udev/rules.d/99-antusb.rules"
    sed -e "s|VENDOR_ID|$ID_VENDOR|g" -e "s|PRODUCT_ID|$ID_PRODUCT|g" "$ANTUSB_TEMPLATE" > "$UDEV_RULE_DEST"

    udevadm control --reload-rules
    udevadm trigger
    log "ANT+ USB udev rule applied successfully."

    read -r -p "Please unplug and replug your ANT+ USB stick, then press Enter..."
else
    log "Skipping ANT+ USB adapter setup."
fi

# -----------------------
# STEP 10: Install systemd service
# -----------------------
log ""
log "=== STEP 10: Install systemd service ==="

read -r -p "Install AMWA service? [yes/no]: " INSTALL_SERVICE
if [[ "$INSTALL_SERVICE" == "yes" ]]; then
    if [ ! -f "$SERVICE_TEMPLATE" ]; then
        log "Error: Service template not found: $SERVICE_TEMPLATE"
        exit 1
    fi

    if [ -f "$SERVICE_FILE" ]; then
        log "Backing up existing service..."
        cp "$SERVICE_FILE" "${SERVICE_FILE}.bak"
    fi

    cp "$SERVICE_TEMPLATE" "$SERVICE_FILE"

    sed -i "s|USER|${CURRENT_USER}|g" "$SERVICE_FILE"
    sed -i "s|REPO_DIR|${REPO_PATH}|g" "$SERVICE_FILE"

    log "Reloading systemd and starting service..."
    systemctl daemon-reload | tee -a "$LOG_FILE"
    systemctl enable amwa | tee -a "$LOG_FILE"
    systemctl restart amwa | tee -a "$LOG_FILE"

    systemctl status amwa --no-pager | tee -a "$LOG_FILE"
fi

log ""
log "=== Installation finished successfully ==="
log "Detailed logs are available at $LOG_FILE"