#!/bin/bash
# Test runner for Ming Pao Archiver

echo "🧪 Running Ming Pao Archiver Test Suite"
echo "================================================"

# Install dev dependencies if not already installed
echo "📦 Installing dev dependencies..."
uv pip install -e ".[dev]" -q

# Run tests with coverage
echo ""
echo "🏃 Running tests with coverage..."
uv run pytest "$@"

# Store exit code
EXIT_CODE=$?

# Show results summary
if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ All tests passed!"
else
    echo ""
    echo "❌ Some tests failed. Exit code: $EXIT_CODE"
fi

exit $EXIT_CODE
