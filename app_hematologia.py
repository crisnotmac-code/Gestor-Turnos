import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re
import os
import smtplib
from email.message import EmailMessage

st.set_page_config(page_title="Gestor Hematología 2026", layout="wide")
st.markdown("""<style>@media print { header, [data-testid="stSidebar"], [data-testid="stToolbar"] { display: none !important; } .main { max-width: 100% !important; padding: 0 !important; } @page { size: landscape; margin: 1cm; } }</style>""", unsafe_allow_html=True)

# Lista Maestra Adjuntos
plantilla = ["Dra. Busnego", "Dr. Moreno", "Dra. Sánchez", "Dra. Hernández", "Dra. Martín", "Dra. Alberich", "Dr. Breña", "Dra. Notario", "Dr. Figueroa", "Dra. Peris", "Dra. Montalvo", "Dr. R. de Paz", "Dra. Herrero", "Dra. Lorenzo", "Dra. R. Esteban", "Dra. Hernanz", "Dra. Marrero", "Dr. González", "Dr. G. Roulston", "Dr. R. Rull", "Dr. De Ramos"]

meses_es_str = {"ENERO":1, "FEBRERO":2, "MARZO":3, "ABRIL":4, "MAYO":5, "JUNIO":6, "JULIO":7, "AGOSTO":8, "SEPTIEMBRE":9, "OCTUBRE":10, "NOVIEMBRE":11, "DICIEMBRE":12}
meses_es = {1:"ENERO", 2:"FEBRERO", 3:"MARZO", 4:"ABRIL", 5:"MAYO", 6:"JUNIO", 7:"JULIO", 8:"AGOSTO", 9:"SEPTIEMBRE", 10:"OCTUBRE", 11:"NOVIEMBRE", 12:"DICIEMBRE"}

def limpiar_texto(s):
    if pd.isna(s): return ""
    s = str(s).upper()
    for k, v in {"Á":"A", "É":"E", "Í":"I", "Ó":"O", "Ú":"U", "-":" "}.items(): 
        s = s.replace(k, v)
    s = re.sub(r'[^\w\s]', '', s)
    return ' '.join(s.split())

def formatear_resi(n_orig):
    n = limpiar_texto(str(n_orig))
    if not n: return ""
    
    if "CLIMENT" in n or ("JULIA" in n and "GONZALEZ" in n): return "Dra. Climent"
    if "DOS SANTOS" in n: return "Dra. R. Dos Santos"
    if "RUBIO" in n: return "Dra. R. Rubio"
    if "MARCAL" in n: return "Dra. Marcal"
    if "MARTINEZ" in n: return "Dra. Martínez Carrasco"
    if "QUINTERO" in n: return "Dr. Quintero"
    if "CRESPO" in n: return "Dra. Crespo"
    if "OLIVA" in n: return "Dra. Oliva"
    
    parts = n.split()
    if not parts: return ""
    fem_names = ["CARMEN", "MARIA", "SOFIA", "JULIA", "GLORIA", "VALERIA", "ANA", "PATRICIA", "SILVIA", "ELENA", "MINERVA", "NEREA", "YAXIRAXI", "NURIA", "CRISTINA", "LAURA"]
    genero = "Dra." if parts[0].endswith("A") or parts[0] in fem_names else "Dr."
    apellido = parts[1].capitalize() if len(parts) > 1 else parts[0].capitalize()
    return f"{genero} {apellido}"

def match_medico(nombre_texto, med):
    nt = limpiar_texto(nombre_texto)
    mt = limpiar_texto(med).replace("DR. ", "").replace("DRA. ", "").replace("DR ", "").replace("DRA ", "").strip()
    
    if "CLIMENT" in nt and "GONZALEZ" in mt: return False
    
    if med == "Dr. R. de Paz": return ("PAZ" in nt) or (("RIOS" in nt or "PABLO" in nt) and "RULL" not in nt)
    if med == "Dr. R. Rull": return "RULL" in nt
    if med == "Dr. G. Roulston": return "ROULSTON" in nt or "KEVIN" in nt
    if med == "Dra. R. Esteban": return "RODRIGUEZ" in nt and "SANTOS" not in nt and "RUBIO" not in nt
    if med == "Dr. De Ramos": return "RAMOS" in nt
    if med == "Dra. Alberich": return "ALBERICH" in nt or "LABERICH" in nt
    
    apellido_principal = mt.split()[0]
    return apellido_principal in nt.split()

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
            if not os.path.exists(archivo): return None, None, None, None
            f = archivo
        elif hasattr(archivo, 'getvalue'): f = io.BytesIO(archivo.getvalue())
        else: f = archivo
            
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
                                enc.append(formatear_resi(txt))
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
                        matched_any = False
                        for med in plantilla:
                            if match_medico(txt_full, med): 
                                enc.append(med)
                                matched_any = True
                        if not matched_any:
                            n_res_raw = str(r.iloc[1]).strip() + " " + str(r.iloc[0]).strip() if len(r) > 1 else str(r.iloc[0]).strip()
                            n_res_raw = n_res_raw.replace("nan", "").replace("None", "").strip()
                            if n_res_raw: 
                                enc.append(f"{formatear_resi(n_res_raw)} (Resi)")
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
                    matched_any = False
                    for med in plantilla:
                        if match_medico(nombre_celda, med): 
                            enc.append(med)
                            matched_any = True
                    if not matched_any:
                        n_res_raw = nombre_celda.replace("nan", "").replace("None", "").strip()
                        if n_res_raw: 
                            enc.append(f"{formatear_resi(n_res_raw)} (Resi)")
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
                            resi_raw = str(r[c_res]).strip()
                            resi = formatear_resi(resi_raw)
                            
                            is_saliente = resi in sal_resis
                            is_ausente = any(resi == a.replace(" (Resi)", "") for a in ausentes)

                            if not is_saliente and not is_ausente and resi != "": 
                                rot_texto = str(r[c_rot]).strip()
                                rot_up = rot_texto.upper()
                                if any(k in rot_up for k in ["PLANTA", "HOSPITALIZACION", "HOSPITALIZACIÓN"]): resi_planta.append(resi)
                                elif any(k in rot_up for k in ["DIA", "DÍA", "HD", "AMBULATORIO"]): resi_hd.append(resi)
                                elif any(k in rot_up for k in ["DIAG", "LAB", "MORFOLOG", "CITOMETR", "BIOLOGIA"]): resi_diag.append(resi)
                                elif any(k in rot_up for k in ["BANCO", "TRANSFUS", "AFERESIS", "AFÉRESIS"]): resi_banco.append(resi)
                                elif any(k in rot_up for k in ["CONS", "XHEM"]): resi_cons.append(resi)
                                else: resi_otros.append(f"{resi} ({rot_texto})")
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
        res["Ped"] = ""; res["IC_Hosp"] = ""; res["Gestion"] = []
        return res

    def asignar(m):
        if m and m not in asignados:
            asignados.append(m); return True
        return False

    # 1. COAGULACIÓN Y SUR
    disp_rios = "Dr. R. de Paz" not in asignados
    disp_mont = "Dra. Montalvo" not in asignados
    res["Coag"] = []
    if disp_rios: res["Coag"].append("Dr. R. de Paz"); asignados.append("Dr. R. de Paz")
    if disp_mont: res["Coag"].append("Dra. Montalvo"); asignados.append("Dra. Montalvo")

    sur_titu = {"Monday": "Dr. G. Roulston", "Tuesday": "Dra. Montalvo", "Wednesday": "Dra. Herrero", "Thursday": "Dr. De Ramos", "Friday": "Dra. R. Esteban"}.get(dia_en)
    if sur_titu == "Dra. Montalvo" and disp_mont: res["Sur"] = "✅ Dra. Montalvo"
    elif asignar(sur_titu): res["Sur"] = f"✅ {sur_titu}"
    else: res["Sur"] = "❌ [VACÍO]"

    # 2. CONSULTAS XHEM
    r_xhem = {
        "Monday": [("XHEM4A", "Dra. Marrero"), ("XHEM4B", "Dra. Hernanz"), ("XHEM4G", "Dra. Lorenzo"), ("XHEM11", "Dr. R. de Paz")], 
        "Tuesday": [("XHEM4A", "Dra. Marrero"), ("XHEM4E", "Dr. De Ramos"), ("XHEM11", "Dr. R. de Paz"), ("XHEM1A", "Dra. Herrero")], 
        "Wednesday": [("XHEM4B", "Dra. Hernanz"), ("XHEM4D", "Dra. Martín"), ("XHEM4G", "Dra. Lorenzo"), ("XHEM10 (Tromb.)", "Dra. Montalvo")], 
        "Thursday": [("XHEM4B", "Dra. Hernanz"), ("XHEM5", "Dra. Sánchez"), ("XHEM11", "Dr. R. de Paz"), ("XHEM1A", "Dra. Herrero")], 
        "Friday": [("XHEM4A", "Dra. Marrero"), ("XHEM11", "Dr. R. de Paz"), ("XHEM10 (Tromb.)", "Dra. Montalvo")]
    }
    for cod in ["XHEM4A", "XHEM4B", "XHEM4D", "XHEM4E", "XHEM4G", "XHEM5", "XHEM1A", "XHEM10 (Tromb.)", "XHEM11"]: res["Agendas"][cod] = ""
    for c, m in r_xhem.get(dia_en, []):
        if m in ["Dr. R. de Paz", "Dra. Montalvo"]: res["Agendas"][c] = f"✅ {m}" if m not in ausentes + salientes + bajas else f"❌ {m} (No disp.)"
        elif asignar(m): res["Agendas"][c] = f"✅ {m}"
        else: res["Agendas"][c] = f"❌ {m} (No disp.)"

    # 3. TAO (ACO) 
    tao_assigned = []
    if dia_en in ["Monday"] and disp_mont:
        tao_assigned.append("✅ Dra. Montalvo")
    if dia_en in ["Tuesday", "Thursday"] and "Dra. Lorenzo" not in asignados:
        asignados.append("Dra. Lorenzo")
        tao_assigned.append("✅ Dra. Lorenzo")
    if dia_en in ["Wednesday", "Friday"] and disp_rios:
        tao_assigned.append("✅ Dr. R. de Paz")
        
    if tao_assigned:
        res["TAO"] = " / ".join(tao_assigned)
    else:
        res["TAO"] = "✅ Dr. R. de Paz (Simult. ACO)" if disp_rios else "❌ [ACO VACÍO]"

    # 4. PEDIATRÍA E IC HOSPITALARIA
    ic_hosp = []
    
    if asignar("Dr. González"): res["Ped"] = "✅ Dr. González"
    elif "Dra. Peris" not in ausentes + salientes + bajas: res["Ped"] = "✅ Dra. Peris (Simult. Banco)"
    elif "Dr. De Ramos" not in ausentes + salientes + bajas: res["Ped"] = "✅ Dr. De Ramos (Simult.)"
    else: res["Ped"] = "❗ [VACÍO]"

    if "Dr. González" not in ausentes + salientes + bajas: ic_hosp.append("✅ Dr. González")
    if "Dr. G. Roulston" not in ausentes + salientes + bajas: ic_hosp.append("✅ Dr. G. Roulston")
    res["IC_Hosp"] = " / ".join(ic_hosp) if ic_hosp else "❌ [VACÍO]"

    # 5. LABS Y BANCO
    res["Diag"] = ["✅ Dr. Breña" if asignar("Dr. Breña") else "❌ [VACÍO]", "✅ Dra. Notario" if asignar("Dra. Notario") else "❌ [VACÍO]"]
    res["Hem"] = "✅ Dra. Alberich" if asignar("Dra. Alberich") else "❌ [VACÍO]"
    res["Banco"] = ["✅ Dr. Figueroa" if asignar("Dr. Figueroa") else "❌ [VACÍO]", "✅ Dra. Peris" if asignar("Dra. Peris") else "❌ [VACÍO]"]

    # 6. ASIGNACIÓN ESTRICTA DE PLANTA Y HD
    p_hoy = ["", "", ""]
    hd = ["", "", ""]
    
    p_titu = ["Dra. Busnego", "Dr. Moreno", "Dra. R. Esteban"]
    hd_titu = [
        {"Monday": "Dra. Sánchez", "Tuesday": "Dr. R. Rull", "Wednesday": "Dra. Sánchez", "Friday": "Dra. Sánchez"}.get(dia_en),
        {"Monday": "Dra. Hernández", "Tuesday": "Dra. Hernández", "Thursday": "Dra. Hernández", "Friday": "Dra. Hernández"}.get(dia_en),
        {"Monday": "Dra. Martín", "Tuesday": "Dra. Martín", "Thursday": "Dra. Martín"}.get(dia_en)
    ]
    
    p_sust = ["Dra. Herrero", "Dr. De Ramos", "Dr. G. Roulston"]
    hd_sust = ["Dr. De Ramos", "Dr. G. Roulston", "Dra. Martín"] # Martín baja prioridad en viernes

    habituales_hd = ["Dra. Sánchez", "Dra. Hernández", "Dr. De Ramos", "Dra. Martín", "Dr. R. Rull", "Dr. G. Roulston"]

    no_pisan_planta = ["Dra. Sánchez", "Dra. Hernández", "Dra. Lorenzo", "Dr. R. Rull", "Dr. R. de Paz", "Dr. González", "Dra. Marrero", "Dra. Hernanz", "Dra. Martín"]
    no_pisan_hd = ["Dr. Moreno", "Dra. R. Esteban", "Dra. Lorenzo", "Dr. R. Rull", "Dr. R. de Paz", "Dr. González", "Dra. Marrero", "Dra. Hernanz", "Dra. Herrero"]
    
    no_pisan_p1_p2 = ["Dra. R. Esteban"]
    no_pisan_p1_p3 = ["Dr. Moreno"]

    def is_gest(m): return (dia_en=="Tuesday" and m=="Dra. Sánchez") or (dia_en=="Wednesday" and m=="Dra. Hernández")

    for i in range(3):
        if hd_titu[i] and asignar(hd_titu[i]): hd[i] = f"✅ {hd_titu[i]}"
    for i in range(3):
        if p_titu[i] and asignar(p_titu[i]): p_hoy[i] = f"✅ {p_titu[i]}"

    def fill_spot(spot_type, spot_idx, sust_list):
        for s in sust_list:
            if s not in asignados:
                if spot_type == 'P' and s in no_pisan_planta: continue
                if spot_type == 'HD' and s in no_pisan_hd: continue
                if spot_type == 'P' and spot_idx in [0, 1] and s in no_pisan_p1_p2: continue
                if spot_type == 'P' and spot_idx in [0, 2] and s in no_pisan_p1_p3: continue
                asignados.append(s)
                if spot_type == 'HD' and s in habituales_hd: return f"✅ {s}"
                if spot_type == 'P' and s == "Dra. Herrero": return f"🔄 {s}" 
                return f"🔄 {s}"
        
        if spot_type == 'HD':
            hd_gest = {"Tuesday": "Dra. Sánchez", "Wednesday": "Dra. Hernández"}.get(dia_en)
            if hd_gest and hd_gest not in asignados:
                asignados.append(hd_gest); return f"⚠️ {hd_gest} (Gestión rota)"
        
        for m in plantilla:
            if m not in asignados:
                if spot_type == 'P' and m in no_pisan_planta: continue
                if spot_type == 'HD' and m in no_pisan_hd: continue
                if spot_type == 'P' and spot_idx in [0, 1] and m in no_pisan_p1_p2: continue
                if spot_type == 'P' and spot_idx in [0, 2] and m in no_pisan_p1_p3: continue
                if is_gest(m): continue
                asignados.append(m)
                if spot_type == 'HD' and m in habituales_hd: return f"✅ {m}"
                if spot_type == 'P' and m == "Dra. Herrero": return f"🔄 {m}"
                return f"🟦 {m}"
                
        for m in plantilla:
            if m not in asignados:
                if spot_type == 'P' and m in no_pisan_planta: continue
                if spot_type == 'HD' and m in no_pisan_hd: continue
                if spot_type == 'P' and spot_idx in [0, 1] and m in no_pisan_p1_p2: continue
                if spot_type == 'P' and spot_idx in [0, 2] and m in no_pisan_p1_p3: continue
                asignados.append(m)
                if spot_type == 'HD' and m in habituales_hd: return f"✅ {m}"
                if spot_type == 'P' and m == "Dra. Herrero": return f"🔄 {m}"
                return f"⚠️ {m} (Gestión)"
                
        return ""

    if dia_en in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        if hd[2] == "" and "Dra. Martín" not in asignados and dia_en != "Friday": # Friday lower priority
            asignados.append("Dra. Martín")
            hd[2] = "✅ Dra. Martín" 
        if hd[1] == "" and "Dr. G. Roulston" not in asignados:
            asignados.append("Dr. G. Roulston")
            hd[1] = "✅ Dr. G. Roulston" 

    if p_hoy[0] == "": p_hoy[0] = fill_spot('P', 0, p_sust)
    if p_hoy[1] == "": p_hoy[1] = fill_spot('P', 1, p_sust)
    
    if dia_en in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        if hd[0] == "": hd[0] = fill_spot('HD', 0, hd_sust)
        if hd[1] == "": hd[1] = fill_spot('HD', 1, hd_sust)
        if hd[2] == "": hd[2] = fill_spot('HD', 2, hd_sust)

    if p_hoy[2] == "":
        hd_lleno = all(h != "" for h in hd[:3])
        if hd_lleno: 
            p_hoy[2] = fill_spot('P', 2, p_sust)

    p_filled = [i for i, x in enumerate(p_hoy) if x != ""]
    hd_filled = [i for i, x in enumerate(hd[:3]) if x != ""]
    
    while len(p_filled) > len(hd_filled):
        movable_idx = None
        for idx in [2, 0, 1]:
            if p_hoy[idx] != "":
                med_name = p_hoy[idx].replace("✅", "").replace("🔄", "").replace("🟦", "").replace("⚠️", "").split("(")[0].strip()
                if med_name not in ["Dr. Moreno", "Dra. R. Esteban", "Dra. Busnego", "Dra. Herrero"]:
                    movable_idx = idx
                    break
        
        if movable_idx is None: break 
        
        free_hd = [i for i in range(3) if i not in hd_filled]
        if not free_hd: break
        
        hd_idx = free_hd[0]
        med_text = p_hoy[movable_idx]
        med_name = med_text.replace("✅", "").replace("🔄", "").replace("🟦", "").replace("⚠️", "").split("(")[0].strip()
        
        hd[hd_idx] = f"✅ {med_name}"
        p_hoy[movable_idx] = "---" 
        
        p_filled = [i for i, x in enumerate(p_hoy) if x != "" and x != "---"]
        hd_filled = [i for i, x in enumerate(hd[:3]) if x != ""]

    if "Dra. Herrero" not in asignados:
        for idx in [2, 0, 1]:
            if p_hoy[idx] in ["", "---"]:
                p_hoy[idx] = "🔄 Dra. Herrero"
                asignados.append("Dra. Herrero")
                break

    for i in range(3):
        if p_hoy[i] == "": p_hoy[i] = ""
        if hd[i] == "": hd[i] = ""

    # 8. INTERCONSULTA VIRTUAL Y EXTERNA
    res["IC_Virt"] = ""
    if dia_en == "Friday":
        if "Dra. Lorenzo" not in ausentes + salientes + bajas: 
            res["IC_Virt"] = "✅ Dra. Lorenzo"
            if "Dra. Lorenzo" not in asignados: asignados.append("Dra. Lorenzo")
        else: res["IC_Virt"] = ""
    elif dia_en == "Wednesday":
        if "Dra. Marrero" not in ausentes + salientes + bajas: 
            res["IC_Virt"] = "✅ Dra. Marrero"
            if "Dra. Marrero" not in asignados: asignados.append("Dra. Marrero")
        else: res["IC_Virt"] = ""
    elif dia_en == "Tuesday":
        if "Dra. Hernanz" not in ausentes + salientes + bajas:
            res["IC_Virt"] = "✅ Dra. Hernanz"
            if "Dra. Hernanz" not in asignados: asignados.append("Dra. Hernanz")
        else: res["IC_Virt"] = ""

    if "Dr. R. Rull" not in ausentes + salientes + bajas:
        if "Dr. R. Rull" in asignados: res["IC_Ext"] = "✅ Dr. R. Rull (Simult.)"
        else: res["IC_Ext"] = "✅ Dr. R. Rull"; asignados.append("Dr. R. Rull")
    else: res["IC_Ext"] = ""

    res["H_Dia"] = [f"HD{i+1}: {h}" for i, h in enumerate(hd) if h != "---"]
    res["Planta"] = [f"P{i+1}: {p}" for i, p in enumerate(p_hoy) if p != "---"]
    
    while len(res["Planta"]) < 3: res["Planta"].append("---")
    while len(res["H_Dia"]) < 3: res["H_Dia"].append("---")
        
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
        
        # --- NUEVO ORDEN DE EXCEL ---
        pts = [
            "P1", "P2", "P3", "P Resi", 
            "HD1", "HD2", "HD3", "HD Res", 
            "Cons 1", "Cons 2", "Cons 3", "Cons Resi", 
            "Coagulación", "TAO", 
            "Pediatría", 
            "Diag 1", "Diag 2", "Diag Resi", "Hem", 
            "Banco 1", "Banco 2", "Banco Resi", 
            "Sur", 
            "IC Hosp", "IC Virt", "IC Ext", 
            "Guardia", "Guardia_Resis", 
            "Saliente", "Sal_Resis", "Ausentes", 
            "Gestión", "Otras Rotaciones", "No Disponibles Totales"
        ]
        
        tb = {p: [] for p in pts}
        cols = []
        for i in range(5):
            d = calcular_cuadrante(lunes + timedelta(days=i), df_g, df_v, bajas, df_g_r, df_rot_r)
            cols.append(f"{d['Día'][:3]} {d['Fecha'][:5]}")
            
            tb["Guardia"].append(d.get("Guardia", ""))
            tb["Guardia_Resis"].append(d.get("Guardia_Resis", ""))
            
            if d.get("Es_Festivo"):
                for p in pts: 
                    if p not in ["Guardia", "Guardia_Resis", "Saliente", "Sal_Resis", "Ausentes", "P Resi", "HD Res", "Cons Resi", "Diag Resi", "Banco Resi", "Otras Rotaciones", "No Disponibles Totales"]:
                        tb[p].append("🛑 FESTIVO")
                    elif p not in ["Guardia", "Guardia_Resis"]: tb[p].append("")
                tb["No Disponibles Totales"][-1] = ""
            else:
                nrms = []
                for cod, m in d["Agendas"].items():
                    if "✅" in m or "🔄" in m:
                        nm = m.replace("✅ ","").replace("🔄 ","🔄 ")
                        if cod not in ["XHEM10 (Tromb.)", "XHEM11"]: nrms.append(f"{cod}: {nm}")
                while len(nrms) < 3: nrms.append("")
                
                def c(v): return v.replace("✅ ","").replace("🟦 ","").replace("⚠️ ","").replace("❗ ","").replace("⚖️ ","⚖️ ")
                def g(l, x): 
                    if len(l) > x and ": " in l[x]: return c(l[x].split(": ")[1])
                    return ""
                
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
                tb["IC Hosp"].append(c(d["IC_Hosp"]))
                tb["IC Virt"].append(c(d["IC_Virt"]))
                tb["IC Ext"].append(c(d["IC_Ext"]))
                tb["Pediatría"].append(c(d["Ped"]))
                tb["Gestión"].append(" / ".join(d["Gestion"]) if d["Gestion"] else "")
                tb["Otras Rotaciones"].append(" / ".join(d["Resi_Otros"]) if d["Resi_Otros"] else "")
                
                # Contador de No Disponibles
                total_aus = len(d["Ausentes"]) + len(bajas) + len([s for s in d.get("Saliente","").split(" / ") if s]) + len([s for s in d.get("Saliente_Resis","").split(" / ") if s])
                tb["No Disponibles Totales"].append(str(total_aus))

        df = pd.DataFrame(tb, index=cols).T
        
        # Eliminar filas completamente vacías
        for r in ["Guardia", "Guardia_Resis", "Saliente", "Sal_Resis", "Ausentes", "P Resi", "HD Res", "Cons Resi", "Diag Resi", "Banco Resi", "Gestión", "Otras Rotaciones", "No Disponibles Totales"]:
            if all(x == "" for x in df.loc[r]): df = df.drop(r)
        
        b = io.BytesIO()
        with pd.ExcelWriter(b, engine='xlsxwriter') as w: 
            df.to_excel(w, sheet_name='Semana')
            wb = w.book
            ws = w.sheets['Semana']
            
            # --- PALETA DE COLORES ---
            bg_planta = '#E2EFDA'      # Verde Planta
            bg_planta_r = '#F0F6EA'    # Verde Suave Resi
            bg_hd = '#DDEBF7'          # Azul HD
            bg_hd_r = '#EEF4FA'        # Azul Suave Resi
            bg_cons = '#FCE4D6'        # Naranja Cons
            bg_cons_r = '#FDF0E8'      # Naranja Suave Resi
            bg_tao = '#FFF2CC'         # Amarillo TAO/Coag
            bg_ped = '#FDE9D9'         # Rosa Suave Pediatria
            bg_lab = '#E4DFEC'         # Morado Lab
            bg_lab_r = '#F0EDF4'       # Morado Suave Resi
            bg_banco = '#F2DCDB'       # Rojo Banco
            bg_banco_r = '#F8EDED'     # Rojo Suave Resi
            bg_sur = '#FFF8DC'         # Dorado Claro Sur
            bg_ic = '#D1EEEE'          # Turquesa Interconsultas
            bg_def = '#FFFFFF'         # Blanco
            bg_idx = '#F2F2F2'         # Gris claro índices
            bg_total = '#595959'       # Gris Oscuro Totales
            
            def get_row_color(r):
                if r in ['P1', 'P2', 'P3']: return bg_planta
                if r == 'P Resi': return bg_planta_r
                if str(r).startswith('HD') and 'Res' not in r: return bg_hd
                if r == 'HD Res': return bg_hd_r
                if str(r).startswith('Cons') and 'Res' not in r: return bg_cons
                if r == 'Cons Resi': return bg_cons_r
                if r in ['Coagulación', 'TAO']: return bg_tao
                if r == 'Pediatría': return bg_ped
                if str(r).startswith('Diag') or str(r).startswith('Hem'): return bg_lab
                if r == 'Diag Resi': return bg_lab_r
                if str(r).startswith('Banco') and 'Res' not in r: return bg_banco
                if r == 'Banco Resi': return bg_banco_r
                if r == 'Sur': return bg_sur
                if str(r).startswith('IC '): return bg_ic
                if r == 'No Disponibles Totales': return bg_total
                return bg_def

            fmt_cabecera = wb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            fmt_cells = {}
            fmt_index = {}
            fmt_total_val = wb.add_format({'bold': True, 'bg_color': '#D9D9D9', 'font_color': '#C00000', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            
            # Formateo celdas vacías (rojo)
            fmt_vacio = wb.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            
            for r_idx, row_name in enumerate(df.index):
                c_bg = get_row_color(row_name)
                i_bg = bg_idx if c_bg == bg_def else c_bg
                
                # Excepción para la fila de totales
                if c_bg == bg_total:
                    i_bg_style = wb.add_format({'bold': True, 'valign': 'vcenter', 'align': 'left', 'border': 1, 'bg_color': bg_total, 'font_color': 'white'})
                elif i_bg not in fmt_index:
                    fmt_index[i_bg] = wb.add_format({'bold': True, 'valign': 'vcenter', 'align': 'left', 'border': 1, 'bg_color': i_bg})
                    i_bg_style = fmt_index[i_bg]
                else:
                    i_bg_style = fmt_index[i_bg]
                    
                if c_bg not in fmt_cells and c_bg != bg_total:
                    fmt_cells[c_bg] = wb.add_format({'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'border': 1, 'bg_color': c_bg})
                
                ws.write(r_idx + 1, 0, row_name, i_bg_style)
                
                for c_idx, val in enumerate(df.loc[row_name]):
                    s_val = str(val).strip() if pd.notna(val) else ""
                    
                    if row_name == 'No Disponibles Totales':
                        ws.write(r_idx + 1, c_idx + 1, s_val, fmt_total_val)
                    elif s_val == "" and row_name not in ["Guardia", "Guardia_Resis", "Saliente", "Sal_Resis", "Ausentes", "P Resi", "HD Res", "Cons Resi", "Diag Resi", "Banco Resi", "Otras Rotaciones", "Gestión"]:
                        # Celdas vacías en estructura crítica = ROJO
                        ws.write(r_idx + 1, c_idx + 1, s_val, fmt_vacio)
                    else:
                        # Borrar la palabra VACIO si existiera y dejar solo el color
                        if "VACÍO" in s_val: s_val = ""
                        ws.write(r_idx + 1, c_idx + 1, s_val, fmt_cells[c_bg])

            ws.set_column(0, 0, 20)
            ws.set_column(1, len(df.columns), 28)
            
            for col_num, value in enumerate(df.columns.values):
                ws.write(0, col_num + 1, value, fmt_cabecera)
            ws.write(0, 0, "", fmt_cabecera)
            
        st.table(df)
        
        c_down, c_mail = st.columns(2)
        with c_down:
            st.download_button("📥 Descargar Excel Semana", b.getvalue(), f"Sem_{lunes.strftime('%d%m')}.xlsx", "application/vnd.ms-excel")
        with c_mail:
            st.markdown("📩 Configura Streamlit Secrets para habilitar el envío automático por correo.")

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
