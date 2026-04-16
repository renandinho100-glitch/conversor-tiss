import xml.etree.ElementTree as ET
from collections import deque
from xml.dom import minidom
import re

def limpar_texto(texto):
    if not texto: return ""
    return re.sub(r'[^A-Z0-9]', '', texto.upper())

def processar_xmls(envio_file, retorno_file):
    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    
    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos: {e}"

    # Identifica se é Amazonia Saúde pelo Registro ANS
    registro_ans = root_ret.find('.//ans:registroANS', ns)
    is_amazonia = registro_ans is not None and registro_ans.text == '303976'

    mapa_retorno = {}
    mapa_cabecalho_guia = {} 
    
    # 1. MAPEAMENTO DO RETORNO
    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        n_guia = relacao.find('.//ans:numeroGuiaPrestador', ns).text.strip()
        
        meta = {}
        for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text.strip() if (elem is not None and elem.text) else ""
        mapa_cabecalho_guia[n_guia] = meta

        for item in relacao.findall('.//ans:detalhesGuia', ns):
            seq_ret = item.find('ans:sequencialItem', ns).text if item.find('ans:sequencialItem', ns) is not None else ""
            p_elem = item.find('.//ans:procedimento', ns)
            cod = p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else ""
            descr = p_elem.find('ans:descricaoProcedimento', ns).text if p_elem is not None else ""
            data = item.find('ans:dataRealizacao', ns).text if item.find('ans:dataRealizacao', ns) is not None else ""
            v_inf = f"{float(item.find('.//ans:valorInformado', ns).text):.2f}"
            
            # Coleta e SOMA de Glosas (Caso haja mais de uma para o mesmo item)
            v_lib = float(item.find('.//ans:valorLiberado', ns).text)
            glosas = item.findall('.//ans:relacaoGlosa', ns)
            v_total_glosa = sum(float(g.find('ans:valorGlosa', ns).text) for g in glosas if g.find('ans:valorGlosa', ns) is not None)
            cod_glosa = glosas[0].find('ans:tipoGlosa', ns).text if glosas else None

            conteudo = {
                'v_lib': v_lib, 
                'cod_glosa': cod_glosa, 
                'v_glo': v_total_glosa,
                'cod_ret': cod
            }
            
            # HIERARQUIA COM SEQUENCIAL PARA AMAZONIA SAUDE
            chaves = []
            if is_amazonia and seq_ret:
                chaves.append(f"{n_guia}_SEQ_{seq_ret}") # Prioridade máxima: Sequencial
            
            chaves.extend([
                f"{n_guia}_{cod}_{data}_{v_inf}",
                f"{n_guia}_{limpar_texto(descr)}_{v_inf}",
                f"{n_guia}_{v_inf}"
            ])
            
            for c in chaves:
                if c not in mapa_retorno: mapa_retorno[c] = deque()
                mapa_retorno[c].append(conteudo)

    # ... (Restante da lógica de montagem do XML seguindo a nova hierarquia)
    # Ao buscar no mapa_retorno, o script tentará primeiro a chave _SEQ_ se for Amazonia Saúde.
