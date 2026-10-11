import { useApp } from '../store'
import { defaultPreferences, display, type Json, type Preferences } from './backend'

export function timezoneLabel(preferences: Preferences): string {
  if (preferences.time_mode === 'utc') return 'UTC'
  if (preferences.time_mode === 'local') return `Local · ${Intl.DateTimeFormat().resolvedOptions().timeZone}`
  const offset = preferences.utc_offset_minutes
  return `UTC${offset >= 0 ? '+' : '-'}${String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0')}:${String(Math.abs(offset) % 60).padStart(2, '0')} (fixed offset)`
}

export function formatTime(value: Json | undefined, preferences: Preferences): string {
  if (typeof value !== 'string') return display(value)
  // Only convert an instant with a recorded timezone. MySQL DATETIME values stay untouched.
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return `${value} (timezone unknown)`
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return value
  if (preferences.time_mode === 'local') {
    return new Intl.DateTimeFormat('en-GB', { year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZoneName: 'longOffset' }).format(date)
  }
  const offset = preferences.time_mode === 'custom' ? preferences.utc_offset_minutes : 0
  const shifted = new Date(date.getTime() + offset * 60000).toISOString().replace('T', ' ').replace('Z', '')
  return `${shifted} ${timezoneLabel(preferences)}`
}

export function useTimeDisplay() {
  const preferences = useApp(s => s.settings?.preferences ?? defaultPreferences)
  return { label: timezoneLabel(preferences), time: (value: Json | undefined) => formatTime(value, preferences) }
}
