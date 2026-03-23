import psycopg2
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import altair as alt
import pandas as pd
import streamlit as st
from io import BytesIO
import zipfile

st.set_page_config(
    page_title="Invoice Dashboard",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="auto",
)

ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]
APP_PASSWORD = st.secrets["APP_PASSWORD"] 

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if not st.session_state.authenticated:
    st.markdown("""
    <style>
    /* =========================
       GLOBAL LAYOUT
       ========================= */
    [data-testid="stSidebar"],
    section[data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }
    
    [data-testid="stVerticalBlock"] > div:first-child:has(div:empty) {
        display: none !important;
    }
    
    body {
        background: linear-gradient(135deg, #f6f8fc 0%, #eef1f7 100%);
    }
    
    .block-container {
        padding-top: 3rem !important;
        max-width: 900px !important;
    }
    
    /* =========================
       LOGIN CARD
       ========================= */
    .login-card {
        background: white;
        padding: 35px 40px;
        border-radius: 16px;
        border: 1px solid #e6e6e6;
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.08);
        text-align: center;
    }
    
    .login-title {
        font-size: 26px;
        font-weight: 600;
        margin-top: 10px;
        margin-bottom: 10px;
    }
    
    .login-sub {
        color: #666;
        margin-bottom: 25px;
        line-height: 1.5;
        font-size: 15px;
    }
    
    /* =========================
       HEADER BUTTONS
       ========================= */
    .stButton > button,
    .stDownloadButton > button {
        border-radius: 10px !important;
        border: 1px solid #e2e5ec !important;
        background: white !important;
        color: #2f3342 !important;
        font-weight: 500 !important;
        font-size: 13px !important;
        padding: 0.4rem 0.8rem !important;
        transition: all 0.2s ease !important;
    }
    
    .stButton > button:hover,
    .stDownloadButton > button:hover {
        border-color: #381CC1 !important;
        color: #381CC1 !important;
        box-shadow: 0 4px 12px rgba(56, 28, 193, 0.12) !important;
    }
    
    /* =========================
       LOGIN BUTTONS
       ========================= */
    .login-card .stButton > button {
        border-radius: 12px !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        padding: 0.7rem 1rem !important;
        background: #f5f6fa !important;
    }
    
    /* Note: nth-of-type may be fragile depending on Streamlit structure */
    .login-card .stButton:nth-of-type(2) > button {
        background: linear-gradient(135deg, #4b2be3 0%, #381CC1 100%) !important;
        color: white !important;
        border: none !important;
        box-shadow: 0 6px 18px rgba(56, 28, 193, 0.25) !important;
    }
    
    .login-card .stButton:nth-of-type(2) > button:hover {
        color: white !important;
        box-shadow: 0 8px 22px rgba(56, 28, 193, 0.35) !important;
    }
    
    /* =========================
       TEXT INPUT
       ========================= */
    [data-testid="stTextInput"] > div {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    
    [data-testid="stTextInput"] input {
        border-radius: 12px !important;
        border: 1px solid #dfe3ea !important;
        background: #f7f8fc !important;
        padding: 0.7rem !important;
        font-size: 15px !important;
        box-shadow: none !important;
    }
    
    [data-testid="stTextInput"] input:focus {
        border-color: #381CC1 !important;
        box-shadow: 0 0 0 2px rgba(56, 28, 193, 0.15) !important;
        outline: none !important;
    }
    </style>
    
    """, unsafe_allow_html=True)
        
    c1, c2, c3 = st.columns([1.2, 2.6, 1.2])
    
    with c2:
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
            
        logo_path = Path(__file__).parent / "LogoWhiteBgrd.png"
        if logo_path.exists():
            st.image(str(logo_path), width=100)
        else:
            st.warning("Logo file not found.")
            
        st.markdown(
            '<div class="login-title">🔒 Invoice Dashboard</div>', 
            unsafe_allow_html=True)
            
        st.markdown(
            '<div class="login-sub">Authorized viewers only. Enter password to access project financial dashboard.</div>',
            unsafe_allow_html=True)
    
        pwd = st.text_input(
            "Password",
            type="password",
            placeholder="Enter password",
            label_visibility="collapsed"
        )
    
        col1, col2 = st.columns(2)
    
        with col1:
            if st.button("Viewer Access", use_container_width=True):
                if pwd == APP_PASSWORD:
                    st.session_state.authenticated = True
                    st.session_state.is_admin = False
                    st.rerun()
                else:
                    st.error("Incorrect viewer password")
    
        with col2:
            if st.button("Admin Access", use_container_width=True):
                if pwd == ADMIN_PASSWORD:
                    st.session_state.authenticated = True
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Incorrect admin password")
    
        st.caption("If you need access, please contact the dashboard owner.")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

READ_ONLY = not st.session_state.is_admin

# ============================================================
# CONFIG
# ============================================================
pd.options.display.float_format = "{:,.2f}".format

SESSION_DEFAULTS = {
    "saving_txn": False,
    "edit_loaded": False,
    "edit_id": None,
    "edit_project": None,
    "edit_vendor": None,
    "edit_category": None,
    "edit_phase": None,
    "edit_line_item": None,
    "last_saved_txn": None,
}

EDITABLE_TXN_COLUMNS = ["txn_date", "receipt_number", "amount", "notes"]

# ============================================================
# SESSION STATE
# ============================================================
def init_session_state() -> None:
    for key, value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ============================================================
# DB HELPERS
# ============================================================

DATABASE_URL = st.secrets["DATABASE_URL"]  # stored in Streamlit secrets

#@st.cache_resource
def get_connection():
    return psycopg2.connect(
        st.secrets["DATABASE_URL"],
        #connect_timeout=5,
        sslmode="require"
    )
    
# Friendly error display
def show_db_error(action="work with the database"):
    st.error(
        f"Something went wrong while trying to {action}. "
        "Please refresh the page and try again."
    )
    st.info(
        "If the problem continues, wait a few seconds and try again. "
        "The database connection may have been interrupted temporarily."
    )
    
#safe read
# def load_df(sql: str, params: tuple = ()) -> pd.DataFrame:
#    con = get_connection()
#   return pd.read_sql(sql, con, params=params)

def load_df(sql, params=None, action="load data"):
    try:
        with closing(get_connection()) as con:
            return pd.read_sql(sql, con, params=params)

    except psycopg2.InterfaceError:
        show_db_error(action)
        st.stop()

    except psycopg2.OperationalError:
        st.warning("The database may still be waking up. Please try again in a few seconds.")
        st.stop()

    except Exception:
        show_db_error(action)
        st.stop()
        
from contextlib import closing
import psycopg2
import streamlit as st

def exec_sql(sql, params=None, action="save data"):
    try:
        with closing(get_connection()) as con:
            with con.cursor() as cur:
                cur.execute(sql, params)
            con.commit()
        return True

    except psycopg2.InterfaceError:
        st.warning("Connection was interrupted while saving. Please try again.")
        return False

    except psycopg2.OperationalError:
        st.warning("The database is temporarily unavailable. Please wait a moment and try again.")
        return False

    except psycopg2.IntegrityError as e:
        msg = str(e)

        if "duplicate key value" in msg:
            st.warning(
                "This transaction already exists and was not saved.\n\n"
                "It looks like you may have clicked **Save Transaction** more than once."
            )
        else:
            st.error(f"Database integrity error: {msg}")

        return False

    except Exception as e:
        show_db_error(action)
        return False

def refresh_data() -> None:
    st.cache_data.clear()
    st.rerun()

# ============================================================
# EXPORT HELPERS
# ============================================================
EXPORT_TABLES = [
    "build_category",
    "projects",
    "vendors",
    "phase",
    "line_item",
    "project_line_item_budget",
    "transactions",
]

def export_table_df(table_name: str) -> pd.DataFrame:
    if table_name not in EXPORT_TABLES:
        raise ValueError(f"Export not allowed for table: {table_name}")
    return load_df(f"SELECT * FROM {table_name}")

def build_csv_export(table_name: str) -> bytes:
    df = export_table_df(table_name)
    return df.to_csv(index=False).encode("utf-8")

def build_numbers_zip_export() -> bytes:
    output = BytesIO()

    with closing(get_connection()) as con:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for table_name in EXPORT_TABLES:
                df = pd.read_sql(f"SELECT * FROM {table_name}", con)
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                zf.writestr(f"{table_name}.csv", csv_bytes)

    output.seek(0)
    return output.getvalue()

# ============================================================
# GENERIC HELPERS
# ============================================================
def chart_size(
    n_items: int,
    base_height: int = 30,
    min_height: int = 300,
    max_height: int = 1200,
) -> tuple[int, int]:
    height = min(max_height, max(min_height, base_height * max(n_items, 1)))
    width = 950
    return width, height

def add_totals_row(
    df: pd.DataFrame,
    label_col: str | None = None,
    label: str = "Total",
) -> pd.DataFrame:
    df_total = df.copy()
    numeric_cols = df_total.select_dtypes(include="number").columns
    totals = df_total[numeric_cols].sum()
    total_row = {col: "" for col in df_total.columns}
    if label_col and label_col in df_total.columns:
        total_row[label_col] = label
    for col in numeric_cols:
        total_row[col] = totals[col]
    return pd.concat([df_total, pd.DataFrame([total_row])], ignore_index=True)

def pretty_report_table(
    df: pd.DataFrame,
    currency_cols: list[str] | None = None,
    percent_cols: list[str] | None = None,
    variance_cols: list[str] | None = None,
    decimals: int = 0,
):
    currency_cols = currency_cols or []
    percent_cols = percent_cols or []
    variance_cols = variance_cols or []
    fmt: dict[str, str] = {}
    for col in currency_cols:
        if col in df.columns:
            fmt[col] = f"${{:,.{decimals}f}}"
    for col in percent_cols:
        if col in df.columns:
            fmt[col] = "{:,.1f}%"
    styler = (
        df.style.format(fmt, na_rep="—").set_properties(
            **{"text-align": "left", "white-space": "nowrap"}
        )
    )
    for col in variance_cols:
        if col in df.columns:
            styler = styler.map(
                lambda v: (
                    "color: #D62728; font-weight: 600;"
                    if pd.notnull(v) and v < 0
                    else "color: #2E8B57; font-weight: 600;"
                    if pd.notnull(v) and v > 0
                    else ""
                ),
                subset=[col],
            )
    styler = styler.apply(
        lambda row: [
            "font-weight:700; background-color:#F3F4F6;"
            if "Total" in row.astype(str).values
            else ""
            for _ in row
        ],
        axis=1,
    )
    return styler

def get_name_from_id(df: pd.DataFrame, id_col: str, name_col: str, value):
    matches = df.loc[df[id_col] == value, name_col]
    return matches.iloc[0] if not matches.empty else str(value)
    
# ============================================================
# LOOKUPS / CACHED DATA
# ============================================================
@st.cache_data
def load_lookups():
    projects = load_df(
        "SELECT project_id, project_name FROM projects ORDER BY project_name;"
    )
    vendors = load_df("SELECT vendor_id, vendor_name FROM vendors ORDER BY vendor_name;")
    categories = load_df(
        """
        SELECT build_category_id, name, sort_order, description
        FROM build_category
        ORDER BY sort_order;
        """
    )
    phases = load_df(
        """
        SELECT phase_id, build_category_id, name, sort_order
        FROM phase
        ORDER BY build_category_id, sort_order;
        """
    )
    line_items = load_df(
        """
        SELECT line_item_id, phase_id, name, sort_order
        FROM line_item
        ORDER BY phase_id, sort_order;
        """
    )
    return projects, vendors, categories, phases, line_items


@st.cache_data(ttl=60)
def load_transactions_joined() -> pd.DataFrame:
    return load_df(
        """
        SELECT
            t.transaction_id,
            t.project_id,
            p.project_name,
            bc.build_category_id,
            bc.name AS category,
            bc.sort_order AS category_sort,
            ph.phase_id,
            ph.name AS phase,
            ph.sort_order AS phase_sort,
            li.line_item_id,
            li.name AS line_item,
            li.description AS description,
            li.sort_order AS line_item_sort,
            t.vendor_id,
            v.vendor_name,
            t.amount,
            t.txn_date,
            t.receipt_number,
            t.notes,
            t.created_at
        FROM transactions t
        LEFT JOIN projects p ON p.project_id = t.project_id
        LEFT JOIN vendors v ON v.vendor_id = t.vendor_id
        LEFT JOIN phase ph ON ph.phase_id = t.phase_id
        LEFT JOIN build_category bc ON bc.build_category_id = ph.build_category_id
        LEFT JOIN line_item li ON li.line_item_id = t.line_item_id
        ORDER BY t.txn_date DESC, t.transaction_id DESC;
        """
    )


def get_phase_options(phases: pd.DataFrame, category_id: int) -> pd.DataFrame:
    return phases[phases["build_category_id"] == category_id].reset_index(drop=True)


def get_line_item_options(line_items: pd.DataFrame, phase_id: int) -> pd.DataFrame:
    return line_items[line_items["phase_id"] == phase_id].reset_index(drop=True)


# ============================================================
# QUERY HELPERS
# ============================================================
@st.cache_data(ttl=60)
def load_project_summary(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        SELECT
            p.project_name,
            COALESCE(b.planned_amount, 0) AS planned,
            COALESCE(a.actual_amount, 0) AS actual,
            COALESCE(a.txn_count, 0) AS txn_count,
            COALESCE(a.vendor_count, 0) AS vendor_count
        FROM projects p
        LEFT JOIN (
            SELECT
                project_id,
                SUM(planned_amount) AS planned_amount
            FROM project_line_item_budget
            GROUP BY project_id
        ) b ON p.project_id = b.project_id
        LEFT JOIN (
            SELECT
                project_id,
                SUM(amount) AS actual_amount,
                COUNT(*) AS txn_count,
                COUNT(DISTINCT vendor_id) AS vendor_count
            FROM transactions
            GROUP BY project_id
        ) a ON p.project_id = a.project_id
        WHERE p.project_id = %s
        """,
        (project_id,),
    )


def load_project_transactions(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        SELECT
            t.transaction_id,
            t.txn_date,
            t.receipt_number,
            t.notes,
            t.amount,
            v.vendor_name,
            ph.name AS phase,
            bc.name AS category,
            li.name AS line_item
        FROM transactions t
        LEFT JOIN vendors v
            ON t.vendor_id = v.vendor_id
        LEFT JOIN phase ph
            ON t.phase_id = ph.phase_id
        LEFT JOIN build_category bc
            ON ph.build_category_id = bc.build_category_id
        LEFT JOIN line_item li
            ON t.line_item_id = li.line_item_id
        WHERE t.project_id = %s
        ORDER BY t.txn_date
        """,
        (project_id,),
    )

@st.cache_data(ttl=60)
def load_phase_budget_vs_actual(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        SELECT
            ph.phase_id,
            ph.name AS phase,
            ph.sort_order,
            COALESCE(pb.planned, 0) AS planned,
            COALESCE(ac.actual, 0) AS actual
        FROM phase ph
        LEFT JOIN (
            SELECT
                li.phase_id,
                plb.project_id,
                SUM(plb.planned_amount) AS planned
            FROM project_line_item_budget plb
            JOIN line_item li
                ON plb.line_item_id = li.line_item_id
            GROUP BY li.phase_id, plb.project_id
        ) pb
            ON ph.phase_id = pb.phase_id
           AND pb.project_id = %s
        LEFT JOIN (
            SELECT
                phase_id,
                project_id,
                SUM(amount) AS actual
            FROM transactions
            GROUP BY phase_id, project_id
        ) ac
            ON ph.phase_id = ac.phase_id
           AND ac.project_id = %s
        ORDER BY ph.sort_order
        """,
        (project_id, project_id),
    )

def load_phase_variance(project_id: str) -> pd.DataFrame:
    df = load_phase_budget_vs_actual(project_id).copy()
    df["variance"] = df["actual"] - df["planned"]
    return df

def load_line_item_variance_for_phase(
    project_id: str, phase_name: str
) -> pd.DataFrame:
    return load_df(
        """
        SELECT
            li.name AS line_item,
            COALESCE(pb.planned, 0) AS planned,
            COALESCE(ac.actual, 0) AS actual,
            COALESCE(ac.actual, 0) - COALESCE(pb.planned, 0) AS variance
        FROM line_item li
        JOIN phase ph
            ON li.phase_id = ph.phase_id
        LEFT JOIN (
            SELECT
                line_item_id,
                project_id,
                SUM(planned_amount) AS planned
            FROM project_line_item_budget
            GROUP BY line_item_id, project_id
        ) pb
            ON li.line_item_id = pb.line_item_id
           AND pb.project_id = %s
        LEFT JOIN (
            SELECT
                line_item_id,
                project_id,
                SUM(amount) AS actual
            FROM transactions
            GROUP BY line_item_id, project_id
        ) ac
            ON li.line_item_id = ac.line_item_id
           AND ac.project_id = %s
        WHERE ph.name = %s
        ORDER BY li.sort_order, li.name
        """,
        (project_id, project_id, phase_name),
    )

def load_project_actual_cost_curve(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        SELECT
            CAST(txn_date AS DATE) AS txn_day,
            SUM(amount) AS daily_actual
        FROM transactions
        WHERE project_id = %s
          AND txn_date IS NOT NULL
        GROUP BY CAST(txn_date AS DATE)
        ORDER BY CAST(txn_date AS DATE);
        """,
        (project_id,),
    )

def load_project_daily_spend(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        SELECT
            CAST(txn_date AS DATE) AS txn_day,
            SUM(amount) AS daily_spend
        FROM transactions
        WHERE project_id = %s
          AND txn_date IS NOT NULL
        GROUP BY CAST(txn_date AS DATE)
        ORDER BY CAST(txn_date AS DATE)
        """,
        (project_id,),
    )

def load_project_budget_burndown(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        SELECT
            CAST(txn_date AS DATE) AS txn_date,
            SUM(amount) AS daily_spend
        FROM transactions
        WHERE project_id = %s
          AND txn_date IS NOT NULL
        GROUP BY CAST(txn_date AS DATE)
        ORDER BY CAST(txn_date AS DATE)
        """,
        (project_id,),
    )

def load_project_total_budget(project_id: str) -> float:
    df = load_df(
        """
        SELECT COALESCE(SUM(planned_amount), 0) AS total_budget
        FROM project_line_item_budget
        WHERE project_id = %s;
        """,
        (project_id,),
    )
    return float(df.iloc[0]["total_budget"]) if not df.empty else 0.0

def load_project_budget_vs_actual() -> pd.DataFrame:
    return load_df(
        """
        WITH actuals AS (
            SELECT
                t.project_id,
                COALESCE(SUM(t.amount), 0) AS actual_amount
            FROM transactions t
            GROUP BY t.project_id
        ),
        budgets AS (
            SELECT
                plb.project_id,
                COALESCE(SUM(plb.planned_amount), 0) AS planned_amount
            FROM project_line_item_budget plb
            GROUP BY plb.project_id
        )
        SELECT
            p.project_id,
            p.project_name,
            COALESCE(b.planned_amount, 0) AS planned_amount,
            COALESCE(a.actual_amount, 0) AS actual_amount,
            COALESCE(b.planned_amount, 0) - COALESCE(a.actual_amount, 0) AS variance
        FROM projects p
        LEFT JOIN budgets b
            ON b.project_id = p.project_id
        LEFT JOIN actuals a
            ON a.project_id = p.project_id
        WHERE COALESCE(b.planned_amount, 0) <> 0
           OR COALESCE(a.actual_amount, 0) <> 0
        ORDER BY p.project_name;
        """
    )

def load_project_category_budget_vs_actual(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        WITH actuals AS (
            SELECT
                t.project_id,
                bc.build_category_id,
                bc.name AS category,
                bc.sort_order AS category_sort,
                SUM(t.amount) AS actual_amount
            FROM transactions t
            JOIN phase ph
                ON ph.phase_id = t.phase_id
            JOIN build_category bc
                ON bc.build_category_id = ph.build_category_id
            WHERE t.project_id = %s
            GROUP BY
                t.project_id,
                bc.build_category_id,
                bc.name,
                bc.sort_order
        ),
        budgets AS (
            SELECT
                plb.project_id,
                bc.build_category_id,
                bc.name AS category,
                bc.sort_order AS category_sort,
                SUM(plb.planned_amount) AS planned_amount
            FROM project_line_item_budget plb
            JOIN line_item li
                ON li.line_item_id = plb.line_item_id
            JOIN phase ph
                ON ph.phase_id = li.phase_id
            JOIN build_category bc
                ON bc.build_category_id = ph.build_category_id
            WHERE plb.project_id = %s
            GROUP BY
                plb.project_id,
                bc.build_category_id,
                bc.name,
                bc.sort_order
        )
        SELECT
            COALESCE(b.project_id, a.project_id) AS project_id,
            COALESCE(b.build_category_id, a.build_category_id) AS build_category_id,
            COALESCE(b.category, a.category) AS category,
            COALESCE(b.category_sort, a.category_sort) AS category_sort,
            COALESCE(b.planned_amount, 0) AS planned_amount,
            COALESCE(a.actual_amount, 0) AS actual_amount,
            COALESCE(b.planned_amount, 0) - COALESCE(a.actual_amount, 0) AS variance
        FROM budgets b
        LEFT JOIN actuals a
            ON a.project_id = b.project_id
           AND a.build_category_id = b.build_category_id

        UNION ALL

        SELECT
            COALESCE(b.project_id, a.project_id) AS project_id,
            COALESCE(b.build_category_id, a.build_category_id) AS build_category_id,
            COALESCE(b.category, a.category) AS category,
            COALESCE(b.category_sort, a.category_sort) AS category_sort,
            COALESCE(b.planned_amount, 0) AS planned_amount,
            COALESCE(a.actual_amount, 0) AS actual_amount,
            COALESCE(b.planned_amount, 0) - COALESCE(a.actual_amount, 0) AS variance
        FROM actuals a
        LEFT JOIN budgets b
            ON b.project_id = a.project_id
           AND b.build_category_id = a.build_category_id
        WHERE b.build_category_id IS NULL

        ORDER BY category_sort, category;
        """,
        (project_id, project_id),
    )
@st.cache_data(ttl=60)
def load_all_projects_phase_actuals() -> pd.DataFrame:
    return load_df(
        """
        SELECT
            p.project_name,
            bc.name AS category,
            bc.sort_order AS category_sort,
            ph.name AS phase,
            ph.sort_order AS phase_sort,
            SUM(t.amount) AS actual_amount
        FROM transactions t
        JOIN projects p
            ON p.project_id = t.project_id
        JOIN phase ph
            ON ph.phase_id = t.phase_id
        JOIN build_category bc
            ON bc.build_category_id = ph.build_category_id
        GROUP BY
            p.project_name,
            bc.name,
            bc.sort_order,
            ph.name,
            ph.sort_order
        ORDER BY
            bc.sort_order,
            ph.sort_order,
            p.project_name;
        """
    )
    
def load_project_phase_budget_vs_actual(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        WITH actuals AS (
            SELECT
                t.project_id,
                ph.phase_id,
                bc.name AS category,
                bc.sort_order AS category_sort,
                ph.name AS phase,
                ph.sort_order AS phase_sort,
                SUM(t.amount) AS actual_amount
            FROM transactions t
            JOIN phase ph
                ON ph.phase_id = t.phase_id
            JOIN build_category bc
                ON bc.build_category_id = ph.build_category_id
            WHERE t.project_id = %s
            GROUP BY
                t.project_id,
                ph.phase_id,
                bc.name,
                bc.sort_order,
                ph.name,
                ph.sort_order
        ),
        budgets AS (
            SELECT
                plb.project_id,
                ph.phase_id,
                bc.name AS category,
                bc.sort_order AS category_sort,
                ph.name AS phase,
                ph.sort_order AS phase_sort,
                SUM(plb.planned_amount) AS planned_amount
            FROM project_line_item_budget plb
            JOIN line_item li
                ON li.line_item_id = plb.line_item_id
            JOIN phase ph
                ON ph.phase_id = li.phase_id
            JOIN build_category bc
                ON bc.build_category_id = ph.build_category_id
            WHERE plb.project_id = %s
            GROUP BY
                plb.project_id,
                ph.phase_id,
                bc.name,
                bc.sort_order,
                ph.name,
                ph.sort_order
        )
        SELECT
            COALESCE(b.phase_id, a.phase_id) AS phase_id,
            COALESCE(b.category, a.category) AS category,
            COALESCE(b.category_sort, a.category_sort) AS category_sort,
            COALESCE(b.phase, a.phase) AS phase,
            COALESCE(b.phase_sort, a.phase_sort) AS phase_sort,
            COALESCE(b.planned_amount, 0) AS planned_amount,
            COALESCE(a.actual_amount, 0) AS actual_amount,
            COALESCE(b.planned_amount, 0) - COALESCE(a.actual_amount, 0) AS variance
        FROM budgets b
        LEFT JOIN actuals a
            ON a.phase_id = b.phase_id

        UNION ALL

        SELECT
            COALESCE(b.phase_id, a.phase_id) AS phase_id,
            COALESCE(b.category, a.category) AS category,
            COALESCE(b.category_sort, a.category_sort) AS category_sort,
            COALESCE(b.phase, a.phase) AS phase,
            COALESCE(b.phase_sort, a.phase_sort) AS phase_sort,
            COALESCE(b.planned_amount, 0) AS planned_amount,
            COALESCE(a.actual_amount, 0) AS actual_amount,
            COALESCE(b.planned_amount, 0) - COALESCE(a.actual_amount, 0) AS variance
        FROM actuals a
        LEFT JOIN budgets b
            ON b.phase_id = a.phase_id
        WHERE b.phase_id IS NULL

        ORDER BY category_sort, phase_sort;
        """,
        (project_id, project_id),
    )

def load_project_line_item_budget_vs_actual(project_id: str) -> pd.DataFrame:
    return load_df(
        """
        WITH actuals AS (
            SELECT
                t.project_id,
                li.line_item_id,
                bc.name AS category,
                bc.sort_order AS category_sort,
                ph.name AS phase,
                ph.sort_order AS phase_sort,
                li.name AS line_item,
                li.sort_order AS line_item_sort,
                SUM(t.amount) AS actual_amount
            FROM transactions t
            JOIN line_item li
                ON li.line_item_id = t.line_item_id
            JOIN phase ph
                ON ph.phase_id = li.phase_id
            JOIN build_category bc
                ON bc.build_category_id = ph.build_category_id
            WHERE t.project_id = %s
            GROUP BY
                t.project_id,
                li.line_item_id,
                bc.name,
                bc.sort_order,
                ph.name,
                ph.sort_order,
                li.name,
                li.sort_order
        ),
        budgets AS (
            SELECT
                plb.project_id,
                li.line_item_id,
                bc.name AS category,
                bc.sort_order AS category_sort,
                ph.name AS phase,
                ph.sort_order AS phase_sort,
                li.name AS line_item,
                li.sort_order AS line_item_sort,
                SUM(plb.planned_amount) AS planned_amount
            FROM project_line_item_budget plb
            JOIN line_item li
                ON li.line_item_id = plb.line_item_id
            JOIN phase ph
                ON ph.phase_id = li.phase_id
            JOIN build_category bc
                ON bc.build_category_id = ph.build_category_id
            WHERE plb.project_id = %s
            GROUP BY
                plb.project_id,
                li.line_item_id,
                bc.name,
                bc.sort_order,
                ph.name,
                ph.sort_order,
                li.name,
                li.sort_order
        )
        SELECT
            COALESCE(b.line_item_id, a.line_item_id) AS line_item_id,
            COALESCE(b.category, a.category) AS category,
            COALESCE(b.category_sort, a.category_sort) AS category_sort,
            COALESCE(b.phase, a.phase) AS phase,
            COALESCE(b.phase_sort, a.phase_sort) AS phase_sort,
            COALESCE(b.line_item, a.line_item) AS line_item,
            COALESCE(b.line_item_sort, a.line_item_sort) AS line_item_sort,
            COALESCE(b.planned_amount, 0) AS planned_amount,
            COALESCE(a.actual_amount, 0) AS actual_amount,
            COALESCE(b.planned_amount, 0) - COALESCE(a.actual_amount, 0) AS variance
        FROM budgets b
        LEFT JOIN actuals a
            ON a.line_item_id = b.line_item_id

        UNION ALL

        SELECT
            COALESCE(b.line_item_id, a.line_item_id) AS line_item_id,
            COALESCE(b.category, a.category) AS category,
            COALESCE(b.category_sort, a.category_sort) AS category_sort,
            COALESCE(b.phase, a.phase) AS phase,
            COALESCE(b.phase_sort, a.phase_sort) AS phase_sort,
            COALESCE(b.line_item, a.line_item) AS line_item,
            COALESCE(b.line_item_sort, a.line_item_sort) AS line_item_sort,
            COALESCE(b.planned_amount, 0) AS planned_amount,
            COALESCE(a.actual_amount, 0) AS actual_amount,
            COALESCE(b.planned_amount, 0) - COALESCE(a.actual_amount, 0) AS variance
        FROM actuals a
        LEFT JOIN budgets b
            ON b.line_item_id = a.line_item_id
        WHERE b.line_item_id IS NULL

        ORDER BY category_sort, phase_sort, line_item_sort;
        """,
        (project_id, project_id),
    )

def load_top_cost_drivers_all_projects() -> pd.DataFrame:
    return load_df(
        """
        SELECT
            bc.name AS category,
            ph.name AS phase,
            li.name AS line_item,
            SUM(t.amount) AS actual_amount
        FROM transactions t
        JOIN line_item li
            ON li.line_item_id = t.line_item_id
        JOIN phase ph
            ON ph.phase_id = li.phase_id
        JOIN build_category bc
            ON bc.build_category_id = ph.build_category_id
        GROUP BY
            bc.name,
            bc.sort_order,
            ph.name,
            ph.sort_order,
            li.name,
            li.sort_order
        ORDER BY
            actual_amount DESC;
        """
    )

# ============================================================
# CHART HELPERS
# ============================================================
def planned_vs_actual_chart(df: pd.DataFrame, x_field: str, title: str):
    chart_source = df.copy()

    chart_source["type_label"] = chart_source.apply(
        lambda r: "Actual (Over Budget)"
        if r["actual_amount"] > r["planned_amount"]
        else "Actual",
        axis=1,
    )

    chart_df = chart_source.melt(
        id_vars=[x_field, "type_label"],
        value_vars=["planned_amount", "actual_amount"],
        var_name="type",
        value_name="amount",
    )

    chart_df["legend_type"] = chart_df.apply(
        lambda r: "Planned" if r["type"] == "planned_amount" else r["type_label"],
        axis=1,
    )

    bars = (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X(
                f"{x_field}:N",
                title=title,
                axis=alt.Axis(labelAngle=-35, labelLimit=0),
            ),
            y=alt.Y(
                "amount:Q",
                title="Amount",
                axis=alt.Axis(format="$,.0f"),
            ),
            xOffset="type",
            color=alt.Color(
                "legend_type:N",
                scale=alt.Scale(
                    domain=["Planned", "Actual", "Actual (Over Budget)"],
                    range=["#2E8B57", "#F28E2B", "#D62728"],
                ),
                legend=alt.Legend(title=""),
            ),
            tooltip=[
                alt.Tooltip(f"{x_field}:N", title=title),
                alt.Tooltip("legend_type:N", title="Type"),
                alt.Tooltip("amount:Q", title="Amount", format="$,.2f"),
            ],
        )
        .properties(height=350)
    )

    labels = (
        alt.Chart(chart_df)
        .mark_text(dy=-6, fontSize=11, fontWeight="bold")
        .encode(
            x=alt.X(f"{x_field}:N"),
            y=alt.Y("amount:Q"),
            xOffset="type",
            text=alt.Text("amount:Q", format="$,.0f"),
            color=alt.Color(
                "legend_type:N",
                scale=alt.Scale(
                    domain=["Planned", "Actual", "Actual (Over Budget)"],
                    range=["#2E8B57", "#F28E2B", "#D62728"],
                ),
                legend=None,
            ),
        )
    )

    return (bars + labels).properties(height=420)

# ============================================================
# TAB RENDERERS
# ============================================================

def render_dashboard_tab(
    projects: pd.DataFrame,
    vendors: pd.DataFrame,
    categories: pd.DataFrame,
    phases: pd.DataFrame,
    line_items: pd.DataFrame,
) -> None:
    del vendors, categories, line_items

    st.subheader("Project Dashboard")

    if projects.empty:
        st.info("No projects found.")
        return

    project_name = st.selectbox("Select project", projects["project_name"].tolist())
    project_id = projects.loc[
        projects["project_name"] == project_name, "project_id"
    ].values[0]

    summary = load_project_summary(project_id)

    if summary.empty:
        st.info("No summary data found for this project.")
        return

    planned = float(summary.iloc[0]["planned"] or 0)
    actual = float(summary.iloc[0]["actual"] or 0)
    txn_count = int(summary.iloc[0]["txn_count"] or 0)
    vendor_count = int(summary.iloc[0]["vendor_count"] or 0)

    remaining = planned - actual
    percent_used = (actual / planned * 100) if planned else 0

    if planned > 0:
        ratio = actual / planned
        if ratio < 0.8:
            st.success("🟢 Project health: On Budget")
        elif ratio < 1:
            st.warning("🟡 Project health: Approaching Budget Limit")
        else:
            st.error("🔴 Project health: Over Budget")

    c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1.2, 1.2, 1, 1, 1])
    c1.metric("Total Budget", f"${planned:,.0f}")
    c2.metric("Actual Spend", f"${actual:,.0f}")
    c3.metric(
        "Remaining Budget",
        f"${remaining:,.0f}",
        delta=f"{remaining / planned * 100:,.1f}% left" if planned else None,
    )
    c4.metric("Transactions", f"{txn_count:,}")
    c5.metric("Budget Used", f"{percent_used:,.1f}%")
    c6.metric("Vendors", f"{vendor_count:,}")

    phase_budget = load_phase_budget_vs_actual(project_id)

    st.divider()
    st.markdown("### Planned vs Actual by Phase")

    if not phase_budget.empty:
        phase_chart_data = phase_budget.melt(
            id_vars="phase",
            value_vars=["planned", "actual"],
            var_name="type",
            value_name="amount",
        )

        chart = (
            alt.Chart(phase_chart_data)
            .mark_bar()
            .encode(
                x=alt.X(
                    "amount:Q",
                    axis=alt.Axis(format="$,.0f"),
                    title="Amount",
                ),
                y=alt.Y(
                    "phase:N",
                    sort=list(phase_budget["phase"]),
                    title="Phase",
                ),
                color=alt.Color(
                    "type:N",
                    scale=alt.Scale(
                        domain=["planned", "actual"],
                        range=["#d3d3d3", "#381CC1"],
                    ),
                    title="",
                ),
                tooltip=[
                    alt.Tooltip("phase:N", title="Phase"),
                    alt.Tooltip("type:N", title="Type"),
                    alt.Tooltip("amount:Q", title="Amount", format="$,.2f"),
                ],
            )
            .properties(height=350)
        )

        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No phase budget/actual data found for this project.")

    st.divider()

    rpt = load_project_transactions(project_id)

    if rpt.empty:
        st.info("No transactions found for this project.")
        return

    rpt["txn_date"] = pd.to_datetime(rpt["txn_date"], errors="coerce")

    variance = load_phase_variance(project_id)

    st.markdown("### Budget Variance by Phase")

    phase_select = alt.selection_point(
        fields=["phase"],
        on="click",
        clear="dblclick",
    )

    variance_chart = (
        alt.Chart(variance)
        .mark_bar()
        .encode(
            x=alt.X("variance:Q", axis=alt.Axis(format="$,.0f")),
            y=alt.Y(
                "phase:N",
                sort=list(phase_budget["phase"]),
                title="Phase",
            ),
            color=alt.condition(
                alt.datum.variance > 0,
                alt.value("#d62728"),
                alt.value("#2ca02c"),
            ),
            tooltip=[
                alt.Tooltip("phase:N", title="Phase"),
                alt.Tooltip("planned:Q", format="$,.2f"),
                alt.Tooltip("actual:Q", format="$,.2f"),
                alt.Tooltip("variance:Q", format="$,.2f"),
            ],
            opacity=alt.condition(phase_select, alt.value(1), alt.value(0.7)),
        )
        .add_params(phase_select)
        .properties(height=350)
    )

    event = st.altair_chart(
        variance_chart,
        use_container_width=True,
        on_select="rerun",
        key="budget_variance_chart",
    )

    selected_phase = None
    if event and "selection" in event:
        sel = event["selection"]
        if "param_1" in sel:
            points = sel["param_1"]
            if points and len(points) > 0 and "phase" in points[0]:
                selected_phase = points[0]["phase"]

    if selected_phase:
        st.info(f"Showing line items for phase: {selected_phase}")
        line_item_variance = load_line_item_variance_for_phase(project_id, selected_phase)

        st.dataframe(
            line_item_variance,
            use_container_width=True,
            hide_index=True,
            column_config={
                "line_item": st.column_config.TextColumn("Line Item", width="medium"),
                "planned": st.column_config.NumberColumn(
                    "Planned", format="$%,.2f", width="small"
                ),
                "actual": st.column_config.NumberColumn(
                    "Actual", format="$%,.2f", width="small"
                ),
                "variance": st.column_config.NumberColumn(
                    "Variance", format="$%,.2f", width="small"
                ),
            },
        )
    else:
        st.caption("Click a phase bar to see line items. Double-click to clear selection.")

    st.divider()

    phase_sum = (
        rpt.groupby("phase", dropna=False)["amount"]
        .sum()
        .reset_index()
        .sort_values("amount", ascending=False)
    )

    vendor_sum = (
        rpt.groupby("vendor_name", dropna=False)["amount"]
        .sum()
        .reset_index()
        .sort_values("amount", ascending=False)
        .head(10)
    )

    left, right = st.columns(2)

    with left:
        st.markdown("### Spend by Phase")
        phase_chart = (
            alt.Chart(phase_sum)
            .mark_bar()
            .encode(
                x=alt.X(
                    "amount:Q",
                    title="Total Spend",
                    axis=alt.Axis(format="$,.0f"),
                ),
                y=alt.Y(
                    "phase:N",
                    sort=list(phase_sum["phase"]),
                    title="Phase",
                    axis=alt.Axis(labelLimit=250),
                ),
                tooltip=[
                    alt.Tooltip("phase:N", title="Phase"),
                    alt.Tooltip("amount:Q", title="Spend", format="$,.2f"),
                ],
            )
            .properties(height=350)
        )
        st.altair_chart(phase_chart, use_container_width=True)

    with right:
        st.markdown("### Top Vendors")
        vendor_chart = (
            alt.Chart(vendor_sum)
            .mark_bar()
            .encode(
                x=alt.X(
                    "amount:Q",
                    title="Total Spend",
                    axis=alt.Axis(format="$,.0f"),
                ),
                y=alt.Y(
                    "vendor_name:N",
                    sort="-x",
                    title="Vendor",
                    axis=alt.Axis(labelLimit=250),
                ),
                tooltip=[
                    alt.Tooltip("vendor_name:N", title="Vendor"),
                    alt.Tooltip("amount:Q", title="Spend", format="$,.2f"),
                ],
            )
            .properties(height=350)
        )
        st.altair_chart(vendor_chart, use_container_width=True)

    st.divider()

def render_new_transaction_tab(
    projects: pd.DataFrame,
    vendors: pd.DataFrame,
    categories: pd.DataFrame,
    phases: pd.DataFrame,
    line_items: pd.DataFrame,
) -> None:
    if READ_ONLY:
        st.info("Read-only mode: adding transactions is disabled for shared viewers.")
        return

    st.subheader("Add New Transaction")

    if (
        projects.empty
        or vendors.empty
        or categories.empty
        or phases.empty
        or line_items.empty
    ):
        st.warning("Missing lookup data. Check your reference tables.")
        return

    c1, c2, c3 = st.columns(3)

    with c1:
        project_id = st.selectbox(
            "Project",
            projects["project_id"].tolist(),
            format_func=lambda x: get_name_from_id(
                projects, "project_id", "project_name", x
            ),
            key="new_txn_project",
        )

        vendor_id = st.selectbox(
            "Vendor",
            vendors["vendor_id"].tolist(),
            format_func=lambda x: get_name_from_id(
                vendors, "vendor_id", "vendor_name", x
            ),
            key="new_txn_vendor",
        )

    with c2:
        category_id = st.selectbox(
            "Build Category",
            categories["build_category_id"].tolist(),
            format_func=lambda x: get_name_from_id(
                categories, "build_category_id", "name", x
            ),
            key="new_txn_category",
        )

        phase_filtered = get_phase_options(phases, category_id)

        if phase_filtered.empty:
            st.warning("No phases for this build category.")
            return

        valid_phase_ids = phase_filtered["phase_id"].tolist()

        if (
            "new_txn_phase" not in st.session_state
            or st.session_state.new_txn_phase not in valid_phase_ids
        ):
            st.session_state.new_txn_phase = valid_phase_ids[0]

        phase_id = st.selectbox(
            "Phase",
            valid_phase_ids,
            format_func=lambda x: get_name_from_id(
                phase_filtered, "phase_id", "name", x
            ),
            key="new_txn_phase",
        )

    with c3:
        li_filtered = get_line_item_options(line_items, phase_id)

        if li_filtered.empty:
            st.warning("No line items for this phase.")
            return

        valid_line_item_ids = li_filtered["line_item_id"].tolist()

        if (
            "new_txn_line_item" not in st.session_state
            or st.session_state.new_txn_line_item not in valid_line_item_ids
        ):
            st.session_state.new_txn_line_item = valid_line_item_ids[0]

        line_item_id = st.selectbox(
            "Line Item",
            valid_line_item_ids,
            format_func=lambda x: get_name_from_id(
                li_filtered, "line_item_id", "name", x
            ),
            key="new_txn_line_item",
        )

    amount = st.number_input(
        "Amount",
        min_value=0.0,
        step=10.0,
        format="%.2f",
        key="new_txn_amount",
    )
    txn_date = st.date_input(
        "Transaction Date",
        value=date.today(),
        key="new_txn_date",
    )
    receipt_number = st.text_input("Receipt Number", key="new_txn_receipt")
    notes = st.text_area("Notes", key="new_txn_notes")

    if st.button(
        "Save Transaction",
        type="primary",
        disabled=st.session_state.saving_txn,
        key="save_new_txn_btn",
    ):
        st.session_state.saving_txn = True

        if amount <= 0:
            st.error("Amount must be greater than 0.")
            st.session_state.saving_txn = False
            return

        saved = exec_sql(
            """
            INSERT INTO transactions (
                project_id, vendor_id, phase_id, line_item_id,
                txn_date, receipt_number, amount, notes, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                project_id,
                int(vendor_id),
                int(phase_id),
                int(line_item_id),
                str(txn_date),
                receipt_number.strip() or None,
                float(amount),
                notes.strip() or None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

        st.session_state.saving_txn = False

        if saved:
            st.session_state["last_saved_txn"] = {
                "project_name": get_name_from_id(
                    projects, "project_id", "project_name", project_id
                ),
                "vendor_name": get_name_from_id(
                    vendors, "vendor_id", "vendor_name", vendor_id
                ),
                "category_name": get_name_from_id(
                    categories, "build_category_id", "name", category_id
                ),
                "phase_name": get_name_from_id(
                    phase_filtered, "phase_id", "name", phase_id
                ),
                "line_item_name": get_name_from_id(
                    li_filtered, "line_item_id", "name", line_item_id
                ),
                "amount": float(amount),
                "txn_date": str(txn_date),
                "receipt_number": receipt_number.strip(),
                "notes": notes.strip(),
            }

            for key in ["new_txn_amount", "new_txn_receipt", "new_txn_notes"]:
                if key in st.session_state:
                    del st.session_state[key]

            refresh_data()

    if st.session_state.get("last_saved_txn"):
        s = st.session_state["last_saved_txn"]
        st.success("Transaction saved successfully ✅")
        st.markdown(
            f"""
**Saved details**
- **Project:** {s['project_name']}
- **Vendor:** {s['vendor_name']}
- **Build Category:** {s['category_name']}
- **Phase:** {s['phase_name']}
- **Line Item:** {s['line_item_name']}
- **Amount:** ${s['amount']:,.2f}
- **Transaction Date:** {s['txn_date']}
- **Receipt Number:** {s['receipt_number'] or '—'}
- **Notes:** {s['notes'] or '—'}
"""
        )

def build_transactions_display_with_subtotals(fdf: pd.DataFrame) -> pd.DataFrame:
    if fdf.empty:
        return pd.DataFrame()

    work = fdf.copy()
    work["txn_date_sort"] = pd.to_datetime(work["txn_date"], errors="coerce")

    work = work.sort_values(
        by=["category_sort", "phase_sort", "line_item_sort", "txn_date_sort", "transaction_id"],
        ascending=[True, True, True, True, True],
        na_position="last",
    )

    rows = []

    for category, cat_df in work.groupby("category", sort=False):
        cat_total = float(cat_df["amount"].fillna(0).sum())

        rows.append({
            "Category": f"▶ {category} (${cat_total:,.2f})",
            "Phase": "",
            "Line Item": "",
            "Description": "",
            "Vendor": "",
            "Date": "",
            "Receipt": "",
            "Amount ($)": None,
            "Notes": "",
        })

        for phase, phase_df in cat_df.groupby("phase", sort=False):
            phase_total = float(phase_df["amount"].fillna(0).sum())

            rows.append({
                "Category": "",
                "Phase": f"• {phase} (${phase_total:,.2f})",
                "Line Item": "",
                "Description": "",
                "Vendor": "",
                "Date": "",
                "Receipt": "",
                "Amount ($)": None,
                "Notes": "",
            })

            for _, r in phase_df.iterrows():
                rows.append({
                    "Category": "",
                    "Phase": "",
                    "Line Item": f"   {r['line_item']}",
                    "Description": r.get("description", ""),
                    "Vendor": r["vendor_name"],
                    "Date": r["txn_date"],
                    "Receipt": r["receipt_number"],
                    "Amount ($)": r["amount"],
                    "Notes": r["notes"],
                })

    return pd.DataFrame(rows)

def render_transactions_tab(
    projects: pd.DataFrame,
    vendors: pd.DataFrame,
    categories: pd.DataFrame,
    phases: pd.DataFrame,
    line_items: pd.DataFrame,
) -> None:
    if READ_ONLY:
        st.info("Read-only mode: editing and deleting transactions is disabled for shared viewers.")
    
    st.subheader("Transactions")

    df = load_transactions_joined()

    df = df.sort_values(
        by=["category_sort", "phase_sort", "line_item_sort", "txn_date"],
        ascending=[True, True, True, True],
        na_position="last",
    )

    if df.empty:
        st.info("No transactions found.")
        return

    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        proj_filter = st.multiselect(
            "Project", sorted(df["project_name"].dropna().unique().tolist())
        )
    with f2:
        vendor_filter = st.multiselect(
            "Vendor", sorted(df["vendor_name"].dropna().unique().tolist())
        )
    with f3:
        cat_filter = st.multiselect(
            "Build Category", sorted(df["category"].dropna().unique().tolist())
        )
    with f4:
        phase_filter = st.multiselect(
            "Phase", sorted(df["phase"].dropna().unique().tolist())
        )
    with f5:
        line_item_filter = st.multiselect(
            "Line Item", sorted(df["line_item"].dropna().unique().tolist())
        )

    d1, d2, d3 = st.columns([1, 1, 2])
    with d1:
        min_date = pd.to_datetime(df["txn_date"], errors="coerce").min()
        min_date = min_date.date() if pd.notnull(min_date) else date(2000, 1, 1)
        date_from = st.date_input("From", value=min_date, key="txn_date_from")
    with d2:
        max_date = pd.to_datetime(df["txn_date"], errors="coerce").max()
        max_date = max_date.date() if pd.notnull(max_date) else date.today()
        date_to = st.date_input("To", value=max_date, key="txn_date_to")
    with d3:
        search = st.text_input(
            "Search (receipt or notes)",
            placeholder="type to filter…",
            key="txn_search",
        )

    fdf = df.copy()

    if proj_filter:
        fdf = fdf[fdf["project_name"].isin(proj_filter)]
    if vendor_filter:
        fdf = fdf[fdf["vendor_name"].isin(vendor_filter)]
    if cat_filter:
        fdf = fdf[fdf["category"].isin(cat_filter)]
    if phase_filter:
        fdf = fdf[fdf["phase"].isin(phase_filter)]
    if line_item_filter:
        fdf = fdf[fdf["line_item"].isin(line_item_filter)]

    fdf["txn_date_parsed"] = pd.to_datetime(fdf["txn_date"], errors="coerce")
    mask = (
        (fdf["txn_date_parsed"].dt.date >= date_from)
        & (fdf["txn_date_parsed"].dt.date <= date_to)
    )
    mask = mask | fdf["txn_date_parsed"].isna()
    fdf = fdf[mask].drop(columns=["txn_date_parsed"])

    if search.strip():
        s = search.strip().lower()
        fdf = fdf[
            fdf["receipt_number"].fillna("").str.lower().str.contains(s)
            | fdf["notes"].fillna("").str.lower().str.contains(s)
        ]
    fdf = fdf.sort_values(
        by=["category_sort", "phase_sort", "line_item_sort", "txn_date"],
        ascending=[True, True, True, True],
        na_position="last",
    )
    st.caption(
        f"Showing {len(fdf)} of {len(df)} transactions | "
        f"Total: ${fdf['amount'].sum():,.2f}"
    )
    # -----------------------------
    # Build filter summary
    # -----------------------------
    selected_filters = []
    
    if proj_filter:
        selected_filters.append(f"Project: {', '.join(proj_filter)}")
    if vendor_filter:
        selected_filters.append(f"Vendor: {', '.join(vendor_filter)}")
    if cat_filter:
        selected_filters.append(f"Build Category: {', '.join(cat_filter)}")
    if phase_filter:
        selected_filters.append(f"Phase: {', '.join(phase_filter)}")
    if line_item_filter:
        selected_filters.append(f"Line Item: {', '.join(line_item_filter)}")
    
    if search.strip():
        selected_filters.append(f"Search: {search.strip()}")
    
    # only mention date filter if it is not the full range
    full_min_date = pd.to_datetime(df["txn_date"], errors="coerce").min()
    full_max_date = pd.to_datetime(df["txn_date"], errors="coerce").max()
    
    full_min_date = full_min_date.date() if pd.notnull(full_min_date) else None
    full_max_date = full_max_date.date() if pd.notnull(full_max_date) else None
    
    if full_min_date and full_max_date:
        if date_from != full_min_date or date_to != full_max_date:
            selected_filters.append(f"Date: {date_from} to {date_to}")
    
    if selected_filters:
        st.markdown("### Grouped view with phase/category totals")
        st.caption("Filters applied: " + " | ".join(selected_filters))
    else:
        st.markdown("### Grouped view with phase/category totals")
        st.caption("Filters applied: None")

    display_df = build_transactions_display_with_subtotals(fdf)
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Category": st.column_config.TextColumn("Category", width="medium"),
            "Phase": st.column_config.TextColumn("Phase", width="medium"),
            "Line Item": st.column_config.TextColumn("Line Item", width="large"),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "Vendor": st.column_config.TextColumn("Vendor", width="medium"),
            "Date": st.column_config.TextColumn("Date", width="small"),
            "Receipt": st.column_config.TextColumn("Receipt", width="small"),
            "Amount ($)": st.column_config.NumberColumn("Amount ($)", format="$%,.2f", width="small"),
            "Notes": st.column_config.TextColumn("Notes", width="medium"),
        },
    )
    
    st.markdown("### Editable transaction table")
    
    grid = fdf[
        [
            "transaction_id",
            "project_name",
            "category",
            "phase",
            "line_item",
            "vendor_name",
            "txn_date",
            "receipt_number",
            "amount",
            "notes",
        ]
    ].copy()
    
    grid["txn_date"] = pd.to_datetime(grid["txn_date"], errors="coerce")
    grid["txn_date"] = grid["txn_date"].fillna("")
    grid["receipt_number"] = grid["receipt_number"].fillna("")
    grid["notes"] = grid["notes"].fillna("")
    grid["amount"] = pd.to_numeric(grid["amount"], errors="coerce")

    edited = st.data_editor(
        grid,
        use_container_width=True,
        hide_index=True,
        disabled=True if READ_ONLY else [
            "transaction_id",
            "project_name",
            "category",
            "phase",
            "line_item",
            "vendor_name",
        ],
        column_config={
            "transaction_id": st.column_config.NumberColumn("ID", width="small"),
            "project_name": st.column_config.TextColumn("Project", width="medium"),
            "category": st.column_config.TextColumn("Category", width="medium"),
            "phase": st.column_config.TextColumn("Phase", width="medium"),
            "line_item": st.column_config.TextColumn("Line Item", width="medium"),
            "vendor_name": st.column_config.TextColumn("Vendor", width="medium"),
            "txn_date": st.column_config.DateColumn("Date", width="small"),
            "receipt_number": st.column_config.TextColumn("Receipt", width="small"),
            "amount": st.column_config.NumberColumn(
                "Amount ($)", format="$%,.2f", width="small"
            ),
            "notes": st.column_config.TextColumn("Notes", width="long"),
        },
        key="txn_editor_safe",
    )

    if not READ_ONLY and st.button("Save inline edits", type="primary"):
        # prevent subtotal/header rows from being treated like real transactions
        original = grid[grid["transaction_id"].notna()].copy().set_index("transaction_id")
        new = edited[edited["transaction_id"].notna()].copy().set_index("transaction_id")

        changed_ids: list[int] = []

        for tid in new.index:
            if tid not in original.index:
                continue

            old_vals = original.loc[tid, EDITABLE_TXN_COLUMNS].copy()
            new_vals = new.loc[tid, EDITABLE_TXN_COLUMNS].copy()

            old_vals = old_vals.fillna("").astype(str)
            new_vals = new_vals.fillna("").astype(str)

            if not old_vals.equals(new_vals):
                changed_ids.append(int(tid))

        if not changed_ids:
            st.info("No changes to save.")
        else:
            success_count = 0
            for tid in changed_ids:
                row = new.loc[tid]
                saved = exec_sql(
                    """
                    UPDATE transactions
                    SET txn_date = %s, receipt_number = %s, amount = %s, notes = %s
                    WHERE transaction_id = %s;
                    """,
                    (
                        str(row["txn_date"]) if pd.notnull(row["txn_date"]) else None,
                        str(row["receipt_number"]).strip()
                        if pd.notnull(row["receipt_number"])
                        and str(row["receipt_number"]).strip()
                        else None,
                        float(row["amount"]) if pd.notnull(row["amount"]) else None,
                        str(row["notes"]).strip()
                        if pd.notnull(row["notes"]) and str(row["notes"]).strip()
                        else None,
                        tid,
                    ),
                )
                if saved:
                    success_count += 1

            if success_count:
                st.success(f"Saved {success_count} updated transaction(s). ✅")
                refresh_data()

    if not READ_ONLY:
        st.markdown("### Edit Project / Vendor / Phase / Line Item (safe dropdowns)")
    
        edit_id = st.number_input(
            "Transaction ID to edit",
            min_value=1,
            step=1,
            key="edit_txn_id",
        )
    
        if st.button("Load transaction", key="load_txn"):
            tx = load_df(
                """
                SELECT transaction_id, project_id, vendor_id, phase_id, line_item_id
                FROM transactions
                WHERE transaction_id = %s
                """,
                (int(edit_id),),
            )
    
            if tx.empty:
                st.error("Transaction ID not found.")
            else:
                tx_row = tx.iloc[0]
    
                phase_row = phases[phases["phase_id"] == tx_row["phase_id"]]
                if phase_row.empty:
                    st.error("Phase for selected transaction not found.")
                else:
                    category_id = int(phase_row["build_category_id"].iloc[0])
    
                    st.session_state.edit_loaded = True
                    st.session_state.edit_id = int(tx_row["transaction_id"])
                    st.session_state.edit_project = tx_row["project_id"]
                    st.session_state.edit_vendor = int(tx_row["vendor_id"])
                    st.session_state.edit_category = int(category_id)
                    st.session_state.edit_phase = int(tx_row["phase_id"])
                    st.session_state.edit_line_item = int(tx_row["line_item_id"])
    
        if st.session_state.get("edit_loaded") and st.session_state.get("edit_category") is not None:
            current_category_id = st.session_state["edit_category"]
    
            phase_df = get_phase_options(phases, current_category_id)
            phase_ids = phase_df["phase_id"].tolist()
    
            if phase_ids and st.session_state.edit_phase not in phase_ids:
                st.session_state.edit_phase = phase_ids[0]
    
            current_phase_id = st.session_state.edit_phase
    
            li_df = get_line_item_options(line_items, current_phase_id)
            li_ids = li_df["line_item_id"].tolist()
    
            if li_ids and st.session_state.edit_line_item not in li_ids:
                st.session_state.edit_line_item = li_ids[0]
    
            c1, c2, c3 = st.columns(3)
    
            with c1:
                st.selectbox(
                    "Project",
                    projects["project_id"].tolist(),
                    key="edit_project",
                    format_func=lambda x: get_name_from_id(
                        projects, "project_id", "project_name", x
                    ),
                )
    
                st.selectbox(
                    "Vendor",
                    vendors["vendor_id"].tolist(),
                    key="edit_vendor",
                    format_func=lambda x: get_name_from_id(
                        vendors, "vendor_id", "vendor_name", x
                    ),
                )
    
            with c2:
                st.selectbox(
                    "Build Category",
                    categories["build_category_id"].tolist(),
                    key="edit_category",
                    format_func=lambda x: get_name_from_id(
                        categories, "build_category_id", "name", x
                    ),
                )
    
                phase_df = get_phase_options(phases, st.session_state.edit_category)
    
                if phase_df.empty:
                    st.warning("No phases for selected category.")
                    return
    
                st.selectbox(
                    "Phase",
                    phase_df["phase_id"].tolist(),
                    key="edit_phase",
                    format_func=lambda x: get_name_from_id(phase_df, "phase_id", "name", x),
                )
    
            with c3:
                li_df = get_line_item_options(line_items, st.session_state.edit_phase)
    
                if li_df.empty:
                    st.warning("No line items for this phase")
                else:
                    st.selectbox(
                        "Line Item",
                        li_df["line_item_id"].tolist(),
                        key="edit_line_item",
                        format_func=lambda x: get_name_from_id(
                            li_df, "line_item_id", "name", x
                        ),
                    )
    
            if st.button("Save relational changes", type="primary"):
                saved = exec_sql(
                    """
                    UPDATE transactions
                    SET project_id = %s, vendor_id = %s, phase_id = %s, line_item_id = %s
                    WHERE transaction_id = %s
                    """,
                    (
                        st.session_state.edit_project,
                        int(st.session_state.edit_vendor),
                        int(st.session_state.edit_phase),
                        int(st.session_state.edit_line_item),
                        int(st.session_state.edit_id),
                    ),
                )
    
                if saved:
                    st.success("Updated relational fields ✅")
                    refresh_data()
    
        st.markdown("### Delete Transaction")
    
        col1, col2 = st.columns([1, 1])
    
        with col1:
            delete_id = st.number_input(
                "Transaction ID",
                min_value=1,
                step=1,
                key="delete_txn_id",
            )
    
        with col2:
            st.write("")
            st.write("")
            confirm = st.checkbox("Confirm delete")
    
        if delete_id:
            preview = load_df(
                """
                SELECT
                    t.transaction_id,
                    p.project_name,
                    v.vendor_name,
                    li.name AS line_item,
                    t.amount,
                    t.txn_date
                FROM transactions t
                LEFT JOIN projects p ON p.project_id = t.project_id
                LEFT JOIN vendors v ON v.vendor_id = t.vendor_id
                LEFT JOIN line_item li ON li.line_item_id = t.line_item_id
                WHERE t.transaction_id = %s
                """,
                (int(delete_id),),
            )
    
            if not preview.empty:
                st.caption("Transaction preview")
                st.dataframe(
                    preview,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "transaction_id": "Transaction ID",
                        "project_name": "Project",
                        "vendor_name": "Vendor",
                        "line_item": "Line Item",
                        "amount": st.column_config.NumberColumn("Amount", format="$%,.2f"),
                        "txn_date": "Date",
                    },
                )
    
        if confirm and st.button("Delete Transaction", use_container_width=True):
            txn_id = int(delete_id)
    
            deleted = exec_sql(
                "DELETE FROM transactions WHERE transaction_id = %s;",
                (txn_id,),
            )
    
            if deleted:
                st.success(f"Transaction #{txn_id} deleted successfully ✅")
                refresh_data()   

def render_reports_tab() -> None:
    st.subheader("Reports")
    df = load_transactions_joined()
    st.markdown("## All Projects – Planned vs Actual")
    all_projects_bva = load_project_budget_vs_actual()
    if all_projects_bva.empty:
        st.info("No budget or actual data found yet.")
    else:
        st.dataframe(
            all_projects_bva[
                ["project_name", "planned_amount", "actual_amount", "variance"]
            ],
            use_container_width=True,
            hide_index=True,
        )

        chart = planned_vs_actual_chart(all_projects_bva, "project_name", "Project")
        st.altair_chart(chart, use_container_width=True)

    st.divider()

    st.markdown("## Top cost drivers across all projects")
    drivers_df = load_top_cost_drivers_all_projects()

    if drivers_df.empty:
        st.info("No transaction data found yet.")
    else:
        st.dataframe(
            drivers_df[["category", "phase", "line_item", "actual_amount"]],
            use_container_width=True,
            hide_index=True,
        )

        width, height = chart_size(len(drivers_df), base_height=30, max_height=1200)

        drivers_chart = (
            alt.Chart(drivers_df)
            .mark_bar(color="#4AA511")
            .encode(
                x=alt.X(
                    "actual_amount:Q",
                    title="Actual Spend",
                    axis=alt.Axis(format="$,.0f"),
                ),
                y=alt.Y(
                    "line_item:N",
                    sort="-x",
                    title="Line Item",
                    axis=alt.Axis(labelLimit=0),
                ),
                tooltip=[
                    alt.Tooltip("category:N", title="Category"),
                    alt.Tooltip("phase:N", title="Phase"),
                    alt.Tooltip("line_item:N", title="Line Item"),
                    alt.Tooltip(
                        "actual_amount:Q",
                        title="Actual Spend",
                        format="$,.2f",
                    ),
                ],
            )
            .properties(width=width, height=height)
        )

        driver_labels = (
            alt.Chart(drivers_df)
            .mark_text(align="left", baseline="middle", dx=5, fontSize=11)
            .encode(
                x=alt.X("actual_amount:Q"),
                y=alt.Y("line_item:N", sort="-x"),
                text=alt.Text("actual_amount:Q", format="$,.0f"),
            )
        )

        st.altair_chart(drivers_chart + driver_labels, use_container_width=True)

    st.divider()

    project_names = sorted(df["project_name"].dropna().unique().tolist())
    budget_project_names = load_df(
        """
        SELECT DISTINCT p.project_name
        FROM project_line_item_budget plb
        JOIN projects p ON p.project_id = plb.project_id
        ORDER BY p.project_name;
        """
    )["project_name"].tolist()

    st.markdown("## Houses Costs Comparison per Construction Phase (Actual)")
    
    try:
        all_phase_actuals = load_all_projects_phase_actuals()
            
        if all_phase_actuals is None or all_phase_actuals.empty:
            st.info("No actual transaction data found yet for project comparison.")
        else:
            required_cols = {"project_name", "category", "phase", "actual_amount"}
            missing_cols = required_cols - set(all_phase_actuals.columns)
    
            if missing_cols:
                st.warning(
                    "Phase comparison chart could not be shown because some required columns are missing: "
                    + ", ".join(sorted(missing_cols))
                )
            else:
                show_total = st.toggle(
                    "Show total per phase (all houses combined)",
                    value=False,
                    key="show_total_phase_compare"
                )
    
                if show_total:
                    group_cols = ["category", "phase"]
    
                    if "category_sort" in all_phase_actuals.columns:
                        group_cols.append("category_sort")
                    if "phase_sort" in all_phase_actuals.columns:
                        group_cols.append("phase_sort")
    
                    all_phase_actuals = (
                        all_phase_actuals
                        .groupby(group_cols, as_index=False)["actual_amount"]
                        .sum()
                    )
    
                    all_phase_actuals["project_name"] = "All Houses"
    
                # build phase label
                all_phase_actuals["phase_label"] = (
                    all_phase_actuals["category"].astype(str)
                    + " • "
                    + all_phase_actuals["phase"].astype(str)
                )
    
                sort_cols = []
                if "category_sort" in all_phase_actuals.columns:
                    sort_cols.append("category_sort")
                if "phase_sort" in all_phase_actuals.columns:
                    sort_cols.append("phase_sort")
    
                if sort_cols:
                    phase_order = (
                        all_phase_actuals
                        .sort_values(sort_cols)["phase_label"]
                        .drop_duplicates()
                        .tolist()
                    )
                else:
                    phase_order = (
                        all_phase_actuals["phase_label"]
                        .drop_duplicates()
                        .tolist()
                    )

                comparison_chart = (
                    alt.Chart(all_phase_actuals)
                    .mark_bar()
                    .encode(
                        x=alt.X(
                            "phase_label:N",
                            sort=phase_order,
                            title="Construction Phase",
                            axis=alt.Axis(labelAngle=-35, labelLimit=220),
                        ),
                        y=alt.Y(
                            "actual_amount:Q",
                            title="Actual Spend",
                            axis=alt.Axis(format="$,.0f"),
                        ),
                        color=alt.Color(
                            "project_name:N",
                            title="House",
                            legend=alt.Legend(orient="top", direction="horizontal"),
                        ),
                        xOffset="project_name:N",
                        tooltip=[
                            alt.Tooltip("project_name:N", title="House"),
                            alt.Tooltip("category:N", title="Category"),
                            alt.Tooltip("phase:N", title="Phase"),
                            alt.Tooltip("actual_amount:Q", title="Actual Spend", format="$,.2f"),
                        ],
                    )
                    .properties(height=430)
                )
    
                comparison_labels = (
                    alt.Chart(all_phase_actuals)
                    .transform_filter(alt.datum.actual_amount > 20000)
                    .mark_text(angle=270, dy=0, dx=1)
                    .encode(
                        x=alt.X("phase_label:N", sort=phase_order),
                        y=alt.Y("actual_amount:Q"),
                        xOffset="project_name:N",
                        text=alt.Text("actual_amount:Q", format="$,.0f"),
                        detail="project_name:N",
                    )
                )
    
                st.altair_chart(comparison_chart + comparison_labels, use_container_width=True)
    
    except Exception as e:
        st.warning(f"Phase comparison chart is temporarily unavailable: {e}")
    st.divider()
    
    all_project_names = sorted(set(project_names) | set(budget_project_names))
    rpt_project = (
        st.selectbox("Select project for reports", all_project_names)
        if all_project_names
        else None
    )

    if rpt_project is None:
        st.info("No transactions or budget data found yet.")
        return

    project_row = load_df(
        """
        SELECT project_id, project_name
        FROM projects
        WHERE project_name = %s;
        """,
        (rpt_project,),
    )

    if project_row.empty:
        st.error("Selected project not found.")
        return

    rpt_project_id = project_row.iloc[0]["project_id"]
    rpt = df[df["project_name"] == rpt_project].copy()

    st.markdown(f"## Vendor spend summary — {rpt_project}")
    if rpt.empty:
        st.info("No actual transactions found for this project.")
    else:
        vendor_sum = (
            rpt.groupby("vendor_name", dropna=False)["amount"]
            .sum()
            .reset_index()
            .sort_values("amount", ascending=False)
        )

        vendor_display = vendor_sum.rename(
            columns={"vendor_name": "Vendor", "amount": "Actual Spend"}
        )
        vendor_display = add_totals_row(vendor_display, "Vendor")

        st.dataframe(
            pretty_report_table(
                vendor_display,
                currency_cols=["Actual Spend"],
                decimals=2,
            ),
            use_container_width=True,
            hide_index=True,
        )

        if not vendor_sum.empty:
            width, height = chart_size(len(vendor_sum))

            bars = (
                alt.Chart(vendor_sum)
                .mark_bar(color="#381CC1")
                .encode(
                    x=alt.X(
                        "amount:Q",
                        title="Total Spend",
                        axis=alt.Axis(format="$,.0f"),
                    ),
                    y=alt.Y(
                        "vendor_name:N",
                        sort="-x",
                        title="Vendor",
                        axis=alt.Axis(labelLimit=0),
                    ),
                    tooltip=[
                        alt.Tooltip("vendor_name:N", title="Vendor"),
                        alt.Tooltip("amount:Q", title="Total Spend", format="$,.2f"),
                    ],
                )
            )

            labels = (
                alt.Chart(vendor_sum)
                .mark_text(align="left", baseline="middle", dx=5, fontSize=11)
                .encode(
                    x=alt.X("amount:Q"),
                    y=alt.Y("vendor_name:N", sort="-x"),
                    text=alt.Text("amount:Q", format="$,.0f"),
                )
            )

            vendor_chart = (bars + labels).properties(width=width, height=height)
            st.altair_chart(vendor_chart, use_container_width=True)

    st.markdown(f"## Build category budget vs actual — {rpt_project}")
    cat_bva = load_project_category_budget_vs_actual(rpt_project_id)

    if cat_bva.empty:
        st.info("No build category budget/actual data found for this project.")
    else:
        cat_display = cat_bva[
            ["category", "planned_amount", "actual_amount", "variance"]
        ].rename(
            columns={
                "category": "Category",
                "planned_amount": "Planned",
                "actual_amount": "Actual",
                "variance": "Variance",
            }
        )

        cat_display = add_totals_row(cat_display, "Category")
        st.dataframe(
            pretty_report_table(
                cat_display,
                currency_cols=["Planned", "Actual", "Variance"],
                variance_cols=["Variance"],
            ),
            use_container_width=True,
            hide_index=True,
        )

        chart = planned_vs_actual_chart(cat_bva, "category", "Category")
        st.altair_chart(chart, use_container_width=True)

    st.markdown(f"## Phase budget vs actual — {rpt_project}")
    phase_bva = load_project_phase_budget_vs_actual(rpt_project_id)

    if phase_bva.empty:
        st.info("No phase budget/actual data found for this project.")
    else:
        phase_bva["percent_used"] = phase_bva.apply(
            lambda r: (r["actual_amount"] / r["planned_amount"] * 100)
            if r["planned_amount"] not in (0, None)
            else None,
            axis=1,
        )

        phase_display = phase_bva[
            ["category", "phase", "planned_amount", "actual_amount", "variance", "percent_used"]
        ].rename(
            columns={
                "category": "Category",
                "phase": "Phase",
                "planned_amount": "Planned",
                "actual_amount": "Actual",
                "variance": "Variance",
                "percent_used": "% Used",
            }
        )

        phase_display = add_totals_row(phase_display, "Category")
        st.dataframe(
            pretty_report_table(
                phase_display,
                currency_cols=["Planned", "Actual", "Variance"],
                percent_cols=["% Used"],
                variance_cols=["Variance"],
            ),
            use_container_width=True,
            hide_index=True,
        )

        phase_chart = planned_vs_actual_chart(phase_bva, "phase", "Phase")
        st.altair_chart(phase_chart, use_container_width=True)

    st.markdown(
        f"## Construction cost curve (actual cumulative spend vs budget ceiling) - {rpt_project}"
    )

    curve_df = load_project_actual_cost_curve(rpt_project_id)

    if curve_df.empty:
        st.info("No dated transactions found for this project.")
    else:
        curve_df["txn_day"] = pd.to_datetime(curve_df["txn_day"], errors="coerce")
        curve_df = curve_df.dropna(subset=["txn_day"]).sort_values("txn_day")
        curve_df["cumulative_actual"] = curve_df["daily_actual"].cumsum()

        total_budget = load_project_total_budget(rpt_project_id)

        actual_line = (
            alt.Chart(curve_df)
            .mark_line(point=True, color="#F28E2B")
            .encode(
                x=alt.X("txn_day:T", title="Date"),
                y=alt.Y("cumulative_actual:Q", title="Cumulative Spend"),
                tooltip=[
                    alt.Tooltip("txn_day:T", title="Date"),
                    alt.Tooltip("daily_actual:Q", title="Daily Actual", format="$,.2f"),
                    alt.Tooltip(
                        "cumulative_actual:Q",
                        title="Cumulative Actual",
                        format="$,.2f",
                    ),
                ],
            )
        )

        layers = [actual_line]

        if total_budget > 0 and len(curve_df) > 0:
            budget_line_df = pd.DataFrame({"budget_total": [total_budget]})

            budget_line = (
                alt.Chart(budget_line_df)
                .mark_rule(color="#2E8B57", strokeDash=[6, 4], size=2)
                .encode(
                    y=alt.Y("budget_total:Q"),
                    tooltip=[
                        alt.Tooltip(
                            "budget_total:Q",
                            title="Budget Ceiling",
                            format="$,.2f",
                        )
                    ],
                )
            )
            layers.append(budget_line)

        cost_curve_chart = alt.layer(*layers).properties(height=420)
        st.altair_chart(cost_curve_chart, use_container_width=True)

    st.markdown("### Daily Spend (Burn Rate)")
    daily = load_project_daily_spend(rpt_project_id)

    if not daily.empty:
        daily["txn_day"] = pd.to_datetime(daily["txn_day"])

        burn_chart = (
            alt.Chart(daily)
            .mark_bar(color="#F28E2B")
            .encode(
                x=alt.X("txn_day:T", title="Date"),
                y=alt.Y(
                    "daily_spend:Q",
                    title="Daily Spend",
                    axis=alt.Axis(format="$,.0f"),
                ),
                tooltip=[
                    alt.Tooltip("txn_day:T", title="Date"),
                    alt.Tooltip(
                        "daily_spend:Q",
                        title="Daily Spend",
                        format="$,.2f",
                    ),
                ],
            )
            .properties(height=350)
        )

        st.altair_chart(burn_chart, use_container_width=True)
    else:
        st.info("No daily spend data found.")

    st.markdown(f"## Budget Burn-Down — {rpt_project}")

    daily = load_project_budget_burndown(rpt_project_id)
    budget_total = load_project_total_budget(rpt_project_id)

    if daily.empty:
        st.info("No transaction data available.")
    else:
        daily["txn_date"] = pd.to_datetime(daily["txn_date"])
        daily = daily.sort_values("txn_date")
        daily["cumulative_spend"] = daily["daily_spend"].cumsum()
        daily["remaining_budget"] = budget_total - daily["cumulative_spend"]

        chart = (
            alt.Chart(daily)
            .mark_line(point=True)
            .encode(
                x=alt.X("txn_date:T", title="Date"),
                y=alt.Y(
                    "remaining_budget:Q",
                    title="Remaining Budget",
                    axis=alt.Axis(format="$,.0f"),
                ),
                tooltip=[
                    alt.Tooltip("txn_date:T", title="Date"),
                    alt.Tooltip(
                        "remaining_budget:Q",
                        title="Remaining Budget",
                        format="$,.2f",
                    ),
                ],
            )
            .properties(height=350)
        )

        st.altair_chart(chart, use_container_width=True)

    st.markdown(f"## Line item budget vs actual — {rpt_project}")
    li_bva = load_project_line_item_budget_vs_actual(rpt_project_id)

    if li_bva.empty:
        st.info("No line item budget/actual data found for this project.")
    else:
        li_bva["percent_used"] = li_bva.apply(
            lambda r: (r["actual_amount"] / r["planned_amount"] * 100)
            if r["planned_amount"] not in (0, None)
            else None,
            axis=1,
        )

        li_display = li_bva[
            [
                "category",
                "phase",
                "line_item",
                "planned_amount",
                "actual_amount",
                "variance",
                "percent_used",
            ]
        ].rename(
            columns={
                "category": "Category",
                "phase": "Phase",
                "line_item": "Line Item",
                "planned_amount": "Planned",
                "actual_amount": "Actual",
                "variance": "Variance",
                "percent_used": "% Used",
            }
        )

        li_display = add_totals_row(li_display, "Category")
        st.dataframe(
            pretty_report_table(
                li_display,
                currency_cols=["Planned", "Actual", "Variance"],
                percent_cols=["% Used"],
                variance_cols=["Variance"],
            ),
            use_container_width=True,
            hide_index=True,
        )

        chart_source = li_bva.sort_values("actual_amount", ascending=False).copy()
        chart_source["legend_type"] = chart_source.apply(
            lambda r: "Actual (Over Budget)"
            if r["actual_amount"] > r["planned_amount"]
            else "Actual",
            axis=1,
        )

        width, height = chart_size(len(chart_source), base_height=34)

        li_chart_df = chart_source.melt(
            id_vars=["line_item", "legend_type"],
            value_vars=["planned_amount", "actual_amount"],
            var_name="type",
            value_name="amount",
        )

        li_chart_df["legend"] = li_chart_df.apply(
            lambda r: "Planned" if r["type"] == "planned_amount" else r["legend_type"],
            axis=1,
        )

        bars = (
            alt.Chart(li_chart_df)
            .mark_bar()
            .encode(
                x=alt.X(
                    "amount:Q",
                    title="Amount",
                    axis=alt.Axis(format="$,.0f"),
                ),
                y=alt.Y(
                    "line_item:N",
                    sort="-x",
                    title="Line Item",
                    axis=alt.Axis(labelLimit=0),
                ),
                yOffset="type",
                color=alt.Color(
                    "legend:N",
                    scale=alt.Scale(
                        domain=["Planned", "Actual", "Actual (Over Budget)"],
                        range=["#2E8B57", "#F28E2B", "#D62728"],
                    ),
                    legend=alt.Legend(title="", orient="top"),
                ),
                tooltip=[
                    alt.Tooltip("line_item:N", title="Line Item"),
                    alt.Tooltip("type:N", title="Type"),
                    alt.Tooltip("amount:Q", title="Amount", format="$,.2f"),
                ],
            )
            .properties(height=350)
        )

        labels = (
            alt.Chart(li_chart_df)
            .mark_text(
                align="left",
                baseline="middle",
                dx=5,
                fontSize=11,
                fontWeight="bold",
            )
            .encode(
                x=alt.X("amount:Q"),
                y=alt.Y("line_item:N", sort="-x"),
                yOffset="type",
                text=alt.Text("amount:Q", format="$,.0f"),
                color=alt.Color(
                    "legend:N",
                    scale=alt.Scale(
                        domain=["Planned", "Actual", "Actual (Over Budget)"],
                        range=["#2E8B57", "#F28E2B", "#D62728"],
                    ),
                    legend=None,
                ),
            )
        )

        li_chart = (bars + labels).properties(width=width, height=height)
        st.altair_chart(li_chart, use_container_width=True)

def render_vendor_admin_tab() -> None:
    st.subheader("Vendor Admin")

    if not st.session_state.is_admin:
        st.warning("Admin access required.")
        return

    vendors_df = load_df(
        """
        SELECT vendor_id, vendor_name
        FROM vendors
        ORDER BY vendor_name;
        """
    )

    st.markdown("### Current Vendors")
    st.dataframe(
        vendors_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "vendor_id": st.column_config.NumberColumn("Vendor ID", width="small"),
            "vendor_name": st.column_config.TextColumn("Vendor Name", width="large"),
        },
    )

    st.divider()

    add_col, edit_col, delete_col = st.columns(3)

    with add_col:
        st.markdown("### Add Vendor")
        new_vendor_name = st.text_input("New vendor name", key="admin_new_vendor_name")

        if st.button("Add vendor", key="add_vendor_btn", use_container_width=True):
            vendor_name = new_vendor_name.strip()
            if not vendor_name:
                st.error("Vendor name cannot be blank.")
            else:
                exists = load_df(
                    "SELECT vendor_id FROM vendors WHERE LOWER(vendor_name) = LOWER(%s);",
                    (vendor_name,),
                )
                if not exists.empty:
                    st.warning("Vendor already exists.")
                else:
                    saved = exec_sql(
                        "INSERT INTO vendors (vendor_name) VALUES (%s);",
                        (vendor_name,),
                    )
                    if saved:
                        st.success(f"Vendor added: {vendor_name}")
                        refresh_data()

    with edit_col:
        st.markdown("### Modify Vendor")
        if vendors_df.empty:
            st.info("No vendors found.")
        else:
            edit_vendor_id = st.selectbox(
                "Select vendor",
                vendors_df["vendor_id"].tolist(),
                format_func=lambda x: get_name_from_id(
                    vendors_df, "vendor_id", "vendor_name", x
                ),
                key="edit_vendor_admin_id",
            )

            current_name = get_name_from_id(
                vendors_df, "vendor_id", "vendor_name", edit_vendor_id
            )

            updated_vendor_name = st.text_input(
                "Updated vendor name",
                value=current_name,
                key="updated_vendor_name",
            )

            if st.button("Save vendor name", key="save_vendor_name_btn", use_container_width=True):
                vendor_name = updated_vendor_name.strip()
                if not vendor_name:
                    st.error("Vendor name cannot be blank.")
                else:
                    exists = load_df(
                        """
                        SELECT vendor_id
                        FROM vendors
                        WHERE LOWER(vendor_name) = LOWER(%s)
                          AND vendor_id <> %s;
                        """,
                        (vendor_name, int(edit_vendor_id)),
                    )
                    if not exists.empty:
                        st.warning("Another vendor with this name already exists.")
                    else:
                        saved = exec_sql(
                            "UPDATE vendors SET vendor_name = %s WHERE vendor_id = %s;",
                            (vendor_name, int(edit_vendor_id)),
                        )
                        if saved:
                            st.success("Vendor updated ✅")
                            refresh_data()

    with delete_col:
        st.markdown("### Delete Vendor")
        if vendors_df.empty:
            st.info("No vendors found.")
        else:
            delete_vendor_id = st.selectbox(
                "Vendor to delete",
                vendors_df["vendor_id"].tolist(),
                format_func=lambda x: get_name_from_id(
                    vendors_df, "vendor_id", "vendor_name", x
                ),
                key="delete_vendor_admin_id",
            )

            delete_vendor_name = get_name_from_id(
                vendors_df, "vendor_id", "vendor_name", delete_vendor_id
            )

            usage_df = load_df(
                """
                SELECT COUNT(*) AS cnt
                FROM transactions
                WHERE vendor_id = %s;
                """,
                (int(delete_vendor_id),),
            )
            usage_count = int(usage_df.iloc[0]["cnt"]) if not usage_df.empty else 0

            if usage_count > 0:
                st.caption(
                    f"This vendor is used in {usage_count} transaction(s) and should not be deleted."
                )
            else:
                st.caption("This vendor is not used in transactions.")

            if st.button(
                "Delete vendor",
                key="delete_vendor_btn",
                use_container_width=True,
                disabled=usage_count > 0,
            ):
                deleted = exec_sql(
                    "DELETE FROM vendors WHERE vendor_id = %s;",
                    (int(delete_vendor_id),),
                )
                if deleted:
                    st.success(f"Deleted vendor: {delete_vendor_name}")
                    refresh_data()

def render_header_menu() -> None:
    top1, top2, top3 = st.columns([6, 0.6, 0.8])

    with top1:
        st.title("📊 Invoice DB – Transactions & Reports")

    with top2:
        if st.session_state.is_admin:
            st.markdown("**🛠 Admin**")
        else:
            st.markdown("**👁 Viewer**")

    with top3:
        with st.popover("⚙️ Menu", use_container_width=True):
            if not st.session_state.is_admin:
                st.markdown("**Admin Access**")
                admin_pwd_menu = st.text_input(
                    "Admin password",
                    type="password",
                    placeholder="Enter admin password",
                    label_visibility="collapsed",
                    key="admin_pwd_menu",
                )

                if st.button(
                    "Unlock Admin",
                    use_container_width=True,
                    key="unlock_admin_menu_btn",
                ):
                    if admin_pwd_menu == ADMIN_PASSWORD:
                        st.session_state.is_admin = True
                        st.success("Admin mode enabled.")
                        st.rerun()
                    else:
                        st.error("Wrong admin password")

            else:
                st.success("Admin mode enabled")
                st.caption("Database is hosted in Neon.")

                if st.button(
                    "Lock Admin",
                    use_container_width=True,
                    key="lock_admin_menu_btn",
                ):
                    st.session_state.is_admin = False
                    st.rerun()

                st.markdown("**Export data**")

                st.download_button(
                    "Download all tables for Numbers",
                    data=build_numbers_zip_export(),
                    file_name="invoice_dashboard_tables_csv.zip",
                    mime="application/zip",
                )

                export_table = st.selectbox(
                    "Export single table as CSV",
                    EXPORT_TABLES,
                    key="menu_export_table_select",
                )

                try:
                    csv_data = build_csv_export(export_table)
                    st.download_button(
                        f"⬇️ Download {export_table}.csv",
                        data=csv_data,
                        file_name=f"{export_table}_{datetime.now():%Y%m%d_%H%M%S}.csv",
                        mime="text/csv",
                        use_container_width=True,
                        key="menu_export_csv_btn",
                    )
                except Exception as e:
                    st.error(f"CSV export failed: {e}")

            if st.button("🔒 Log out", use_container_width=True, key="menu_logout_btn"):
                st.session_state.authenticated = False
                st.session_state.is_admin = False
                st.rerun()
                
# ============================================================
# MAIN APP
# ============================================================
def main() -> None:
    init_session_state()
    render_header_menu()
            
    projects, vendors, categories, phases, line_items = load_lookups()

    if st.session_state.is_admin:
        tab_dashboard, tab_new_txn, tab_txns, tab_reports, tab_vendor = st.tabs(
            [
                "🏠 Project Dashboard",
                "➕ New Transaction",
                "📋 Transactions",
                "📈 Reports",
                "🛠 Vendor Admin",
            ]
        )

        with tab_dashboard:
            render_dashboard_tab(projects, vendors, categories, phases, line_items)

        with tab_new_txn:
            render_new_transaction_tab(
                projects, vendors, categories, phases, line_items
            )

        with tab_txns:
            render_transactions_tab(projects, vendors, categories, phases, line_items)

        with tab_reports:
            render_reports_tab()

        with tab_vendor:
            render_vendor_admin_tab()

    else:
        tab_dashboard, tab_txns, tab_reports = st.tabs(
            [
                "🏠 Project Dashboard",
                "📋 Transactions",
                "📈 Reports",
            ]
        )

        with tab_dashboard:
            render_dashboard_tab(projects, vendors, categories, phases, line_items)

        with tab_txns:
            render_transactions_tab(projects, vendors, categories, phases, line_items)

        with tab_reports:
            render_reports_tab()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        st.error("Something unexpected happened in the app.")
        st.info("Please refresh the page and try again.")
        st.stop()
