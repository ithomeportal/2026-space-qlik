import { Info, CheckCircle2 } from "lucide-react"

export function BestPractice() {
  return (
    <section className="flex items-start justify-between gap-3 rounded-2xl border border-[#FDE68A] bg-[#FFFBEB] px-5 py-4">
      <div className="flex items-start gap-2">
        <Info className="mt-0.5 h-4 w-4 text-[#D97706]" />
        <div>
          <p className="text-sm font-bold text-[#92400E]">Best practice</p>
          <p className="text-xs text-[#B45309]">
            Before payment, review the report against McLeod and lock the month with HR/Finance approval to prevent later
            changes. Once locked, save each monthly cutoff as an approved historical record.
          </p>
        </div>
      </div>
      <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-[#10B981]" />
    </section>
  )
}
