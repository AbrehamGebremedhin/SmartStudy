import { getActivityCalendar } from '../../lib/gamification'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// GitHub-style study calendar driven by daily XP. Each column is a week
// (Sun→Sat), coloured by how much was earned that day.
export default function ActivityHeatmap({ weeks = 10 }) {
  const { cols } = getActivityCalendar(weeks)

  const activeDays = cols.reduce(
    (sum, col) => sum + col.filter(d => !d.future && d.xp > 0).length,
    0,
  )

  // Month label sits above the first column where a new month begins.
  let prevMonth = -1
  const monthLabels = cols.map(col => {
    const firstReal = col.find(d => !d.future) ?? col[0]
    const m = new Date(firstReal.key).getMonth()
    if (m !== prevMonth) {
      prevMonth = m
      return MONTHS[m]
    }
    return ''
  })

  return (
    <div className="heat">
      <div className="heat-head">
        <span className="heat-title">Study activity</span>
        <span className="heat-sub">{activeDays} active {activeDays === 1 ? 'day' : 'days'} · {weeks} weeks</span>
      </div>

      <div className="heat-grid">
        <div className="heat-months">
          {monthLabels.map((m, i) => (
            <span key={i} className="heat-month">{m}</span>
          ))}
        </div>
        <div className="heat-cells">
          {cols.map((col, ci) => (
            <div key={ci} className="heat-col">
              {col.map(day => (
                <span
                  key={day.key}
                  className={`heat-cell l${day.level}${day.isToday ? ' today' : ''}${day.future ? ' future' : ''}`}
                  title={day.future ? '' : `${day.key} · ${day.xp} XP`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="heat-legend">
        <span>Less</span>
        <span className="heat-cell l0" />
        <span className="heat-cell l1" />
        <span className="heat-cell l2" />
        <span className="heat-cell l3" />
        <span className="heat-cell l4" />
        <span>More</span>
      </div>
    </div>
  )
}
