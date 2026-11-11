"""A small searchable data dictionary with explicit column-to-metric lineage."""
import argparse
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (Column, Integer, MetaData, String, Table, Text, create_engine,
                        insert, select, text, update)

ROOT = Path(__file__).resolve().parent
META = MetaData()
ASSETS = Table('gov_assets', META, Column('asset_id', String(100), primary_key=True),
               Column('table_name', String(40)), Column('column_name', String(40)),
               Column('data_type', String(40)), Column('description', Text),
               Column('owner', String(100)), Column('classification', String(20)), Column('version', Integer))
METRICS = Table('gov_metrics', META, Column('metric_id', String(80), primary_key=True),
                Column('name', String(100)), Column('description', Text), Column('owner', String(100)),
                Column('grain', String(80)), Column('sql_text', Text), Column('version', Integer))
EDGES = Table('gov_lineage', META, Column('asset_id', String(100), primary_key=True),
              Column('metric_id', String(80), primary_key=True), Column('purpose', Text))
CHANGES = Table('gov_changes', META, Column('event_id', String(32), primary_key=True),
                Column('entity_id', String(100)), Column('changed_at', String(40)),
                Column('actor', String(100)), Column('reason', Text),
                Column('before_json', Text), Column('after_json', Text), Column('version', Integer))
SAMPLE = Table('gov_demo_transactions', META, Column('transaction_id', String(40), primary_key=True),
               Column('account_id', String(40)), Column('amount_minor', Integer), Column('currency', String(3)),
               Column('transaction_date', String(10)), Column('transaction_type', String(20)))

DESCRIPTIONS = {
    'customers': {
        'customer_id': ('TEXT', 'Synthetic customer identifier; unique and required.', 'CONFIDENTIAL'),
        'market': ('TEXT', 'Customer market: IN, GB, or SG. Not a currency conversion instruction.', 'INTERNAL'),
        'segment': ('TEXT', 'Customer segment: CONSUMER or COMMERCIAL.', 'INTERNAL')},
    'accounts': {
        'account_id': ('TEXT', 'Synthetic account identifier; unique in the clean sample.', 'CONFIDENTIAL'),
        'customer_id': ('TEXT', 'Reference to customers.customer_id.', 'CONFIDENTIAL'),
        'currency': ('CHAR(3)', 'Account currency: INR, GBP, or SGD.', 'INTERNAL'),
        'status': ('TEXT', 'Account lifecycle status: ACTIVE or CLOSED.', 'INTERNAL')},
    'transactions': {
        'transaction_id': ('TEXT', 'Synthetic transaction reference; unique in the clean sample.', 'CONFIDENTIAL'),
        'account_id': ('TEXT', 'Reference to accounts.account_id.', 'CONFIDENTIAL'),
        'amount_minor': ('INTEGER', 'Nonnegative amount in hundredths of currency; 1250 means 12.50 for these three currencies.', 'CONFIDENTIAL'),
        'currency': ('CHAR(3)', 'Transaction currency. Aggregate separately; no FX conversion is implemented.', 'INTERNAL'),
        'transaction_date': ('DATE', 'Business date in YYYY-MM-DD, used for the monthly reporting grain.', 'INTERNAL'),
        'transaction_type': ('TEXT', 'PURCHASE contributes positively; REFUND contributes negatively to net spend.', 'INTERNAL')},
}
OWNERS = {'customers': 'Demo Customer Data Office', 'accounts': 'Demo Account Operations',
          'transactions': 'Demo Payments Operations'}
FORMULAS = {
    'gross_purchase': ('Gross purchase amount', "SUM(CASE WHEN transaction_type='PURCHASE' THEN amount_minor ELSE 0 END)",
                       'Sum purchase amounts; exclude refunds. Report in minor units per month and currency.'),
    'refund_amount': ('Refund amount', "SUM(CASE WHEN transaction_type='REFUND' THEN amount_minor ELSE 0 END)",
                      'Sum refund magnitudes as positive minor units per month and currency.'),
    'net_spend': ('Net spend', "SUM(CASE WHEN transaction_type='REFUND' THEN -amount_minor ELSE amount_minor END)",
                  'Purchase amounts minus refund amounts, in minor units per month and currency.'),
}


def database(url=None):
    url = url or os.getenv('DATABASE_URL') or 'sqlite:///' + (ROOT / 'catalog.db').as_posix()
    engine = create_engine(url, connect_args={'connect_timeout': 5} if url.startswith('postgresql') else {})
    META.create_all(engine)
    return engine


def seed(engine):
    """Idempotent seed: never overwrites authored definitions or change history."""
    with engine.begin() as conn:
        for table_name, columns in DESCRIPTIONS.items():
            for column, (data_type, description, classification) in columns.items():
                asset_id = f'{table_name}.{column}'
                if not conn.execute(select(ASSETS.c.asset_id).where(ASSETS.c.asset_id == asset_id)).first():
                    conn.execute(insert(ASSETS), dict(asset_id=asset_id, table_name=table_name, column_name=column,
                                                     data_type=data_type, description=description, owner=OWNERS[table_name],
                                                     classification=classification, version=0))
        for metric_id, (name, formula, description) in FORMULAS.items():
            # Executable SQL is fixed by code. Editing descriptions cannot execute arbitrary SQL.
            sql = f"SELECT SUBSTR(transaction_date,1,7) AS month, currency, {formula} AS amount_minor FROM gov_demo_transactions GROUP BY SUBSTR(transaction_date,1,7),currency ORDER BY month,currency"
            if not conn.execute(select(METRICS.c.metric_id).where(METRICS.c.metric_id == metric_id)).first():
                conn.execute(insert(METRICS), dict(metric_id=metric_id, name=name, description=description,
                                                  owner='Demo Portfolio Reporting', grain='calendar month x currency',
                                                  sql_text=sql, version=0))
            for column, purpose in [('amount_minor', 'Value being aggregated'), ('transaction_type', 'Purchase/refund condition'),
                                    ('transaction_date', 'Calendar-month grouping'), ('currency', 'Separate currency grouping')]:
                asset_id = f'transactions.{column}'
                if not conn.execute(select(EDGES).where(EDGES.c.asset_id == asset_id, EDGES.c.metric_id == metric_id)).first():
                    conn.execute(insert(EDGES), dict(asset_id=asset_id, metric_id=metric_id, purpose=purpose))
        if conn.execute(select(SAMPLE.c.transaction_id).limit(1)).first() is None:
            with (ROOT / 'data' / 'transactions.csv').open(newline='', encoding='utf-8') as f:
                rows = [dict(row, amount_minor=int(row['amount_minor'])) for row in csv.DictReader(f)]
            conn.execute(insert(SAMPLE), rows)


def assets(engine, search='', classification=None):
    query = select(ASSETS)
    if classification:
        query = query.where(ASSETS.c.classification == classification)
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(query.order_by(ASSETS.c.asset_id)).mappings()]
    # Literal case-insensitive substring search: %, _, and quotes have no special meaning.
    term = search.casefold().strip()
    return [r for r in rows if term in ' '.join(str(v) for v in r.values()).casefold()]


def metrics(engine):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(METRICS).order_by(METRICS.c.metric_id)).mappings()]


def lineage(engine, metric_id):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(EDGES.c.asset_id, EDGES.c.purpose, ASSETS.c.owner,
                                                      ASSETS.c.classification)
                                              .join(ASSETS, EDGES.c.asset_id == ASSETS.c.asset_id)
                                              .where(EDGES.c.metric_id == metric_id).order_by(EDGES.c.asset_id)).mappings()]


def impact(engine, asset_id):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(METRICS.c.metric_id, METRICS.c.name, EDGES.c.purpose)
                                              .join(EDGES, METRICS.c.metric_id == EDGES.c.metric_id)
                                              .where(EDGES.c.asset_id == asset_id).order_by(METRICS.c.metric_id)).mappings()]


def revise(engine, entity_id, changes, actor, reason, expected_version):
    actor, reason = actor.strip(), reason.strip()
    if not actor or len(actor) > 100 or not reason or len(reason) > 2000:
        raise ValueError('Reviewer (1-100 characters) and change reason (1-2000 characters) are required.')
    is_asset = '.' in entity_id
    table, key = (ASSETS, ASSETS.c.asset_id) if is_asset else (METRICS, METRICS.c.metric_id)
    allowed = {'description', 'owner', 'classification'} if is_asset else {'description', 'owner'}
    if not changes or not set(changes) <= allowed:
        raise ValueError('Only documented business fields may be edited; SQL and identifiers are fixed in code.')
    changes = {k: v.strip() for k, v in changes.items()}
    if any(not v or len(v) > (100 if k == 'owner' else 2000) for k, v in changes.items()):
        raise ValueError('Definitions and owners must be nonempty and within the field length limit.')
    if 'classification' in changes and changes['classification'] not in {'PUBLIC', 'INTERNAL', 'CONFIDENTIAL'}:
        raise ValueError('Unknown classification.')
    with engine.begin() as conn:
        before = conn.execute(select(table).where(key == entity_id)).mappings().first()
        if not before:
            raise ValueError('Unknown asset or metric.')
        if before['version'] != expected_version:
            raise ValueError('Definition changed. Refresh before editing.')
        if all(before[k] == v for k, v in changes.items()):
            raise ValueError('No definition changes to save.')
        changed = conn.execute(update(table).where(key == entity_id, table.c.version == expected_version)
                               .values(**changes, version=expected_version + 1))
        if changed.rowcount != 1:
            raise ValueError('Concurrent edit detected. Refresh before saving.')
        after = dict(before, **changes)
        after['version'] = expected_version + 1
        conn.execute(insert(CHANGES), dict(event_id=uuid4().hex, entity_id=entity_id,
                                          changed_at=datetime.now(timezone.utc).isoformat(), actor=actor, reason=reason,
                                          before_json=json.dumps(dict(before)), after_json=json.dumps(after),
                                          version=expected_version + 1))


def history(engine, entity_id):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(CHANGES).where(CHANGES.c.entity_id == entity_id)
                                              .order_by(CHANGES.c.version)).mappings()]


def report(engine, metric_id):
    if metric_id not in FORMULAS:
        raise ValueError('Unknown metric.')
    # Read SQL from the fixed code registry, rather than trusting editable database content.
    formula = FORMULAS[metric_id][1]
    sql = f"SELECT SUBSTR(transaction_date,1,7) AS month, currency, {formula} AS amount_minor FROM gov_demo_transactions GROUP BY SUBSTR(transaction_date,1,7),currency ORDER BY month,currency"
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql)).mappings()]


def csv_export(rows):
    if not rows:
        return ''
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v
                     for k, v in r.items()} for r in rows)
    return out.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts')
    args = parser.parse_args()
    engine = database(args.database_url)
    seed(engine)
    args.output.mkdir(parents=True, exist_ok=True)
    dictionary = assets(engine)
    summary = dict(tables=len(DESCRIPTIONS), columns=len(dictionary), metrics=len(metrics(engine)),
                   lineage_edges=sum(len(lineage(engine, m)) for m in FORMULAS),
                   reports={m: report(engine, m) for m in FORMULAS})
    (args.output / 'dictionary.csv').write_text(csv_export(dictionary), encoding='utf-8')
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
