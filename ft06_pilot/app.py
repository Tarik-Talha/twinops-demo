"""The FT06 pilot owns its UI, engine and Blender output."""
from pathlib import Path
import copy
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ft06_pilot.model import load_instance, scenario_hash
from ft06_pilot.engine import run_scenario
from ft06_pilot.export import RUNTIME, build_blender, export_run

POLICIES = {'İlk hazır olan önce (FIFO)': 'fifo', 'Kısa işlem önce (SPT)': 'spt', 'İşleri sırayla tamamla': 'serial'}
JOB_COLORS = ['#21a3ff', '#ff612e', '#59e682', '#c969ff', '#ffc92e', '#2edbd4']


# =========================================================
# FT06 SCENARIO CONTROLS AND SYNTHETIC DEFAULT PRESERVATION
# =========================================================

st.set_page_config(page_title='TwinOps · FT06', page_icon='🏭', layout='wide')
st.title('TwinOps · FT06 Pilot')
st.caption('6 iş · 6 makine · 36 operasyon · simülasyon + optimizasyon + Blender')
st.info('FT06 yayımlanmış bir test problemidir. Gerçek fabrika ölçümü değildir. Süreler soyut zaman birimidir.')

base = load_instance()
if 'ft06_scenario' not in st.session_state:
    st.session_state.ft06_scenario = copy.deepcopy(base)
    st.session_state.ft06_run = run_scenario(base, 'fifo')
    st.session_state.ft06_proposal = None
    export_run(base, st.session_state.ft06_run)

st.sidebar.header('Üretim senaryosu')
st.sidebar.page_link('http://localhost:8511', label='Sentetik A–B–C uygulaması')
with st.sidebar.form('ft06_controls'):
    policy_label = st.selectbox('Sıralama politikası', list(POLICIES), key='ft06_policy')
    machine = st.selectbox('Kapasitesi değişecek makine', [f'M{i}' for i in range(1, 7)], key='ft06_machine')
    capacity = st.slider('Paralel kapasite', 1, 3, 1, key='ft06_capacity')
    gap = st.slider('İşlerin geliş aralığı', 0, 5, 0, key='ft06_gap', help='Özgün FT06: bütün işler zaman sıfırda hazır.')
    submitted = st.form_submit_button('Senaryoyu çalıştır', type='primary', width='stretch')

if submitted:
    scenario = copy.deepcopy(base)
    for resource in scenario['machines']:
        resource['capacity'] = capacity if resource['id'] == machine else 1
    for i, job in enumerate(scenario['jobs']):
        job['release'] = i * gap
    with st.spinner('Üretim simülasyonu çalışıyor…'):
        result = run_scenario(scenario, POLICIES[policy_label])
    st.session_state.ft06_scenario = scenario
    st.session_state.ft06_run = result
    st.session_state.ft06_proposal = None
    export_run(scenario, result)

if st.sidebar.button('Özgün FT06’ya sıfırla', width='stretch'):
    for key in ['ft06_scenario', 'ft06_run', 'ft06_proposal', 'ft06_policy', 'ft06_machine', 'ft06_capacity', 'ft06_gap']:
        st.session_state.pop(key, None)
    st.rerun()

scenario = st.session_state.ft06_scenario
active = st.session_state.ft06_run
original = scenario_hash(scenario) == scenario_hash(base)
st.sidebar.caption('Özgün FT06' if original else 'Değiştirilmiş deney senaryosu: özgün 55 referansı geçerli değildir.')
st.sidebar.caption('Kontrolleri değiştirdikten sonra “Senaryoyu çalıştır” düğmesine bas. Görünen sonuç uygulanan senaryoya aittir.')


# =========================================================
# OPTIMIZATION COMPARISON AND EXPLICIT APPLICATION
# =========================================================

cols = st.columns(4)
cols[0].metric('Tüm işlerin bitişi', f"{active['makespan']:g}")
cols[1].metric('Tamamlanan iş', active['throughput'])
cols[2].metric('Operasyon', len(active['events']))
cols[3].metric('Ortalama iş beklemesi', f"{sum(j['wait'] for j in active['job_summary']) / len(active['job_summary']):.1f}")
st.caption(f"Aktif politika: {active['policy'].upper()} · Koşu: {active['run_id'][:12]} · {'Özgün FT06' if original else 'Deney senaryosu'}")

if st.button('Optimize et', type='primary'):
    with st.spinner('Aynı işler ve kapasiteler için çizelge aranıyor…'):
        proposal = run_scenario(scenario, 'optimized', time_limit=10)
    st.session_state.ft06_proposal = {'result': proposal, 'baseline': copy.deepcopy(active)}

proposal = st.session_state.ft06_proposal
if proposal and proposal['result']['scenario_id'] == active['scenario_id']:
    recommendation = proposal['result']
    before = proposal['baseline']['makespan']
    status_text = 'Optimum kanıtlandı' if recommendation['status'] == 'OPTIMAL' else 'Süre sınırında bulunan uygulanabilir çizelge'
    st.success(f"{status_text}: bitiş {before:g} → {recommendation['makespan']:g} zaman birimi. Aynı iş yükü ve kapasiteyle karşılaştırıldı.")
    if original and recommendation['status'] == 'OPTIMAL':
        st.caption('Özgün FT06 referansı: 55. Bu sonuç kâr veya gerçek fabrikada yatırım getirisi anlamına gelmez.')
    if st.button('Öneriyi uygula', disabled=active['run_id'] == recommendation['run_id']):
        st.session_state.ft06_run = recommendation
        export_run(scenario, recommendation)
        st.rerun()


# =========================================================
# OPERATION CHART AND EXACT-TIME FACTORY REPLAY
# =========================================================

active = st.session_state.ft06_run
st.subheader('Makine çizelgesi')
fig = go.Figure()
for i, job in enumerate(scenario['jobs']):
    events = [event for event in active['events'] if event['job'] == job['id']]
    fig.add_trace(go.Bar(name=job['id'], orientation='h',
        y=[e['machine'] + (f" · slot {e['slot']+1}" if active['machines'][e['machine']]['capacity'] > 1 else '') for e in events],
        x=[e['duration'] for e in events], base=[e['start'] for e in events],
        marker_color=JOB_COLORS[i % len(JOB_COLORS)],
        customdata=[[e['operation']+1,e['start'],e['end']] for e in events],
        hovertemplate='%{fullData.name} · operasyon %{customdata[0]}<br>%{customdata[1]} → %{customdata[2]}<extra></extra>'))
fig.update_layout(barmode='overlay', height=330, xaxis_title='Soyut zaman birimi', yaxis={'autorange':'reversed'}, margin={'t':10,'b':30}, legend={'orientation':'h'})
st.plotly_chart(fig, width='stretch')

cursor = st.slider('Simülasyon zamanı', 0, int(active['makespan']), min(20, int(active['makespan'])), key='ft06_cursor_' + active['run_id'])
running = [e for e in active['events'] if e['start'] <= cursor < e['end']]
waiting = [e for e in active['events'] if e['ready'] <= cursor < e['start']]
done = sum(j['completion'] <= cursor for j in active['job_summary'])
replay_cols = st.columns(3)
replay_cols[0].metric('İşlenen iş', len(running))
replay_cols[1].metric('Kuyrukta bekleyen iş', len(waiting))
replay_cols[2].metric('Biten iş', done)
st.dataframe(pd.DataFrame([{'Makine':key, 'Kapasite':m['capacity'], 'Kullanım (%)':round(m['utilization']*100,1), 'Ortalama bekleme':round(m['average_wait'],2), 'En büyük kuyruk':m['max_queue']} for key,m in active['machines'].items()]), hide_index=True, width='stretch')


# =========================================================
# BLENDER SCENE BUILD FROM THE ACTIVE VALIDATED RUN
# =========================================================

st.subheader('Blender · kavramsal fabrika')
st.caption('Altı makine ve altı ürün, aktif çizelgenin olaylarıyla hareket eder. Fiziksel fabrika ölçüsü veya enerji verisi içermez.')
if st.button('Blender sahnesini güncelle'):
    try:
        with st.spinner('Aktif koşunun Blender sahnesi ve önizlemesi oluşturuluyor…'):
            build_blender(scenario, active)
        st.success('Blender sahnesi aktif koşuyla eşleşiyor.')
    except (OSError, RuntimeError, TimeoutError) as error:
        st.error(str(error))

manifest_path = RUNTIME / 'scene_manifest.json'
if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['run_id'] == active['run_id']:
        preview = Path(manifest['preview'])
        blend = Path(manifest['blend'])
        if preview.is_file():
            st.image(str(preview), caption='Aktif koşudan oluşturulan Blender sahnesi', width='stretch')
        if blend.is_file():
            st.download_button('Blender sahnesini indir', blend.read_bytes(), 'FT06_Pilot.blend', 'application/octet-stream')
            st.caption('Sahneyi Blender’da açıp Space ile oynat. Canlı veri yenilemesi için yanındaki active_run.json dosyasını da sakla; sahnedeki FT06_Bridge metnini çalıştır. Otomatik betik çalıştırma gerekmiyor.')
    else:
        st.warning('Blender sahnesi önceki koşuya ait. Yeni sonucu görmek için sahneyi güncelle.')
else:
    st.info('İlk sahneyi oluşturmak için “Blender sahnesini güncelle” düğmesine bas.')

st.download_button('Aktif koşuyu indir', json.dumps(dict(active, scenario=scenario), ensure_ascii=False, indent=2), 'active_run.json', 'application/json')
with st.expander('Problem kuralları ve ürün rotaları'):
    st.write('Tüm makineler sürekli açık; işlem bölünmez; tampon sınırsız; kurulum ve taşıma süresi sıfır. Ek işçi, arıza, maliyet ve enerji modeli yok.')
    for job in scenario['jobs']:
        st.write(job['id'] + ': ' + ' → '.join(f"{op['machine']} ({op['duration']})" for op in job['operations']))
