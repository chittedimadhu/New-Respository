from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_from_directory,
)
import sqlite3
import os
import secrets
import smtplib

from email.message import EmailMessage
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# APPLICATION CONFIGURATION
# =========================================================

BASE = os.path.dirname(os.path.abspath(__file__))

DB = os.path.join(BASE, "ehs360.db")

UPLOAD = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD, exist_ok=True)

app = Flask(__name__)

app.secret_key = os.environ.get(
    "EHS360_SECRET",
    secrets.token_hex(24)
)

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

ALLOWED = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "pdf",
}


DEPARTMENTS = [
    "Production",
    "Quality",
    "Engineering",
    "EHS",
    "Warehouse",
    "Utilities",
    "HR",
    "IT",
]


# =========================================================
# DATABASE
# =========================================================

def db():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_column(connection, table, column, definition):

    columns = [
        row["name"]
        for row in connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]

    if column not in columns:

        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():

    connection = db()

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS incidents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            location TEXT NOT NULL,
            severity TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            reporter TEXT NOT NULL,
            created_at TEXT NOT NULL,
            attachment TEXT
        );

        CREATE TABLE IF NOT EXISTS actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_ref TEXT,
            title TEXT NOT NULL,
            owner TEXT NOT NULL,
            due_date TEXT,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS permits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT UNIQUE NOT NULL,
            permit_type TEXT NOT NULL,
            area TEXT NOT NULL,
            requester TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sustainability(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            period TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS observations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            department TEXT NOT NULL,
            severity TEXT NOT NULL,
            reporter_username TEXT NOT NULL,
            reporter_name TEXT NOT NULL,
            hod_username TEXT,
            hod_name TEXT,
            hod_email TEXT,
            responsible_username TEXT,
            responsible_name TEXT,
            capa TEXT,
            capa_due_date TEXT,
            closure_comment TEXT,
            closure_evidence TEXT,
            hod_comment TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            hod_reviewed_at TEXT,
            employee_closed_at TEXT,
            hod_approved_at TEXT
        );
        """
    )

    # Add columns to an older users table if they don't exist
    ensure_column(
        connection,
        "users",
        "email",
        "TEXT"
    )

    ensure_column(
        connection,
        "users",
        "department",
        "TEXT"
    )

    # -----------------------------------------------------
    # ADMIN USER
    # -----------------------------------------------------

    admin = connection.execute(
        """
        SELECT id
        FROM users
        WHERE username='admin'
        """
    ).fetchone()

    if not admin:

        connection.execute(
            """
            INSERT INTO users(
                username,
                password,
                name,
                role,
                email,
                department
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                "admin",
                generate_password_hash("ehs360"),
                "EHS Administrator",
                "admin",
                os.environ.get(
                    "ADMIN_EMAIL",
                    "maddhu52@gmail.com"
                ),
                "EHS",
            )
        )

    else:

        connection.execute(
            """
            UPDATE users
            SET email=?,
                department=?
            WHERE username='admin'
            """,
            (
                os.environ.get(
                    "ADMIN_EMAIL",
                    "maddhu52@gmail.com"
                ),
                "EHS",
            )
        )

    # -----------------------------------------------------
    # DEMO EMPLOYEE
    # -----------------------------------------------------

    employee = connection.execute(
        """
        SELECT id
        FROM users
        WHERE username='employee'
        """
    ).fetchone()

    if not employee:

        connection.execute(
            """
            INSERT INTO users(
                username,
                password,
                name,
                role,
                email,
                department
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                "employee",
                generate_password_hash("employee"),
                "Demo Employee",
                "employee",
                "maddhu52@gmail.com",
                "Production",
            )
        )

    else:

        connection.execute(
            """
            UPDATE users
            SET email=?,
                department=?
            WHERE username='employee'
            """,
            (
                "maddhu52@gmail.com",
                "Production",
            )
        )

    # -----------------------------------------------------
    # DEMO PRODUCTION HOD
    # -----------------------------------------------------

    hod = connection.execute(
        """
        SELECT id
        FROM users
        WHERE username='prod_hod'
        """
    ).fetchone()

    if not hod:

        connection.execute(
            """
            INSERT INTO users(
                username,
                password,
                name,
                role,
                email,
                department
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                "prod_hod",
                generate_password_hash("hod123"),
                "Production HOD",
                "hod",
                "maddhu52@gmail.com",
                "Production",
            )
        )

    else:

        # Temporary test configuration:
        # all Production HOD notifications go to your Gmail.
        connection.execute(
            """
            UPDATE users
            SET email=?,
                department=?,
                role=?
            WHERE username='prod_hod'
            """,
            (
                "maddhu52@gmail.com",
                "Production",
                "hod",
            )
        )

    # -----------------------------------------------------
    # DEFAULT SUSTAINABILITY DATA
    # -----------------------------------------------------

    if connection.execute(
        "SELECT COUNT(*) FROM sustainability"
    ).fetchone()[0] == 0:

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        default_data = [
            ("Energy", 11.4, "% reduction"),
            ("Water", 8.2, "% reduction"),
            ("Waste diverted", 76, "%"),
            ("GHG", 18.6, "% reduction"),
        ]

        for metric, value, unit in default_data:

            connection.execute(
                """
                INSERT INTO sustainability(
                    metric,
                    value,
                    unit,
                    period,
                    created_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    metric,
                    value,
                    unit,
                    "Current",
                    now,
                )
            )

    connection.commit()
    connection.close()


# =========================================================
# EMAIL SYSTEM
# =========================================================

def send_email(
    to_address,
    subject,
    body
):

    smtp_host = os.environ.get(
        "SMTP_HOST"
    )

    smtp_user = os.environ.get(
        "SMTP_USER"
    )

    smtp_password = os.environ.get(
        "SMTP_PASSWORD"
    )

    smtp_from = os.environ.get(
        "SMTP_FROM"
    ) or smtp_user

    smtp_port = int(
        os.environ.get(
            "SMTP_PORT",
            "587"
        )
    )

    if (
        not smtp_host
        or not smtp_user
        or not smtp_password
        or not smtp_from
        or not to_address
    ):

        app.logger.warning(
            "Email not sent: SMTP configuration or recipient missing."
        )

        return False

    try:

        message = EmailMessage()

        message["From"] = smtp_from
        message["To"] = to_address
        message["Subject"] = subject

        message.set_content(body)

        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=30
        ) as smtp:

            smtp.starttls()

            smtp.login(
                smtp_user,
                smtp_password
            )

            smtp.send_message(
                message
            )

        app.logger.info(
            "Email sent successfully to %s",
            to_address
        )

        return True

    except Exception:

        app.logger.exception(
            "EHS360 email delivery failed."
        )

        return False


# =========================================================
# LOGIN
# =========================================================

def login_required():

    return "user" in session


@app.context_processor
def inject_current_user():

    return {
        "current_user": session.get("user")
    }


@app.route(
    "/",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        connection = db()

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE username=?
            """,
            (
                username,
            )
        ).fetchone()

        connection.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user"] = {

                "username":
                    user["username"],

                "name":
                    user["name"],

                "role":
                    user["role"],

                "email":
                    user["email"]
                    if "email" in user.keys()
                    else "",

                "department":
                    user["department"]
                    if "department" in user.keys()
                    else "",
            }

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid username or password.",
            "error"
        )

    return render_template(
        "login.html"
    )


@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    stats = {

        "incidents":
            connection.execute(
                "SELECT COUNT(*) FROM incidents"
            ).fetchone()[0],

        "open_actions":
            connection.execute(
                """
                SELECT COUNT(*)
                FROM actions
                WHERE status!='Closed'
                """
            ).fetchone()[0],

        "permits":
            connection.execute(
                """
                SELECT COUNT(*)
                FROM permits
                WHERE status IN ('Pending','Active')
                """
            ).fetchone()[0],

        "reports":
            connection.execute(
                """
                SELECT COUNT(*)
                FROM incidents
                WHERE status='New'
                """
            ).fetchone()[0],
    }

    recent = connection.execute(
        """
        SELECT *
        FROM incidents
        ORDER BY id DESC
        LIMIT 6
        """
    ).fetchall()

    actions = connection.execute(
        """
        SELECT *
        FROM actions
        WHERE status!='Closed'
        ORDER BY due_date
        LIMIT 6
        """
    ).fetchall()

    connection.close()

    return render_template(
        "dashboard.html",
        stats=stats,
        recent=recent,
        actions=actions,
    )


# =========================================================
# INCIDENT REPORTING
# =========================================================

@app.route(
    "/report",
    methods=["GET", "POST"]
)
def report():

    if not login_required():

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        event_type = request.form.get(
            "event_type",
            "Incident"
        )

        title = request.form.get(
            "title",
            ""
        ).strip()

        location = request.form.get(
            "location",
            ""
        ).strip()

        severity = request.form.get(
            "severity",
            "Medium"
        )

        description = request.form.get(
            "description",
            ""
        ).strip()

        if (
            not title
            or not location
            or not description
        ):

            flash(
                "Title, location and description are required.",
                "error"
            )

            return render_template(
                "report.html"
            )

        connection = db()

        number = connection.execute(
            """
            SELECT COALESCE(MAX(id),0)+1
            FROM incidents
            """
        ).fetchone()[0]

        reference = f"INC-{number:04d}"

        uploaded_file = request.files.get(
            "attachment"
        )

        filename = ""

        if (
            uploaded_file
            and uploaded_file.filename
        ):

            extension = (
                uploaded_file.filename
                .rsplit(".", 1)[-1]
                .lower()
            )

            if extension not in ALLOWED:

                flash(
                    "Unsupported attachment type.",
                    "error"
                )

                connection.close()

                return render_template(
                    "report.html"
                )

            filename = (
                f"{reference}_"
                f"{secure_filename(uploaded_file.filename)}"
            )

            uploaded_file.save(
                os.path.join(
                    UPLOAD,
                    filename
                )
            )

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        connection.execute(
            """
            INSERT INTO incidents(
                ref,
                event_type,
                title,
                location,
                severity,
                description,
                status,
                reporter,
                created_at,
                attachment
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                reference,
                event_type,
                title,
                location,
                severity,
                description,
                "New",
                session["user"]["name"],
                now,
                filename,
            )
        )

        connection.commit()
        connection.close()

        flash(
            f"Report {reference} submitted successfully.",
            "success"
        )

        return redirect(
            url_for("incidents")
        )

    return render_template(
        "report.html"
    )


# =========================================================
# INCIDENT REGISTER
# =========================================================

@app.route("/incidents")
def incidents():

    if not login_required():

        return redirect(
            url_for("login")
        )

    search = request.args.get(
        "q",
        ""
    ).strip()

    connection = db()

    if search:

        rows = connection.execute(
            """
            SELECT *
            FROM incidents
            WHERE ref LIKE ?
               OR title LIKE ?
               OR event_type LIKE ?
            ORDER BY id DESC
            """,
            (
                f"%{search}%",
                f"%{search}%",
                f"%{search}%",
            )
        ).fetchall()

    else:

        rows = connection.execute(
            """
            SELECT *
            FROM incidents
            ORDER BY id DESC
            """
        ).fetchall()

    connection.close()

    return render_template(
        "incidents.html",
        rows=rows,
        q=search,
    )


@app.route(
    "/incidents/<int:incident_id>/status",
    methods=["POST"]
)
def incident_status(
    incident_id
):

    if (
        not login_required()
        or session["user"]["role"]
        not in ("admin", "ehs")
    ):

        return redirect(
            url_for("incidents")
        )

    status = request.form.get(
        "status",
        "Investigation"
    )

    connection = db()

    connection.execute(
        """
        UPDATE incidents
        SET status=?
        WHERE id=?
        """,
        (
            status,
            incident_id,
        )
    )

    connection.commit()
    connection.close()

    flash(
        "Incident status updated.",
        "success"
    )

    return redirect(
        url_for("incidents")
    )


# =========================================================
# CAPA / ACTIONS
# =========================================================

@app.route(
    "/actions",
    methods=["GET", "POST"]
)
def actions():

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    if request.method == "POST":

        connection.execute(
            """
            INSERT INTO actions(
                incident_ref,
                title,
                owner,
                due_date,
                priority,
                status,
                created_at
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                request.form.get(
                    "incident_ref",
                    ""
                ),

                request.form["title"],

                request.form["owner"],

                request.form.get(
                    "due_date",
                    ""
                ),

                request.form.get(
                    "priority",
                    "Medium"
                ),

                "Open",

                datetime.now().strftime(
                    "%Y-%m-%d %H:%M"
                ),
            )
        )

        connection.commit()

        flash(
            "CAPA/action created.",
            "success"
        )

    rows = connection.execute(
        """
        SELECT *
        FROM actions
        ORDER BY
            CASE
                WHEN status='Open'
                THEN 0
                ELSE 1
            END,
            due_date
        """
    ).fetchall()

    connection.close()

    return render_template(
        "actions.html",
        rows=rows
    )


@app.route(
    "/actions/<int:action_id>/close",
    methods=["POST"]
)
def close_action(
    action_id
):

    if not login_required():

        return redirect(
            url_for("actions")
        )

    connection = db()

    connection.execute(
        """
        UPDATE actions
        SET status='Closed'
        WHERE id=?
        """,
        (
            action_id,
        )
    )

    connection.commit()
    connection.close()

    flash(
        "Action closed.",
        "success"
    )

    return redirect(
        url_for("actions")
    )


# =========================================================
# PERMIT TO WORK
# =========================================================

@app.route(
    "/ptw",
    methods=["GET", "POST"]
)
def ptw():

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    if request.method == "POST":

        number = connection.execute(
            """
            SELECT COALESCE(MAX(id),0)+1
            FROM permits
            """
        ).fetchone()[0]

        reference = f"PTW-{number:04d}"

        connection.execute(
            """
            INSERT INTO permits(
                ref,
                permit_type,
                area,
                requester,
                status,
                created_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                reference,
                request.form["permit_type"],
                request.form["area"],
                session["user"]["name"],
                "Pending",
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M"
                ),
            )
        )

        connection.commit()

        flash(
            f"{reference} created.",
            "success"
        )

    rows = connection.execute(
        """
        SELECT *
        FROM permits
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    return render_template(
        "ptw.html",
        rows=rows
    )


@app.route(
    "/ptw/<int:permit_id>/status",
    methods=["POST"]
)
def permit_status(
    permit_id
):

    if not login_required():

        return redirect(
            url_for("ptw")
        )

    status = request.form.get(
        "status",
        "Active"
    )

    connection = db()

    connection.execute(
        """
        UPDATE permits
        SET status=?
        WHERE id=?
        """,
        (
            status,
            permit_id,
        )
    )

    connection.commit()
    connection.close()

    flash(
        "Permit status updated.",
        "success"
    )

    return redirect(
        url_for("ptw")
    )


# =========================================================
# SUSTAINABILITY
# =========================================================

@app.route(
    "/sustainability",
    methods=["GET", "POST"]
)
def sustainability():

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    if request.method == "POST":

        connection.execute(
            """
            INSERT INTO sustainability(
                metric,
                value,
                unit,
                period,
                created_at
            )
            VALUES(?,?,?,?,?)
            """,
            (
                request.form["metric"],
                float(
                    request.form["value"]
                ),
                request.form["unit"],
                request.form["period"],
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M"
                ),
            )
        )

        connection.commit()

        flash(
            "Sustainability data saved.",
            "success"
        )

    rows = connection.execute(
        """
        SELECT *
        FROM sustainability
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    return render_template(
        "sustainability.html",
        rows=rows
    )


# =========================================================
# TRAINING
# =========================================================

@app.route("/training")
def training():

    if not login_required():

        return redirect(
            url_for("login")
        )

    return render_template(
        "training.html"
    )


# =========================================================
# EHS OBSERVATIONS
# =========================================================

def get_hod_for_department(
    connection,
    department
):

    hod = connection.execute(
        """
        SELECT *
        FROM users
        WHERE role='hod'
          AND department=?
        ORDER BY id
        LIMIT 1
        """,
        (
            department,
        )
    ).fetchone()

    if not hod:

        hod = connection.execute(
            """
            SELECT *
            FROM users
            WHERE role IN ('ehs','admin')
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()

    return hod


@app.route(
    "/observations",
    methods=["GET", "POST"]
)
def observations():

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    # -----------------------------------------------------
    # SUBMIT OBSERVATION
    # -----------------------------------------------------

    if request.method == "POST":

        category = request.form.get(
            "category",
            "Unsafe Condition"
        ).strip()

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        location = request.form.get(
            "location",
            ""
        ).strip()

        department = request.form.get(
            "department",
            ""
        ).strip()

        severity = request.form.get(
            "severity",
            "Medium"
        ).strip()

        if (
            not title
            or not description
            or not location
            or not department
        ):

            connection.close()

            flash(
                "Title, description, location and department are required.",
                "error"
            )

            return redirect(
                url_for("observations")
            )

        number = connection.execute(
            """
            SELECT COALESCE(MAX(id),0)+1
            FROM observations
            """
        ).fetchone()[0]

        reference = f"OBS-{number:04d}"

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        hod = get_hod_for_department(
            connection,
            department
        )

        if hod:

            hod_username = hod["username"]
            hod_name = hod["name"]
            hod_email = hod["email"] or ""

        else:

            hod_username = ""
            hod_name = ""
            hod_email = ""

        connection.execute(
            """
            INSERT INTO observations(
                ref,
                category,
                title,
                description,
                location,
                department,
                severity,
                reporter_username,
                reporter_name,
                hod_username,
                hod_name,
                hod_email,
                status,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                reference,
                category,
                title,
                description,
                location,
                department,
                severity,
                session["user"]["username"],
                session["user"]["name"],
                hod_username,
                hod_name,
                hod_email,
                "Pending HOD Review",
                now,
            )
        )

        connection.commit()
        connection.close()

        # -----------------------------------------------
        # EMAIL TO HOD
        # -----------------------------------------------

        if hod_email:

            send_email(
                hod_email,
                f"EHS360 Observation {reference} - HOD Review Required",
                f"""
Dear {hod_name},

A new EHS observation has been reported and requires your review.

Observation: {reference}
Category: {category}
Title: {title}
Department: {department}
Location: {location}
Severity: {severity}
Reported By: {session["user"]["name"]}
Date: {now}

Please log in to EHS360 and review the observation and assign the required CAPA.

EHS360 Management Portal
"""
            )

        flash(
            f"{reference} submitted successfully. Status: Pending HOD Review.",
            "success"
        )

        return redirect(
            url_for("observations")
        )

    # -----------------------------------------------------
    # OBSERVATION LIST
    # -----------------------------------------------------

    rows = connection.execute(
        """
        SELECT *
        FROM observations
        WHERE reporter_username=?
           OR responsible_username=?
           OR hod_username=?
           OR ? IN ('admin','ehs')
        ORDER BY id DESC
        """,
        (
            session["user"]["username"],
            session["user"]["username"],
            session["user"]["username"],
            session["user"]["role"],
        )
    ).fetchall()

    # -----------------------------------------------------
    # HOD REVIEW QUEUE
    # -----------------------------------------------------

    pending_review = connection.execute(
        """
        SELECT *
        FROM observations
        WHERE hod_username=?
          AND status='Pending HOD Review'
        ORDER BY id DESC
        """,
        (
            session["user"]["username"],
        )
    ).fetchall()

    # -----------------------------------------------------
    # HOD APPROVAL QUEUE
    # -----------------------------------------------------

    pending_approval = connection.execute(
        """
        SELECT *
        FROM observations
        WHERE hod_username=?
          AND status='Pending HOD Approval'
        ORDER BY id DESC
        """,
        (
            session["user"]["username"],
        )
    ).fetchall()

    # -----------------------------------------------------
    # EMPLOYEE CAPA QUEUE
    # -----------------------------------------------------

    assigned = connection.execute(
        """
        SELECT *
        FROM observations
        WHERE responsible_username=?
          AND status IN (
              'CAPA Assigned',
              'Rework Required'
          )
        ORDER BY id DESC
        """,
        (
            session["user"]["username"],
        )
    ).fetchall()

    # -----------------------------------------------------
    # EMPLOYEE LIST FOR HOD
    # -----------------------------------------------------

    employees = []

    if session["user"]["role"] in (
        "hod",
        "ehs",
        "admin",
    ):

        department = session["user"].get(
            "department",
            ""
        )

        if (
            session["user"]["role"] == "hod"
            and department
        ):

            employees = connection.execute(
                """
                SELECT
                    username,
                    name,
                    department,
                    email
                FROM users
                WHERE role='employee'
                  AND department=?
                ORDER BY name
                """,
                (
                    department,
                )
            ).fetchall()

        else:

            employees = connection.execute(
                """
                SELECT
                    username,
                    name,
                    department,
                    email
                FROM users
                WHERE role IN (
                    'employee',
                    'hod',
                    'ehs'
                )
                ORDER BY department,name
                """
            ).fetchall()

    connection.close()

    return render_template(
        "observations.html",
        rows=rows,
        pending_review=pending_review,
        pending_approval=pending_approval,
        assigned=assigned,
        employees=employees,
        departments=DEPARTMENTS,
    )


# =========================================================
# HOD REVIEWS OBSERVATION AND ASSIGNS CAPA
# =========================================================

@app.route(
    "/observations/<int:observation_id>/review",
    methods=["POST"]
)
def observation_review(
    observation_id
):

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    observation = connection.execute(
        """
        SELECT *
        FROM observations
        WHERE id=?
        """,
        (
            observation_id,
        )
    ).fetchone()

    if not observation:

        connection.close()

        flash(
            "Observation not found.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    allowed = (
        session["user"]["role"]
        in ("admin", "ehs")
        or
        session["user"]["username"]
        == observation["hod_username"]
    )

    if not allowed:

        connection.close()

        flash(
            "You are not authorized to review this observation.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    responsible_username = request.form.get(
        "responsible_username",
        ""
    ).strip()

    capa = request.form.get(
        "capa",
        ""
    ).strip()

    due_date = request.form.get(
        "capa_due_date",
        ""
    ).strip()

    employee = connection.execute(
        """
        SELECT *
        FROM users
        WHERE username=?
        """,
        (
            responsible_username,
        )
    ).fetchone()

    if (
        not employee
        or not capa
        or not due_date
    ):

        connection.close()

        flash(
            "Select a responsible employee and enter CAPA and due date.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    connection.execute(
        """
        UPDATE observations
        SET responsible_username=?,
            responsible_name=?,
            capa=?,
            capa_due_date=?,
            status='CAPA Assigned',
            hod_reviewed_at=?
        WHERE id=?
        """,
        (
            employee["username"],
            employee["name"],
            capa,
            due_date,
            now,
            observation_id,
        )
    )

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # EMAIL TO RESPONSIBLE EMPLOYEE
    # -----------------------------------------------------

    if employee["email"]:

        send_email(
            employee["email"],
            f"EHS360 CAPA Assigned - {observation['ref']}",
            f"""
Dear {employee['name']},

A CAPA has been assigned to you through EHS360.

Observation: {observation['ref']}
Title: {observation['title']}
Department: {observation['department']}
Location: {observation['location']}
Severity: {observation['severity']}

CAPA:
{capa}

Due Date:
{due_date}

Please complete the action and submit closure evidence in EHS360.

Regards,
EHS360
"""
        )

    flash(
        f"{observation['ref']} reviewed and CAPA assigned to {employee['name']}.",
        "success"
    )

    return redirect(
        url_for("observations")
    )


# =========================================================
# EMPLOYEE CLOSES CAPA
# =========================================================

@app.route(
    "/observations/<int:observation_id>/close",
    methods=["POST"]
)
def observation_close(
    observation_id
):

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    observation = connection.execute(
        """
        SELECT *
        FROM observations
        WHERE id=?
        """,
        (
            observation_id,
        )
    ).fetchone()

    if not observation:

        connection.close()

        flash(
            "Observation not found.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    allowed = (
        session["user"]["username"]
        == observation["responsible_username"]
        or
        session["user"]["role"]
        in ("admin", "ehs")
    )

    if not allowed:

        connection.close()

        flash(
            "You are not authorized to close this CAPA.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    closure_comment = request.form.get(
        "closure_comment",
        ""
    ).strip()

    uploaded_file = request.files.get(
        "closure_evidence"
    )

    evidence = (
        observation["closure_evidence"]
        or ""
    )

    if not closure_comment:

        connection.close()

        flash(
            "Closure comment is required.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    if (
        uploaded_file
        and uploaded_file.filename
    ):

        extension = (
            uploaded_file.filename
            .rsplit(".", 1)[-1]
            .lower()
        )

        if extension not in ALLOWED:

            connection.close()

            flash(
                "Unsupported closure evidence file type.",
                "error"
            )

            return redirect(
                url_for("observations")
            )

        evidence = (
            f"{observation['ref']}_closure_"
            f"{secure_filename(uploaded_file.filename)}"
        )

        uploaded_file.save(
            os.path.join(
                UPLOAD,
                evidence
            )
        )

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    connection.execute(
        """
        UPDATE observations
        SET closure_comment=?,
            closure_evidence=?,
            status='Pending HOD Approval',
            employee_closed_at=?
        WHERE id=?
        """,
        (
            closure_comment,
            evidence,
            now,
            observation_id,
        )
    )

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # EMAIL TO HOD
    # -----------------------------------------------------

    if observation["hod_email"]:

        send_email(
            observation["hod_email"],
            f"EHS360 Observation {observation['ref']} - Closure Approval Required",
            f"""
Dear {observation['hod_name'] or 'HOD'},

The responsible employee has completed the CAPA for observation {observation['ref']}.

Observation:
{observation['title']}

Department:
{observation['department']}

Responsible Employee:
{observation['responsible_name']}

Closure Comment:
{closure_comment}

Please log in to EHS360 and approve or reject the closure.

Regards,
EHS360
"""
        )

    flash(
        f"{observation['ref']} submitted for HOD approval.",
        "success"
    )

    return redirect(
        url_for("observations")
    )


# =========================================================
# HOD APPROVES OR REJECTS CAPA
# =========================================================

@app.route(
    "/observations/<int:observation_id>/approve",
    methods=["POST"]
)
def observation_approve(
    observation_id
):

    if not login_required():

        return redirect(
            url_for("login")
        )

    connection = db()

    observation = connection.execute(
        """
        SELECT *
        FROM observations
        WHERE id=?
        """,
        (
            observation_id,
        )
    ).fetchone()

    if not observation:

        connection.close()

        flash(
            "Observation not found.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    allowed = (
        session["user"]["role"]
        in ("admin", "ehs")
        or
        session["user"]["username"]
        == observation["hod_username"]
    )

    if not allowed:

        connection.close()

        flash(
            "You are not authorized to approve this closure.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    decision = request.form.get(
        "decision",
        "approve"
    )

    hod_comment = request.form.get(
        "hod_comment",
        ""
    ).strip()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    if decision == "approve":

        status = "Closed"

        connection.execute(
            """
            UPDATE observations
            SET status=?,
                hod_comment=?,
                hod_approved_at=?
            WHERE id=?
            """,
            (
                status,
                hod_comment,
                now,
                observation_id,
            )
        )

        result_message = (
            f"{observation['ref']} approved and closed."
        )

    else:

        status = "Rework Required"

        connection.execute(
            """
            UPDATE observations
            SET status=?,
                hod_comment=?
            WHERE id=?
            """,
            (
                status,
                hod_comment,
                observation_id,
            )
        )

        result_message = (
            f"{observation['ref']} returned for rework."
        )

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # EMAIL RESPONSIBLE EMPLOYEE
    # -----------------------------------------------------

    if observation["responsible_username"]:

        connection2 = db()

        employee = connection2.execute(
            """
            SELECT email,name
            FROM users
            WHERE username=?
            """,
            (
                observation["responsible_username"],
            )
        ).fetchone()

        connection2.close()

        if employee and employee["email"]:

            if status == "Closed":

                employee_message = f"""
Dear {employee['name']},

Observation {observation['ref']} has been reviewed and APPROVED by the Department HOD.

The observation is now CLOSED.

HOD Comment:
{hod_comment or 'CAPA verified and approved.'}

Regards,
EHS360
"""

            else:

                employee_message = f"""
Dear {employee['name']},

Observation {observation['ref']} has been reviewed by the Department HOD and returned for REWORK.

HOD Comment:
{hod_comment or 'Please review the observation and complete the required rework.'}

Regards,
EHS360
"""

            send_email(
                employee["email"],
                f"EHS360 Observation {observation['ref']} - {status}",
                employee_message
            )

    # -----------------------------------------------------
    # EMAIL REPORTER
    # -----------------------------------------------------

    if (
        observation["reporter_username"]
        and
        observation["reporter_username"]
        != observation["responsible_username"]
    ):

        connection3 = db()

        reporter = connection3.execute(
            """
            SELECT email,name
            FROM users
            WHERE username=?
            """,
            (
                observation["reporter_username"],
            )
        ).fetchone()

        connection3.close()

        if reporter and reporter["email"]:

            reporter_message = f"""
Dear {reporter['name']},

Your EHS observation {observation['ref']} has been reviewed by the Department HOD.

Final Status:
{status}

HOD Comment:
{hod_comment or 'No additional comment.'}

Regards,
EHS360
"""

            send_email(
                reporter["email"],
                f"EHS360 Observation {observation['ref']} - {status}",
                reporter_message
            )

    flash(
        result_message,
        "success"
    )

    return redirect(
        url_for("observations")
    )


# =========================================================
# FILE UPLOADS
# =========================================================

@app.route(
    "/uploads/<filename>"
)
def uploaded(
    filename
):

    if not login_required():

        return "", 403

    return send_from_directory(
        UPLOAD,
        filename
    )


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

init_db()


# =========================================================
# LOCAL DEVELOPMENT
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False
    )
