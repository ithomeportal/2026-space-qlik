import { AlertTriangle } from "lucide-react"

export function ErrorBanner({ message }: { message?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-sm text-[#991B1B]">
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <div>
        <p className="font-semibold">Couldn&apos;t load this section.</p>
        <p className="text-[#B91C1C]">{message || "The backend may be waking up — retrying automatically."}</p>
      </div>
    </div>
  )
}
