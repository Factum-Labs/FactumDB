import { useEffect, useRef } from 'react'

// Bring a selected destination into view inside scrollable tables and lists.
export function useRevealRow(selection: string) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[data-selected="true"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [selection])
  return ref
}
