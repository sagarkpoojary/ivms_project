import os
import json
from urllib.parse import urlparse
from flask import request, redirect, url_for, flash, render_template, session

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        cfg = {"servers": [], "active_ip": None}
        save_config(cfg)
        return cfg
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

@app.route("/add-server", methods=["POST"])
def add_server():
    server_ip = (request.form.get("server_ip") or "").strip()
    if not server_ip:
        flash("Server address required", "danger")
        return redirect(url_for("server_settings"))
    # normalize scheme if missing
    if not server_ip.startswith(("http://", "https://")):
        server_ip = "http://" + server_ip
    p = urlparse(server_ip)
    if not p.scheme or not p.netloc:
        flash("Invalid server address", "danger")
        return redirect(url_for("server_settings"))

    cfg = load_config()
    servers = cfg.setdefault("servers", [])
    if server_ip in servers:
        flash("Server already added", "warning")
        return redirect(url_for("server_settings"))

    servers.append(server_ip)
    if not cfg.get("active_ip"):
        cfg["active_ip"] = server_ip
    save_config(cfg)
    flash("Server added", "success")
    return redirect(url_for("server_settings"))

@app.route("/set-active-server", methods=["POST"])
def set_active_server():
    active = (request.form.get("active_ip") or "").strip()
    cfg = load_config()
    if active not in cfg.get("servers", []):
        flash("Server not found", "danger")
        return redirect(url_for("server_settings"))
    cfg["active_ip"] = active
    save_config(cfg)
    flash("Active server updated", "success")
    return redirect(url_for("server_settings"))

@app.route("/server-settings", methods=["GET", "POST"])
def server_settings():
    cfg = load_config()
    return render_template("server_settings.html",
                           config=cfg,
                           active_ip=get_traccar_host(),
                           user=session.get('user_name'))

@app.route("/vehicle/add", methods=["GET", "POST"])
def vehicle_form():
    # ...existing code to build `vehicles` ...
    return render_template("vehicle_form.html",
                           vehicles=vehicles,
                           active_ip=get_traccar_host(),
                           user=session.get('user_name'))

@app.context_processor
def inject_globals():
    # provide `user`, `active_ip` and `config` to all templates
    cfg = load_config()
    user = session.get('user_name') or 'Admin'
    return {
        "user": user,
        "active_ip": cfg.get("active_ip") or "",
        "config": cfg
    }