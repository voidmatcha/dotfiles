#!/bin/bash
set -euo pipefail

# LaunchAgent has a minimal PATH; restore tmux + node + the global npm bin dir.
# nvm installs Node under ~/.nvm/versions/node/<ver>/bin — we resolve the latest
# installed version at runtime so this keeps working across Node upgrades.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if [ -d "$HOME/.nvm/versions/node" ]; then
  latest_node="$(find "$HOME/.nvm/versions/node" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort -V | tail -n1 || true)"
  if [ -n "$latest_node" ] && [ -d "$HOME/.nvm/versions/node/$latest_node/bin" ]; then
    export PATH="$HOME/.nvm/versions/node/$latest_node/bin:$PATH"
  fi
fi
if [ -z "${PURPLEMUX_GIT_PATH:-}" ] && git_path="$(command -v git 2>/dev/null)"; then
  export PURPLEMUX_GIT_PATH="$git_path"
elif [ -n "${PURPLEMUX_GIT_PATH:-}" ]; then
  export PURPLEMUX_GIT_PATH
fi
# Intentionally do NOT fabricate a default PURPLEMUX_GIT_VERSION: the hook only
# short-circuits `git --version` when an operator sets it explicitly. Otherwise
# real git runs (via the resolved PURPLEMUX_GIT_PATH redirect), so a future
# purplemux/dep that does in-process git detection gets the true version.

if ! command -v purplemux >/dev/null 2>&1; then
  echo "[purplemux] purplemux not found in PATH — install with 'npm install -g purplemux'" >&2
  exit 78
fi

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

# purplemux listens on :8022. services.sh exposes it through Tailscale Serve:
# tailscale serve --bg --https=443 --set-path=/ http://localhost:8022
exec purplemux
