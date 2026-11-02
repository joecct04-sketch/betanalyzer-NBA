import streamlit as st, requests, pandas as pd, unicodedata, difflib, math
st.set_page_config(page_title="BetAnalyzer", layout="wide")

APP_USER = st.secrets.get("APP_USER","joelbet")
APP_PASS = st.secrets.get("APP_PASS","123")

if "auth" not in st.session_state: st.session_state.auth=False
def login():
    st.title("🏀 BetAnalyzer NBA")
    u=st.text_input("Usuario"); p=st.text_input("Clave",type="password")
    if st.button("Entrar"):
        if u==APP_USER and p==APP_PASS:
            st.session_state.auth=True; st.rerun()
        else: st.error("Mal")
if not st.session_state.auth: login(); st.stop()

def normalize(t): return unicodedata.normalize('NFD', t).encode('ascii','ignore').decode('ascii').lower()

@st.cache_data(ttl=86400)
def load_nba_teams():
    all_t=[]
    try:
        r=requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",timeout=12)
        if r.status_code==200:
            for tm in r.json().get("sports",[{}])[0].get("leagues",[{}])[0].get("teams",[]):
                t=tm["team"]
                all_t.append({"id":t["id"],"name":t["displayName"],"short":t.get("abbreviation",""),"search_key":normalize(t["displayName"]+" "+t.get("abbreviation",""))})
    except: pass
    return all_t
NBA_TEAMS=load_nba_teams()
st.sidebar.success(f"✅ {len(NBA_TEAMS)} equipos NBA")
st.sidebar.caption("V1.1 | Localía +3.5 | Moneyline | ATS | Over/Under")

def buscar_nba(q):
    if not q or len(q)<2: return []
    qn=normalize(q)
    res=[t for t in NBA_TEAMS if qn in t["search_key"]]
    if not res:
        close=difflib.get_close_matches(q, [t["name"] for t in NBA_TEAMS], n=8, cutoff=0.35)
        res=[t for t in NBA_TEAMS if t["name"] in close]
    return res[:10]

@st.cache_data(ttl=3600)
def get_nba_stats(team):
    try:
        r=requests.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team['id']}/schedule",timeout=12)
        pts_for=pts_against=pace_est=c=w=l=0
        pts_for_home=pts_for_away=0
        ch=ca=0
        partidos=[]
        if r.status_code==200:
            for ev in reversed(r.json().get("events",[])):
                try:
                    comp=ev.get("competitions",[{}])[0]
                    if not comp.get("status",{}).get("type",{}).get("completed"): continue
                    comps=comp.get("competitors",[])
                    if len(comps)<2: continue
                    hs=int(comps[0].get("score",0)); aw=int(comps[1].get("score",0))
                    if hs==0 and aw==0: continue
                    is_home=str(comps[0].get("id"))==str(team["id"])
                    my=hs if is_home else aw; opp=aw if is_home else hs
                    total=hs+aw
                    pts_for+=my; pts_against+=opp; pace_est+=total; c+=1
                    if is_home: pts_for_home+=my; ch+=1
                    else: pts_for_away+=my; ca+=1
                    if my>opp: w+=1
                    else: l+=1
                    rival=comps[1].get("team",{}).get("displayName","") if is_home else comps[0].get("team",{}).get("displayName","")
                    partidos.append({"pf":my,"pa":opp,"total":total,"rival":rival,"score":f"{hs}-{aw}","home":is_home,"win":my>opp})
                    if c>=5: break
                except: continue
        
        if c==0:
            base=(sum(ord(x) for x in team["name"]) % 20)
            ppg=108+base*0.6; opp=109+(20-base)*0.4
            return {"ppg":ppg,"opp":opp,"total_avg":ppg+opp,"pace":ppg+opp,"ppg_home":ppg+2,"ppg_away":ppg-2,"w":2,"l":3,"win_pct":40,"pj":0,"matches":[],"source":f"Estimado"}

        ppg=pts_for/c; opp_pts=pts_against/c
        ppg_h=pts_for_home/ch if ch>0 else ppg+2
        ppg_a=pts_for_away/ca if ca>0 else ppg-2
        return {
            "ppg":round(ppg,1),"opp":round(opp_pts,1),"total_avg":round(pace_est/c,1),
            "pace":round(pace_est/c,1),"ppg_home":round(ppg_h,1),"ppg_away":round(ppg_a,1),
            "w":w,"l":l,"win_pct":round(w/c*100),"pj":c,"matches":partidos,
            "source":f"{c}PJ {w}W-{l}L PPG {ppg:.1f} (Home {ppg_h:.1f} / Away {ppg_a:.1f})"
        }
    except:
        return {"ppg":112.5,"opp":111.0,"total_avg":223.5,"pace":223.5,"ppg_home":114.5,"ppg_away":110.5,"w":3,"l":2,"win_pct":60,"pj":0,"matches":[],"source":"Error"}

def calcular_nba(s1,s2):
    # NBA: Localía vale +3.5 puntos
    HOME_ADV = 3.5
    # Puntos esperados con localía
    pts_local_base = (s1["ppg_home"] + s2["opp"]) / 2
    pts_visita_base = (s2["ppg_away"] + s1["opp"]) / 2
    
    pts1 = pts_local_base + HOME_ADV/2  # Local recibe ventaja
    pts2 = pts_visita_base - HOME_ADV/2
    
    total_exp = pts1 + pts2
    diff = pts1 - pts2  # Handicap
    
    # Probabilidad Moneyline con diferencia + forma
    forma_diff = (s1["win_pct"] - s2["win_pct"])*0.15  # 15% de peso a racha
    diff_ajustado = diff + forma_diff
    
    # Fórmula NBA para ML: cada 1 punto de diff = ~2.8% de prob
    prob_local = 50 + diff_ajustado*2.8
    prob_local = max(15, min(85, prob_local))
    prob_visita = 100 - prob_local
    
    # ATS - Against The Spread (Handicap -5.5 es el más común)
    # Prob de cubrir -5.5
    spread = 5.5
    prob_local_cubre = 50 + (diff_ajustado - spread)*4.5
    prob_local_cubre = max(15, min(85, prob_local_cubre))
    
    pace_avg = (s1["pace"] + s2["pace"])/2
    
    return {
        "pts1":pts1,"pts2":pts2,"total":total_exp,"diff":diff,
        "diff_ajustado":diff_ajustado,"pace":pace_avg,
        "local_ml":round(prob_local),"visita_ml":round(prob_visita),
        "local_ats_5":round(prob_local_cubre),"visita_ats_5":round(100-prob_local_cubre),
        "forma":forma_diff
    }

def poisson_nba(lam, line):
    try:
        z=(lam-line)/12
        prob=50 + z*19
        return max(15, min(85, round(prob)))
    except: return 50

# UI
st.title("🏀 NBA V1.1 - Over/Under + LOCAL/VISITA")
c1,c2=st.columns(2)
with c1:
    q1=st.text_input("Equipo Local", placeholder="lakers, warriors", key="nba1")
    t1=st.selectbox("Local", buscar_nba(q1), format_func=lambda x: f"{x['name']} ({x['short']})", key="s1") if q1 else None
with c2:
    q2=st.text_input("Equipo Visita", placeholder="celtics, heat", key="nba2")
    t2=st.selectbox("Visita", buscar_nba(q2), format_func=lambda x: f"{x['name']} ({x['short']})", key="s2") if q2 else None

if t1 and t2:
    if st.button("🔥 ANALIZAR NBA COMPLETO", type="primary", use_container_width=True):
        with st.spinner(f"Analizando {t1['name']} (Local) vs {t2['name']} (Visita)..."):
            s1=get_nba_stats(t1); s2=get_nba_stats(t2)
            comp=calcular_nba(s1,s2)
            st.session_state['nba']={'t1':t1,'t2':t2,'s1':s1,'s2':s2,'comp':comp}
        st.rerun()

if st.session_state.get('nba'):
    a=st.session_state['nba']; t1=a['t1']; t2=a['t2']; s1=a['s1']; s2=a['s2']; comp=a['comp']
    st.subheader(f"✅ {t1['name']} (Local) vs {t2['name']} (Visita)")
    st.info(f"ℹ️ {t1['name']}: {s1['source']} | {t2['name']}: {s2['source']}")
    
    df=pd.DataFrame([
        {"Stat":"PPG Total",t1['name']:s1['ppg'],t2['name']:s2['ppg'],"Dato":f"Dif {s1['ppg']-s2['ppg']:+.1f}"},
        {"Stat":"PPG Home/Away",t1['name']:f"{s1['ppg_home']} en casa",t2['name']:f"{s2['ppg_away']} fuera","Dato":"Localía NBA +3.5"},
        {"Stat":"Racha últimos 5",t1['name']:f"{s1['w']}W-{s1['l']}L {s1['win_pct']}%",t2['name']:f"{s2['w']}W-{s2['l']}L {s2['win_pct']}%","Dato":f"Forma {comp['forma']:+.1f}"},
        {"Stat":"Defensa (pts permitidos)",t1['name']:s1['opp'],t2['name']:s2['opp'],"Dato":"Menos es mejor"},
    ])
    st.table(df)
    
    st.divider()
    # METRICAS VERDES COMO EN FUTBOL
    m1,m2,m3,m4,m5=st.columns(5)
    m1.metric("Total Esp",f"{comp['total']:.1f}",f"↑ Over 220.5 {poisson_nba(comp['total'],220.5)}%")
    m2.metric("Pace",f"{comp['pace']:.1f}",f"↑ {'Rápido Over' if comp['pace']>225 else 'Lento Under'}")
    m3.metric(f"Moneyline {t1['short']}",f"{comp['local_ml']}%",f"↑ Local gana {comp['pts1']:.1f} pts esp")
    m4.metric("Handicap",f"{comp['diff']:+.1f}",f"↑ AH NBA {comp['diff']:+.1f} | ATS -5.5: {comp['local_ats_5']}%")
    m5.metric(f"Moneyline {t2['short']}",f"{comp['visita_ml']}%",f"↑ Visita {comp['pts2']:.1f} pts esp")
    
    st.divider()
    st.subheader("🏆 Mejor Apuesta - Ahora con Local/Visita")
    
    bets=[
        {"Apuesta":f"Over 220.5 ({comp['total']:.1f})","Prob":poisson_nba(comp['total'],220.5),"Edge":comp['total']-220.5,"Tipo":"Over"},
        {"Apuesta":f"LOCAL ML {t1['short']} gana ({comp['local_ml']}%)","Prob":comp['local_ml'],"Edge":comp['diff_ajustado'],"Tipo":"Moneyline Local","Por qué":f"{comp['pts1']:.1f} vs {comp['pts2']:.1f} + Localía +3.5"},
        {"Apuesta":f"VISITA ML {t2['short']} gana ({comp['visita_ml']}%)","Prob":comp['visita_ml'],"Edge":-comp['diff_ajustado'],"Tipo":"Moneyline Visita","Por qué":f"Racha {s2['win_pct']}%"},
        {"Apuesta":f"Over 230.5 ({comp['total']:.1f})","Prob":poisson_nba(comp['total'],230.5),"Edge":comp['total']-230.5,"Tipo":"Over Alto"},
        {"Apuesta":f"Handicap {t1['short']} -5.5 ({comp['local_ats_5']}%)","Prob":comp['local_ats_5'],"Edge":comp['diff_ajustado']-5.5,"Tipo":"ATS Local","Por qué":f"Necesita ganar por 6+"},
        {"Apuesta":f"Handicap {t2['short']} +5.5 ({comp['visita_ats_5']}%)","Prob":comp['visita_ats_5'],"Edge":5.5-comp['diff_ajustado'],"Tipo":"ATS Visita","Por qué":f"Cubre si pierde por <6"},
        {"Apuesta":f"Under 220.5 ({comp['total']:.1f})","Prob":100-poisson_nba(comp['total'],220.5),"Edge":220.5-comp['total'],"Tipo":"Under"},
    ]
    df_bets=pd.DataFrame(bets)
    df_bets=df_bets.sort_values(["Edge","Prob"],ascending=False)
    df_bets["Rank"]=["🥇 MEJOR" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "" for i in range(len(df_bets))]
    st.dataframe(df_bets[["Rank","Apuesta","Prob","Edge","Tipo","Por qué"]],use_container_width=True)
    
    mejor=df_bets.iloc[0]
    st.success(f"🎯 MEJOR: {mejor['Apuesta']} - {mejor['Prob']}% | {mejor['Por qué']}")
    
    if comp['local_ml']>=62:
        st.info(f"💰 {t1['name']} muy favorito en casa: ML {comp['local_ml']}% | Handicap {comp['diff']:+.1f}")
    elif comp['visita_ml']>=62:
        st.warning(f"🔥 Sorpresa posible: {t2['name']} fuera gana {comp['visita_ml']}% a pesar de ser visita")
