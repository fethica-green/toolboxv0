import os, sys, subprocess
import sqlite3
import streamlit as st
import pandas as pd
import datetime
from datetime import date, time
from io import BytesIO
from fpdf import FPDF
from PyPDF2 import PdfMerger
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import requests

# ──────────────────────────────────────────────────────────────────────────────
# Auto-install xlrd for Excel support
try:
    import xlrd
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "xlrd>=2.0.1"], check=True)
    import xlrd
# ──────────────────────────────────────────────────────────────────────────────

# --- Page config & CSS ---
st.set_page_config(page_title="MENA Team Logistics Toolbox", layout="wide")
st.markdown("""
<style>
  /* Move title below logo and enlarge */
  .header { flex-direction: column !important; align-items: center !important; }
  .header img { margin-bottom: 1rem; }
  .header .title { font-size: 5rem !important; text-align: center !important; }
</style>

</style>
""", unsafe_allow_html=True)

# --- Authentication ---
LOGIN, PASSWORD = "MTR", "MTR38"
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        if os.path.exists("hd_logo.png"):
            st.image("hd_logo.png", width=200)
        st.markdown("<div class='title'>🛫🧰 MENA Team Logistics Toolbox 🌍📦</div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        with st.form("login_form"):
            st.write("### 🔐 Please log in")
            user = st.text_input("Login")
            pwd  = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                if user==LOGIN and pwd==PASSWORD:
                    st.session_state.auth=True
                    st.success("✅ Logged in")
                else:
                    st.error("❌ Invalid credentials")
    st.stop()

# --- Helpers ---
def calculate_days(dep, ret):
    try: return max((ret-dep).days+1,1) if ret else 1
    except: return 1

def init_db(db="travel_records.db"):
    conn = sqlite3.connect(db, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
      CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        traveler TEXT, position TEXT, ta TEXT,
        project TEXT, fund TEXT, activity TEXT,
        budget_line TEXT, airfare_ticket REAL,
        change_fare REAL, final_fare REAL,
        airplus_invoice TEXT, eticket_number TEXT,
        itinerary TEXT, departure_date TEXT,
        return_date TEXT, travel_class TEXT,
        trip_type TEXT, co2_tons REAL,
        days_travelled INTEGER, booked_by TEXT,
        remarks TEXT, created_at TEXT
      )
    """)
    conn.commit()
    return conn

def backup_excel(conn, backup_dir="backups"):
    os.makedirs(backup_dir, exist_ok=True)
    today = date.today().isoformat()
    dest = os.path.join(backup_dir, f"travel_records_{today}.xlsx")
    if os.path.exists(dest): return
    df = pd.read_sql_query("SELECT * FROM records", conn)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, sheet_name="Records", index=False)
        wb, ws = w.book, w.sheets["Records"]
        fmt = wb.add_format({
            "bold":True, "text_wrap":True, "valign":"center",
            "fg_color":"#DC2626","color":"white","border":1
        })
        for i,col in enumerate(df.columns):
            ws.write(0, i, col, fmt)
            width = max(df[col].astype(str).map(len).max(), len(col)) + 2
            ws.set_column(i, i, width)
    with open(dest,"wb") as f:
        f.write(buf.getvalue())

# --- Amadeus flight lookup ---
CLIENT_ID     = "idd7hl95bnBrW4AR2gvyKwskc6GiKTep"
CLIENT_SECRET = "Wf6Lm0qOAxzhDavO"
def get_token():
    r = requests.post(
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        data={"grant_type":"client_credentials",
              "client_id":CLIENT_ID,
              "client_secret":CLIENT_SECRET}
    )
    return r.json().get("access_token")

def search_flights(o,d,dt,cls):
    tok = get_token()
    if not tok: return []
    r = requests.get(
        "https://test.api.amadeus.com/v2/shopping/flight-offers",
        headers={"Authorization":f"Bearer {tok}"},
        params={"originLocationCode":o,
                "destinationLocationCode":d,
                "departureDate":dt,
                "adults":1,
                "travelClass":cls,
                "max":10}
    )
    return r.json().get("data",[]) if r.status_code==200 else []

def show_flights(ofs):
    if not ofs:
        st.warning("No flights available.")
        return
    rows=[]
    for i,f in enumerate(ofs,1):
        seg = f["itineraries"][0]["segments"]
        bags = f["travelerPricings"][0]["fareDetailsBySegment"][0]\
                  .get("includedCheckedBags",{}).get("quantity",0)
        rows.append({
            "Option":i,
            "From":seg[0]["departure"]["iataCode"],
            "To":seg[-1]["arrival"]["iataCode"],
            "Depart":seg[0]["departure"]["at"],
            "Arrive":seg[-1]["arrival"]["at"],
            "Price (CHF)":float(f["price"]["total"]),
            "Refundable":f["pricingOptions"].get("refundable",False),
            "Bags":bags,
            "Stops":len(seg)-1})
    df=pd.DataFrame(rows)
    gb=GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=True)
    AgGrid(df,gridOptions=gb.build(),update_mode=GridUpdateMode.MODEL_CHANGED)
    buf=BytesIO(); df.to_excel(buf,index=False)
    st.download_button("⬇️ Export Flights",buf.getvalue(),"flights.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# --- HEADER ---
h1,h2,h3 = st.columns([1,6,1])
with h1:
    if os.path.exists("hd_logo.png"):
        st.image("hd_logo.png",width=200)
with h2:
    st.markdown("<div class='title'>🛫🧰 MENA Team Logistics Toolbox 🌍📦</div>", unsafe_allow_html=True)

# --- SIDEBAR: Mission vs Meeting ---
section = st.sidebar.radio(
    "🔹 Select Section",
    ["🚀 Mission","📅 Meeting"],
    index=0
)

# ──────────────────────────────────────────────────────────────────────────────
# MISSION
# ──────────────────────────────────────────────────────────────────────────────
def render_mission():
    st.header("01. Mission")
    tabs = st.tabs([
        "🛫 Flight Lookup",
        "🧾 Travel Authorization",
        "💼 DSA Declaration",
        "💳 Other Expenses",
        "🗄️ Travel Records"
    ])

    # Flight Lookup
    with tabs[0]:
        st.subheader("🔍 Flight Lookup")
        tp = st.radio("Trip Type",["One-way","Round-trip","Multi-destination"], key="flt_tp")
        cl = st.selectbox("Class",["ECONOMY","BUSINESS","FIRST"], key="flt_cl")
        d_only = st.checkbox("Direct only", key="flt_dir")
        r_only = st.checkbox("Refundable only", key="flt_ref")
        bag    = st.checkbox("Include baggage", key="flt_bag")
        if tp=="Multi-destination":
            o1=st.text_input("Seg1 From (IATA)",key="flt_o1"); d1=st.text_input("Seg1 To",key="flt_d1")
            dt1=st.date_input("Seg1 Date",key="flt_dt1")
            o2=st.text_input("Seg2 From (IATA)",key="flt_o2"); d2=st.text_input("Seg2 To",key="flt_d2")
            dt2=st.date_input("Seg2 Date",key="flt_dt2")
        else:
            o1=st.text_input("Origin IATA",key="flt_o"); d1=st.text_input("Destination IATA",key="flt_d")
            dt1=st.date_input("Depart on",date.today(),key="flt_dt"); dt2=None
            if tp=="Round-trip":
                dt2=st.date_input("Return on",date.today(),key="flt_rd")
        if st.button("Search Flights",key="flt_go"):
            if tp=="Multi-destination":
                show_flights(search_flights(o1,d1,str(dt1),cl))
                show_flights(search_flights(o2,d2,str(dt2),cl))
            else:
                offers = search_flights(o1,d1,str(dt1),cl)
                filt=[]
                for f in offers:
                    seg=f["itineraries"][0]["segments"]
                    if d_only and len(seg)>1: continue
                    if r_only and not f["pricingOptions"].get("refundable"): continue
                    if bag and f["travelerPricings"][0]["fareDetailsBySegment"][0]\
                              .get("includedCheckedBags",{}).get("quantity",0)==0: continue
                    filt.append(f)
                show_flights(filt)

    # Travel Authorization
    with tabs[1]:
        st.subheader("🧾 Travel Authorization")
        if "ta_list" not in st.session_state:
            st.session_state.ta_list=[]
        # auto-generate TA#
        nm = st.text_input("Traveler's Name", key="ta_nm")
        ta_no=""
        if nm:
            parts=nm.split()
            code=parts[0][0].upper()+ (parts[1][:2].upper() if len(parts)>1 else parts[0][1:3].upper())
            yy=datetime.datetime.now().year%100
            cnt=sum(1 for ta in st.session_state.ta_list if ta["Name"]==nm)+1
            ta_no=f"TA-{code}-{yy:02d}-{cnt:03d}"
        st.text_input("TA Number", value=ta_no, disabled=True, key="ta_no")
        tt = st.radio("Trip Type",["One-way","Round-trip","Multi-destination"], key="ta_tp")
        # project/fund/activity/budget
        p1,p2,p3,p4 = st.columns(4)
        proj = p1.text_input("Project Code", key="ta_proj")
        fund = p2.text_input("Fund Code", key="ta_fund")
        act  = p3.text_input("Activity Code", key="ta_act")
        bd   = p4.text_input("Budget Line", key="ta_bd")
        # Manager, Focal Point, Office
        m1,m2,m3 = st.columns(3)
        mgr = m1.text_input("Manager", key="ta_mgr")
        fp  = m2.text_input("Focal Point", key="ta_fp")
        ofc = m3.text_input("Office", key="ta_ofc")
        if st.button("✅ Save TA", key="ta_save"):
            st.session_state.ta_list.append({
                "Name":nm, "TA":ta_no,
                "Project":proj, "Fund":fund,
                "Activity":act, "Budget":bd,
                "Manager":mgr, "Focal Point":fp, "Office":ofc
            })
            st.success("Travel Authorization saved")
        if st.session_state.ta_list:
            df = pd.DataFrame(st.session_state.ta_list)
            st.data_editor(df, num_rows="dynamic")
            buf = BytesIO(); df.to_excel(buf,index=False)
            st.download_button("⬇️ Export Authorizations",buf.getvalue(),"tas.xlsx")

    # DSA Declaration
    with tabs[2]:
        st.subheader("💼 DSA Declaration")
        # load local file only
        if os.path.exists("Perdiem DSA 2025 par pays.xlsx"):
            tmp=pd.read_excel("Perdiem DSA 2025 par pays.xlsx",sheet_name="Feuil1",skiprows=4)
            tmp=tmp[['Country','Area','Full DSA.1','Lunch only.1','Dinner only.1']].dropna(subset=['Country'])
            tmp.columns=['Country','Area','Full_DSA','Lunch_Only','Dinner_Only']
            dsa_df=tmp
        else:
            st.error("DSA file missing"); return

        if "missions" not in st.session_state:
            st.session_state.missions=[]
        nm2=st.text_input("Traveler's Name", key="dsa_nm2")
        ta2=st.text_input("TA Number", key="dsa_ta2")
        country=st.selectbox("Country", sorted(dsa_df['Country']), key="dsa_ct2")
        city=st.selectbox("City", sorted(dsa_df[dsa_df['Country']==country]['Area']), key="dsa_city2")
        d1,t1 = st.columns(2)
        dep_d = d1.date_input("Dep Date", date.today(), key="dsa_dd2")
        dep_t = d1.time_input("Dep Time", time(8,0),      key="dsa_dt2")
        ret_d = t1.date_input("Ret Date", date.today(), key="dsa_rd2")
        ret_t = t1.time_input("Ret Time", time(20,0),    key="dsa_rt2")

        # Deductions
        dl,dm,dfc = st.columns(3)
        if 'ded_lunch' not in st.session_state: st.session_state.ded_lunch=0
        if 'ded_dinner' not in st.session_state: st.session_state.ded_dinner=0
        if 'ded_full'   not in st.session_state: st.session_state.ded_full=0
        with dl:
            st.write(f"Lunch Ded: {st.session_state.ded_lunch}")
            if st.button("+ Lunch", key="dsa_al2"): st.session_state.ded_lunch+=1
            if st.button("- Lunch", key="dsa_sl2") and st.session_state.ded_lunch>0: st.session_state.ded_lunch-=1
        with dm:
            st.write(f"Dinner Ded: {st.session_state.ded_dinner}")
            if st.button("+ Dinner", key="dsa_ad2"): st.session_state.ded_dinner+=1
            if st.button("- Dinner", key="dsa_sd2") and st.session_state.ded_dinner>0: st.session_state.ded_dinner-=1
        with dfc:
            st.write(f"Full Ded: {st.session_state.ded_full}")
            if st.button("+ Full", key="dsa_af2"): st.session_state.ded_full+=1
            if st.button("- Full", key="dsa_sf2") and st.session_state.ded_full>0: st.session_state.ded_full-=1

        receipts = st.file_uploader(
            "Upload receipts (pdf,jpg,png,msg,eml)",
            type=['pdf','jpg','jpeg','png','msg','eml'],
            accept_multiple_files=True,
            key="dsa_recv2"
        )
        if st.button("✅ Save Mission", key="dsa_save2"):
            taux = dsa_df[(dsa_df['Country']==country)&(dsa_df['Area']==city)].iloc[0]
            full,lun,din = map(float, (taux['Full_DSA'], taux['Lunch_Only'], taux['Dinner_Only']))
            dt_dep = datetime.datetime.combine(dep_d, dep_t)
            dt_ret = datetime.datetime.combine(ret_d, ret_t)
            days = (dt_ret.date()-dt_dep.date()).days+1
            d_dep = full if dep_t<time(10,0) else (din if dep_t<=time(14,0) else 0)
            d_ret = full if ret_t>time(19,0) else (lun if ret_t>=time(13,0) else 0)
            mid   = max(days-2,0)
            tot   = d_dep + d_ret + mid*full
            ded   = st.session_state.ded_lunch*lun + st.session_state.ded_dinner*din + st.session_state.ded_full*full
            final = tot - ded
            st.session_state.missions.append({
                "Name":nm2, "TA":ta2,
                "Country":country, "City":city,
                "Days":days, "Total DSA":final,
                "Attachments":len(receipts or [])
            })
            st.success("DSA mission saved.")
        if st.session_state.missions:
            dfm = pd.DataFrame(st.session_state.missions)
            st.data_editor(dfm, num_rows="dynamic")
            buf = BytesIO(); dfm.to_excel(buf,index=False)
            st.download_button("⬇️ Export Missions",buf.getvalue(),"dsa_missions.xlsx")

    # Other Expenses
    with tabs[3]:
        st.subheader("💳 Other Expenses")
        if 'expenses' not in st.session_state: st.session_state.expenses=[]
        if 'exp_files' not in st.session_state: st.session_state.exp_files={}

        # Traveler’s Name, TA Number, Submission Date
        c1,c2,c3 = st.columns(3)
        traveler = c1.text_input("Traveler's Name", key="exp_trav2")
        ta_num   = c2.text_input("TA Number", key="exp_ta2b")
        sub_date = c3.date_input("Submission Date", date.today(), key="exp_sub2")

        # then existing fields
        e1,e2,e3 = st.columns(3)
        office    = e1.selectbox("Office", ["Geneva","Tunis","Beirut","Amman","Cairo","Other"], key="exp_off2")
        codes     = {"Consultancy fee":"60100","Taxi Fare":"62000","Room fees":"63000","Other":"60990"}
        category  = e2.selectbox("Category", list(codes.keys()), key="exp_cat2b")
        acct_code = codes[category]
        e2.markdown(f"📘 Code: **{acct_code}**")
        desc      = e3.text_input("Description", key="exp_desc2b")

        p4,f4,a4 = st.columns(3)
        proj      = p4.text_input("Project Code",  key="exp_pj2b")
        fund      = f4.text_input("Fund Code",     key="exp_fd2b")
        act       = a4.text_input("Activity Code", key="exp_ac2b")
        bd        = st.text_input("Budget Line",   key="exp_bd2b")

        cur  = st.selectbox("Currency", ["CHF","EUR","USD"], key="exp_cur2b")
        amt  = st.number_input("Amount", min_value=0.0, key="exp_amt2b")
        rate = st.number_input("Exchange Rate", value=1.0, key="exp_rate2b")
        chf  = round(amt*rate,2)
        st.markdown(f"💰 In CHF: **{chf}**")

        ups = st.file_uploader(
            "Upload receipts (pdf,jpg,png,msg,eml)",
            type=['pdf','jpg','jpeg','png','msg','eml'],
            accept_multiple_files=True,
            key="exp_up2b"
        )
        if ups:
            st.session_state.exp_files[len(st.session_state.expenses)] = [(f.name,f.getvalue()) for f in ups]
            st.success(f"{len(ups)} file(s) attached.")

        if st.button("➕ Add Entry", key="exp_add2b"):
            st.session_state.expenses.append({
                "Traveler":   traveler,
                "TA Number":  ta_num,
                "Submission": sub_date,
                "Office":     office,
                "Category":   category,
                "Code":       acct_code,
                "Description":desc,
                "Project":    proj,
                "Fund":       fund,
                "Activity":   act,
                "Budget Line":bd,
                "Currency":   cur,
                "Amount":     amt,
                "Rate":       rate,
                "CHF":        chf,
                "Files":      "; ".join(n for n,_ in st.session_state.exp_files.get(len(st.session_state.expenses),[]))
            })
            st.success("Expense added.")
        if st.session_state.expenses:
            dfe = pd.DataFrame(st.session_state.expenses)
            st.data_editor(dfe, num_rows="dynamic")
            buf = BytesIO(); dfe.to_excel(buf,index=False)
            st.download_button("⬇️ Export Expenses",buf.getvalue(),"expenses.xlsx")

    # Travel Records
    with tabs[4]:
        st.subheader("🗄️ Travel Records")
        conn = init_db(); backup_excel(conn)
        s1,s2,s3 = st.tabs(["📝 New Trip","📊 Records","📈 Dashboard"])
        with s1:
            st.write("**Record a New Trip**")
            a1,a2,a3=st.columns(3)
            tr=a1.text_input("Traveler",key="rec_tr2")
            ps=a2.selectbox("Position",["Staff","Consultant","Guest"],key="rec_pos2")
            tn=a3.text_input("TA Number",key="rec_ta3b")
            it=st.text_input("Itinerary",key="rec_it2b")
            dp=st.date_input("Depart",date.today(),key="rec_dp2b")
            rt=st.date_input("Return",date.today(),key="rec_rt2b")
            cls=st.selectbox("Class",["Economy","Business"],key="rec_cls2b")
            fare=st.number_input("Fare (CHF)",min_value=0.0,key="rec_fare2b")
            if st.button("Save Trip",key="rec_save2b"):
                conn.execute("""
                  INSERT INTO records (
                    traveler,position,ta,itinerary,departure_date,return_date,
                    travel_class,final_fare,created_at
                  ) VALUES (?,?,?,?,?,?,?,?,?)
                """,(
                    tr,ps,tn,it,dp.isoformat(),rt.isoformat(),
                    cls,fare,datetime.datetime.now().isoformat()
                ))
                conn.commit(); st.success("Trip saved")
        with s2:
            df=pd.read_sql_query("SELECT * FROM records ORDER BY id DESC",conn)
            if df.empty:
                st.info("No records.")
            else:
                st.data_editor(df, num_rows="dynamic")
                buf=BytesIO(); df.to_excel(buf,index=False)
                st.download_button("⬇️ Export Records",buf.getvalue(),"records.xlsx")
        with s3:
            df=pd.read_sql_query("SELECT * FROM records",conn)
            st.metric("Total Trips",len(df))

# ──────────────────────────────────────────────────────────────────────────────
# MEETING
# ──────────────────────────────────────────────────────────────────────────────
def render_meeting():
    import pandas as pd
    from io import BytesIO

    st.header("02. Meeting")

    tabs = st.tabs([
        "📝 Meeting Form",
        "📈 Effective Cost",
        "📋 Meeting List",
        "🛒 PO Follow-up"
    ])

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 1: Meeting Form
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[0]:
        st.subheader("Meeting Form")

        # --- Metadata form ---
        with st.form("meeting_meta"):
            c1, c2, c3 = st.columns([3, 2, 3])
            meeting_name = c1.text_input("Event Name", placeholder="e.g. MF08 NARD meeting in Glion 06–07 MAY")
            mf_number    = c2.text_input("MF #",       placeholder="e.g. MF-NARD-25-008")
            meeting_loc  = c3.text_input("Location",   placeholder="e.g. Glion")

            c4, c5, c6 = st.columns(3)
            proj_code    = c4.text_input("Project Code", placeholder="e.g. NARD")
            fund_code    = c5.text_input("Fund Code",    placeholder="e.g. CHE150")
            manual_pax   = c6.number_input("Number of Pax", min_value=1, value=1)

            if st.form_submit_button("✔ Save Meeting Details"):
                st.session_state._meeting_meta = {
                    "Event Name": meeting_name,
                    "MF #":       mf_number,
                    "Location":   meeting_loc,
                    "Project":    proj_code,
                    "Fund":       fund_code,
                    "Manual Pax": manual_pax
                }
                st.success("Meeting details saved.")

        meta = st.session_state.get("_meeting_meta", {})

        # --- Participants & auto pax count ---
        parts_text = st.text_area("List of Participants (one per line)", height=150)
        participants = [p.strip() for p in parts_text.splitlines() if p.strip()]
        computed_pax = len(participants)
        st.markdown(f"**Computed Pax:** {computed_pax}")
        num_pax = computed_pax or meta.get("Manual Pax", 1)

        total_meeting = 0.0

        # --- Flight International ---
        st.markdown("### Flight Intl")
        f1, f2, f3, f4 = st.columns([2, 1, 1, 4])
        fi_cur = f1.selectbox("Currency", ["CHF","EUR","USD"], key="fi_cur")
        fi_pp  = f2.number_input("Amt/Pax", min_value=0.0, key="fi_pp")
        fi_tot = fi_pp * num_pax
        f3.metric("Total", f"{fi_tot:,.2f} {fi_cur}")
        fi_det = f4.text_input("Details", key="fi_det")
        total_meeting += fi_tot

        # --- Reimbursement (same form) ---
        st.markdown("### Reimbursement")
        r1, r2, r3, r4 = st.columns([2,1,1,4])
        r_cur = r1.selectbox("Currency", ["CHF","EUR","USD"], key="r_cur")
        r_pp  = r2.number_input("Amt/Pax", min_value=0.0, key="r_pp")
        r_tot = r_pp * num_pax
        r1.metric("Total", f"{r_tot:,.2f} {r_cur}")
        r_det = r4.text_input("Details", key="r_det")
        total_meeting += r_tot

        # --- Audio Equipment (same form) ---
        st.markdown("### Audio Equipment")
        a1, a2, a3, a4 = st.columns([2,1,1,4])
        ae_cur = a1.selectbox("Currency", ["CHF","EUR","USD"], key="ae_cur")
        ae_pp  = a2.number_input("Amt/Pax", min_value=0.0, key="ae_pp")
        ae_tot = ae_pp * num_pax
        a1.metric("Total", f"{ae_tot:,.2f} {ae_cur}")
        ae_det = a4.text_input("Details", key="ae_det")
        total_meeting += ae_tot

        # --- Expenses – Subject to PO ---
        st.markdown("### Expenses – Subject to PO")
        # Hotel
        h1, h2, h3, h4 = st.columns([2,1,1,4])
        hotel_cur = h1.selectbox("Hotel – Currency", ["CHF","EUR","USD"], key="hotel_cur")
        hotel_pp  = h2.number_input("Amt/Pax", min_value=0.0, key="hotel_pp")
        hotel_tot = hotel_pp * num_pax
        h3.metric("Total", f"{hotel_tot:,.2f} {hotel_cur}")
        hotel_det = h4.text_input("Details", key="hotel_det")
        total_meeting += hotel_tot

        # Catering
        c1, c2, c3, c4 = st.columns([2,1,1,4])
        cat_cur = c1.selectbox("Catering – Currency", ["CHF","EUR","USD"], key="cat_cur")
        cat_pp  = c2.number_input("Amt/Pax", min_value=0.0, key="cat_pp")
        cat_tot = cat_pp * num_pax
        c3.metric("Total", f"{cat_tot:,.2f} {cat_cur}")
        cat_det = c4.text_input("Details", key="cat_det")
        total_meeting += cat_tot

        # Ground Transportation
        g1, g2, g3, g4 = st.columns([1,1,1,4])
        gt_transfers = g1.number_input("# Transfers", min_value=0, step=1, key="gt_tr")
        gt_cur       = g2.selectbox("Currency", ["CHF","EUR","USD"], key="gt_cur")
        gt_pp        = g3.number_input("Amt/Transfer", min_value=0.0, key="gt_pp")
        gt_tot       = gt_transfers * gt_pp
        g3.metric("Total", f"{gt_tot:,.2f} {gt_cur}")
        gt_det       = g4.text_input("Details", key="gt_det")
        total_meeting += gt_tot

        # --- Additional Expenses dynamic ---
        st.markdown("### Other Expenses")
        if "other_expenses" not in st.session_state:
            st.session_state.other_expenses = []
        oe1, oe2, oe3, oe4 = st.columns([3,1,1,4])
        oe_name = oe1.text_input("Expense", key="oe_name")
        oe_cur  = oe2.selectbox("", ["CHF","EUR","USD"], key="oe_cur", label_visibility="collapsed")
        oe_amt  = oe3.number_input("", min_value=0.0, key="oe_amt", label_visibility="collapsed")
        oe_det  = oe4.text_input("", key="oe_det", label_visibility="collapsed")
        if st.button("➕ Add Other Expense"):
            st.session_state.other_expenses.append({
                "Expense": oe_name,
                "Currency": oe_cur,
                "Amount": oe_amt,
                "Details": oe_det
            })
            st.success("Other expense added.")
        if st.session_state.other_expenses:
            df_oe = pd.DataFrame(st.session_state.other_expenses)
            st.data_editor(df_oe, num_rows="dynamic")
            oe_total = df_oe["Amount"].sum()
            total_meeting += oe_total

        # --- Total Meeting Authorisation ---
        st.markdown("---")
        st.markdown(f"## 🧾 Total Meeting Authorisation: {total_meeting:,.2f} CHF")

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 2: Effective Cost (manual zeros)
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[1]:
        st.subheader("📈 Effective Cost")
        total_eff = 0.0
        components = [
            ("Flights", "eff_flights"),
            ("Hotel",   "eff_hotel"),
            ("Ground Transportation", "eff_gt"),
            ("DSA",     "eff_dsa"),
            ("Catering","eff_cat"),
            ("Audio Equipment","eff_ae")
        ]
        for label, key in components:
            c1, c2 = st.columns([3,1])
            with c1:
                st.selectbox(f"{label} – Currency", ["CHF","EUR","USD"], key=f"{key}_cur")
            with c2:
                amt = st.number_input(f"{label} – Total Amount", min_value=0.0, value=0.0, key=f"{key}_amt")
            total_eff += amt
            st.write("")
        st.markdown("---")
        st.markdown(f"## 💰 Total Effective Meeting Cost: {total_eff:,.2f} CHF")

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 3: Meeting List
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[2]:
        st.subheader("📋 Meeting List")
        dfm = pd.DataFrame(st.session_state.get("meetings", []))
        if dfm.empty:
            st.info("No meetings saved yet.")
        else:
            st.data_editor(dfm, num_rows="dynamic")

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 4: PO Follow-up
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[3]:
        st.subheader("🛒 Purchase Order Follow-up")
        if "po" not in st.session_state:
            st.session_state.po = []
        last_mf = st.session_state.get("meetings", [{}])[-1].get("MF #", "")
        po_no = st.text_input("PO Number", key="po_no_mtg")
        po_dt = st.date_input("Order Date", date.today(), key="po_date_mtg")
        status= st.selectbox("Status", ["Open","In Progress","Closed"], key="po_status_mtg")
        if st.button("💾 Save PO Follow-up"):
            st.session_state.po.append({
                "MF #": last_mf,
                "PO": po_no,
                "Date": str(po_dt),
                "Status": status
            })
            st.success("PO follow-up saved.")
        dfp = pd.DataFrame(st.session_state.po)
        if not dfp.empty:
            st.data_editor(dfp, num_rows="dynamic")



# ──────────────────────────────────────────────────────────────────────────────
# Dispatch
if section.startswith("🚀"):
    render_mission()
else:
    render_meeting()

st.markdown("<div style='text-align:center;color:gray;margin-top:2rem;'>© All rights reserved MTR</div>", unsafe_allow_html=True)
