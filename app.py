import fitz  # PyMuPDF
import re
import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.secret_key = 'sua-chave-secreta-aqui'

# Configuração do logger (igual ao anterior)
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

# Configurações (igual ao anterior)
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
    # Função extrair_valor_linha (igual à anterior)
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
    """
    Extrai o primeiro Mês/Ano encontrado no texto da página.
    Retorna uma tupla com (string_formatada, ano) ou ("Período não identificado", None)
    """
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
                return f"{mes_padrao} {ano}", ano  # Agora retorna uma tupla

    logger.warning("Mês/Ano não encontrado no texto da página.")
    return "Período não identificado", None

def processar_pdf(caminho_pdf):
    """
    Processa o PDF para extrair valores e o Mês/Ano do conteúdo.
    Retorna uma lista de tuplas: [(mes_ano, dicionario_valores), ...] ou [] em caso de erro.
    """
    try:
        doc = fitz.open(caminho_pdf)
        resultados_por_pagina = []  # Lista para armazenar resultados de cada página

        CODIGOS = {
            '7033': 'titular',
            '7035': 'conjuge',
            '7034': 'dependente',
            '7038': 'agregado_jovem',
            '7039': 'agregado_maior',
            '7037': 'plano_especial',
            '7040': 'coparticipacao',
            '7049': 'retroativo',
            '7088': 'parcela_risco',
            '7089': 'parcela_risco',
            '7090': 'parcela_risco',
            '7091': 'parcela_risco'
        }
        campos_obrigatorios = [
            'titular', 'conjuge', 'dependente', 'agregado_jovem',
            'agregado_maior', 'plano_especial', 'coparticipacao',
            'retroativo', 'parcela_risco'
        ]

        for page_num, page in enumerate(doc):
            texto_pagina = page.get_text("text")
            linhas = texto_pagina.split('\n')
            logger.debug(f"Processando Página {page_num + 1} do arquivo {os.path.basename(caminho_pdf)}")

            mes_ano_encontrado, ano_encontrado = extrair_mes_ano_do_texto(texto_pagina)
            logger.info(f"Mês/Ano encontrado para {os.path.basename(caminho_pdf)} (Página {page_num + 1}): {mes_ano_encontrado}")

            valores = {campo: 0.0 for campo in campos_obrigatorios}  # Reinicia valores para cada página

            for i, linha in enumerate(linhas):
                linha_strip = linha.strip()

                codigo_match = re.match(r'^(\d{4})\b', linha_strip)
                codigo_encontrado = None
                campo_alvo = None

                if codigo_match:
                    codigo_encontrado = codigo_match.group(1)
                    if codigo_encontrado in CODIGOS:
                        campo_alvo = CODIGOS[codigo_encontrado]

                if not campo_alvo:
                    if re.search(r'Assistência a Saúde|PLANO DE SAUDE DOS SERV', linha, re.IGNORECASE):
                        campo_alvo = 'titular'
                    elif re.search(r'Planserv Especial|PLANSERV ESPECIAL', linha, re.IGNORECASE):
                        campo_alvo = 'plano_especial'
                    elif re.search(r'Planserv Agregado Jovem', linha, re.IGNORECASE):
                        campo_alvo = 'agregado_jovem'
                    elif re.search(r'CO-PARTICIPAÇÃO PLANSERV|coparticipacao', linha, re.IGNORECASE):
                        campo_alvo = 'coparticipacao'

                if campo_alvo:
                    valor_linha = extrair_valor_linha(linha)
                    if valor_linha > 0:
                        valores[campo_alvo] += valor_linha
                        logger.debug(f"'{campo_alvo}' (Cod: {codigo_encontrado if codigo_encontrado else 'Texto'}) - Valor {valor_linha} encontrado na mesma linha.")
                    else:
                        for offset in range(1, 4):
                            if i + offset < len(linhas):
                                valor_prox = extrair_valor_linha(linhas[i + offset])
                                if valor_prox > 0:
                                    valores[campo_alvo] += valor_prox
                                    logger.debug(f"'{campo_alvo}' (Cod: {codigo_encontrado if codigo_encontrado else 'Texto'}) - Valor {valor_prox} encontrado na linha +{offset}.")
                                    break

            resultados_por_pagina.append((mes_ano_encontrado, valores))  # Adiciona resultado da página à lista

        return resultados_por_pagina

    except Exception as e:
        logger.error(f"Erro ao processar PDF {caminho_pdf}: {str(e)}", exc_info=True)
        return []  # Retorna uma lista vazia em caso de erro

# Rota Index (igual)
@app.route('/')
def index():
    session.clear()
    return render_template('index.html')

# Rota Upload MODIFICADA para agrupar por ano
@app.route('/upload', methods=['POST'])
def upload():
    if 'files' not in request.files:
        flash('Nenhum arquivo selecionado')
        return redirect(url_for('index'))

    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        flash('Nenhum arquivo selecionado')
        return redirect(url_for('index'))

    # Estrutura para agrupar por ano
    resultados_por_ano = {}
    erros = []
    arquivos_processados_count = 0 # Contador de arquivos (não páginas)

    campos_base = [ # Define os campos esperados na estrutura 'geral'
            'titular', 'conjuge', 'dependente',
            'agregado_jovem', 'agregado_maior',
            'plano_especial', 'coparticipacao',
            'retroativo', 'parcela_risco'
        ]

    for file in files:
        if file.filename == '' or not allowed_file(file.filename):
            continue

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        arquivo_teve_erro = False # Flag para este arquivo específico

        try:
            file.save(filepath)
            logger.info(f"Arquivo salvo: {filepath}")

            resultados_pagina = processar_pdf(filepath) # Retorna lista de (mes_ano, valores_pagina)

            if resultados_pagina:
                arquivos_processados_count += 1 # Conta o arquivo como processado se a função retornou algo
                for mes_ano_str, valores_pagina in resultados_pagina:
                    if mes_ano_str != "Período não identificado":
                        try:
                            # Extrai o ano da string "Mês Ano"
                            ano = mes_ano_str.split()[-1]
                            if not ano.isdigit() or len(ano) != 4:
                                raise ValueError("Ano inválido extraído")

                            # Cria a entrada do ano se não existir
                            if ano not in resultados_por_ano:
                                resultados_por_ano[ano] = {
                                    'geral': {campo: 0.0 for campo in campos_base},
                                    'total_ano': 0.0, # <-- Inicializa total_ano
                                    'detalhes_mensais': [] # Mantém detalhes mensais aqui
                                }

                            # Soma nos resultados gerais do ano
                            total_pagina = 0.0
                            for campo, valor in valores_pagina.items():
                                if campo in resultados_por_ano[ano]['geral']:
                                    resultados_por_ano[ano]['geral'][campo] += valor
                                    total_pagina += valor # Soma para o total da página/mês
                                else:
                                    logger.warning(f"Campo '{campo}' da pág/mês {mes_ano_str} (arq: {filename}) não encontrado na estrutura do ano {ano}.")

                            # Acumula o total da página/mês no total_ano
                            resultados_por_ano[ano]['total_ano'] += total_pagina # <-- Acumula o total do ano

                            # Adiciona aos detalhes mensais (como estava)
                            resultados_por_ano[ano]['detalhes_mensais'].append({
                                'mes': mes_ano_str,
                                'arquivo': filename, # Pode ser útil saber qual arquivo gerou qual mês
                                'valores': valores_pagina
                            })

                        except (IndexError, ValueError) as e:
                            logger.error(f"Não foi possível extrair/validar o ano de '{mes_ano_str}' (arq: '{filename}'). Erro: {e}")
                            if not arquivo_teve_erro: # Adiciona erro apenas uma vez por arquivo
                                erros.append(f"{filename} (dados inválidos: {mes_ano_str})")
                                arquivo_teve_erro = True
                    else:
                        logger.warning(f"Mês/Ano não identificado em uma página do arquivo: {filename}")
                        if not arquivo_teve_erro: # Adiciona erro apenas uma vez por arquivo
                             erros.append(f"{filename} (período não identificado)")
                             arquivo_teve_erro = True
            else:
                 # Se processar_pdf retornou vazio, mas não lançou exceção, consideramos erro de processamento
                 logger.error(f"Falha ao processar PDF (retorno vazio): {filename}")
                 if not arquivo_teve_erro:
                     erros.append(f"{filename} (falha no processamento)")
                     arquivo_teve_erro = True

            # Opcional: Remover o arquivo após processamento
            # try:
            #     os.remove(filepath)
            #     logger.info(f"Arquivo removido: {filepath}")
            # except OSError as e:
            #     logger.error(f"Erro ao remover arquivo {filepath}: {e}")

        except Exception as e:
            logger.error(f"Erro GERAL no loop de upload para o arquivo {filename}: {str(e)}", exc_info=True)
            if not arquivo_teve_erro: # Adiciona erro apenas uma vez por arquivo
                 erros.append(f"{filename} (erro inesperado)")
            # Tenta remover arquivo mesmo com erro
            if os.path.exists(filepath):
                try: os.remove(filepath)
                except OSError as re: logger.error(f"Erro ao remover {filepath} após erro: {re}")

    # Verifica se algum arquivo foi processado com sucesso
    if not resultados_por_ano and arquivos_processados_count == 0: # Nenhum dado válido extraído
        if erros:
            flash(f'Falha ao processar todos os arquivos enviados. Erros: {"; ".join(erros)}', 'error')
        else:
            flash('Nenhum arquivo PDF válido encontrado ou processado.', 'warning')
        return redirect(url_for('index'))

    # Salva na sessão
    session['resultados_por_ano'] = resultados_por_ano
    session['erros'] = list(set(erros)) # Remove duplicatas da lista de erros

    # Mensagem de aviso se houve erros parciais
    if session['erros']:
        flash(f'Processamento concluído com {len(session["erros"])} erro(s). Verifique os detalhes. Arquivos com erro: {", ".join(session["erros"])}', 'warning')

    return redirect(url_for('mostrar_resultados'))

# Rota mostrar_resultados MODIFICADA para exibir por ano
@app.route('/resultados')
def mostrar_resultados():
    if 'resultados_por_ano' not in session:
        flash('Nenhum resultado encontrado. Por favor, faça o upload dos arquivos primeiro.', 'warning')
        return redirect(url_for('index'))

    resultados_por_ano = session.get('resultados_por_ano', {})
    erros_proc = session.get('erros', []) # Pega a lista de erros da sessão

    # Calcula o total geral somando os totais de cada ano válido
    total_geral_calculado = 0.0
    for ano, dados_ano in resultados_por_ano.items():
        # Considera apenas anos válidos (evita somar "Desconhecido", etc., se houver)
        if ano.isdigit() and len(ano) == 4:
             total_geral_calculado += dados_ano.get('total_ano', 0.0) # Usa .get para segurança

    # Ordena os anos para exibição (opcional, mas recomendado)
    anos_ordenados = sorted([a for a in resultados_por_ano.keys() if a.isdigit()], key=int, reverse=True)
    outros_anos = sorted([a for a in resultados_por_ano.keys() if not a.isdigit()])
    chaves_ordenadas = anos_ordenados + outros_anos
    resultados_por_ano_ordenado = {chave: resultados_por_ano[chave] for chave in chaves_ordenadas}


    return render_template('resultado.html',
                           resultados_por_ano=resultados_por_ano_ordenado, # Passa a estrutura por ano ordenada
                           total_geral=total_geral_calculado,        # Passa o total geral calculado
                           erros_processamento=erros_proc,           # Passa a lista de erros
                           now=datetime.now())

# Rota detalhes_mensais MODIFICADA para buscar detalhes por ano
@app.route('/detalhes')
def detalhes_mensais():
    if 'resultados_por_ano' not in session:
        return redirect(url_for('index'))

    resultados_por_ano = session['resultados_por_ano']
    detalhes = []
    anos_disponiveis = set()

    for ano, dados_ano in resultados_por_ano.items():
        anos_disponiveis.add(ano)
        # Acessa a chave correta 'detalhes_mensais'
        for detalhe_mensal in dados_ano.get('detalhes_mensais', []): # Usa .get para segurança
            detalhe_mensal['ano'] = ano # Adiciona o ano para possível uso futuro
            detalhes.append(detalhe_mensal)

    erros_proc = session.get('erros', [])
    resultados_validos = []
    resultados_invalidos = []

    for r in detalhes:
        mes_str = r.get('mes', 'Período não identificado')
        if mes_str == 'Período não identificado':
            resultados_invalidos.append(r)
            continue

        try:
            partes = mes_str.split()
            mes_nome = partes[0]
            ano = int(partes[1])
            mes_num = 13 # Default para inválido/desconhecido
            for nome_map, num_map in MESES_ORDEM.items():
                 if mes_nome.lower() == nome_map.lower():
                      mes_num = num_map
                      break
            if mes_num != 13:
                resultados_validos.append((ano, mes_num, r))
            else:
                 logger.warning(f"Não foi possível mapear o mês '{mes_nome}' para um número.")
                 resultados_invalidos.append(r)

        except (ValueError, IndexError, TypeError) as e: # Adiciona TypeError para segurança
            logger.error(f"Erro ao parsear/ordenar mês '{mes_str}' do arquivo {r.get('arquivo')}: {e}")
            resultados_invalidos.append(r)

    # Ordena primeiro por ano, depois por mês
    resultados_ordenados = [r for _, _, r in sorted(resultados_validos, key=lambda x: (x[0], x[1]))]
    # Adiciona os inválidos no final
    resultados_ordenados += resultados_invalidos

    return render_template('detalhes_mes.html',
                           resultados=resultados_ordenados,
                           # Ordena os anos disponíveis para o seletor (se usar um)
                           anos_disponiveis=sorted(list(anos_disponiveis), reverse=True),
                           erros_processamento=erros_proc,
                           now=datetime.now())


if __name__ == '__main__':
    app.run(debug=True) # Mantenha debug=True para desenvolvimento local
