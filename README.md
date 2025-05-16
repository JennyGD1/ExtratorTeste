# Extrator de Contracheques

Aplicação web para extrair automaticamente valores de contracheques em PDF baseado em códigos específicos.

## Funcionalidades

- Upload de múltiplos arquivos PDF de contracheques
- Extração automática de valores baseada em códigos identificadores
- Exibição de resultados consolidados
- Interface web simples e intuitiva

## Códigos Reconhecidos

| Código | Descrição               | Chave no Sistema       |
|--------|-------------------------|------------------------|
| 7033   | Titular                 | `titular`              |
| 7035   | Cônjuge                 | `conjuge`              |
| 7034   | Dependente              | `dependente`           |
| 7037   | Plano Especial          | `plano_especial`       |
| 7038   | Agregado Jovem          | `agregado_jovem`       |
| 7039   | Agregado Maior          | `agregado_maior`       |
| 7040   | Co-participação         | `coparticipacao`       |
| 7088-91| Parcela de Risco        | `parcela_risco`        |

## Como Usar

1. Acesse a aplicação web
2. Clique em "Selecionar arquivos" e escolha os PDFs dos contracheques
3. Clique em "Processar"
4. Visualize os resultados organizados por beneficiário e totais gerais

## Requisitos Técnicos

- Python 3.9+
- Dependências:
  - Flask 2.3.2
  - PyPDF2 3.0.1
  - Gunicorn 20.1.0

## Instalação para Desenvolvimento

1. Clone o repositório:
   ```bash
   git clone https://github.com/JennyGD1/Extrator-Contracheques.git
   cd Extrator-Contracheques

   ## Saída Gerada

A aplicação mostrará:
- Valores individuais por código
- Total por categoria (beneficiários, planos, taxas)
- **TOTAL GERAL** (soma de todos os valores)
## Personalização da Interface

Para modificar o estilo do **Total Geral**, edite o CSS em `templates/resultado.html`:

```html
<style>
    .total-geral {
        font-size: 1.2em;
        color: #006600;  /* Cor verde escuro */
        font-weight: bold;
    }
</style>
```
