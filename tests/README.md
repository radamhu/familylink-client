# Tests

Comprehensive test suite for the familylink package.

## Structure

```
tests/
├── conftest.py              # Shared fixtures and test configuration
├── fixtures/                # Sample data for testing
│   ├── sample_config.csv    # Sample CSV config
│   ├── mock_api_responses.json  # Mock API responses
│   └── cookies_sample.txt   # Sample cookies file
├── unit/                    # Unit tests (isolated, fast)
│   ├── test_client.py       # Client logic tests
│   ├── test_models.py       # Pydantic model tests
│   └── test_cli.py          # CLI parsing tests
├── integration/             # Integration tests (component interaction)
│   ├── test_client_integration.py  # Client + auth methods
│   └── test_cli_integration.py     # CLI + config loading
├── smoke/                   # Smoke tests (basic functionality)
│   ├── test_import.py       # Package import tests
│   └── test_cli_help.py     # CLI help command
└── e2e/                     # End-to-end tests (full workflows)
    └── test_e2e_workflow.py # Complete user workflows
```

## Running Tests

### Local Interactive Runner
```bash
# Interactive menu
python scripts/run_tests.py

# Or direct execution
python scripts/run_tests.py --suite all -v
python scripts/run_tests.py --suite unit
python scripts/run_tests.py --suite lint
```

### Manual Pytest
```bash
# All tests
uv run pytest

# Specific suite
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
uv run pytest tests/smoke/ -v
uv run pytest tests/e2e/ -v

# With coverage
uv run pytest --cov=src/familylink --cov-report=html

# Single test file
uv run pytest tests/unit/test_client.py -v
```

### CI Pipeline
The GitHub Actions workflow (`.github/workflows/ci.yml`) runs:
1. Lint & Format Check (Ruff)
2. Type Check (MyPy)
3. Unit Tests (Python 3.10, 3.11, 3.12)
4. Integration Tests
5. Smoke Tests
6. E2E Tests
7. Coverage Report (80% threshold)

## Test Categories

### 🔬 Unit Tests
- Test individual functions/methods in isolation
- Mock all external dependencies (HTTP, filesystem)
- Fast execution (<1s per test)
- Focus: Business logic correctness

### 🔗 Integration Tests
- Test interaction between components
- Mock only external APIs
- Moderate execution time
- Focus: Component contracts

### 💨 Smoke Tests
- Basic "does it work" checks
- Package imports, CLI help
- Very fast execution
- Focus: Critical paths functional

### 🌍 E2E Tests
- Complete user workflows
- Mocked API responses
- Slower execution
- Focus: Real-world scenarios

## Coverage

Minimum coverage: **80%**

View coverage report:
```bash
uv run pytest --cov=src/familylink --cov-report=html
open htmlcov/index.html
```

## Dependencies

Test dependencies are defined in `pyproject.toml`:
- `pytest`: Test framework
- `pytest-cov`: Coverage reporting
- `pytest-mock`: Mocking utilities
- `pytest-httpx`: HTTP mocking
- `freezegun`: Time mocking
- `mypy`: Type checking
