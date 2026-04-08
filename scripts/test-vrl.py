#!/usr/bin/env python3
"""Test runner for Vector VRL parsers.

Discovers test fixtures in vrl/tests/*.json, matches each to its VRL parser
by filename convention, runs test cases through Vector, and compares output
against expected fields (subset match).

Adding a new parser test: create vrl/tests/<parser-name>.json matching
vrl/<parser-name>.vrl. No other files need modification.

Test file format (JSON array):
    [
      {
        "name": "descriptive-test-name",
        "input": { ... event fields ... },
        "expect": { ... subset of expected output fields ... }
      }
    ]

Usage:
    ./scripts/test-vrl.py              # Run all parser tests
    ./scripts/test-vrl.py talos        # Run only parse-talos tests
    ./scripts/test-vrl.py ceph talos   # Run parse-ceph and parse-talos tests
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VRL_DIR = REPO_ROOT / "kubernetes/apps/observability/victoria-logs-single/vrl"
TESTS_DIR = VRL_DIR / "tests"
VECTOR_IMAGE = "timberio/vector:0.54.0-alpine"

# Minimal Vector config template. The VRL file path is mounted at /vrl/prog.vrl;
# stdin source with JSON decoding feeds the remap transform, console sink emits
# clean JSON for comparison.
VECTOR_CONFIG = """\
sources:
  input:
    type: stdin
    decoding:
      codec: json
transforms:
  parser:
    type: remap
    inputs: [input]
    file: /vrl/prog.vrl
sinks:
  output:
    type: console
    inputs: [parser]
    encoding:
      codec: json
"""

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def run_vrl(vrl_file: Path, inputs: list[dict]) -> list[dict] | str:
    """Run inputs through a VRL program via Docker.

    Returns list of output dicts on success, or error string on failure.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as cfg:
        cfg.write(VECTOR_CONFIG)
        config_path = cfg.name

    try:
        input_lines = "\n".join(json.dumps(e) for e in inputs) + "\n"
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "-v",
                f"{vrl_file}:/vrl/prog.vrl:ro",
                "-v",
                f"{config_path}:/etc/vector/vector.yaml:ro",
                VECTOR_IMAGE,
            ],
            input=input_lines,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return f"Vector failed (exit {result.returncode}):\n{result.stderr}"

        outputs = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    outputs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return outputs
    finally:
        os.unlink(config_path)


def subset_match(actual: dict, expected: dict, path: str = "") -> list[str]:
    """Verify all expected fields exist in actual with matching values.

    Returns list of mismatch descriptions (empty = pass).
    """
    errors = []
    for key, exp_val in expected.items():
        full_key = f"{path}.{key}" if path else key
        if key not in actual:
            errors.append(f"missing: {full_key}")
            continue
        act_val = actual[key]
        if isinstance(exp_val, dict) and isinstance(act_val, dict):
            errors.extend(subset_match(act_val, exp_val, full_key))
        elif act_val != exp_val:
            errors.append(
                f"{full_key}: expected {json.dumps(exp_val)}, got {json.dumps(act_val)}"
            )
    return errors


def run_tests(test_file: Path, vrl_file: Path) -> tuple[int, int]:
    """Run all test cases from a test file. Returns (passed, failed)."""
    with open(test_file) as f:
        cases = json.load(f)

    inputs = [case["input"] for case in cases]
    result = run_vrl(vrl_file, inputs)

    if isinstance(result, str):
        print(f"  {RED}ERROR{RESET} {result}")
        return 0, len(cases)

    if len(result) != len(cases):
        print(f"  {RED}ERROR{RESET} expected {len(cases)} outputs, got {len(result)}")
        return 0, len(cases)

    passed = 0
    failed = 0
    for case, actual in zip(cases, result):
        name = case["name"]
        expected = case["expect"]
        errors = subset_match(actual, expected)
        if errors:
            print(f"  {RED}FAIL{RESET} {name}")
            for err in errors:
                print(f"       {err}")
            failed += 1
        else:
            print(f"  {GREEN}PASS{RESET} {name}")
            passed += 1

    return passed, failed


def main():
    filters = sys.argv[1:] if len(sys.argv) > 1 else []

    if not TESTS_DIR.exists():
        print(f"{RED}Tests directory not found: {TESTS_DIR}{RESET}")
        sys.exit(1)

    test_files = sorted(TESTS_DIR.glob("*.json"))
    if filters:
        test_files = [f for f in test_files if any(filt in f.stem for filt in filters)]

    if not test_files:
        print(f"{YELLOW}No matching test files in {TESTS_DIR}{RESET}")
        sys.exit(1)

    total_passed = 0
    total_failed = 0

    for test_file in test_files:
        parser_name = test_file.stem
        vrl_file = VRL_DIR / f"{parser_name}.vrl"
        if not vrl_file.exists():
            print(f"{YELLOW}Skip{RESET} {test_file.name}: no {parser_name}.vrl")
            continue

        print(f"\n{BOLD}{parser_name}{RESET}")
        passed, failed = run_tests(test_file, vrl_file)
        total_passed += passed
        total_failed += failed

    print(f"\n{BOLD}Results:{RESET} {GREEN}{total_passed} passed{RESET}", end="")
    if total_failed:
        print(f", {RED}{total_failed} failed{RESET}")
    else:
        print()

    sys.exit(1 if total_failed else 0)


if __name__ == "__main__":
    main()
