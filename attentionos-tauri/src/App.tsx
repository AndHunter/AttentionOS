import { useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification'
import './App.css'

type Metric = { label: string; value: string; detail: string }
type TimelineSegment = { app: string; task?: string | null; kind?: string; start_minute: number; end_minute: number; duration_minutes: number }
type AppUsage = { name: string; duration_minutes: number; percent: number }
type RecentSession = { time: string; application: string; duration_minutes: number; task?: string | null }
type StatePoint = { minute: number; effectiveness: number; decline_risk: number; state: string; marker?: string | null; break_benefit?: number | null }
type DailySummary = { work_minutes: number; effective_minutes_estimate: number; break_count: number; recommendation_count: number; accepted_count: number; ignored_count: number; average_decline_risk: number; recovered_effective_minutes_estimate: number; best_period?: string | null }
type DashboardPayload = {
  date: string
  db_path: string
  event_count: number
  focused_minutes: number
  active_minutes: number
  context_switches: number
  current_state: Metric
  metrics: Metric[]
  timeline: TimelineSegment[]
  top_apps: AppUsage[]
  recent_sessions: RecentSession[]
  state_history: StatePoint[]
  daily_summary: DailySummary
}
type NotificationPayload = { id: number; created_at: string; title: string; body: string; state: string; kind: string }
type BreakState = { state: string; recommended_minutes?: number | null; started_at?: string | null; planned_until?: string | null; elapsed_seconds: number; remaining_seconds: number }
type MlDiagnostics = { last_inference_at?: string | null; model_version?: string | null; policy_source?: string | null; candidate_utilities: Record<string, number>; diagnostics: Record<string, unknown>; real_telemetry_hours: number; self_reports: number; recommendations: number; completed_breaks: number; ignored_recommendations: number; usable_outcomes: number }
type PersonalTrainingResult = { status: string; samples: number; model_version: string; validation_mae?: number | null; message: string }
type RuntimeSettings = {
  preferences: { language: string; theme: string; launch_on_startup: boolean; minimize_to_tray: boolean; start_minimized: boolean; current_task_label: string }
  tracking: { idle_threshold_minutes: number; track_active_window: boolean; track_window_titles: boolean; track_keyboard_activity: boolean; track_mouse_activity: boolean; excluded_applications: string[] }
  notifications: { break_recommendations: boolean; performance_warnings: boolean; minimum_interval_minutes: number; live_check_interval_seconds: number; do_not_disturb_start: string; do_not_disturb_end: string }
  model: { min_training_samples: number }
}
type UiText = typeof en
type DemoPrediction = {
  mode: string
  status: 'ready' | 'warmup'
  state?: string
  reason?: string
  disclaimer?: string
  disclaimer_ru?: string
  model_version?: string
  current_effectiveness?: number
  decline_15m?: number
  decline_30m?: number
  decline_60m?: number
  decline_probability?: number
  break_benefit?: number
  recommended_action?: string
  recommended_break_minutes?: number | null
  next_break_eta_minutes?: number | null
  policy_source?: string
  active_minutes?: number
  telemetry_available_minutes?: number
  latency_ms?: number
  recommendation?: { action: string; state?: string; title: string; reason: string; confidence: number; recommended_break_minutes?: number | null; break_benefit?: number; policy_source?: string; utilities?: Record<string, number> }
  diagnostics?: Record<string, unknown>
  signals?: { name: string; label?: string; value: number; unit?: string }[]
  metadata?: { samples?: number; metrics?: Record<string, Record<string, number>>; feature_importance?: Record<string, number> }
}

const palette = ['#2F8F83', '#4D7EA8', '#7A6FBC', '#B8794A', '#4E937A', '#8C6A56', '#68758E']
const defaultTaskIds = [
  'work',
  'study',
  'school',
  'homework',
  'coding',
  'ml',
  'math',
  'physics',
  'chemistry',
  'biology',
  'english',
  'language',
  'reading',
  'writing',
  'research',
  'creative',
  'communication',
  'admin',
  'planning',
  'gaming',
  'rest',
  'other',
]

const ru = {
  subtitle: '\u041b\u043e\u043a\u0430\u043b\u044c\u043d\u0430\u044f \u0430\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430 \u0444\u043e\u043a\u0443\u0441\u0430',
  localOnly: '\u0422\u043e\u043b\u044c\u043a\u043e \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e',
  notifications: '\u0423\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f',
  settings: '\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438',
  currentState: '\u0422\u0435\u043a\u0443\u0449\u0435\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435',
  timeline: '\u0422\u0430\u0439\u043c\u043b\u0430\u0439\u043d',
  timelineHint: '24 \u0447\u0430\u0441\u0430 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0433\u043e \u0434\u043d\u044f \u043f\u043e telemetry.',
  today: '\u0421\u0435\u0433\u043e\u0434\u043d\u044f',
  noData: '\u0414\u0430\u043d\u043d\u044b\u0445 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442',
  noDataText: '\u0417\u0430\u043f\u0443\u0441\u0442\u0438 \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0435, \u0438 \u0437\u0434\u0435\u0441\u044c \u043f\u043e\u044f\u0432\u0438\u0442\u0441\u044f \u0442\u0430\u0439\u043c\u043b\u0430\u0439\u043d.',
  activityPattern: '\u041f\u0430\u0442\u0442\u0435\u0440\u043d \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u0438',
  stateHistory: '\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u044f',
  dailySummary: '\u0418\u0442\u043e\u0433 \u0434\u043d\u044f',
  topApps: '\u0422\u043e\u043f \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0439',
  recentSessions: '\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0441\u0435\u0441\u0441\u0438\u0438',
  time: '\u0412\u0440\u0435\u043c\u044f',
  app: '\u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435',
  duration: '\u0414\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c',
  task: '\u0417\u0430\u0434\u0430\u0447\u0430',
  currentTask: '\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430',
  startTracking: '\u041d\u0430\u0447\u0430\u0442\u044c',
  stopTracking: '\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c',
  tracking: '\u0418\u0434\u0451\u0442 \u0441\u0431\u043e\u0440',
  stopped: '\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e',
  checkIn: '\u041e\u0442\u0447\u0451\u0442',
  save: '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c',
  close: '\u0417\u0430\u043a\u0440\u044b\u0442\u044c',
  exported: '\u042d\u043a\u0441\u043f\u043e\u0440\u0442',
  deleted: '\u0423\u0434\u0430\u043b\u0435\u043d\u043e',
  demo: 'DEMO',
  demoModel: '\u0414\u0435\u043c\u043e-ML',
  demoDisclaimer: '\u0414\u0435\u043c\u043e-\u043c\u043e\u0434\u0435\u043b\u044c \u043e\u0431\u0443\u0447\u0435\u043d\u0430 \u043d\u0430 \u0441\u0438\u043d\u0442\u0435\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0445 \u0434\u0430\u043d\u043d\u044b\u0445.',
  declineRisk: '\u0420\u0438\u0441\u043a \u0441\u043d\u0438\u0436\u0435\u043d\u0438\u044f',
  effectiveness: '\u042d\u0444\u0444\u0435\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u044c',
  breakBenefit: '\u041f\u043e\u043b\u044c\u0437\u0430 \u043f\u0435\u0440\u0435\u0440\u044b\u0432\u0430',
  recoveredTime: 'Восстановлено',
  recommendation: '\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f',
  collectingData: '\u0421\u0431\u043e\u0440 \u0434\u0430\u043d\u043d\u044b\u0445',
  loading: '\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430',
  refresh: '\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c',
  unassigned: '\u0411\u0435\u0437 \u0437\u0430\u0434\u0430\u0447\u0438',
  idle: '\u0411\u0435\u0437\u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435',
  focused: '\u0424\u043e\u043a\u0443\u0441',
  active: '\u0410\u043a\u0442\u0438\u0432\u043d\u043e',
  switches: '\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f',
  noAppUsage: '\u0414\u0430\u043d\u043d\u044b\u0445 \u043f\u043e \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f\u043c \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.',
  notificationHint: '\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0438 \u043f\u043e \u043f\u0435\u0440\u0435\u0440\u044b\u0432\u0430\u043c \u0438 \u0441\u0438\u0441\u0442\u0435\u043c\u043d\u044b\u0435 \u0437\u0430\u043c\u0435\u0442\u043a\u0438.',
  noNotifications: '\u0423\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u0439 \u043d\u0435\u0442',
  notificationEmptyText: '\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0438 \u043f\u043e\u044f\u0432\u044f\u0442\u0441\u044f \u0437\u0434\u0435\u0441\u044c \u0438 \u0432 Windows.',
  settingsSubtitle: '\u0418\u0437\u043c\u0435\u043d\u044f\u0435\u043c\u044b\u0435 \u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b runtime \u0438 \u0441\u0431\u043e\u0440\u0449\u0438\u043a\u0430.',
  tabs: { general: '\u041e\u0431\u0449\u0435', tracking: '\u0421\u0431\u043e\u0440', notifications: '\u0423\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f', privacy: '\u0414\u0430\u043d\u043d\u044b\u0435', model: '\u041c\u043e\u0434\u0435\u043b\u044c' },
  labels: {
    language: '\u042f\u0437\u044b\u043a', theme: '\u0422\u0435\u043c\u0430', launch: '\u0417\u0430\u043f\u0443\u0441\u043a\u0430\u0442\u044c \u0441 Windows', tray: '\u0421\u0432\u043e\u0440\u0430\u0447\u0438\u0432\u0430\u0442\u044c \u0432 \u0442\u0440\u0435\u0439', minimized: '\u0421\u0442\u0430\u0440\u0442\u043e\u0432\u0430\u0442\u044c \u0441\u0432\u0451\u0440\u043d\u0443\u0442\u044b\u043c',
    idle: '\u041f\u043e\u0440\u043e\u0433 \u043f\u0440\u043e\u0441\u0442\u043e\u044f, \u043c\u0438\u043d', activeWindow: '\u041e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u0442\u044c \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u043e\u043a\u043d\u043e', windowTitles: '\u0423\u0447\u0438\u0442\u044b\u0432\u0430\u0442\u044c \u0445\u044d\u0448 \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043a\u043e\u0432 \u043e\u043a\u043e\u043d', keyboard: '\u0421\u0447\u0438\u0442\u0430\u0442\u044c \u043a\u043b\u0430\u0432\u0438\u0430\u0442\u0443\u0440\u0443', mouse: '\u0421\u0447\u0438\u0442\u0430\u0442\u044c \u043c\u044b\u0448\u044c', excluded: '\u0418\u0441\u043a\u043b\u044e\u0447\u0451\u043d\u043d\u044b\u0435 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f', noExcluded: '\u041d\u0435\u0442 \u0438\u0441\u043a\u043b\u044e\u0447\u0451\u043d\u043d\u044b\u0445',
    breakRecommendations: '\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0438 \u043f\u043e \u043f\u0435\u0440\u0435\u0440\u044b\u0432\u0430\u043c', performanceWarnings: '\u041f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u044f \u043e \u0441\u043f\u0430\u0434\u0435', minInterval: '\u041c\u0438\u043d. \u0438\u043d\u0442\u0435\u0440\u0432\u0430\u043b, \u043c\u0438\u043d', liveInterval: '\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430, \u0441\u0435\u043a', dndStart: '\u041d\u0435 \u0431\u0435\u0441\u043f\u043e\u043a\u043e\u0438\u0442\u044c \u0441', dndEnd: '\u041d\u0435 \u0431\u0435\u0441\u043f\u043e\u043a\u043e\u0438\u0442\u044c \u0434\u043e', unread: '\u041d\u0435\u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d\u043d\u044b\u0435',
    database: '\u0411\u0430\u0437\u0430', storage: '\u0425\u0440\u0430\u043d\u0435\u043d\u0438\u0435', typedText: '\u0412\u0432\u0435\u0434\u0451\u043d\u043d\u044b\u0439 \u0442\u0435\u043a\u0441\u0442', screenshots: '\u0421\u043a\u0440\u0438\u043d\u0448\u043e\u0442\u044b', eventsLoaded: '\u0421\u043e\u0431\u044b\u0442\u0438\u0439 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u043e', modelSamples: '\u041c\u0438\u043d. \u043e\u0442\u0447\u0451\u0442\u043e\u0432 \u0434\u043b\u044f \u043c\u043e\u0434\u0435\u043b\u0438', personalModel: '\u041f\u0435\u0440\u0441\u043e\u043d\u0430\u043b\u044c\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c', trainingUi: '\u041e\u0431\u0443\u0447\u0435\u043d\u0438\u0435',
  },
  values: { system: '\u0421\u0438\u0441\u0442\u0435\u043c\u043d\u043e', light: '\u0421\u0432\u0435\u0442\u043b\u0430\u044f', dark: '\u0422\u0451\u043c\u043d\u0430\u044f', localSqlite: '\u0422\u043e\u043b\u044c\u043a\u043e \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 SQLite', never: '\u041d\u0438\u043a\u043e\u0433\u0434\u0430 \u043d\u0435 \u0437\u0430\u043f\u0438\u0441\u044b\u0432\u0430\u0435\u0442\u0441\u044f', collecting: '\u0421\u0431\u043e\u0440 \u0434\u0430\u043d\u043d\u044b\u0445', trainingLater: '\u0421\u0442\u0430\u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e \u043f\u043e\u0441\u043b\u0435 \u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e\u0433\u043e \u0447\u0438\u0441\u043b\u0430 \u043e\u0442\u0447\u0451\u0442\u043e\u0432' },
  actions: { exportData: '\u042d\u043a\u0441\u043f\u043e\u0440\u0442 \u0434\u0430\u043d\u043d\u044b\u0445', deleteTelemetry: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0442\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u044e', deleteReports: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043e\u0442\u0447\u0451\u0442\u044b', deleteInterventions: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0438', deleteModel: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043c\u043e\u0434\u0435\u043b\u044c', deleteAll: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0451 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e', add: '\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c', testNotification: '\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0442\u0435\u0441\u0442\u043e\u0432\u043e\u0435', trainPersonalModel: '\u041e\u0431\u0443\u0447\u0438\u0442\u044c \u043d\u0430 \u043c\u043e\u0438\u0445 \u0434\u0430\u043d\u043d\u044b\u0445' },
  report: { title: '\u041a\u0430\u043a \u043f\u0440\u043e\u0448\u043b\u0430 \u0441\u0435\u0441\u0441\u0438\u044f?', subtitle: '\u041a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u043e\u0442\u0447\u0451\u0442 \u0434\u043b\u044f \u043b\u0438\u0447\u043d\u043e\u0439 \u043c\u043e\u0434\u0435\u043b\u0438.', effectiveness: '\u042d\u0444\u0444\u0435\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u044c', fatigue: '\u0423\u0441\u0442\u0430\u043b\u043e\u0441\u0442\u044c', difficulty: '\u0421\u043b\u043e\u0436\u043d\u043e\u0441\u0442\u044c', note: '\u0417\u0430\u043c\u0435\u0442\u043a\u0430', notePlaceholder: '\u041d\u0435\u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e', skip: '\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c', save: '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043e\u0442\u0447\u0451\u0442' },
  tasks: { work: 'Работа', study: 'Учёба', school: 'Уроки', homework: 'Домашка', coding: 'Программирование', ml: 'ML', math: 'Математика', physics: 'Физика', chemistry: 'Химия', biology: 'Биология', english: 'Английский', language: 'Другой язык', reading: 'Чтение', writing: 'Письмо', research: 'Исследование', creative: 'Творчество', communication: 'Общение', admin: 'Админка', planning: 'Планирование', rest: 'Отдых', gaming: 'Игра', other: 'Другое', none: 'Без задачи' },
  breakActions: { start: '\u041d\u0430\u0447\u0430\u0442\u044c \u043f\u0435\u0440\u0435\u0440\u044b\u0432', manual: 'Начать отдых сейчас', ignore: '\u0418\u0433\u043d\u043e\u0440\u0438\u0440\u043e\u0432\u0430\u0442\u044c', return: '\u0412\u0435\u0440\u043d\u0443\u0442\u044c\u0441\u044f \u043a \u0440\u0430\u0431\u043e\u0442\u0435', timer: '\u041f\u0435\u0440\u0435\u0440\u044b\u0432' },
}
const en = {
  subtitle: 'Local-first focus analytics', localOnly: 'Local only', notifications: 'Notifications', settings: 'Settings',
  currentState: 'Current state', timeline: 'Timeline', timelineHint: 'Full 24-hour local day from telemetry.',
  today: 'Today', noData: 'No focus data yet', noDataText: 'Start tracking and AttentionOS will build your timeline.',
  activityPattern: 'Activity Pattern', stateHistory: 'State history', dailySummary: 'Daily summary', topApps: 'Top Apps', recentSessions: 'Recent Sessions', time: 'Time', app: 'Application',
  duration: 'Duration', task: 'Task', currentTask: 'Current task', startTracking: 'Start tracking',
  stopTracking: 'Stop', tracking: 'Tracking', stopped: 'Stopped', checkIn: 'Check in', save: 'Save', close: 'Close',
  exported: 'Exported', deleted: 'Deleted',
  demo: 'DEMO', demoModel: 'Demo ML', demoDisclaimer: 'Demo model trained on synthetic data.',
  declineRisk: 'Decline risk', effectiveness: 'Effectiveness', breakBenefit: 'Break benefit', recoveredTime: 'Recovered', recommendation: 'Recommendation', collectingData: 'Collecting data',
  loading: 'Loading', refresh: 'Refresh', unassigned: 'Unassigned', idle: 'Idle', focused: 'Focused', active: 'Active', switches: 'Switches', noAppUsage: 'No app usage yet.',
  notificationHint: 'Break recommendations and system notes.', noNotifications: 'No notifications', notificationEmptyText: 'Recommendations will appear here and in Windows.',
  settingsSubtitle: 'Editable runtime preferences used by the collector.',
  tabs: { general: 'General', tracking: 'Tracking', notifications: 'Notifications', privacy: 'Data', model: 'Model' },
  labels: {
    language: 'Language', theme: 'Theme', launch: 'Launch on startup', tray: 'Minimize to tray', minimized: 'Start minimized',
    idle: 'Idle threshold, minutes', activeWindow: 'Track active window', windowTitles: 'Track window title hashes', keyboard: 'Track keyboard activity', mouse: 'Track mouse activity', excluded: 'Excluded applications', noExcluded: 'No excluded apps',
    breakRecommendations: 'Break recommendations', performanceWarnings: 'Performance warnings', minInterval: 'Minimum interval, minutes', liveInterval: 'Live check interval, seconds', dndStart: 'Do not disturb start', dndEnd: 'Do not disturb end', unread: 'Unread notifications',
    database: 'Database', storage: 'Data storage', typedText: 'Typed text', screenshots: 'Screenshots', eventsLoaded: 'Events loaded', modelSamples: 'Minimum training samples', personalModel: 'Personal model', trainingUi: 'Training UI',
  },
  values: { system: 'System', light: 'Light', dark: 'Dark', localSqlite: 'Local SQLite only', never: 'Never recorded', collecting: 'Collecting data', trainingLater: 'Unavailable until enough self-reports exist' },
  actions: { exportData: 'Export data', deleteTelemetry: 'Delete telemetry', deleteReports: 'Delete self reports', deleteInterventions: 'Delete interventions', deleteModel: 'Delete model', deleteAll: 'Delete all local data', add: 'Add', testNotification: 'Send test notification', trainPersonalModel: 'Train on my data' },
  report: { title: 'How was that session?', subtitle: 'A short check-in for the personal model.', effectiveness: 'Effectiveness', fatigue: 'Fatigue', difficulty: 'Difficulty', note: 'Note', notePlaceholder: 'Optional', skip: 'Skip', save: 'Save report' },
  tasks: { work: 'Work', study: 'Study', school: 'Lessons', homework: 'Homework', coding: 'Coding', ml: 'ML', math: 'Math', physics: 'Physics', chemistry: 'Chemistry', biology: 'Biology', english: 'English', language: 'Other language', reading: 'Reading', writing: 'Writing', research: 'Research', creative: 'Creative', communication: 'Communication', admin: 'Admin', planning: 'Planning', rest: 'Rest', gaming: 'Gaming', other: 'Other', none: 'Unassigned' },
  breakActions: { start: 'Start break', manual: 'Start rest now', ignore: 'Ignore', return: 'Return to work', timer: 'Break' },
}

function lang(settings: RuntimeSettings | null): 'en' | 'ru' { return settings?.preferences.language === 'ru' ? 'ru' : 'en' }
function tx(settings: RuntimeSettings | null) { return lang(settings) === 'ru' ? ru : en }
function todayIso() {
  const date = new Date()
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
function shiftDate(value: string, days: number) { const date = new Date(`${value}T12:00:00`); date.setDate(date.getDate() + days); return date.toISOString().slice(0, 10) }
function formatDate(value: string, language: 'en' | 'ru' = 'en') { return new Intl.DateTimeFormat(language === 'ru' ? 'ru-RU' : 'en', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(`${value}T12:00:00`)) }
function formatMinutes(minutes: number, language: 'en' | 'ru' = 'en') {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (language === 'ru') return h > 0 ? `${h}ч ${String(m).padStart(2, '0')}м` : `${m}м`
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}
function translateMetricValue(value: string, language: 'en' | 'ru') {
  if (language !== 'ru') return value
  return value.replace(/(\d+)h\s*(\d+)m/g, '$1ч $2м').replace(/(\d+)m/g, '$1м')
}
function formatClock(minute: number) { return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}` }
function formatSeconds(seconds: number) { const m = Math.floor(Math.max(seconds, 0) / 60); const s = Math.max(seconds, 0) % 60; return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` }
function formatNotificationTime(value: string, language: 'en' | 'ru') { const normalized = value.includes('T') ? value : value.replace(' ', 'T') + 'Z'; return new Intl.DateTimeFormat(language === 'ru' ? 'ru-RU' : 'en', { hour: '2-digit', minute: '2-digit' }).format(new Date(normalized)) }
function riskLabel(language: 'en' | 'ru', t: UiText) { return language === 'ru' ? `${t.declineRisk} эффективности через 15/30/60 мин` : `Effectiveness ${t.declineRisk.toLowerCase()} in 15/30/60 min` }
function risk30Label(language: 'en' | 'ru') { return language === 'ru' ? 'Риск снижения эффективности через 30 мин' : 'Effectiveness decline risk in 30 min' }
function riskNote(language: 'en' | 'ru') { return language === 'ru' ? 'Три числа выше — вероятность снижения эффективности через 15, 30 и 60 минут. Прогноз строится по текущей telemetry, трендам активности, переключениям, непрерывной работе и истории перерывов.' : 'The three numbers are decline probabilities in 15, 30, and 60 minutes, based on telemetry, activity trends, switches, continuous work, and break history.' }
function recoveredNote(language: 'en' | 'ru') { return language === 'ru' ? '«Восстановлено» — оценка эффективных минут, которые модель считает возвращёнными после завершённых перерывов. Будет около 0, пока нет завершённых перерывов с outcome.' : 'Recovered is the estimated effective time regained after completed breaks. It stays near 0 until completed break outcomes exist.' }
function pct(value?: number | null) { return value == null ? '-' : `${Math.round(value * 100)}%` }
function effectiveTheme(settings: RuntimeSettings | null) { return !settings || settings.preferences.theme === 'system' ? 'light' : settings.preferences.theme }
async function ensureNotificationPermission() {
  let permissionGranted = await isPermissionGranted()
  if (!permissionGranted) {
    const permission = await requestPermission()
    permissionGranted = permission === 'granted'
  }
  return permissionGranted
}

function App() {
  const [date, setDate] = useState(todayIso())
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [notifications, setNotifications] = useState<NotificationPayload[]>([])
  const [settings, setSettings] = useState<RuntimeSettings | null>(null)
  const [demoPrediction, setDemoPrediction] = useState<DemoPrediction | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [selfReportOpen, setSelfReportOpen] = useState(false)
  const [selectedSegment, setSelectedSegment] = useState<TimelineSegment | null>(null)
  const [tracking, setTracking] = useState(false)
  const [breakState, setBreakState] = useState<BreakState | null>(null)
  const [mlDiagnostics, setMlDiagnostics] = useState<MlDiagnostics | null>(null)
  const t = tx(settings)

  async function refresh(target = date, showLoading = false) {
    if (showLoading) setLoading(true)
    setError(null)
    try {
      const [dash, notes, runtime, active, demo, currentBreak, diagnostics] = await Promise.all([
        invoke<DashboardPayload>('get_dashboard', { date: target }),
        invoke<NotificationPayload[]>('get_notifications', { limit: 8 }),
        invoke<RuntimeSettings>('get_settings'),
        invoke<boolean>('get_tracking_status'),
        invoke<DemoPrediction>('get_demo_ml_prediction'),
        invoke<BreakState>('get_break_state'),
        invoke<MlDiagnostics>('get_ml_diagnostics'),
      ])
      setDashboard(applyDemoMetric(dash, demo)); setNotifications(notes); setSettings(runtime); setTracking(active); setDemoPrediction(demo); setBreakState(currentBreak); setMlDiagnostics(diagnostics); setSelectedSegment(dash.timeline.at(-1) ?? null)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { if (showLoading) setLoading(false) }
  }

  useEffect(() => { refresh(date, true) }, [date])
  useEffect(() => {
    const timer = window.setInterval(() => {
      refresh(date)
    }, breakState?.state === 'BREAK' ? 5000 : tracking ? 30000 : 60000)
    return () => window.clearInterval(timer)
  }, [date, tracking, breakState?.state])
  useEffect(() => {
    const timer = window.setInterval(async () => {
      if (!tracking || !settings?.notifications.break_recommendations) return
      try {
        const notes = await invoke<NotificationPayload[]>('get_notifications', { limit: 8 })
        setNotifications(notes)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    }, Math.max((settings?.notifications.live_check_interval_seconds ?? 60) * 1000, 60000))
    return () => window.clearInterval(timer)
  }, [tracking, settings?.notifications.break_recommendations, settings?.notifications.live_check_interval_seconds])
  const unreadCount = notifications.filter((item) => item.state === 'unread').length
  const appColor = useMemo(() => { const map = new Map<string, string>(); dashboard?.timeline.forEach((s) => { if (!map.has(s.app)) map.set(s.app, palette[map.size % palette.length]) }); return map }, [dashboard?.timeline])
  const taskOptions = defaultTaskIds
  const currentTaskValue = settings?.preferences.current_task_label && defaultTaskIds.includes(settings.preferences.current_task_label) ? settings.preferences.current_task_label : 'other'

  async function saveRuntimeSettings(next: RuntimeSettings) { await invoke('save_settings', { settings: next }); setSettings(next) }
  async function setCurrentTask(task: string) { if (!settings) return; await saveRuntimeSettings({ ...settings, preferences: { ...settings.preferences, current_task_label: task } }) }
  async function toggleTracking() { if (tracking) { await invoke('stop_tracking'); setTracking(false) } else { if (settings) await saveRuntimeSettings({ ...settings, preferences: { ...settings.preferences, current_task_label: currentTaskValue } }); await invoke('start_tracking'); setTracking(true) } await refresh(date, true) }
  async function startBreak(minutes?: number) { if (!tracking) { await invoke('start_tracking'); setTracking(true) } await invoke('start_break', { minutes: minutes ?? demoPrediction?.recommended_break_minutes ?? breakState?.recommended_minutes ?? 10 }); await refresh(date, true) }
  async function ignoreBreak() { await invoke('ignore_break'); await refresh(date, true) }
  async function finishBreak() { await invoke('finish_break'); await refresh(date, true) }
  async function markRead(id: number) { await invoke('mark_notification_read', { id }); await refresh(date, true) }
  async function sendTestNotification() {
    const note = await invoke<NotificationPayload>('create_test_notification')
    setNotifications((items) => [note, ...items].slice(0, 8))
    const granted = await ensureNotificationPermission()
    if (granted) sendNotification({ title: localizeNotificationTitle(note.title, lang(settings)), body: localizeNotificationBody(note.body, lang(settings)) })
  }
  async function trainPersonalModel(minSamples: number) {
    return await invoke<PersonalTrainingResult>('train_personal_model', { minSamples })
  }

  return (
    <main className="shell" data-theme={effectiveTheme(settings)}>
      <header className="topbar"><div><div className="brand">AttentionOS</div><div className="subtle">{t.subtitle}</div></div><div className="topbar-actions"><button type="button" className="button ghost" onClick={() => setNotificationsOpen(true)}>{t.notifications}{unreadCount > 0 && <span className="badge">{unreadCount}</span>}</button><button type="button" className="button ghost" onClick={() => setSettingsOpen(true)}>{t.settings}</button></div></header>
      {error && <div className="error">Could not load AttentionOS data: {error}</div>}
      <section className="tracking-card"><div className="tracking-status"><span className={tracking ? 'pulse-dot active' : 'pulse-dot'} /><strong>{tracking ? t.tracking : t.stopped}</strong></div><label className="task-select"><span>{t.currentTask}</span><select value={currentTaskValue} onChange={(e) => setCurrentTask(e.target.value)}>{taskOptions.map((task) => <option value={task} key={task}>{displayTask(task, t)}</option>)}</select></label>{breakState?.state === 'BREAK' ? <div className="break-inline"><span>{t.breakActions.timer}</span><strong>{formatSeconds(breakState.remaining_seconds)}</strong><button type="button" className="button primary" onClick={finishBreak}>{t.breakActions.return}</button></div> : <button type="button" className="button rest" onClick={() => startBreak(10)}>{t.breakActions.manual}</button>}<button type="button" className={`button ${tracking ? 'danger' : 'primary'}`} onClick={toggleTracking}>{tracking ? t.stopTracking : t.startTracking}</button><button type="button" className="button" onClick={() => setSelfReportOpen(true)}>{t.checkIn}</button></section>
      <section className="hero-grid"><article className="state-card"><div className="eyebrow">{translateMetric(dashboard?.current_state.label ?? t.currentState, lang(settings))} <span className="demo-badge" title={t.demoDisclaimer}>{t.demo}</span></div><h1>{loading ? t.loading : demoStateTitle(demoPrediction, lang(settings), dashboard?.current_state.value)}</h1><p>{demoPrediction?.status === 'ready' ? t.demoDisclaimer : translateMetricDetail(dashboard?.current_state.detail ?? '', lang(settings))}</p><div className="state-meta"><span>{formatDate(date, lang(settings))}</span><span>{dashboard?.event_count ?? 0} {lang(settings) === 'ru' ? '\u0441\u043e\u0431\u044b\u0442\u0438\u0439' : 'events'}</span></div></article><div className="metrics-grid">{(dashboard?.metrics ?? []).map((m) => <article className="metric-card" key={m.label}><div className="metric-label">{translateMetric(m.label, lang(settings))}</div><div className="metric-value">{translateMetricValue(m.value, lang(settings))}</div><div className="metric-detail">{translateMetricDetail(m.detail, lang(settings))}</div></article>)}</div></section>
      {demoPrediction && <section className="panel demo-panel"><div className="panel-header"><div><h2>{t.demoModel} <span className="demo-badge" title={t.demoDisclaimer}>{t.demo}</span></h2><p>{demoPrediction.status === 'ready' ? t.demoDisclaimer : (demoPrediction.reason ?? t.collectingData)}</p></div><strong>{demoPrediction.model_version ?? 'demo-v1'}</strong></div><div className="demo-grid"><MetricPill label={t.effectiveness} value={demoPrediction.status === 'ready' ? `${demoPrediction.current_effectiveness?.toFixed(0)}/100` : formatMinutes(Math.round(demoPrediction.telemetry_available_minutes ?? demoPrediction.active_minutes ?? 0), lang(settings))} /><MetricPill label={riskLabel(lang(settings), t)} value={demoPrediction.status === 'ready' ? `${pct(demoPrediction.decline_15m)} / ${pct(demoPrediction.decline_30m)} / ${pct(demoPrediction.decline_60m)}` : '-'} /><MetricPill label={t.breakBenefit} value={demoPrediction.status === 'ready' ? `${(demoPrediction.break_benefit ?? 0).toFixed(1)}/10` : '-'} /><MetricPill label={t.recommendation} value={localizeDemoAction(demoPrediction.recommended_action ?? demoPrediction.recommendation?.action ?? 'CONTINUE', lang(settings), demoPrediction.recommended_break_minutes)} /></div><p className="risk-note">{riskNote(lang(settings))}</p><div className="break-actions">{demoPrediction.state === 'BREAK_RECOMMENDED' && breakState?.state !== 'BREAK' && <><button type="button" className="button primary" onClick={() => startBreak()}>{t.breakActions.start}</button><button type="button" className="button" onClick={ignoreBreak}>{t.breakActions.ignore}</button></>}{breakState?.state === 'BREAK' && <><span className="metric-pill compact"><span>{t.breakActions.timer}</span><strong>{formatSeconds(breakState.remaining_seconds)}</strong></span><button type="button" className="button primary" onClick={finishBreak}>{t.breakActions.return}</button></>}</div>{demoPrediction.signals && <div className="signal-list">{demoPrediction.signals.slice(0, 4).map((signal) => <span key={signal.name}>{localizeSignal(signal.label ?? signal.name, lang(settings))}: {signal.value}{signal.unit ? ` ${signal.unit}` : ''}</span>)}</div>}</section>}
      <DailySummaryPanel summary={dashboard?.daily_summary ?? null} t={t} />
      <section className="panel timeline-panel"><div className="panel-header"><div><h2>{t.timeline}</h2><p>{t.timelineHint}</p></div><div className="date-nav"><button type="button" onClick={() => setDate(shiftDate(date, -1))}>{'<'}</button><span>{date === todayIso() ? t.today : formatDate(date, lang(settings))}</span><button type="button" onClick={() => setDate(shiftDate(date, 1))}>{'>'}</button></div></div>{dashboard && dashboard.timeline.length > 0 ? <div className="timeline"><div className="timeline-track">{dashboard.timeline.map((segment, index) => { const dayStart = 0; const dayEnd = 24 * 60; const start = Math.max(segment.start_minute, dayStart); const end = Math.min(segment.end_minute, dayEnd); if (end <= dayStart || start >= dayEnd) return null; const left = ((start - dayStart) / (dayEnd - dayStart)) * 100; const width = Math.max(((end - start) / (dayEnd - dayStart)) * 100, 0.25); const selected = selectedSegment?.app === segment.app && selectedSegment?.start_minute === segment.start_minute; return <button type="button" className={`timeline-segment ${segment.kind === 'idle' ? 'idle' : ''} ${selected ? 'selected' : ''}`} key={`${segment.app}-${segment.start_minute}-${index}`} style={{ left: `${left}%`, width: `${width}%`, background: segment.kind === 'idle' ? undefined : appColor.get(segment.app) }} title={`${formatClock(segment.start_minute)}-${formatClock(segment.end_minute)} | ${displayApp(segment, t)} | ${t.task}: ${displayTask(segment.task, t)}`} onClick={() => setSelectedSegment(segment)} onMouseEnter={() => setSelectedSegment(segment)} /> })}</div><div className="timeline-axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div>{selectedSegment && <div className="timeline-detail"><strong>{displayApp(selectedSegment, t)}</strong><span>{formatClock(selectedSegment.start_minute)}-{formatClock(selectedSegment.end_minute)}</span><span>{formatMinutes(selectedSegment.duration_minutes, lang(settings))}</span><span>{t.task}: {displayTask(selectedSegment.task, t)}</span></div>}</div> : <div className="empty-state"><h3>{t.noData}</h3><p>{t.noDataText}</p></div>}</section>
      <section className="analytics-grid"><article className="panel"><div className="panel-header"><div><h2>{t.stateHistory}</h2><p>{lang(settings) === 'ru' ? 'Эффективность, риск снижения и перерывы за день.' : 'Effectiveness, decline risk, and breaks across the day.'}</p></div></div><StateHistory points={dashboard?.state_history ?? []} t={t} /></article><article className="panel"><div className="panel-header"><div><h2>{t.topApps}</h2><p>{lang(settings) === 'ru' ? '\u041f\u043e \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u043c\u0443 \u0432\u0440\u0435\u043c\u0435\u043d\u0438.' : 'Ranked by active foreground time.'}</p></div></div><div className="app-list">{(dashboard?.top_apps ?? []).length > 0 ? dashboard?.top_apps.map((app, index) => <div className="app-row" key={app.name}><span className="rank">{index + 1}</span><span className="app-name">{app.name}</span><span>{formatMinutes(app.duration_minutes, lang(settings))}</span><div className="progress"><span style={{ width: `${app.percent}%` }} /></div></div>) : <p className="muted">{t.noAppUsage}</p>}</div></article></section>
      <section className="panel"><div className="panel-header"><div><h2>{t.recentSessions}</h2><p>{lang(settings) === 'ru' ? '\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0431\u043b\u043e\u043a\u0438 \u0440\u0430\u0431\u043e\u0442\u044b.' : 'Latest foreground work blocks.'}</p></div></div><div className="sessions-table"><div className="table-head"><span>{t.time}</span><span>{t.app}</span><span>{t.duration}</span><span>{t.task}</span></div>{(dashboard?.recent_sessions ?? []).map((s) => <div className="table-row" key={`${s.time}-${s.application}-${s.duration_minutes}`}><span>{s.time}</span><span>{s.application}</span><span>{formatMinutes(s.duration_minutes, lang(settings))}</span><span>{displayTask(s.task, t)}</span></div>)}</div></section>
      {notificationsOpen && <NotificationsDrawer notifications={notifications} markRead={markRead} close={() => setNotificationsOpen(false)} t={t} />}
      {settingsOpen && settings && <SettingsModal dashboard={dashboard} demoPrediction={demoPrediction} settings={settings} mlDiagnostics={mlDiagnostics} unreadCount={unreadCount} ui={t} onClose={() => setSettingsOpen(false)} onTestNotification={sendTestNotification} onTrainModel={trainPersonalModel} onSave={async (next) => { await saveRuntimeSettings(next); setSettingsOpen(false); await refresh() }} />}
      {selfReportOpen && settings && <SelfReportModal settings={settings} ui={t} onClose={() => setSelfReportOpen(false)} onSaved={async () => { setSelfReportOpen(false); await refresh() }} />}
    </main>
  )
}

function NotificationsDrawer({ notifications, markRead, close, t }: { notifications: NotificationPayload[]; markRead: (id: number) => void; close: () => void; t: UiText }) {
  const language = t === ru ? 'ru' : 'en'
  return <aside className="drawer"><div className="drawer-backdrop" onClick={close} /><div className="drawer-panel"><div className="panel-header"><div><h2>{t.notifications}</h2><p>{t.notificationHint}</p></div><button type="button" className="icon-button" onClick={close}>x</button></div>{notifications.length > 0 ? notifications.map((item) => <button type="button" className="notification" key={item.id} onClick={() => markRead(item.id)}><span className={item.state === 'unread' ? 'dot active' : 'dot'} /><strong>{localizeNotificationTitle(item.title, language)}</strong><p>{localizeNotificationBody(item.body, language)}</p><small>{formatNotificationTime(item.created_at, language)} · {localizeNotificationMeta(item.kind, item.state, language)}</small></button>) : <div className="empty-state compact"><h3>{t.noNotifications}</h3><p>{t.notificationEmptyText}</p></div>}</div></aside>
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return <div className="metric-pill"><span>{label}</span><strong>{value}</strong></div>
}

function DailySummaryPanel({ summary, t }: { summary: DailySummary | null; t: UiText }) {
  if (!summary) return null
  const language = t === ru ? 'ru' : 'en'
  return <section className="panel daily-summary"><div className="panel-header"><div><h2>{t.dailySummary}</h2><p>{t.demoDisclaimer}</p></div></div><div className="demo-grid"><MetricPill label={t.active} value={formatMinutes(summary.work_minutes, language)} /><MetricPill label={t.effectiveness} value={formatMinutes(summary.effective_minutes_estimate, language)} /><MetricPill label={risk30Label(language)} value={`${Math.round(summary.average_decline_risk * 100)}%`} /><MetricPill label={t.recoveredTime} value={`~${formatMinutes(summary.recovered_effective_minutes_estimate, language)}`} /><MetricPill label={t.recommendation} value={`${summary.recommendation_count} / ${summary.accepted_count}`} /><MetricPill label={t.breakActions.ignore} value={String(summary.ignored_count)} /></div><p className="risk-note">{recoveredNote(language)}</p>{summary.best_period && <p className="muted">{summary.best_period}</p>}</section>
}

function StateHistory({ points, t }: { points: StatePoint[]; t: UiText }) {
  const language = t === ru ? 'ru' : 'en'
  const visible = points.slice(-120)
  const [selected, setSelected] = useState<StatePoint | null>(null)
  if (points.length === 0) return <div className="empty-state compact"><h3>{t.noData}</h3><p>{t.collectingData}</p></div>
  const active = (selected && visible.find((point) => point.minute === selected.minute)) || visible[visible.length - 1]
  return <div className="state-history-wrap"><div className="state-history">{visible.map((point, index) => <button type="button" key={`${point.minute}-${index}`} className={`${point.state === 'break' ? 'break' : ''} ${point.marker === 'recommendation' ? 'recommendation' : ''} ${active.minute === point.minute ? 'selected' : ''}`} title={`${formatClock(point.minute)} | ${t.effectiveness}: ${Math.round(point.effectiveness)} | ${risk30Label(language)}: ${Math.round(point.decline_risk * 100)}%${point.break_benefit != null ? ` | ${t.breakBenefit}: ${point.break_benefit}/10` : ''}`} style={{ left: `${(point.minute / 1440) * 100}%`, bottom: `${Math.max(4, Math.min(point.effectiveness, 100))}%` }} onClick={() => setSelected(point)} onMouseEnter={() => setSelected(point)}><i style={{ height: `${Math.max(2, Math.round(point.decline_risk * 48))}px` }} /></button>)}</div><div className="state-detail"><strong>{formatClock(active.minute)}</strong><span>{t.effectiveness}: {Math.round(active.effectiveness)}/100</span><span>{risk30Label(language)}: {Math.round(active.decline_risk * 100)}%</span>{active.break_benefit != null && <span>{t.breakBenefit}: {active.break_benefit}/10</span>}</div></div>
}

function displayTask(task: string | null | undefined, t: UiText) {
  if (!task || task === 'None') return t.tasks.none
  return (t.tasks as Record<string, string>)[task] ?? task
}

function displayApp(segment: TimelineSegment, t: UiText) {
  return segment.kind === 'idle' ? t.idle : segment.app
}

function SettingsModal({ dashboard, demoPrediction, settings, mlDiagnostics, unreadCount, ui, onClose, onTestNotification, onTrainModel, onSave }: { dashboard: DashboardPayload | null; demoPrediction: DemoPrediction | null; settings: RuntimeSettings; mlDiagnostics: MlDiagnostics | null; unreadCount: number; ui: UiText; onClose: () => void; onTestNotification: () => Promise<void>; onTrainModel: (minSamples: number) => Promise<PersonalTrainingResult>; onSave: (settings: RuntimeSettings) => Promise<void> }) {
  const [tab, setTab] = useState('general')
  const [draft, setDraft] = useState<RuntimeSettings>(structuredClone(settings))
  const [excludedInput, setExcludedInput] = useState('')
  const [status, setStatus] = useState('')
  const update = (next: RuntimeSettings) => setDraft(structuredClone(next))
  const setPreference = <K extends keyof RuntimeSettings['preferences']>(key: K, value: RuntimeSettings['preferences'][K]) => update({ ...draft, preferences: { ...draft.preferences, [key]: value } })
  const setTracking = <K extends keyof RuntimeSettings['tracking']>(key: K, value: RuntimeSettings['tracking'][K]) => update({ ...draft, tracking: { ...draft.tracking, [key]: value } })
  const setNotifications = <K extends keyof RuntimeSettings['notifications']>(key: K, value: RuntimeSettings['notifications'][K]) => update({ ...draft, notifications: { ...draft.notifications, [key]: value } })
  async function trainModel() {
    setStatus(ui.loading)
    try {
      const result = await onTrainModel(draft.model.min_training_samples)
      const mae = result.validation_mae == null ? '-' : result.validation_mae.toFixed(3)
      setStatus(`${result.status}: ${result.samples} samples, MAE ${mae}`)
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err))
    }
  }
  const tabs = ['general', 'tracking', 'notifications', 'privacy', 'model']
  return <aside className="modal-layer"><div className="modal-backdrop" onClick={onClose} /><section className="settings-modal"><div className="settings-titlebar"><div><h2>{ui.settings}</h2><p>{ui.settingsSubtitle}</p></div><button type="button" className="icon-button" onClick={onClose}>x</button></div><div className="settings-tabs">{tabs.map((item) => <button type="button" className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>{ui.tabs[item as keyof typeof ui.tabs]}</button>)}</div><div className="settings-body">
    {tab === 'general' && <div className="settings-form"><Select label={ui.labels.language} value={draft.preferences.language} options={['system', 'en', 'ru']} optionLabel={(v) => v === 'system' ? ui.values.system : v.toUpperCase()} onChange={(v) => setPreference('language', v)} /><Select label={ui.labels.theme} value={draft.preferences.theme} options={['system', 'light', 'dark']} optionLabel={(v) => ({ system: ui.values.system, light: ui.values.light, dark: ui.values.dark }[v] ?? v)} onChange={(v) => setPreference('theme', v)} /><Checkbox label={ui.labels.launch} checked={draft.preferences.launch_on_startup} onChange={(v) => setPreference('launch_on_startup', v)} /><Checkbox label={ui.labels.tray} checked={draft.preferences.minimize_to_tray} onChange={(v) => setPreference('minimize_to_tray', v)} /><Checkbox label={ui.labels.minimized} checked={draft.preferences.start_minimized} onChange={(v) => setPreference('start_minimized', v)} /></div>}
    {tab === 'tracking' && <div className="settings-form"><NumberInput label={ui.labels.idle} min={1} max={30} value={draft.tracking.idle_threshold_minutes} onChange={(v) => setTracking('idle_threshold_minutes', v)} /><Checkbox label={ui.labels.activeWindow} checked={draft.tracking.track_active_window} onChange={(v) => setTracking('track_active_window', v)} /><Checkbox label={ui.labels.windowTitles} checked={draft.tracking.track_window_titles} onChange={(v) => setTracking('track_window_titles', v)} /><Checkbox label={ui.labels.keyboard} checked={draft.tracking.track_keyboard_activity} onChange={(v) => setTracking('track_keyboard_activity', v)} /><Checkbox label={ui.labels.mouse} checked={draft.tracking.track_mouse_activity} onChange={(v) => setTracking('track_mouse_activity', v)} /><div className="field full"><label>{ui.labels.excluded}</label><div className="excluded-list">{draft.tracking.excluded_applications.length === 0 && <span className="empty-chip">{ui.labels.noExcluded}</span>}{draft.tracking.excluded_applications.map((item) => <button type="button" key={item} onClick={() => setTracking('excluded_applications', draft.tracking.excluded_applications.filter((entry) => entry !== item))}>{item} x</button>)}</div><div className="inline-input"><input value={excludedInput} onChange={(e) => setExcludedInput(e.target.value)} placeholder="example.exe" /><button type="button" onClick={() => { const value = excludedInput.trim(); if (!value) return; setTracking('excluded_applications', [...draft.tracking.excluded_applications, value]); setExcludedInput('') }}>{ui.actions.add}</button></div></div></div>}
    {tab === 'notifications' && <div className="settings-form"><Checkbox label={ui.labels.breakRecommendations} checked={draft.notifications.break_recommendations} onChange={(v) => setNotifications('break_recommendations', v)} /><Checkbox label={ui.labels.performanceWarnings} checked={draft.notifications.performance_warnings} onChange={(v) => setNotifications('performance_warnings', v)} /><Select label={ui.labels.minInterval} value={String(draft.notifications.minimum_interval_minutes)} options={['15', '30', '45', '60']} onChange={(v) => setNotifications('minimum_interval_minutes', Number(v))} /><NumberInput label={ui.labels.liveInterval} min={60} max={1800} value={draft.notifications.live_check_interval_seconds} onChange={(v) => setNotifications('live_check_interval_seconds', v)} /><TextInput label={ui.labels.dndStart} value={draft.notifications.do_not_disturb_start} onChange={(v) => setNotifications('do_not_disturb_start', v)} /><TextInput label={ui.labels.dndEnd} value={draft.notifications.do_not_disturb_end} onChange={(v) => setNotifications('do_not_disturb_end', v)} /><SettingRow label={ui.labels.unread} value={String(unreadCount)} /><button type="button" className="button primary" onClick={onTestNotification}>{ui.actions.testNotification}</button></div>}
    {tab === 'privacy' && <div className="settings-form"><SettingRow label={ui.labels.database} value={dashboard?.db_path ?? '-'} /><SettingRow label={ui.labels.storage} value={ui.values.localSqlite} /><SettingRow label={ui.labels.typedText} value={ui.values.never} /><SettingRow label={ui.labels.screenshots} value={ui.values.never} /><SettingRow label={ui.labels.eventsLoaded} value={String(dashboard?.event_count ?? 0)} /><div className="danger-grid"><ActionButton label={ui.actions.exportData} command="export_data" onDone={(m) => setStatus(`${ui.exported}: ${m}`)} /><ActionButton label={ui.actions.deleteTelemetry} command="delete_telemetry" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteTelemetry}`)} /><ActionButton label={ui.actions.deleteReports} command="delete_self_reports" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteReports}`)} /><ActionButton label={ui.actions.deleteInterventions} command="delete_interventions" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteInterventions}`)} /><ActionButton label={ui.actions.deleteModel} command="delete_model" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteModel}`)} /><ActionButton label={ui.actions.deleteAll} command="delete_all_data" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteAll}`)} /></div>{status && <p className="settings-status">{status}</p>}</div>}
    {tab === 'model' && <div className="settings-form"><SettingRow label={ui.demoModel} value={`${demoPrediction?.model_version ?? mlDiagnostics?.model_version ?? 'demo-v1'} / Synthetic demo`} /><SettingRow label={ui.demo} value={ui.demoDisclaimer} /><SettingRow label={ui.labels.eventsLoaded} value={String(demoPrediction?.metadata?.samples ?? 0)} /><SettingRow label="MAE" value={String(demoPrediction?.metadata?.metrics?.temporal?.effectiveness_mae?.toFixed(3) ?? '-')} /><SettingRow label="Decline ROC-AUC" value={String(demoPrediction?.metadata?.metrics?.temporal?.decline_roc_auc?.toFixed(3) ?? '-')} /><SettingRow label="Inference latency" value={`${demoPrediction?.latency_ms ?? '-'} ms`} /><SettingRow label="Last inference" value={mlDiagnostics?.last_inference_at ?? String(demoPrediction?.diagnostics?.last_inference_at ?? '-')} /><SettingRow label="Policy source" value={mlDiagnostics?.policy_source ?? demoPrediction?.policy_source ?? '-'} /><SettingRow label="Telemetry window" value={String((mlDiagnostics?.diagnostics?.telemetry_available_minutes ?? demoPrediction?.telemetry_available_minutes ?? '-') as string)} /><SettingRow label="Real telemetry" value={`${(mlDiagnostics?.real_telemetry_hours ?? 0).toFixed(1)} h`} /><SettingRow label="Self reports" value={String(mlDiagnostics?.self_reports ?? 0)} /><SettingRow label="Recommendations" value={String(mlDiagnostics?.recommendations ?? 0)} /><SettingRow label="Completed breaks" value={String(mlDiagnostics?.completed_breaks ?? 0)} /><SettingRow label="Ignored" value={String(mlDiagnostics?.ignored_recommendations ?? 0)} /><SettingRow label="Usable outcomes" value={String(mlDiagnostics?.usable_outcomes ?? 0)} /><UtilityRows utilities={mlDiagnostics?.candidate_utilities ?? demoPrediction?.recommendation?.utilities ?? {}} /><NumberInput label={ui.labels.modelSamples} min={5} max={500} value={draft.model.min_training_samples} onChange={(v) => update({ ...draft, model: { min_training_samples: v } })} /><button type="button" className="button primary" onClick={trainModel}>{ui.actions.trainPersonalModel}</button><SettingRow label={ui.labels.personalModel} value={String(demoPrediction?.diagnostics?.personal_model_loaded ?? false)} /><SettingRow label={ui.labels.trainingUi} value={ui.values.trainingLater} />{status && <p className="settings-status">{status}</p>}</div>}
  </div><div className="settings-actions"><button type="button" className="button" onClick={onClose}>{ui.close}</button><button type="button" className="button primary" onClick={() => onSave(draft)}>{ui.save}</button></div></section></aside>
}

function ActionButton({ label, command, danger, onDone }: { label: string; command: string; danger?: boolean; onDone: (message: string) => void }) { return <button type="button" className={`button ${danger ? 'danger' : ''}`} onClick={async () => { if (danger && !window.confirm(`${label}?`)) return; const result = await invoke<string | null>(command); onDone(result ?? '') }}>{label}</button> }
function SettingRow({ label, value }: { label: string; value: string }) { return <div className="setting-row"><span>{label}</span><strong>{value}</strong></div> }
function UtilityRows({ utilities }: { utilities: Record<string, number> }) { const rows = Object.entries(utilities).sort((a, b) => b[1] - a[1]).slice(0, 7); if (rows.length === 0) return null; return <div className="utility-list">{rows.map(([action, value]) => <SettingRow key={action} label={action.replace('_', ' ')} value={Number(value).toFixed(2)} />)}</div> }
function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) { return <label className="check-row"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /><span>{label}</span></label> }
function Select({ label, value, options, optionLabel, onChange }: { label: string; value: string; options: string[]; optionLabel?: (value: string) => string; onChange: (value: string) => void }) { return <label className="field"><span>{label}</span><select value={value} onChange={(e) => onChange(e.target.value)}>{options.map((item) => <option value={item} key={item}>{optionLabel ? optionLabel(item) : item}</option>)}</select></label> }
function NumberInput({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) { return <label className="field"><span>{label}</span><input type="number" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} /></label> }
function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="field"><span>{label}</span><input value={value} onChange={(e) => onChange(e.target.value)} /></label> }
function SelfReportModal({ settings, ui, onClose, onSaved }: { settings: RuntimeSettings; ui: UiText; onClose: () => void; onSaved: () => Promise<void> }) {
  const [effectiveness, setEffectiveness] = useState(3)
  const [fatigue, setFatigue] = useState(2)
  const [difficulty, setDifficulty] = useState(3)
  const [note, setNote] = useState('')
  async function save() {
    await invoke('save_self_report', { report: { effectiveness, fatigue, difficulty, note, task: settings.preferences.current_task_label === 'None' ? null : settings.preferences.current_task_label } })
    await onSaved()
  }
  return <aside className="modal-layer"><div className="modal-backdrop" onClick={onClose} /><section className="report-modal"><div className="settings-titlebar"><div><h2>{ui.report.title}</h2><p>{ui.report.subtitle}</p></div><button type="button" className="icon-button" onClick={onClose}>x</button></div><div className="report-body"><Rating label={ui.report.effectiveness} value={effectiveness} onChange={setEffectiveness} /><Rating label={ui.report.fatigue} value={fatigue} onChange={setFatigue} /><Rating label={ui.report.difficulty} value={difficulty} onChange={setDifficulty} /><label className="field full"><span>{ui.report.note}</span><textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={ui.report.notePlaceholder} maxLength={500} /></label></div><div className="settings-actions"><button type="button" className="button" onClick={onClose}>{ui.report.skip}</button><button type="button" className="button primary" onClick={save}>{ui.report.save}</button></div></section></aside>
}
function Rating({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <div className="rating-row"><span>{label}</span><div>{[1, 2, 3, 4, 5].map((item) => <button type="button" className={item === value ? 'active' : ''} onClick={() => onChange(item)} key={item}>{item}</button>)}</div></div>
}
function translateMetric(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'Focused time': '\u0412\u0440\u0435\u043c\u044f \u0444\u043e\u043a\u0443\u0441\u0430', 'Active time': '\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f', 'Context switches': '\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f', 'Input events': '\u0421\u043e\u0431\u044b\u0442\u0438\u044f \u0432\u0432\u043e\u0434\u0430', 'Current state': '\u0422\u0435\u043a\u0443\u0449\u0435\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435', 'Decline risk 30m': 'Риск снижения эффективности через 30 мин' } as Record<string, string>)[value] ?? value }
function translateMetricDetail(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'Active time inside productive selected task categories': 'Активное время в продуктивных выбранных категориях: учёба, ML, математика, английский, код и т.д.', 'All non-idle keyboard, mouse, and foreground activity': 'Всё не-idle время с клавиатурой, мышью или активным окном.', 'Non-idle time for the selected task': 'Активное время в выбранной задаче.', 'Non-idle work outside common distractions': '\u0410\u043a\u0442\u0438\u0432\u043d\u0430\u044f \u0440\u0430\u0431\u043e\u0442\u0430 \u0432\u043d\u0435 \u043e\u0442\u0432\u043b\u0435\u0447\u0435\u043d\u0438\u0439', 'Keyboard, mouse, and foreground activity': '\u041a\u043b\u0430\u0432\u0438\u0430\u0442\u0443\u0440\u0430, \u043c\u044b\u0448\u044c \u0438 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u043e\u043a\u043d\u043e', 'Foreground app changes': '\u0421\u043c\u0435\u043d\u044b \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e \u043e\u043a\u043d\u0430', 'Aggregate counts, no typed text': '\u0422\u043e\u043b\u044c\u043a\u043e \u0441\u0447\u0451\u0442\u0447\u0438\u043a\u0438, \u0431\u0435\u0437 \u0442\u0435\u043a\u0441\u0442\u0430', 'Derived from local telemetry only': '\u0420\u0430\u0441\u0441\u0447\u0438\u0442\u0430\u043d\u043e \u0438\u0437 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0439 \u0442\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u0438', 'Predicted decline risk over the next 30 minutes': 'Та же модель: короткая карточка показывает только 30-минутный риск.' } as Record<string, string>)[value] ?? value }
function localizeNotificationTitle(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'Time for a break': '\u041f\u043e\u0440\u0430 \u043d\u0430 \u043f\u0435\u0440\u0435\u0440\u044b\u0432', 'AttentionOS test': '\u0422\u0435\u0441\u0442 AttentionOS' } as Record<string, string>)[value] ?? value }
function localizeNotificationBody(value: string, language: 'en' | 'ru') {
  if (language !== 'ru') return value
  if (value === 'Test notification from AttentionOS. If you see this, notifications are connected.') return '\u0422\u0435\u0441\u0442\u043e\u0432\u043e\u0435 \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u0435 AttentionOS. \u0415\u0441\u043b\u0438 \u0442\u044b \u0435\u0433\u043e \u0432\u0438\u0434\u0438\u0448\u044c, \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u044b.'
  const match = value.match(/working for ([\d.]+) min.*break: (\d+) min/i)
  if (match) return `\u0422\u044b \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0448\u044c \u0443\u0436\u0435 ${Math.round(Number(match[1]))} \u043c\u0438\u043d. \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u0435\u043c\u044b\u0439 \u043e\u0442\u0434\u044b\u0445: ${match[2]} \u043c\u0438\u043d.`
  return value
}
function localizeNotificationMeta(kind: string, state: string, language: 'en' | 'ru') {
  if (language !== 'ru') return `${kind} - ${state}`
  const states: Record<string, string> = { unread: '\u043d\u043e\u0432\u043e\u0435', read: '\u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d\u043e', dismissed: '\u0441\u043a\u0440\u044b\u0442\u043e' }
  const kinds: Record<string, string> = { intervention: '\u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f', system: '\u0441\u0438\u0441\u0442\u0435\u043c\u0430' }
  return `${kinds[kind] ?? kind} - ${states[state] ?? state}`
}
function applyDemoMetric(dashboard: DashboardPayload, demo: DemoPrediction): DashboardPayload {
  const metrics = dashboard.metrics.filter((item) => item.label !== 'Input events')
  const risk = demo.status === 'ready' ? Math.round((demo.decline_probability ?? 0) * 100) : null
  metrics.push({
    label: 'Decline risk 30m',
    value: risk === null ? '-' : `${risk}%`,
    detail: demo.status === 'ready' ? 'Predicted decline risk over the next 30 minutes' : 'Collecting at least 30 minutes of telemetry',
  })
  return { ...dashboard, metrics }
}
function demoStateTitle(demo: DemoPrediction | null, language: 'en' | 'ru', fallback?: string) {
  if (!demo || demo.status !== 'ready') return language === 'ru' ? '\u0421\u0431\u043e\u0440 \u0434\u0430\u043d\u043d\u044b\u0445' : (fallback ?? 'Collecting data')
  if (demo.state === 'BREAK_RECOMMENDED') return language === 'ru' ? '\u041e\u0422\u0414\u041e\u0425\u041d\u0423\u0422\u042c' : 'BREAK'
  return language === 'ru' ? '\u0420\u0410\u0411\u041e\u0422\u0410\u0422\u042c' : 'WORK'
}
function localizeDemoAction(action: string, language: 'en' | 'ru', minutes?: number | null) {
  if (language !== 'ru') return action.replace('_', ' ')
  if (action.startsWith('BREAK')) return `\u041f\u0435\u0440\u0435\u0440\u044b\u0432 ${minutes ?? action.split('_')[1]} \u043c\u0438\u043d`
  return ({ CONTINUE: '\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442\u044c', SWITCH_TASK: '\u0421\u043c\u0435\u043d\u0438\u0442\u044c \u0437\u0430\u0434\u0430\u0447\u0443' } as Record<string, string>)[action] ?? action
}
function localizeSignal(name: string, language: 'en' | 'ru') {
  if (language !== 'ru') return name.replaceAll('_', ' ')
  return ({
    session_duration_vs_baseline: '\u0421\u0435\u0441\u0441\u0438\u044f \u043a baseline',
    switch_rate_delta_5_30: '\u0420\u043e\u0441\u0442 \u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0439',
    input_rate_slope_30m: '\u0422\u0440\u0435\u043d\u0434 \u0432\u0432\u043e\u0434\u0430',
    active_ratio_vs_baseline: '\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u044c \u043a baseline',
    workload_last_4h: '\u041d\u0430\u0433\u0440\u0443\u0437\u043a\u0430 4\u0447',
  } as Record<string, string>)[name] ?? name
}

export default App
