#!/bin/bash
set -euo pipefail

# LaunchAgent has a minimal PATH; restore tmux + node + the global npm bin dir.
# nvm installs Node under ~/.nvm/versions/node/<ver>/bin. Fold in EVERY installed
# version's bin (highest first), not just the latest, so a version-specific
# global `purplemux` is found no matter which Node it was installed under. Also
# fold in the global npm prefix bin for non-nvm (brew/system) Node installs.
build_purplemux_path() {
  export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
  if [ -d "$HOME/.nvm/versions/node" ]; then
    local ver dir
    while IFS= read -r ver; do
      [ -n "$ver" ] || continue
      dir="$HOME/.nvm/versions/node/$ver/bin"
      if [ -d "$dir" ]; then
        PATH="$dir:$PATH"
      fi
    done < <(find "$HOME/.nvm/versions/node" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort -V)
    export PATH
  fi
  if command -v npm >/dev/null 2>&1; then
    local npm_prefix npm_bin
    # `|| true`: at early login npm can be resolvable while its node backend
    # is not ready yet; without the guard, set -e would abort the launcher
    # right here — before the retry loop this function exists to serve.
    npm_prefix="$(npm prefix -g 2>/dev/null || true)"
    npm_bin="${npm_prefix:+$npm_prefix/bin}"
    if [ -n "$npm_bin" ] && [ -d "$npm_bin" ]; then
      case ":$PATH:" in
        *":$npm_bin:"*) ;;
        *) export PATH="$npm_bin:$PATH" ;;
      esac
    fi
  fi
  return 0
}
build_purplemux_path
if [ -z "${PURPLEMUX_GIT_PATH:-}" ] && git_path="$(command -v git 2>/dev/null)"; then
  export PURPLEMUX_GIT_PATH="$git_path"
elif [ -n "${PURPLEMUX_GIT_PATH:-}" ]; then
  export PURPLEMUX_GIT_PATH
fi
# Intentionally do NOT fabricate a default PURPLEMUX_GIT_VERSION: the hook only
# short-circuits `git --version` when an operator sets it explicitly. Otherwise
# real git runs (via the resolved PURPLEMUX_GIT_PATH redirect), so a future
# purplemux/dep that does in-process git detection gets the true version.

# At early login the node/brew symlinks this wrapper relies on may not be ready
# yet, so `purplemux` can be transiently unresolvable. An immediate exit 78 left
# the LaunchAgent flapping (KeepAlive only re-runs it every ThrottleInterval=60s,
# so startup could lag minutes). Rebuild PATH and retry briefly before giving up.
attempt=0
max_attempts="${PURPLEMUX_RESOLVE_ATTEMPTS:-10}"
# Non-integer override would make `-ge` error (status 2, treated as false),
# turning the bail-out branch unreachable and the loop infinite.
case "$max_attempts" in
  ''|*[!0-9]*) max_attempts=10 ;;
esac
until command -v purplemux >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "[purplemux] purplemux not found in PATH after $attempt attempts — install with 'npm install -g purplemux'" >&2
    exit 78
  fi
  sleep 3
  build_purplemux_path
done

# purplemux 0.4.x resolves the user's PATH by spawning `/bin/zsh -ilc
# 'echo -n "$PATH"'` during startup. Under launchd that child can stay stuck
# before the HTTP listener is created, leaving the LaunchAgent "running" but
# with nothing bound to :8022. Keep launchd startup deterministic by answering
# that exact PATH probe from the already-restored wrapper PATH.
hook_dir="$HOME/.local/share/dotfiles"
hook_path="$hook_dir/purplemux-launch-hook.cjs"
mkdir -p "$hook_dir"
cat > "$hook_path.tmp" <<'NODE'
'use strict';

const child_process = require('child_process');
const { EventEmitter } = require('events');
const { PassThrough } = require('stream');
const { promisify } = require('util');

const originalExecFile = child_process.execFile;
const originalPromisified = originalExecFile[promisify.custom];

function isPathProbe(file, args) {
  return (
    Array.isArray(args) &&
    /(^|\/)(zsh|bash|sh)$/.test(String(file)) &&
    args.includes('-ilc') &&
    args.includes('echo -n "$PATH"')
  );
}

function resolvedGitPath(file) {
  const gitPath = process.env.PURPLEMUX_GIT_PATH || '';
  if (String(file) !== 'git' || !gitPath || gitPath === 'git') {
    return null;
  }
  return gitPath;
}

function resolvedGitVersion(file, args) {
  if (!resolvedGitPath(file) || !Array.isArray(args) || args.length !== 1 || args[0] !== '--version') {
    return null;
  }
  return process.env.PURPLEMUX_GIT_VERSION || null;
}

function fakeChildProcess(stdoutText = '') {
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.pid = process.pid;
  child.killed = false;
  child.exitCode = 0;
  child.signalCode = null;
  child.kill = () => {
    child.killed = true;
    return true;
  };
  child.ref = () => child;
  child.unref = () => child;
  process.nextTick(() => {
    child.stdout.end(stdoutText);
    child.stderr.end();
    child.emit('exit', 0, null);
    child.emit('close', 0, null);
  });
  return child;
}

function callbackFrom(args, options, callback) {
  if (typeof callback === 'function') return callback;
  if (typeof options === 'function') return options;
  if (typeof args === 'function') return args;
  return null;
}

function patchedExecFile(file, args, options, callback) {
  if (isPathProbe(file, args)) {
    const cb = callbackFrom(args, options, callback);
    if (cb) {
      process.nextTick(() => cb(null, process.env.PATH || '', ''));
    }
    return fakeChildProcess();
  }
  const gitVersion = resolvedGitVersion(file, args);
  if (gitVersion) {
    const cb = callbackFrom(args, options, callback);
    if (cb) {
      process.nextTick(() => cb(null, `${gitVersion}\n`, ''));
    }
    return fakeChildProcess(`${gitVersion}\n`);
  }
  const gitPath = resolvedGitPath(file);
  if (gitPath) {
    const nextArgs = Array.from(arguments);
    nextArgs[0] = gitPath;
    return originalExecFile.apply(this, nextArgs);
  }
  return originalExecFile.apply(this, arguments);
}

patchedExecFile[promisify.custom] = function patchedExecFilePromise(file, args, options) {
  if (isPathProbe(file, args)) {
    return Promise.resolve({ stdout: process.env.PATH || '', stderr: '' });
  }
  const gitVersion = resolvedGitVersion(file, args);
  if (gitVersion) {
    return Promise.resolve({ stdout: `${gitVersion}\n`, stderr: '' });
  }
  const gitPath = resolvedGitPath(file);
  if (gitPath) {
    if (originalPromisified) {
      return originalPromisified.call(this, gitPath, args, options);
    }
    return promisify(originalExecFile).call(this, gitPath, args, options);
  }
  if (originalPromisified) {
    return originalPromisified.call(this, file, args, options);
  }
  return promisify(originalExecFile).call(this, file, args, options);
};

child_process.execFile = patchedExecFile;
NODE
mv "$hook_path.tmp" "$hook_path"

case " ${NODE_OPTIONS:-} " in
  *" --require=$hook_path "*) ;;
  *) export NODE_OPTIONS="--require=$hook_path${NODE_OPTIONS:+ $NODE_OPTIONS}" ;;
esac

# Run purplemux under the node it was installed with: its `#!/usr/bin/env node`
# shebang resolves node from PATH, which after the multi-version fold above may
# name a newer node than the install's own. Prefer the node sitting next to the
# resolved purplemux (an nvm version bin or the brew prefix) so native deps and
# spawned node/npm children stay on the matching install.
purplemux_bin="$(command -v purplemux)"
purplemux_dir="$(dirname "$purplemux_bin")"
if [ -x "$purplemux_dir/node" ]; then
  export PATH="$purplemux_dir:$PATH"
fi

# purplemux listens on :8022. services.sh exposes it through Tailscale Serve:
# tailscale serve --bg --https=443 --set-path=/ http://localhost:8022
exec "$purplemux_bin"
