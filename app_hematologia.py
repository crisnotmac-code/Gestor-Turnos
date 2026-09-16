import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re
import os

st.set_page_config(page_title="Gestor Hematología 2026", layout="wide")
st.markdown("""<style>@media print { header, [data-testid="stSidebar"], [data-testid="stToolbar"] { display: none !important; } .main { max-width: 100% !important; padding: 0 !important; } @page { size: landscape; margin: 1cm; } }</style>""", unsafe_allow_html=True)

# Lista Maestra
plantilla = ["Dra. Busnego", "Dr. Moreno", "Dra. Sánchez", "Dra. Hernández", "Dra. Martín", "Dra. Alberich", "Dr. Breña", "Dra. Notario", "Dr. Figueroa", "Dra. Peris", "Dra. Montalvo", "Dr. Ríos de Paz", "Dra. Herrero", "Dra. Lorenzo", "Dra. Rodríguez Esteban", "Dra. Hernanz", "Dra. Marrero", "Dr. González", "Dr. García Roulston", "Dr. Ríos Rull", "Dr. De Ramos"]

# Médicos que NUNCA deben usarse para rellenar huecos de Planta ni HD
blindados = ["Dra. Marrero", "Dra. Hernanz", "Dra. Lorenzo", "Dr. Ríos Rull", "Dr. Ríos de Paz", "Dr. González"]

meses_es_str = {"ENERO":1, "FEBRERO":2, "MARZO":3, "ABRIL":4, "MAYO":5, "JUNIO":6, "JULIO":7, "AGOSTO":8, "SEPTIEMBRE":9, "OCTUBRE":10, "NOVIEMBRE":11, "DICIEMBRE":12}
meses_es = {1:"ENERO", 2:"FEBRERO", 3:"MARZO", 4:"ABRIL", 5:"MAYO", 6:"JUNIO", 7:"JULIO", 8:"AGOSTO", 9:"SEPTIEMBRE", 10:"OCTUBRE", 11:"NOVIEMBRE", 12:"DICIEMBRE"}

def limpiar_texto(s):
    if pd.isna(s): return ""
    s = str(s).upper()
    for k, v in {"Á":"A", "É":"E", "Í":"I", "Ó":"O", "Ú":"U"}.items(): s = s.replace(k, v)
    return s

def match_medico(nombre_texto, med):
    nt = limpiar_texto(nombre_texto)
    mt = limpiar_texto(med).replace("DR. ", "").replace("DRA. ", "").replace("DR ", "").replace("DRA ", "").strip()
    
    if "CLIMENT" in nt and "GONZALEZ" in mt: return False

    if "RIOS DE PAZ" in mt: return ("PAZ" in nt) or (("RIOS" in nt or "PABLO" in nt) and "RULL" not in nt)
    if "RIOS RULL" in mt: return "RULL" in nt
    if "GARCIA ROULSTON" in mt: return "ROULSTON" in nt or "KEVIN" in nt or "GARCIA" in mt
    if "RODRIGUEZ ESTEBAN" in mt: return "RODRIGUEZ" in nt
    if "ALBERICH" in mt: return "ALBERICH" in nt or "LABERICH" in nt
    if "DE RAMOS" in mt: return "RAMOS" in nt
    
    words = [w for w in mt.split() if len(w) > 3]
    for w in words:
        if w in nt: return True
    return False

def parse_vacaciones(texto, mes_por_defecto):
    texto = limpiar_texto(str(texto)).replace(' Y ', ',')
    bloques = [b.strip() for b in texto.split(',') if b.strip()]
    parsed_ranges = []
    current_month = None
    
    for b in reversed(bloques):
        for m_str, m_num in meses_es_str.items():
            if m_str in b:
                if current_month is None: current_month = m_num
                break
        if current_month is not None: break
        
    if current_month is None:
        current_month = mes_por_defecto

    for bloque in reversed(bloques):
        if "AL" in bloque or "-" in bloque:
            sep = "AL" if "AL" in bloque else "-"
            parts = bloque.split(sep)
            if len(parts) >= 2:
                p1, p2 = parts[0], parts[-1]
                m2 = current_month
                for m_str, m_num in meses_es_str.items():
                    if m_str in p2: m2 = m_num; break
                if m2: current_month = m2
                
                m1 = m2
                for m_str, m_num in meses_es_str.items():
                    if m_str in p1: m1 = m_num; break
                
                nums1 = [int(s) for s in re.findall(r'\d+', p1)]
                nums2 = [int(s) for s in re.findall(r'\d+', p2)]
                
                if nums1 and nums2:
                    ini, fin = nums1[-1], nums2[0]
                    if m1 == m2 and m2 is not None and ini > fin:
                        m1 = m2 - 1 if m2 > 1 else 12
                    if m1 is not None and m2 is not None:
                        parsed_ranges.append((ini, m1, fin, m2))
        else:
            m = current_month
            for m_str, m_num in meses_es_str.items():
                if m_str in bloque: m = m_num; break
            if m: current_month = m
            
            nums = [int(s) for s in re.findall(r'\d+', bloque)]
            for n in nums:
                if m is not None:
                    parsed_ranges.append((n, m, n, m))
    return parsed_ranges

def esta_en_rango(dia, mes, rangos):
    val = mes * 100 + dia
    for (ini, m_ini, fin, m_fin) in rangos:
        v_ini = m_ini * 100 + ini
        v_fin = m_fin * 100 + fin
        if v_ini > v_fin:
            if val >= v_ini or val <= v_fin: return True
        else:
            if v_ini <= val <= v_fin: return True
    return False

def verificar_dia_en_texto(texto, fecha_dt):
    rangos = parse_vacaciones(texto, fecha_dt.month)
    return esta_en_rango(fecha_dt.day, fecha_dt.month, rangos)

def is_matching_date(val, target_date):
    if isinstance(val, (pd.Timestamp, datetime)):
        try: return val.date() == target_date.date()
        except: return val == target_date.date()
    try:
        val_str = str(val).strip()
        if val_str and val_str.replace('.','',1).isdigit() and int(float(val_str)) == target_date.day:
            return True
    except: pass
    return False

def cargar_todo(archivo):
    try:
        if isinstance(archivo, str):
            if not os.path.exists(archivo):
                return None, None, None, None
            f = archivo
        elif hasattr(archivo, 'getvalue'):
            f = io.BytesIO(archivo.getvalue())
        else:
            f = archivo
            
        xl = pd.ExcelFile(f)
        def get_sheet(keywords, header_mode=0):
            for sheet in xl.sheet_names:
                sheet_up = str(sheet).strip().upper()
                for kw in keywords:
                    if kw in sheet_up: return xl.parse(sheet, header=header_mode)
            return None

        df_g = get_sheet(["GUARDIAS", "GUARDIA"], header_mode=None)
        df_v = get_sheet(["VACACIONES", "VACACION", "LIBRE"], header_mode=0)
        df_g_r = get_sheet(["GUARDIAS_R", "RESIDENTES_G", "RESIS"], header_mode=None)
        df_rot_r = get_sheet(["ROTACIONES_R", "ROTACION"], header_mode=0)
        
        def clean_df(d):
            if d is not None and not d.empty: return d.loc[:, ~d.columns.duplicated()]
            return d
            
        return clean_df(df_g), clean_df(df_v), clean_df(df_g_r), clean_df(df_rot_r)
    except Exception as e:
        st.error(f"🚨 Error técnico leyendo el Excel: {str(e)}")
        return None, None, None, None

def extraer_diario(df, fecha_dt, is_vacaciones=False, is_resi=False):
    if df is None or df.empty: return [], False
    enc = []
    es_festivo = False
    mes_str = meses_es[fecha_dt.month]
    
    if is_resi:
        for _, r in df.iterrows():
            try:
                val = r.iloc[0]
                if is_matching_date(val, fecha_dt):
                    for x in r.values[1:]:
                        if pd.notna(x) and isinstance(x, str):
                            txt = x.strip()
                            if txt.upper() not in ["FESTIVO", "VACACION", "LIBRE", "SÁBADO", "DOMINGO", "LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES"] and not txt.isdigit():
                                enc.append(txt.title())
            except: continue
        return list(set(enc)), False

    if is_vacaciones:
        c_ini = next((c for c in df.columns if "ini" in str(c).lower()), None)
        c_fin = next((c for c in df.columns if "fin" in str(c).lower()), None)
        if c_ini is not None and c_fin is not None:
            for _, r in df.iterrows():
                try:
                    d_ini = pd.to_datetime(r[c_ini], dayfirst=True)
                    d_fin = pd.to_datetime(r[c_fin], dayfirst=True)
                    if d_ini.date() <= fecha_dt.date() <= d_fin.date():
                        txt_full = " ".join([str(x).upper() for x in r.values if pd.notna(x)])
                        for med in plantilla:
                            if match_medico(txt_full, med): enc.append(med)
                except Exception: continue
        else:
            col_dias_idx = -1
            for i, col in enumerate(df.columns):
                if "DIA" in str(col).upper() or "LIBRE" in str(col).upper(): col_dias_idx = i; break
            if col_dias_idx == -1: col_dias_idx = df.shape[1] - 1
            for _, r in df.iterrows():
                nombre_celda = str(r.iloc[0]) + " " + str(r.iloc[1]) if df.shape[1] > 1 else str(r.iloc[0])
                texto_dias = str(r.iloc[col_dias_idx])
                if verificar_dia_en_texto(texto_dias, fecha_dt):
                    for med in plantilla:
                        if match_medico(nombre_celda, med): enc.append(med)
        return list(set(enc)), False
    else:
        for _, r in df.iterrows():
            try:
                val = r.iloc[0]
                if is_matching_date(val, fecha_dt):
                    txt_full = " ".join([str(x).upper() for x in r.values if pd.notna(x)])
                    meses_presentes = [m for m in meses_es.values() if m in txt_full]
                    if meses_presentes and mes_str not in meses_presentes: continue 
                    if "FESTIVO" in txt_full or "VACACION" in txt_full: es_festivo = True
                    for med in plantilla:
                        if match_medico(txt_full, med): enc.append(med)
            except: continue
        return list(set(enc)), es_festivo

def calcular_cuadrante(fecha, df_g, df_v, bajas, df_g_r=None, df_rot_r=None):
    f_dt = pd.to_datetime(fecha)
    dia_en = f_dt.strftime('%A')
    
    guardia_hoy, fest_g = extraer_diario(df_g, f_dt, is_vacaciones=False)
    guardia_hoy_resis, fest_gr = extraer_diario(df_g_r, f_dt, is_vacaciones=False, is_resi=True)
    ausentes, fest_v = extraer_diario(df_v, f_dt, is_vacaciones=True)
    
    salientes, _ = extraer_diario(df_g, (f_dt - timedelta(days=1)), is_vacaciones=False)
    if dia_en == "Monday": 
        sal_mon, _ = extraer_diario(df_g, (f_dt - timedelta(days=2)), is_vacaciones=False)
        salientes.extend(sal_mon)
    salientes = list(set(salientes))

    sal_resis, _ = extraer_diario(df_g_r, (f_dt - timedelta(days=1)), is_vacaciones=False, is_resi=True)
    if dia_en == "Monday": 
        salr_mon, _ = extraer_diario(df_g_r, (f_dt - timedelta(days=2)), is_vacaciones=False, is_resi=True)
        sal_resis.extend(salr_mon)
    sal_resis = list(set(sal_resis))
    
    asignados = list(set(ausentes + bajas + salientes))

    # Clasificación de Residentes por áreas
    resi_planta, resi_hd, resi_diag, resi_banco, resi_cons, resi_otros = [], [], [], [], [], []
    
    if df_rot_r is not None and not df_rot_r.empty:
        try:
            c_res = next((c for c in df_rot_r.columns if 'res' in str(c).lower() or 'nom' in str(c).lower()), df_rot_r.columns[0])
            c_rot = next((c for c in df_rot_r.columns if 'rot' in str(c).lower() or 'pues' in str(c).lower()), df_rot_r.columns[1])
            c_i = next((c for c in df_rot_r.columns if 'ini' in str(c).lower() or 'desd' in str(c).lower()), df_rot_r.columns[2])
            c_f = next((c for c in df_rot_r.columns if 'fin' in str(c).lower() or 'hast' in str(c).lower()), df_rot_r.columns[3])
            
            for _, r in df_rot_r.iterrows():
                try:
                    if pd.notna(r[c_i]) and pd.notna(r[c_f]):
                        d_ini = pd.to_datetime(r[c_i], dayfirst=True)
                        d_fin = pd.to_datetime(r[c_f], dayfirst=True)
                        if d_ini.date() <= f_dt.date() <= d_fin.date():
                            resi = str(r[c_res]).strip().title()
                            if resi not in [s.title() for s in sal_resis] and resi.lower() not in ["nan", "none", ""]: 
                                rot_texto = str(r[c_rot]).strip()
                                rot_up = rot_texto.upper()
                                # Lógica de clasificación
                                if any(k in rot_up for k in ["PLANTA", "HOSPITALIZACION", "HOSPITALIZACIÓN"]): 
                                    resi_planta.append(resi)
                                elif any(k in rot_up for k in ["DIA", "DÍA", "HD", "AMBULATORIO"]): 
                                    resi_hd.append(resi)
                                elif any(k in rot_up for k in ["DIAG", "LAB", "MORFOLOG", "CITOMETR", "BIOLOGIA"]): 
                                    resi_diag.append(resi)
                                elif any(k in rot_up for k in ["BANCO", "TRANSFUS", "AFERESIS", "AFÉRESIS"]): 
                                    resi_banco.append(resi)
                                elif any(k in rot_up for k in ["CONS", "XHEM"]): 
                                    resi_cons.append(resi)
                                else: 
                                    resi_otros.append(f"{resi} ({rot_texto})")
                except: continue
        except: pass

    res = {
        "Fecha": f_dt.strftime('%d/%m/%Y'), "Día": f_dt.strftime('%A'), 
        "Guardia": " / ".join(guardia_hoy) if guardia_hoy else "",
        "Guardia_Resis": " / ".join(guardia_hoy_resis) if guardia_hoy_resis else "",
        "Saliente": " / ".join(salientes) if salientes else "", 
        "Saliente_Resis": " / ".join(sal_resis) if sal_resis else "", 
        "Resi_Planta": resi_planta, "Resi_HD": resi_hd, "Resi_Diag": resi_diag, "Resi_Banco": resi_banco, "Resi_Cons": resi_cons, "Resi_Otros": resi_otros,
        "Ausentes": ausentes, "Agendas": {}
    }

    es_festivo = fest_g or fest_gr or fest_v or (f_dt.weekday() >= 5)
    if es_festivo:
        res["Es_Festivo"] = True
        res["Saliente"] = ""; res["Saliente_Resis"] = ""
        res["Ausentes"] = []
        res["Resi_Planta"] = []; res["Resi_HD"] = []; res["Resi_Diag"] = []; res["Resi_Banco"] = []; res["Resi_Cons"] = []; res["Resi_Otros"] = []
        for cod in ["XHEM4A", "XHEM4B", "XHEM4D", "XHEM4E", "XHEM4G", "XHEM5", "XHEM1A", "XHEM10 (Tromb.)", "XHEM11"]: res["Agendas"][cod] = ""
        res["Coag"] = []; res["Sur"] = ""; res["TAO"] = ""; res["Diag"] = ["", ""]
        res["Hem"] = ""; res["Banco"] = ["", ""]; res["IC_Ext"] = ""; res["IC_Virt"] = ""
        res["Planta"] = ["🛑 FESTIVO", "🛑 FESTIVO", "🛑 FESTIVO"]
        res["H_Dia"] = ["🛑 FESTIVO", "🛑 FESTIVO", "🛑 FESTIVO"]
        res["Ped"] = ""; res["IC_Hosp"] = ""; res["Busca"] = ""; res["Gestion"] = []
        return res

    def asignar(m):
        if m and m not in asignados:
            asignados.append(m); return True
        return False

    # 1. COAGULACIÓN Y SUR
    disp_rios, disp_mont = "Dr. Ríos de Paz" not in asignados, "Dra. Montalvo" not in asignados
    res["Coag"] = []
    if disp_rios: res["Coag"].append("Dr. Ríos de Paz"); asignados.append("Dr. Ríos de Paz")
    if disp_mont: res["Coag"].append("Dra. Montalvo"); asignados.append("Dra. Montalvo")

    sur_titu = {"Monday": "Dr. García Roulston", "Tuesday": "Dra. Montalvo", "Wednesday": "Dra. Herrero", "Thursday": "Dr. De Ramos", "Friday": "Dra. Rodríguez Esteban"}.get(dia_en)
    if sur_titu == "Dra. Montalvo" and disp_mont: res["Sur"] = "✅ Dra. Montalvo"
    elif asignar(sur_titu): res["Sur"] = f"✅ {sur_titu}"
    else: res["Sur"] = "❌ [VACÍO]"

    # 2. CONSULTAS XHEM
    r_xhem = {
        "Monday": [("XHEM4A", "Dra. Marrero"), ("XHEM4B", "Dra. Hernanz"), ("XHEM4G", "Dra. Lorenzo"), ("XHEM11", "Dr. Ríos de Paz")], 
        "Tuesday": [("XHEM4A", "Dra. Marrero"), ("XHEM4E", "Dr. De Ramos"), ("XHEM11", "Dr. Ríos de Paz"), ("XHEM1A", "Dra. Herrero")], 
        "Wednesday": [("XHEM4B", "Dra. Hernanz"), ("XHEM4D", "Dra. Martín"), ("XHEM4G", "Dra. Lorenzo"), ("XHEM10 (Tromb.)", "Dra. Montalvo")], 
        "Thursday": [("XHEM4B", "Dra. Hernanz"), ("XHEM5", "Dra. Sánchez"), ("XHEM11", "Dr. Ríos de Paz"), ("XHEM1A", "Dra. Herrero")], 
        "Friday": [("XHEM4A", "Dra. Marrero"), ("XHEM11", "Dr. Ríos de Paz")]
    }
    for cod in ["XHEM4A", "XHEM4B", "XHEM4D", "XHEM4E", "XHEM4G", "XHEM5", "XHEM1A", "XHEM10 (Tromb.)", "XHEM11"]: res["Agendas"][cod] = ""
    for c, m in r_xhem.get(dia_en, []):
        if m in ["Dr. Ríos de Paz", "Dra. Montalvo"]: res["Agendas"][c] = f"✅ {m}" if m not in ausentes + salientes + bajas else f"❌ {m} (No disp.)"
        elif asignar(m): res["Agendas"][c] = f"✅ {m}"
        else: res["Agendas"][c] = f"❌ {m} (No disp.)"

    # 3. TAO (ACO)
    tao_titu = {"Monday": "Dra. Montalvo", "Tuesday": "Dra. Lorenzo", "Wednesday": "Dr. Ríos de Paz", "Thursday": "Dra. Montalvo", "Friday": "Dr. Ríos de Paz"}.get(dia_en)
    if tao_titu == "Dra. Montalvo" and disp_mont: res["TAO"] = "✅ Dra. Montalvo"
    elif tao_titu == "Dr. Ríos de Paz" and disp_rios: res["TAO"] = "✅ Dr. Ríos de Paz"
    elif tao_titu == "Dra. Lorenzo" and asignar("Dra. Lorenzo"): res["TAO"] = "✅ Dra. Lorenzo"
    elif asignar("Dra. Herrero"): res["TAO"] = "🔄 Dra. Herrero"
    else: res["TAO"] = "✅ Dr. Ríos de Paz (Simult. ACO)" if disp_rios else "❌ [ACO VACÍO]"

    # 4. PEDIATRÍA E IC HOSPITALARIA
    ic_hosp = []
    if asignar("Dr. González"): res["Ped"] = "✅ Dr. González"
    elif asignar("Dr. De Ramos"): res["Ped"] = "🔄 Dr. De Ramos"
    elif "Dra. Peris" not in ausentes + salientes + bajas: res["Ped"] = "✅ Dra. Peris (Simult. Banco)"
    else: res["Ped"] = "❗ [VACÍO]"

    if "Dr. González" not in ausentes + salientes + bajas: ic_hosp.append("✅ Dr. González")
    if "Dr. García Roulston" not in ausentes + salientes + bajas: ic_hosp.append("✅ Dr. García Roulston")
    res["IC_Hosp"] = " / ".join(ic_hosp) if ic_hosp else "❌ [VACÍO]"

    # 5. LABS Y BANCO
    res["Diag"] = ["✅ Dr. Breña" if asignar("Dr. Breña") else "❌ [VACÍO]", "✅ Dra. Notario" if asignar("Dra. Notario") else "❌ [VACÍO]"]
    res["Hem"] = "✅ Dra. Alberich" if asignar("Dra. Alberich") else "❌ [VACÍO]"
    res["Banco"] = ["✅ Dr. Figueroa" if asignar("Dr. Figueroa") else "❌ [VACÍO]", "✅ Dra. Peris" if asignar("Dra. Peris") else "❌ [VACÍO]"]

    # 6. LA CASCADA ESTRUCTURAL DE PLANTA Y HD
    p_hoy = ["", "", ""]
    hd = ["", "", ""]
    
    p_titu = ["Dra. Busnego", "Dr. Moreno", "Dra. Rodríguez Esteban"]
    hd_titu = [
        {"Monday": "Dra. Sánchez", "Tuesday": "Dr. Ríos Rull", "Wednesday": "Dra. Sánchez", "Thursday": "Dra. Martín", "Friday": "Dra. Sánchez"}.get(dia_en),
        {"Monday": "Dra. Hernández", "Tuesday": "Dra. Hernández", "Thursday": "Dra. Hernández", "Friday": "Dra. Hernández"}.get(dia_en),
        None
    ]
    p_sust = ["Dr. García Roulston", "Dr. De Ramos", "Dra. Herrero", "Dra. Martín"]
    hd_sust = ["Dra. Martín", "Dr. García Roulston", "Dr. De Ramos", "Dra. Herrero", "Dra. Rodríguez Esteban"]

    def is_gest(m): return (dia_en=="Tuesday" and m=="Dra. Sánchez") or (dia_en=="Wednesday" and m=="Dra. Hernández")
    active_titulares = [t for t in [p_titu[0], p_titu[1], hd_titu[0], hd_titu[1], hd_titu[2], p_titu[2]] if t]

    def fill_position(titular, sust_list, is_hd=False):
        if titular and titular not in asignados:
            asignados.append(titular); return f"✅ {titular}"
        for s in sust_list:
            if s not in blindados and s not in asignados:
                asignados.append(s); return f"🔄 {s}"
        hd_gest = {"Tuesday": "Dra. Sánchez", "Wednesday": "Dra. Hernández"}.get(dia_en)
        if is_hd and hd_gest and hd_gest not in asignados and hd_gest not in blindados:
            asignados.append(hd_gest); return f"⚠️ {hd_gest} (Gestión rota para HD)"
        for m in plantilla:
            if m not in asignados and m not in blindados and m not in active_titulares and not is_gest(m):
                asignados.append(m); return f"🟦 {m}" if is_hd else f"🔄 {m}"
        for m in plantilla:
            if m not in asignados and m not in blindados and m not in active_titulares:
                asignados.append(m); return f"⚠️ {m} (Gestión)"
        for m in plantilla:
            if m not in asignados and m not in blindados:
                asignados.append(m); return f"⚠️ {m} (Reasignado)"
        return "❌ [VACÍO]"

    p_hoy[0] = fill_position(p_titu[0], p_sust, False)
    p_hoy[1] = fill_position(p_titu[1], p_sust, False)
    
    if dia_en in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        hd[0] = fill_position(hd_titu[0], hd_sust, True)
        hd[1] = fill_position(hd_titu[1], hd_sust, True)
        hd[2] = fill_position(hd_titu[2], hd_sust, True)
    else: hd[0] = hd[1] = hd[2] = "❌ [VACÍO]"

    hd_lleno = all("VACÍO" not in h for h in hd[:3])
    if hd_lleno: p_hoy[2] = fill_position(p_titu[2], p_sust, False)
    else: p_hoy[2] = "❌ [VACÍO]"

    # 7. RESCATES DE ÚLTIMA HORA
    def rescate_extremo(arr, idx, is_hd=False):
        if arr[idx] == "" or "VACÍO" not in arr[idx]: return
        ok = False
        s_list = hd_sust + plantilla if is_hd else plantilla
        for m in s_list:
            if m not in asignados and m not in blindados and not is_gest(m):
                asignados.append(m); arr[idx] = f"🟦 {m}" if is_hd else f"🔄 {m}"; ok = True; break
        if not ok:
            for m in plantilla:
                if m not in asignados and m not in blindados:
                    asignados.append(m); arr[idx] = f"⚠️ {m} (Gestión)"; break

    rescate_extremo(p_hoy, 0); rescate_extremo(p_hoy, 1)
    for i in range(3): rescate_extremo(hd, i, True)
    
    hd_lleno_final = all("VACÍO" not in h for h in hd[:3])
    if hd_lleno_final and "VACÍO" in p_hoy[2]:
        p_hoy[2] = fill_position(p_titu[2], p_sust, False)
        rescate_extremo(p_hoy, 2)
    elif not hd_lleno_final: p_hoy[2] = "❌ [VACÍO]"

    # BALANCEADOR OBLIGATORIO PLANTA VS HD
    p_filled = [i for i, x in enumerate(p_hoy) if "VACÍO" not in x and x != ""]
    hd_filled = [i for i, x in enumerate(hd[:3]) if "VACÍO" not in x and x != ""]
    
    while len(p_filled) > len(hd_filled):
        p_to_move = p_filled[-1]
        free_hd = [i for i in range(3) if i not in hd_filled]
        if not free_hd: break
        
        hd_idx = free_hd[0]
        med_text = p_hoy[p_to_move]
        med_name = med_text.replace("✅", "").replace("🔄", "").replace("🟦", "").replace("⚠️", "").split("(")[0].strip()
        
        hd[hd_idx] = f"⚖️ {med_name} (Balanceado)"
        p_hoy[p_to_move] = "❌ [VACÍO]"
        
        p_filled = [i for i, x in enumerate(p_hoy) if "VACÍO" not in x and x != ""]
        hd_filled = [i for i, x in enumerate(hd[:3]) if "VACÍO" not in x and x != ""]

    # 8. INTERCONSULTA VIRTUAL Y EXTERNA
    res["IC_Virt"] = ""
    if dia_en == "Friday":
        if "Dra. Lorenzo" not in ausentes + salientes + bajas: 
            res["IC_Virt"] = "✅ Dra. Lorenzo"
            if "Dra. Lorenzo" not in asignados: asignados.append("Dra. Lorenzo")
        elif "Dr. Ríos Rull" not in ausentes + salientes + bajas: res["IC_Virt"] = "✅ Dr. Ríos Rull (Simult.)"
    elif dia_en == "Wednesday" and "Dr. Ríos Rull" not in ausentes + salientes + bajas: res["IC_Virt"] = "✅ Dr. Ríos Rull (Simult.)"
    elif dia_en == "Tuesday":
        if "Dra. Hernanz" not in ausentes + salientes + bajas:
            res["IC_Virt"] = "✅ Dra. Hernanz"
            if "Dra. Hernanz" not in asignados: asignados.append("Dra. Hernanz")

    if "Dr. Ríos Rull" not in ausentes + salientes + bajas:
        if "Dr. Ríos Rull" in asignados: res["IC_Ext"] = "✅ Dr. Ríos Rull (Simult.)"
        else: res["IC_Ext"] = "✅ Dr. Ríos Rull"; asignados.append("Dr. Ríos Rull")
    else: res["IC_Ext"] = "❌ [VACÍO]"

    # 9. BUSCA DEFINITIVO 
    busca_prioridad = ["Dra. Herrero", "Dra. Martín", "Dr. De Ramos", "Dr. García Roulston", "Dra. Rodríguez Esteban"]
    med_busca_final = next((m for m in busca_prioridad if m not in asignados and m in plantilla), None)
    
    if med_busca_final: 
        res["Busca"] = f"🚨 {med_busca_final}"
        asignados.append(med_busca_final)
    else: res["Busca"] = "❌ [SIN BUSCA]"

    res["H_Dia"] = [f"HD{i+1}: {h}" for i, h in enumerate(hd) if h != ""]
    res["Planta"] = [f"P{i+1}: {p}" for i, p in enumerate(p_hoy)]
    res["Gestion"] = [m for m in plantilla if m not in asignados]
    return res

st.sidebar.header("📁 Administración")
df_g, df_v, df_g_r, df_rot_r = cargar_todo("datos.xlsx")
if df_g is not None: st.sidebar.success("✅ BD conectada")
arc = st.sidebar.file_uploader("Actualizar Excel:", type=["xlsx"])
if arc: df_g, df_v, df_g_r, df_rot_r = cargar_todo(arc)

if df_g is not None:
    modo = st.sidebar.selectbox("Vista:", ["Diaria", "Semanal", "Mensual"])
    f_sel = st.sidebar.date_input("Día:", datetime.now())
    bajas = st.sidebar.multiselect("Bajas imprevistas:", plantilla)
    
    if modo == "Diaria":
        d = calcular_cuadrante(f_sel, df_g, df_v, bajas, df_g_r, df_rot_r)
        st.header(f"Gestión {d['Fecha']} ({d['Día']})")
        c_p, _ = st.columns([1, 4])
        with c_p: st.info("💡 PDF: Ctrl+P -> Ajusta a 60-70%")
        
        if d.get("Es_Festivo"):
            st.error("🛑 DÍA FESTIVO / FIN DE SEMANA (Sin actividad ordinaria en el servicio)")
            c1, c2 = st.columns(2)
            with c1: st.markdown(f"**⚕️ Médico de Guardia:** {d.get('Guardia', '')}")
            with c2: st.markdown(f"**🎓 Residente de Guardia:** {d.get('Guardia_Resis', '')}")
        else:
            if d["Saliente"]: st.warning(f"🛑 Salientes: {d['Saliente']}")
            if d["Saliente_Resis"]: st.warning(f"🛑 Salientes (Resis): {d['Saliente_Resis']}")
            if d["Ausentes"]: st.error(f"🏖️ Vacaciones/Bajas: {', '.join(d['Ausentes'])}")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.subheader("🛏️ Clínica")
                for x in d["Planta"]: st.markdown(x)
                if d["Resi_Planta"]: st.markdown(f"**P Resi:** {', '.join(d['Resi_Planta'])}")
                st.divider()
                st.write("**Hospital de Día:**")
                for x in d["H_Dia"]: st.markdown(x)
                if d["Resi_HD"]: st.markdown(f"**HD Res:** {', '.join(d['Resi_HD'])}")
            with c2:
                st.subheader("💉 Coagulación")
                if not d['Coag']: st.markdown("❌ [VACÍO]")
                else:
                    for m in d['Coag']: st.markdown(f"✅ {m}")
                st.divider()
                st.subheader("🔬 Lab")
                for x in d["Diag"]: st.markdown(x)
                st.markdown(f"**Hem:** {d['Hem']}")
                if d["Resi_Diag"]: st.markdown(f"**Diag Resi:** {', '.join(d['Resi_Diag'])}")
                st.divider()
                st.subheader("🩸 Banco")
                for x in d["Banco"]: st.markdown(x)
                if d["Resi_Banco"]: st.markdown(f"**Banco Resi:** {', '.join(d['Resi_Banco'])}")
            with c3:
                st.subheader("📋 Agendas XHEM")
                for c, m in d["Agendas"].items():
                    if "✅" in m or "❌" in m or "🔄" in m: st.markdown(f"**{c}**: {m}")
                if d["Resi_Cons"]: st.markdown(f"**Cons Resi:** {', '.join(d['Resi_Cons'])}")
                st.divider()
                st.markdown(f"**TAO:** {d['TAO']}")
                st.markdown(f"**Sur:** {d['Sur']}")
            with c4:
                st.subheader("🏥 IC y Pediatría")
                st.markdown(f"IC Hosp: {d['IC_Hosp']}")
                st.markdown(f"IC Virt: {d['IC_Virt']}")
                st.markdown(f"IC Ext: {d['IC_Ext']}")
                st.markdown(f"**Ped:** {d['Ped']}")
                st.divider()
                st.markdown(f"**Busca:** {d['Busca']}")
                st.divider()
                st.subheader("📂 Gestión")
                if d["Gestion"]:
                    for m in d["Gestion"]: st.markdown(f"💼 {m}")
                else: st.markdown("No personal libre.")
                
            st.divider()
            st.subheader("🎓 Otras Rotaciones / Externas")
            if d["Resi_Otros"]:
                for r in d["Resi_Otros"]: st.markdown(f"🔹 {r}")
            else: st.markdown("Ningún residente en rotaciones externas.")

    elif modo == "Semanal":
        lunes = f_sel - timedelta(days=f_sel.weekday())
        pts = ["Guardia", "Guardia_Resis", "Saliente", "Sal_Resis", "Ausentes", "P1", "P2", "P3", "P Resi", "HD1", "HD2", "HD3", "HD Res", "Cons 1", "Cons 2", "Cons 3", "Cons Resi", "Coagulación", "Sur", "TAO", "Diag 1", "Diag 2", "Diag Resi", "Hem", "Banco 1", "Banco 2", "Banco Resi", "Busca", "IC Hosp", "IC Virt", "IC Ext", "Pediatría", "Gestión", "Otras Rotaciones"]
        tb = {p: [] for p in pts}
        cols = []
        for i in range(5):
            d = calcular_cuadrante(lunes + timedelta(days=i), df_g, df_v, bajas, df_g_r, df_rot_r)
            cols.append(f"{d['Día'][:3]} {d['Fecha'][:5]}")
            
            tb["Guardia"].append(d.get("Guardia", ""))
            tb["Guardia_Resis"].append(d.get("Guardia_Resis", ""))
            
            if d.get("Es_Festivo"):
                for p in pts[2:]: tb[p].append("🛑 FESTIVO" if p not in ["Saliente", "Sal_Resis", "Ausentes", "P Resi", "HD Res", "Cons Resi", "Diag Resi", "Banco Resi", "Otras Rotaciones"] else "")
            else:
                nrms = []
                for cod, m in d["Agendas"].items():
                    if "✅" in m or "🔄" in m:
                        nm = m.replace("✅ ","").replace("🔄 ","🔄 ")
                        if cod not in ["XHEM10 (Tromb.)", "XHEM11"]: nrms.append(f"{cod}: {nm}")
                while len(nrms) < 3: nrms.append("")
                
                def c(v): return v.replace("✅ ","").replace("🟦 ","").replace("⚠️ ","").replace("❗ ","").replace("⚖️ ","⚖️ ")
                def g(l, x): return c(l[x].split(": ")[1] if len(l)>x and ": " in l[x] else "")
                
                tb["Saliente"].append(d.get("Saliente", ""))
                tb["Sal_Resis"].append(d.get("Saliente_Resis", ""))
                tb["Ausentes"].append(" / ".join(d["Ausentes"]) if d["Ausentes"] else "")
                tb["P1"].append(g(d["Planta"],0))
                tb["P2"].append(g(d["Planta"],1))
                tb["P3"].append(g(d["Planta"],2))
                tb["P Resi"].append(" / ".join(d["Resi_Planta"]) if d["Resi_Planta"] else "")
                tb["HD1"].append(g(d["H_Dia"],0))
                tb["HD2"].append(g(d["H_Dia"],1))
                tb["HD3"].append(g(d["H_Dia"],2))
                tb["HD Res"].append(" / ".join(d["Resi_HD"]) if d["Resi_HD"] else "")
                tb["Cons 1"].append(nrms[0])
                tb["Cons 2"].append(nrms[1])
                tb["Cons 3"].append(nrms[2])
                tb["Cons Resi"].append(" / ".join(d["Resi_Cons"]) if d["Resi_Cons"] else "")
                tb["Coagulación"].append(" / ".join(d["Coag"]) if d["Coag"] else "")
                tb["Sur"].append(c(d["Sur"]))
                tb["TAO"].append(c(d["TAO"]))
                tb["Diag 1"].append(c(d["Diag"][0]))
                tb["Diag 2"].append(c(d["Diag"][1]))
                tb["Diag Resi"].append(" / ".join(d["Resi_Diag"]) if d["Resi_Diag"] else "")
                tb["Hem"].append(c(d["Hem"]))
                tb["Banco 1"].append(c(d["Banco"][0]))
                tb["Banco 2"].append(c(d["Banco"][1]))
                tb["Banco Resi"].append(" / ".join(d["Resi_Banco"]) if d["Resi_Banco"] else "")
                tb["Busca"].append(d["Busca"].replace("🚨 ",""))
                tb["IC Hosp"].append(c(d["IC_Hosp"]))
                tb["IC Virt"].append(c(d["IC_Virt"]))
                tb["IC Ext"].append(c(d["IC_Ext"]))
                tb["Pediatría"].append(c(d["Ped"]))
                tb["Gestión"].append(" / ".join(d["Gestion"]) if d["Gestion"] else "")
                tb["Otras Rotaciones"].append(" / ".join(d["Resi_Otros"]) if d["Resi_Otros"] else "")
            
        df = pd.DataFrame(tb, index=cols).T
        for r in ["Guardia", "Guardia_Resis", "Saliente", "Sal_Resis", "Ausentes", "P Resi", "HD Res", "Cons Resi", "Diag Resi", "Banco Resi", "Gestión", "Otras Rotaciones"]:
            if all(x == "" for x in df.loc[r]): df = df.drop(r)
        st.table(df)
        
        b = io.BytesIO()
        with pd.ExcelWriter(b, engine='xlsxwriter') as w: 
            df.to_excel(w, sheet_name='Semana')
            wb = w.book
            ws = w.sheets['Semana']
            f_celda = wb.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
            f_cabecera = wb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            f_indice = wb.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1, 'align': 'left', 'valign': 'vcenter'})
            ws.set_column(0, 0, 20, f_indice)
            ws.set_column(1, len(df.columns), 28, f_celda)
            for col_num, value in enumerate(df.columns.values):
                ws.write(0, col_num + 1, value, f_cabecera)
        st.download_button("📥 Descargar Excel Semana", b.getvalue(), f"Sem_{lunes.strftime('%d%m')}.xlsx", "application/vnd.ms-excel")

    elif modo == "Mensual":
        ms = st.sidebar.selectbox("Médico:", plantilla)
        im = f_sel.replace(day=1)
        fm = (im + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        cl = []
        for dia in pd.date_range(im, fm):
            if dia.weekday() >= 5: continue
            d = calcular_cuadrante(dia, df_g, df_v, bajas, df_g_r, df_rot_r)
            if ms in d.get("Saliente", ""): pst = "🛑 SALIENTE"
            elif ms in d.get("Ausentes", []) or ms in bajas: pst = "🏖️ VACACIONES"
            elif d.get("Es_Festivo"):
                pst = "⚕️ GUARDIA FESTIVO" if ms in d.get("Guardia", "") else "🛑 FESTIVO"
            else:
                p = []
                for k, v in d.items():
                    if k == "Agendas":
                        for cd, md in v.items():
                            if ms in md: p.append(cd)
                    elif isinstance(v, list) and any(ms in str(x) for x in v): p.append(k)
                    elif isinstance(v, str) and ms in v: p.append(k)
                pst = " + ".join(list(set(p))) if p else "Gestión"
            cl.append({"Fecha": dia.strftime("%d/%m"), "Día": dia.strftime("%A"), "Puesto": pst})
        dfm = pd.DataFrame(cl)
        st.table(dfm)
        
        b = io.BytesIO()
        with pd.ExcelWriter(b, engine='xlsxwriter') as w: 
            dfm.to_excel(w, sheet_name='Mes', index=False)
            wb = w.book
            ws = w.sheets['Mes']
            f_celda = wb.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
            f_cabecera = wb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            ws.set_column(0, 1, 15, f_celda)
            ws.set_column(2, 2, 50, f_celda)
            for col_num, value in enumerate(dfm.columns.values):
                ws.write(0, col_num, value, f_cabecera)
        st.download_button("📥 Descargar Excel Mes", b.getvalue(), f"Mes_{ms}.xlsx", "application/vnd.ms-excel")
else: st.info("Sube datos.xlsx a GitHub o usa el panel lateral.")
