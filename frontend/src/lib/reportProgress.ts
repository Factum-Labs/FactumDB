export interface ReportProgressDetails { label: string; amount: string }

export function reportProgressDetails(stage: string, processed: number, unit?: string): ReportProgressDetails {
  if (stage === 'resuming' || stage === 'starting') return {
    label: `${stage === 'resuming' ? 'Resuming' : 'Starting'} report preparation…`, amount: '',
  }
  const label = stage.replaceAll('_', ' ')
  const title = label.charAt(0).toUpperCase() + label.slice(1)
  const activeLabel = /^(reading|rendering|finalizing)\b/.test(label) ? title : `Preparing ${label}`
  const amount = unit === 'bytes'
    ? `${(processed / 1_000_000).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} MB`
    : `${processed.toLocaleString()} ${unit === 'pages' ? 'pages' : 'entries'}`
  return { label: activeLabel, amount: `${amount} processed` }
}

export function reportProgress(stage: string, processed: number, unit?: string): string {
  const details = reportProgressDetails(stage, processed, unit)
  return [details.label, details.amount].filter(Boolean).join(' · ')
}
