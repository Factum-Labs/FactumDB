import json

import pytest

from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_history_summary_repository import HistorySummaries


@pytest.fixture
def db():
    connection = open_case_database(':memory:')
    for case in ('a', 'b'):
        connection.execute("INSERT INTO cases(case_id,case_name,examiner,workspace_path,created_at) VALUES (?,?,?,?,?)", (case, case, 'examiner', '/tmp', 'now'))
    connection.commit()
    yield connection
    connection.close()


def seed(db, case='a', count=205):
    histories = [dict(record=dict(id=f'accounts:{i}', database='credit', table='credit.accounts', key=f'id = {i}', label=f'Account {i}'), method='primary_key_exact', steps=[{}]) for i in range(count)]
    histories.append(dict(record=dict(id='accounts:0', database='other', table='other.accounts', key='id = 0', label='Other'), method='primary_key_exact', steps=[]))
    db.execute("INSERT OR REPLACE INTO analysis_results VALUES (?, 'reconstruction', ?, 'now')", (case, json.dumps(dict(histories=histories))))
    db.commit()


def test_pages_tables_location_and_case_isolation(db):
    seed(db)
    repo = HistorySummaries(db)
    assert repo.tables('a')['total'] == 206
    first = repo.page('a', 'credit', 'credit.accounts')
    second = repo.page('a', 'credit', 'credit.accounts', 100)
    assert len(first['items']) == len(second['items']) == 100
    assert first['total'] == 205
    assert first['items'][0]['record']['id'] == 'accounts:0'
    assert second['items'][0]['record']['id'] == 'accounts:100'
    assert len(repo.page('a', 'credit', 'credit.accounts', 200)['items']) == 5
    assert repo.page('b')['total'] == 0
    assert repo.page('a', 'credit', 'absent')['items'] == []
    with pytest.raises(ValueError, match='ambiguous'):
        repo.locate('a', 'accounts:0')
    assert repo.locate('a', 'accounts:104', 'credit.accounts')['offset'] == 100
    plan = db.execute('EXPLAIN QUERY PLAN SELECT * FROM history_summaries WHERE case_id=? AND database_name=? AND qualified_table_name=? ORDER BY ordinal LIMIT 100', ('a','credit','credit.accounts')).fetchall()
    assert any('idx_history_table' in r[3] for r in plan)


def test_backfill_empty_update_delete_and_rollback(db):
    seed(db)
    repo = HistorySummaries(db)
    repo.ensure('a')
    # A ready empty index must not be rebuilt on every request.
    repo.ensure('b')
    db.execute("INSERT INTO history_summaries SELECT 'b', ordinal, database_name, qualified_table_name, record_id, record_json, method, step_count FROM history_summaries WHERE case_id='a' AND ordinal=0")
    db.commit()
    assert repo.page('b')['total'] == 1
    with pytest.raises(RuntimeError):
        with db:
            db.execute("UPDATE analysis_results SET result_json = '{\"histories\":[]}' WHERE case_id='a'")
            repo.rebuild('a')
            raise RuntimeError('simulate failed save')
    assert repo.page('a')['total'] == 206
    with db:
        db.execute("UPDATE analysis_results SET result_json = '{\"histories\":[]}' WHERE case_id='a'")
    assert repo.page('a')['total'] == 0
    seed(db, count=2)
    # INSERT OR REPLACE is followed by explicit rebuilding in the save path.
    with db:
        repo.rebuild('a')
    assert repo.page('a')['total'] == 3
    with db:
        db.execute("DELETE FROM analysis_results WHERE case_id='a'")
    assert repo.page('a')['total'] == 0


@pytest.mark.parametrize('args', [dict(offset=-1), dict(limit=0), dict(limit=101), dict(limit=True), dict(table='accounts')])
def test_invalid_requests(db, args):
    with pytest.raises(ValueError):
        HistorySummaries(db).page('a', **args)


def test_bundled_pages_parity_and_validation(db):
    from sidecar.views import analysis_detail
    seed(db)
    repo = HistorySummaries(db)
    for database, table, offset in [(None, None, 0), ('credit', 'credit.accounts', 100), ('credit', 'credit.accounts', 200), ('other', 'other.accounts', 0)]:
        page = repo.page('a', database, table, offset, include_details=True)
        legacy = repo.page('a', database, table, offset)
        assert [item['summary'] for item in page['items']] == legacy['items']
        for item in page['items']:
            record = item['summary']['record']
            single = analysis_detail(db, 'a', 'history', record['id'], qualified_table=record['table'])
            assert {key: item[key] for key in ('detail', 'findings')} == single
    assert repo.page('b', include_details=True)['items'] == []
    assert repo.page('a', 'credit', 'missing', include_details=True)['items'] == []
    with pytest.raises(ValueError, match='boolean'):
        repo.page('a', include_details=1)


def test_bundle_preserves_large_values_and_long_histories(db):
    from sidecar.views import analysis_detail
    history = dict(record=dict(id='products:1|2', database='credit', table='credit.products', key='1|2'),
                   method='composite_primary_key_exact', steps=[dict(value=2**60, text='x' * 10000) for _ in range(201)])
    db.execute("INSERT INTO analysis_results VALUES ('a', 'reconstruction', ?, 'now')", (json.dumps(dict(histories=[history])),))
    db.commit()
    item = HistorySummaries(db).page('a', include_details=True)['items'][0]
    assert item['detail'] == analysis_detail(db, 'a', 'history', 'products:1|2')['detail']
    assert len(item['detail']['steps']) == 201
