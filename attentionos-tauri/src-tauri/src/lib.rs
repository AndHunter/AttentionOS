use chrono::{Local, Timelike};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::env;
use std::fs::{File, OpenOptions};
use std::io::Read;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager};
use winreg::enums::HKEY_CURRENT_USER;
use winreg::RegKey;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct CollectorProcess {
    child: Mutex<Option<Child>>,
}

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
    kind: String,
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
struct StatePoint {
    minute: i64,
    effectiveness: f64,
    decline_risk: f64,
    state: String,
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
    state_history: Vec<StatePoint>,
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

#[derive(Debug, Serialize, Deserialize)]
struct SelfReportPayload {
    effectiveness: i64,
    fatigue: i64,
    difficulty: i64,
    note: String,
    task: Option<String>,
}

#[derive(Debug, Serialize)]
struct BreakStatePayload {
    state: String,
    recommended_minutes: Option<i64>,
    started_at: Option<String>,
    planned_until: Option<String>,
    elapsed_seconds: i64,
    remaining_seconds: i64,
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
                live_check_interval_seconds: 300,
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
fn save_self_report(report: SelfReportPayload) -> Result<(), String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    let now_utc = chrono::Utc::now().naive_utc();
    let window_start = now_utc - chrono::Duration::minutes(30);
    let note = report.note.trim();
    conn.execute(
        "INSERT INTO self_reports (
            timestamp,
            task_name,
            telemetry_window_start,
            telemetry_window_end,
            perceived_effectiveness,
            perceived_fatigue,
            task_difficulty,
            note
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        params![
            now_utc.to_string(),
            report.task,
            window_start.to_string(),
            now_utc.to_string(),
            report.effectiveness.clamp(1, 5),
            report.fatigue.clamp(1, 5),
            report.difficulty.clamp(1, 5),
            if note.is_empty() { None } else { Some(note.to_string()) },
        ],
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

#[tauri::command]
fn evaluate_recommendations() -> Result<Vec<NotificationPayload>, String> {
    run_recommendation_service()?;
    get_notifications(Some(8))
}

#[tauri::command]
fn get_demo_ml_prediction() -> Result<serde_json::Value, String> {
    get_latest_demo_ml_prediction().or_else(|_| {
        Ok(serde_json::json!({
            "mode": "demo",
            "status": "warmup",
            "state": "WORK",
            "reason": "Prediction is not ready yet. Background ML will update it.",
            "recommended_action": "CONTINUE",
            "policy_source": "WARMUP"
        }))
    })
}

fn run_demo_ml_once() -> Result<serde_json::Value, String> {
    let mut command = python_collector_command()?;
    command
        .args(["-m", "attentionos.ml.demo.inference"])
        .stdin(Stdio::null())
        .stderr(Stdio::from(open_collector_log("demo_ml_stderr.log")?))
        .env("PYTHONUTF8", "1")
        .env("PYTHONWARNINGS", "ignore");
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    let output = command
        .output()
        .map_err(|err| format!("Could not run demo ML inference: {err}"))?;
    if !output.status.success() {
        return Err(format!(
            "Demo ML inference exited with status {}. {}",
            output.status,
            demo_ml_stderr_tail()
        ));
    }
    serde_json::from_slice(&output.stdout).map_err(|err| err.to_string())
}

fn spawn_demo_ml_scheduler() {
    thread::spawn(|| {
        thread::sleep(Duration::from_secs(20));
        loop {
            if let Err(err) = run_demo_ml_once() {
                eprintln!("Demo ML scheduler failed: {err}");
            }
            let settings = load_runtime_settings();
            let interval = settings
                .notifications
                .live_check_interval_seconds
                .clamp(60, 1800) as u64;
            thread::sleep(Duration::from_secs(interval));
        }
    });
}

fn get_latest_demo_ml_prediction() -> Result<serde_json::Value, String> {
    let db_path = attentionos_db_path()?;
    if !db_path.exists() {
        return Err("Database does not exist".to_string());
    }
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    let exists: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'ml_predictions'",
            [],
            |row| row.get(0),
        )
        .unwrap_or(0);
    if exists == 0 {
        return Err("No prediction table yet".to_string());
    }
    let mut stmt = conn
        .prepare(
            "SELECT timestamp, model_version, effectiveness, decline_15m, decline_30m, decline_60m, \
             break_benefit, recommended_action, recommended_break_minutes, next_break_eta, confidence, policy_source \
             FROM ml_predictions ORDER BY id DESC LIMIT 1",
        )
        .map_err(|err| err.to_string())?;
    let prediction = stmt
        .query_row([], |row| {
            let action: String = row.get(7)?;
            let break_minutes: Option<i64> = row.get(8)?;
            let confidence: Option<f64> = row.get(10)?;
            let policy_source: Option<String> = row.get(11)?;
            Ok(serde_json::json!({
                "mode": "demo",
                "status": "ready",
                "state": if action.starts_with("BREAK") { "BREAK_RECOMMENDED" } else { "WORK" },
                "model_version": row.get::<_, Option<String>>(1)?.unwrap_or_else(|| "demo-v1".to_string()),
                "current_effectiveness": row.get::<_, Option<f64>>(2)?,
                "decline_15m": row.get::<_, Option<f64>>(3)?,
                "decline_30m": row.get::<_, Option<f64>>(4)?,
                "decline_60m": row.get::<_, Option<f64>>(5)?,
                "decline_probability": row.get::<_, Option<f64>>(4)?,
                "break_benefit": row.get::<_, Option<f64>>(6)?,
                "recommended_action": action,
                "recommended_break_minutes": break_minutes,
                "next_break_eta_minutes": row.get::<_, Option<i64>>(9)?,
                "policy_source": policy_source.clone().unwrap_or_else(|| "MODEL".to_string()),
                "latency_ms": 0,
                "recommendation": {
                    "action": action,
                    "state": if action.starts_with("BREAK") { "BREAK_RECOMMENDED" } else { "WORK" },
                    "title": if action.starts_with("BREAK") { "Break recommended" } else { "Work" },
                    "reason": "Latest persisted background ML prediction.",
                    "confidence": confidence.unwrap_or(0.0),
                    "recommended_break_minutes": break_minutes,
                    "policy_source": policy_source.unwrap_or_else(|| "MODEL".to_string())
                },
                "diagnostics": {
                    "last_inference_at": row.get::<_, Option<String>>(0)?,
                    "source": "sqlite_cache"
                }
            }))
        })
        .map_err(|err| err.to_string())?;
    Ok(prediction)
}

#[tauri::command]
fn create_test_notification() -> Result<NotificationPayload, String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    let now_utc = chrono::Utc::now().naive_utc().to_string();
    conn.execute(
        "INSERT INTO notifications (
            created_at,
            title,
            body,
            state,
            intervention_id,
            kind,
            action_payload
        ) VALUES (?1, ?2, ?3, 'unread', NULL, 'system_test', ?4)",
        params![
            now_utc,
            "AttentionOS test",
            "Test notification from AttentionOS. If you see this, notifications are connected.",
            "{\"source\":\"tauri-test\"}",
        ],
    )
    .map_err(|err| err.to_string())?;
    let id = conn.last_insert_rowid();
    Ok(NotificationPayload {
        id,
        created_at: now_utc,
        title: "AttentionOS test".to_string(),
        body: "Test notification from AttentionOS. If you see this, notifications are connected."
            .to_string(),
        state: "unread".to_string(),
        kind: "system_test".to_string(),
    })
}

#[tauri::command]
fn start_break(minutes: Option<i64>) -> Result<BreakStatePayload, String> {
    let planned = minutes.unwrap_or_else(latest_recommended_break_minutes).clamp(1, 180);
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    let now = chrono::Utc::now().naive_utc();
    let until = now + chrono::Duration::minutes(planned);
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params!["break_state", "BREAK"],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params!["break_started_at", now.to_string()],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params!["break_planned_until", until.to_string()],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "INSERT INTO recommendations (timestamp, recommended_action, recommended_duration, accepted, started_at) \
         VALUES (?1, ?2, ?3, 1, ?1)",
        params![now.to_string(), format!("BREAK_{planned}"), planned],
    )
    .map_err(|err| err.to_string())?;
    get_break_state()
}

#[tauri::command]
fn finish_break() -> Result<BreakStatePayload, String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    let now = chrono::Utc::now().naive_utc();
    let started = runtime_value(&conn, "break_started_at")
        .and_then(|value| parse_sqlite_time_utc(&value).ok());
    let actual = started
        .map(|start| now.signed_duration_since(start).num_minutes().max(0))
        .unwrap_or(0);
    conn.execute(
        "UPDATE recommendations SET completed_at = ?1, actual_duration = ?2 \
         WHERE id = (SELECT id FROM recommendations WHERE started_at IS NOT NULL ORDER BY id DESC LIMIT 1)",
        params![now.to_string(), actual],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params!["break_state", "READY_TO_WORK"],
    )
    .map_err(|err| err.to_string())?;
    get_break_state()
}

#[tauri::command]
fn get_break_state() -> Result<BreakStatePayload, String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    let state = runtime_value(&conn, "break_state").unwrap_or_else(|| "WORK".to_string());
    let started_at = runtime_value(&conn, "break_started_at");
    let planned_until = runtime_value(&conn, "break_planned_until");
    let now = chrono::Utc::now().naive_utc();
    let started = started_at
        .as_ref()
        .and_then(|value| parse_sqlite_time_utc(value).ok());
    let until = planned_until
        .as_ref()
        .and_then(|value| parse_sqlite_time_utc(value).ok());
    let elapsed_seconds = started
        .map(|start| now.signed_duration_since(start).num_seconds().max(0))
        .unwrap_or(0);
    let remaining_seconds = until
        .map(|end| end.signed_duration_since(now).num_seconds().max(0))
        .unwrap_or(0);
    Ok(BreakStatePayload {
        state,
        recommended_minutes: Some(latest_recommended_break_minutes()),
        started_at,
        planned_until,
        elapsed_seconds,
        remaining_seconds,
    })
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
fn start_tracking(state: tauri::State<'_, CollectorProcess>) -> Result<(), String> {
    let mut guard = state.child.lock().map_err(|err| err.to_string())?;
    if let Some(child) = guard.as_mut() {
        if child.try_wait().map_err(|err| err.to_string())?.is_none() {
            return Ok(());
        }
    }
    record_tracking_started()?;
    let stdout = open_collector_log("collector_stdout.log")?;
    let stderr = open_collector_log("collector_stderr.log")?;
    let mut command = python_collector_command()?;
    command
        .args(["-m", "attentionos.collector.engine"])
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .env("PYTHONUTF8", "1");
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    let mut child = command
        .spawn()
        .map_err(|err| format!("Could not start collector via Python: {err}"))?;
    thread::sleep(Duration::from_millis(900));
    if let Some(status) = child.try_wait().map_err(|err| err.to_string())? {
        return Err(format!(
            "Collector exited immediately with status {status}. {}",
            collector_stderr_tail()
        ));
    }
    *guard = Some(child);
    Ok(())
}

fn record_tracking_started() -> Result<(), String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES ('tracking_started_at', ?1) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params![chrono::Utc::now().naive_utc().to_string()],
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn ensure_runtime_state(conn: &Connection) -> Result<(), String> {
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_runtime_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        [],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recommendations (\
         id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, recommended_action TEXT, \
         recommended_duration INTEGER, accepted INTEGER DEFAULT 0, started_at TEXT, completed_at TEXT, actual_duration REAL)",
        [],
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn runtime_value(conn: &Connection, key: &str) -> Option<String> {
    conn.query_row(
        "SELECT value FROM app_runtime_state WHERE key = ?1",
        params![key],
        |row| row.get(0),
    )
    .ok()
}

fn latest_recommended_break_minutes() -> i64 {
    let Ok(db_path) = attentionos_db_path() else {
        return 10;
    };
    let Ok(conn) = Connection::open(db_path) else {
        return 10;
    };
    if !table_exists(&conn, "ml_predictions").unwrap_or(false) {
        return 10;
    }
    conn.query_row(
        "SELECT recommended_break_minutes FROM ml_predictions \
         WHERE recommended_action LIKE 'BREAK_%' AND recommended_break_minutes IS NOT NULL \
         ORDER BY id DESC LIMIT 1",
        [],
        |row| row.get::<_, i64>(0),
    )
    .unwrap_or(10)
}

fn parse_sqlite_time_utc(value: &str) -> Result<chrono::NaiveDateTime, chrono::ParseError> {
    let normalized = value.replace('T', " ");
    let trimmed = normalized.split('.').next().unwrap_or(&normalized);
    chrono::NaiveDateTime::parse_from_str(trimmed, "%Y-%m-%d %H:%M:%S")
}

#[tauri::command]
fn stop_tracking(state: tauri::State<'_, CollectorProcess>) -> Result<(), String> {
    let mut guard = state.child.lock().map_err(|err| err.to_string())?;
    if let Some(child) = guard.as_mut() {
        let _ = child.kill();
        let _ = child.wait();
    }
    *guard = None;
    Ok(())
}

#[tauri::command]
fn get_tracking_status(state: tauri::State<'_, CollectorProcess>) -> Result<bool, String> {
    let mut guard = state.child.lock().map_err(|err| err.to_string())?;
    if let Some(child) = guard.as_mut() {
        if child.try_wait().map_err(|err| err.to_string())?.is_none() {
            return Ok(true);
        }
    }
    *guard = None;
    Ok(false)
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

fn open_collector_log(file_name: &str) -> Result<File, String> {
    let path = attentionos_data_dir()?.join(file_name);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|err| err.to_string())
}

fn collector_stderr_tail() -> String {
    let Ok(path) = attentionos_data_dir().map(|dir| dir.join("collector_stderr.log")) else {
        return String::new();
    };
    let Ok(mut file) = File::open(path) else {
        return String::new();
    };
    let mut raw = String::new();
    let _ = file.read_to_string(&mut raw);
    let tail = raw
        .chars()
        .rev()
        .take(1200)
        .collect::<String>()
        .chars()
        .rev()
        .collect::<String>();
    if tail.trim().is_empty() {
        String::new()
    } else {
        format!("stderr: {tail}")
    }
}

fn python_collector_command() -> Result<Command, String> {
    let candidates: Vec<(&str, Vec<&str>)> = if cfg!(windows) {
        vec![
            ("python", vec!["--version"]),
            ("py", vec!["-3", "--version"]),
        ]
    } else {
        vec![
            ("python3", vec!["--version"]),
            ("python", vec!["--version"]),
        ]
    };

    for (program, args) in candidates {
        let mut probe = Command::new(program);
        probe.args(args);
        #[cfg(windows)]
        probe.creation_flags(CREATE_NO_WINDOW);
        if probe.output().map(|output| output.status.success()).unwrap_or(false) {
            let mut command = Command::new(program);
            if program == "py" {
                command.arg("-3");
            }
            return Ok(command);
        }
    }

    Err("Could not find Python. Install Python 3.12+ and make sure python or py is available in PATH.".to_string())
}

fn run_recommendation_service() -> Result<(), String> {
    let stdout = open_collector_log("recommendations_stdout.log")?;
    let stderr = open_collector_log("recommendations_stderr.log")?;
    let mut command = python_collector_command()?;
    command
        .args([
            "-c",
            "from attentionos.config import get_config; from attentionos.settings import SettingsStore; from attentionos.application.recommendations import RecommendationService; c=get_config(); s=SettingsStore(c.data_dir / 'settings.json').load(); RecommendationService(c, s).evaluate_now()",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .env("PYTHONUTF8", "1");
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    let status = command
        .status()
        .map_err(|err| format!("Could not evaluate recommendations via Python: {err}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "Recommendation evaluation exited with status {status}. {}",
            recommendation_stderr_tail()
        ))
    }
}

fn recommendation_stderr_tail() -> String {
    let Ok(path) = attentionos_data_dir().map(|dir| dir.join("recommendations_stderr.log")) else {
        return String::new();
    };
    let Ok(mut file) = File::open(path) else {
        return String::new();
    };
    let mut raw = String::new();
    let _ = file.read_to_string(&mut raw);
    let tail = raw
        .chars()
        .rev()
        .take(1200)
        .collect::<String>()
        .chars()
        .rev()
        .collect::<String>();
    if tail.trim().is_empty() {
        String::new()
    } else {
        format!("stderr: {tail}")
    }
}

fn demo_ml_stderr_tail() -> String {
    let Ok(path) = attentionos_data_dir().map(|dir| dir.join("demo_ml_stderr.log")) else {
        return String::new();
    };
    let Ok(mut file) = File::open(path) else {
        return String::new();
    };
    let mut raw = String::new();
    let _ = file.read_to_string(&mut raw);
    let tail = raw
        .chars()
        .rev()
        .take(1200)
        .collect::<String>()
        .chars()
        .rev()
        .collect::<String>();
    if tail.trim().is_empty() {
        String::new()
    } else {
        format!("stderr: {tail}")
    }
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
             WHERE substr(datetime(ts_start, 'localtime'), 1, 10) = ?1
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
    let state_history = Connection::open(&db_path)
        .ok()
        .map(|conn| state_history(&conn, &date).unwrap_or_default())
        .unwrap_or_default();
    let timed_events = timed_events(&events);
    let event_count = events.len() as i64;
    let active_seconds = timed_events
        .iter()
        .filter(|item| is_active_event(item.event))
        .map(|item| item.duration_seconds)
        .sum::<i64>();
    let focused_seconds = timed_events
        .iter()
        .filter(|item| is_active_event(item.event))
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
                detail: "Non-idle time for the selected task".to_string(),
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
        state_history,
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
        .map(|utc| {
            chrono::DateTime::<chrono::Utc>::from_naive_utc_and_offset(utc, chrono::Utc)
                .with_timezone(&Local)
                .naive_local()
        })
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
        let is_idle = !is_active_event(item.event);
        let app = if is_idle {
            "Idle".to_string()
        } else {
            clean_app_name(&item.event.process_name)
        };
        let kind = if is_idle { "idle" } else { "app" }.to_string();
        if let Some(last) = segments.last_mut() {
            if last.app == app
                && last.task == item.event.task_label
                && last.kind == kind
            {
                last.end_minute = end;
                last.duration_minutes = (last.end_minute - last.start_minute).max(1);
                continue;
            }
        }
        segments.push(TimelineSegment {
            app,
            task: item.event.task_label.clone(),
            kind,
            start_minute: start,
            end_minute: end,
            duration_minutes: (end - start).max(1),
        });
    }
    segments
}

fn recent_sessions(events: &[TimedEvent<'_>]) -> Vec<RecentSession> {
    let mut blocks: Vec<RecentSession> = Vec::new();
    let mut current_start = 0;
    let mut current_end = 0;
    let mut current_task: Option<String> = None;
    let mut apps = BTreeMap::<String, bool>::new();
    for item in events.iter().filter(|item| is_active_event(item.event)) {
        let task = item.event.task_label.clone();
        let gap = if current_end == 0 { 0 } else { item.start_minute - current_end };
        let should_split = current_end == 0 || current_task != task || gap > 10;
        if should_split && current_end > current_start {
            blocks.push(work_block(current_start, current_end, current_task.clone(), &apps));
            apps.clear();
        }
        if should_split {
            current_start = item.start_minute;
            current_task = task;
        }
        current_end = item.end_minute;
        apps.insert(clean_app_name(&item.event.process_name), true);
    }
    if current_end > current_start {
        blocks.push(work_block(current_start, current_end, current_task, &apps));
    }
    blocks.into_iter().rev().take(8).collect()
}

fn work_block(
    start: i64,
    end: i64,
    task: Option<String>,
    apps: &BTreeMap<String, bool>,
) -> RecentSession {
    RecentSession {
        time: format!(
            "{:02}:{:02}-{:02}:{:02}",
            start / 60,
            start % 60,
            end / 60,
            end % 60
        ),
        application: apps.keys().cloned().collect::<Vec<_>>().join(", "),
        duration_minutes: (end - start).max(1),
        task,
    }
}

fn state_history(conn: &Connection, date: &str) -> Result<Vec<StatePoint>, String> {
    if !table_exists(conn, "ml_predictions")? {
        return Ok(Vec::new());
    }
    let mut stmt = conn
        .prepare(
            "SELECT timestamp, effectiveness, decline_30m, recommended_action \
             FROM ml_predictions \
             WHERE substr(datetime(timestamp, 'localtime'), 1, 10) = ?1 \
             ORDER BY timestamp ASC",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map(params![date], |row| {
            let timestamp: String = row.get(0)?;
            let action: Option<String> = row.get(3)?;
            Ok(StatePoint {
                minute: minute_of_day(&timestamp),
                effectiveness: row.get::<_, Option<f64>>(1)?.unwrap_or(0.0),
                decline_risk: row.get::<_, Option<f64>>(2)?.unwrap_or(0.0),
                state: if action.unwrap_or_default().starts_with("BREAK") {
                    "break".to_string()
                } else {
                    "work".to_string()
                },
            })
        })
        .map_err(|err| err.to_string())?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|err| err.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(CollectorProcess {
            child: Mutex::new(None),
        })
        .plugin(tauri_plugin_notification::init())
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
            spawn_demo_ml_scheduler();
            let show = MenuItem::with_id(app, "show", "Show AttentionOS", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            let mut tray_builder = TrayIconBuilder::with_id("attentionos");
            if let Some(icon) = app.default_window_icon() {
                tray_builder = tray_builder.icon(icon.clone());
            }
            tray_builder
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
            save_self_report,
            evaluate_recommendations,
            get_demo_ml_prediction,
            create_test_notification,
            start_break,
            finish_break,
            get_break_state,
            get_settings,
            save_settings,
            start_tracking,
            stop_tracking,
            get_tracking_status,
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
