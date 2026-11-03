"""Separate Streamlit UI; legacy synthetic and FT06 applications remain unchanged."""
from pathlib import Path
import copy
import json
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from embroidery_pilot.model import clock, load_scenario, scenario_hash, validate_scenario
from embroidery_pilot.engine import run_scenario
from embroidery_pilot.export import RUNTIME as BASE_RUNTIME, export_run, build_blender, find_blender
from embroidery_pilot.blender_bridge import snapshot_at

COLORS = {'hoop_prepare':'#54a7ff', 'embroidery':'#34d6b0', 'attach_embroidery':'#ffbe55',
          'chenille_change':'#b898ff', 'chenille':'#ff775e'}
LABELS = {'hoop_prepare':'Kasnak / hazırlık', 'embroidery':'Standart nakış', 'attach_embroidery':'Sabitleme nakışı',
          'chenille_change':'Süzene moduna geçiş', 'chenille':'Süzene'}

# =========================================================
# ISOLATED PILOT STATE AND CLEAR DATA PROVENANCE
# =========================================================
st.set_page_config(page_title='TwinOps · Nakış Pilotu', page_icon='🧵', layout='wide')

# =========================================================
# SESSION-SCOPED ARTIFACTS FOR INDEPENDENT DEMO VISITORS
# =========================================================
if 'emb_session_id' not in st.session_state:
    st.session_state.emb_session_id = uuid.uuid4().hex[:24]
RUNTIME = BASE_RUNTIME / st.session_state.emb_session_id
st.markdown('''<style>
.stApp {background:radial-gradient(ellipse at top right,#13303a 0%,#0e151f 48%);}
[data-testid="stMetric"] {background:#172532;border:1px solid #284454;border-radius:12px;padding:16px;}
div[data-testid="stSidebar"] {background:#111e29;}
h1 {letter-spacing:-.04em;} .block-container {padding-top:4rem;}
</style>''', unsafe_allow_html=True)
st.caption('TWINOPS  /  FT06 TEMELİNDEN NAKIŞ PİLOTUNA')
st.title('Üretimi gör. Planı karşılaştır.')
st.write('3 Barudan · 1 Tajima · eşzamanlı kafalar · operatör ve kasnak kısıtları')

if 'emb_scenario' not in st.session_state:
    s = load_scenario()
    st.session_state.emb_scenario = s
    st.session_state.emb_fifo = run_scenario(s)
    st.session_state.emb_optimized = None
    st.session_state.emb_revision = 0
    st.session_state.emb_choice = 'FIFO referans'

scenario = st.session_state.emb_scenario
if scenario['data_kind'] == 'synthetic':
    st.warning('SENTETİK DEMO — Siparişler ve hızlar saha verisi değildir. Bu ekran gerçek ticari kazanç göstermez.')
else:
    st.warning('ÖLÇÜLMÜŞ GİRDİ BEYANI — Kaynak kullanıcı beyanıdır; hızlar senaryo varsayımıdır. Sonuçlar plan tahminidir, gerçekleşmiş ticari kazanç değildir.')
st.sidebar.header('Pilot kontrolü')
st.sidebar.info('Envanter kullanıcı beyanı: M1/M2 15 kafa Barudan 2003; M3 18 kafa Barudan 2015; M4 18 kafa Tajima, yılı/modeli belirsiz.')
st.sidebar.caption('Çalışan eski uygulamalar ve FT06 ayrı kalır. Bu pilot kendi koşu ve sahne klasörüne yazar.')
time_limit = st.sidebar.slider('Çözüm için süre (saniye)', 1, 30, 10)

# =========================================================
# EDITABLE SCENARIO ASSUMPTIONS WITH EXPLICIT APPLY
# =========================================================
with st.expander('Senaryoyu düzenle · hızlar, kaynaklar ve siparişler', expanded=False):
    st.caption('Süreler duvar saati dakikasıdır: 0 = Gün 1 09:00; 480 = Gün 1 17:00; 1440 = Gün 2 09:00. Her plan günü mesai günü varsayılır.')
    st.caption('Parti boyu sabittir. Örnek: 36 ürün / 18 kafa = 2 çevrim; 36 / 15 kafa = 3 çevrim. Son partinin süresi de tam çevrimdir.')
    with st.form('emb_scenario_form'):
        c1,c2,c3,c4 = st.columns(4)
        days = c1.number_input('Plan ufku (gün)', 1, 14, scenario['days'])
        workers = c2.number_input('Operatör havuzu', 1, 20, scenario['workers'])
        hoops = c3.number_input('Kasnak stoku (adet)', 1, 500, scenario['hoops'])
        attend = c4.checkbox('Çalışırken de operatör gerekli', scenario['attend_running'])
        st.write('Makine ayarları · etkin ilmek/dakika değerleri SENARYO VARSAYIMIDIR')
        machines = pd.DataFrame([{**m, 'capabilities':','.join(m['capabilities'])} for m in scenario['machines']])
        machine_edit = st.data_editor(machines, key=f'machine_editor_{st.session_state.emb_revision}',
                                      disabled=['id','label','rate_basis'], hide_index=True, width='stretch',
                                      column_config={'capabilities':st.column_config.TextColumn('Kabiliyet: standard,chenille'),
                                                     'standard_spm':st.column_config.NumberColumn('Nakış ilmek/dk', min_value=1, max_value=3000),
                                                     'attach_spm':st.column_config.NumberColumn('Sabitleme ilmek/dk', min_value=1, max_value=3000),
                                                     'chenille_spm':st.column_config.NumberColumn('Süzene ilmek/dk', min_value=1, max_value=3000)})
        st.write('Sentetik siparişler · gerçek sipariş yüklemek için aşağıdaki JSON sözleşmesini kullan')
        orders = pd.DataFrame([{**o, 'eligible':','.join(o['eligible'])} for o in scenario['orders']])
        order_edit = st.data_editor(orders, key=f'order_editor_{st.session_state.emb_revision}', num_rows='dynamic',
                                    hide_index=True, width='stretch', column_config={
                                        'kind':st.column_config.SelectboxColumn('Tür', options=['standard','chenille'], required=True),
                                        'eligible':st.column_config.TextColumn('Uygun makineler (virgüllü)'),
                                        'quantity':st.column_config.NumberColumn('Adet', min_value=1, step=1),
                                        'batch_size':st.column_config.NumberColumn('Parti adedi', min_value=1, step=1)})
        apply = st.form_submit_button('Değişiklikleri uygula ve FIFO çalıştır', type='primary')
    if apply:
        try:
            new = copy.deepcopy(scenario)
            new.update(days=int(days), workers=int(workers), hoops=int(hoops), attend_running=bool(attend))
            new['machines'] = machine_edit.to_dict('records')
            new['orders'] = order_edit.to_dict('records')
            for m in new['machines']:
                m['capabilities'] = [v.strip() for v in m['capabilities'].split(',')]
            for o in new['orders']:
                o['eligible'] = [v.strip() for v in o['eligible'].split(',')]
            new = validate_scenario(new)
            fifo = run_scenario(new)
            st.session_state.emb_scenario, st.session_state.emb_fifo = new, fifo
            st.session_state.emb_optimized = None
            st.session_state.emb_revision += 1
            st.session_state.emb_choice = 'FIFO referans'
            st.rerun()
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            st.error(f'Ayarlar uygulanmadı: {error} Görünen sonuç önceki uygulanmış senaryoya aittir.')
    uploaded = st.file_uploader('Senaryo JSON yükle (en fazla 1 MiB)', type=['json'])
    if st.button('Yüklenen JSON ile çalıştır', disabled=uploaded is None):
        try:
            if uploaded.size > 1024 * 1024:
                raise ValueError('Dosya 1 MiB sınırını aşıyor.')
            new = validate_scenario(json.loads(uploaded.getvalue().decode('utf-8-sig')))
            fifo = run_scenario(new)
            st.session_state.emb_scenario, st.session_state.emb_fifo = new, fifo
            st.session_state.emb_optimized = None
            st.session_state.emb_revision += 1
            st.session_state.emb_choice = 'FIFO referans'
            st.rerun()
        except (ValueError, TypeError, KeyError) as error:
            st.error(f'JSON uygulanmadı: {error}')

# =========================================================
# FIFO VERSUS CP-SAT ON THE SAME INPUT AND RESOURCE CONSTRAINTS
# =========================================================
if st.button('CP-SAT planını hesapla', type='primary'):
    try:
        with st.spinner('Aynı partiler, mesai ve kaynaklar için çizelge aranıyor…'):
            st.session_state.emb_optimized = run_scenario(scenario, 'optimized', time_limit=time_limit)
        st.session_state.emb_choice = 'CP-SAT planı'
    except (ValueError, RuntimeError) as error:
        st.error(f'Plan oluşturulamadı: {error}')

fifo, optimized = st.session_state.emb_fifo, st.session_state.emb_optimized
choices = ['FIFO referans'] + (['CP-SAT planı'] if optimized else [])
choice = st.radio('Görüntülenen plan', choices, horizontal=True, key='emb_choice')
active = optimized if choice == 'CP-SAT planı' else fifo
st.caption(f"Uygulanan veri: {scenario['data_kind']} · Senaryo {active['scenario_id']} · Koşu {active['run_id']}")
if scenario['data_kind'] == 'measured':
    st.info('Ölçülmüş girdi etiketi kullanıcı beyanıdır; hızlar hâlâ senaryo varsayımıdır. Tahminler gerçek ticari sonuç değildir.')
a,b,c,d = st.columns(4)
a.metric('Planlanan toplam ürün', active['completed_pieces'])
b.metric('İlk mesai sonunda ürün', active['first_shift_pieces'])
c.metric('Toplam sipariş gecikmesi', f"{active['total_tardiness']} dk")
d.metric('Tüm işlerin bitişi', clock(active['makespan']).split(' · ')[1])
d.caption(clock(active['makespan']).split(' · ')[0])
tabs = st.tabs(['Karşılaştırma', 'Üretim zaman çizgisi', '3D ve zaman akışı', 'Varsayımlar ve çıktı'])

with tabs[0]:
    st.subheader('Aynı yük, aynı kaynaklar')
    rows = []
    for label, r in [('FIFO', fifo), ('CP-SAT', optimized)]:
        if r:
            rows.append({'Plan':label, 'Durum':r['status'], 'Toplam gecikme (dk)':r['total_tardiness'],
                         'Bitiş':clock(r['makespan']), 'Toplam adet':r['completed_pieces'],
                         'İlk mesai adedi':r['first_shift_pieces'], 'Operatör dakika':r['operator_minutes']})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    if optimized:
        if optimized['status'] == 'FIFO_FALLBACK':
            st.warning('Süre sınırında CP-SAT çözümü bulunamadı; doğrulanmış FIFO planı gösteriliyor. Optimum iddiası yok.')
        else:
            st.success(f"{'Optimum kanıtlandı' if optimized['status']=='OPTIMAL' else 'Uygulanabilir çözüm bulundu; optimum kanıtlanmadı'} · Amaç: önce toplam sipariş gecikmesi, sonra tüm işlerin bitişi.")
            st.caption(f"Amaç değeri: {optimized['objective_value']:g} · Kanıt alt sınırı: {optimized['objective_bound']:g}. Bu değerler dakika veya para değildir; ağırlıklı amaç fonksiyonudur.")
    st.info('Ekonomik etki: potansiyel senaryo. Gerçek fiyat, katkı payı, fazla mesai, gecikme cezası ve ek ürünün satılabilirliği bilinmediği için TL/kâr/ROI üretilmez.')
    st.caption('Toplam gecikme sipariş bazında toplanır; birden fazla geciken sipariş varsa geçen süreden büyük olabilir. Optimizasyonun her koşuda üstün sonuç vermesi garanti değildir.')

with tabs[1]:
    st.subheader('Partiler ve ardışık işlem fazları')
    fig = go.Figure()
    for phase, color in COLORS.items():
        points = [(e,p) for e in active['events'] for p in e['phases'] if p['phase'] == phase]
        fig.add_trace(go.Bar(name=LABELS[phase], orientation='h',
                            x=[p['duration'] for e,p in points], base=[p['start'] for e,p in points],
                            y=[e['machine'] for e,p in points], marker_color=color,
                            customdata=[[e['batch'],e['pieces'],clock(p['start']),clock(p['end'])] for e,p in points],
                            hovertemplate='%{customdata[0]} · %{customdata[1]} ürün<br>%{customdata[2]} → %{customdata[3]}<extra>%{fullData.name}</extra>'))
    for day in range(scenario['days'] - 1):
        fig.add_vrect(x0=day*1440+480, x1=(day+1)*1440, fillcolor='#84919e', opacity=.12, line_width=0)
    ticks = sorted(set([0, active['makespan']] + [d*1440+k for d in range(scenario['days']) for k in (0,240,480) if d*1440+k<=active['makespan']]))
    fig.update_layout(barmode='overlay', height=400, template='plotly_dark',
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', legend_orientation='h',
                      xaxis={'tickvals':ticks,'ticktext':[clock(t) for t in ticks]}, yaxis={'categoryorder':'array','categoryarray':list(reversed([m['id'] for m in scenario['machines']]))})
    st.plotly_chart(fig, width='stretch')
    st.caption('Hazırlık da makineyi tutar. Tajima sabitleme ve süzene fazları tek partide bitişiktir. Gri alanlar mesai dışıdır.')
    st.dataframe(pd.DataFrame([{'Parti':e['batch'],'Makine':e['machine'],'Adet':e['pieces'],
                              'Başlangıç':clock(e['start']),'Bitiş':clock(e['end'])} for e in active['events']]), hide_index=True, width='stretch')

with tabs[2]:
    st.subheader('Üretim anını incele')
    timestamp = st.slider('Zaman (ilk gün 09:00’dan itibaren dakika)', 0, active['makespan'], min(30,active['makespan']))
    snap = snapshot_at(dict(active, scenario=scenario), timestamp)
    st.write(f"**{snap['clock']}** · Tamamlanan {snap['completed_pieces']} · Operatör {snap['operators']}/{scenario['workers']} · Kasnak {snap['hoops']}/{scenario['hoops']}")
    st.dataframe(pd.DataFrame([{'Parti':bid, 'Durum':v['status'], 'İşlem':LABELS.get(v['phase'],'—'), 'Adet':v['pieces']} for bid,v in snap['batches'].items()]), hide_index=True, width='stretch')
    try:
        find_blender()
        blender_available = True
    except FileNotFoundError:
        blender_available = False
    if not blender_available:
        st.caption('Blender sahnesi üretmek için Blender kurulu yerel ortam gerekir. Plan ve OpenUSD dosyalarını Varsayımlar ve çıktı bölümünden indirebilirsin.')
    if st.button('Bu plan için Blender sahnesi oluştur',disabled=not blender_available):
        try:
            with st.spinner('Ayrı Blender sahnesi ve OpenUSD çıktısı doğrulanıyor…'):
                build_blender(scenario, active,runtime=RUNTIME)
            st.success('Sahne oluşturuldu. Blender dosyasında zaman çizgisini oynatabilirsin.')
        except (RuntimeError, OSError, ValueError) as error:
            st.error(str(error))
    manifest_path = RUNTIME / 'scene_manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['run_id'] == active['run_id']:
            st.image(manifest['preview'], caption='Kavramsal yerleşim · 30. dakika önizlemesi · her token bir parti', width='stretch')
            st.code(manifest['blend'], language=None)
        else:
            st.caption('Önceki önizleme başka koşuya ait. Seçili plan için sahne oluştur.')
    st.caption('Blender 1 kare = 1 duvar saati dakikası. Hazırlık/mode geçişleri ve yüklü kafa sayısı işlenmiştir. Saat etiketi olay anlarını gösterir ve sonraki olaya kadar sabit kalır.')

with tabs[3]:
    st.write(scenario['source'])
    for assumption in scenario['assumptions']:
        st.markdown('- ' + assumption)
    st.download_button('Uygulanan senaryoyu indir', json.dumps(scenario,indent=2,ensure_ascii=False), 'embroidery_scenario.json', 'application/json')
    folder = export_run(scenario, active,runtime=RUNTIME)
    st.download_button('Doğrulanmış planı indir', (folder/'active_run.json').read_bytes(), 'embroidery_run.json', 'application/json')
    st.download_button('OpenUSD sahnesini indir', (folder/'embroidery.usda').read_bytes(), 'embroidery.usda', 'text/plain')
    st.caption('Her ziyaretçinin çıktıları ayrı bir oturum klasöründe tutulur. Kaydetmek istediğin plan ve sahneleri indir.')
