from app import app
from models.database import load_server_config, save_server_config
import os
import sys

def migrate_server():
    with app.app_context():
        cfg = load_server_config()
        old_ip = cfg.get("active_ip")
        new_ip = "172.16.1.26:8082"
        
        cfg["active_ip"] = new_ip
        if "servers" not in cfg:
            cfg["servers"] = []
        if new_ip not in cfg["servers"]:
            cfg["servers"].append(new_ip)
            
        save_server_config(cfg)
        print(f"Server migrated from {old_ip} to {new_ip}")

if __name__ == "__main__":
    migrate_server()
