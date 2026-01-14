#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration validation utility

Usage:
    python validate_config.py [--create-sample] [--check config.json]
"""

import argparse
import sys
from pathlib import Path

# Add current directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from config_models import ConfigValidator
except ImportError as e:
    print(f"Error importing config models: {e}")
    print("Please install pydantic: pip install pydantic>=2.0.0")
    sys.exit(1)


def validate_config_file(config_path: str):
    """Validate a configuration file"""
    print(f"Validating configuration: {config_path}")
    print("=" * 50)

    result = ConfigValidator.validate_config_file(config_path)

    if result["valid"]:
        print("✅ Configuration is valid!")
        config = result["config"]

        # Show summary
        print(f"📁 Database path: {config.database.path}")
        print(f"📝 Log level: {config.logging.level}")
        print(f"⏱️ Rate limit delay: {config.archiving.rate_limit_delay}s")
        print(f"📊 Daily limit: {config.daily_limit}")
        print(f"🔍 Keywords enabled: {config.keywords.enabled}")
        print(f"🔧 Parallel enabled: {config.parallel.enabled}")

        if config.date_range:
            print(
                f"📅 Date range: {config.date_range.start} to {config.date_range.end}"
            )

        if result["warnings"]:
            print("\n⚠️ Warnings:")
            for warning in result["warnings"]:
                print(f"  - {warning}")
    else:
        print("❌ Configuration validation failed!")
        print("\nErrors:")
        for error in result["errors"]:
            print(f"  - {error}")

    return result["valid"]


def create_sample_config(output_path: str):
    """Create a sample configuration file"""
    print(f"Creating sample configuration: {output_path}")

    if ConfigValidator.create_sample_config(output_path):
        print("✅ Sample configuration created successfully!")
        print(f"📝 Edit {output_path} to customize settings")
    else:
        print("❌ Failed to create sample configuration")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Ming Pao Configuration Validator")
    parser.add_argument(
        "--create-sample", metavar="PATH", help="Create a sample configuration file"
    )
    parser.add_argument(
        "--check",
        metavar="CONFIG_FILE",
        default="config.json",
        help="Validate configuration file (default: config.json)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show detailed validation output"
    )

    args = parser.parse_args()

    if args.create_sample:
        create_sample_config(args.create_sample)
    else:
        success = validate_config_file(args.check)
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
