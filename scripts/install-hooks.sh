#!/bin/sh
# Run this once after cloning to install git hooks.
HOOKS_DIR="$(git rev-parse --git-dir)/hooks"

cat > "$HOOKS_DIR/pre-push" << 'HOOK'
#!/bin/sh
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
  exit 0
fi
echo "Running tests before push to main..."
python -m pytest tests/ -x --tb=short -q
STATUS=$?
if [ $STATUS -ne 0 ]; then
  echo ""
  echo "ERROR: Tests failed. Push blocked."
  exit 1
fi
echo "All tests passed. Proceeding with push."
exit 0
HOOK

chmod +x "$HOOKS_DIR/pre-push"
echo "pre-push hook installed at $HOOKS_DIR/pre-push"
