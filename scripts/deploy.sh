#!/usr/bin/env bash
# Deploy gniza: commit, push, sync to local install, restart web service
set -e

cd "$(dirname "$0")/.."

# Run tests before deploy
if command -v python3 &>/dev/null && python3 -m pytest --version &>/dev/null 2>&1; then
    echo "Running tests..."
    python3 -m pytest tests/ -q || { echo "Tests failed! Aborting deploy."; exit 1; }
fi

# Commit and push
if [[ -n "$(git status --porcelain)" ]]; then
    git add bin/ lib/ tui/ web/ daemon/ etc/ scripts/ rpm/ debian/ tests/ .gitea/ pyproject.toml README.md DOCUMENTATION.md .gitignore
    msg="${1:-Deploy update}"
    git commit -m "$msg"
fi
git push

# Sync to local install
INSTALL_DIR="${HOME}/.local/share/gniza"
if [[ -d "$INSTALL_DIR" ]]; then
    cp bin/gniza "$INSTALL_DIR/bin/gniza"
    cp -r lib/* "$INSTALL_DIR/lib/"
    cp -r tui/* "$INSTALL_DIR/tui/"
    mkdir -p "$INSTALL_DIR/web" "$INSTALL_DIR/etc"
    cp -r web/* "$INSTALL_DIR/web/"
    cp -r etc/* "$INSTALL_DIR/etc/"
    mkdir -p "$INSTALL_DIR/scripts"
    cp -r scripts/* "$INSTALL_DIR/scripts/"
    # Sync user service files if systemd user dir exists
    if [[ -d "${HOME}/.config/systemd/user" ]]; then
        sed -e "s|/usr/local/gniza|${INSTALL_DIR}|g" \
            -e "s|WantedBy=multi-user.target|WantedBy=default.target|" \
            etc/gniza-web.service > "${HOME}/.config/systemd/user/gniza-web.service"
        systemctl --user daemon-reload 2>/dev/null || true
    fi
    # Sync daemon files
    mkdir -p "$INSTALL_DIR/daemon"
    cp -r daemon/* "$INSTALL_DIR/daemon/"
    echo "Synced to $INSTALL_DIR"
fi

# Restart services
if systemctl --user is-active gniza-web.service &>/dev/null; then
    systemctl --user restart gniza-web.service
    echo "Web service restarted"
fi
if systemctl --user is-active gniza-daemon.service &>/dev/null; then
    systemctl --user restart gniza-daemon.service
    echo "Daemon restarted"
fi

# Post-deploy smoke test
sleep 2
if systemctl --user is-active gniza-web.service &>/dev/null; then
    if curl -sf -o /dev/null http://127.0.0.1:2323/login 2>/dev/null; then
        echo "Web service health check: OK"
    else
        echo "WARNING: Web service is running but not responding on port 2323"
    fi
fi

# Build and publish .deb package
DEB_REPO_HOST="deb.gniza.app"
DEB_REPO_PATH="/var/www/deb.gniza.app"
DEB_DISTROS="stable bookworm trixie noble jammy"

if bash scripts/build-deb.sh; then
    VERSION="$(grep -oP 'GNIZA4LINUX_VERSION="\K[^"]+' lib/constants.sh)"
    DEB_FILE="dist/gniza_${VERSION}_all.deb"
    if [[ -f "$DEB_FILE" ]]; then
        echo "Uploading .deb to ${DEB_REPO_HOST}..."
        scp "$DEB_FILE" "root@${DEB_REPO_HOST}:/tmp/gniza_${VERSION}_all.deb"
        for distro in $DEB_DISTROS; do
            ssh "root@${DEB_REPO_HOST}" "reprepro -b ${DEB_REPO_PATH} includedeb ${distro} /tmp/gniza_${VERSION}_all.deb" 2>&1 || true
        done
        ssh "root@${DEB_REPO_HOST}" "rm -f /tmp/gniza_${VERSION}_all.deb"
        echo "Published gniza ${VERSION} to deb repo (${DEB_DISTROS})"
    fi
else
    echo "WARNING: .deb build failed, skipping repo publish"
fi

# Build and publish .rpm package
RPM_REPO_HOST="deb.gniza.app"  # same server
RPM_REPO_PATH="/var/www/rpm.gniza.app"

if command -v rpmbuild &>/dev/null; then
    if bash scripts/build-rpm.sh; then
        RPM_FILE=$(find dist -name "gniza-${VERSION}*.rpm" | head -1)
        if [[ -n "$RPM_FILE" && -f "$RPM_FILE" ]]; then
            echo "Uploading .rpm to ${RPM_REPO_HOST}..."
            scp "$RPM_FILE" "root@${RPM_REPO_HOST}:/tmp/"
            ssh "root@${RPM_REPO_HOST}" "mkdir -p ${RPM_REPO_PATH}/packages && cp /tmp/$(basename "$RPM_FILE") ${RPM_REPO_PATH}/packages/ && cd ${RPM_REPO_PATH} && createrepo_c . 2>/dev/null || createrepo . && rm -f /tmp/$(basename "$RPM_FILE")"
            echo "Published RPM to repo"
        fi
    else
        echo "WARNING: .rpm build failed, skipping repo publish"
    fi
fi

echo "Done"
