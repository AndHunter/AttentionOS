use chrono::{Local, Timelike};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::env;
use std::path::PathBuf;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager};
use winreg::enums::HKEY_CURRENT_USER;
use winreg::RegKey;

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

#[derive(Debug, Clone, Serialize, Deserialize)]
struct UserPreferences {
    language: String,
    theme: String,
    launch_on_startup: bool,
    minimize_to_tray: bool,
    start_minimized: bool,
    current_task_label: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TrackingSettings {
    idle_threshold_minutes: i64,
    track_active_window: bool,
    track_window_titles: bool,
    track_keyboard_activity: bool,
    track_mouse_activity: bool,
    excluded_applications: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct NotificationSettings {
    break_recommendations: bool,
    performance_warnings: bool,
    minimum_interval_minutes: i64,
    live_check_interval_seconds: i64,
    do_not_disturb_start: String,
    do_not_disturb_end: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ModelSettings {
    min_training_samples: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RuntimeSettingsPayload {
    preferences: UserPreferences,
    tracking: TrackingSettings,
    notifications: NotificationSettings,
    model: ModelSettings,
}

impl Default for RuntimeSettingsPayload {
    fn default() -> Self {
        Self {
            preferences: UserPreferences {
                language: "system".to_string(),
                theme: "system".to_string(),
                launch_on_startup: false,
                minimize_to_tray: false,
                start_minimized: false,
                current_task_label: "None".to_string(),
            },
            tracking: TrackingSettings {
                idle_threshold_minutes: 5,
                track_active_window: true,
                track_window_titles: false,
                track_keyboard_activity: true,
                track_mouse_activity: true,
                excluded_applications: Vec::new(),
            },
            notifications: NotificationSettings {
                break_recommendations: true,
                performance_warnings: false,
                minimum_interval_minutes: 30,
                live_check_interval_seconds: 60,
                do_not_disturb_start: "23:00".to_string(),
                do_not_disturb_end: "08:00".to_string(),
            },
            model: ModelSettings {
                min_training_samples: 30,
            },
        }
    }
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

#[derive(Debug)]
struct TimedEvent<'a> {
    event: &'a EventRow,
    duration_seconds: i64,
    start_minute: i64,
    end_minute: i64,
}

#[tauri::command]
fn get_dashboard(date: Option<String>) -> Result<DashboardPayload, String> {
    let target = date.unwrap_or_else(|| Local::now().date_naive().to_string());
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(&db_path).map_err(|err| err.to_string())?;
    let settings = load_runtime_settings();
    let events = load_events_for_day(&conn, &target)?
        .into_iter()
        .filter(|event| {
            !is_excluded_app(
                &event.process_name,
                &settings.tracking.excluded_applications,
            )
        })
        .collect::<Vec<_>>();
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

#[tauri::command]
fn get_settings() -> Result<RuntimeSettingsPayload, String> {
    let path = attentionos_settings_path()?;
    if !path.exists() {
        return Ok(RuntimeSettingsPayload::default());
    }
    let raw = std::fs::read_to_string(path).map_err(|err| err.to_string())?;
    serde_json::from_str(&raw).or_else(|_| Ok(RuntimeSettingsPayload::default()))
}

#[tauri::command]
fn save_settings(app: AppHandle, settings: RuntimeSettingsPayload) -> Result<(), String> {
    let path = attentionos_settings_path()?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let raw = serde_json::to_string_pretty(&settings).map_err(|err| err.to_string())?;
    std::fs::write(path, raw).map_err(|err| err.to_string())?;
    apply_startup_setting(&app, settings.preferences.launch_on_startup)?;
    Ok(())
}

#[tauri::command]
fn export_data() -> Result<String, String> {
    let db_path = attentionos_db_path()?;
    let export_dir = attentionos_data_dir()?.join("exports");
    std::fs::create_dir_all(&export_dir).map_err(|err| err.to_string())?;
    let output = export_dir.join(format!(
        "attentionos_export_{}.json",
        Local::now().format("%Y%m%d_%H%M%S")
    ));
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    let payload = serde_json::json!({
        "activity_events": table_as_json(&conn, "activity_events")?,
        "self_reports": table_as_json(&conn, "self_reports")?,
        "interventions": table_as_json(&conn, "interventions")?,
        "notifications": table_as_json(&conn, "notifications")?,
    });
    std::fs::write(
        &output,
        serde_json::to_string_pretty(&payload).map_err(|err| err.to_string())?,
    )
    .map_err(|err| err.to_string())?;
    Ok(output.display().to_string())
}

#[tauri::command]
fn delete_telemetry() -> Result<(), String> {
    execute_delete(&["activity_events"])
}

#[tauri::command]
fn delete_self_reports() -> Result<(), String> {
    execute_delete(&["self_reports"])
}

#[tauri::command]
fn delete_interventions() -> Result<(), String> {
    execute_delete(&["interventions", "notifications"])
}

#[tauri::command]
fn delete_all_data() -> Result<(), String> {
    execute_delete(&[
        "activity_events",
        "self_reports",
        "interventions",
        "notifications",
    ])
}

#[tauri::command]
fn delete_model() -> Result<(), String> {
    let model_dir = attentionos_data_dir()?.join("models");
    if model_dir.exists() {
        std::fs::remove_dir_all(model_dir).map_err(|err| err.to_string())?;
    }
    Ok(())
}

fn attentionos_db_path() -> Result<PathBuf, String> {
    Ok(attentionos_data_dir()?.join("attentionos.db"))
}

fn attentionos_data_dir() -> Result<PathBuf, String> {
    let root = env::var_os("LOCALAPPDATA")
        .or_else(|| env::var_os("APPDATA"))
        .map(PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA/APPDATA is not available".to_string())?;
    Ok(root.join("AttentionOS"))
}

fn attentionos_settings_path() -> Result<PathBuf, String> {
    Ok(attentionos_data_dir()?.join("settings.json"))
}

fn load_runtime_settings() -> RuntimeSettingsPayload {
    let Ok(path) = attentionos_settings_path() else {
        return RuntimeSettingsPayload::default();
    };
    let Ok(raw) = std::fs::read_to_string(path) else {
        return RuntimeSettingsPayload::default();
    };
    serde_json::from_str(&raw).unwrap_or_default()
}

fn is_excluded_app(process_name: &str, excluded: &[String]) -> bool {
    let normalized = process_name.trim().to_lowercase();
    excluded
        .iter()
        .map(|item| item.trim().to_lowercase())
        .filter(|item| !item.is_empty())
        .any(|item| normalized == item || normalized == format!("{item}.exe"))
}

fn apply_startup_setting(app: &AppHandle, enabled: bool) -> Result<(), String> {
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let (run_key, _) = hkcu
        .create_subkey("Software\\Microsoft\\Windows\\CurrentVersion\\Run")
        .map_err(|err| err.to_string())?;
    if enabled {
        let exe = env::current_exe().map_err(|err| err.to_string())?;
        let value = format!("\"{}\"", exe.display());
        run_key
            .set_value("AttentionOS", &value)
            .map_err(|err| err.to_string())?;
    } else {
        let _ = run_key.delete_value("AttentionOS");
    }
    if let Some(window) = app.get_webview_window("main") {
        let settings = load_runtime_settings();
        if settings.preferences.start_minimized {
            let _ = window.hide();
        }
    }
    Ok(())
}

fn table_exists(conn: &Connection, table: &str) -> Result<bool, String> {
    let count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?1",
            params![table],
            |row| row.get(0),
        )
        .map_err(|err| err.to_string())?;
    Ok(count > 0)
}

fn execute_delete(tables: &[&str]) -> Result<(), String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    for table in tables {
        if table_exists(&conn, table)? {
            conn.execute(&format!("DELETE FROM {table}"), [])
                .map_err(|err| err.to_string())?;
        }
    }
    Ok(())
}

fn table_as_json(conn: &Connection, table: &str) -> Result<Vec<serde_json::Value>, String> {
    if !table_exists(conn, table)? {
        return Ok(Vec::new());
    }
    let mut stmt = conn
        .prepare(&format!("SELECT * FROM {table}"))
        .map_err(|err| err.to_string())?;
    let names = stmt
        .column_names()
        .into_iter()
        .map(str::to_string)
        .collect::<Vec<_>>();
    let rows = stmt
        .query_map([], |row| {
            let mut object = serde_json::Map::new();
            for (index, name) in names.iter().enumerate() {
                let value = row
                    .get::<_, String>(index)
                    .map(serde_json::Value::String)
                    .or_else(|_| row.get::<_, i64>(index).map(serde_json::Value::from))
                    .or_else(|_| row.get::<_, f64>(index).map(serde_json::Value::from))
                    .unwrap_or(serde_json::Value::Null);
                object.insert(name.clone(), value);
            }
            Ok(serde_json::Value::Object(object))
        })
        .map_err(|err| err.to_string())?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|err| err.to_string())
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
    let timed_events = timed_events(&events);
    let event_count = events.len() as i64;
    let active_seconds = timed_events
        .iter()
        .filter(|item| is_active_event(item.event))
        .map(|item| item.duration_seconds)
        .sum::<i64>();
    let focused_seconds = timed_events
        .iter()
        .filter(|item| is_active_event(item.event) && !is_distraction(&item.event.process_name))
        .map(|item| item.duration_seconds)
        .sum::<i64>();
    let context_switches = count_switches(&events);
    let top_apps = top_apps(&timed_events, active_seconds);
    let timeline = timeline_segments(&timed_events);
    let recent_sessions = recent_sessions(&timed_events);

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

fn timed_events(events: &[EventRow]) -> Vec<TimedEvent<'_>> {
    events
        .iter()
        .enumerate()
        .map(|(index, event)| {
            let start_time = parse_sqlite_time(&event.ts_start);
            let raw_seconds = events
                .get(index + 1)
                .map(|next| {
                    parse_sqlite_time(&next.ts_start)
                        .signed_duration_since(start_time)
                        .num_seconds()
                })
                .unwrap_or_else(|| event_duration_seconds(event).max(3));
            let duration_seconds = raw_seconds.clamp(1, 15);
            let start_minute = minute_of_day(&event.ts_start);
            let end_minute = start_minute + ((duration_seconds as f64) / 60.0).ceil() as i64;
            TimedEvent {
                event,
                duration_seconds,
                start_minute,
                end_minute: end_minute.max(start_minute + 1),
            }
        })
        .collect()
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
    if seconds <= 0 {
        0
    } else {
        ((seconds as f64) / 60.0).ceil() as i64
    }
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

fn is_active_event(event: &EventRow) -> bool {
    event.keyboard_events > 0 || event.mouse_events > 0 || event.idle_seconds < 120.0
}

fn count_switches(events: &[EventRow]) -> i64 {
    events
        .windows(2)
        .filter(|pair| pair[0].process_name != pair[1].process_name)
        .count() as i64
}

fn top_apps(events: &[TimedEvent<'_>], active_seconds: i64) -> Vec<AppUsage> {
    let mut totals = BTreeMap::<String, i64>::new();
    for item in events.iter().filter(|item| is_active_event(item.event)) {
        *totals
            .entry(clean_app_name(&item.event.process_name))
            .or_default() += item.duration_seconds;
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

fn timeline_segments(events: &[TimedEvent<'_>]) -> Vec<TimelineSegment> {
    let mut segments: Vec<TimelineSegment> = Vec::new();
    for item in events {
        let start = item.start_minute;
        let end = item.end_minute;
        if let Some(last) = segments.last_mut() {
            if last.app == clean_app_name(&item.event.process_name)
                && last.task == item.event.task_label
            {
                last.end_minute = end;
                last.duration_minutes = (last.end_minute - last.start_minute).max(1);
                continue;
            }
        }
        segments.push(TimelineSegment {
            app: clean_app_name(&item.event.process_name),
            task: item.event.task_label.clone(),
            start_minute: start,
            end_minute: end,
            duration_minutes: (end - start).max(1),
        });
    }
    segments
}

fn recent_sessions(events: &[TimedEvent<'_>]) -> Vec<RecentSession> {
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
            let handle = app.handle().clone();
            apply_startup_setting(
                &handle,
                load_runtime_settings().preferences.launch_on_startup,
            )?;
            let show = MenuItem::with_id(app, "show", "Show AttentionOS", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::with_id("attentionos")
                .tooltip("AttentionOS")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        if let Some(window) = tray.app_handle().get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;
            if load_runtime_settings().preferences.start_minimized {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if load_runtime_settings().preferences.minimize_to_tray {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            get_dashboard,
            get_notifications,
            mark_notification_read,
            get_settings,
            save_settings,
            export_data,
            delete_telemetry,
            delete_self_reports,
            delete_interventions,
            delete_all_data,
            delete_model
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
