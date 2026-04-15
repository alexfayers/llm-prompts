#!/usr/bin/env sh
set -e

REPO="git+https://github.com/alexfayers/llm-prompts.git"

# Install uv if not available
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "Installing llm-prompts..."
uv tool install "$REPO" --force

echo "Creating default config..."
llm-prompts setup --init >/dev/null 2>&1 || true

echo ""
echo "Done! Edit ~/.config/llm-prompts/config.toml to customise, then run:"
echo "  llm-prompts install {agent}    # kiro, cline, copilot, or all"
