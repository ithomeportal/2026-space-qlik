"use client"

interface Props {
  errors: Array<unknown>
  label: string
}

export function DCErrorBanner({ errors, label }: Props) {
  const real = errors.filter((e) => e instanceof Error) as Error[]
  if (real.length === 0) return null
  return (
    <div className="mb-3 rounded-md border border-[#FCA5A5] bg-[#FEF2F2] px-3 py-2 text-xs text-[#991B1B]">
      <strong>{label}</strong> — {real[0].message}. Try again or narrow the filters.
    </div>
  )
}
