# ── Taps ──
tap "anomalyco/tap"
tap "oven-sh/bun"

# ── CLI tools ──
brew "git"
brew "git-filter-repo"           # surgical rewrites of git history (author, paths, etc.)
brew "gh"
brew "uv"                        # Astral's fast Python package/tool installer (used by serena)
brew "curl"
brew "wget"
brew "jq"                       # JSON parser/filter
brew "gettext"                  # envsubst — used by install.sh to render MCP template
brew "tree"                     # directory tree viewer
brew "htop"                     # system monitor (top replacement)
brew "ripgrep"                  # fast grep replacement
brew "fd"                       # friendlier find replacement
brew "bat"                      # cat with syntax highlighting
brew "git-delta"                # syntax-highlighted git diff/blame viewer
brew "eza"                      # ls with icons and colors
brew "fzf"                      # fuzzy finder (Ctrl+R etc.)
brew "atuin"                    # SQLite-backed shell history with sync
brew "direnv"                   # auto-load per-directory env from .envrc
brew "zoxide"                   # smarter cd with directory learning
brew "rtk"                      # CLI proxy for 60-90% LLM token savings
brew "mkcert"
brew "whisper-cpp"
brew "tmux"                     # terminal multiplexer
brew "mosh"                     # mobile shell — resilient UDP terminal sessions over SSH (survives roaming/disconnects)
brew "vercel-cli"               # Vercel deployment CLI
brew "postgresql"               # PostgreSQL database
brew "mole"
brew "bats-core"                # Bash Automated Testing System
brew "pipx"                     # isolated Python CLI installer (used for twitter-cli, rdt-cli)
brew "oven-sh/bun/bun"          # Bun JS runtime — required by claude-mem@thedotmack hooks (scripts/bun-runner.js)
brew "yt-dlp"                   # YouTube/Bilibili/1800+ sites — metadata + subtitle extraction
brew "anomalyco/tap/opencode"   # AI coding agent (third-party tap; tracks latest)
brew "code-server"              # VS Code in browser (auto-launched via LaunchAgent)
brew "docker"                   # docker CLI only (no Docker Desktop). Pair with Rancher Desktop or similar engine on hosts with licensing restrictions.
brew "mas"                      # Mac App Store CLI


# ── GUI apps (Cask) ──
cask "google-chrome"
cask "visual-studio-code"
cask "slack"
cask "notion"
cask "obsidian"
cask "microsoft-teams"
cask "discord"
cask "figma"
cask "raycast"
cask "karabiner-elements"
cask "rectangle"
cask "claude-code"
cask "cursor"
cask "zoom"
cask "keka"                     # file archiver
cask "cmux"                     # Ghostty-based terminal for AI coding agents
cask "tailscale-app"            # private mesh VPN for remote access (cask renamed from "tailscale" in 2025)

# ── VS Code extensions ──
vscode "alefragnani.bookmarks"
vscode "anthropic.claude-code"
vscode "arcanis.vscode-zipfs"
vscode "clinyong.vscode-css-modules"
vscode "dbaeumer.vscode-eslint"
vscode "eamodio.gitlens"
vscode "editorconfig.editorconfig"
vscode "esbenp.prettier-vscode"
vscode "formulahendry.auto-close-tag"
vscode "formulahendry.auto-complete-tag"
vscode "formulahendry.auto-rename-tag"
vscode "formulahendry.code-runner"
vscode "github.vscode-github-actions"
vscode "gruntfuggly.todo-tree"
vscode "henrynguyen5-vsc.vsc-nvm"
vscode "lottiefiles.vscode-lottie"
vscode "mechatroner.rainbow-csv"
vscode "ms-playwright.playwright"
vscode "rangav.vscode-thunder-client"
vscode "redhat.vscode-yaml"
vscode "ritwickdey.liveserver"
vscode "shd101wyy.markdown-preview-enhanced"
vscode "sibiraj-s.vscode-scss-formatter"
vscode "streetsidesoftware.code-spell-checker"
vscode "stylelint.vscode-stylelint"
vscode "unifiedjs.vscode-mdx"
vscode "vincaslt.highlight-matching-tag"
vscode "usernamehw.errorlens"
vscode "wix.vscode-import-cost"
vscode "vitest.explorer"
vscode "christian-kohler.npm-intellisense"
vscode "mkxml.vscode-filesize"
vscode "tomoki1207.pdf"
vscode "vscode-icons-team.vscode-icons"

# ── Mac App Store apps (managed via mas) ──
# Re-generate with: mas list | awk '{id=$1; $1=""; sub(/^ /,""); name=$0; sub(/ +\([^)]+\) *$/,"",name); printf "mas \"%s\", id: %s\n", name, id}'
