import fitz  # PyMuPDF
import re
import os
import urllib3
from urllib3.exceptions import MaxRetryError, TimeoutError, NewConnectionError, ConnectTimeoutError as Urllib3ConnectTimeoutError
from flask import Flask, render_template, request, jsonify, session, redirect, flash, url_for
from datetime import datetime
import logging
import time
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
    timeout=urllib3.Timeout(connect=30.0, read=30.0),  # Reduzir para 30 segundos
    retries=urllib3.Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
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

def processar_contracheque_pdf(pdf_content, mes_ano_ref):
    try:
        if not validar_pdf(pdf_content):
            logger.warning(f"Conteúdo PDF inválido ou vazio para {mes_ano_ref}")
            return None
            
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        texto = ""
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            texto += page.get_text()
        
        doc.close() # Importante fechar o documento
            
        valores = {}
        found_any = False
        for codigo, descricao in CODIGOS_COBRANCA.items():
            # Regex mais robusto: procura o código, depois qualquer coisa (não guloso)
            # até um valor numérico com vírgula e duas casas decimais.
            # Considera espaços antes/depois do valor.
            padrao = rf"{codigo}\s*.*?[\s\S]*?(\d+\s*,\s*\d{{2}})"
            match = re.search(padrao, texto, re.IGNORECASE) # re.IGNORECASE pode ajudar
            if match:
                valor_str = match.group(1).replace(' ', '').replace(',', '.')
                try:
                    valor = float(valor_str)
                    # Se a descrição já existe e é "Parcela de Risco", some os valores
                    if descricao == 'Parcela de Risco' and descricao in valores:
                        valores[descricao] += valor
                    else:
                        valores[descricao] = valor
                    found_any = True
                except ValueError:
                    logger.error(f"Erro ao converter valor '{match.group(1)}' para float no PDF {mes_ano_ref} para código {codigo}")
            
        return valores if found_any else None # Retorna None se nenhum código foi encontrado
    
    except Exception as e:
        logger.error(f"Erro ao processar PDF {mes_ano_ref}: {str(e)}", exc_info=True)
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
        try:
            ano_inicial = int(data.get('ano_inicial', 0))
            ano_final = int(data.get('ano_final', 0))
        except ValueError:
            return jsonify({"error": "Anos devem ser números inteiros"}), 400
            
        if ano_final < ano_inicial:
            return jsonify({
                "error": "O ano final não pode ser menor que o inicial",
                "login_url": f"{RH_BAHIA_BASE_URL}/login"
            }), 400

        resultados = []
        erros_mes = []
        
        # Configuração otimizada de headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': RH_BAHIA_BASE_URL,
            'Accept': 'application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        # Verifica se há cookie de sessão específico nos dados da requisição
        if 'rh_bahia_session_cookie' in data:
            headers['Cookie'] = data['rh_bahia_session_cookie']
            logger.info("Cookie de sessão do RH Bahia detectado nos dados da requisição")

        logger.info(f"Iniciando busca para matrícula {matricula}, período {ano_inicial}-{ano_final}")
        
        num_total_meses = (ano_final - ano_inicial + 1) * 12
        mes_processado_idx = 0

        for ano in range(ano_inicial, ano_final + 1):
            for mes in range(1, 13):
                mes_processado_idx += 1
                mes_ano_str = f"{mes:02d}/{ano}"
                url = CONTRACHEQUE_URL_TEMPLATE.format(ano=ano, mes=mes, matricula=matricula)
                
                logger.info(f"Tentando {mes_ano_str} ({mes_processado_idx}/{num_total_meses}): {url}")
                
                try:
                    # Timeout reduzido para 30 segundos (conexão) e 30 segundos (leitura)
                    response = http.request('GET', url, headers=headers, timeout=30.0, preload_content=False)

                    if response.status == 401:
                        error_msg = f"Falha de autenticação (401) para {url}. Verifique se está logado no portal RH Bahia."
                        logger.warning(error_msg)
                        if not resultados:
                            return jsonify({
                                "error": error_msg,
                                "login_url": f"{RH_BAHIA_BASE_URL}/login",
                                "requires_auth": True
                            }), 401
                        erros_mes.append(f"{mes_ano_str}: Falha de autenticação")
                        continue

                    if response.status != 200:
                        logger.warning(f"Erro HTTP {response.status} ao acessar {url}")
                        erros_mes.append(f"{mes_ano_str}: Erro HTTP {response.status}")
                        response.release_conn()
                        continue
                    
                    pdf_data = response.data
                    response.release_conn()

                    if not validar_pdf(pdf_data):
                        logger.warning(f"Conteúdo de {url} não é um PDF válido")
                        erros_mes.append(f"{mes_ano_str}: Arquivo inválido")
                        continue

                    valores = processar_contracheque_pdf(pdf_data, mes_ano_str)
                    if valores:
                        resultados.append({
                            'mes': mes_ano_str,
                            'url': url,
                            'valores': valores
                        })
                        logger.info(f"Sucesso ao processar {mes_ano_str}")
                    else:
                        logger.info(f"Nenhum código encontrado em {mes_ano_str}")
                        erros_mes.append(f"{mes_ano_str}: Sem dados de cobrança")
                
                except (MaxRetryError, Urllib3ConnectTimeoutError, TimeoutError, NewConnectionError) as e:
                    logger.error(f"Erro de conexão para {url}: {str(e)}")
                    erros_mes.append(f"{mes_ano_str}: Erro de conexão")
                    continue
                except Exception as e_inner:
                    logger.error(f"Erro inesperado ao processar {url}: {str(e_inner)}", exc_info=True)
                    erros_mes.append(f"{mes_ano_str}: Erro inesperado")
                    continue

                # Delay entre requisições para evitar sobrecarga
                time.sleep(0.5)

        # Tratamento dos resultados finais
        if not resultados:
            if erros_mes:
                logger.info(f"Busca concluída sem sucesso. Erros: {erros_mes}")
                return jsonify({
                    "error": "Não foi possível obter contracheques",
                    "details": erros_mes,
                    "login_url": f"{RH_BAHIA_BASE_URL}/login",
                    "status_code": 502
                }), 502
            else:
                logger.warning("Nenhum resultado obtido sem erros registrados")
                return jsonify({
                    "error": "Servidor RH Bahia não respondeu",
                    "status_code": 503
                }), 503

        # Armazenamento na sessão
        session['resultados'] = resultados
        session['matricula'] = matricula
        session['periodo'] = f"{ano_inicial}-{ano_final}"
        session['erros_mes'] = erros_mes
        
        logger.info(f"Busca finalizada: {len(resultados)} sucessos, {len(erros_mes)} erros")
        
        return jsonify({
            'success': True,
            'matricula': matricula,
            'periodo': f"{ano_inicial}-{ano_final}",
            'quantidade_sucesso': len(resultados),
            'quantidade_erros': len(erros_mes),
            'message': f"{len(resultados)} contracheques processados. {len(erros_mes)} meses com problemas." if erros_mes else "Todos os contracheques processados com sucesso."
        })
    
    except Exception as e_outer:
        logger.error(f"Erro geral: {str(e_outer)}", exc_info=True)
        return jsonify({
            'error': "Erro interno ao processar solicitação",
            'details': str(e_outer),
            'status_code': 500
        }), 500
@app.route('/resultados')
def mostrar_resultados():
    if 'resultados' not in session and 'erros_mes' not in session: # Se não há nem resultados nem erros
        flash('Nenhum dado encontrado da busca anterior. Por favor, faça uma nova busca.', 'warning')
        return redirect(url_for('index'))
    
    return render_template('resultado.html',
                           resultados=session.get('resultados', []),
                           matricula=session.get('matricula', 'N/A'),
                           periodo=session.get('periodo', 'N/A'),
                           erros_mes=session.get('erros_mes', []),
                           now=datetime.now())

@app.route('/detalhes/<path:mes_ano>') # path: permite '/' no parâmetro
def detalhes_mensais(mes_ano):
    if 'resultados' not in session:
        flash('Sessão expirada ou busca não realizada.', 'warning')
        return redirect(url_for('index'))
    
    resultados_sessao = session.get('resultados', [])
    resultado = next((r for r in resultados_sessao if r['mes'] == mes_ano), None)
    
    if not resultado:
        flash(f'Contracheque para {mes_ano} não encontrado nos resultados processados.', 'error')
        return redirect(url_for('mostrar_resultados'))
    
    # Se 'valores' pode ser None ou não existir:
    if not resultado.get('valores'):
        flash(f'Não foram encontrados dados de cobrança para o contracheque de {mes_ano}.', 'info')
        # Você pode querer mostrar a página de detalhes mesmo assim, mas indicando a ausência de valores
        # ou redirecionar. Por ora, vamos permitir a visualização.

    return render_template('detalhes_mes.html',
                           contracheque=resultado, # 'valores' pode ser None ou um dict vazio
                           now=datetime.now())


if __name__ == '__main__':
    # app.run(debug=True) # debug=True não é recomendado para produção via Gunicorn
    # Gunicorn vai gerenciar a execução. Esta seção é mais para desenvolvimento local.
    # Para desenvolvimento local:
    # Se não estiver usando Gunicorn localmente, pode usar:
    app.run(host='0.0.0.0', port=8080, debug=True)
