#!/usr/bin/env python3
"""
Vector VRL Configuration Testing Tool

Tests Vector Remap Language (VRL) configurations against sample log data.
Fully generic - works with any Vector config and log format.

Usage:
  # Test with built-in samples (shows output structure)
  ./test-vector-config.py config.yaml

  # Test with custom samples from JSON file
  ./test-vector-config.py config.yaml --samples samples.json

Sample JSON format:
  [
    {
      "input": {"message": "log line", "field": "value"},
      "expect": {"field": "expected_value"} or null to expect drop
    }
  ]
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional


class VectorTester:
    """Test Vector VRL configurations with sample data."""

    VECTOR_IMAGE = "timberio/vector:0.50.0-alpine"

    def __init__(self, config_file: Path, verbose: bool = False):
        self.config_file = config_file
        self.verbose = verbose
        self.vrl_code = self._extract_vrl()

    def _extract_vrl(self) -> str:
        """Extract VRL transform code from Vector config."""
        with open(self.config_file) as f:
            content = f.read()

        in_source = False
        vrl_lines = []
        indent_level = None

        for line in content.split("\n"):
            stripped = line.lstrip()

            if "source:" in stripped and in_source:
                break

            if "source: |" in stripped:
                in_source = True
                indent_level = len(line) - len(stripped)
                continue

            if in_source:
                if stripped and not stripped.startswith("#"):
                    current_indent = len(line) - len(stripped)
                    if current_indent <= indent_level:
                        break
                    vrl_lines.append(line[indent_level + 2 :])
                elif not stripped:
                    vrl_lines.append("")

        if not vrl_lines:
            raise ValueError("No VRL source found in config")

        return "\n".join(vrl_lines)

    def test_sample(self, sample: Dict, expected: Optional[Dict] = None, name: str = "") -> bool:
        """Test a single log sample through VRL transformation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as event_file:
            json.dump(sample, event_file)
            event_path = event_file.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vrl", delete=False) as vrl_file:
            vrl_file.write(self.vrl_code)
            vrl_path = vrl_file.name

        try:
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{event_path}:/event.json",
                    "-v",
                    f"{vrl_path}:/program.vrl",
                    self.VECTOR_IMAGE,
                    "vrl",
                    "-i",
                    "/event.json",
                    "-p",
                    "/program.vrl",
                    "--print-object",
                ],
                capture_output=True,
                text=True,
            )

            # Handle aborted/dropped logs
            if "aborted" in result.stdout.lower() or "aborted" in result.stderr.lower():
                is_expected = expected is None
                status = "✓" if is_expected else "✗"
                desc = name or str(sample)[:60]
                print(f"  {status} Dropped: {desc}")
                return is_expected

            # Handle errors
            if result.returncode != 0 or "error" in result.stderr.lower():
                print(f"  ✗ VRL error: {result.stderr[:200]}")
                return False

            # Parse output
            output_lines = [line for line in result.stdout.split("\n") if line.strip() and not line.startswith("2025-")]
            if not output_lines:
                print(f"  ✗ No output")
                return False

            try:
                output = json.loads(output_lines[0])
            except json.JSONDecodeError:
                print(f"  ✗ Invalid JSON: {output_lines[0][:100]}")
                return False

            # Validate expectations if provided
            if expected:
                for key, value in expected.items():
                    if output.get(key) != value:
                        print(f"  ✗ {key}={output.get(key)!r} (expected {value!r})")
                        return False
                desc = name or ", ".join(f"{k}={v}" for k, v in expected.items())
                print(f"  ✓ {desc}")
            else:
                # No expectations - just show structure
                if self.verbose:
                    print(f"  ✓ Output:\n{json.dumps(output, indent=4)}")
                else:
                    fields = ", ".join(f"{k}={v!r}" for k, v in list(output.items())[:3])
                    print(f"  ✓ Fields: {fields}{'...' if len(output) > 3 else ''}")

            return True

        finally:
            Path(event_path).unlink(missing_ok=True)
            Path(vrl_path).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Test Vector VRL configurations",
        epilog="Supports both .yaml Vector configs and .vrl files directly.",
    )
    parser.add_argument("config", type=Path, help="Path to Vector config (.yaml) or VRL file (.vrl)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show full output JSON")
    parser.add_argument("-s", "--samples", type=Path, help="JSON file with test samples")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"File not found: {args.config}")
        sys.exit(1)

    # Direct .vrl file support
    if args.config.suffix == ".vrl":
        with open(args.config) as f:
            vrl_code = f.read()

        class DirectVRLTester(VectorTester):
            VECTOR_IMAGE = "timberio/vector:0.50.0-alpine"

            def __init__(self, vrl_code, verbose):
                self.config_file = args.config
                self.verbose = verbose
                self.vrl_code = vrl_code

        tester = DirectVRLTester(vrl_code, args.verbose)
    else:
        tester = VectorTester(args.config, args.verbose)

    # Auto-discover test samples following convention
    if not args.samples:
        # Convention: test-samples.json in same directory as config/vrl file
        auto_samples = args.config.parent / "test-samples.json"
        if auto_samples.exists():
            args.samples = auto_samples
            print(f"Auto-discovered: {auto_samples}")

    # Load samples or use generic default
    if args.samples:
        with open(args.samples) as f:
            samples = json.load(f)
    else:
        # Generic fallback - just shows structure
        samples = [{"message": "Sample log line"}]

    print(f"Testing {args.config.name}...")
    passed = 0
    failed = 0

    for idx, sample in enumerate(samples, 1):
        if isinstance(sample, dict) and "input" in sample:
            # Structured test with expectations
            success = tester.test_sample(sample["input"], sample.get("expect"), sample.get("name", f"test-{idx}"))
        else:
            # Simple input - just show what happens
            success = tester.test_sample(sample)

        if success:
            passed += 1
        else:
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
