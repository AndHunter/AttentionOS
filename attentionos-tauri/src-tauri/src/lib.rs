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
use tauri_plugin_notification::NotificationExt;
use winreg::enums::HKEY_CURRENT_USER;
use winreg::RegKey;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const MAX_EVENT_DURATION_SECONDS: i64 = 15;
const TIMELINE_GAP_IDLE_MINUTES: i64 = 5;
const MIN_FOCUS_BLOCK_SECONDS: i64 = 60;
const OUTCOME_CAPTURE_INTERVAL_SECONDS: u64 = 60;
const OUTCOME_HORIZONS_MINUTES: [i64; 3] = [15, 30, 60];
const SELF_REPORT_SCHEDULER_INTERVAL_SECONDS: u64 = 300;
const MIN_REPORT_INTERVAL_MINUTES: i64 = 45;
const POST_BREAK_REPORT_DELAY_MINUTES: i64 = 15;
const PERSONALIZATION_EXPERIMENTAL_OUTCOMES: i64 = 30;
const PERSONALIZATION_EARLY_OUTCOMES: i64 = 50;
const PERSONALIZATION_TARGET_OUTCOMES: i64 = 100;
const SQLITE_SCHEMA_VERSION: i64 = 4;

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
    state: String,
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
    marker: Option<String>,
    break_benefit: Option<f64>,
}

#[derive(Debug, Serialize)]
struct DailySummaryPayload {
    work_minutes: i64,
    effective_minutes_estimate: i64,
    average_effectiveness: Option<f64>,
    break_count: i64,
    recommendation_count: i64,
    accepted_count: i64,
    ignored_count: i64,
    average_break_minutes: Option<f64>,
    break_effectiveness_delta: Option<f64>,
    average_decline_risk: f64,
    recovered_effective_minutes_estimate: i64,
    recovered_effective_minutes_available: bool,
    personalization_samples_today: i64,
    acceptance_rate: Option<f64>,
    completion_rate: Option<f64>,
    best_period: Option<String>,
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
    daily_summary: DailySummaryPayload,
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

#[derive(Debug, Serialize)]
struct MlDiagnosticsPayload {
    last_inference_at: Option<String>,
    model_version: Option<String>,
    policy_source: Option<String>,
    candidate_utilities: serde_json::Value,
    diagnostics: serde_json::Value,
    current_state: Option<String>,
    latest_recommendation_id: Option<i64>,
    selected_action: Option<String>,
    latest_recommendation_accepted: Option<bool>,
    latest_recommendation_ignored: Option<bool>,
    pending_outcome_captures: i64,
    self_report_next_eligible_at: Option<String>,
    personalization_progress: i64,
    personal_model_status: String,
    real_telemetry_hours: f64,
    self_reports: i64,
    recommendations: i64,
    completed_breaks: i64,
    ignored_recommendations: i64,
    usable_outcomes: i64,
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
                min_training_samples: 5,
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

#[derive(Debug, Clone)]
struct PredictionSnapshot {
    id: i64,
    model_version: Option<String>,
    policy_source: Option<String>,
    effectiveness: f64,
    decline_15: f64,
    decline_30: f64,
    decline_60: f64,
    break_benefit: f64,
}

#[derive(Debug)]
struct OutcomeWindowMetrics {
    active_ratio: f64,
    switch_rate: f64,
    input_rate: f64,
    idle_ratio: f64,
    task_after: Option<String>,
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
    ensure_runtime_state(&conn)?;
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
    Ok(build_dashboard(
        target,
        db_path,
        events,
        (settings.tracking.idle_threshold_minutes * 60) as f64,
    ))
}

#[tauri::command]
fn get_notifications(limit: Option<i64>) -> Result<Vec<NotificationPayload>, String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
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
    mark_break_notifications_read(&conn)?;
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
            if note.is_empty() {
                None
            } else {
                Some(note.to_string())
            },
        ],
    )
    .map_err(|err| err.to_string())?;
    mark_break_notifications_read(&conn)?;
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

#[tauri::command]
fn get_ml_diagnostics() -> Result<MlDiagnosticsPayload, String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    if !table_exists(&conn, "ml_predictions")? {
        return Ok(ml_diagnostics_empty(&conn));
    }
    let candidate_exists = column_exists(&conn, "ml_predictions", "candidate_utilities")?;
    let diagnostics_exists = column_exists(&conn, "ml_predictions", "diagnostics_json")?;
    let sql = format!(
        "SELECT timestamp, model_version, policy_source, {}, {} FROM ml_predictions ORDER BY id DESC LIMIT 1",
        if candidate_exists { "candidate_utilities" } else { "NULL" },
        if diagnostics_exists { "diagnostics_json" } else { "NULL" }
    );
    conn.query_row(&sql, [], |row| {
        let candidate_raw: Option<String> = row.get(3)?;
        let diagnostics_raw: Option<String> = row.get(4)?;
        let progress = ml_progress(&conn);
        let latest_recommendation = latest_recommendation_status(&conn);
        Ok(MlDiagnosticsPayload {
            last_inference_at: row.get(0)?,
            model_version: row.get(1)?,
            policy_source: row.get(2)?,
            candidate_utilities: parse_json_object(candidate_raw),
            diagnostics: parse_json_object(diagnostics_raw),
            current_state: runtime_value(&conn, "break_state").or_else(|| Some("WORK".to_string())),
            latest_recommendation_id: latest_recommendation.as_ref().map(|item| item.0),
            selected_action: latest_recommendation
                .as_ref()
                .and_then(|item| item.1.clone()),
            latest_recommendation_accepted: latest_recommendation.as_ref().map(|item| item.2),
            latest_recommendation_ignored: latest_recommendation.as_ref().map(|item| item.3),
            pending_outcome_captures: pending_outcome_capture_count(&conn).unwrap_or_default(),
            self_report_next_eligible_at: self_report_next_eligible_at(&conn),
            personalization_progress: personalization_progress(progress.usable_outcomes),
            personal_model_status: personal_model_status(progress.usable_outcomes),
            real_telemetry_hours: progress.real_telemetry_hours,
            self_reports: progress.self_reports,
            recommendations: progress.recommendations,
            completed_breaks: progress.completed_breaks,
            ignored_recommendations: progress.ignored_recommendations,
            usable_outcomes: progress.usable_outcomes,
        })
    })
    .or_else(|_| Ok(ml_diagnostics_empty(&conn)))
}

struct MlProgress {
    real_telemetry_hours: f64,
    self_reports: i64,
    recommendations: i64,
    completed_breaks: i64,
    ignored_recommendations: i64,
    usable_outcomes: i64,
}

fn ml_diagnostics_empty(conn: &Connection) -> MlDiagnosticsPayload {
    let progress = ml_progress(conn);
    let latest_recommendation = latest_recommendation_status(conn);
    MlDiagnosticsPayload {
        last_inference_at: None,
        model_version: None,
        policy_source: None,
        candidate_utilities: serde_json::json!({}),
        diagnostics: serde_json::json!({}),
        current_state: runtime_value(conn, "break_state").or_else(|| Some("WORK".to_string())),
        latest_recommendation_id: latest_recommendation.as_ref().map(|item| item.0),
        selected_action: latest_recommendation
            .as_ref()
            .and_then(|item| item.1.clone()),
        latest_recommendation_accepted: latest_recommendation.as_ref().map(|item| item.2),
        latest_recommendation_ignored: latest_recommendation.as_ref().map(|item| item.3),
        pending_outcome_captures: pending_outcome_capture_count(conn).unwrap_or_default(),
        self_report_next_eligible_at: self_report_next_eligible_at(conn),
        personalization_progress: personalization_progress(progress.usable_outcomes),
        personal_model_status: personal_model_status(progress.usable_outcomes),
        real_telemetry_hours: progress.real_telemetry_hours,
        self_reports: progress.self_reports,
        recommendations: progress.recommendations,
        completed_breaks: progress.completed_breaks,
        ignored_recommendations: progress.ignored_recommendations,
        usable_outcomes: progress.usable_outcomes,
    }
}

fn ml_progress(conn: &Connection) -> MlProgress {
    let action_outcomes = table_count(conn, "action_outcomes");
    MlProgress {
        real_telemetry_hours: telemetry_hours(conn),
        self_reports: table_count(conn, "self_reports"),
        recommendations: table_count(conn, "recommendations"),
        completed_breaks: scalar_count(
            conn,
            "SELECT COUNT(*) FROM recommendations WHERE completed_at IS NOT NULL",
        ),
        ignored_recommendations: scalar_count(
            conn,
            "SELECT COUNT(*) FROM recommendations WHERE COALESCE(ignored, 0) = 1",
        ),
        usable_outcomes: if action_outcomes > 0 {
            action_outcomes
        } else {
            table_count(conn, "recommendation_outcomes")
        },
    }
}

fn personalization_progress(usable_outcomes: i64) -> i64 {
    usable_outcomes.clamp(0, PERSONALIZATION_TARGET_OUTCOMES)
}

fn personal_model_status(usable_outcomes: i64) -> String {
    if usable_outcomes >= PERSONALIZATION_TARGET_OUTCOMES {
        "eligible".to_string()
    } else if usable_outcomes >= PERSONALIZATION_EARLY_OUTCOMES {
        "early_personalization".to_string()
    } else if usable_outcomes >= PERSONALIZATION_EXPERIMENTAL_OUTCOMES {
        "experimental".to_string()
    } else {
        "collecting".to_string()
    }
}

fn latest_recommendation_status(conn: &Connection) -> Option<(i64, Option<String>, bool, bool)> {
    if !table_exists(conn, "recommendations").unwrap_or(false) {
        return None;
    }
    conn.query_row(
        "SELECT id, recommended_action, COALESCE(accepted, 0), COALESCE(ignored, 0) \
         FROM recommendations ORDER BY id DESC LIMIT 1",
        [],
        |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, i64>(2)? == 1,
                row.get::<_, i64>(3)? == 1,
            ))
        },
    )
    .ok()
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

#[tauri::command]
fn train_personal_model(min_samples: Option<i64>) -> Result<serde_json::Value, String> {
    let mut command = python_collector_command()?;
    let min_samples = min_samples.unwrap_or(5).clamp(3, 500).to_string();
    command
        .args([
            "-m",
            "attentionos.ml.personal_train",
            "--min-samples",
            min_samples.as_str(),
        ])
        .stdin(Stdio::null())
        .stderr(Stdio::from(open_collector_log("personal_ml_stderr.log")?))
        .env("PYTHONUTF8", "1")
        .env("PYTHONWARNINGS", "ignore");
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    let output = command
        .output()
        .map_err(|err| format!("Could not train personal ML model: {err}"))?;
    if !output.status.success() {
        return Err(format!(
            "Personal ML training exited with status {}.",
            output.status
        ));
    }
    serde_json::from_slice(&output.stdout).map_err(|err| err.to_string())
}

fn column_exists(conn: &Connection, table: &str, column: &str) -> Result<bool, String> {
    let mut stmt = conn
        .prepare(&format!("PRAGMA table_info({table})"))
        .map_err(|err| err.to_string())?;
    let columns = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(|err| err.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| err.to_string())?;
    Ok(columns.iter().any(|item| item == column))
}

fn parse_json_object(value: Option<String>) -> serde_json::Value {
    value
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_else(|| serde_json::json!({}))
}

fn table_count(conn: &Connection, table: &str) -> i64 {
    if !table_exists(conn, table).unwrap_or(false) {
        return 0;
    }
    scalar_count(conn, &format!("SELECT COUNT(*) FROM {table}"))
}

fn scalar_count(conn: &Connection, sql: &str) -> i64 {
    conn.query_row(sql, [], |row| row.get::<_, i64>(0))
        .unwrap_or(0)
}

fn telemetry_hours(conn: &Connection) -> f64 {
    if !table_exists(conn, "activity_events").unwrap_or(false) {
        return 0.0;
    }
    conn.query_row(
        "SELECT COALESCE(SUM(MAX((julianday(ts_end) - julianday(ts_start)) * 86400.0, 0)), 0) / 3600.0 FROM activity_events",
        [],
        |row| row.get::<_, f64>(0),
    )
    .unwrap_or(0.0)
}

fn spawn_demo_ml_scheduler(app: AppHandle) {
    thread::spawn(move || {
        thread::sleep(Duration::from_secs(20));
        loop {
            if let Err(err) = run_demo_ml_once() {
                eprintln!("Demo ML scheduler failed: {err}");
            } else if let Err(err) = deliver_latest_model_notification(&app) {
                eprintln!("Demo ML notification delivery failed: {err}");
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

fn deliver_latest_model_notification(app: &AppHandle) -> Result<(), String> {
    let db_path = attentionos_db_path()?;
    if !db_path.exists() {
        return Ok(());
    }
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    let last_id = runtime_value(&conn, "last_native_notification_id")
        .and_then(|value| value.parse::<i64>().ok())
        .unwrap_or(0);
    let settings = load_runtime_settings();
    if !settings.notifications.break_recommendations || notifications_quiet_now(&settings) {
        mark_latest_ml_notifications_seen(&conn)?;
        return Ok(());
    }
    let freshness_seconds = (settings
        .notifications
        .live_check_interval_seconds
        .clamp(60, 1800)
        * 2)
    .max(900);
    let freshness_cutoff =
        chrono::Utc::now().naive_utc() - chrono::Duration::seconds(freshness_seconds);
    let query = if runtime_value(&conn, "break_state").as_deref() == Some("BREAK") {
        "SELECT id, title, body FROM notifications \
         WHERE state = 'unread' AND kind LIKE 'ml_%' AND kind != 'ml_break_recommendation' AND id > ?1 \
         AND created_at >= ?2 \
         ORDER BY id DESC LIMIT 1"
    } else {
        "SELECT id, title, body FROM notifications \
         WHERE state = 'unread' AND kind LIKE 'ml_%' AND id > ?1 \
         AND created_at >= ?2 \
         ORDER BY id DESC LIMIT 1"
    };
    let rows = {
        let mut stmt = conn.prepare(query).map_err(|err| err.to_string())?;
        let rows = stmt
            .query_map(params![last_id, freshness_cutoff.to_string()], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(|err| err.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|err| err.to_string())?
    };
    for (id, title, body) in rows {
        show_app_notification(app, &title, &body);
        set_runtime_value(&conn, "last_native_notification_id", &id.to_string())?;
    }
    Ok(())
}

fn spawn_break_monitor(app: AppHandle) {
    thread::spawn(move || loop {
        if let Err(err) = complete_expired_break(&app) {
            eprintln!("Break monitor failed: {err}");
        }
        thread::sleep(Duration::from_secs(10));
    });
}

fn spawn_outcome_capture_scheduler() {
    thread::spawn(move || loop {
        if let Err(err) = capture_pending_action_outcomes() {
            eprintln!("Outcome capture scheduler failed: {err}");
        }
        thread::sleep(Duration::from_secs(OUTCOME_CAPTURE_INTERVAL_SECONDS));
    });
}

fn spawn_self_report_scheduler(app: AppHandle) {
    thread::spawn(move || loop {
        if let Err(err) = maybe_prompt_self_report(&app) {
            eprintln!("Self-report scheduler failed: {err}");
        }
        thread::sleep(Duration::from_secs(SELF_REPORT_SCHEDULER_INTERVAL_SECONDS));
    });
}

fn complete_expired_break(app: &AppHandle) -> Result<(), String> {
    let db_path = attentionos_db_path()?;
    if !db_path.exists() {
        return Ok(());
    }
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    if runtime_value(&conn, "break_state").as_deref() != Some("BREAK") {
        return Ok(());
    }
    let Some(planned_until) = runtime_value(&conn, "break_planned_until") else {
        return Ok(());
    };
    let planned = parse_sqlite_time_utc(&planned_until).map_err(|err| err.to_string())?;
    let now = chrono::Utc::now().naive_utc();
    if now < planned {
        return Ok(());
    }
    complete_break_in_conn(&conn, now)?;
    if runtime_value(&conn, "break_ready_notified_for").as_deref() == Some(planned_until.as_str()) {
        return Ok(());
    }
    set_runtime_value(&conn, "break_ready_notified_for", &planned_until)?;
    let local_time = Local::now().format("%H:%M").to_string();
    let body = format!("{local_time} - Можно возвращаться к работе. Перерыв завершен.");
    let notification_id = insert_app_notification(
        &conn,
        "AttentionOS",
        &body,
        "ml_ready_to_work",
        "{\"source\":\"break-monitor\"}",
    )?;
    set_runtime_value(
        &conn,
        "last_native_notification_id",
        &notification_id.to_string(),
    )?;
    if !notifications_quiet_now(&load_runtime_settings()) {
        show_app_notification(app, "AttentionOS", &body);
    }
    Ok(())
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
    let mut prediction = stmt
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
    if break_ignore_active(&conn) {
        prediction["state"] = serde_json::json!("WORK");
        prediction["recommended_action"] = serde_json::json!("CONTINUE");
        prediction["recommended_break_minutes"] = serde_json::Value::Null;
        prediction["next_break_eta_minutes"] = serde_json::json!(5);
        prediction["policy_source"] = serde_json::json!("FALLBACK");
        prediction["recommendation"]["action"] = serde_json::json!("CONTINUE");
        prediction["recommendation"]["state"] = serde_json::json!("WORK");
        prediction["recommendation"]["title"] = serde_json::json!("Work");
        prediction["recommendation"]["reason"] =
            serde_json::json!("ignore_cooldown: user ignored the break recommendation.");
        prediction["recommendation"]["recommended_break_minutes"] = serde_json::Value::Null;
        prediction["recommendation"]["policy_source"] = serde_json::json!("FALLBACK");
    }
    match runtime_value(&conn, "break_state").as_deref() {
        Some("BREAK") => {
            let minutes = runtime_value(&conn, "break_planned_until")
                .and_then(|value| parse_sqlite_time_utc(&value).ok())
                .map(|until| {
                    until
                        .signed_duration_since(chrono::Utc::now().naive_utc())
                        .num_minutes()
                        .max(1)
                })
                .unwrap_or_else(latest_recommended_break_minutes);
            prediction["state"] = serde_json::json!("BREAK");
            prediction["recommended_action"] = serde_json::json!(format!("BREAK_{minutes}"));
            prediction["recommended_break_minutes"] = serde_json::json!(minutes);
            prediction["next_break_eta_minutes"] = serde_json::json!(0);
            prediction["policy_source"] = serde_json::json!("FALLBACK");
            prediction["recommendation"]["action"] = serde_json::json!(format!("BREAK_{minutes}"));
            prediction["recommendation"]["state"] = serde_json::json!("BREAK");
            prediction["recommendation"]["title"] = serde_json::json!("Break in progress");
            prediction["recommendation"]["reason"] = serde_json::json!(
                "break_timer: recommendation is locked until the planned break ends."
            );
            prediction["recommendation"]["recommended_break_minutes"] = serde_json::json!(minutes);
            prediction["recommendation"]["policy_source"] = serde_json::json!("FALLBACK");
        }
        Some("READY_TO_WORK") => {
            prediction["state"] = serde_json::json!("WORK");
            prediction["recommended_action"] = serde_json::json!("CONTINUE");
            prediction["recommended_break_minutes"] = serde_json::Value::Null;
            prediction["next_break_eta_minutes"] = serde_json::json!(5);
            prediction["policy_source"] = serde_json::json!("FALLBACK");
            prediction["recommendation"]["action"] = serde_json::json!("CONTINUE");
            prediction["recommendation"]["state"] = serde_json::json!("WORK");
            prediction["recommendation"]["title"] = serde_json::json!("Work");
            prediction["recommendation"]["reason"] =
                serde_json::json!("break_completed: planned break finished and work can resume.");
            prediction["recommendation"]["recommended_break_minutes"] = serde_json::Value::Null;
            prediction["recommendation"]["policy_source"] = serde_json::json!("FALLBACK");
        }
        _ => {}
    }
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
    let planned = minutes
        .unwrap_or_else(latest_recommended_break_minutes)
        .clamp(1, 180);
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    let now = chrono::Utc::now().naive_utc();
    let until = now + chrono::Duration::minutes(planned);
    let task_before = current_task_label();
    set_runtime_value(
        &conn,
        "pre_break_task_label",
        task_before.as_deref().unwrap_or("None"),
    )?;
    set_current_task_label_value("rest")?;
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
    set_runtime_value(&conn, "break_ready_notified_for", "")?;
    mark_break_notifications_read(&conn)?;
    let snapshot = latest_prediction_snapshot(&conn);
    let prediction_before_id = snapshot.as_ref().map(|item| item.id);
    let updated = conn
        .execute(
            "UPDATE recommendations SET accepted = 1, ignored = 0, started_at = ?1, break_started_at = ?1, \
             recommended_duration = COALESCE(recommended_duration, ?2), recommended_break_minutes = COALESCE(recommended_break_minutes, ?2), \
             prediction_before_id = COALESCE(prediction_before_id, ?3), task_before = COALESCE(task_before, ?4), \
             task_id = COALESCE(task_id, ?4), task_category = COALESCE(task_category, ?5), \
             model_version = COALESCE(model_version, ?6), policy_source = COALESCE(policy_source, ?7), \
             effectiveness_before = COALESCE(effectiveness_before, ?8), decline_15 = COALESCE(decline_15, ?9), \
             decline_30 = COALESCE(decline_30, ?10), decline_60 = COALESCE(decline_60, ?11), \
             break_benefit = COALESCE(break_benefit, ?12) \
             WHERE id = (SELECT id FROM recommendations WHERE recommended_action LIKE 'BREAK_%' AND completed_at IS NULL AND COALESCE(ignored, 0) = 0 ORDER BY id DESC LIMIT 1)",
            params![
                now.to_string(),
                planned,
                prediction_before_id,
                task_before,
                task_category_for(task_before.as_deref()),
                snapshot.as_ref().and_then(|item| item.model_version.clone()),
                snapshot.as_ref().and_then(|item| item.policy_source.clone()),
                snapshot.as_ref().map(|item| item.effectiveness),
                snapshot.as_ref().map(|item| item.decline_15),
                snapshot.as_ref().map(|item| item.decline_30),
                snapshot.as_ref().map(|item| item.decline_60),
                snapshot.as_ref().map(|item| item.break_benefit),
            ],
        )
        .map_err(|err| err.to_string())?;
    if updated == 0 {
        conn.execute(
            "INSERT INTO recommendations (timestamp, created_at, model_version, policy_source, recommended_action, \
             recommended_duration, recommended_break_minutes, accepted, ignored, started_at, break_started_at, \
             prediction_before_id, task_before, task_id, task_category, effectiveness_before, decline_15, decline_30, \
             decline_60, break_benefit) \
             VALUES (?1, ?1, ?2, ?3, ?4, ?5, ?5, 1, 0, ?1, ?1, ?6, ?7, ?7, ?8, ?9, ?10, ?11, ?12, ?13)",
            params![
                now.to_string(),
                snapshot.as_ref().and_then(|item| item.model_version.clone()),
                snapshot.as_ref().and_then(|item| item.policy_source.clone()),
                format!("BREAK_{planned}"),
                planned,
                prediction_before_id,
                task_before,
                task_category_for(task_before.as_deref()),
                snapshot.as_ref().map(|item| item.effectiveness),
                snapshot.as_ref().map(|item| item.decline_15),
                snapshot.as_ref().map(|item| item.decline_30),
                snapshot.as_ref().map(|item| item.decline_60),
                snapshot.as_ref().map(|item| item.break_benefit),
            ],
        )
        .map_err(|err| err.to_string())?;
    }
    get_break_state()
}

#[tauri::command]
fn ignore_break() -> Result<BreakStatePayload, String> {
    let db_path = attentionos_db_path()?;
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    let settings = load_runtime_settings();
    let now = chrono::Utc::now().naive_utc();
    let until = now + chrono::Duration::minutes(settings.notifications.minimum_interval_minutes);
    let recommendation_id = latest_actionable_break_recommendation_id(&conn)
        .or_else(|| latest_break_recommendation_id(&conn));
    let snapshot = latest_prediction_snapshot(&conn);
    let prediction_before_id = snapshot.as_ref().map(|item| item.id);
    let task_before = current_task_label();
    conn.execute(
        "UPDATE recommendations SET accepted = 0, ignored = 1, ignored_at = ?1, \
         prediction_before_id = COALESCE(prediction_before_id, ?2), task_before = COALESCE(task_before, ?3), \
         task_id = COALESCE(task_id, ?3), task_category = COALESCE(task_category, ?4), \
         model_version = COALESCE(model_version, ?5), policy_source = COALESCE(policy_source, ?6), \
         effectiveness_before = COALESCE(effectiveness_before, ?7), decline_15 = COALESCE(decline_15, ?8), \
         decline_30 = COALESCE(decline_30, ?9), decline_60 = COALESCE(decline_60, ?10), \
         break_benefit = COALESCE(break_benefit, ?11) \
         WHERE id = COALESCE(?12, (SELECT id FROM recommendations WHERE recommended_action LIKE 'BREAK_%' ORDER BY id DESC LIMIT 1))",
        params![
            now.to_string(),
            prediction_before_id,
            task_before,
            task_category_for(task_before.as_deref()),
            snapshot.as_ref().and_then(|item| item.model_version.clone()),
            snapshot.as_ref().and_then(|item| item.policy_source.clone()),
            snapshot.as_ref().map(|item| item.effectiveness),
            snapshot.as_ref().map(|item| item.decline_15),
            snapshot.as_ref().map(|item| item.decline_30),
            snapshot.as_ref().map(|item| item.decline_60),
            snapshot.as_ref().map(|item| item.break_benefit),
            recommendation_id,
        ],
    )
    .map_err(|err| err.to_string())?;
    if let Some(id) = recommendation_id {
        persist_recommendation_outcome(&conn, id, false, true)?;
    }
    mark_break_notifications_read(&conn)?;
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params!["break_ignore_until", until.to_string()],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params!["break_state", "WORK"],
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
    complete_break_in_conn(&conn, now)?;
    get_break_state()
}

fn complete_break_in_conn(conn: &Connection, now: chrono::NaiveDateTime) -> Result<(), String> {
    let started = runtime_value(conn, "break_started_at")
        .and_then(|value| parse_sqlite_time_utc(&value).ok());
    let actual = started
        .map(|start| now.signed_duration_since(start).num_minutes().max(0))
        .unwrap_or(0);
    let actual_seconds = started
        .map(|start| now.signed_duration_since(start).num_seconds().max(0))
        .unwrap_or(0);
    let recommendation_id = latest_started_recommendation_id(conn);
    let prediction_after_id = latest_prediction_id(conn);
    let restored_task = runtime_value(conn, "pre_break_task_label")
        .filter(|value| {
            let trimmed = value.trim();
            !trimmed.is_empty()
                && !trimmed.eq_ignore_ascii_case("none")
                && !trimmed.eq_ignore_ascii_case("rest")
        })
        .unwrap_or_else(|| "work".to_string());
    let task_after = Some(restored_task.clone());
    conn.execute(
        "UPDATE recommendations SET completed_at = ?1, break_finished_at = ?1, actual_duration = ?2, \
         actual_break_seconds = ?5, prediction_after_id = ?3, task_after = ?4 \
         WHERE id = (SELECT id FROM recommendations WHERE started_at IS NOT NULL AND completed_at IS NULL ORDER BY id DESC LIMIT 1)",
        params![now.to_string(), actual, prediction_after_id, task_after, actual_seconds],
    )
    .map_err(|err| err.to_string())?;
    if let Some(id) = recommendation_id {
        persist_recommendation_outcome(conn, id, true, false)?;
    }
    set_runtime_value(conn, "break_state", "READY_TO_WORK")?;
    set_runtime_value(conn, "last_meaningful_break_at", &now.to_string())?;
    set_runtime_value(conn, "current_work_episode_started_at", &now.to_string())?;
    set_runtime_value(conn, "ready_to_work_since", &now.to_string())?;
    set_runtime_value(conn, "pre_break_task_label", "")?;
    set_current_task_label_value(&restored_task)?;
    Ok(())
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
    write_runtime_settings(&settings)?;
    apply_startup_setting(&app, settings.preferences.launch_on_startup)?;
    Ok(())
}

fn write_runtime_settings(settings: &RuntimeSettingsPayload) -> Result<(), String> {
    let path = attentionos_settings_path()?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let raw = serde_json::to_string_pretty(&settings).map_err(|err| err.to_string())?;
    std::fs::write(path, raw).map_err(|err| err.to_string())?;
    Ok(())
}

fn set_current_task_label_value(label: &str) -> Result<(), String> {
    let mut settings = load_runtime_settings();
    settings.preferences.current_task_label = label.to_string();
    write_runtime_settings(&settings)
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
    conn.pragma_update(None, "user_version", SQLITE_SCHEMA_VERSION)
        .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_runtime_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        [],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ml_predictions (\
         id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, model_version TEXT, \
         effectiveness REAL, decline_15m REAL, decline_30m REAL, decline_60m REAL, \
         continue_utility REAL, best_break_utility REAL, break_benefit REAL, \
         recommended_action TEXT, recommended_break_minutes INTEGER, next_break_eta INTEGER, \
         confidence REAL, policy_source TEXT, candidate_utilities TEXT, diagnostics_json TEXT)",
        [],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recommendations (\
         id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, recommended_action TEXT, \
         recommended_duration INTEGER, accepted INTEGER DEFAULT 0, ignored INTEGER DEFAULT 0, \
         started_at TEXT, completed_at TEXT, ignored_at TEXT, actual_duration REAL, \
         prediction_before_id INTEGER, prediction_after_id INTEGER, task_before TEXT, task_after TEXT)",
        [],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recommendation_outcomes (\
         id INTEGER PRIMARY KEY AUTOINCREMENT, recommendation_id INTEGER, created_at TEXT NOT NULL, \
         action TEXT, accepted INTEGER DEFAULT 0, ignored INTEGER DEFAULT 0, planned_duration INTEGER, \
         actual_duration REAL, prediction_before_id INTEGER, prediction_after_id INTEGER, \
         effectiveness_before REAL, effectiveness_after REAL, decline_30m_before REAL, decline_30m_after REAL, \
         task_before TEXT, task_after TEXT, active_minutes_during_break REAL, idle_minutes_during_break REAL, \
         rest_task_minutes_during_break REAL, restful_break_score REAL)",
        [],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS action_outcomes (\
         id INTEGER PRIMARY KEY AUTOINCREMENT, recommendation_id INTEGER NOT NULL, action TEXT NOT NULL, \
         captured_at TEXT NOT NULL, prediction_after_id INTEGER, effectiveness_after REAL, \
         decline_15_after REAL, decline_30_after REAL, decline_60_after REAL, \
         active_ratio_after REAL, switch_rate_after REAL, input_rate_after REAL, idle_ratio_after REAL, \
         task_after TEXT, minutes_since_action INTEGER NOT NULL)",
        [],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_action_outcomes_recommendation_horizon \
         ON action_outcomes(recommendation_id, minutes_since_action)",
        [],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recommendations_created_at ON recommendations(created_at)",
        [],
    )
    .ok();
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_outcomes_captured_at ON action_outcomes(captured_at)",
        [],
    )
    .ok();
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notifications (\
         id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, \
         state TEXT NOT NULL, intervention_id INTEGER, kind TEXT NOT NULL, action_payload TEXT)",
        [],
    )
    .map_err(|err| err.to_string())?;
    ensure_column(conn, "recommendations", "ignored", "INTEGER DEFAULT 0")?;
    ensure_column(conn, "ml_predictions", "candidate_utilities", "TEXT")?;
    ensure_column(conn, "ml_predictions", "diagnostics_json", "TEXT")?;
    ensure_column(conn, "recommendations", "ignored_at", "TEXT")?;
    ensure_column(conn, "recommendations", "prediction_before_id", "INTEGER")?;
    ensure_column(conn, "recommendations", "prediction_after_id", "INTEGER")?;
    ensure_column(conn, "recommendations", "task_before", "TEXT")?;
    ensure_column(conn, "recommendations", "task_after", "TEXT")?;
    ensure_column(conn, "recommendations", "created_at", "TEXT")?;
    ensure_column(conn, "recommendations", "model_version", "TEXT")?;
    ensure_column(conn, "recommendations", "policy_source", "TEXT")?;
    ensure_column(
        conn,
        "recommendations",
        "recommended_break_minutes",
        "INTEGER",
    )?;
    ensure_column(conn, "recommendations", "decline_15", "REAL")?;
    ensure_column(conn, "recommendations", "decline_30", "REAL")?;
    ensure_column(conn, "recommendations", "decline_60", "REAL")?;
    ensure_column(conn, "recommendations", "effectiveness_before", "REAL")?;
    ensure_column(conn, "recommendations", "break_benefit", "REAL")?;
    ensure_column(conn, "recommendations", "break_started_at", "TEXT")?;
    ensure_column(conn, "recommendations", "break_finished_at", "TEXT")?;
    ensure_column(conn, "recommendations", "actual_break_seconds", "INTEGER")?;
    ensure_column(conn, "recommendations", "task_id", "TEXT")?;
    ensure_column(conn, "recommendations", "task_category", "TEXT")?;
    conn.execute(
        "UPDATE recommendations SET created_at = COALESCE(created_at, timestamp)",
        [],
    )
    .ok();
    conn.execute(
        "UPDATE recommendations SET recommended_break_minutes = COALESCE(recommended_break_minutes, recommended_duration)",
        [],
    )
    .ok();
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recommendations_created_at ON recommendations(created_at)",
        [],
    )
    .ok();
    ensure_column(
        conn,
        "recommendation_outcomes",
        "active_minutes_during_break",
        "REAL",
    )?;
    ensure_column(
        conn,
        "recommendation_outcomes",
        "idle_minutes_during_break",
        "REAL",
    )?;
    ensure_column(
        conn,
        "recommendation_outcomes",
        "rest_task_minutes_during_break",
        "REAL",
    )?;
    ensure_column(
        conn,
        "recommendation_outcomes",
        "restful_break_score",
        "REAL",
    )?;
    Ok(())
}

fn ensure_column(
    conn: &Connection,
    table: &str,
    column: &str,
    definition: &str,
) -> Result<(), String> {
    let mut stmt = conn
        .prepare(&format!("PRAGMA table_info({table})"))
        .map_err(|err| err.to_string())?;
    let columns = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(|err| err.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| err.to_string())?;
    if !columns.iter().any(|item| item == column) {
        conn.execute(
            &format!("ALTER TABLE {table} ADD COLUMN {column} {definition}"),
            [],
        )
        .map_err(|err| err.to_string())?;
    }
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

fn set_runtime_value(conn: &Connection, key: &str, value: &str) -> Result<(), String> {
    conn.execute(
        "INSERT INTO app_runtime_state (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params![key, value],
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn insert_app_notification(
    conn: &Connection,
    title: &str,
    body: &str,
    kind: &str,
    action_payload: &str,
) -> Result<i64, String> {
    ensure_runtime_state(conn)?;
    conn.execute(
        "INSERT INTO notifications (created_at, title, body, state, intervention_id, kind, action_payload) \
         VALUES (?1, ?2, ?3, 'unread', NULL, ?4, ?5)",
        params![
            chrono::Utc::now().naive_utc().to_string(),
            title,
            body,
            kind,
            action_payload,
        ],
    )
    .map_err(|err| err.to_string())?;
    Ok(conn.last_insert_rowid())
}

fn mark_break_notifications_read(conn: &Connection) -> Result<(), String> {
    if !table_exists(conn, "notifications").unwrap_or(false) {
        return Ok(());
    }
    conn.execute(
        "UPDATE notifications SET state = 'read' \
         WHERE state = 'unread' AND kind = 'ml_break_recommendation'",
        [],
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn mark_latest_ml_notifications_seen(conn: &Connection) -> Result<(), String> {
    let latest = conn
        .query_row(
            "SELECT MAX(id) FROM notifications WHERE kind LIKE 'ml_%'",
            [],
            |row| row.get::<_, Option<i64>>(0),
        )
        .unwrap_or(None);
    if let Some(id) = latest {
        set_runtime_value(conn, "last_native_notification_id", &id.to_string())?;
    }
    Ok(())
}

fn show_app_notification(app: &AppHandle, title: &str, body: &str) {
    let _ = app.notification().builder().title(title).body(body).show();
}

fn notifications_quiet_now(settings: &RuntimeSettingsPayload) -> bool {
    let Some(start) = parse_hhmm_minutes(&settings.notifications.do_not_disturb_start) else {
        return false;
    };
    let Some(end) = parse_hhmm_minutes(&settings.notifications.do_not_disturb_end) else {
        return false;
    };
    if start == end {
        return false;
    }
    let now = Local::now();
    let minute = now.hour() * 60 + now.minute();
    if start < end {
        minute >= start && minute < end
    } else {
        minute >= start || minute < end
    }
}

fn parse_hhmm_minutes(value: &str) -> Option<u32> {
    let (hour, minute) = value.trim().split_once(':')?;
    let hour = hour.parse::<u32>().ok()?;
    let minute = minute.parse::<u32>().ok()?;
    if hour > 23 || minute > 59 {
        return None;
    }
    Some(hour * 60 + minute)
}

fn break_ignore_active(conn: &Connection) -> bool {
    let Some(value) = runtime_value(conn, "break_ignore_until") else {
        return false;
    };
    let Ok(until) = parse_sqlite_time_utc(&value) else {
        return false;
    };
    chrono::Utc::now().naive_utc() < until
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

fn latest_prediction_id(conn: &Connection) -> Option<i64> {
    latest_prediction_snapshot(conn).map(|item| item.id)
}

fn latest_prediction_snapshot(conn: &Connection) -> Option<PredictionSnapshot> {
    if !table_exists(conn, "ml_predictions").unwrap_or(false) {
        return None;
    }
    conn.query_row(
        "SELECT id, model_version, policy_source, effectiveness, decline_15m, decline_30m, \
         decline_60m, break_benefit \
         FROM ml_predictions ORDER BY id DESC LIMIT 1",
        [],
        prediction_snapshot_from_row,
    )
    .ok()
}

fn prediction_snapshot_by_id(conn: &Connection, id: Option<i64>) -> Option<PredictionSnapshot> {
    let id = id?;
    if !table_exists(conn, "ml_predictions").unwrap_or(false) {
        return None;
    }
    conn.query_row(
        "SELECT id, model_version, policy_source, effectiveness, decline_15m, decline_30m, \
         decline_60m, break_benefit \
         FROM ml_predictions WHERE id = ?1",
        params![id],
        prediction_snapshot_from_row,
    )
    .ok()
}

fn prediction_snapshot_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<PredictionSnapshot> {
    Ok(PredictionSnapshot {
        id: row.get(0)?,
        model_version: row.get(1)?,
        policy_source: row.get(2)?,
        effectiveness: row.get::<_, Option<f64>>(3)?.unwrap_or(0.0),
        decline_15: row.get::<_, Option<f64>>(4)?.unwrap_or(0.0),
        decline_30: row.get::<_, Option<f64>>(5)?.unwrap_or(0.0),
        decline_60: row.get::<_, Option<f64>>(6)?.unwrap_or(0.0),
        break_benefit: row.get::<_, Option<f64>>(7)?.unwrap_or(0.0),
    })
}

fn latest_break_recommendation_id(conn: &Connection) -> Option<i64> {
    conn.query_row(
        "SELECT id FROM recommendations WHERE recommended_action LIKE 'BREAK_%' ORDER BY id DESC LIMIT 1",
        [],
        |row| row.get(0),
    )
    .ok()
}

fn latest_actionable_break_recommendation_id(conn: &Connection) -> Option<i64> {
    conn.query_row(
        "SELECT id FROM recommendations \
         WHERE recommended_action LIKE 'BREAK_%' AND completed_at IS NULL \
         AND COALESCE(accepted, 0) = 0 AND COALESCE(ignored, 0) = 0 \
         ORDER BY id DESC LIMIT 1",
        [],
        |row| row.get(0),
    )
    .ok()
}

fn latest_started_recommendation_id(conn: &Connection) -> Option<i64> {
    conn.query_row(
        "SELECT id FROM recommendations WHERE started_at IS NOT NULL AND completed_at IS NULL ORDER BY id DESC LIMIT 1",
        [],
        |row| row.get(0),
    )
    .ok()
}

fn current_task_label() -> Option<String> {
    let task = load_runtime_settings().preferences.current_task_label;
    if task.trim().is_empty() || task.eq_ignore_ascii_case("none") {
        None
    } else {
        Some(task)
    }
}

fn task_category_for(task: Option<&str>) -> Option<String> {
    let value = task?.trim().to_lowercase();
    if value.is_empty() || value == "none" {
        return None;
    }
    let category = match value.as_str() {
        "homework" | "school" => "study",
        "physics" | "chemistry" | "biology" => "science",
        "language" => "english",
        "planning" => "admin",
        "work" | "study" | "coding" | "ml" | "math" | "english" | "reading" | "writing"
        | "research" | "creative" | "communication" | "admin" | "gaming" | "rest" | "other" => {
            value.as_str()
        }
        _ => "other",
    };
    Some(category.to_string())
}

fn persist_recommendation_outcome(
    conn: &Connection,
    recommendation_id: i64,
    accepted: bool,
    ignored: bool,
) -> Result<(), String> {
    let now = chrono::Utc::now().naive_utc().to_string();
    let mut stmt = conn
        .prepare(
            "SELECT recommended_action, recommended_duration, actual_duration, prediction_before_id, prediction_after_id, task_before, task_after \
             FROM recommendations WHERE id = ?1",
        )
        .map_err(|err| err.to_string())?;
    let row = stmt
        .query_row(params![recommendation_id], |row| {
            Ok((
                row.get::<_, Option<String>>(0)?,
                row.get::<_, Option<i64>>(1)?,
                row.get::<_, Option<f64>>(2)?,
                row.get::<_, Option<i64>>(3)?,
                row.get::<_, Option<i64>>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<String>>(6)?,
            ))
        })
        .map_err(|err| err.to_string())?;
    let before = prediction_snapshot(conn, row.3);
    let after = prediction_snapshot(conn, row.4.or_else(|| latest_prediction_id(conn)));
    let break_quality = recommendation_break_quality(conn, recommendation_id);
    conn.execute(
        "INSERT INTO recommendation_outcomes (recommendation_id, created_at, action, accepted, ignored, planned_duration, actual_duration, \
         prediction_before_id, prediction_after_id, effectiveness_before, effectiveness_after, decline_30m_before, decline_30m_after, task_before, task_after) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
        params![
            recommendation_id,
            now,
            row.0,
            if accepted { 1 } else { 0 },
            if ignored { 1 } else { 0 },
            row.1,
            row.2,
            row.3,
            row.4.or_else(|| latest_prediction_id(conn)),
            before.map(|item| item.0),
            after.map(|item| item.0),
            before.map(|item| item.1),
            after.map(|item| item.1),
            row.5,
            row.6.or_else(current_task_label),
        ],
    )
    .map_err(|err| err.to_string())?;
    conn.execute(
        "UPDATE recommendation_outcomes SET active_minutes_during_break = ?1, idle_minutes_during_break = ?2, \
         rest_task_minutes_during_break = ?3, restful_break_score = ?4 WHERE id = last_insert_rowid()",
        params![
            break_quality.0,
            break_quality.1,
            break_quality.2,
            break_quality.3,
        ],
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn recommendation_break_quality(conn: &Connection, recommendation_id: i64) -> (f64, f64, f64, f64) {
    if !table_exists(conn, "activity_events").unwrap_or(false) {
        return (0.0, 0.0, 0.0, 0.0);
    }
    let row = conn
        .query_row(
            "SELECT started_at, completed_at, COALESCE(actual_duration, recommended_duration, 0) FROM recommendations WHERE id = ?1",
            params![recommendation_id],
            |row| {
                Ok((
                    row.get::<_, Option<String>>(0)?,
                    row.get::<_, Option<String>>(1)?,
                    row.get::<_, Option<f64>>(2)?,
                ))
            },
        )
        .ok();
    let Some((Some(started_at), Some(completed_at), planned_duration)) = row else {
        return (0.0, 0.0, 0.0, 0.0);
    };
    let idle_threshold_seconds =
        (load_runtime_settings().tracking.idle_threshold_minutes * 60) as f64;
    let result = conn.query_row(
        "SELECT \
         COALESCE(SUM(CASE WHEN COALESCE(idle_seconds, 0) < ?3 THEN MAX((julianday(ts_end) - julianday(ts_start)) * 1440.0, 0) ELSE 0 END), 0), \
         COALESCE(SUM(CASE WHEN COALESCE(idle_seconds, 0) >= ?3 THEN MAX((julianday(ts_end) - julianday(ts_start)) * 1440.0, 0) ELSE 0 END), 0), \
         COALESCE(SUM(CASE WHEN lower(COALESCE(task_label, '')) IN ('rest', 'отдых') THEN MAX((julianday(ts_end) - julianday(ts_start)) * 1440.0, 0) ELSE 0 END), 0) \
         FROM activity_events WHERE ts_start < ?2 AND ts_end > ?1",
        params![started_at, completed_at, idle_threshold_seconds],
        |row| Ok((row.get::<_, f64>(0)?, row.get::<_, f64>(1)?, row.get::<_, f64>(2)?)),
    );
    let Ok((active, idle, rest_task)) = result else {
        return (0.0, 0.0, 0.0, 0.0);
    };
    let denom = planned_duration.unwrap_or(0.0).max(active + idle).max(1.0);
    let score = ((idle + rest_task * 0.75 - active * 0.25) / denom).clamp(0.0, 1.0);
    (active, idle, rest_task, score)
}

#[derive(Debug)]
struct PendingAction {
    recommendation_id: i64,
    action: String,
    action_at: chrono::NaiveDateTime,
}

fn capture_pending_action_outcomes() -> Result<usize, String> {
    let db_path = attentionos_db_path()?;
    if !db_path.exists() {
        return Ok(0);
    }
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    capture_pending_action_outcomes_in_conn(&conn, chrono::Utc::now().naive_utc())
}

fn capture_pending_action_outcomes_in_conn(
    conn: &Connection,
    now: chrono::NaiveDateTime,
) -> Result<usize, String> {
    let actions = pending_actions(conn)?;
    let mut inserted = 0usize;
    for action in actions {
        for horizon in OUTCOME_HORIZONS_MINUTES {
            let due_at = action.action_at + chrono::Duration::minutes(horizon);
            if now < due_at || action_outcome_exists(conn, action.recommendation_id, horizon)? {
                continue;
            }
            let prediction = latest_prediction_snapshot_at_or_before(conn, due_at)
                .or_else(|| latest_prediction_snapshot(conn));
            let metrics = activity_window_metrics(conn, action.action_at, due_at)?;
            conn.execute(
                "INSERT OR IGNORE INTO action_outcomes (recommendation_id, action, captured_at, \
                 prediction_after_id, effectiveness_after, decline_15_after, decline_30_after, decline_60_after, \
                 active_ratio_after, switch_rate_after, input_rate_after, idle_ratio_after, task_after, minutes_since_action) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
                params![
                    action.recommendation_id,
                    action.action,
                    now.to_string(),
                    prediction.as_ref().map(|item| item.id),
                    prediction.as_ref().map(|item| item.effectiveness),
                    prediction.as_ref().map(|item| item.decline_15),
                    prediction.as_ref().map(|item| item.decline_30),
                    prediction.as_ref().map(|item| item.decline_60),
                    metrics.active_ratio,
                    metrics.switch_rate,
                    metrics.input_rate,
                    metrics.idle_ratio,
                    metrics.task_after,
                    horizon,
                ],
            )
            .map_err(|err| err.to_string())?;
            if conn.changes() > 0 {
                inserted += 1;
            }
        }
    }
    Ok(inserted)
}

fn pending_outcome_capture_count(conn: &Connection) -> Result<i64, String> {
    if !table_exists(conn, "action_outcomes")? || !table_exists(conn, "recommendations")? {
        return Ok(0);
    }
    let now = chrono::Utc::now().naive_utc();
    let mut count = 0;
    for action in pending_actions(conn)? {
        for horizon in OUTCOME_HORIZONS_MINUTES {
            let due_at = action.action_at + chrono::Duration::minutes(horizon);
            if now >= due_at && !action_outcome_exists(conn, action.recommendation_id, horizon)? {
                count += 1;
            }
        }
    }
    Ok(count)
}

fn pending_actions(conn: &Connection) -> Result<Vec<PendingAction>, String> {
    if !table_exists(conn, "recommendations")? {
        return Ok(Vec::new());
    }
    let mut stmt = conn
        .prepare(
            "SELECT id, recommended_action, COALESCE(recommended_break_minutes, recommended_duration), \
             COALESCE(accepted, 0), COALESCE(ignored, 0), \
             COALESCE(break_started_at, started_at, ignored_at, timestamp) \
             FROM recommendations \
             WHERE COALESCE(accepted, 0) = 1 OR COALESCE(ignored, 0) = 1",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            let id = row.get::<_, i64>(0)?;
            let recommended_action = row
                .get::<_, Option<String>>(1)?
                .unwrap_or_else(|| "BREAK".to_string());
            let minutes = row.get::<_, Option<i64>>(2)?.unwrap_or(0);
            let accepted = row.get::<_, i64>(3)? == 1;
            let ignored = row.get::<_, i64>(4)? == 1;
            let raw_time = row.get::<_, String>(5)?;
            let action = if ignored {
                format!("IGNORE_{recommended_action}")
            } else if accepted {
                recommended_action
            } else if minutes > 0 {
                format!("BREAK_{minutes}")
            } else {
                "ACTION".to_string()
            };
            Ok((id, action, raw_time))
        })
        .map_err(|err| err.to_string())?;
    let mut actions = Vec::new();
    for row in rows {
        let (recommendation_id, action, raw_time) = row.map_err(|err| err.to_string())?;
        if let Ok(action_at) = parse_sqlite_time_utc(&raw_time) {
            actions.push(PendingAction {
                recommendation_id,
                action,
                action_at,
            });
        }
    }
    Ok(actions)
}

fn action_outcome_exists(
    conn: &Connection,
    recommendation_id: i64,
    horizon: i64,
) -> Result<bool, String> {
    if !table_exists(conn, "action_outcomes")? {
        return Ok(false);
    }
    let exists = conn
        .query_row(
            "SELECT 1 FROM action_outcomes WHERE recommendation_id = ?1 AND minutes_since_action = ?2 LIMIT 1",
            params![recommendation_id, horizon],
            |_| Ok(()),
        )
        .is_ok();
    Ok(exists)
}

fn latest_prediction_snapshot_at_or_before(
    conn: &Connection,
    at: chrono::NaiveDateTime,
) -> Option<PredictionSnapshot> {
    if !table_exists(conn, "ml_predictions").unwrap_or(false) {
        return None;
    }
    conn.query_row(
        "SELECT id, model_version, policy_source, effectiveness, decline_15m, decline_30m, \
         decline_60m, break_benefit \
         FROM ml_predictions WHERE timestamp <= ?1 ORDER BY timestamp DESC LIMIT 1",
        params![at.to_string()],
        prediction_snapshot_from_row,
    )
    .ok()
}

fn activity_window_metrics(
    conn: &Connection,
    start: chrono::NaiveDateTime,
    end: chrono::NaiveDateTime,
) -> Result<OutcomeWindowMetrics, String> {
    let settings = load_runtime_settings();
    let idle_threshold_seconds = (settings.tracking.idle_threshold_minutes * 60) as f64;
    let events = load_events_for_window(conn, start, end)?
        .into_iter()
        .filter(|event| {
            !is_excluded_app(
                &event.process_name,
                &settings.tracking.excluded_applications,
            )
        })
        .collect::<Vec<_>>();
    let window_minutes = end.signed_duration_since(start).num_seconds().max(60) as f64 / 60.0;
    if events.is_empty() {
        return Ok(OutcomeWindowMetrics {
            active_ratio: 0.0,
            switch_rate: 0.0,
            input_rate: 0.0,
            idle_ratio: 1.0,
            task_after: current_task_label(),
        });
    }
    let mut total_seconds = 0i64;
    let mut active_seconds = 0i64;
    let mut input_events = 0i64;
    for event in &events {
        let seconds = event_overlap_seconds(event, start, end);
        if seconds <= 0 {
            continue;
        }
        total_seconds += seconds;
        if is_active_event(event, idle_threshold_seconds) {
            active_seconds += seconds;
        }
        input_events += event.keyboard_events + event.mouse_events;
    }
    let total_seconds = total_seconds.max(1);
    let switches = count_switches(&events) as f64;
    Ok(OutcomeWindowMetrics {
        active_ratio: (active_seconds as f64 / total_seconds as f64).clamp(0.0, 1.0),
        switch_rate: switches / window_minutes,
        input_rate: input_events as f64 / window_minutes,
        idle_ratio: ((total_seconds - active_seconds) as f64 / total_seconds as f64)
            .clamp(0.0, 1.0),
        task_after: events
            .iter()
            .rev()
            .find_map(|event| event.task_label.clone())
            .or_else(current_task_label),
    })
}

fn load_events_for_window(
    conn: &Connection,
    start: chrono::NaiveDateTime,
    end: chrono::NaiveDateTime,
) -> Result<Vec<EventRow>, String> {
    if !table_exists(conn, "activity_events")? {
        return Ok(Vec::new());
    }
    let mut stmt = conn
        .prepare(
            "SELECT ts_start, ts_end, process_name, idle_seconds, keyboard_events, mouse_events, task_label \
             FROM activity_events WHERE ts_start < ?2 AND ts_end > ?1 ORDER BY ts_start ASC",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map(params![start.to_string(), end.to_string()], |row| {
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

fn event_overlap_seconds(
    event: &EventRow,
    start: chrono::NaiveDateTime,
    end: chrono::NaiveDateTime,
) -> i64 {
    let Ok(event_start) = parse_sqlite_time_utc(&event.ts_start) else {
        return 0;
    };
    let Ok(event_end) = parse_sqlite_time_utc(&event.ts_end) else {
        return 0;
    };
    let overlap_start = event_start.max(start);
    let overlap_end = event_end.min(end);
    overlap_end
        .signed_duration_since(overlap_start)
        .num_seconds()
        .clamp(0, MAX_EVENT_DURATION_SECONDS)
}

fn self_report_next_eligible_at(conn: &Connection) -> Option<String> {
    let last_report = if table_exists(conn, "self_reports").unwrap_or(false) {
        conn.query_row("SELECT MAX(timestamp) FROM self_reports", [], |row| {
            row.get::<_, Option<String>>(0)
        })
        .unwrap_or(None)
    } else {
        None
    };
    let last_prompt = runtime_value(conn, "last_self_report_prompt_at");
    let latest = [last_report, last_prompt]
        .into_iter()
        .flatten()
        .filter_map(|value| parse_sqlite_time_utc(&value).ok())
        .max();
    latest
        .map(|time| time + chrono::Duration::minutes(MIN_REPORT_INTERVAL_MINUTES))
        .map(|time| time.to_string())
}

fn maybe_prompt_self_report(app: &AppHandle) -> Result<(), String> {
    let db_path = attentionos_db_path()?;
    if !db_path.exists() {
        return Ok(());
    }
    let conn = Connection::open(db_path).map_err(|err| err.to_string())?;
    ensure_runtime_state(&conn)?;
    let now = chrono::Utc::now().naive_utc();
    if let Some(next) =
        self_report_next_eligible_at(&conn).and_then(|value| parse_sqlite_time_utc(&value).ok())
    {
        if now < next {
            return Ok(());
        }
    }
    let Some(trigger_at) = latest_self_report_trigger_time(&conn) else {
        return Ok(());
    };
    if now < trigger_at + chrono::Duration::minutes(POST_BREAK_REPORT_DELAY_MINUTES) {
        return Ok(());
    }
    let last_prompt = runtime_value(&conn, "last_self_report_prompt_at")
        .and_then(|value| parse_sqlite_time_utc(&value).ok());
    if last_prompt
        .map(|value| value >= trigger_at)
        .unwrap_or(false)
    {
        return Ok(());
    }
    let local_time = Local::now().format("%H:%M").to_string();
    let body = format!("{local_time} - Как прошла последняя сессия?");
    let notification_id = insert_app_notification(
        &conn,
        "AttentionOS",
        &body,
        "self_report_prompt",
        "{\"source\":\"self-report-scheduler\"}",
    )?;
    set_runtime_value(&conn, "last_self_report_prompt_at", &now.to_string())?;
    let settings = load_runtime_settings();
    if settings.notifications.break_recommendations && !notifications_quiet_now(&settings) {
        show_app_notification(app, "AttentionOS", &body);
        set_runtime_value(
            &conn,
            "last_native_notification_id",
            &notification_id.to_string(),
        )?;
    }
    Ok(())
}

fn latest_self_report_trigger_time(conn: &Connection) -> Option<chrono::NaiveDateTime> {
    if !table_exists(conn, "recommendations").unwrap_or(false) {
        return None;
    }
    conn.query_row(
        "SELECT MAX(COALESCE(break_finished_at, completed_at, ignored_at)) \
         FROM recommendations WHERE completed_at IS NOT NULL OR ignored_at IS NOT NULL",
        [],
        |row| row.get::<_, Option<String>>(0),
    )
    .unwrap_or(None)
    .and_then(|value| parse_sqlite_time_utc(&value).ok())
}

fn prediction_snapshot(conn: &Connection, id: Option<i64>) -> Option<(f64, f64)> {
    prediction_snapshot_by_id(conn, id).map(|item| (item.effectiveness, item.decline_30))
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
        "ml_predictions": table_as_json(&conn, "ml_predictions")?,
        "recommendations": table_as_json(&conn, "recommendations")?,
        "recommendation_outcomes": table_as_json(&conn, "recommendation_outcomes")?,
        "action_outcomes": table_as_json(&conn, "action_outcomes")?,
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
    execute_delete(&[
        "interventions",
        "notifications",
        "ml_predictions",
        "recommendations",
        "recommendation_outcomes",
        "action_outcomes",
    ])
}

#[tauri::command]
fn delete_all_data() -> Result<(), String> {
    execute_delete(&[
        "activity_events",
        "self_reports",
        "interventions",
        "notifications",
        "ml_predictions",
        "recommendations",
        "recommendation_outcomes",
        "action_outcomes",
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
        if probe
            .output()
            .map(|output| output.status.success())
            .unwrap_or(false)
        {
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

fn build_dashboard(
    date: String,
    db_path: PathBuf,
    events: Vec<EventRow>,
    idle_threshold_seconds: f64,
) -> DashboardPayload {
    let (state_history, daily_summary_from_db, break_segments) = Connection::open(&db_path)
        .ok()
        .map(|conn| {
            let _ = ensure_runtime_state(&conn);
            (
                state_history(&conn, &date).unwrap_or_default(),
                daily_summary_from_db(&conn, &date),
                break_timeline_segments(&conn, &date).unwrap_or_default(),
            )
        })
        .unwrap_or_default();
    let timed_events = timed_events(&events);
    let event_count = events.len() as i64;
    let active_seconds = timed_events
        .iter()
        .filter(|item| is_active_event(item.event, idle_threshold_seconds))
        .map(|item| item.duration_seconds)
        .sum::<i64>();
    let focused_seconds = focused_activity_seconds(&timed_events, idle_threshold_seconds);
    let context_switches = count_switches(&events);
    let top_apps = top_apps(&timed_events, active_seconds, idle_threshold_seconds);
    let mut timeline = timeline_segments(&timed_events, idle_threshold_seconds);
    timeline.extend(break_segments);
    timeline.sort_by(|a, b| {
        a.start_minute
            .cmp(&b.start_minute)
            .then_with(|| a.end_minute.cmp(&b.end_minute))
    });
    let recent_sessions = recent_sessions(&timed_events, idle_threshold_seconds);

    let focused_minutes = active_seconds_to_minutes(focused_seconds);
    let active_minutes = active_seconds_to_minutes(active_seconds);
    let daily_summary = DailySummaryPayload {
        work_minutes: active_minutes,
        effective_minutes_estimate: daily_summary_from_db
            .average_effectiveness
            .map(|value| ((active_minutes as f64) * (value / 100.0).clamp(0.0, 1.0)).round() as i64)
            .unwrap_or(active_minutes),
        average_effectiveness: daily_summary_from_db.average_effectiveness,
        break_count: daily_summary_from_db.break_count,
        recommendation_count: daily_summary_from_db.recommendation_count,
        accepted_count: daily_summary_from_db.accepted_count,
        ignored_count: daily_summary_from_db.ignored_count,
        average_break_minutes: daily_summary_from_db.average_break_minutes,
        break_effectiveness_delta: daily_summary_from_db.break_effectiveness_delta,
        average_decline_risk: daily_summary_from_db.average_decline_risk,
        recovered_effective_minutes_estimate: daily_summary_from_db
            .recovered_effective_minutes_estimate,
        recovered_effective_minutes_available: daily_summary_from_db
            .recovered_effective_minutes_available,
        personalization_samples_today: daily_summary_from_db.personalization_samples_today,
        acceptance_rate: if daily_summary_from_db.recommendation_count > 0 {
            Some(
                daily_summary_from_db.accepted_count as f64
                    / daily_summary_from_db.recommendation_count as f64,
            )
        } else {
            None
        },
        completion_rate: if daily_summary_from_db.accepted_count > 0 {
            Some(
                daily_summary_from_db.break_count as f64
                    / daily_summary_from_db.accepted_count as f64,
            )
        } else {
            None
        },
        best_period: best_work_block(&recent_sessions),
    };
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
                detail: "Active time inside productive selected task categories".to_string(),
            },
            Metric {
                label: "Active time".to_string(),
                value: format_minutes(active_minutes),
                detail: "All non-idle keyboard, mouse, and foreground activity".to_string(),
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
        daily_summary,
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
            let duration_seconds = raw_seconds.clamp(1, MAX_EVENT_DURATION_SECONDS);
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

fn is_active_event(event: &EventRow, idle_threshold_seconds: f64) -> bool {
    event.keyboard_events > 0
        || event.mouse_events > 0
        || event.idle_seconds < idle_threshold_seconds
}

fn is_focus_event(event: &EventRow, idle_threshold_seconds: f64) -> bool {
    is_active_event(event, idle_threshold_seconds)
        && is_productive_task(event.task_label.as_deref())
}

fn focused_activity_seconds(events: &[TimedEvent<'_>], idle_threshold_seconds: f64) -> i64 {
    let mut total = 0;
    let mut block_seconds = 0;
    let mut block_app = String::new();
    let mut block_task: Option<String> = None;
    let mut block_end_minute = 0;

    for item in events
        .iter()
        .filter(|item| is_focus_event(item.event, idle_threshold_seconds))
    {
        let app = clean_app_name(&item.event.process_name);
        let same_block = block_seconds > 0
            && block_app == app
            && block_task == item.event.task_label
            && item.start_minute <= block_end_minute + 1;
        if !same_block {
            if block_seconds >= MIN_FOCUS_BLOCK_SECONDS {
                total += block_seconds;
            }
            block_seconds = 0;
            block_app = app;
            block_task = item.event.task_label.clone();
        }
        block_seconds += item.duration_seconds;
        block_end_minute = item.end_minute;
    }
    if block_seconds >= MIN_FOCUS_BLOCK_SECONDS {
        total += block_seconds;
    }
    total
}

fn is_productive_task(task: Option<&str>) -> bool {
    let Some(task) = task else {
        return false;
    };
    let normalized = task.trim().to_lowercase();
    if normalized == "\u{0434}\u{0440}\u{0443}\u{0433}\u{043e}\u{0435}"
        || normalized == "\u{043e}\u{0442}\u{0434}\u{044b}\u{0445}"
        || normalized == "\u{0438}\u{0433}\u{0440}\u{0430}"
    {
        return false;
    }
    !normalized.is_empty()
        && !matches!(
            normalized.as_str(),
            "none" | "other" | "rest" | "gaming" | "game" | "другое" | "отдых" | "игра"
        )
}

fn is_rest_task(task: Option<&str>) -> bool {
    let Some(task) = task else {
        return false;
    };
    let normalized = task.trim().to_lowercase();
    if normalized == "rest"
        || normalized == "break"
        || normalized == "\u{043e}\u{0442}\u{0434}\u{044b}\u{0445}"
        || normalized == "\u{043f}\u{0435}\u{0440}\u{0435}\u{0440}\u{044b}\u{0432}"
    {
        return true;
    }
    matches!(
        task.trim().to_lowercase().as_str(),
        "rest" | "отдых" | "break" | "перерыв"
    )
}

fn count_switches(events: &[EventRow]) -> i64 {
    events
        .windows(2)
        .filter(|pair| pair[0].process_name != pair[1].process_name)
        .count() as i64
}

fn top_apps(
    events: &[TimedEvent<'_>],
    active_seconds: i64,
    idle_threshold_seconds: f64,
) -> Vec<AppUsage> {
    let mut totals = BTreeMap::<String, i64>::new();
    for item in events
        .iter()
        .filter(|item| is_active_event(item.event, idle_threshold_seconds))
    {
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

fn timeline_segments(
    events: &[TimedEvent<'_>],
    idle_threshold_seconds: f64,
) -> Vec<TimelineSegment> {
    let mut segments: Vec<TimelineSegment> = Vec::new();
    let mut last_end: Option<i64> = None;
    for item in events {
        let start = item.start_minute.clamp(0, 24 * 60);
        if start >= 24 * 60 {
            continue;
        }
        let end = item.end_minute.clamp(start + 1, 24 * 60);
        if let Some(previous_end) = last_end {
            if start - previous_end >= TIMELINE_GAP_IDLE_MINUTES {
                push_timeline_segment(
                    &mut segments,
                    TimelineSegment {
                        app: "Idle".to_string(),
                        task: None,
                        kind: "idle".to_string(),
                        state: "IDLE".to_string(),
                        start_minute: previous_end,
                        end_minute: start,
                        duration_minutes: (start - previous_end).max(1),
                    },
                );
            }
        } else if start >= TIMELINE_GAP_IDLE_MINUTES {
            push_timeline_segment(
                &mut segments,
                TimelineSegment {
                    app: "Idle".to_string(),
                    task: None,
                    kind: "idle".to_string(),
                    state: "IDLE".to_string(),
                    start_minute: 0,
                    end_minute: start,
                    duration_minutes: start.max(1),
                },
            );
        }
        let is_idle = !is_active_event(item.event, idle_threshold_seconds);
        let is_break = is_rest_task(item.event.task_label.as_deref());
        let app = if is_idle {
            "Idle".to_string()
        } else if is_break {
            "Break".to_string()
        } else {
            clean_app_name(&item.event.process_name)
        };
        let kind = if is_idle {
            "idle"
        } else if is_break {
            "break"
        } else {
            "app"
        }
        .to_string();
        push_timeline_segment(
            &mut segments,
            TimelineSegment {
                app,
                task: item.event.task_label.clone(),
                kind,
                state: if is_idle {
                    "IDLE".to_string()
                } else if is_break {
                    "BREAK".to_string()
                } else {
                    "WORK".to_string()
                },
                start_minute: start,
                end_minute: end,
                duration_minutes: (end - start).max(1),
            },
        );
        last_end = Some(last_end.map(|value| value.max(end)).unwrap_or(end));
    }
    segments
}

fn push_timeline_segment(segments: &mut Vec<TimelineSegment>, segment: TimelineSegment) {
    if segment.end_minute <= segment.start_minute {
        return;
    }
    if let Some(last) = segments.last_mut() {
        let contiguous = segment.start_minute <= last.end_minute + 1;
        if contiguous
            && last.app == segment.app
            && last.task == segment.task
            && last.kind == segment.kind
        {
            last.end_minute = last.end_minute.max(segment.end_minute);
            last.duration_minutes = (last.end_minute - last.start_minute).max(1);
            return;
        }
    }
    segments.push(segment);
}

fn recent_sessions(events: &[TimedEvent<'_>], idle_threshold_seconds: f64) -> Vec<RecentSession> {
    let mut blocks: Vec<RecentSession> = Vec::new();
    let mut current_start = 0;
    let mut current_end = 0;
    let mut current_task: Option<String> = None;
    let mut apps = BTreeMap::<String, bool>::new();
    for item in events
        .iter()
        .filter(|item| is_active_event(item.event, idle_threshold_seconds))
    {
        let task = item.event.task_label.clone();
        let gap = if current_end == 0 {
            0
        } else {
            item.start_minute - current_end
        };
        let should_split = current_end == 0 || current_task != task || gap > 10;
        if should_split && current_end > current_start {
            blocks.push(work_block(
                current_start,
                current_end,
                current_task.clone(),
                &apps,
            ));
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

fn break_timeline_segments(conn: &Connection, date: &str) -> Result<Vec<TimelineSegment>, String> {
    if !table_exists(conn, "recommendations")? {
        return Ok(Vec::new());
    }
    let mut stmt = conn
        .prepare(
            "SELECT COALESCE(break_started_at, started_at), COALESCE(break_finished_at, completed_at), \
             COALESCE(recommended_break_minutes, recommended_duration, 10) \
             FROM recommendations WHERE COALESCE(accepted, 0) = 1 AND COALESCE(break_started_at, started_at) IS NOT NULL",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, Option<String>>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, Option<i64>>(2)?.unwrap_or(10),
            ))
        })
        .map_err(|err| err.to_string())?;
    let mut segments = Vec::new();
    for row in rows {
        let (Some(start_raw), finished_raw, planned_minutes) =
            row.map_err(|err| err.to_string())?
        else {
            continue;
        };
        let start_local = parse_sqlite_time(&start_raw);
        let end_local = finished_raw
            .as_deref()
            .map(parse_sqlite_time)
            .unwrap_or_else(|| start_local + chrono::Duration::minutes(planned_minutes.max(1)));
        if start_local.date().to_string() != date && end_local.date().to_string() != date {
            continue;
        }
        let mut start_minute = i64::from(start_local.time().num_seconds_from_midnight() / 60);
        let mut end_minute = i64::from(end_local.time().num_seconds_from_midnight() / 60);
        if start_local.date().to_string() < date.to_string() {
            start_minute = 0;
        }
        if end_local.date().to_string() > date.to_string() || end_minute <= start_minute {
            end_minute = 24 * 60;
        }
        segments.push(TimelineSegment {
            app: "Break".to_string(),
            task: Some("rest".to_string()),
            kind: "break".to_string(),
            state: "BREAK".to_string(),
            start_minute: start_minute.clamp(0, 24 * 60),
            end_minute: end_minute.clamp(start_minute + 1, 24 * 60),
            duration_minutes: (end_minute - start_minute).max(1),
        });
    }
    Ok(segments)
}

fn state_history(conn: &Connection, date: &str) -> Result<Vec<StatePoint>, String> {
    if !table_exists(conn, "ml_predictions")? {
        return recommendation_state_markers(conn, date);
    }
    let mut stmt = conn
        .prepare(
            "SELECT timestamp, effectiveness, decline_30m, recommended_action, break_benefit \
             FROM ml_predictions \
             WHERE substr(datetime(timestamp, 'localtime'), 1, 10) = ?1 \
             ORDER BY timestamp ASC",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map(params![date], |row| {
            let timestamp: String = row.get(0)?;
            let action: Option<String> = row.get(3)?;
            let action_value = action.unwrap_or_default();
            Ok(StatePoint {
                minute: minute_of_day(&timestamp),
                effectiveness: row.get::<_, Option<f64>>(1)?.unwrap_or(0.0),
                decline_risk: row.get::<_, Option<f64>>(2)?.unwrap_or(0.0),
                state: if action_value.starts_with("BREAK") {
                    "BREAK_RECOMMENDED".to_string()
                } else {
                    "WORK".to_string()
                },
                marker: if action_value.starts_with("BREAK") {
                    Some("break_recommended".to_string())
                } else {
                    None
                },
                break_benefit: row.get::<_, Option<f64>>(4)?,
            })
        })
        .map_err(|err| err.to_string())?;
    let mut points = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| err.to_string())?;
    points.extend(recommendation_state_markers(conn, date)?);
    points.sort_by(|a, b| {
        a.minute
            .cmp(&b.minute)
            .then_with(|| a.marker.cmp(&b.marker))
    });
    Ok(points)
}

fn recommendation_state_markers(conn: &Connection, date: &str) -> Result<Vec<StatePoint>, String> {
    if !table_exists(conn, "recommendations")? {
        return Ok(Vec::new());
    }
    let mut stmt = conn
        .prepare(
            "SELECT timestamp, started_at, completed_at, ignored_at, effectiveness_before, decline_30, break_benefit \
             FROM recommendations ORDER BY timestamp ASC",
        )
        .map_err(|err| err.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, Option<String>>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, Option<f64>>(4)?.unwrap_or(0.0),
                row.get::<_, Option<f64>>(5)?.unwrap_or(0.0),
                row.get::<_, Option<f64>>(6)?,
            ))
        })
        .map_err(|err| err.to_string())?;
    let mut points = Vec::new();
    for row in rows {
        let (created, started, completed, ignored, effectiveness, risk, benefit) =
            row.map_err(|err| err.to_string())?;
        push_state_marker(
            &mut points,
            created,
            date,
            effectiveness,
            risk,
            "BREAK_RECOMMENDED",
            "break_recommended",
            benefit,
        );
        push_state_marker(
            &mut points,
            started,
            date,
            effectiveness,
            risk,
            "BREAK",
            "break_started",
            benefit,
        );
        push_state_marker(
            &mut points,
            completed,
            date,
            effectiveness,
            risk,
            "READY_TO_WORK",
            "break_finished",
            benefit,
        );
        push_state_marker(
            &mut points,
            ignored,
            date,
            effectiveness,
            risk,
            "WORK",
            "recommendation_ignored",
            benefit,
        );
    }
    Ok(points)
}

fn push_state_marker(
    points: &mut Vec<StatePoint>,
    timestamp: Option<String>,
    date: &str,
    effectiveness: f64,
    risk: f64,
    state: &str,
    marker: &str,
    benefit: Option<f64>,
) {
    let Some(timestamp) = timestamp else {
        return;
    };
    let local = parse_sqlite_time(&timestamp);
    if local.date().to_string() != date {
        return;
    }
    points.push(StatePoint {
        minute: i64::from(local.time().num_seconds_from_midnight() / 60),
        effectiveness,
        decline_risk: risk,
        state: state.to_string(),
        marker: Some(marker.to_string()),
        break_benefit: benefit,
    });
}

#[derive(Default)]
struct DailySummaryDb {
    average_effectiveness: Option<f64>,
    break_count: i64,
    recommendation_count: i64,
    accepted_count: i64,
    ignored_count: i64,
    average_break_minutes: Option<f64>,
    break_effectiveness_delta: Option<f64>,
    average_decline_risk: f64,
    recovered_effective_minutes_estimate: i64,
    recovered_effective_minutes_available: bool,
    personalization_samples_today: i64,
}

fn daily_summary_from_db(conn: &Connection, date: &str) -> DailySummaryDb {
    let mut summary = DailySummaryDb::default();
    if table_exists(conn, "ml_predictions").unwrap_or(false) {
        let row = conn
            .query_row(
                "SELECT AVG(effectiveness), AVG(decline_30m) FROM ml_predictions \
                 WHERE substr(datetime(timestamp, 'localtime'), 1, 10) = ?1",
                params![date],
                |row| Ok((row.get::<_, Option<f64>>(0)?, row.get::<_, Option<f64>>(1)?)),
            )
            .ok();
        if let Some((effectiveness, risk)) = row {
            summary.average_decline_risk = risk.unwrap_or(0.0);
            summary.average_effectiveness = effectiveness;
        }
    }
    if table_exists(conn, "recommendations").unwrap_or(false) {
        summary.recommendation_count = scalar_count(
            conn,
            &format!(
                "SELECT COUNT(*) FROM recommendations WHERE substr(datetime(timestamp, 'localtime'), 1, 10) = '{}'",
                date.replace('\'', "''")
            ),
        );
        summary.accepted_count = scalar_count(
            conn,
            &format!(
                "SELECT COUNT(*) FROM recommendations WHERE accepted = 1 AND substr(datetime(timestamp, 'localtime'), 1, 10) = '{}'",
                date.replace('\'', "''")
            ),
        );
        summary.ignored_count = scalar_count(
            conn,
            &format!(
                "SELECT COUNT(*) FROM recommendations WHERE COALESCE(ignored, 0) = 1 AND substr(datetime(timestamp, 'localtime'), 1, 10) = '{}'",
                date.replace('\'', "''")
            ),
        );
        summary.break_count = scalar_count(
            conn,
            &format!(
                "SELECT COUNT(*) FROM recommendations WHERE completed_at IS NOT NULL AND substr(datetime(timestamp, 'localtime'), 1, 10) = '{}'",
                date.replace('\'', "''")
            ),
        );
        summary.average_break_minutes = conn
            .query_row(
                "SELECT AVG(COALESCE(actual_break_seconds / 60.0, actual_duration, recommended_break_minutes, recommended_duration)) \
                 FROM recommendations WHERE completed_at IS NOT NULL AND substr(datetime(timestamp, 'localtime'), 1, 10) = ?1",
                params![date],
                |row| row.get::<_, Option<f64>>(0),
            )
            .unwrap_or(None);
    }
    if table_exists(conn, "action_outcomes").unwrap_or(false) {
        summary.personalization_samples_today = scalar_count(
            conn,
            &format!(
                "SELECT COUNT(*) FROM action_outcomes WHERE substr(datetime(captured_at, 'localtime'), 1, 10) = '{}'",
                date.replace('\'', "''")
            ),
        );
        summary.break_effectiveness_delta = conn
            .query_row(
                "SELECT AVG(o.effectiveness_after - r.effectiveness_before) \
                 FROM action_outcomes o \
                 JOIN recommendations r ON r.id = o.recommendation_id \
                 WHERE o.minutes_since_action = 30 AND r.accepted = 1 \
                 AND o.effectiveness_after IS NOT NULL AND r.effectiveness_before IS NOT NULL \
                 AND substr(datetime(o.captured_at, 'localtime'), 1, 10) = ?1",
                params![date],
                |row| row.get::<_, Option<f64>>(0),
            )
            .unwrap_or(None);
        let recovered = conn
            .query_row(
                "SELECT SUM(MAX(o.effectiveness_after - r.effectiveness_before, 0) * 30.0 / 100.0) \
                 FROM action_outcomes o \
                 JOIN recommendations r ON r.id = o.recommendation_id \
                 WHERE o.minutes_since_action = 30 AND r.accepted = 1 \
                 AND o.effectiveness_after IS NOT NULL AND r.effectiveness_before IS NOT NULL \
                 AND substr(datetime(o.captured_at, 'localtime'), 1, 10) = ?1",
                params![date],
                |row| row.get::<_, Option<f64>>(0),
            )
            .unwrap_or(None);
        if let Some(value) = recovered {
            summary.recovered_effective_minutes_estimate = value.round() as i64;
            summary.recovered_effective_minutes_available = true;
        }
    }
    if !summary.recovered_effective_minutes_available
        && table_exists(conn, "recommendation_outcomes").unwrap_or(false)
    {
        let recovered = conn
            .query_row(
                "SELECT SUM( \
                    MAX( \
                        COALESCE(o.effectiveness_after, COALESCE(o.effectiveness_before, 0) + COALESCE(p.break_benefit, 0) * 3.0) \
                        - COALESCE(o.effectiveness_before, 0), \
                        0 \
                    ) * COALESCE(o.actual_duration, o.planned_duration, 10) / 100.0 \
                    * (0.55 + COALESCE(o.restful_break_score, 0.5) * 0.45) \
                 ) \
                 FROM recommendation_outcomes o \
                 LEFT JOIN ml_predictions p ON p.id = o.prediction_before_id \
                 WHERE o.accepted = 1 AND substr(datetime(o.created_at, 'localtime'), 1, 10) = ?1",
                params![date],
                |row| row.get::<_, Option<f64>>(0),
            )
            .unwrap_or(None);
        if let Some(value) = recovered {
            summary.recovered_effective_minutes_estimate = value.round() as i64;
            summary.recovered_effective_minutes_available = true;
        }
    }
    summary
}

fn best_work_block(sessions: &[RecentSession]) -> Option<String> {
    sessions
        .iter()
        .max_by_key(|session| session.duration_minutes)
        .map(|session| {
            format!(
                "{} | {}",
                session.time,
                session.task.clone().unwrap_or_else(|| "None".to_string())
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(process_name: &str, task_label: Option<&str>) -> EventRow {
        EventRow {
            ts_start: "2026-08-23 00:00:00".to_string(),
            ts_end: "2026-08-23 00:00:15".to_string(),
            process_name: process_name.to_string(),
            idle_seconds: 0.0,
            keyboard_events: 1,
            mouse_events: 0,
            task_label: task_label.map(str::to_string),
        }
    }

    #[test]
    fn timeline_inserts_idle_gap_and_does_not_merge_across_pc_off_time() {
        let rows = vec![event("Code.exe", Some("ml")), event("Code.exe", Some("ml"))];
        let items = vec![
            TimedEvent {
                event: &rows[0],
                duration_seconds: 15,
                start_minute: 16 * 60 + 50,
                end_minute: 16 * 60 + 51,
            },
            TimedEvent {
                event: &rows[1],
                duration_seconds: 15,
                start_minute: 21 * 60 + 30,
                end_minute: 21 * 60 + 31,
            },
        ];

        let segments = timeline_segments(&items, 300.0);
        let active_code_segments = segments
            .iter()
            .filter(|segment| segment.kind == "app" && segment.app == "Code")
            .count();
        let gap = segments.iter().find(|segment| {
            segment.kind == "idle"
                && segment.start_minute == 16 * 60 + 51
                && segment.end_minute == 21 * 60 + 30
        });

        assert_eq!(active_code_segments, 2);
        assert!(gap.is_some());
    }

    #[test]
    fn focus_time_counts_stable_blocks_not_all_active_seconds() {
        let rows = vec![
            event("Code.exe", Some("ml")),
            event("Code.exe", Some("ml")),
            event("Code.exe", Some("ml")),
            event("Code.exe", Some("ml")),
            event("Chrome.exe", Some("ml")),
            event("Telegram.exe", Some("ml")),
        ];
        let items = rows
            .iter()
            .enumerate()
            .map(|(index, row)| TimedEvent {
                event: row,
                duration_seconds: 15,
                start_minute: index as i64,
                end_minute: index as i64 + 1,
            })
            .collect::<Vec<_>>();
        let active_seconds = items
            .iter()
            .filter(|item| is_active_event(item.event, 300.0))
            .map(|item| item.duration_seconds)
            .sum::<i64>();
        let focus_seconds = focused_activity_seconds(&items, 300.0);

        assert_eq!(active_seconds, 90);
        assert_eq!(focus_seconds, 60);
    }

    fn create_activity_events_table(conn: &Connection) {
        conn.execute(
            "CREATE TABLE activity_events (\
             ts_start TEXT NOT NULL, ts_end TEXT NOT NULL, process_name TEXT NOT NULL, \
             idle_seconds REAL NOT NULL, keyboard_events INTEGER NOT NULL, mouse_events INTEGER NOT NULL, \
             task_label TEXT)",
            [],
        )
        .unwrap();
    }

    #[test]
    fn runtime_state_creates_action_outcomes_table() {
        let conn = Connection::open_in_memory().unwrap();
        ensure_runtime_state(&conn).unwrap();
        let columns = conn
            .prepare("PRAGMA table_info(action_outcomes)")
            .unwrap()
            .query_map([], |row| row.get::<_, String>(1))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();

        assert!(columns.contains(&"recommendation_id".to_string()));
        assert!(columns.contains(&"minutes_since_action".to_string()));
        assert!(columns.contains(&"active_ratio_after".to_string()));
    }

    #[test]
    fn captures_action_outcomes_once_for_due_horizons() {
        let conn = Connection::open_in_memory().unwrap();
        ensure_runtime_state(&conn).unwrap();
        create_activity_events_table(&conn);
        let action_at = chrono::NaiveDate::from_ymd_opt(2026, 8, 23)
            .unwrap()
            .and_hms_opt(12, 0, 0)
            .unwrap();
        conn.execute(
            "INSERT INTO ml_predictions (timestamp, model_version, effectiveness, decline_15m, decline_30m, decline_60m, break_benefit, recommended_action) \
             VALUES (?1, 'demo-test', 50.0, 0.2, 0.3, 0.4, 6.0, 'BREAK_15')",
            params![action_at.to_string()],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO ml_predictions (timestamp, model_version, effectiveness, decline_15m, decline_30m, decline_60m, break_benefit, recommended_action) \
             VALUES (?1, 'demo-test', 64.0, 0.1, 0.2, 0.3, 3.0, 'CONTINUE')",
            params![(action_at + chrono::Duration::minutes(30)).to_string()],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO recommendations (timestamp, created_at, recommended_action, recommended_duration, recommended_break_minutes, accepted, started_at, break_started_at, effectiveness_before) \
             VALUES (?1, ?1, 'BREAK_15', 15, 15, 1, ?1, ?1, 50.0)",
            params![action_at.to_string()],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO activity_events (ts_start, ts_end, process_name, idle_seconds, keyboard_events, mouse_events, task_label) \
             VALUES (?1, ?2, 'Code.exe', 0.0, 12, 4, 'ml')",
            params![
                (action_at + chrono::Duration::minutes(16)).to_string(),
                (action_at + chrono::Duration::minutes(16) + chrono::Duration::seconds(15)).to_string(),
            ],
        )
        .unwrap();

        let inserted = capture_pending_action_outcomes_in_conn(
            &conn,
            action_at + chrono::Duration::minutes(61),
        )
        .unwrap();
        let inserted_again = capture_pending_action_outcomes_in_conn(
            &conn,
            action_at + chrono::Duration::minutes(62),
        )
        .unwrap();
        let horizons = conn
            .prepare(
                "SELECT minutes_since_action FROM action_outcomes ORDER BY minutes_since_action",
            )
            .unwrap()
            .query_map([], |row| row.get::<_, i64>(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();

        assert_eq!(inserted, 3);
        assert_eq!(inserted_again, 0);
        assert_eq!(horizons, vec![15, 30, 60]);
    }

    #[test]
    fn break_segments_and_state_markers_are_built_from_recommendations() {
        let conn = Connection::open_in_memory().unwrap();
        ensure_runtime_state(&conn).unwrap();
        let started = "2026-08-23 09:10:00";
        let finished = "2026-08-23 09:25:00";
        conn.execute(
            "INSERT INTO recommendations (timestamp, created_at, recommended_action, recommended_duration, recommended_break_minutes, accepted, started_at, completed_at, break_started_at, break_finished_at, effectiveness_before, decline_30, break_benefit) \
             VALUES (?1, ?1, 'BREAK_15', 15, 15, 1, ?1, ?2, ?1, ?2, 45.0, 0.62, 8.0)",
            params![started, finished],
        )
        .unwrap();

        let segments = break_timeline_segments(&conn, "2026-08-23").unwrap();
        let markers = recommendation_state_markers(&conn, "2026-08-23").unwrap();

        assert_eq!(segments.len(), 1);
        assert_eq!(segments[0].kind, "break");
        assert_eq!(segments[0].task.as_deref(), Some("rest"));
        assert!(markers
            .iter()
            .any(|point| point.marker.as_deref() == Some("break_started")));
        assert!(markers
            .iter()
            .any(|point| point.marker.as_deref() == Some("break_finished")));
    }
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
            spawn_demo_ml_scheduler(handle.clone());
            spawn_break_monitor(handle.clone());
            spawn_outcome_capture_scheduler();
            spawn_self_report_scheduler(handle.clone());
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
            get_ml_diagnostics,
            train_personal_model,
            create_test_notification,
            start_break,
            ignore_break,
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
