# gunicorn.conf.py
bind = "0.0.0.0:8080"  # Porta padrão do Render
workers = 2          # Número de workers
timeout = 120        # Timeout em segundos (aumentado)
keepalive = 5          # Keep-alive em segundos
worker_class = "sync"  # Tipo de worker
