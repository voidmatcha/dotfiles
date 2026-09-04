# RTK - Rust Token Killer

**Usage**: Compress noisy command output before transcript ingress. Automatic
rewrites are kept only where they have demonstrated value; the resulting RTK
analytics are a directional estimate, not verified token or billing savings.

## Meta Commands (always use rtk directly)

```bash
rtk gain              # Show RTK's estimated output reduction
rtk gain --history    # Show command history with RTK estimates
rtk discover          # Analyze Claude Code history for missed opportunities
rtk proxy <cmd>       # Bypass one RTK command filter
rtk read -l aggressive <file>  # Explicit lossy structural overview
```

## Installation Verification

```bash
rtk --version         # Should show: rtk X.Y.Z
rtk gain              # Should run (treat its numbers as estimates)
which rtk             # Verify correct binary
```

⚠️ **Name collision**: If `rtk gain` fails, you may have reachingforthejack/rtk (Rust Type Kit) installed instead.

## Hook policy

The Claude Code hook keeps useful search rewrites such as `grep` and `rg`.
`cat/head/tail` are excluded: RTK's default `read -l none` returns full content,
so those rewrites add no demonstrated reduction. Use native reads for exact
content. Invoke `rtk read -l aggressive` only when a lossy structural overview
is acceptable.

For byte-exact comparisons, redirect raw output to a temporary file and inspect
that file directly. `rtk proxy` is a bypass mechanism, not by itself proof that
the surrounding transcript preserved every byte.

Refer to README.md for the shared agent/tooling overview and command reference.
