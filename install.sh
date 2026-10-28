#!/bin/sh
set -eu

TCPSER_REPOSITORY=https://github.com/go4retro/tcpser.git
TCPSER_COMMIT=234ccfde0bb6a874c353c0cdca0fa0ca76c5cca3
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
adapter=
wiring_confirmed=0
non_interactive=0
admin_user=${SUDO_USER:-}
usage() {
    echo 'Usage: sudo sh install.sh [--adapter my018|ma620|serial] [--my018-wiring-confirmed] [--non-interactive] [--admin-user USER]'
    echo 'Default for new installations: MY018 (documented A/B/C + 2N3904 wiring required).'
    echo 'Existing installations retain their selected adapter unless --adapter is given.'
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --adapter|--admin-user)
            option=$1
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            if [ "$option" = --adapter ]; then adapter=$2; else admin_user=$2; fi
            shift 2 ;;
        --my018-wiring-confirmed) wiring_confirmed=1; shift ;;
        --non-interactive) non_interactive=1; shift ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
case "$adapter" in ''|my018|ma620|serial) ;; *) usage >&2; exit 2 ;; esac

if [ "$(id -u)" -ne 0 ]; then
    echo "Start dit script als root: sudo ./install.sh" >&2
    exit 1
fi

for required in python3 flock; do
    command -v "$required" >/dev/null || { echo "Required: $required" >&2; exit 1; }
done
if [ -z "$admin_user" ] || [ "$admin_user" = root ] || ! id "$admin_user" >/dev/null 2>&1; then
    echo 'Use sudo from your Raspberry Pi Imager account, or specify --admin-user EXISTING_USER.' >&2
    exit 1
fi

if [ "$non_interactive" = 0 ] && [ -z "$adapter" ] && [ ! -f /etc/retromodem/retromodem.env ]; then
    if [ -r /dev/tty ] && ( : </dev/tty ) 2>/dev/null; then
        printf 'Adapter: 1 MY018 (preferred), 2 MA-620 (IR fallback), 3 Prolific RS-232 [1]: ' >/dev/tty
        IFS= read -r answer </dev/tty
        case "$answer" in ''|1|my018) adapter=my018 ;; 2|ma620) adapter=ma620 ;; 3|serial) adapter=serial ;; *) exit 2 ;; esac
    fi
fi
if [ "$non_interactive" = 0 ] && [ "$wiring_confirmed" = 0 ] &&
   { [ "$adapter" = my018 ] || { [ -z "$adapter" ] && [ ! -f /etc/retromodem/retromodem.env ]; }; }; then
    if [ -r /dev/tty ] && ( : </dev/tty ) 2>/dev/null; then
        printf 'MY018 requires A/B/C selector wiring + the 2N3904 circuit in docs/MY018-SETUP.md. Is that fitted? [yes/no]: ' >/dev/tty
        IFS= read -r answer </dev/tty
        case "$answer" in yes|ja) wiring_confirmed=1 ;; *) echo 'Installation cancelled.' >&2; exit 1 ;; esac
    fi
fi
# Validate configuration before package/system changes. No secrets are printed.
set --
[ -z "$adapter" ] || set -- "$@" --adapter "$adapter"
[ "$wiring_confirmed" = 0 ] || set -- "$@" --my018-wiring-confirmed
python3 "$PROJECT_DIR/scripts/install-configure.py" "$@"

exec 9>/run/lock/retromodem-install.lock
flock -n 9 || { echo 'Another RetroModem installation is running.' >&2; exit 1; }

if [ ! -r /etc/os-release ] || ! grep -q '^ID=raspbian' /etc/os-release || \
   ! grep -q '^VERSION_ID="\?12"\?$' /etc/os-release; then
    echo "Deze installer vereist Raspberry Pi OS Legacy Bookworm (Debian 12), 32-bit." >&2
    echo "Kies in Raspberry Pi Imager: Raspberry Pi OS (other) -> Legacy, 32-bit -> Lite." >&2
    exit 1
fi

case $(uname -m) in
    armv6l|armv7l) ;;
    *)
        echo "Deze eerste installer ondersteunt alleen de 32-bit Raspberry Pi OS-kernel." >&2
        exit 1
        ;;
esac
kernel_release=$(uname -r)
case "$kernel_release" in
    *-rpi-v6) kernel_headers=linux-headers-rpi-v6 ;;
    *-rpi-v7) kernel_headers=linux-headers-rpi-v7 ;;
    *-rpi-v7l) kernel_headers=linux-headers-rpi-v7l ;;
    *) echo "Unsupported kernel flavor: $kernel_release (expected Bookworm 32-bit rpi-v6/v7/v7l)." >&2; exit 1 ;;
esac
available_kb=$(df -Pk / | awk 'NR == 2 {print $4}')
[ "$available_kb" -ge 1048576 ] || { echo 'At least 1 GiB free space is required for installation builds.' >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    avahi-daemon autoconf automake build-essential dkms git irda-utils \
    curl iproute2 iputils-ping nmap arp-scan dnsutils traceroute libtool lrzsz openobex-apps libopenobex2-dev pkg-config "$kernel_headers" \
    composer dnsmasq imagemagick network-manager nftables openssh-server php-cli php-curl php-gd \
    php-mbstring php-xml ppp procps psmisc python3 python3-bs4 python3-cryptography usbutils xinetd \
    raspi-utils util-linux patch ca-certificates

# Keep the existing Imager administrator and SSH credentials. Never introduce
# a shared sudo-capable account/password during installation.
if [ ! -f "/lib/modules/$kernel_release/build/Makefile" ]; then
    echo "Headers do not match the running kernel $kernel_release." >&2
    echo 'Reboot after kernel/header updates, then run this installer again.' >&2
    exit 1
fi
for required in pinctrl vcgencmd timeout; do
    command -v "$required" >/dev/null || { echo "Required Pi utility missing: $required" >&2; exit 1; }
done

work_dir=$(mktemp -d /tmp/retromodem-install.XXXXXX)
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM

package_version=$(sh "$PROJECT_DIR/scripts/build-irda" "$work_dir/irda" "$kernel_release")

# tcpser is not available consistently in Raspberry Pi OS repositories. Pin a
# reviewed upstream release so a clean installation produces the same modem
# emulator as the development appliance.
git clone --filter=blob:none "$TCPSER_REPOSITORY" "$work_dir/tcpser"
git -C "$work_dir/tcpser" checkout --detach "$TCPSER_COMMIT"
patch -d "$work_dir/tcpser" -p1 < "$PROJECT_DIR/patches/tcpser-initialize-termios.patch"
make -C "$work_dir/tcpser"
install -m 0755 "$work_dir/tcpser/tcpser" /usr/local/bin/tcpser

install -d -m 0755 /opt/retromodem
rm -rf /opt/retromodem/retroweb
cp -a "$PROJECT_DIR/proxy/retroweb" /opt/retromodem/retroweb
composer install --working-dir=/opt/retromodem/retroweb --no-dev --no-interaction --prefer-dist

install -d -m 0755 /etc/retromodem /usr/local/lib/retromodem /usr/local/sbin \
    /usr/local/share/retromodem/static/software \
    /usr/local/share/retromodem/static/guides/psion /var/lib/retromodem/transfers \
    /var/lib/retromodem/software-library /var/lib/retromodem/chatgpt
reboot_required=$(python3 "$PROJECT_DIR/scripts/install-configure.py" "$@" --apply)
python3 - "$admin_user" "$PROJECT_DIR" "$package_version" <<'PY'
import json, pathlib, re, subprocess, sys
admin, project, dkms = sys.argv[1:]
source = pathlib.Path(project) / '.retromodem-source-commit'
commit = source.read_text().strip() if source.exists() else ''
if not commit:
    result = subprocess.run(['git', '-C', project, 'rev-parse', 'HEAD'], capture_output=True, text=True)
    commit = result.stdout.strip() if result.returncode == 0 else ''
if not re.fullmatch(r'[0-9a-f]{40}', commit):
    commit = 'local-unversioned'
pathlib.Path('/etc/retromodem/install.json').write_text(json.dumps({
    'admin_user': admin, 'source_commit': commit, 'irda_dkms_version': dkms,
}, indent=2) + '\n')
PY
install -m 0644 "$PROJECT_DIR/config/nftables.conf" /etc/retromodem/nftables.conf
install -m 0644 "$PROJECT_DIR/config/dnsmasq-retromodem.conf" /etc/dnsmasq.d/retromodem.conf
install -m 0644 "$PROJECT_DIR/config/hardware/adapters.json" /etc/retromodem/adapters.json
if [ ! -e /etc/retromodem/phonebook.json ]; then
    install -m 0644 "$PROJECT_DIR/config/phonebook.json" /etc/retromodem/phonebook.json
fi
install -m 0755 "$PROJECT_DIR/scripts/ensure-chatgpt-phonebook.py" /usr/local/lib/retromodem/ensure-chatgpt-phonebook.py
/usr/local/lib/retromodem/ensure-chatgpt-phonebook.py
install -m 0755 "$PROJECT_DIR/scripts/prepare-irda" /usr/local/lib/retromodem/prepare-irda
install -m 0755 "$PROJECT_DIR/scripts/my018-power-cycle" /usr/local/lib/retromodem/my018-power-cycle
install -m 0755 "$PROJECT_DIR/scripts/start-irda" /usr/local/lib/retromodem/start-irda
install -m 0755 "$PROJECT_DIR/scripts/wait-irda" /usr/local/lib/retromodem/wait-irda
install -m 0755 "$PROJECT_DIR/scripts/set-mode-leds" /usr/local/lib/retromodem/set-mode-leds
install -m 0755 "$PROJECT_DIR/scripts/status-leds.py" /usr/local/lib/retromodem/status-leds.py
install -m 0755 "$PROJECT_DIR/scripts/diagnose" /usr/local/sbin/retromodem-diagnose
install -m 0755 "$PROJECT_DIR/scripts/configure-ap" /usr/local/lib/retromodem/configure-ap
install -m 0755 "$PROJECT_DIR/scripts/ap-fallback" /usr/local/lib/retromodem/ap-fallback
install -m 0755 "$PROJECT_DIR/scripts/connect-wifi" /usr/local/lib/retromodem/connect-wifi
install -m 0755 "$PROJECT_DIR/scripts/proxy-enabled" /usr/local/lib/retromodem/proxy-enabled
install -m 0755 "$PROJECT_DIR/scripts/proxy-firewall" /usr/local/lib/retromodem/proxy-firewall
install -m 0755 "$PROJECT_DIR/scripts/retroweb-proxy.py" /usr/local/lib/retromodem/retroweb-proxy.py
install -m 0755 "$PROJECT_DIR/scripts/transfer.py" /usr/local/lib/retromodem/transfer.py
python3 "$PROJECT_DIR/scripts/build-palm-progress" /usr/local/lib/retromodem/irobex-palm-progress
install -m 0755 "$PROJECT_DIR/scripts/modem-backend.py" /usr/local/lib/retromodem/modem-backend.py
install -m 0755 "$PROJECT_DIR/scripts/chatgpt-bbs.py" /usr/local/lib/retromodem/chatgpt-bbs.py
install -m 0644 "$PROJECT_DIR/web/openai_auth.py" /usr/local/lib/retromodem/openai_auth.py
install -m 0644 "$PROJECT_DIR/web/chat_history.py" /usr/local/lib/retromodem/chat_history.py
install -m 0644 "$PROJECT_DIR/web/network_tools.py" /usr/local/lib/retromodem/network_tools.py
install -m 0644 "$PROJECT_DIR/web/local_ui.py" /usr/local/lib/retromodem/local_ui.py
install -m 0755 "$PROJECT_DIR/scripts/apply-mode" /usr/local/lib/retromodem/apply-mode
install -m 0755 "$PROJECT_DIR/scripts/dialup-ppp" /usr/local/lib/retromodem/dialup-ppp
install -m 0755 "$PROJECT_DIR/scripts/selftest" /usr/local/lib/retromodem/selftest
install -m 0755 "$PROJECT_DIR/scripts/button-control.py" /usr/local/lib/retromodem/button-control.py
install -m 0755 "$PROJECT_DIR/scripts/verify-install" /usr/local/sbin/retromodem-verify
cc -O2 -Wall -I"$PROJECT_DIR/src/legacy-irda" \
    -o /usr/local/lib/retromodem/irpsion5-send \
    "$PROJECT_DIR/src/legacy-irda/irpsion5.c"
cc -O2 -Wall -I"$PROJECT_DIR/src" \
    -o /usr/local/lib/retromodem/irda-modem-hints \
    "$PROJECT_DIR/src/irda-modem-hints.c"
install -m 0755 "$PROJECT_DIR/web/web.py" /usr/local/lib/retromodem/web.py
install -m 0644 "$PROJECT_DIR/web/chatgpt_web.py" /usr/local/lib/retromodem/chatgpt_web.py
install -m 0644 "$PROJECT_DIR/web/static/software/"* /usr/local/share/retromodem/static/software/
install -m 0644 "$PROJECT_DIR/web/static/guides/psion/"* /usr/local/share/retromodem/static/guides/psion/
install -m 0644 "$PROJECT_DIR/config/ppp/retromodem" /etc/ppp/peers/retromodem
install -m 0644 "$PROJECT_DIR/config/sysctl.conf" /etc/sysctl.d/90-retromodem.conf
install -m 0644 "$PROJECT_DIR/systemd/retromodem-irda.service" /etc/systemd/system/retromodem-irda.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-network.service" /etc/systemd/system/retromodem-network.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-ppp.service" /etc/systemd/system/retromodem-ppp.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-tcpser.service" /etc/systemd/system/retromodem-tcpser.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-mode.service" /etc/systemd/system/retromodem-mode.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-ap-fallback.service" /etc/systemd/system/retromodem-ap-fallback.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-web.service" /etc/systemd/system/retromodem-web.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-chatgpt.service" /etc/systemd/system/retromodem-chatgpt.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-proxy.service" /etc/systemd/system/retromodem-proxy.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-retroweb-core.service" /etc/systemd/system/retromodem-retroweb-core.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-leds.service" /etc/systemd/system/retromodem-leds.service
install -m 0644 "$PROJECT_DIR/systemd/retromodem-button.service" /etc/systemd/system/retromodem-button.service
install -m 0644 "$PROJECT_DIR/config/xinetd-retromodem-ppp" /etc/xinetd.d/retromodem-ppp

# Record checksums only for files that the installer owns on every run. User
# data and editable settings (retromodem.env, phonebook and software library)
# are intentionally excluded.
manifest=/usr/local/share/retromodem/install-manifest.sha256
managed_files='etc/retromodem/nftables.conf
etc/dnsmasq.d/retromodem.conf
etc/retromodem/adapters.json
etc/ppp/peers/retromodem
etc/sysctl.d/90-retromodem.conf
etc/systemd/system/retromodem-irda.service
etc/systemd/system/retromodem-network.service
etc/systemd/system/retromodem-ppp.service
etc/systemd/system/retromodem-tcpser.service
etc/systemd/system/retromodem-mode.service
etc/systemd/system/retromodem-ap-fallback.service
etc/systemd/system/retromodem-web.service
etc/systemd/system/retromodem-chatgpt.service
etc/systemd/system/retromodem-proxy.service
etc/systemd/system/retromodem-retroweb-core.service
etc/systemd/system/retromodem-leds.service
etc/systemd/system/retromodem-button.service
etc/xinetd.d/retromodem-ppp
usr/local/bin/tcpser
usr/local/lib/retromodem/prepare-irda
usr/local/lib/retromodem/my018-power-cycle
usr/local/lib/retromodem/start-irda
usr/local/lib/retromodem/wait-irda
usr/local/lib/retromodem/set-mode-leds
usr/local/lib/retromodem/status-leds.py
usr/local/lib/retromodem/configure-ap
usr/local/lib/retromodem/ap-fallback
usr/local/lib/retromodem/connect-wifi
usr/local/lib/retromodem/proxy-enabled
usr/local/lib/retromodem/proxy-firewall
usr/local/lib/retromodem/retroweb-proxy.py
usr/local/lib/retromodem/transfer.py
usr/local/lib/retromodem/modem-backend.py
usr/local/lib/retromodem/chatgpt-bbs.py
usr/local/lib/retromodem/openai_auth.py
usr/local/lib/retromodem/chat_history.py
usr/local/lib/retromodem/network_tools.py
usr/local/lib/retromodem/local_ui.py
usr/local/lib/retromodem/chatgpt_web.py
usr/local/lib/retromodem/ensure-chatgpt-phonebook.py
usr/local/lib/retromodem/apply-mode
usr/local/lib/retromodem/dialup-ppp
usr/local/lib/retromodem/selftest
usr/local/lib/retromodem/button-control.py
usr/local/lib/retromodem/irpsion5-send
usr/local/lib/retromodem/irda-modem-hints
usr/local/lib/retromodem/web.py
usr/local/sbin/retromodem-diagnose
usr/local/sbin/retromodem-verify'
(cd / && sha256sum $managed_files) > "$manifest"

hostnamectl set-hostname retromodem
systemctl enable NetworkManager.service avahi-daemon.service dnsmasq.service ssh.service
systemctl daemon-reload
set -a
. /etc/retromodem/retromodem.env
set +a
if [ "${RETROMODEM_MY018_POWER_CYCLE:-0}" = 1 ]; then
    if systemctl is-active --quiet hciuart.service; then reboot_required=1; fi
    systemctl disable hciuart.service 2>/dev/null || true
    for uart in serial0 ttyAMA0 ttyS0; do
        if systemctl is-active --quiet "serial-getty@$uart.service"; then reboot_required=1; fi
        systemctl disable "serial-getty@$uart.service" 2>/dev/null || true
    done
    # Do not stop Bluetooth/console or drive the GPIO UART live before reboot.
    [ "$(readlink -f /dev/serial0 2>/dev/null || true)" = /dev/ttyAMA0 ] || reboot_required=1
    if grep -Eq 'console=(serial0|ttyAMA0|ttyS0)(,| |$)' /proc/cmdline; then reboot_required=1; fi
fi
/usr/local/lib/retromodem/configure-ap
systemctl disable retromodem-irda.service retromodem-ppp.service retromodem-tcpser.service 2>/dev/null || true
systemctl enable retromodem-network.service retromodem-mode.service retromodem-leds.service \
    retromodem-button.service retromodem-ap-fallback.service retromodem-web.service \
    retromodem-chatgpt.service xinetd.service
systemctl disable --now retromodem-68kproxy.service 2>/dev/null || true
rm -f /etc/systemd/system/retromodem-68kproxy.service
systemctl enable retromodem-retroweb-core.service retromodem-proxy.service
systemctl restart avahi-daemon.service
systemctl restart dnsmasq.service
systemctl restart retromodem-network.service
systemctl restart xinetd.service retromodem-ap-fallback.service retromodem-web.service retromodem-chatgpt.service
systemctl restart retromodem-retroweb-core.service retromodem-proxy.service || true

if [ "$reboot_required" = 1 ] || [ -d /sys/module/irda ]; then
    # An already-loaded driver may still be the previous build. A reboot loads
    # the installed DKMS modules and the configured UART/power defaults together.
    install -d /var/lib/retromodem
    cat /proc/sys/kernel/random/boot_id > /var/lib/retromodem/reboot-required
    echo 'RetroModem installed. Reboot required before modem testing: sudo reboot'
elif systemctl restart retromodem-mode.service; then
    systemctl restart retromodem-button.service
    echo "RetroModem is geïnstalleerd en gestart."
else
    echo "RetroModem is geïnstalleerd, maar de gekozen adapter is nog niet beschikbaar." >&2
    echo "Sluit de adapter aan en voer uit: sudo systemctl restart retromodem-mode" >&2
fi

echo "Diagnose: sudo retromodem-diagnose"
echo "Installatie controleren: sudo retromodem-verify"
echo "SSH administrator remains: $admin_user (your existing password/key)."
