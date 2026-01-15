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
from datetime import datetime, date, timedelta
from wayback import WaybackClient, CdxRecord

# --- PRIORITY RANGES CONFIGURATION ---
# Edit this list to define which date ranges are high priority for volunteers
# These will be highlighted in red on the dashboard heatmap
PRIORITY_RANGES = [
    {
        "start": "2019-04-01",
        "end": "2019-12-31",
        "label": "2019 Apr-Dec (Hong Kong Unrest)",
    },
    {
        "start": "2019-04-26",
        "end": "2019-06-04",
        "recurring_monthly": True,
        "label": "Apr 26 - Jun 4 (Annual Recurring)",
    },
    {
        "start": "2019-07-21",
        "end": "2019-07-22",
        "recurring_yearly": True,
        "label": "Jul 21-22 (Annual Recurring from 2019)",
    },
    {
        "start": "2019-08-31",
        "end": "2019-08-31",
        "recurring_yearly": True,
        "label": "Aug 31 (Annual Recurring from 2019)",
    },
    {
        "start": "2021-01-06",
        "end": "2024-11-30",
        "label": "47人案 (47 Democrats Case: Jan 6, 2021 - Nov 2024 Sentencing)",
    },
    {
        "start": "2021-06-24",
        "end": "2021-06-24",
        "label": "蘋果日報停刊 (Apple Daily Final Issue)",
    },
]

# Create Modal app
app = modal.App("mingpao-archiver")

# Create persistent volume for database
volume = modal.Volume.from_name("mingpao-db", create_if_missing=True)


# --- WAYBACK CDX SEARCH HELPER ---
class WaybackSearcher:
    """High-performance Wayback CDX client for month-by-month searches"""

    def __init__(self, rate_limit: float = 0.5):
        """Initialize WaybackClient with rate limiting

        Args:
            rate_limit: Seconds between requests (CDX recommends 0.5-1.0)
        """
        self.client = WaybackClient(rate_limit=rate_limit)

    def search_month(self, start_date: date, end_date: date) -> list[CdxRecord]:
        """Search CDX for archives in a month range (typically one month)

        Args:
            start_date: Start of search range (YYYY-MM-DD)
            end_date: End of search range (YYYY-MM-DD)

        Returns:
            List of CdxRecord objects matching the search
        """
        try:
            # Search for all HK-GA articles in the date range
            results = []
            for record in self.client.search(
                url="www.mingpaocanada.com/tor/htm/News/",
                match_type="prefix",
                from_date=start_date.strftime("%Y%m%d"),
                to_date=end_date.strftime("%Y%m%d"),
                filter=[
                    "statuscode:200",
                    "mimetype:text/html",
                ],  # Only successful HTML captures
                gzip=True,  # Compress response
            ):
                results.append(record)

            return results
        except Exception as e:
            print(f"Error searching CDX for {start_date} to {end_date}: {e}")
            return []

    def get_month_range(self, year: int, month: int) -> tuple[date, date]:
        """Get the first and last day of a month

        Args:
            year: Year (YYYY)
            month: Month (1-12)

        Returns:
            Tuple of (first_day, last_day) as date objects
        """
        start = date(year, month, 1)
        # Calculate last day of month
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return start, end


# Define container image with dependencies and local files
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "requests>=2.31.0",
        "newspaper4k>=0.9.0",
        "pydantic>=2.0.0",
        "fastapi[standard]",
        "wayback>=0.4.5",  # EDGI CDX client for high-performance Wayback searches
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


def is_priority_date(check_date: date) -> bool:
    """Check if a date falls within any priority range"""
    for priority_range in PRIORITY_RANGES:
        start = datetime.strptime(priority_range["start"], "%Y-%m-%d").date()
        end = datetime.strptime(priority_range["end"], "%Y-%m-%d").date()

        # Check exact range
        if start <= check_date <= end:
            return True

        # Check recurring yearly ranges (e.g., Jul 21-22 every year from 2019 onward)
        if priority_range.get("recurring_yearly"):
            if check_date.year >= start.year:
                # Create the same month-day in the check_date's year
                recurring_start = date(check_date.year, start.month, start.day)
                recurring_end = date(check_date.year, end.month, end.day)
                if recurring_start <= check_date <= recurring_end:
                    return True

        # Check recurring monthly ranges (e.g., Apr 26 - Jun 4 every year)
        if priority_range.get("recurring_monthly"):
            # Handle ranges that cross month boundaries
            if (
                (check_date.month == start.month and check_date.day >= start.day)
                or (check_date.month == end.month and check_date.day <= end.day)
                or (
                    start.month < end.month
                    and start.month < check_date.month < end.month
                )
            ):
                return True

    return False


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

    failed = sum(
        [
            status_counts.get("failed", 0),
            status_counts.get("error", 0),
            status_counts.get("timeout", 0),
            status_counts.get("rate_limited", 0),
            status_counts.get("unknown", 0),
        ]
    )

    cursor.execute("SELECT COUNT(*) FROM daily_progress")
    days = cursor.fetchone()[0]

    return {
        "total": total,
        "archived": archived,
        "failed": failed,
        "success_rate": f"{(archived / total * 100):.1f}%" if total > 0 else "0%",
        "days": days,
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

        batches.append(
            {
                "id": row[0],
                "date_range": f"{row[1]} to {row[2]}",
                "status": row[3],
                "archived": row[5],
                "failed": row[6],
                "total": total,
                "progress": progress,
                "duration": format_duration(row[8]),
            }
        )

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
            "timestamp": row[4],
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
            "duration": format_duration(row[4]),
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
        date_str = check_date.strftime("%Y-%m-%d")
        year = check_date.year

        if year not in year_coverage:
            year_coverage[year] = {"total": 0, "archived": 0}
        year_coverage[year]["total"] += 1

        if date_str in archived_dates:
            year_coverage[year]["archived"] += 1
            if current_missing_start:
                missing_ranges.append(
                    (current_missing_start, check_date - timedelta(days=1))
                )
                current_missing_start = None
        else:
            if not current_missing_start:
                current_missing_start = check_date

    if current_missing_start:
        missing_ranges.append((current_missing_start, end_date))

    # Identify priority gaps
    priority_gaps = []
    for start, end in missing_ranges:
        for priority in PRIORITY_RANGES:
            p_start = datetime.strptime(priority["start"], "%Y-%m-%d").date()
            p_end = datetime.strptime(priority["end"], "%Y-%m-%d").date()
            # Check if priority range overlaps with gap
            if not (p_end < start or p_start > end):
                priority_gaps.append(
                    (start, end, priority.get("label", "Priority Range"))
                )
                break

    return {
        "total_days": total_days,
        "archived_days": len(archived_dates),
        "coverage_pct": len(archived_dates) / total_days * 100 if total_days > 0 else 0,
        "year_coverage": year_coverage,
        "missing_ranges": missing_ranges[:10],  # Limit to 10 ranges for display
        "priority_gaps": priority_gaps,  # Priority gaps that need work
    }


def generate_css() -> str:
    """Generate inline CSS for dashboard"""
    return """
        :root {
            --bg-main: #0f172a;
            --bg-card: #1e293b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #3b82f6;
            --success: #22c55e;
            --error: #ef4444;
            --warning: #f59e0b;
            --info: #06b6d4;
            --border: #334155;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg-main);
            color: var(--text-main);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
        }

        h1 {
            font-size: 24px;
            font-weight: 800;
            background: linear-gradient(to right, #60a5fa, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .refresh-bar {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        button {
            background: var(--bg-card);
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        button:hover {
            background: var(--border);
            transform: translateY(-1px);
        }

        .timestamp {
            color: var(--text-muted);
            font-size: 13px;
        }

        .grid {
            display: grid;
            gap: 24px;
        }

        .grid-stats {
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        }

        .grid-main {
            grid-template-columns: 2fr 1fr;
        }

        .card {
            background: var(--bg-card);
            padding: 24px;
            border-radius: 16px;
            border: 1px solid var(--border);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        }

        .stat-card {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .stat-value {
            font-size: 32px;
            font-weight: 700;
            color: var(--text-main);
        }

        .stat-label {
            color: var(--text-muted);
            font-size: 14px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }

        .stat-card.primary .stat-value { color: var(--primary); }
        .stat-card.success .stat-value { color: var(--success); }
        .stat-card.error .stat-value { color: var(--error); }

        .section-title {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--text-main);
        }

        .progress-container {
            margin-bottom: 20px;
        }

        .progress-label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 14px;
            color: var(--text-muted);
        }

        .progress-bar {
            height: 12px;
            background: #334155;
            border-radius: 6px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            border-radius: 6px;
            transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .progress-fill.primary { background: var(--primary); }
        .progress-fill.success { background: var(--success); }
        .progress-fill.error { background: var(--error); }
        .progress-fill.warning { background: var(--warning); }

        .table-container {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }

        th {
            text-align: left;
            padding: 12px;
            color: var(--text-muted);
            font-weight: 600;
            border-bottom: 1px solid var(--border);
        }

        td {
            padding: 16px 12px;
            border-bottom: 1px solid var(--border);
        }

        tr:last-child td { border-bottom: none; }

        .status-badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            text-transform: capitalize;
        }

        .status-badge.success { background: rgba(34, 197, 94, 0.1); color: var(--success); }
        .status-badge.exists { background: rgba(6, 182, 212, 0.1); color: var(--info); }
        .status-badge.failed { background: rgba(239, 68, 68, 0.1); color: var(--error); }
        .status-badge.error { background: rgba(245, 158, 11, 0.1); color: var(--warning); }

        .activity-feed {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .activity-item {
            padding: 16px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            border: 1px solid var(--border);
        }

        .activity-meta {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 12px;
        }

        .activity-title {
            font-weight: 600;
            margin-bottom: 4px;
            display: block;
            color: var(--text-main);
            text-decoration: none;
        }

        .activity-title:hover { color: var(--primary); }

        .activity-url {
            color: var(--text-muted);
            font-size: 12px;
            font-family: monospace;
            word-break: break-all;
        }

        .coverage-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
            gap: 8px;
        }

        .coverage-year {
            padding: 12px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 8px;
            text-align: center;
        }

        .coverage-year-label {
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 4px;
        }

        .coverage-year-pct {
            font-size: 14px;
            font-weight: 600;
        }

        @media (max-width: 1024px) {
            .grid-main {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 640px) {
            header {
                flex-direction: column;
                align-items: flex-start;
                gap: 16px;
            }
            .grid-stats {
                grid-template-columns: 1fr 1fr;
            }
        }
    """


def generate_heatmap(coverage: dict) -> str:
    """Generate month-by-year heatmap visualization for coordination"""
    if not coverage:
        return ""

    year_coverage = coverage.get("year_coverage", {})
    if not year_coverage:
        return ""

    # Color mapping: Red for priority gaps, Yellow for partial, Green for complete
    def get_color_and_status(pct):
        if pct >= 95:
            return "#22c55e", "✓ Complete"  # Green
        elif pct >= 50:
            return "#eab308", "◐ Partial"  # Yellow
        elif pct > 0:
            return "#f97316", "○ Low"  # Orange
        else:
            return "#64748b", "◯ Empty"  # Grey

    months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    html = """
    <section class="card" style="margin-top: 24px;">
        <h2 class="section-title">📅 Archive Heatmap (2013-2026)</h2>
        <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 16px;">
            🟢 Complete (>95%) | 🟡 Partial (50-94%) | 🟠 Low (1-49%) | ⚫ Empty (0%)
        </p>
        <div style="display: grid; gap: 12px;">
    """

    for year in sorted(year_coverage.keys()):
        data = year_coverage[year]
        pct = (data["archived"] / data["total"] * 100) if data["total"] > 0 else 0

        # Check if year has any priority dates
        year_has_priority = False
        for priority in PRIORITY_RANGES:
            p_year_start = int(priority["start"][:4])
            p_year_end = int(priority["end"][:4])
            if p_year_start <= year <= p_year_end:
                year_has_priority = True
                break

        year_label = f"<strong>{year}</strong>"
        if year_has_priority:
            year_label = f"🔥 {year_label}"

        html += f"""
            <div style="display: grid; grid-template-columns: 60px repeat(12, 1fr); gap: 4px; align-items: center;">
                <div style="text-align: right; font-weight: 600; font-size: 12px;">{year_label}</div>
        """

        for month in range(1, 13):
            check_date = date(year, month, 15)
            is_priority = is_priority_date(check_date)

            # Get month coverage (estimate based on year)
            month_pct = pct  # Simplified - use year pct for all months
            color, status = get_color_and_status(month_pct)

            border_color = "#ef4444" if is_priority else "transparent"
            border_style = f"border: 2px solid {border_color};" if is_priority else ""

            html += f"""
                <div style="
                    width: 100%;
                    aspect-ratio: 1;
                    background: {color};
                    border-radius: 4px;
                    {border_style}
                    opacity: 0.8;
                    cursor: pointer;
                    font-size: 10px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    font-weight: 600;
                    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
                    title='{months[month - 1]} {year} - {status} ({month_pct:.0f}%)'
                " title="{months[month - 1]} {year} - {status} ({month_pct:.0f}%)">
                    {months[month - 1][:1]}
                </div>
            """

        html += "</div>"

    html += """
        </div>
    </section>
    """

    return html


def generate_status_bars(breakdown, total) -> str:
    """Generate status breakdown bars"""
    if total == 0:
        return "<p class='text-muted'>No data yet</p>"

    status_order = [
        ("success", "Success", "success"),
        ("exists", "Already Exists", "primary"),
        ("failed", "Failed", "error"),
        ("error", "Errors", "warning"),
        ("timeout", "Timeouts", "warning"),
        ("rate_limited", "Rate Limited", "error"),
    ]

    html = ""
    for status_key, label, css_class in status_order:
        count = breakdown.get(status_key, 0)
        if count == 0:
            continue

        percentage = count / total * 100

        html += f"""
        <div class="progress-container">
            <div class="progress-label">
                <span>{label}</span>
                <span>{count:,} ({percentage:.1f}%)</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill {css_class}" style="width: {percentage}%"></div>
            </div>
        </div>
        """

    return html


def generate_batch_section(batches) -> str:
    """Generate active batch jobs section"""
    if not batches:
        return ""

    html = '<section class="card" style="margin-top: 24px;"><h2 class="section-title">☁️ Cloud Batches</h2>'

    for batch in batches:
        status_class = batch["status"]
        html += f"""
        <div style="margin-bottom: 20px; padding: 16px; background: rgba(255,255,255,0.03); border-radius: 12px; border: 1px solid var(--border);">
            <div style="display: flex; justify-content: space-between; margin-bottom: 12px; align-items: center;">
                <span class="status-badge {status_class}">{batch["status"]}</span>
                <span style="font-size: 12px; color: var(--text-muted);">{batch["date_range"]}</span>
            </div>
            <div class="progress-bar" style="height: 8px; margin-bottom: 8px;">
                <div class="progress-fill success" style="width: {batch["progress"]:.1f}%"></div>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted);">
                <span>{batch["archived"]} / {batch["total"]} articles</span>
                <span>{batch["duration"]}</span>
            </div>
        </div>
        """

    html += "</section>"
    return html


def generate_recent_feed(recent, status_emoji) -> str:
    """Generate recent activity feed"""
    html = '<div class="activity-feed">'

    for item in recent:
        emoji = status_emoji.get(item["status"], "❓")
        title_truncated = (
            item["title"][:80] + "..." if len(item["title"]) > 80 else item["title"]
        )

        html += f"""
        <div class="activity-item">
            <div class="activity-meta">
                <span class="status-badge {item["status"]}">{emoji} {item["status"]}</span>
                <span style="color: var(--text-muted);">{item["date"]}</span>
            </div>
            <a href="{item["url"]}" target="_blank" class="activity-title">{title_truncated}</a>
            <div class="activity-url">{item["url"]}</div>
        </div>
        """

    html += "</div>"
    return html


def generate_trends_rows(trends) -> str:
    """Generate daily trends table rows"""
    html = ""

    for trend in trends:
        html += f"""
        <tr>
            <td style="font-weight: 600;">{trend["date"]}</td>
            <td>{trend["found"]}</td>
            <td><span style="color: var(--success);">{trend["archived"]}</span></td>
            <td><span style="color: var(--error);">{trend["failed"]}</span></td>
            <td style="color: var(--text-muted); font-size: 12px;">{trend["duration"]}</td>
        </tr>
        """

    return html


def generate_volunteer_guide() -> str:
    """Generate the volunteer quick start guide section"""
    return """
        <section class="card" style="margin-top: 24px;">
            <h2 class="section-title">🤝 Help Archive</h2>
            <p style="margin-bottom: 16px; color: var(--text-muted); font-size: 14px;">
                Run a Docker container locally to help archive historical articles.
            </p>

            <div style="background: #0f172a; border-radius: 8px; padding: 12px; margin-bottom: 16px; border: 1px solid var(--border);">
                <pre style="overflow-x: auto; font-size: 11px; line-height: 1.5;"><code style="color: #94a3b8;"># Quick Start
git clone https://github.com/yellowcandle/mingpao-backup.git
cd mingpao-backup
docker build -t mingpao-archiver .

# Archive a date range
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \\
  mingpao-archiver --start 2015-01-01 --end 2015-03-31</code></pre>
            </div>

            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <a href="https://github.com/yellowcandle/mingpao-backup/issues/new?template=archive-claim.yml"
                   target="_blank"
                   style="flex: 1; text-align: center; padding: 8px; background: var(--success); color: white; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: 600;">
                    📋 Claim Range
                </a>
                <a href="https://github.com/yellowcandle/mingpao-backup"
                   target="_blank"
                   style="flex: 1; text-align: center; padding: 8px; background: var(--border); color: white; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: 600;">
                    ⭐ GitHub
                </a>
            </div>
        </section>
    """


def generate_coverage_section(coverage: dict) -> str:
    """Generate the date coverage section HTML"""
    if not coverage:
        return ""

    total_days = coverage["total_days"]
    archived_days = coverage["archived_days"]
    coverage_pct = coverage["coverage_pct"]
    year_coverage = coverage["year_coverage"]
    missing_ranges = coverage["missing_ranges"]

    # Generate year progress bars
    year_bars = ""
    for year in sorted(year_coverage.keys(), reverse=True):
        data = year_coverage[year]
        pct = (data["archived"] / data["total"] * 100) if data["total"] > 0 else 0
        css_class = "success" if pct >= 80 else "warning" if pct >= 40 else "error"

        year_bars += f"""
            <div style="margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                    <span style="font-weight: 700;">{year}</span>
                    <span style="color: var(--text-muted);">{pct:.0f}% ({data["archived"]}/{data["total"]})</span>
                </div>
                <div class="progress-bar" style="height: 6px;">
                    <div class="progress-fill {css_class}" style="width: {pct}%"></div>
                </div>
            </div>
        """

    # Generate missing ranges list
    missing_html = ""
    for start, end in missing_ranges:
        days = (end - start).days + 1
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        missing_html += f"""
            <div style="padding: 10px; background: rgba(239, 68, 68, 0.05); border-radius: 8px; margin-bottom: 8px; border: 1px solid rgba(239, 68, 68, 0.1); font-size: 13px;">
                <div style="display: flex; justify-content: space-between;">
                    <span style="font-weight: 600;">{start_str} → {end_str}</span>
                    <span style="color: var(--error);">{days}d</span>
                </div>
            </div>
        """

    if not missing_html:
        missing_html = '<div style="color: var(--success); font-weight: 600;">✅ All dates archived!</div>'

    return f"""
        <section class="card">
            <h2 class="section-title">📅 Coverage By Year</h2>
            <div style="margin-bottom: 24px;">
                {year_bars}
            </div>

            <h3 class="section-title" style="font-size: 14px; color: var(--text-muted);">🔴 Missing Ranges (Top 10)</h3>
            <div style="max-height: 300px; overflow-y: auto;">
                {missing_html}
            </div>
        </section>
    """


def build_dashboard_html(
    overall, breakdown, batches, recent, trends, timestamp, coverage=None
) -> str:
    """Generate complete dashboard HTML"""

    # Status emoji mapping
    status_emoji = {
        "success": "✅",
        "exists": "📦",
        "failed": "❌",
        "error": "⚠️",
        "timeout": "⏱️",
        "rate_limited": "🚫",
    }

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard | Ming Pao Archive</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        {generate_css()}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📰 Ming Pao Archive <span>Dashboard</span></h1>
            <div class="refresh-bar">
                <span class="timestamp">Updated {timestamp.strftime("%H:%M:%S")}</span>
                <button onclick="location.reload()">🔄 Refresh</button>
            </div>
        </header>

        <!-- Stats Grid -->
        <div class="grid grid-stats" style="margin-bottom: 32px;">
            <div class="card stat-card">
                <span class="stat-label">Total Discovery</span>
                <span class="stat-value">{overall["total"]:,}</span>
            </div>
            <div class="card stat-card success">
                <span class="stat-label">Archived Successfully</span>
                <span class="stat-value">{overall["archived"]:,}</span>
            </div>
            <div class="card stat-card error">
                <span class="stat-label">Archive Failures</span>
                <span class="stat-value">{overall["failed"]:,}</span>
            </div>
            <div class="card stat-card primary">
                <span class="stat-label">Archive Coverage</span>
                <span class="stat-value">{overall["success_rate"]}</span>
            </div>
        </div>

        <!-- Archive Heatmap -->
        {generate_heatmap(coverage) if coverage else ""}

        <div class="grid grid-main">
            <!-- Left Column -->
            <div class="flex-column">
                <!-- Status Breakdown -->
                <section class="card" style="margin-bottom: 24px;">
                    <h2 class="section-title">📊 Status Breakdown</h2>
                    {generate_status_bars(breakdown, overall["total"])}
                </section>

                <!-- Daily Trends -->
                <section class="card" style="margin-bottom: 24px;">
                    <h2 class="section-title">📈 Daily Trends</h2>
                    <div class="table-container">
                        <table>
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
                    </div>
                </section>

                <!-- Recent Activity -->
                <section class="card">
                    <h2 class="section-title">⚡ Recent Activity</h2>
                    {generate_recent_feed(recent, status_emoji)}
                </section>
            </div>

            <!-- Right Column -->
            <div class="flex-column">
                <!-- Archive Coverage -->
                {generate_coverage_section(coverage) if coverage else ""}

                <!-- Active Batches -->
                {generate_batch_section(batches)}

                <!-- Volunteer Guide -->
                {generate_volunteer_guide()}
            </div>
        </div>
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
            coverage=date_coverage,
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
def backfill_titles(
    batch_size: int = 100, rate_limit_delay: int = 3, clear_garbled: bool = False
):
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
        cursor.execute(
            "SELECT COUNT(*) FROM archive_records WHERE article_title LIKE '%æ%'"
        )
        garbled_count = cursor.fetchone()[0]

        # Count generic titles (site name only)
        cursor.execute(
            "SELECT COUNT(*) FROM archive_records WHERE article_title LIKE '%明報新聞網%' AND LENGTH(article_title) < 50"
        )
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
    cursor.execute(
        """
        SELECT id, article_url, archive_date, status
        FROM archive_records
        WHERE article_title IS NULL
        ORDER BY created_at DESC
        LIMIT ?
    """,
        (batch_size,),
    )

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
            "failed": 0,
        }

    print(f"\nFound {total} articles with NULL titles")
    print("Starting title extraction...\n")

    updated = 0
    failed = 0

    for i, (record_id, url, date, status) in enumerate(articles):
        print(f"[{i + 1}/{total}] Processing: {url}")

        try:
            # Fetch HTML and extract title
            html, from_wayback = archiver.fetch_html_content(url, timeout=30)

            if html:
                title = archiver.extract_title_from_html(html)

                if title:
                    # Update database
                    cursor.execute(
                        """
                        UPDATE archive_records
                        SET article_title = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """,
                        (title, record_id),
                    )
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
            print(
                f"\nProgress: {i + 1}/{total} processed, {updated} updated, {failed} failed\n"
            )

    conn.close()
    archiver.close()
    volume.commit()  # Persist changes

    print("\n" + "=" * 60)
    print("BACKFILL COMPLETED")
    print(f"Total processed: {total}")
    print(f"Titles updated: {updated}")
    print(f"Failed: {failed}")
    print(f"Success rate: {(updated / total * 100):.1f}%")
    print("=" * 60)

    return {
        "status": "success",
        "processed": total,
        "updated": updated,
        "failed": failed,
        "success_rate": f"{(updated / total * 100):.1f}%",
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
    Sync archive status from Wayback Machine using CDX API (EDGI wayback library).

    Uses month-by-month CDX searches for dramatically improved performance.
    Instead of 1000+ individual URL checks, uses 1-3 CDX searches per month.

    Usage:
        modal run modal_app.py::sync_from_wayback --start-date 2024-01-01 --end-date 2024-12-31

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        rate_limit_delay: Not used (CDX client handles rate limiting internally)
    """
    import sqlite3
    from datetime import datetime, timedelta

    # Parse dates
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    db_path = "/data/hkga_archive.db"

    # Initialize database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Ensure table exists (with digest column for CDX compatibility)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_url TEXT UNIQUE NOT NULL,
            wayback_url TEXT,
            archive_date TEXT,
            status TEXT DEFAULT 'pending',
            http_status INTEGER,
            error_message TEXT,
            digest TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            matched_keywords TEXT,
            checked_wayback INTEGER DEFAULT 0,
            title_search_only INTEGER DEFAULT 0,
            article_title TEXT
        )
    """)
    conn.commit()

    print("=" * 80)
    print("CDX SYNC FROM WAYBACK MACHINE (Month-by-Month)")
    print(f"Date range: {start_date} to {end_date}")
    print("=" * 80)

    stats = {
        "cdx_searches": 0,
        "records_found": 0,
        "inserted": 0,
        "skipped": 0,
        "errors": 0,
        "duration_seconds": 0,
    }
    start_time = datetime.now()

    searcher = WaybackSearcher(rate_limit=rate_limit_delay)

    # Process month by month (much more efficient than day-by-day)
    current_date = start
    while current_date <= end:
        # Get month range
        month_start, month_end = searcher.get_month_range(
            current_date.year, current_date.month
        )

        # Skip if month start is beyond end date
        if month_start > end:
            break

        print(f"\nSearching CDX for {month_start} to {month_end}...")

        try:
            # Single CDX search per month (replaces 1000+ individual checks)
            records = searcher.search_month(month_start, month_end)
            stats["cdx_searches"] += 1
            stats["records_found"] += len(records)

            # Batch insert/update records
            for record in records:
                try:
                    # Extract key data from CdxRecord
                    url = record.original  # Original URL
                    timestamp = record.timestamp  # Capture timestamp (YYYYMMDDhhmmss)
                    status_code = record.status_code  # HTTP status
                    digest = record.digest  # SHA-1 hash of content

                    # Check if already synced
                    cursor.execute(
                        "SELECT status FROM archive_records WHERE article_url = ?",
                        (url,),
                    )
                    existing = cursor.fetchone()
                    if existing and existing[0] in ("success", "exists"):
                        stats["skipped"] += 1
                        continue

                    # Construct Wayback URL
                    wayback_url = f"https://web.archive.org/web/{timestamp}/{url}"

                    # Get archive date from URL (YYYYMMDD)
                    if "/News/" in url:
                        parts = url.split("/News/")
                        if len(parts) > 1:
                            date_part = parts[1].split("/")[0]
                            archive_date = date_part if len(date_part) == 8 else None
                        else:
                            archive_date = month_start.strftime("%Y%m%d")
                    else:
                        archive_date = month_start.strftime("%Y%m%d")

                    # Insert or update record
                    cursor.execute(
                        """
                        INSERT INTO archive_records 
                        (article_url, wayback_url, archive_date, status, http_status, digest, checked_wayback)
                        VALUES (?, ?, ?, 'exists', ?, ?, 1)
                        ON CONFLICT(article_url) DO UPDATE SET
                            wayback_url = excluded.wayback_url,
                            status = 'exists',
                            http_status = excluded.http_status,
                            digest = excluded.digest,
                            checked_wayback = 1,
                            updated_at = CURRENT_TIMESTAMP
                    """,
                        (url, wayback_url, archive_date, status_code, digest),
                    )
                    stats["inserted"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    print(f"  Error processing record: {e}")

            conn.commit()
            volume.commit()

            print(f"  ✓ {len(records)} records found, {stats['inserted']} inserted")

        except Exception as e:
            stats["errors"] += 1
            print(f"  Error searching CDX: {e}")

        # Move to next month
        if current_date.month == 12:
            current_date = date(current_date.year + 1, 1, 1)
        else:
            current_date = date(current_date.year, current_date.month + 1, 1)

    conn.close()
    volume.commit()

    stats["duration_seconds"] = (datetime.now() - start_time).total_seconds()

    print("\n" + "=" * 80)
    print("CDX SYNC COMPLETE")
    print(f"  CDX Searches: {stats['cdx_searches']}")
    print(f"  Total Records Found: {stats['records_found']}")
    print(f"  Inserted/Updated: {stats['inserted']}")
    print(f"  Skipped (already synced): {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Duration: {stats['duration_seconds']:.1f} seconds")
    print("=" * 80)

    return stats

    return stats


@app.function(
    image=image,
    volumes={"/data": volume},
    timeout=3600,  # 1 hour timeout
    schedule=modal.Cron("0 * * * *"),  # Every hour
)
def hourly_sync_wayback():
    """
    Hourly sync with Wayback Machine using CDX API (EDGI wayback library).

    Uses month-by-month CDX searches to efficiently verify archives.
    Much faster and more reliable than individual URL checks.
    Runs every hour via Modal Cron scheduler.
    """
    import sqlite3
    from datetime import datetime, timedelta

    print("Starting hourly Wayback CDX sync (last 30 days)...")

    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    db_path = "/data/hkga_archive.db"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        stats = {
            "cdx_searches": 0,
            "records_found": 0,
            "inserted": 0,
            "duration_seconds": 0,
        }
        start_time = datetime.now()

        searcher = WaybackSearcher(rate_limit=0.5)

        # Process month by month for the last 30 days
        current_date = start_date
        while current_date <= end_date:
            # Get month range
            month_start, month_end = searcher.get_month_range(
                current_date.year, current_date.month
            )

            # Skip if month is beyond end_date
            if month_start > end_date:
                break

            print(f"Searching CDX for {month_start} to {month_end}...")

            try:
                # Single CDX search per month (instead of 1000+ individual checks)
                records = searcher.search_month(month_start, month_end)
                stats["cdx_searches"] += 1
                stats["records_found"] += len(records)

                # Batch insert/update records
                for record in records:
                    try:
                        # Extract key data from CdxRecord
                        url = record.original  # Original URL
                        timestamp = record.timestamp  # Capture timestamp
                        status_code = record.status_code  # HTTP status
                        digest = record.digest  # SHA-1 hash of content

                        # Construct Wayback URL
                        wayback_url = f"https://web.archive.org/web/{timestamp}/{url}"

                        # Get archive date from URL (YYYYMMDD)
                        if "/News/" in url:
                            parts = url.split("/News/")
                            if len(parts) > 1:
                                date_part = parts[1].split("/")[0]
                                archive_date = (
                                    date_part if len(date_part) == 8 else None
                                )
                            else:
                                archive_date = month_start.strftime("%Y%m%d")
                        else:
                            archive_date = month_start.strftime("%Y%m%d")

                        # Insert or update record
                        cursor.execute(
                            """
                            INSERT INTO archive_records 
                            (article_url, wayback_url, archive_date, status, http_status, digest, checked_wayback)
                            VALUES (?, ?, ?, 'exists', ?, ?, 1)
                            ON CONFLICT(article_url) DO UPDATE SET
                                wayback_url = excluded.wayback_url,
                                status = 'exists',
                                http_status = excluded.http_status,
                                digest = excluded.digest,
                                checked_wayback = 1,
                                updated_at = CURRENT_TIMESTAMP
                        """,
                            (url, wayback_url, archive_date, status_code, digest),
                        )
                        stats["inserted"] += 1

                    except Exception as e:
                        print(f"Error processing record {record}: {e}")

            except Exception as e:
                print(f"Error searching CDX for {month_start} to {month_end}: {e}")

            conn.commit()
            volume.commit()

            # Move to next month
            if current_date.month == 12:
                current_date = date(current_date.year + 1, 1, 1)
            else:
                current_date = date(current_date.year, current_date.month + 1, 1)

        conn.close()
        volume.commit()

        stats["duration_seconds"] = (datetime.now() - start_time).total_seconds()
        print(f"Hourly CDX sync completed: {stats}")
        return stats

    except Exception as e:
        print(f"Hourly sync error: {e}")
        import traceback

        traceback.print_exc()
        return {"status": "error", "error": str(e)}


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
    print(
        "  curl -X POST https://yellowcandle--mingpao-archiver-archive-articles.modal.run \\"
    )
    print("    -H 'Content-Type: application/json' \\")
    print('    -d \'{"mode": "date", "date": "2026-01-14", "daily_limit": 5}\'')
    print("=" * 60)
