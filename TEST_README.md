# Testing Ming Pao Archiver

## Running Tests

### Quick Start
```bash
./run_tests.sh
```

This will:
- Install development dependencies (pytest, pytest-cov, etc.)
- Run all tests with coverage report
- Generate HTML coverage report in `htmlcov/`

### Manual Test Running
```bash
# Install dependencies
uv pip install -e ".[dev]"

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=mingpao_hkga_archiver

# Run specific test file
uv run pytest tests/test_rate_limiter.py
uv run pytest tests/test_url_validation.py

# Run with verbose output
uv run pytest -v

# Run specific test
uv run pytest tests/test_rate_limiter.py::TestRateLimiter::test_rate_limiter_enforces_delay
```

## Test Coverage

Current test files:
- `test_rate_limiter.py` - Rate limiter functionality
- `test_url_validation.py` - URL validation and security
- `test_url_generation.py` - URL generation for dates
- `test_archiver.py` - Main archiver class (with mocking)
- `test_database.py` - Database operations

### Coverage Report
After running tests, view coverage:
```bash
open htmlcov/index.html
```

## Test Structure

All tests follow pytest conventions:
- Test files start with `test_`
- Test classes start with `Test`
- Test methods start with `test_`

### Fixtures
Tests use pytest fixtures for:
- Temporary configuration files
- Temporary databases
- Mocked archiver instances
- Isolated test environments

## Adding New Tests

When adding new features, add corresponding tests:

1. Create test file in `tests/` directory
2. Follow naming convention: `test_feature_name.py`
3. Use pytest fixtures for setup
4. Mock external dependencies (HTTP requests, etc.)
5. Assert expected behavior

Example:
```python
def test_new_feature():
    archiver = create_test_archiver()
    result = archiver.new_feature()
    assert result == expected_value
```

## CI/CD Integration

These tests can be integrated into GitHub Actions:
```yaml
- name: Run tests
  run: |
    pip install -e ".[dev]"
    pytest --cov=mingpao_hkga_archiver
```
