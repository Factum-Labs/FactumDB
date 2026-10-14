import { ruleCatalogue } from '../data/ruleCatalogue'
import { RESULT_TONE } from '../data/types'
import { Badge } from './Badge'

export function RuleCatalogue({ compact = false }: { compact?: boolean }) {
  return <details className={'rounded-md border border-line bg-panel ' + (compact ? 'p-3 text-[11px]' : 'p-4')}>
    <summary className={'cursor-pointer font-medium ' + (compact ? 'text-[11px]' : 'text-xs')}>Rule catalogue</summary>
    <p className="mt-3 text-xs text-muted">All {ruleCatalogue.length} analysis rules. Descriptions are abbreviated; results apply where a rule assigns a classification.</p>
    <div role="region" aria-label="Rule catalogue table" tabIndex={0} className="mt-3 max-h-96 overflow-auto rounded border border-line">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Analysis rule catalogue with categories, short descriptions and results</caption>
        <thead className="sticky top-0 bg-thead text-dim"><tr>
          {['Rule', 'Category', 'Description', 'Result'].map(label => <th key={label} scope="col" className="px-3 py-2 font-semibold">{label}</th>)}
        </tr></thead>
        <tbody>{ruleCatalogue.map(rule => <tr key={rule.id} className="border-t border-line">
          <th scope="row" className="whitespace-nowrap px-3 py-2 font-mono font-normal">{rule.id}</th>
          <td className="whitespace-nowrap px-3 py-2 text-muted">{rule.category}</td>
          <td className="min-w-48 px-3 py-2">{rule.description}</td>
          <td className="px-3 py-2">{rule.result ? <Badge tone={RESULT_TONE[rule.result]}>{rule.result}</Badge> : <span className="text-muted" aria-label="No classification assigned">—</span>}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </details>
}
