use chrono::{Local, Timelike};
use rusqlite::{params, Connection};
use serde::Serialize;
use std::collections::BTreeMap;
use std::env;
use std::path::PathBuf;

#[derive(Debug, Serialize)]
struct Metric {
    label: String,
    value: String,
    detail: String,
}

#[derive(Debug, Serialize)]
struct TimelineSegment {
    app: String,
    task: Option<String>,
    start_minute: i64,
    end_minute: i64,
    duration_minutes: i64,
}

#[derive(Debug, Serialize)]
struct AppUsage {
    name: String,
    duration_minutes: i64,
    percent: f64,
}

#[derive(Debug, Serialize)]
struct RecentSession {
    time: String,
    application: String,
    duration_minutes: i64,
    task: Option<String>,
}

#[derive(Debug, Serialize)]
struct DashboardPayload {
    date: String,
    db_path: String,
    has_data: bool,
    event_count: i64,
    focused_minutes: i64,
    active_minutes: i64,
    context_switches: i64,
    current_state: Metric,
    metrics: Vec<Metric>,
    timeline: Vec<TimelineSegment>,
    top_apps: Vec<AppUsage>,
    recent_sessions: Vec<RecentSession>,
}

#[derive(Debug, Serialize)]
struct NotificationPayload {
    id: i64,
    created_at: String,
    title: String,
    body: String,
    state: String,
    kind: String,
}

#[derive(Debug)]
struct EventRow {
    ts_start: String,
    ts_end: String,
    process_name: String,
    idle_seconds: f64,
    keyboard_events: i64,
    mouse_events: i64,
    task_label: Option<String>,
}

#[tauri::command]
fn get_dashboard(date: Option<String>) -> Result<DashboardPayload, String> {
    let target = date.unwrap_or_else(|| Local::now().date_naive().to_string());
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(&db_path).map_err(|err| err.to_string())?;
    let events = load_events_for_day(&conn, &target)?;
    Ok(build_dashboard(target, db_path, events))
}

#[tauri::command]
fn get_notifications(limit: Option<i64>) -> Result<Vec<NotificationPayload>, String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    let table_exists: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'notifications'",
            [],
            |row| row.get(0),
        )
        .map_err(|err| err.to_string())?;
    if table_exists == 0 {
        return Ok(Vec::new());
    }

    let max_rows = limit.unwrap_or(8).clamp(1, 50);
    let mut stmt = conn
        .prepare(
            "SELECT id, created_at, title, body, state, kind
             FROM notifications
             ORDER BY created_at DESC
             LIMIT ?1",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map(params![max_rows], |row| {
            Ok(NotificationPayload {
                id: row.get(0)?,
                created_at: row.get(1)?,
                title: row.get(2)?,
                body: row.get(3)?,
                state: row.get(4)?,
                kind: row.get(5)?,
            })
        })
        .map_err(|err| err.to_string())?;

    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|err| err.to_string())
}

#[tauri::command]
fn mark_notification_read(id: i64) -> Result<(), String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    conn.execute(
        "UPDATE notifications SET state = 'read' WHERE id = ?1",
        params![id],
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn attentionos_db_path() -> Result<PathBuf, String> {
    let root = env::var_os("LOCALAPPDATA")
        .or_else(|| env::var_os("APPDATA"))
        .map(PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA/APPDATA is not available".to_string())?;
    Ok(root.join("AttentionOS").join("attentionos.db"))
}

fn load_events_for_day(conn: &Connection, date: &str) -> Result<Vec<EventRow>, String> {
    let table_exists: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'activity_events'",
            [],
            |row| row.get(0),
        )
        .map_err(|err| err.to_string())?;
    if table_exists == 0 {
        return Ok(Vec::new());
    }

    let mut stmt = conn
        .prepare(
            "SELECT ts_start, ts_end, process_name, idle_seconds, keyboard_events, mouse_events, task_label
             FROM activity_events
             WHERE substr(ts_start, 1, 10) = ?1
             ORDER BY ts_start ASC",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map(params![date], |row| {
            Ok(EventRow {
                ts_start: row.get(0)?,
                ts_end: row.get(1)?,
                process_name: row.get(2)?,
                idle_seconds: row.get(3)?,
                keyboard_events: row.get(4)?,
                mouse_events: row.get(5)?,
                task_label: row.get(6)?,
            })
        })
        .map_err(|err| err.to_string())?;

    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|err| err.to_string())
}

fn build_dashboard(date: String, db_path: PathBuf, events: Vec<EventRow>) -> DashboardPayload {
    let event_count = events.len() as i64;
    let active_seconds = events
        .iter()
        .filter(|event| event.idle_seconds < 120.0)
        .map(event_duration_seconds)
        .sum::<i64>();
    let focused_seconds = events
        .iter()
        .filter(|event| event.idle_seconds < 120.0 && !is_distraction(&event.process_name))
        .map(event_duration_seconds)
        .sum::<i64>();
    let context_switches = count_switches(&events);
    let top_apps = top_apps(&events, active_seconds);
    let timeline = timeline_segments(&events);
    let recent_sessions = recent_sessions(&events);

    let focused_minutes = active_seconds_to_minutes(focused_seconds);
    let active_minutes = active_seconds_to_minutes(active_seconds);
    let state_label = if event_count == 0 {
        "No data yet"
    } else if focused_minutes >= 90 && context_switches < 30 {
        "Deep work"
    } else if focused_minutes >= 30 {
        "Working"
    } else {
        "Warming up"
    };

    DashboardPayload {
        date,
        db_path: db_path.display().to_string(),
        has_data: event_count > 0,
        event_count,
        focused_minutes,
        active_minutes,
        context_switches,
        current_state: Metric {
            label: "Current state".to_string(),
            value: if event_count == 0 {
                "-".to_string()
            } else {
                state_label.to_string()
            },
            detail: "Derived from local telemetry only".to_string(),
        },
        metrics: vec![
            Metric {
                label: "Focused time".to_string(),
                value: format_minutes(focused_minutes),
                detail: "Non-idle work outside common distractions".to_string(),
            },
            Metric {
                label: "Active time".to_string(),
                value: format_minutes(active_minutes),
                detail: "Keyboard, mouse, and foreground activity".to_string(),
            },
            Metric {
                label: "Context switches".to_string(),
                value: context_switches.to_string(),
                detail: "Foreground app changes".to_string(),
            },
            Metric {
                label: "Input events".to_string(),
                value: events
                    .iter()
                    .map(|event| event.keyboard_events + event.mouse_events)
                    .sum::<i64>()
                    .to_string(),
                detail: "Aggregate counts, no typed text".to_string(),
            },
        ],
        timeline,
        top_apps,
        recent_sessions,
    }
}

fn event_duration_seconds(event: &EventRow) -> i64 {
    let start = parse_sqlite_time(&event.ts_start);
    let end = parse_sqlite_time(&event.ts_end);
    end.signed_duration_since(start).num_seconds().max(0)
}

fn parse_sqlite_time(value: &str) -> chrono::NaiveDateTime {
    let normalized = value.replace('T', " ");
    let trimmed = normalized.split('.').next().unwrap_or(&normalized);
    chrono::NaiveDateTime::parse_from_str(trimmed, "%Y-%m-%d %H:%M:%S")
        .unwrap_or_else(|_| Local::now().naive_local())
}

fn minute_of_day(value: &str) -> i64 {
    let time = parse_sqlite_time(value);
    i64::from(time.time().num_seconds_from_midnight() / 60)
}

fn active_seconds_to_minutes(seconds: i64) -> i64 {
    ((seconds as f64) / 60.0).round() as i64
}

fn format_minutes(minutes: i64) -> String {
    let hours = minutes / 60;
    let mins = minutes % 60;
    if hours > 0 {
        format!("{hours}h {mins:02}m")
    } else {
        format!("{mins}m")
    }
}

fn clean_app_name(name: &str) -> String {
    name.trim()
        .strip_suffix(".exe")
        .unwrap_or(name.trim())
        .to_string()
}

fn is_distraction(process_name: &str) -> bool {
    let lower = process_name.to_lowercase();
    ["telegram", "discord", "whatsapp", "steam"]
        .iter()
        .any(|item| lower.contains(item))
}

fn count_switches(events: &[EventRow]) -> i64 {
    events
        .windows(2)
        .filter(|pair| pair[0].process_name != pair[1].process_name)
        .count() as i64
}

fn top_apps(events: &[EventRow], active_seconds: i64) -> Vec<AppUsage> {
    let mut totals = BTreeMap::<String, i64>::new();
    for event in events.iter().filter(|event| event.idle_seconds < 120.0) {
        *totals
            .entry(clean_app_name(&event.process_name))
            .or_default() += event_duration_seconds(event);
    }
    let mut rows = totals
        .into_iter()
        .map(|(name, seconds)| AppUsage {
            name,
            duration_minutes: active_seconds_to_minutes(seconds),
            percent: if active_seconds > 0 {
                seconds as f64 / active_seconds as f64 * 100.0
            } else {
                0.0
            },
        })
        .collect::<Vec<_>>();
    rows.sort_by(|a, b| b.duration_minutes.cmp(&a.duration_minutes));
    rows.truncate(5);
    rows
}

fn timeline_segments(events: &[EventRow]) -> Vec<TimelineSegment> {
    let mut segments = Vec::new();
    for event in events {
        let start = minute_of_day(&event.ts_start);
        let end = minute_of_day(&event.ts_end).max(start + 1);
        if let Some(last) = segments.last_mut() {
            if last.app == clean_app_name(&event.process_name) && last.task == event.task_label {
                last.end_minute = end;
                last.duration_minutes = (last.end_minute - last.start_minute).max(1);
                continue;
            }
        }
        segments.push(TimelineSegment {
            app: clean_app_name(&event.process_name),
            task: event.task_label.clone(),
            start_minute: start,
            end_minute: end,
            duration_minutes: (end - start).max(1),
        });
    }
    segments
}

fn recent_sessions(events: &[EventRow]) -> Vec<RecentSession> {
    timeline_segments(events)
        .into_iter()
        .rev()
        .take(8)
        .map(|segment| RecentSession {
            time: format!(
                "{:02}:{:02}",
                segment.start_minute / 60,
                segment.start_minute % 60
            ),
            application: segment.app,
            duration_minutes: segment.duration_minutes,
            task: segment.task,
        })
        .collect()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_dashboard,
            get_notifications,
            mark_notification_read
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
