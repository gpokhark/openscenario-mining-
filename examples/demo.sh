#!/usr/bin/env bash
# Paced walkthrough for screen recording. Uses only the bundled sample: no cloning, no token.
#   bash examples/demo.sh              wait for Enter between steps (record with voiceover)
#   DEMO_AUTO=3 bash examples/demo.sh  pause 3 s between steps (for VHS / unattended runs)
#   DEMO_AUTO=0 bash examples/demo.sh  no pauses (quick check that everything runs)
set -u
cd "$(dirname "$0")/.."

SCM="uv run --extra parquet python -m scenariomine"
bold=$'\033[1m'; dim=$'\033[2m'; cyan=$'\033[36m'; reset=$'\033[0m'

pause() {
  if [ -n "${DEMO_AUTO:-}" ]; then sleep "$DEMO_AUTO"; else read -r -p "${dim}[Enter to continue]${reset} " _; fi
  echo
}
step() { clear 2>/dev/null || true; echo "${bold}${cyan}== $1${reset}"; echo "${dim}$2${reset}"; echo; }
run()  { echo "${bold}\$ $*${reset}"; "$@" 2>&1 | grep -v "^warning: .VIRTUAL_ENV"; echo; }
runq() { echo "${bold}\$ $1${reset}"; eval "$1" 2>&1 | grep -v "^warning: .VIRTUAL_ENV"; echo; }

step "1/5  The corpus in one command" "Bundled pilot sample: 5 repositories, full Git history of every .xosc file."
runq "uv run --extra parquet python examples/quickstart.py"
pause

step "2/5  Ask for a topic: pedestrian crossing" "Each hit shows the evidence that matched, the licence, and a permalink to the exact file version."
runq "$SCM find --data data/sample --topic pedestrian --publishable --limit 3"
pause

step "3/5  Another topic: cut-in" "Same command, different topic. Identical copies are collapsed into one hit."
runq "$SCM find --data data/sample --topic cut_in --publishable --limit 3"
pause

step "4/5  When the corpus cannot answer" "Speed bumps are an OpenDRIVE (road) feature. The tool says so instead of guessing."
runq "$SCM find --data data/sample --topic speed_bump --limit 3"
pause

step "5/5  Provenance and licence in machine-readable form" "--json feeds other tools and the Claude Code skill. (The sample holds only permissive repositories; pointer-only records appear in the full corpus.)"
runq "$SCM find --data data/sample --topic pedestrian --publishable --limit 1 --json | head -c 700; echo ' ...'"
echo "${bold}Repository:${reset} https://github.com/gpokhark/openscenario-mining-   (MIT)"
