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

# --- 1. SAYFA VE GÜVENLİK ---
st.set_page_config(page_title="Alpha-Hunt Motoru", layout="wide")

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.title("🔒 Kilitli Ekran")
        st.warning("Bu uygulama Kâzım Karabacak'a aittir. Lütfen giriş yapın.")
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
st.markdown("Analiz: **İdealite (Trend)** + **Temel Büyüme (F/K)** + **Teknik Ortalamaya Dönüş (500G)**.")

# --- 2. PARAMETRELER VE GEMINI ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul (BIST) Modu", value=False)

default_tickers = "THYAO, TUPRS, KCHOL, EREGL, FROTO" if bist_mode else "AAPL, MSFT, GOOGL, NVDA, META, TSLA, AVGO"
default_bench = "XU100.IS" if bist_mode else "^GSPC"
default_dxy = "TRY=X" if bist_mode else "DX-Y.NYB"

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Resimden Hisse Çıkarma")
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    st.sidebar.success("🔑 Gemini API Anahtarı yüklendi!")
else:
    st.sidebar.warning("Gemini API Anahtarı eksik!")

uploaded_file = st.sidebar.file_uploader("Resim Yükle", type=["png", "jpg", "jpeg"])
if "current_tickers" not in st.session_state: st.session_state.current_tickers = default_tickers

if uploaded_file and "GEMINI_API_KEY" in st.secrets:
    if st.sidebar.button("✨ Resmi Oku"):
        with st.spinner("Gemini inceliyor..."):
            try:
                model = genai.GenerativeModel('gemini-2.5-flash')
                prompt = "Resimdeki tickerları bul. SADECE büyük harflerle, virgülle ayrılmış liste ver. Örn: AAPL, MSFT"
                response = model.generate_content([prompt, Image.open(uploaded_file)])
                st.session_state.current_tickers = response.text.strip()
                st.rerun()
            except Exception as e: st.sidebar.error(str(e))

st.sidebar.markdown("---")
tickers_input = st.sidebar.text_area("Hisse Sembolleri (Virgülle ayırın)", st.session_state.current_tickers, height=150)
bench_ticker = st.sidebar.text_input("Endeks", default_bench)
dxy_ticker = st.sidebar.text_input("Likidite (DXY)", default_dxy)
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers]

# --- 3. HAFIZA VE BAN KORUMALI VERİ MOTORU ---
def calc_roc(series, periods): return series.pct_change(periods=periods) * 100
def calc_weighted_rs(series): return (0.4 * calc_roc(series, 63) + 0.2 * calc_roc(series, 126) + 0.2 * calc_roc(series, 189) + 0.2 * calc_roc(series, 252))

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price_data(all_ticks): return yf.download(all_ticks, period="4y", interval="1d", progress=False)["Close"]

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_fundamental_data(sym, is_bist):
    t_pe, f_pe, sec = np.nan, np.nan, "Bilinmiyor"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"} # Ban Koruması
    
    try:
        info = yf.Ticker(sym).info
        sec = info.get('sector', info.get('industry', 'Bilinmiyor'))
        t_pe = info.get('trailingPE', np.nan)
        f_pe = info.get('forwardPE', np.nan)
        if pd.notna(t_pe) and (t_pe <= 0 or t_pe > 500): t_pe = np.nan
        if pd.notna(f_pe) and (f_pe <= 0 or f_pe > 500): f_pe = np.nan
        if (pd.notna(t_pe) or pd.notna(f_pe)) and sec != "Bilinmiyor":
            return t_pe, f_pe, sec, f"✅ {sym}: Yahoo OK", "success"
    except: pass

    if not is_bist:
        try:
            res = requests.get(f"https://finviz.com/quote.ashx?t={sym}", headers=headers, timeout=5)
            if sec == "Bilinmiyor":
                m = re.search(r'f=sec_[^>]+>([^<]+)</a>', res.text)
                if m: sec = m.group(1)
            m_pe = re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
            m_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
            if m_pe and m_pe.group(1) != '-': t_pe = float(m_pe.group(1))
            if m_fwd and m_fwd.group(1) != '-': f_pe = float(m_fwd.group(1))
            if sec != "Bilinmiyor" or pd.notna(t_pe) or pd.notna(f_pe):
                return t_pe, f_pe, sec, f"🔄 {sym}: Finviz OK", "success"
        except: pass
    return t_pe, f_pe, sec, f"❌ {sym}: Veri Yok", "error"

# --- 4. ANALİZ VE HESAPLAMA ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    debug_logs = []
    with st.spinner("Fiyatlar indiriliyor..."):
        data = fetch_price_data(tickers + [bench_ticker, dxy_ticker]).ffill().dropna(subset=[bench_ticker])
        p_idx, p_dxy = data[bench_ticker], data[dxy_ticker]
        adj_bench = pd.Series(np.where(p_dxy > 0, p_idx / p_dxy, p_idx), index=data.index)
        bench_rs = calc_weighted_rs(adj_bench)
        idx_ret = p_idx.pct_change()

    with st.spinner("Temel veriler çekiliyor..."):
        f_data = {}
        for s in tickers:
            t_pe, f_pe, sec, msg, tp = fetch_fundamental_data(s, bist_mode)
            f_data[s] = {"trail": t_pe, "fwd": f_pe, "sec": sec}
            debug_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            time.sleep(0.1) # Ban Koruması (Hız Kesici)

    with st.spinner("Sonuçlar hesaplanıyor..."):
        results = []
        all_fwd = [d["fwd"] for d in f_data.values() if pd.notna(d["fwd"])]
        avg_fwd = np.median(all_fwd) if all_fwd else 20.0
        
        for s in tickers:
            if s not in data.columns or data[s].isnull().all(): continue
            inf = f_data.get(s, {"trail": np.nan, "fwd": np.nan, "sec": "Bilinmiyor"})
            p_close = data[s]
            is_ipo = p_close.dropna().count() < lookback
            
            stk_rs = calc_weighted_rs(p_close)
            diff = (stk_rs - bench_rs).tail(lookback)
            rs_ratio = diff[diff > 0].sum() / (abs(diff[diff <= 0].sum()) if diff[diff <= 0].sum() != 0 else 0.0001)
            
            ret, iret = p_close.pct_change().tail(252), idx_ret.tail(252)
            beta = (ret.corr(iret) * (ret.std() / iret.std())) if iret.std() > 0 else 1.0
            ideal = (rs_ratio + (rs_ratio / max(0.1, beta))) / 2.0
            
            t_pe, f_pe = inf["trail"], inf["fwd"]
            if pd.notna(t_pe) and pd.notna(f_pe) and t_pe > 0: growth_chp = f_pe / t_pe
            elif pd.notna(f_pe): growth_chp = f_pe / avg_fwd
            else: growth_chp = np.nan

            hist_chp = p_close.iloc[-1] / p_close.tail(lookback).mean() if len(p_close) >= lookback else -999
            
            results.append({
                "Hisse": s.replace(".IS", ""), "Sektör": inf["sec"], "Saf Oran": rs_ratio, 
                "Beta": beta, "İdealite": ideal, "Temel Ucuzluk": growth_chp, "Teknik Ucuzluk": hist_chp
            })

    # --- 5. TABLO VE SABİT RENK SINIRLARI (OUTLIER KORUMASI) ---
    if results:
        df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
        st.write(f"**Sepet Medyan İleri F/K:** `{round(avg_fwd, 2)}`")
        
        # vmin ve vmax değerleri renk kaymasını engeller (Sabit Sınır)
        st.dataframe(df.style.background_gradient(cmap='RdYlGn_r', subset=['Temel Ucuzluk'], vmin=0.5, vmax=1.5)
                     .background_gradient(cmap='RdYlGn_r', subset=['Teknik Ucuzluk'], vmin=0.7, vmax=1.3).format({
            "Saf Oran": "{:.2f}", "Beta": "{:.2f}", "İdealite": "{:.2f}",
            "Temel Ucuzluk": "{:.2f}", 
            "Teknik Ucuzluk": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok")
        }, na_rep="Veri Yok"), use_container_width=True, height=1000)

        st.markdown("---")
        st.markdown("### 📋 TradingView Kopyalama Merkezi")
        prefix = "BIST:" if bist_mode else "NASDAQ:"
        c1, c2 = st.columns(2)
        
        with c1:
            st.success("**TV Takip Listesi İçin (Tümü)**")
            tv_str = ",".join([f"{prefix}{sym}" for sym in df["Hisse"].tolist()])
            st.code(tv_str, language="text")
            
        with c2:
            st.info("**TV Isı Haritası İçin (İlk 38)**")
            t38 = df["Hisse"].head(38).tolist()
            st.code(" \n".join([f"{i+1}. {sym}" for i, sym in enumerate(t38)]), language="text")

        with st.expander("🛠️ Loglar"):
            for l in debug_logs: st.write(l)
