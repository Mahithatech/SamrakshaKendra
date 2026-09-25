import gradio as gr
import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "http://127.0.0.1:8000"


# ============================================================
# BACKEND API FUNCTIONS
# ============================================================

def get_hospital_count():
    try:
        response = requests.get(
            f"{API_URL}/hospitals/count",
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            if isinstance(data, dict):
                return str(data.get("count", 0))

            return str(data)

        return "API Error"

    except Exception as e:
        return "Offline"


def get_disease_count():
    try:
        response = requests.get(
            f"{API_URL}/diseases/count",
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            if isinstance(data, dict):
                return str(data.get("count", 0))

            return str(data)

        return "API Error"

    except Exception:
        return "Offline"


def get_diseases():
    try:
        response = requests.get(
            f"{API_URL}/diseases",
            timeout=15
        )

        if response.status_code != 200:
            return [[
                "-",
                f"API Error: {response.status_code}",
                "-",
                "-"
            ]]

        diseases = response.json()

        if not diseases:
            return []

        rows = []

        for disease in diseases:
            rows.append([
                disease.get("id"),
                disease.get("name"),
                disease.get("category"),
                disease.get("description")
            ])

        return rows

    except Exception as e:
        return [[
            "-",
            "Connection Error",
            "-",
            str(e)
        ]]


def search_hospitals(
    search="",
    state="",
    district="",
    category="",
    limit=20
):
    try:

        params = {
            "search": search or None,
            "state": state or None,
            "district": district or None,
            "category": category or None,
            "limit": int(limit)
        }

        params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }

        response = requests.get(
            f"{API_URL}/hospitals",
            params=params,
            timeout=15
        )

        if response.status_code != 200:
            return [[
                "-",
                f"API Error: {response.status_code}",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-"
            ]]

        hospitals = response.json()

        if not hospitals:
            return []

        rows = []

        for hospital in hospitals:

            rows.append([
                hospital.get("id"),
                hospital.get("name"),
                hospital.get("state"),
                hospital.get("district"),
                hospital.get("city"),
                hospital.get("category"),
                hospital.get("pincode"),
                hospital.get("phone")
            ])

        return rows

    except Exception as e:

        return [[
            "-",
            "Connection Error",
            str(e),
            "-",
            "-",
            "-",
            "-",
            "-"
        ]]


# ============================================================
# LOGIN / LOGOUT
# ============================================================

def login(username, password):

    if username == "admin" and password == "admin123":

        return (
            """
            ### ✅ Login successful

            Welcome, **Admin**!
            """,
            gr.update(visible=True),
            gr.update(visible=False)
        )

    return (
        """
        ### ❌ Invalid username or password

        Please check your credentials.
        """,
        gr.update(visible=False),
        gr.update(visible=True)
    )


def logout():

    return (
        "You have been logged out.",
        gr.update(visible=False),
        gr.update(visible=True)
    )


# ============================================================
# CUSTOM CSS
# ============================================================

CSS = """

body {
    background: #f5f7fb;
}

.gradio-container {
    max-width: 1450px !important;
    margin: auto !important;
}

#login-box {
    max-width: 500px;
    margin: 80px auto;
}

.dashboard-title {
    font-size: 34px;
    font-weight: 700;
}

.dashboard-subtitle {
    color: #667085;
    font-size: 16px;
}

.stat-card {
    border-radius: 16px !important;
    padding: 18px !important;
    border: 1px solid #e5e7eb !important;
    background: white !important;
}

.section-title {
    font-size: 25px;
    font-weight: 700;
}

"""

# ============================================================
# GRADIO APPLICATION
# ============================================================

with gr.Blocks(
    title="Samraksha Kendra",
    css=CSS
) as app:

    # ========================================================
    # LOGIN PAGE
    # ========================================================

    login_page = gr.Column(
        visible=True,
        elem_id="login-box"
    )

    with login_page:

        gr.Markdown(
            """
            # 🏥 Samraksha Kendra

            ## Digital Disease Surveillance & Early Warning System

            Secure access to hospital and disease surveillance
            information.
            """
        )

        username = gr.Textbox(
            label="Username",
            placeholder="Enter username"
        )

        password = gr.Textbox(
            label="Password",
            placeholder="Enter password",
            type="password"
        )

        login_button = gr.Button(
            "🔐 Login",
            variant="primary"
        )

        login_message = gr.Markdown()


    # ========================================================
    # DASHBOARD
    # ========================================================

    dashboard = gr.Column(
        visible=False
    )

    with dashboard:

        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        gr.Markdown(
            """
            # Samraksha Kendra

            ## Digital Disease Surveillance & Early Warning System

            <div class="dashboard-subtitle">

            Welcome, **Admin**

            <br>

            Here's what's happening with disease surveillance
            across India.

            </div>
            """
        )

        gr.Markdown("---")


        # ====================================================
        # STATISTICS
        # ====================================================

        with gr.Row():

            # ------------------------------------------------
            # HOSPITALS
            # ------------------------------------------------

            with gr.Column(
                elem_classes=["stat-card"]
            ):

                gr.Markdown(
                    """
                    ### 🏥 Total Hospitals
                    """
                )

                hospital_count = gr.Textbox(
                    value=get_hospital_count(),
                    show_label=False,
                    interactive=False
                )

                gr.Markdown(
                    "Imported hospital data from PostgreSQL"
                )


            # ------------------------------------------------
            # DISEASES
            # ------------------------------------------------

            with gr.Column(
                elem_classes=["stat-card"]
            ):

                gr.Markdown(
                    """
                    ### 🦠 Total Diseases
                    """
                )

                disease_count = gr.Textbox(
                    value=get_disease_count(),
                    show_label=False,
                    interactive=False
                )

                gr.Markdown(
                    "Diseases available in PostgreSQL database"
                )


            # ------------------------------------------------
            # SURVEILLANCE
            # ------------------------------------------------

            with gr.Column(
                elem_classes=["stat-card"]
            ):

                gr.Markdown(
                    """
                    ### 📋 Surveillance Records
                    """
                )

                gr.Markdown(
                    """
                    **Coming Next**
                    """
                )

                gr.Markdown(
                    "Hospital disease reporting database"
                )


            # ------------------------------------------------
            # ALERTS
            # ------------------------------------------------

            with gr.Column(
                elem_classes=["stat-card"]
            ):

                gr.Markdown(
                    """
                    ### 🚨 Active Alerts
                    """
                )

                gr.Markdown(
                    """
                    **Coming Next**
                    """
                )

                gr.Markdown(
                    "Early warning system"
                )


        gr.Markdown("---")


        # ====================================================
        # HOSPITAL SEARCH
        # ====================================================

        gr.Markdown(
            """
            ## 🏥 Hospital Search

            Search and explore hospitals from the PostgreSQL
            hospital database.
            """
        )

        with gr.Row():

            search = gr.Textbox(
                label="Hospital Name",
                placeholder="Example: Care Hospital"
            )

            state = gr.Textbox(
                label="State",
                placeholder="Example: Karnataka"
            )


        with gr.Row():

            district = gr.Textbox(
                label="District",
                placeholder="Example: Bengaluru"
            )

            category = gr.Textbox(
                label="Category",
                placeholder="Example: Private"
            )

            limit = gr.Number(
                label="Number of Results",
                value=20,
                minimum=1,
                maximum=100
            )


        search_button = gr.Button(
            "🔍 Search Hospitals",
            variant="primary"
        )


        hospital_results = gr.Dataframe(
            headers=[
                "ID",
                "Hospital Name",
                "State",
                "District",
                "City",
                "Category",
                "Pincode",
                "Phone"
            ],
            datatype=[
                "number",
                "str",
                "str",
                "str",
                "str",
                "str",
                "str"
            ],
            interactive=False
        )


        search_button.click(
            fn=search_hospitals,
            inputs=[
                search,
                state,
                district,
                category,
                limit
            ],
            outputs=hospital_results
        )


        gr.Markdown("---")


        # ====================================================
        # DISEASE DATABASE
        # ====================================================

        gr.Markdown(
            """
            ## 🦠 Disease Database

            Diseases currently available in the PostgreSQL
            surveillance database.
            """
        )


        disease_refresh_button = gr.Button(
            "🔄 Load Diseases",
            variant="primary"
        )


        disease_results = gr.Dataframe(
            headers=[
                "ID",
                "Disease Name",
                "Category",
                "Description"
            ],
            datatype=[
                "number",
                "str",
                "str",
                "str"
            ],
            interactive=False,
            wrap=True
        )


        disease_refresh_button.click(
            fn=get_diseases,
            inputs=[],
            outputs=disease_results
        )


        gr.Markdown("---")


        # ====================================================
        # FUTURE SURVEILLANCE MODULE
        # ====================================================

        gr.Markdown(
            """
            ## 📋 Disease Surveillance

            The surveillance module will connect hospitals with
            disease records and case information.
            """
        )


        with gr.Row():

            gr.Button(
                "🦠 Diseases"
            )

            gr.Button(
                "📋 Surveillance Records"
            )

            gr.Button(
                "🚨 Alerts"
            )


        gr.Markdown("---")


        # ====================================================
        # FUTURE DASHBOARD MODULES
        # ====================================================

        gr.Markdown(
            """
            ## 🗺️ Disease Hotspots

            **Coming in the next implementation stage**

            Hospital locations and disease case counts will be
            used to identify and visualize disease hotspots.
            """
        )


        gr.Markdown(
            """
            ## 📰 Latest Disease Activity

            **Coming in the next implementation stage**

            Recent surveillance records will be displayed here
            with disease, hospital, location, cases and date.
            """
        )


        gr.Markdown(
            """
            ## 📊 Analytics

            **Coming in the next implementation stage**

            Disease trends, case distribution and alert statistics
            will be visualized using dashboard charts.
            """
        )


        gr.Markdown("---")


        # ====================================================
        # LOGOUT
        # ====================================================

        logout_button = gr.Button(
            "🚪 Logout",
            variant="stop"
        )


    # ========================================================
    # EVENTS
    # ========================================================

    login_button.click(
        fn=login,
        inputs=[
            username,
            password
        ],
        outputs=[
            login_message,
            dashboard,
            login_page
        ]
    )


    logout_button.click(
        fn=logout,
        outputs=[
            login_message,
            dashboard,
            login_page
        ]
    )


# ============================================================
# LAUNCH
# ============================================================

app.launch()