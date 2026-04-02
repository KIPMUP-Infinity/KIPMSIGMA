# ── Trade plan lines + labels style TradingView ────────
                    if ai_data:
                        try:
                            el  = ai_data.get('entry_low')
                            eh  = ai_data.get('entry_high')
                            sl  = ai_data.get('stop_loss')
                            tp1 = ai_data.get('tp1')
                            tp2 = ai_data.get('tp2')
                            tp3 = ai_data.get('tp3')

                            # Fungsi ajaib untuk menggambar garis full & label nempel persis di Sumbu Y Kanan
                            def _draw_tv_level(y_val, label_text, line_color, bg_color, text_color, dash_style='dash'):
                                if not y_val: return
                                y_val = float(y_val)

                                # 1. Garis membentang full (xref='paper' menjamin garis menyentuh ujung)
                                fig.add_shape(
                                    type="line", xref="paper", yref="y",
                                    x0=0, x1=1, y0=y_val, y1=y_val,
                                    line=dict(color=line_color, width=1.5, dash=dash_style),
                                    layer="below"
                                )

                                # 2. Label Tag nempel di Sumbu Y Kanan (x=1.0)
                                fig.add_annotation(
                                    xref='paper', yref='y',
                                    x=1.0, y=y_val,
                                    text=f"<b>{label_text} {y_val:,.0f}</b>",
                                    showarrow=False,
                                    xanchor='left', yanchor='middle',
                                    font=dict(color=text_color, size=10, family='IBM Plex Mono, monospace'),
                                    bgcolor=bg_color,
                                    bordercolor=line_color,
                                    borderwidth=1,
                                    borderpad=4
                                )

                            # Gambar Area BUY (Kotak hijau transparan + Batas Atas Bawah)
                            if el and eh:
                                fig.add_trace(go.Scatter(
                                    x=x_str + x_str[::-1],
                                    y=[float(eh)]*n_bars + [float(el)]*n_bars,
                                    fill='toself', mode='lines',
                                    fillcolor='rgba(8,153,129,0.15)', # Hijau transparan
                                    line=dict(width=0), showlegend=False,
                                ), row=1, col=1)

                                # Garis Buy Area (Gaya TradingView: tulisan hijau background gelap)
                                _draw_tv_level(eh, "BUY AREA", '#089981', tv_bg_color, '#089981', 'dash')
                                _draw_tv_level(el, "BUY AREA", '#089981', tv_bg_color, '#089981', 'dash')

                            # Gambar SL (Warna Merah Solid, tulisan putih background merah)
                            if sl:
                                _draw_tv_level(sl, "SL", '#f23645', '#f23645', '#ffffff', 'solid')

                            # Gambar TP (Gaya TradingView: Kuning Solid, garis putus-putus)
                            if tp1: _draw_tv_level(tp1, "TP1", '#F5C242', '#F5C242', '#000000', 'dot')
                            if tp2: _draw_tv_level(tp2, "TP2", '#F5C242', '#F5C242', '#000000', 'dot')
                            if tp3: _draw_tv_level(tp3, "TP3", '#F5C242', '#F5C242', '#000000', 'dot')

                        except Exception as e:
                            st.warning(f"AI gagal menghasilkan koordinat harga yang pas: {e}")
