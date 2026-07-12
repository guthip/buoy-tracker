#!/bin/sh
# Legacy-code sweep: finds the categories of rot that hide from tests.
# Run from the repo root:  tools/lint_legacy.sh
# Human judgment required on the output — some hits are false positives
# (paho callback signatures, compat re-exports, string-built class names).
set -e
PY=${PY:-venv/bin/python3}

echo "=== 1. Dead Python (vulture) ==============================="
$PY -m vulture src/ --min-confidence 80 2>/dev/null || echo "(pip install vulture)"

echo ""
echo "=== 2. Hard-coded colors in JS (design-system violations) ==="
grep -noE "#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b|'white'|'black'" static/app.js | head -40
echo "(map-layer Leaflet colors are tolerated; UI element colors are not)"

echo ""
echo "=== 3. Inline style writes in JS (should be class/token) ===="
grep -nE "\.style\.[a-zA-Z]+ *=" static/app.js | grep -viE "width|height|display|left|top|transform" | head -20

echo ""
echo "=== 4. JS functions with no callers ========================="
$PY - <<'PYEOF'
import re
js = open('static/app.js').read()
html = open('templates/simple.html').read()
defs = set(re.findall(r'function ([A-Za-z_$][\w$]*)\s*\(', js) +
           re.findall(r'window\.([A-Za-z_$][\w$]*)\s*=\s*function', js))
for name in sorted(defs):
    refs = len(re.findall(rf'\b{re.escape(name)}\b', js + html))
    d = len(re.findall(rf'function {re.escape(name)}\b|window\.{re.escape(name)}\s*=', js))
    if refs <= d:
        print(' ', name)
PYEOF

echo ""
echo "=== 5. CSS classes with no emitter =========================="
$PY - <<'PYEOF'
import re
css = open('static/style.css').read()
js = open('static/app.js').read() + open('templates/simple.html').read()
allow = {'leaflet-tile','leaflet-popup-content-wrapper','leaflet-popup-tip',
         'leaflet-tooltip-custom','dragging','expanded','chip-batt','chip-fix','chip-heard',
         'chip-fill-y','chip-fill-r','batt-g','batt-y','batt-r','batt-n'}
for c in sorted(set(re.findall(r'\.([a-z][\w-]+)', css))):
    if c in allow: continue
    if not re.search(rf"['\" ]{re.escape(c)}[ '\"<]|class=\"[^\"]*{re.escape(c)}", js):
        print(' ', c)
PYEOF

echo ""
echo "=== 6. Docs referencing endpoints that don't exist =========="
for ep in $(grep -oE 'api/[a-z/_-]+' README.md DOCKER.md 2>/dev/null | cut -d: -f2 | sort -u); do
  grep -q "$ep" src/main.py || echo "  $ep (in docs, not in routes)"
done

echo ""
echo "=== 7. Duplicate code blocks in Python (pylint) =============="
echo "(catches literal copy-paste; two functions doing the same job in"
echo " different words — e.g. send_movement_alert/send_battery_alert"
echo " before 2026-07-12 — won't show up here and need a human read)"
$PY -m pylint --disable=all --enable=duplicate-code src/ 2>/dev/null || echo "(pip install pylint)"
