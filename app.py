import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import re
import google.generativeai as genai
from PIL import Image

# --- SAYFA AYARLARI VE GÜVENLİK ---
st.set_page_config(page_title="Alpha-Hunt: RS Rank Tarayıcı", layout="wide")

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

st.title("Alpha-Hunt: TradingView İçin RS Rank Tarayıcı")

# --- PARAMETRELER ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul Modu", value=False)
exclude_finance = st.sidebar.checkbox("Banka, Finans, Kripto, Kumar Hariç Tut", value=True)

default_tickers = "THYAO, TUPRS, KCHOL, EREGL" if bist_mode else "AAPL, MSFT, GOOGL, NVDA, META"
default_bench = "XU100.IS" if bist_mode else "^GSPC"

# Gemini
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
uploaded_file = st.sidebar.file_uploader("Resimden Hisse Çek", type=["png", "jpg", "jpeg"])
if "current_tickers" not in st.session_state: st.session_state.current_tickers = default_tickers

if uploaded_file and st.sidebar.button("✨ Resmi Oku"):
    with st.spinner("Gemini inceliyor..."):
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            resp = model.generate_content(["Sadece tickerları virgülle ver.", Image.open(uploaded_file)])
            st.session_state.current_tickers = resp.text.strip()
            st.rerun()
        except Exception as e: st.error(str(e))

tickers_input = st.sidebar.text_area("Semboller", st.session_state.current_tickers, height=120)
bench_ticker = st.sidebar.text_input("Endeks", default_bench)
dxy_ticker = st.sidebar.text_input("Likidite (DXY)", "TRY=X" if bist_mode else "DX-Y.NYB")
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers]

# --- FONKSİYONLAR ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price(ticks): return yf.download(ticks, period="4y", interval="1d", progress=False)["Close"]

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_sector(sym):
    try:
        sec = yf.Ticker(sym).info.get('sector', yf.Ticker(sym).info.get('industry', 'Bilinmiyor'))
        if sec != "Bilinmiyor": return sec
    except: pass
    if not bist_mode:
        try:
            res = requests.get(f"https://finviz.com/quote.ashx?t={sym}", headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            m = re.search(r'f=sec_[^>]+>([^<]+)</a>', res.text)
            if m: return m.group(1)
        except: pass
    return "Bilinmiyor"

# --- ANALİZ MOTORU ---
if st.sidebar.button("🚀 Tarama ve Sıralama Başlat", type="primary"):
    with st.spinner("Hesaplanıyor..."):
        data = fetch_price(tickers + [bench_ticker, dxy_ticker]).ffill().dropna(subset=[bench_ticker])
        p_idx, p_dxy = data[bench_ticker], data[dxy_ticker]
        adj_bench = pd.Series(np.where(p_dxy > 0, p_idx / p_dxy, p_idx), index=data.index)
        
        b_roc = (0.4 * adj_bench.pct_change(63) + 0.2 * adj_bench.pct_change(126) + 
                 0.2 * adj_bench.pct_change(189) + 0.2 * adj_bench.pct_change(252)) * 100
        idx_ret = p_idx.pct_change()

        results, bl = [], ["bank", "financial", "credit", "crypto", "gambling", "banka", "finans", "sigorta", "yatırım"]
        
        for s in tickers:
            if s not in data.columns or data[s].isnull().all(): continue
            sec = fetch_sector(s)
            
            # Filtreye takılanları ve AVGO istisnasını yönet
            is_blacklisted = any(b in sec.lower() for b in bl)
            if exclude_finance and is_blacklisted and "AVGO" not in s: continue

            p_close = data[s]
            s_roc = (0.4 * p_close.pct_change(63) + 0.2 * p_close.pct_change(126) + 
                     0.2 * p_close.pct_change(189) + 0.2 * p_close.pct_change(252)) * 100
            diff = (s_roc - b_roc).tail(lookback)
            rs = diff[diff > 0].sum() / (abs(diff[diff <= 0].sum()) if diff[diff <= 0].sum() != 0 else 0.0001)
            
            ret, iret = p_close.pct_change().tail(252), idx_ret.tail(252)
            beta = (ret.corr(iret) * (ret.std() / iret.std())) if iret.std() > 0 else 1.0
            ideal = (rs + (rs / max(0.1, beta))) / 2.0

            clean_sym = s.replace(".IS", "")
            results.append({"Hisse": clean_sym, "İdealite": ideal, "Sektör": sec})

    if results:
        df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
        st.dataframe(df, use_container_width=True)
        
        # TRADINGVIEW İÇİN KOPYALAMA KODU (Prefix'li)
        st.markdown("### 📋 TradingView İçin Kopyala")
        prefix = "BIST:" if bist_mode else "NASDAQ:"
        
        # Hisseleri "BIST:THYAO,BIST:TUPRS" veya "NASDAQ:AAPL,NASDAQ:NVDA" formatında birleştirir
        tv_string = ",".join([f'"{prefix}{sym}"' for sym in df["Hisse"].tolist()])
        
        st.code(tv_string, language="text")
