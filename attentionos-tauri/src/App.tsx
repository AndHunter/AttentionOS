import { useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
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
}
const en = {
  subtitle: 'Local-first focus analytics', localOnly: 'Local only', notifications: 'Notifications', settings: 'Settings',
  currentState: 'Current state', timeline: 'Timeline', timelineHint: '09:00-18:00 workday view from local telemetry.',
  today: 'Today', noData: 'No focus data yet', noDataText: 'Start tracking and AttentionOS will build your timeline.',
  activityPattern: 'Activity Pattern', topApps: 'Top Apps', recentSessions: 'Recent Sessions', time: 'Time', app: 'Application',
  duration: 'Duration', task: 'Task', currentTask: 'Current task', addTask: 'Add', startTracking: 'Start tracking',
  stopTracking: 'Stop', tracking: 'Tracking', stopped: 'Stopped', checkIn: 'Check in', save: 'Save', close: 'Close',
  exported: 'Exported', deleted: 'Deleted',
}

function lang(settings: RuntimeSettings | null): 'en' | 'ru' { return settings?.preferences.language === 'ru' ? 'ru' : 'en' }
function tx(settings: RuntimeSettings | null) { return lang(settings) === 'ru' ? ru : en }
function todayIso() { return new Date().toISOString().slice(0, 10) }
function shiftDate(value: string, days: number) { const date = new Date(`${value}T12:00:00`); date.setDate(date.getDate() + days); return date.toISOString().slice(0, 10) }
function formatDate(value: string) { return new Intl.DateTimeFormat('en', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(`${value}T12:00:00`)) }
function formatMinutes(minutes: number) { const h = Math.floor(minutes / 60); const m = minutes % 60; return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m` }
function formatClock(minute: number) { return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}` }
function effectiveTheme(settings: RuntimeSettings | null) { return !settings || settings.preferences.theme === 'system' ? 'light' : settings.preferences.theme }

function App() {
  const [date, setDate] = useState(todayIso())
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [notifications, setNotifications] = useState<NotificationPayload[]>([])
  const [settings, setSettings] = useState<RuntimeSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [selectedSegment, setSelectedSegment] = useState<TimelineSegment | null>(null)
  const [tracking, setTracking] = useState(false)
  const [customTask, setCustomTask] = useState('')
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
  const unreadCount = notifications.filter((item) => item.state === 'unread').length
  const appColor = useMemo(() => { const map = new Map<string, string>(); dashboard?.timeline.forEach((s) => { if (!map.has(s.app)) map.set(s.app, palette[map.size % palette.length]) }); return map }, [dashboard?.timeline])
  const taskOptions = useMemo(() => Array.from(new Set(['None', ...defaultTasks, ...(settings?.preferences.current_task_label && settings.preferences.current_task_label !== 'None' ? [settings.preferences.current_task_label] : [])])), [settings?.preferences.current_task_label])

  async function saveRuntimeSettings(next: RuntimeSettings) { await invoke('save_settings', { settings: next }); setSettings(next) }
  async function setCurrentTask(task: string) { if (!settings) return; await saveRuntimeSettings({ ...settings, preferences: { ...settings.preferences, current_task_label: task } }) }
  async function addTask() { const task = customTask.trim(); if (!task) return; await setCurrentTask(task); setCustomTask('') }
  async function toggleTracking() { if (tracking) { await invoke('stop_tracking'); setTracking(false) } else { if (settings) await saveRuntimeSettings(settings); await invoke('start_tracking'); setTracking(true) } await refresh() }
  async function markRead(id: number) { await invoke('mark_notification_read', { id }); await refresh() }

  return (
    <main className="shell" data-theme={effectiveTheme(settings)}>
      <header className="topbar"><div><div className="brand">AttentionOS</div><div className="subtle">{t.subtitle}</div></div><div className="topbar-actions"><span className="privacy-pill">{t.localOnly}</span><button type="button" className="icon-button" onClick={() => refresh()} aria-label="Refresh">R</button><button type="button" className="button ghost" onClick={() => setNotificationsOpen(true)}>{t.notifications}{unreadCount > 0 && <span className="badge">{unreadCount}</span>}</button><button type="button" className="button ghost" onClick={() => setSettingsOpen(true)}>{t.settings}</button></div></header>
      {error && <div className="error">Could not load AttentionOS data: {error}</div>}
      <section className="tracking-card"><div className="tracking-status"><span className={tracking ? 'pulse-dot active' : 'pulse-dot'} /><strong>{tracking ? t.tracking : t.stopped}</strong></div><label className="task-select"><span>{t.currentTask}</span><select value={settings?.preferences.current_task_label ?? 'None'} onChange={(e) => setCurrentTask(e.target.value)}>{taskOptions.map((task) => <option value={task} key={task}>{task}</option>)}</select></label><div className="inline-input task-add"><input value={customTask} onChange={(e) => setCustomTask(e.target.value)} placeholder={t.addTask} /><button type="button" onClick={addTask}>{t.addTask}</button></div><button type="button" className={`button ${tracking ? 'danger' : 'primary'}`} onClick={toggleTracking}>{tracking ? t.stopTracking : t.startTracking}</button><button type="button" className="button" onClick={() => setSettingsOpen(true)}>{t.checkIn}</button></section>
      <section className="hero-grid"><article className="state-card"><div className="eyebrow">{translateMetric(dashboard?.current_state.label ?? t.currentState, lang(settings))}</div><h1>{loading ? 'Loading' : dashboard?.current_state.value}</h1><p>{translateMetricDetail(dashboard?.current_state.detail ?? '', lang(settings))}</p><div className="state-meta"><span>{formatDate(date)}</span><span>{dashboard?.event_count ?? 0} events</span></div></article><div className="metrics-grid">{(dashboard?.metrics ?? []).map((m) => <article className="metric-card" key={m.label}><div className="metric-label">{translateMetric(m.label, lang(settings))}</div><div className="metric-value">{m.value}</div><div className="metric-detail">{translateMetricDetail(m.detail, lang(settings))}</div></article>)}</div></section>
      <section className="panel timeline-panel"><div className="panel-header"><div><h2>{t.timeline}</h2><p>{t.timelineHint}</p></div><div className="date-nav"><button type="button" onClick={() => setDate(shiftDate(date, -1))}>{'<'}</button><span>{date === todayIso() ? t.today : formatDate(date)}</span><button type="button" onClick={() => setDate(shiftDate(date, 1))}>{'>'}</button></div></div>{dashboard && dashboard.timeline.length > 0 ? <div className="timeline"><div className="timeline-track">{dashboard.timeline.map((segment, index) => { const dayStart = 9 * 60; const dayEnd = 18 * 60; const start = Math.max(segment.start_minute, dayStart); const end = Math.min(segment.end_minute, dayEnd); if (end <= dayStart || start >= dayEnd) return null; const left = ((start - dayStart) / (dayEnd - dayStart)) * 100; const width = Math.max(((end - start) / (dayEnd - dayStart)) * 100, 0.8); const selected = selectedSegment?.app === segment.app && selectedSegment?.start_minute === segment.start_minute; return <button type="button" className={`timeline-segment ${selected ? 'selected' : ''}`} key={`${segment.app}-${segment.start_minute}-${index}`} style={{ left: `${left}%`, width: `${width}%`, background: appColor.get(segment.app) }} title={`${segment.app} - ${formatMinutes(segment.duration_minutes)}`} onClick={() => setSelectedSegment(segment)} onMouseEnter={() => setSelectedSegment(segment)} /> })}</div><div className="timeline-axis"><span>09:00</span><span>12:00</span><span>15:00</span><span>18:00</span></div>{selectedSegment && <div className="timeline-detail"><strong>{selectedSegment.app}</strong><span>{formatClock(selectedSegment.start_minute)}-{formatClock(selectedSegment.end_minute)}</span><span>{formatMinutes(selectedSegment.duration_minutes)}</span><span>{t.task}: {selectedSegment.task ?? 'Unassigned'}</span></div>}</div> : <div className="empty-state"><h3>{t.noData}</h3><p>{t.noDataText}</p></div>}</section>
      <section className="analytics-grid"><article className="panel"><div className="panel-header"><div><h2>{t.activityPattern}</h2><p>{lang(settings) === 'ru' ? '\u0424\u043e\u043a\u0443\u0441 \u0438 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f.' : 'Focused vs active minutes.'}</p></div></div><div className="bar-comparison"><Bar label="Focused" value={dashboard?.focused_minutes ?? 0} max={dashboard?.active_minutes ?? 1} lang={lang(settings)} /><Bar label="Active" value={dashboard?.active_minutes ?? 0} max={dashboard?.active_minutes ?? 1} lang={lang(settings)} /><Bar label="Switches" value={dashboard?.context_switches ?? 0} max={Math.max(dashboard?.context_switches ?? 0, 40)} lang={lang(settings)} /></div></article><article className="panel"><div className="panel-header"><div><h2>{t.topApps}</h2><p>{lang(settings) === 'ru' ? '\u041f\u043e \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u043c\u0443 \u0432\u0440\u0435\u043c\u0435\u043d\u0438.' : 'Ranked by active foreground time.'}</p></div></div><div className="app-list">{(dashboard?.top_apps ?? []).length > 0 ? dashboard?.top_apps.map((app, index) => <div className="app-row" key={app.name}><span className="rank">{index + 1}</span><span className="app-name">{app.name}</span><span>{formatMinutes(app.duration_minutes)}</span><div className="progress"><span style={{ width: `${app.percent}%` }} /></div></div>) : <p className="muted">No app usage yet.</p>}</div></article></section>
      <section className="panel"><div className="panel-header"><div><h2>{t.recentSessions}</h2><p>{lang(settings) === 'ru' ? '\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0431\u043b\u043e\u043a\u0438 \u0440\u0430\u0431\u043e\u0442\u044b.' : 'Latest foreground work blocks.'}</p></div><span className="muted">SQLite: {dashboard?.db_path}</span></div><div className="sessions-table"><div className="table-head"><span>{t.time}</span><span>{t.app}</span><span>{t.duration}</span><span>{t.task}</span></div>{(dashboard?.recent_sessions ?? []).map((s) => <div className="table-row" key={`${s.time}-${s.application}-${s.duration_minutes}`}><span>{s.time}</span><span>{s.application}</span><span>{formatMinutes(s.duration_minutes)}</span><span>{s.task ?? 'Unassigned'}</span></div>)}</div></section>
      {notificationsOpen && <NotificationsDrawer notifications={notifications} markRead={markRead} close={() => setNotificationsOpen(false)} t={t} />}
      {settingsOpen && settings && <SettingsModal dashboard={dashboard} settings={settings} unreadCount={unreadCount} ui={t} onClose={() => setSettingsOpen(false)} onSave={async (next) => { await saveRuntimeSettings(next); setSettingsOpen(false); await refresh() }} />}
    </main>
  )
}

function NotificationsDrawer({ notifications, markRead, close, t }: { notifications: NotificationPayload[]; markRead: (id: number) => void; close: () => void; t: typeof en }) {
  return <aside className="drawer"><div className="drawer-backdrop" onClick={close} /><div className="drawer-panel"><div className="panel-header"><div><h2>{t.notifications}</h2><p>Break recommendations and system notes.</p></div><button type="button" className="icon-button" onClick={close}>x</button></div>{notifications.length > 0 ? notifications.map((item) => <button type="button" className="notification" key={item.id} onClick={() => markRead(item.id)}><span className={item.state === 'unread' ? 'dot active' : 'dot'} /><strong>{item.title}</strong><p>{item.body}</p><small>{item.kind} - {item.state}</small></button>) : <div className="empty-state compact"><h3>No notifications</h3><p>Break recommendations will appear here.</p></div>}</div></aside>
}

function Bar({ label, value, max, lang }: { label: string; value: number; max: number; lang: 'en' | 'ru' }) {
  return <div className="bar-row"><div><span>{translateMetric(label, lang)}</span><strong>{label === 'Switches' ? value : formatMinutes(value)}</strong></div><div className="bar-track"><span style={{ width: `${Math.min((value / Math.max(max, 1)) * 100, 100)}%` }} /></div></div>
}

function SettingsModal({ dashboard, settings, unreadCount, ui, onClose, onSave }: { dashboard: DashboardPayload | null; settings: RuntimeSettings; unreadCount: number; ui: typeof en; onClose: () => void; onSave: (settings: RuntimeSettings) => Promise<void> }) {
  const [tab, setTab] = useState('general')
  const [draft, setDraft] = useState<RuntimeSettings>(structuredClone(settings))
  const [excludedInput, setExcludedInput] = useState('')
  const [status, setStatus] = useState('')
  const update = (next: RuntimeSettings) => setDraft(structuredClone(next))
  const setPreference = <K extends keyof RuntimeSettings['preferences']>(key: K, value: RuntimeSettings['preferences'][K]) => update({ ...draft, preferences: { ...draft.preferences, [key]: value } })
  const setTracking = <K extends keyof RuntimeSettings['tracking']>(key: K, value: RuntimeSettings['tracking'][K]) => update({ ...draft, tracking: { ...draft.tracking, [key]: value } })
  const setNotifications = <K extends keyof RuntimeSettings['notifications']>(key: K, value: RuntimeSettings['notifications'][K]) => update({ ...draft, notifications: { ...draft.notifications, [key]: value } })
  const tabs = ['general', 'tracking', 'notifications', 'privacy', 'model']
  return <aside className="modal-layer"><div className="modal-backdrop" onClick={onClose} /><section className="settings-modal"><div className="settings-titlebar"><div><h2>{ui.settings}</h2><p>Editable runtime preferences used by the collector.</p></div><button type="button" className="icon-button" onClick={onClose}>x</button></div><div className="settings-tabs">{tabs.map((item) => <button type="button" className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>{item}</button>)}</div><div className="settings-body">
    {tab === 'general' && <div className="settings-form"><Select label="Language" value={draft.preferences.language} options={['system', 'en', 'ru']} onChange={(v) => setPreference('language', v)} /><Select label="Theme" value={draft.preferences.theme} options={['system', 'light', 'dark']} onChange={(v) => setPreference('theme', v)} /><Checkbox label="Launch on startup" checked={draft.preferences.launch_on_startup} onChange={(v) => setPreference('launch_on_startup', v)} /><Checkbox label="Minimize to tray" checked={draft.preferences.minimize_to_tray} onChange={(v) => setPreference('minimize_to_tray', v)} /><Checkbox label="Start minimized" checked={draft.preferences.start_minimized} onChange={(v) => setPreference('start_minimized', v)} /></div>}
    {tab === 'tracking' && <div className="settings-form"><NumberInput label="Idle threshold, minutes" min={1} max={30} value={draft.tracking.idle_threshold_minutes} onChange={(v) => setTracking('idle_threshold_minutes', v)} /><Checkbox label="Track active window" checked={draft.tracking.track_active_window} onChange={(v) => setTracking('track_active_window', v)} /><Checkbox label="Track window titles" checked={draft.tracking.track_window_titles} onChange={(v) => setTracking('track_window_titles', v)} /><Checkbox label="Track keyboard activity" checked={draft.tracking.track_keyboard_activity} onChange={(v) => setTracking('track_keyboard_activity', v)} /><Checkbox label="Track mouse activity" checked={draft.tracking.track_mouse_activity} onChange={(v) => setTracking('track_mouse_activity', v)} /><div className="field full"><label>Excluded applications</label><div className="excluded-list">{draft.tracking.excluded_applications.length === 0 && <span className="empty-chip">No excluded apps</span>}{draft.tracking.excluded_applications.map((item) => <button type="button" key={item} onClick={() => setTracking('excluded_applications', draft.tracking.excluded_applications.filter((entry) => entry !== item))}>{item} x</button>)}</div><div className="inline-input"><input value={excludedInput} onChange={(e) => setExcludedInput(e.target.value)} placeholder="example.exe" /><button type="button" onClick={() => { const value = excludedInput.trim(); if (!value) return; setTracking('excluded_applications', [...draft.tracking.excluded_applications, value]); setExcludedInput('') }}>Add</button></div></div></div>}
    {tab === 'notifications' && <div className="settings-form"><Checkbox label="Break recommendations" checked={draft.notifications.break_recommendations} onChange={(v) => setNotifications('break_recommendations', v)} /><Checkbox label="Performance warnings" checked={draft.notifications.performance_warnings} onChange={(v) => setNotifications('performance_warnings', v)} /><Select label="Minimum interval, minutes" value={String(draft.notifications.minimum_interval_minutes)} options={['15', '30', '45', '60']} onChange={(v) => setNotifications('minimum_interval_minutes', Number(v))} /><NumberInput label="Live check interval, seconds" min={30} max={300} value={draft.notifications.live_check_interval_seconds} onChange={(v) => setNotifications('live_check_interval_seconds', v)} /><TextInput label="Do not disturb start" value={draft.notifications.do_not_disturb_start} onChange={(v) => setNotifications('do_not_disturb_start', v)} /><TextInput label="Do not disturb end" value={draft.notifications.do_not_disturb_end} onChange={(v) => setNotifications('do_not_disturb_end', v)} /><SettingRow label="Unread notifications" value={String(unreadCount)} /></div>}
    {tab === 'privacy' && <div className="settings-form"><SettingRow label="Database" value={dashboard?.db_path ?? 'Not loaded'} /><SettingRow label="Data storage" value="Local SQLite only" /><SettingRow label="Typed text" value="Never recorded" /><SettingRow label="Screenshots" value="Never recorded" /><SettingRow label="Events loaded" value={String(dashboard?.event_count ?? 0)} /><div className="danger-grid"><ActionButton label="Export data" command="export_data" onDone={(m) => setStatus(`${ui.exported}: ${m}`)} /><ActionButton label="Delete telemetry" command="delete_telemetry" danger onDone={() => setStatus(`${ui.deleted}: telemetry`)} /><ActionButton label="Delete self reports" command="delete_self_reports" danger onDone={() => setStatus(`${ui.deleted}: self reports`)} /><ActionButton label="Delete interventions" command="delete_interventions" danger onDone={() => setStatus(`${ui.deleted}: interventions`)} /><ActionButton label="Delete model" command="delete_model" danger onDone={() => setStatus(`${ui.deleted}: model`)} /><ActionButton label="Delete all local data" command="delete_all_data" danger onDone={() => setStatus(`${ui.deleted}: all local data`)} /></div>{status && <p className="settings-status">{status}</p>}</div>}
    {tab === 'model' && <div className="settings-form"><NumberInput label="Minimum training samples" min={5} max={500} value={draft.model.min_training_samples} onChange={(v) => update({ ...draft, model: { min_training_samples: v } })} /><SettingRow label="Personal model" value="Collecting data" /><SettingRow label="Training UI" value="Unavailable until enough self-reports exist" /></div>}
  </div><div className="settings-actions"><button type="button" className="button" onClick={onClose}>{ui.close}</button><button type="button" className="button primary" onClick={() => onSave(draft)}>{ui.save}</button></div></section></aside>
}

function ActionButton({ label, command, danger, onDone }: { label: string; command: string; danger?: boolean; onDone: (message: string) => void }) { return <button type="button" className={`button ${danger ? 'danger' : ''}`} onClick={async () => { if (danger && !window.confirm(`${label}?`)) return; const result = await invoke<string | null>(command); onDone(result ?? '') }}>{label}</button> }
function SettingRow({ label, value }: { label: string; value: string }) { return <div className="setting-row"><span>{label}</span><strong>{value}</strong></div> }
function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) { return <label className="check-row"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /><span>{label}</span></label> }
function Select({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) { return <label className="field"><span>{label}</span><select value={value} onChange={(e) => onChange(e.target.value)}>{options.map((item) => <option value={item} key={item}>{item}</option>)}</select></label> }
function NumberInput({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) { return <label className="field"><span>{label}</span><input type="number" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} /></label> }
function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="field"><span>{label}</span><input value={value} onChange={(e) => onChange(e.target.value)} /></label> }
function translateMetric(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'Focused time': '\u0412\u0440\u0435\u043c\u044f \u0444\u043e\u043a\u0443\u0441\u0430', 'Active time': '\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f', 'Context switches': '\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f', 'Input events': '\u0421\u043e\u0431\u044b\u0442\u0438\u044f \u0432\u0432\u043e\u0434\u0430', 'Current state': '\u0422\u0435\u043a\u0443\u0449\u0435\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435' } as Record<string, string>)[value] ?? value }
function translateMetricDetail(value: string, language: 'en' | 'ru') { if (language !== 'ru') return value; return ({ 'Non-idle work outside common distractions': '\u0410\u043a\u0442\u0438\u0432\u043d\u0430\u044f \u0440\u0430\u0431\u043e\u0442\u0430 \u0432\u043d\u0435 \u043e\u0442\u0432\u043b\u0435\u0447\u0435\u043d\u0438\u0439', 'Keyboard, mouse, and foreground activity': '\u041a\u043b\u0430\u0432\u0438\u0430\u0442\u0443\u0440\u0430, \u043c\u044b\u0448\u044c \u0438 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u043e\u043a\u043d\u043e', 'Foreground app changes': '\u0421\u043c\u0435\u043d\u044b \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e \u043e\u043a\u043d\u0430', 'Aggregate counts, no typed text': '\u0422\u043e\u043b\u044c\u043a\u043e \u0441\u0447\u0451\u0442\u0447\u0438\u043a\u0438, \u0431\u0435\u0437 \u0442\u0435\u043a\u0441\u0442\u0430', 'Derived from local telemetry only': '\u0420\u0430\u0441\u0441\u0447\u0438\u0442\u0430\u043d\u043e \u0438\u0437 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0439 \u0442\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u0438' } as Record<string, string>)[value] ?? value }

export default App
