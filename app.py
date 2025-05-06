######################################### LIBRERIAS ############################################

import os
import json
import boto3
import pandas as pd
from google.oauth2 import service_account   
from googleapiclient.discovery import build
from matplotlib.colors import to_rgb, to_hex
from flask import Flask, request, render_template

######################################## CREDENCIALES ###########################################

S3_SA_KEY              = os.getenv("S3_SA_KEY")
SHEET_ID               = os.getenv("SHEET_ID")
SCOPES                 = os.getenv("SCOPES").split(",")
S3_BUCKET              = os.getenv("S3_BUCKET")
AWS_ACCESS_KEY         = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY         = os.getenv("AWS_SECRET_KEY")

####################################### CLIENTE DE AWS ##########################################

s3 = boto3.client("s3",aws_access_key_id=AWS_ACCESS_KEY,aws_secret_access_key=AWS_SECRET_KEY)

#################################### ACCEDER A GOOGLE SHEETS ####################################

def get_service_account_credentials():
    """Carga la clave de la cuenta de servicio desde S3 y devuelve un objeto Credentials."""
    obj      = s3.get_object(Bucket=S3_BUCKET, Key=S3_SA_KEY)
    sa_info  = json.loads(obj["Body"].read().decode())
    creds_sa = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return creds_sa

def build_sheets_service():
    creds = get_service_account_credentials()
    return build("sheets", "v4", credentials=creds)

def fetch_sheet_data(service, sheet_name):
    rng  = f"{sheet_name}!A1:Z1000"
    vals = (service.spreadsheets().values()
            .get(spreadsheetId=SHEET_ID, range=rng)
            .execute()
            .get("values", []))

    if len(vals) < 2:
        return pd.DataFrame()

    raw_headers = vals[1]
    headers     = [str(h).strip() for h in raw_headers]
    data_rows   = vals[2:]
    max_cols    = max(len(headers), *(len(r) for r in data_rows)) if data_rows else len(headers)
    if len(headers) < max_cols:
        headers += [f"Col_{i}" for i in range(len(headers)+1, max_cols+1)]
    padded = [row + [None]*(max_cols - len(row)) for row in data_rows]
    return pd.DataFrame(padded, columns=headers)

######################################### OBTENIENDO LA DATA ####################################

service = build_sheets_service()
DF_NAMES = ["BanCoppel", "DiDi", "AutoAvanza", "UltraDinero", "FMP", "General"]
dfs = {name: fetch_sheet_data(service, name) for name in DF_NAMES}

app = Flask(__name__)

############################################## APP ###############################################

@app.route("/", methods=["GET"])
def index():
    selected_df = request.args.get("df", DF_NAMES[0])
    start_month = request.args.get("start_date", "")
    end_month   = request.args.get("end_date", "")

    #service = build_sheets_service()                                     # IF YOU WANT IT LIVE       
    #df      = fetch_sheet_data(service, selected_df)                     # IF YOU WANT IT LIVE       
    #dfs = {name: fetch_sheet_data(service, name) for name in DF_NAMES}   # IF YOU WANT IT LIVE       
    df = dfs[selected_df].copy()                                          # IF YOU WANT IT TO REVIVE
    
    ######################################## KPIs y GRAFICAS ########################################
    
    # KPIs - INGRESOS, COSTO TOTAL y UTILIDAD
    df["Marca_Temporal"] = pd.to_datetime(df["Marca_Temporal"].astype(str),format="%Y-%m",errors="coerce")
    df["Factura"] = (df["Factura"].astype(str).str.replace(r"[^\d\.]", "", regex=True).replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0))
    df["Total"] = (df["Total"].astype(str).str.replace(r"[^\d\.]", "", regex=True).replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0))
    mask = pd.Series(True, index=df.index)
    
    if start_month:
        inicio = pd.to_datetime(start_month + "-01", format="%Y-%m-%d")
        mask &= df["Marca_Temporal"] >= inicio
    if end_month:
        fin = pd.to_datetime(end_month + "-01", format="%Y-%m-%d")
        mask &= df["Marca_Temporal"] <= fin
    df = df[mask]

    valor_kpi = df["Factura"].cumsum().iloc[-1] if not df.empty else 0
    costo_total = df["Total"].cumsum().iloc[-1] if not df.empty else 0 
    utilidad = valor_kpi - costo_total 
    
    #################################################################################################
    
    # KPI - RENTABILIDAD
    df["Rentabilidad"] = (df["Rentabilidad"].astype(str).str.replace(r"[^\d\.]", "", regex=True).replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0))
    df_grouped = (df.groupby(df["Marca_Temporal"].dt.to_period("M")).agg({"Rentabilidad": "mean"}).reset_index())
    df_grouped["Marca_Temporal"] = df_grouped["Marca_Temporal"].dt.to_timestamp()
    
    rentabilidad_labels = df_grouped["Marca_Temporal"].dt.strftime("%Y-%m").tolist()
    rentabilidad_values = df_grouped["Rentabilidad"].round(2).tolist()
    rentabilidad_pct = df_grouped["Rentabilidad"].mean() if not df_grouped.empty else 0
    
    #################################################################################################
    
    # KPI - COSTO POR 1 PESO
    df["Costo_por_1_peso"] = (df["Costo_por_1_peso"].astype(str).str.replace(r"[^\d\.]", "", regex=True).replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0))
    df_costo_grouped = (df.groupby(df["Marca_Temporal"].dt.to_period("M")).agg({"Costo_por_1_peso": "mean"}).reset_index())
    df_costo_grouped["Marca_Temporal"] = df_costo_grouped["Marca_Temporal"].dt.to_timestamp()
    costo_por_1_promedio = df_costo_grouped["Costo_por_1_peso"].mean() if not df_costo_grouped.empty else 0
    
    costo_labels = df_costo_grouped["Marca_Temporal"].dt.strftime("%Y-%m").tolist()
    costo_values = df_costo_grouped["Costo_por_1_peso"].round(4).tolist()

    #################################################################################################

    # KPI - STAFF
    df["Staff_Supervisores"] = (df["Staff_Supervisores"].astype(str).str.replace(r"[^\d]", "", regex=True).replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0))
    df["Staff_Asesores"] = (df["Staff_Asesores"].astype(str).str.replace(r"[^\d]", "", regex=True).replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0))
    df_staff_grouped = (df.groupby(df["Marca_Temporal"].dt.to_period("M")).agg({"Staff_Supervisores": "sum","Staff_Asesores": "sum"}).reset_index())
    df_staff_grouped["Marca_Temporal"] = df_staff_grouped["Marca_Temporal"].dt.to_timestamp()

    df_staff_grouped["Staff_Total"] = df_staff_grouped["Staff_Supervisores"] + df_staff_grouped["Staff_Asesores"]
    staff_total_acumulado = df_staff_grouped["Staff_Total"].sum() if not df_staff_grouped.empty else 0
    
    staff_labels = df_staff_grouped["Marca_Temporal"].dt.strftime("%Y-%m").tolist()
    staff_supervisores_values = df_staff_grouped["Staff_Supervisores"].tolist()
    staff_asesores_values = df_staff_grouped["Staff_Asesores"].tolist()

    #################################################################################################

    # GRAFICA - INGRESOS, COSTO TOTAL y UTILIDAD
    df_main_grouped = (df.groupby(df["Marca_Temporal"].dt.to_period("M")).agg({"Factura": "sum","Total": "sum"}).reset_index())
    df_main_grouped["Marca_Temporal"] = df_main_grouped["Marca_Temporal"].dt.to_timestamp()
    df_main_grouped["Utilidad"] = df_main_grouped["Factura"] - df_main_grouped["Total"]

    main_labels = df_main_grouped["Marca_Temporal"].dt.strftime("%Y-%m").tolist()
    ingresos_values = df_main_grouped["Factura"].round(2).tolist()
    costos_values = df_main_grouped["Total"].round(2).tolist()
    utilidad_values = df_main_grouped["Utilidad"].round(2).tolist()
    
    ##################################################################################################
    
    # PIE CHART – DISTRIBUCION DE COSTOS
    cols_masivos  = ["WA", "SIMs", "Blaster", "Predictivo", "Manual"]
    cols_personal = ["Sueldo_Supervisores", "Sueldo_Asesores",
                    "Costo_Social_Supervisores", "Costo_Social_Asesores"]
    cols_computo  = ["CRM", "Computadoras", "Email", "Software"]
    cols_varios   = ["Oficinas", "Penalizaciones", "Pagos_Propios", "Sueldo_Estructura"]
    all_cost_cols = cols_masivos + cols_personal + cols_computo + cols_varios
    
    for col in all_cost_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(r"[^\d\.]", "", regex=True)
                .replace("", "0")
                .pipe(pd.to_numeric, errors="coerce")
                .fillna(0)
            )
            
    totales = {
        "Masivos":  df[cols_masivos].sum().sum(),
        "Personal": df[cols_personal].sum().sum(),
        "Computo":  df[cols_computo].sum().sum(),
        "Varios":   df[cols_varios].sum().sum()
    }
    pie_labels, pie_values = zip(
        *sorted(totales.items(), key=lambda x: x[1], reverse=True)
    )
    
    pie_base_color = "#1B59F8" 
    pie_max_mix    = 0.60
    
    ###################################################################################################
    
    # SANKEY CHART - FLUJO DE COSTOS
    mapping = {
        "WA": "Masivos", "SIMs": "Masivos", "Blaster": "Masivos",
        "Predictivo": "Masivos", "Manual": "Masivos",
        "Sueldo_Supervisores": "Personal", "Sueldo_Asesores": "Personal",
        "Costo_Social_Supervisores": "Personal", "Costo_Social_Asesores": "Personal",
        "CRM": "Cómputo", "Computadoras": "Cómputo",
        "Email": "Cómputo", "Software": "Cómputo",
        "Oficinas": "Varios", "Penalizaciones": "Varios", "Pagos_Propios": "Varios", "Sueldo_Estructura": "Varios"
    }

    subcats    = list(mapping.keys())
    categories = ["Masivos", "Personal", "Cómputo", "Varios"]
    sink_node  = ["Costo total"]
    nodes      = subcats + categories + sink_node
    idx        = {n: i for i, n in enumerate(nodes)}

    subcat_totals = df[subcats].fillna(0).sum()

    cat_totals = {cat: 0 for cat in categories}
    for s, v in subcat_totals.items():
        cat_totals[mapping[s]] += v

    sources, targets, values, link_colors = [], [], [], []

    for s in subcats:
        sources.append(idx[s])
        targets.append(idx[mapping[s]])
        values.append(subcat_totals[s])

    for c in categories:
        sources.append(idx[c])
        targets.append(idx["Costo total"])
        values.append(cat_totals[c])
        
    custom_colors = ['#f211b5', '#1b59f8', '#ffa600', '#ff4e5b']
    cat_color_levels = {cat: to_rgb(color) for cat, color in zip(categories, custom_colors)}
    node_colors = []
    
    for n in nodes:
        if n in subcats:
            node_colors.append(to_hex(cat_color_levels[mapping[n]]))
        elif n in categories:
            node_colors.append(to_hex(cat_color_levels[n]))
        else:
            node_colors.append("#0b1f46")

    link_colors = []
    for s in sources:
        r, g, b = to_rgb(node_colors[s])
        link_colors.append(f"rgba({r*255:.0f},{g*255:.0f},{b*255:.0f},0.6)")

    sankey_kwargs = dict(
        sankey_nodes       = nodes,
        sankey_sources     = sources,
        sankey_targets     = targets,
        sankey_values      = values,
        sankey_node_colors = node_colors,
        sankey_link_colors = link_colors,
    )
    
    ########################################## COMPARATIVO DE CAMPAÑAS ##############################################

    # GRAFICA BURBUJA MULTIVARIABLE
    cols_masivos = ["WA", "SIMs", "Blaster", "Predictivo", "Manual"]        
    bubble_labels, bubble_x, bubble_y, bubble_utilidad = [], [], [], []

    for camp, df_camp in dfs.items():
        if camp == "General":
            continue
        df_tmp = df_camp.copy()

        df_tmp["Marca_Temporal"] = pd.to_datetime(
            df_tmp["Marca_Temporal"].astype(str), format="%Y-%m", errors="coerce"
        )
        mask_tmp = pd.Series(True, index=df_tmp.index)
        if start_month:
            mask_tmp &= df_tmp["Marca_Temporal"] >= inicio
        if end_month:
            mask_tmp &= df_tmp["Marca_Temporal"] <= fin
        df_tmp = df_tmp[mask_tmp]

        df_tmp["Rentabilidad"] = (
            df_tmp["Rentabilidad"]
            .astype(str).str.replace(r"[^\d\.]", "", regex=True)
            .replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0)
        )
        for col in ["Factura", "Total", *cols_masivos]:
            if col in df_tmp.columns:
                df_tmp[col] = (
                    df_tmp[col].astype(str).str.replace(r"[^\d\.]", "", regex=True)
                    .replace("", "0").pipe(pd.to_numeric, errors="coerce").fillna(0)
                )

        rentabilidad_prom = df_tmp["Rentabilidad"].mean() if not df_tmp.empty else 0
        masivos_total     = df_tmp[cols_masivos].sum().sum()      
        utilidad_total    = df_tmp["Factura"].sum() - df_tmp["Total"].sum()   

        bubble_labels.append(camp)
        bubble_x.append(round(rentabilidad_prom, 2))
        bubble_y.append(round(masivos_total, 2))
        bubble_utilidad.append(round(utilidad_total, 2))
        
    ###########################################################################################
    
    # STEAMGRAPH - EVOLUCIÓN DE COSTOS
    steam_series  = {}
    all_months    = set()

    for camp, df_camp in dfs.items():
        if camp == "General":
            continue

        df_tmp = df_camp.copy()
        df_tmp["Marca_Temporal"] = pd.to_datetime(
            df_tmp["Marca_Temporal"].astype(str), format="%Y-%m", errors="coerce"
        )

        mask_tmp = pd.Series(True, index=df_tmp.index)
        if start_month:
            mask_tmp &= df_tmp["Marca_Temporal"] >= inicio
        if end_month:
            mask_tmp &= df_tmp["Marca_Temporal"] <= fin
        df_tmp = df_tmp[mask_tmp]

        df_tmp["Total"] = (
            df_tmp["Total"].astype(str)
                .str.replace(r"[^\d\.]", "", regex=True)
                .replace("", "0")
                .pipe(pd.to_numeric, errors="coerce")
                .fillna(0)
        )

        serie = df_tmp.groupby(df_tmp["Marca_Temporal"].dt.to_period("M"))["Total"].sum()
        steam_series[camp] = serie
        all_months.update(serie.index)

    steam_labels     = sorted(all_months)                                   
    steam_labels_fmt = [p.to_timestamp().strftime("%Y-%m") for p in steam_labels]
    steam_names = sorted(steam_series.keys())                            
    steam_data  = [
        [ round(steam_series[c].get(mes, 0), 2) for mes in steam_labels ]  
        for c in steam_names
    ]

########################## MESES DISPONIBLES PARA LOS PICKERS ############################

    orig_df = dfs[selected_df].copy()
    orig_df["Marca_Temporal"] = pd.to_datetime(
        orig_df["Marca_Temporal"].astype(str), format="%Y-%m", errors="coerce"
    )
    available_months = sorted(
        orig_df["Marca_Temporal"]
              .dropna()
              .dt.strftime("%Y-%m")
              .unique()
    )
    
#################################################################################################

    return render_template(
        "dashboard.html",
        df_names=DF_NAMES,
        selected_df=selected_df,
        start_month=start_month,
        end_month=end_month,
        valor_kpi=valor_kpi,
        costo_total=costo_total,
        utilidad=utilidad,
        rentabilidad_pct=rentabilidad_pct,
        rentabilidad_labels=rentabilidad_labels,
        rentabilidad_values=rentabilidad_values,
        rentabilidad_avg_line=round(rentabilidad_pct, 2),
        costo_por_1_promedio=costo_por_1_promedio,
        costo_labels=costo_labels,
        costo_values=costo_values,
        staff_total_acumulado=staff_total_acumulado,
        staff_labels=staff_labels,
        staff_supervisores_values=staff_supervisores_values,
        staff_asesores_values=staff_asesores_values,
        main_labels=main_labels,
        ingresos_values=ingresos_values,
        costos_values=costos_values,
        utilidad_values=utilidad_values,
        pie_labels = pie_labels,
        pie_values = pie_values,
        pie_base_color = pie_base_color,
        pie_max_mix = pie_max_mix,
        **sankey_kwargs,
        bubble_labels=bubble_labels,
        bubble_x=bubble_x,
        bubble_y=bubble_y,
        bubble_utilidad=bubble_utilidad,
        steam_labels=steam_labels_fmt,
        steam_names=steam_names,
        steam_data=steam_data,
        available_months=available_months,
)
