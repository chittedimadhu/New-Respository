EHS360 V2 — REAL-USE STARTER

What this version does:
- Real Flask web application
- SQLite database created automatically
- Login and role-ready sessions
- Incident / Near Miss / Safety Observation / Environmental Event reporting
- Photo/PDF evidence upload
- Incident status management for admin
- CAPA / action creation and closure
- Permit to Work creation and status workflow
- Sustainability data entry
- Responsive desktop + mobile interface
- Same database serves computer and mobile browsers on the same network

DEMO USERS
Admin: admin / ehs360
Employee: employee / employee

WINDOWS
1. Install Python 3.11+ from python.org if not already installed.
2. Extract this folder.
3. Double-click start_windows.bat.
4. Open http://127.0.0.1:5000 on the computer.
5. For a phone on the same Wi-Fi, find the computer's local IP (e.g. 192.168.1.20)
   and open http://192.168.1.20:5000 on the phone.
   Windows Firewall may ask permission for Python; allow it on Private networks.

MAC / LINUX
Run ./start_mac_linux.sh
Then open http://127.0.0.1:5000

IMPORTANT FOR COMPANY DEPLOYMENT
This is a production-oriented starter, not a finished enterprise deployment.
Before external/company-wide production use, add:
- HTTPS and a real domain
- Strong password policy and password reset
- SSO/Active Directory if required
- PostgreSQL or managed database for scale
- Role/permission matrix
- Backup and disaster recovery
- Audit trail
- Email/SMS/push notifications
- Antivirus/file scanning
- CSRF protection and hardened deployment
- Formal validation against your company's EHS procedures and legal requirements

DATA
The SQLite database file ehs360.db and uploads folder are created automatically beside app.py.
Back up both.
