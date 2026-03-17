#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

VERSION="$(grep -oP 'GNIZA4LINUX_VERSION="\K[^"]+' "$REPO_DIR/lib/constants.sh")"
if [ -z "$VERSION" ]; then
    echo "ERROR: Could not extract version from lib/constants.sh" >&2
    exit 1
fi

echo "Building gniza ${VERSION} .rpm package..."

# Create rpmbuild directory structure
RPMBUILD=$(mktemp -d)
trap 'rm -rf "$RPMBUILD"' EXIT
mkdir -p "$RPMBUILD"/{SPECS,SOURCES,BUILD,RPMS,SRPMS}

# Copy source files to SOURCES
for dir in bin lib tui web daemon etc scripts data; do
    if [ -d "$REPO_DIR/$dir" ]; then
        cp -a "$REPO_DIR/$dir" "$RPMBUILD/SOURCES/"
    fi
done
[ -f "$REPO_DIR/LICENSE" ] && cp "$REPO_DIR/LICENSE" "$RPMBUILD/SOURCES/"

# Generate spec file from template
sed "s|%{VERSION}|$VERSION|g" "$REPO_DIR/rpm/gniza.spec" > "$RPMBUILD/SPECS/gniza.spec"

# Build RPM
rpmbuild --define "_topdir $RPMBUILD" -bb "$RPMBUILD/SPECS/gniza.spec"

# Copy output
mkdir -p "$REPO_DIR/dist"
find "$RPMBUILD/RPMS" -name "*.rpm" -exec cp {} "$REPO_DIR/dist/" \;

output=$(find "$REPO_DIR/dist" -name "gniza-${VERSION}*.rpm" | head -1)
echo ""
echo "Package built successfully:"
echo "  $output"
echo "  Size: $(du -h "$output" | cut -f1)"
