from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import sqlite3, os, secrets
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
ALLOWED = {"png","jpg","jpeg","webp","pdf"}

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS incidents(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE NOT NULL,
      event_type TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL,
      severity TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
      reporter TEXT NOT NULL, created_at TEXT NOT NULL, attachment TEXT
    );
    CREATE TABLE IF NOT EXISTS actions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, incident_ref TEXT, title TEXT NOT NULL,
      owner TEXT NOT NULL, due_date TEXT, priority TEXT NOT NULL,
      status TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS permits(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE NOT NULL,
      permit_type TEXT NOT NULL, area TEXT NOT NULL, requester TEXT NOT NULL,
      status TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sustainability(
      id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT NOT NULL,
      value REAL NOT NULL, unit TEXT NOT NULL, period TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    """)
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        c.execute("INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)",
                  ("admin","pbkdf2:sha256:600000$demo$2f0e0d0a0c6d8f9c4c1e7d7f0b0c7c7e6d8d6e3f4e1a0d6c8e0f0b6c1a4d2e5","EHS Administrator","admin"))
        # Replace demo hash with a generated valid hash.
        c.execute("UPDATE users SET password=? WHERE username='admin'", (generate_password_hash("ehs360"),))
        c.execute("INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)",
                  ("employee","", "Demo Employee","employee"))
        c.execute("UPDATE users SET password=? WHERE username='employee'", (generate_password_hash("employee"),))
    if c.execute("SELECT COUNT(*) FROM sustainability").fetchone()[0] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for metric,value,unit in [("Energy",11.4,"% reduction"),("Water",8.2,"% reduction"),("Waste diverted",76,"%"),("GHG",18.6,"% reduction")]:
            c.execute("INSERT INTO sustainability(metric,value,unit,period,created_at) VALUES(?,?,?,?,?)",
                      (metric,value,unit,"Current",now))
    c.commit(); c.close()

def login_required():
    return "user" in session

@app.context_processor
def inject():
    return {"current_user": session.get("user")}

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","")
        c = db(); user = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone(); c.close()
        if user and check_password_hash(user["password"], p):
            session["user"] = {"username":user["username"],"name":user["name"],"role":user["role"]}
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if not login_required(): return redirect(url_for("login"))
    c=db()
    stats={
      "incidents": c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0],
      "open_actions": c.execute("SELECT COUNT(*) FROM actions WHERE status!='Closed'").fetchone()[0],
      "permits": c.execute("SELECT COUNT(*) FROM permits WHERE status IN ('Pending','Active')").fetchone()[0],
      "reports": c.execute("SELECT COUNT(*) FROM incidents WHERE status='New'").fetchone()[0],
    }
    recent=c.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 6").fetchall()
    actions=c.execute("SELECT * FROM actions WHERE status!='Closed' ORDER BY due_date LIMIT 6").fetchall()
    c.close()
    return render_template("dashboard.html",stats=stats,recent=recent,actions=actions)

@app.route("/report", methods=["GET","POST"])
def report():
    if not login_required(): return redirect(url_for("login"))
    if request.method=="POST":
        et=request.form.get("event_type","Incident"); title=request.form.get("title","").strip()
        loc=request.form.get("location","").strip(); sev=request.form.get("severity","Medium")
        desc=request.form.get("description","").strip()
        if not title or not loc or not desc:
            flash("Title, location and description are required.","error")
            return render_template("report.html")
        c=db(); n=c.execute("SELECT COALESCE(MAX(id),0)+1 FROM incidents").fetchone()[0]
        ref=f"INC-{n:04d}"
        file=request.files.get("attachment"); filename=""
        if file and file.filename:
            ext=file.filename.rsplit(".",1)[-1].lower()
            if ext not in ALLOWED:
                flash("Unsupported attachment type.","error"); c.close(); return render_template("report.html")
            filename=f"{ref}_{secure_filename(file.filename)}"; file.save(os.path.join(UPLOAD,filename))
        now=datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("""INSERT INTO incidents(ref,event_type,title,location,severity,description,status,reporter,created_at,attachment)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",(ref,et,title,loc,sev,desc,"New",session["user"]["name"],now,filename))
        c.commit(); c.close()
        flash(f"Report {ref} submitted successfully.","success")
        return redirect(url_for("incidents"))
    return render_template("report.html")

@app.route("/incidents")
def incidents():
    if not login_required(): return redirect(url_for("login"))
    q=request.args.get("q","").strip()
    c=db()
    if q:
        rows=c.execute("SELECT * FROM incidents WHERE ref LIKE ? OR title LIKE ? OR event_type LIKE ? ORDER BY id DESC",
                       (f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    else:
        rows=c.execute("SELECT * FROM incidents ORDER BY id DESC").fetchall()
    c.close(); return render_template("incidents.html",rows=rows,q=q)

@app.route("/incidents/<int:incident_id>/status", methods=["POST"])
def incident_status(incident_id):
    if not login_required() or session["user"]["role"] not in ("admin","ehs"): return redirect(url_for("incidents"))
    status=request.form.get("status","Investigation")
    c=db(); c.execute("UPDATE incidents SET status=? WHERE id=?",(status,incident_id)); c.commit(); c.close()
    flash("Incident status updated.","success"); return redirect(url_for("incidents"))

@app.route("/actions", methods=["GET","POST"])
def actions():
    if not login_required(): return redirect(url_for("login"))
    c=db()
    if request.method=="POST":
        c.execute("""INSERT INTO actions(incident_ref,title,owner,due_date,priority,status,created_at)
                     VALUES(?,?,?,?,?,?,?)""",
                  (request.form.get("incident_ref",""),request.form["title"],request.form["owner"],
                   request.form.get("due_date",""),request.form.get("priority","Medium"),"Open",
                   datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit(); flash("CAPA/action created.","success")
    rows=c.execute("SELECT * FROM actions ORDER BY CASE status WHEN 'Open' THEN 0 ELSE 1 END, due_date").fetchall()
    c.close(); return render_template("actions.html",rows=rows)

@app.route("/actions/<int:action_id>/close", methods=["POST"])
def close_action(action_id):
    if not login_required(): return redirect(url_for("actions"))
    c=db(); c.execute("UPDATE actions SET status='Closed' WHERE id=?",(action_id,)); c.commit(); c.close()
    flash("Action closed.","success"); return redirect(url_for("actions"))

@app.route("/ptw", methods=["GET","POST"])
def ptw():
    if not login_required(): return redirect(url_for("login"))
    c=db()
    if request.method=="POST":
        n=c.execute("SELECT COALESCE(MAX(id),0)+1 FROM permits").fetchone()[0]
        ref=f"PTW-{n:04d}"
        c.execute("INSERT INTO permits(ref,permit_type,area,requester,status,created_at) VALUES(?,?,?,?,?,?)",
                  (ref,request.form["permit_type"],request.form["area"],session["user"]["name"],"Pending",datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit(); flash(f"{ref} created.","success")
    rows=c.execute("SELECT * FROM permits ORDER BY id DESC").fetchall(); c.close()
    return render_template("ptw.html",rows=rows)

@app.route("/ptw/<int:permit_id>/status", methods=["POST"])
def permit_status(permit_id):
    if not login_required(): return redirect(url_for("ptw"))
    status=request.form.get("status","Active")
    c=db(); c.execute("UPDATE permits SET status=? WHERE id=?",(status,permit_id)); c.commit(); c.close()
    flash("Permit status updated.","success"); return redirect(url_for("ptw"))

@app.route("/sustainability", methods=["GET","POST"])
def sustainability():
    if not login_required(): return redirect(url_for("login"))
    c=db()
    if request.method=="POST":
        c.execute("INSERT INTO sustainability(metric,value,unit,period,created_at) VALUES(?,?,?,?,?)",
                  (request.form["metric"],float(request.form["value"]),request.form["unit"],request.form["period"],datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit(); flash("Sustainability data saved.","success")
    rows=c.execute("SELECT * FROM sustainability ORDER BY id DESC").fetchall(); c.close()
    return render_template("sustainability.html",rows=rows)

@app.route("/training")
def training():
    if not login_required(): return redirect(url_for("login"))
    return render_template("training.html")

@app.route("/uploads/<filename>")
def uploaded(filename):
    if not login_required(): return "",403
    return send_from_directory(UPLOAD,filename)

init_db()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
