"use client"

import { useState } from "react"
import { X, Plus, Trash2, Lock, Unlock, Loader2 } from "lucide-react"
import { useBonusRoster, useBonusMutations, type RosterEmployee } from "@/lib/bonus-api"
import { BRAND, ROLE_LABEL } from "../format"

const ROLES: RosterEmployee["role"][] = ["kam", "freight_match", "tracking_tracing"]

export function RosterEditor({ period, onClose }: { period: string | undefined; onClose: () => void }) {
  const { data, isLoading } = useBonusRoster(period, true)
  const m = useBonusMutations()
  const d = data?.data
  const periodKey = d?.period.key ?? period ?? ""

  const [teamFx, setTeamFx] = useState<string>("")
  const [nightFx, setNightFx] = useState<string>("")
  const [newRows, setNewRows] = useState<Record<string, { name: string; role: string; salary: string }>>({})

  const fxTeam = teamFx !== "" ? teamFx : d ? String(d.settings.teamFx) : ""
  const fxNight = nightFx !== "" ? nightFx : d ? String(d.settings.nightFx) : ""
  const locked = d?.lock.status === "approved"

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 py-10" onClick={onClose}>
      <div
        className="w-full max-w-4xl rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between rounded-t-2xl px-5 py-3 text-white" style={{ background: BRAND }}>
          <h2 className="text-base font-bold">HR Settings — {d?.period.label ?? "Bonus Calculator"}</h2>
          <button onClick={onClose} className="rounded-md p-1 hover:bg-white/20">
            <X className="h-5 w-5" />
          </button>
        </div>

        {isLoading || !d ? (
          <div className="flex items-center justify-center py-20 text-[#6B7280]">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…
          </div>
        ) : (
          <div className="max-h-[70vh] space-y-6 overflow-y-auto p-5">
            {/* FX + Lock */}
            <section className="rounded-xl border border-[#E5E7EB] p-4">
              <h3 className="text-sm font-bold text-[#1F2937]">Board-pinned FX rates</h3>
              <p className="mt-0.5 text-xs text-[#6B7280]">
                HR sets the exchange rates used for this period.
                {d.settings.suggestedDofFx != null && (
                  <>
                    {" "}Suggested DOF (Banxico FIX): <strong>{d.settings.suggestedDofFx.toFixed(4)}</strong>
                    <button
                      className="ml-2 rounded border border-[#DDD6FE] px-2 py-0.5 text-[11px] font-medium text-[#6D28D9] hover:bg-[#F5F3FF]"
                      onClick={() => setTeamFx(String(d.settings.suggestedDofFx))}
                    >
                      Use for team FX
                    </button>
                  </>
                )}
              </p>
              <div className="mt-3 flex flex-wrap items-end gap-4">
                <label className="text-xs font-semibold text-[#475569]">
                  Team FX (USD→MXN)
                  <input
                    type="number"
                    step="0.0001"
                    value={fxTeam}
                    onChange={(e) => setTeamFx(e.target.value)}
                    className="mt-1 block w-36 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm"
                  />
                </label>
                <label className="text-xs font-semibold text-[#475569]">
                  Night FX (USD→MXN)
                  <input
                    type="number"
                    step="0.0001"
                    value={fxNight}
                    onChange={(e) => setNightFx(e.target.value)}
                    className="mt-1 block w-36 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm"
                  />
                </label>
                <button
                  disabled={m.saveFx.isPending}
                  onClick={() =>
                    m.saveFx.mutate({ period_key: periodKey, team_fx: Number(fxTeam), night_fx: Number(fxNight) })
                  }
                  className="rounded-md px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
                  style={{ background: BRAND }}
                >
                  {m.saveFx.isPending ? "Saving…" : "Save FX"}
                </button>
                <button
                  onClick={() => (locked ? m.unlock.mutate(periodKey) : m.lock.mutate(periodKey))}
                  className={`flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm font-semibold ${
                    locked ? "border-[#FCA5A5] text-[#B91C1C]" : "border-[#86EFAC] text-[#15803D]"
                  }`}
                >
                  {locked ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
                  {locked ? "Unlock period" : "Lock period"}
                </button>
              </div>
              {d.settings.pinned && (
                <p className="mt-2 text-[11px] text-[#94A3B8]">Last pinned by {d.settings.updatedBy ?? "—"}.</p>
              )}
            </section>

            {/* Roster per team */}
            {d.teams.map((team) => {
              const draft = newRows[team.id] ?? { name: "", role: "tracking_tracing", salary: "0" }
              return (
                <section key={team.id} className="rounded-xl border border-[#E5E7EB] p-4">
                  <h3 className="text-sm font-bold text-[#1F2937]">{team.name}</h3>
                  <div className="mt-2 space-y-2">
                    {team.employees.map((emp) => (
                      <RosterRow key={emp.id} teamId={team.id} emp={emp} mutations={m} />
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-dashed border-[#E5E7EB] pt-3">
                    <input
                      placeholder="New employee name"
                      value={draft.name}
                      onChange={(e) => setNewRows((p) => ({ ...p, [team.id]: { ...draft, name: e.target.value } }))}
                      className="w-48 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm"
                    />
                    <select
                      value={draft.role}
                      onChange={(e) => setNewRows((p) => ({ ...p, [team.id]: { ...draft, role: e.target.value } }))}
                      className="rounded-md border border-[#E5E7EB] px-2 py-1 text-sm"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABEL[r]}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      placeholder="Salary MXN"
                      value={draft.salary}
                      onChange={(e) => setNewRows((p) => ({ ...p, [team.id]: { ...draft, salary: e.target.value } }))}
                      className="w-28 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm"
                    />
                    <button
                      disabled={!draft.name || m.createRoster.isPending}
                      onClick={() => {
                        m.createRoster.mutate({
                          team_id: team.id,
                          name: draft.name,
                          role: draft.role,
                          salary_mxn: Number(draft.salary) || 0,
                        })
                        setNewRows((p) => ({ ...p, [team.id]: { name: "", role: "tracking_tracing", salary: "0" } }))
                      }}
                      className="flex items-center gap-1 rounded-md border border-[#DDD6FE] px-2 py-1 text-sm font-medium text-[#6D28D9] hover:bg-[#F5F3FF] disabled:opacity-50"
                    >
                      <Plus className="h-4 w-4" /> Add
                    </button>
                  </div>
                </section>
              )
            })}

            {/* Afterhours */}
            <section className="rounded-xl border border-[#E5E7EB] p-4">
              <h3 className="text-sm font-bold text-[#1F2937]">Afterhours (Night / Weekend)</h3>
              <div className="mt-2 space-y-2">
                {d.afterhours.map((a) => (
                  <AfterhoursRow key={a.id} row={a} mutations={m} />
                ))}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

function RosterRow({
  teamId,
  emp,
  mutations,
}: {
  teamId: string
  emp: RosterEmployee
  mutations: ReturnType<typeof useBonusMutations>
}) {
  const [name, setName] = useState(emp.name)
  const [role, setRole] = useState(emp.role)
  const [salary, setSalary] = useState(String(emp.salaryMxn))
  const dirty = name !== emp.name || role !== emp.role || Number(salary) !== emp.salaryMxn
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input value={name} onChange={(e) => setName(e.target.value)} className="w-48 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm" />
      <select value={role} onChange={(e) => setRole(e.target.value as RosterEmployee["role"])} className="rounded-md border border-[#E5E7EB] px-2 py-1 text-sm">
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {ROLE_LABEL[r]}
          </option>
        ))}
      </select>
      <input type="number" value={salary} onChange={(e) => setSalary(e.target.value)} className="w-28 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm" />
      <button
        disabled={!dirty || mutations.updateRoster.isPending}
        onClick={() =>
          mutations.updateRoster.mutate({ id: emp.id, team_id: teamId, name, role, salary_mxn: Number(salary) || 0 })
        }
        className="rounded-md border border-[#E5E7EB] px-2 py-1 text-xs font-medium text-[#475569] enabled:hover:bg-[#F3F4F6] disabled:opacity-40"
      >
        Save
      </button>
      <button
        onClick={() => mutations.deleteRoster.mutate(emp.id)}
        className="rounded-md border border-[#FCA5A5] p-1 text-[#B91C1C] hover:bg-[#FEF2F2]"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  )
}

function AfterhoursRow({
  row,
  mutations,
}: {
  row: { id: string; group: string; name: string; salaryMxn: number; receivesBonus: boolean }
  mutations: ReturnType<typeof useBonusMutations>
}) {
  const [name, setName] = useState(row.name)
  const [salary, setSalary] = useState(String(row.salaryMxn))
  const [receives, setReceives] = useState(row.receivesBonus)
  const dirty = name !== row.name || Number(salary) !== row.salaryMxn || receives !== row.receivesBonus
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-28 text-xs font-medium text-[#6B7280]">{row.group}</span>
      <input value={name} onChange={(e) => setName(e.target.value)} className="w-48 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm" />
      <input type="number" value={salary} onChange={(e) => setSalary(e.target.value)} className="w-28 rounded-md border border-[#E5E7EB] px-2 py-1 text-sm" />
      <label className="flex items-center gap-1 text-xs text-[#475569]">
        <input type="checkbox" checked={receives} onChange={(e) => setReceives(e.target.checked)} />
        Eligible
      </label>
      <button
        disabled={!dirty || mutations.updateAfterhours.isPending}
        onClick={() => mutations.updateAfterhours.mutate({ id: row.id, name, salary_mxn: Number(salary) || 0, receives_bonus: receives })}
        className="rounded-md border border-[#E5E7EB] px-2 py-1 text-xs font-medium text-[#475569] enabled:hover:bg-[#F3F4F6] disabled:opacity-40"
      >
        Save
      </button>
    </div>
  )
}
