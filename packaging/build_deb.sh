#!/bin/sh
# Build dist/image-measure_<version>_all.deb from the repository sources.
# Usage: packaging/build_deb.sh <version>      e.g. packaging/build_deb.sh 0.1.0
# Install the result with: sudo apt install ./dist/image-measure_<version>_all.deb
set -eu

VERSION="${1:?usage: $0 <version>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

# The app lives in /usr/lib/image-measure; /usr/bin/image-measure starts it.
LIB="$STAGE/usr/lib/image-measure"
install -d "$LIB" "$STAGE/usr/bin" "$STAGE/DEBIAN" \
    "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/256x256/apps" \
    "$STAGE/usr/share/doc/image-measure"
install -m 644 "$ROOT/image_measure.py" "$ROOT/geometry.py" "$ROOT/image-measure.png" "$LIB/"
install -m 644 "$ROOT/image-measure.png" "$STAGE/usr/share/icons/hicolor/256x256/apps/"
install -m 644 "$ROOT/packaging/image-measure.desktop" "$STAGE/usr/share/applications/"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/image-measure/"

cat > "$STAGE/usr/bin/image-measure" <<'SH'
#!/bin/sh
exec python3 /usr/lib/image-measure/image_measure.py "$@"
SH
chmod 755 "$STAGE/usr/bin/image-measure"

# Refresh the icon cache and menu database after install and removal.
for script in postinst postrm; do
    cat > "$STAGE/DEBIAN/$script" <<'SH'
#!/bin/sh
set -e
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
SH
    chmod 755 "$STAGE/DEBIAN/$script"
done

cat > "$STAGE/DEBIAN/control" <<CTRL
Package: image-measure
Version: $VERSION
Section: graphics
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-tk, python3-pil, python3-pil.imagetk
Recommends: fonts-dejavu-core
Installed-Size: $(du -sk "$STAGE/usr" | cut -f1)
Maintainer: Andres Rivas <andres.rivas@focus.uy>
Homepage: https://github.com/andresrc92/image_measure
Description: measure lengths, radii, angles and areas on an image
 Open an image, draw reference lines over features of known length to set
 the scale, then measure with lines, circles (center or 3-point), angles,
 rectangles and polygons. Measurements can be saved as JSON and exported
 as an annotated PNG.
CTRL

mkdir -p "$ROOT/dist"
dpkg-deb --build --root-owner-group "$STAGE" "$ROOT/dist/image-measure_${VERSION}_all.deb"
