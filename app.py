import fitz  # PyMuPDF
import re
import os
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, flash
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.secret_key = 'sua-chave-secreta-aqui'

# Configurações
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

# Dicionário de códigos de cobrança (atualize conforme necessário)
CODIGOS_COBRANCA = {
    '7033': 'Titular',
    '7035': 'Cônjuge',
    '7034': 'Dependente',
    '7038': 'Agregado Jovem',
    '7039': 'Agregado Maior',
    '7037': 'Plano Especial',
    '7040': 'Coparticipação',
    '7049': 'Retroativo',
    '7088': 'Parcela de Risco',
    '7089': 'Parcela de Risco',
    '7090': 'Parcela de Risco',
    '7091': 'Parcela de Risco'
}

def processar_contracheque_pdf(pdf_content):
    """Processa o conteúdo PDF do contracheque e extrai os valores"""
    try:
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        texto = ""
        for page in doc:
            texto += page.get_text()
        
        valores = {}
        # Procura por cada código de cobrança no texto
        for codigo, descricao in CODIGOS_COBRANCA.items():
            padrao = rf"{codigo}.*?(\d+,\d{2})"
            match = re.search(padrao, texto)
            if match:
                valor = float(match.group(1).replace(',', '.'))
                valores[descricao] = valor
        
        return valores
    
    except Exception as e:
        logger.error(f"Erro ao processar PDF: {str(e)}")
        return None

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
        
        for ano in range(ano_inicial, ano_final + 1):
            for mes in range(1, 13):
                url = CONTRACHEQUE_URL_TEMPLATE.format(
                    ano=ano,
                    mes=mes,
                    matricula=matricula
                )
                
                try:
                    # Faz a requisição REAL para o RH BAHIA
                    response = requests.get(
                        url,
                        cookies=request.cookies,  # Passa os cookies da sessão
                        headers={
                            'User-Agent': 'Mozilla/5.0',
                            'Referer': RH_BAHIA_BASE_URL
                        },
                        timeout=10
                    )
                    
                    if response.status_code == 401:
                        return jsonify({
                            "error": "Faça login no RH BAHIA primeiro",
                            "login_url": f"{RH_BAHIA_BASE_URL}/login"
                        }), 401
                    
                    if response.status_code != 200:
                        logger.warning(f"Erro ao acessar {url} - Status: {response.status_code}")
                        continue
                    
                    # Processa o PDF retornado
                    valores = processar_contracheque_pdf(response.content)
                    if valores:
                        resultados.append({
                            'mes': f"{mes:02d}/{ano}",
                            'url': url,
                            'valores': valores
                        })
                    
                except Exception as e:
                    logger.error(f"Erro ao processar {mes}/{ano}: {str(e)}")
                    continue
        
        if not resultados:
            return jsonify({
                "error": "Nenhum contracheque encontrado para o período",
                "login_url": f"{RH_BAHIA_BASE_URL}/login"
            }), 404
        
        # Armazena resultados na sessão
        session['resultados'] = resultados
        session['matricula'] = matricula
        session['periodo'] = f"{ano_inicial}-{ano_final}"
        
        return jsonify({
            'success': True,
            'matricula': matricula,
            'periodo': f"{ano_inicial}-{ano_final}",
            'quantidade': len(resultados)
        })
    
    except Exception as e:
        logger.error(f"Erro geral: {str(e)}")
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
                         matricula=session['matricula'],
                         periodo=session['periodo'],
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
