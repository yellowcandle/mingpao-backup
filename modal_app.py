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


def build_dashboard_html(overall, breakdown, batches, recent, trends, timestamp) -> str:
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

        conn.close()

        # Generate HTML
        html = build_dashboard_html(
            overall=overall_stats,
            breakdown=status_breakdown,
            batches=active_batches,
            recent=recent_archives,
            trends=daily_trends,
            timestamp=datetime.now()
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
