#!/bin/sh
# PrivacyWorm installer for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/simonlpaige/privacyworm/main/install.sh | sh
#
# What it does (nothing needs to be installed first - not git, not Python):
#   1. Gets "uv", a small, widely used Python app manager (astral.sh/uv),
#      unless you already have it.
#   2. Uses uv to install PrivacyWorm into its own private folder, with
#      its own copy of Python if your computer doesn't have a recent one.
#   3. Checks for Chrome/Edge (or downloads a private Chromium), and adds
#      PrivacyWorm to your Applications / app launcher.
#
# Run it again any time to update. Your saved info is kept.
# Uninstall: privacyworm uninstall
#
# Options (environment variables):
#   PRIVACYWORM_REF=<branch or tag>   install a different version (default: main)
#   PRIVACYWORM_SOURCE=<path or URL>  install from a local folder or other archive
#   PRIVACYWORM_NO_SHORTCUT=1         don't add an app-menu shortcut
#   PRIVACYWORM_NO_LAUNCH=1           don't offer to open PrivacyWorm at the end

set -eu

REPO="simonlpaige/privacyworm"
REF="${PRIVACYWORM_REF:-main}"
SOURCE="${PRIVACYWORM_SOURCE:-https://github.com/$REPO/archive/refs/heads/$REF.zip}"

if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"; GREEN="$(printf '\033[32m')"; YELLOW="$(printf '\033[33m')"
  RED="$(printf '\033[31m')"; RESET="$(printf '\033[0m')"
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

step() { printf '\n%s==>%s %s%s%s\n' "$GREEN" "$RESET" "$BOLD" "$1" "$RESET"; }
note() { printf '    %s\n' "$1"; }
warn() { printf '%s  ! %s%s\n' "$YELLOW" "$1" "$RESET"; }
die()  { printf '\n%sInstall stopped:%s %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }

download() {  # download <url> -> stdout
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    die "Need curl or wget to download files. Install one and try again."
  fi
}

find_uv() {
  for c in "$(command -v uv 2>/dev/null || true)" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -n "$c" ] && [ -x "$c" ]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

printf '\n%sPrivacyWorm installer%s\n' "$BOLD" "$RESET"
note "Finds your info on people-search sites and helps you get it removed."

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) die "This installer is for macOS and Linux. On Windows, use install.ps1 (see the README)." ;;
esac

# 1. uv --------------------------------------------------------------------
step "Getting the installer helper (uv)"
if UV="$(find_uv)"; then
  note "Already have it: $UV"
else
  note "Downloading uv from astral.sh ..."
  download https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
    || die "Couldn't install uv. Check your internet connection and try again."
  UV="$(find_uv)" || die "uv installed but can't be found. Open a new terminal and run this again."
  note "Installed uv."
fi

# 2. PrivacyWorm --------------------------------------------------------------
step "Installing PrivacyWorm (this can take a minute the first time)"
"$UV" tool install --force --reinstall --python ">=3.11" \
  "privacyworm[mugshot] @ $SOURCE" >/dev/null 2>"${TMPDIR:-/tmp}/privacyworm-install.log" || {
  cat "${TMPDIR:-/tmp}/privacyworm-install.log" >&2
  die "uv couldn't install PrivacyWorm (details above)."
}
BIN_DIR="$("$UV" tool dir --bin 2>/dev/null)"
PW="$BIN_DIR/privacyworm"
[ -x "$PW" ] || die "Install finished but $PW is missing."
note "Installed to $BIN_DIR"

# Make 'privacyworm' work in new terminal windows.
"$UV" tool update-shell >/dev/null 2>&1 || true

# 3. Browser + shortcut -------------------------------------------------------
step "Setting up the browser and shortcut"
SETUP_ARGS=""
[ "${PRIVACYWORM_NO_SHORTCUT:-}" = "1" ] && SETUP_ARGS="--no-shortcut"
# shellcheck disable=SC2086
if ! "$PW" setup $SETUP_ARGS; then
  warn "The browser isn't ready yet. Follow the hint above, then run: privacyworm doctor"
fi

# Done ------------------------------------------------------------------------
printf '\n%s%sPrivacyWorm is installed.%s\n' "$GREEN" "$BOLD" "$RESET"
if [ "$(uname -s)" = "Darwin" ]; then
  note "Open it from Spotlight or Applications (\"PrivacyWorm\"),"
else
  note "Open it from your app launcher (\"PrivacyWorm\"),"
fi
note "or type  privacyworm  in a new terminal window."
note "To update later, run this same install command again."

if [ "${PRIVACYWORM_NO_LAUNCH:-}" != "1" ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
  printf '\n  %sOpen PrivacyWorm now? [Y/n]:%s ' "$BOLD" "$RESET" >/dev/tty
  read -r answer </dev/tty || answer="n"
  case "$answer" in
    ""|y|Y|yes|YES) exec "$PW" </dev/tty >/dev/tty 2>&1 ;;
  esac
fi
