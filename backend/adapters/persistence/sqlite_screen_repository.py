"""Rebuildable desktop indexes. Archival analysis JSON remains authoritative.

Indexes are written with analysis, not recomputed on each case opening. Older
cases use bounded SQLite projections; opening them never rebuilds whole indexes.
"""
import json
import hashlib
from collections import Counter

from adapters.persistence._reconciliation import compact, references
from core.application.errors import NotFoundError


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class ScreenRepository:
    def __init__(self, connection):
        self.connection = connection

    def rebuild(self, case_id, stage, data):
        from sidecar.views import _findings
        c = self.connection
        c.execute('DELETE FROM screen_items WHERE case_id=? AND stage=?', (case_id, stage))
        c.execute('DELETE FROM screen_summary WHERE case_id=? AND stage=?', (case_id, stage))
        c.execute('DELETE FROM screen_coverage WHERE case_id=? AND stage=?', (case_id, stage))
        if 'coverage' in data:
            c.execute('INSERT INTO screen_coverage VALUES (?,?,?)', (case_id, stage, dumps(data['coverage'])))
        items = []
        def add(kind, ordinal, identity, bucket, summary, detail):
            encoded = dumps(summary)
            items.append((case_id, stage, kind, ordinal, str(identity), bucket, encoded, encoded if summary is detail else dumps(detail)))
        summary = {}
        if stage == 'grouping':
            transactions = data.get('transactions', [])
            summary = dict(transactions=len(transactions), gaps=len(data.get('coverage', {}).get('gaps', [])))
            for i, tx in enumerate(transactions):
                small = {key: tx.get(key) for key in ('id', 'status', 'source_file', 'start_position', 'commit_timestamp')}
                small['event_count'] = len(tx.get('events', []))
                # Event pages are separate, so a large transaction cannot monopolize IPC.
                detail = {key: value for key, value in tx.items() if key != 'events'}
                detail['event_count'] = small['event_count']
                add('transactions', i, tx['id'], tx.get('status', ''), small, detail)
                for n, event in enumerate(tx.get('events', [])):
                    add('events', n, n, tx['id'], event, event)
        elif stage == 'correlation':
            summary = dict(records=len(data.get('records', [])))
            # Graph inputs are only requested on explicit expansion.
            for kind in ('records', 'edges'):
                for i, row in enumerate(data.get(kind, [])):
                    keys = ('record','method') if kind=='records' else ('tx_id','record_id','event_type')
                    small = {key:row.get(key) for key in keys}
                    add('graph_' + kind, i, i, '', small, small)
        elif stage == 'reconstruction':
            histories = data.get('histories', [])
            summary = dict(histories=len(histories))
            for i, history in enumerate(histories):
                record = history['record']
                small = dict(record=record, method=history.get('method'), step_count=len(history.get('steps', [])))
                detail = {key: value for key, value in history.items() if key != 'steps'}
                detail['step_count'] = small['step_count']
                detail['steps_paginated'] = True
                add('histories', i, record['id'], record['table'], small, detail)
                for n, step in enumerate(history.get('steps', [])):
                    add('history_steps', n, n, dumps([record['table'], record['id']]), step, step)
        elif stage == 'reconciliation':
            is_compact = compact(data)
            pool = data.get('finding_pool', [])
            if is_compact:
                c.execute('DELETE FROM screen_finding_pool WHERE case_id=?', (case_id,))
                c.executemany('INSERT INTO screen_finding_pool VALUES (?,?,?)', ((case_id, i, dumps(f)) for i, f in enumerate(pool)))
            fields = data.get('rows', [])
            counts = Counter()
            for i, row in enumerate(fields):
                detail = dict(row)
                small = {key: row.get(key) for key in ('record_id', 'field', 'log_display', 'phys_display', 'result', 'rule_id')}
                add('comparisons', i, row['record_id'], str(row['field']), small, detail)
            for i, record in enumerate(data.get('records', [])):
                refs = record.get('field_refs', []) if is_compact else record.get('fields', [])
                small = dict(record_id=record['record']['id'], result=record['rollup'], summary=record.get('rollup_label'),
                             rule_id=record.get('rollup_rule_id'), field_count=len(refs))
                counts[record['rollup']] += 1
                add('reconciliation', i, small['record_id'], record['rollup'], small, small)
            summary = dict(comparisons=len(fields), exact=sum(r.get('result') == 'Exact' for r in fields),
                           unresolved=sum(r.get('result') == 'Unresolved' for r in fields), counts=dict(counts),
                           )
        found = {}
        findings = references(data['finding_refs'], data['finding_pool'], 'finding_refs') if stage == 'reconciliation' and compact(data) else data.get('findings', [])
        for finding in findings:
            if finding.get('severity') != 'info':
                _findings(finding, found)
        for i, finding in enumerate(found.values()):
            bucket = dumps([finding['rule_id'], finding['severity']])
            identity = hashlib.sha256(dumps(finding).encode()).hexdigest()
            add('findings', i, identity, bucket, finding, finding)
        c.executemany('INSERT INTO screen_items VALUES (?,?,?,?,?,?,?,?)', items)
        if stage == 'reconciliation':
            summary['storage_header'] = {key: data[key] for key in ('storage_format', 'storage_version') if key in data}
        summary['indexed'] = True
        c.execute('INSERT INTO screen_summary VALUES (?,?,?)', (case_id, stage, dumps(summary)))
        self.refresh_groups(case_id)

    def refresh_groups(self, case_id):
        if not self.ensure(case_id, ('grouping', 'correlation', 'reconstruction', 'reconciliation')):
            self.connection.execute('DELETE FROM screen_group_ready WHERE case_id=?', (case_id,))
            self.connection.execute('DELETE FROM screen_groups WHERE case_id=?', (case_id,))
            return
        groups = self._groups(case_id)
        self.connection.execute('DELETE FROM screen_groups WHERE case_id=?', (case_id,))
        self.connection.executemany('INSERT INTO screen_groups VALUES (?,?,?)', ((case_id, i, dumps(group)) for i, group in enumerate(groups)))
        self.connection.execute('INSERT OR REPLACE INTO screen_group_ready VALUES (?)', (case_id,))

    def ensure(self, case_id, stages):
        saved = self.summaries(case_id)
        return all(saved.get(stage, {}).get('indexed') or not self.connection.execute('SELECT 1 FROM analysis_results WHERE case_id=? AND stage=?', (case_id, stage)).fetchone() for stage in stages)

    def legacy_summary(self, case_id, stage):
        saved = self.summaries(case_id)
        if stage in saved and (stage != 'reconciliation' or 'comparisons' in saved[stage]):
            return saved[stage]
        paths = {'grouping': ('transactions',), 'correlation': ('records',), 'reconstruction': ('histories',), 'reconciliation': ()}[stage]
        pairs = ','.join(f"'{path}',json_array_length(result_json,'$.{path}')" for path in paths)
        row = self.connection.execute(f'SELECT json_object({pairs}) FROM analysis_results WHERE case_id=? AND stage=?', (case_id, stage)).fetchone()
        if not row:
            return {}
        summary = dict(saved.get(stage, json.loads(row[0])))
        if stage == 'grouping':
            summary['gaps'] = self.connection.execute("SELECT json_array_length(result_json,'$.coverage.gaps') FROM analysis_results WHERE case_id=? AND stage=?", (case_id, stage)).fetchone()[0]
        if stage == 'reconciliation':
            if 'counts' not in summary:
                summary['counts'] = dict(self.connection.execute("SELECT json_extract(j.value,'$.rollup'),count(*) FROM analysis_results a,json_each(a.result_json,'$.records') j WHERE a.case_id=? AND a.stage=? GROUP BY json_extract(j.value,'$.rollup')", (case_id, stage)))
            values = dict(self.connection.execute("SELECT json_extract(j.value,'$.result'),count(*) FROM analysis_results a,json_each(a.result_json,'$.rows') j WHERE a.case_id=? AND a.stage=? GROUP BY json_extract(j.value,'$.result')", (case_id, stage)))
            summary['comparisons'] = sum(values.values())
            summary['exact'], summary['unresolved'] = values.get('Exact', 0), values.get('Unresolved', 0)
        with self.connection:
            self.connection.execute('INSERT OR REPLACE INTO screen_summary VALUES (?,?,?)', (case_id, stage, dumps(summary)))
        return summary

    def _finding_source(self, is_compact):
        # Materialize pool/refs once, avoiding a full JSON parse for each finding.
        compact_where = "a.case_id=:case_id AND a.stage='reconciliation'" if is_compact else '0'
        expanded_where = "a.case_id=:case_id AND a.stage!='reconciliation'" if is_compact else 'a.case_id=:case_id'
        return f'''WITH pool AS MATERIALIZED (
            SELECT a.stage,p.key,p.value FROM analysis_results a,json_each(a.result_json,'$.finding_pool') p WHERE {compact_where} AND json_extract(p.value,'$.severity')!='info'),
          refs AS MATERIALIZED (SELECT a.stage,r.value FROM analysis_results a,json_each(a.result_json,'$.finding_refs') r WHERE {compact_where}),
          combined AS (
            SELECT p.value FROM refs r JOIN pool p ON p.stage=r.stage AND p.key=r.value
            UNION ALL SELECT j.value FROM analysis_results a,json_each(a.result_json,'$.findings') j WHERE {expanded_where} AND json_extract(j.value,'$.severity')!='info'),
          findings AS (SELECT min(value) AS value FROM combined WHERE json_extract(value,'$.severity')!='info'
            GROUP BY json_extract(value,'$.rule_id'),json_extract(value,'$.severity'),json_extract(value,'$.subject'),json_extract(value,'$.context'),json_extract(value,'$.provenance')) '''

    def _cache_storage_header(self, case_id, is_compact):
        from adapters.persistence._reconciliation import STORAGE_FORMAT, STORAGE_VERSION
        header = dict(storage_format=STORAGE_FORMAT, storage_version=STORAGE_VERSION) if is_compact else {}
        self.connection.execute(
            "INSERT INTO screen_summary VALUES (?,'reconciliation',?) "
            "ON CONFLICT(case_id,stage) DO UPDATE SET summary_json=json_set(summary_json,'$.storage_header',json(?))",
            (case_id, dumps(dict(storage_header=header)), dumps(header)),
        )

    def _ensure_legacy_findings(self, case_id):
        if self.connection.execute("SELECT 1 FROM screen_legacy_ready WHERE case_id=? AND kind='findings'", (case_id,)).fetchone():
            if 'storage_header' not in self.summaries(case_id).get('reconciliation', {}):
                from sidecar.views import _compact_storage
                with self.connection:
                    self._cache_storage_header(case_id, _compact_storage(self.connection, case_id))
            return
        from sidecar.views import _compact_storage
        is_compact=_compact_storage(self.connection, case_id)
        if is_compact:
            size = self.connection.execute("SELECT json_array_length(result_json,'$.finding_pool') FROM analysis_results WHERE case_id=? AND stage='reconciliation'", (case_id,)).fetchone()[0]
            invalid = self.connection.execute("SELECT 1 FROM analysis_results a,json_each(a.result_json,'$.finding_refs') r WHERE a.case_id=? AND a.stage='reconciliation' AND (r.type!='integer' OR r.value<0 OR r.value>=?) LIMIT 1", (case_id,size)).fetchone()
            if invalid:
                raise ValueError('Invalid finding reference in saved reconciliation')
        with self.connection:
            self._cache_storage_header(case_id, is_compact)
            self.connection.execute(self._finding_source(is_compact) + "INSERT INTO screen_legacy_findings SELECT :case_id,row_number() OVER (),json_extract(value,'$.rule_id'),json_extract(value,'$.severity'),json_array(coalesce(json_extract(value,'$.subject.kind'),''),coalesce(json_extract(value,'$.subject.id'),'')),value FROM findings", dict(case_id=case_id))
            self.connection.execute("INSERT INTO screen_legacy_ready VALUES (?,'findings')", (case_id,))

    def _legacy_page(self, case_id, kind, offset, limit, bucket, identity):
        from sidecar.views import _findings
        if kind == 'findings':
            self._ensure_legacy_findings(case_id)
            args = dict(case_id=case_id, offset=offset, limit=limit, rule=None, severity=None)
            if bucket is not None:
                args['rule'], args['severity'] = json.loads(bucket)
            where = "case_id=:case_id AND (:rule IS NULL OR rule=:rule AND severity=:severity)"
            total = self.connection.execute(f'SELECT count(*) FROM screen_legacy_findings WHERE {where}', args).fetchone()[0]
            found = {}
            for row in self.connection.execute(f"SELECT finding_json FROM screen_legacy_findings WHERE {where} ORDER BY ordinal LIMIT :limit OFFSET :offset", args):
                _findings(json.loads(row[0]), found)
            return dict(items=list(found.values()), total=total, offset=offset, limit=limit, summaries=self.summaries(case_id))
        stage, array, fields, extra, bucket_path, id_path = {
            'transactions': ('grouping', 'transactions', ('id','status','source_file','start_position','commit_timestamp'), {'event_count': "json_array_length(j.value,'$.events')"}, '$.status', '$.id'),
            'histories': ('reconstruction', 'histories', ('record','method'), {'step_count': "json_array_length(j.value,'$.steps')"}, '$.record.table', '$.record.id'),
            'reconciliation': ('reconciliation','records', (), {'record_id': "json_extract(j.value,'$.record.id')", 'result': "json_extract(j.value,'$.rollup')", 'summary': "json_extract(j.value,'$.rollup_label')", 'rule_id': "json_extract(j.value,'$.rollup_rule_id')", 'field_count': "coalesce(json_array_length(j.value,'$.field_refs'),json_array_length(j.value,'$.fields'))"}, '$.rollup', '$.record.id'),
            'comparisons': ('reconciliation','rows', ('record_id','field','log_display','phys_display','result','rule_id'), {}, '$.field', '$.record_id'),
            'graph_records': ('correlation','records', ('record','method'), {}, '$.record.table', '$.record.id'),
            'graph_edges': ('correlation','edges', ('tx_id','record_id','event_type'), {}, '$.event_type', '$.record_id'),
        }.get(kind, (None, None, None, None, None, None))
        if kind in {'events', 'history_steps'}:
            stage, parent, id_path = ('grouping','transactions','$.id') if kind=='events' else ('reconstruction','histories','$.record.id')
            table, selected = (None, bucket) if kind=='events' else json.loads(bucket)
            source = "analysis_results a,json_each(a.result_json,?) parent,json_each(parent.value,?) j"
            args = [f'$.{parent}', '$.events' if kind=='events' else '$.steps', case_id, stage, id_path, selected, table, table]
            where = "a.case_id=? AND a.stage=? AND json_extract(parent.value,?)=? AND (? IS NULL OR json_extract(parent.value,'$.record.table')=?)"
            total = self.connection.execute(f'SELECT count(*) FROM {source} WHERE {where}', args).fetchone()[0]
            items = [json.loads(r[0]) for r in self.connection.execute(f'SELECT j.value FROM {source} WHERE {where} LIMIT ? OFFSET ?', [*args,limit,offset])]
        else:
            pairs = [f"'{key}',json_extract(j.value,'$.{key}')" for key in fields] + [f"'{key}',{value}" for key,value in extra.items()]
            # Older cases get only cheap projected rows, not expanded detail copies.
            # This SQL-only index is reusable by later pages and optional graphs.
            if not self.connection.execute('SELECT 1 FROM screen_legacy_ready WHERE case_id=? AND kind=?', (case_id,kind)).fetchone():
                with self.connection:
                    self.connection.execute(f"INSERT INTO screen_legacy_pages SELECT a.case_id,?,cast(j.key AS INTEGER),json_extract(j.value,?),json_extract(j.value,?),json_object({','.join(pairs)}) FROM analysis_results a,json_each(a.result_json,?) j WHERE a.case_id=? AND a.stage=?",
                                            (kind,id_path,bucket_path,f'$.{array}',case_id,stage))
                    self.connection.execute('INSERT INTO screen_legacy_ready VALUES (?,?)', (case_id,kind))
            where,args = 'case_id=? AND kind=?', [case_id,kind]
            if bucket is not None:
                where += ' AND bucket=?'; args.append(bucket)
            if identity is not None:
                where += ' AND identity=?'; args.append(identity)
            total = self.connection.execute(f'SELECT count(*) FROM screen_legacy_pages WHERE {where}', args).fetchone()[0]
            items = [json.loads(r[0]) for r in self.connection.execute(f'SELECT summary_json FROM screen_legacy_pages WHERE {where} ORDER BY ordinal LIMIT ? OFFSET ?', [*args,limit,offset])]
        if stage == 'reconciliation':
            # Rollup cards count records. Do not scan every field comparison just
            # to display the main record table or one expanded record.
            saved = self.summaries(case_id).get(stage, {})
            if kind == 'reconciliation' and 'counts' not in saved:
                saved['counts'] = dict(self.connection.execute("SELECT bucket,count(*) FROM screen_legacy_pages WHERE case_id=? AND kind='reconciliation' GROUP BY bucket", (case_id,)))
                with self.connection:
                    self.connection.execute('INSERT OR REPLACE INTO screen_summary VALUES (?,?,?)', (case_id,stage,dumps(saved)))
        else:
            self.legacy_summary(case_id, stage)
        return dict(items=items, total=total, offset=offset, limit=limit, summaries=self.summaries(case_id))

    def summaries(self, case_id):
        return {r[0]: json.loads(r[1]) for r in self.connection.execute('SELECT stage, summary_json FROM screen_summary WHERE case_id=?', (case_id,))}

    def page(self, case_id, kind, offset=0, limit=100, bucket=None, identity=None):
        stages = {'transactions': ('grouping',), 'events': ('grouping',), 'histories': ('reconstruction',), 'history_steps': ('reconstruction',),
                  'reconciliation': ('reconciliation',), 'comparisons': ('reconciliation',),
                  'findings': ('grouping', 'correlation', 'reconstruction', 'reconciliation'),
                  'graph_records': ('correlation',), 'graph_edges': ('correlation',)}
        if kind not in stages:
            raise ValueError('Unsupported screen page')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('offset must be nonnegative and limit must be 1–100')
        if bucket is not None and not isinstance(bucket, str) or identity is not None and not isinstance(identity, str):
            raise ValueError('Filters must be strings')
        if not self.ensure(case_id, stages[kind]):
            return self._legacy_page(case_id, kind, offset, limit, bucket, identity)
        where, args = 'case_id=? AND kind=?', [case_id, kind]
        if bucket is not None:
            where += ' AND bucket=?'; args.append(bucket)
        if identity is not None:
            where += ' AND identity=?'; args.append(identity)
        # Findings are deduplicated across analysis stages using their exact identity.
        source = f'(SELECT identity, min(summary_json) AS summary_json, min(ordinal) AS ordinal FROM screen_items WHERE {where} GROUP BY identity)' if kind == 'findings' else f'(SELECT summary_json, ordinal FROM screen_items WHERE {where})'
        total = self.connection.execute(f'SELECT count(*) FROM {source}', args).fetchone()[0]
        result = [json.loads(r[0]) for r in self.connection.execute(f'SELECT summary_json FROM {source} ORDER BY ordinal LIMIT ? OFFSET ?', [*args, limit, offset])]
        return dict(items=result, total=total, offset=offset, limit=limit, summaries=self.summaries(case_id))

    def detail(self, case_id, kind, identity, bucket=None):
        stages = {'transactions': 'grouping', 'histories': 'reconstruction', 'comparisons': 'reconciliation'}
        if kind not in stages:
            raise ValueError('Unsupported screen detail')
        if not self.ensure(case_id, (stages[kind],)):
            from sidecar.views import analysis_detail
            legacy_kind = {'transactions':'transaction','histories':'history','comparisons':'comparison'}[kind]
            if kind == 'comparisons':
                return analysis_detail(self.connection, case_id, legacy_kind, identity, field=bucket)['detail']
            array,path = ('transactions','$.id') if kind=='transactions' else ('histories','$.record.id')
            projection = "json_set(json_remove(j.value,'$.events'),'$.event_count',json_array_length(j.value,'$.events'))" if kind=='transactions' else 'j.value'
            row = self.connection.execute(f"SELECT {projection} FROM analysis_results a,json_each(a.result_json,?) j WHERE a.case_id=? AND a.stage=? AND json_extract(j.value,?)=? AND (? IS NULL OR json_extract(j.value,'$.record.table')=?) LIMIT 1",
                                           (f'$.{array}',case_id,stages[kind],path,identity,bucket if kind=='histories' else None,bucket if kind=='histories' else None)).fetchone()
            if row is None:
                raise NotFoundError('Selected item not found')
            detail = json.loads(row[0])
            if kind == 'transactions':
                detail.pop('events', None)
            if kind == 'histories':
                detail['step_count'] = len(detail.get('steps', [])); detail['steps_paginated'] = True
                detail['steps'] = detail.get('steps', [])[:101]
                detail.pop('events', None)
            return detail
        matches = self.connection.execute('SELECT detail_json FROM screen_items WHERE case_id=? AND kind=? AND identity=? AND (? IS NULL OR bucket=?)',
                                          (case_id, kind, identity, bucket, bucket)).fetchall()
        if len(matches) != 1:
            raise NotFoundError('Detail not found or identity is ambiguous')
        detail = json.loads(matches[0][0])
        if kind == 'comparisons' and 'finding_refs' in detail:
            refs = detail.pop('finding_refs')
            findings = []
            for ref in refs:
                if type(ref) is not int or ref < 0:
                    raise ValueError('Invalid comparison finding reference')
                row = self.connection.execute('SELECT finding_json FROM screen_finding_pool WHERE case_id=? AND ordinal=?', (case_id, ref)).fetchone()
                if row is None:
                    raise ValueError('Missing comparison finding reference')
                findings.append(json.loads(row[0]))
            detail['findings'] = findings
        if kind == 'histories':
            key = dumps([detail['record']['table'], detail['record']['id']])
            detail['steps'] = [json.loads(r[0]) for r in self.connection.execute('SELECT detail_json FROM screen_items WHERE case_id=? AND kind=? AND bucket=? ORDER BY ordinal LIMIT 101',
                                                                               (case_id, 'history_steps', key))]
        return detail

    def locate(self, case_id, kind, identity, bucket=None):
        stage = {'transactions': 'grouping', 'reconciliation': 'reconciliation'}
        if kind not in stage:
            raise ValueError('Unsupported screen location')
        if not self.ensure(case_id, (stage[kind],)):
            array, path = ('transactions', '$.id') if kind=='transactions' else ('records','$.record.id')
            row = self.connection.execute("SELECT cast(j.key AS INTEGER) FROM analysis_results a,json_each(a.result_json,?) j WHERE a.case_id=? AND a.stage=? AND json_extract(j.value,?)=? LIMIT 1", (f'$.{array}',case_id,stage[kind],path,identity)).fetchone()
            if row is None:
                raise NotFoundError('Selected item not found')
            return dict(offset=row[0] // 100 * 100)
        row = self.connection.execute('SELECT ordinal FROM screen_items WHERE case_id=? AND kind=? AND identity=? AND (? IS NULL OR bucket=?)',
                                      (case_id, kind, identity, bucket, bucket)).fetchone()
        if row is None:
            raise NotFoundError('Selected item not found')
        index = self.connection.execute('SELECT count(*) FROM screen_items WHERE case_id=? AND kind=? AND ordinal<? AND (? IS NULL OR bucket=?)',
                                        (case_id, kind, row[0], bucket, bucket)).fetchone()[0]
        return dict(offset=index // 100 * 100)

    def groups(self, case_id):
        indexed = self.ensure(case_id, ('grouping', 'correlation', 'reconstruction', 'reconciliation'))
        if not self.connection.execute('SELECT 1 FROM screen_group_ready WHERE case_id=?', (case_id,)).fetchone():
            with self.connection:
                if indexed:
                    self.refresh_groups(case_id)
                else:
                    from core.domain.rules import RULES
                    self._ensure_legacy_findings(case_id)
                    groups = []
                    for rule,severity,count,subjects in self.connection.execute('SELECT rule,severity,count(*),count(DISTINCT subject_json) FROM screen_legacy_findings WHERE case_id=? GROUP BY rule,severity', (case_id,)):
                        definition = RULES.get(rule)
                        groups.append(dict(id=dumps([rule,severity]),rule=rule,severity=severity,occurrences=count,subjects=subjects,title=definition.title if definition else rule,
                                           explanation=definition.statement if definition else '',service=definition.service if definition else '',entries=[],toolRunIds=[]))
                    rank = {'warning':0,'notice':1,'info':2}
                    groups.sort(key=lambda g: (rank.get(g['severity'],3),g['rule'],g['severity']))
                    self.connection.execute('DELETE FROM screen_groups WHERE case_id=?', (case_id,))
                    self.connection.executemany('INSERT INTO screen_groups VALUES (?,?,?)', ((case_id,i,dumps(group)) for i,group in enumerate(groups)))
                    self.connection.execute('INSERT OR REPLACE INTO screen_group_ready VALUES (?)', (case_id,))
        return [json.loads(r[0]) for r in self.connection.execute('SELECT group_json FROM screen_groups WHERE case_id=? ORDER BY ordinal', (case_id,))]

    def _groups(self, case_id):
        from core.domain.rules import RULES
        result = []
        for bucket, count, subjects in self.connection.execute('''SELECT bucket, count(*), count(DISTINCT json_array(coalesce(json_extract(summary_json,'$.subject.kind'),''),coalesce(json_extract(summary_json,'$.subject.id'),'')))
            FROM (SELECT bucket, identity, min(summary_json) AS summary_json FROM screen_items WHERE case_id=? AND kind='findings' GROUP BY bucket,identity)
            GROUP BY bucket''', (case_id,)):
            rule, severity = json.loads(bucket)
            definition = RULES.get(rule)
            result.append(dict(id=bucket, rule=rule, severity=severity, occurrences=count, subjects=subjects,
                               title=definition.title if definition else rule, explanation=definition.statement if definition else '',
                               service=definition.service if definition else '', entries=[], toolRunIds=[]))
        rank = {'warning': 0, 'notice': 1, 'info': 2}
        result.sort(key=lambda g: (rank.get(g['severity'], 3), g['rule'], g['severity']))
        return result
