import { createRoot } from 'react-dom/client'
import { GapsScreen } from '../src/screens/GapsScreen'
import { RecordHistoryScreen } from '../src/screens/RecordHistoryScreen'
import { useApp } from '../src/store'
import type { CaseData, Row } from '../src/lib/backend'

const findings: Row[] = Array.from({ length: 205 }, (_, index) => ({ rule_id: 'R-RECON-002', severity: 'notice',
  subject: { kind: 'field', id: `visits:${String(index).padStart(3, '0')}.status` },
  description: `Field comparison ${String(index).padStart(3, '0')}`, context: { record: `visits:${index}` },
  provenance: [{ tool_run_id: 'source-run', source_file: 'mysql-bin.000003', log_position: index }],
}))
findings.push(...Array.from({ length: 105 }, (_, index) => ({ rule_id: `R-Z-${String(index).padStart(3, '0')}`, severity: 'notice', subject: { kind: 'record', id: `visits:${index}` }, description: 'Additional notice', context: {}, provenance: [] })))
const data: CaseData = {
  case: { case_id: 'browser-case-a', case_name: 'Browser fixture', examiner: 'test', workspace_path: '', created_at: '' },
  tables: { evidence_files: [{ evidence_id: 'e1', filename: 'visits.ibd' }], tool_runs: [{ tool_run_id: 'source-run' }],
    warnings: Array.from({ length: 205 }, (_, index) => ({ warning_id: `w${String(index).padStart(3, '0')}`, code: 'DECODE', evidence_id: 'e1', tool_run_id: 'source-run', message: `Decode warning ${String(index).padStart(3, '0')}`, context_json: '{"column":"status"}', created_at: '2026-10-11' })),
  },
  analysis: { grouping: { coverage: { complete: false } } }, findings,
  finding_rules: { 'R-RECON-002': { title: 'Values agree under limited coverage', explanation: 'Matching values with incomplete coverage.', service: 'reconciliation' } }, run: null,
}
useApp.setState({ data, screen: 'gaps', tablePages: {}, ready: true })
export default function Fixture() {
  const screen = useApp(state => state.screen)
  const selectedTool = useApp(state => state.selectedTool)
  return <div className="p-4">
    <div className="mb-4 flex gap-4">
      <button onClick={() => useApp.getState().go('settings')}>Other screen</button>
      <button onClick={() => useApp.getState().go('gaps')}>Gaps screen</button>
      <button onClick={() => useApp.setState({ data: { ...data, case: { ...data.case, case_id: 'browser-case-b' } }, screen: 'gaps' })}>Other case</button>
      <button onClick={() => useApp.setState({ data: { ...data, analysis: { reconstruction: { histories: Array.from({ length: 205 }, (_, index) => ({
        record: { id: `visits:${index}`, table: 'visits', key: index }, method: 'primary_key_exact', steps: [],
      })) } } }, selectedRecord: 'visits:0', tablePages: {}, screen: 'record' })}>Record screen</button>
    </div>
    {screen === 'gaps' ? <GapsScreen /> : screen === 'record' ? <RecordHistoryScreen /> : <p>Screen {screen} · Selected tool {selectedTool}</p>}
  </div>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
