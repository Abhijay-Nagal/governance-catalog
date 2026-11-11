# Data Governance Catalog & Report Traceability

## 1. Your one-minute explanation

"I built a small governance catalog to make a fictional card dataset understandable and traceable. It documents thirteen columns, their owners, definitions and sensitivity labels. Three monthly reports have explicit dependencies on source columns, so a user can trace a number back to its inputs or inspect the impact of changing a column. Business definitions have versioned before/after history. The report calculations run on a clean synthetic snapshot and are tested against an independent Python calculation."

The strongest story is clarity and accountability. Do not present it as an enterprise catalog, automatic lineage engine or compliance certification.

## 2. Governance in practical language

Data management is the work of collecting, storing, transforming and using data. Data governance establishes agreed meanings, responsibilities and rules for that work. A dashboard can compute a number correctly while still confusing stakeholders if nobody agrees on what that number means.

Consider two teams reporting spend. One includes refunds as positive values; another subtracts them. Both SQL queries can execute successfully but answer different questions. A catalog makes the definition, grain, owner and source dependencies explicit before the number is consumed.

- Metadata is data about data: a column name, type, description or owner.
- A data dictionary explains fields in a structured dataset.
- A business glossary defines business concepts. This small project contains metric definitions rather than a full separate enterprise glossary.
- An owner is accountable for a dataset or definition.
- A steward often handles day-to-day definition and quality work. The demo stores owner labels and does not model a separate steward role.
- Classification labels expected sensitivity. It does not itself enforce access.
- Lineage describes how an output depends on inputs and transformations.
- Impact analysis asks which documented outputs could be affected by an input change.
- Grain states what one report row represents, here calendar month by currency.

The fictional team names in seed data are demonstration labels, not real departments or employment relationships.

## 3. Architecture and reading order

`metadata constants + clean transaction CSV -> idempotent seed -> relational catalog -> discovery / lineage / reports -> controlled business-field edits + change history`

Read `catalog.py` in this order: schema, `DESCRIPTIONS`, `OWNERS`, `FORMULAS`, `database`, `seed`, discovery and lineage functions, `revise`, report execution and CLI. Read `app.py` after understanding those functions.

The catalog is standalone. It bundles the same clean transaction scenario as the quality project but does not query that project's database. Customers/accounts are conceptual documented sources; the physical table used for its demo reports is `gov_demo_transactions`. There is no automatic quality-gated publishing pipeline between the apps.

`gov_assets` stores one row per source column. `gov_metrics` stores one row per metric, its definition, owner, grain and displayed SQL. `gov_lineage` links a source asset to a metric with a purpose. `gov_changes` stores revision evidence. `gov_demo_transactions` contains the clean report snapshot.

The asset primary key is a stable string such as `transactions.amount_minor`. The lineage primary key is `(asset_id,metric_id)`, preventing duplicate direct edges. This is a simple relational model; a graph database would add setup without helping these twelve direct edges.

## 4. The documented schema

Customers has customer_id, market and segment. Accounts has account_id, customer_id, currency and status. Transactions has transaction_id, account_id, amount_minor, currency, transaction_date and transaction_type. That is 3 + 4 + 6 = 13 columns.

Identifiers and amount are marked CONFIDENTIAL as an educational handling convention; the values are synthetic. Market, segment, currency, date, status and transaction type are INTERNAL in this sample. PUBLIC is available as an allowed classification even though none is required by the initial seed.

Every field has a nonempty definition, a type and an owner. Types describe the logical source schema; a DATE annotation does not mean the raw CSV contains a database DATE object. The demo physical transaction date is canonical text so the limited report SQL is portable.

Ownership helps answer who should clarify a definition or investigate an issue. It is different from a database role, login, permission grant or approval authority. The user interface does not hide CONFIDENTIAL fields; classification is descriptive metadata only.

## 5. Three metrics with explicit semantics

Gross purchase amount: sum positive magnitudes for PURCHASE rows, excluding refunds.

Refund amount: sum positive magnitudes for REFUND rows.

Net spend: purchases minus refund magnitudes.

Every report row has grain `(calendar_month,currency)`. Currency is part of the grouping because 1 INR and 1 GBP cannot be added into a meaningful nominal total without an exchange-rate policy. The project has no FX conversion. All three supported currencies use 100 minor units per major unit.

```sql
SELECT SUBSTR(transaction_date, 1, 7) AS month,
       currency,
       SUM(CASE
         WHEN transaction_type = 'REFUND' THEN -amount_minor
         ELSE amount_minor
       END) AS amount_minor
FROM gov_demo_transactions
GROUP BY SUBSTR(transaction_date, 1, 7), currency
ORDER BY month, currency;
```

`CASE` chooses a contribution for each input row; `SUM` adds contributions within the group. The ELSE branch assumes all nonrefund rows are purchases because the bundled clean snapshot follows that contract. Unknown transaction types in a future loader need validation or an explicit failure branch, not a casual assumption.

`SUBSTR` extracts the YYYY-MM calendar month from canonical dates. A production dataset with timestamps would need timezone and business-calendar decisions. The sample has one month and three currencies; the query still groups by both columns rather than hard-coding one row per currency.

On the deterministic fixture, net amounts are GBP 22,095,500; INR 22,234,500; SGD 21,984,500 minor units. These remain separate values. Their real-world financial significance is zero because the data is fictional.

## 6. Why all four lineage columns matter

Each metric links to four source columns:

- amount_minor: the value aggregated.
- transaction_type: determines purchase versus refund treatment.
- transaction_date: determines reporting month.
- currency: determines separate currency groups.

Three metrics times four dependencies gives twelve explicit edges. A common mistake is recording only amount_minor and forgetting the columns that influence filtering or grouping. Then a currency/date schema change would look harmless even though it changes the report.

The lineage direction is source column -> metric. Selecting net_spend shows its four upstream inputs. Selecting transactions.amount_minor shows three directly affected metrics. Selecting customers.customer_id shows no registered report dependencies, because none of these three formulas uses it directly.

No edges means no documented dependency in this catalog. It does not establish that no unknown spreadsheets, external jobs or analysts use the field. The project has no scanning agent or SQL parser that discovers those consumers.

The dashboard shows the transformation SQL alongside the source columns. That is the traceability story: definition, grain, owner, inputs, transformation and output can be inspected in one place. The project does not trace individual report cells back to every contributing source row.

## 7. Search and classification

Search is a literal, case-insensitive substring match over fetched metadata. Percent signs and underscores are ordinary characters rather than SQL LIKE wildcards. The classification filter is a bound SQL equality predicate. With thirteen rows, fetching metadata and searching in Python is simple and adequate.

For a large catalog, use indexed database search and pagination; do not describe this implementation as an enterprise search engine. Always distinguish a design extension from an implemented feature.

CSV exports use readable field names and neutralize formula-trigger prefixes in authored definitions. The stored definitions keep their original text. This is a download handling measure, not a substitute for access control.

## 8. Seeding and persistence

`seed` inserts missing assets, metrics, lineage links and the clean transaction snapshot. Calling it again does not overwrite user-authored owner/definition revisions. This is important because Streamlit may restart or open additional sessions.

Idempotent seed is not the same thing as a migration system. If the code's metric formula changes later, an already-seeded database will still have its old displayed SQL unless it is explicitly migrated. The fixed execution registry would use the new code, so updating formula code must include migrating displayed SQL and version metadata. This is documented as a limitation rather than silently ignored.

Business definition edits do not change executable calculations. A user can clarify the description and owner, but cannot submit arbitrary SQL through the form. The `report` function accepts only known metric IDs and builds SQL from the code registry. The SQL field shown in the database is descriptive metadata, not trusted executable user content.

## 9. Controlled definition revisions

Assets can change description, owner and classification. Metrics can change description and owner. Identifiers, data types, grain and executable SQL are not editable through this form. Unknown edit keys are rejected.

A revision requires nonempty fields, a reviewer, a reason and the version the user observed. The function rejects no-op updates so history represents actual changes. It reads the old row, checks the version, conditionally updates the matching version and inserts before/after JSON into history in one transaction.

Version starts at zero and increments per revision. If two browser sessions begin at version zero and one saves first, the second cannot overwrite it with a stale edit. A conditional update count of zero indicates a conflict even if both sessions initially read the same version.

Before/after JSON makes a change understandable: who claimed the change, what fields changed and why. It is not an immutable audit service; a privileged database user could alter it. Reviewer text is self-declared, not authenticated identity or a two-person approval workflow.

## 10. Tests and independent evidence

The tests verify thirteen documented fields, three registered metrics, all four dependencies for each, literal search, classification, direct impact, seed preservation, stale revisions, invalid/no-op edits and unknown metrics. Streamlit AppTest changes a definition through the real form and verifies the displayed result after rerun.

The arithmetic test computes expected net spend in Python directly from the generator's numeric rule, then compares it with SQL results. This is more meaningful than asserting that the SQL function equals a second call to itself. It also checks `gross - refunds = net` for each currency separately.

Tests against PostgreSQL cover the actual backend functions. UI tests intentionally use temporary SQLite files for isolation. The source fixture and expected outputs make the scope reproducible; no test proves every possible metadata policy or malformed external data case.

## 11. Five-minute demo

1. Search amount_minor and explain its definition, owner, logical type and sensitivity label.
2. Inspect downstream impact: all three monthly metrics depend on it.
3. Select net spend and identify four upstream columns and why each matters.
4. Read the CASE/SUM/GROUP BY query in plain English.
5. Show the three currency-separated output rows and explain the reporting grain.
6. Revise the column owner with a reviewer and reason; show before/after history.
7. Refresh or reopen the app and show that the revised definition persists.
8. Explain that classifications are metadata and the lineage is manually maintained.

## 12. Questions with answer guidance

**How is governance different from validation?** Validation checks values against expectations. Governance establishes meanings, accountability and rules for handling data. The quality monitor and catalog address different parts of the same lifecycle.

**What is lineage?** A documented dependency between source data, transformations and outputs. This project stores direct source-column-to-metric edges and shows SQL; it does not infer a full multi-job graph.

**Why store currency/date as lineage inputs?** They affect grouping and therefore the meaning of output rows. Dependencies include columns controlling computation, not just the numeric column being summed.

**What is grain?** The unit represented by one report row. Here it is calendar month x currency. Joining facts at incompatible grains can duplicate values even when syntax is correct.

**Does CONFIDENTIAL mean access is blocked?** No. It is a handling label. Enforcement would require identity, authorization, policy and tested access controls.

**Can a business user change the calculation?** Not through this form. They can edit descriptive business fields. Executable SQL is fixed in code; formula changes need review and an explicit metadata migration.

**Why no graph database?** Thirteen columns and twelve direct edges fit a relational table naturally. A graph system becomes useful for complex traversal needs, not just because the word lineage is used.

**Why preserve definition history?** Consumers need to understand changing meanings and ownership. Before/after values and reasons support review. This does not prove that the stated reason is correct.

**What if two users edit at once?** The expected version detects stale saves. Update and change event share a transaction so partial history cannot be committed through the function.

**How do you test a report?** Define its grain and semantics first, then compare outputs with an independent calculation and check identities such as purchases minus refunds equals net per currency.

**What does no impact result mean?** No dependency is registered in this scoped catalog. It is not proof that all possible downstream uses have been discovered.

**What would production need?** Authenticated owners/reviewers, approval policy, enforced permissions, discovery integrations, versioned migrations, retention and richer lineage. Those are future designs, not resume claims.

## 13. Exercises and readiness

Exercise A: write an active-account-count metric. State its grain and list only the actual source columns it needs. Avoid copying transaction dependencies blindly.

Exercise B: explain how the monthly report would change if transaction_date became a UTC timestamp but reports followed local market business days. Identify where timezone policy belongs.

Exercise C: edit a description to start with `=SUM(1,2)` and download the dictionary. Confirm the CSV representation is neutralized while stored metadata remains the authored text.

Exercise D: add an unused conceptual field to DESCRIPTIONS. Confirm direct impact is empty and state the correct interpretation.

Exercise E: explain how you would migrate a changed net-spend formula so displayed SQL, executed SQL and metric version remain consistent. Do not modify production definitions by just rerunning seed.

You are ready when you can define metadata, lineage, grain, ownership and classification; trace one output to all four inputs; explain versioned edits; and distinguish documentation from enforcement.

Reference documentation: https://www.postgresql.org/docs/current/queries-table-expressions.html ; https://docs.sqlalchemy.org/en/20/core/connections.html ; https://docs.cloud.google.com/bigquery/docs/data-governance . GCP is an optional conceptual extension, not an implemented deployment.
