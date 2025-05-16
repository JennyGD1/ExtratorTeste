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
    timeout=urllib3.Timeout(connect=60.0, read=60.0), # Aumentando o connect timeout para 60 segundos
    retries=urllib3.Retry(
        total=2, # Total de 2 retentativas (3 tentativas no total)
        backoff_factor=1, # Adiciona delay (ex: 0s, 2s, 4s) entre tentativas
        status_forcelist=[429, 500, 502, 503, 504], # Tentar novamente para estes erros HTTP
        allowed_methods=["GET"] # ou methods=["GET"] dependendo da versão
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
                "login_url": f"{RH_BAHIA_BASE_URL}/login" # Manter URL de login para referência
            }), 400

        resultados = []
        erros_mes = []
        
        # Headers (Atenção à questão dos cookies explicada anteriormente)
        # Idealmente, o cookie de sessão do RH Bahia deveria ser injetado aqui.
        # Por agora, vamos manter como estava, mas ciente da limitação.
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': RH_BAHIA_BASE_URL,
            'Accept': 'application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', # Aceitar mais tipos pode ajudar
            'X-Requested-With': 'XMLHttpRequest',
            # A linha abaixo pega os cookies enviados PELO NAVEGADOR DO USUÁRIO PARA O SEU APP FLASK.
            # Estes NÃO SÃO os cookies da sessão do usuário no site rhbahia.ba.gov.br
            # a menos que haja uma configuração de proxy muito específica.
            # 'Cookie': '; '.join([f'{k}={v}' for k, v in request.cookies.items()]) if request.cookies else ''
            # Para testes, você poderia hardcodar um cookie válido aqui se obtiver um:
            # 'Cookie': 'JSESSIONID=SEU_COOKIE_AQUI_DO_RHBAHIA' # Exemplo
        }
        
        # Adicionar um cookie de sessão específico, se você conseguir capturá-lo após o login no RH Bahia
        # Este é um ponto CRUCIAL para acesso a dados protegidos.
        # Se o RH Bahia usa um cookie chamado, por exemplo, 'portal_session_id', você precisaria dele.
        # Exemplo: headers['Cookie'] = 'portal_session_id=valor_do_cookie_capturado'

        # Tentar obter o cookie de sessão do RH Bahia do cliente, se ele for enviado (improvável entre domínios)
        # Ou, se você tem uma forma de o usuário fornecer o cookie:
        rh_bahia_cookie = data.get('rh_bahia_session_cookie') # Supondo que o frontend possa enviar
        if rh_bahia_cookie:
             headers['Cookie'] = rh_bahia_cookie
        elif request.cookies: # Fallback para o que você tinha, mas com ressalvas
             # logger.warning("Usando cookies da requisição do cliente para o servidor Flask. Estes podem não ser os cookies de sessão do RH Bahia.")
             # headers['Cookie'] = '; '.join([f'{k}={v}' for k, v in request.cookies.items()])
             pass # Melhor não enviar cookies incorretos. A autenticação precisa ser tratada de forma mais robusta.


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
                    response = http.request('GET', url, headers=headers, preload_content=False) # preload_content=False para liberar conexão mais rápido
                    # response.read() será chamado depois, ou response.data usado

                    if response.status == 401:
                        logger.warning(f"Falha de autenticação (401) para {url}. O usuário precisa estar logado no RH Bahia e a sessão ativa/correta.")
                        # Não retorna imediatamente, tenta outros meses, mas avisa sobre o problema de login
                        # Se isso acontecer consistentemente, toda a busca falhará.
                        # Considerar retornar um erro aqui se for o primeiro mês e der 401.
                        if not resultados: # Se for o primeiro e já deu 401
                             return jsonify({
                                "error": f"Falha de autenticação (401) ao acessar {RH_BAHIA_BASE_URL}. Verifique se está logado no portal RH Bahia e tente novamente. Se o problema persistir, o método de autenticação pode precisar ser revisto.",
                                "login_url": f"{RH_BAHIA_BASE_URL}/login"
                            }), 401
                        erros_mes.append(f"{mes_ano_str}: Falha de autenticação (401)")
                        continue # Pula para o próximo mês

                    if response.status != 200:
                        logger.warning(f"Erro HTTP {response.status} ao acessar {url}")
                        erros_mes.append(f"{mes_ano_str}: Erro HTTP {response.status}")
                        response.release_conn() # Garante que a conexão é liberada
                        continue
                    
                    pdf_data = response.data # Lê o conteúdo aqui
                    response.release_conn() # Libera a conexão de volta ao pool

                    if validar_pdf(pdf_data):
                        valores = processar_contracheque_pdf(pdf_data, mes_ano_str)
                        if valores:
                            resultados.append({
                                'mes': mes_ano_str,
                                'url': url, # Pode ser útil para depuração ou download manual pelo usuário
                                'valores': valores
                            })
                            logger.info(f"Sucesso ao processar {mes_ano_str}. Valores: {valores}")
                        else:
                            logger.info(f"Nenhum código de cobrança encontrado em {mes_ano_str} (PDF válido, mas sem dados de interesse).")
                            # Você pode optar por adicionar uma entrada vazia ou uma com erro específico
                            erros_mes.append(f"{mes_ano_str}: PDF válido, mas nenhum código encontrado.")
                    else:
                        logger.warning(f"Conteúdo de {url} não é um PDF válido ou está vazio. Status: {response.status}")
                        erros_mes.append(f"{mes_ano_str}: Arquivo não é PDF ou está corrompido.")
                
                except (MaxRetryError, Urllib3ConnectTimeoutError, TimeoutError, NewConnectionError) as e:
                    logger.error(f"Timeout/Erro de Conexão para {url}: {str(e)}")
                    erros_mes.append(f"{mes_ano_str}: Timeout ou erro de conexão com o servidor RH Bahia.")
                    # response.release_conn() # Se o response existir e a conexão não foi liberada
                    continue # Pula para o próximo mês
                except Exception as e_inner:
                    logger.error(f"Erro inesperado ao processar {url}: {str(e_inner)}", exc_info=True)
                    erros_mes.append(f"{mes_ano_str}: Erro inesperado durante processamento.")
                    continue

                # Adiciona um pequeno delay para não sobrecarregar o servidor do RH Bahia
                time.sleep(0.5) # 0.5 segundos de delay entre requisições

        if not resultados and not erros_mes: # Nenhuma tentativa foi bem sucedida ou falhou, estranho
             logger.warning("Nenhum resultado e nenhum erro registrado. Verificar lógica.")
             return jsonify({
                "error": "Nenhum contracheque encontrado ou processado. O servidor RH Bahia pode estar inacessível ou não há dados para o período.",
                "login_url": f"{RH_BAHIA_BASE_URL}/login",
                "status_code": 503 # Service Unavailable
             }), 503
        
        if not resultados and erros_mes: # Nenhum sucesso, mas houve erros
            logger.info(f"Nenhum contracheque encontrado com sucesso. Erros: {erros_mes}")
            return jsonify({
                "error": "Não foi possível buscar os contracheques. Verifique os detalhes abaixo.",
                "details": erros_mes,
                "login_url": f"{RH_BAHIA_BASE_URL}/login",
                "status_code": 502 # Bad Gateway (problema com o upstream)
            }), 502

        session['resultados'] = resultados
        session['matricula'] = matricula
        session['periodo'] = f"{ano_inicial}-{ano_final}"
        session['erros_mes'] = erros_mes # Armazena também os erros para exibir
        
        logger.info(f"Busca finalizada para {matricula}. {len(resultados)} contracheques encontrados. {len(erros_mes)} meses com erro.")
        
        return jsonify({
            'success': True,
            'matricula': matricula,
            'periodo': f"{ano_inicial}-{ano_final}",
            'quantidade_sucesso': len(resultados),
            'quantidade_erros': len(erros_mes),
            'message': f"{len(resultados)} contracheques processados com sucesso. {len(erros_mes)} meses apresentaram problemas." if erros_mes else f"{len(resultados)} contracheques processados com sucesso."
            # 'redirect_url': url_for('mostrar_resultados') # O frontend já faz o redirect
        })
    
    except Exception as e_outer:
        logger.error(f"Erro geral na função buscar_contracheques: {str(e_outer)}", exc_info=True)
        return jsonify({
            'error': "Ocorreu um erro inesperado ao processar sua solicitação.",
            'details': str(e_outer),
            'login_url': f"{RH_BAHIA_BASE_URL}/login"
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
