#!/bin/sh
# Install the security core service on a Linux server: sh install-core.sh /path/to/unpacked/app-folder
# Creates the service group and user, copies the app to /opt/audio-translate/app and starts the core. Nothing secret is printed.
set -eu
SRC="${1:?usage: install-core.sh <folder that holds security-core/bin/audio-security-core>}"
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
[ -x "$SRC/security-core/bin/audio-security-core" ] || { echo "no core binary in $SRC" >&2; exit 1; }
getent group audio-translate >/dev/null || groupadd --system audio-translate
id audio-translate >/dev/null 2>&1 || useradd --system --gid audio-translate --home-dir /var/lib/audio-translate-app --create-home --shell /usr/sbin/nologin audio-translate
mkdir -p /opt/audio-translate
rm -rf /opt/audio-translate/app.new && cp -a "$SRC" /opt/audio-translate/app.new
chown -R root:root /opt/audio-translate/app.new && chmod -R go-w /opt/audio-translate/app.new
[ -d /opt/audio-translate/app ] && mv /opt/audio-translate/app /opt/audio-translate/app.prev.$(date +%s)
mv /opt/audio-translate/app.new /opt/audio-translate/app
install -m 0644 "$(dirname "$0")/audio-security-core.service" /etc/systemd/system/audio-security-core.service
systemctl daemon-reload && systemctl enable --now audio-security-core.service
sleep 1; systemctl is-active audio-security-core.service
