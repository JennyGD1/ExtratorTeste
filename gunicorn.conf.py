# gunicorn.conf.py
bind = "0.0.0.0:8080"
workers = 2
timeout = 180  # Aumentando o timeout do Gunicorn
keepalive = 5
worker_class = "sync"
