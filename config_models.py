#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration models with Pydantic validation

Provides type-safe configuration management:
- Automatic validation of config values
- Clear error messages for invalid configs
- Default values and type conversion
- Nested configuration support
"""

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, validator


class LoggingConfig(BaseModel):
    """Logging configuration"""

    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    file: str = Field(default="logs/hkga_archiver.log", min_length=1)


class DatabaseConfig(BaseModel):
    """Database configuration"""

    path: str = Field(default="hkga_archive.db", min_length=1)


class ArchivingConfig(BaseModel):
    """Archiving operation configuration"""

    rate_limit_delay: float = Field(default=3.0, gt=0, le=60)
    verify_first: bool = Field(default=False)
    timeout: int = Field(default=30, gt=0, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay: int = Field(default=10, gt=0, le=60)


class KeywordsConfig(BaseModel):
    """Keyword filtering configuration"""

    enabled: bool = Field(default=False)
    terms: List[str] = Field(default=[])
    case_sensitive: bool = Field(default=False)
    language: str = Field(default="zh-TW", pattern="^(zh-TW|zh-CN|en)$")
    script: str = Field(default="traditional", pattern="^(traditional|simplified)$")
    normalization: str = Field(default="NFC", pattern="^(NFC|NFD|NFKC|NFKD)$")
    logic: str = Field(default="or", pattern="^(or|and)$")
    search_content: bool = Field(default=False)
    parallel_workers: int = Field(default=2, ge=1, le=10)
    wayback_first: bool = Field(default=True)

    @validator("terms")
    def validate_terms(cls, v):
        if not v:
            raise ValueError("Keyword terms cannot be empty when keywords are enabled")
        return v


class ParallelConfig(BaseModel):
    """Parallel processing configuration"""

    enabled: bool = Field(default=False)
    max_workers: int = Field(default=2, ge=1, le=20)
    rate_limit_delay: float = Field(default=3.0, gt=0, le=60)


class DateRangeConfig(BaseModel):
    """Date range configuration"""

    start: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")

    @validator("end")
    def validate_date_range(cls, v, values):
        if "start" in values:
            from datetime import datetime

            start_date = datetime.strptime(values["start"], "%Y-%m-%d")
            end_date = datetime.strptime(v, "%Y-%m-%d")
            if end_date < start_date:
                raise ValueError("End date must be after start date")
        return v


class MingPaoConfig(BaseModel):
    """Main configuration model for Ming Pao archiver"""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    archiving: ArchivingConfig = Field(default_factory=ArchivingConfig)
    keywords: KeywordsConfig = Field(default_factory=KeywordsConfig)
    parallel: ParallelConfig = Field(default_factory=ParallelConfig)

    daily_limit: int = Field(default=2000, ge=1, le=10000)
    use_newspaper: bool = Field(default=False)
    use_newspaper4k_titles: bool = Field(default=False)
    use_index_page: bool = Field(default=True)
    date_range: Optional[DateRangeConfig] = None

    @validator("keywords")
    def validate_keywords_config(cls, v, values):
        if v.enabled and not v.terms:
            raise ValueError("Keyword terms must be provided when keywords are enabled")
        return v

    @classmethod
    def load_from_file(cls, config_path: str) -> "MingPaoConfig":
        """
        Load configuration from JSON file with validation

        Args:
            config_path: Path to configuration file

        Returns:
            Validated MingPaoConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValidationError: If config is invalid
        """
        import json
        from pathlib import Path

        config_file = Path(config_path)

        if not config_file.exists():
            # Return default config if file doesn't exist
            return cls()

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            return cls(**config_data)

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise ValueError(f"Error loading config file: {e}")

    def save_to_file(self, config_path: str) -> bool:
        """
        Save configuration to JSON file

        Args:
            config_path: Path to save configuration

        Returns:
            True if successful, False otherwise
        """
        import json
        from pathlib import Path

        try:
            config_file = Path(config_path)
            config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(self.dict(), f, indent=2, ensure_ascii=False)

            return True
        except Exception:
            return False

    def merge_with_file(self, config_path: str) -> "MingPaoConfig":
        """
        Merge current config with file config (file overrides)

        Args:
            config_path: Path to configuration file

        Returns:
            New merged configuration
        """
        try:
            file_config = self.load_from_file(config_path)
            current_dict = self.dict()
            file_dict = file_config.dict()

            # Deep merge file config over current
            self._deep_merge(current_dict, file_dict)

            return MingPaoConfig(**current_dict)
        except FileNotFoundError:
            # File doesn't exist, return current config
            return self

    def _deep_merge(self, base_dict: Dict, update_dict: Dict):
        """Recursively merge update_dict into base_dict"""
        for key, value in update_dict.items():
            if (
                key in base_dict
                and isinstance(base_dict[key], dict)
                and isinstance(value, dict)
            ):
                self._deep_merge(base_dict[key], value)
            else:
                base_dict[key] = value

    def get_effective_date_range(self) -> Optional[DateRangeConfig]:
        """Get effective date range from config or defaults"""
        if self.date_range:
            return self.date_range

        # Return a default date range if none specified
        from datetime import datetime, timedelta

        today = datetime.now()
        start_date = today - timedelta(days=7)
        end_date = today

        return DateRangeConfig(
            start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d")
        )

    def is_keywords_enabled(self) -> bool:
        """Check if keyword filtering is enabled"""
        return self.keywords.enabled and bool(self.keywords.terms)

    def is_parallel_enabled(self) -> bool:
        """Check if parallel processing is enabled"""
        return self.parallel.enabled

    def get_rate_limit_delay(self) -> float:
        """Get effective rate limit delay for archiving"""
        if self.keywords.enabled and not self.keywords.search_content:
            # Use parallel rate limit for title-only filtering
            return self.parallel.rate_limit_delay
        else:
            # Use archiving rate limit for content search
            return self.archiving.rate_limit_delay


class ConfigValidator:
    """Utility class for configuration validation"""

    @staticmethod
    def validate_config_file(config_path: str) -> Dict[str, Any]:
        """
        Validate configuration file and return detailed errors

        Args:
            config_path: Path to configuration file

        Returns:
            Dictionary with validation results
        """
        result = {"valid": False, "config": None, "errors": [], "warnings": []}

        try:
            config = MingPaoConfig.load_from_file(config_path)
            result["valid"] = True
            result["config"] = config

            # Add warnings for potentially problematic settings
            if config.archiving.rate_limit_delay < 2:
                result["warnings"].append(
                    "Rate limit delay < 2 seconds may trigger rate limiting"
                )

            if config.daily_limit > 5000:
                result["warnings"].append(
                    "Daily limit > 5000 may cause performance issues"
                )

            if config.keywords.enabled and len(config.keywords.terms) > 20:
                result["warnings"].append(
                    "More than 20 keywords may slow down filtering"
                )

        except FileNotFoundError:
            result["errors"].append(f"Configuration file not found: {config_path}")
        except ValueError as e:
            result["errors"].append(f"Configuration error: {e}")
        except Exception as e:
            result["errors"].append(f"Unexpected error: {e}")

        return result

    @staticmethod
    def create_sample_config(output_path: str) -> bool:
        """
        Create a sample configuration file

        Args:
            output_path: Path to save sample config

        Returns:
            True if successful, False otherwise
        """
        sample_config = MingPaoConfig()

        # Add some example values
        sample_config.keywords.terms = ["香港", "政治", "中國"]
        sample_config.date_range = DateRangeConfig(start="2025-01-01", end="2025-01-31")

        return sample_config.save_to_file(output_path)


# Backward compatibility function
def load_config(config_path: str = "config.json") -> Dict:
    """
    Load configuration for backward compatibility

    Returns the raw dictionary format for existing code
    """
    try:
        config = MingPaoConfig.load_from_file(config_path)
        return config.dict()
    except Exception:
        # Fallback to basic default config
        return MingPaoConfig().dict()
