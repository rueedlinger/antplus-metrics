#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

LOG_FILE="/var/log/amwa_install.log"

log() {
    echo -e "$1" | tee -a "$LOG_FILE"
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
log "write files to /etc/systemd/system."
log ""
log "NO WARRANTY is provided. Use at your own risk."
log ""

read -r -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    log "Aborted."
    exit 1
fi

# -----------------------
# CHECK SUDO
# -----------------------
if [[ $EUID -ne 0 ]]; then
    log "Error: This script must be run with sudo."
    log "Example: sudo ./install.sh"
    exit 1
fi

CURRENT_USER=${SUDO_USER:-$(whoami)}
log "Running commands as user: $CURRENT_USER"

run_as_user() {
    sudo -u "$CURRENT_USER" bash -c "$1"
}

# -----------------------
# CONFIGURATION
# -----------------------
REPO_DIR="amwa"
REPO_URL="https://github.com/rueedlinger/${REPO_DIR}"
VENV_DIR=".setup"
FRONTEND_DIR="frontend"
SERVICE_FILE="/etc/systemd/system/amwa.service"

USER_HOME=$(eval echo "~$CURRENT_USER")
REPO_PATH="${USER_HOME}/${REPO_DIR}"

# -----------------------
# STEP 0: Clone repository
# -----------------------
log ""
log "=== Step 0: Cloning repository ==="
if [ ! -d "$REPO_PATH" ]; then
    run_as_user "git clone $REPO_URL $REPO_PATH"
else
    run_as_user "git -C $REPO_PATH pull"
fi

chown -R "$CURRENT_USER":"$CURRENT_USER" "$REPO_PATH"

# -----------------------
# STEP 1: Check dependencies
# -----------------------
log ""
log "=== Step 1: Checking dependencies ==="
dependencies=(python3 python3-venv node npm git)

for cmd in "${dependencies[@]}"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log "Error: $cmd is not installed."
        exit 1
    fi
done

# Optional version checks
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
# STEP 2: Setup Python environment
# -----------------------
log ""
log "=== Step 2: Setting up Python virtual environment ==="
run_as_user "
cd $REPO_PATH
if [ ! -d '$VENV_DIR' ]; then
    python3 -m venv $VENV_DIR
fi
source $VENV_DIR/bin/activate
pip install --upgrade pip
pip install uv
"

# -----------------------
# STEP 3: Build backend
# -----------------------
log ""
log "=== Step 3: Building backend ==="
run_as_user "
cd $REPO_PATH
source $VENV_DIR/bin/activate
uv sync --all-groups
"

# -----------------------
# STEP 4: Build frontend
# -----------------------
log ""
log "=== Step 4: Building frontend ==="
if run_as_user "[ -d '$REPO_PATH/$FRONTEND_DIR' ]"; then
    run_as_user "
cd $REPO_PATH
npm ci --include=dev --prefix $FRONTEND_DIR
npm run build --prefix $FRONTEND_DIR
"
else
    log "Warning: Frontend directory '$FRONTEND_DIR' does not exist."
    exit 1
fi

# -----------------------
# STEP 5: Copy frontend build
# -----------------------
log ""
log "=== Step 5: Copying frontend build ==="
run_as_user "
cd $REPO_PATH
mkdir -p app/dist
cp -r $FRONTEND_DIR/dist/. app/dist/
"

# -----------------------
# STEP 6: Optional ANT+ USB setup
# -----------------------
log ""
log "=== Step 6: Optional ANT+ USB adapter setup ==="
read -r -p "Do you want to configure the ANT+ USB adapter? [yes/no]: " ANTUSB_CHOICE

if [[ "$ANTUSB_CHOICE" == "yes" ]]; then
    usermod -aG plugdev "$CURRENT_USER"
    log "Added $CURRENT_USER to plugdev group. Log out and back in if necessary."

    lsusb

    read -r -p "Enter the idVendor (e.g., 0fcf): " ID_VENDOR
    read -r -p "Enter the idProduct (e.g., 1008): " ID_PRODUCT

    log "Using Vendor ID: $ID_VENDOR"
    log "Using Product ID: $ID_PRODUCT"

    UDEV_RULE_DEST="/etc/udev/rules.d/99-antusb.rules"
    if [ -f "$UDEV_RULE_DEST" ]; then
        log "Udev rule already exists at $UDEV_RULE_DEST, skipping creation."
    else
        cat <<EOF > "$UDEV_RULE_DEST"
SUBSYSTEM=="usb", ATTR{idVendor}=="$ID_VENDOR", ATTR{idProduct}=="$ID_PRODUCT", GROUP="plugdev", MODE="0660"
EOF
        udevadm control --reload-rules
        udevadm trigger
        log "ANT+ USB udev rule applied successfully."
    fi

    read -r -p "Please unplug and replug your ANT+ USB stick, then press Enter..."
else
    log "Skipping ANT+ USB adapter setup."
fi

# -----------------------
# STEP 7: Install systemd service
# -----------------------
log ""
log "=== Step 7: Optional systemd service installation ==="
read -r -p "Do you want to install and start the AMWA systemd service? [yes/no]: " INSTALL_SERVICE_CHOICE

if [[ "$INSTALL_SERVICE_CHOICE" == "yes" ]]; then

    SERVICE_SRC="${REPO_PATH}/scripts/amwa.service"

    if [ ! -f "$SERVICE_SRC" ]; then
        log "Service file not found: $SERVICE_SRC"
        exit 1
    fi

    if [ -f "$SERVICE_FILE" ]; then
        log "Warning: Service file already exists. Backing up..."
        cp "$SERVICE_FILE" "${SERVICE_FILE}.bak"
    fi

    cp "$SERVICE_SRC" "$SERVICE_FILE"

    sed -i "s|ExecStart=.*|ExecStart=${REPO_PATH}/scripts/start.sh|" "$SERVICE_FILE"
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" "$SERVICE_FILE"
    sed -i "s|User=.*|User=${CURRENT_USER}|" "$SERVICE_FILE"

    systemctl daemon-reload
    systemctl enable amwa
    systemctl start amwa

    log ""
    log "=== Step 8: Service status ==="
    systemctl status amwa --no-pager
else
    log "Skipping systemd service installation."
fi

log ""
log "=== Installation finished successfully ==="
log "Detailed logs are available at $LOG_FILE"