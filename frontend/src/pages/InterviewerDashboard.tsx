import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { apiRequest } from "../api/apiClient";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { DashboardIcon as Icon } from "../components/dashboard/DashboardIcon";
import { dashboardSummary, interviewLive, type DashboardData } from "../components/dashboard/dashboardData";
import { formatDate, formatTime, timeZoneLabel } from "../utils/dateTime";

const focus = "focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-blue-500";
const card = "rounded-2xl border border-slate-200 bg-white shadow-sm";
const number = (value: number | undefined) => value == null ? "—" : value.toLocaleString("en-GB");
const plural = (value: number, singular: string) => `${number(value)} ${singular}${value === 1 ? "" : "s"}`;

export function InterviewerDashboard() {
  const { user } = useAuth();
  const { refreshVersion } = useSupervisor();
  const [data, setData] = useState<DashboardData>({});
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [reload, setReload] = useState(0);
  const [updated, setUpdated] = useState<number>();
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    let active = true;
    setLoading(true);
    const sources = [{ key: "jobs", path: "/job-descriptions", label: "job descriptions" },
      { key: "screening", path: "/screening/jobs", label: "applications and screening" },
      { key: "interviews", path: "/interviews/schedules", label: "interviews" }] as const;
    void Promise.allSettled(sources.map(source => apiRequest(source.path))).then(results => {
      if (!active) return;
      const next: Record<string, unknown> = {};
      const failures: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled" && Array.isArray(result.value)) next[sources[index].key] = result.value;
        else failures.push(sources[index].label);
      });
      setData(next as DashboardData); setErrors(failures);
      setUpdated(Date.now()); setNow(Date.now()); setLoading(false);
    });
    return () => { active = false; };
  }, [reload, refreshVersion]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => window.clearInterval(timer);
  }, []);

  const summary = dashboardSummary(data, now);
  const metric = (value: number | undefined) => loading ? "—" : number(value);
  const tasks = [
    { count: summary.pending, title: "Review CV screening", detail: "Applications need a current screening result.", path: "assessments", color: "bg-sky-50 text-sky-700" },
    { count: summary.drafts, title: "Review job drafts", detail: "Finish the description and approve when ready.", path: "jobs", color: "bg-amber-50 text-amber-700" },
    { count: summary.overdue, title: "Check past interview slots", detail: "These slots have passed but are not marked complete.", path: "interviews", color: "bg-rose-50 text-rose-700" },
  ].filter(task => task.count != null && task.count > 0);
  const stats = [
    { title: "Published posts", value: summary.published, detail: "Currently published job posts", path: "jobs", icon: "jobs" as const, color: "bg-blue-50 text-blue-700" },
    { title: "Applications", value: summary.applications, detail: "Across your job posts", path: "candidates", icon: "people" as const, color: "bg-teal-50 text-teal-700" },
    { title: "Need CV screening", value: summary.pending, detail: "Missing a current screening result", path: "assessments", icon: "screen" as const, color: "bg-amber-50 text-amber-700" },
    { title: "Upcoming interviews", value: summary.upcoming?.length, detail: summary.today == null ? "Interview schedule unavailable" : `${plural(summary.today, "interview")} today`, path: "interviews", icon: "calendar" as const, color: "bg-violet-50 text-violet-700" },
  ];

  return <section className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs font-semibold uppercase tracking-widest text-blue-600">Your recruitment workspace</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">Recruitment overview</h1>
        <p className="mt-2 text-sm text-slate-500">Welcome back{user?.name ? `, ${user.name}` : ""}. Here’s where your hiring stands.</p></div>
      <button type="button" disabled={loading} onClick={() => setReload(value => value + 1)} className={`inline-flex min-h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-600 transition hover:border-blue-200 hover:text-blue-700 disabled:opacity-50 ${focus}`}><Icon name="refresh" />{loading ? "Refreshing…" : "Refresh overview"}</button>
    </header>

    <section aria-label="Hiring snapshot" className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-blue-900 via-blue-800 to-blue-600 p-6 text-white shadow-lg shadow-blue-900/10 sm:p-7">
      <div aria-hidden="true" className="pointer-events-none absolute -right-12 -top-24 h-72 w-72 rounded-full border-[40px] border-white/5" />
      <div className="relative flex flex-wrap items-center justify-between gap-6"><div className="max-w-xl">
        <p className="text-xs font-medium tracking-wide text-blue-100">{formatDate(new Date(now).toISOString())} · {timeZoneLabel()}</p>
        <h2 className="mt-3 text-2xl font-semibold tracking-tight">Make your next great hire.</h2>
        <p className="mt-2 text-sm leading-6 text-blue-100">Keep your roles, candidate screening, and interviews moving in one place.</p>
        <div className="mt-5 flex flex-wrap gap-2"><Link to="/interviewer/jobs" className={`inline-flex min-h-10 items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm font-semibold text-blue-800 transition hover:bg-blue-50 ${focus}`}><Icon name="jobs" />Manage jobs</Link>
          <Link to="/interviewer/schedule-interviews" className={`inline-flex min-h-10 items-center gap-2 rounded-xl border border-white/30 bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/20 ${focus}`}><Icon name="calendar" />Schedule interviews</Link></div>
      </div><div className="flex gap-6 rounded-2xl border border-white/15 bg-white/10 px-5 py-4 sm:gap-8">
        <div><p className="text-2xl font-semibold tabular-nums">{metric(summary.approved)}</p><p className="mt-1 text-xs text-blue-100">Approved descriptions</p></div>
        <div className="border-l border-white/20 pl-6 sm:pl-8"><p className="text-2xl font-semibold tabular-nums">{metric(summary.completed)}</p><p className="mt-1 text-xs text-blue-100">Interviews completed</p></div>
      </div></div>
    </section>

    {errors.length ? <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Couldn’t load {errors.join(", ")}. Unavailable totals are shown as —. Use Refresh overview to try again.</div> : null}
    {loading ? <p role="status" className="text-sm text-slate-500">Loading your hiring overview…</p> : null}

    <section aria-label="Hiring totals" aria-busy={loading} className="grid grid-cols-1 gap-3 min-[400px]:grid-cols-2 xl:grid-cols-4">
      {stats.map(stat => <Link key={stat.title} to={`/interviewer/${stat.path}`} className={`group ${card} p-5 transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md motion-reduce:transform-none ${focus}`}>
        <div className="flex items-center justify-between gap-2"><span className={`flex h-10 w-10 items-center justify-center rounded-xl ${stat.color}`}><Icon name={stat.icon} /></span><Icon name="arrow" className="h-4 w-4 text-slate-300 transition group-hover:text-blue-600" /></div>
        <dl className="mt-4"><dt className="text-sm font-medium text-slate-600">{stat.title}</dt><dd className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-slate-900">{metric(stat.value)}</dd></dl>
        <p className="mt-2 text-xs leading-5 text-slate-500">{stat.value == null && !loading ? "Information unavailable" : stat.detail}</p>
      </Link>)}
    </section>

    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <section aria-label="Next interviews" className={`${card} min-w-0 p-5 sm:p-6`}>
        <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="text-lg font-semibold text-slate-900">Next interviews</h2><p className="mt-1 text-xs text-slate-500">Your next conversations · {timeZoneLabel()}</p></div><Link to="/interviewer/interviews" className={`rounded text-sm font-semibold text-blue-600 hover:text-blue-800 ${focus}`}>View all →</Link></div>
        {loading ? <p className="py-10 text-sm text-slate-400">Loading interviews…</p> : !summary.upcoming ? <p className="py-10 text-sm text-slate-500">Interview information is unavailable. Try refreshing.</p> : !summary.upcoming.length ? <div className="mt-5 rounded-2xl bg-slate-50 px-5 py-8 text-center"><Icon name="calendar" className="mx-auto h-7 w-7 text-blue-400" /><p className="mt-3 font-medium text-slate-700">No upcoming interviews</p><p className="mt-1 text-sm text-slate-500">Choose candidates from your rankings to plan the next conversation.</p><Link to="/interviewer/schedule-interviews" className={`mt-4 inline-block rounded text-sm font-semibold text-blue-600 ${focus}`}>Schedule an interview →</Link></div> : <ul className="mt-4 divide-y divide-slate-100">{summary.upcoming.slice(0, 3).map(item => <li key={item.id} className="flex flex-wrap items-center gap-3 py-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 font-semibold text-blue-700" aria-hidden="true">{item.candidate_name.trim().slice(0, 1).toUpperCase() || "?"}</div>
          <div className="min-w-0 flex-1 basis-36"><p className="break-words font-semibold text-slate-800">{item.candidate_name}</p><p className="mt-0.5 break-words text-xs text-slate-500">{item.job_title}</p><p className="mt-2 text-xs font-medium text-slate-600">{formatDate(item.start_utc)} · {formatTime(item.start_utc)} · {item.duration_minutes} min</p></div>
          <div className="flex flex-wrap items-center gap-2">{interviewLive(item) ? <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">{item.room_status === "waiting" ? "Candidate waiting" : "Room open"}</span> : null}
            <Link to={`/interviews/${item.id}/console`} aria-label={`Open interview with ${item.candidate_name}`} className={`rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-100 ${focus}`}>Open interview</Link></div>
        </li>)}</ul>}
      </section>

      <section aria-label="Needs attention" className={`${card} p-5 sm:p-6`}><h2 className="text-lg font-semibold text-slate-900">Needs attention</h2><p className="mt-1 text-xs text-slate-500">A clear next step for your hiring workflow.</p>
        {loading ? <p className="py-10 text-sm text-slate-400">Checking your next steps…</p> : tasks.length ? <ul className="mt-4 space-y-2">{tasks.map(task => <li key={task.path}><Link to={`/interviewer/${task.path}`} className={`flex items-start gap-3 rounded-xl p-3 transition hover:bg-slate-50 ${focus}`}><span className={`flex h-9 min-w-9 items-center justify-center rounded-xl px-2 text-sm font-bold tabular-nums ${task.color}`}>{number(task.count)}</span><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-slate-800">{task.title}</p><p className="mt-1 text-xs leading-5 text-slate-500">{task.detail}</p></div><Icon name="arrow" className="mt-1 h-4 w-4 shrink-0 text-slate-400" /></Link></li>)}</ul> : errors.length ? <p className="mt-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-800">Refresh the missing information to see your next steps.</p> : !data.jobs?.length ? <div className="mt-5 rounded-2xl bg-blue-50 p-5"><p className="font-semibold text-blue-900">Start with your first role</p><p className="mt-2 text-sm leading-6 text-blue-800">Create a job description manually or describe the role to the assistant on the Jobs page.</p><Link to="/interviewer/jobs" className={`mt-4 inline-flex items-center gap-2 rounded text-sm font-semibold text-blue-700 ${focus}`}>Create a job description <Icon name="arrow" className="h-4 w-4" /></Link></div> : <div className="mt-5 rounded-2xl bg-emerald-50 p-5"><Icon name="check" className="h-6 w-6 text-emerald-600" /><p className="mt-2 font-semibold text-emerald-900">You’re up to date</p><p className="mt-1 text-sm leading-6 text-emerald-800">No pending CV screening, draft reviews, or past slots to check.</p></div>}
      </section>
    </div>

    <section aria-label="Role activity" className={`${card} overflow-hidden`}><header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-5 sm:px-6"><div><h2 className="text-lg font-semibold text-slate-900">Role activity</h2><p className="mt-1 text-xs text-slate-500">Applications and CV screening progress by job post.</p></div><Link to="/interviewer/assessments" className={`rounded text-sm font-semibold text-blue-600 ${focus}`}>Go to CV screening →</Link></header>
      {loading ? <p className="p-6 text-sm text-slate-400">Loading role activity…</p> : !summary.roles ? <p className="p-6 text-sm text-slate-500">Role activity is unavailable. Try refreshing.</p> : !summary.roles.length ? <div className="px-6 py-8"><p className="font-medium text-slate-700">Your roles will appear here</p><p className="mt-1 text-sm text-slate-500">Publish a job to start collecting applications and tracking screening progress.</p></div> : <ul className="divide-y divide-slate-100">{summary.roles.map(role => {
        const screened = Math.max(0, role.application_count - role.pending_count);
        return <li key={role.id} className="grid items-center gap-4 px-5 py-5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(160px,0.7fr)] sm:px-6"><div className="min-w-0"><p className="break-words text-sm font-semibold text-slate-800">{role.title}</p><span className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${role.posting_status === "published" ? "bg-teal-50 text-teal-700" : "bg-slate-100 text-slate-600"}`}>{role.posting_status.replaceAll("_", " ")}</span></div>
          <p className="text-sm text-slate-600"><span className="font-semibold tabular-nums text-slate-900">{number(role.application_count)}</span> applications</p>
          <div>{role.application_count ? <><div className="flex justify-between gap-3 text-xs"><span className="text-slate-500">CVs screened</span><span className="font-medium tabular-nums text-blue-700">{screened} / {role.application_count}</span></div><div role="progressbar" aria-label={`CV screening for ${role.title}`} aria-valuenow={screened} aria-valuemin={0} aria-valuemax={role.application_count} aria-valuetext={`${screened} of ${role.application_count} applications have current screening results`} className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-500" style={{ width: `${screened / role.application_count * 100}%` }} /></div></> : <p className="text-xs text-slate-400">No applications yet</p>}</div></li>;
      })}</ul>}
    </section>

    <nav aria-label="Dashboard shortcuts" className="grid gap-3 sm:grid-cols-3">{[
      { path: "candidates", title: "Browse candidates", detail: "Profiles, CVs, and applications", icon: "people" as const, color: "text-teal-600" },
      { path: "assessments", title: "Screen CVs", detail: "Match candidates to your roles", icon: "screen" as const, color: "text-sky-600" },
      { path: "reports", title: "Compare assessments", detail: "Review scores and final rankings", icon: "check" as const, color: "text-violet-600" },
    ].map(link => <Link key={link.path} to={`/interviewer/${link.path}`} className={`flex items-center gap-3 ${card} p-4 transition hover:border-blue-200 ${focus}`}><span className={`rounded-xl bg-slate-50 p-2.5 ${link.color}`}><Icon name={link.icon} /></span><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-slate-800">{link.title}</p><p className="mt-1 text-xs leading-5 text-slate-500">{link.detail}</p></div><Icon name="arrow" className="h-4 w-4 shrink-0 text-slate-400" /></Link>)}</nav>
    {updated && !loading ? <p className="text-right text-xs text-slate-400">{errors.length ? "Last refresh attempted" : "Last refreshed"} {formatTime(new Date(updated).toISOString())} · {timeZoneLabel()}</p> : null}
  </section>;
}
