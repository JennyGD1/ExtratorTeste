import fitz  # PyMuPDF
import re
import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.secret_key = 'sua-chave-secreta-aqui'  # Em produção, use variáveis de ambiente

# Configurações do RH BAHIA
RH_BAHIA_BASE_URL = "https://rhbahia.ba.gov.br"
CONTRACHEQUE_URL_TEMPLATE = RH_BAHIA_BASE_URL + "/auditor/contracheque/file/pdf/{ano}/{mes:02d}/1/{matricula}"

# Configuração do logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('app.log', maxBytes=100000, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

MESES_ORDEM = {
    'Janeiro': 1, 'Fevereiro': 2, 'Março': 3, 'Abril': 4,
    'Maio': 5, 'Junho': 6, 'Julho': 7, 'Agosto': 8,
    'Setembro': 9, 'Outubro': 10, 'Novembro': 11, 'Dezembro': 12,
    'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAI': 5, 'JUN': 6,
    'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12
}

# Configurações de upload (mantidas para compatibilidade)
UPLOAD_FOLDER = '/tmp/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config.update({
    'UPLOAD_FOLDER': UPLOAD_FOLDER,
    'MAX_CONTENT_LENGTH': 100 * 1024 * 1024,
    'ALLOWED_EXTENSIONS': {'pdf'},
})

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extrair_valor_linha(linha):
    padrao_valor = r'(\d{1,3}(?:[\.\s]?\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2})'
    valores = re.findall(padrao_valor, linha)
    if valores:
        valor_str = valores[-1].replace('.', '').replace(',', '.')
        try:
            return float(valor_str)
        except ValueError:
            return 0.0
    return 0.0

def extrair_mes_ano_do_texto(texto_pagina):
    padrao_mes_ano = r'(Janeiro|Fevereiro|Março|Abril|Maio|Junho|Julho|Agosto|Setembro|Outubro|Novembro|Dezembro|JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*[/.-]?\s*(\d{4})'
    match = re.search(padrao_mes_ano, texto_pagina, re.IGNORECASE)
    if match:
        mes = match.group(1).capitalize()
        ano = match.group(2)
        for k, v in MESES_ORDEM.items():
            if mes.upper() == k.upper():
                mes_padrao = k.capitalize() if len(k) > 3 else k
                if len(mes_padrao) <= 3:
                    for nome_completo, num in MESES_ORDEM.items():
                        if num == v and len(nome_completo) > 3:
                            mes_padrao = nome_completo
                            break
                return f"{mes_padrao} {ano}", ano
    return "Período não identificado", None

@app.route('/')
def index():
    session.clear()
    return render_template('index.html')

@app.route('/buscar_contracheques', methods=['POST'])
def buscar_contracheques():
    try:
        data = request.get_json()
        matricula = data['matricula']
        ano_inicial = int(data['ano_inicial'])
        ano_final = int(data['ano_final'])
        
        if ano_final < ano_inicial:
            return jsonify({
                "error": "O ano final não pode ser menor que o inicial",
                "login_url": f"{RH_BAHIA_BASE_URL}/login"
            }), 400

        resultados = []
        
        # Simulação - substitua por requests reais ao RH BAHIA
        for ano in range(ano_inicial, ano_final + 1):
            for mes in range(1, 13):
                url = CONTRACHEQUE_URL_TEMPLATE.format(
                    ano=ano,
                    mes=mes,
                    matricula=matricula
                )
                
                # Aqui você faria a requisição real ao RH BAHIA
                # response = requests.get(url, cookies=request.cookies)
                
                # Exemplo de resultado simulado
                resultados.append({
                    'mes': f"{mes:02d}/{ano}",
                    'url': url,
                    'valores': {
                        'titular': 5000.00,
                        'descontos': 500.00,
                        # ... outros campos
                    }
                })
        
        return jsonify({
            'success': True,
            'matricula': matricula,
            'periodo': f"{ano_inicial}-{ano_final}",
            'resultados': resultados
        })
    
    except Exception as e:
        logger.error(f"Erro ao buscar contracheques: {str(e)}")
        return jsonify({
            'error': "Erro ao processar sua solicitação",
            'login_url': f"{RH_BAHIA_BASE_URL}/login"
        }), 500

@app.route('/resultados')
def mostrar_resultados():
    if 'resultados' not in session:
        flash('Nenhum resultado encontrado. Por favor, faça uma nova busca.', 'warning')
        return redirect(url_for('index'))
    
    return render_template('resultado.html',
                         resultados=session['resultados'],
                         now=datetime.now())

@app.route('/detalhes/<mes_ano>')
def detalhes_mensais(mes_ano):
    if 'resultados' not in session:
        return redirect(url_for('index'))
    
    resultado = next((r for r in session['resultados'] if r['mes'] == mes_ano), None)
    
    if not resultado:
        flash('Contracheque não encontrado', 'error')
        return redirect(url_for('mostrar_resultados'))
    
    return render_template('detalhes_mes.html',
                         contracheque=resultado,
                         now=datetime.now())

if __name__ == '__main__':
    app.run(debug=True)
