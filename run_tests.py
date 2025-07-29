#!/usr/bin/env python3
"""Test runner script for ToolProcessor behavior-driven specifications.

This script provides convenient ways to run the comprehensive test suite
with different configurations and reporting options.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n{'='*50}")
    print(f"🧪 {description}")
    print(f"{'='*50}")
    print(f"Running: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"\n❌ {description} failed with exit code {result.returncode}")
        return False
    else:
        print(f"\n✅ {description} completed successfully")
        return True


def install_dependencies():
    """Install test dependencies."""
    cmd = [sys.executable, "-m", "pip", "install", "-r", "tests/requirements.txt"]
    return run_command(cmd, "Installing test dependencies")


def run_tests(coverage=True, verbose=False, parallel=False, html_report=False, filter_expr=None):
    """Run the test suite with specified options."""
    cmd = [sys.executable, "-m", "pytest"]

    if verbose:
        cmd.append("-v")

    if coverage:
        cmd.extend(["--cov=tool_processor", "--cov-report=term-missing"])

    if html_report:
        cmd.append("--cov-report=html")

    if parallel:
        cmd.extend(["-n", "auto"])

    if filter_expr:
        cmd.extend(["-k", filter_expr])

    cmd.append("tests/")

    description = "Running ToolProcessor behavior-driven specifications"
    if filter_expr:
        description += f" (filtered: {filter_expr})"

    return run_command(cmd, description)


def run_linting():
    """Run code quality checks."""
    print("\n🔍 Running code quality checks...")

    # Check if flake8 is available
    try:
        subprocess.run([sys.executable, "-m", "flake8", "--version"],
                       capture_output=True, check=True)
        cmd = [sys.executable, "-m", "flake8", "tool_processor.py", "tests/"]
        if not run_command(cmd, "Code style check (flake8)"):
            return False
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  flake8 not installed, skipping style check")

    # Check if mypy is available
    try:
        subprocess.run([sys.executable, "-m", "mypy", "--version"],
                       capture_output=True, check=True)
        cmd = [sys.executable, "-m", "mypy", "tool_processor.py"]
        if not run_command(cmd, "Type check (mypy)"):
            return False
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  mypy not installed, skipping type check")

    return True


def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(
        description="Run ToolProcessor behavior-driven specifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py                     # Run all tests with coverage
  python run_tests.py --no-coverage       # Run tests without coverage
  python run_tests.py --verbose           # Run with verbose output
  python run_tests.py --parallel          # Run tests in parallel
  python run_tests.py --html              # Generate HTML coverage report
  python run_tests.py --filter "session"  # Run only session-related tests
  python run_tests.py --install-deps      # Install test dependencies
  python run_tests.py --lint              # Run code quality checks
  python run_tests.py --all               # Run everything (deps, lint, tests)
        """
    )

    parser.add_argument("--install-deps", action="store_true",
                        help="Install test dependencies")
    parser.add_argument("--no-coverage", action="store_true",
                        help="Skip coverage reporting")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--parallel", "-n", action="store_true",
                        help="Run tests in parallel")
    parser.add_argument("--html", action="store_true",
                        help="Generate HTML coverage report")
    parser.add_argument("--filter", "-k",
                        help="Filter tests by expression")
    parser.add_argument("--lint", action="store_true",
                        help="Run code quality checks")
    parser.add_argument("--all", action="store_true",
                        help="Run everything: install deps, lint, and tests")

    args = parser.parse_args()

    success = True

    # Handle --all flag
    if args.all:
        args.install_deps = True
        args.lint = True
        args.html = True

    # Install dependencies if requested
    if args.install_deps:
        if not install_dependencies():
            success = False

    # Run linting if requested
    if args.lint and success:
        if not run_linting():
            success = False

    # Run tests if no specific action requested or if --all
    if success and (not any([args.install_deps, args.lint]) or args.all):
        coverage = not args.no_coverage
        if not run_tests(
            coverage=coverage,
            verbose=args.verbose,
            parallel=args.parallel,
            html_report=args.html,
            filter_expr=args.filter
        ):
            success = False

    # Final summary
    print(f"\n{'='*50}")
    if success:
        print("🎉 All operations completed successfully!")
        if args.html:
            print("📊 HTML coverage report: htmlcov/index.html")
    else:
        print("💥 Some operations failed!")
        return 1
    print(f"{'='*50}\n")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
