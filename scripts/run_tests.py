#!/usr/bin/env python3
"""Interactive test runner for familylink package.

Mirrors the CI pipeline locally, allowing developers to run tests on-demand
with full control over which test suites to execute.
"""

import argparse
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import List

# Terminal colors
class Color:
    """ANSI color codes for terminal output."""

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


class TestSuite(str, Enum):
    """Available test suites."""

    LINT = "lint"
    FORMAT = "format"
    TYPECHECK = "typecheck"
    UNIT = "unit"
    INTEGRATION = "integration"
    SMOKE = "smoke"
    E2E = "e2e"
    COVERAGE = "coverage"
    ALL = "all"


def print_header(message: str) -> None:
    """Print a formatted header."""
    print(f"\n{Color.BOLD}{Color.HEADER}{'=' * 70}{Color.ENDC}")
    print(f"{Color.BOLD}{Color.HEADER}{message.center(70)}{Color.ENDC}")
    print(f"{Color.BOLD}{Color.HEADER}{'=' * 70}{Color.ENDC}\n")


def print_step(message: str) -> None:
    """Print a step message."""
    print(f"{Color.OKCYAN}▶ {message}{Color.ENDC}")


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"{Color.OKGREEN}✓ {message}{Color.ENDC}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"{Color.FAIL}✗ {message}{Color.ENDC}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{Color.WARNING}⚠ {message}{Color.ENDC}")


def run_command(cmd: List[str], description: str) -> bool:
    """Run a command and return success status.

    Args:
        cmd: Command to run as list of strings
        description: Human-readable description of the command

    Returns:
        True if command succeeded, False otherwise
    """
    print_step(f"{description}...")
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=False,
            text=True,
        )
        print_success(f"{description} completed")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"{description} failed with exit code {e.returncode}")
        return False
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        print_warning("Make sure dependencies are installed: uv sync --group test")
        return False


def run_lint() -> bool:
    """Run linting checks."""
    print_header("LINT CHECK")
    return run_command(["uv", "run", "ruff", "check", "."], "Ruff linter")


def run_format_check() -> bool:
    """Run format checks."""
    print_header("FORMAT CHECK")
    return run_command(
        ["uv", "run", "ruff", "format", "--check", "."], "Ruff formatter check"
    )


def run_typecheck() -> bool:
    """Run type checking."""
    print_header("TYPE CHECK")
    return run_command(
        [
            "uv",
            "run",
            "mypy",
            "src/familylink",
            "--ignore-missing-imports",
            "--check-untyped-defs",
        ],
        "MyPy type checker",
    )


def run_unit_tests(verbose: bool = False) -> bool:
    """Run unit tests."""
    print_header("UNIT TESTS")
    cmd = ["uv", "run", "pytest", "tests/unit/"]
    if verbose:
        cmd.append("-v")
    cmd.extend(["--cov=src/familylink", "--cov-report=term"])
    return run_command(cmd, "Unit tests")


def run_integration_tests(verbose: bool = False) -> bool:
    """Run integration tests."""
    print_header("INTEGRATION TESTS")
    cmd = ["uv", "run", "pytest", "tests/integration/"]
    if verbose:
        cmd.append("-v")
    return run_command(cmd, "Integration tests")


def run_smoke_tests(verbose: bool = False) -> bool:
    """Run smoke tests."""
    print_header("SMOKE TESTS")
    cmd = ["uv", "run", "pytest", "tests/smoke/"]
    if verbose:
        cmd.append("-v")
    return run_command(cmd, "Smoke tests")


def run_e2e_tests(verbose: bool = False) -> bool:
    """Run E2E tests."""
    print_header("E2E TESTS")
    cmd = ["uv", "run", "pytest", "tests/e2e/"]
    if verbose:
        cmd.append("-v")
    return run_command(cmd, "E2E tests")


def run_coverage_report(fail_under: int = 80) -> bool:
    """Run all tests with coverage report."""
    print_header("FULL COVERAGE REPORT")
    cmd = [
        "uv",
        "run",
        "pytest",
        "tests/",
        "-v",
        "--cov=src/familylink",
        "--cov-report=html",
        "--cov-report=term",
        f"--cov-fail-under={fail_under}",
    ]
    success = run_command(cmd, "Full test suite with coverage")
    if success:
        print_success(f"Coverage report generated: htmlcov/index.html")
    return success


def run_all_tests(verbose: bool = False, fail_under: int = 80) -> bool:
    """Run all test suites in sequence."""
    print_header("FULL CI PIPELINE")

    results = {
        "Lint": run_lint(),
        "Format": run_format_check(),
        "Type Check": run_typecheck(),
        "Unit Tests": run_unit_tests(verbose),
        "Integration Tests": run_integration_tests(verbose),
        "Smoke Tests": run_smoke_tests(verbose),
        "E2E Tests": run_e2e_tests(verbose),
        "Coverage": run_coverage_report(fail_under),
    }

    # Summary
    print_header("TEST SUMMARY")
    all_passed = True
    for name, passed in results.items():
        if passed:
            print_success(f"{name}: PASSED")
        else:
            print_error(f"{name}: FAILED")
            all_passed = False

    return all_passed


def interactive_menu() -> None:
    """Display interactive menu for test selection."""
    print_header("FAMILYLINK TEST RUNNER")
    print("Select test suite to run:\n")
    print(f"  {Color.OKCYAN}1{Color.ENDC} - Lint & Format Check")
    print(f"  {Color.OKCYAN}2{Color.ENDC} - Type Check")
    print(f"  {Color.OKCYAN}3{Color.ENDC} - Unit Tests")
    print(f"  {Color.OKCYAN}4{Color.ENDC} - Integration Tests")
    print(f"  {Color.OKCYAN}5{Color.ENDC} - Smoke Tests")
    print(f"  {Color.OKCYAN}6{Color.ENDC} - E2E Tests")
    print(f"  {Color.OKCYAN}7{Color.ENDC} - Full Coverage Report")
    print(f"  {Color.OKCYAN}8{Color.ENDC} - Run ALL (Full CI Pipeline)")
    print(f"  {Color.OKCYAN}0{Color.ENDC} - Exit\n")

    try:
        choice = input(f"{Color.BOLD}Enter your choice [0-8]: {Color.ENDC}")

        suite_map = {
            "1": lambda: run_lint() and run_format_check(),
            "2": run_typecheck,
            "3": lambda: run_unit_tests(verbose=True),
            "4": lambda: run_integration_tests(verbose=True),
            "5": lambda: run_smoke_tests(verbose=True),
            "6": lambda: run_e2e_tests(verbose=True),
            "7": lambda: run_coverage_report(fail_under=80),
            "8": lambda: run_all_tests(verbose=True, fail_under=80),
            "0": lambda: sys.exit(0),
        }

        if choice in suite_map:
            success = suite_map[choice]()
            if success:
                print_success("\n✓ All checks passed!")
                return
            else:
                print_error("\n✗ Some checks failed!")
                sys.exit(1)
        else:
            print_error("Invalid choice!")
            sys.exit(1)

    except KeyboardInterrupt:
        print(f"\n\n{Color.WARNING}Interrupted by user{Color.ENDC}")
        sys.exit(130)


def main() -> None:
    """Main entry point for test runner."""
    parser = argparse.ArgumentParser(
        description="Interactive test runner mirroring CI pipeline"
    )
    parser.add_argument(
        "--suite",
        type=str,
        choices=[s.value for s in TestSuite],
        help="Test suite to run (skips interactive menu)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose test output",
    )
    parser.add_argument(
        "--fail-under",
        type=int,
        default=80,
        help="Minimum coverage percentage (default: 80)",
    )

    args = parser.parse_args()

    # Change to project root
    project_root = Path(__file__).parent.parent
    import os

    os.chdir(project_root)

    # Non-interactive mode
    if args.suite:
        suite_runners = {
            TestSuite.LINT: lambda: run_lint() and run_format_check(),
            TestSuite.FORMAT: run_format_check,
            TestSuite.TYPECHECK: run_typecheck,
            TestSuite.UNIT: lambda: run_unit_tests(args.verbose),
            TestSuite.INTEGRATION: lambda: run_integration_tests(args.verbose),
            TestSuite.SMOKE: lambda: run_smoke_tests(args.verbose),
            TestSuite.E2E: lambda: run_e2e_tests(args.verbose),
            TestSuite.COVERAGE: lambda: run_coverage_report(args.fail_under),
            TestSuite.ALL: lambda: run_all_tests(args.verbose, args.fail_under),
        }

        success = suite_runners[TestSuite(args.suite)]()
        sys.exit(0 if success else 1)

    # Interactive mode
    interactive_menu()


if __name__ == "__main__":
    main()
