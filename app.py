from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import sqlite3, os, secrets, smtplib
from email.message import EmailMessage
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "ehs360.db")
UPLOAD = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("EHS360_SECRET", secrets.token_hex(24))
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

ALLOWED = {"png", "jpg", "jpeg", "webp", "pdf"}

DEPARTMENTS = [
    "Production",
    "Quality",
    "Engineering",
    "EHS",
    "Warehouse",
    "Utilities",
    "HR",
    "IT"
]


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def ensure_column(c, table, column, definition):
    columns = [
        row["name"]
        for row in c.execute(f"PRAGMA table_info({table})").fetchall()
    ]

    if column not in columns:
        c.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    c = db()

    c.executescript("""
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
    """)

    ensure_column(c, "users", "email", "TEXT")
    ensure_column(c, "users", "department", "TEXT")

    admin = c.execute(
        "SELECT id FROM users WHERE username='admin'"
    ).fetchone()

    if not admin:
        c.execute(
            """
            INSERT INTO users(
                username,password,name,role,email,department
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
                    "admin@ehs360.local"
                ),
                "EHS"
            )
        )
    else:
        c.execute(
            """
            UPDATE users
            SET email=COALESCE(email,?),
                department=COALESCE(department,?)
            WHERE username='admin'
            """,
            (
                os.environ.get(
                    "ADMIN_EMAIL",
                    "admin@ehs360.local"
                ),
                "EHS"
            )
        )

    employee = c.execute(
        "SELECT id FROM users WHERE username='employee'"
    ).fetchone()

    if not employee:
        c.execute(
            """
            INSERT INTO users(
                username,password,name,role,email,department
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                "employee",
                generate_password_hash("employee"),
                "Demo Employee",
                "employee",
                "employee@ehs360.local",
                "Production"
            )
        )
    else:
        c.execute(
            """
            UPDATE users
            SET email=COALESCE(email,?),
                department=COALESCE(department,?)
            WHERE username='employee'
            """,
            (
                "employee@ehs360.local",
                "Production"
            )
        )

    hod = c.execute(
        "SELECT id FROM users WHERE username='prod_hod'"
    ).fetchone()

    if not hod:
        c.execute(
            """
            INSERT INTO users(
                username,password,name,role,email,department
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                "prod_hod",
                generate_password_hash("hod123"),
                "Production HOD",
                "hod",
                "production.hod@ehs360.local",
                "Production"
            )
        )

    if c.execute(
        "SELECT COUNT(*) FROM sustainability"
    ).fetchone()[0] == 0:

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        for metric, value, unit in [
            ("Energy", 11.4, "% reduction"),
            ("Water", 8.2, "% reduction"),
            ("Waste diverted", 76, "%"),
            ("GHG", 18.6, "% reduction")
        ]:

            c.execute(
                """
                INSERT INTO sustainability(
                    metric,value,unit,period,created_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    metric,
                    value,
                    unit,
                    "Current",
                    now
                )
            )

    c.commit()
    c.close()


def send_email(to_address, subject, body):

    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM") or user
    port = int(os.environ.get("SMTP_PORT", "587"))

    if not host or not user or not password or not sender or not to_address:
        app.logger.info(
            "Email not sent: SMTP is not configured or recipient is missing."
        )
        return False

    try:

        msg = EmailMessage()

        msg["From"] = sender
        msg["To"] = to_address
        msg["Subject"] = subject

        msg.set_content(body)

        with smtplib.SMTP(
            host,
            port,
            timeout=20
        ) as smtp:

            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)

        return True

    except Exception:

        app.logger.exception(
            "EHS360 email delivery failed"
        )

        return False


def login_required():
    return "user" in session


@app.context_processor
def inject():

    return {
        "current_user": session.get("user")
    }


@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        u = request.form.get(
            "username",
            ""
        ).strip()

        p = request.form.get(
            "password",
            ""
        )

        c = db()

        user = c.execute(
            "SELECT * FROM users WHERE username=?",
            (u,)
        ).fetchone()

        c.close()

        if user and check_password_hash(
            user["password"],
            p
        ):

            session["user"] = {

                "username": user["username"],

                "name": user["name"],

                "role": user["role"],

                "email": user["email"]
                if "email" in user.keys()
                else "",

                "department": user["department"]
                if "department" in user.keys()
                else ""
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


@app.route("/dashboard")
def dashboard():

    if not login_required():
        return redirect(
            url_for("login")
        )

    c = db()

    stats = {

        "incidents":
        c.execute(
            "SELECT COUNT(*) FROM incidents"
        ).fetchone()[0],

        "open_actions":
        c.execute(
            "SELECT COUNT(*) FROM actions WHERE status!='Closed'"
        ).fetchone()[0],

        "permits":
        c.execute(
            """
            SELECT COUNT(*)
            FROM permits
            WHERE status IN ('Pending','Active')
            """
        ).fetchone()[0],

        "reports":
        c.execute(
            """
            SELECT COUNT(*)
            FROM incidents
            WHERE status='New'
            """
        ).fetchone()[0]
    }

    recent = c.execute(
        """
        SELECT *
        FROM incidents
        ORDER BY id DESC
        LIMIT 6
        """
    ).fetchall()

    actions = c.execute(
        """
        SELECT *
        FROM actions
        WHERE status!='Closed'
        ORDER BY due_date
        LIMIT 6
        """
    ).fetchall()

    c.close()

    return render_template(
        "dashboard.html",
        stats=stats,
        recent=recent,
        actions=actions
    )


@app.route("/report", methods=["GET", "POST"])
def report():

    if not login_required():
        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        et = request.form.get(
            "event_type",
            "Incident"
        )

        title = request.form.get(
            "title",
            ""
        ).strip()

        loc = request.form.get(
            "location",
            ""
        ).strip()

        sev = request.form.get(
            "severity",
            "Medium"
        )

        desc = request.form.get(
            "description",
            ""
        ).strip()

        if not title or not loc or not desc:

            flash(
                "Title, location and description are required.",
                "error"
            )

            return render_template(
                "report.html"
            )

        c = db()

        n = c.execute(
            """
            SELECT COALESCE(MAX(id),0)+1
            FROM incidents
            """
        ).fetchone()[0]

        ref = f"INC-{n:04d}"

        file = request.files.get(
            "attachment"
        )

        filename = ""

        if file and file.filename:

            ext = file.filename.rsplit(
                ".",
                1
            )[-1].lower()

            if ext not in ALLOWED:

                flash(
                    "Unsupported attachment type.",
                    "error"
                )

                c.close()

                return render_template(
                    "report.html"
                )

            filename = (
                f"{ref}_"
                f"{secure_filename(file.filename)}"
            )

            file.save(
                os.path.join(
                    UPLOAD,
                    filename
                )
            )

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        c.execute(
            """
            INSERT INTO incidents(
                ref,event_type,title,location,severity,
                description,status,reporter,created_at,attachment
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ref,
                et,
                title,
                loc,
                sev,
                desc,
                "New",
                session["user"]["name"],
                now,
                filename
            )
        )

        c.commit()
        c.close()

        flash(
            f"Report {ref} submitted successfully.",
            "success"
        )

        return redirect(
            url_for("incidents")
        )

    return render_template(
        "report.html"
    )


@app.route("/incidents")
def incidents():

    if not login_required():
        return redirect(
            url_for("login")
        )

    q = request.args.get(
        "q",
        ""
    ).strip()

    c = db()

    if q:

        rows = c.execute(
            """
            SELECT *
            FROM incidents
            WHERE ref LIKE ?
               OR title LIKE ?
               OR event_type LIKE ?
            ORDER BY id DESC
            """,
            (
                f"%{q}%",
                f"%{q}%",
                f"%{q}%"
            )
        ).fetchall()

    else:

        rows = c.execute(
            """
            SELECT *
            FROM incidents
            ORDER BY id DESC
            """
        ).fetchall()

    c.close()

    return render_template(
        "incidents.html",
        rows=rows,
        q=q
    )


@app.route(
    "/incidents/<int:incident_id>/status",
    methods=["POST"]
)
def incident_status(
    incident_id
):

    if not login_required() or session["user"]["role"] not in (
        "admin",
        "ehs"
    ):

        return redirect(
            url_for("incidents")
        )

    status = request.form.get(
        "status",
        "Investigation"
    )

    c = db()

    c.execute(
        """
        UPDATE incidents
        SET status=?
        WHERE id=?
        """,
        (
            status,
            incident_id
        )
    )

    c.commit()
    c.close()

    flash(
        "Incident status updated.",
        "success"
    )

    return redirect(
        url_for("incidents")
    )


@app.route(
    "/actions",
    methods=["GET", "POST"]
)
def actions():

    if not login_required():
        return redirect(
            url_for("login")
        )

    c = db()

    if request.method == "POST":

        c.execute(
            """
            INSERT INTO actions(
                incident_ref,title,owner,due_date,
                priority,status,created_at
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
                )
            )
        )

        c.commit()

        flash(
            "CAPA/action created.",
            "success"
        )

    rows = c.execute(
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

    c.close()

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

    c = db()

    c.execute(
        """
        UPDATE actions
        SET status='Closed'
        WHERE id=?
        """,
        (action_id,)
    )

    c.commit()
    c.close()

    flash(
        "Action closed.",
        "success"
    )

    return redirect(
        url_for("actions")
    )


@app.route(
    "/ptw",
    methods=["GET", "POST"]
)
def ptw():

    if not login_required():

        return redirect(
            url_for("login")
        )

    c = db()

    if request.method == "POST":

        n = c.execute(
            """
            SELECT COALESCE(MAX(id),0)+1
            FROM permits
            """
        ).fetchone()[0]

        ref = f"PTW-{n:04d}"

        c.execute(
            """
            INSERT INTO permits(
                ref,permit_type,area,requester,
                status,created_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                ref,
                request.form["permit_type"],
                request.form["area"],
                session["user"]["name"],
                "Pending",
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M"
                )
            )
        )

        c.commit()

        flash(
            f"{ref} created.",
            "success"
        )

    rows = c.execute(
        """
        SELECT *
        FROM permits
        ORDER BY id DESC
        """
    ).fetchall()

    c.close()

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

    c = db()

    c.execute(
        """
        UPDATE permits
        SET status=?
        WHERE id=?
        """,
        (
            status,
            permit_id
        )
    )

    c.commit()
    c.close()

    flash(
        "Permit status updated.",
        "success"
    )

    return redirect(
        url_for("ptw")
    )


@app.route(
    "/sustainability",
    methods=["GET", "POST"]
)
def sustainability():

    if not login_required():

        return redirect(
            url_for("login")
        )

    c = db()

    if request.method == "POST":

        c.execute(
            """
            INSERT INTO sustainability(
                metric,value,unit,period,created_at
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
                )
            )
        )

        c.commit()

        flash(
            "Sustainability data saved.",
            "success"
        )

    rows = c.execute(
        """
        SELECT *
        FROM sustainability
        ORDER BY id DESC
        """
    ).fetchall()

    c.close()

    return render_template(
        "sustainability.html",
        rows=rows
    )


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
# EHS OBSERVATIONS WORKFLOW
# =========================================================

def get_hod_for_department(
    c,
    department
):

    hod = c.execute(
        """
        SELECT *
        FROM users
        WHERE role='hod'
          AND department=?
        ORDER BY id
        LIMIT 1
        """,
        (department,)
    ).fetchone()

    if not hod:

        hod = c.execute(
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

    c = db()

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

        if not title or not description or not location or not department:

            c.close()

            flash(
                "Title, description, location and department are required.",
                "error"
            )

            return redirect(
                url_for("observations")
            )

        n = c.execute(
            """
            SELECT COALESCE(MAX(id),0)+1
            FROM observations
            """
        ).fetchone()[0]

        ref = f"OBS-{n:04d}"

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        hod = get_hod_for_department(
            c,
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

        c.execute(
            """
            INSERT INTO observations(
                ref,category,title,description,location,
                department,severity,reporter_username,
                reporter_name,hod_username,hod_name,hod_email,
                status,created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ref,
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
                now
            )
        )

        c.commit()
        c.close()

        if hod_email:

            send_email(
                hod_email,
                f"EHS360 Observation {ref} - HOD Review Required",
                f"""
Dear {hod_name},

A new EHS observation has been reported and requires your review.

Observation: {ref}
Category: {category}
Title: {title}
Department: {department}
Location: {location}
Severity: {severity}
Reported By: {session["user"]["name"]}
Date: {now}

Please log in to EHS360, review the observation and assign the required CAPA to a responsible employee.

EHS360 Management Portal
"""
            )

        flash(
            f"{ref} submitted successfully. Status: Pending HOD Review.",
            "success"
        )

        return redirect(
            url_for("observations")
        )

    rows = c.execute(
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
            session["user"]["role"]
        )
    ).fetchall()

    pending_review = c.execute(
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

    pending_approval = c.execute(
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

    assigned = c.execute(
        """
        SELECT *
        FROM observations
        WHERE responsible_username=?
          AND status IN ('CAPA Assigned','Rework Required')
        ORDER BY id DESC
        """,
        (
            session["user"]["username"],
        )
    ).fetchall()

    employees = []

    if session["user"]["role"] in (
        "hod",
        "ehs",
        "admin"
    ):

        department = session["user"].get(
            "department",
            ""
        )

        if (
            session["user"]["role"] == "hod"
            and department
        ):

            employees = c.execute(
                """
                SELECT username,name,department
                FROM users
                WHERE role='employee'
                  AND department=?
                ORDER BY name
                """,
                (department,)
            ).fetchall()

        else:

            employees = c.execute(
                """
                SELECT username,name,department
                FROM users
                WHERE role IN ('employee','hod','ehs')
                ORDER BY department,name
                """
            ).fetchall()

    c.close()

    return render_template(
        "observations.html",
        rows=rows,
        pending_review=pending_review,
        pending_approval=pending_approval,
        assigned=assigned,
        employees=employees,
        departments=DEPARTMENTS
    )


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

    c = db()

    obs = c.execute(
        """
        SELECT *
        FROM observations
        WHERE id=?
        """,
        (
            observation_id,
        )
    ).fetchone()

    if not obs:

        c.close()

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
        ==
        obs["hod_username"]
    )

    if not allowed:

        c.close()

        flash(
            "You are not authorized to review this observation.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    responsible = request.form.get(
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

    employee = c.execute(
        """
        SELECT *
        FROM users
        WHERE username=?
        """,
        (
            responsible,
        )
    ).fetchone()

    if not employee or not capa or not due_date:

        c.close()

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

    c.execute(
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
            observation_id
        )
    )

    c.commit()
    c.close()

    if employee["email"]:

        send_email(
            employee["email"],
            f"EHS360 CAPA Assigned - {obs['ref']}",
            f"""
Dear {employee['name']},

A CAPA has been assigned to you through EHS360.

Observation: {obs['ref']}
Title: {obs['title']}
Department: {obs['department']}
Location: {obs['location']}
Severity: {obs['severity']}

CAPA:
{capa}

Due Date: {due_date}

Please complete the action and submit closure evidence in EHS360.

Regards,
EHS360
"""
        )

    flash(
        f"{obs['ref']} reviewed and CAPA assigned to {employee['name']}.",
        "success"
    )

    return redirect(
        url_for("observations")
    )


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

    c = db()

    obs = c.execute(
        """
        SELECT *
        FROM observations
        WHERE id=?
        """,
        (
            observation_id,
        )
    ).fetchone()

    if not obs:

        c.close()

        flash(
            "Observation not found.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    allowed = (
        session["user"]["username"]
        == obs["responsible_username"]
        or
        session["user"]["role"]
        in ("admin", "ehs")
    )

    if not allowed:

        c.close()

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

    file = request.files.get(
        "closure_evidence"
    )

    evidence = (
        obs["closure_evidence"]
        or
        ""
    )

    if not closure_comment:

        c.close()

        flash(
            "Closure comment is required.",
            "error"
        )

        return redirect(
            url_for("observations")
        )

    if file and file.filename:

        ext = file.filename.rsplit(
            ".",
            1
        )[-1].lower()

        if ext not in ALLOWED:

            c.close()

            flash(
                "Unsupported closure evidence file type.",
                "error"
            )

            return redirect(
                url_for("observations")
            )

        evidence = (
            f"{obs['ref']}_closure_"
            f"{secure_filename(file.filename)}"
        )

        file.save(
            os.path.join(
                UPLOAD,
                evidence
            )
        )

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    c.execute(
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
            observation_id
        )
    )

    c.commit()
    c.close()

    if obs["hod_email"]:

        send_email(
            obs["hod_email"],
            f"EHS360 Observation {obs['ref']} - Closure Approval Required",
            f"""
Dear {obs['hod_name'] or 'HOD'},

The responsible employee has completed the CAPA for observation {obs['ref']}.

Observation: {obs['title']}
Department: {obs['department']}
Responsible Employee: {obs['responsible_name']}

Closure Comment:
{closure_comment}

Please log in to EHS360 and approve or reject the closure.

Regards,
EHS360
"""
        )

    flash(
        f"{obs['ref']} submitted for HOD approval.",
        "success"
    )

    return redirect(
        url_for("observations")
    )


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

    c = db()

    obs = c.execute(
        """
        SELECT *
        FROM observations
        WHERE id=?
        """,
        (
            observation_id,
        )
    ).fetchone()

    if not obs:

        c.close()

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
        ==
        obs["hod_username"]
    )

    if not allowed:

        c.close()

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

        c.execute(
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
                observation_id
            )
        )

        message = (
            f"{obs['ref']} approved and closed."
        )

    else:

        status = "Rework Required"

        c.execute(
            """
            UPDATE observations
            SET status=?,
                hod_comment=?
            WHERE id=?
            """,
            (
                status,
                hod_comment,
                observation_id
            )
        )

        message = (
            f"{obs['ref']} returned for rework."
        )

    c.commit()
    c.close()

    if obs["responsible_username"]:

        c2 = db()

        employee = c2.execute(
            """
            SELECT email,name
            FROM users
            WHERE username=?
            """,
            (
                obs["responsible_username"],
            )
        ).fetchone()

        c2.close()

        if employee and employee["email"]:

            send_email(
                employee["email"],
                f"EHS360 Observation {obs['ref']} - {status}",
                f"""
Dear {employee['name']},

Observation {obs['ref']} has been reviewed by the Department HOD.

Status: {status}

HOD Comment:
{hod_comment or 'No additional comment'}

{
'The observation is now closed.'
if status == 'Closed'
else
'Please review the HOD comment and complete the required rework.'
}

Regards,
EHS360
"""
            )

    if (
        obs["reporter_username"]
        and
        obs["reporter_username"]
        != obs["responsible_username"]
    ):

        c3 = db()

        reporter = c3.execute(
            """
            SELECT email,name
            FROM users
            WHERE username=?
            """,
            (
                obs["reporter_username"],
            )
        ).fetchone()

        c3.close()

        if reporter and reporter["email"]:

            send_email(
                reporter["email"],
                f"EHS360 Observation {obs['ref']} - {status}",
                f"""
Dear {reporter['name']},

Your EHS observation {obs['ref']} has been reviewed by the Department HOD.

Status: {status}

HOD Comment:
{hod_comment or 'No additional comment'}

Regards,
EHS360
"""
            )

    flash(
        message,
        "success"
    )

    return redirect(
        url_for("observations")
    )


@app.route(
    "/uploads/<filename>"
)
def uploaded(filename):

    if not login_required():

        return "", 403

    return send_from_directory(
        UPLOAD,
        filename
    )


init_db()


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
