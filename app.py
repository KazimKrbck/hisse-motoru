import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import re
import google.generativeai as genai
from PIL import Image
from datetime import datetime

# --- 1. SAYFA AYARLARI VE GÜVENLİK ---
st.set_page_config(page_title="Alpha-Hunt Motoru", layout="wide")

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

st.title("Alpha-Hunt: Çift Katmanlı Ucuzluk & RsRank Motoru [KazimKrbck]")

# --- 2. GİRDİLER VE GEMINI ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 BIST Modu", value=False)
if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = "THYAO, TUPRS, KCHOL, EREGL" if bist_mode else "AAPL, MSFT, NVDA, AVGO, META, TSLA"

uploaded_file = st.sidebar.file_uploader("Resim Yükle", type=["png", "jpg", "jpeg"])
if uploaded_file and "GEMINI_API_KEY" in st.secrets:
    if st.sidebar.button("✨ Resmi Oku"):
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(["Tickerları virgülle ver.", Image.open(uploaded_file)])
        st.session_state.current_tickers = response.text.strip()
        st.rerun()

tickers_input = st.sidebar.text_area("Hisseler", st.session_state.current_tickers, height=150)
bench_ticker = st.sidebar.text_input("Endeks", "XU100.IS" if bist_mode else "^GSPC")
dxy_ticker = st.sidebar.text_input("DXY/Kur", "TRY=X" if bist_mode else "DX-Y.NYB")
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers]

# --- 3. HAFIZALI VE BAN KORUMALI VERİ MOTORU ---
@st.cache_data(ttl=3600)
def get_prices(ticks): return yf.download(ticks, period="4y", interval="1d", progress=False)["Close"]

@st.cache_data(ttl=86400)
def get_fundamentals(sym, is_bist):
    t_pe, f_pe, sec = np.nan, np.nan, "Bilinmiyor"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        info = yf.Ticker(sym).info
        sec = info.get('sector', 'Bilinmiyor')
        t_pe, f_pe = info.get('trailingPE', np.nan), info.get('forwardPE', np.nan)
        if pd.notna(f_pe) and (f_pe <= 0 or f_pe > 500): f_pe = np.nan
        if (pd.notna(t_pe) or pd.notna(f_pe)): return t_pe, f_pe, sec
    except: pass

    if not is_bist:
        try:
            res = requests.get(f"https://finviz.com/quote.ashx?t={sym}", headers=headers, timeout=5)
            m_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
            if m_fwd and m_fwd.group(1) != '-': f_pe = float(m_fwd.group(1))
            return t_pe, f_pe, sec
        except: pass
    return t_pe, f_pe, sec

# --- 4. ANALİZ MOTORU ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    data = get_prices(tickers + [bench_ticker, dxy_ticker]).ffill().dropna(subset=[bench_ticker])
    p_idx, p_dxy = data[bench_ticker], data[dxy_ticker]
    adj_bench = pd.Series(np.where(p_dxy > 0, p_idx / p_dxy, p_idx), index=data.index)
    
    results, all_fwd = [], []
    
    for s in tickers:
        t_pe, f_pe, sec = get_fundamentals(s, bist_mode)
        if pd.notna(f_pe): all_fwd.append(f_pe)
        time.sleep(0.1) # Ban Koruması
        
        p_close = data[s]
        rs = (p_close.pct_change(63).tail(lookback).sum()) 
        beta = p_close.pct_change().corr(p_idx.pct_change())
        ideal = rs / max(0.1, beta)
        
        hist_chp = p_close.iloc[-1] / p_close.tail(lookback).mean() if len(p_close) >= lookback else -999
        
        results.append({
            "Hisse": s.replace(".IS", ""), "Sektör": sec, "İdealite": ideal,
            "Temel Ucuzluk": f_pe / (t_pe if pd.notna(t_pe) and t_pe > 0 else 1) if pd.notna(f_pe) else np.nan,
            "Teknik Ucuzluk": hist_chp
        })

    # --- 5. TABLO VE GÖRSELLEŞTİRME (Sola Yaslı) ---
    df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
    df.index += 1
    df.index.name = "RS Rank Sırası"

    st.write(f"**Sepet Medyan İleri F/K:** `{round(np.median(all_fwd) if all_fwd else 20.0, 2)}`")
    
    # set_properties ile veriler sola yaslandı
    styled_df = (df.style
                 .set_properties(**{'text-align': 'left'})
                 .background_gradient(cmap='RdYlGn_r', subset=['Temel Ucuzluk'], vmin=0.5, vmax=1.5)
                 .background_gradient(cmap='RdYlGn_r', subset=['Teknik Ucuzluk'], vmin=0.7, vmax=1.3)
                 .format({
                     "İdealite": "{:.2f}",
                     "Temel Ucuzluk": "{:.2f}",
                     "Teknik Ucuzluk": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok")
                 }, na_rep="Veri Yok"))
                 
    st.dataframe(styled_df, use_container_width=True, height=1000)

    # TV Kopyalama Çıktıları
    prefix = "BIST:" if bist_mode else "NASDAQ:"
    c1, c2 = st.columns(2)
    with c1:
        st.success("**TV Takip Listesi (Watchlist) İçin**")
        st.code(",".join([f"{prefix}{sym}" for sym in df["Hisse"].tolist()]), language="text")
    with c2:
        st.info("**TV Isı Haritası İçin (İlk 20 Hisse)**")
        st.code(" \n".join([f"{i+1}. {sym}" for i, sym in enumerate(df["Hisse"].head(20))]), language="text")
