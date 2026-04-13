//@version=6
indicator("Alpha-Hunt: Çift Ucuzluk Isı Haritası (Sola Yaslı)", overlay=true)

// =========================================================================
// 1. GİRDİLER (İlk 20 Hisse)
// =========================================================================
var string note = "Python uygulamasından çıkan ilk 20 hisseyi sırasıyla girin."

s01 = input.symbol("", "1. Hisse", group="RS Rank Sıralaması", tooltip=note), s02 = input.symbol("", "2. Hisse", group="RS Rank Sıralaması")
s03 = input.symbol("", "3. Hisse", group="RS Rank Sıralaması"), s04 = input.symbol("", "4. Hisse", group="RS Rank Sıralaması")
s05 = input.symbol("", "5. Hisse", group="RS Rank Sıralaması"), s06 = input.symbol("", "6. Hisse", group="RS Rank Sıralaması")
s07 = input.symbol("", "7. Hisse", group="RS Rank Sıralaması"), s08 = input.symbol("", "8. Hisse", group="RS Rank Sıralaması")
s09 = input.symbol("", "9. Hisse", group="RS Rank Sıralaması"), s10 = input.symbol("", "10. Hisse", group="RS Rank Sıralaması")

s11 = input.symbol("", "11. Hisse", group="RS Rank Sıralaması"), s12 = input.symbol("", "12. Hisse", group="RS Rank Sıralaması")
s13 = input.symbol("", "13. Hisse", group="RS Rank Sıralaması"), s14 = input.symbol("", "14. Hisse", group="RS Rank Sıralaması")
s15 = input.symbol("", "15. Hisse", group="RS Rank Sıralaması"), s16 = input.symbol("", "16. Hisse", group="RS Rank Sıralaması")
s17 = input.symbol("", "17. Hisse", group="RS Rank Sıralaması"), s18 = input.symbol("", "18. Hisse", group="RS Rank Sıralaması")
s19 = input.symbol("", "19. Hisse", group="RS Rank Sıralaması"), s20 = input.symbol("", "20. Hisse", group="RS Rank Sıralaması")

// =========================================================================
// 2. VERİ MOTORU VE KONTRAST RENGİ
// =========================================================================
var string dummy_sym = "NASDAQ:AAPL" 

get_metrics(sym) =>
    real_sym = sym == "" ? dummy_sym : sym
    pe_val = request.financial(real_sym, "PRICE_EARNINGS_FORWARD", "FY", ignore_invalid_symbol=true)
    v_pe = na(pe_val) ? 0.0 : pe_val
    v_c = na(pe_val) ? 0 : 1
    s_pe = math.sum(v_pe, 1250), s_c = math.sum(v_c, 1250)
    a_pe = s_c > 0 ? (s_pe / s_c) : na
    fk_r = (sym == "" or na(pe_val) or na(a_pe) or a_pe <= 0) ? na : (pe_val / a_pe)
    y_av = (sym == "") ? 0.0 : (s_c / 252.0)
    
    [c_p, sma] = request.security(real_sym, "D", [close, ta.sma(close, 500)], ignore_invalid_symbol=true)
    t_r = (sym == "" or na(c_p) or na(sma) or sma <= 0) ? na : (c_p / sma)
    [fk_r, y_av, t_r]

get_txt_color(val, mid_val) =>
    na(val) ? color.white : (math.abs(val - mid_val) > 0.25 ? color.white : color.black)

[fk01, y01, t01] = get_metrics(s01), [fk02, y02, t02] = get_metrics(s02), [fk03, y03, t03] = get_metrics(s03)
[fk04, y04, t04] = get_metrics(s04), [fk05, y05, t05] = get_metrics(s05), [fk06, y06, t06] = get_metrics(s06)
[fk07, y07, t07] = get_metrics(s07), [fk08, y08, t08] = get_metrics(s08), [fk09, y09, t09] = get_metrics(s09)
[fk10, y10, t10] = get_metrics(s10), [fk11, y11, t11] = get_metrics(s11), [fk12, y12, t12] = get_metrics(s12)
[fk13, y13, t13] = get_metrics(s13), [fk14, y14, t14] = get_metrics(s14), [fk15, y15, t15] = get_metrics(s15)
[fk16, y16, t16] = get_metrics(s16), [fk17, y17, t17] = get_metrics(s17), [fk18, y18, t18] = get_metrics(s18)
[fk19, y19, t19] = get_metrics(s19), [fk20, y20, t20] = get_metrics(s20)

// =========================================================================
// 3. TABLO (OUTLIER KORUMASI + KONTRAST + 2 ONDALIK + SOLA YASLI)
// =========================================================================
add_arr(s, f, y, t, arr_s, arr_f, arr_y, arr_t) =>
    if s != ""
        array.push(arr_s, s), array.push(arr_f, f), array.push(arr_y, y), array.push(arr_t, t)

if barstate.islast
    s_a = array.new_string(), f_a = array.new_float(), y_a = array.new_float(), t_a = array.new_float()
    add_arr(s01, fk01, y01, t01, s_a, f_a, y_a, t_a), add_arr(s02, fk02, y02, t02, s_a, f_a, y_a, t_a)
    add_arr(s03, fk03, y03, t03, s_a, f_a, y_a, t_a), add_arr(s04, fk04, y04, t04, s_a, f_a, y_a, t_a)
    add_arr(s05, fk05, y05, t05, s_a, f_a, y_a, t_a), add_arr(s06, fk06, y06, t06, s_a, f_a, y_a, t_a)
    add_arr(s07, fk07, y07, t07, s_a, f_a, y_a, t_a), add_arr(s08, fk08, y08, t08, s_a, f_a, y_a, t_a)
    add_arr(s09, fk09, y09, t09, s_a, f_a, y_a, t_a), add_arr(s10, fk10, y10, t10, s_a, f_a, y_a, t_a)
    add_arr(s11, fk11, y11, t11, s_a, f_a, y_a, t_a), add_arr(s12, fk12, y12, t12, s_a, f_a, y_a, t_a)
    add_arr(s13, fk13, y13, t13, s_a, f_a, y_a, t_a), add_arr(s14, fk14, y14, t14, s_a, f_a, y_a, t_a)
    add_arr(s15, fk15, y15, t15, s_a, f_a, y_a, t_a), add_arr(s16, fk16, y16, t16, s_a, f_a, y_a, t_a)
    add_arr(s17, fk17, y17, t17, s_a, f_a, y_a, t_a), add_arr(s18, fk18, y18, t18, s_a, f_a, y_a, t_a)
    add_arr(s19, fk19, y19, t19, s_a, f_a, y_a, t_a), add_arr(s20, fk20, y20, t20, s_a, f_a, y_a, t_a)

    v_c = array.size(s_a)
    if v_c > 0
        tbl = table.new(position.middle_right, 4, v_c + 1, bgcolor = color.new(color.black, 10), border_width = 1, border_color = color.new(color.gray, 50))
        
        // Başlıklar (Sola Yaslı)
        table.cell(tbl, 0, 0, "RS Rank Sırası", text_color=color.white, bgcolor=color.new(color.purple, 20), text_halign=text.align_left)
        table.cell(tbl, 1, 0, "Hisse", text_color=color.white, bgcolor=color.new(color.purple, 20), text_halign=text.align_left)
        table.cell(tbl, 2, 0, "Temel Ucz.", text_color=color.white, bgcolor=color.new(color.purple, 20), text_halign=text.align_left)
        table.cell(tbl, 3, 0, "Teknik Ucz.", text_color=color.white, bgcolor=color.new(color.purple, 20), text_halign=text.align_left)
        
        for i = 0 to v_c - 1
            tick = array.size(str.split(array.get(s_a, i), ":")) > 1 ? array.get(str.split(array.get(s_a, i), ":"), 1) : array.get(s_a, i)
            f_v = array.get(f_a, i), y_v = array.get(y_a, i), t_v = array.get(t_a, i)
            
            // Outlier Clipping
            color f_c = na(f_v) ? color.new(color.gray, 50) : (f_v >= 1.0 ? color.from_gradient(math.min(f_v, 1.5), 1.0, 1.5, color.new(color.yellow, 10), color.new(color.red, 10)) : color.from_gradient(math.max(f_v, 0.5), 0.5, 1.0, color.new(color.green, 10), color.new(color.yellow, 10)))
            color t_c = na(t_v) ? color.new(color.gray, 50) : (t_v >= 1.0 ? color.from_gradient(math.min(t_v, 1.3), 1.0, 1.3, color.new(color.yellow, 10), color.new(color.red, 10)) : color.from_gradient(math.max(t_v, 0.7), 0.7, 1.0, color.new(color.green, 10), color.new(color.yellow, 10)))
            
            // Kontrast Renkler
            f_txt_c = get_txt_color(f_v, 1.0), t_txt_c = get_txt_color(t_v, 1.0)
            y_t = y_v >= 4.9 ? "5Y" : str.tostring(y_v, "#.1") + "Y"
            
            // Veri Hücreleri (Sola Yaslı - text_halign eklendi)
            table.cell(tbl, 0, i + 1, str.tostring(i + 1), text_color=color.white, text_halign=text.align_left)
            table.cell(tbl, 1, i + 1, tick, text_color=color.white, text_halign=text.align_left)
            table.cell(tbl, 2, i + 1, y_v == 0 or na(f_v) ? "Yok" : str.tostring(f_v, "#.00") + "x (" + y_t + ")", text_color=f_txt_c, bgcolor=y_v == 0 ? color.new(color.gray, 50) : f_c, text_halign=text.align_left)
            table.cell(tbl, 3, i + 1, na(t_v) ? "Yok" : str.tostring(t_v, "#.00"), text_color=t_txt_c, bgcolor=t_c, text_halign=text.align_left)
