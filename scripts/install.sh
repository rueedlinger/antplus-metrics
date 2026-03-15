#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

LOG_FILE="$(eval echo "~$SUDO_USER")/amwa_install.log"

# Truncate the log at the start of the script
> "$LOG_FILE"

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

run_as_user() {
    sudo -u "$CURRENT_USER" bash -c "$1"
}

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

# -----------------------
# STEP 1: Optional system update and install dependencies
# -----------------------
log ""
log "=== STEP 1: Update system and install required software ==="

read -r -p "Do you want to update the system and install required software (nodejs, npm, git, python3, python3-pip, python3-venv, vim, nginx)? [yes/no]: " INSTALL_SOFTWARE

if [[ "$INSTALL_SOFTWARE" == "yes" ]]; then
    log "Updating package lists..."
    apt-get update -y | tee -a "$LOG_FILE"

    log "Installing required software..."
    apt-get install -y nodejs npm git python3 python3-pip python3-venv vim nginx | tee -a "$LOG_FILE"

    log "System update and software installation complete."
else
    log "Skipping system update and software installation."
fi

# -----------------------
# STEP 2: Clone repository
# -----------------------
log ""
log "=== Step 2: Cloning repository ==="
if [ ! -d "$REPO_PATH" ]; then
    run_as_user "git clone $REPO_URL $REPO_PATH"
else
    run_as_user "git -C $REPO_PATH pull"
fi

chown -R "$CURRENT_USER":"$CURRENT_USER" "$REPO_PATH"

# -----------------------
# STEP 3: Check dependencies
# -----------------------
log ""
log "=== Step 3: Checking dependencies ==="
dependencies=(python3 node npm git)

for cmd in "${dependencies[@]}"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log "Error: $cmd is not installed."
        exit 1
    fi
done

# Check python3-venv package
if ! python3 -m venv --help >/dev/null 2>&1; then
    log "Error: python3-venv package is not installed."
    log "Install it with: sudo apt install python3-venv"
    exit 1
fi

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
# STEP 4: Setup Python environment
# -----------------------
log ""
log "=== Step 4: Setting up Python virtual environment ==="
run_as_user "
cd $REPO_PATH
if [ ! -d '$SETUP_VENV_DIR' ]; then
    python3 -m venv $SETUP_VENV_DIR
fi
source $SETUP_VENV_DIR/bin/activate
pip install --upgrade pip
pip install uv
"

# -----------------------
# STEP 5: Build backend
# -----------------------
log ""
log "=== Step 5: Building backend ==="
run_as_user "
cd $REPO_PATH
source $SETUP_VENV_DIR/bin/activate
uv sync --all-groups --active
"

# -----------------------
# STEP 6: Build frontend
# -----------------------
log ""
log "=== Step 6: Building frontend ==="
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
# STEP 7: Deploy frontend to web root
# -----------------------
log ""
log "=== Step 7: Copying frontend build to /var/www/html ==="

FRONTEND_BUILD_DIR="${REPO_PATH}/${FRONTEND_DIR}/dist"
WEB_ROOT="/var/www/html"

if [ -d "$FRONTEND_BUILD_DIR" ]; then
    log "Cleaning existing files in $WEB_ROOT..."
    rm -rf "${WEB_ROOT:?}/"*   # The :? prevents accidental deletion if variable is empty

    log "Copying new frontend build to $WEB_ROOT..."
    cp -r "$FRONTEND_BUILD_DIR"/* "$WEB_ROOT"/

    chown -R www-data:www-data "$WEB_ROOT"
    log "Frontend deployed to $WEB_ROOT successfully."
else
    log "Error: Frontend build directory '$FRONTEND_BUILD_DIR' not found."
    exit 1
fi

# -----------------------
# STEP 8: Optional Nginx configuration
# -----------------------
log ""
log "=== Step 8: Optional Nginx configuration ==="

read -r -p "Do you want to configure Nginx for the AMWA frontend? [yes/no]: " CONFIGURE_NGINX
if [[ "$CONFIGURE_NGINX" != "yes" ]]; then
    log "Skipping Nginx configuration."
else

    # Check if nginx exists
    if ! command -v nginx >/dev/null 2>&1; then
        log "Error: nginx is not installed. Please install nginx first."
        exit 1
    fi

    NGINX_SRC="${REPO_PATH}/scripts/nginx.conf"
    NGINX_DEST="/etc/nginx/sites-available/default"

    # Ensure nginx config exists in repo
    if [ ! -f "$NGINX_SRC" ]; then
        log "Error: nginx config not found at $NGINX_SRC"
        exit 1
    fi

    # Backup existing nginx config if not already backed up
    if [ ! -f "${NGINX_DEST}.bak" ]; then
        log "Backing up existing nginx config..."
        cp "$NGINX_DEST" "${NGINX_DEST}.bak"
    else
        log "Backup already exists at ${NGINX_DEST}.bak"
    fi

    # Copy new config from repo
    log "Copying nginx config from repository..."
    cp "$NGINX_SRC" "$NGINX_DEST"

    # Always set root to the frontend web root
    log "Setting Nginx root to $WEB_ROOT in server block(s)..."
    awk -v root="$WEB_ROOT" '
        $1 == "server" {in_server=1}
        in_server && $1 == "}" {in_server=0}
        in_server && $1 == "root" {$2=root";"}
        {print}
    ' "$NGINX_DEST" > "${NGINX_DEST}.tmp" && mv "${NGINX_DEST}.tmp" "$NGINX_DEST"

    # Test nginx config
    log "Testing nginx configuration..."
    if nginx -t 2>&1 | tee -a "$LOG_FILE"; then
        log "Reloading nginx..."
        systemctl reload nginx
        log "Nginx configuration complete."
    else
        log "Error: nginx configuration test failed. Check ${NGINX_DEST}."
        exit 1
    fi

fi

# -----------------------
# STEP 9: Optional ANT+ USB setup
# -----------------------
log ""
log "=== Step 9: Optional ANT+ USB adapter setup ==="
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
# STEP 10: Install systemd service
# -----------------------
log ""
log "=== STEP 10: Install systemd service ==="

read -r -p "Install AMWA service? [yes/no]: " INSTALL_SERVICE

if [[ "$INSTALL_SERVICE" == "yes" ]]; then

    SERVICE_SRC="${REPO_PATH}/scripts/amwa.service"

    if [ ! -f "$SERVICE_SRC" ]; then
        log "Service file not found: $SERVICE_SRC"
        exit 1
    fi

    if [ -f "$SERVICE_FILE" ]; then
        log "Backing up existing service..."
        cp "$SERVICE_FILE" "${SERVICE_FILE}.bak"
    fi

    cp "$SERVICE_SRC" "$SERVICE_FILE"

    # Replace placeholders in the systemd service file
    sed -i "s|USER|${CURRENT_USER}|g" "$SERVICE_FILE"
    sed -i "s|REPO_DIR|${REPO_PATH}|g" "$SERVICE_FILE"

    systemctl daemon-reload
    systemctl enable amwa
    systemctl restart amwa

    systemctl status amwa --no-pager

fi

log ""
log "=== Installation finished successfully ==="
log "Detailed logs are available at $LOG_FILE"