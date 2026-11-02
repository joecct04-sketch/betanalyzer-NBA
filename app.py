import streamlit as st, requests, pandas as pd, unicodedata, difflib, math
st.set_page_config(page_title="BetAnalyzer NBA", layout="wide")

APP_USER = st.secrets.get("APP_USER","joelbet")
APP_PASS = st.secrets.get("APP_PASS","123")

if "auth" not in st.session_state: st.session_state.auth=False
def login():
    st.title("🏀 BetAnalyzer NBA")
    st.caption("EQUIPO vs EQUIPO | PPG Real | Pace | Over/Under 220.5")
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
    """PPG Real últimos 5 + Pace"""
    try:
        r=requests.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team['id']}/schedule",timeout=12)
        pts_for=pts_against=pace_est=c=0
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
                    rival=comps[1].get("team",{}).get("displayName","") if is_home else comps[0].get("team",{}).get("displayName","")
                    partidos.append({"pf":my,"pa":opp,"total":total,"rival":rival,"score":f"{hs}-{aw}"})
                    if c>=5: break
                except: continue
        
        if c==0:
            base=(sum(ord(x) for x in team["name"]) % 20)
            ppg=108+base*0.6; opp=109+(20-base)*0.4
            return {"ppg":ppg,"opp":opp,"total_avg":ppg+opp,"pace":ppg+opp,"pj":0,"matches":[],"source":f"Estimado {team['name']}"}

        ppg=pts_for/c; opp=pts_against/c; total_avg=pace_est/c
        # Pace NBA = si total > 225, equipo rápido
        return {
            "ppg":round(ppg,1),"opp":round(opp,1),"total_avg":round(total_avg,1),
            "pace":round(total_avg,1),"pj":c,"matches":partidos,
            "source":f"ESPN NBA {c}PJ {pts_for}PF/{pts_against}PA - Total avg {total_avg:.1f}"
        }
    except:
        return {"ppg":112.5,"opp":111.0,"total_avg":223.5,"pace":223.5,"pj":0,"matches":[],"source":"Error"}

def calcular_nba(s1,s2):
    # Puntos esperados = Ataque A vs Defensa B
    pts1=(s1["ppg"]+s2["opp"])/2
    pts2=(s2["ppg"]+s1["opp"])/2
    total_exp=pts1+pts2
    diff=pts1-pts2
    # Probabilidades
    pl=38+diff*1.8; pv=38-diff*1.8; pe=24-abs(diff)*0.3; tot=pl+pe+pv
    pace_avg=(s1["pace"]+s2["pace"])/2
    
    return {
        "pts1":pts1,"pts2":pts2,"total":total_exp,"diff":diff,
        "pace":pace_avg,"local":round(pl/tot*100),"visita":round(pv/tot*100),"empate":round(pe/tot*100)
    }

def poisson_nba(lam, line):
    # Para NBA usamos normal aproximada
    try:
        # Desv estándar NBA ~12 puntos
        import math as m
        z=(lam-line)/12
        # prob over = 1 - cdf
        # aproximación
        prob=50 + z*19  # cada punto ~1.9% en NBA
        return max(15, min(85, round(prob)))
    except: return 50

# UI NBA
st.title("🏀 NBA V1.0 - Over/Under Puntos REAL")
c1,c2=st.columns(2)
with c1:
    q1=st.text_input("Equipo NBA 1", placeholder="lakers, warriors", key="nba1")
    t1=st.selectbox("Equipo 1", buscar_nba(q1), format_func=lambda x: f"{x['name']} ({x['short']})", key="s1") if q1 else None
with c2:
    q2=st.text_input("Equipo NBA 2", placeholder="celtics, heat", key="nba2")
    t2=st.selectbox("Equipo 2", buscar_nba(q2), format_func=lambda x: f"{x['name']} ({x['short']})", key="s2") if q2 else None

if t1 and t2:
    if st.button("🔥 ANALIZAR NBA OVER/UNDER", type="primary", use_container_width=True):
        with st.spinner(f"Sacando PPG reales de {t1['name']} y {t2['name']}..."):
            s1=get_nba_stats(t1); s2=get_nba_stats(t2)
            comp=calcular_nba(s1,s2)
            st.session_state['nba']={'t1':t1,'t2':t2,'s1':s1,'s2':s2,'comp':comp}
        st.rerun()

if st.session_state.get('nba'):
    a=st.session_state['nba']; t1=a['t1']; t2=a['t2']; s1=a['s1']; s2=a['s2']; comp=a['comp']
    st.subheader(f"✅ {t1['name']} vs {t2['name']}")
    st.info(f"ℹ️ {s1['source']} | {s2['source']}")
    
    df=pd.DataFrame([
        {"Stat":"PPG Anotados (ataque)",t1['name']:s1['ppg'],t2['name']:s2['ppg'],"Dif":f"{s1['ppg']-s2['ppg']:+.1f}"},
        {"Stat":"PPG Permitidos (defensa)",t1['name']:s1['opp'],t2['name']:s2['opp'],"Dif":f"{s1['opp']-s2['opp']:+.1f} (menos es mejor)"},
        {"Stat":"Total avg últimos 5",t1['name']:s1['total_avg'],t2['name']:s2['total_avg'],"Dif":f"{s1['total_avg']-s2['total_avg']:+.1f}"},
        {"Stat":"Pace (ritmo)",t1['name']:f"{s1['pace']:.1f}",t2['name']:f"{s2['pace']:.1f}","Dif":f"{comp['pace']:.1f} esperado"},
    ])
    st.table(df)
    
    with st.expander("Ver últimos 5 partidos reales"):
        ca,cb=st.columns(2)
        with ca:
            st.write(f"**{t1['name']}**")
            for m in s1['matches']: st.caption(f"{m['score']} vs {m['rival']} | PF:{m['pf']} Total:{m['total']}")
        with cb:
            st.write(f"**{t2['name']}**")
            for m in s2['matches']: st.caption(f"{m['score']} vs {m['rival']} | PF:{m['pf']} Total:{m['total']}")
    
    st.divider()
    m1,m2,m3,m4,m5=st.columns(5)
    m1.metric("Total Esperado",f"{comp['total']:.1f}",f"↑ Over 220.5 {poisson_nba(comp['total'],220.5)}%")
    m2.metric("Pace Esperado",f"{comp['pace']:.1f}",f"↑ Rápido" if comp['pace']>225 else "↓ Lento")
    m3.metric("Pts Local",f"{comp['pts1']:.1f}",f"{s1['ppg']} vs def {s2['opp']}")
    m4.metric("Handicap NBA",f"{comp['diff']:+.1f}",f"Local {comp['local']}% vs {comp['visita']}%")
    m5.metric("Pts Visita",f"{comp['pts2']:.1f}",f"{s2['ppg']} vs def {s1['opp']}")
    
    st.divider()
    st.subheader("🏆 Mejor Apuesta Over/Under - NBA")
    bets=[
        {"Apuesta":f"Over 220.5 ({comp['total']:.1f})","Prob":poisson_nba(comp['total'],220.5),"Edge":comp['total']-220.5,"Tipo":"Over Medio"},
        {"Apuesta":f"Over 230.5 ({comp['total']:.1f})","Prob":poisson_nba(comp['total'],230.5),"Edge":comp['total']-230.5,"Tipo":"Over Alto"},
        {"Apuesta":f"Under 220.5 ({comp['total']:.1f})","Prob":100-poisson_nba(comp['total'],220.5),"Edge":220.5-comp['total'],"Tipo":"Under"},
        {"Apuesta":f"Over 210.5 ({comp['total']:.1f})","Prob":poisson_nba(comp['total'],210.5),"Edge":comp['total']-210.5,"Tipo":"Over Bajo"},
        {"Apuesta":f"Handicap Local {comp['diff']:+.1f}","Prob":comp['local'],"Edge":comp['diff'],"Tipo":"Handicap"},
        {"Apuesta":f"Handicap Visita {comp['diff']:+.1f}","Prob":comp['visita'],"Edge":-comp['diff'],"Tipo":"Handicap"},
    ]
    df=pd.DataFrame(bets)
    df=df.sort_values(["Edge","Prob"],ascending=False)
    df["Rank"]=["🥇 MEJOR" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "" for i in range(len(df))]
    st.dataframe(df,use_container_width=True)
    st.success(f"🎯 MEJOR NBA: {df.iloc[0]['Apuesta']} - {df.iloc[0]['Prob']}% | Edge {df.iloc[0]['Edge']:+.1f} pts")
    
    if comp['total']>230:
        st.info("🔥 Partido de PACE ALTO - Over 220.5 / 230.5 con valor")
    elif comp['total']<215:
        st.warning("🐢 Partido LENTO - Under 220.5 con valor")
