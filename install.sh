#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo ./install.sh"; exit 1; }
command -v pihole-FTL >/dev/null || { echo "Pi-hole v6 is required."; exit 1; }
apt-get update
apt-get install -y git python3 python3-pil python3-requests python3-spidev python3-rpi.gpio
raspi-config nonint do_spi 0 || true
if ! id pihole-eink >/dev/null 2>&1; then
  useradd --system --home /opt/pihole-eink --shell /usr/sbin/nologin pihole-eink
fi
for g in spi gpio; do getent group "$g" >/dev/null && usermod -aG "$g" pihole-eink || true; done
install -d -o pihole-eink -g pihole-eink /opt/pihole-eink/assets/hologram
install -m 0755 "$ROOT/pihole_eink.py" /opt/pihole-eink/pihole_eink.py
if compgen -G "$ROOT/assets/hologram/*.png" > /dev/null; then
  install -m 0644 "$ROOT"/assets/hologram/*.png /opt/pihole-eink/assets/hologram/
else
  echo "No face PNGs found in assets/hologram/."
  echo "On an existing RICK-HOLE Pi, run: ./scripts/copy-assets-from-live-install.sh"
  exit 1
fi
[[ -f "$ROOT/rick_voice.py" ]] && install -m 0644 "$ROOT/rick_voice.py" /opt/pihole-eink/rick_voice.py || true
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 https://github.com/waveshareteam/e-Paper.git "$TMP/e-Paper"
cp -a "$TMP/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd" /opt/pihole-eink/
chown -R pihole-eink:pihole-eink /opt/pihole-eink
install -m 0644 "$ROOT/quotes/default.json" /etc/pihole-eink-text.json
if [[ ! -f /etc/pihole-eink.json ]]; then
  install -m 0600 "$ROOT/config/pihole-eink.example.json" /etc/pihole-eink.json
  echo "Created /etc/pihole-eink.json. Run: sudo ./scripts/configure.sh"
fi
install -d /var/www/html/admin/img
touch /var/www/html/admin/img/rick-hole-live.png
chown pihole-eink:pihole-eink /var/www/html/admin/img/rick-hole-live.png
chmod 0644 /var/www/html/admin/img/rick-hole-live.png
install -m 0644 "$ROOT/systemd/pihole-eink.service" /etc/systemd/system/pihole-eink.service
systemctl daemon-reload
systemctl enable pihole-eink.service
echo "Core installed. Configure /etc/pihole-eink.json, then: sudo systemctl restart pihole-eink"
echo "Optional dashboard card: sudo ./scripts/install-dashboard.sh"
