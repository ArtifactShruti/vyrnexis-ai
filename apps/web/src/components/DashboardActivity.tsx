import { useState } from "react";

export type ActivityDay = { date: string; events: number; alerts: number; incidents: number };

const series = [
  { key: "events", label: "Events received" },
  { key: "alerts", label: "Alerts created" },
  { key: "incidents", label: "Incidents opened" },
] as const;

const formatDay = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
const displayDate = (date: string) => formatDay.format(new Date(date + "T00:00:00Z"));

export default function DashboardActivity({ activity }: { activity: ActivityDay[] }) {
  const [range, setRange] = useState<7 | 30>(7);
  const [selected, setSelected] = useState<string | null>(null);
  const days = activity.slice(-range);
  const chosen = days.find((day) => day.date === selected);
  const peak = Math.max(1, ...days.flatMap((day) => series.map(({ key }) => day[key])));
  const values = series.map(({ key, label }) => ({
    key, label, value: chosen ? chosen[key] : days.reduce((sum, day) => sum + day[key], 0),
  }));
  const hasActivity = values.some(({ value }) => value > 0) || !!chosen;

  return <section className="panel dashboard-activity" aria-labelledby="dashboard-activity-title">
    <header className="dashboard-activity-heading">
      <div>
        <h2 id="dashboard-activity-title">Recorded activity</h2>
        <p>Daily organization activity in UTC. Today is still in progress.</p>
      </div>
      <div className="dashboard-activity-range" aria-label="Activity period">
        {([7, 30] as const).map((value) => <button type="button" key={value} aria-pressed={range === value}
          onClick={() => { setRange(value); setSelected(null); }}>{value} days</button>)}
      </div>
    </header>
    <div className="dashboard-activity-metrics" aria-live="polite">
      <div className="dashboard-activity-period">
        <span>{chosen ? displayDate(chosen.date) : `${displayDate(days[0].date)} – ${displayDate(days[days.length - 1].date)}`}</span>
        {chosen && <button type="button" onClick={() => setSelected(null)}>Show period totals</button>}
      </div>
      {values.map(({ key, label, value }) => <div key={key}>
        <span><i className={key} aria-hidden="true" />{label}</span>
        <strong>{value.toLocaleString()}</strong>
      </div>)}
    </div>
    {hasActivity ? <div className="dashboard-activity-scroll">
      <div className="dashboard-activity-axis" aria-hidden="true"><span>{peak.toLocaleString()}</span><span>0</span></div>
      <div className="dashboard-activity-days" role="group" aria-label="Select a day to inspect its counts">
        {days.map((day, index) => {
          const showDate = range === 7 || index % 5 === 0 || index === days.length - 1;
          const description = series.map(({ key, label }) => `${label} ${day[key]}`).join(", ");
          return <button type="button" key={day.date} aria-pressed={chosen?.date === day.date}
            aria-label={`${displayDate(day.date)} UTC, ${description}`} title={description}
            onClick={() => setSelected(chosen?.date === day.date ? null : day.date)}>
            <span className="dashboard-activity-bars" aria-hidden="true">
              {series.map(({ key }) => <i key={key} className={key}
                style={{ height: day[key] ? `max(2px, ${day[key] * 100 / peak}%)` : 0 }} />)}
            </span>
            <span className="dashboard-activity-tick" aria-hidden="true">{showDate ? displayDate(day.date) : "\u00a0"}</span>
          </button>;
        })}
      </div>
    </div> : <p className="dashboard-activity-empty">No events, alerts, or incidents were recorded in this period.</p>}
  </section>;
}
