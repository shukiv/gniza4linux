#!/usr/bin/env bash
# Deploy gniza: commit, push, sync to local install, restart web service
set -e

cd "$(dirname "$0")/.."

# Commit and push
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
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
    echo "Synced to $INSTALL_DIR"
fi

# Restart web service
if systemctl --user is-active gniza-web.service &>/dev/null; then
    systemctl --user restart gniza-web.service
    echo "Web service restarted"
fi

echo "Done"
