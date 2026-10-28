#!/bin/sh
# Fetch a pinned RetroModem source revision. Download as the SSH user, then sudo.
set -eu

usage() {
    cat <<'EOF'
Usage: sh bootstrap.sh --ref COMMIT [options]

  --ref COMMIT                 Required full 40-character Git commit SHA
  --adapter my018|ma620|serial  Installer choice (default: interactive, MY018 first)
  --my018-wiring-confirmed     Confirm the documented modified MY018 circuit
  --non-interactive            Do not ask installer questions
  --token-file FILE            Owner-only GitHub token file for the private repo
  --download-only DIRECTORY    Download and validate sources; do not install
  --help                      Show this help without network or system changes

Private access: alternatively set RETROMODEM_GITHUB_TOKEN before running.
Tokens are used only for downloading and are not passed to the installer.
EOF
}

die() { printf 'RetroModem bootstrap: %s\n' "$*" >&2; exit 1; }
ref=
adapter=
wiring=0
noninteractive=0
token_file=
download_only=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --ref|--adapter|--token-file|--download-only)
            option=$1
            [ "$#" -ge 2 ] || die "$option requires a value"
            case "$option" in
                --ref) ref=$2 ;;
                --adapter) adapter=$2 ;;
                --token-file) token_file=$2 ;;
                --download-only) download_only=$2 ;;
            esac
            shift 2 ;;
        --my018-wiring-confirmed) wiring=1; shift ;;
        --non-interactive) noninteractive=1; shift ;;
        *) die "Unknown option: $1" ;;
    esac
done
[ "${#ref}" -eq 40 ] || die '--ref must be a full 40-character commit SHA'
case "$ref" in *[!0-9a-fA-F]*) die '--ref must contain only hexadecimal characters' ;; esac
case "$adapter" in ''|my018|ma620|serial) ;; *) die 'Adapter must be my018, ma620 or serial' ;; esac

command -v curl >/dev/null 2>&1 || die 'curl is required'
command -v python3 >/dev/null 2>&1 || die 'python3 is required'
[ -z "$download_only" ] || [ ! -e "$download_only" ] || die 'Download destination already exists'
if [ -z "$download_only" ] && [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die 'sudo is required to run the installer'
fi

umask 077
work_dir=$(mktemp -d /tmp/retromodem-bootstrap.XXXXXX)
cleanup() { rm -rf "$work_dir"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

unset token
token=${RETROMODEM_GITHUB_TOKEN:-}
if [ -n "$token_file" ]; then
    [ -z "$token" ] || die 'Use either --token-file or RETROMODEM_GITHUB_TOKEN, not both'
    token=$(python3 - "$token_file" <<'PY'
import os
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1])
info = path.lstat()
if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
    sys.exit('Token file must be a regular file owned by you with permissions 0600 or 0400')
print(path.read_text().strip())
PY
    ) || die 'Unable to read the token file'
fi
if [ -n "$token_file" ] && [ -z "$token" ]; then die 'Token file is empty'; fi
case "$token" in *[!A-Za-z0-9_]*) die 'Invalid GitHub token format' ;; esac
# Do not export the token to curl or the eventual installer. Feed curl config
# through stdin, so the header is not exposed in process arguments or a file.
unset RETROMODEM_GITHUB_TOKEN GH_TOKEN GITHUB_TOKEN
url="https://api.github.com/repos/BjornB2/retromodem/tarball/$ref"
printf 'Downloading RetroModem commit %s\n' "$ref"
if ! {
    printf 'header = "Accept: application/vnd.github+json"\n'
    if [ -n "$token" ]; then printf 'header = "Authorization: Bearer %s"\n' "$token"; fi
} | curl -q --config - --fail --silent --show-error --location \
    --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 300 \
    --output "$work_dir/source.tar.gz" "$url"; then
    unset token
    die 'Download failed. For the private repository, check token access to BjornB2/retromodem.'
fi
unset token

# Never extract arbitrary archive paths or links. GitHub source archives have
# one top-level directory, which is removed here. No tar extraction subprocess
# is needed, and no archive-provided executable is run during validation.
python3 - "$work_dir/source.tar.gz" "$work_dir/source" "$ref" <<'PY'
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

archive, destination, revision = sys.argv[1:]
root = Path(destination)
with tarfile.open(archive, 'r:gz') as source:
    members = source.getmembers()
    if len(members) > 10000 or sum(m.size for m in members) > 100 * 1024 * 1024:
        sys.exit('Source archive exceeds allowed size')
    prefixes = set()
    selected = []
    names = set()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            sys.exit('Unsafe archive path')
        if not (member.isdir() or member.isfile()):
            sys.exit('Source archive contains a link or unsupported file type')
        prefixes.add(path.parts[0])
        relative = Path(*path.parts[1:])
        if not path.parts[1:]:
            if not member.isdir():
                sys.exit('Archive root is not a directory')
            continue
        if relative.as_posix() in names:
            sys.exit('Duplicate archive path')
        names.add(relative.as_posix())
        selected.append((member, root / relative))
    if len(prefixes) != 1:
        sys.exit('Expected a single source directory')
    if 'install.sh' not in names:
        sys.exit('Source archive is missing install.sh')
    root.mkdir()
    for member, target in selected:
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    (root / '.retromodem-source-commit').write_text(revision.lower() + '\n')
PY

if [ -n "$download_only" ]; then
    python3 - "$work_dir/source" "$download_only" <<'PY'
from pathlib import Path
import shutil
import sys

destination = Path(sys.argv[2])
shutil.copytree(sys.argv[1], destination)
PY
    printf 'Validated sources saved in %s; installer was not run.\n' "$download_only"
    exit 0
fi

set --
[ -z "$adapter" ] || set -- "$@" --adapter "$adapter"
[ "$wiring" -eq 0 ] || set -- "$@" --my018-wiring-confirmed
[ "$noninteractive" -eq 0 ] || set -- "$@" --non-interactive
if [ "$(id -u)" -eq 0 ]; then
    sh "$work_dir/source/install.sh" "$@"
else
    sudo sh "$work_dir/source/install.sh" "$@"
fi
