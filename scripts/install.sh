#!/usr/bin/env bash
SCRIPT_DIR=$( cd -- "$( dirname -- "$(readlink -f "${BASH_SOURCE[0]}")" )" &> /dev/null && pwd )
ROOT_DIR=$(dirname "$SCRIPT_DIR")

AGENTS_DIR="$HOME/.agents"

log() {
    local levels=(debug info warn error success) i
    for i in "${!levels[@]}"; do [[ "${levels[i]}" == "$1" ]] && break; done
    [[ "${levels[i]}" != "$1" ]] && { >&2 echo "Unknown level: $1"; return 1; }
    if [ -t 2 ]; then
        local c=("\033[0;90m" "\033[0;37m" "\033[0;33m" "\033[0;31m" "\033[0;32m") p=("⚙︎" "▶" "⚠︎" "✗" "✓")
        >&2 echo -e "${c[i]}${p[i]} $2\033[0;0m"
    else
        local p=("[.]" "[*]" "[-]" "[!]" "[+]")
        >&2 echo "${p[i]} $2"
    fi
}

# Install skills
for skill in "$ROOT_DIR/skills/"*; do
    if [ -d "$skill" ]; then
        skill_name=$(basename "$skill")

        if [ -L "$AGENTS_DIR/skills/$skill_name" ]; then
            log warn "Skill '$skill_name' is already installed. Skipping."
            continue
        fi

        if ! ln -s "$skill" "$AGENTS_DIR/skills/$skill_name"; then
            log error "Failed to install skill: $skill_name"
            continue
        fi
        log success "Installed skill: $skill_name"
    fi
done
