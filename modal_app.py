"""
Modal deployment for Ming Pao Canada HK-GA Archiver

Deploys the archiver as a serverless function with:
- HTTP API endpoints for manual triggering
- Persistent volume for SQLite database
- Statistics endpoint for monitoring

Usage:
    # Deploy to Modal
    modal deploy modal_app.py

    # Test locally
    modal run modal_app.py

    # View logs
    modal logs mingpao-archiver
"""

import modal
import sys
from pathlib import Path
from typing import Optional

# Create Modal app
app = modal.App("mingpao-archiver")

# Create persistent volume for database
volume = modal.Volume.from_name("mingpao-db", create_if_missing=True)

# Define container image with dependencies and local files
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "requests>=2.31.0",
        "newspaper4k>=0.9.0",
        "pydantic>=2.0.0",
        "fastapi[standard]",
    )
    # Add local Python files into image
    .add_local_file("mingpao_hkga_archiver.py", "/root/mingpao_hkga_archiver.py")
    .add_local_file(
        "mingpao_archiver_refactored.py", "/root/mingpao_archiver_refactored.py"
    )
    .add_local_file("url_generator.py", "/root/url_generator.py")
    .add_local_file("wayback_archiver.py", "/root/wayback_archiver.py")
    .add_local_file("keyword_filter.py", "/root/keyword_filter.py")
    .add_local_file("database_repository.py", "/root/database_repository.py")
    .add_local_file("config_models.py", "/root/config_models.py")
    .add_local_file("archiving_strategies.py", "/root/archiving_strategies.py")
    .add_local_file("config.json", "/root/config.json")
)


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=86400,  # 24 hours for large jobs
    cpu=1,
)
@modal.fastapi_endpoint(method="POST")
def archive_articles(request_data: dict):
    """
    HTTP endpoint to trigger archiving

    Request body (JSON):
    {
        "mode": "date" | "range" | "backdays",
        "date": "2026-01-13",           # For mode=date
        "start": "2026-01-01",          # For mode=range
        "end": "2026-01-31",            # For mode=range
        "backdays": 7,                  # For mode=backdays
        "keywords": ["香港", "政治"],   # Optional
        "daily_limit": 2000             # Optional
    }

    Returns:
    {
        "status": "success" | "error",
        "mode": "date" | "range" | "backdays",
        "result": {...},
        "stats": {...}
    }
    """
    import json
    from datetime import datetime, timedelta

    # Import refactored archiver (copied into image)
    sys.path.insert(0, "/root")
    from mingpao_archiver_refactored import MingPaoArchiver, parse_date

    # Update config to use persistent volume
    config_path = Path("/root/config.json")
    with open(config_path, "r") as f:
        config = json.load(f)

    # Override paths to use volume
    config["database"]["path"] = "/data/hkga_archive.db"
    config["logging"]["file"] = "/data/logs/hkga_archiver.log"

    # Create logs directory in volume
    import os

    os.makedirs("/data/logs", exist_ok=True)

    # Save modified config
    temp_config = "/tmp/modal_config.json"
    with open(temp_config, "w") as f:
        json.dump(config, f)

    # Create archiver instance
    archiver = MingPaoArchiver(temp_config)

    # Apply request parameters
    mode = request_data.get("mode", "date")

    if request_data.get("keywords"):
        archiver.config["keywords"]["enabled"] = True
        archiver.config["keywords"]["terms"] = request_data["keywords"]

    if request_data.get("daily_limit"):
        archiver.config["daily_limit"] = request_data["daily_limit"]

    # Execute archiving
    try:
        if mode == "date":
            if "date" not in request_data:
                return {
                    "status": "error",
                    "error": "Missing 'date' parameter for mode='date'",
                }, 400

            date = parse_date(request_data["date"])
            result = archiver.archive_date(date)

        elif mode == "range":
            if "start" not in request_data or "end" not in request_data:
                return {
                    "status": "error",
                    "error": "Missing 'start' or 'end' parameter for mode='range'",
                }, 400

            start = parse_date(request_data["start"])
            end = parse_date(request_data["end"])
            result = archiver.archive_date_range(start, end)

        elif mode == "backdays":
            if "backdays" not in request_data:
                return {
                    "status": "error",
                    "error": "Missing 'backdays' parameter for mode='backdays'",
                }, 400

            backdays = request_data["backdays"]
            end_date = datetime.now()
            start_date = end_date - timedelta(days=backdays - 1)
            result = archiver.archive_date_range(start_date, end_date)

        else:
            return {
                "status": "error",
                "error": f"Invalid mode: {mode}",
                "valid_modes": ["date", "range", "backdays"],
            }, 400

        # Commit volume changes
        volume.commit()

        # Return success response
        return {
            "status": "success",
            "mode": mode,
            "result": result,
            "stats": archiver.stats,
        }

    except Exception as e:
        import traceback

        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }, 500

    finally:
        archiver.close()


@app.function(
    image=image,
    volumes={"/data": volume},
)
@modal.fastapi_endpoint(method="GET")
def get_stats():
    """
    Get archiving statistics from database

    Returns summary of archived articles, recent activity, and database stats
    """
    import sqlite3

    db_path = "/data/hkga_archive.db"

    try:
        # Check if database exists
        import os

        if not os.path.exists(db_path):
            return {
                "status": "empty",
                "message": "No database found. Run archiving first.",
                "total_articles": 0,
                "successful": 0,
                "days_processed": 0,
            }

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Total articles
        cursor.execute("SELECT COUNT(*) FROM archive_records")
        total = cursor.fetchone()[0]

        # Count by status type
        cursor.execute("""
            SELECT status, COUNT(*) 
            FROM archive_records 
            GROUP BY status
        """)
        status_counts = dict(cursor.fetchall())

        # Successful = 'success' (newly archived) + 'exists' (already in Wayback)
        success = status_counts.get("success", 0)
        exists = status_counts.get("exists", 0)
        archived_total = success + exists  # Total articles in Wayback

        # Failed = all failure types
        failed = status_counts.get("failed", 0)
        error = status_counts.get("error", 0)
        timeout = status_counts.get("timeout", 0)
        rate_limited = status_counts.get("rate_limited", 0)
        unknown = status_counts.get("unknown", 0)
        failed_total = failed + error + timeout + rate_limited + unknown

        # Days processed
        cursor.execute("SELECT COUNT(*) FROM daily_progress")
        days = cursor.fetchone()[0]

        # Recent archives (last 10)
        cursor.execute("""
            SELECT article_url, archive_date, status, article_title
            FROM archive_records
            ORDER BY created_at DESC
            LIMIT 10
        """)
        recent = cursor.fetchall()

        # Recent days processed
        cursor.execute("""
            SELECT date, articles_found, articles_archived, articles_failed
            FROM daily_progress
            ORDER BY date DESC
            LIMIT 5
        """)
        recent_days = cursor.fetchall()

        conn.close()

        return {
            "status": "success",
            "total_articles": total,
            "archived": archived_total,  # success + exists
            "failed": failed_total,  # all failure types
            "success_rate": f"{(archived_total / total * 100):.1f}%"
            if total > 0
            else "0%",
            "days_processed": days,
            "breakdown": {
                "success": success,  # Newly archived this run
                "exists": exists,  # Already in Wayback
                "failed": failed,  # HTTP error
                "error": error,  # Exception
                "timeout": timeout,  # Timeout
                "rate_limited": rate_limited,  # 403
                "unknown": unknown,  # Unknown status
            },
            "recent_archives": [
                {"url": r[0], "date": r[1], "status": r[2], "title": r[3]}
                for r in recent
            ],
            "recent_days": [
                {"date": d[0], "found": d[1], "archived": d[2], "failed": d[3]}
                for d in recent_days
            ],
        }

    except Exception as e:
        import traceback

        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }, 500


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=86400,  # 24 hours
    cpu=1,
    schedule=modal.Cron("0 6 * * *"),  # Run daily at 6 AM UTC
)
def daily_archive():
    """
    Scheduled daily archiving job - runs automatically at 6 AM UTC

    Archives the last 3 days to catch any missed articles
    """
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, "/root")
    from mingpao_archiver_refactored import MingPaoArchiver

    # Setup config for volume
    config_path = Path("/root/config.json")
    with open(config_path, "r") as f:
        config = json.load(f)

    config["database"]["path"] = "/data/hkga_archive.db"
    config["logging"]["file"] = "/data/logs/hkga_archiver.log"

    import os

    os.makedirs("/data/logs", exist_ok=True)

    temp_config = "/tmp/modal_config.json"
    with open(temp_config, "w") as f:
        json.dump(config, f)

    archiver = MingPaoArchiver(temp_config)

    try:
        # Archive last 3 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=2)

        print(
            f"Daily archive: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )
        result = archiver.archive_date_range(start_date, end_date)

        volume.commit()
        print(f"Daily archive complete: {archiver.stats}")
        return result

    finally:
        archiver.close()


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=86400,  # 24 hours max (Modal limit)
    cpu=1,
)
def batch_historical_archive(start_date: str, end_date: str):
    """
    Long-running batch archive for historical data

    Runs entirely in the cloud - continues even if your machine is off.

    Usage:
        modal run modal_app.py::batch_historical_archive --start-date 2013-01-01 --end-date 2026-01-15

    Or trigger from Python:
        batch_historical_archive.spawn("2013-01-01", "2026-01-15")
    """
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, "/root")
    from mingpao_archiver_refactored import MingPaoArchiver, parse_date

    # Setup config
    config_path = Path("/root/config.json")
    with open(config_path, "r") as f:
        config = json.load(f)

    config["database"]["path"] = "/data/hkga_archive.db"
    config["logging"]["file"] = "/data/logs/hkga_archiver.log"

    import os

    os.makedirs("/data/logs", exist_ok=True)

    temp_config = "/tmp/modal_config.json"
    with open(temp_config, "w") as f:
        json.dump(config, f)

    archiver = MingPaoArchiver(temp_config)

    try:
        start = parse_date(start_date)
        end = parse_date(end_date)

        print("=" * 60)
        print("BATCH HISTORICAL ARCHIVE")
        print(f"Start: {start.strftime('%Y-%m-%d')}")
        print(f"End: {end.strftime('%Y-%m-%d')}")
        print("=" * 60)

        # Process month by month
        current = start
        month_count = 0

        while current <= end:
            # Calculate month end
            if current.month == 12:
                month_end = datetime(current.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = datetime(current.year, current.month + 1, 1) - timedelta(
                    days=1
                )

            # Don't go past end date
            if month_end > end:
                month_end = end

            print(
                f"\n[Month {month_count + 1}] Processing {current.strftime('%Y-%m')}..."
            )

            try:
                result = archiver.archive_date_range(current, month_end)
                volume.commit()  # Commit after each month
                print(
                    f"  Archived: {result.get('archived', 0)}, Failed: {result.get('failed', 0)}"
                )
            except Exception as e:
                print(f"  ERROR: {e}")

            # Move to next month
            if current.month == 12:
                current = datetime(current.year + 1, 1, 1)
            else:
                current = datetime(current.year, current.month + 1, 1)

            month_count += 1

        print("\n" + "=" * 60)
        print(f"BATCH COMPLETE: Processed {month_count} months")
        print(f"Stats: {archiver.stats}")
        print("=" * 60)

        return {
            "status": "complete",
            "months_processed": month_count,
            "stats": archiver.stats,
        }

    finally:
        archiver.close()


@app.local_entrypoint()
def main(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    Local entry point - can trigger batch archive or run tests

    Usage:
        # Quick test (today's date)
        modal run modal_app.py

        # Batch historical archive (runs in cloud, detached)
        modal run modal_app.py --start-date 2013-01-01 --end-date 2026-01-15
    """
    import json

    if start_date and end_date:
        # Spawn batch job in the cloud (detached)
        print("=" * 60)
        print("SPAWNING BATCH ARCHIVE IN CLOUD")
        print(f"Start: {start_date}")
        print(f"End: {end_date}")
        print("=" * 60)
        print("\nThis job will continue running even if you close your terminal.")
        print("Monitor progress at: https://modal.com/apps")
        print(
            "Check stats at: https://yellowcandle--mingpao-archiver-get-stats.modal.run"
        )
        print()

        # Use .spawn() for detached execution
        call = batch_historical_archive.spawn(start_date, end_date)
        print(f"Job spawned with ID: {call.object_id}")
        return

    # Default: quick test
    test_request = {"mode": "date", "date": "2026-01-13"}

    print("=" * 60)
    print("Testing Modal archiver locally")
    print("=" * 60)
    print(f"\nRequest: {json.dumps(test_request, indent=2)}")
    print("\nCalling archive_articles.remote()...\n")

    result = archive_articles.remote(test_request)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("Fetching statistics...")
    print("=" * 60 + "\n")

    stats = get_stats.remote()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
