import streamlit as st
import yfinance as yf
from yahooquery import Ticker as YQTicker
import pandas as pd
import numpy as np
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import google.generativeai as genai
from PIL import Image
from datetime import datetime

# --- 1. SAYFA AYARLARI VE GÜVENLİK ---
st.set_page_config(page_title="Alpha-Hunt Motoru", layout="wide", initial_sidebar_state="expanded")

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.title("🔒 Kilitli Ekran")
        pwd = st.text_input("Uygulama Şifresi", type="password")
        if st.button("Giriş Yap"):
            if "APP_PASSWORD" in st.secrets and pwd == st.secrets["APP_PASSWORD"]:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Hatalı şifre!")
        st.stop()

check_password()

st.title("🦅 Alpha-Hunt: Odaklanmış Liderler & RS Motoru")
st.info(f"⏱️ **Sistem Hazır.** | 🖥️ Son Güncelleme: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- 2. HAYALET OTURUM (STEALTH SESSION) ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
]

def get_stealth_session():
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    return session

if "http_session" not in st.session_state:
    st.session_state.http_session = get_stealth_session()

# --- 3. DİNAMİK ALPHA PUANLAMA (P/S %50, ROE %30, F/K %20) ---
def calculate_alpha_score(ps, roe, f_pe):
    scores, weights = {}, {}
    if pd.notna(ps) and ps > 0:
        scores['ps'] = 100 if ps < 2 else (80 if ps < 5 else (40 if ps < 10 else 10))
        weights['ps'] = 0.50
    if pd.notna(roe):
        scores['roe'] = 100 if roe > 25 else (70 if roe > 10 else (30 if roe > 0 else 0))
        weights['roe'] = 0.30
    if pd.notna(f_pe) and f_pe > 0:
        scores['fpe'] = 100 if f_pe < 20 else (70 if f_pe < 40 else (40 if f_pe < 70 else 10))
        weights['fpe'] = 0.20
    
    if not scores: return np.nan
    total_active_weight = sum(weights.values())
    return sum(scores[k] * (weights[k] / total_active_weight) for k in scores)

# --- 4. GİRDİLER VE GEMINI YAPAY ZEKA ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 BIST Modu", value=False)

if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = "AAPL, NVDA, TSLA, CVNA, PLTR, SHOP, HOOD"

uploaded_file = st.sidebar.file_uploader("Resmi Geminiye Yükle", type=["png", "jpg", "jpeg"])
if uploaded_file and "GEMINI_API_KEY" in st.secrets:
    if st.sidebar.button("✨ Resmi Oku"):
        with st.spinner("Yapay Zeka resmi inceliyor..."):
            try:
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content(["Tickerları virgülle ver. Başka hiçbir kelime yazma.", Image.open(uploaded_file)])
                st.session_state.current_tickers = response.text.strip()
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"YZ Bağlantı Hatası: {e}")

tickers_input = st.sidebar.text_area("Hisseler", st.session_state.current_tickers, height=150)
bench_ticker = st.sidebar.text_input("Endeks", "XU100.IS" if bist_mode else "^GSPC")
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers]
tickers = list(dict.fromkeys(tickers))

# --- 5. ANALİZ DÖNGÜSÜ ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    with st.spinner("Piyasa fiyatlamaları indiriliyor..."):
        data = yf.download(tickers + [bench_ticker], period="4y", interval="1d", progress=False)["Close"].ffill()
    
    results = []
    progress_bar = st.progress(0)
    debug_area = st.empty()
    st.write("---")
    
    total = len(tickers)
    for i, s in enumerate(tickers):
        now = datetime.now().strftime('%H:%M:%S')
        
        f_pe, ps, roe, sec = np.nan, np.nan, np.nan, "Bilinmiyor"
        try:
            yq = YQTicker(s)
            sd = yq.summary_detail.get(s, {})
            f_pe = sd.get('forwardPE', np.nan)
            ps = sd.get('priceToSalesTrailing12Months', np.nan)
            roe = yq.financial_data.get(s, {}).get('returnOnEquity', np.nan)
            if pd.notna(roe): roe *= 100
            sec = yq.asset_profile.get(s, {}).get('sector', 'Bilinmiyor')
        except: pass

        if not bist_mode and (pd.isna(ps) or pd.isna(roe)):
            try:
                headers = {"User-Agent": random.choice(USER_AGENTS), "Referer": "https://finviz.com/"}
                res = st.session_state.http_session.get(f"https://finviz.com/quote.ashx?t={s}", headers=headers, timeout=10)
                if res.status_code == 200:
                    if pd.isna(ps):
                        m = re.search(r'P/S.*?<b>\s*(.*?)\s*</b>', res.text, re.S)
                        if m and m.group(1) != '-': ps = float(m.group(1))
                    if pd.isna(roe):
                        m = re.search(r'ROE.*?<b>\s*(.*?)\s*%?\s*</b>', res.text, re.S)
                        if m and m.group(1) != '-': roe = float(m.group(1).replace('%', ''))
            except: pass

        res_status = "✅ BAŞARILI" if pd.notna(ps) else "⚠️ EKSİK VERİ"
        na_red = "<span style='color:#ff4b4b; font-weight:bold;'>N/A</span>"
        ps_str = f"{ps:.2f}" if pd.notna(ps) else na_red
        roe_str = f"{roe:.2f}" if pd.notna(roe) else na_red
        fpe_str = f"{f_pe:.2f}" if pd.notna(f_pe) else na_red

        terminal_html = f"""
        <div style="background-color: #0e1117; padding: 15px; border-radius: 8px; border: 1px solid #444; font-family: monospace; color: #e6eaf1; line-height: 1.6;">
            [{now}] 🔍 TALEP: <b>{s}</b> -> Sorgu Tamamlanıyor...<br>
            [{now}] {res_status}: P/S: {ps_str} | ROE: {roe_str} | F/K: {fpe_str}
        </div>
        """
        debug_area.markdown(terminal_html, unsafe_allow_html=True)

        alpha = calculate_alpha_score(ps, roe, f_pe)
        time.sleep(random.uniform(1.0, 2.0))
        
        ideal, hist_chp = 0, -999
        if s in data.columns:
            p = data[s].dropna()
            if len(p) > 63:
                rs = p.pct_change(63).tail(lookback).sum()
                beta = p.pct_change().corr(data[bench_ticker].pct_change())
                ideal = rs / max(0.1, beta)
                hist_chp = p.iloc[-1] / p.tail(lookback).mean() if len(p) >= lookback else -999

        results.append({
            "Hisse": s.replace(".IS",""), "Sektör": sec, "İdealite": ideal,
            "Teknik Ucuzluk": hist_chp, "Alpha Puanı": alpha, "Güncel P/S": ps, 
            "ROE (%)": roe, "İleri F/K": f_pe
        })
        progress_bar.progress((i+1)/len(tickers))

    debug_area.markdown(f'<div style="background-color: #0e1117; padding: 15px; border-radius: 8px; border: 1px solid #198754; color: #198754; font-weight: bold; font-family: monospace;">[{datetime.now().strftime("%H:%M:%S")}] ✅ ANALİZ TAMAMLANDI.</div>', unsafe_allow_html=True)

    # --- 6. GÖRSELLEŞTİRME (TABLO 2 TABLO 1 ALTINDA) ---
    df_master = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
    df_master.index += 1
    
    st.subheader("🔥 Tablo 1: İdealite (RS Rank)")
    st.dataframe(df_master[["Hisse", "Sektör", "İdealite", "Teknik Ucuzluk"]].style
                 .background_gradient(cmap='RdYlGn_r', subset=['Teknik Ucuzluk'], vmin=0.7, vmax=1.3)
                 .format({"İdealite": "{:.2f}", "Teknik Ucuzluk": lambda x: "IPO" if x == -999 else f"{x:.2f}"}, na_rep="N/A"), use_container_width=True)

    st.subheader("🌟 Tablo 2: Alpha Puanı & Temeller")
    st.dataframe(df_master[["Hisse", "Alpha Puanı", "Güncel P/S", "ROE (%)", "İleri F/K"]].style
                 .background_gradient(cmap='Greens', subset=['Alpha Puanı'], vmin=0, vmax=100)
                 .background_gradient(cmap='RdYlGn_r', subset=['Güncel P/S'], vmin=1, vmax=8)
                 .format({"Alpha Puanı": "{:.2f}", "Güncel P/S": "{:.2f}x", "ROE (%)": "{:.2f}%", "İleri F/K": "{:.2f}"}, na_rep="N/A"), use_container_width=True)

    # --- ÖZEL TABLOLAR: LİDERLER VE HAZİNELER ---
    st.divider()
    median_ideal = df_master["İdealite"].median()

    # Tablo 3: Piyasa Liderleri (Kutsal Kâse) - 25 HİSSE
    st.subheader("🦅 Tablo 3: Piyasa Liderleri (Kutsal Kâse)")
    st.caption("ℹ️ Momentum olarak listenin üst yarısında olup, Alpha Puanı en yüksek olan **25** lider hisse.")
    df_leaders = df_master[df_master["İdealite"] >= median_ideal].sort_values("Alpha Puanı", ascending=False).head(25).reset_index(drop=True)
    df_leaders.index += 1
    st.dataframe(df_leaders[["Hisse", "Sektör", "Alpha Puanı", "İdealite", "Güncel P/S", "ROE (%)", "İleri F/K"]].style
                 .background_gradient(cmap='Greens', subset=['Alpha Puanı'], vmin=0, vmax=100)
                 .background_gradient(cmap='RdYlGn', subset=['İdealite'])
                 .format({"Alpha Puanı": "{:.2f}", "İdealite": "{:.2f}", "Güncel P/S": "{:.2f}x", "ROE (%)": "{:.2f}%", "İleri F/K": "{:.2f}"}, na_rep="N/A"), use_container_width=True)

    # Tablo 4: Gizli Hazineler
    st.subheader("💎 Tablo 4: Gizli Hazineler (Pusu Listesi)")
    df_hidden = df_master[df_master["İdealite"] < median_ideal].sort_values("Alpha Puanı", ascending=False).head(10).reset_index(drop=True)
    df_hidden.index += 1
    st.dataframe(df_hidden[["Hisse", "Sektör", "Alpha Puanı", "İdealite", "Güncel P/S", "ROE (%)", "İleri F/K"]].style
                 .background_gradient(cmap='Greens', subset=['Alpha Puanı'], vmin=0, vmax=100)
                 .background_gradient(cmap='RdYlGn', subset=['İdealite'])
                 .format({"Alpha Puanı": "{:.2f}", "İdealite": "{:.2f}", "Güncel P/S": "{:.2f}x", "ROE (%)": "{:.2f}%", "İleri F/K": "{:.2f}"}, na_rep="N/A"), use_container_width=True)

    # --- 7. TRADINGVIEW AKTARIM (SADECE KUTSAL KASE LİSTESİ) ---
    st.divider()
    st.subheader("📋 TradingView Aktarım Listesi (Kutsal Kâse - Top 25)")
    st.caption("ℹ️ Bu liste doğrudan yukarıdaki 25 Piyasa Liderinden oluşturulmuştur.")
    
    c3, c4 = st.columns(2)
    pfx = "BIST:" if bist_mode else "NASDAQ:"
    with c3:
        st.success("**Kutsal Kâse Takip Listesi**")
        st.code(",".join([f"{pfx}{s}" for s in df_leaders["Hisse"]]))
    with c4:
        st.info("**Kutsal Kâse Isı Haritası Girdisi**")
        st.code(" \n".join([f"{i+1}. {sym}" for i, sym in enumerate(df_leaders["Hisse"])]))
