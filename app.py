from __future__ import annotations

import os
from datetime import datetime
from io import BytesIO

import barcode
import qrcode
from barcode.writer import ImageWriter
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///assets.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    pin = db.Column(db.String(12), nullable=True)


class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.String(50), unique=True, nullable=False)
    part_number = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    ownership = db.Column(db.String(50), nullable=False)
    location = db.Column(db.String(120), nullable=True)
    assigned_to = db.Column(db.String(120), nullable=True)
    calibration_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="available")


ALLOWED_STATUS = {"available", "reserved", "divested"}


def current_user() -> User | None:
    user_id = session.get("user_id")
    return User.query.get(user_id) if user_id else None


def role_required(*roles):
    def decorator(view):
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please sign in first.", "warning")
                return redirect(url_for("login"))
            if user.role not in roles:
                flash("You do not have permission for this action.", "danger")
                return redirect(url_for("index"))
            return view(*args, **kwargs)

        wrapped.__name__ = view.__name__
        return wrapped

    return decorator


@app.route("/")
def index():
    user = current_user()
    query = Asset.query

    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip().lower()
    location = request.args.get("location", "").strip()

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Asset.asset_id.ilike(like),
                Asset.part_number.ilike(like),
                Asset.description.ilike(like),
                Asset.assigned_to.ilike(like),
            )
        )
    if status in ALLOWED_STATUS:
        query = query.filter(Asset.status == status)
    if location:
        query = query.filter(Asset.location.ilike(f"%{location}%"))

    assets = query.order_by(Asset.asset_id.asc()).all()
    return render_template("index.html", assets=assets, user=user, status=status, search=search, location=location)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
        pin = request.form.get("pin", "").strip()
        user = User.query.filter_by(employee_id=employee_id).first()
        if user and (not user.pin or user.pin == pin):
            session["user_id"] = user.id
            flash(f"Signed in as {user.name} ({user.role}).", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "info")
    return redirect(url_for("login"))


@app.route("/assets/new", methods=["GET", "POST"])
@role_required("manager")
def create_asset():
    if request.method == "POST":
        asset_id = request.form["asset_id"].strip()
        if Asset.query.filter_by(asset_id=asset_id).first():
            flash("Asset ID already exists.", "danger")
            return redirect(url_for("create_asset"))

        asset = Asset(
            asset_id=asset_id,
            part_number=request.form["part_number"].strip(),
            description=request.form["description"].strip(),
            ownership=request.form["ownership"].strip(),
            location=request.form.get("location", "").strip(),
            assigned_to=request.form.get("assigned_to", "").strip(),
            status=request.form.get("status", "available").strip().lower(),
        )
        cal = request.form.get("calibration_date", "").strip()
        if cal:
            asset.calibration_date = datetime.strptime(cal, "%Y-%m-%d").date()
        if asset.status not in ALLOWED_STATUS:
            asset.status = "available"

        db.session.add(asset)
        db.session.commit()
        flash("Asset created.", "success")
        return redirect(url_for("asset_detail", asset_id=asset.asset_id))

    return render_template("asset_form.html", asset=None, statuses=sorted(ALLOWED_STATUS))


@app.route("/assets/<asset_id>")
def asset_detail(asset_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    asset = Asset.query.filter_by(asset_id=asset_id).first_or_404()
    return render_template("asset_detail.html", asset=asset, user=user, statuses=sorted(ALLOWED_STATUS))


@app.route("/assets/<asset_id>/update", methods=["POST"])
def update_asset(asset_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    asset = Asset.query.filter_by(asset_id=asset_id).first_or_404()
    if user.role != "manager" and asset.status != "available":
        flash("Users can only modify assets with available status.", "danger")
        return redirect(url_for("asset_detail", asset_id=asset_id))

    asset.location = request.form.get("location", "").strip()
    asset.assigned_to = request.form.get("assigned_to", "").strip()
    cal = request.form.get("calibration_date", "").strip()
    asset.calibration_date = datetime.strptime(cal, "%Y-%m-%d").date() if cal else None

    if user.role == "manager":
        asset.part_number = request.form.get("part_number", asset.part_number).strip()
        asset.description = request.form.get("description", asset.description).strip()
        asset.ownership = request.form.get("ownership", asset.ownership).strip()
        status = request.form.get("status", asset.status).strip().lower()
        asset.status = status if status in ALLOWED_STATUS else asset.status

    db.session.commit()
    flash("Asset updated.", "success")
    return redirect(url_for("asset_detail", asset_id=asset_id))


@app.route("/scan")
def scan_lookup():
    code = request.args.get("code", "").strip()
    if not code:
        flash("Provide ?code=<asset_id> from scanner input.", "warning")
        return redirect(url_for("index"))

    asset = Asset.query.filter_by(asset_id=code).first()
    if not asset:
        flash(f"No asset found for code '{code}'.", "danger")
        return redirect(url_for("index"))
    return redirect(url_for("asset_detail", asset_id=asset.asset_id))


@app.route("/assets/<asset_id>/qrcode.png")
def asset_qrcode(asset_id):
    asset = Asset.query.filter_by(asset_id=asset_id).first_or_404()
    target_url = request.host_url.rstrip("/") + url_for("scan_lookup", code=asset.asset_id)
    img = qrcode.make(target_url)
    stream = BytesIO()
    img.save(stream, format="PNG")
    stream.seek(0)
    return send_file(stream, mimetype="image/png", as_attachment=True, download_name=f"{asset.asset_id}_qr.png")


@app.route("/assets/<asset_id>/barcode.png")
def asset_barcode(asset_id):
    asset = Asset.query.filter_by(asset_id=asset_id).first_or_404()
    code128 = barcode.get("code128", asset.asset_id, writer=ImageWriter())
    stream = BytesIO()
    code128.write(stream, options={"module_width": 0.2, "module_height": 15, "font_size": 10, "dpi": 300})
    stream.seek(0)
    return send_file(stream, mimetype="image/png", as_attachment=True, download_name=f"{asset.asset_id}_barcode.png")


@app.route("/users/new", methods=["GET", "POST"])
@role_required("manager")
def create_user():
    if request.method == "POST":
        employee_id = request.form["employee_id"].strip()
        if User.query.filter_by(employee_id=employee_id).first():
            flash("Employee ID already exists.", "danger")
            return redirect(url_for("create_user"))

        user = User(
            employee_id=employee_id,
            name=request.form["name"].strip(),
            role=request.form["role"].strip(),
            pin=request.form.get("pin", "").strip() or None,
        )
        db.session.add(user)
        db.session.commit()
        flash("User created.", "success")
        return redirect(url_for("index"))

    return render_template("user_form.html")


@app.route("/users/<employee_id>/qrcode.png")
def user_qrcode(employee_id):
    user = User.query.filter_by(employee_id=employee_id).first_or_404()
    payload = request.host_url.rstrip("/") + url_for("login") + f"?employee_id={user.employee_id}"
    img = qrcode.make(payload)
    stream = BytesIO()
    img.save(stream, format="PNG")
    stream.seek(0)
    return send_file(stream, mimetype="image/png", as_attachment=True, download_name=f"user_{user.employee_id}_qr.png")


def init_db():
    db.create_all()
    if not User.query.filter_by(employee_id="MGR001").first():
        db.session.add(User(employee_id="MGR001", name="Default Manager", role="manager", pin="1234"))
    if not User.query.filter_by(employee_id="USR001").first():
        db.session.add(User(employee_id="USR001", name="Default User", role="user", pin="1234"))
    db.session.commit()


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
