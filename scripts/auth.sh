#!/bin/bash
set -euo pipefail

# shellcheck disable=SC2034 # consumed by scripts/lib/common.sh after source.
TAG="auth"
AUTH_SCRIPT_SOURCE="${BASH_SOURCE[0]}"
while [ -L "$AUTH_SCRIPT_SOURCE" ]; do
  AUTH_SCRIPT_DIR="$(cd "$(dirname "$AUTH_SCRIPT_SOURCE")" && pwd)"
  AUTH_SCRIPT_SOURCE="$(readlink "$AUTH_SCRIPT_SOURCE")"
  case "$AUTH_SCRIPT_SOURCE" in
    /*) ;;
    *) AUTH_SCRIPT_SOURCE="$AUTH_SCRIPT_DIR/$AUTH_SCRIPT_SOURCE" ;;
  esac
done
AUTH_SCRIPT_DIR="$(cd "$(dirname "$AUTH_SCRIPT_SOURCE")" && pwd)"
# shellcheck source=scripts/lib/common.sh
# shellcheck disable=SC1091
source "$AUTH_SCRIPT_DIR/lib/common.sh"

KEYCHAIN_PREFIX="io.voidmatcha.dotfiles"
KEYCHAIN_ACCOUNT="${DOTFILES_KEYCHAIN_ACCOUNT:-${USER:-$(id -un)}}"
AUTH_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles-auth"
CUSTOM_CREDENTIALS_FILE="${DOTFILES_AUTH_REGISTRY_FILE:-$AUTH_CONFIG_DIR/credentials.tsv}"

usage() {
  cat <<'USAGE'
Usage: dotfiles-auth <command> [arguments]

One entry point for browser/OAuth sessions, Keychain-backed API keys and
tokens, repository profiles, and process-scoped secret injection.

Commands:
  status
      Show login and Keychain state without reading secret values.
  catalog
      Show where credentials live and how they are routed, without reading
      secret values.
  setup [all|core|personal|work|social]
      Run the supported browser login flows and open the relevant token pages.
      Existing logins are kept.
  set <all|personal|work|work-rw|credential-name>
      Store a credential group or one credential. all includes personal and
      work read profiles but deliberately excludes work-rw.
  register <name> <ENV_VAR> <personal-ro|work-ro|work-rw>
      Register an environment-token consumer (CLI, SDK, automation, or MCP).
      No secret value is written to the registry; follow with set <name> or
      set all.
  unregister <name>
      Remove a custom registration and its Keychain entry.
  remove <secret-name>
      Remove one Keychain entry.
  profile [show]
  profile set <personal-ro|work-ro|none>
  profile clear
      Store the default authentication profile in the current repository's
      local Git config. work-rw is intentionally command-scoped.
  run <auto|personal-ro|work-ro|work-rw|none> -- <command> [args...]
      Inject only the selected profile into one child process.

Examples:
  dotfiles-auth setup personal
  dotfiles-auth setup all
  dotfiles-auth setup social
  dotfiles-auth catalog
  dotfiles-auth set all
  dotfiles-auth register sentry SENTRY_AUTH_TOKEN work-ro
  dotfiles-auth set sentry
  dotfiles-auth profile set work-ro
  dotfiles-auth run work-rw -- codex
USAGE
}

canonical_secret_name() {
  case "${1:-}" in
    figma) printf '%s\n' "figma-personal" ;;
    zeplin) printf '%s\n' "zeplin-personal" ;;
    exa|figma-personal|figma-work|zeplin-personal|zeplin-work|\
      atlassian-personal-ro|atlassian-work-ro|atlassian-work-rw)
      printf '%s\n' "$1"
      ;;
    *) return 1 ;;
  esac
}

validate_credential_name() {
  [[ "${1:-}" =~ ^[a-z0-9][a-z0-9._-]*$ ]]
}

validate_env_name() {
  [[ "${1:-}" =~ ^[A-Z_][A-Z0-9_]*$ ]]
}

validate_custom_profile() {
  case "${1:-}" in
    personal-ro|work-ro|work-rw) ;;
    *) return 1 ;;
  esac
}

custom_registry_records() {
  local name env_name profile extra
  [ -f "$CUSTOM_CREDENTIALS_FILE" ] || return 0
  [ ! -L "$CUSTOM_CREDENTIALS_FILE" ] || {
    error "custom credential registry must not be a symlink: $CUSTOM_CREDENTIALS_FILE"
    return 2
  }

  while IFS=$'\t' read -r name env_name profile extra; do
    [ -n "$name$env_name$profile$extra" ] || continue
    if [ -n "$extra" ] || ! validate_credential_name "$name" || \
      ! validate_env_name "$env_name" || ! validate_custom_profile "$profile"; then
      error "invalid custom credential registry entry: $name"
      return 2
    fi
    printf '%s\t%s\t%s\n' "$name" "$env_name" "$profile"
  done < "$CUSTOM_CREDENTIALS_FILE"
}

custom_credential_record() {
  local wanted="$1" records name env_name profile
  records="$(custom_registry_records)" || return $?
  while IFS=$'\t' read -r name env_name profile; do
    [ -n "$name" ] || continue
    if [ "$name" = "$wanted" ]; then
      printf '%s\t%s\t%s\n' "$name" "$env_name" "$profile"
      return 0
    fi
  done <<< "$records"
  return 1
}

resolve_credential_name() {
  local requested="${1:-}" canonical status
  if canonical="$(canonical_secret_name "$requested")"; then
    printf '%s\n' "$canonical"
    return 0
  fi
  if custom_credential_record "$requested" >/dev/null; then
    printf '%s\n' "$requested"
    return 0
  else
    status=$?
    [ "$status" -eq 1 ] || return "$status"
  fi
  return 1
}

secret_env_name() {
  local name
  name="$(canonical_secret_name "${1:-}")" || return 1
  case "$name" in
    exa) printf '%s\n' "EXA_API_KEY" ;;
    figma-personal) printf '%s\n' "FIGMA_PERSONAL_API_KEY" ;;
    figma-work) printf '%s\n' "FIGMA_WORK_API_KEY" ;;
    zeplin-personal) printf '%s\n' "ZEPLIN_PERSONAL_ACCESS_TOKEN" ;;
    zeplin-work) printf '%s\n' "ZEPLIN_WORK_ACCESS_TOKEN" ;;
    atlassian-personal-ro) printf '%s\n' "ATLASSIAN_PERSONAL_RO_AUTH" ;;
    atlassian-work-ro) printf '%s\n' "ATLASSIAN_WORK_RO_AUTH" ;;
    atlassian-work-rw) printf '%s\n' "ATLASSIAN_WORK_RW_AUTH" ;;
    *) return 1 ;;
  esac
}

runtime_env_name() {
  local name record env_name
  name="$(resolve_credential_name "${1:-}")" || return $?
  case "$name" in
    figma-personal|figma-work) printf '%s\n' "FIGMA_API_KEY" ;;
    zeplin-personal|zeplin-work) printf '%s\n' "ZEPLIN_ACCESS_TOKEN" ;;
    exa|atlassian-personal-ro|atlassian-work-ro|atlassian-work-rw)
      secret_env_name "$name"
      ;;
    *)
      record="$(custom_credential_record "$name")" || return $?
      IFS=$'\t' read -r _ env_name _ <<< "$record"
      printf '%s\n' "$env_name"
      ;;
  esac
}

keychain_service() {
  local name env_name
  name="$(resolve_credential_name "${1:-}")" || return $?
  if env_name="$(secret_env_name "$name" 2>/dev/null)"; then
    printf '%s.%s\n' "$KEYCHAIN_PREFIX" "$env_name"
  else
    printf '%s.custom.%s\n' "$KEYCHAIN_PREFIX" "$name"
  fi
}

require_keychain() {
  if ! command -v security >/dev/null 2>&1; then
    error "macOS Keychain CLI is unavailable"
    return 1
  fi
}

secret_is_stored() {
  local service
  service="$(keychain_service "$1")" || return 1
  security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$service" \
    >/dev/null 2>&1
}

set_secret() {
  local name="${1:-}" env_name service value_hint="API key or token"
  name="$(resolve_credential_name "$name")" || {
    error "unknown secret: ${name:-<missing>}"
    return 2
  }
  env_name="$(runtime_env_name "$name")"
  require_keychain
  service="$(keychain_service "$name")"

  case "$name" in
    atlassian-*) value_hint="complete Authorization header (Basic ... or Bearer ...)" ;;
    zeplin-*) value_hint="Zeplin personal access token" ;;
  esac

  info "Keychain will prompt for $name ($env_name)."
  info "Paste the $value_hint once; input is hidden."
  # `security` documents that -w with no value, in final position, owns the
  # secure prompt. Never read the credential in this shell or put it in argv.
  security add-generic-password -U \
    -a "$KEYCHAIN_ACCOUNT" \
    -s "$service" \
    -l "dotfiles: $name" \
    -j "Managed by dotfiles-auth as $env_name" \
    -w
  info "stored $name in macOS Keychain"
}

remove_secret() {
  local name="${1:-}" service
  name="$(resolve_credential_name "$name")" || {
    error "unknown secret: ${name:-<missing>}"
    return 2
  }
  require_keychain
  service="$(keychain_service "$name")"
  if security delete-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$service" \
      >/dev/null 2>&1; then
    info "removed $name from macOS Keychain"
  else
    warn "$name was not stored"
  fi
}

credential_name_is_reserved() {
  case "${1:-}" in
    all|personal|work|work-rw|figma|zeplin) return 0 ;;
  esac
  canonical_secret_name "${1:-}" >/dev/null 2>&1
}

env_name_is_managed_builtin() {
  case "${1:-}" in
    EXA_API_KEY|FIGMA_API_KEY|ZEPLIN_ACCESS_TOKEN|\
      FIGMA_PERSONAL_API_KEY|FIGMA_WORK_API_KEY|\
      ZEPLIN_PERSONAL_ACCESS_TOKEN|ZEPLIN_WORK_ACCESS_TOKEN|\
      ATLASSIAN_PERSONAL_RO_AUTH|ATLASSIAN_WORK_RO_AUTH|ATLASSIAN_WORK_RW_AUTH)
      return 0
      ;;
    *) return 1 ;;
  esac
}

write_custom_registry_entry() {
  local name="$1" env_name="$2" profile="$3" temp_file records
  mkdir -p "$AUTH_CONFIG_DIR"
  chmod 700 "$AUTH_CONFIG_DIR"
  temp_file="$(mktemp "$AUTH_CONFIG_DIR/.credentials.XXXXXX")"
  records="$(custom_registry_records)" || {
    rm -f "$temp_file"
    return 2
  }
  if [ -n "$records" ]; then
    printf '%s\n' "$records" > "$temp_file"
  fi
  printf '%s\t%s\t%s\n' "$name" "$env_name" "$profile" >> "$temp_file"
  chmod 600 "$temp_file"
  mv "$temp_file" "$CUSTOM_CREDENTIALS_FILE"
}

register_credential() {
  local name="${1:-}" env_name="${2:-}" profile="${3:-}" \
    existing records existing_name existing_env existing_profile status
  validate_credential_name "$name" || {
    error "credential name must match [a-z0-9][a-z0-9._-]*"
    return 2
  }
  credential_name_is_reserved "$name" && {
    error "credential name is reserved: $name"
    return 2
  }
  validate_env_name "$env_name" || {
    error "environment variable must use uppercase letters, digits, and underscores"
    return 2
  }
  env_name_is_managed_builtin "$env_name" && {
    error "environment variable is already managed by a built-in credential: $env_name"
    return 2
  }
  validate_custom_profile "$profile" || {
    error "custom credential profile must be personal-ro, work-ro, or work-rw"
    return 2
  }

  if existing="$(custom_credential_record "$name")"; then
    if [ "$existing" = "$name"$'\t'"$env_name"$'\t'"$profile" ]; then
      info "custom credential already registered: $name"
      return 0
    fi
    error "custom credential already exists with different routing: $name"
    return 2
  else
    status=$?
    [ "$status" -eq 1 ] || return "$status"
  fi

  records="$(custom_registry_records)" || return $?
  while IFS=$'\t' read -r existing_name existing_env existing_profile; do
    [ -n "$existing_name" ] || continue
    if [ "$existing_env" = "$env_name" ] && [ "$existing_profile" = "$profile" ]; then
      error "$env_name is already routed in $profile by $existing_name"
      return 2
    fi
  done <<< "$records"

  write_custom_registry_entry "$name" "$env_name" "$profile"
  info "registered $name -> $env_name ($profile); secret remains in Keychain only"
}

unregister_credential() {
  local name="${1:-}" record records temp_file service
  record="$(custom_credential_record "$name")" || {
    error "custom credential is not registered: ${name:-<missing>}"
    return 2
  }
  require_keychain
  service="$(keychain_service "$name")"
  security delete-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$service" \
    >/dev/null 2>&1 || true

  records="$(custom_registry_records)" || return $?
  temp_file="$(mktemp "$AUTH_CONFIG_DIR/.credentials.XXXXXX")"
  while IFS=$'\t' read -r registered_name registered_env registered_profile; do
    [ -n "$registered_name" ] || continue
    [ "$registered_name" = "$name" ] && continue
    printf '%s\t%s\t%s\n' "$registered_name" "$registered_env" \
      "$registered_profile" >> "$temp_file"
  done <<< "$records"
  chmod 600 "$temp_file"
  mv "$temp_file" "$CUSTOM_CREDENTIALS_FILE"
  info "unregistered $name and removed its Keychain entry"
}

credential_group_names() {
  local group="$1" records name env_name profile
  case "$group" in
    personal)
      printf '%s\n' exa figma-personal zeplin-personal atlassian-personal-ro
      ;;
    work)
      printf '%s\n' figma-work zeplin-work atlassian-work-ro
      ;;
    work-rw)
      printf '%s\n' atlassian-work-rw
      ;;
    all)
      printf '%s\n' exa figma-personal zeplin-personal atlassian-personal-ro \
        figma-work zeplin-work atlassian-work-ro
      ;;
    *) return 2 ;;
  esac

  records="$(custom_registry_records)" || return $?
  while IFS=$'\t' read -r name env_name profile; do
    [ -n "$name" ] || continue
    case "$group:$profile" in
      personal:personal-ro|work:work-ro|work-rw:work-rw|\
        all:personal-ro|all:work-ro)
        printf '%s\n' "$name"
        ;;
    esac
  done <<< "$records"
}

set_secret_group() {
  local group="$1" names name
  names="$(credential_group_names "$group")" || return $?
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    set_secret "$name"
  done <<< "$names"
  if [ "$group" = "all" ]; then
    info "work-rw remains explicit: dotfiles-auth set work-rw"
  fi
}

legacy_secret_names() {
  local file
  for file in "$HOME/.dev.secrets.env" "$HOME/.zshrc.local"; do
    [ -f "$file" ] || continue
    sed -nE 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/p' \
      "$file" 2>/dev/null || true
  done | sort -u
}

linkedin_session_present() {
  local profile_dir="$HOME/.linkedin-mcp/profile"
  [ -d "$profile_dir" ] && [ -n "$(ls -A "$profile_dir" 2>/dev/null)" ]
}

reddit_session_present() {
  [ -f "$HOME/.config/rdt-cli/credential.json" ]
}

social_session_status() {
  if command -v uvx >/dev/null 2>&1; then
    if linkedin_session_present; then
      printf '%-30s %s\n' "linkedin-session" "profile present"
    else
      printf '%-30s %s\n' "linkedin-session" "login required"
    fi
  else
    printf '%-30s %s\n' "linkedin-session" "client unavailable"
  fi

  if command -v twitter >/dev/null 2>&1; then
    printf '%-30s %s\n' "twitter-session" "browser-managed"
  else
    printf '%-30s %s\n' "twitter-session" "client unavailable"
  fi

  if command -v rdt >/dev/null 2>&1; then
    if reddit_session_present; then
      printf '%-30s %s\n' "reddit-session" "stored"
    else
      printf '%-30s %s\n' "reddit-session" "login required"
    fi
  else
    printf '%-30s %s\n' "reddit-session" "client unavailable"
  fi
}

catalog_env_token() {
  local name="$1" profile="$2" env_name service
  env_name="$(runtime_env_name "$name")"
  service="$(keychain_service "$name")"
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$name" "env-token" "$profile" "$env_name" "keychain:$service"
}

auth_catalog() {
  local records name env_name profile
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "name" "kind" "route" "binding" "store"

  catalog_env_token exa personal-ro
  catalog_env_token figma-personal personal-ro
  catalog_env_token figma-work work-ro
  catalog_env_token zeplin-personal personal-ro
  catalog_env_token zeplin-work work-ro
  catalog_env_token atlassian-personal-ro personal-ro
  catalog_env_token atlassian-work-ro work-ro
  catalog_env_token atlassian-work-rw work-rw

  records="$(custom_registry_records)" || return $?
  while IFS=$'\t' read -r name env_name profile; do
    [ -n "$name" ] || continue
    catalog_env_token "$name" "$profile"
  done <<< "$records"

  printf '%s\t%s\t%s\t%s\t%s\n' \
    "github-cli" "native-oauth" "unscoped" "-" "gh-managed" \
    "codex" "native-oauth" "unscoped" "-" "codex-managed" \
    "git-https" "native" "unscoped" "-" "git-credential-osxkeychain" \
    "git-ssh" "native" "unscoped" "-" "$HOME/.ssh + macOS Keychain" \
    "linkedin-session" "browser-session" "unscoped" "-" "$HOME/.linkedin-mcp/profile" \
    "twitter-session" "browser-session" "unscoped" "-" "signed-in local browser" \
    "reddit-session" "browser-session" "unscoped" "-" "$HOME/.config/rdt-cli/credential.json"
  printf '\ncustom-registry\t%s\n' "$CUSTOM_CREDENTIALS_FILE"
}

auth_status() {
  local name legacy records env_name profile
  require_keychain
  printf '%-30s %s\n' "credential" "state"
  printf '%-30s %s\n' "----------" "-----"
  for name in exa figma-personal figma-work zeplin-personal zeplin-work \
    atlassian-personal-ro atlassian-work-ro atlassian-work-rw; do
    if secret_is_stored "$name"; then
      printf '%-30s %s\n' "$name" "stored"
    else
      printf '%-30s %s\n' "$name" "not stored"
    fi
  done

  records="$(custom_registry_records)" || return $?
  while IFS=$'\t' read -r name env_name profile; do
    [ -n "$name" ] || continue
    if secret_is_stored "$name"; then
      printf '%-30s %s\n' "$name [$profile]" "stored"
    else
      printf '%-30s %s\n' "$name [$profile]" "not stored"
    fi
  done <<< "$records"

  if command -v gh >/dev/null 2>&1; then
    if gh auth status >/dev/null 2>&1; then
      printf '%-30s %s\n' "github-cli" "authenticated"
    else
      printf '%-30s %s\n' "github-cli" "login required"
    fi
  fi
  if command -v codex >/dev/null 2>&1; then
    if codex login status >/dev/null 2>&1; then
      printf '%-30s %s\n' "codex" "authenticated"
    else
      printf '%-30s %s\n' "codex" "login required"
    fi
  fi
  social_session_status

  legacy="$(legacy_secret_names)"
  if [ -n "$legacy" ]; then
    printf '\nLegacy shell secret declarations remain (values not read):\n'
    printf '%s\n' "$legacy" | sed 's/^/  /'
    printf 'Store their replacement with dotfiles-auth, then remove the old line.\n'
  fi
}

run_login() {
  local target="$1"
  case "$target" in
    git)
      command -v gh >/dev/null 2>&1 || { warn "gh is not installed"; return 0; }
      gh auth status >/dev/null 2>&1 || gh auth login --web --git-protocol https
      ;;
    codex)
      command -v codex >/dev/null 2>&1 || { warn "codex is not installed"; return 0; }
      codex login status >/dev/null 2>&1 || codex login
      ;;
    figma)
      command -v codex >/dev/null 2>&1 || { warn "codex is not installed"; return 0; }
      codex mcp login figma
      ;;
    atlassian-personal-ro|atlassian-work-ro)
      command -v codex >/dev/null 2>&1 || { warn "codex is not installed"; return 0; }
      codex mcp login "$target"
      ;;
    linkedin)
      command -v uvx >/dev/null 2>&1 || { warn "uvx is not installed"; return 0; }
      if linkedin_session_present; then
        info "LinkedIn browser profile is already present; validity is checked on use"
      else
        uvx mcp-server-linkedin@latest --login
      fi
      ;;
    twitter)
      command -v twitter >/dev/null 2>&1 || { warn "twitter is not installed"; return 0; }
      if twitter status >/dev/null 2>&1; then
        info "Twitter/X browser session is authenticated"
      else
        open_auth_page twitter-login
      fi
      ;;
    reddit)
      command -v rdt >/dev/null 2>&1 || { warn "rdt is not installed"; return 0; }
      if rdt status >/dev/null 2>&1; then
        info "Reddit browser session is authenticated"
      else
        rdt login
      fi
      ;;
    *)
      error "unknown login target: $target"
      return 2
      ;;
  esac
}

open_auth_page() {
  local target="$1" label url
  case "$target" in
    figma-token)
      label="Figma token settings"
      url="https://www.figma.com/settings"
      ;;
    zeplin-token)
      label="Zeplin developer settings"
      url="https://app.zeplin.io/profile/developer"
      ;;
    atlassian-token)
      label="Atlassian API token settings"
      url="https://id.atlassian.com/manage-profile/security/api-tokens"
      ;;
    twitter-login)
      label="X/Twitter login"
      url="https://x.com/login"
      ;;
    *)
      error "unknown browser page: $target"
      return 2
      ;;
  esac

  if ! command -v open >/dev/null 2>&1; then
    warn "Cannot open $label automatically: macOS open command is unavailable"
    return 0
  fi
  if open "$url"; then
    info "Opened $label"
  else
    warn "Could not open $label; open it manually: $url"
  fi
}

open_token_pages() {
  local profile_label="$1"
  open_auth_page figma-token
  open_auth_page zeplin-token
  open_auth_page atlassian-token
  info "Confirm the active browser account is the intended $profile_label identity before generating tokens"
}

setup_auth() {
  local scope="${1:-core}"
  case "$scope" in
    all)
      run_login git
      run_login codex
      run_login figma
      run_login atlassian-personal-ro
      run_login atlassian-work-ro
      run_login linkedin
      run_login twitter
      run_login reddit
      open_token_pages personal/work
      info "Store personal and work-read tokens with: dotfiles-auth set all"
      ;;
    core)
      run_login git
      run_login codex
      run_login figma
      ;;
    personal)
      run_login git
      run_login codex
      run_login figma
      run_login atlassian-personal-ro
      open_token_pages personal
      info "Store non-OAuth personal tokens with: dotfiles-auth set personal"
      ;;
    work)
      run_login codex
      run_login atlassian-work-ro
      open_token_pages work
      info "Store work collaboration tokens with: dotfiles-auth set work"
      ;;
    social)
      run_login linkedin
      run_login twitter
      run_login reddit
      info "Browser sessions stay in provider-owned local profiles, not shell variables"
      ;;
    *)
      error "unknown setup scope: $scope"
      return 2
      ;;
  esac
}

repo_profile() {
  local profile=""
  if [ -n "${DOTFILES_AUTH_PROFILE:-}" ]; then
    profile="$DOTFILES_AUTH_PROFILE"
  elif command -v git >/dev/null 2>&1 && \
      git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    profile="$(git config --local --get dotfiles.authProfile 2>/dev/null || true)"
  fi
  printf '%s\n' "${profile:-personal-ro}"
}

validate_profile() {
  case "$1" in
    personal-ro|work-ro|work-rw|none) ;;
    *)
      error "unknown auth profile: $1"
      return 2
      ;;
  esac
}

manage_profile() {
  local action="${1:-show}" profile="${2:-}"
  case "$action" in
    show)
      repo_profile
      ;;
    set)
      if [ "$profile" = "work-rw" ]; then
        error "work-rw is command-scoped; use: dotfiles-auth run work-rw -- <command>"
        return 2
      fi
      case "$profile" in
        personal-ro|work-ro|none) ;;
        *) error "profile set requires personal-ro, work-ro, or none"; return 2 ;;
      esac
      git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
        error "profile settings require a Git repository"
        return 2
      }
      git config --local dotfiles.authProfile "$profile"
      info "repository auth profile: $profile"
      ;;
    clear)
      git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
        error "profile settings require a Git repository"
        return 2
      }
      git config --local --unset-all dotfiles.authProfile 2>/dev/null || true
      info "repository auth profile cleared"
      ;;
    *) error "unknown profile action: $action"; return 2 ;;
  esac
}

append_secret_env() {
  local name="$1" env_name service value
  env_name="$(runtime_env_name "$name")"
  service="$(keychain_service "$name")"
  value="$(security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$service" -w \
    2>/dev/null)" || return 0
  [ -n "$value" ] || return 0
  SECRET_ENV+=("$env_name=$value")
}

append_custom_profile_env() {
  local wanted_profile="$1" records name env_name profile
  records="$(custom_registry_records)" || return $?
  while IFS=$'\t' read -r name env_name profile; do
    [ -n "$name" ] || continue
    [ "$profile" = "$wanted_profile" ] || continue
    append_secret_env "$name"
  done <<< "$records"
}

clear_managed_environment() {
  local records name env_name profile
  unset EXA_API_KEY FIGMA_API_KEY ZEPLIN_ACCESS_TOKEN \
    FIGMA_PERSONAL_API_KEY FIGMA_WORK_API_KEY \
    ZEPLIN_PERSONAL_ACCESS_TOKEN ZEPLIN_WORK_ACCESS_TOKEN \
    ATLASSIAN_PERSONAL_RO_AUTH ATLASSIAN_WORK_RO_AUTH ATLASSIAN_WORK_RW_AUTH
  records="$(custom_registry_records)" || return $?
  while IFS=$'\t' read -r name env_name profile; do
    [ -n "$name" ] || continue
    unset "$env_name"
  done <<< "$records"
}

run_with_profile() {
  local requested="${1:-auto}" profile
  shift || true
  [ "${1:-}" = "--" ] || {
    error "run requires -- before the command"
    return 2
  }
  shift
  [ "$#" -gt 0 ] || { error "run requires a command"; return 2; }

  if [ "$requested" = "auto" ]; then
    profile="$(repo_profile)"
  else
    profile="$requested"
  fi
  validate_profile "$profile"
  require_keychain

  SECRET_ENV=()
  case "$profile" in
    personal-ro)
      append_secret_env exa
      append_secret_env figma-personal
      append_secret_env zeplin-personal
      append_secret_env atlassian-personal-ro
      append_custom_profile_env personal-ro
      ;;
    work-ro)
      append_secret_env figma-work
      append_secret_env zeplin-work
      append_secret_env atlassian-work-ro
      append_custom_profile_env work-ro
      ;;
    work-rw)
      append_secret_env figma-work
      append_secret_env zeplin-work
      append_secret_env atlassian-work-rw
      append_custom_profile_env work-rw
      ;;
    none) ;;
  esac

  clear_managed_environment
  if [ "${#SECRET_ENV[@]}" -gt 0 ]; then
    export "${SECRET_ENV[@]}"
  fi
  exec "$@"
}

command_name="${1:-}"
case "$command_name" in
  status)
    shift
    [ "$#" -eq 0 ] || { usage >&2; exit 2; }
    auth_status
    ;;
  catalog)
    shift
    [ "$#" -eq 0 ] || { usage >&2; exit 2; }
    auth_catalog
    ;;
  setup)
    shift
    setup_auth "${1:-core}"
    ;;
  set)
    shift
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    case "$1" in
      all|personal|work|work-rw) set_secret_group "$1" ;;
      *) set_secret "$1" ;;
    esac
    ;;
  remove)
    shift
    remove_secret "${1:-}"
    ;;
  register)
    shift
    [ "$#" -eq 3 ] || { usage >&2; exit 2; }
    register_credential "$1" "$2" "$3"
    ;;
  unregister)
    shift
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    unregister_credential "$1"
    ;;
  profile)
    shift
    manage_profile "${1:-show}" "${2:-}"
    ;;
  run)
    shift
    run_with_profile "$@"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    error "unknown command: $command_name"
    usage >&2
    exit 2
    ;;
esac
