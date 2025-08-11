#!/usr/bin/env python3

import sys
import yaml
from pathlib import Path
from jsonpath_ng import parse
from typing import List, Dict, Any, Optional, Union
import argparse


class YamlValidator:
    def __init__(self, config_file: str = ".yaml-validator.yaml"):
        self.config_file = config_file
        self.config = self._load_config()
        self.errors = []

    def _load_config(self) -> Dict[str, Any]:
        """Load validation configuration from file."""
        config_path = Path(self.config_file)
        if not config_path.exists():
            print(f"Error: Configuration file {self.config_file} not found")
            sys.exit(1)

        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"Error: Invalid YAML in {self.config_file}: {e}")
            sys.exit(1)

    def _find_yaml_files(self, directory: str = "kubernetes") -> List[Path]:
        """Find all YAML files in the specified directory recursively."""
        base_path = Path(directory)
        if not base_path.exists():
            return []

        yaml_files = []
        for pattern in ["*.yaml", "*.yml"]:
            yaml_files.extend(base_path.rglob(pattern))

        return yaml_files

    def _load_yaml_documents(self, file_path: Path) -> List[Dict[str, Any]]:
        """Load all YAML documents from a file, handling multi-document files."""
        try:
            with open(file_path, 'r') as f:
                documents = list(yaml.safe_load_all(f))
                # Filter out None documents (empty sections)
                return [doc for doc in documents if doc is not None]
        except yaml.YAMLError as e:
            print(f"Warning: Could not parse {file_path}: {e}")
            return []
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}")
            return []

    def _evaluate_jsonpath(self, document: Dict[str, Any], path: str) -> List[Any]:
        """Evaluate a JSONPath expression against a document."""
        try:
            jsonpath_expr = parse(path)
            matches = jsonpath_expr.find(document)
            return [match.value for match in matches]
        except Exception as e:
            # JSONPath parsing failed - path might not exist in document
            return []

    def _check_condition(self, document: Dict[str, Any], condition: Dict[str, Any]) -> bool:
        """Check if a single condition passes for a document."""
        path = condition.get('path')
        expected_value = condition.get('value')

        if not path:
            return False

        matches = self._evaluate_jsonpath(document, path)

        # If no matches found, condition fails
        if not matches:
            return False

        # Check if all matches have the expected value
        if expected_value is not None:
            return all(match == expected_value for match in matches)

        # If no expected value specified, just check that path exists
        return len(matches) > 0

    def _check_when_conditions(self, document: Dict[str, Any], when_conditions: List[Dict[str, Any]]) -> bool:
        """Check if all 'when' conditions are met."""
        return all(self._check_condition(document, condition) for condition in when_conditions)

    def _validate_rule(self, document: Dict[str, Any], rule: Dict[str, Any], file_path: Path) -> List[str]:
        """Validate a single rule against a document."""
        rule_errors = []

        # Check if rule applies to this document
        applies_to = rule.get('applies_to', {})
        if 'kind' in applies_to:
            doc_kind = document.get('kind')
            if doc_kind != applies_to['kind']:
                return rule_errors  # Rule doesn't apply

        rule_name = rule.get('name', 'Unnamed rule')

        # Handle conditional logic (when/then)
        if 'when' in rule and 'then' in rule:
            when_conditions = rule['when']
            if self._check_when_conditions(document, when_conditions):
                # When conditions met, check then conditions
                then_conditions = rule['then']
                for condition in then_conditions:
                    if not self._check_condition(document, condition):
                        rule_errors.append(
                            f"{file_path}: {rule_name} - Condition failed: {condition['path']} "
                            f"should be {condition.get('value', 'present')}"
                        )

        # Handle unconditional checks
        if 'conditions' in rule:
            conditions = rule['conditions']
            for condition in conditions:
                if not self._check_condition(document, condition):
                    rule_errors.append(
                        f"{file_path}: {rule_name} - Condition failed: {condition['path']} "
                        f"should be {condition.get('value', 'present')}"
                    )

        return rule_errors

    def validate_files(self, files: Optional[List[str]] = None, use_stdin: bool = False) -> bool:
        """Validate specified files, stdin, or all YAML files in kubernetes directory."""
        if use_stdin:
            return self._validate_stdin()

        if files:
            yaml_files = [Path(f) for f in files if Path(f).exists()]
        else:
            yaml_files = self._find_yaml_files()

        if not yaml_files:
            print("No YAML files found to validate")
            return True

        rules = self.config.get('rules', [])
        if not rules:
            print("No validation rules configured")
            return True

        total_errors = []

        for file_path in yaml_files:
            documents = self._load_yaml_documents(file_path)

            for document in documents:
                for rule in rules:
                    errors = self._validate_rule(document, rule, file_path)
                    total_errors.extend(errors)

        # Print all errors
        if total_errors:
            print("\nYAML Validation Errors:")
            for error in total_errors:
                print(f"  ❌ {error}")
            print(f"\nFound {len(total_errors)} validation error(s)")
            return False
        else:
            print(f"✅ All {len(yaml_files)} YAML files passed validation")
            return True

    def _validate_stdin(self) -> bool:
        """Validate YAML data from stdin."""
        try:
            stdin_content = sys.stdin.read()
            if not stdin_content.strip():
                print("No YAML data provided on stdin")
                return True

            documents = list(yaml.safe_load_all(stdin_content))
            documents = [doc for doc in documents if doc is not None]

            if not documents:
                print("No valid YAML documents found in stdin")
                return True

            rules = self.config.get('rules', [])
            if not rules:
                print("No validation rules configured")
                return True

            total_errors = []

            for i, document in enumerate(documents):
                for rule in rules:
                    errors = self._validate_rule(document, rule, Path(f"<stdin-doc-{i}>"))
                    total_errors.extend(errors)

            # Print all errors
            if total_errors:
                print("\nYAML Validation Errors:")
                for error in total_errors:
                    print(f"  ❌ {error}")
                print(f"\nFound {len(total_errors)} validation error(s)")
                return False
            else:
                print(f"✅ All {len(documents)} YAML document(s) from stdin passed validation")
                return True

        except yaml.YAMLError as e:
            print(f"Error: Invalid YAML in stdin: {e}")
            return False
        except Exception as e:
            print(f"Error reading from stdin: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Validate YAML files against configuration rules")
    parser.add_argument("files", nargs="*", help="Specific files to validate (default: all in kubernetes/)")
    parser.add_argument("--config", "-c", default=".yaml-validator.yaml",
                       help="Configuration file (default: .yaml-validator.yaml)")
    parser.add_argument("--stdin", action="store_true",
                       help="Read YAML data from stdin instead of files")

    args = parser.parse_args()

    validator = YamlValidator(args.config)
    success = validator.validate_files(args.files, use_stdin=args.stdin)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
