"""

Spine Automation – company website + admin portal (Flask).



Run locally:   python app.py

Production:    gunicorn app:app



Edit the COMPANY block below (or set the matching environment variables)

to put your real phone number, e-mail and address on the site.

"""

import hmac

import os

import re

import secrets

import sqlite3

import time

import uuid

from datetime import datetime, timedelta, timezone

from functools import wraps

from pathlib import Path



from flask import (Flask, abort, flash, g, redirect, render_template, request,

                   send_from_directory, session, url_for)

from werkzeug.middleware.proxy_fix import ProxyFix

from werkzeug.security import check_password_hash, generate_password_hash

from werkzeug.exceptions import RequestEntityTooLarge



try:
    from PIL import Image, ImageOps
except ImportError as exc:
    raise RuntimeError("Pillow is required. Install it with: pip install Pillow") from exc


# --------------------------------------------------------------------------

# CONFIG  –  edit these

# --------------------------------------------------------------------------

COMPANY = {

    "name": os.environ.get("COMPANY_NAME", "Spine Automation"),

    "tagline": "PLC & Industrial Automation Solutions",

    # >>> REPLACE with your real number (include country code) <<<

    "phone_display": os.environ.get("COMPANY_PHONE", "+91 9822437473"),

    "email": os.environ.get("COMPANY_EMAIL", "satyawannarale@rediffmail.com"),

    "address": os.environ.get("COMPANY_ADDRESS", "Spine Automations, Ground Floor, Sector 1,A wing, Ellora Shopee ,Indrayani Nagar, Bhosari, Pune."),

    "hours": os.environ.get("COMPANY_HOURS", "Mon – Sun, 9:00 AM – 6:00 PM"),

    # Digits only with country code, e.g. 919876543210. Leave empty to hide.

    "whatsapp": os.environ.get("COMPANY_WHATSAPP", "+91 9822437473"),

}

COMPANY["phone_href"] = "tel:" + re.sub(r"[^\d+]", "", COMPANY["phone_display"])

PLACEHOLDER_PHONE = COMPANY["phone_display"] == "+91 9822437473"  



# What the site offers – edit freely. (icon names live in templates/_icons.html)

SERVICES = [

    ("chip", "PLC Programming & Commissioning",

     "Logic design, programming, testing and on-site start-up for new lines and machines."),

    ("monitor", "SCADA & HMI Development",

     "Operator screens, alarms, trends and reporting so your team sees the plant at a glance."),

    ("panel", "Control Panel Manufacturing",

     "Custom-built, neatly wired and fully tested panels – from small machines to full plants."),

    ("drive", "VFD, Drives & Motor Control",

     "Selection, installation and tuning of variable frequency drives, servos and soft starters."),

    ("wrench", "Retrofit & Upgrades",

     "Replace ageing relay logic or obsolete controllers with modern automation – with minimal downtime."),

    ("shield", "Service & AMC",

     "Breakdown support, preventive maintenance and annual maintenance contracts."),

]



PROCESS = [

    ("Understand", "We study your process, drawings and downtime pain-points."),

    ("Design", "Architecture, I/O list, panel layout and a clear quotation."),

    ("Build", "Panel assembly and PLC / SCADA programming, tested before dispatch."),

    ("Commission", "On-site installation, loop checks and operator training."),

    ("Support", "Documentation, spares guidance and responsive after-sales service."),

]



BASE_DIR = Path(__file__).resolve().parent
IS_VERCEL = os.environ.get("VERCEL", "").lower() == "1"
IS_PRODUCTION = IS_VERCEL or os.environ.get("FLASK_ENV", "").lower() == "production"

# This codebase currently uses local SQLite and local uploads. Vercel functions
# have ephemeral filesystems, so stop rather than silently lose projects/inquiries.
if IS_VERCEL:
    raise RuntimeError(
        "Vercel deployment is blocked until the database is migrated to managed "
        "PostgreSQL and uploaded images to persistent object storage. This app "
        "currently uses local SQLite and local files."
    )

INSTANCE_DIR = Path(os.environ.get("SPINE_INSTANCE_DIR", BASE_DIR / "instance"))
UPLOAD_DIR = Path(os.environ.get("SPINE_UPLOAD_DIR", BASE_DIR / "uploads"))
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(INSTANCE_DIR / "spine.db")))

_DEFAULT_ADMIN_PASSWORD = "ChangeMe@123"
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)
USING_DEFAULT_PASSWORD = ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD
if IS_PRODUCTION and (not os.environ.get("ADMIN_USERNAME") or not os.environ.get("ADMIN_PASSWORD") or USING_DEFAULT_PASSWORD):
    raise RuntimeError("Set a unique ADMIN_USERNAME and strong ADMIN_PASSWORD in production.")
_ADMIN_PW_HASH = generate_password_hash(ADMIN_PASSWORD)

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}

MAX_GALLERY_PER_UPLOAD = 20

MAX_GALLERY_TOTAL = 40

LOCAL_TZ = timezone(timedelta(minutes=int(os.environ.get("TZ_OFFSET_MINUTES", "330"))))  # IST



INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)





def _load_secret_key():
    env = os.environ.get("SECRET_KEY")
    if env:
        if IS_PRODUCTION and len(env) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters in production.")
        return env
    if IS_PRODUCTION:
        raise RuntimeError("Set SECRET_KEY as a production environment variable.")
    key_file = INSTANCE_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


app = Flask(__name__)

app.config.update(

    SECRET_KEY=_load_secret_key(),

    MAX_CONTENT_LENGTH=80 * 1024 * 1024,  # total request size cap

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_SECURE=(IS_PRODUCTION or os.environ.get("SECURE_COOKIES") == "1"),

    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),

    TEMPLATES_AUTO_RELOAD=not IS_PRODUCTION,

    MAX_FORM_MEMORY_SIZE=2 * 1024 * 1024,

)

if os.environ.get("TRUST_PROXY") == "1":  # set when behind nginx / a PaaS proxy

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)



# --------------------------------------------------------------------------

# Database

# --------------------------------------------------------------------------

SCHEMA = """

CREATE TABLE IF NOT EXISTS categories (

    id   INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL UNIQUE COLLATE NOCASE,

    slug TEXT NOT NULL UNIQUE

);

CREATE TABLE IF NOT EXISTS projects (

    id          INTEGER PRIMARY KEY AUTOINCREMENT,

    title       TEXT NOT NULL,

    description TEXT NOT NULL,

    category_id INTEGER NOT NULL REFERENCES categories(id),

    cover_image TEXT NOT NULL,

    created_at  TEXT NOT NULL DEFAULT (datetime('now'))

);

CREATE TABLE IF NOT EXISTS project_images (

    id         INTEGER PRIMARY KEY AUTOINCREMENT,

    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    filename   TEXT NOT NULL

);

CREATE TABLE IF NOT EXISTS inquiries (

    id         INTEGER PRIMARY KEY AUTOINCREMENT,

    name       TEXT NOT NULL,

    phone      TEXT NOT NULL,

    email      TEXT,

    company    TEXT,

    message    TEXT NOT NULL,

    is_read    INTEGER NOT NULL DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT (datetime('now'))

);

CREATE INDEX IF NOT EXISTS idx_projects_created ON projects(created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(category_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_project_images_project ON project_images(project_id, id);
CREATE INDEX IF NOT EXISTS idx_inquiries_created ON inquiries(id DESC);
"""





def connect():

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")

    return conn





def get_db():

    if "db" not in g:

        g.db = connect()

    return g.db





@app.teardown_appcontext

def close_db(_exc):

    db = g.pop("db", None)

    if db is not None:

        db.close()





def init_db():

    conn = connect()

    conn.executescript(SCHEMA)

    conn.commit()

    conn.close()





# Local SQLite initialization is retained for existing development workflows.
# Before Vercel deployment, migrate this schema/data layer to managed PostgreSQL.
init_db()



# --------------------------------------------------------------------------

# Helpers

# --------------------------------------------------------------------------

def slugify(text):

    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

    return s or "category"





def clean_name(text, limit=60):

    return re.sub(r"\s+", " ", (text or "")).strip()[:limit]





def get_or_create_category(db, name):

    row = db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()

    if row:

        return row["id"]

    base = slugify(name)

    slug, n = base, 2

    while db.execute("SELECT 1 FROM categories WHERE slug = ?", (slug,)).fetchone():

        slug = f"{base}-{n}"

        n += 1

    cur = db.execute("INSERT INTO categories (name, slug) VALUES (?, ?)", (name, slug))

    return cur.lastrowid





def save_image(storage):
    """Validate, normalize and store an uploaded image; return its filename."""
    original_name = storage.filename or "upload"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in ALLOWED_EXT:
        raise ValueError(f"'{original_name}' is not a supported image (use JPG, PNG, WEBP or GIF).")

    output_ext = "jpg" if ext == "jpeg" else ext
    name = f"{uuid.uuid4().hex}.{output_ext}"
    path = UPLOAD_DIR / name
    try:
        with Image.open(storage.stream) as check_img:
            check_img.verify()
        storage.stream.seek(0)
        with Image.open(storage.stream) as source:
            if source.width * source.height > 40_000_000:
                raise ValueError("Image dimensions are too large (maximum 40 megapixels).")
            if ext == "gif":
                # Preserve animation after successful image verification.
                storage.stream.seek(0)
                storage.save(path)
            else:
                img = ImageOps.exif_transpose(source)
                img.thumbnail((1920, 1920))
                if output_ext == "jpg":
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.save(path, format="JPEG", quality=85, optimize=True)
                elif output_ext == "png":
                    img.save(path, format="PNG", optimize=True)
                elif output_ext == "webp":
                    img.save(path, format="WEBP", quality=85, method=6)
    except ValueError:
        if path.exists():
            path.unlink()
        raise
    except Exception as exc:
        if path.exists():
            path.unlink()
        raise ValueError(f"'{original_name}' could not be read as an image.") from exc
    return name


def remove_file(name):

    if not name:

        return

    try:

        (UPLOAD_DIR / Path(name).name).unlink(missing_ok=True)

    except OSError:

        pass





_hits = {}





def too_many(key, limit, window):

    now = time.time()

    recent = [t for t in _hits.get(key, []) if now - t < window]

    _hits[key] = recent

    return len(recent) >= limit





def record_hit(key):

    _hits.setdefault(key, []).append(time.time())





def fetch_projects(db, where="", args=(), limit=None):

    sql = ("SELECT p.*, c.name AS category_name, c.slug AS category_slug "

           "FROM projects p JOIN categories c ON c.id = p.category_id "

           f"{where} ORDER BY p.created_at DESC, p.id DESC")

    if limit:

        sql += f" LIMIT {int(limit)}"

    return db.execute(sql, args).fetchall()





def parse_db_time(value):

    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)





@app.template_filter("date")

def fmt_date(value):

    return parse_db_time(value).astimezone(LOCAL_TZ).strftime("%d %b %Y")





@app.template_filter("datetime")

def fmt_datetime(value):

    return parse_db_time(value).astimezone(LOCAL_TZ).strftime("%d %b %Y, %I:%M %p")





@app.template_filter("excerpt")

def excerpt(value, n=120):

    value = re.sub(r"\s+", " ", value).strip()

    return value if len(value) <= n else value[: n - 1].rstrip() + "…"





def csrf_token():

    if "_csrf" not in session:

        session["_csrf"] = secrets.token_urlsafe(32)

    return session["_csrf"]





app.jinja_env.globals["csrf_token"] = csrf_token





@app.before_request

def csrf_protect():

    if request.method == "POST":

        token = session.get("_csrf", "")

        sent = request.form.get("csrf_token", "")

        if not token or not hmac.compare_digest(token, sent):

            abort(400, "Your form expired or was invalid. Please go back, refresh the page and try again.")





@app.after_request

def security_headers(resp):

    resp.headers.setdefault("X-Content-Type-Options", "nosniff")

    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")

    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.path == "/admin" or request.path.startswith("/admin/"):
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        resp.headers["Cache-Control"] = "no-store"

    return resp





@app.context_processor

def inject_globals():

    ctx = {

        "company": COMPANY,

        "year": datetime.now().year,

        "is_admin": bool(session.get("admin")),

    }

    if request.path.startswith("/admin") and session.get("admin"):

        ctx["unread_count"] = get_db().execute(

            "SELECT COUNT(*) FROM inquiries WHERE is_read = 0").fetchone()[0]

    return ctx





@app.errorhandler(400)

@app.errorhandler(404)

@app.errorhandler(405)

def http_error(err):

    return render_template("error.html", code=err.code, message=err.description), err.code





@app.errorhandler(RequestEntityTooLarge)

def too_large(_err):

    return render_template(

        "error.html", code=413,

        message="That upload is too large (limit 80 MB per submit). Try fewer or smaller photos."), 413





def admin_required(view):

    @wraps(view)

    def wrapper(*a, **kw):

        if not session.get("admin"):

            return redirect(url_for("admin_login"))

        return view(*a, **kw)

    return wrapper





# --------------------------------------------------------------------------

# Public pages

# --------------------------------------------------------------------------

def _site_url():
    """Canonical public origin; production must configure SITE_URL explicitly."""
    configured = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    if IS_PRODUCTION:
        return None
    return request.url_root.rstrip("/")


@app.route("/robots.txt")
def robots_txt():
    from flask import Response
    origin = _site_url()
    lines = ["User-agent: *", "Allow: /", "Disallow: /admin"]
    if origin:
        lines.append(f"Sitemap: {origin}/sitemap.xml")
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    from flask import Response
    from xml.sax.saxutils import escape
    origin = _site_url()
    if not origin:
        return Response("Set SITE_URL to the canonical https:// domain before enabling the production sitemap.\n",
                        status=503, mimetype="text/plain")
    urls = [origin + "/", origin + "/gallery", origin + "/contact"]
    db = get_db()
    rows = db.execute("SELECT id FROM projects ORDER BY created_at DESC, id DESC").fetchall()
    urls.extend(origin + url_for("project_detail", project_id=row["id"]) for row in rows)
    body = '<?xml version="1.0" encoding="UTF-8"?>\n'
    body += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    body += "".join("<url><loc>" + escape(url) + "</loc></url>" for url in urls)
    body += "</urlset>"
    return Response(body, mimetype="application/xml")


@app.route("/media/<path:filename>")

def media(filename):

    return send_from_directory(UPLOAD_DIR, filename, max_age=60 * 60 * 24 * 365)





@app.route("/")

def home():
    db = get_db()
    latest = fetch_projects(db, limit=6)
    total_projects = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    rows = db.execute(
        "SELECT c.id AS category_id, c.name AS category_name, c.slug AS category_slug, "
        "COUNT(p.id) AS project_count "
        "FROM categories c JOIN projects p ON p.category_id = c.id "
        "GROUP BY c.id, c.name, c.slug ORDER BY c.name COLLATE NOCASE"
    ).fetchall()
    tiles = []
    for row in rows:
        newest = db.execute(
            "SELECT cover_image FROM projects WHERE category_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1", (row["category_id"],)
        ).fetchone()
        if newest:
            tiles.append({"name": row["category_name"], "slug": row["category_slug"],
                          "cover": newest["cover_image"], "count": row["project_count"]})
    return render_template("home.html", services=SERVICES, process=PROCESS,
                           latest=latest, tiles=tiles, total_projects=total_projects)


@app.route("/gallery")
def gallery():

    db = get_db()

    groups = {}

    for p in fetch_projects(db):

        groups.setdefault((p["category_name"], p["category_slug"]), []).append(p)

    ordered = sorted(groups.items(), key=lambda kv: kv[0][0].lower())

    return render_template("gallery.html", groups=ordered, total=sum(len(v) for v in groups.values()))





@app.route("/project/<int:project_id>")

def project_detail(project_id):

    db = get_db()

    rows = fetch_projects(db, "WHERE p.id = ?", (project_id,))

    if not rows:

        abort(404, "That project could not be found.")

    project = rows[0]

    images = db.execute("SELECT * FROM project_images WHERE project_id = ? ORDER BY id",

                        (project_id,)).fetchall()

    related = fetch_projects(db, "WHERE p.category_id = ? AND p.id != ?",

                             (project["category_id"], project_id), limit=3)

    return render_template("project.html", project=project, images=images, related=related)





PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")





@app.route("/contact", methods=["GET", "POST"])

def contact():

    form = {"name": "", "phone": "", "email": "", "company": "",

            "message": request.args.get("ref", "")[:200]}

    if form["message"]:

        form["message"] = f"I'd like a quote for something similar to: {form['message']}\n\n"

    if request.method == "POST":

        form = {k: request.form.get(k, "").strip() for k in ("name", "phone", "email", "company", "message")}

        ip = request.remote_addr or "?"

        if request.form.get("website"):  # honeypot – bots fill this in

            flash("Thank you! We'll get back to you shortly.", "success")

            return redirect(url_for("contact"))

        errors = []

        if not 2 <= len(form["name"]) <= 100:

            errors.append("Please enter your name.")

        if not PHONE_RE.match(form["phone"]):

            errors.append("Please enter a valid phone number so we can call you back.")

        if form["email"] and not EMAIL_RE.match(form["email"]):

            errors.append("That e-mail address doesn't look right.")

        if not 5 <= len(form["message"]) <= 3000:

            errors.append("Please tell us briefly what you need (5–3000 characters).")

        if len(form["company"]) > 120 or len(form["email"]) > 150:

            errors.append("Company or e-mail is too long.")

        if not errors and too_many(("contact", ip), 5, 600):

            errors.append("Too many requests from your connection. Please call us instead.")

        if errors:

            for e in errors:

                flash(e, "error")

            return render_template("contact.html", form=form), 400

        get_db().execute(

            "INSERT INTO inquiries (name, phone, email, company, message) VALUES (?,?,?,?,?)",

            (form["name"], form["phone"], form["email"] or None, form["company"] or None, form["message"]))

        get_db().commit()

        record_hit(("contact", ip))

        flash("Thank you! Your request has been received – we'll call you back shortly.", "success")

        return redirect(url_for("contact") + "#form")

    return render_template("contact.html", form=form)





# --------------------------------------------------------------------------

# Admin: auth

# --------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])

def admin_login():

    if session.get("admin"):

        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":

        ip = request.remote_addr or "?"

        if too_many(("login", ip), 5, 600):

            flash("Too many failed attempts. Please wait 10 minutes and try again.", "error")

            return render_template("admin_login.html"), 429

        user_ok = hmac.compare_digest(request.form.get("username", ""), ADMIN_USERNAME)

        pass_ok = check_password_hash(_ADMIN_PW_HASH, request.form.get("password", ""))

        if user_ok and pass_ok:

            session.clear()

            session["admin"] = True

            session.permanent = True

            return redirect(url_for("admin_dashboard"))

        record_hit(("login", ip))

        flash("Incorrect username or password.", "error")

        return render_template("admin_login.html"), 401

    return render_template("admin_login.html")





@app.route("/admin/logout", methods=["POST"])

def admin_logout():

    session.clear()

    return redirect(url_for("admin_login"))





# --------------------------------------------------------------------------

# Admin: dashboard

# --------------------------------------------------------------------------

@app.route("/admin")

@admin_required

def admin_dashboard():

    db = get_db()

    stats = {

        "projects": db.execute("SELECT COUNT(*) FROM projects").fetchone()[0],

        "categories": db.execute("SELECT COUNT(*) FROM categories").fetchone()[0],

        "inquiries": db.execute("SELECT COUNT(*) FROM inquiries").fetchone()[0],

    }

    recent_projects = fetch_projects(db, limit=5)

    recent_inquiries = db.execute("SELECT * FROM inquiries ORDER BY id DESC LIMIT 5").fetchall()

    return render_template("admin_dashboard.html", stats=stats, recent_projects=recent_projects,

                           recent_inquiries=recent_inquiries,

                           warn_password=USING_DEFAULT_PASSWORD, warn_phone=PLACEHOLDER_PHONE)





# --------------------------------------------------------------------------

# Admin: projects

# --------------------------------------------------------------------------

@app.route("/admin/projects")

@admin_required

def admin_projects():

    return render_template("admin_projects.html", projects=fetch_projects(get_db()))





def read_project_form():

    data = {

        "title": request.form.get("title", "").strip(),

        "description": request.form.get("description", "").strip(),

        "category": request.form.get("category", ""),

        "new_category": clean_name(request.form.get("new_category", "")),

    }

    errors = []

    if not 3 <= len(data["title"]) <= 150:

        errors.append("Title is required (3–150 characters).")

    if not 10 <= len(data["description"]) <= 6000:

        errors.append("Description is required (10–6000 characters).")

    if data["category"] == "__new__":

        if not data["new_category"]:

            errors.append("Type a name for the new category.")

    elif not data["category"].isdigit():

        errors.append("Please choose a category (or create a new one).")

    return data, errors





def resolve_category(db, data):

    if data["category"] == "__new__":

        return get_or_create_category(db, data["new_category"])

    row = db.execute("SELECT id FROM categories WHERE id = ?", (int(data["category"]),)).fetchone()

    return row["id"] if row else None





def categories_for_form(db):

    return db.execute("SELECT * FROM categories ORDER BY name COLLATE NOCASE").fetchall()





@app.route("/admin/projects/new", methods=["GET", "POST"])

@admin_required

def admin_project_new():

    db = get_db()

    form = {"title": "", "description": "", "category": "", "new_category": ""}

    if request.method == "POST":

        form, errors = read_project_form()

        cover = request.files.get("cover")

        gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]

        if not cover or not cover.filename:

            errors.append("Please choose a cover image.")

        if len(gallery_files) > MAX_GALLERY_PER_UPLOAD:

            errors.append(f"Add at most {MAX_GALLERY_PER_UPLOAD} gallery images at a time.")

        saved = []

        if not errors:

            try:

                cover_name = save_image(cover)

                saved.append(cover_name)

                gallery_names = []

                for f in gallery_files:

                    n = save_image(f)

                    saved.append(n)

                    gallery_names.append(n)

                cat_id = resolve_category(db, form)

                if cat_id is None:

                    raise ValueError("That category no longer exists.")

                cur = db.execute(

                    "INSERT INTO projects (title, description, category_id, cover_image) VALUES (?,?,?,?)",

                    (form["title"], form["description"], cat_id, cover_name))

                db.executemany("INSERT INTO project_images (project_id, filename) VALUES (?,?)",

                               [(cur.lastrowid, n) for n in gallery_names])

                db.commit()

                flash(f"Project “{form['title']}” published.", "success")

                return redirect(url_for("admin_projects"))

            except ValueError as e:

                errors.append(str(e))

            except sqlite3.Error:

                errors.append("Database error – nothing was saved. Please try again.")

            db.rollback()

            for n in saved:

                remove_file(n)

        for e in errors:

            flash(e, "error")

        return render_template("admin_project_form.html", project=None, form=form,

                               categories=categories_for_form(db), gallery=[]), 400

    return render_template("admin_project_form.html", project=None, form=form,

                           categories=categories_for_form(db), gallery=[])





@app.route("/admin/projects/<int:project_id>/edit", methods=["GET", "POST"])

@admin_required

def admin_project_edit(project_id):

    db = get_db()

    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()

    if not project:

        abort(404, "Project not found.")

    gallery = db.execute("SELECT * FROM project_images WHERE project_id = ? ORDER BY id",

                         (project_id,)).fetchall()

    form = {"title": project["title"], "description": project["description"],

            "category": str(project["category_id"]), "new_category": ""}

    if request.method == "POST":

        form, errors = read_project_form()

        cover = request.files.get("cover")

        new_files = [f for f in request.files.getlist("gallery") if f and f.filename]

        delete_ids = {int(i) for i in request.form.getlist("delete_images") if i.isdigit()}

        valid_ids = {g_["id"] for g_ in gallery}

        delete_ids &= valid_ids

        if len(new_files) > MAX_GALLERY_PER_UPLOAD:

            errors.append(f"Add at most {MAX_GALLERY_PER_UPLOAD} gallery images at a time.")

        if len(gallery) - len(delete_ids) + len(new_files) > MAX_GALLERY_TOTAL:

            errors.append(f"A project can have at most {MAX_GALLERY_TOTAL} gallery images.")

        saved, old_files = [], []

        if not errors:

            try:

                cover_name = project["cover_image"]

                if cover and cover.filename:

                    cover_name = save_image(cover)

                    saved.append(cover_name)

                    old_files.append(project["cover_image"])

                new_names = []

                for f in new_files:

                    n = save_image(f)

                    saved.append(n)

                    new_names.append(n)

                cat_id = resolve_category(db, form)

                if cat_id is None:

                    raise ValueError("That category no longer exists.")

                db.execute("UPDATE projects SET title=?, description=?, category_id=?, cover_image=? WHERE id=?",

                           (form["title"], form["description"], cat_id, cover_name, project_id))

                for g_ in gallery:

                    if g_["id"] in delete_ids:

                        old_files.append(g_["filename"])

                        db.execute("DELETE FROM project_images WHERE id = ?", (g_["id"],))

                db.executemany("INSERT INTO project_images (project_id, filename) VALUES (?,?)",

                               [(project_id, n) for n in new_names])

                db.commit()

                for n in old_files:

                    remove_file(n)

                flash("Project updated.", "success")

                return redirect(url_for("admin_projects"))

            except ValueError as e:

                errors.append(str(e))

            except sqlite3.Error:

                errors.append("Database error – nothing was saved. Please try again.")

            db.rollback()

            for n in saved:

                remove_file(n)

        for e in errors:

            flash(e, "error")

        return render_template("admin_project_form.html", project=project, form=form,

                               categories=categories_for_form(db), gallery=gallery), 400

    return render_template("admin_project_form.html", project=project, form=form,

                           categories=categories_for_form(db), gallery=gallery)





@app.route("/admin/projects/<int:project_id>/delete", methods=["POST"])

@admin_required

def admin_project_delete(project_id):

    db = get_db()

    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()

    if not project:

        abort(404, "Project not found.")

    files = [project["cover_image"]] + [r["filename"] for r in db.execute(

        "SELECT filename FROM project_images WHERE project_id = ?", (project_id,))]

    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))  # images cascade

    db.commit()

    for n in files:

        remove_file(n)

    flash(f"Project “{project['title']}” deleted.", "success")

    return redirect(url_for("admin_projects"))





# --------------------------------------------------------------------------

# Admin: categories

# --------------------------------------------------------------------------

@app.route("/admin/categories", methods=["GET", "POST"])

@admin_required

def admin_categories():

    db = get_db()

    if request.method == "POST":

        name = clean_name(request.form.get("name", ""))

        if not name:

            flash("Enter a category name.", "error")

        elif db.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():

            flash("That category already exists.", "error")

        else:

            get_or_create_category(db, name)

            db.commit()

            flash(f"Category “{name}” added.", "success")

        return redirect(url_for("admin_categories"))

    rows = db.execute(

        "SELECT c.*, (SELECT COUNT(*) FROM projects p WHERE p.category_id = c.id) AS n "

        "FROM categories c ORDER BY c.name COLLATE NOCASE").fetchall()

    return render_template("admin_categories.html", categories=rows)





@app.route("/admin/categories/<int:cat_id>/rename", methods=["POST"])

@admin_required

def admin_category_rename(cat_id):

    db = get_db()

    name = clean_name(request.form.get("name", ""))

    if not name:

        flash("Enter a category name.", "error")

    elif db.execute("SELECT 1 FROM categories WHERE name = ? AND id != ?", (name, cat_id)).fetchone():

        flash("Another category already uses that name.", "error")

    elif db.execute("SELECT 1 FROM categories WHERE id = ?", (cat_id,)).fetchone():

        base = slugify(name)

        slug, n = base, 2

        while db.execute("SELECT 1 FROM categories WHERE slug = ? AND id != ?", (slug, cat_id)).fetchone():

            slug = f"{base}-{n}"

            n += 1

        db.execute("UPDATE categories SET name = ?, slug = ? WHERE id = ?", (name, slug, cat_id))

        db.commit()

        flash("Category renamed.", "success")

    return redirect(url_for("admin_categories"))





@app.route("/admin/categories/<int:cat_id>/delete", methods=["POST"])

@admin_required

def admin_category_delete(cat_id):

    db = get_db()

    if db.execute("SELECT 1 FROM projects WHERE category_id = ?", (cat_id,)).fetchone():

        flash("This category still has projects. Move or delete them first.", "error")

    else:

        db.execute("DELETE FROM categories WHERE id = ?", (cat_id,))

        db.commit()

        flash("Category deleted.", "success")

    return redirect(url_for("admin_categories"))





# --------------------------------------------------------------------------

# Admin: inquiries

# --------------------------------------------------------------------------

@app.route("/admin/inquiries")

@admin_required

def admin_inquiries():

    rows = get_db().execute("SELECT * FROM inquiries ORDER BY id DESC").fetchall()

    return render_template("admin_inquiries.html", inquiries=rows)





@app.route("/admin/inquiries/<int:inq_id>/toggle", methods=["POST"])

@admin_required

def admin_inquiry_toggle(inq_id):

    db = get_db()

    db.execute("UPDATE inquiries SET is_read = 1 - is_read WHERE id = ?", (inq_id,))

    db.commit()

    return redirect(url_for("admin_inquiries"))





@app.route("/admin/inquiries/<int:inq_id>/delete", methods=["POST"])

@admin_required

def admin_inquiry_delete(inq_id):

    db = get_db()

    db.execute("DELETE FROM inquiries WHERE id = ?", (inq_id,))

    db.commit()

    flash("Inquiry deleted.", "success")

    return redirect(url_for("admin_inquiries"))





if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG") == "1" and not IS_PRODUCTION
    app.run(host="127.0.0.1" if not IS_PRODUCTION else "0.0.0.0",
            port=int(os.environ.get("PORT", 5000)), debug=debug)
