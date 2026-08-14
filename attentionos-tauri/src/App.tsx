import { useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification'
import './App.css'

type Metric = { label: string; value: string; detail: string }
type TimelineSegment = { app: string; task?: string | null; start_minute: number; end_minute: number; duration_minutes: number }
type AppUsage = { name: string; duration_minutes: number; percent: number }
type RecentSession = { time: string; application: string; duration_minutes: number; task?: string | null }
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
}
type NotificationPayload = { id: number; created_at: string; title: string; body: string; state: string; kind: string }
type RuntimeSettings = {
  preferences: { language: string; theme: string; launch_on_startup: boolean; minimize_to_tray: boolean; start_minimized: boolean; current_task_label: string }
  tracking: { idle_threshold_minutes: number; track_active_window: boolean; track_window_titles: boolean; track_keyboard_activity: boolean; track_mouse_activity: boolean; excluded_applications: string[] }
  notifications: { break_recommendations: boolean; performance_warnings: boolean; minimum_interval_minutes: number; live_check_interval_seconds: number; do_not_disturb_start: string; do_not_disturb_end: string }
  model: { min_training_samples: number }
}
type UiText = typeof en

const palette = ['#2F8F83', '#4D7EA8', '#7A6FBC', '#B8794A', '#4E937A', '#8C6A56', '#68758E']
const defaultTasks = ['Coding', 'ML', 'Math', 'English', 'Rest', 'Meeting', 'Admin', 'Other']

const ru = {
  subtitle: '\u041b\u043e\u043a\u0430\u043b\u044c\u043d\u0430\u044f \u0430\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430 \u0444\u043e\u043a\u0443\u0441\u0430',
  localOnly: '\u0422\u043e\u043b\u044c\u043a\u043e \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e',
  notifications: '\u0423\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f',
  settings: '\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438',
  currentState: '\u0422\u0435\u043a\u0443\u0449\u0435\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435',
  timeline: '\u0422\u0430\u0439\u043c\u043b\u0430\u0439\u043d',
  timelineHint: '\u0420\u0430\u0431\u043e\u0447\u0438\u0439 \u0434\u0435\u043d\u044c 09:00-18:00 \u043f\u043e \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0439 \u0442\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u0438.',
  today: '\u0421\u0435\u0433\u043e\u0434\u043d\u044f',
  noData: '\u0414\u0430\u043d\u043d\u044b\u0445 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442',
  noDataText: '\u0417\u0430\u043f\u0443\u0441\u0442\u0438 \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0435, \u0438 \u0437\u0434\u0435\u0441\u044c \u043f\u043e\u044f\u0432\u0438\u0442\u0441\u044f \u0442\u0430\u0439\u043c\u043b\u0430\u0439\u043d.',
  activityPattern: '\u041f\u0430\u0442\u0442\u0435\u0440\u043d \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u0438',
  topApps: '\u0422\u043e\u043f \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0439',
  recentSessions: '\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0441\u0435\u0441\u0441\u0438\u0438',
  time: '\u0412\u0440\u0435\u043c\u044f',
  app: '\u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435',
  duration: '\u0414\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c',
  task: '\u0417\u0430\u0434\u0430\u0447\u0430',
  currentTask: '\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430',
  addTask: '\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c',
  startTracking: '\u041d\u0430\u0447\u0430\u0442\u044c',
  stopTracking: '\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c',
  tracking: '\u0418\u0434\u0451\u0442 \u0441\u0431\u043e\u0440',
  stopped: '\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e',
  checkIn: '\u041e\u0442\u0447\u0451\u0442',
  save: '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c',
  close: '\u0417\u0430\u043a\u0440\u044b\u0442\u044c',
  exported: '\u042d\u043a\u0441\u043f\u043e\u0440\u0442',
  deleted: '\u0423\u0434\u0430\u043b\u0435\u043d\u043e',
  loading: '\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430',
  refresh: '\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c',
  unassigned: '\u0411\u0435\u0437 \u0437\u0430\u0434\u0430\u0447\u0438',
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
  actions: { exportData: '\u042d\u043a\u0441\u043f\u043e\u0440\u0442 \u0434\u0430\u043d\u043d\u044b\u0445', deleteTelemetry: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0442\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u044e', deleteReports: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043e\u0442\u0447\u0451\u0442\u044b', deleteInterventions: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0438', deleteModel: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043c\u043e\u0434\u0435\u043b\u044c', deleteAll: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0451 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e', add: '\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c', testNotification: '\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0442\u0435\u0441\u0442\u043e\u0432\u043e\u0435' },
  report: { title: '\u041a\u0430\u043a \u043f\u0440\u043e\u0448\u043b\u0430 \u0441\u0435\u0441\u0441\u0438\u044f?', subtitle: '\u041a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u043e\u0442\u0447\u0451\u0442 \u0434\u043b\u044f \u043b\u0438\u0447\u043d\u043e\u0439 \u043c\u043e\u0434\u0435\u043b\u0438.', effectiveness: '\u042d\u0444\u0444\u0435\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u044c', fatigue: '\u0423\u0441\u0442\u0430\u043b\u043e\u0441\u0442\u044c', difficulty: '\u0421\u043b\u043e\u0436\u043d\u043e\u0441\u0442\u044c', note: '\u0417\u0430\u043c\u0435\u0442\u043a\u0430', notePlaceholder: '\u041d\u0435\u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e', skip: '\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c', save: '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043e\u0442\u0447\u0451\u0442' },
}
const en = {
  subtitle: 'Local-first focus analytics', localOnly: 'Local only', notifications: 'Notifications', settings: 'Settings',
  currentState: 'Current state', timeline: 'Timeline', timelineHint: '09:00-18:00 workday view from local telemetry.',
  today: 'Today', noData: 'No focus data yet', noDataText: 'Start tracking and AttentionOS will build your timeline.',
  activityPattern: 'Activity Pattern', topApps: 'Top Apps', recentSessions: 'Recent Sessions', time: 'Time', app: 'Application',
  duration: 'Duration', task: 'Task', currentTask: 'Current task', addTask: 'Add', startTracking: 'Start tracking',
  stopTracking: 'Stop', tracking: 'Tracking', stopped: 'Stopped', checkIn: 'Check in', save: 'Save', close: 'Close',
  exported: 'Exported', deleted: 'Deleted',
  loading: 'Loading', refresh: 'Refresh', unassigned: 'Unassigned', focused: 'Focused', active: 'Active', switches: 'Switches', noAppUsage: 'No app usage yet.',
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
  actions: { exportData: 'Export data', deleteTelemetry: 'Delete telemetry', deleteReports: 'Delete self reports', deleteInterventions: 'Delete interventions', deleteModel: 'Delete model', deleteAll: 'Delete all local data', add: 'Add', testNotification: 'Send test notification' },
  report: { title: 'How was that session?', subtitle: 'A short check-in for the personal model.', effectiveness: 'Effectiveness', fatigue: 'Fatigue', difficulty: 'Difficulty', note: 'Note', notePlaceholder: 'Optional', skip: 'Skip', save: 'Save report' },
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
function formatMinutes(minutes: number) { const h = Math.floor(minutes / 60); const m = minutes % 60; return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m` }
function formatClock(minute: number) { return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}` }
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [selfReportOpen, setSelfReportOpen] = useState(false)
  const [selectedSegment, setSelectedSegment] = useState<TimelineSegment | null>(null)
  const [tracking, setTracking] = useState(false)
  const [customTask, setCustomTask] = useState('')
  const [lastToastId, setLastToastId] = useState(0)
  const t = tx(settings)

  async function refresh(target = date) {
    setLoading(true); setError(null)
    try {
      const [dash, notes, runtime, active] = await Promise.all([
        invoke<DashboardPayload>('get_dashboard', { date: target }),
        invoke<NotificationPayload[]>('get_notifications', { limit: 8 }),
        invoke<RuntimeSettings>('get_settings'),
        invoke<boolean>('get_tracking_status'),
      ])
      setDashboard(dash); setNotifications(notes); setSettings(runtime); setTracking(active); setSelectedSegment(dash.timeline.at(-1) ?? null)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setLoading(false) }
  }

  useEffect(() => { refresh(date) }, [date])
  useEffect(() => {
    const timer = window.setInterval(() => {
      refresh(date)
    }, tracking ? 10000 : 30000)
    return () => window.clearInterval(timer)
  }, [date, tracking])
  useEffect(() => {
    const timer = window.setInterval(async () => {
      if (!tracking || !settings?.notifications.break_recommendations) return
      try {
        const notes = await invoke<NotificationPayload[]>('evaluate_recommendations')
        setNotifications(notes)
        const newest = notes.find((item) => item.state === 'unread')
        if (newest && newest.id > lastToastId) {
          const granted = await ensureNotificationPermission()
          if (granted) sendNotification({ title: localizeNotificationTitle(newest.title, lang(settings)), body: localizeNotificationBody(newest.body, lang(settings)) })
          setLastToastId(newest.id)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    }, Math.max((settings?.notifications.live_check_interval_seconds ?? 60) * 1000, 60000))
    return () => window.clearInterval(timer)
  }, [tracking, settings, lastToastId])
  const unreadCount = notifications.filter((item) => item.state === 'unread').length
  const appColor = useMemo(() => { const map = new Map<string, string>(); dashboard?.timeline.forEach((s) => { if (!map.has(s.app)) map.set(s.app, palette[map.size % palette.length]) }); return map }, [dashboard?.timeline])
  const taskOptions = useMemo(() => Array.from(new Set(['None', ...defaultTasks, ...(settings?.preferences.current_task_label && settings.preferences.current_task_label !== 'None' ? [settings.preferences.current_task_label] : [])])), [settings?.preferences.current_task_label])

  async function saveRuntimeSettings(next: RuntimeSettings) { await invoke('save_settings', { settings: next }); setSettings(next) }
  async function setCurrentTask(task: string) { if (!settings) return; await saveRuntimeSettings({ ...settings, preferences: { ...settings.preferences, current_task_label: task } }) }
  async function addTask() { const task = customTask.trim(); if (!task) return; await setCurrentTask(task); setCustomTask('') }
  async function toggleTracking() { if (tracking) { await invoke('stop_tracking'); setTracking(false) } else { if (settings) await saveRuntimeSettings(settings); await invoke('start_tracking'); setTracking(true) } await refresh() }
  async function markRead(id: number) { await invoke('mark_notification_read', { id }); await refresh() }
  async function sendTestNotification() {
    const note = await invoke<NotificationPayload>('create_test_notification')
    setNotifications((items) => [note, ...items].slice(0, 8))
    const granted = await ensureNotificationPermission()
    if (granted) sendNotification({ title: localizeNotificationTitle(note.title, lang(settings)), body: localizeNotificationBody(note.body, lang(settings)) })
    setLastToastId(note.id)
  }

  return (
    <main className="shell" data-theme={effectiveTheme(settings)}>
      <header className="topbar"><div><div className="brand">AttentionOS</div><div className="subtle">{t.subtitle}</div></div><div className="topbar-actions"><span className="privacy-pill">{t.localOnly}</span><button type="button" className="icon-button" onClick={() => refresh()} aria-label="Refresh">R</button><button type="button" className="button ghost" onClick={() => setNotificationsOpen(true)}>{t.notifications}{unreadCount > 0 && <span className="badge">{unreadCount}</span>}</button><button type="button" className="button ghost" onClick={() => setSettingsOpen(true)}>{t.settings}</button></div></header>
      {error && <div className="error">Could not load AttentionOS data: {error}</div>}
      <section className="tracking-card"><div className="tracking-status"><span className={tracking ? 'pulse-dot active' : 'pulse-dot'} /><strong>{tracking ? t.tracking : t.stopped}</strong></div><label className="task-select"><span>{t.currentTask}</span><select value={settings?.preferences.current_task_label ?? 'None'} onChange={(e) => setCurrentTask(e.target.value)}>{taskOptions.map((task) => <option value={task} key={task}>{task}</option>)}</select></label><div className="inline-input task-add"><input value={customTask} onChange={(e) => setCustomTask(e.target.value)} placeholder={t.addTask} /><button type="button" onClick={addTask}>{t.actions.add}</button></div><button type="button" className={`button ${tracking ? 'danger' : 'primary'}`} onClick={toggleTracking}>{tracking ? t.stopTracking : t.startTracking}</button><button type="button" className="button" onClick={() => setSelfReportOpen(true)}>{t.checkIn}</button></section>
      <section className="hero-grid"><article className="state-card"><div className="eyebrow">{translateMetric(dashboard?.current_state.label ?? t.currentState, lang(settings))}</div><h1>{loading ? t.loading : translateState(dashboard?.current_state.value ?? '-', lang(settings))}</h1><p>{translateMetricDetail(dashboard?.current_state.detail ?? '', lang(settings))}</p><div className="state-meta"><span>{formatDate(date, lang(settings))}</span><span>{dashboard?.event_count ?? 0} {lang(settings) === 'ru' ? '\u0441\u043e\u0431\u044b\u0442\u0438\u0439' : 'events'}</span></div></article><div className="metrics-grid">{(dashboard?.metrics ?? []).map((m) => <article className="metric-card" key={m.label}><div className="metric-label">{translateMetric(m.label, lang(settings))}</div><div className="metric-value">{m.value}</div><div className="metric-detail">{translateMetricDetail(m.detail, lang(settings))}</div></article>)}</div></section>
      <section className="panel timeline-panel"><div className="panel-header"><div><h2>{t.timeline}</h2><p>{t.timelineHint}</p></div><div className="date-nav"><button type="button" onClick={() => setDate(shiftDate(date, -1))}>{'<'}</button><span>{date === todayIso() ? t.today : formatDate(date, lang(settings))}</span><button type="button" onClick={() => setDate(shiftDate(date, 1))}>{'>'}</button></div></div>{dashboard && dashboard.timeline.length > 0 ? <div className="timeline"><div className="timeline-track">{dashboard.timeline.map((segment, index) => { const dayStart = 9 * 60; const dayEnd = 18 * 60; const start = Math.max(segment.start_minute, dayStart); const end = Math.min(segment.end_minute, dayEnd); if (end <= dayStart || start >= dayEnd) return null; const left = ((start - dayStart) / (dayEnd - dayStart)) * 100; const width = Math.max(((end - start) / (dayEnd - dayStart)) * 100, 0.8); const selected = selectedSegment?.app === segment.app && selectedSegment?.start_minute === segment.start_minute; return <button type="button" className={`timeline-segment ${selected ? 'selected' : ''}`} key={`${segment.app}-${segment.start_minute}-${index}`} style={{ left: `${left}%`, width: `${width}%`, background: appColor.get(segment.app) }} title={`${segment.app} - ${formatMinutes(segment.duration_minutes)}`} onClick={() => setSelectedSegment(segment)} onMouseEnter={() => setSelectedSegment(segment)} /> })}</div><div className="timeline-axis"><span>09:00</span><span>12:00</span><span>15:00</span><span>18:00</span></div>{selectedSegment && <div className="timeline-detail"><strong>{selectedSegment.app}</strong><span>{formatClock(selectedSegment.start_minute)}-{formatClock(selectedSegment.end_minute)}</span><span>{formatMinutes(selectedSegment.duration_minutes)}</span><span>{t.task}: {selectedSegment.task ?? t.unassigned}</span></div>}</div> : <div className="empty-state"><h3>{t.noData}</h3><p>{t.noDataText}</p></div>}</section>
      <section className="analytics-grid"><article className="panel"><div className="panel-header"><div><h2>{t.activityPattern}</h2><p>{lang(settings) === 'ru' ? '\u0424\u043e\u043a\u0443\u0441 \u0438 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f.' : 'Focused vs active minutes.'}</p></div></div><div className="bar-comparison"><Bar label="Focused" value={dashboard?.focused_minutes ?? 0} max={dashboard?.active_minutes ?? 1} lang={lang(settings)} /><Bar label="Active" value={dashboard?.active_minutes ?? 0} max={dashboard?.active_minutes ?? 1} lang={lang(settings)} /><Bar label="Switches" value={dashboard?.context_switches ?? 0} max={Math.max(dashboard?.context_switches ?? 0, 40)} lang={lang(settings)} /></div></article><article className="panel"><div className="panel-header"><div><h2>{t.topApps}</h2><p>{lang(settings) === 'ru' ? '\u041f\u043e \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u043c\u0443 \u0432\u0440\u0435\u043c\u0435\u043d\u0438.' : 'Ranked by active foreground time.'}</p></div></div><div className="app-list">{(dashboard?.top_apps ?? []).length > 0 ? dashboard?.top_apps.map((app, index) => <div className="app-row" key={app.name}><span className="rank">{index + 1}</span><span className="app-name">{app.name}</span><span>{formatMinutes(app.duration_minutes)}</span><div className="progress"><span style={{ width: `${app.percent}%` }} /></div></div>) : <p className="muted">{t.noAppUsage}</p>}</div></article></section>
      <section className="panel"><div className="panel-header"><div><h2>{t.recentSessions}</h2><p>{lang(settings) === 'ru' ? '\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0431\u043b\u043e\u043a\u0438 \u0440\u0430\u0431\u043e\u0442\u044b.' : 'Latest foreground work blocks.'}</p></div><span className="muted">SQLite: {dashboard?.db_path}</span></div><div className="sessions-table"><div className="table-head"><span>{t.time}</span><span>{t.app}</span><span>{t.duration}</span><span>{t.task}</span></div>{(dashboard?.recent_sessions ?? []).map((s) => <div className="table-row" key={`${s.time}-${s.application}-${s.duration_minutes}`}><span>{s.time}</span><span>{s.application}</span><span>{formatMinutes(s.duration_minutes)}</span><span>{s.task ?? t.unassigned}</span></div>)}</div></section>
      {notificationsOpen && <NotificationsDrawer notifications={notifications} markRead={markRead} close={() => setNotificationsOpen(false)} t={t} />}
      {settingsOpen && settings && <SettingsModal dashboard={dashboard} settings={settings} unreadCount={unreadCount} ui={t} onClose={() => setSettingsOpen(false)} onTestNotification={sendTestNotification} onSave={async (next) => { await saveRuntimeSettings(next); setSettingsOpen(false); await refresh() }} />}
      {selfReportOpen && settings && <SelfReportModal settings={settings} ui={t} onClose={() => setSelfReportOpen(false)} onSaved={async () => { setSelfReportOpen(false); await refresh() }} />}
    </main>
  )
}

function NotificationsDrawer({ notifications, markRead, close, t }: { notifications: NotificationPayload[]; markRead: (id: number) => void; close: () => void; t: UiText }) {
  const language = t === ru ? 'ru' : 'en'
  return <aside className="drawer"><div className="drawer-backdrop" onClick={close} /><div className="drawer-panel"><div className="panel-header"><div><h2>{t.notifications}</h2><p>{t.notificationHint}</p></div><button type="button" className="icon-button" onClick={close}>x</button></div>{notifications.length > 0 ? notifications.map((item) => <button type="button" className="notification" key={item.id} onClick={() => markRead(item.id)}><span className={item.state === 'unread' ? 'dot active' : 'dot'} /><strong>{localizeNotificationTitle(item.title, language)}</strong><p>{localizeNotificationBody(item.body, language)}</p><small>{localizeNotificationMeta(item.kind, item.state, language)}</small></button>) : <div className="empty-state compact"><h3>{t.noNotifications}</h3><p>{t.notificationEmptyText}</p></div>}</div></aside>
}

function Bar({ label, value, max, lang }: { label: string; value: number; max: number; lang: 'en' | 'ru' }) {
  return <div className="bar-row"><div><span>{translateMetric(label, lang)}</span><strong>{label === 'Switches' ? value : formatMinutes(value)}</strong></div><div className="bar-track"><span style={{ width: `${Math.min((value / Math.max(max, 1)) * 100, 100)}%` }} /></div></div>
}

function SettingsModal({ dashboard, settings, unreadCount, ui, onClose, onTestNotification, onSave }: { dashboard: DashboardPayload | null; settings: RuntimeSettings; unreadCount: number; ui: UiText; onClose: () => void; onTestNotification: () => Promise<void>; onSave: (settings: RuntimeSettings) => Promise<void> }) {
  const [tab, setTab] = useState('general')
  const [draft, setDraft] = useState<RuntimeSettings>(structuredClone(settings))
  const [excludedInput, setExcludedInput] = useState('')
  const [status, setStatus] = useState('')
  const update = (next: RuntimeSettings) => setDraft(structuredClone(next))
  const setPreference = <K extends keyof RuntimeSettings['preferences']>(key: K, value: RuntimeSettings['preferences'][K]) => update({ ...draft, preferences: { ...draft.preferences, [key]: value } })
  const setTracking = <K extends keyof RuntimeSettings['tracking']>(key: K, value: RuntimeSettings['tracking'][K]) => update({ ...draft, tracking: { ...draft.tracking, [key]: value } })
  const setNotifications = <K extends keyof RuntimeSettings['notifications']>(key: K, value: RuntimeSettings['notifications'][K]) => update({ ...draft, notifications: { ...draft.notifications, [key]: value } })
  const tabs = ['general', 'tracking', 'notifications', 'privacy', 'model']
  return <aside className="modal-layer"><div className="modal-backdrop" onClick={onClose} /><section className="settings-modal"><div className="settings-titlebar"><div><h2>{ui.settings}</h2><p>{ui.settingsSubtitle}</p></div><button type="button" className="icon-button" onClick={onClose}>x</button></div><div className="settings-tabs">{tabs.map((item) => <button type="button" className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>{ui.tabs[item as keyof typeof ui.tabs]}</button>)}</div><div className="settings-body">
    {tab === 'general' && <div className="settings-form"><Select label={ui.labels.language} value={draft.preferences.language} options={['system', 'en', 'ru']} optionLabel={(v) => v === 'system' ? ui.values.system : v.toUpperCase()} onChange={(v) => setPreference('language', v)} /><Select label={ui.labels.theme} value={draft.preferences.theme} options={['system', 'light', 'dark']} optionLabel={(v) => ({ system: ui.values.system, light: ui.values.light, dark: ui.values.dark }[v] ?? v)} onChange={(v) => setPreference('theme', v)} /><Checkbox label={ui.labels.launch} checked={draft.preferences.launch_on_startup} onChange={(v) => setPreference('launch_on_startup', v)} /><Checkbox label={ui.labels.tray} checked={draft.preferences.minimize_to_tray} onChange={(v) => setPreference('minimize_to_tray', v)} /><Checkbox label={ui.labels.minimized} checked={draft.preferences.start_minimized} onChange={(v) => setPreference('start_minimized', v)} /></div>}
    {tab === 'tracking' && <div className="settings-form"><NumberInput label={ui.labels.idle} min={1} max={30} value={draft.tracking.idle_threshold_minutes} onChange={(v) => setTracking('idle_threshold_minutes', v)} /><Checkbox label={ui.labels.activeWindow} checked={draft.tracking.track_active_window} onChange={(v) => setTracking('track_active_window', v)} /><Checkbox label={ui.labels.windowTitles} checked={draft.tracking.track_window_titles} onChange={(v) => setTracking('track_window_titles', v)} /><Checkbox label={ui.labels.keyboard} checked={draft.tracking.track_keyboard_activity} onChange={(v) => setTracking('track_keyboard_activity', v)} /><Checkbox label={ui.labels.mouse} checked={draft.tracking.track_mouse_activity} onChange={(v) => setTracking('track_mouse_activity', v)} /><div className="field full"><label>{ui.labels.excluded}</label><div className="excluded-list">{draft.tracking.excluded_applications.length === 0 && <span className="empty-chip">{ui.labels.noExcluded}</span>}{draft.tracking.excluded_applications.map((item) => <button type="button" key={item} onClick={() => setTracking('excluded_applications', draft.tracking.excluded_applications.filter((entry) => entry !== item))}>{item} x</button>)}</div><div className="inline-input"><input value={excludedInput} onChange={(e) => setExcludedInput(e.target.value)} placeholder="example.exe" /><button type="button" onClick={() => { const value = excludedInput.trim(); if (!value) return; setTracking('excluded_applications', [...draft.tracking.excluded_applications, value]); setExcludedInput('') }}>{ui.actions.add}</button></div></div></div>}
    {tab === 'notifications' && <div className="settings-form"><Checkbox label={ui.labels.breakRecommendations} checked={draft.notifications.break_recommendations} onChange={(v) => setNotifications('break_recommendations', v)} /><Checkbox label={ui.labels.performanceWarnings} checked={draft.notifications.performance_warnings} onChange={(v) => setNotifications('performance_warnings', v)} /><Select label={ui.labels.minInterval} value={String(draft.notifications.minimum_interval_minutes)} options={['15', '30', '45', '60']} onChange={(v) => setNotifications('minimum_interval_minutes', Number(v))} /><NumberInput label={ui.labels.liveInterval} min={60} max={300} value={draft.notifications.live_check_interval_seconds} onChange={(v) => setNotifications('live_check_interval_seconds', v)} /><TextInput label={ui.labels.dndStart} value={draft.notifications.do_not_disturb_start} onChange={(v) => setNotifications('do_not_disturb_start', v)} /><TextInput label={ui.labels.dndEnd} value={draft.notifications.do_not_disturb_end} onChange={(v) => setNotifications('do_not_disturb_end', v)} /><SettingRow label={ui.labels.unread} value={String(unreadCount)} /><button type="button" className="button primary" onClick={onTestNotification}>{ui.actions.testNotification}</button></div>}
    {tab === 'privacy' && <div className="settings-form"><SettingRow label={ui.labels.database} value={dashboard?.db_path ?? '-'} /><SettingRow label={ui.labels.storage} value={ui.values.localSqlite} /><SettingRow label={ui.labels.typedText} value={ui.values.never} /><SettingRow label={ui.labels.screenshots} value={ui.values.never} /><SettingRow label={ui.labels.eventsLoaded} value={String(dashboard?.event_count ?? 0)} /><div className="danger-grid"><ActionButton label={ui.actions.exportData} command="export_data" onDone={(m) => setStatus(`${ui.exported}: ${m}`)} /><ActionButton label={ui.actions.deleteTelemetry} command="delete_telemetry" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteTelemetry}`)} /><ActionButton label={ui.actions.deleteReports} command="delete_self_reports" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteReports}`)} /><ActionButton label={ui.actions.deleteInterventions} command="delete_interventions" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteInterventions}`)} /><ActionButton label={ui.actions.deleteModel} command="delete_model" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteModel}`)} /><ActionButton label={ui.actions.deleteAll} command="delete_all_data" danger onDone={() => setStatus(`${ui.deleted}: ${ui.actions.deleteAll}`)} /></div>{status && <p className="settings-status">{status}</p>}</div>}
    {tab === 'model' && <div className="settings-form"><NumberInput label={ui.labels.modelSamples} min={5} max={500} value={draft.model.min_training_samples} onChange={(v) => update({ ...draft, model: { min_training_samples: v } })} /><SettingRow label={ui.labels.personalModel} value={ui.values.collecting} /><SettingRow label={ui.labels.trainingUi} value={ui.values.trainingLater} /></div>}
  </div><div className="settings-actions"><button type="button" className="button" onClick={onClose}>{ui.close}</button><button type="button" className="button primary" onClick={() => onSave(draft)}>{ui.save}</button></div></section></aside>
}

function ActionButton({ label, command, danger, onDone }: { label: string; command: string; danger?: boolean; onDone: (message: string) => void }) { return <button type="button" className={`button ${danger ? 'danger' : ''}`} onClick={async () => { if (danger && !window.confirm(`${label}?`)) return; const result = await invoke<string | null>(command); onDone(result ?? '') }}>{label}</button> }
function SettingRow({ label, value }: { label: string; value: string }) { return <div className="setting-row"><span>{label}</span><strong>{value}</strong></div> }
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
function translateMetric(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'Focused time': '\u0412\u0440\u0435\u043c\u044f \u0444\u043e\u043a\u0443\u0441\u0430', 'Active time': '\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f', 'Context switches': '\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f', 'Input events': '\u0421\u043e\u0431\u044b\u0442\u0438\u044f \u0432\u0432\u043e\u0434\u0430', 'Current state': '\u0422\u0435\u043a\u0443\u0449\u0435\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435' } as Record<string, string>)[value] ?? value }
function translateMetricDetail(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'Non-idle work outside common distractions': '\u0410\u043a\u0442\u0438\u0432\u043d\u0430\u044f \u0440\u0430\u0431\u043e\u0442\u0430 \u0432\u043d\u0435 \u043e\u0442\u0432\u043b\u0435\u0447\u0435\u043d\u0438\u0439', 'Keyboard, mouse, and foreground activity': '\u041a\u043b\u0430\u0432\u0438\u0430\u0442\u0443\u0440\u0430, \u043c\u044b\u0448\u044c \u0438 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u043e\u043a\u043d\u043e', 'Foreground app changes': '\u0421\u043c\u0435\u043d\u044b \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e \u043e\u043a\u043d\u0430', 'Aggregate counts, no typed text': '\u0422\u043e\u043b\u044c\u043a\u043e \u0441\u0447\u0451\u0442\u0447\u0438\u043a\u0438, \u0431\u0435\u0437 \u0442\u0435\u043a\u0441\u0442\u0430', 'Derived from local telemetry only': '\u0420\u0430\u0441\u0441\u0447\u0438\u0442\u0430\u043d\u043e \u0438\u0437 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0439 \u0442\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u0438' } as Record<string, string>)[value] ?? value }
function translateState(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'No data yet': '\u0414\u0430\u043d\u043d\u044b\u0445 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442', 'Deep work': '\u0413\u043b\u0443\u0431\u043e\u043a\u0430\u044f \u0440\u0430\u0431\u043e\u0442\u0430', Working: '\u0420\u0430\u0431\u043e\u0442\u0430', 'Warming up': '\u0420\u0430\u0437\u0433\u043e\u043d' } as Record<string, string>)[value] ?? value }
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

export default App
