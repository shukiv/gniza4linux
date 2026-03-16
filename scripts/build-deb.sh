#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Extract version from lib/constants.sh
VERSION="$(grep -oP 'GNIZA4LINUX_VERSION="\K[^"]+' "$REPO_DIR/lib/constants.sh")"
if [ -z "$VERSION" ]; then
    echo "ERROR: Could not extract version from lib/constants.sh" >&2
    exit 1
fi

echo "Building gniza ${VERSION} .deb package..."

# Create staging directory
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

# Create DEBIAN directory
mkdir -p "$staging/DEBIAN"
sed "s|{{VERSION}}|$VERSION|" "$REPO_DIR/debian/control" > "$staging/DEBIAN/control"
cp "$REPO_DIR/debian/postinst" "$staging/DEBIAN/postinst"
cp "$REPO_DIR/debian/prerm"    "$staging/DEBIAN/prerm"
cp "$REPO_DIR/debian/postrm"   "$staging/DEBIAN/postrm"
chmod 755 "$staging/DEBIAN/postinst" "$staging/DEBIAN/prerm" "$staging/DEBIAN/postrm"

# Create application directory
mkdir -p "$staging/usr/local/gniza"

# Copy application directories
for dir in bin lib tui web daemon etc scripts data; do
    if [ -d "$REPO_DIR/$dir" ]; then
        cp -a "$REPO_DIR/$dir" "$staging/usr/local/gniza/"
    fi
done

# Copy LICENSE
if [ -f "$REPO_DIR/LICENSE" ]; then
    cp "$REPO_DIR/LICENSE" "$staging/usr/local/gniza/"
fi

# Create symlink: /usr/local/bin/gniza -> /usr/local/gniza/bin/gniza
mkdir -p "$staging/usr/local/bin"
ln -s /usr/local/gniza/bin/gniza "$staging/usr/local/bin/gniza"

# Strip unwanted files from staging
rm -rf "$staging/usr/local/gniza/.git"
find "$staging" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$staging" -name "*.pyc" -delete 2>/dev/null || true
find "$staging" -name "*.swp" -delete 2>/dev/null || true
find "$staging" -name "*.swo" -delete 2>/dev/null || true
find "$staging" -name "*~" -delete 2>/dev/null || true
rm -f "$staging/usr/local/gniza/textual-mcp.log"
rm -f "$staging/usr/local/gniza/FEATURES.md"
rm -f "$staging/usr/local/gniza/logo.txt"
rm -f "$staging/usr/local/gniza/gniza-logo.png"
rm -rf "$staging/usr/local/gniza/tests"
rm -f "$staging/usr/local/gniza/.gitignore"
rm -f "$staging/usr/local/gniza/.mcp.json"
rm -f "$staging/usr/local/gniza/gniza.svg"
rm -f "$staging/usr/local/gniza/README.md"
rm -f "$staging/usr/local/gniza/DOCUMENTATION.md"

# Remove install/build scripts that shouldn't ship in the deb
rm -f "$staging/usr/local/gniza/scripts/install.sh"
rm -f "$staging/usr/local/gniza/scripts/uninstall.sh"
rm -f "$staging/usr/local/gniza/scripts/deploy.sh"
rm -f "$staging/usr/local/gniza/scripts/build-deb.sh"

# Ensure bin/gniza is executable
chmod +x "$staging/usr/local/gniza/bin/gniza"

# Calculate and inject Installed-Size (in KB)
installed_size=$(du -sk "$staging" | cut -f1)
echo "Installed-Size: $installed_size" >> "$staging/DEBIAN/control"

# Build the .deb
mkdir -p "$REPO_DIR/dist"
output="$REPO_DIR/dist/gniza_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$staging" "$output"

echo ""
echo "Package built successfully:"
echo "  $output"
echo "  Size: $(du -h "$output" | cut -f1)"
