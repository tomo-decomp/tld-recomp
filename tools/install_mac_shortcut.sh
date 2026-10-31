#!/bin/bash
# Puts "Jogar TLD.command" on the desktop: a double-click rebuilds what changed and starts the game.
cd "$(dirname "$0")/.." || exit 1
pwd > "$HOME/.tldrecomp_repo"
cp "Jogar TLD.command" "$HOME/Desktop/Jogar TLD.command"
chmod +x "$HOME/Desktop/Jogar TLD.command" "Jogar TLD.command"
xattr -d com.apple.quarantine "$HOME/Desktop/Jogar TLD.command" 2>/dev/null
echo "Shortcut on the desktop: Jogar TLD.command"
