import type { RequirementProfileDraft } from "../../types";

export function JobRequirementsPanel({ profile, confirmed, canConfirm, busy, onConfirm }: {
  profile: RequirementProfileDraft; confirmed: boolean; canConfirm: boolean; busy: boolean; onConfirm: () => void;
}) {
  return <section aria-label="Job requirements" className="rounded-2xl border border-slate-200 bg-white p-5">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-slate-800">Job requirements</h3><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${confirmed ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}>{confirmed ? "Confirmed" : "In progress"}</span></div>
    <p className="mt-3 break-words font-semibold text-slate-800">{profile.title || "Tell the assistant the job title"}</p>
    {profile.summary ? <p className="mt-2 text-sm leading-6 text-slate-600">{profile.summary}</p> : null}
    <div className="mt-4 grid gap-3 sm:grid-cols-2">{([
      ["Required skills", profile.required_skills, "bg-sky-50 text-sky-800"],
      ["Preferred skills", profile.preferred_skills, "bg-violet-50 text-violet-800"],
      ["Qualifications", profile.qualifications, "bg-amber-50 text-amber-800"],
      ["Selection criteria", profile.selection_criteria, "bg-teal-50 text-teal-800"],
    ] as const).map(([name, items, style]) => items.length ? <section key={name} className={`rounded-xl p-3 ${style}`}><h4 className="text-xs font-semibold">{name}</h4><ul className="mt-2 space-y-2 text-sm">{items.map((item, index) => <li key={index}><span className="font-medium">{item.name}</span>{item.details ? <span className="block text-xs leading-5 opacity-90">{item.details}</span> : null}</li>)}</ul></section> : null)}</div>
    {profile.min_years_experience !== null ? <p className="mt-4 text-sm text-slate-600">Experience: <span className="font-semibold text-slate-800">{profile.min_years_experience}+ years</span></p> : null}
    {canConfirm ? <button type="button" disabled={busy} onClick={onConfirm} className="mt-4 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">Confirm requirements</button> : null}
  </section>;
}
