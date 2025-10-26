import os
import inspect
import pandas as pd

from jupyter_dash import JupyterDash
from dash import dcc, html, dash_table, Input, Output
import plotly.express as px

# -----------------------------------------------------------------
# CONFIG / CREDENTIALS
# -----------------------------------------------------------------
USERNAME = os.getenv("GS_USERNAME", "marc.ventolra@gmail.com")
PASSWORD = os.getenv("GS_PASSWORD", "Marc12016$")

# -----------------------------------------------------------------
# Import AnimalShelter from Project One code
# -----------------------------------------------------------------
ShelterClass = None
last_import_error = None
for modname in ("CRUD_Python_Module", "gradstore_crud"):
    try:
        module = __import__(modname, fromlist=["AnimalShelter"])
        ShelterClass = getattr(module, "AnimalShelter", None)
        if ShelterClass:
            break
    except Exception as e:
        last_import_error = e

if ShelterClass is None:
    raise RuntimeError(f"Could not import AnimalShelter class. Last import error: {last_import_error}")

# -----------------------------------------------------------------
# Build instance with flexible constructor
# -----------------------------------------------------------------
def try_construct():
    # Try common constructor patterns
    patterns = [
        (),                       # no-arg
        (USERNAME,),              # username only
        (USERNAME, PASSWORD),     # username + password
    ]
    # Also try via signature to avoid obvious mismatches
    sig = inspect.signature(ShelterClass.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    if len(params) == 0 and () not in patterns:
        patterns.insert(0, ())
    for args in patterns:
        try:
            return ShelterClass(*args)
        except Exception:
            continue
    # last resort: call without args
    return ShelterClass()

shelter = try_construct()

# -----------------------------------------------------------------
# Resolve a working "read-like" method and a callable that returns records
# -----------------------------------------------------------------
CANDIDATE_METHODS = [
    "read", "retrieve", "read_all", "readAll",
    "get", "get_all", "find", "fetch", "fetch_all",
    "read_records", "read_all_records", "get_records",
]

def resolve_reader(obj):
    for name in CANDIDATE_METHODS:
        if hasattr(obj, name):
            fn = getattr(obj, name)
            if callable(fn):
                # Test call signatures: with query, with no args
                try:
                    return lambda q: fn(q)
                except TypeError:
                    try:
                        return lambda q: fn()
                    except Exception:
                        pass
    # Try a generic "collection.find"
    if hasattr(obj, "collection") and hasattr(obj.collection, "find"):
        return lambda q: obj.collection.find(q)
    if hasattr(obj, "database") and hasattr(obj.database, "find"):
        return lambda q: obj.database.find(q)
    raise RuntimeError("Could not find a usable read method. Please check CRUD_Python_Module.py and confirm a method exists to retrieve records.")

reader = resolve_reader(shelter)

# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------
def to_dataframe(records):
    try:
        df = pd.DataFrame(list(records))
    except Exception:
        df = pd.DataFrame(records)
    if "_id" in df.columns:
        df["_id"] = df["_id"].astype(str)
    return df

def build_query(animal_type, outcome_type, breed_text, sex_list):
    q = {}
    if animal_type and animal_type != "All":
        q["animal_type"] = animal_type
    if outcome_type and outcome_type != "All":
        q["outcome_type"] = outcome_type
    if breed_text:
        q["breed"] = {"$regex": breed_text, "$options": "i"}
    if sex_list:
        q["sex_upon_outcome"] = {"$in": sex_list}
    return q

# -----------------------------------------------------------------
# Initial fetch
# -----------------------------------------------------------------
try:
    base_df = to_dataframe(reader({}))
    print("✅ Connected and fetched initial data.")
except Exception as e:
    print("❌ Data fetch failed:", e)
    base_df = pd.DataFrame()

EXPECTED_COLS = [
    "_id","name","animal_id","animal_type","breed","color","age_upon_outcome",
    "sex_upon_outcome","outcome_type","outcome_subtype","date_of_birth"
]
for c in EXPECTED_COLS:
    if c not in base_df.columns:
        base_df[c] = None

animal_types = ["All"] + sorted([x for x in base_df["animal_type"].dropna().unique().tolist()]) if "animal_type" in base_df.columns else ["All"]
outcome_types = ["All"] + sorted([x for x in base_df["outcome_type"].dropna().unique().tolist()]) if "outcome_type" in base_df.columns else ["All"]
sex_options = sorted([x for x in base_df["sex_upon_outcome"].dropna().unique().tolist()]) if "sex_upon_outcome" in base_df.columns else []

# -----------------------------------------------------------------
# Dash App
# -----------------------------------------------------------------
app = JupyterDash(__name__)
app.layout = html.Div(
    style={"fontFamily":"Arial, sans-serif","padding":"1rem 2rem"},
    children=[
        html.H2("Grazioso Salvare - Animal Outcomes Dashboard"),
        html.Div(style={"display":"grid","gridTemplateColumns":"repeat(4, 1fr)","gap":"1rem"}, children=[
            html.Div([html.Label("Animal Type"), dcc.Dropdown(id="f-animal", options=[{"label":x,"value":x} for x in animal_types], value="All", clearable=False)]),
            html.Div([html.Label("Outcome Type"), dcc.Dropdown(id="f-outcome", options=[{"label":x,"value":x} for x in outcome_types], value="All", clearable=False)]),
            html.Div([html.Label("Breed contains"), dcc.Input(id="f-breed", type="text", debounce=True, placeholder="Shepherd", style={"width":"100%"})]),
            html.Div([html.Label("Sex Upon Outcome"), dcc.Dropdown(id="f-sex", options=[{"label":x,"value":x} for x in sex_options], multi=True)]),
        ]),
        dash_table.DataTable(
            id="tbl",
            columns=[{"name":c, "id":c} for c in EXPECTED_COLS],
            data=base_df.to_dict("records"),
            page_action="native", page_size=10,
            sort_action="native", filter_action="native",
            row_selectable="single",
            style_table={"overflowX":"auto"},
            style_header={"backgroundColor":"#f0f0f0","fontWeight":"bold"},
            style_cell={"padding":"6px","fontSize":14},
        ),
        html.Div(style={"height":"12px"}),
        dcc.Graph(id="chart"),
    ]
)

@app.callback(
    Output("tbl","data"),
    Input("f-animal","value"),
    Input("f-outcome","value"),
    Input("f-breed","value"),
    Input("f-sex","value"),
)
def update_table(animal, outcome, breed, sex):
    q = build_query(animal, outcome, breed, sex or [])
    try:
        df = to_dataframe(reader(q))
    except Exception as e:
        print("Query error:", e)
        df = pd.DataFrame(columns=EXPECTED_COLS)
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = None
    return df.to_dict("records")

@app.callback(
    Output("chart","figure"),
    Input("tbl","data")
)
def update_chart(rows):
    df = pd.DataFrame(rows)
    if df.empty or "outcome_type" not in df.columns:
        return px.bar(title="Outcome Type Distribution (no data)")
    ct = df["outcome_type"].fillna("Unknown").value_counts().reset_index()
    ct.columns = ["outcome_type","count"]
    fig = px.bar(ct, x="outcome_type", y="count", title="Outcome Type Distribution")
    fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
    return fig

if __name__ == "__main__":
    try:
        get_ipython  # type: ignore  # noqa
        app.run_server(mode="inline", debug=False)
    except Exception:
        app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT",8050)), debug=False)
