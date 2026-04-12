import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import re
import google.generativeai as genai
from PIL import Image

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Hisse Sıralama Motoru", layout="wide")
st.title("🔥 İdealite ve F/K Isı Haritası")
st.markdown("Likidite ayarlı teknik metrikler ve normalize edilmiş F/K haritası.")

# --- GİRDİLER VE GEMINI YAPAY ZEKA ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul (BIST) Modu", value=False)

if bist_mode:
    default_tickers, default_bench, default_dxy = "THYAO, TUPRS", "XU100.IS", "TRY=X"
else:
    default_tickers, default_bench, default_dxy = "AAPL, NVDA, MSFT", "^GSPC", "DX-Y.NYB"

# --- GEMINI GİZLİ KASA ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    st.sidebar.success("🔑 Gemini API Hazır!")
else:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")
    if api_key: genai.configure(api_key=api_key)

# --- RESİM OKUMA ---
uploaded_file = st.sidebar.file_uploader("Resim Yükle", type=["png", "jpg", "jpeg"])
if "current_tickers" not in st.session_state: st.session_state.current_tickers = default_tickers

if uploaded_file and st.sidebar.button("✨ Resmi Oku"):
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        img = Image.open(uploaded_file)
        response = model.generate_content(["Resimdeki borsa sembollerini virgülle ayırarak ver.", img])
        st.session_state.current_tickers = response.text.strip()
        st.sidebar.success("Hisseler güncellendi!")
    except Exception as e: st.sidebar.error(f"Hata: {e}")

st.sidebar.markdown("---")
tickers_input = st.sidebar.text_area("Hisse Sembolleri", st.session_state.current_tickers, height=150)
bench_ticker = st.sidebar.text_input("Piyasa Endeksi", default_bench)
dxy_ticker = st.sidebar.text_input("DXY / Kur", default_dxy)
lookback = st.sidebar.number_input("Geriye Bakış (Gün)", value=500)

# --- ANALİZ MOTORU ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    with st.spinner("Hesaplanıyor..."):
        raw_list = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
        tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_list]
        
        all_t = tickers + [bench_ticker, dxy_ticker]
        data = yf.download(all_t, period="4y", interval="1d")["Close"].ffill().dropna(subset=[bench_ticker])
        
        # Matematiksel işlemler
        p_index, p_curr = data[bench_ticker], data[dxy_ticker]
        adj_bench = (p_index / p_curr) if (p_curr > 0).all() else p_index
        
        def get_rs(s): return (0.4 * s.pct_change(63) + 0.2 * s.pct_change(126) + 0.2 * s.pct_change(189) + 0.2 * s.pct_change(252)) * 100
        bench_rs = get_rs(adj_bench)
        
        results = []
        f_data = {}
        for s in tickers:
            try:
                info = yf.Ticker(s).info
                f_data[s] = info.get('forwardPE', info.get('trailingPE', np.nan))
            except: f_data[s] = np.nan
        
        avg_pe = np.median([v for v in f_data.values() if pd.notna(v) and v > 0]) if f_data else 15.0

        for s in tickers:
            if s not in data.columns: continue
            stock_rs = get_rs(data[s])
            diff = (stock_rs - bench_rs).tail(lookback)
            pn_ratio = diff[diff > 0].sum() / (abs(diff[diff <= 0].sum()) or 0.0001)
            
            ret, m_ret = data[s].pct_change().tail(252), p_index.pct_change().tail(252)
            beta = (ret.corr(m_ret) * (ret.std() / m_ret.std())) if m_ret.std() > 0 else 1.0
            beta_score = pn_ratio / (max(beta, 0.1))
            
            pe = f_data.get(s, np.nan)
            results.append({
                "Hisse": s.replace(".IS", ""),
                "Saf Oran": round(pn_ratio, 2),
                "Beta Skor": round(beta_score, 2),
                "İdealite": round((pn_ratio + beta_score) / 2, 2),
                "F/K": round(pe, 2) if pd.notna(pe) else np.nan,
                "Ucuzluk": pe / avg_pe if pd.notna(pe) else np.nan
            })

        if results:
            df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
            
            # SOLA YASLI TASARIM
            styled = df.style.set_properties(**{'text-align': 'left'}) \
                .background_gradient(cmap='RdYlGn_r', subset=['Ucuzluk'], vmin=0.5, vmax=2.0) \
                .format({"Ucuzluk": "{:.2f}", "F/K": "{:.2f}"}, na_rep="Veri Yok")
            
            st.dataframe(
                styled,
                use_container_width=False,
                column_config={
                    "Hisse": st.column_config.TextColumn("Hisse", width="small"),
                    "Saf Oran": st.column_config.NumberColumn("Saf Oran", width="small"),
                    "Beta Skor": st.column_config.NumberColumn("Beta Skor", width="small"),
                    "İdealite": st.column_config.NumberColumn("İdealite", width="small"),
                    "F/K": st.column_config.NumberColumn("F/K", width="small"),
                    "Ucuzluk": st.column_config.NumberColumn("Ucuzluk (x)", width="small"),
                }
            )
