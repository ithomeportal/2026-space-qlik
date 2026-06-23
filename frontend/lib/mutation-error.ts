"use client"

import { toast } from "sonner"

/**
 * Standard `onError` handler for React Query mutations. Surfaces a red toast so
 * a failed Save/Delete is visible to the user instead of silently re-enabling
 * the button (the failure mode Bruno hit on the Bonus Calculator, 2026-06-23).
 *
 * @param action short verb phrase, e.g. "Save FX" → toast reads "Save FX failed".
 */
export function mutationErrorToast(action: string) {
  return (error: unknown) => {
    const msg = error instanceof Error ? error.message : "Unexpected error"
    toast.error(`${action} failed`, {
      description: /^API error:/i.test(msg)
        ? "The server rejected the request — please retry."
        : msg,
    })
  }
}
