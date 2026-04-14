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

st.title("🦅 Alpha-Hunt: Değerleme & RS Motoru (PEG-Free)")
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
    
    # P/S Puanı (%50) - Düşük iyi
    if pd.notna(ps) and ps > 0:
        scores['ps'] = 100 if ps < 2 else (80 if ps < 5 else (40 if ps < 10 else 10))
        weights['ps'] = 0.50
        
    # ROE Puanı (%30) - Yüksek iyi
    if pd.notna(roe):
        scores['roe'] = 100 if roe > 25 else (70 if roe > 10 else (30 if roe > 0 else 0))
        weights['roe'] = 0.30
        
    # İleri F/K Puanı (%20) - Makul düzey iyi
    if pd.notna(f_pe) and f_pe > 0:
        scores['fpe'] = 100 if f_pe < 20 else (70 if f_pe < 40 else (40 if f_pe < 70 else 10))
        weights['fpe'] = 0.20
    
    if not scores: return np.nan
    
    total_active_weight = sum(weights.values())
    return sum(scores[k] * (weights[k] / total_active_weight) for k in scores)

# --- 4. GİRDİLER VE GEMINI ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 BIST Modu", value=False)
tickers_input = st.sidebar.text_area("Hisseler", st.session_state.get('current_tickers', 'AAPL, NVDA, CVNA, PLTR, SHOP'), height=150)
bench_ticker = st.sidebar.text_input("Endeks", "XU100.IS" if bist_mode else "^GSPC")
lookback = st.sidebar.number_input("LookBack", value=500)

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
        
        # 1. Debug Satırı: Başvuru
        debug_msg = f"[{now}] 🔍 TALEP: {s} -> YahooQuery & Finviz Sorgulanıyor..."
        
        # Veri Çekme (Öncelik YahooQuery)
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

        # Finviz Fallback (Sağlam Regex ile)
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

        # 2. Debug Satırı: Sonuç
        res_status = "✅ BAŞARILI" if pd.notna(ps) else "⚠️ EKSİK VERİ"
        debug_msg += f"\n[{now}] {res_status}: P/S:{ps if pd.notna(ps) else 'N/A'} | ROE:{roe if pd.notna(roe) else 'N/A'} | F/K:{f_pe if pd.notna(f_pe) else 'N/A'}"
        debug_area.code(debug_msg)

        alpha = calculate_alpha_score(ps, roe, f_pe)
        time.sleep(random.uniform(1.0, 2.0))
        
        # RS Rank (Momentum) Hesaplaması
        ideal = 0
        if s in data.columns:
            p = data[s].dropna()
            if len(p) > 63:
                rs = p.pct_change(63).tail(lookback).sum()
                beta = p.pct_change().corr(data[bench_ticker].pct_change())
                ideal = rs / max(0.1, beta)

        results.append({"Hisse": s.replace(".IS",""), "Alpha Puanı": alpha, "Güncel P/S": ps, "ROE (%)": roe, "İleri F/K": f_pe, "İdealite": ideal, "Sektör": sec})
        progress_bar.progress((i+1)/total)

    # --- 6. GÖRSELLEŞTİRME ---
    df_master = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
    df_master.index += 1
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🔥 Tablo 1: İdealite (RS Rank)")
        st.caption("ℹ️ **Teknik:** Momentum/Beta rasyosu. Trenddeki en güçlü hisseleri zirveye taşır.")
        st.dataframe(df_master[["Hisse", "Sektör", "İdealite"]].style
                     .set_properties(**{'text-align': 'left'})
                     .background_gradient(cmap='RdYlGn', subset=['İdealite']), use_container_width=True)

    with col2:
        st.subheader("🌟 Tablo 2: Alpha Puanı & Temeller")
        st.caption("ℹ️ **Alpha:** P/S (%50), ROE (%30), F/K (%20). Eksik veri ağırlığı diğerlerine dağıtılır.")
        st.dataframe(df_master[["Hisse", "Alpha Puanı", "Güncel P/S", "ROE (%)", "İleri F/K"]].style
                     .set_properties(**{'text-align': 'left'})
                     .background_gradient(cmap='Greens', subset=['Alpha Puanı'], vmin=0, vmax=100)
                     .background_gradient(cmap='RdYlGn_r', subset=['Güncel P/S'], vmin=1, vmax=8)
                     .format({"Alpha Puanı": "{:.0f}", "Güncel P/S": "{:.2f}x", "ROE (%)": "{:.1f}%", "İleri F/K": "{:.1f}"}, na_rep="N/A"), use_container_width=True)

    # --- 7. DİNAMİK TRADINGVIEW AKTARIM ---
    st.divider()
    st.subheader("📋 TradingView Aktarım Listeleri")
    sort_opt = st.radio("Listeyi Kopyalamadan Önce Sıralama Seçin:", ["İdealite", "Alpha Puanı", "Güncel P/S"], horizontal=True)
    
    # Küçükten büyüğe mi (P/S için evet, diğerleri için hayır)
    df_ex = df_master.sort_values(sort_opt, ascending=(sort_opt=="Güncel P/S"))
    
    c3, c4 = st.columns(2)
    prefix = "BIST:" if bist_mode else "NASDAQ:"
    with c3:
        st.success(f"**Takip Listesi ({sort_opt} Sıralı)**")
        st.code(",".join([f"{prefix}{s}" for s in df_ex["Hisse"]]))
    with c4:
        st.info(f"**Isı Haritası Girdisi (İlk 38 - {sort_opt} Sıralı)**")
        st.code(" \n".join([f"{i+1}. {sym}" for i, sym in enumerate(df_ex["Hisse"].head(38))]))
