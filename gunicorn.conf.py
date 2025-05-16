# gunicorn.conf.py
workers = 2  # Número de processos trabalhadores
timeout = 60  # Timeout de 60 segundos (padrão é 30)
keepalive = 5  # Mantém conexões vivas por 5 segundos
