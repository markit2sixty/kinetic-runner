"""
Stats Module for PositionAnalyzer
Handles all user statistics calculations and data retrieval
"""

import sqlite3
import os

# Database path - handle both running from WEB folder and ENGINE folder
def get_db_path():
    # Try WEB folder first (when running app.py)
    web_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'WEB', 'master.db')
    if os.path.exists(web_db):
        return web_db
    # Try current directory (when running from WEB folder)
    local_db = 'master.db'
    if os.path.exists(local_db):
        return local_db
    # Default to WEB folder path
    return web_db

DB_PATH = get_db_path()


def get_db_connection():
    """Get a connection to the database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_user_account_info(user_id):
    """
    Get basic account information for a user
    Returns: dict with username and created_at (join date)
    """
    conn = get_db_connection()
    user = conn.execute(
        "SELECT username, created_at FROM users WHERE user_id = ?", 
        (user_id,)
    ).fetchone()
    conn.close()
    
    if user:
        return {
            "username": user['username'],
            "joinDate": user['created_at']
        }
    return None


def get_user_calibration(user_id):
    """
    Get the most recent calibration data for a user
    Returns: dict with mickeys_per_mm and calibration_date, or None
    """
    conn = get_db_connection()
    calibration = conn.execute(
        """SELECT mickeys_per_mm, calibration_date 
           FROM user_profiles 
           WHERE user_id = ? AND mickeys_per_mm IS NOT NULL 
           ORDER BY calibration_date DESC 
           LIMIT 1""", 
        (user_id,)
    ).fetchone()
    conn.close()
    
    if calibration:
        return {
            "mickeys_per_mm": calibration['mickeys_per_mm'],
            "date": calibration['calibration_date']
        }
    return None


def get_user_survey(user_id):
    """
    Get the most recent survey data for a user
    Returns: dict with all survey fields, or None
    """
    conn = get_db_connection()
    survey = conn.execute(
        """SELECT survey_game, survey_sensitivity, survey_skill_level, 
                  survey_aiming_level, survey_mousepad_dims, survey_completed_at
           FROM user_profiles 
           WHERE user_id = ? AND survey_completed_at IS NOT NULL 
           ORDER BY survey_completed_at DESC 
           LIMIT 1""", 
        (user_id,)
    ).fetchone()
    conn.close()
    
    if survey:
        return {
            "game": survey['survey_game'],
            "sensitivity": survey['survey_sensitivity'],
            "skillLevel": survey['survey_skill_level'],
            "aimingLevel": survey['survey_aiming_level'],
            "mousepadDimensions": survey['survey_mousepad_dims'],
            "completedDate": survey['survey_completed_at']
        }
    return None


def get_session_stats(user_id):
    """
    Get session statistics for a user
    A "session" is defined as one start/stop cycle on the recording device
    Returns: dict with totalCount and totalDurationSeconds
    """
    conn = get_db_connection()
    session_stats = conn.execute(
        """SELECT COUNT(*) as total_sessions, 
                  COALESCE(SUM(duration_seconds), 0) as total_duration
           FROM sessions 
           WHERE user_id = ?""", 
        (user_id,)
    ).fetchone()
    conn.close()
    
    return {
        "totalCount": session_stats['total_sessions'] if session_stats else 0,
        "totalDurationSeconds": session_stats['total_duration'] if session_stats else 0
    }


def get_complete_user_stats(user_id):
    """
    Get all user statistics in one call
    Combines account info, calibration, survey, and session stats
    Returns: dict with all user stats
    """
    account_info = get_user_account_info(user_id)
    calibration = get_user_calibration(user_id)
    survey = get_user_survey(user_id)
    sessions = get_session_stats(user_id)
    
    return {
        "success": True,
        "username": account_info['username'] if account_info else None,
        "joinDate": account_info['joinDate'] if account_info else None,
        "calibration": calibration,
        "survey": survey,
        "sessions": sessions
    }


def format_duration(seconds):
    """
    Format duration in seconds to a human-readable string
    Returns: string like "2h 30m" or "45 minutes"
    """
    if not seconds or seconds == 0:
        return "0 minutes"
    
    minutes = int(seconds // 60)
    hours = minutes // 60
    remaining_mins = minutes % 60
    
    if hours > 0:
        return f"{hours}h {remaining_mins}m"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def format_join_date(date_str):
    """
    Format a date string to show time since joining
    Returns: string like "Jan 15, 2026 (18 days ago)"
    """
    if not date_str:
        return "Unknown"
    
    from datetime import datetime
    
    try:
        join_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        now = datetime.now()
        diff = now - join_date
        diff_days = diff.days
        
        if diff_days >= 365:
            years = diff_days // 365
            time_ago = f"{years} year{'s' if years > 1 else ''}"
        elif diff_days >= 30:
            months = diff_days // 30
            time_ago = f"{months} month{'s' if months > 1 else ''}"
        else:
            time_ago = f"{diff_days} day{'s' if diff_days != 1 else ''}"
        
        formatted = join_date.strftime("%b %d, %Y %I:%M %p")
        return f"{formatted} ({time_ago} ago)"
    except:
        return date_str
