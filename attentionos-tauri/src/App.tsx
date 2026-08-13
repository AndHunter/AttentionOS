import { useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import './App.css'

type Metric = { label: string; value: string; detail: string }
type TimelineSegment = {
  app: string
  task?: string | null
  start_minute: number
  end_minute: number
  duration_minutes: number
}
type AppUsage = { name: string; duration_minutes: number; percent: number }
type RecentSession = {
  time: string
  application: string
  duration_minutes: number
  task?: string | null
}
type DashboardPayload = {
  date: string
  db_path: string
  has_data: boolean
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
type NotificationPayload = {
  id: number
  created_at: string
  title: string
  body: string
  state: string
  kind: string
}
type RuntimeSettings = {
  preferences: {
    language: string
    theme: string
    launch_on_startup: boolean
    minimize_to_tray: boolean
    start_minimized: boolean
    current_task_label: string
  }
  tracking: {
    idle_threshold_minutes: number
    track_active_window: boolean
    track_window_titles: boolean
    track_keyboard_activity: boolean
    track_mouse_activity: boolean
    excluded_applications: string[]
  }
  notifications: {
    break_recommendations: boolean
    performance_warnings: boolean
    minimum_interval_minutes: number
    live_check_interval_seconds: number
    do_not_disturb_start: string
    do_not_disturb_end: string
  }
  model: { min_training_samples: number }
}

const palette = ['#2F8F83', '#4D7EA8', '#7A6FBC', '#B8794A', '#4E937A', '#8C6A56', '#68758E']

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function shiftDate(value: string, days: number) {
  const date = new Date(`${value}T12:00:00`)
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(new Date(`${value}T12:00:00`))
}

function formatMinutes(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return hours > 0 ? `${hours}h ${mins.toString().padStart(2, '0')}m` : `${mins}m`
}

function formatClock(minute: number) {
  return `${Math.floor(minute / 60).toString().padStart(2, '0')}:${(minute % 60)
    .toString()
    .padStart(2, '0')}`
}

function effectiveTheme(settings: RuntimeSettings | null) {
  if (!settings || settings.preferences.theme === 'system') return 'light'
  return settings.preferences.theme
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
  const [selectedSegment, setSelectedSegment] = useState<TimelineSegment | null>(null)

  async function refresh(target = date) {
    setLoading(true)
    setError(null)
    try {
      const [nextDashboard, nextNotifications, nextSettings] = await Promise.all([
        invoke<DashboardPayload>('get_dashboard', { date: target }),
        invoke<NotificationPayload[]>('get_notifications', { limit: 8 }),
        invoke<RuntimeSettings>('get_settings'),
      ])
      setDashboard(nextDashboard)
      setNotifications(nextNotifications)
      setSettings(nextSettings)
      setSelectedSegment(nextDashboard.timeline.at(-1) ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh(date)
  }, [date])

  const unreadCount = notifications.filter((item) => item.state === 'unread').length
  const appColor = useMemo(() => {
    const map = new Map<string, string>()
    dashboard?.timeline.forEach((segment) => {
      if (!map.has(segment.app)) map.set(segment.app, palette[map.size % palette.length])
    })
    return map
  }, [dashboard?.timeline])

  async function markRead(id: number) {
    await invoke('mark_notification_read', { id })
    await refresh()
  }

  return (
    <main className="shell" data-theme={effectiveTheme(settings)}>
      <header className="topbar">
        <div>
          <div className="brand">AttentionOS</div>
          <div className="subtle">Local-first focus analytics</div>
        </div>
        <div className="topbar-actions">
          <span className="privacy-pill">Local only</span>
          <button type="button" className="icon-button" onClick={() => refresh()} aria-label="Refresh">
            R
          </button>
          <button type="button" className="button ghost" onClick={() => setNotificationsOpen(true)}>
            Notifications {unreadCount > 0 && <span className="badge">{unreadCount}</span>}
          </button>
          <button type="button" className="button ghost" onClick={() => setSettingsOpen(true)}>
            Settings
          </button>
        </div>
      </header>

      {error && <div className="error">Could not load AttentionOS data: {error}</div>}

      <section className="hero-grid">
        <article className="state-card">
          <div className="eyebrow">{dashboard?.current_state.label ?? 'Current state'}</div>
          <h1>{loading ? 'Loading' : dashboard?.current_state.value}</h1>
          <p>{dashboard?.current_state.detail ?? 'Reading local telemetry.'}</p>
          <div className="state-meta">
            <span>{formatDate(date)}</span>
            <span>{dashboard?.event_count ?? 0} events</span>
          </div>
        </article>

        <div className="metrics-grid">
          {(dashboard?.metrics ?? []).map((metric) => (
            <article className="metric-card" key={metric.label}>
              <div className="metric-label">{metric.label}</div>
              <div className="metric-value">{metric.value}</div>
              <div className="metric-detail">{metric.detail}</div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel timeline-panel">
        <div className="panel-header">
          <div>
            <h2>Timeline</h2>
            <p>09:00-18:00 workday view from local foreground telemetry.</p>
          </div>
          <div className="date-nav">
            <button type="button" onClick={() => setDate(shiftDate(date, -1))}>{'<'}</button>
            <span>{date === todayIso() ? 'Today' : formatDate(date)}</span>
            <button type="button" onClick={() => setDate(shiftDate(date, 1))}>{'>'}</button>
          </div>
        </div>

        {dashboard && dashboard.timeline.length > 0 ? (
          <div className="timeline">
            <div className="timeline-track">
              {dashboard.timeline.map((segment, index) => {
                const dayStart = 9 * 60
                const dayEnd = 18 * 60
                const start = Math.max(segment.start_minute, dayStart)
                const end = Math.min(segment.end_minute, dayEnd)
                if (end <= dayStart || start >= dayEnd) return null
                const left = ((start - dayStart) / (dayEnd - dayStart)) * 100
                const width = Math.max(((end - start) / (dayEnd - dayStart)) * 100, 0.8)
                const isSelected =
                  selectedSegment?.app === segment.app &&
                  selectedSegment?.start_minute === segment.start_minute
                return (
                  <button
                    type="button"
                    className={`timeline-segment ${isSelected ? 'selected' : ''}`}
                    key={`${segment.app}-${segment.start_minute}-${index}`}
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      background: appColor.get(segment.app),
                    }}
                    title={`${segment.app} - ${formatMinutes(segment.duration_minutes)}`}
                    onClick={() => setSelectedSegment(segment)}
                    onMouseEnter={() => setSelectedSegment(segment)}
                  />
                )
              })}
            </div>
            <div className="timeline-axis">
              <span>09:00</span>
              <span>12:00</span>
              <span>15:00</span>
              <span>18:00</span>
            </div>
            {selectedSegment && (
              <div className="timeline-detail">
                <strong>{selectedSegment.app}</strong>
                <span>
                  {formatClock(selectedSegment.start_minute)}-{formatClock(selectedSegment.end_minute)}
                </span>
                <span>{formatMinutes(selectedSegment.duration_minutes)}</span>
                <span>Task: {selectedSegment.task ?? 'Unassigned'}</span>
              </div>
            )}
          </div>
        ) : (
          <div className="empty-state">
            <h3>No focus data yet</h3>
            <p>Start tracking in AttentionOS and this timeline will fill with your real day.</p>
          </div>
        )}
      </section>

      <section className="analytics-grid">
        <article className="panel">
          <div className="panel-header">
            <div>
              <h2>Activity Pattern</h2>
              <p>Focused vs active minutes for the selected day.</p>
            </div>
          </div>
          <div className="bar-comparison">
            <Bar label="Focused" value={dashboard?.focused_minutes ?? 0} max={dashboard?.active_minutes ?? 1} />
            <Bar label="Active" value={dashboard?.active_minutes ?? 0} max={dashboard?.active_minutes ?? 1} />
            <Bar label="Switches" value={dashboard?.context_switches ?? 0} max={Math.max(dashboard?.context_switches ?? 0, 40)} />
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <h2>Top Apps</h2>
              <p>Ranked by active foreground time.</p>
            </div>
          </div>
          <div className="app-list">
            {(dashboard?.top_apps ?? []).length > 0 ? (
              dashboard?.top_apps.map((app, index) => (
                <div className="app-row" key={app.name}>
                  <span className="rank">{index + 1}</span>
                  <span className="app-name">{app.name}</span>
                  <span>{formatMinutes(app.duration_minutes)}</span>
                  <div className="progress"><span style={{ width: `${app.percent}%` }} /></div>
                </div>
              ))
            ) : (
              <p className="muted">No app usage yet.</p>
            )}
          </div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Recent Sessions</h2>
            <p>Latest foreground work blocks.</p>
          </div>
          <span className="muted">SQLite: {dashboard?.db_path}</span>
        </div>
        <div className="sessions-table">
          <div className="table-head">
            <span>Time</span>
            <span>Application</span>
            <span>Duration</span>
            <span>Task</span>
          </div>
          {(dashboard?.recent_sessions ?? []).map((session) => (
            <div className="table-row" key={`${session.time}-${session.application}-${session.duration_minutes}`}>
              <span>{session.time}</span>
              <span>{session.application}</span>
              <span>{formatMinutes(session.duration_minutes)}</span>
              <span>{session.task ?? 'Unassigned'}</span>
            </div>
          ))}
        </div>
      </section>

      {notificationsOpen && (
        <aside className="drawer">
          <div className="drawer-backdrop" onClick={() => setNotificationsOpen(false)} />
          <div className="drawer-panel">
            <div className="panel-header">
              <div>
                <h2>Notifications</h2>
                <p>Break recommendations and system notes.</p>
              </div>
              <button type="button" className="icon-button" onClick={() => setNotificationsOpen(false)}>x</button>
            </div>
            {notifications.length > 0 ? (
              notifications.map((item) => (
                <button type="button" className="notification" key={item.id} onClick={() => markRead(item.id)}>
                  <span className={item.state === 'unread' ? 'dot active' : 'dot'} />
                  <strong>{item.title}</strong>
                  <p>{item.body}</p>
                  <small>{item.kind} - {item.state}</small>
                </button>
              ))
            ) : (
              <div className="empty-state compact">
                <h3>No notifications</h3>
                <p>Break recommendations will appear here.</p>
              </div>
            )}
          </div>
        </aside>
      )}

      {settingsOpen && (
        <SettingsModal
          dashboard={dashboard}
          settings={settings}
          unreadCount={unreadCount}
          onClose={() => setSettingsOpen(false)}
          onSave={async (next) => {
            await invoke('save_settings', { settings: next })
            setSettings(next)
            setSettingsOpen(false)
            await refresh()
          }}
        />
      )}
    </main>
  )
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="bar-row">
      <div>
        <span>{label}</span>
        <strong>{label === 'Switches' ? value : formatMinutes(value)}</strong>
      </div>
      <div className="bar-track">
        <span style={{ width: `${Math.min((value / Math.max(max, 1)) * 100, 100)}%` }} />
      </div>
    </div>
  )
}

function SettingsModal({
  dashboard,
  settings,
  unreadCount,
  onClose,
  onSave,
}: {
  dashboard: DashboardPayload | null
  settings: RuntimeSettings | null
  unreadCount: number
  onClose: () => void
  onSave: (settings: RuntimeSettings) => Promise<void>
}) {
  const [tab, setTab] = useState('general')
  const [draft, setDraft] = useState<RuntimeSettings | null>(settings)
  const [excludedInput, setExcludedInput] = useState('')

  useEffect(() => setDraft(settings), [settings])
  if (!draft) return null

  const update = (next: RuntimeSettings) => setDraft(structuredClone(next))
  const setPreference = <K extends keyof RuntimeSettings['preferences']>(
    key: K,
    value: RuntimeSettings['preferences'][K],
  ) => update({ ...draft, preferences: { ...draft.preferences, [key]: value } })
  const setTracking = <K extends keyof RuntimeSettings['tracking']>(
    key: K,
    value: RuntimeSettings['tracking'][K],
  ) => update({ ...draft, tracking: { ...draft.tracking, [key]: value } })
  const setNotifications = <K extends keyof RuntimeSettings['notifications']>(
    key: K,
    value: RuntimeSettings['notifications'][K],
  ) => update({ ...draft, notifications: { ...draft.notifications, [key]: value } })

  const tabs = ['general', 'tracking', 'notifications', 'privacy', 'model']

  return (
    <aside className="modal-layer">
      <div className="modal-backdrop" onClick={onClose} />
      <section className="settings-modal">
        <div className="settings-titlebar">
          <div>
            <h2>Settings</h2>
            <p>Editable runtime preferences used by the existing collector.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>x</button>
        </div>
        <div className="settings-tabs">
          {tabs.map((item) => (
            <button type="button" className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>
              {item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </div>

        <div className="settings-body">
          {tab === 'general' && (
            <div className="settings-form">
              <Select label="Language" value={draft.preferences.language} options={['system', 'en', 'ru']} onChange={(value) => setPreference('language', value)} />
              <Select label="Theme" value={draft.preferences.theme} options={['system', 'light', 'dark']} onChange={(value) => setPreference('theme', value)} />
              <Checkbox label="Launch on startup" checked={draft.preferences.launch_on_startup} onChange={(value) => setPreference('launch_on_startup', value)} />
              <Checkbox label="Minimize to tray" checked={draft.preferences.minimize_to_tray} onChange={(value) => setPreference('minimize_to_tray', value)} />
              <Checkbox label="Start minimized" checked={draft.preferences.start_minimized} onChange={(value) => setPreference('start_minimized', value)} />
            </div>
          )}

          {tab === 'tracking' && (
            <div className="settings-form">
              <NumberInput label="Idle threshold, minutes" min={1} max={30} value={draft.tracking.idle_threshold_minutes} onChange={(value) => setTracking('idle_threshold_minutes', value)} />
              <Checkbox label="Track active window" checked={draft.tracking.track_active_window} onChange={(value) => setTracking('track_active_window', value)} />
              <Checkbox label="Track window titles" checked={draft.tracking.track_window_titles} onChange={(value) => setTracking('track_window_titles', value)} />
              <Checkbox label="Track keyboard activity" checked={draft.tracking.track_keyboard_activity} onChange={(value) => setTracking('track_keyboard_activity', value)} />
              <Checkbox label="Track mouse activity" checked={draft.tracking.track_mouse_activity} onChange={(value) => setTracking('track_mouse_activity', value)} />
              <div className="field full">
                <label>Excluded applications</label>
                <div className="excluded-list">
                  {draft.tracking.excluded_applications.map((item) => (
                    <button type="button" key={item} onClick={() => setTracking('excluded_applications', draft.tracking.excluded_applications.filter((entry) => entry !== item))}>
                      {item} x
                    </button>
                  ))}
                </div>
                <div className="inline-input">
                  <input value={excludedInput} onChange={(event) => setExcludedInput(event.target.value)} placeholder="example.exe" />
                  <button type="button" onClick={() => {
                    const value = excludedInput.trim()
                    if (!value) return
                    setTracking('excluded_applications', [...draft.tracking.excluded_applications, value])
                    setExcludedInput('')
                  }}>
                    Add
                  </button>
                </div>
              </div>
            </div>
          )}

          {tab === 'notifications' && (
            <div className="settings-form">
              <Checkbox label="Break recommendations" checked={draft.notifications.break_recommendations} onChange={(value) => setNotifications('break_recommendations', value)} />
              <Checkbox label="Performance warnings" checked={draft.notifications.performance_warnings} onChange={(value) => setNotifications('performance_warnings', value)} />
              <Select label="Minimum interval, minutes" value={String(draft.notifications.minimum_interval_minutes)} options={['15', '30', '45', '60']} onChange={(value) => setNotifications('minimum_interval_minutes', Number(value))} />
              <NumberInput label="Live check interval, seconds" min={30} max={300} value={draft.notifications.live_check_interval_seconds} onChange={(value) => setNotifications('live_check_interval_seconds', value)} />
              <TextInput label="Do not disturb start" value={draft.notifications.do_not_disturb_start} onChange={(value) => setNotifications('do_not_disturb_start', value)} />
              <TextInput label="Do not disturb end" value={draft.notifications.do_not_disturb_end} onChange={(value) => setNotifications('do_not_disturb_end', value)} />
              <SettingRow label="Unread notifications" value={unreadCount.toString()} />
            </div>
          )}

          {tab === 'privacy' && (
            <div className="settings-form">
              <SettingRow label="Database" value={dashboard?.db_path ?? 'Not loaded'} />
              <SettingRow label="Data storage" value="Local SQLite only" />
              <SettingRow label="Typed text" value="Never recorded" />
              <SettingRow label="Screenshots" value="Never recorded" />
              <SettingRow label="Events loaded" value={(dashboard?.event_count ?? 0).toString()} />
            </div>
          )}

          {tab === 'model' && (
            <div className="settings-form">
              <NumberInput label="Minimum training samples" min={5} max={500} value={draft.model.min_training_samples} onChange={(value) => update({ ...draft, model: { min_training_samples: value } })} />
              <SettingRow label="Personal model" value="Collecting data" />
              <SettingRow label="Training UI" value="Unavailable until enough self-reports exist" />
            </div>
          )}
        </div>

        <div className="settings-actions">
          <button type="button" className="button" onClick={onClose}>Close</button>
          <button type="button" className="button primary" onClick={() => onSave(draft)}>Save settings</button>
        </div>
      </section>
    </aside>
  )
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="setting-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="check-row">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((item) => <option value={item} key={item}>{item}</option>)}
      </select>
    </label>
  )
}

function NumberInput({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type="number" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  )
}

function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}

export default App
