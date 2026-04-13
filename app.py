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

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Hisse Sıralama Motoru", layout="wide")

# --- GÜVENLİK / ŞİFRE EKRANI ---
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

# --- BAŞLIK ---
st.title("Hisse RsRank bazlı İdealite ve Ortalama F/K Isı Haritası [KazimKrbck]")
st.markdown("Likidite ayarlı teknik metrikler, normalize edilmiş F/K haritası ve **Gemini Görüntü Okuma** sistemi.")

# --- GİRDİLER VE GEMINI ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul (BIST) Modu", value=False)

if bist_mode:
    default_tickers = "THYAO, TUPRS, KCHOL, AKBNK, ISCTR, EREGL, FROTO, SISE, BIMAS, ASELS"
    default_bench = "XU100.IS"
    default_dxy = "TRY=X" 
else:
    default_tickers = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, INTC, AMD, NFLX, AVGO"
    default_bench = "^GSPC"
    default_dxy = "DX-Y.NYB"

# Gemini Görüntü Okuma
st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Resimden Hisse Çıkarma")
if "GEMINI_API_KEY" in st.secrets:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 Gemini API Anahtarı yüklendi!")
else:
    gemini_api_key = st.sidebar.text_input("Gemini API Anahtarı", type="password")

uploaded_file = st.sidebar.file_uploader("Resim Yükle", type=["png", "jpg", "jpeg"])

if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = default_tickers

if uploaded_file and gemini_api_key:
    if st.sidebar.button("✨ Resmi Oku"):
        with st.spinner("Gemini inceliyor..."):
            try:
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                img = Image.open(uploaded_file)
                prompt = "Resimdeki hisse tickerlarını bul. SADECE büyük harflerle, virgülle ayrılmış liste ver. Örn: AAPL, MSFT"
                response = model.generate_content([prompt, img])
                st.session_state.current_tickers = response.text.strip()
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Hata: {str(e)[:40]}")

st.sidebar.markdown("---")
tickers_input = st.sidebar.text_area("Hisse Sembolleri", st.session_state.current_tickers, height=150)
bench_ticker = st.sidebar.text_input("Endeks", default_bench)
dxy_ticker = st.sidebar.text_input("Likidite (DXY)", default_dxy)
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers][:100]

# --- HESAPLAMA VE VERİ ÇEKME (HAFIZA GELİŞTİRMELİ) ---
def calc_roc(series, periods):
    return series.pct_change(periods=periods) * 100

def calc_weighted_rs(series):
    return (0.4 * calc_roc(series, 63) + 0.2 * calc_roc(series, 126) + 
            0.2 * calc_roc(series, 189) + 0.2 * calc_roc(series, 252))

@st.cache_data(ttl=3600, max_entries=2, show_spinner=False)
def fetch_price_data(all_ticks):
    return yf.download(all_ticks, period="4y", interval="1d", progress=False)["Close"]

@st.cache_data(ttl=86400, max_entries=150, show_spinner=False)
def fetch_fundamental_data(sym, is_bist):
    pe_val = np.nan
    sector = "Bilinmiyor"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        t_obj = yf.Ticker(sym)
        info = t_obj.info
        sector = info.get('sector', info.get('industry', 'Bilinmiyor'))
        if is_bist:
            pe_val = info.get('trailingPE', info.get('forwardPE', np.nan))
        else:
            pe_val = info.get('forwardPE', info.get('trailingPE', np.nan))
        if pd.notna(pe_val) and pe_val > 0 and sector != "Bilinmiyor":
            return pe_val, sector, f"✅ {sym}: Yahoo OK", "success"
    except: pass

    if not is_bist:
        try:
            res = requests.get(f"https://finviz.com/quote.ashx?t={sym}", headers=headers, timeout=5)
            if sector == "Bilinmiyor":
                m = re.search(r'f=sec_[^>]+>([^<]+)</a>', res.text)
                if m: sector = m.group(1)
            m_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
            m_pe = re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
            if m_fwd and m_fwd.group(1) != '-': pe_val = float(m_fwd.group(1))
            elif m_pe and m_pe.group(1) != '-': pe_val = float(m_pe.group(1))
            if sector != "Bilinmiyor" or pd.notna(pe_val):
                return pe_val, sector, f"🔄 {sym}: Finviz OK", "success"
        except: pass
    return pe_val, sector, f"❌ {sym}: Veri Yok", "error"

# --- ANALİZ MOTORU ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    debug_logs = []
    with st.spinner("Fiyatlar indiriliyor..."):
        all_ticks = tickers + [bench_ticker, dxy_ticker]
        data = fetch_price_data(all_ticks).ffill().dropna(subset=[bench_ticker])
        p_idx, p_dxy = data[bench_ticker], data[dxy_ticker]
        adj_bench = pd.Series(np.where(p_dxy > 0, p_idx / p_dxy, p_idx), index=data.index)
        bench_rs = calc_weighted_rs(adj_bench)
        idx_ret = p_idx.pct_change()

    with st.spinner("Temel veriler çekiliyor..."):
        f_data = {}
        for s in tickers:
            pe, sec, msg, tp = fetch_fundamental_data(s, bist_mode)
            f_data[s] = {"pe": pe, "sector": sec}
            debug_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            time.sleep(0.1) # Sunucu koruması

    with st.spinner("Sonuçlar hesaplanıyor..."):
        results = []
        all_pes = [d["pe"] for d in f_data.values() if pd.notna(d["pe"])]
        avg_pe = np.median(all_pes) if all_pes else 10.0
        
        for s in tickers:
            if s not in data.columns or data[s].isnull().all(): continue
            inf = f_data.get(s, {"pe": np.nan, "sector": "Bilinmiyor"})
            p_close = data[s]
            is_ipo = p_close.dropna().count() < lookback
            
            stk_rs = calc_weighted_rs(p_close)
            diff = (stk_rs - bench_rs).tail(lookback)
            rs_ratio = diff[diff > 0].sum() / (abs(diff[diff <= 0].sum()) if diff[diff <= 0].sum() != 0 else 0.0001)
            
            ret, iret = p_close.pct_change().tail(252), idx_ret.tail(252)
            beta = (ret.corr(iret) * (ret.std() / iret.std())) if iret.std() > 0 else 1.0
            ideal = (rs_ratio + (rs_ratio / max(0.1, beta))) / 2.0
            
            results.append({
                "Hisse": s.replace(".IS", ""), "Sektör": inf["sector"],
                "Saf Oran": rs_ratio, "Beta": beta, "İdealite": ideal,
                "F/K Değeri": inf["pe"], "Ucuzluk Skoru (x)": (inf["pe"]/avg_pe if pd.notna(inf["pe"]) else np.nan) if not is_ipo else -999
            })

    if results:
        df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
        st.write(f"**Sepet Medyan F/K:** `{round(avg_pe, 2)}`")
        st.dataframe(df.style.background_gradient(cmap='RdYlGn_r', subset=['Ucuzluk Skoru (x)'], vmin=0.5, vmax=2.0).format({
            "Saf Oran": "{:.2f}", "Beta": "{:.2f}", "İdealite": "{:.2f}", "F/K Değeri": "{:.2f}",
            "Ucuzluk Skoru (x)": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok")
        }, na_rep="Veri Yok"), use_container_width=True, height=800)
        with st.expander("Loglar"):
            for l in debug_logs: st.write(l)
