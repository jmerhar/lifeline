#!/usr/bin/env bash

# inspect.sh
# Runs IntelliJ IDEA CLI inspections offline and reports any issues found.
# Uses an idea.properties workaround to run alongside an open IDE instance.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSPECT_CMD="/Applications/IntelliJ IDEA.app/Contents/bin/inspect.sh"
PROFILE="$PROJECT_DIR/.idea/inspectionProfiles/Project_Default.xml"
XML_DIR="$PROJECT_DIR/inspect/xml"
IDEA_TMP="$PROJECT_DIR/inspect/idea"

if [[ ! -f "$INSPECT_CMD" ]]; then
    echo "Error: IntelliJ IDEA not found at $INSPECT_CMD"
    exit 1
fi

# --- Create idea.properties to isolate from running IDE ---
# Only system and log paths need isolation (lock files, caches). The config path
# is left at its default so the headless instance shares the same plugins, SDKs,
# and settings as the running IDE — producing identical inspection results.
IDEA_PROPS="$(mktemp)"
cat > "$IDEA_PROPS" <<EOF
idea.system.path=$IDEA_TMP/system
idea.log.path=$IDEA_TMP/log
EOF
export IDEA_PROPERTIES="$IDEA_PROPS"

cleanup() {
    rm -f "$IDEA_PROPS"
}
trap cleanup EXIT

# --- Prepare output directories ---
rm -rf "$XML_DIR" "$IDEA_TMP"
mkdir -p "$XML_DIR"

# --- Run inspections (XML output) ---
echo "Running IntelliJ inspections..."
"$INSPECT_CMD" "$PROJECT_DIR" "$PROFILE" "$XML_DIR" -v0 2>/dev/null

# --- Report issues ---
ISSUE_FILES=("$XML_DIR"/*.xml)
if [[ -e "${ISSUE_FILES[0]}" ]]; then
    echo ""
    echo "Found ${#ISSUE_FILES[@]} inspection file(s) with issues:"
    for f in "${ISSUE_FILES[@]}"; do
        echo "  $(basename "$f")"
    done
    exit 1
else
    echo "No inspection issues found."
fi
