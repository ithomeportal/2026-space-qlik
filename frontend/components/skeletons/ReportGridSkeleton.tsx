import { Skeleton } from "@/components/ui/skeleton"
import { ReportCardSkeleton } from "./ReportCardSkeleton"

export function ReportGridSkeleton() {
  return (
    <div className="space-y-10">
      {[1, 2].map((section) => (
        <div key={section}>
          <Skeleton className="mb-4 h-7 w-32" />
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <ReportCardSkeleton key={i} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
