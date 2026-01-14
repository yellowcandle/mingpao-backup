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
import os
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


# ============================================================================
# Dashboard Helper Functions
# ============================================================================

def format_duration(seconds) -> str:
    """Format seconds into human-readable duration"""
    if not seconds:
        return "N/A"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return f"{int(seconds)}s"


def build_empty_dashboard() -> str:
    """Build dashboard for empty database"""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Ming Pao Archive Dashboard</title>
    <style>
        body {
            font-family: sans-serif;
            text-align: center;
            padding: 50px;
            background: #f5f5f5;
        }
        .empty-state {
            max-width: 500px;
            margin: 0 auto;
            padding: 40px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            margin-bottom: 20px;
        }
        a {
            color: #007bff;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="empty-state">
        <h1>📰 Ming Pao Archive Dashboard</h1>
        <p>No data available yet. Start archiving to see statistics.</p>
        <p style="margin-top: 20px;">
            Trigger archiving via the API endpoint
        </p>
    </div>
</body>
</html>
"""


def get_overall_stats(cursor) -> dict:
    """Get overall statistics"""
    cursor.execute("SELECT COUNT(*) FROM archive_records")
    total = cursor.fetchone()[0]

    cursor.execute("""
        SELECT status, COUNT(*)
        FROM archive_records
        GROUP BY status
    """)
    status_counts = dict(cursor.fetchall())

    success = status_counts.get("success", 0)
    exists = status_counts.get("exists", 0)
    archived = success + exists

    failed = sum([
        status_counts.get("failed", 0),
        status_counts.get("error", 0),
        status_counts.get("timeout", 0),
        status_counts.get("rate_limited", 0),
        status_counts.get("unknown", 0)
    ])

    cursor.execute("SELECT COUNT(*) FROM daily_progress")
    days = cursor.fetchone()[0]

    return {
        "total": total,
        "archived": archived,
        "failed": failed,
        "success_rate": f"{(archived / total * 100):.1f}%" if total > 0 else "0%",
        "days": days
    }


def get_status_breakdown(cursor) -> dict:
    """Get detailed status breakdown for visualization"""
    cursor.execute("""
        SELECT status, COUNT(*)
        FROM archive_records
        GROUP BY status
    """)
    return dict(cursor.fetchall())


def get_active_batches(cursor) -> list:
    """Get active or recently completed batch jobs"""
    cursor.execute("""
        SELECT batch_id, start_date, end_date, status,
               articles_found, articles_archived, articles_failed,
               started_at, execution_time
        FROM batch_progress
        WHERE status IN ('in_progress', 'pending')
           OR completed_at > datetime('now', '-24 hours')
        ORDER BY started_at DESC
        LIMIT 5
    """)

    batches = []
    for row in cursor.fetchall():
        total = row[5] + row[6]  # archived + failed
        progress = (row[5] / total * 100) if total > 0 else 0

        batches.append({
            "id": row[0],
            "date_range": f"{row[1]} to {row[2]}",
            "status": row[3],
            "archived": row[5],
            "failed": row[6],
            "total": total,
            "progress": progress,
            "duration": format_duration(row[8])
        })

    return batches


def get_recent_archives(cursor) -> list:
    """Get last 10 archived articles"""
    cursor.execute("""
        SELECT article_url, archive_date, status, article_title, created_at
        FROM archive_records
        ORDER BY created_at DESC
        LIMIT 10
    """)

    return [
        {
            "url": row[0],
            "date": row[1],
            "status": row[2],
            "title": row[3] or "Untitled",
            "timestamp": row[4]
        }
        for row in cursor.fetchall()
    ]


def get_daily_trends(cursor) -> list:
    """Get last 5 days of archiving activity"""
    cursor.execute("""
        SELECT date, articles_found, articles_archived, articles_failed, execution_time
        FROM daily_progress
        ORDER BY date DESC
        LIMIT 5
    """)

    return [
        {
            "date": row[0],
            "found": row[1],
            "archived": row[2],
            "failed": row[3],
            "duration": format_duration(row[4])
        }
        for row in cursor.fetchall()
    ]


def get_date_coverage(cursor) -> dict:
    """Calculate date range coverage from 2013-01-01 to today."""
    from datetime import date, timedelta

    start_date = date(2013, 1, 1)
    end_date = date.today()
    total_days = (end_date - start_date).days + 1

    # Get all dates with data from daily_progress
    cursor.execute("""
        SELECT DISTINCT date FROM daily_progress
        WHERE articles_found > 0
    """)
    archived_dates = set(row[0] for row in cursor.fetchall())

    # Calculate coverage by year
    year_coverage = {}
    missing_ranges = []
    current_missing_start = None

    for i in range(total_days):
        check_date = start_date + timedelta(days=i)
        date_str = check_date.strftime('%Y-%m-%d')
        year = check_date.year

        if year not in year_coverage:
            year_coverage[year] = {'total': 0, 'archived': 0}
        year_coverage[year]['total'] += 1

        if date_str in archived_dates:
            year_coverage[year]['archived'] += 1
            if current_missing_start:
                missing_ranges.append((current_missing_start, check_date - timedelta(days=1)))
                current_missing_start = None
        else:
            if not current_missing_start:
                current_missing_start = check_date

    if current_missing_start:
        missing_ranges.append((current_missing_start, end_date))

    return {
        'total_days': total_days,
        'archived_days': len(archived_dates),
        'coverage_pct': len(archived_dates) / total_days * 100 if total_days > 0 else 0,
        'year_coverage': year_coverage,
        'missing_ranges': missing_ranges[:10]  # Limit to 10 ranges for display
    }


def generate_css() -> str:
    """Generate inline CSS for dashboard"""
    return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }

        header {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }

        .refresh-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 10px;
        }

        button {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
        }

        button:hover {
            background: #0056b3;
        }

        .timestamp {
            color: #666;
            font-size: 14px;
        }

        .summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }

        .card.success {
            border-left: 4px solid #28a745;
        }

        .card.error {
            border-left: 4px solid #dc3545;
        }

        .card-value {
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 5px;
        }

        .card-label {
            color: #666;
            font-size: 14px;
        }

        .section {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        h2 {
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #f0f0f0;
            padding-bottom: 10px;
        }

        .status-bar {
            margin-bottom: 15px;
        }

        .status-label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
            font-size: 14px;
        }

        .bar {
            height: 25px;
            background: #e0e0e0;
            border-radius: 5px;
            overflow: hidden;
        }

        .bar-fill {
            height: 100%;
            transition: width 0.3s ease;
        }

        .bar-fill.success { background: #28a745; }
        .bar-fill.exists { background: #17a2b8; }
        .bar-fill.failed { background: #dc3545; }
        .bar-fill.error { background: #ffc107; }

        .batch-progress {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 10px;
        }

        .batch-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }

        .batch-status {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
        }

        .batch-status.in_progress { background: #ffc107; color: #000; }
        .batch-status.completed { background: #28a745; color: #fff; }
        .batch-status.pending { background: #6c757d; color: #fff; }

        .activity-feed {
            max-height: 400px;
            overflow-y: auto;
        }

        .activity-item {
            padding: 10px;
            border-bottom: 1px solid #f0f0f0;
            font-size: 14px;
        }

        .activity-item:last-child {
            border-bottom: none;
        }

        .activity-url {
            color: #007bff;
            text-decoration: none;
            font-family: monospace;
            font-size: 12px;
        }

        .activity-title {
            color: #333;
            margin-top: 5px;
        }

        .trends-table {
            width: 100%;
            border-collapse: collapse;
        }

        .trends-table th,
        .trends-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #f0f0f0;
        }

        .trends-table th {
            background: #f8f9fa;
            font-weight: 600;
        }

        .trends-table tr:hover {
            background: #f8f9fa;
        }

        @media (max-width: 768px) {
            .summary-cards {
                grid-template-columns: 1fr 1fr;
            }

            h1 {
                font-size: 22px;
            }

            .refresh-bar {
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }
        }
    """


def generate_status_bars(breakdown, total) -> str:
    """Generate status breakdown bars"""
    if total == 0:
        return "<p>No data yet</p>"

    status_order = [
        ("success", "Success", "success"),
        ("exists", "Already Exists", "exists"),
        ("failed", "Failed", "failed"),
        ("error", "Errors", "error"),
        ("timeout", "Timeouts", "error"),
        ("rate_limited", "Rate Limited", "error")
    ]

    html = ""
    for status_key, label, css_class in status_order:
        count = breakdown.get(status_key, 0)
        if count == 0:
            continue

        percentage = (count / total * 100)

        html += f"""
        <div class="status-bar">
            <div class="status-label">
                <span>{label}</span>
                <span>{count:,} ({percentage:.1f}%)</span>
            </div>
            <div class="bar">
                <div class="bar-fill {css_class}" style="width: {percentage}%"></div>
            </div>
        </div>
        """

    return html


def generate_batch_section(batches) -> str:
    """Generate active batch jobs section"""
    html = '<section class="section"><h2>Active Batch Jobs</h2>'

    for batch in batches:
        status_class = batch['status']
        html += f"""
        <div class="batch-progress">
            <div class="batch-header">
                <div>
                    <strong>{batch['id']}</strong>
                    <span class="batch-status {status_class}">{batch['status'].upper()}</span>
                </div>
                <span>{batch['date_range']}</span>
            </div>
            <div class="bar">
                <div class="bar-fill success" style="width: {batch['progress']:.1f}%"></div>
            </div>
            <div style="margin-top: 5px; font-size: 14px; color: #666;">
                {batch['archived']} / {batch['total']} articles · {batch['duration']}
            </div>
        </div>
        """

    html += '</section>'
    return html


def generate_recent_feed(recent, status_emoji) -> str:
    """Generate recent activity feed"""
    html = ""

    for item in recent:
        emoji = status_emoji.get(item['status'], "❓")
        title_truncated = item['title'][:80] + "..." if len(item['title']) > 80 else item['title']

        html += f"""
        <div class="activity-item">
            <div>
                {emoji}
                <span style="color: #666;">{item['date']}</span>
                <span class="batch-status {item['status']}" style="margin-left: 10px;">
                    {item['status']}
                </span>
            </div>
            <div class="activity-title">{title_truncated}</div>
            <a href="{item['url']}" target="_blank" class="activity-url">{item['url']}</a>
        </div>
        """

    return html


def generate_trends_rows(trends) -> str:
    """Generate daily trends table rows"""
    html = ""

    for trend in trends:
        success_rate = (trend['archived'] / trend['found'] * 100) if trend['found'] > 0 else 0

        html += f"""
        <tr>
            <td><strong>{trend['date']}</strong></td>
            <td>{trend['found']}</td>
            <td>{trend['archived']}</td>
            <td>{trend['failed']}</td>
            <td>{trend['duration']}</td>
        </tr>
        """

    return html


def generate_volunteer_guide() -> str:
    """Generate the volunteer quick start guide section"""
    return """
        <section class="section">
            <h2>🤝 Help Us Archive</h2>
            <p style="margin-bottom: 16px; color: #9ca3af;">
                Run a Docker container locally to help archive historical articles. Pick a missing date range above!
            </p>

            <div style="background: #1f2937; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <h3 style="font-size: 0.9rem; color: #60a5fa; margin-bottom: 12px;">Quick Start</h3>
                <pre style="background: #111827; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; line-height: 1.6;"><code style="color: #e5e7eb;"># Clone and build
git clone https://github.com/yellowcandle/mingpao-backup.git
cd mingpao-backup
docker build -t mingpao-archiver .

# Create data directories
mkdir -p data logs

# Archive a date range (example: 2015 Q1)
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \\
  mingpao-archiver --start 2015-01-01 --end 2015-03-31</code></pre>
            </div>

            <div style="display: flex; gap: 12px; flex-wrap: wrap;">
                <a href="https://github.com/yellowcandle/mingpao-backup/issues/new?template=archive-claim.yml"
                   target="_blank"
                   style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #22c55e; color: white; text-decoration: none; border-radius: 6px; font-weight: 500;">
                    📋 Claim a Date Range
                </a>
                <a href="https://github.com/yellowcandle/mingpao-backup/blob/main/CONTRIBUTING.md"
                   target="_blank"
                   style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #374151; color: white; text-decoration: none; border-radius: 6px; font-weight: 500;">
                    📖 Full Guide
                </a>
                <a href="https://github.com/yellowcandle/mingpao-backup"
                   target="_blank"
                   style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #374151; color: white; text-decoration: none; border-radius: 6px; font-weight: 500;">
                    ⭐ GitHub Repo
                </a>
            </div>
        </section>
    """


def generate_coverage_section(coverage: dict) -> str:
    """Generate the date coverage section HTML"""
    if not coverage:
        return ""

    total_days = coverage['total_days']
    archived_days = coverage['archived_days']
    coverage_pct = coverage['coverage_pct']
    year_coverage = coverage['year_coverage']
    missing_ranges = coverage['missing_ranges']

    # Generate year progress bars
    year_bars = ""
    for year in sorted(year_coverage.keys()):
        data = year_coverage[year]
        pct = (data['archived'] / data['total'] * 100) if data['total'] > 0 else 0
        color = "#22c55e" if pct >= 80 else "#eab308" if pct >= 40 else "#ef4444"
        year_bars += f"""
            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <span style="width: 50px; font-weight: bold;">{year}</span>
                <div style="flex: 1; background: #374151; border-radius: 4px; height: 20px; overflow: hidden;">
                    <div style="width: {pct:.1f}%; height: 100%; background: {color};"></div>
                </div>
                <span style="width: 80px; text-align: right; margin-left: 10px;">{pct:.0f}% ({data['archived']}/{data['total']})</span>
            </div>
        """

    # Generate missing ranges list
    missing_html = ""
    for start, end in missing_ranges:
        days = (end - start).days + 1
        start_str = start.strftime('%Y-%m-%d')
        end_str = end.strftime('%Y-%m-%d')
        missing_html += f"""
            <div style="padding: 8px 12px; background: #1f2937; border-radius: 6px; margin-bottom: 6px;">
                <span style="color: #f87171;">●</span>
                <strong>{start_str}</strong> to <strong>{end_str}</strong>
                <span style="color: #9ca3af; margin-left: 8px;">({days} days)</span>
            </div>
        """

    if not missing_html:
        missing_html = '<div style="color: #22c55e;">All dates archived!</div>'

    return f"""
        <section class="section">
            <h2>📅 Archive Coverage</h2>
            <div style="margin-bottom: 20px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span>Coverage: {archived_days:,} / {total_days:,} days</span>
                    <span style="font-weight: bold; color: {'#22c55e' if coverage_pct >= 80 else '#eab308' if coverage_pct >= 40 else '#ef4444'};">{coverage_pct:.1f}%</span>
                </div>
                <div style="background: #374151; border-radius: 8px; height: 24px; overflow: hidden;">
                    <div style="width: {coverage_pct:.1f}%; height: 100%; background: linear-gradient(90deg, #22c55e, #16a34a); transition: width 0.3s;"></div>
                </div>
            </div>

            <h3 style="margin: 20px 0 12px; font-size: 1rem; color: #9ca3af;">Year by Year</h3>
            <div style="margin-bottom: 20px;">
                {year_bars}
            </div>

            <h3 style="margin: 20px 0 12px; font-size: 1rem; color: #9ca3af;">Missing Ranges (Top 10)</h3>
            <div style="max-height: 200px; overflow-y: auto;">
                {missing_html}
            </div>
        </section>
    """


def build_dashboard_html(overall, breakdown, batches, recent, trends, timestamp, coverage=None) -> str:
    """Generate complete dashboard HTML"""

    # Status emoji mapping
    status_emoji = {
        "success": "✅",
        "exists": "📦",
        "failed": "❌",
        "error": "⚠️",
        "timeout": "⏱️",
        "rate_limited": "🚫"
    }

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ming Pao Archive Dashboard</title>
    <style>
        {generate_css()}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📰 Ming Pao Archive Dashboard</h1>
            <div class="refresh-bar">
                <button onclick="location.reload()">🔄 Refresh</button>
                <span class="timestamp">Last updated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}</span>
            </div>
        </header>

        <!-- Summary Cards -->
        <div class="summary-cards">
            <div class="card">
                <div class="card-value">{overall['total']:,}</div>
                <div class="card-label">Total Articles</div>
            </div>
            <div class="card success">
                <div class="card-value">{overall['archived']:,}</div>
                <div class="card-label">Archived ({overall['success_rate']})</div>
            </div>
            <div class="card error">
                <div class="card-value">{overall['failed']:,}</div>
                <div class="card-label">Failed</div>
            </div>
            <div class="card">
                <div class="card-value">{overall['days']}</div>
                <div class="card-label">Days Processed</div>
            </div>
        </div>

        <!-- Status Breakdown -->
        <section class="section">
            <h2>Status Breakdown</h2>
            {generate_status_bars(breakdown, overall['total'])}
        </section>

        <!-- Archive Coverage -->
        {generate_coverage_section(coverage) if coverage else ''}

        <!-- Volunteer Guide -->
        {generate_volunteer_guide()}

        <!-- Active Batches -->
        {generate_batch_section(batches) if batches else ''}

        <!-- Recent Archives -->
        <section class="section">
            <h2>Recent Archives</h2>
            <div class="activity-feed">
                {generate_recent_feed(recent, status_emoji)}
            </div>
        </section>

        <!-- Daily Trends -->
        <section class="section">
            <h2>Daily Trends</h2>
            <table class="trends-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Found</th>
                        <th>Archived</th>
                        <th>Failed</th>
                        <th>Duration</th>
                    </tr>
                </thead>
                <tbody>
                    {generate_trends_rows(trends)}
                </tbody>
            </table>
        </section>
    </div>
</body>
</html>
"""
    return html


@app.function(
    image=image,
    volumes={"/data": volume},
)
@modal.fastapi_endpoint(method="GET")
def dashboard():
    """
    Render HTML dashboard for archiving statistics

    Returns comprehensive archiving dashboard with:
    - Overall statistics (total, archived, failed, success rate)
    - Status breakdown visualization
    - Active batch job progress
    - Recent archived articles
    - Daily trends

    Access at: https://yellowcandle--mingpao-archiver-dashboard.modal.run
    """
    import sqlite3
    from datetime import datetime
    from fastapi.responses import HTMLResponse

    db_path = "/data/hkga_archive.db"

    try:
        # Check if database exists
        if not os.path.exists(db_path):
            return HTMLResponse(content=build_empty_dashboard())

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Gather all statistics
        overall_stats = get_overall_stats(cursor)
        status_breakdown = get_status_breakdown(cursor)
        active_batches = get_active_batches(cursor)
        recent_archives = get_recent_archives(cursor)
        daily_trends = get_daily_trends(cursor)
        date_coverage = get_date_coverage(cursor)

        conn.close()

        # Generate HTML
        html = build_dashboard_html(
            overall=overall_stats,
            breakdown=status_breakdown,
            batches=active_batches,
            recent=recent_archives,
            trends=daily_trends,
            timestamp=datetime.now(),
            coverage=date_coverage
        )

        return HTMLResponse(content=html)

    except Exception as e:
        import traceback

        error_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Dashboard Error</title>
    <style>
        body {{
            font-family: sans-serif;
            padding: 50px;
            background: #f5f5f5;
        }}
        .error {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            max-width: 800px;
            margin: 0 auto;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        pre {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
    </style>
</head>
<body>
    <div class="error">
        <h1>❌ Dashboard Error</h1>
        <p><strong>Error:</strong> {str(e)}</p>
        <pre>{traceback.format_exc()}</pre>
    </div>
</body>
</html>
"""
        return HTMLResponse(content=error_html, status_code=500)


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=86400,  # 24 hours for large backfills
    cpu=1,
)
def backfill_titles(batch_size: int = 100, rate_limit_delay: int = 3, clear_garbled: bool = False):
    """
    Backfill article titles for records with NULL titles

    Extracts titles from Wayback Machine for articles that were archived
    before the title extraction feature was implemented.

    Args:
        batch_size: Number of articles to process (default: 100)
        rate_limit_delay: Seconds between requests (default: 3)
        clear_garbled: Clear garbled titles (containing 'æ') before backfill (default: False)

    Returns:
        Dictionary with backfill statistics

    Usage:
        # Via Python
        modal run modal_app.py::backfill_titles --batch-size 100

        # Clear garbled titles and re-fetch
        modal run modal_app.py::backfill_titles --clear-garbled --batch-size 500

        # Or trigger via spawn
        backfill_titles.spawn(batch_size=500, rate_limit_delay=3)
    """
    import sqlite3
    import sys
    import time
    from datetime import datetime

    sys.path.insert(0, "/root")
    from mingpao_archiver_refactored import MingPaoArchiver

    db_path = "/data/hkga_archive.db"

    print("=" * 60)
    print("TITLE BACKFILL STARTED")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Batch size: {batch_size}")
    print(f"Rate limit: {rate_limit_delay}s")
    print("=" * 60)

    # Initialize archiver for title extraction
    config_path = "/root/config.json"
    import json
    with open(config_path, "r") as f:
        config = json.load(f)

    config["database"]["path"] = db_path
    temp_config = "/tmp/backfill_config.json"
    with open(temp_config, "w") as f:
        json.dump(config, f)

    archiver = MingPaoArchiver(temp_config)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Clear garbled/generic titles if requested
    if clear_garbled:
        # Count garbled titles (mojibake)
        cursor.execute("SELECT COUNT(*) FROM archive_records WHERE article_title LIKE '%æ%'")
        garbled_count = cursor.fetchone()[0]

        # Count generic titles (site name only)
        cursor.execute("SELECT COUNT(*) FROM archive_records WHERE article_title LIKE '%明報新聞網%' AND LENGTH(article_title) < 50")
        generic_count = cursor.fetchone()[0]

        print(f"\n🧹 Found {garbled_count} garbled titles (containing 'æ')")
        print(f"🧹 Found {generic_count} generic titles (site name only)")

        if garbled_count > 0 or generic_count > 0:
            cursor.execute("""
                UPDATE archive_records SET article_title = NULL
                WHERE article_title LIKE '%æ%'
                   OR (article_title LIKE '%明報新聞網%' AND LENGTH(article_title) < 50)
            """)
            conn.commit()
            print(f"✅ Cleared {cursor.rowcount} bad titles\n")

    # Get articles with NULL titles
    cursor.execute("""
        SELECT id, article_url, archive_date, status
        FROM archive_records
        WHERE article_title IS NULL
        ORDER BY created_at DESC
        LIMIT ?
    """, (batch_size,))

    articles = cursor.fetchall()
    total = len(articles)

    if total == 0:
        print("\n✅ No articles need title backfill!")
        conn.close()
        archiver.close()
        volume.commit()
        return {
            "status": "success",
            "message": "No articles need backfill",
            "processed": 0,
            "updated": 0,
            "failed": 0
        }

    print(f"\nFound {total} articles with NULL titles")
    print("Starting title extraction...\n")

    updated = 0
    failed = 0

    for i, (record_id, url, date, status) in enumerate(articles):
        print(f"[{i+1}/{total}] Processing: {url}")

        try:
            # Fetch HTML and extract title
            html, from_wayback = archiver.fetch_html_content(url, timeout=30)

            if html:
                title = archiver.extract_title_from_html(html)

                if title:
                    # Update database
                    cursor.execute("""
                        UPDATE archive_records
                        SET article_title = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (title, record_id))
                    conn.commit()

                    updated += 1
                    print(f"  ✅ Title: {title[:60]}...")
                else:
                    failed += 1
                    print(f"  ⚠️ Could not extract title from HTML")
            else:
                failed += 1
                print(f"  ❌ Could not fetch HTML")

        except Exception as e:
            failed += 1
            print(f"  ❌ Error: {str(e)}")

        # Rate limiting
        if i < total - 1:
            time.sleep(rate_limit_delay)

        # Progress update every 10 articles
        if (i + 1) % 10 == 0:
            print(f"\nProgress: {i+1}/{total} processed, {updated} updated, {failed} failed\n")

    conn.close()
    archiver.close()
    volume.commit()  # Persist changes

    print("\n" + "=" * 60)
    print("BACKFILL COMPLETED")
    print(f"Total processed: {total}")
    print(f"Titles updated: {updated}")
    print(f"Failed: {failed}")
    print(f"Success rate: {(updated/total*100):.1f}%")
    print("=" * 60)

    return {
        "status": "success",
        "processed": total,
        "updated": updated,
        "failed": failed,
        "success_rate": f"{(updated/total*100):.1f}%"
    }


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


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=86400,  # 24 hours max
)
def sync_from_wayback(start_date: str, end_date: str, rate_limit_delay: float = 0.5):
    """
    Sync archive status from Wayback Machine without re-archiving.

    Checks which URLs are already in Wayback and updates our database.
    This populates the dashboard with accurate coverage data.

    Usage:
        modal run modal_app.py::sync_from_wayback --start-date 2024-01-01 --end-date 2024-12-31

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        rate_limit_delay: Seconds between API requests (default 0.5)
    """
    import sqlite3
    import requests
    import time
    from datetime import datetime, timedelta

    # Parse dates
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    db_path = "/data/hkga_archive.db"

    # Initialize database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Ensure table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_url TEXT UNIQUE NOT NULL,
            wayback_url TEXT,
            archive_date TEXT,
            status TEXT DEFAULT 'pending',
            http_status INTEGER,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            matched_keywords TEXT,
            checked_wayback INTEGER DEFAULT 0,
            title_search_only INTEGER DEFAULT 0,
            article_title TEXT
        )
    """)
    conn.commit()

    # URL prefixes for HK-GA articles
    HK_GA_PREFIXES = [
        "gaa", "gab", "gac", "gad", "gae", "gaf", "gag",
        "gba", "gbb", "gbc", "gbd", "gbe",
        "gca", "gcb", "gcc", "gcd",
        "gda", "gdb", "gdc",
        "gha", "ghb", "ghc",
        "gma", "gmb", "gmc",
        "gna", "gnb", "gnc",
        "goa", "gob", "goc",
    ]

    print("=" * 60)
    print("SYNC FROM WAYBACK MACHINE")
    print(f"Date range: {start_date} to {end_date}")
    print("=" * 60)

    stats = {"checked": 0, "found": 0, "not_found": 0, "errors": 0, "skipped": 0}
    current_date = start

    while current_date <= end:
        date_str = current_date.strftime("%Y%m%d")
        date_display = current_date.strftime("%Y-%m-%d")
        day_found = 0
        day_checked = 0

        # Generate URLs for this date
        for prefix in HK_GA_PREFIXES:
            for num in range(1, 20):  # 1-19 per prefix
                url = f"http://www.mingpaocanada.com/tor/htm/News/{date_str}/HK-{prefix}{num}_r.htm"

                # Check if already in database with success/exists status
                cursor.execute(
                    "SELECT status FROM archive_records WHERE article_url = ?",
                    (url,)
                )
                existing = cursor.fetchone()
                if existing and existing[0] in ("success", "exists"):
                    stats["skipped"] += 1
                    continue

                # Check Wayback availability
                try:
                    api_url = f"https://archive.org/wayback/available?url={url}"
                    response = requests.get(api_url, timeout=10)
                    data = response.json()

                    day_checked += 1
                    stats["checked"] += 1

                    snapshots = data.get("archived_snapshots", {})
                    closest = snapshots.get("closest", {})

                    if closest.get("available"):
                        wayback_url = closest.get("url", "")
                        timestamp = closest.get("timestamp", "")

                        # Insert or update record
                        cursor.execute("""
                            INSERT INTO archive_records (article_url, wayback_url, archive_date, status, checked_wayback)
                            VALUES (?, ?, ?, 'exists', 1)
                            ON CONFLICT(article_url) DO UPDATE SET
                                wayback_url = excluded.wayback_url,
                                status = 'exists',
                                checked_wayback = 1,
                                updated_at = CURRENT_TIMESTAMP
                        """, (url, wayback_url, date_str))

                        day_found += 1
                        stats["found"] += 1
                    else:
                        stats["not_found"] += 1

                    time.sleep(rate_limit_delay)

                except Exception as e:
                    stats["errors"] += 1
                    print(f"  Error checking {url}: {e}")
                    time.sleep(1)  # Longer delay on error

        conn.commit()
        volume.commit()

        if day_checked > 0:
            print(f"  {date_display}: checked {day_checked}, found {day_found} in Wayback")

        current_date += timedelta(days=1)

    conn.close()
    volume.commit()

    print("\n" + "=" * 60)
    print("SYNC COMPLETE")
    print(f"  Checked: {stats['checked']}")
    print(f"  Found in Wayback: {stats['found']}")
    print(f"  Not found: {stats['not_found']}")
    print(f"  Skipped (already synced): {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")
    print("=" * 60)

    return stats


@app.local_entrypoint()
def main(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    Local entry point - triggers batch archive in the cloud

    Usage:
        # Archive from start date to today
        modal run modal_app.py --start-date 2025-12-01

        # Archive specific date range
        modal run modal_app.py --start-date 2013-01-01 --end-date 2026-01-15

        # Test via HTTP endpoints (recommended):
        curl https://yellowcandle--mingpao-archiver-get-stats.modal.run
    """
    import json
    from datetime import datetime

    if start_date:
        # Default end_date to today if not provided
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

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

    # No arguments - show usage
    print("=" * 60)
    print("Ming Pao Archiver - Modal Deployment")
    print("=" * 60)
    print("\nUsage:")
    print("  modal run modal_app.py --start-date 2025-12-01 [--end-date 2026-01-15]")
    print("\nTo test the deployed app, use HTTP endpoints:")
    print("  curl https://yellowcandle--mingpao-archiver-get-stats.modal.run")
    print("\nTo trigger archiving:")
    print("  curl -X POST https://yellowcandle--mingpao-archiver-archive-articles.modal.run \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -d '{\"mode\": \"date\", \"date\": \"2026-01-14\", \"daily_limit\": 5}'")
    print("=" * 60)
