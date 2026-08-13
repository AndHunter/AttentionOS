import { useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import './App.css'

type Metric = {
  label: string
  value: string
  detail: string
}

type TimelineSegment = {
  app: string
  task?: string | null
  start_minute: number
  end_minute: number
  duration_minutes: number
}

type AppUsage = {
  name: string
  duration_minutes: number
  percent: number
}

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

function App() {
  const [date, setDate] = useState(todayIso())
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [notifications, setNotifications] = useState<NotificationPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  async function refresh(target = date) {
    setLoading(true)
    setError(null)
    try {
      const [nextDashboard, nextNotifications] = await Promise.all([
        invoke<DashboardPayload>('get_dashboard', { date: target }),
        invoke<NotificationPayload[]>('get_notifications', { limit: 8 }),
      ])
      setDashboard(nextDashboard)
      setNotifications(nextNotifications)
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
      if (!map.has(segment.app)) {
        map.set(segment.app, palette[map.size % palette.length])
      }
    })
    return map
  }, [dashboard?.timeline])

  async function markRead(id: number) {
    await invoke('mark_notification_read', { id })
    await refresh()
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="brand">AttentionOS</div>
          <div className="subtle">Local-first focus analytics</div>
        </div>
        <div className="topbar-actions">
          <span className="privacy-pill">Local only</span>
          <button type="button" className="icon-button" onClick={() => refresh()} aria-label="Refresh">
            ↻
          </button>
          <button type="button" className="button ghost" onClick={() => setDrawerOpen(true)}>
            Notifications {unreadCount > 0 && <span className="badge">{unreadCount}</span>}
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
            <button type="button" onClick={() => setDate(shiftDate(date, -1))}>‹</button>
            <span>{date === todayIso() ? 'Today' : formatDate(date)}</span>
            <button type="button" onClick={() => setDate(shiftDate(date, 1))}>›</button>
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
                return (
                  <div
                    className="timeline-segment"
                    key={`${segment.app}-${segment.start_minute}-${index}`}
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      background: appColor.get(segment.app),
                    }}
                    title={`${segment.app} · ${formatMinutes(segment.duration_minutes)}${segment.task ? ` · ${segment.task}` : ''}`}
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
            <div className="table-row" key={`${session.time}-${session.application}`}>
              <span>{session.time}</span>
              <span>{session.application}</span>
              <span>{formatMinutes(session.duration_minutes)}</span>
              <span>{session.task ?? 'Unassigned'}</span>
            </div>
          ))}
        </div>
      </section>

      {drawerOpen && (
        <aside className="drawer">
          <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)} />
          <div className="drawer-panel">
            <div className="panel-header">
              <div>
                <h2>Notifications</h2>
                <p>Break recommendations and system notes.</p>
              </div>
              <button type="button" className="icon-button" onClick={() => setDrawerOpen(false)}>×</button>
            </div>
            {notifications.length > 0 ? (
              notifications.map((item) => (
                <button type="button" className="notification" key={item.id} onClick={() => markRead(item.id)}>
                  <span className={item.state === 'unread' ? 'dot active' : 'dot'} />
                  <strong>{item.title}</strong>
                  <p>{item.body}</p>
                  <small>{item.kind} · {item.state}</small>
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

export default App
