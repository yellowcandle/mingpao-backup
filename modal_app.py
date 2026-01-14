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

# Create Modal app
app = modal.App("mingpao-archiver")

# Create persistent volume for database
volume = modal.Volume.from_name("mingpao-db", create_if_missing=True)

# Define container image with dependencies and local files
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "requests>=2.31.0",
        "internetarchive>=5.7.1",
        "newspaper4k>=0.9.0",
    )
    # Add local Python files into the image
    .add_local_file("mingpao_hkga_archiver.py", "/root/mingpao_hkga_archiver.py")
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

    # Import archiver (copied into image)
    sys.path.insert(0, "/root")
    from mingpao_hkga_archiver import MingPaoHKGAArchiver, parse_date

    # Update config to use persistent volume
    config_path = Path("/root/config.json")
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Override paths to use volume
    config['database']['path'] = '/data/hkga_archive.db'
    config['logging']['file'] = '/data/logs/hkga_archiver.log'

    # Create logs directory in volume
    import os
    os.makedirs('/data/logs', exist_ok=True)

    # Save modified config
    temp_config = '/tmp/modal_config.json'
    with open(temp_config, 'w') as f:
        json.dump(config, f)

    # Create archiver instance
    archiver = MingPaoHKGAArchiver(temp_config)

    # Apply request parameters
    mode = request_data.get('mode', 'date')

    if request_data.get('keywords'):
        archiver.config['keywords']['enabled'] = True
        archiver.config['keywords']['terms'] = request_data['keywords']

    if request_data.get('daily_limit'):
        archiver.config['daily_limit'] = request_data['daily_limit']

    # Execute archiving
    try:
        if mode == 'date':
            if 'date' not in request_data:
                return {
                    "status": "error",
                    "error": "Missing 'date' parameter for mode='date'"
                }, 400

            date = parse_date(request_data['date'])
            result = archiver.archive_date(date)

        elif mode == 'range':
            if 'start' not in request_data or 'end' not in request_data:
                return {
                    "status": "error",
                    "error": "Missing 'start' or 'end' parameter for mode='range'"
                }, 400

            start = parse_date(request_data['start'])
            end = parse_date(request_data['end'])
            result = archiver.archive_date_range(start, end)

        elif mode == 'backdays':
            if 'backdays' not in request_data:
                return {
                    "status": "error",
                    "error": "Missing 'backdays' parameter for mode='backdays'"
                }, 400

            backdays = request_data['backdays']
            end_date = datetime.now()
            start_date = end_date - timedelta(days=backdays - 1)
            result = archiver.archive_date_range(start_date, end_date)

        else:
            return {
                "status": "error",
                "error": f"Invalid mode: {mode}",
                "valid_modes": ["date", "range", "backdays"]
            }, 400

        # Commit volume changes
        volume.commit()

        # Return success response
        return {
            "status": "success",
            "mode": mode,
            "result": result,
            "stats": archiver.stats
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
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
                "days_processed": 0
            }

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Total articles
        cursor.execute("SELECT COUNT(*) FROM archive_records")
        total = cursor.fetchone()[0]

        # Successful archives
        cursor.execute("SELECT COUNT(*) FROM archive_records WHERE status='success'")
        success = cursor.fetchone()[0]

        # Failed archives
        cursor.execute("SELECT COUNT(*) FROM archive_records WHERE status='failed'")
        failed = cursor.fetchone()[0]

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
            "successful": success,
            "failed": failed,
            "success_rate": f"{(success/total*100):.1f}%" if total > 0 else "0%",
            "days_processed": days,
            "recent_archives": [
                {
                    "url": r[0],
                    "date": r[1],
                    "status": r[2],
                    "title": r[3]
                }
                for r in recent
            ],
            "recent_days": [
                {
                    "date": d[0],
                    "found": d[1],
                    "archived": d[2],
                    "failed": d[3]
                }
                for d in recent_days
            ]
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }, 500


@app.local_entrypoint()
def main():
    """
    Local testing entry point

    Usage:
        modal run modal_app.py
    """
    import json

    # Test with a sample request
    test_request = {
        "mode": "date",
        "date": "2026-01-13"
    }

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
