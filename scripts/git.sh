#!/bin/bash
set -euo pipefail
TAG="git"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── User info ──
echo ""
echo "=== Git account setup ==="
echo ""

prompt_with_default() {
  local prompt="$1"
  local default="$2"
  local value

  if $DRY_RUN || $NON_INTERACTIVE; then
    printf '%s\n' "$default"
    return 0
  fi

  read -rp "$prompt [$default]: " value
  printf '%s\n' "${value:-$default}"
}

backup_existing_file() {
  local file="$1"
  local backup_dst

  if [ ! -e "$file" ]; then
    return 0
  fi

  backup_dst="$(next_backup_path "$file")"
  cp -p "$file" "$backup_dst"
  info "Backed up: $file -> $backup_dst"
}

# Read current values as defaults
_cur_personal_name=$(git config -f "$DOTFILES_DIR/configs/.gitconfig-personal" user.name 2>/dev/null || true)
_cur_personal_email=$(git config -f "$DOTFILES_DIR/configs/.gitconfig-personal" user.email 2>/dev/null || true)
_cur_work_name=$(git config -f "$DOTFILES_DIR/configs/.gitconfig-work" user.name 2>/dev/null || true)
_cur_work_email=$(git config -f "$DOTFILES_DIR/configs/.gitconfig-work" user.email 2>/dev/null || true)

personal_name="$(prompt_with_default "Personal Git name" "$_cur_personal_name")"
personal_email="$(prompt_with_default "Personal Git email" "$_cur_personal_email")"
work_name="$(prompt_with_default "Work Git name" "$_cur_work_name")"
work_email="$(prompt_with_default "Work Git email" "$_cur_work_email")"

if ! $DRY_RUN && $NON_INTERACTIVE; then
  if [ -z "$personal_name" ] || [ -z "$personal_email" ] || [ -z "$work_name" ] || [ -z "$work_email" ]; then
    error "Non-interactive Git setup requires existing personal/work git name and email values."
    exit 1
  fi
fi

if $DRY_RUN; then
  info "[dry-run] .gitconfig-personal: $personal_name <$personal_email>"
  info "[dry-run] .gitconfig-work: $work_name <$work_email>"
else
  # Write user.name/email to the (tracked) personal/work configs.
  # signingkey lives in ~/.gitconfig.local because the SSH key path is
  # machine-specific and shouldn't be committed.
  backup_existing_file "$DOTFILES_DIR/configs/.gitconfig-personal"
  cat > "$DOTFILES_DIR/configs/.gitconfig-personal" <<EOF
[user]
    name = $personal_name
    email = $personal_email
# signingkey: machine-local — set in ~/.gitconfig.local
EOF

  backup_existing_file "$DOTFILES_DIR/configs/.gitconfig-work"
  cat > "$DOTFILES_DIR/configs/.gitconfig-work" <<EOF
[user]
    name = $work_name
    email = $work_email
# signingkey: machine-local — set in ~/.gitconfig.local
EOF

  # Machine-local signing config. Per-account keys generated below.
  # Verifiers (GitHub) need the same key registered as a "Signing key" on
  # the account, in addition to the auth key — separate dropdowns on
  # github.com/settings/keys.
  #
  # Override PERSONAL_SIGNING_KEY / WORK_SIGNING_KEY env vars to point at
  # machine-specific paths (e.g. hardware-backed key, shared keychain).
  PERSONAL_SIGNING_KEY="${PERSONAL_SIGNING_KEY:-$HOME/.ssh/id_ed25519_personal.pub}"
  WORK_SIGNING_KEY="${WORK_SIGNING_KEY:-$HOME/.ssh/id_ed25519_work.pub}"

  cat > "$HOME/.gitconfig.local" <<EOF
[user]
    signingkey = $PERSONAL_SIGNING_KEY
[gpg]
    format = ssh
[commit]
    gpgsign = true
[tag]
    gpgsign = true

# Override per work scope: when remote matches oss.navercorp.com, use the work key.
[includeIf "hasconfig:remote.*.url:https://**oss.navercorp.com/**"]
    path = ~/.gitconfig.local-work
[includeIf "hasconfig:remote.*.url:git@**oss.navercorp.com:**"]
    path = ~/.gitconfig.local-work
[includeIf "hasconfig:remote.*.url:ssh://**oss.navercorp.com/**"]
    path = ~/.gitconfig.local-work
EOF

  cat > "$HOME/.gitconfig.local-work" <<EOF
[user]
    signingkey = $WORK_SIGNING_KEY
EOF
fi

# ── Project directories ──
# Convention: company repos live under ~/work/, personal repos under ~/personal/.
# Git account selection is remote-URL-based (see configs/.gitconfig), but the
# company overlay's project-scoped MCP config lives at ~/work/.mcp.json — so
# Claude Code automatically picks up company MCP servers when started in any
# ~/work/<repo>/ directory, and leaves them out everywhere else.
if ! $DRY_RUN; then
  mkdir -p "$HOME/work" "$HOME/personal"
fi

# ── Generate SSH keys ──
generate_ssh_key() {
  local name="$1"
  local email="$2"
  local key_file="$HOME/.ssh/id_ed25519_$name"
  local pub_file="${key_file}.pub"

  if [ -f "$key_file" ] && [ -f "$pub_file" ]; then
    info "SSH key already exists: $key_file (with .pub)"
    return
  fi

  if [ -f "$key_file" ] && [ ! -f "$pub_file" ]; then
    warn "Found $key_file but no .pub — regenerating .pub from private key"
    if ! $DRY_RUN; then
      ssh-keygen -y -f "$key_file" > "$pub_file"
      chmod 644 "$pub_file"
    fi
    return
  fi

  info "Generating SSH key: $name ($email)"
  if $DRY_RUN; then
    info "[dry-run] Skipping ssh-keygen"
  else
    if $NON_INTERACTIVE; then
      want_pw=N
    else
      read -rp "Use a passphrase for $name key? (Y/n) " want_pw
    fi
    if [[ "$want_pw" =~ ^[Nn]$ ]]; then
      ssh-keygen -t ed25519 -C "$email" -f "$key_file" -N ""
    else
      ssh-keygen -t ed25519 -C "$email" -f "$key_file"
    fi
  fi
}

generate_ssh_key "personal" "$personal_email"
generate_ssh_key "work" "$work_email"

# ── SSH config ──
SSH_CONFIG="$HOME/.ssh/config"
SSH_CONFIG_DIR="$HOME/.ssh/config.d"
DOTFILES_SSH_CONFIG="$HOME/.ssh/config.d/dotfiles.conf"
SSH_INCLUDE_LINE='Include ~/.ssh/config.d/*.conf'
if $DRY_RUN; then
  info "[dry-run] Would ensure $SSH_INCLUDE_LINE in $SSH_CONFIG"
  info "[dry-run] Would write $DOTFILES_SSH_CONFIG"
else
  ensure_dir "$HOME/.ssh" "$SSH_CONFIG_DIR"
  if [ ! -f "$SSH_CONFIG" ]; then
    printf '%s\n' "$SSH_INCLUDE_LINE" > "$SSH_CONFIG"
  elif ! grep -Fxq "$SSH_INCLUDE_LINE" "$SSH_CONFIG"; then
    backup_existing_file "$SSH_CONFIG"
    tmp_ssh_config="$(mktemp)"
    {
      printf '%s\n\n' "$SSH_INCLUDE_LINE"
      cat "$SSH_CONFIG"
    } > "$tmp_ssh_config"
    mv "$tmp_ssh_config" "$SSH_CONFIG"
  fi

  cat > "$DOTFILES_SSH_CONFIG" <<EOF
# Personal GitHub
Host github.com-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes

# Work GitHub
Host github.com-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes

# Default (personal)
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes
EOF
  chmod 600 "$DOTFILES_SSH_CONFIG"
  chmod 600 "$SSH_CONFIG"
fi

# ── Register with ssh-agent ──
# macOS Sequoia+ no longer auto-loads keys into ssh-agent on session start, so
# we use --apple-use-keychain to persist the passphrase in the user's Keychain.
# That way every shell — and signed-commit invocation — picks up the key
# without re-prompting.
#
# IMPORTANT: ssh-add needs to prompt for the passphrase the FIRST time. We
# can't safely do that here (the install script is running non-interactively
# from install.sh's perspective), so we just record which keys still need to
# be registered and surface them in the final warning block below.
KEYS_NEEDING_AGENT=()
if ! $DRY_RUN; then
  eval "$(ssh-agent -s)" >/dev/null 2>&1
  # ssh-add -l exits 1 when the agent has no identities — expected on a fresh
  # agent. Swallow that so `set -euo pipefail` doesn't kill the script silently.
  loaded_fingerprints=$(ssh-add -l 2>/dev/null | awk '{print $2}' || true)
  for key in id_ed25519_personal id_ed25519_work; do
    [ -f "$HOME/.ssh/$key" ] || continue
    fp=$(ssh-keygen -lf "$HOME/.ssh/$key.pub" 2>/dev/null | awk '{print $2}')
    if echo "$loaded_fingerprints" | grep -Fxq "$fp"; then
      info "$key already in ssh-agent"
    else
      KEYS_NEEDING_AGENT+=("$key")
    fi
  done
fi

# ── Global gitignore ──
# install.sh creates the symlink; we just register it as the global excludesfile.
# Path is recorded as-is — git resolves it lazily, so the symlink doesn't need
# to exist yet.
if $DRY_RUN; then
  info "[dry-run] git config --global core.excludesfile ~/.gitignore_global"
else
  git config --global core.excludesfile "$HOME/.gitignore_global"
fi

echo ""
info "Git setup done"
echo ""
warn "═══════════════════════════════════════════════════════════════"
warn "  REQUIRED MANUAL STEPS — git won't push/sign correctly until done"
warn "═══════════════════════════════════════════════════════════════"
warn ""

# 1. ssh-agent / Keychain registration
if [ "${#KEYS_NEEDING_AGENT[@]}" -gt 0 ]; then
  warn "1) Register SSH keys with ssh-agent + macOS Keychain (one-time, per key):"
  for key in "${KEYS_NEEDING_AGENT[@]}"; do
    warn "     ssh-add --apple-use-keychain ~/.ssh/$key"
  done
  warn "     # ssh-add will prompt for each key's passphrase. After this every"
  warn "     # shell + signed commit picks the key up automatically."
  warn "     # Verify:  ssh-add -l   (both keys should appear)"
else
  info "1) ssh-agent registration: already done ✓"
fi
warn ""

# 2. gh CLI authentication — needed for HTTPS git ops on each host you push to,
#    and lets step 3 register public keys via CLI instead of pbcopy/browser.
warn "2) Authenticate gh CLI on each git host:"
warn "     gh auth login -h github.com -p https -w \\"
warn "       -s admin:public_key,admin:ssh_signing_key,gist,read:org,repo,workflow"
warn "     # Corporate GHE: swap host, e.g. -h oss.navercorp.com (drop 'workflow' scope)."
warn "     # Stale account on a host?  gh auth logout -h <host> -u <old-handle>   first."
warn ""

# 3. Public key registration on git hosts (Auth + Signing — two separate slots)
warn "3) Register PUBLIC keys on each host as BOTH Auth + Signing."
warn "   (Signing is a separate dropdown — needed for the 'Verified' badge.)"
warn ""
warn "   CLI path (uses gh from step 2):"
warn "     gh ssh-key add ~/.ssh/id_ed25519_personal.pub --type authentication --title \"\$(hostname -s)-personal\""
warn "     gh ssh-key add ~/.ssh/id_ed25519_personal.pub --type signing        --title \"\$(hostname -s)-personal-sig\""
warn "     # Add --hostname <host> for non-github.com (e.g. oss.navercorp.com)."
warn "     # Repeat for ~/.ssh/id_ed25519_work.pub against each host you use the work identity on."
warn ""
warn "   Manual fallback (no gh on that host):"
warn "     pbcopy < ~/.ssh/id_ed25519_personal.pub   # paste at github.com/settings/keys"
warn "     pbcopy < ~/.ssh/id_ed25519_work.pub       # paste at work-host/settings/keys"
warn ""

# 4. Sanity check
warn "4) Verify auth works on each host:"
warn "     ssh -T git@github.com                    # 'Hi <user>!'"
warn "     ssh -T git@<your-internal-git-host>      # 'Hi <user>!'"
warn ""
