# processador_contracheque.py
import json
import re
import logging

logger = logging.getLogger(__name__)

class ProcessadorContracheque:

    def __init__(self, config_path='config.json'):
        try:
            with open(config_path) as f:
                self.config = json.load(f)

        except FileNotFoundError:
            logger.error(f"Arquivo de configuração {config_path} não encontrado")
            self.config = {"padroes_contracheque": {}}

        except json.JSONDecodeError:
            logger.error(f"Erro ao decodificar o arquivo de configuração {config_path}")
            self.config = {"padroes_contracheque": {}}
    
    def identificar_tipo(self, texto):
        texto = texto.upper()
        for tipo, config in self.config['padroes_contracheque'].items():
            for identificador in config['identificadores']:
                if identificador.upper() in texto:
                    return tipo
        return "padrao"
    
    def extrair_dados(self, texto, tipo=None):
        if not tipo:
            tipo = self.identificar_tipo(texto)
        
        campos_config = self._get_campos_config(tipo)
        dados = {}
        
        for campo_interno, padrao in campos_config.items():
            match = re.search(rf"{re.escape(padrao)}\s*.*?([\d.,]+)", texto, re.IGNORECASE | re.DOTALL)
 
            if match:    
                try:          
                   valor_str = match.group(1)
                   valor_str = valor_str.replace('.', '').replace(',', '.')
                   valor = float(valor_str)
                   dados[campo_interno] = valor
                   logger.debug(f"Campo '{campo_interno}' encontrado com valor: {valor}") # Log de sucesso
                except ValueError:
                   logger.warning(f"Valor inválido encontrado após '{padrao}': {match.group(1)}")
                   continue

                except IndexError:
                   logger.warning(f"Regex encontrou padrão '{padrao}' mas não capturou grupo de valor.")
                   continue
        else:
         logger.debug(f"Padrão '{padrao}' para o campo '{campo_interno}' não encontrado no texto.") # Log de falha
        
        return dados
    
    def _get_campos_config(self, tipo):
        config = self.config['padroes_contracheque'].get(tipo, {})

        if 'herda' in config:
            base_config = self._get_campos_config(config['herda'])
            base_config.update(config.get('campos', {}))
            return base_config

        return config.get('campos', {})
