"""Run: streamlit run app.py --server.port 8503"""
import os
import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError
import catalog as c

st.set_page_config(page_title='Data Governance Catalog', page_icon='📚', layout='wide')
st.markdown('**DATA OPERATIONS / GOVERNANCE**')
st.title('Know what a number means.')
st.caption('Data Governance Catalog & Report Traceability · Manually documented lineage · Synthetic portfolio')


@st.cache_resource
def connection(url):
    engine = c.database(url or None)
    c.seed(engine)
    return engine


try:
    engine = connection(os.getenv('DATABASE_URL', ''))
except SQLAlchemyError:
    st.error('Cannot connect to the configured database. Check DATABASE_URL and the server, or unset DATABASE_URL to use the local SQLite demo. See README for the WSL PostgreSQL setup.')
    st.stop()
with st.sidebar:
    st.header('Discover data')
    st.caption(f'Database: {engine.dialect.name}. Owners are fictional demo teams.')
    term = st.text_input('Search definitions, columns, owners')
    classification = st.selectbox('Classification', ['All', 'PUBLIC', 'INTERNAL', 'CONFIDENTIAL'])
dictionary = c.assets(engine, term, None if classification == 'All' else classification)
all_metrics = c.metrics(engine)
cols = st.columns(4)
for col, label, value in zip(cols, ['Source tables', 'Documented columns', 'Report metrics', 'Lineage links'],
                             [3, len(c.assets(engine)), len(all_metrics), sum(len(c.lineage(engine, m['metric_id'])) for m in all_metrics)]):
    col.metric(label, value)
dictionary_tab, reports, definitions = st.tabs(['Data dictionary & impact', 'Metric lineage & reports', 'Definition changes'])
with dictionary_tab:
    st.dataframe(pd.DataFrame(dictionary), hide_index=True, width='stretch')
    st.download_button('Download filtered dictionary', c.csv_export(dictionary), 'data-dictionary.csv', 'text/csv')
    if dictionary:
        asset_id = st.selectbox('Inspect downstream impact', [r['asset_id'] for r in dictionary])
        impacted = c.impact(engine, asset_id)
        if impacted:
            st.dataframe(pd.DataFrame(impacted), hide_index=True)
        else:
            st.info('No report dependencies are documented for this column. This does not prove that no other consumers exist.')
with reports:
    metric = st.selectbox('Report metric', all_metrics, format_func=lambda m: m['name'])
    st.markdown(f'**Definition:** {metric["description"]}')
    st.caption(f'Owner: {metric["owner"]} · Grain: {metric["grain"]} · Definition version: {metric["version"]}')
    st.subheader('Source columns → monthly transformation → report metric')
    st.dataframe(pd.DataFrame(c.lineage(engine, metric['metric_id'])), hide_index=True)
    st.code(metric['sql_text'], language='sql')
    result = c.report(engine, metric['metric_id'])
    st.dataframe(pd.DataFrame(result), hide_index=True)
    st.download_button('Download metric report', c.csv_export(result), metric['metric_id'] + '.csv', 'text/csv')
    st.caption('Reports run on a bundled clean snapshot, independently of the quality-monitor database. There is no automatic publishing gate between the three apps.')
with definitions:
    entities = [*c.assets(engine), *all_metrics]
    entity_id = st.selectbox('Definition to revise', [x.get('asset_id', x.get('metric_id')) for x in entities])
    entity = next(x for x in entities if x.get('asset_id', x.get('metric_id')) == entity_id)
    with st.form('revise-' + entity_id):
        owner = st.text_input('Business owner', value=entity['owner'])
        description = st.text_area('Business definition', value=entity['description'])
        changes = dict(owner=owner, description=description)
        if 'classification' in entity:
            levels = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL']
            changes['classification'] = st.selectbox('Sensitivity', levels, index=levels.index(entity['classification']))
        actor = st.text_input('Reviewer')
        reason = st.text_area('Change reason')
        if st.form_submit_button('Save definition revision'):
            try:
                c.revise(engine, entity_id, changes, actor, reason, entity['version'])
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    events = c.history(engine, entity_id)
    st.subheader('Version history')
    st.dataframe(pd.DataFrame(events).drop(columns=['event_id'], errors='ignore'), hide_index=True)
    if events:
        st.download_button('Download definition history', c.csv_export(events), 'definition-history.csv', 'text/csv')
    st.caption('Business definitions are editable. Executable metric SQL is maintained in code and changes require code review. Labels describe sensitivity; they do not enforce access controls.')
