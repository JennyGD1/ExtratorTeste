import fitz  # PyMuPDF
import re
import os
import urllib3
from urllib3.exceptions import MaxRetryError, TimeoutError
from flask import Flask, render_template, request, jsonify, session, redirect, flash, url_for
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.secret_key = 'sua-chave-secreta-aqui'



# Configuração de logging
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('logs/app.log', maxBytes=1000000, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configurações
RH_BAHIA_BASE_URL = "https://rhbahia.ba.gov.br"
CONTRACHEQUE_URL_TEMPLATE = RH_BAHIA_BASE_URL + "/auditor/contracheque/file/pdf/{ano}/{mes:02d}/1/{matricula}"

# Configuração do urllib3 com timeout aumentado
http = urllib3.PoolManager(
    timeout=urllib3.Timeout(connect=30.0, read=60.0),
    retries=urllib3.Retry(2)
)
# Dicionário de códigos de cobrança
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

def validar_pdf(content):
    """Verifica se o conteúdo parece ser um PDF válido"""
    return content and len(content) > 100 and content.startswith(b'%PDF')

def processar_contracheque_pdf(pdf_content):
    """Processa o conteúdo PDF do contracheque e extrai os valores"""
    try:
        if not validar_pdf(pdf_content):
            raise ValueError("Arquivo PDF inválido ou vazio")
            
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        texto = ""
        for page in doc:
            texto += page.get_text()
        
        valores = {}
        for codigo, descricao in CODIGOS_COBRANCA.items():
            padrao = rf"{codigo}.*?(\d+,\d{{2}})"
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
        if not data or 'matricula' not in data:
            return jsonify({"error": "Dados inválidos"}), 400
            
        matricula = data['matricula']
        ano_inicial = int(data.get('ano_inicial', 0))
        ano_final = int(data.get('ano_final', 0))
        
        if ano_final < ano_inicial:
            return jsonify({
                "error": "O ano final não pode ser menor que o inicial",
                "login_url": f"{RH_BAHIA_BASE_URL}/login"
            }), 400

        resultados = []
        
        # Headers definidos aqui dentro da função
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': RH_BAHIA_BASE_URL,
            'Accept': 'application/pdf',
            'X-Requested-With': 'XMLHttpRequest',
            'Cookie': '; '.join([f'{k}={v}' for k, v in request.cookies.items()]) if request.cookies else ''
        }
        
        for ano in range(ano_inicial, ano_final + 1):
            for mes in range(1, 13):
                url = CONTRACHEQUE_URL_TEMPLATE.format(
                    ano=ano,
                    mes=mes,
                    matricula=matricula
                )
                
                try:
                    response = http.request('GET', url, headers=headers)
                    
                    if response.status == 401:
                        return jsonify({
                            "error": "Faça login no RH BAHIA primeiro",
                            "login_url": f"{RH_BAHIA_BASE_URL}/login"
                        }), 401
                    
                    if response.status != 200:
                        logger.warning(f"Erro ao acessar {url} - Status: {response.status}")
                        continue
                    
                    if validar_pdf(response.data):
                        valores = processar_contracheque_pdf(response.data)
                        if valores:
                            resultados.append({
                                'mes': f"{mes:02d}/{ano}",
                                'url': url,
                                'valores': valores
                            })
                    
                except (MaxRetryError, TimeoutError) as e:
                    logger.error(f"Timeout ao acessar RH Bahia: {str(e)}")
                    continue

        # Verificação de resultados deve estar AQUI, dentro da função
        if not resultados:
            return jsonify({
                "error": "Nenhum contracheque encontrado. Servidor pode estar indisponível.",
                "status": 503
            }), 503
        
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
        logger.error(f"Erro geral na busca: {str(e)}", exc_info=True)
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
