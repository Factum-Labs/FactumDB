/** Exercise settings controls in a browser; Python tests cover persistence and archive recovery. */
import React from 'react'
import { createRoot } from 'react-dom/client'
import { mockIPC } from '@tauri-apps/api/mocks'
import App from '../src/App'
import { defaultPreferences, type Settings } from '../src/lib/backend'
import { useApp } from '../src/store'

let locked = false
let settings: Settings = { workspace: 'C:/FactumDB/workspace', profile: {}, preferences: defaultPreferences,
  tools: { innochecksum_path: 'innochecksum', ibd2sdi_path: 'ibd2sdi', ibd2sql_path: '', mysqlbinlog_path: 'mysqlbinlog', python_path: 'python', include_deleted: false } }
let changedPassword = false
let restoreCount = 0
let deleteCount = 0
Object.assign(globalThis, { isTauri: true })
Object.assign(globalThis, { setSharedWorkspace: () => useApp.setState({
  settings: { ...settings, workspace_operations_available: false },
}) })
mockIPC((command, args) => {
  if (command === 'pick_backup_path') return args?.restore ? 'C:/backups/workspace.fdbbackup' : 'C:/backups/new.fdbbackup'
  if (command === 'open_workspace') return null
  if (command !== 'backend_request') throw new Error(`Unexpected native command ${command}`)
  const payload = args?.payload as Record<string, unknown>
  switch (args?.command) {
    case 'auth_status': return { user: { username: 'Examiner' }, locked }
    case 'auth_touch': return { active: true }
    case 'get_settings': return settings
    case 'list_cases': return []
    case 'delete_case':
      if (payload.case_id !== 'delete-browser-case' || payload.confirmation !== 'Browser case') throw new Error('Invalid delete confirmation')
      deleteCount++; return { deleted: true, case_id: payload.case_id }
    case 'configure_profile': settings = { ...settings, profile: payload }; return settings
    case 'configure_preferences': settings = { ...settings, preferences: payload as unknown as Settings['preferences'] }; return settings
    case 'change_password':
      if (payload.current_password !== 'Current password 123') throw new Error('AuthenticationError: Incorrect password')
      if (payload.new_password !== payload.password_confirmation) throw new Error('ValueError: Passwords do not match')
      changedPassword = true; return { changed: true }
    case 'auth_lock': locked = true; return { locked }
    case 'auth_unlock':
      if (payload.password !== 'Current password 123') throw new Error('AuthenticationError: Incorrect password')
      locked = false; return { user: { username: 'Examiner' } }
    case 'storage_usage': return { total_bytes: 2048, free_bytes: 1024 ** 3, cases: {}, categories: { working: 1024, databases_and_settings: 1024 } }
    case 'backup_workspace': return { path: payload.path, files: 3 }
    case 'inspect_workspace_backup': return { created_at: '2026-10-11T00:00:00+00:00', case_count: 2, total_bytes: 4096, sha256: 'preview-hash', original_evidence_included: false }
    case 'restore_workspace':
      if (payload.current_password !== 'Current password 123' || payload.sha256 !== 'preview-hash') throw new Error('Invalid restore confirmation')
      restoreCount++; return { restored: true, rollback_path: 'C:/FactumDB/workspace.rollback-test' }
    default: throw new Error(`Unexpected backend command ${args?.command}`)
  }
})
useApp.setState({ user: { username: 'Examiner' }, authChecked: true, ready: true, settings, screen: 'settings' })
createRoot(document.getElementById('root')!).render(<App />)

const waitFor = async (condition: () => boolean) => {
  const started = Date.now()
  while (!condition()) {
    if (Date.now() - started > 5000) throw new Error('Browser condition timed out')
    await new Promise(resolve => setTimeout(resolve, 20))
  }
}
function assert(condition: unknown, message: string): asserts condition { if (!condition) throw new Error(message) }
function button(text: string) {
  const element = [...document.querySelectorAll('button')].find(button => button.textContent?.trim() === text)
  assert(element, `Button missing: ${text}`); return element
}
function input(label: string) {
  const element = [...document.querySelectorAll('label')].find(element => element.textContent?.trim().startsWith(label))?.querySelector('input, select')
  assert(element instanceof HTMLInputElement || element instanceof HTMLSelectElement, `Field missing: ${label}`); return element
}
async function fill(label: string, value: string) {
  const element = input(label)
  const prototype = element instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLSelectElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value)
  element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 0))
}
async function submit(text: string, condition: () => boolean) {
  await waitFor(() => !button(text).disabled)
  button(text).click()
  try { await waitFor(() => condition() && !useApp.getState().busy) } catch { throw new Error(`Action timed out: ${text}. ${document.body.textContent}`) }
  await new Promise(resolve => setTimeout(resolve, 0))
}

Object.assign(window, { runSettingsChecks: async () => {
  await waitFor(() => !!document.querySelector('h2'))
  await waitFor(() => !!document.body.textContent?.includes('2 KB'))
  assert(document.body.textContent?.includes('Workspace breakdown'), 'Storage usage loads automatically when Settings opens')
  await fill('Display name', 'Dr Browser Examiner'); await fill('Organization', 'Browser Lab'); await fill('Examiner ID', 'EX-42')
  await submit('Save profile', () => settings.profile?.display_name === 'Dr Browser Examiner')
  await fill('Current password', 'Current password 123'); await fill('New password', 'Changed password 456'); await fill('Confirm new password', 'Changed password 456')
  await submit('Change password', () => changedPassword)
  await waitFor(() => (input('New password') as HTMLInputElement).value === '')
  await fill('Timestamp display', 'custom')
  await waitFor(() => document.body.textContent!.includes('UTC offset (minutes'))
  await fill('UTC offset (minutes', '330')
  await submit('Save preferences', () => settings.preferences?.utc_offset_minutes === 330)
  assert(document.body.textContent?.includes('UTC+05:30'), 'Custom timezone preview is visible')
  await submit('Refresh usage', () => !!document.body.textContent?.includes('2 KB'))
  await submit('Create workspace backup', () => !!document.body.textContent?.includes('Backup verified and saved'))
  await submit('Select backup to restore', () => !!document.body.textContent?.includes('Restore preview'))
  assert(button('Restore workspace').disabled, 'Restore requires explicit confirmation and a password')
  input('Replace the workspace with this backup').click(); await fill('Current account password', 'Current password 123')
  await waitFor(() => !button('Restore workspace').disabled)
  // Lock hides all settings, including the restore password and workspace path.
  button('Lock').click()
  await waitFor(() => document.body.textContent!.includes('Session locked'))
  assert(!document.body.textContent!.includes('C:/FactumDB/workspace'), 'Workspace is hidden while locked')
  await fill('Password', 'incorrect')
  await submit('Unlock', () => !!document.body.textContent?.includes('Incorrect password'))
  await fill('Password', 'Current password 123')
  await submit('Unlock', () => !!document.body.textContent?.includes('Examiner profile'))
  assert(document.body.textContent?.includes('UTC+05:30'), 'Preferences survive unlocking')
  await submit('Select backup to restore', () => !!document.body.textContent?.includes('Restore preview'))
  input('Replace the workspace with this backup').click(); await fill('Current account password', 'Current password 123')
  await submit('Restore workspace', () => restoreCount === 1 && !!document.body.textContent?.includes('Sign in to FactumDB'))
  assert(document.body.textContent?.includes('workspace.rollback-test'), 'Rollback location is visible after restore')
  useApp.setState({ user: { username: 'Examiner' }, settings, ready: true, screen: 'cases', notice: null,
    cases: [{ id: 'delete-browser-case', name: 'Browser case', examiner: 'Examiner', opened: '2026-10-11', files: 0, status: 'Registered', workspace: 'C:/FactumDB/workspace/cases/delete-browser-case' }] })
  await waitFor(() => !!document.querySelector('[aria-label="Delete case Browser case"]'))
  button('Delete').click()
  await waitFor(() => !!document.querySelector('dialog[open]'))
  assert(button('Delete case').disabled, 'Deletion requires the exact case name')
  button('Cancel').click()
  await waitFor(() => !document.querySelector('dialog'))
  assert(deleteCount === 0, 'Cancel does not delete the case')
  button('Delete').click()
  await waitFor(() => !!document.querySelector('dialog[open]'))
  await fill('Type the case name to confirm', 'Wrong case')
  assert(button('Delete case').disabled, 'A different case name cannot confirm deletion')
  await fill('Type the case name to confirm', 'Browser case')
  await submit('Delete case', () => deleteCount === 1 && useApp.getState().cases.length === 0)
  await waitFor(() => !document.querySelector('dialog'))
  // Leave settings visible for the screenshot.
  useApp.setState({ user: { username: 'Examiner' }, settings, ready: true, screen: 'settings', notice: null })
  await waitFor(() => document.body.textContent!.includes('Examiner profile'))
  return true
} })
