import streamlit as st
import pandas as pd
import pdfplumber
from io import BytesIO
import re
import plotly.express as px

# --- PAGE SETTINGS ---
st.set_page_config(page_title="Invoice Analyzer Pro v2.0", layout="wide")
st.title("📄 Invoice Analyzer Pro – Smart Discount & Rate Calculator")

st.markdown("""
### ⚙️ Features
- Upload **any PDF invoice**
- Auto-extract **Item Name, Price, Paid Qty, Free Qty**
- Choose your **Discount %**
- Calculates:
  - ✅ Discounted Unit Price  
  - ✅ Effective Rate  
  - ✅ Total Quantity  
- Search, visualize & export your data
""")

# --- SIDEBAR HISTORY ---
if "discount_history" not in st.session_state:
    st.session_state["discount_history"] = []

discount_percent = st.sidebar.number_input("💰 Discount Percentage", min_value=0.0, max_value=100.0, value=13.0, step=0.5)
if discount_percent not in st.session_state["discount_history"]:
    st.session_state["discount_history"].insert(0, discount_percent)
    if len(st.session_state["discount_history"]) > 5:
        st.session_state["discount_history"].pop()

st.sidebar.markdown("### 🕓 Recent Discounts")
for d in st.session_state["discount_history"]:
    st.sidebar.write(f"{d}%")

discount_multiplier = (100 - discount_percent) / 100

# --- FILE UPLOAD ---
uploaded_file = st.file_uploader("📤 Upload PDF Invoice", type=["pdf"])

def clean_number(x):
    if isinstance(x, str):
        x = re.sub(r"[^\d.]", "", x)
    try:
        return float(x)
    except:
        return 0

if uploaded_file:
    try:
        st.info("🔍 Extracting data from your PDF... Please wait.")
        df_list = []

        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    df_list.append(pd.DataFrame(table[1:], columns=table[0]))

        if not df_list:
            st.error("❌ No table found. Make sure your PDF contains a proper invoice table.")
        else:
            df = pd.concat(df_list, ignore_index=True)
            df.columns = [c.strip().title() for c in df.columns]

            # --- DETECT COLUMNS ---
            col_map = {}
            for col in df.columns:
                col_low = col.lower()
                if "item" in col_low or "name" in col_low:
                    col_map["Item Name"] = col
                elif "price" in col_low or "rate" in col_low or "amount" in col_low:
                    col_map["Original Price"] = col
                elif "qty" in col_low and "free" not in col_low:
                    col_map["Paid Qty"] = col
                elif "free" in col_low:
                    col_map["Free Qty"] = col

            missing = [x for x in ["Item Name", "Original Price", "Paid Qty", "Free Qty"] if x not in col_map]
            if missing:
                st.warning(f"⚠️ Missing columns detected: {', '.join(missing)} — trying to continue anyway.")
                for m in missing:
                    df[m] = 0

            df = df.rename(columns={v: k for k, v in col_map.items() if v in df.columns})

            # --- CLEAN DATA ---
            for c in ["Original Price", "Paid Qty", "Free Qty"]:
                df[c] = df[c].apply(clean_number)

            df = df[df["Item Name"].astype(str).str.strip() != ""]
            df = df.fillna(0)

            # --- CALCULATIONS ---
            df["Discounted Unit Price"] = df["Original Price"] * discount_multiplier
            df["Total Qty"] = df["Paid Qty"] + df["Free Qty"]
            df["Effective Rate"] = (df["Paid Qty"] * df["Discounted Unit Price"]) / df["Total Qty"]
            df["Total Value"] = df["Paid Qty"] * df["Discounted Unit Price"]
            df = df.round(2)

            # --- SEARCH BAR ---
            search = st.text_input("🔎 Search Item Name")
            if search:
                df = df[df["Item Name"].astype(str).str.contains(search, case=False, na=False)]

            # --- DISPLAY TABLE ---
            st.success("✅ Invoice Processed Successfully!")
            st.dataframe(df, use_container_width=True)

            # --- DOWNLOADS ---
            excel_output = BytesIO()
            csv_output = BytesIO()
            df.to_excel(excel_output, index=False)
            df.to_csv(csv_output, index=False)
            excel_output.seek(0)
            csv_output.seek(0)

            col1, col2 = st.columns(2)
            with col1:
                st.download_button("📥 Download Excel", data=excel_output, file_name="invoice_analysis.xlsx")
            with col2:
                st.download_button("📄 Download CSV", data=csv_output, file_name="invoice_analysis.csv")

            # --- SUMMARY ---
            st.markdown("### 📊 Summary")
            st.write(f"**Discount Applied:** {discount_percent}%")
            st.write(f"**Total Items:** {len(df)}")
            st.write(f"**Total Paid Qty:** {df['Paid Qty'].sum():,.0f}")
            st.write(f"**Total Free Qty:** {df['Free Qty'].sum():,.0f}")
            st.write(f"**Total Value (After Discount):** Rs. {df['Total Value'].sum():,.2f}")

            # --- CHART ---
            chart_data = df.groupby("Item Name")[["Paid Qty", "Free Qty"]].sum().reset_index()
            fig = px.bar(chart_data, x="Item Name", y=["Paid Qty", "Free Qty"], barmode="group",
                         title="📈 Paid vs Free Quantity per Item")
            st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"⚠️ Error while processing PDF: {e}")
