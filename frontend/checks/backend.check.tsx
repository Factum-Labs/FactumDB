/**
 * Real frontend store → Python JSON-lines → SQLite integration.
 * Tauri IPC is substituted at the native boundary; Rust tests cover that bridge.
 * Render each screen against domain golden data as well as the live workflow.
 */
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync, existsSync, chmodSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join, sep } from 'node:path'
import { createInterface } from 'node:readline'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'
import { mockIPC, clearMocks } from '@tauri-apps/api/mocks'
import { useApp } from '../src/store'
import { request, display, type CaseData } from '../src/lib/backend'
import { CasesScreen, IntakeScreen, PipelineScreen, TimelineScreen, RecordHistoryScreen, ReconciliationScreen, GapsScreen, ProvenanceScreen, ReportScreen, SettingsScreen } from '../src/screens/ConnectedScreens'

const prefix = join(tmpdir(), 'factumdb-ui-check-')
const workspace = mkdtempSync(prefix)
const backend = resolve('../backend')
const python = process.env.FACTUMDB_PYTHON ?? (process.platform === 'win32' ? 'py' : 'python3')
const script = [
  'import sys',
  'from sidecar.desktop import DesktopRuntime',
  'from sidecar.protocol import serve',
  'runtime = DesktopRuntime(sys.argv[1])',
  'from pathlib import Path',
  'from types import SimpleNamespace',
  'from tests.application.test_desktop_runtime import tools',
  'tools(runtime, Path(sys.argv[1]), SimpleNamespace(setattr=lambda obj, name, value: setattr(obj, name, value)))',
  'router = runtime.router()',
  'def seed(payload):',
  '    from tests.fixtures.datasets import DS02',
  '    from tests.fixtures.pipeline import run_pipeline',
  '    result = run_pipeline(DS02)',
  '    stores = runtime.session(payload["case_id"])[1]',
  '    for stage in ("grouping", "correlation", "reconstruction", "reconciliation"):',
  '        getattr(stores.domain, "save_" + stage)(payload["case_id"], getattr(result, stage))',
  '    return runtime.case_data(payload)',
  'router.register("seed_test_results", seed)',
  'try: serve(sys.stdin, sys.stdout, router)',
  'finally: runtime.close()',
].join('\n')
const child = spawn(python, [...(python === 'py' ? ['-3.11'] : []), '-B', '-u', '-c', script, workspace], {
  cwd: backend, env: { ...process.env, PYTHONUTF8: '1' }, windowsHide: true, stdio: ['pipe', 'pipe', 'inherit'],
})
const lines = createInterface({ input: child.stdout })
let sequence = 0
const pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void }>()
lines.on('line', line => {
  const response = JSON.parse(line)
  const waiter = pending.get(response.request_id)
  if (!waiter) return
  pending.delete(response.request_id)
  if (response.ok) waiter.resolve(response.result)
  else waiter.reject(new Error(response.error_code + ': ' + response.error_message))
})
child.on('error', error => { for (const waiter of pending.values()) waiter.reject(error) })
child.on('exit', code => { for (const waiter of pending.values()) waiter.reject(new Error('Python exited: ' + code)) })
Object.assign(globalThis, { window: {}, isTauri: true })
mockIPC((command, args) => {
  assert.equal(command, 'backend_request')
  return new Promise((resolve, reject) => {
    const id = String(++sequence)
    pending.set(id, { resolve, reject })
    child.stdin.write(JSON.stringify({ request_id: id, command: args?.command, payload: args?.payload }) + '\n')
  })
})

let copy: string | undefined
const deadline = setTimeout(() => { child.kill(); throw new Error('Frontend integration check timed out') }, 30_000)
const originalSnapshotHook = React.useSyncExternalStore
try {
  await useApp.getState().initialize()
  assert.equal(useApp.getState().ready, true, useApp.getState().error ?? '')
  assert.equal(await useApp.getState().createCase('UI integration', 'Examiner'), true)
  const caseId = useApp.getState().data!.case.case_id
  const tablespace = join(workspace, 'accounts.ibd')
  const log = join(workspace, 'binlog.000001')
  writeFileSync(tablespace, 'test tablespace')
  writeFileSync(log, 'test binary log')
  assert.equal(await useApp.getState().registerEvidence([tablespace, log]), true)
  const evidence = useApp.getState().data!.tables.evidence_files[0]
  await useApp.getState().verifyEvidence(String(evidence.evidence_id))
  assert.equal(useApp.getState().data!.tables.evidence_files[0].verification_status, 'verified')
  copy = String(useApp.getState().data!.tables.evidence_files[0].working_copy_path)
  const cancelledWork = useApp.getState().runAllStages()
  await useApp.getState().cancelPipeline()
  await cancelledWork
  assert.equal(useApp.getState().data!.run!.stopped, true)
  assert.ok(useApp.getState().data!.run!.stages.some(s => s.status === 'cancelled'))
  await useApp.getState().resetPipeline()
  await useApp.getState().runAllStages()
  assert.equal(useApp.getState().pipelineComplete, true, useApp.getState().error ?? '')
  assert.equal(useApp.getState().stagesDone, 10)
  const exportPath = join(workspace, 'report.json')
  await useApp.getState().exportCase(exportPath)
  assert.ok(existsSync(exportPath))
  await useApp.getState().verifyEvidence('missing')
  assert.match(useApp.getState().error!, /NotFoundError/)
  assert.equal(useApp.getState().busy, false)
  await useApp.getState().resetPipeline()
  await useApp.getState().cancelPipeline()
  assert.equal(useApp.getState().data!.run!.stopped, true)
  assert.ok(useApp.getState().data!.run!.stages.every(s => s.status === 'cancelled'))
  await useApp.getState().openCase(caseId)
  assert.equal(useApp.getState().data!.case.case_name, 'UI integration')
  const seeded = await request<CaseData>('seed_test_results', { case_id: caseId })
  useApp.setState({ data: seeded, pipelineComplete: true, error: null })
  // SSR uses the hydration snapshot; render the state just returned by Python.
  React.useSyncExternalStore = (subscribe, getSnapshot) => originalSnapshotHook(subscribe, getSnapshot, getSnapshot)
  for (const Component of [CasesScreen, IntakeScreen, PipelineScreen, TimelineScreen, RecordHistoryScreen, ReconciliationScreen, GapsScreen, ProvenanceScreen, ReportScreen, SettingsScreen]) {
    const html = renderToStaticMarkup(<Component />)
    assert.ok(html.length > 100, Component.name)
  }
  assert.match(renderToStaticMarkup(<TimelineScreen />), /committed/)
  assert.match(renderToStaticMarkup(<RecordHistoryScreen />), /Committed log state/)
  assert.match(renderToStaticMarkup(<ReconciliationScreen />), /log-derived|Log-derived/)
  assert.equal(display({ __integer__: '9007199254740993' }), '9007199254740993')
  assert.equal(display({ __decimal__: '4000.10' }), '4000.10')
  assert.equal(display({ __unobserved__: true }), '[not observed]')
  assert.equal(display(null), 'NULL')
  console.log('PASS: frontend workflow, backend errors, cancellation, SQLite export, and all ten screen renderings.')
} finally {
  clearTimeout(deadline)
  React.useSyncExternalStore = originalSnapshotHook
  clearMocks()
  lines.close()
  child.stdin.end()
  await new Promise<void>(resolve => child.on('exit', () => resolve()))
  for (const evidence of useApp.getState().data?.tables.evidence_files ?? []) {
    const path = String(evidence.working_copy_path)
    if (existsSync(path)) chmodSync(path, 0o666)
  }
  if (copy && existsSync(copy)) chmodSync(copy, 0o666)
  const target = resolve(workspace)
  assert.ok(target.startsWith(resolve(prefix)) && target.startsWith(resolve(tmpdir()) + sep))
  rmSync(target, { recursive: true })
}
