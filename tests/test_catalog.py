import os
from pathlib import Path
import sys
import pytest
from sqlalchemy import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog as c


@pytest.fixture
def engine(tmp_path):
    e = c.database(os.getenv('TEST_DATABASE_URL') or 'sqlite:///' + (tmp_path / 'catalog.db').as_posix())
    c.META.drop_all(e)
    c.META.create_all(e)
    c.seed(e)
    yield e
    e.dispose()


def test_dictionary_and_lineage_are_complete_for_registered_metrics(engine):
    assert len(c.assets(engine)) == 13
    assert len(c.metrics(engine)) == 3
    for metric in c.FORMULAS:
        assert {r['asset_id'] for r in c.lineage(engine, metric)} == {
            'transactions.amount_minor', 'transactions.currency', 'transactions.transaction_date', 'transactions.transaction_type'}


def test_literal_search_and_classification_filter(engine):
    assert len(c.assets(engine, 'amount_minor')) == 1
    assert c.assets(engine, "%' OR 1=1 --") == []
    assert all(r['classification'] == 'CONFIDENTIAL' for r in c.assets(engine, classification='CONFIDENTIAL'))


def test_impact_reports_only_documented_dependencies(engine):
    assert len(c.impact(engine, 'transactions.amount_minor')) == 3
    assert c.impact(engine, 'customers.customer_id') == []


def test_definitions_are_versioned_and_seed_does_not_overwrite(engine):
    c.revise(engine, 'transactions.amount_minor', {'owner': 'Demo Finance Controls'}, 'Analyst', 'Ownership handover.', 0)
    c.seed(engine)
    row = c.assets(engine, 'transactions.amount_minor')[0]
    assert row['owner'] == 'Demo Finance Controls'
    assert row['version'] == 1
    assert len(c.history(engine, 'transactions.amount_minor')) == 1


def test_stale_definition_update_is_rejected(engine):
    c.revise(engine, 'net_spend', {'owner': 'Demo Reporting'}, 'A', 'Assign owner.', 0)
    with pytest.raises(ValueError, match='Refresh'):
        c.revise(engine, 'net_spend', {'owner': 'Other owner'}, 'B', 'Stale change.', 0)
    assert len(c.history(engine, 'net_spend')) == 1


@pytest.mark.parametrize('changes', [{'sql_text': 'DROP TABLE gov_assets'}, {'classification': 'SECRET'}, {'owner': ''}])
def test_invalid_business_edits_never_mutate_history(engine, changes):
    with pytest.raises(ValueError):
        c.revise(engine, 'transactions.amount_minor', changes, 'A', 'Attempt invalid edit.', 0)
    assert c.history(engine, 'transactions.amount_minor') == []


def test_metric_arithmetic_and_currency_separation(engine):
    gross = {r['currency']: r['amount_minor'] for r in c.report(engine, 'gross_purchase')}
    refund = {r['currency']: r['amount_minor'] for r in c.report(engine, 'refund_amount')}
    net = {r['currency']: r['amount_minor'] for r in c.report(engine, 'net_spend')}
    assert set(net) == {'INR', 'GBP', 'SGD'}
    assert all(net[k] == gross[k] - refund[k] for k in net)
    # Independently calculated from the fixture generator's arithmetic, no SQL.
    expected = dict.fromkeys(['INR', 'GBP', 'SGD'], 0)
    for i in range(1, 3001):
        expected[['INR', 'GBP', 'SGD'][(i-1) % 3]] += (100 + i*137 % 50000) * (-1 if i % 20 == 0 else 1)
    assert net == expected


def test_unknown_metric_is_rejected(engine):
    with pytest.raises(ValueError):
        c.report(engine, 'made_up')


def test_noop_revision_is_rejected(engine):
    original = c.assets(engine, 'transactions.amount_minor')[0]
    with pytest.raises(ValueError, match='No definition changes'):
        c.revise(engine, original['asset_id'], {'owner': original['owner']}, 'A', 'No change.', 0)


def test_dashboard_search_and_definition_revision(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'app.db').as_posix())
    app = AppTest.from_file(str(c.ROOT / 'app.py'), default_timeout=30).run()
    assert not app.exception
    assert [m.value for m in app.metric] == ['3', '13', '3', '12']
    next(t for t in app.text_input if t.label == 'Business owner').set_value('Demo Finance Controls')
    next(t for t in app.text_input if t.label == 'Reviewer').set_value('Demo analyst')
    next(t for t in app.text_area if t.label == 'Change reason').set_value('Documented a handover.')
    next(b for b in app.button if b.label == 'Save definition revision').click().run()
    assert not app.exception
    assert next(t for t in app.text_input if t.label == 'Business owner').value == 'Demo Finance Controls'
