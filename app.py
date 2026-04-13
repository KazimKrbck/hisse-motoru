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
st.title("Hisse RsRank bazlı İdealite ve Ortalama F/K bazlı Ucuzluk Isı Haritası [KazimKrbck]")
st.markdown("Likidite ayarlı teknik metrikler, normalize edilmiş F/K haritası ve **Gemini Görüntü Okuma** sistemi.")

# --- PARAMETRELER VE KONTROL PANELİ ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul (BIST) Modu", value=False)

if bist_mode:
    default_tickers = "THYAO, TUPRS, KCHOL, AKBNK, ISCTR, EREGL, FROTO, SISE, BIMAS, ASELS"
    default_bench = "XU100.IS"
    default_dxy = "TRY=X" 
else:
    default_tickers = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, INTC, AMD, NFLX"
    default_bench = "^GSPC"
    default_dxy = "DX-Y.NYB"

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Sektör Filtreleri")
exclude_finance = st.sidebar.checkbox("Banka, Finans, Kripto ve Kumar Hariç Tut", value=True)

# --- GEMINI GÖRÜNTÜ OKUMA ---
st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Resimden Hisse Çıkarma")
if "GEMINI_API_KEY" in st.secrets:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 Gemini API Anahtarı kasadan yüklendi.")
else:
    gemini_api_key = st.sidebar.text_input("Gemini API Anahtarı", type="password")

uploaded_file = st.sidebar.file_uploader("Hisse Listesi Resmi Yükle", type=["png", "jpg", "jpeg"])

if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = default_tickers

if uploaded_file is not None and gemini_api_key:
    if st.sidebar.button("✨ Resmi Oku ve Listeyi Doldur"):
        with st.spinner("Gemini inceliyor..."):
            try:
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                img = Image.open(uploaded_file)
                prompt = "Resimdeki tickerları bul. SADECE büyük harflerle, virgülle ayrılmış liste ver. Örn: AAPL, MSFT"
                response = model.generate_content([prompt, img])
                st.session_state.current_tickers = response.text.strip()
                st.sidebar.success("Hisseler çekildi!")
            except Exception as e:
                st.sidebar.error(f"Hata: {str(e)[:40]}")

st.sidebar.markdown("---")
tickers_input = st.sidebar.text_area("Hisse Sembolleri", st.session_state.current_tickers, height=120)
bench_ticker = st.sidebar.text_input("Piyasa Endeksi", default_bench)
dxy_ticker = st.sidebar.text_input("Kur/Likidite (DXY)", default_dxy)
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers][:100]

# --- FONKSİYONLAR VE CACHE SİSTEMİ ---
def calc_roc(series, periods):
    return series.pct_change(periods=periods) * 100

def calc_weighted_rs(series):
    return (0.4 * calc_roc(series, 63) + 0.2 * calc_roc(series, 126) + 
            0.2 * calc_roc(series, 189) + 0.2 * calc_roc(series, 252))

@st.cache_data(ttl=3600, max_entries=2, show_spinner=False)
def fetch_price_data(all_ticks):
    return yf.download(all_ticks, period="4y", interval="1d", progress=False)["Close"]

# RAM Koruması ve Finviz Yedek Motorlu Kusursuz Veri Çekici
@st.cache_data(ttl=86400, max_entries=150, show_spinner=False)
def fetch_fundamental_data(sym, is_bist):
    pe_val = np.nan
    sector = "Bilinmiyor"
    
    # 1. YFINANCE (Yahoo)
    try:
        t_obj = yf.Ticker(sym)
        info = t_obj.info
        sector = info.get('sector', info.get('industry', 'Bilinmiyor'))
        pe_val = info.get('trailingPE' if is_bist else 'forwardPE', info.get('forwardPE' if is_bist else 'trailingPE', np.nan))
        
        if pd.notna(pe_val) and (pe_val <= 0 or pe_val > 500): 
            pe_val = np.nan
            
        if pd.notna(pe_val) and sector != "Bilinmiyor":
            return pe_val, sector, f"✅ {sym}: Veri Yahoo'dan çekildi.", "success"
    except Exception:
        pass 

    # 2. FINVIZ (Yedek Motor - Gerçek İnsan Kimliği İle)
    if is_bist:
        return pe_val, sector, f"⚠️ {sym}: BIST hissesi için Yahoo eksik veri verdi.", "warning"
        
    try:
        # Bizi banlamaması için gerekli tam kimlik
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        url = f"https://finviz.com/quote.ashx?t={sym}"
        res = requests.get(url, headers=headers, timeout=5)
        
        if sector == "Bilinmiyor":
            match_sec = re.search(r'f=sec_[^>]+>([^<]+)</a>', res.text)
            if match_sec:
                sector = match_sec.group(1)
        
        if np.isnan(pe_val):
            match_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
            match_pe = re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
            
            temp_pe = np.nan
            if match_fwd and match_fwd.group(1) != '-':
                temp_pe = float(match_fwd.group(1))
            elif match_pe and match_pe.group(1) != '-':
                temp_pe = float(match_pe.group(1))
                
            if pd.notna(temp_pe) and 0 < temp_pe <= 500:
                pe_val = temp_pe
        
        if sector != "Bilinmiyor" or not np.isnan(pe_val):
            return pe_val, sector, f"🔄 {sym}: Eksikler FINVIZ üzerinden kurtarıldı.", "success"
        else:
            return pe_val, sector, f"❌ {sym}: Veri bulunamadı.", "error"
            
    except Exception:
        return pe_val, sector, f"❌ {sym}: Finviz bağlantı hatası.", "error"


# --- ANALİZ MOTORU ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    debug_logs = []
    
    with st.spinner("Veriler indiriliyor..."):
        all_to_fetch = tickers + [bench_ticker, dxy_ticker]
        data = fetch_price_data(all_to_fetch).ffill().dropna(subset=[bench_ticker])
        p_index, p_curr = data[bench_ticker], data[dxy_ticker]
        adj_bench = pd.Series(np.where(p_curr > 0, p_index / p_curr, p_index), index=data.index)
        bench_rs = calc_weighted_rs(adj_bench)
        idx_ret = p_index.pct_change()

        fundamental_data = {}
        for sym in tickers:
            pe, sec, msg, tp = fetch_fundamental_data(sym, bist_mode)
            fundamental_data[sym] = {"pe": pe, "sector": sec}
            debug_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            time.sleep(0.1)  # API'lerin sunucuyu dondurmasını engellemek için saliselik nefes

    with st.spinner("İdealite ve Ucuzluk Skorları Hesaplanıyor..."):
        results = []
        # Hem Türkçe hem İngilizce zırhlı kara liste
        blacklist = ["bank", "financial", "credit", "crypto", "gambling", "casino", "insurance", 
                     "banka", "finans", "sigorta", "yatırım", "menkul", "faktoring"]
        
        # Filtrelenmiş sepet medyanı
        valid_pes = [d["pe"] for d in fundamental_data.values() if pd.notna(d["pe"]) and not (exclude_finance and any(b in d["sector"].lower() for b in blacklist))]
        avg_basket_pe = np.median(valid_pes) if valid_pes else 10.0
        
        for sym in tickers:
            if sym not in data.columns or data[sym].isnull().all(): continue
            f_info = fundamental_data.get(sym, {"pe": np.nan, "sector": "Bilinmiyor"})
            
            if exclude_finance and any(b in f_info["sector"].lower() for b in blacklist):
                debug_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ {sym} filtrelendi ({f_info['sector']}).")
                continue

            p_close = data[sym]
            is_ipo = p_close.dropna().count() < lookback
            stock_rs = calc_weighted_rs(p_close)
            diff = (stock_rs - bench_rs).tail(lookback)
            rs_ratio = diff[diff > 0].sum() / (abs(diff[diff <= 0].sum()) if diff[diff <= 0].sum() != 0 else 0.0001)
            
            stock_ret = p_close.pct_change().tail(252)
            curr_idx_ret = idx_ret.tail(252)
            beta = (stock_ret.corr(curr_idx_ret) * (stock_ret.std() / curr_idx_ret.std())) if curr_idx_ret.std() > 0 else 1.0
            ideal_score = (rs_ratio + (rs_ratio / max(0.1, beta))) / 2.0
            
            results.append({
                "Hisse": sym.replace(".IS", "") if bist_mode else sym,
                "Sektör": f_info["sector"],
                "Saf Oran": rs_ratio,
                "Beta": beta,
                "İdealite": ideal_score,
                "F/K Değeri": f_info["pe"],
                "Ort. İleri F/K": avg_basket_pe,
                "Ucuzluk Skoru (x)": -999 if is_ipo else (f_info["pe"] / avg_basket_pe if pd.notna(f_info["pe"]) else np.nan)
            })

    if results:
        df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
        st.write(f"**Referans Medyan F/K (Sepet):** `{round(avg_basket_pe, 2)}`")
        
        # Isı Haritası ve 2 Ondalık Format
        styled_df = df.style.background_gradient(cmap='RdYlGn_r', subset=['Ucuzluk Skoru (x)'], vmin=0.5, vmax=2.0).format({
            "Saf Oran": "{:.2f}", "Beta": "{:.2f}", "İdealite": "{:.2f}", 
            "F/K Değeri": "{:.2f}", "Ort. İleri F/K": "{:.2f}",
            "Ucuzluk Skoru (x)": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok")
        }, na_rep="Veri Yok")
        
        st.dataframe(styled_df, use_container_width=True, height=800)
        with st.expander("🛠️ Saat Damgalı Debug Konsolu"):
            for log in debug_logs: st.write(log)
    else:
        st.error("Görüntülenecek veri bulunamadı. Filtreleri veya sembolleri kontrol edin.")
